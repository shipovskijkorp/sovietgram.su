"""Bounded image transformations; never change animated or original files."""
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import caches
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
            # Expand palette/tRNS transparency before resampling. Otherwise
            # palette PNGs can acquire jagged edges or lose their alpha.
            if fmt != "JPEG" and ("transparency" in oriented.info or "A" in oriented.getbands()):
                oriented = oriented.convert("RGBA")
                oriented.info.pop("transparency", None)
            elif fmt != "JPEG" and oriented.mode not in {"RGB", "L"}:
                oriented = oriented.convert("RGB")
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



THUMBNAIL_EDGE = 384
THUMBNAIL_VERSION = "v1"
THUMBNAIL_CACHE_BYTES = 256 * 1024
THUMBNAIL_CACHE_SECONDS = 900


def cached_thumbnail(attachment, version):
    """Call only after access and source existence checks.

    Attachments use immutable storage names. The supplied version includes
    the attachment identity, stored filename, size and transformation version.
    A cache entry is never an authorization decision.
    """
    cache = caches["thumbnails"]
    key = "thumb:" + version
    content = cache.get(key)
    if isinstance(content, bytes):
        return content
    with attachment.file.open("rb") as source:
        content = make_thumbnail(source)
    if len(content) <= THUMBNAIL_CACHE_BYTES:
        cache.set(key, content, timeout=THUMBNAIL_CACHE_SECONDS)
    return content



def make_thumbnail(source):
    """A bounded static preview, not a replacement for the stored media."""
    with Image.open(source) as image:
        width, height = image.size
        if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
            raise ValueError("Unsupported image")
        if max(width, height) > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
            raise ValueError("Image too large")
        # Preview just the first frame of animated media. The viewer uses
        # the untouched full file and still plays the animation.
        if image.format == "JPEG":
            image.draft("RGB", (THUMBNAIL_EDGE, THUMBNAIL_EDGE))
        oriented = ImageOps.exif_transpose(image)
        alpha = "A" in oriented.getbands() or "transparency" in oriented.info
        oriented = oriented.convert("RGBA" if alpha else "RGB")
        oriented.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)
        # Paste into a fresh image to avoid retaining EXIF, ICC or arbitrary
        # metadata inherited from the uploaded image.
        clean = Image.new(oriented.mode, oriented.size)
        clean.paste(oriented)
        output = BytesIO()
        clean.save(output, format="WEBP", quality=80, method=2)
        return output.getvalue()
