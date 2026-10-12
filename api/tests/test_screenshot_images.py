"""Screenshot renditions (app-store-listings design D7)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.images import (
    SCREENSHOT_FULL_MAX_EDGE,
    SCREENSHOT_THUMBNAIL_HEIGHT,
    check_screenshot,
    render_screenshot,
    screenshot_rel_path,
)
from app.models import screenshot_thumbnail_path


def encode(size, fmt="PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "orange").save(buffer, format=fmt)
    return buffer.getvalue()


def test_renditions_are_webp_at_their_sizes():
    full, thumb = render_screenshot(encode((3000, 1875)))

    full_img, thumb_img = Image.open(io.BytesIO(full)), Image.open(io.BytesIO(thumb))
    assert full_img.format == thumb_img.format == "WEBP"
    assert full_img.size == (SCREENSHOT_FULL_MAX_EDGE, 1500)
    assert thumb_img.size == (1088, SCREENSHOT_THUMBNAIL_HEIGHT)


def test_portrait_screenshot_thumbnail_keeps_its_height():
    full, thumb = render_screenshot(encode((1170, 2532)))
    assert Image.open(io.BytesIO(full)).size[1] == SCREENSHOT_FULL_MAX_EDGE
    assert Image.open(io.BytesIO(thumb)).size[1] == SCREENSHOT_THUMBNAIL_HEIGHT


def test_small_screenshot_is_not_upscaled():
    full, thumb = render_screenshot(encode((800, 500)))
    assert Image.open(io.BytesIO(full)).size == (800, 500)
    assert Image.open(io.BytesIO(thumb)).size == (800, 500)


def test_paths_are_keyed_by_source_and_pair_up():
    source = encode((100, 100))
    path = screenshot_rel_path(source)

    assert path.startswith("screenshots/") and path.endswith(".webp")
    assert path == screenshot_rel_path(source)
    assert path != screenshot_rel_path(encode((100, 101)))
    assert screenshot_thumbnail_path(path) == path.removesuffix(".webp") + "-thumb.webp"


def test_check_accepts_a_valid_screenshot():
    check_screenshot(encode((1600, 1000), "JPEG"))


def test_render_rejects_corrupt_bytes():
    with pytest.raises(ValueError, match="not a readable image"):
        render_screenshot(b"garbage")
