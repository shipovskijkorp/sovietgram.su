from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.utils.datastructures import MultiValueDict

from config.context_processors import upload_limits
from .forms import MessageForm


MIB = 1024 * 1024


@override_settings(SOVIETGRAM_MAX_FILE_MIB=2, SOVIETGRAM_MAX_TOTAL_MIB=3)
class UploadLimitTests(SimpleTestCase):
    def form(self, *sizes):
        files = [SimpleUploadedFile(f"file-{i}.bin", b"x" * size)
                 for i, size in enumerate(sizes)]
        return MessageForm({"attachment_mode": "file"},
                           MultiValueDict({"attachments": files}))

    def test_limits_are_shared_with_template(self):
        self.assertEqual(upload_limits(None), {"upload_file_mib": 2, "upload_total_mib": 3})
        form = self.form(2 * MIB, MIB)
        self.assertTrue(form.is_valid(), form.errors)

    def test_per_file_limit(self):
        form = self.form(2 * MIB + 1)
        self.assertFalse(form.is_valid())
        self.assertIn("2 МБ", str(form.errors["attachments"]))

    def test_total_limit(self):
        form = self.form(2 * MIB, MIB + 1)
        self.assertFalse(form.is_valid())
        self.assertIn("3 МБ", str(form.errors["attachments"]))

    def test_count_still_limited(self):
        form = self.form(*([1] * 11))
        self.assertFalse(form.is_valid())
        self.assertIn("10", str(form.errors["attachments"]))
