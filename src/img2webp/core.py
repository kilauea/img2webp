"""
Core conversion logic for img2webp.

This module is deliberately free of any CLI or GUI concerns so that every
front end (CLI, web, desktop) shares exactly the same conversion behaviour.

Key behaviours:
  * Accepts JPEG/PNG input, writes WebP or AVIF output.
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

# Input extensions we accept (case-insensitive).
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}

# Output formats and their file extensions.
FORMAT_WEBP = "webp"
FORMAT_AVIF = "avif"
SUPPORTED_FORMATS = (FORMAT_WEBP, FORMAT_AVIF)
FORMAT_EXT = {FORMAT_WEBP: ".webp", FORMAT_AVIF: ".avif"}
# Pillow format identifiers used by Image.save().
_PIL_FORMAT = {FORMAT_WEBP: "WEBP", FORMAT_AVIF: "AVIF"}

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
    # Source and destination sizes in bytes (0 when not applicable, e.g. on
    # failure or when an existing output was skipped).
    src_bytes: int = 0
    dst_bytes: int = 0


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
    # Output format: "webp" (default) or "avif".
    fmt: str = FORMAT_WEBP
    # When True, drop EXIF/ICC/XMP metadata from the output. Default False
    # keeps the source metadata (orientation, color profile, etc.).
    strip_metadata: bool = False
    # When set, also emit a thumbnail whose longest side is this many px.
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
        if self.fmt not in SUPPORTED_FORMATS:
            raise ValueError(f"format must be one of {', '.join(SUPPORTED_FORMATS)}")
        if self.thumbnail is not None and self.thumbnail <= 0:
            raise ValueError("thumbnail size must be a positive integer")
        if not 0 <= self.thumbnail_quality <= 100:
            raise ValueError("thumbnail_quality must be between 0 and 100")


def dest_for(src: Path, base: Path, output_dir: Path | None, fmt: str = FORMAT_WEBP) -> Path:
    """
    Compute the output path for a source image in the given format.

    When ``output_dir`` is None the output sits next to the source. Otherwise the source tree
    (relative to ``base``) is mirrored under ``output_dir``. The extension follows ``fmt``
    (``.webp`` or ``.avif``).

    """
    ext = FORMAT_EXT[fmt]
    if output_dir is None:
        return src.with_suffix(ext)
    rel = src.relative_to(base).with_suffix(ext)
    return output_dir / rel


def thumb_dest_for(dst: Path, fmt: str = FORMAT_WEBP) -> Path:
    """
    Compute the thumbnail path for a main output path.

    The thumbnail sits next to the main output with a ``.thumb`` infix, e.g. ``photo.webp`` ->
    ``photo.thumb.webp`` (or ``.avif`` for AVIF output).

    """
    ext = FORMAT_EXT[fmt]
    return dst.with_suffix(f".thumb{ext}")


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
    fmt: str = FORMAT_WEBP,
) -> list[Job]:
    """
    Build the list of conversion jobs from a file or directory input.

    Directories are walked recursively. Non-image files are ignored. Output paths use the
    extension for ``fmt`` (``.webp`` or ``.avif``).

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
        return [Job(input_path, dest_for(input_path, input_path.parent, output_dir, fmt))]

    if input_path.is_dir():
        jobs: list[Job] = []
        for root, _dirs, files in os.walk(input_path):
            root_path = Path(root)
            for name in sorted(files):
                src = root_path / name
                if src.suffix.lower() in SUPPORTED_EXTS:
                    jobs.append(Job(src, dest_for(src, input_path, output_dir, fmt)))
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


def extract_metadata(img: Image.Image) -> dict:
    """
    Collect EXIF/ICC/XMP metadata from an opened image as save kwargs.

    Returns a dict with any of ``exif``, ``icc_profile``, ``xmp`` that are present on the source,
    suitable for passing to ``Image.save``. Empty when the image carries no metadata.

    """
    meta: dict = {}
    exif = img.info.get("exif")
    if exif:
        meta["exif"] = exif
    icc = img.info.get("icc_profile")
    if icc:
        meta["icc_profile"] = icc
    xmp = img.info.get("xmp")
    if xmp:
        meta["xmp"] = xmp
    return meta


def _save_image(  # pylint: disable=too-many-arguments
    img: Image.Image,
    dst: Path,
    *,
    fmt: str,
    lossless: bool,
    quality: int,
    method: int,
    metadata: dict | None = None,
) -> None:
    """Save an image as WebP or AVIF, normalising its mode and attaching metadata."""
    img = _normalize_mode(img)
    save_kwargs: dict = dict(metadata or {})
    if fmt == FORMAT_WEBP:
        save_kwargs["method"] = method
        if lossless:
            save_kwargs["lossless"] = True
            # In lossless mode WebP "quality" tunes compression effort; 100
            # yields the smallest file.
            save_kwargs["quality"] = 100
        else:
            save_kwargs["lossless"] = False
            save_kwargs["quality"] = quality
    else:  # AVIF
        # Map the shared WebP "method" (0=fast..6=best) onto AVIF "speed"
        # (0=slowest/best..10=fastest), so a higher effort means a slower,
        # better-compressing encode in both formats.
        save_kwargs["speed"] = max(0, 10 - method)
        if lossless:
            save_kwargs["lossless"] = True
            save_kwargs["quality"] = 100
        else:
            save_kwargs["quality"] = quality
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, _PIL_FORMAT[fmt], **save_kwargs)


def convert_one(job: Job, options: Options) -> Result:
    """
    Convert a single image according to ``options``.

    Produces the main output (WebP or AVIF) and, when ``options.thumbnail`` is
    set, an additional ``.thumb`` image alongside it (always lossy). The
    returned ``Result`` carries the source and destination byte sizes so a
    size-reduction report can be built.

    Safe to call inside a worker process: it never raises, returning a
    ``Result`` with ``ok=False`` and a message on failure instead.

    """
    try:
        thumb_dst = thumb_dest_for(job.dst, options.fmt) if options.thumbnail else None

        # Honour skip-existing. If a thumbnail is requested we only skip when
        # both the main output and the thumbnail already exist.
        if not options.overwrite and job.dst.exists() and (thumb_dst is None or thumb_dst.exists()):
            return Result(job.src, job.dst, True, "skipped (exists)")

        src_bytes = job.src.stat().st_size
        job.dst.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(job.src) as img:
            img.load()
            # Collect source metadata before resizing; keep it unless stripping.
            metadata = {} if options.strip_metadata else extract_metadata(img)
            main = resize_image(img, options.max_width, options.max_height)

            _save_image(
                main,
                job.dst,
                fmt=options.fmt,
                lossless=options.lossless,
                quality=options.quality,
                method=options.method,
                metadata=metadata,
            )

            if thumb_dst is not None:
                # Thumbnail fits inside a square box of side ``thumbnail``.
                # Derived from the already-resized main image; never upscaled.
                # Thumbnails never carry metadata (they are derived previews).
                thumb = resize_image(main, options.thumbnail, options.thumbnail)
                _save_image(
                    thumb,
                    thumb_dst,
                    fmt=options.fmt,
                    lossless=False,
                    quality=options.thumbnail_quality,
                    method=options.method,
                )

        dst_bytes = job.dst.stat().st_size
        msg = "ok (+thumb)" if thumb_dst is not None else "ok"
        return Result(job.src, job.dst, True, msg, src_bytes=src_bytes, dst_bytes=dst_bytes)
    # A worker must never crash the pool: capture any failure as a result.
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return Result(job.src, job.dst, False, f"error: {exc}")
