from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import transaction

from .lifecycle import delete_user_account
from .privacy import account_expired_for_inactivity
from .two_factor import verify_factor_locked


class EmailOrUsernameBackend(ModelBackend):
    """Password plus TOTP/recovery code when required."""

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and not user.platform_suspended_at

    def authenticate(self, request, username=None, password=None, otp=None, **kwargs):
        UserModel = get_user_model()
        identifier = username or kwargs.get(UserModel.USERNAME_FIELD)
        if not identifier or password is None:
            return None
        user = UserModel._default_manager.filter(username__iexact=identifier).first()
        if user is None:
            user = UserModel._default_manager.filter(email__iexact=identifier).first()
        if user is None:
            UserModel().set_password(password)
            return None
        with transaction.atomic():
            user = UserModel._default_manager.select_for_update().filter(pk=user.pk).first()
            if user is None or not user.check_password(password):
                return None
            if account_expired_for_inactivity(user):
                delete_user_account(user)
                return None
            if not self.user_can_authenticate(user):
                return None
            if user.two_factor_enabled and not verify_factor_locked(user, otp):
                return None
            return user
