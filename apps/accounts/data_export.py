"""Password/2FA-confirmed account portability without exporting server secrets."""
import json
import tempfile
import zipfile

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import FileResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from apps.messenger.models import (
    ChannelComment, ChannelPostView, Chat, ChatFolder, ChatMemberModeration,
    ChatParticipant, Contact, Message, MessageAttachment, MessageHiddenForUser,
    MessageReaction, ScheduledAttachment, ScheduledMessage, Sticker, StickerPack,
)
from .account_security import FactorConfirmedForm, _limited, _page
from .models import User, UserBlock
from .two_factor import verify_factor_locked

# Bound temporary disk and CPU use on a small VPS. Never silently truncate.
MAX_BYTES = 256 * 1024 * 1024
CHUNK = 64 * 1024


class ExportError(ValueError):
    pass


class AccountExportForm(forms.Form, FactorConfirmedForm):
    account_id = forms.IntegerField(widget=forms.HiddenInput())
    password = forms.CharField(
        label="Текущий пароль", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    otp = forms.CharField(
        label="Код двухфакторной защиты", required=False, max_length=64,
        widget=forms.PasswordInput(attrs={"autocomplete": "one-time-code"}),
    )
    include_files = forms.BooleanField(
        label="Включить файлы, аватар и изображения стикеров", required=False,
        help_text="Без этой отметки экспортируются текст и метаданные файлов.",
    )


def exportable_messages(user, now):
    # Membership and visibility are checked in the same SQL statement.
    # No protected chat, hidden/deleted/expired message or banned community.
    membership = ChatParticipant.objects.filter(
        chat_id=OuterRef("chat_id"), user=user, is_hidden=False,
        cleared_before_message_id__lt=OuterRef("pk"),
    ).filter(
        Q(chat__type=Chat.Type.PRIVATE) |
        Q(chat__history_visible_to_new_members=True) |
        Q(can_see_pre_join_history=True) |
        Q(joined_at__lte=OuterRef("created_at"))
    )
    bans = ChatMemberModeration.objects.filter(
        user=user, banned=True, chat_id=OuterRef("chat_id"),
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    hidden = MessageHiddenForUser.objects.filter(user=user, message_id=OuterRef("pk"))
    return Message.objects.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        is_deleted=False, chat__protect_content=False,
    ).filter(Exists(membership)).exclude(Exists(bans)).exclude(Exists(hidden))


def rows(query, *fields):
    return query.order_by("pk").values(*fields).iterator(chunk_size=200)


def safe_special(row):
    # Never reveal another account's poll vote or task-completion identity.
    data = row.pop("special_data", None)
    kind = row.get("special_type")
    if not isinstance(data, dict):
        return row
    if kind == Message.SpecialType.POLL:
        result = {key: data[key] for key in (
            "question", "anonymous", "multiple", "quiz", "correct_option",
            "explanation", "closed",
        ) if key in data}
        result["options"] = [{"text": item.get("text", "")} for item in data.get("options", [])
                             if isinstance(item, dict)]
    elif kind == Message.SpecialType.TODO:
        result = {key: data[key] for key in ("title", "allow_others_add", "allow_others_mark") if key in data}
        # Current task text may have been added by another participant.
        # Export only the user's original message text/title in this case.
    elif kind == Message.SpecialType.ARTICLE:
        result = {key: data[key] for key in ("title", "subtitle", "body", "format") if key in data}
    elif kind == Message.SpecialType.LOCATION:
        result = {key: data[key] for key in ("label", "latitude", "longitude") if key in data}
    else:
        result = {}
    row["special"] = result
    return row


class ArchiveWriter:
    def __init__(self, bundle):
        self.bundle = bundle
        self.bytes = 0
        self.counts = {}
        self.missing = 0

    def write(self, stream, chunk):
        self.bytes += len(chunk)
        if self.bytes > MAX_BYTES:
            raise ExportError("Экспорт превышает 256 МиБ. Попробуйте отключить файлы или экспортировать чаты отдельно.")
        stream.write(chunk)

    def json(self, path, data):
        payload = json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2).encode("utf-8")
        with self.bundle.open(path, "w") as stream:
            self.write(stream, payload)

    def jsonl(self, path, data):
        count = 0
        with self.bundle.open(path, "w") as stream:
            for row in data:
                payload = json.dumps(row, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":"))
                self.write(stream, (payload + "\n").encode("utf-8"))
                count += 1
        self.counts[path] = count

    def file(self, path, field):
        if not field:
            return False
        try:
            source = field.storage.open(field.name, "rb")
        except (OSError, ValueError):
            self.missing += 1
            return False
        with source, self.bundle.open(path, "w") as target:
            while chunk := source.read(CHUNK):
                self.write(target, chunk)
        return True

    def binary(self, path, data):
        with self.bundle.open(path, "w") as stream:
            self.write(stream, bytes(data))


