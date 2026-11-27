"""Date-only deadlines for collaborative checklists."""
from datetime import date
import re


def clean_due_date(value):
    if value in ("", None):
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Укажите дату в формате ГГГГ-ММ-ДД.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("Укажите существующую календарную дату.") from None


def task_payload(task, today):
    try:
        due = clean_due_date(task.get("due_date"))
    except ValueError:
        due = ""
    return {
        "due_date": due,
        "due_label": f"{due[8:10]}.{due[5:7]}.{due[:4]}" if due else "",
        "overdue": bool(due and due < today.isoformat() and not task.get("done")),
    }
