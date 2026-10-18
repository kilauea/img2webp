"""
Core conversion logic for img2webp.

This module is deliberately free of any CLI or GUI concerns so that every
front end (CLI, web, desktop) shares exactly the same conversion behaviour.

Key behaviours:
  * Accepts JPEG/PNG input, writes WebP output.
  * Lossless by default; optional lossy mode with a quality setting.
  * Optional max width/height constraints that *scale* (never crop) while
    preserving aspect ratio. When both are given, the image is scaled to fit
    inside the width x height box (the smaller scale factor wins). Images are
    never upscaled.
  * Pure functions suitable for running inside a ProcessPoolExecutor.

"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# Pillow >= 9.1 moved resampling filters under Image.Resampling; keep a single
# reference that works on both new and old Pillow without tripping linters.
try:  # pragma: no cover - trivial compatibility shim
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - old Pillow
    _LANCZOS = Image.LANCZOS  # pylint: disable=no-member

# Input extensions we accept (case-insensitive). Output is always ``.webp``.
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}

# Default WebP encoder effort (0=fast/larger, 6=best/smallest).
DEFAULT_METHOD = 6
# Default quality used in lossy mode.
DEFAULT_QUALITY = 90
# Default quality used for thumbnails (always lossy).
DEFAULT_THUMBNAIL_QUALITY = 80


@dataclass
class Job:
    """A single conversion unit: one source image to one destination path."""

    src: Path
    dst: Path


@dataclass
class Result:
    """The outcome of a single conversion."""

    src: Path
    dst: Path
    ok: bool
    message: str = ""


@dataclass
class Options:
    # A config object naturally groups many related settings; the attribute
    # count is intentional and clearer than splitting it apart.
    # pylint: disable=too-many-instance-attributes
    """Conversion options shared across all front ends."""

    max_width: int | None = None
    max_height: int | None = None
    lossless: bool = True
    quality: int = DEFAULT_QUALITY
    method: int = DEFAULT_METHOD
    overwrite: bool = False
    # When set, also emit a thumbnail WebP whose longest side is this many px.
    # Thumbnails are always lossy (lossless thumbnails defeat their purpose).
    thumbnail: int | None = None
    thumbnail_quality: int = DEFAULT_THUMBNAIL_QUALITY

    def validate(self) -> None:
        """Raise ValueError if any option is out of range."""
        if self.max_width is not None and self.max_width <= 0:
            raise ValueError("max_width must be a positive integer")
        if self.max_height is not None and self.max_height <= 0:
            raise ValueError("max_height must be a positive integer")
        if not 0 <= self.quality <= 100:
            raise ValueError("quality must be between 0 and 100")
        if not 0 <= self.method <= 6:
            raise ValueError("method must be between 0 and 6")
        if self.thumbnail is not None and self.thumbnail <= 0:
            raise ValueError("thumbnail size must be a positive integer")
        if not 0 <= self.thumbnail_quality <= 100:
            raise ValueError("thumbnail_quality must be between 0 and 100")


def dest_for(src: Path, base: Path, output_dir: Path | None) -> Path:
    """
    Compute the output ``.webp`` path for a source image.

    When ``output_dir`` is None the output sits next to the source. Otherwise the source tree
    (relative to ``base``) is mirrored under ``output_dir``.

    """
    if output_dir is None:
        return src.with_suffix(".webp")
    rel = src.relative_to(base).with_suffix(".webp")
    return output_dir / rel


def thumb_dest_for(dst: Path) -> Path:
    """
    Compute the thumbnail path for a main output path.

    The thumbnail sits next to the main output with a ``.thumb.webp`` suffix, e.g. ``photo.webp`` ->
    ``photo.thumb.webp``.

    """
    return dst.with_suffix(".thumb.webp")


def parse_optional_dim(value) -> int | None:
    """
    Parse an optional positive-integer dimension from a form or JSON value.

    Blank, ``None``, or ``"0"`` mean "no constraint" and return ``None``. Any other value must be a
    positive integer, otherwise ``ValueError`` is raised.

    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
    if value in ("", "0", 0):
        return None
    n = int(value)
    if n <= 0:
        raise ValueError("dimensions must be positive integers")
    return n


