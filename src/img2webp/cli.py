"""Command-line interface for img2webp."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .core import DEFAULT_QUALITY, DEFAULT_THUMBNAIL_QUALITY, Options, discover_jobs
from . import run_batch


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the img2webp command-line interface."""
    p = argparse.ArgumentParser(
        prog="img2webp",
        description="Convert JPEG/PNG images to WebP (lossless by default).",
    )
    p.add_argument("input", type=Path, help="Input image file or directory.")
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (tree mirrored). Default: alongside sources.",
    )
    p.add_argument(
        "-W",
        "--max-width",
        type=int,
        default=None,
        help="Max width in px; downscales preserving aspect ratio.",
    )
    p.add_argument(
        "-H",
        "--max-height",
        type=int,
        default=None,
        help="Max height in px; downscales preserving aspect ratio. "
        "If both are given, the image is scaled to fit inside the box.",
    )
    p.add_argument(
        "--lossy",
        action="store_true",
        help="Use lossy WebP instead of the default lossless encoding.",
    )
    p.add_argument(
        "-q",
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help=f"Quality (0-100) for lossy mode. Default: {DEFAULT_QUALITY}.",
    )
    p.add_argument(
        "--method",
        type=int,
        default=6,
        choices=range(0, 7),
        metavar="0-6",
        help="WebP encoder effort (0=fast, 6=best). Default: 6.",
    )
    p.add_argument(
        "-t",
        "--thumbnail",
        type=int,
        default=None,
        metavar="PX",
        help="Also emit a <name>.thumb.webp thumbnail whose longest side is "
        "PX pixels (lossy, aspect ratio preserved).",
    )
    p.add_argument(
        "--thumbnail-quality",
        type=int,
        default=DEFAULT_THUMBNAIL_QUALITY,
        metavar="0-100",
        help=f"Thumbnail quality. Default: {DEFAULT_THUMBNAIL_QUALITY}.",
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=os.cpu_count() or 1,
        help="Number of concurrent worker processes. Default: CPU count.",
    )
    p.add_argument(
        "-f",
        "--overwrite",
        action="store_true",
        help="Overwrite existing .webp outputs (default: skip them).",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the CLI: parse arguments, convert images, and return an exit code."""
    args = build_parser().parse_args(argv)

    options = Options(
        max_width=args.max_width,
        max_height=args.max_height,
        lossless=not args.lossy,
        quality=args.quality,
        method=args.method,
        overwrite=args.overwrite,
        thumbnail=args.thumbnail,
        thumbnail_quality=args.thumbnail_quality,
    )
    try:
        options.validate()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        jobs = discover_jobs(args.input, args.output_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not jobs:
        print("No supported images found.", file=sys.stderr)
        return 1

    workers = max(1, args.jobs)
    mode = "lossless" if options.lossless else f"lossy q{options.quality}"
    print(f"Converting {len(jobs)} image(s) with {workers} worker(s) [{mode}]...")

    failures = 0

    def report(res) -> None:
        nonlocal failures
        status = "OK " if res.ok else "FAIL"
        if not res.ok:
            failures += 1
        print(f"  [{status}] {res.src} -> {res.dst} ({res.message})")

    run_batch(jobs, options, workers=workers, on_result=report)

    done = len(jobs) - failures
    print(f"Done. {done} succeeded, {failures} failed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
