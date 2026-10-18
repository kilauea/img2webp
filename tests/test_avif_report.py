"""Tests for AVIF output format and the size-reduction report."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from img2webp import report as rpt
from img2webp import run_batch
from img2webp.core import (
    FORMAT_AVIF,
    FORMAT_WEBP,
    Job,
    Options,
    Result,
    convert_one,
    dest_for,
    discover_jobs,
    thumb_dest_for,
)


class TestFormatPaths:
    def test_dest_for_webp(self):
        assert dest_for(Path("/in/a.jpg"), Path("/in"), None, FORMAT_WEBP) == Path("/in/a.webp")

    def test_dest_for_avif(self):
        assert dest_for(Path("/in/a.jpg"), Path("/in"), None, FORMAT_AVIF) == Path("/in/a.avif")

    def test_dest_for_avif_output_dir_mirrors(self):
        got = dest_for(Path("/in/sub/a.png"), Path("/in"), Path("/out"), FORMAT_AVIF)
        assert got == Path("/out/sub/a.avif")

    def test_thumb_dest_webp_and_avif(self):
        assert thumb_dest_for(Path("/o/a.webp"), FORMAT_WEBP) == Path("/o/a.thumb.webp")
        assert thumb_dest_for(Path("/o/a.avif"), FORMAT_AVIF) == Path("/o/a.thumb.avif")

    def test_discover_jobs_uses_format_extension(self, sample_tree):
        jobs = discover_jobs(sample_tree, None, FORMAT_AVIF)
        assert jobs
        assert all(j.dst.suffix == ".avif" for j in jobs)


class TestAvifConversion:
    def test_convert_produces_avif(self, tmp_path, make_image):
        src = make_image(tmp_path / "a.jpg", size=(300, 200))
        dst = tmp_path / "a.avif"
        res = convert_one(Job(src, dst), Options(fmt=FORMAT_AVIF))
        assert res.ok
        assert dst.exists()
        with Image.open(dst) as im:
            assert im.format == "AVIF"
            assert im.size == (300, 200)

    def test_avif_thumbnail_extension(self, tmp_path, make_image):
        src = make_image(tmp_path / "a.jpg", size=(800, 600))
        dst = tmp_path / "a.avif"
        res = convert_one(Job(src, dst), Options(fmt=FORMAT_AVIF, thumbnail=128))
        assert res.ok
        assert (tmp_path / "a.thumb.avif").exists()

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError):
            Options(fmt="jpeg").validate()


class TestSizeCapture:
    def test_result_carries_sizes(self, tmp_path, make_image):
        src = make_image(tmp_path / "a.jpg", size=(400, 300))
        dst = tmp_path / "a.webp"
        res = convert_one(Job(src, dst), Options())
        assert res.src_bytes == src.stat().st_size
        assert res.dst_bytes == dst.stat().st_size
        assert res.dst_bytes > 0

    def test_skipped_has_zero_sizes(self, tmp_path, make_image):
        src = make_image(tmp_path / "a.jpg", size=(50, 50))
        dst = tmp_path / "a.webp"
        convert_one(Job(src, dst), Options())  # create it
        res = convert_one(Job(src, dst), Options(overwrite=False))
        assert "skipped" in res.message
        assert res.src_bytes == 0 and res.dst_bytes == 0


class TestReport:
    def _results(self):
        return [
            Result(Path("/in/a.jpg"), Path("/o/a.webp"), True, "ok", 100000, 25000),
            Result(Path("/in/b.png"), Path("/o/b.webp"), True, "ok", 50000, 60000),
            Result(Path("/in/c.jpg"), Path("/o/c.webp"), True, "skipped (exists)", 0, 0),
            Result(Path("/in/d.jpg"), Path("/o/d.webp"), False, "error: boom"),
        ]

    def test_build_excludes_skipped_and_failed(self):
        rep = rpt.build_report(self._results())
        assert len(rep.rows) == 2

    def test_row_reduction_pct(self):
        rep = rpt.build_report(self._results())
        a = rep.rows[0]
        assert a.reduction_pct == pytest.approx(75.0)
        b = rep.rows[1]
        assert b.reduction_pct == pytest.approx(-20.0)  # grew

    def test_totals(self):
        rep = rpt.build_report(self._results())
        assert rep.total_original == 150000
        assert rep.total_new == 85000
        assert rep.total_reduction_pct == pytest.approx(43.333, abs=0.01)

    def test_render_text_has_total_row(self):
        rep = rpt.build_report(self._results())
        text = rpt.render_text(rep)
        assert "TOTAL" in text
        assert "Reduction" in text

    def test_render_csv_structure(self):
        rep = rpt.build_report(self._results())
        csv_text = rpt.render_csv(rep)
        lines = csv_text.strip().splitlines()
        assert lines[0] == "source,output,original_bytes,new_bytes,reduction_pct"
        assert lines[-1].startswith("TOTAL,")
        assert len(lines) == 1 + 2 + 1  # header + 2 rows + total

    def test_empty_report_text(self):
        assert "No converted" in rpt.render_text(rpt.build_report([]))

    def test_human_size(self):
        assert rpt.human_size(0) == "0 B"
        assert rpt.human_size(1536) == "1.5 KB"

    def test_infer_format(self):
        assert rpt.infer_format(Path("r.csv")) == "csv"
        assert rpt.infer_format(Path("r.txt")) == "text"
        assert rpt.infer_format(Path("r")) == "text"

    def test_save_report_text(self, tmp_path):
        rep = rpt.build_report(self._results())
        out = rpt.save_report(rep, tmp_path / "sub" / "r.txt", "text")
        assert out.exists()
        assert "TOTAL" in out.read_text()

    def test_save_report_csv(self, tmp_path):
        rep = rpt.build_report(self._results())
        out = rpt.save_report(rep, tmp_path / "r.csv", "csv")
        assert out.read_text().startswith("source,output,")

    def test_save_report_bad_format(self, tmp_path):
        rep = rpt.build_report(self._results())
        with pytest.raises(ValueError):
            rpt.save_report(rep, tmp_path / "r.bin", "bogus")

    def test_to_dicts(self):
        rep = rpt.build_report(self._results())
        dicts = rpt.to_dicts(rep)
        assert dicts[0]["original_bytes"] == 100000
        assert dicts[0]["reduction_pct"] == 75.0


def test_report_from_real_batch(sample_tree, tmp_path):
    jobs = discover_jobs(sample_tree, tmp_path / "out", FORMAT_WEBP)
    results = run_batch(jobs, Options(overwrite=True), workers=2)
    rep = rpt.build_report(results)
    assert len(rep.rows) == 2
    assert rep.total_original > 0
    assert all(r.new_bytes > 0 for r in rep.rows)