def discover_jobs(
    input_path: Path,
    output_dir: Path | None = None,
) -> list[Job]:
    """
    Build the list of conversion jobs from a file or directory input.

    Directories are walked recursively. Non-image files are ignored.

    Raises:
        FileNotFoundError: if ``input_path`` does not exist.
        ValueError: if ``input_path`` is a file with an unsupported extension.

    """
    input_path = Path(input_path)

    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTS:
            raise ValueError(
                f"Unsupported input file type: {input_path.suffix!r} "
                f"(supported: {', '.join(sorted(SUPPORTED_EXTS))})"
            )
        return [Job(input_path, dest_for(input_path, input_path.parent, output_dir))]

    if input_path.is_dir():
        jobs: list[Job] = []
        for root, _dirs, files in os.walk(input_path):
            root_path = Path(root)
            for name in sorted(files):
                src = root_path / name
                if src.suffix.lower() in SUPPORTED_EXTS:
                    jobs.append(Job(src, dest_for(src, input_path, output_dir)))
        return jobs

    raise FileNotFoundError(f"Input path does not exist: {input_path}")


def compute_size(
    size: tuple[int, int],
    max_width: int | None,
    max_height: int | None,
) -> tuple[int, int]:
    """
    Return the target (w, h) after applying width/height constraints.

    Preserves aspect ratio and never upscales. If no constraint binds, the original size is returned
    unchanged.

    """
    w, h = size
    scales = []
    if max_width is not None:
        scales.append(max_width / w)
    if max_height is not None:
        scales.append(max_height / h)
    if not scales:
        return w, h
    scale = min(scales)
    if scale >= 1:  # already fits; never upscale
        return w, h
    return max(1, round(w * scale)), max(1, round(h * scale))


def resize_image(img: Image.Image, max_width: int | None, max_height: int | None) -> Image.Image:
    """Downscale an image to fit the given constraints, preserving aspect ratio."""
    new_size = compute_size(img.size, max_width, max_height)
    if new_size == img.size:
        return img
    return img.resize(new_size, _LANCZOS)


def _normalize_mode(img: Image.Image) -> Image.Image:
    """Convert modes WebP cannot store directly into ones it can."""
    if img.mode in ("P", "LA"):
        return img.convert("RGBA")
    if img.mode == "CMYK":
        return img.convert("RGB")
    return img


def _save_webp(
    img: Image.Image,
    dst: Path,
    *,
    lossless: bool,
    quality: int,
    method: int,
) -> None:
    """Save an image as WebP, normalising its mode first."""
    img = _normalize_mode(img)
    save_kwargs: dict = {"method": method}
    if lossless:
        save_kwargs["lossless"] = True
        # In lossless mode WebP "quality" tunes compression effort; 100
        # yields the smallest file.
        save_kwargs["quality"] = 100
    else:
        save_kwargs["lossless"] = False
        save_kwargs["quality"] = quality
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "WEBP", **save_kwargs)


def convert_one(job: Job, options: Options) -> Result:
    """
    Convert a single image according to ``options``.

    Produces the main WebP output and, when ``options.thumbnail`` is set, an
    additional ``.thumb.webp`` thumbnail alongside it (always lossy).

    Safe to call inside a worker process: it never raises, returning a
    ``Result`` with ``ok=False`` and a message on failure instead.

    """
    try:
        thumb_dst = thumb_dest_for(job.dst) if options.thumbnail else None

        # Honour skip-existing. If a thumbnail is requested we only skip when
        # both the main output and the thumbnail already exist.
        if not options.overwrite and job.dst.exists() and (thumb_dst is None or thumb_dst.exists()):
            return Result(job.src, job.dst, True, "skipped (exists)")

        job.dst.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(job.src) as img:
            img.load()
            main = resize_image(img, options.max_width, options.max_height)

            _save_webp(
                main,
                job.dst,
                lossless=options.lossless,
                quality=options.quality,
                method=options.method,
            )

            if thumb_dst is not None:
                # Thumbnail fits inside a square box of side ``thumbnail``.
                # Derived from the already-resized main image; never upscaled.
                thumb = resize_image(main, options.thumbnail, options.thumbnail)
                _save_webp(
                    thumb,
                    thumb_dst,
                    lossless=False,
                    quality=options.thumbnail_quality,
                    method=options.method,
                )

        msg = "ok (+thumb)" if thumb_dst is not None else "ok"
        return Result(job.src, job.dst, True, msg)
    # A worker must never crash the pool: capture any failure as a result.
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return Result(job.src, job.dst, False, f"error: {exc}")
