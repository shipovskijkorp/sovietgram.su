"""CommonMark, GFM, chat extensions and untrusted-input regression tests."""
from django.core.cache import cache
from django.test import Client, TestCase, SimpleTestCase
from django.urls import reverse

from apps.accounts.models import User
from .markdown import render_message_markdown
from .models import Message
from .services import get_or_create_direct_chat


class MarkdownRenderTests(SimpleTestCase):
    def render(self, source, scope="test-message"):
        return render_message_markdown(source, scope)

    def test_commonmark_blocks_and_nested_inline_markup(self):
        html = self.render(
            "# Title\n\n## Subtitle\n\n**bold *italic*** and __bold__\n\n"
            "> quoted\n> > nested\n\n"
            "- first\n  - second\n\n3. third\n4. fourth\n\n"
            "---\n\n[Example](https://example.org)\n\n"
            "    indented code\n"
        )
        for tag in (
            "<h1>Title</h1>", "<h2>Subtitle</h2>", "<strong>bold <em>italic</em></strong>",
            "<strong>bold</strong>", "<blockquote>", "<ul>", '<ol start="3">',
            "<hr>", 'href="https://example.org"', "<pre><code>indented code",
        ):
            self.assertIn(tag, html)
        self.assertGreaterEqual(html.count("<blockquote>"), 2)
        self.assertGreaterEqual(html.count("<ul>"), 2)

    def test_gfm_tables_task_lists_and_strike(self):
        html = self.render(
            "| Name | Count |\n| :--- | ---: |\n| A | 2 |\n\n"
            "- [x] done\n- [ ] pending\n\n~~obsolete~~"
        )
        for tag in ("<table>", "<thead>", "<tbody>", "<th", "<td", "markdown-align-right",
                    '<input', 'type="checkbox"', "checked", "disabled"):
            self.assertIn(tag, html)
        self.assertTrue("<s>obsolete</s>" in html or "<del>obsolete</del>" in html)

    def test_code_highlighting_and_literal_content(self):
        html = self.render("~~~python\nif x < 2:\n    print('hi')\n~~~\n\n" + chr(96) + "@alice #tag" + chr(96))
        self.assertIn('<pre><code class="language-python">', html)
        self.assertIn("md-hl-", html)
        self.assertIn("&lt;", html)
        self.assertIn("<code>@alice #tag</code>", html)
        self.assertNotIn("data-user-profile", html)
        self.assertNotIn("data-message-hashtag", html)

    def test_footnotes_are_scoped_and_definition_lists_render(self):
        source = "Reference[^1]\n\n[^1]: footnote text\n\nTerm\n: Definition"
        first = self.render(source, "message-7")
        second = self.render(source, "message-8")
        self.assertIn('id="fn-message-7-', first)
        self.assertIn('href="#fn-message-7-', first)
        self.assertIn('id="fn-message-8-', second)
        self.assertIn("<dl>", first)
        self.assertIn("<dt>Term</dt>", first)

    def test_social_tokens_spoiler_and_underline(self):
        html = self.render("**@alice** #topic ++underlined++ ||secret|| https://example.org/#fragment alice@example.org")
        self.assertIn('data-user-profile=""', html)
        self.assertIn('data-message-hashtag="#topic"', html)
        self.assertIn("<u>underlined</u>", html)
        self.assertIn('class="message-spoiler"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertNotIn('data-message-hashtag="#fragment"', html)
        self.assertEqual(html.count("data-user-profile"), 1)

    def test_untrusted_html_and_unsafe_url_schemes_are_inert(self):
        html = self.render(
            '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n'
            '[bad](javascript:alert%281%29) [bad2](jav&#x61;script:alert%281%29) '
            '[bad3](data:text/html,x) ![bad](file:///etc/passwd)'
        )
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn('href="data:', html)
        self.assertNotIn('data-markdown-image-url="file:', html)
        self.assertIn("&lt;script&gt;", html)

    def test_external_images_require_explicit_load(self):
        html = self.render('![Example *image*](https://example.org/picture.png)')
        self.assertIn('data-markdown-image-url="https://example.org/picture.png"', html)
        self.assertIn('data-markdown-image-alt="Example image"', html)
        self.assertNotIn("<img", html)


class MarkdownIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "outsider@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)

    def test_send_history_edit_and_initial_page_share_renderer(self):
        source = "    indented code\n\n# Heading\n\n**hello**"
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": source}, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["message"]
        self.assertEqual(item["text"], source)
        self.assertEqual(Message.objects.get(pk=item["id"]).text, source)
        self.assertIn("<pre><code>indented code", item["markdown_html"])
        self.assertIn("<h1>Heading</h1>", item["markdown_html"])
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, "<h1>Heading</h1>", html=True)
        history = self.client.get(reverse("messenger:message_history", args=[self.chat.pk])).json()
        self.assertEqual(history["messages"][0]["markdown_html"], item["markdown_html"])
        updated = self.client.post(
            reverse("messenger:edit_message", args=[self.chat.pk, item["id"]]),
            {"text": "## Changed\n\n- Item"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertIn("<h2>Changed</h2>", updated.json()["message"]["markdown_html"])

    def test_preview_is_authenticated_bounded_csrf_protected_and_does_not_send(self):
        url = reverse("messenger:markdown_preview", args=[self.chat.pk])
        response = self.client.post(url, {"text": "**test**"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("<strong>test</strong>", response.json()["markdown_html"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(Message.objects.exists())
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"text": "x" * 4097}).status_code, 400)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.alice)
        self.assertEqual(csrf.post(url, {"text": "test"}).status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(url, {"text": "test"}).status_code, 404)
