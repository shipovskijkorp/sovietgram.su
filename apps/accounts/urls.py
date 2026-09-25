from django.urls import path

from .views import (
    SovietgramLoginView,
    SovietgramLogoutView,
    SovietgramPasswordChangeView,
    add_account,
    profile,
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
    path("logout/", SovietgramLogoutView.as_view(), name="logout"),
    path("accounts/add/", add_account, name="add_account"),
    path("accounts/switch/<int:user_id>/", switch_account, name="switch_account"),
    path("profile/", profile, name="profile"),
    path("settings/", settings_view, name="settings"),
    path("profile/avatar/remove/", remove_avatar, name="remove_avatar"),
    path(
        "profile/password/",
        SovietgramPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("u/<str:username>/", public_profile, name="public_profile"),
]
