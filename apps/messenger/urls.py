from django.urls import path

from . import community_profiles, views

app_name = "messenger"

urlpatterns = [
    path("", views.home, name="home"),
    path("contacts/", views.contacts, name="contacts"),
    path("create/", views.create_community, name="create_community"),
    path("join/<str:username>/", views.join_public_chat, name="join_public_chat"),
    path("invite/<str:token>/", community_profiles.join_invite, name="join_invite"),
    path("contacts/<str:username>/add/", views.add_contact, name="add_contact"),
    path("contacts/<str:username>/remove/", views.remove_contact, name="remove_contact"),
    path("saved/", views.saved_messages, name="saved_messages"),
    path("calls/", views.calls, name="calls"),
    path("chat/start/<str:username>/", views.start_chat, name="start_chat"),
    path("chat/<int:chat_id>/", views.chat_detail, name="chat"),
    path("chat/<int:chat_id>/profile/", community_profiles.community_profile, name="community_profile"),
    path("chat/<int:chat_id>/profile/settings/", community_profiles.community_settings, name="community_settings"),
    path("chat/<int:chat_id>/profile/invites/", community_profiles.community_invite_action, name="community_invite_action"),
    path("chat/<int:chat_id>/profile/update/", community_profiles.community_profile_update, name="community_profile_update"),
    path("chat/<int:chat_id>/profile/members/", community_profiles.community_member_action, name="community_member_action"),
    path("chat/<int:chat_id>/profile/member-candidates/", community_profiles.community_member_candidates, name="community_member_candidates"),
    path("chat/<int:chat_id>/profile/action/", community_profiles.community_profile_action, name="community_profile_action"),
    path("chat/<int:chat_id>/send/", views.send_message, name="send_message"),
    path("chat/<int:chat_id>/poll/", views.poll_messages, name="poll_messages"),
    path("chat/<int:chat_id>/search/", views.search_messages, name="search_messages"),
    path("chat/<int:chat_id>/draft/", views.save_draft, name="save_draft"),
    path("chat/<int:chat_id>/typing/", views.typing, name="typing"),
    path("chat/<int:chat_id>/action/", views.chat_action, name="chat_action"),
    path("chat/<int:chat_id>/message/<int:message_id>/edit/", views.edit_message, name="edit_message"),
    path("chat/<int:chat_id>/message/<int:message_id>/delete/", views.delete_message, name="delete_message"),
    path("chat/<int:chat_id>/message/<int:message_id>/forward/", views.forward_message, name="forward_message"),
    path("chat/<int:chat_id>/message/<int:message_id>/pin/", views.pin_message, name="pin_message"),
    path("attachment/<int:attachment_id>/view/", views.view_attachment, name="view_attachment"),
    path("attachment/<int:attachment_id>/download/", views.download_attachment, name="download_attachment"),
]
