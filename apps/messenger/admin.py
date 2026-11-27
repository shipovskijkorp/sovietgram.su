from django.contrib import admin

from .models import (
    Chat,
    ChatParticipant,
    Contact,
    Message,
    MessageAttachment,
    PinnedMessage,
    SavedGif,
)


class ChatParticipantInline(admin.TabularInline):
    model = ChatParticipant
    extra = 0


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ("id", "direct_key", "updated_at")
    search_fields = ("direct_key",)
    inlines = (ChatParticipantInline,)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("owner", "user", "created_at")
    search_fields = ("owner__username", "user__username")


class MessageAttachmentInline(admin.TabularInline):
    model = MessageAttachment
    extra = 0


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "chat", "sender", "is_deleted", "edited_at", "created_at")
    list_filter = ("is_deleted",)
    search_fields = ("sender__username", "text", "forwarded_from_name")
    inlines = (MessageAttachmentInline,)


@admin.register(PinnedMessage)
class PinnedMessageAdmin(admin.ModelAdmin):
    list_display = ("message", "chat", "pinned_by", "pinned_at")
    search_fields = ("message__text", "pinned_by__username")

@admin.register(SavedGif)
class SavedGifAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "name", "size", "published_at", "created_at")
    list_filter = ("can_publish", "published_at")
    search_fields = ("name", "tags", "owner__username")
    fields = ("owner", "name", "tags", "size", "can_publish", "published_at", "created_at")
    readonly_fields = fields
    actions = ("unpublish",)

    def has_add_permission(self, request):
        return False

    @admin.action(description="Убрать выбранные GIF из публичного каталога")
    def unpublish(self, request, queryset):
        queryset.update(published_at=None)
