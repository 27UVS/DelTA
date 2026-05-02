from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer

from app.duration_display import format_approx_ymd
from app.storage import Storage, APP_TZ


def _parse_iso(s: str | None) -> datetime | None:
    if not s or not str(s).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(s).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
    except Exception:
        return None


def _calendar_days_since(anchor: datetime, now: datetime) -> int:
    ad = anchor.astimezone(APP_TZ).date()
    nd = now.astimezone(APP_TZ).date()
    return (nd - ad).days


def _minute_bucket(dt: datetime) -> str:
    d = dt.astimezone(APP_TZ).replace(second=0, microsecond=0)
    return d.isoformat(timespec="minutes")


def _task_time_sig(t: dict[str, Any]) -> str:
    return "|".join(
        [
            str(t.get("start_due") or ""),
            str(t.get("end_due") or ""),
            str(bool(t.get("no_deadline", False))),
            str(bool(t.get("recurring", False))),
            str(t.get("created_at") or ""),
        ]
    )


def _responsible_phrase(storage: Storage, task: dict[str, Any]) -> str:
    prof = storage.get_profile()
    admin_name = str(prof.get("nickname", "Администратор"))
    ids = [str(x) for x in (task.get("responsible_subject_ids") or []) if x]
    if not ids:
        rid = task.get("responsible_subject_id")
        if rid:
            ids = [str(rid)]
    if not ids:
        return "—"
    subjects = storage.get_subjects()
    # Subjects store display text in "nickname" (same as board / dialogs); "name" is legacy/abscent.
    id_to_name = {
        str(s.get("id")): str(s.get("nickname") or s.get("name") or "").strip()
        for s in subjects
    }
    parts: list[str] = []
    for i in ids:
        if i == "__admin__":
            parts.append(admin_name)
        else:
            nm = (id_to_name.get(i) or "").strip()
            # If the subject is missing from subjects.json (deleted / old id).
            parts.append(nm if nm else f"(удалён: {i})")
    return ", ".join([p for p in parts if str(p).strip()]) or "—"


def _show_windows_toast(title: str, message: str) -> None:
    from app.win_notify_bridge import show_task_toast

    show_task_toast(title, message)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "tasks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "tasks": {}}
        if "tasks" not in data or not isinstance(data["tasks"], dict):
            data["tasks"] = {}
        return data
    except Exception:
        return {"version": 1, "tasks": {}}


class TaskBackgroundNotifier(QObject):
    """
    Windows toast reminders for tasks in column «В процессе» while the app runs
    (including «hidden» mode when full_shutdown is off).
    """

    def __init__(self, storage: Storage, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._storage = storage
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        profile = self._storage.get_profile()
        if bool(profile.get("full_shutdown", True)):
            return
        period = int(profile.get("task_notify_interval_days", 7) or 7)
        period = max(1, min(30, period))

        state_path = self._storage.paths.task_notify_state_path
        state = _load_state(state_path)
        tasks_map: dict[str, Any] = state.setdefault("tasks", {})

        progress = self._storage.load_tasks("progress")
        seen: set[str] = set()
        dirty = False
        now = datetime.now(APP_TZ)
        bucket = _minute_bucket(now)

        for task in progress:
            tid = str(task.get("id") or "")
            if not tid:
                continue
            seen.add(tid)
            sig = _task_time_sig(task)
            entry = tasks_map.get(tid)
            if not isinstance(entry, dict):
                entry = {}
                tasks_map[tid] = entry
            if entry.get("sig") != sig:
                entry.clear()
                entry["sig"] = sig
                dirty = True

            title = str(task.get("title") or "Задание").strip() or "Задание"
            resp = _responsible_phrase(self._storage, task)

            no_deadline = bool(task.get("no_deadline", False))
            end_raw = str(task.get("end_due") or "").strip()
            end_dt = _parse_iso(end_raw) if (not no_deadline and end_raw) else None
            has_deadline = end_dt is not None
            start_raw = str(task.get("start_due") or "").strip()
            start_dt = _parse_iso(start_raw) if start_raw else None
            created_dt = _parse_iso(str(task.get("created_at") or ""))

            if has_deadline and end_dt is not None:
                dirty |= self._handle_deadline_task(
                    entry, title=title, resp=resp, now=now, bucket=bucket, deadline=end_dt, period=period
                )
            else:
                anchor = start_dt or created_dt or now
                dirty |= self._handle_no_deadline_task(
                    entry, title=title, resp=resp, now=now, bucket=bucket, anchor=anchor, period=period
                )

        # Drop state for tasks that left «В процессе».
        for tid in list(tasks_map.keys()):
            if tid not in seen:
                tasks_map.pop(tid, None)
                dirty = True

        if dirty:
            _atomic_write_json(state_path, state)

    def _fired(self, entry: dict[str, Any], key: str, bucket: str) -> bool:
        return str(entry.get(key) or "") == bucket

    def _mark(self, entry: dict[str, Any], key: str, bucket: str) -> bool:
        if str(entry.get(key) or "") == bucket:
            return False
        entry[key] = bucket
        return True

    def _handle_no_deadline_task(
        self,
        entry: dict[str, Any],
        *,
        title: str,
        resp: str,
        now: datetime,
        bucket: str,
        anchor: datetime,
        period: int,
    ) -> bool:
        """Periodic reminders from startline (or created_at), same clock as anchor each day."""
        passed = _calendar_days_since(anchor, now)
        if passed <= 0:
            return False
        if passed % period != 0:
            return False
        if now.hour != anchor.hour or now.minute != anchor.minute:
            return False
        key = f"nd:{period}"
        if self._fired(entry, key, bucket):
            return False
        body = f"Задание {title}, выполняемое {resp}, находится в работе уже {format_approx_ymd(passed)}"
        _show_windows_toast("DelTA — задания", body)
        return self._mark(entry, key, bucket)

    def _handle_deadline_task(
        self,
        entry: dict[str, Any],
        *,
        title: str,
        resp: str,
        now: datetime,
        bucket: str,
        deadline: datetime,
        period: int,
    ) -> bool:
        dirty = False
        dl_min = _minute_bucket(deadline)

        # One-shot: reached deadline (same minute as deadline's local time).
        if bucket == dl_min and now >= deadline.replace(second=0, microsecond=0):
            k_dead = "deadline_hit"
            if not self._fired(entry, k_dead, dl_min):
                body = f"Срок задания {title}, выполняемое {resp}, подошел к концу!"
                _show_windows_toast("DelTA — задания", body)
                dirty |= self._mark(entry, k_dead, dl_min)

        # After deadline: repeats every `period` calendar days from deadline date, at deadline clock.
        if now <= deadline:
            return dirty

        overdue_days = _calendar_days_since(deadline, now)
        if overdue_days <= 0:
            return dirty
        if overdue_days % period != 0:
            return dirty
        if now.hour != deadline.hour or now.minute != deadline.minute:
            return dirty

        k_od = f"od:{period}"
        if self._fired(entry, k_od, bucket):
            return dirty
        body = f"Задание {title}, выполняемое {resp}, просрочено на {format_approx_ymd(overdue_days)}"
        _show_windows_toast("DelTA — задания", body)
        dirty |= self._mark(entry, k_od, bucket)
        return dirty
