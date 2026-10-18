"""Tests for the thumbnail feature."""

from __future__ import annotations

from PIL import Image

from img2webp import run_batch, thumb_dest_for
from img2webp.core import Job, Options, convert_one, discover_jobs


def test_thumb_dest_for():
    from pathlib import Path

    assert thumb_dest_for(Path("/x/photo.webp")) == Path("/x/photo.thumb.webp")


def test_thumbnail_created_alongside_main(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(2000, 1000))
    dst = tmp_path / "a.webp"
    res = convert_one(Job(src, dst), Options(thumbnail=256))
    assert res.ok
    assert "thumb" in res.message
    thumb = tmp_path / "a.thumb.webp"
    assert dst.exists()
    assert thumb.exists()


def test_thumbnail_fits_longest_side(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(2000, 1000))
    dst = tmp_path / "a.webp"
    convert_one(Job(src, dst), Options(thumbnail=256))
    with Image.open(tmp_path / "a.thumb.webp") as im:
        # Longest side (width here) capped at 256; aspect ratio preserved.
        assert max(im.size) == 256
        assert im.size == (256, 128)


def test_thumbnail_never_upscales(tmp_path, make_image):
    src = make_image(tmp_path / "small.png", size=(100, 80), mode="RGBA")
    dst = tmp_path / "small.webp"
    convert_one(Job(src, dst), Options(thumbnail=256))
    with Image.open(tmp_path / "small.thumb.webp") as im:
        assert im.size == (100, 80)  # unchanged, not upscaled


def test_thumbnail_respects_main_resize(tmp_path, make_image):
    # Main capped to 500 wide, thumbnail to 256 -> thumb derived from resized.
    src = make_image(tmp_path / "a.jpg", size=(2000, 1000))
    dst = tmp_path / "a.webp"
    convert_one(Job(src, dst), Options(max_width=500, thumbnail=256))
    with Image.open(dst) as main:
        assert main.size == (500, 250)
    with Image.open(tmp_path / "a.thumb.webp") as thumb:
        assert thumb.size == (256, 128)


def test_no_thumbnail_by_default(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(400, 300))
    dst = tmp_path / "a.webp"
    res = convert_one(Job(src, dst), Options())
    assert res.message == "ok"
    assert not (tmp_path / "a.thumb.webp").exists()


def test_skip_regenerates_missing_thumbnail(tmp_path, make_image):
    # Main exists but thumbnail is missing -> not skipped; thumb created.
    src = make_image(tmp_path / "a.jpg", size=(400, 300))
    dst = tmp_path / "a.webp"
    convert_one(Job(src, dst), Options())  # main only
    assert not (tmp_path / "a.thumb.webp").exists()
    res = convert_one(Job(src, dst), Options(thumbnail=128, overwrite=False))
    assert res.ok
    assert "thumb" in res.message
    assert (tmp_path / "a.thumb.webp").exists()


def test_skip_when_both_exist(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(400, 300))
    dst = tmp_path / "a.webp"
    convert_one(Job(src, dst), Options(thumbnail=128))  # both created
    res = convert_one(Job(src, dst), Options(thumbnail=128, overwrite=False))
    assert "skipped" in res.message


def test_thumbnail_validation():
    import pytest

    with pytest.raises(ValueError):
        Options(thumbnail=0).validate()
    with pytest.raises(ValueError):
        Options(thumbnail_quality=200).validate()


def test_run_batch_with_thumbnails(sample_tree, tmp_path):
    out = tmp_path / "out"
    jobs = discover_jobs(sample_tree, out)
    results = run_batch(jobs, Options(thumbnail=128, overwrite=True), workers=2)
    assert all(r.ok for r in results)
    assert (out / "a.thumb.webp").exists()
    assert (out / "sub" / "b.thumb.webp").exists()
