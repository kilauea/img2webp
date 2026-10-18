"""Tests for actual image conversion and the concurrent batch runner."""

from __future__ import annotations

from PIL import Image, ImageChops

from img2webp import run_batch
from img2webp.core import Job, Options, convert_one, discover_jobs


def test_convert_produces_webp(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(400, 300))
    dst = tmp_path / "a.webp"
    res = convert_one(Job(src, dst), Options())
    assert res.ok
    assert dst.exists()
    with Image.open(dst) as im:
        assert im.format == "WEBP"
        assert im.size == (400, 300)


def test_resize_applied_on_convert(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(2400, 1600))
    dst = tmp_path / "a.webp"
    res = convert_one(Job(src, dst), Options(max_width=1200))
    assert res.ok
    with Image.open(dst) as im:
        assert im.size == (1200, 800)  # aspect ratio preserved


def test_lossless_is_pixel_exact(tmp_path):
    # A detailed pattern where lossy artefacts would show.
    src = tmp_path / "pattern.png"
    im = Image.new("RGB", (128, 128))
    px = im.load()
    for y in range(128):
        for x in range(128):
            px[x, y] = ((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
    im.save(src)

    dst = tmp_path / "pattern.webp"
    assert convert_one(Job(src, dst), Options(lossless=True)).ok
    with Image.open(dst) as out:
        diff = ImageChops.difference(im, out.convert("RGB")).getbbox()
    assert diff is None  # identical


def test_alpha_preserved(tmp_path, make_image):
    src = make_image(tmp_path / "logo.png", size=(100, 100), mode="RGBA", color=(0, 160, 220, 128))
    dst = tmp_path / "logo.webp"
    assert convert_one(Job(src, dst), Options()).ok
    with Image.open(dst) as im:
        assert im.mode == "RGBA"


def test_skip_existing_without_overwrite(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(50, 50))
    dst = tmp_path / "a.webp"
    assert convert_one(Job(src, dst), Options()).ok
    res = convert_one(Job(src, dst), Options(overwrite=False))
    assert res.ok
    assert "skipped" in res.message


def test_overwrite_true_reconverts(tmp_path, make_image):
    src = make_image(tmp_path / "a.jpg", size=(50, 50))
    dst = tmp_path / "a.webp"
    convert_one(Job(src, dst), Options())
    res = convert_one(Job(src, dst), Options(overwrite=True))
    assert res.message == "ok"


def test_convert_failure_is_reported_not_raised(tmp_path):
    # Source does not exist -> convert_one returns ok=False, no exception.
    res = convert_one(Job(tmp_path / "missing.jpg", tmp_path / "x.webp"), Options())
    assert not res.ok
    assert "error" in res.message


def test_run_batch_converts_all(sample_tree, tmp_path):
    out = tmp_path / "out"
    jobs = discover_jobs(sample_tree, out)
    results = run_batch(jobs, Options(overwrite=True), workers=2)
    assert len(results) == 2
    assert all(r.ok for r in results)
    assert (out / "a.webp").exists()
    assert (out / "sub" / "b.webp").exists()


def test_run_batch_empty_returns_empty():
    assert run_batch([], Options()) == []


def test_run_batch_calls_callback(sample_tree, tmp_path):
    seen = []
    jobs = discover_jobs(sample_tree, tmp_path / "out")
    run_batch(jobs, Options(overwrite=True), workers=1, on_result=seen.append)
    assert len(seen) == len(jobs)
