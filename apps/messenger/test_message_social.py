"""Persistent reactions, mention lookup and whole-token search."""
from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.lifecycle import delete_user_account
from apps.accounts.models import User, UserBlock
from .models import Chat, ChatParticipant, Message, MessageHiddenForUser, MessageReaction, ChatMemberModeration, ChatAdminLog
from .services import get_or_create_direct_chat


class MessageSocialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "other@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.message = Message.objects.create(chat=self.chat, sender=self.bob, text="Привет")
        self.url = reverse("messenger:message_reaction", args=[self.chat.pk, self.message.pk])

    def react(self, emoji, client=None, url=None):
        return (client or self.client).post(url or self.url, {"emoji": emoji})

    def test_reactions_are_idempotent_and_replace_or_remove_previous(self):
        first = self.react("👍").json()
        self.assertEqual(first["reactions"], [{"emoji": "👍", "count": 1, "selected": True}])
        self.assertEqual(first["reaction_version"], 1)
        self.assertEqual(self.react("👍").json(), first)
        changed = self.react("🔥").json()
        self.assertEqual(changed["reaction_version"], 2)
        self.assertEqual(changed["reactions"], [{"emoji": "🔥", "count": 1, "selected": True}])
        self.assertEqual(MessageReaction.objects.filter(message=self.message).count(), 1)
        removed = self.react("").json()
        self.assertEqual(removed["reaction_version"], 3)
        self.assertEqual(removed["reactions"], [])
        self.assertEqual(self.react("").json(), removed)
        self.assertEqual(self.react("invalid").status_code, 400)
        self.assertEqual(self.client.post(self.url).status_code, 400)

    def test_counts_are_shared_but_selection_is_personal(self):
        peer = Client()
        peer.force_login(self.bob)
        self.react("❤️")
        self.assertEqual(self.react("❤️", peer).json()["reactions"], [
            {"emoji": "❤️", "count": 2, "selected": True},
        ])
        self.react("🔥", peer)
        history = self.client.get(reverse("messenger:message_history", args=[self.chat.pk])).json()
        self.assertEqual(history["messages"][0]["reactions"], [
            {"emoji": "❤️", "count": 1, "selected": True},
            {"emoji": "🔥", "count": 1, "selected": False},
        ])
        response = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(response, 'data-message-reaction="❤️"')
        self.assertContains(response, 'data-pick-reaction="🔥"')
        self.assertContains(response, self.url)

    def test_reaction_poll_updates_do_not_report_content_changes(self):
        start = timezone.now() - timedelta(seconds=1)
        original_updated = self.message.updated_at
        self.react("😂")
        self.message.refresh_from_db()
        self.assertEqual(self.message.updated_at, original_updated)
        self.assertIsNotNone(self.message.reaction_changed_at)
        peer = Client()
        peer.force_login(self.bob)
        payload = peer.get(reverse("messenger:poll_messages", args=[self.chat.pk]), {
            "after": self.message.pk, "since": (timezone.now() + timedelta(seconds=1)).isoformat(),
            "reaction_since": start.isoformat(),
        }).json()
        self.assertEqual(payload["updates"], [])
        self.assertEqual(payload["reaction_updates"], [{
            "message_id": self.message.pk, "reaction_version": 1,
            "reactions": [{"emoji": "😂", "count": 1, "selected": False}],
        }])
        self.assertIn("reaction_cursor_time", payload)

    def test_reaction_permissions_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        outsider = Client()
        outsider.force_login(self.outsider)
        self.assertEqual(self.react("👍", outsider).status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.alice)
        self.assertEqual(self.react("👍", csrf_client).status_code, 403)
        MessageHiddenForUser.objects.create(message=self.message, user=self.alice)
        self.assertEqual(self.react("👍").status_code, 404)
        self.assertFalse(MessageReaction.objects.exists())

    def test_blocked_private_chat_rejects_new_reactions(self):
        self.react("👍")
        UserBlock.objects.create(blocker=self.bob, blocked=self.alice)
        self.assertEqual(self.react("🔥").status_code, 403)
        self.assertEqual(self.react("").status_code, 200)

    def test_read_only_channel_member_can_react(self):
        channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="Channel")
        ChatParticipant.objects.create(chat=channel, user=self.bob, role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=channel, user=self.alice)
        message = Message.objects.create(chat=channel, sender=self.bob, text="News")
        url = reverse("messenger:message_reaction", args=[channel.pk, message.pk])
        self.assertEqual(self.react("❤️", url=url).status_code, 200)

    def test_deleted_message_rejects_reactions_and_removes_existing(self):
        self.react("👍")
        peer = Client()
        peer.force_login(self.bob)
        response = peer.post(reverse("messenger:delete_message", args=[self.chat.pk, self.message.pk]), {
            "scope": "everyone",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.react("👍").status_code, 404)
        self.assertFalse(MessageReaction.objects.filter(message=self.message).exists())

    def test_deleted_account_removes_reaction_from_surviving_group_message(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        ChatParticipant.objects.create(chat=group, user=self.bob, role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=group, user=self.alice)
        message = Message.objects.create(chat=group, sender=self.bob, text="Survives")
        self.react("🔥", url=reverse("messenger:message_reaction", args=[group.pk, message.pk]))
        delete_user_account(self.alice)
        message.refresh_from_db()
        self.assertEqual(message.reaction_version, 2)
        self.assertFalse(message.reactions.exists())

    def test_mentions_only_suggest_accessible_active_chat_members(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        ChatParticipant.objects.create(chat=group, user=self.alice)
        ChatParticipant.objects.create(chat=group, user=self.bob)
        url = reverse("messenger:mention_candidates", args=[group.pk])
        self.assertEqual(self.client.get(url, {"q": "bo"}).json()["results"], [
            {"username": self.bob.username, "display_name": self.bob.display_name},
        ])
        self.assertEqual(self.client.get(url, {"q": "out"}).json()["results"], [])
        outsider = Client()
        outsider.force_login(self.outsider)
        self.assertEqual(outsider.get(url).status_code, 404)
        UserBlock.objects.create(blocker=self.bob, blocked=self.alice)
        self.assertEqual(self.client.get(url).json()["results"], [])

    def test_hashtag_and_mention_search_use_whole_tokens_and_visibility(self):
        exact = Message.objects.create(chat=self.chat, sender=self.bob, text="Hello @alice, #Новости!")
        Message.objects.create(chat=self.chat, sender=self.bob, text="Hello @alice2 #Новости2")
        Message.objects.create(chat=self.chat, sender=self.bob, text="alice@alice.example")
        hidden = Message.objects.create(chat=self.chat, sender=self.bob, text="#новости @alice")
        MessageHiddenForUser.objects.create(message=hidden, user=self.alice)
        search = reverse("messenger:search_messages", args=[self.chat.pk])
        for query in ("#новости", "@alice"):
            with self.subTest(query=query):
                self.assertEqual([item["id"] for item in self.client.get(search, {"q": query}).json()["results"]], [exact.pk])
                global_results = self.client.get(reverse("messenger:global_search"), {"q": query}).json()["messages"]
                self.assertEqual([item["id"] for item in global_results], [exact.pk])


    def test_community_reaction_configuration_and_individual_restrictions(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Restricted")
        ChatParticipant.objects.create(chat=group, user=self.bob, role="owner")
        ChatParticipant.objects.create(chat=group, user=self.alice)
        ChatParticipant.objects.create(chat=group, user=self.outsider, role="admin", admin_permissions=[])
        msg = Message.objects.create(chat=group, sender=self.bob, text="News")
        url = reverse("messenger:message_reaction", args=[group.pk,msg.pk])
        settings_url = reverse("messenger:community_settings", args=[group.pk])
        owner = Client()
        owner.force_login(self.bob)
        admin = Client()
        admin.force_login(self.outsider)
        self.assertEqual(self.react("🔥",url=url).status_code,200)
        values = {"section":"reactions","reactions":'["👍"]'}
        self.assertEqual(self.client.post(settings_url,values).status_code,403)
        self.assertEqual(admin.post(settings_url,values).status_code,403)
        self.assertEqual(owner.post(settings_url, {"section":"reactions","reactions":'["bad"]'}).status_code,400)
        result = owner.post(settings_url, values)
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()["settings"]["allowed_reactions"],["👍"])
        self.assertEqual(self.react("❤️",url=url).status_code,403)
        self.assertEqual(self.react("",url=url).status_code,200)
        self.assertEqual(self.react("👍",url=url).status_code,200)
        payload = self.client.get(reverse("messenger:poll_messages",args=[group.pk])).json()
        self.assertEqual(payload["allowed_reactions"],["👍"])
        sanction = ChatMemberModeration.objects.create(chat=group,user=self.alice,denied_permissions=["react"])
        self.assertEqual(self.react("👍",url=url).status_code,403)
        self.assertEqual(self.react("",url=url).status_code,200)
        sanction.delete()
        self.assertEqual(owner.post(settings_url, {"section":"reactions","reactions":"[]"}).status_code,200)
        self.assertEqual(self.react("👍",url=url).status_code,403)
        self.assertTrue(ChatAdminLog.objects.filter(chat=group,action="reactions").exists())

    def test_reactor_list_respects_membership_filters_and_channel_anonymity(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Reactors")
        ChatParticipant.objects.create(chat=group,user=self.alice,role="owner")
        ChatParticipant.objects.create(chat=group,user=self.bob)
        message = Message.objects.create(chat=group,sender=self.alice,text="Group")
        MessageReaction.objects.create(message=message,user=self.bob,emoji="🔥")
        MessageReaction.objects.create(message=message,user=self.alice,emoji="👍")
        url = reverse("messenger:message_reactors",args=[group.pk,message.pk])
        data = self.client.get(url,{"emoji":"🔥"}).json()
        self.assertEqual(data["reactors"],[{"name":"bob","username":"bob","emoji":"🔥"}])
        self.assertEqual(data["visible_total"],1)
        self.assertEqual(len(data["counts"]),2)
        self.assertEqual(self.client.get(url,{"account_id":self.bob.pk}).status_code,409)
        outsider = Client()
        outsider.force_login(self.outsider)
        self.assertEqual(outsider.get(url).status_code,404)
        ChatParticipant.objects.filter(chat=group,user=self.bob).delete()
        self.assertEqual(self.client.get(url,{"emoji":"🔥"}).json()["reactors"],[])
        group.type = Chat.Type.CHANNEL
        group.save(update_fields=["type"])
        result = self.client.get(url).json()
        self.assertTrue(result["anonymous"])
        self.assertEqual(result["reactors"],[])
        self.assertEqual(sum(row["count"] for row in result["counts"]),2)
        MessageHiddenForUser.objects.create(message=message,user=self.alice)
        self.assertEqual(self.client.get(url).status_code,404)
