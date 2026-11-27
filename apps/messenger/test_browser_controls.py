"""Real-browser interaction tests against Django's isolated live test server.

Opt-in locally: install playwright and Chromium, then set
SOVIETGRAM_BROWSER_TESTS=1. CI runs these in a separate job.
"""
import os
import re
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
        cls.browser = cls.playwright.chromium.launch(headless=True, args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        ])
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

    def test_channel_discussion_lifecycle(self):
        post = Message.objects.create(chat=self.channel, sender=self.owner, text="Channel publication")
        self.go(self.channel)
        self.manage()
        self.click('label:has(#communitySettingsComments)')
        self.expect(self.page.locator("#communitySettingsComments")).to_be_checked()
        self.expect(self.page.locator("#communitySettingsComments")).to_be_enabled()
        self.click("#communitySettingsClose")
        self.click("#communityProfileClose")
        entry = f'.message[data-message-id="{post.pk}"] [data-discussion-url]'
        self.visible(entry)
        self.click(entry)
        self.visible("#channelDiscussion")
        self.visible("#discussionForm")
        self.page.locator("#discussionText").fill("First comment")
        self.click("#discussionSend")
        first = self.page.locator(".discussion-comment").filter(has_text="First comment")
        self.expect(first).to_be_visible()
        first.get_by_role("button",name="Ответить",exact=True).click()
        self.visible("#discussionReply")
        self.page.locator("#discussionText").fill("Second comment")
        self.click("#discussionSend")
        second = self.page.locator(".discussion-comment").filter(has_text="Second comment")
        self.expect(second).to_be_visible()
        self.expect(second.locator(".discussion-comment-reply")).to_contain_text("First comment")
        second.get_by_role("button",name="Изменить",exact=True).click()
        self.page.locator("#discussionText").fill("Edited comment")
        self.click("#discussionSend")
        edited = self.page.locator(".discussion-comment").filter(has_text="Edited comment")
        self.expect(edited).to_be_visible()
        self.click("#discussionLock")
        self.hidden("#discussionForm")
        self.expect(self.page.locator("#discussionStatus")).to_contain_text("Закрыты")
        self.click("#discussionLock")
        self.visible("#discussionForm")
        edited.get_by_role("button",name="Удалить",exact=True).click()
        self.expect(edited).to_have_count(0)
        self.expect(self.page.locator("#discussionStatus")).to_have_text("Комментарии: 1")
        self.click("#discussionClose")
        self.hidden("#channelDiscussion")
        self.expect(self.page.locator(entry)).to_contain_text("Комментарии: 1")

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

    def test_multiple_reactions_in_message_picker(self):
        self.go(self.direct)
        selector = '.message[data-message-id="' + str(self.direct_message.pk) + '"]'
        for emoji in ("👍", "🔥", "❤️"):
            self.page.locator(selector).click(button="right")
            self.click('#messageReactionPicker [data-pick-reaction="' + emoji + '"]')
            self.expect(self.page.locator(selector + ' [data-message-reaction="' + emoji + '"]')).to_have_attribute("aria-pressed", "true")
        self.expect(self.page.locator(selector + ' [data-message-reaction][aria-pressed="true"]')).to_have_count(3)
        self.click(selector + ' [data-message-reaction="🔥"]')
        self.expect(self.page.locator(selector + ' [data-message-reaction][aria-pressed="true"]')).to_have_count(2)
        self.page.reload(wait_until="domcontentloaded")
        self.expect(self.page.locator(selector + ' [data-message-reaction][aria-pressed="true"]')).to_have_count(2)

    def test_schedule_article_and_sticker_from_real_controls(self):
        from PIL import Image
        from .models import ScheduledMessage, Sticker, StickerPack
        buffer = BytesIO()
        Image.new("RGBA", (8, 8), "red").save(buffer, format="WEBP")
        pack = StickerPack.objects.create(owner=self.owner, name="Schedule pack")
        sticker = Sticker.objects.create(pack=pack, image=buffer.getvalue())
        self.go(self.direct)
        self.click("#attachmentButton")
        self.click('[data-attach-special="article"]')
        self.visible('[data-special-panel="article"]')
        self.page.locator("#attachArticleTitle").fill("Future article")
        self.page.locator("#attachArticleBody").fill("**Scheduled body**")
        self.page.locator("#attachSpecialSchedule").check()
        self.expect(self.page.locator("#attachSpecialSend")).to_have_text("Запланировать")
        self.click("#attachSpecialSend")
        self.hidden("#attachSpecialBackdrop")
        self.assertTrue(ScheduledMessage.objects.filter(sender=self.owner, special_type="article",
                                                        special_data__title="Future article").exists())
        self.click('[data-open-stickers][data-sticker-send="true"]')
        self.visible("#stickerDialog")
        self.page.locator(f'.sticker-tile[data-sticker-id="{sticker.pk}"]').click(button="right")
        self.page.locator("#stickerItemMenu").get_by_role("button", name="Отправить позже", exact=True).click()
        self.visible("#scheduledDialog")
        self.expect(self.page.locator("#scheduledTitle")).to_have_text("Запланировать стикер")
        self.click("#scheduledSave")
        self.visible("#scheduledListPane")
        self.expect(self.page.locator("#scheduledList")).to_contain_text("Стикер")
        self.assertTrue(ScheduledMessage.objects.filter(sender=self.owner, sticker_source_id=sticker.pk).exists())

    def test_video_note_record_preview_send_and_reload(self):
        self.context.grant_permissions(["camera", "microphone"], origin=self.live_server_url)
        self.go(self.direct)
        action = self.page.locator("#sendButton")
        self.expect(action).to_have_attribute("data-composer-action", "voice")
        action.click()
        self.expect(action).to_have_attribute("data-composer-action", "video_note")
        self.page.locator("#messageInput").fill("Test")
        self.expect(action).to_have_attribute("data-composer-action", "send")
        self.page.locator("#messageInput").fill("")
        self.expect(action).to_have_attribute("data-composer-action", "video_note")
        box = action.bounding_box()
        x, y = box["x"] + box["width"]/2, box["y"] + box["height"]/2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.visible("#videoNoteDialog")
        self.expect(self.page.locator("#videoNoteDialog")).to_have_attribute("data-record-state", "recording")
        self.page.mouse.move(x, y-105, steps=6)
        self.page.mouse.up()
        self.visible("#videoNoteStop")
        self.visible("#videoNoteSend")
        self.page.wait_for_timeout(3000)
        self.click("#videoNoteStop")
        self.visible("#videoNoteSend")
        self.expect(self.page.locator("#videoNotePreview")).to_have_attribute("src", re.compile(r"^blob:"))
        self.expect(self.page.locator("#videoNoteSend")).to_be_enabled()
        self.page.wait_for_function("document.getElementById('videoNotePreview').videoWidth > 0 && document.getElementById('videoNotePreview').readyState >= 2")
        self.click("#videoNoteSend")
        self.hidden("#videoNoteDialog")
        self.expect(self.page.locator("[data-video-note-player]")).to_have_count(1)
        attachment = MessageAttachment.objects.get(message__chat=self.direct, kind="video_note")
        self.assertGreaterEqual(attachment.duration_ms, 200)
        self.assertLessEqual(attachment.duration_ms, 60000)
        self.page.reload(wait_until="domcontentloaded")
        self.visible("[data-video-note-player]")
        self.expect(self.page.locator("[data-video-note-player]")).to_have_attribute("data-note-id", str(attachment.pk))
        player = self.page.locator("[data-video-note-player]")
        note_id = str(attachment.pk)
        initial = player.bounding_box()
        self.assertAlmostEqual(initial["width"], initial["height"], delta=3)
        self.expect(player.locator('input[type="range"]')).to_have_count(0)
        self.expect(player.locator("[data-note-seek]")).to_have_css("visibility", "hidden")
        self.expect(player.locator("..").locator("..")).to_have_css("background-color", "rgba(0, 0, 0, 0)")
        self.click("[data-video-note-player] [data-note-play]")
        self.expect(player).to_have_class(re.compile("is-expanded"))
        self.expect(player).to_have_class(re.compile("is-playing"))
        self.assertGreater(player.bounding_box()["width"], initial["width"] + 40)
        self.expect(player.locator("[data-note-error]")).to_be_hidden()
        self.click("[data-video-note-player] [data-note-mute]")
        self.expect(player.locator("[data-note-mute]")).to_have_attribute("aria-pressed", "true")
        self.click("[data-video-note-player] [data-note-play]")
        self.expect(player).not_to_have_class(re.compile("is-playing"))
        # Seek clockwise to the halfway point of the circular timeline.
        self.page.wait_for_function("document.querySelector('[data-video-note-player] video').readyState >= 1")
        ring = player.locator("[data-note-seek]").bounding_box()
        self.page.mouse.click(ring["x"] + ring["width"]/2, ring["y"] + ring["height"]*.95)
        self.page.wait_for_function("Number(document.querySelector('[data-note-seek]').getAttribute('aria-valuenow')) >= 40")
        self.expect(player).to_have_attribute("data-note-id", note_id)
        self.click("[data-video-note-player] [data-note-collapse]")
        self.expect(player).not_to_have_class(re.compile("is-expanded"))
        self.assertAlmostEqual(player.bounding_box()["width"], initial["width"], delta=3)
        self.expect(action).to_have_attribute("data-composer-action", "video_note")
        box = action.bounding_box()
        x, y = box["x"] + box["width"]/2, box["y"] + box["height"]/2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.expect(self.page.locator("#videoNoteDialog")).to_have_attribute("data-record-state", "recording")
        self.page.mouse.move(x-115, y, steps=6)
        self.page.mouse.up()
        self.hidden("#videoNoteDialog")
        self.assertEqual(MessageAttachment.objects.filter(message__chat=self.direct, kind="video_note").count(), 1)
        # Ordinary hold-and-release sends directly, no intermediate preview.
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.expect(self.page.locator("#videoNoteDialog")).to_have_attribute("data-record-state", "recording")
        self.page.wait_for_timeout(1200)
        self.page.mouse.up()
        self.hidden("#videoNoteDialog")
        self.expect(self.page.locator("[data-video-note-player]")).to_have_count(2)
        action.click()
        self.expect(action).to_have_attribute("data-composer-action", "voice")

    def test_video_note_recovers_from_delayed_camera_and_codec_start_failure(self):
        self.context.grant_permissions(["camera", "microphone"], origin=self.live_server_url)
        self.page.add_init_script("""
            const getCamera = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            window.cameraAttempts = 0;
            navigator.mediaDevices.getUserMedia = async constraints => {
                if (!constraints.video) return getCamera(constraints);
                window.cameraAttempts++;
                if (window.cameraAttempts === 1) throw new DOMException("Test permission denial", "NotAllowedError");
                await new Promise(resolve => setTimeout(resolve, 1100));
                return getCamera(constraints);
            };
            const originalStart = MediaRecorder.prototype.start;
            window.encoderAttempts = 0;
            MediaRecorder.prototype.start = function(...args) {
                window.encoderAttempts++;
                if (window.encoderAttempts === 1) throw new DOMException("Test codec failure", "NotSupportedError");
                return originalStart.apply(this, args);
            };
        """)
        self.go(self.direct)
        self.page.set_viewport_size({"width":390, "height":844})
        self.visible("#sendButton")
        action = self.page.locator("#sendButton")
        action.click()
        self.expect(action).to_have_attribute("data-composer-action", "video_note")
        box = action.bounding_box()
        x, y = box["x"] + box["width"]/2, box["y"] + box["height"]/2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.expect(self.page.locator("#videoNoteDialog")).to_have_attribute("data-record-state", "error")
        self.page.mouse.up()
        self.visible("#videoNoteRetry")
        self.click("#videoNoteClose")
        self.hidden("#videoNoteDialog")
        # A camera prompt can outlast the original hold. Releasing must leave
        # a usable preview instead of silently disposing the permission request.
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.expect(self.page.locator("#videoNoteDialog")).to_have_attribute("data-record-state", "opening")
        self.page.mouse.up()
        self.expect(self.page.locator("#videoNoteDialog")).to_have_attribute("data-record-state", "ready")
        self.click("#videoNoteStart")
        self.expect(self.page.locator("#videoNoteDialog")).to_have_attribute("data-record-state", "recording")
        self.assertGreaterEqual(self.page.evaluate("window.encoderAttempts"), 2)
        self.page.wait_for_timeout(1200)
        self.click("#videoNoteStop")
        self.expect(self.page.locator("#videoNoteSend")).to_be_enabled()
        self.page.wait_for_function("document.getElementById('videoNotePreview').videoWidth > 0")
        self.click("#videoNoteSend")
        self.hidden("#videoNoteDialog")
        self.expect(self.page.locator("[data-video-note-player]")).to_have_count(1)
        self.assertEqual(MessageAttachment.objects.filter(message__chat=self.direct, kind="video_note").count(), 1)

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

    def test_sticker_pack_publish_revoke_and_preview(self):
        from io import BytesIO
        from PIL import Image
        from .models import Sticker, StickerPack

        buffer = BytesIO()
        Image.new("RGBA", (16, 16), "red").save(buffer, format="WEBP")
        pack = StickerPack.objects.create(owner=self.owner, name="Share test")
        Sticker.objects.create(pack=pack, image=buffer.getvalue(), emoji="X")
        self.go(query="?manage_stickers=1")
        self.visible("#stickerDialog")
        self.click(f'[data-sticker-pack="{pack.pk}"]')
        self.click("#stickerPackMenuToggle")
        self.expect(self.page.locator("#stickerShare")).to_be_enabled()
        self.click("#stickerShare")
        self.visible("#stickerPromptForm")
        self.click("#stickerPromptSubmit")
        self.visible("#stickerSharePanel")
        link = self.page.locator("#stickerShareLink").input_value()
        self.assertIn("/addstickers/", link)
        self.page.goto(link, wait_until="domcontentloaded")
        self.visible(".shared-sticker-preview img")
        self.expect(self.page.locator(".auth-heading h1")).to_have_text("Share test")
        self.go(query="?manage_stickers=1")
        self.click(f'[data-sticker-pack="{pack.pk}"]')
        self.visible("#stickerSharePanel")
        self.click("#stickerPackMenuToggle")
        self.click("#stickerUnshare")
        self.click("#stickerPromptSubmit")
        self.expect(self.page.locator("#stickerDialogTitle")).to_have_text("Share test")
        self.hidden("#stickerSharePanel")
        self.assertEqual(self.page.request.get(link).status, 404)

    def test_sticker_manager_create_rename_upload_and_delete(self):
        from io import BytesIO
        from PIL import Image
        from .models import StickerPack

        self.go(query="?settings=main")
        self.click('#telegramSettings [data-open-stickers]')
        self.visible("#stickerDialog")
        self.expect(self.page.locator("#stickerDialogTitle")).to_have_text("Мои наборы")
        self.click("#stickerCreatePack")
        self.page.locator("#stickerPromptInput").fill("New pack")
        self.click("#stickerPromptSubmit")
        self.expect(self.page.locator("#stickerDialogTitle")).to_have_text("New pack")
        self.click("#stickerUploadToggle")
        buffer = BytesIO()
        Image.new("RGBA", (16, 16), "blue").save(buffer, format="PNG")
        self.page.locator("#stickerFile").set_input_files({
            "name": "sticker.png", "mimeType": "image/png", "buffer": buffer.getvalue(),
        })
        self.page.locator("#stickerEmoji").fill("😀")
        self.click('#stickerUploadForm button[type="submit"]')
        self.visible(".sticker-tile")
        self.click("#stickerPackMenuToggle")
        self.click("#stickerRename")
        self.page.locator("#stickerPromptInput").fill("Renamed")
        self.click("#stickerPromptSubmit")
        self.expect(self.page.locator("#stickerDialogTitle")).to_have_text("Renamed")
        self.click("#stickerPackMenuToggle")
        self.click("#stickerEditMode")
        self.expect(self.page.locator("#stickerUploadToggle")).to_have_text("Готово")
        self.click(".sticker-tile")
        self.click("#stickerPromptSubmit")
        self.expect(self.page.locator("#stickerDialogTitle")).to_have_text("Renamed")
        self.expect(self.page.locator(".sticker-tile")).to_have_count(0)
        self.click("#stickerPackMenuToggle")
        self.click("#stickerDeletePack")
        self.click("#stickerPromptSubmit")
        self.expect(self.page.locator("#stickerDialogTitle")).to_have_text("Мои наборы")
        self.assertFalse(StickerPack.objects.filter(owner=self.owner).exists())
        self.click("#stickerInstallLink")
        self.page.locator("#stickerPromptInput").fill("https://example.invalid/addstickers/invalid")
        self.click("#stickerPromptSubmit")
        self.expect(self.page.locator("#stickerError")).to_contain_text("ссылка на набор")
        self.click("#stickerBack")
        self.click("#stickerDialogClose")

    def test_sticker_picker_context_actions_and_incoming_preview(self):
        from io import BytesIO
        from PIL import Image
        from .models import Sticker, StickerPack, MessageAttachment

        data = BytesIO()
        Image.new("RGBA", (16, 16), "red").save(data, format="WEBP")
        pack = StickerPack.objects.create(owner=self.owner, name="Picker test")
        sticker = Sticker.objects.create(pack=pack, image=data.getvalue(), emoji="🎉")
        self.go(self.direct)
        self.page.locator("#messageInput").fill("Draft stays")
        self.click('[data-open-stickers][data-sticker-send="true"]')
        self.visible("#stickerPackTabs")
        self.page.locator("#stickerSearch").fill("Picker test")
        tile = self.page.locator(f'[data-sticker-id="{sticker.pk}"]')
        self.expect(tile).to_be_visible()
        tile.click(button="right")
        self.visible("#stickerItemMenu")
        self.page.locator("#stickerItemMenu").get_by_role("button", name="Добавить в избранное").click()
        self.expect(self.page.locator("#stickerDialog")).to_have_attribute("aria-busy", "false")
        sticker.refresh_from_db()
        self.assertTrue(sticker.is_favorite)
        self.page.locator("#stickerSearch").fill("")
        self.click('[data-sticker-tab="favorites"]')
        tile.click()
        self.hidden("#stickerDialog")
        self.expect(self.page.locator("#messageInput")).to_have_value("Draft stays")
        attachment = MessageAttachment.objects.get(message__chat=self.direct, kind="sticker")
        image = self.page.locator(f'[data-sticker-attachment="{attachment.pk}"]')
        self.expect(image).to_be_visible()
        self.assertEqual(image.locator("[data-save-sticker]").count(), 0)
        self.assertEqual(image.locator(".message-sticker__preview").count(), 1)
        image.click(button="right")
        self.click('[data-message-action="save-sticker"]')
        self.visible("#stickerIncomingPreview")
        self.visible("#stickerSaveIncoming")
        self.click("#stickerSaveIncoming")
        self.hidden("#stickerDialog")
        self.assertEqual(pack.stickers.count(), 2)
        self.page.reload(wait_until="domcontentloaded")
        self.click(f'[data-sticker-attachment="{attachment.pk}"] .message-sticker__preview')
        self.visible("#stickerIncomingPreview")
        self.click("#stickerDialogClose")

        self.page.set_viewport_size({"width": 390, "height": 844})
        self.click('[data-open-stickers][data-sticker-send="true"]')
        self.visible("#stickerPackTabs")
        rect = self.page.locator("#stickerDialog").bounding_box()
        self.assertAlmostEqual(rect["x"], 0, delta=2)
        self.assertAlmostEqual(rect["y"] + rect["height"], 844, delta=2)
        self.click("#stickerDialogClose")

    def test_draft_and_pinned_chat_filters_survive_sidebar_refresh(self):
        ChatParticipant.objects.filter(chat=self.direct, user=self.owner).update(draft_text="Draft filter")
        ChatParticipant.objects.filter(chat=self.group, user=self.owner).update(is_pinned=True)
        self.go()
        direct = f'#chatList [data-chat-id="{self.direct.pk}"]'
        group = f'#chatList [data-chat-id="{self.group.pk}"]'
        self.click('[data-chat-filter="draft"]')
        self.visible(direct)
        self.hidden(group)
        self.page.reload(wait_until="domcontentloaded")
        self.visible(direct)
        self.hidden(group)
        self.expect(self.page.locator('[data-chat-filter="draft"]')).to_have_attribute("aria-pressed", "true")
        ChatParticipant.objects.filter(chat=self.direct, user=self.owner).update(draft_text="")
        self.page.evaluate("() => window.SovietgramSidebar.refresh()")
        self.hidden(direct)
        self.expect(self.page.locator("#chatFilterEmpty")).to_have_text("Нет чатов с черновиками.")
        self.click('[data-chat-filter="pinned"]')
        self.visible(group)
        self.hidden(direct)
        self.click('[data-chat-filter="all"]')
        self.visible(direct)

    def test_chat_date_navigation_and_pinned_link_filters(self):
        from datetime import datetime, UTC
        from .models import PinnedMessage

        old = self.direct_message
        Message.objects.filter(pk=old.pk).update(created_at=datetime(2025, 6, 1, 12, tzinfo=UTC))
        PinnedMessage.objects.create(chat=self.direct, message=old, pinned_by=self.owner)
        Message.objects.bulk_create([Message(chat=self.direct, sender=self.owner, text=f"New {i}") for i in range(105)])
        link = Message.objects.create(chat=self.direct, sender=self.owner, text="https://example.net/feature")
        self.go(self.direct)
        self.click("#chatSearchToggle")
        self.visible("#chatSearchPanel")
        self.click(".chat-search-filters summary")
        self.page.locator("#chatSearchKind").select_option("link")
        self.expect(self.page.locator("#chatSearchResults")).to_contain_text("https://example.net/feature")
        self.page.locator("#chatSearchKind").select_option("pinned")
        self.expect(self.page.locator("#chatSearchResults")).to_contain_text("Browser direct test")
        self.click(".chat-search-filters summary")
        self.click("#chatJumpMentionButton")
        self.expect(self.page.locator("#chatHistoryTargetStatus")).to_have_text("Непрочитанных упоминаний не найдено.")
        self.page.locator("#chatJumpDate").fill("2025-06-02")
        self.click("#chatJumpDateButton")
        self.expect(self.page.locator("#chatHistoryTargetStatus")).to_have_text("За выбранную дату сообщений нет.")
        self.page.locator("#chatJumpDate").fill("2025-06-01")
        self.click("#chatJumpDateButton")
        self.expect(self.page.locator("#messageStage")).to_have_attribute("data-focus-message", str(old.pk))
        self.visible(f"#message-{old.pk}")
        self.hidden("#chatSearchPanel")

        # The list shortcut opens the real paginated search, not the
        # eight-message summary used for the top pin banner.
        self.click("#pinnedMessageListButton")
        self.visible("#chatSearchPanel")
        self.expect(self.page.locator("#chatSearchKind")).to_have_value("pinned")
        self.expect(self.page.locator("#chatSearchResults")).to_contain_text("Browser direct test")
        self.click("#chatSearchClose")
        self.visible("#historyJumpLatest")
        self.click("#historyJumpLatest")
        self.visible(f"#message-{link.pk}")
        self.hidden("#historyJumpLatest")
        self.expect(self.page.locator("#messageStage")).to_have_attribute("data-focus-message", "0")
        from urllib.parse import urlsplit, parse_qs
        self.assertNotIn("message", parse_qs(urlsplit(self.page.url).query))
        self.assertEqual(self.page.locator(f"#message-{old.pk}").count(), 0)
        # The old pin must navigate back to the actual message.
        self.click("#pinnedMessageBar")
        self.expect(self.page.locator("#messageStage")).to_have_attribute("data-focus-message", str(old.pk))
        self.visible(f"#message-{old.pk}")

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
        self.visible("#stickerPackTabs")
        self.click("#stickerManage")
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

    def test_platform_admin_panel_and_report_flow(self):
        from apps.accounts.two_factor import encrypt_secret
        import pyotp

        self.owner.platform_role = User.PlatformRole.OWNER
        self.owner.two_factor_secret = encrypt_secret(pyotp.random_base32())
        self.owner.save(update_fields=["platform_role","two_factor_secret"])
        reported = Message.objects.create(chat=self.direct,sender=self.peer,text="Reportable message")
        self.go(self.direct)
        self.page.locator(f'.message[data-message-id="{reported.pk}"]').click(button="right")
        self.click('[data-message-action="report"]')
        self.page.locator('select[name="reason"]').select_option("spam")
        self.page.locator('textarea[name="details"]').fill("Browser report")
        self.page.get_by_role("button",name="Отправить жалобу").click()
        self.expect(self.page.get_by_role("heading",name="Мои жалобы")).to_be_visible()
        self.go()
        self.click("#profileMenuButton")
        self.click("#platformAdminEntry")
        self.expect(self.page.get_by_role("heading",name="Обзор",exact=True)).to_be_visible()
        self.page.locator(".platform-sidebar nav").get_by_role("link",name="Жалобы",exact=True).click()
        self.page.locator(".platform-table-wrap tbody a").first.click()
        self.expect(self.page.locator(".platform-evidence")).to_contain_text("Reportable message")
        self.page.locator('input[name="reason"]').fill("Confirmed spam")
        self.click('button[value="delete_message"]')
        self.expect(self.page.locator(".platform-status")).to_have_text("Решена")
        self.page.locator(".platform-sidebar nav").get_by_role("link",name="Пользователи",exact=True).click()
        self.page.locator('input[name="q"]').fill("peer")
        self.page.get_by_role("button",name="Найти").click()
        self.page.locator(".platform-table-wrap tbody a").first.click()
        self.page.locator('form:has(button[value="suspend"]) input[name="reason"]').fill("Browser moderation")
        self.click('button[value="suspend"]')
        self.visible('button[value="restore"]')
        self.page.locator('form:has(button[value="restore"]) input[name="reason"]').fill("Appeal accepted")
        self.click('button[value="restore"]')
        self.visible('button[value="suspend"]')
        self.page.locator(".platform-sidebar nav").get_by_role("link",name="Журнал действий").click()
        self.expect(self.page.locator(".platform-table-wrap")).to_contain_text("delete_reported_message")
        self.expect(self.page.locator(".platform-table-wrap")).to_contain_text("Browser moderation")
        self.assertFalse(Message.objects.filter(pk=reported.pk,is_deleted=False).exists())

    def test_durable_text_outbox_survives_tab_close_and_concurrent_tabs(self):
        from .models import MessageSendReceipt

        self.go(self.direct)
        send_url = self.live_server_url + reverse("messenger:send_message", args=[self.direct.pk])
        self.context.route(send_url, lambda route: route.abort())
        self.page.locator("#messageInput").fill("Durable queue test")
        self.click("#sendButton")
        self.expect(self.page.locator("#pendingTextMessages")).to_contain_text("Durable queue test")
        self.expect(self.page.locator("#pendingTextMessages")).to_contain_text("сохранены на этом устройстве")
        self.expect(self.page.locator("#pendingTextMessages")).to_contain_text("Ожидает повторной отправки")
        self.page.close()
        self.page = self.context.new_page()
        self.go(self.direct)
        self.expect(self.page.locator("#pendingTextMessages")).to_contain_text("Durable queue test")
        second = self.context.new_page()
        second.goto(self.live_server_url + reverse("messenger:chat", args=[self.direct.pk]))
        self.expect(second.locator("#pendingTextMessages")).to_contain_text("Durable queue test")
        self.context.unroute(send_url)
        self.page.bring_to_front()
        self.expect(self.page.locator(".message__text").last).to_have_text("Durable queue test", timeout=30000)
        self.expect(self.page.locator("#pendingTextMessages")).to_be_hidden()
        second.bring_to_front()
        self.expect(second.locator("#pendingTextMessages")).to_be_hidden(timeout=15000)
        self.assertEqual(Message.objects.filter(chat=self.direct, text="Durable queue test").count(), 1)
        self.assertEqual(MessageSendReceipt.objects.filter(sender=self.owner).count(), 1)
        second.close()

    def test_desktop_footer_follows_composer_height(self):
        self.go(self.direct)
        def aligned():
            self.page.wait_for_function("""() => {
                const footer = document.querySelector("#desktopChatSidebar > .sidebar__footer");
                const composer = document.querySelector("#messageForm");
                if (!footer || !composer) return false;
                const a = footer.getBoundingClientRect(), b = composer.getBoundingClientRect();
                return Math.abs(a.top - b.top) <= 1 && Math.abs(a.height - b.height) <= 1
                    && Math.abs(a.bottom - b.bottom) <= 1;
            }""")
        aligned()
        initial = self.page.locator("#messageForm").bounding_box()["height"]
        self.page.locator("#messageInput").fill("One\nTwo\nThree\nFour\nFive")
        self.page.wait_for_function("(h) => document.querySelector('#messageForm').getBoundingClientRect().height > h + 10", arg=initial)
        aligned()
        self.page.locator("#messageInput").fill("")
        self.page.wait_for_function("(h) => Math.abs(document.querySelector('#messageForm').getBoundingClientRect().height - h) <= 1", arg=initial)
        aligned()
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.hidden("#desktopChatSidebar")
        self.page.set_viewport_size({"width": 1360, "height": 900})
        aligned()

    def test_desktop_sidebar_width_is_applied_before_late_scripts(self):
        self.go(self.direct)
        separator = self.page.locator("#desktopSidebarResizer")
        sidebar = self.page.locator("#desktopChatSidebar")
        separator.focus()
        separator.press("Home")
        self.expect(separator).to_have_attribute("aria-valuenow", "280")
        self.assertAlmostEqual(sidebar.bounding_box()["width"], 280, delta=1)

        # Simulate a slow/unavailable end-of-body layout controller. The
        # next chat must already have the saved width even without that JS.
        script_url = re.compile(r"/static/js/desktop-ui\.js(?:\?.*)?$")
        self.page.route(script_url, lambda route: route.abort())
        self.click(f'#chatList a[data-chat-id="{self.group.pk}"]')
        self.page.wait_for_load_state("domcontentloaded")
        self.visible(".conversation--chat")
        self.assertAlmostEqual(sidebar.bounding_box()["width"], 280, delta=1)
        self.assertEqual(self.page.evaluate("""() =>
            document.documentElement.style.getPropertyValue("--sg-desktop-sidebar")"""), "280px")

        self.page.unroute(script_url)
        self.page.reload(wait_until="domcontentloaded")
        self.expect(separator).to_have_attribute("aria-valuenow", "280")
        self.assertAlmostEqual(sidebar.bounding_box()["width"], 280, delta=1)
        separator.press("End")
        self.expect(separator).to_have_attribute("aria-valuenow", "520")
        self.click(f'#chatList a[data-chat-id="{self.direct.pk}"]')
        self.page.wait_for_load_state("domcontentloaded")
        self.expect(separator).to_have_attribute("aria-valuenow", "520")
        self.assertAlmostEqual(sidebar.bounding_box()["width"], 520, delta=1)
        separator.press("Enter")
        self.assertEqual(self.page.evaluate("""() =>
            document.documentElement.style.getPropertyValue("--sg-desktop-sidebar")"""), "")

    def test_desktop_workspace_and_resizable_chat_list(self):
        self.go()
        self.visible("#desktopSidebarResizer")
        self.visible("#desktopNewChat")
        self.hidden("#mobileSearchToggle")
        self.hidden("#sidebarComposeButton")
        self.visible(".conversation-empty-hint")
        separator = self.page.locator("#desktopSidebarResizer")
        sidebar = self.page.locator("#desktopChatSidebar")
        before = sidebar.bounding_box()["width"]
        separator.focus()
        separator.press("ArrowRight")
        self.assertGreater(sidebar.bounding_box()["width"], before)
        separator.press("End")
        self.expect(separator).to_have_attribute("aria-valuenow", "520")
        self.assertAlmostEqual(sidebar.bounding_box()["width"], 520, delta=2)
        self.go(self.direct)
        self.visible(".sidebar")
        self.visible(".conversation--chat")
        self.hidden(".mobile-back")
        self.assertAlmostEqual(sidebar.bounding_box()["width"], 520, delta=2)
        self.visible("#messageInput")
        self.visible("#sendOptionsToggle")
        self.visible('#messageForm [data-compose-panel="format"]')
        self.hidden("#mobileComposerToggle")
        self.page.locator("#messageInput").fill("Desktop layout test")
        self.click("#sendButton")
        self.expect(self.page.locator(".message__text").last).to_have_text("Desktop layout test")
        # Mouse dragging, persistence and reset use the same bounded sizing path.
        box = separator.bounding_box()
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] - 55, box["y"] + box["height"] / 2, steps=6)
        self.page.mouse.up()
        resized = sidebar.bounding_box()["width"]
        self.assertLess(resized, 520)
        self.assertGreaterEqual(resized, 280)
        self.page.reload(wait_until="domcontentloaded")
        self.assertAlmostEqual(sidebar.bounding_box()["width"], resized, delta=2)
        separator.dblclick()
        self.assertLess(sidebar.bounding_box()["width"], resized)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.hidden("#desktopSidebarResizer")
        self.hidden("#desktopNewChat")
        self.hidden(".sidebar")
        self.visible(".mobile-back")
        self.visible("#mobileComposerToggle")
        self.page.set_viewport_size({"width": 1360, "height": 900})
        self.visible("#desktopSidebarResizer")
        self.visible("#sendOptionsToggle")
        self.hidden("#mobileComposerToggle")

    def test_mobile_workspace_navigation_and_composer(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.go()
        self.visible(".mobile-chat-title")
        self.hidden("#chatFilter")
        self.hidden(".conversation--empty")
        self.visible("#sidebarComposeButton")
        self.expect(self.page.locator(".sidebar")).to_have_css("display", "flex")
        self.assertLessEqual(self.page.locator(".app-shell").bounding_box()["width"], 390)
        self.click("#mobileSearchToggle")
        self.visible("#chatFilter")
        self.page.locator("#chatFilter").fill("peer")
        self.visible("#sidebarGlobalSearch")
        self.click("#mobileSearchToggle")
        self.hidden("#chatFilter")
        self.hidden("#sidebarGlobalSearch")
        self.click("#sidebarComposeButton")
        self.visible("#sidebarComposeMenu")
        self.click('#sidebarComposeMenu [data-community-open="group"]')
        self.visible("#communityWizard")
        self.page.locator("#communityWizard [data-community-close]:visible").first.click()
        self.hidden("#communityWizard")
        self.click("#profileMenuButton")
        self.expect(self.page.locator("#profileMenu")).to_have_class(re.compile(r"\bis-open\b"))
        self.expect(self.page.locator("#profileMenu .sidebar__footer")).to_have_count(1)
        self.click('#profileMenu [data-open-settings="main"]')
        self.visible("#telegramSettings")
        self.expect(self.page.locator(".tg-settings-window")).to_have_css("border-radius", "0px")
        self.page.locator("#telegramSettings [data-settings-close]:visible").first.click()
        self.hidden("#telegramSettings")
        self.page.goto(self.live_server_url + reverse("messenger:chat", args=[self.direct.pk]),
                       wait_until="domcontentloaded")
        self.hidden(".sidebar")
        self.visible(".mobile-back")
        self.visible("#messageInput")
        self.visible("#mobileComposerToggle")
        self.hidden("#sendOptionsToggle")
        self.click("#mobileComposerToggle")
        self.visible("#mobileComposerTools")
        self.visible("#sendOptionsToggle")
        self.visible('#mobileComposerTools [data-compose-panel="format"]')
        self.visible('.composer__field [data-open-stickers][data-sticker-send="true"]')
        self.click("#mobileComposerToggle")
        self.hidden("#mobileComposerTools")
        self.page.locator("#messageInput").fill("Mobile test")
        self.click("#sendButton")
        self.expect(self.page.locator(".message__text").last).to_have_text("Mobile test")
        self.click(".conversation-header__identity")
        self.visible("#userProfileOverlay")
        self.expect(self.page.locator(".user-profile-overlay > .tg-profile")).to_have_css("border-radius", "0px")
        self.click("#userProfileClose")
        self.hidden("#userProfileOverlay")
        self.click(".mobile-back")
        self.visible("#profileMenuButton")
        self.visible("#sidebarComposeButton")
        self.page.set_viewport_size({"width": 1360, "height": 900})
        self.visible("#chatFilter")
        self.hidden("#sidebarComposeButton")
        self.expect(self.page.locator(".sidebar > .sidebar__footer")).to_have_count(1)

    def test_native_select_colors_follow_account_theme(self):
        from apps.accounts.two_factor import encrypt_secret
        import pyotp

        self.owner.platform_role = User.PlatformRole.OWNER
        self.owner.two_factor_secret = encrypt_secret(pyotp.random_base32())
        self.owner.save(update_fields=["platform_role", "two_factor_secret"])
        pages = [
            (reverse("administration:user_detail", args=[self.peer.pk]), 'select[name="role"]'),
            (reverse("administration:users"), 'select[name="status"]'),
            (reverse("administration:submit_report", args=["user", self.peer.pk]), 'select[name="reason"]'),
        ]
        for theme, ink, surface in (
            ("dark", "rgb(238, 229, 216)", "rgb(33, 29, 26)"),
            ("light", "rgb(42, 36, 29)", "rgb(255, 250, 241)"),
        ):
            User.objects.filter(pk=self.owner.pk).update(theme=theme)
            for path, selector in pages:
                with self.subTest(theme=theme, path=path):
                    self.page.goto(self.live_server_url + path, wait_until="domcontentloaded")
                    control = self.page.locator(selector)
                    self.expect(control).to_be_visible()
                    self.expect(control).to_have_css("color-scheme", theme)
                    self.expect(control).to_have_css("background-color", surface)
                    for option in control.locator("option").all():
                        self.expect(option).to_have_css("color", ink)
                        self.expect(option).to_have_css("background-color", surface)

    def test_contact_alias_and_channel_post_view_counter(self):
        from .models import Contact, ChannelPostView

        Contact.objects.create(owner=self.owner, user=self.peer)
        self.go(query="?profile=peer")
        self.visible("#userProfileOverlay")
        self.click("#userProfileMore")
        self.click("#userProfileRenameContact")
        self.page.locator("#userProfileAliasInput").fill("Личный контакт")
        self.click("#userProfileAliasSave")
        self.expect(self.page.locator("#userProfileName")).to_have_text("Личный контакт")
        self.visible("#userProfileOriginalNameRow")
        self.click("#userProfileClose")
        self.expect(self.page.locator(f'#chatList [data-chat-id="{self.direct.pk}"] strong')).to_have_text("Личный контакт")
        self.go(self.direct)
        self.expect(self.page.locator(".conversation-header__text strong")).to_have_text("Личный контакт")
        self.click(".conversation-header__identity")
        self.click("#userProfileMore")
        self.click("#userProfileRenameContact")
        self.click("#userProfileAliasReset")
        self.expect(self.page.locator("#userProfileName")).to_have_text("peer")
        self.hidden("#userProfileOriginalNameRow")

        post = Message.objects.create(chat=self.channel, sender=self.owner, text="Просмотры канала")
        self.go(self.channel)
        count = self.page.locator(f'#message-{post.pk} [data-channel-view-count]')
        self.expect(count).to_have_text("1", timeout=15000)
        self.page.reload(wait_until="domcontentloaded")
        self.expect(count).to_have_text("1", timeout=15000)
        self.assertEqual(ChannelPostView.objects.filter(post=post).count(), 1)
        self.manage()
        self.click('[data-community-settings-open="statistics"]')
        self.visible("#communityStatsChannel")
        self.expect(self.page.locator('[data-channel-stat="views"]')).to_have_text("1")
        self.expect(self.page.locator('[data-channel-stat="reach"]')).to_have_text("1")
        self.expect(self.page.locator("#communityStatsViews .community-stats-chart-row")).to_have_count(7)

    def test_selected_text_quote_survives_sending_and_reload(self):
        self.go(self.direct)
        source = self.page.locator(f'#message-{self.direct_message.pk} .message__text')
        source.evaluate("""element => {
            const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
            const node = walker.nextNode();
            const start = node.textContent.indexOf("direct");
            const range = document.createRange();
            range.setStart(node, start);
            range.setEnd(node, start + 6);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        }""")
        source.dispatch_event("contextmenu", {"clientX": 700, "clientY": 300, "button": 2})
        self.visible('[data-message-action="quote"]')
        self.page.wait_for_function("""() => {
            const menu = document.getElementById("messageContextMenu").getBoundingClientRect();
            const action = document.querySelector('[data-message-action="quote"]').getBoundingClientRect();
            return menu.top >= -1 && menu.left >= -1 &&
                menu.bottom <= innerHeight + 1 && menu.right <= innerWidth + 1 &&
                action.top >= 0 && action.bottom <= innerHeight;
        }""")
        self.click('[data-message-action="quote"]')
        self.expect(self.page.locator("#composerReplyPreview")).to_have_text("direct")
        self.page.locator("#messageInput").fill("Reply with a quote")
        self.click("#sendButton")
        self.expect(self.page.locator(".message-reply-quote")).to_have_text("direct")
        self.hidden("#composerReply")
        self.page.reload(wait_until="domcontentloaded")
        self.expect(self.page.locator(".message-reply-quote")).to_have_text("direct")

    def test_foreign_profile_controls(self):
        self.go(query="?profile=peer")
        self.visible("#userProfileOverlay")
        self.visible("#userProfileMessage")
        self.visible("#userProfileMute")
        self.visible("#userProfileContact")
        self.visible("#userProfileCommonGroups")
        self.expect(self.page.locator("#userProfileCommonGroupsLabel")).to_have_text("1 общая группа")
        self.click("#userProfileCommonGroups summary")
        self.expect(self.page.locator("#userProfileCommonGroupsList a")).to_have_text("UI test group")
        self.click("#userProfileContact")
        self.expect(self.page.locator("#userProfileContactLabel")).to_have_text("Удалить контакт")
        self.click("#userProfileMute")
        self.click('#userProfileMuteMenu [data-peer-mute="forever"]')
        self.expect(self.page.locator("#userProfileMuteLabel")).to_have_text("Без звука")
        self.click("#userProfileMore")
        self.click("#userProfileAutoDelete")
        self.click('#userProfileTimerOptions [data-peer-timer="86400"]')
        self.expect(self.page.locator("#userProfileAutoDeleteLabel")).to_have_text("Автоудаление · 1 день")
        self.click("#userProfileMore")
        self.click("#userProfileProtection")
        self.expect(self.page.locator("#userProfileProtectionLabel")).to_have_text("Разрешить копирование")
        self.click("#userProfileBlock")
        self.expect(self.page.locator("#userProfileBlockLabel")).to_have_text("Разблокировать")
        self.click("#userProfileBlock")
        self.expect(self.page.locator("#userProfileBlockLabel")).to_have_text("Заблокировать")
        self.click("#userProfileMore")
        self.visible("#userProfileReport")
        self.page.keyboard.press("Escape")
        self.hidden("#userProfileMoreMenu")
        self.visible("#userProfileOverlay")
        self.click("#userProfileClose")
        self.hidden("#userProfileOverlay")
        self.go(query="?profile=other")
        self.visible("#userProfileMessage")
        self.hidden("#userProfileMute")
        self.hidden("#userProfileCommonGroups")
        self.click("#userProfileMore")
        self.hidden("#userProfileAutoDelete")
        self.hidden("#userProfileProtection")

    def test_two_factor_enrollment_and_recovery_login(self):
        import pyotp

        self.go(query="?settings=privacy")
        self.click('a[href="' + reverse("accounts:two_factor") + '"]')
        self.page.locator('input[name="password"]').fill("Password-1945!")
        self.page.get_by_role("button",name="Настроить двухфакторную защиту").click()
        self.visible("#totpSetupSecret")
        secret = self.page.locator("#totpSetupSecret").input_value()
        self.page.locator('input[name="otp"]').fill(pyotp.TOTP(secret).now())
        self.page.get_by_role("button",name="Включить защиту").click()
        self.visible("#recoveryCodes")
        codes = self.page.locator("#recoveryCodes").inner_text().split()
        self.assertEqual(len(codes),10)
        self.page.get_by_role("link",name="Я сохранил коды").click()
        self.expect(self.page).to_have_url(self.live_server_url + reverse("messenger:home"))
        self.visible("#profileMenuButton")
        self.page.goto(self.live_server_url + reverse("accounts:two_factor"))
        self.expect(self.page.locator("#recoveryRemaining")).to_have_text("10")
        self.context.clear_cookies()
        self.page.goto(self.live_server_url + reverse("accounts:login"))
        self.page.locator("#id_username").fill(self.owner.username)
        self.page.locator("#id_password").fill("Password-1945!")
        self.page.get_by_role("button",name="Войти",exact=True).click()
        self.visible("#id_otp")
        self.page.locator("#id_password").fill("Password-1945!")
        self.page.locator("#id_otp").fill(codes[0])
        self.page.get_by_role("button",name="Войти",exact=True).click()
        self.visible("#profileMenuButton")
        self.page.goto(self.live_server_url + reverse("accounts:two_factor"))
        self.expect(self.page.locator("#recoveryRemaining")).to_have_text("9")

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
        self.expect(self.page.locator("#notificationPreferencesStatus")).to_contain_text("Настройки синхронизируются")
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.notification_preferences["mention"])
        self.assertFalse(self.owner.notification_preferences["badge"])
        self.page.reload(wait_until="domcontentloaded")
        self.visible('[data-settings-screen="notifications"]')
        self.expect(self.page.locator(mention)).not_to_be_checked()
        self.expect(self.page.locator(badge)).not_to_be_checked()
        self.click("#settingsSectionBack")
        self.visible('[data-settings-screen="main"]')

    def test_account_storage_preference_and_safe_cache_cleanup(self):
        self.go(query="?settings=main")
        self.click('#telegramSettings a[href="' + reverse("accounts:storage") + '"]')
        self.visible(".storage-page")
        self.page.locator("#id_media_preload").uncheck()
        self.click(".storage-page button[type=submit]")
        self.expect(self.page.locator("#id_media_preload")).not_to_be_checked()
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.media_preload)
        self.page.evaluate("""async () => {
            const cache = await caches.open("sovietgram-public-shell-test");
            await cache.put("/offline/", new Response("public"));
            const unrelated = await caches.open("unrelated-test");
            await unrelated.put("/unrelated", new Response("keep"));
            localStorage.setItem("sovietgram.storage.test", "keep");
        }""")
        # Reload once so the inventory observes the seeded cache.
        self.page.reload(wait_until="domcontentloaded")
        self.visible("#storageClearCache")
        # The service worker may remove old versioned public caches on
        # activation; its current shell is also safe to delete.
        self.expect(self.page.locator("#storageClearCache")).to_be_enabled()
        self.click("#storageClearCache")
        self.expect(self.page.locator("#storageCacheStatus")).to_contain_text("Публичный кэш очищен")
        self.assertTrue(self.page.evaluate("""async () =>
            (await caches.has("unrelated-test")) &&
            localStorage.getItem("sovietgram.storage.test") === "keep"
        """))
        self.go(self.direct)
        self.expect(self.page.locator("body")).to_have_attribute("data-media-preload", "false")

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
