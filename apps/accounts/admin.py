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
