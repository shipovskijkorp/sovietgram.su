"""Authenticated account-scoped folder CRUD and explicit membership management."""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from . import views
from .folder_rules import CATEGORIES, MAX_CHATS, MAX_FOLDERS, decorate_folder_categories
from .models import ChatFolder, ChatParticipant
from .ratelimit import rate_limit


def error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def serialize(folder, allowed):
    return {
        "id": folder.pk, "name": folder.name, "revision": folder.revision,
        "categories": folder.categories,
        "included": [pk for pk in folder.included_chat_ids if pk in allowed],
        "excluded": [pk for pk in folder.excluded_chat_ids if pk in allowed],
        "pinned": [pk for pk in folder.pinned_chat_ids if pk in allowed],
        "exclude_muted": folder.exclude_muted, "exclude_read": folder.exclude_read,
        "exclude_archived": folder.exclude_archived,
    }


def parse_ids(value, allowed):
    if not isinstance(value, list) or len(value) > MAX_CHATS:
        raise ValueError("В списке может быть не более 200 чатов.")
    if any(type(pk) is not int or pk not in allowed for pk in value):
        raise ValueError("Один из выбранных чатов недоступен.")
    return list(dict.fromkeys(value))


def parse_config(payload, allowed):
    name = payload.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32 or any(ord(c) < 32 for c in name):
        raise ValueError("Название папки должно содержать от 1 до 32 символов.")
    categories = payload.get("categories")
    if not isinstance(categories, list) or any(not isinstance(c, str) or c not in CATEGORIES for c in categories):
        raise ValueError("Некорректные категории.")
    included = parse_ids(payload.get("included"), allowed)
    excluded = parse_ids(payload.get("excluded"), allowed)
    if set(included) & set(excluded):
        raise ValueError("Чат нельзя одновременно включить и исключить.")
    flags = {}
    for key in ("exclude_muted", "exclude_read", "exclude_archived"):
        value = payload.get(key)
        if type(value) is not bool:
            raise ValueError("Некорректные фильтры.")
        flags[key] = value
    return {"name": name.strip(), "categories": list(dict.fromkeys(categories)),
            "included_chat_ids": included, "excluded_chat_ids": excluded, **flags}


@login_required
@require_http_methods(["GET", "POST"])
@rate_limit("chat_folders")
def chat_folders(request):
    if request.method == "GET":
        if request.GET.get("account_id", str(request.user.pk)) != str(request.user.pk):
            return error("Аккаунт изменился. Обновите страницу.", 409)
        chats = views._prepare_sidebar_chats(request.user, False) + views._prepare_sidebar_chats(request.user, True)
        decorate_folder_categories(chats, request.user)
        allowed = {chat.pk for chat in chats}
        response = JsonResponse({
            "ok": True, "account_id": request.user.pk,
            "folders": [serialize(folder, allowed) for folder in ChatFolder.objects.filter(owner=request.user)],
            "chats": [{"id": chat.pk, "name": chat.display_name_ui,
                       "category": chat.folder_category_ui, "archived": chat.is_archived_ui,
                       "muted": chat.is_muted_ui, "unread": chat.has_unread_ui}
                      for chat in chats],
        })
        response["Cache-Control"] = "private, no-store"
        return response

    if request.POST.get("account_id") != str(request.user.pk):
        return error("Аккаунт изменился. Обновите страницу.", 409)
    action = request.POST.get("action", "")
    try:
        payload = json.loads(request.POST.get("payload", "{}"))
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, TypeError):
        return error("Некорректные данные папки.")
    with transaction.atomic():
        get_user_model().objects.select_for_update().only("id").get(pk=request.user.pk)
        rows = list(ChatFolder.objects.select_for_update().filter(owner=request.user))
        allowed = set(ChatParticipant.objects.filter(
            user=request.user, is_hidden=False,
        ).values_list("chat_id", flat=True))
        folder = None
        if action != "create":
            pk = payload.get("id")
            folder = next((row for row in rows if type(pk) is int and row.pk == pk), None)
            if folder is None:
                return error("Папка недоступна.", 404)
            if payload.get("revision") != folder.revision:
                return error("Папка уже изменена. Обновите список.", 409)
        try:
            if action == "create":
                if len(rows) >= MAX_FOLDERS:
                    return error("Можно создать до 20 папок.")
                config = parse_config(payload, allowed)
                if any(row.name.casefold() == config["name"].casefold() for row in rows):
                    return error("Папка с таким названием уже существует.")
                folder = ChatFolder.objects.create(owner=request.user, position=len(rows), **config)
            elif action == "edit":
                config = parse_config(payload, allowed)
                if any(row.pk != folder.pk and row.name.casefold() == config["name"].casefold() for row in rows):
                    return error("Папка с таким названием уже существует.")
                for key, value in config.items():
                    setattr(folder, key, value)
                folder.pinned_chat_ids = [pk for pk in folder.pinned_chat_ids
                                          if pk in allowed and pk not in folder.excluded_chat_ids]
                folder.revision += 1
                folder.save(update_fields=[*config, "pinned_chat_ids", "revision"])
            elif action == "delete":
                folder.delete()
                for position, row in enumerate(item for item in rows if item.pk != payload["id"]):
                    if row.position != position:
                        row.position = position
                        row.revision += 1
                        row.save(update_fields=["position", "revision"])
                return JsonResponse({"ok": True, "deleted": payload["id"]})
            elif action in ("move_up", "move_down"):
                index = rows.index(folder)
                other = index + (-1 if action == "move_up" else 1)
                if 0 <= other < len(rows):
                    rows[index], rows[other] = rows[other], rows[index]
                    for position, row in enumerate(rows):
                        if row.position != position:
                            row.position = position
                            row.revision += 1
                            row.save(update_fields=["position", "revision"])
            elif action == "membership":
                chat_id = payload.get("chat_id")
                mode = payload.get("mode")
                if type(chat_id) is not int or chat_id not in allowed or mode not in ("auto", "include", "exclude"):
                    return error("Некорректное действие с чатом.")
                included = [pk for pk in folder.included_chat_ids if pk != chat_id and pk in allowed]
                excluded = [pk for pk in folder.excluded_chat_ids if pk != chat_id and pk in allowed]
                if mode == "include":
                    included.append(chat_id)
                elif mode == "exclude":
                    excluded.append(chat_id)
                if len(included) > MAX_CHATS or len(excluded) > MAX_CHATS:
                    return error("Достигнут предел в 200 чатов.")
                folder.included_chat_ids, folder.excluded_chat_ids = included, excluded
                if mode == "exclude":
                    folder.pinned_chat_ids = [pk for pk in folder.pinned_chat_ids if pk != chat_id]
                folder.revision += 1
                folder.save(update_fields=["included_chat_ids", "excluded_chat_ids", "pinned_chat_ids", "revision"])
            else:
                return error("Неизвестное действие.")
        except ValueError as exc:
            return error(str(exc))
        return JsonResponse({"ok": True, "folder": serialize(folder, allowed)})