def build_export(user, include_files=False):
    now = timezone.now()
    visible = exportable_messages(user, now)
    own = visible.filter(sender=user)
    memberships = ChatParticipant.objects.filter(user=user, is_hidden=False)
    archive = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as bundle:
            writer = ArchiveWriter(bundle)
            avatar_path = None
            if include_files and user.avatar and writer.file("media/avatar.bin", user.avatar):
                avatar_path = "media/avatar.bin"
            # Explicit allowlist, never dump User.__dict__ or credential fields.
            profile = {field: getattr(user, field) for field in (
                "id", "username", "email", "email_verified_at", "first_name", "last_name",
                "bio", "birthday", "date_joined", "last_seen_at", "personal_channel_id",
                "theme", "enter_to_send", "media_preload", "notification_preferences", "keep_archived_chats", "keep_folder_chats_archived",
                "archive_unknown_chats", "archive_in_main_menu", "privacy_settings",
                "default_auto_delete_seconds", "delete_after_inactive_days", "two_factor_enabled",
            )}
            profile["avatar_archive_path"] = avatar_path
            writer.json("profile.json", profile)
            writer.jsonl("security_events.jsonl", rows(user.security_events.all(), "kind", "device", "created_at"))
            writer.jsonl("contacts.jsonl", rows(Contact.objects.filter(owner=user),
                "user_id", "user__username", "alias", "created_at"))
            writer.jsonl("blocked.jsonl", rows(UserBlock.objects.filter(blocker=user),
                "blocked_id", "blocked__username", "created_at"))
            writer.jsonl("folders.jsonl", rows(ChatFolder.objects.filter(owner=user),
                "id", "name", "position", "categories", "included_chat_ids", "excluded_chat_ids",
                "pinned_chat_ids", "exclude_muted", "exclude_read", "exclude_archived"))
            writer.jsonl("memberships.jsonl", rows(memberships,
                "chat_id", "chat__type", "chat__title", "chat__username", "role", "joined_at",
                "read_through_id", "is_pinned", "pin_order", "is_archived", "is_muted",
                "muted_until", "marked_unread_at"))
            writer.jsonl("drafts.jsonl", rows(memberships.filter(chat__protect_content=False)
                .filter(Q(draft_text__gt="") | Q(draft_reply_id__isnull=False)),
                "chat_id", "draft_text", "draft_reply_id", "draft_updated_at"))
            writer.jsonl("messages.jsonl", (safe_special(row) for row in rows(own,
                "id", "chat_id", "text", "special_type", "special_data", "silent", "created_at", "edited_at")))
            writer.jsonl("reactions.jsonl", rows(MessageReaction.objects.filter(user=user, message__in=visible),
                "message_id", "emoji", "created_at"))
            writer.jsonl("channel_comments.jsonl", rows(ChannelComment.objects.filter(
                author=user, post__in=visible, is_deleted=False),
                "id", "post_id", "text", "created_at", "edited_at"))
            writer.jsonl("channel_views.jsonl", rows(ChannelPostView.objects.filter(user=user, post__in=visible),
                "post_id", "viewed_at"))
            scheduled = ScheduledMessage.objects.filter(
                sender=user, chat_id__in=memberships.filter(chat__protect_content=False).values("chat_id"),
                status__in=[ScheduledMessage.Status.PENDING, ScheduledMessage.Status.FAILED],
            )
            if include_files:
                for item in scheduled.filter(sticker_source_id__isnull=False).iterator(chunk_size=20):
                    if item.sticker_image:
                        writer.binary(f"scheduled/sticker-{item.pk}.webp", item.sticker_image)

            def scheduled_rows():
                for row in rows(scheduled, "id", "chat_id", "text", "special_type", "special_data",
                                "silent", "scheduled_for", "status", "sticker_source_id"):
                    path = f"scheduled/sticker-{row['id']}.webp"
                    row["attachment_type"] = "sticker" if row.pop("sticker_source_id") is not None else ""
                    row["archive_path"] = path if path in bundle.NameToInfo else None
                    yield row

            writer.jsonl("scheduled.jsonl", scheduled_rows())
            queued_files = ScheduledAttachment.objects.filter(scheduled__in=scheduled).order_by("pk")
            if include_files:
                for attachment in queued_files.iterator(chunk_size=20):
                    writer.file(f"scheduled/attachment-{attachment.pk}.bin", attachment.file)

            def queued_attachment_rows():
                for row in rows(queued_files, "id", "scheduled_id", "kind", "original_name", "mime_type",
                                "size", "duration_ms", "is_spoiler"):
                    path = f"scheduled/attachment-{row['id']}.bin"
                    row["archive_path"] = path if path in bundle.NameToInfo else None
                    yield row

            writer.jsonl("scheduled_attachments.jsonl", queued_attachment_rows())
            archived_photos = user.avatar_history.all()
            if include_files:
                for photo in archived_photos:
                    writer.file(f"avatars/history-{photo.pk}.bin", photo.image)

            def avatar_rows():
                for row in rows(archived_photos, "id", "archived_at"):
                    path = f"avatars/history-{row['id']}.bin"
                    row["archive_path"] = path if path in bundle.NameToInfo else None
                    yield row

            writer.jsonl("avatar_history.jsonl", avatar_rows())
            writer.jsonl("sticker_packs.jsonl", rows(StickerPack.objects.filter(owner=user),
                "id", "name", "created_at", "catalog_published_at", "auto_update_at", "auto_update_error"))

            def sticker_rows():
                query = Sticker.objects.filter(pack__owner=user).order_by("pk")
                if not include_files:
                    query = query.defer("image")
                for sticker in query.iterator(chunk_size=50):
                    path = None
                    if include_files:
                        path = f"stickers/{sticker.pk}.webp"
                        writer.binary(path, sticker.image)
                    yield {"id": sticker.pk, "pack_id": sticker.pack_id, "emoji": sticker.emoji,
                           "is_favorite": sticker.is_favorite, "created_at": sticker.created_at,
                           "last_used_at": sticker.last_used_at, "archive_path": path}

            # ZipFile cannot open two writable members at the same time. Copy
            # optional binaries first, then stream the metadata in a separate pass.
            def stickers_metadata():
                query = Sticker.objects.filter(pack__owner=user).order_by("pk").defer("image")
                for sticker in query.iterator(chunk_size=100):
                    yield {"id": sticker.pk, "pack_id": sticker.pack_id, "emoji": sticker.emoji,
                           "is_favorite": sticker.is_favorite, "created_at": sticker.created_at,
                           "last_used_at": sticker.last_used_at,
                           "archive_path": f"stickers/{sticker.pk}.webp" if include_files and
                               f"stickers/{sticker.pk}.webp" in bundle.NameToInfo else None}

            if include_files:
                for _ in sticker_rows():
                    pass
            writer.jsonl("stickers.jsonl", stickers_metadata())

            attachments = MessageAttachment.objects.filter(message__in=own).order_by("pk")
            if include_files:
                for attachment in attachments.iterator(chunk_size=100):
                    writer.file(f"media/attachment-{attachment.pk}.bin", attachment.file)

            def attachment_rows():
                for row in rows(attachments, "id", "message_id", "kind", "original_name", "mime_type",
                                "size", "duration_ms", "is_spoiler", "created_at"):
                    path = f"media/attachment-{row['id']}.bin"
                    row["archive_path"] = path if include_files and path in bundle.NameToInfo else None
                    yield row

            writer.jsonl("attachments.jsonl", attachment_rows())
            writer.json("manifest.json", {
                "format": "sovietgram-account-export-v1", "created_at": now,
                "includes_files": include_files, "counts": writer.counts,
                "missing_files": writer.missing, "scope": [
                    "Account settings, contacts, folders, accessible own messages and personal activity.",
                    "No other users' messages, protected chats' content, hidden/deleted/expired messages, credentials or sessions.",
                    "Binary attachment names are mapped in attachments.jsonl; .bin files may be renamed to original_name.",
                    "This is a portability export, not a database backup or importable account.",
                ],
            })
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise


