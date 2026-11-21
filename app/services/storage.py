"""Category icon uploads: validate, resize to 128x128 WEBP with Pillow, and store in Supabase Storage.

Bucket `category-icons` is public-read. Objects live at `{user_id}/{uuid4().hex}.webp`
(random names, never the original filename). The user's own token is used, so the
bucket's per-user-folder policies apply.
"""

from __future__ import annotations

import logging
from io import BytesIO
from uuid import uuid4

from PIL import Image, ImageOps
from werkzeug.datastructures import FileStorage

from app.services.db import CAUGHT, friendly, user_client

logger = logging.getLogger(__name__)

BUCKET = "category-icons"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ICON_SIZE = 128
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 40_000_000
ICON_MESSAGE = "Upload a JPG, PNG or WEBP image under 2 MB."


class IconError(ValueError):
    """The uploaded file isn't an acceptable icon."""


def process_icon(file: FileStorage) -> bytes:
    """Validate an upload and return a 128x128 center-cropped WEBP as bytes."""
    data = file.stream.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise IconError(ICON_MESSAGE)

    try:
        img = Image.open(BytesIO(data))
        if img.format not in ALLOWED_FORMATS or img.width * img.height > MAX_PIXELS:
            raise IconError(ICON_MESSAGE)
        img.verify()

        img = Image.open(BytesIO(data))  # verify() leaves the image unusable: reopen
        img = ImageOps.exif_transpose(img)
        img.seek(0)  # first frame only (animated images)
        has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
        img = img.convert("RGBA" if has_alpha else "RGB")
        img = ImageOps.fit(img, (ICON_SIZE, ICON_SIZE), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

        out = BytesIO()
        img.save(out, format="WEBP", quality=85, method=4)
        return out.getvalue()
    except IconError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise IconError(ICON_MESSAGE) from None


def upload_icon(user_id: str, data: bytes) -> str:
    """Upload processed icon bytes and return the object path."""
    path = f"{user_id}/{uuid4().hex}.webp"
    try:
        user_client().storage.from_(BUCKET).upload(
            path, data, {"content-type": "image/webp", "cache-control": "31536000", "upsert": "false"}
        )
    except CAUGHT as error:
        raise friendly(error) from None
    return path


def remove_icon(path: str | None) -> None:
    """Best-effort delete of an icon object. Never raises."""
    if not path:
        return
    try:
        removed = user_client().storage.from_(BUCKET).remove([path])
        if not removed:
            logger.warning("Icon object was not removed (not found or not visible).")
    except Exception as error:  # noqa: BLE001 - cleanup must never break a request
        logger.warning("Could not remove icon object: %s", type(error).__name__)


def icon_url(path: str) -> str:
    return user_client().storage.from_(BUCKET).get_public_url(path)
