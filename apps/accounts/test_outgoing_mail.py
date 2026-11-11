"""Outgoing SMTP smoke tests (never connect to a real relay in CI)."""

from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class OutgoingMailTests(SimpleTestCase):
    def test_brevo_host_and_starttls_defaults(self):
        self.assertEqual(settings.EMAIL_HOST, "smtp-relay.brevo.com")
        self.assertEqual(settings.EMAIL_PORT, 587)
        self.assertTrue(settings.EMAIL_USE_TLS)
        self.assertFalse(settings.EMAIL_USE_SSL)
        self.assertGreater(settings.EMAIL_TIMEOUT, 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_test_email_uses_default_sovietgram_sender(self):
        call_command("sendtestemail", "recipient@example.net", verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(message.to, ["recipient@example.net"])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp-relay.brevo.com",
        EMAIL_PORT=587,
        EMAIL_USE_TLS=True,
        EMAIL_USE_SSL=False,
        EMAIL_HOST_USER="example-smtp-login",
        EMAIL_HOST_PASSWORD="fake-test-key",
        EMAIL_TIMEOUT=15,
    )
    @patch("django.core.mail.backends.smtp.smtplib.SMTP")
    def test_smtp_uses_starttls_and_key_without_network(self, smtp_class):
        delivered = mail.send_mail(
            "Sovietgram SMTP test",
            "A safe test email.",
            None,
            ["recipient@example.net"],
        )
        self.assertEqual(delivered, 1)
        smtp_class.assert_called_once()
        # Django 5.2 constructs smtplib.SMTP with positional host/port,
        # while newer implementations may use keyword arguments.
        args, kwargs = smtp_class.call_args
        host = kwargs.get("host", args[0] if len(args) >= 1 else None)
        port = kwargs.get("port", args[1] if len(args) >= 2 else None)
        self.assertEqual(host, "smtp-relay.brevo.com")
        self.assertEqual(port, 587)
        smtp_class.return_value.starttls.assert_called_once()
        smtp_class.return_value.login.assert_called_once_with(
            "example-smtp-login", "fake-test-key"
        )
        self.assertTrue(smtp_class.return_value.sendmail.called)
