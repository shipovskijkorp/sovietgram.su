from pathlib import Path

from django import forms
from PIL import Image, UnidentifiedImageError


MAX_ATTACHMENTS = 10
MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_TOTAL_SIZE = 100 * 1024 * 1024
MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp",
    ".mp4", ".webm", ".mov", ".m4v",
}
IMAGE_FORMATS = {
    ".png": {"PNG"},
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".webp": {"WEBP"},
}
MEDIA_CONTENT_TYPES = {
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".mp4": {"video/mp4"},
    ".webm": {"video/webm"},
    ".mov": {"video/quicktime"},
    ".m4v": {"video/x-m4v", "video/mp4"},
}
MAX_IMAGE_DIMENSION = 12_000
MAX_IMAGE_PIXELS = 40_000_000


def _validate_inline_image(uploaded, extension):
    original_position = uploaded.tell() if hasattr(uploaded, "tell") else 0
    try:
        with Image.open(uploaded) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                raise forms.ValidationError(
                    f"Сторона изображения не должна превышать {MAX_IMAGE_DIMENSION} пикселей."
                )
            if width * height > MAX_IMAGE_PIXELS:
                raise forms.ValidationError(
                    f"Изображение не должно превышать {MAX_IMAGE_PIXELS // 1_000_000} мегапикселей."
                )
            if image_format not in IMAGE_FORMATS.get(extension, set()):
                raise forms.ValidationError(
                    "Расширение изображения не соответствует его реальному формату."
                )
            image.verify()
    except forms.ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise forms.ValidationError("Файл не является корректным поддерживаемым изображением.")
    finally:
        if hasattr(uploaded, "seek"):
            uploaded.seek(original_position)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        result = single_file_clean(data, initial)
        return [result] if result else []


class MessageForm(forms.Form):
    MODE_MEDIA = "media"
    MODE_FILE = "file"

    text = forms.CharField(required=False, max_length=4096)
    reply_to = forms.IntegerField(required=False, min_value=1)
    attachment_mode = forms.ChoiceField(
        required=False,
        choices=((MODE_MEDIA, "Медиа"), (MODE_FILE, "Файл")),
        initial=MODE_MEDIA,
    )
    attachments = MultipleFileField(required=False)

    def clean_text(self):
        return self.cleaned_data.get("text", "").strip()

    def clean_attachment_mode(self):
        return self.cleaned_data.get("attachment_mode") or self.MODE_MEDIA

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        if len(files) > MAX_ATTACHMENTS:
            raise forms.ValidationError(
                f"За раз можно отправить не больше {MAX_ATTACHMENTS} файлов."
            )

        mode = self.cleaned_data.get("attachment_mode") or self.MODE_MEDIA
        total_size = 0
        for uploaded in files:
            extension = Path(uploaded.name).suffix.lower()
            content_type = (getattr(uploaded, "content_type", "") or "").lower()
            if extension == ".gif" or content_type == "image/gif":
                raise forms.ValidationError("GIF в Stalingram пока отключены.")
            if mode == self.MODE_MEDIA:
                if extension not in MEDIA_EXTENSIONS:
                    raise forms.ValidationError(
                        "В режиме медиа можно отправлять только изображения и видео."
                    )
                allowed_content_types = MEDIA_CONTENT_TYPES.get(extension, set())
                if content_type not in allowed_content_types:
                    raise forms.ValidationError(
                        "MIME-тип файла не соответствует его расширению."
                    )
                if extension in IMAGE_FORMATS:
                    _validate_inline_image(uploaded, extension)
            if uploaded.size > MAX_FILE_SIZE:
                raise forms.ValidationError("Один файл должен быть не больше 25 МБ.")
            total_size += uploaded.size

        if total_size > MAX_TOTAL_SIZE:
            raise forms.ValidationError(
                "Общий размер вложений должен быть не больше 100 МБ."
            )
        return files

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("text") and not cleaned.get("attachments"):
            raise forms.ValidationError("Введите сообщение или прикрепите файл.")
        return cleaned


class EditMessageForm(forms.Form):
    text = forms.CharField(required=False, max_length=4096)

    def clean_text(self):
        return self.cleaned_data.get("text", "").strip()
