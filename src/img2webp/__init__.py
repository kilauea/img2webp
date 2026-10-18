"""img2webp - Convert JPEG/PNG images to WebP (lossless by default).

Public API:
    Job, Result, Options       - data types
    discover_jobs              - build jobs from a file/dir
    convert_one                - convert a single job
    compute_size, resize_image - scaling helpers
    run_batch                  - run many jobs concurrently
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable, Iterable

from .core import (
    DEFAULT_METHOD,
    DEFAULT_QUALITY,
    DEFAULT_THUMBNAIL_QUALITY,
    SUPPORTED_EXTS,
    Job,
    Options,
    Result,
    compute_size,
    convert_one,
    dest_for,
    discover_jobs,
    parse_optional_dim,
    resize_image,
    thumb_dest_for,
)

__version__ = "1.0.0"

__all__ = [
    "DEFAULT_METHOD",
    "DEFAULT_QUALITY",
    "DEFAULT_THUMBNAIL_QUALITY",
    "SUPPORTED_EXTS",
    "Job",
    "Options",
    "Result",
    "compute_size",
    "convert_one",
    "dest_for",
    "discover_jobs",
    "parse_optional_dim",
    "resize_image",
    "thumb_dest_for",
    "run_batch",
    "__version__",
]


def run_batch(
    jobs: Iterable[Job],
    options: Options,
    workers: int = 1,
    on_result: Callable[[Result], None] | None = None,
) -> list[Result]:
    """
    Convert many jobs concurrently using a process pool.

    Args:
        jobs: iterable of Job to convert.
        options: shared conversion options (validated by the caller).
        workers: number of worker processes (coerced to >= 1).
        on_result: optional callback invoked (in the calling thread) as each
            result completes - useful for progress reporting in GUIs.

    Returns:
        A list of Result, sorted by source path for stable output.

    """
    jobs = list(jobs)
    workers = max(1, workers)
    results: list[Result] = []

    if not jobs:
        return results

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(convert_one, job, options) for job in jobs]
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            if on_result is not None:
                on_result(res)

    results.sort(key=lambda r: str(r.src))
    return results
