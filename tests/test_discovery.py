"""Tests for job discovery from files and directories."""

from __future__ import annotations

from pathlib import Path

import pytest

from img2webp.core import discover_jobs


def test_single_file(sample_tree):
    jobs = discover_jobs(sample_tree / "a.jpg")
    assert len(jobs) == 1
    assert jobs[0].src.name == "a.jpg"
    assert jobs[0].dst.name == "a.webp"


def test_directory_recursive_ignores_non_images(sample_tree):
    jobs = discover_jobs(sample_tree)
    names = sorted(j.src.name for j in jobs)
    assert names == ["a.jpg", "b.png"]  # notes.txt ignored


def test_output_dir_mirrors_tree(sample_tree, tmp_path):
    out = tmp_path / "out"
    jobs = discover_jobs(sample_tree, out)
    dsts = sorted(str(j.dst.relative_to(out)) for j in jobs)
    assert dsts == ["a.webp", str(Path("sub") / "b.webp")]


def test_unsupported_file_raises(tmp_path):
    bad = tmp_path / "doc.txt"
    bad.write_text("x")
    with pytest.raises(ValueError):
        discover_jobs(bad)


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_jobs(tmp_path / "nope")


def test_empty_directory_returns_no_jobs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert discover_jobs(empty) == []
