from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QThread, Signal

from app.app_paths import AppPaths

TASK_KINDS = ("draft", "progress", "finished", "delayed")


def _read_json_file(path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


def load_board_files(paths: AppPaths) -> dict[str, Any]:
    """Read all board-related JSON from disk (runs in a worker thread; no Qt UI)."""
    tasks_by_kind: dict[str, list[dict[str, Any]]] = {}
    mapping = {
        "draft": paths.tasks_draft_path,
        "progress": paths.tasks_progress_path,
        "finished": paths.tasks_finished_path,
        "delayed": paths.tasks_delayed_path,
    }
    for kind in TASK_KINDS:
        doc = _read_json_file(mapping[kind], {"tasks": []})
        tasks = doc.get("tasks", []) if isinstance(doc, dict) else []
        tasks_by_kind[kind] = list(tasks)

    subjects_doc = _read_json_file(paths.subjects_path, {"subjects": []})
    subjects = subjects_doc.get("subjects", []) if isinstance(subjects_doc, dict) else []

    profile = _read_json_file(paths.profile_path, default={})
    if not isinstance(profile, dict):
        profile = {}

    roles_doc = _read_json_file(paths.roles_path, {"roles": []})
    if not isinstance(roles_doc, dict):
        roles_doc = {"roles": []}

    statuses_doc = _read_json_file(paths.statuses_path, {"statuses": []})
    if not isinstance(statuses_doc, dict):
        statuses_doc = {"statuses": []}

    people_settings_doc = _read_json_file(paths.people_settings_path, {"people": {}})
    if not isinstance(people_settings_doc, dict):
        people_settings_doc = {"people": {}}

    return {
        "tasks_by_kind": tasks_by_kind,
        "subjects": subjects,
        "profile": profile,
        "roles_doc": roles_doc,
        "statuses_doc": statuses_doc,
        "people_settings_doc": people_settings_doc,
    }


class BoardPrefetchThread(QThread):
    """Loads JSON off the UI thread so the main thread stays responsive."""

    loaded = Signal(dict)
    failed = Signal(str)

    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self._paths = paths

    def run(self) -> None:
        try:
            data = load_board_files(self._paths)
            self.loaded.emit(data)
        except Exception as e:
            self.failed.emit(str(e))
