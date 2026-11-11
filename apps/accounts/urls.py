from django.urls import path

from .views import (
    SovietgramLoginView,
    SovietgramLogoutView,
    SovietgramPasswordChangeView,
    add_account,
    profile,
    presence_heartbeat,
    verification_pending,
    verify_email,
    resend_verification,
    profile_avatar,
    public_profile,
    register,
    remove_avatar,
    settings_view,
    switch_account,
)

app_name = "accounts"

urlpatterns = [
    path("login/", SovietgramLoginView.as_view(), name="login"),
    path("register/", register, name="register"),
    path("verify-email/pending/", verification_pending, name="verification_pending"),
    path("verify-email/resend/", resend_verification, name="resend_verification"),
    path("verify-email/<str:token>/", verify_email, name="verify_email"),
    path("logout/", SovietgramLogoutView.as_view(), name="logout"),
    path("accounts/add/", add_account, name="add_account"),
    path("accounts/switch/<int:user_id>/", switch_account, name="switch_account"),
    path("profile/", profile, name="profile"),
    path("presence/heartbeat/", presence_heartbeat, name="presence_heartbeat"),
    path("settings/", settings_view, name="settings"),
    path("profile/avatar/remove/", remove_avatar, name="remove_avatar"),
    path(
        "profile/password/",
        SovietgramPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("u/<str:username>/avatar/", profile_avatar, name="profile_avatar"),
    path("u/<str:username>/", public_profile, name="public_profile"),
]