@login_required
@never_cache
@ensure_csrf_cookie
@sensitive_post_parameters("password", "otp")
@require_http_methods(["GET", "POST"])
def account_export(request):
    form = AccountExportForm(request.POST if request.method == "POST" else None,
                             initial={"account_id": request.user.pk})
    form.configure_factor(request.user)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["account_id"] != request.user.pk:
            form.add_error(None, "Аккаунт изменился. Откройте настройки заново.")
        elif _limited("account-export", request.user.pk, 3, window=600):
            form.add_error(None, "Слишком много попыток. Повторите через десять минут.")
        else:
            authorized = None
            with transaction.atomic():
                user = User.objects.select_for_update().filter(pk=request.user.pk, is_active=True).first()
                if user is None or not user.check_password(form.cleaned_data["password"]):
                    form.add_error("password", "Неверный пароль.")
                elif not verify_factor_locked(user, form.cleaned_data.get("otp")):
                    form.add_error("otp", "Нужен действительный код двухфакторной защиты.")
                else:
                    authorized = user
            if authorized is not None:
                try:
                    archive = build_export(authorized, form.cleaned_data["include_files"])
                except ExportError as error:
                    form.add_error(None, str(error))
                except (OSError, ValueError):
                    form.add_error(None, "Не удалось сформировать архив. Попробуйте позже.")
                else:
                    response = FileResponse(archive, as_attachment=True, filename=f"sovietgram-account-{authorized.pk}.zip")
                    response["Content-Type"] = "application/zip"
                    response["Referrer-Policy"] = "same-origin"
                    response["X-Content-Type-Options"] = "nosniff"
                    return response
    return _page(request, title="Экспорт данных", heading="Экспорт данных аккаунта",
        description=("Скачайте ZIP с профилем, настройками, контактами, папками, вашими доступными "
                     "сообщениями, реакциями, комментариями, отложенными сообщениями и стикерами. "
                     "Чужие сообщения и содержимое защищённых, скрытых или удалённых переписок не включаются. "
                     "Историю отдельного незащищённого чата можно скачать из его меню. "
                     "Лимит исходных данных — 256 МиБ. Архив не зашифрован: храните его в безопасном месте."),
        form=form, submit="Скачать ZIP",
        back=reverse("messenger:home") + "?settings=main", back_label="К настройкам")
