"""Tests for pure core logic: size computation, options, destination paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from img2webp.core import Options, compute_size, dest_for


class TestComputeSize:
    def test_no_constraints_returns_original(self):
        assert compute_size((2000, 1000), None, None) == (2000, 1000)

    def test_width_only(self):
        # 2000x1000 scaled so width=500 -> 500x250
        assert compute_size((2000, 1000), 500, None) == (500, 250)

    def test_height_only(self):
        # 2000x1000 scaled so height=250 -> 500x250
        assert compute_size((2000, 1000), None, 250) == (500, 250)

    def test_both_height_binds(self):
        # width factor .5, height factor .2 -> height wins -> 400x200
        assert compute_size((2000, 1000), 1000, 200) == (400, 200)

    def test_both_width_binds(self):
        # width factor .3, height factor .8 -> width wins -> 600x300
        assert compute_size((2000, 1000), 600, 800) == (600, 300)

    def test_never_upscales(self):
        # constraints larger than the image -> unchanged
        assert compute_size((800, 600), 5000, 5000) == (800, 600)

    def test_aspect_ratio_preserved(self):
        w, h = compute_size((3000, 2000), 1024, None)
        assert w == 1024
        assert abs(w / h - 3000 / 2000) < 0.01


class TestOptionsValidate:
    def test_valid_defaults_ok(self):
        Options().validate()  # should not raise

    @pytest.mark.parametrize(
        "field,value",
        [
            ("max_width", 0),
            ("max_width", -5),
            ("max_height", 0),
            ("max_height", -1),
            ("quality", -1),
            ("quality", 101),
            ("method", -1),
            ("method", 7),
        ],
    )
    def test_invalid_values_raise(self, field, value):
        opts = Options(**{field: value})
        with pytest.raises(ValueError):
            opts.validate()


class TestDestFor:
    def test_alongside_source_when_no_output_dir(self):
        src = Path("/data/pics/a.jpg")
        assert dest_for(src, src.parent, None) == Path("/data/pics/a.webp")

    def test_mirrors_tree_under_output_dir(self):
        base = Path("/data/in")
        src = base / "sub" / "a.png"
        out = Path("/data/out")
        assert dest_for(src, base, out) == Path("/data/out/sub/a.webp")
