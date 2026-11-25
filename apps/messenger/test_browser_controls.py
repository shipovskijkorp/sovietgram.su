"""Real-browser interaction tests against Django's isolated live test server.

Opt-in locally: install playwright and Chromium, then set
SOVIETGRAM_BROWSER_TESTS=1. CI runs these in a separate job.
"""
import os
from unittest import skipUnless
from unittest.mock import patch
from tempfile import TemporaryDirectory
from io import BytesIO

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, MessageAttachment, MessageReaction
from .services import get_or_create_direct_chat


@skipUnless(os.environ.get("SOVIETGRAM_BROWSER_TESTS") == "1", "Browser tests are opt-in")
@override_settings(
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    SOVIETGRAM_REQUIRE_EMAIL_VERIFICATION=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class BrowserControlsTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from playwright.sync_api import expect, sync_playwright

        # Sync Playwright uses an asyncio loop in a greenlet on this thread.
        # Allow Django's synchronous test fixtures/flush only during this isolated
        # live-server test class; the production process is never affected.
        cls.enterClassContext(patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"}))
        cls.expect = staticmethod(expect)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user("owner", "owner@example.net", "Password-1945!")
        self.peer = User.objects.create_user("peer", "peer@example.net", "Password-1945!")
        self.other = User.objects.create_user("other", "other@example.net", "Password-1945!")
        self.direct = get_or_create_direct_chat(self.owner, self.peer)
        self.group = Chat.objects.create(type=Chat.Type.GROUP, title="UI test group")
        self.channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="UI test channel")
        for community in (self.group, self.channel):
            ChatParticipant.objects.create(chat=community, user=self.owner, role="owner")
            ChatParticipant.objects.create(chat=community, user=self.peer, role="member")
        self.message = Message.objects.create(chat=self.group, sender=self.owner, text="Browser control test")
        self.direct_message = Message.objects.create(chat=self.direct, sender=self.owner, text="Browser direct test")
        self.context = self.browser.new_context(
            viewport={"width": 1360, "height": 900}, locale="ru-RU", timezone_id="Europe/Moscow",
        )
        self.addCleanup(self.context.close)
        self.client.force_login(self.owner)
        self.context.add_cookies([
            {"name":settings.SESSION_COOKIE_NAME, "value":self.client.cookies[settings.SESSION_COOKIE_NAME].value,
             "url":self.live_server_url},
            {"name":"sovietgram_timezone", "value":"Europe/Moscow", "url":self.live_server_url},
        ])
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("response", lambda response: print(f"Browser HTTP {response.status}: {response.url}", flush=True)
                     if response.status >= 500 else None)
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.addCleanup(lambda: self.assertEqual(self.errors, [], "Uncaught browser errors"))

    def go(self, chat=None, query=""):
        path = reverse("messenger:chat",args=[chat.pk]) if chat else reverse("messenger:home")
        self.page.goto(self.live_server_url + path + query, wait_until="domcontentloaded")
        self.expect(self.page.locator("#profileMenuButton")).to_be_visible()

    def click(self, selector):
        self.page.locator(selector).click()

    def visible(self, selector):
        self.expect(self.page.locator(selector)).to_be_visible()

    def hidden(self, selector):
        self.expect(self.page.locator(selector)).to_be_hidden()

    def menu(self, selector):
        self.click("#chatMenuButton")
        self.visible("#chatMenu")
        self.click("#chatMenu " + selector)

    def manage(self):
        self.menu("[data-open-community-settings]")
        self.visible("#communitySettings")
        self.visible("#communitySettingsOverview")
        self.hidden("#communitySettingsLoadState")
        self.hidden("#chatMenu")

    def test_group_and_channel_management_every_section(self):
        for chat in (self.group, self.channel):
            with self.subTest(chat_type=chat.type):
                self.go(chat)
                self.manage()
                sections = ["type","reactions","statistics","invites","join-requests","admins","members","moderation","log"]
                if chat.type == Chat.Type.GROUP:
                    sections.append("permissions")
                for name in sections:
                    self.click('[data-community-settings-open="' + name + '"]')
                    view = '[data-community-settings-view="' + name + '"]'
                    self.visible(view)
                    if name == "invites":
                        self.click("#communitySettingsInviteCreateOpen")
                        self.visible("#communitySettingsInviteForm")
                        self.click("#communitySettingsInviteCancel")
                        self.hidden("#communitySettingsInviteForm")
                    if name == "members":
                        self.click("#communitySettingsAddMember")
                        self.visible("#communitySettingsMemberSearchWrap")
                        self.click("#communitySettingsAddMember")
                        self.hidden("#communitySettingsMemberSearchWrap")
                    self.click(view + " [data-community-settings-back]")
                    self.visible("#communitySettingsOverview")
                self.click("#communitySettingsClose")
                self.hidden("#communitySettings")
                self.visible("#communityProfile")
                self.click("#communityProfileSettingsOpen")
                self.visible("#communitySettingsOverview")
                self.page.keyboard.press("Escape")
                self.hidden("#communitySettings")
                self.click("#communityProfileClose")
                self.hidden("#communityProfile")

    def test_management_is_independent_of_profile_failure_and_retries(self):
        self.go(self.group)
        profile_pattern = "**/chat/*/profile/"
        settings_pattern = "**/chat/*/profile/settings/"
        self.page.route(profile_pattern, lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"ok":false,"error":"Profile unavailable"}'))
        self.page.route(settings_pattern, lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"ok":false,"error":"Management unavailable"}'))
        self.menu("[data-open-community-settings]")
        self.visible("#communitySettings")
        self.visible("#communitySettingsRetry")
        self.expect(self.page.locator("#communitySettingsLoadMessage")).to_have_text("Management unavailable")
        self.hidden("#communitySettingsOverview")
        self.page.unroute(settings_pattern)
        self.click("#communitySettingsRetry")
        self.visible("#communitySettingsOverview")
        self.hidden("#communitySettingsRetry")
        self.click("#communitySettingsClose")
        self.visible("#communityProfileRetry")
        self.page.unroute(profile_pattern)
        self.click("#communityProfileRetry")
        self.expect(self.page.locator("#communityProfileName")).to_have_text(self.group.title)
        self.hidden("#communityProfileLoadState")

    def test_group_selection_message_context_forward_and_delete(self):
        self.go(self.group)
        self.menu("[data-select-messages]")
        self.visible("#messageSelectionBar")
        self.expect(self.page.locator("#messageSelectionCount")).to_have_text("0")
        self.expect(self.page.locator("#messageSelectionForward")).to_be_disabled()
        message = '.message[data-message-id="' + str(self.message.pk) + '"]'
        self.click(message)
        self.expect(self.page.locator("#messageSelectionCount")).to_have_text("1")
        self.click("#messageSelectionClose")
        self.hidden("#messageSelectionBar")

        self.page.locator(message).click(button="right")
        self.visible("#messageContextMenu")
        self.click('[data-message-action="reply"]')
        self.visible("#composerReply")
        self.click("#composerReplyClose")
        self.hidden("#composerReply")

        self.page.locator(message).click(button="right")
        self.click('[data-message-action="edit"]')
        self.visible("#editMessageModal")
        self.page.locator("#editMessageText").fill("Edited browser message")
        self.click("#editMessageSave")
        self.hidden("#editMessageModal")
        self.expect(self.page.locator(message + " .message__text")).to_have_text("Edited browser message")

        self.page.locator(message).click(button="right")
        self.click('[data-message-action="forward"]')
        self.visible("#forwardMessageModal")
        self.click('[data-forward-target="saved"]')
        self.expect(self.page.locator("#forwardConfirm")).to_be_enabled()
        self.click("#forwardConfirm")
        self.hidden("#forwardMessageModal")

        self.page.locator(message).click(button="right")
        self.click('[data-message-action="delete"]')
        self.visible("#deleteMessageModal")
        self.click("#deleteMessageConfirm")
        self.hidden("#deleteMessageModal")
        self.expect(self.page.locator(message)).to_have_count(0)

    def test_community_statistics_period_switch(self):
        self.go(self.group)
        self.manage()
        self.click('[data-community-settings-open="statistics"]')
        self.visible("#communityStatsContent")
        self.expect(self.page.locator('[data-stats-value="messages"]')).to_have_text("1")
        self.expect(self.page.locator("#communityStatsMessages .community-stats-chart-row")).to_have_count(7)
        self.click('[data-stats-days="30"]')
        self.expect(self.page.locator("#communityStatsMessages .community-stats-chart-row")).to_have_count(30)
        self.click("#communityStatsRefresh")
        self.visible("#communityStatsContent")
        self.click('[data-community-settings-view="statistics"] [data-community-settings-back]')
        self.visible("#communitySettingsOverview")

    def test_group_reaction_management_and_reactor_list(self):
        MessageReaction.objects.create(message=self.message,user=self.peer,emoji="🔥")
        self.go(self.group)
        self.manage()
        self.click('[data-community-settings-open="reactions"]')
        self.visible('[data-community-settings-view="reactions"]')
        self.click('#communitySettingsReactionChoices label:has(input[value="🔥"])')
        self.click('#communitySettingsReactionsForm button[type="submit"]')
        self.visible("#communitySettingsOverview")
        self.click("#communitySettingsClose")
        self.click("#communityProfileClose")
        selector = '.message[data-message-id="' + str(self.message.pk) + '"]'
        self.page.locator(selector).click(button="right")
        self.hidden('#messageReactionPicker [data-pick-reaction="🔥"]')
        self.visible('#messageReactionPicker [data-pick-reaction="👍"]')
        self.click('[data-message-action="reactors"]')
        self.visible("#messageReactorsDialog")
        self.expect(self.page.locator("#messageReactorsList")).to_contain_text("@peer")
        self.click("#messageReactorsClose")
        self.hidden("#messageReactorsDialog")

    def test_group_message_readers_dialog(self):
        ChatParticipant.objects.filter(chat=self.group, user=self.peer).update(read_through_id=self.message.pk)
        self.go(self.group)
        message = '.message[data-message-id="' + str(self.message.pk) + '"]'
        self.page.locator(message).click(button="right")
        self.click('[data-message-action="readers"]')
        self.visible("#messageReadersDialog")
        self.expect(self.page.locator("#messageReadersStatus")).to_have_text("Прочитали: 1")
        self.expect(self.page.locator("#messageReadersList")).to_contain_text("@peer")
        self.click("#messageReadersClose")
        self.hidden("#messageReadersDialog")

    def test_chat_search_stickers_attachments_scheduling_and_folders(self):
        self.go(self.direct)
        self.click("#chatSearchToggle")
        self.visible("#chatSearchPanel")
        self.page.locator("#chatSearchInput").fill("Browser direct")
        self.expect(self.page.locator("#chatSearchResults")).to_contain_text("Browser direct test")
        self.click("#chatSearchClose")
        self.hidden("#chatSearchPanel")

        self.click('[data-open-stickers][data-sticker-send="true"]')
        self.visible("#stickerDialog")
        self.expect(self.page.locator("#stickerCreatePack")).to_be_enabled()
        self.click("#stickerDialogClose")
        self.hidden("#stickerDialog")

        for kind in ("poll", "todo", "location", "article"):
            self.click("#attachmentButton")
            self.visible("#attachmentMenu")
            self.click('[data-attach-special="' + kind + '"]')
            self.visible("#attachSpecialBackdrop")
            self.visible('[data-special-panel="' + kind + '"]')
            self.click("#attachSpecialClose")
            self.hidden("#attachSpecialBackdrop")

        self.menu("[data-open-scheduled]")
        self.visible("#scheduledDialog")
        self.expect(self.page.locator("#scheduledClose")).to_be_enabled()
        self.click("#scheduledNew")
        self.visible("#scheduledEditor")
        self.click("#scheduledBack")
        self.visible("#scheduledListPane")
        self.click("#scheduledClose")
        self.hidden("#scheduledDialog")

        self.menu("[data-chat-folders]")
        self.visible("#chatFoldersDialog")
        self.expect(self.page.locator("#chatFoldersClose")).to_be_enabled()
        self.click("#chatFoldersClose")
        self.hidden("#chatFoldersDialog")

    def test_gallery_filters_navigation_and_protected_download(self):
        from PIL import Image

        storage = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=storage))
        picture = BytesIO()
        Image.new("RGB", (8, 8), "red").save(picture, format="PNG")
        content = picture.getvalue()
        for name in ("a.png", "b.png"):
            MessageAttachment.objects.create(
                message=self.direct_message, kind="image", original_name=name,
                file=ContentFile(content, name=name), size=len(content),
            )
        MessageAttachment.objects.create(
            message=self.direct_message, kind="file", original_name="note.txt",
            file="test/note.txt", size=42,
        )
        self.go(self.direct)
        self.menu('[data-open-gallery="media"]')
        self.visible("#chatMediaGallery")
        self.expect(self.page.locator("#chatGalleryItems .chat-gallery-card")).to_have_count(2)
        self.page.locator("#chatGalleryItems [data-lightbox-image]").first.click()
        self.visible("#imageViewer")
        self.expect(self.page.locator("#imageViewerCount")).to_have_text("1 / 2")
        self.click("#imageViewerNext")
        self.expect(self.page.locator("#imageViewerCount")).to_have_text("2 / 2")
        self.expect(self.page.locator("#imageViewerNext")).to_be_disabled()
        self.click("#imageViewerPrev")
        self.expect(self.page.locator("#imageViewerCount")).to_have_text("1 / 2")
        self.click("#imageViewerClose")
        self.hidden("#imageViewer")
        self.click('[data-gallery-kind="files"]')
        self.expect(self.page.locator("#chatGalleryItems")).to_contain_text("note.txt")
        self.expect(self.page.locator("#chatGalleryItems [data-gallery-download]")).to_have_count(1)
        self.click("#chatGalleryClose")
        self.hidden("#chatMediaGallery")
        self.direct.protect_content = True
        self.direct.save(update_fields=["protect_content"])
        self.go(self.direct)
        self.menu('[data-open-gallery="media"]')
        self.expect(self.page.locator("#chatGalleryItems .chat-gallery-card")).to_have_count(2)
        self.expect(self.page.locator("#chatGalleryItems [data-gallery-download]")).to_have_count(0)
        self.page.locator("#chatGalleryItems [data-lightbox-image]").first.click()
        self.hidden("#imageViewerDownload")
        self.click("#imageViewerClose")
        self.click("#chatGalleryClose")

    def test_notification_preferences_persist_after_reload(self):
        self.go(query="?settings=main")
        self.click('[data-settings-target="notifications"]')
        self.visible('[data-settings-screen="notifications"]')
        mention = '[data-notification-preference="mention"]'
        badge = '[data-notification-preference="badge"]'
        self.expect(self.page.locator(mention)).to_be_checked()
        # The native input is covered by its visible decorative track.
        # Exercise the associated label rather than forcing a hidden click.
        self.click('label:has(' + mention + ')')
        self.click('label:has(' + badge + ')')
        self.expect(self.page.locator(mention)).not_to_be_checked()
        self.page.reload(wait_until="domcontentloaded")
        self.visible('[data-settings-screen="notifications"]')
        self.expect(self.page.locator(mention)).not_to_be_checked()
        self.expect(self.page.locator(badge)).not_to_be_checked()
        self.click("#settingsSectionBack")
        self.visible('[data-settings-screen="main"]')

    def test_settings_sections_and_return_navigation(self):
        self.go(query="?settings=main")
        self.visible("#telegramSettings")
        self.click('[data-settings-target="privacy"]')
        self.visible('[data-settings-screen="privacy"]')
        for name in ("password","auto-delete","blocked","sessions","inactive"):
            self.click('[data-settings-target="' + name + '"]')
            self.visible('[data-settings-screen="' + name + '"]')
            self.click("#settingsSectionBack")
            self.visible('[data-settings-screen="privacy"]')
        self.click("#settingsSectionBack")
        self.visible('[data-settings-screen="main"]')
        self.click('[data-settings-target="chat"]')
        self.visible('[data-settings-screen="chat"]')
        self.click('[data-settings-target="archive"]')
        self.visible('[data-settings-screen="archive"]')
        self.click("#settingsSectionBack")
        self.visible('[data-settings-screen="chat"]')
        self.click("#settingsSectionBack")
        self.visible('[data-settings-screen="main"]')
        self.click("#settingsMenuButton")
        self.visible("#settingsMenu")
        self.click("#settingsMenuButton")
        self.hidden("#settingsMenu")
        self.click('#telegramSettings .tg-settings-topbar [data-settings-close]')
        self.hidden("#telegramSettings")
