"""Shared pytest fixtures for img2webp tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def make_image():
    """Factory to create an image file of a given size/mode at a path."""

    def _make(path: Path, size=(1200, 800), mode="RGB", color=(180, 90, 40)):
        path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "RGBA" and len(color) == 3:
            color = (*color, 255)
        img = Image.new(mode, size, color)
        img.save(path)
        return path

    return _make


@pytest.fixture
def sample_tree(tmp_path, make_image):
    """A nested input tree with two images and one non-image file."""
    root = tmp_path / "in"
    make_image(root / "a.jpg", size=(2400, 1600), mode="RGB")
    make_image(root / "sub" / "b.png", size=(900, 700), mode="RGBA")
    (root / "notes.txt").write_text("ignore me")
    return root
