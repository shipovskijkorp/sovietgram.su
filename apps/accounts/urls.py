from django.urls import path

from . import account_security, avatar_history, data_export, notification_preferences, security_events, storage_views, two_factor_views, share_qr

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
    path("password/reset/", account_security.password_reset_request, name="password_reset"),
    path("password/reset/sent/", account_security.password_reset_sent, name="password_reset_sent"),
    path("password/reset/confirm/<str:token>/", account_security.password_reset_confirm, name="password_reset_confirm"),
    path("profile/delete/", account_security.delete_account, name="delete_account"),
    path("profile/email/", account_security.email_change_request, name="email_change"),
    path("profile/two-factor/", two_factor_views.two_factor_settings, name="two_factor"),
    path("profile/email/confirm/<str:token>/", account_security.email_change_confirm, name="email_change_confirm"),
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
    path("settings/export/", data_export.account_export, name="account_export"),
    path("settings/storage/", storage_views.storage_settings, name="storage"),
    path("settings/notification-preferences/", notification_preferences.notification_preferences, name="notification_preferences"),
    path("settings/security-history/", security_events.security_history, name="security_history"),
    path("profile/avatar/remove/", remove_avatar, name="remove_avatar"),
    path("profile/avatar/history/", avatar_history.history, name="avatar_history"),
    path("profile/avatar/history/<int:photo_id>/image/", avatar_history.image, name="avatar_history_image"),
    path("profile/avatar/history/<int:photo_id>/action/", avatar_history.action, name="avatar_history_action"),
    path(
        "profile/password/",
        SovietgramPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("u/<str:username>/avatar/", profile_avatar, name="profile_avatar"),
    path("u/<str:username>/qr/", share_qr.profile_qr, name="profile_qr"),
    path("u/<str:username>/", public_profile, name="public_profile"),
]
