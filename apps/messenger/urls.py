from django.urls import path

from . import views

app_name = "messenger"

urlpatterns = [
    path("", views.home, name="home"),
    path("contacts/", views.contacts, name="contacts"),
    path("contacts/<str:username>/add/", views.add_contact, name="add_contact"),
    path("contacts/<str:username>/remove/", views.remove_contact, name="remove_contact"),
    path("saved/", views.saved_messages, name="saved_messages"),
    path("chat/start/<str:username>/", views.start_chat, name="start_chat"),
    path("chat/<int:chat_id>/", views.chat_detail, name="chat"),
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
