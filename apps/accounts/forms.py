from pathlib import Path

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class IdentifierAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Логин или почта",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "Логин или почта",
            }
        ),
    )
    password = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "placeholder": "Пароль"}
        ),
    )


class RegisterForm(UserCreationForm):
    username = forms.CharField(
        label="Логин",
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "placeholder": "Логин"}
        ),
    )
    email = forms.EmailField(
        label="Почта",
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "placeholder": "name@example.com"}
        ),
    )
    password1 = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "placeholder": "Пароль"}
        ),
    )
    password2 = forms.CharField(
        label="Повтор пароля",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "placeholder": "Повторите пароль"}
        ),
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Пользователь с таким логином уже существует.")
        if User.objects.filter(email__iexact=username).exists():
            raise forms.ValidationError("Этот логин совпадает с почтой другого пользователя.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Эта почта уже используется.")
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("Эта почта совпадает с логином другого пользователя.")
        return email


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        label="Имя",
        required=False,
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "given-name", "placeholder": "Имя"}
        ),
    )
    last_name = forms.CharField(
        label="Фамилия",
        required=False,
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "family-name", "placeholder": "Фамилия"}
        ),
    )
    username = forms.CharField(
        label="Имя пользователя",
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "placeholder": "username"}
        ),
    )
    bio = forms.CharField(
        label="О себе",
        required=False,
        max_length=160,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "maxlength": 160,
                "placeholder": "Несколько слов о себе",
            }
        ),
    )
    email = forms.EmailField(
        label="Почта",
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "placeholder": "name@example.com"}
        ),
    )
    avatar = forms.ImageField(
        label="Фотография профиля",
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
    )

    birthday = forms.DateField(
        label="День рождения",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "bio", "email", "avatar", "birthday")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        users = User.objects.exclude(pk=self.instance.pk)
        if users.filter(username__iexact=username).exists():
            raise forms.ValidationError("Пользователь с таким именем уже существует.")
        if users.filter(email__iexact=username).exists():
            raise forms.ValidationError("Это имя совпадает с почтой другого пользователя.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        users = User.objects.exclude(pk=self.instance.pk)
        if users.filter(email__iexact=email).exists():
            raise forms.ValidationError("Эта почта уже используется.")
        if users.filter(username__iexact=email).exists():
            raise forms.ValidationError("Эта почта совпадает с именем другого пользователя.")
        return email

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar

        # ModelForm returns the already stored FieldFile when the user did not
        # select a new file. Only fresh browser uploads have to be revalidated.
        if not isinstance(avatar, UploadedFile):
            return avatar

        if getattr(avatar, "size", 0) > 5 * 1024 * 1024:
            raise forms.ValidationError("Фотография должна быть не больше 5 МБ.")

        content_type = (getattr(avatar, "content_type", "") or "").lower()
        extension = Path(avatar.name).suffix.lower()
        allowed_types = {
            ".jpg": ("image/jpeg", "JPEG"),
            ".jpeg": ("image/jpeg", "JPEG"),
            ".png": ("image/png", "PNG"),
            ".webp": ("image/webp", "WEBP"),
        }
        expected = allowed_types.get(extension)
        if expected is None or content_type != expected[0]:
            raise forms.ValidationError("Поддерживаются только PNG, JPEG и WebP.")

        image = getattr(avatar, "image", None)
        if image is None:
            raise forms.ValidationError("Не удалось проверить изображение.")
        width, height = image.size
        if width > 4096 or height > 4096 or width * height > 16_000_000:
            raise forms.ValidationError(
                "Фотография слишком большая: максимум 4096×4096 и 16 мегапикселей."
            )
        if (image.format or "").upper() != expected[1]:
            raise forms.ValidationError(
                "Расширение фотографии не соответствует её реальному формату."
            )
        return avatar


class UserSettingsForm(forms.ModelForm):
    theme = forms.ChoiceField(
        label="Тема оформления",
        choices=User.Theme.choices,
        widget=forms.RadioSelect,
    )
    enter_to_send = forms.BooleanField(
        label="Отправлять сообщения по Enter",
        required=False,
    )

    class Meta:
        model = User
        fields = ("theme", "enter_to_send")


class OverlayProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=False, max_length=150)
    username = forms.CharField(max_length=150)
    bio = forms.CharField(required=False, max_length=160)
    avatar = forms.ImageField(required=False)
    birthday = forms.DateField(required=False)
    personal_channel = forms.ModelChoiceField(queryset=None, required=False)

    class Meta:
        model = User
        fields = (
            "first_name",
            "username",
            "bio",
            "avatar",
            "birthday",
            "personal_channel",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.messenger.models import Chat, ChatParticipant

        if self.instance and self.instance.pk:
            channel_ids = ChatParticipant.objects.filter(
                user=self.instance,
                role=ChatParticipant.Role.OWNER,
                chat__type=Chat.Type.CHANNEL,
            ).values_list("chat_id", flat=True)
            self.fields["personal_channel"].queryset = Chat.objects.filter(
                pk__in=channel_ids,
                type=Chat.Type.CHANNEL,
            ).order_by("title", "pk")
        else:
            self.fields["personal_channel"].queryset = Chat.objects.none()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        users = User.objects.exclude(pk=self.instance.pk)
        if users.filter(username__iexact=username).exists():
            raise forms.ValidationError("Пользователь с таким именем уже существует.")
        if users.filter(email__iexact=username).exists():
            raise forms.ValidationError("Это имя совпадает с почтой другого пользователя.")
        return username

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar

        # ModelForm returns the already stored FieldFile when the user did not
        # select a new file. Only fresh browser uploads have to be revalidated.
        if not isinstance(avatar, UploadedFile):
            return avatar

        if getattr(avatar, "size", 0) > 5 * 1024 * 1024:
            raise forms.ValidationError("Фотография должна быть не больше 5 МБ.")

        content_type = (getattr(avatar, "content_type", "") or "").lower()
        extension = Path(avatar.name).suffix.lower()
        allowed_types = {
            ".jpg": ("image/jpeg", "JPEG"),
            ".jpeg": ("image/jpeg", "JPEG"),
            ".png": ("image/png", "PNG"),
            ".webp": ("image/webp", "WEBP"),
        }
        expected = allowed_types.get(extension)
        if expected is None or content_type != expected[0]:
            raise forms.ValidationError("Поддерживаются только PNG, JPEG и WebP.")

        image = getattr(avatar, "image", None)
        if image is None:
            raise forms.ValidationError("Не удалось проверить изображение.")
        width, height = image.size
        if width > 4096 or height > 4096 or width * height > 16_000_000:
            raise forms.ValidationError("Фотография слишком большая.")
        if (image.format or "").upper() != expected[1]:
            raise forms.ValidationError("Расширение фотографии не соответствует формату.")
        return avatar
