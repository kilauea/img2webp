"""
Size-reduction reporting for img2webp.

Builds a per-file report from conversion results showing the original file size, the new file size,
and the reduction percentage, plus totals. The report can be rendered as a human-readable text table
or as CSV, and saved to a file.

"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .core import Result

# CSV / programmatic column headers.
COLUMNS = ("source", "output", "original_bytes", "new_bytes", "reduction_pct")


@dataclass
class ReportRow:
    """A single row of the size-reduction report."""

    source: str
    output: str
    original_bytes: int
    new_bytes: int

    @property
    def reduction_pct(self) -> float:
        """
        Return the size reduction as a percentage of the original.

        Positive means the output is smaller than the source. Zero when the original size is unknown
        (0 bytes).

        """
        if self.original_bytes <= 0:
            return 0.0
        return (1.0 - self.new_bytes / self.original_bytes) * 100.0


@dataclass
class Report:
    """A full report: the converted rows plus totals."""

    rows: list[ReportRow]

    @property
    def total_original(self) -> int:
        """Total original bytes across all rows."""
        return sum(r.original_bytes for r in self.rows)

    @property
    def total_new(self) -> int:
        """Total output bytes across all rows."""
        return sum(r.new_bytes for r in self.rows)

    @property
    def total_reduction_pct(self) -> float:
        """Overall reduction percentage across all rows."""
        if self.total_original <= 0:
            return 0.0
        return (1.0 - self.total_new / self.total_original) * 100.0


def build_report(results: Iterable[Result]) -> Report:
    """
    Build a :class:`Report` from conversion results.

    Only successful conversions that actually produced an output (``dst_bytes`` > 0) are included;
    skipped or failed entries are omitted so the size figures stay meaningful.

    """
    rows = [
        ReportRow(str(r.src), str(r.dst), r.src_bytes, r.dst_bytes)
        for r in results
        if r.ok and r.dst_bytes > 0
    ]
    return Report(rows)


def human_size(num_bytes: int) -> str:
    """Format a byte count as a short human-readable string (e.g. ``1.2 MB``)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def render_text(report: Report) -> str:
    """Render the report as a human-readable aligned text table."""
    if not report.rows:
        return "No converted images to report."

    name_w = max(len("File"), *(len(Path(r.source).name) for r in report.rows))
    lines = [
        f"{'File':<{name_w}}  {'Original':>10}  {'New':>10}  {'Reduction':>9}",
        f"{'-' * name_w}  {'-' * 10}  {'-' * 10}  {'-' * 9}",
    ]
    for row in report.rows:
        lines.append(
            f"{Path(row.source).name:<{name_w}}  "
            f"{human_size(row.original_bytes):>10}  "
            f"{human_size(row.new_bytes):>10}  "
            f"{row.reduction_pct:>8.1f}%"
        )
    lines.append(f"{'-' * name_w}  {'-' * 10}  {'-' * 10}  {'-' * 9}")
    lines.append(
        f"{'TOTAL':<{name_w}}  "
        f"{human_size(report.total_original):>10}  "
        f"{human_size(report.total_new):>10}  "
        f"{report.total_reduction_pct:>8.1f}%"
    )
    return "\n".join(lines)


def render_csv(report: Report) -> str:
    """Render the report as CSV text (header + one row per file + a TOTAL row)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for row in report.rows:
        writer.writerow(
            [
                row.source,
                row.output,
                row.original_bytes,
                row.new_bytes,
                f"{row.reduction_pct:.2f}",
            ]
        )
    writer.writerow(
        [
            "TOTAL",
            "",
            report.total_original,
            report.total_new,
            f"{report.total_reduction_pct:.2f}",
        ]
    )
    return buf.getvalue()


def to_dicts(report: Report) -> list[dict]:
    """Return the report rows as JSON-serialisable dicts (for the web GUI)."""
    return [
        {
            "source": r.source,
            "output": r.output,
            "original_bytes": r.original_bytes,
            "new_bytes": r.new_bytes,
            "reduction_pct": round(r.reduction_pct, 2),
        }
        for r in report.rows
    ]


def save_report(report: Report, path: Path, fmt: str = "text") -> Path:
    """
    Save the report to ``path`` in ``"text"`` or ``"csv"`` format.

    The parent directory is created if needed. Returns the path written.

    """
    if fmt not in ("text", "csv"):
        raise ValueError("report format must be 'text' or 'csv'")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render_csv(report) if fmt == "csv" else render_text(report) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def infer_format(path: Path) -> str:
    """Infer the report format from a path's extension (``.csv`` -> csv, else text)."""
    return "csv" if Path(path).suffix.lower() == ".csv" else "text"


def summary_line(report: Report) -> str:
    """Return a one-line overall summary suitable for logging."""
    return (
        f"{len(report.rows)} file(s): "
        f"{human_size(report.total_original)} -> {human_size(report.total_new)} "
        f"({report.total_reduction_pct:.1f}% reduction)"
    )


__all__: Sequence[str] = (
    "COLUMNS",
    "Report",
    "ReportRow",
    "build_report",
    "human_size",
    "infer_format",
    "render_csv",
    "render_text",
    "save_report",
    "summary_line",
    "to_dicts",
)
