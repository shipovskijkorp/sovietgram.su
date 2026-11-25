from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User
from .forms import SovietgramAdminAuthenticationForm

admin.site.login_form = SovietgramAdminAuthenticationForm
admin.site.login_template = "accounts/login.html"


@admin.register(User)
class SovietgramUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Профиль Sovietgram", {"fields": ("bio", "avatar", "last_seen_at")}),
        ("Настройки Sovietgram", {"fields": ("theme", "enter_to_send")}),
    )
    readonly_fields = ("last_seen_at",)

    def save_model(self, request, obj, form, change):
        # An admin form opened before enrollment must not restore stale 2FA
        # credentials, replay counters, password hashes or security versions.
        if not change:
            return super().save_model(request, obj, form, change)
        writable = {field.name for field in obj._meta.concrete_fields if not field.primary_key and field.editable}
        fields = writable.intersection(form.changed_data) - {"password"}
        if fields:
            obj.save(update_fields=fields)
