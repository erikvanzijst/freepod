from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps

MAX_ICON_SIZE = 10 * 1024 * 1024  # 10MB
MAX_ICON_DIMENSION = 2048
ICON_SIZE = 256


def process_icon(image_data: bytes) -> bytes:
    """Process icon image: normalize orientation, center-crop to square, downscale to 256, output PNG.

    Args:
        image_data: Raw image bytes

    Returns:
        Processed PNG image bytes

    Raises:
        ValueError: If image is too large or invalid
    """
    if len(image_data) > MAX_ICON_SIZE:
        raise ValueError(
            f"Image file too large. Maximum size is {MAX_ICON_SIZE // (1024 * 1024)}MB"
        )

    try:
        img = Image.open(io.BytesIO(image_data))
    except Exception as e:
        raise ValueError(f"Invalid image file: {e}") from e

    width, height = img.size
    if width > MAX_ICON_DIMENSION or height > MAX_ICON_DIMENSION:
        raise ValueError(
            f"Image dimensions too large. Maximum allowed is {MAX_ICON_DIMENSION}x{MAX_ICON_DIMENSION}"
        )

    if hasattr(img, "_getexif") and img._getexif():
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    size = min(img.size)
    left = (img.width - size) // 2
    top = (img.height - size) // 2
    right = left + size
    bottom = top + size
    img = img.crop((left, top, right, bottom))

    if img.width > ICON_SIZE or img.height > ICON_SIZE:
        img.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)

    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output.getvalue()


def generate_icon_filename(processed_data: bytes) -> str:
    """Generate an icon filename based on SHA1 hash of the processed image data.

    Args:
        processed_data: Processed PNG bytes

    Returns:
        Relative path like "icons/<sha1>.png"
    """
    sha1_hash = hashlib.sha1(processed_data).hexdigest()
    return f"icons/{sha1_hash}.png"


def save_icon(processed_data: bytes, rel_path: str) -> Path:
    """Save processed icon data to static storage.

    Args:
        processed_data: Processed PNG bytes
        rel_path: Relative path including icons/ prefix

    Returns:
        Absolute path to saved file
    """
    from app.config import get_settings

    static_path = get_settings().static_path
    file_path = static_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(processed_data)
    return file_path


# ---------------------------------------------------------------------------
# Screenshots (app-store-listings design D7)
# ---------------------------------------------------------------------------

SCREENSHOT_FORMATS = ("PNG", "JPEG", "WEBP")
SCREENSHOT_MAX_BYTES = 1024 * 1024
SCREENSHOT_MAX_DIMENSION = 4096
SCREENSHOTS_MAX_COUNT = 12
SCREENSHOTS_MAX_TOTAL_BYTES = 5 * 1024 * 1024
# The page's strip is 340 CSS px tall; thumbnails cover 2x density.
SCREENSHOT_THUMBNAIL_HEIGHT = 680
SCREENSHOT_FULL_MAX_EDGE = 2400
SCREENSHOT_QUALITY = 82
# Part of every rendition's name, so changing the pipeline republishes them all.
SCREENSHOT_PIPELINE_VERSION = 1


def check_screenshot(image_data: bytes) -> None:
    """Validate a committed screenshot without decoding its pixels.

    Raises:
        ValueError: naming the limit the image breaks.
    """
    if len(image_data) > SCREENSHOT_MAX_BYTES:
        raise ValueError(
            f"is {len(image_data)} bytes; the limit is {SCREENSHOT_MAX_BYTES} bytes (1 MB)"
        )
    try:
        img = Image.open(io.BytesIO(image_data))
    except Exception as e:
        raise ValueError(f"is not a readable image: {e}") from e
    if img.format not in SCREENSHOT_FORMATS:
        raise ValueError(f"is {img.format}; screenshots must be PNG, JPEG or WebP")
    if max(img.size) > SCREENSHOT_MAX_DIMENSION:
        raise ValueError(
            f"is {img.width}x{img.height}; the long edge limit is {SCREENSHOT_MAX_DIMENSION} px"
        )


def screenshot_rel_path(image_data: bytes) -> str:
    """Static-storage path of a screenshot's full-size rendition.

    Keyed by the *source* bytes, so whether the renditions exist can be checked
    without rendering them.
    """
    digest = hashlib.sha1(f"v{SCREENSHOT_PIPELINE_VERSION}:".encode() + image_data).hexdigest()
    return f"screenshots/{digest}.webp"


def render_screenshot(image_data: bytes) -> tuple[bytes, bytes]:
    """Render a screenshot's full-size and thumbnail WebP files.

    Returns:
        ``(full, thumbnail)`` encoded bytes.

    Raises:
        ValueError: If the image cannot be decoded.
    """
    try:
        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)
        img.load()
    except Exception as e:
        raise ValueError(f"is not a readable image: {e}") from e
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    full = img.copy()
    full.thumbnail((SCREENSHOT_FULL_MAX_EDGE, SCREENSHOT_FULL_MAX_EDGE), Image.LANCZOS)

    thumb = img.copy()
    if thumb.height > SCREENSHOT_THUMBNAIL_HEIGHT:
        width = max(1, round(thumb.width * SCREENSHOT_THUMBNAIL_HEIGHT / thumb.height))
        thumb = thumb.resize((width, SCREENSHOT_THUMBNAIL_HEIGHT), Image.LANCZOS)

    return _webp(full), _webp(thumb)


def _webp(img: Image.Image) -> bytes:
    output = io.BytesIO()
    img.save(output, format="WEBP", quality=SCREENSHOT_QUALITY, method=6)
    return output.getvalue()


def save_static(data: bytes, rel_path: str) -> Path:
    """Write bytes to static storage at ``rel_path``."""
    return save_icon(data, rel_path)
