"""Personal labels never replace another user's public identity."""
import unicodedata

from .models import Contact


def contact_aliases(owner):
    return dict(Contact.objects.filter(owner=owner).exclude(alias="")
                .values_list("user_id", "alias"))


def contact_display_name(owner, user, aliases=None):
    if owner.pk == user.pk:
        return user.display_name
    if aliases is None:
        alias = Contact.objects.filter(owner=owner, user=user).values_list("alias", flat=True).first()
    else:
        alias = aliases.get(user.pk)
    return alias or user.display_name


def normalize_alias(value):
    if any(unicodedata.category(char) in {"Cc", "Cs", "Cf"} for char in value):
        raise ValueError("Имя не должно содержать управляющие символы.")
    alias = " ".join(value.split())
    if len(alias) > 100:
        raise ValueError("Имя должно содержать не более 100 символов.")
    return alias
