"""TOTP and one-time recovery codes. Caller locks the user row."""
import base64
import hashlib
import re
import secrets
from datetime import timedelta

import pyotp
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

ATTEMPTS = 5
WINDOW = timedelta(minutes=5)
PERIOD = 30


def _cipher():
    return MultiFernet([
        Fernet(base64.urlsafe_b64encode(salted_hmac(
            "sovietgram.totp.encryption.v1", "fernet",
            secret=key, algorithm="sha256",
        ).digest()))
        for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]
    ])


def encrypt_secret(secret):
    return _cipher().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(token):
    return _cipher().decrypt(token.encode("ascii")).decode("ascii")


def matching_step(secret, code, now=None, last_step=-1):
    code = str(code or "").strip()
    if not re.fullmatch(r"[0-9]{6}", code):
        return None
    step = int((now or timezone.now()).timestamp()) // PERIOD
    totp = pyotp.TOTP(secret, interval=PERIOD)
    matches = [
        candidate for candidate in (step - 1, step, step + 1)
        if candidate > last_step and constant_time_compare(totp.at(candidate * PERIOD), code)
    ]
    return max(matches) if matches else None


def recovery_hash(code):
    normalized = re.sub(r"[\s-]+", "", str(code or "")).upper()
    if not re.fullmatch(r"[0-9A-F]{20}", normalized):
        return None
    return hashlib.sha256(("sovietgram.recovery.v1:" + normalized).encode("ascii")).hexdigest()


def new_recovery_codes():
    codes = []
    while len(codes) < 10:
        raw = secrets.token_hex(10).upper()
        code = "-".join(raw[i:i+5] for i in range(0, 20, 5))
        if code not in codes:
            codes.append(code)
    return codes, [recovery_hash(code) for code in codes]


def verify_factor_locked(user, code, *, now=None):
    """Consume a code under a User row lock; commit failures too."""
    if not user.two_factor_enabled:
        return True
    if not code or not str(code).strip():
        return False
    now = now or timezone.now()
    if not user.two_factor_failure_window or now - user.two_factor_failure_window >= WINDOW:
        user.two_factor_failure_window = now
        user.two_factor_failures = 0
    if user.two_factor_failures >= ATTEMPTS:
        return False
    digest = recovery_hash(code)
    hashes = list(user.two_factor_recovery_hashes or [])
    index = next((i for i, stored in enumerate(hashes) if digest and constant_time_compare(stored, digest)), None)
    step = None
    if index is None:
        try:
            step = matching_step(decrypt_secret(user.two_factor_secret), code, now, user.two_factor_last_step)
        except (InvalidToken, ValueError, TypeError):
            step = None
    if index is None and step is None:
        user.two_factor_failures += 1
        user.save(update_fields=["two_factor_failures", "two_factor_failure_window"])
        return False
    if index is not None:
        hashes.pop(index)
        user.two_factor_recovery_hashes = hashes
    else:
        user.two_factor_last_step = step
    user.two_factor_failures = 0
    user.two_factor_failure_window = None
    user.save(update_fields=["two_factor_last_step", "two_factor_recovery_hashes",
                             "two_factor_failures", "two_factor_failure_window"])
    return True
