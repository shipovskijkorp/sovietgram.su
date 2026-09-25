from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .privacy import account_expired_for_inactivity


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate with either a username or an email address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        identifier = username or kwargs.get(UserModel.USERNAME_FIELD)
        if not identifier or password is None:
            return None

        user = UserModel._default_manager.filter(username__iexact=identifier).first()
        if user is None:
            user = UserModel._default_manager.filter(email__iexact=identifier).first()

        if user and user.check_password(password):
            if account_expired_for_inactivity(user):
                user.delete()
                return None
            if self.user_can_authenticate(user):
                return user
        return None
