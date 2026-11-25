"""Bounded image transformations; never change animated or original files."""
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .forms import MAX_IMAGE_DIMENSION, MAX_IMAGE_PIXELS

COMPRESS_EDGE = 1920
COMPRESS_THRESHOLD = 512 * 1024
STATIC_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


def compress_image_upload(uploaded):
    """Called only after normal upload validation and explicit user opt-in.

    Preserve file type, transparency and animation. Return the original when
    a transformation is not useful or decoding/encoding fails.
    """
    fmt = STATIC_FORMATS.get(Path(uploaded.name).suffix.lower())
    if not fmt:
        return uploaded
    try:
        uploaded.seek(0)
        with Image.open(uploaded) as image:
            width, height = image.size
            if (image.format != fmt or getattr(image, "is_animated", False)
                    or max(width, height) > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS):
                return uploaded
            if max(width, height) <= COMPRESS_EDGE and uploaded.size <= COMPRESS_THRESHOLD:
                return uploaded
            if fmt == "JPEG":
                image.draft("RGB", (COMPRESS_EDGE, COMPRESS_EDGE))
            oriented = ImageOps.exif_transpose(image)
            oriented.thumbnail((COMPRESS_EDGE, COMPRESS_EDGE), Image.Resampling.LANCZOS)
            if fmt == "JPEG":
                oriented = oriented.convert("RGB")
            elif oriented.mode not in {"RGB", "RGBA", "L", "LA"}:
                oriented = oriented.convert("RGBA" if "transparency" in oriented.info else "RGB")
            result = BytesIO()
            options = {"quality": 85, "optimize": True} if fmt == "JPEG" else (
                {"quality": 85, "method": 3} if fmt == "WEBP" else {"compress_level": 6}
            )
            oriented.save(result, format=fmt, **options)
            content = result.getvalue()
        if len(content) >= uploaded.size:
            return uploaded
        return SimpleUploadedFile(
            Path(uploaded.name).name, content, content_type=uploaded.content_type,
        )
    except (OSError, ValueError, EOFError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError):
        return uploaded
    finally:
        uploaded.seek(0)
