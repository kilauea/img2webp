"""Tests for EXIF/metadata preservation and stripping."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from img2webp.core import (
    FORMAT_AVIF,
    FORMAT_WEBP,
    Job,
    Options,
    convert_one,
    extract_metadata,
    thumb_dest_for,
)

# EXIF tag numbers used in the tests.
_ORIENTATION = 274
_DESCRIPTION = 270


@pytest.fixture
def exif_jpeg(tmp_path, make_image):
    """A JPEG carrying an EXIF orientation + description tag."""
    path = tmp_path / "src.jpg"
    exif = Image.Exif()
    exif[_ORIENTATION] = 6
    exif[_DESCRIPTION] = "test-description"
    Image.new("RGB", (120, 90), (90, 140, 200)).save(path, exif=exif.tobytes())
    return path


def _exif_desc(path: Path):
    with Image.open(path) as im:
        if not im.info.get("exif"):
            return None
        return im.getexif().get(_DESCRIPTION)


def test_source_has_exif(exif_jpeg):
    # Sanity check: the fixture really carries EXIF.
    assert _exif_desc(exif_jpeg) == "test-description"


def test_extract_metadata_reads_exif(exif_jpeg):
    with Image.open(exif_jpeg) as im:
        meta = extract_metadata(im)
    assert "exif" in meta


def test_extract_metadata_empty_without_metadata(tmp_path, make_image):
    plain = make_image(tmp_path / "plain.png", size=(10, 10))
    with Image.open(plain) as im:
        assert extract_metadata(im) == {}


class TestKeepVsStrip:
    @pytest.mark.parametrize("fmt", [FORMAT_WEBP, FORMAT_AVIF])
    def test_metadata_preserved_by_default(self, exif_jpeg, tmp_path, fmt):
        dst = tmp_path / f"keep.{fmt}"
        res = convert_one(Job(exif_jpeg, dst), Options(fmt=fmt, overwrite=True))
        assert res.ok
        assert _exif_desc(dst) == "test-description"

    @pytest.mark.parametrize("fmt", [FORMAT_WEBP, FORMAT_AVIF])
    def test_metadata_stripped_when_requested(self, exif_jpeg, tmp_path, fmt):
        dst = tmp_path / f"strip.{fmt}"
        res = convert_one(
            Job(exif_jpeg, dst), Options(fmt=fmt, strip_metadata=True, overwrite=True)
        )
        assert res.ok
        with Image.open(dst) as im:
            assert not im.info.get("exif")

    def test_thumbnail_never_carries_metadata(self, exif_jpeg, tmp_path):
        dst = tmp_path / "img.webp"
        convert_one(
            Job(exif_jpeg, dst),
            Options(fmt=FORMAT_WEBP, thumbnail=48, strip_metadata=False, overwrite=True),
        )
        # Main keeps metadata, thumbnail does not.
        assert _exif_desc(dst) == "test-description"
        thumb = thumb_dest_for(dst, FORMAT_WEBP)
        with Image.open(thumb) as im:
            assert not im.info.get("exif")


def test_strip_metadata_default_is_false():
    assert Options().strip_metadata is False
