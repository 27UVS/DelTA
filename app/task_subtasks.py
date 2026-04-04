from __future__ import annotations

import uuid
from typing import Any


def get_subtasks_from_task(task: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Parse subtasks list from task dict (backward compatible)."""
    if not isinstance(task, dict):
        return []
    raw = task.get("subtasks")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        sid = str(x.get("id") or uuid.uuid4().hex)
        title = str(x.get("title") or "").strip()
        if not title:
            continue
        done = bool(x.get("done", False))
        ids = [str(i) for i in (x.get("responsible_subject_ids") or []) if i]
        rid = str(x.get("responsible_subject_id") or "")
        if not ids and rid:
            ids = [rid]
        if not ids:
            continue
        rid = ids[0]
        out.append(
            {
                "id": sid,
                "title": title,
                "done": done,
                "responsible_subject_id": rid,
                "responsible_subject_ids": ids[:1],
            }
        )
    return out


def subtasks_done_count(subtasks: list[dict[str, Any]]) -> int:
    return sum(1 for s in subtasks if bool(s.get("done")))


def subtasks_sequential_dones_flags(subtasks_ordered: list[dict[str, Any]]) -> list[bool]:
    """Canonical done flags: after the first incomplete item, all are False."""
    out: list[bool] = []
    seen_incomplete = False
    for s in subtasks_ordered:
        d = bool(s.get("done"))
        if seen_incomplete:
            out.append(False)
        else:
            out.append(d)
            if not d:
                seen_incomplete = True
    return out


def validate_subtasks_sequential_order(subtasks_ordered: list[dict[str, Any]]) -> None:
    """Raise ValueError if any item is done while an earlier item is not done."""
    seen_incomplete = False
    for s in subtasks_ordered:
        done = bool(s.get("done"))
        if done and seen_incomplete:
            raise ValueError(
                "Подзадачи выполняются по порядку: сначала завершите предыдущие пункты цепочки. "
                "Нельзя отметить выполненным следующий, если выше в списке есть невыполненные."
            )
        if not done:
            seen_incomplete = True


def normalize_subtask_row(*, title: str, responsible_id: str, done: bool, existing_id: str | None) -> dict[str, Any]:
    rid = str(responsible_id).strip()
    if not rid:
        raise ValueError("empty responsible")
    t = str(title).strip()
    if not t:
        raise ValueError("empty subtask title")
    return {
        "id": str(existing_id or uuid.uuid4().hex),
        "title": t,
        "done": bool(done),
        "responsible_subject_id": rid,
        "responsible_subject_ids": [rid],
    }


def get_subtasks_max_per_row_from_ui(ui: dict[str, Any]) -> int:
    try:
        v = int(ui.get("subtasks_max_per_row", 6))
    except Exception:
        v = 6
    return max(2, min(24, v))
