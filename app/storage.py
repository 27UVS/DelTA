from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from app.app_paths import AppPaths, get_app_paths


APP_TZ = timezone(timedelta(hours=3))


def utc_now_iso() -> str:
    # Kept for backward compatibility: historically the app used UTC+0.
    # The prototype now uses a fixed UTC+3 timezone for all timestamps.
    return datetime.now(APP_TZ).isoformat(timespec="seconds")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


SYSTEM_ADMIN_ROLE_ID = "role_admin"
SYSTEM_NONE_ROLE_ID = "role_none"

SYSTEM_STATUS_NONE_ID = "status_none"
SYSTEM_STATUS_AVAILABLE_ID = "status_available"
SYSTEM_STATUS_BUSY_ID = "status_busy"
SYSTEM_STATUS_ABSENT_ID = "status_absent"


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    color: str
    priority: int
    locked: bool
    for_stories: bool


@dataclass(frozen=True)
class Status:
    id: str
    name: str
    color: str
    locked: bool


class Storage:
    """
    Local JSON storage ("memory") for the desktop prototype.

    We intentionally avoid external DBs (MySQL/PostgreSQL/etc) as requested.
    """

    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or get_app_paths()
        self._json_cache: dict[str, Any] = {}
        self._rev: int = 0
        self._ensure_dirs()
        self._ensure_seed()

    @property
    def rev(self) -> int:
        return int(self._rev)

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        _ensure_parent(path)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
        self._json_cache[str(path.resolve())] = copy.deepcopy(payload)
        self._rev += 1

    def warm_cache(self, path: Path, data: Any) -> None:
        """Replace in-memory cache for path (e.g. after background prefetch)."""
        self._json_cache[str(path.resolve())] = copy.deepcopy(data)

    def _json_root_cached(self, path: Path, default: Any) -> Any:
        """Read-only view of the JSON root object (shared cache; do not mutate)."""
        key = str(path.resolve())
        if key in self._json_cache:
            return self._json_cache[key]
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return default
        self._json_cache[key] = data
        return data

    def _read_json_mut(self, path: Path, default: Any) -> Any:
        """Independent copy for code that mutates the document before save."""
        key = str(path.resolve())
        if key in self._json_cache:
            return copy.deepcopy(self._json_cache[key])
        if not path.exists():
            return copy.deepcopy(default) if isinstance(default, (dict, list)) else default
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return copy.deepcopy(default) if isinstance(default, (dict, list)) else default
        self._json_cache[key] = data
        return copy.deepcopy(data)

    def _ensure_dirs(self) -> None:
        self.paths.db_dir.mkdir(parents=True, exist_ok=True)
        self.paths.avatars_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_seed(self) -> None:
        roles_data = self._json_root_cached(self.paths.roles_path, default={})
        if not roles_data.get("roles"):
            seed_roles = [
                {
                    "id": SYSTEM_ADMIN_ROLE_ID,
                    "name": "Администратор",
                    "color": "#000000",
                    "priority": 0,
                    "locked": True,
                },
                {
                    "id": SYSTEM_NONE_ROLE_ID,
                    "name": "Без роли",
                    "color": "#BDBDBD",
                    "priority": 9999,
                    "locked": True,
                },
                {
                    "id": str(uuid.uuid4()),
                    "name": "Руководитель",
                    "color": "#ee3157",
                    "priority": 1,
                    "locked": False,
                },
            ]
            self._atomic_write_json(self.paths.roles_path, {"roles": seed_roles})

        statuses_data = self._json_root_cached(self.paths.statuses_path, default={})
        if not statuses_data.get("statuses"):
            seed_statuses = [
                {"id": SYSTEM_STATUS_NONE_ID, "name": "Без статуса", "color": "#9E9E9E", "locked": True},
                {"id": SYSTEM_STATUS_AVAILABLE_ID, "name": "Доступен", "color": "#4CAF50", "locked": False},
                {"id": SYSTEM_STATUS_BUSY_ID, "name": "Занят", "color": "#FF9800", "locked": False},
                {"id": SYSTEM_STATUS_ABSENT_ID, "name": "Отсутствует", "color": "#EF5350", "locked": False},
            ]
            self._atomic_write_json(self.paths.statuses_path, {"statuses": seed_statuses})
        else:
            # Backward-compatible defaults for newly added status fields.
            cur = self._read_json_mut(self.paths.statuses_path, default={"statuses": []}) or {"statuses": []}
            changed = False
            for st in cur.get("statuses", []) or []:
                if not isinstance(st, dict):
                    continue
                if "color" not in st:
                    st["color"] = "#9E9E9E" if str(st.get("id")) == SYSTEM_STATUS_NONE_ID else "#4CAF50"
                    changed = True
            if changed:
                self._atomic_write_json(self.paths.statuses_path, cur)

        # Tasks kind files (read-only in admin UI, but must exist).
        for p in [
            self.paths.tasks_draft_path,
            self.paths.tasks_progress_path,
            self.paths.tasks_finished_path,
            self.paths.tasks_delayed_path,
        ]:
            if not p.exists():
                self._atomic_write_json(p, {"tasks": []})

        if not self.paths.subjects_path.exists():
            self._atomic_write_json(self.paths.subjects_path, {"subjects": []})

        if not self.paths.profile_path.exists():
            seed_profile = {
                "nickname": "Администратор",
                "avatar_path": None,
                "experimental_mode": False,
                "links": {
                    "youtube": "",
                    "instagram": "",
                    "tumblr": "",
                    "x": "",
                    "telegram": "",
                    "vk": "",
                    "other": "",
                },
                "role_ids": [SYSTEM_ADMIN_ROLE_ID],
            }
            self._atomic_write_json(self.paths.profile_path, seed_profile)
        else:
            # Backward-compatible defaults for new profile fields.
            cur = self._read_json_mut(self.paths.profile_path, default={}) or {}
            changed = False
            if "experimental_mode" not in cur:
                cur["experimental_mode"] = False
                changed = True
            if changed:
                self._atomic_write_json(self.paths.profile_path, cur)

        if not self.paths.ui_settings_path.exists():
            seed_ui_settings = {
                "theme": "dark",  # dark|light
                "background_color": "#1F1F1F",
                "background_image_path": None,
                # Main page UI:
                "people_panel_open": True,
                "people_panel_pinned": False,
            }
            self._atomic_write_json(self.paths.ui_settings_path, seed_ui_settings)
        else:
            # Backward-compatible defaults for new settings.
            cur = self._read_json_mut(self.paths.ui_settings_path, default={}) or {}
            changed = False
            if "people_panel_open" not in cur:
                cur["people_panel_open"] = True
                changed = True
            if "people_panel_pinned" not in cur:
                cur["people_panel_pinned"] = False
                changed = True
            if changed:
                self._atomic_write_json(self.paths.ui_settings_path, cur)

        # Per-person extra settings (email + 2 links + preferred link) are stored separately
        # from the admin profile links (per requirements).
        if not self.paths.people_settings_path.exists():
            self._atomic_write_json(self.paths.people_settings_path, {"people": {}})

        # Stories + statuses (used by the "Stories" planner mode).
        if not self.paths.story_statuses_path.exists():
            seed_story_statuses = [
                {"id": "story_not_started", "name": "Не начат", "color": "#9E9E9E", "locked": True, "default": True},
                {"id": "story_writing", "name": "Пишется", "color": "#42A5F5", "locked": False},
                {"id": "story_written_no_translation", "name": "Написан без перевода", "color": "#7E57C2", "locked": False},
                {"id": "story_written", "name": "Написан", "color": "#5C6BC0", "locked": False},
                {"id": "story_drawing", "name": "Рисуется", "color": "#26A69A", "locked": False},
                {"id": "story_drawing_not_finished", "name": "Рисуется, не дописан", "color": "#FF1744", "locked": False},
                {"id": "story_drawing_no_translation", "name": "Рисуется, нет перевода", "color": "#26A69A", "locked": False},
                {"id": "story_ready", "name": "Готов", "color": "#66BB6A", "locked": False},
                {"id": "story_ready_no_translation", "name": "Готов без перевода", "color": "#66BB6A", "locked": False},
                {"id": "story_review", "name": "На проверке", "color": "#FFA726", "locked": False},
                {"id": "story_delayed", "name": "Отложен", "color": "#BDBDBD", "locked": False},
                {"id": "story_published", "name": "Опубликован", "color": "#FF7043", "locked": False},
            ]
            self._atomic_write_json(self.paths.story_statuses_path, {"statuses": seed_story_statuses})
        else:
            # Backward-compatible: ensure required story statuses exist and update colors/names.
            cur = self._read_json_mut(self.paths.story_statuses_path, default={"statuses": []}) or {"statuses": []}
            if not isinstance(cur, dict):
                cur = {"statuses": []}
            sts = cur.get("statuses")
            if not isinstance(sts, list):
                sts = []
                cur["statuses"] = sts

            by_id: dict[str, dict] = {}
            for x in sts:
                if isinstance(x, dict) and x.get("id"):
                    by_id[str(x.get("id"))] = x

            changed = False

            def _ensure(st_id: str, name: str, color: str, *, locked: bool = False, default: bool = False) -> None:
                nonlocal changed
                if st_id in by_id:
                    st = by_id[st_id]
                    # Update name/color to the latest canonical values.
                    if str(st.get("name") or "") != name:
                        st["name"] = name
                        changed = True
                    if str(st.get("color") or "") != color:
                        st["color"] = color
                        changed = True
                    if "locked" not in st:
                        st["locked"] = bool(locked)
                        changed = True
                    if default and not bool(st.get("default", False)):
                        st["default"] = True
                        changed = True
                    return
                st = {"id": st_id, "name": name, "color": color, "locked": bool(locked)}
                if default:
                    st["default"] = True
                sts.append(st)
                by_id[st_id] = st
                changed = True

            _ensure("story_not_started", "Не начат", "#9E9E9E", locked=True, default=True)
            _ensure("story_writing", "Пишется", "#42A5F5")
            _ensure("story_written_no_translation", "Написан без перевода", "#7E57C2")
            _ensure("story_written", "Написан", "#5C6BC0")
            _ensure("story_drawing", "Рисуется", "#26A69A")
            _ensure("story_drawing_not_finished", "Рисуется, не дописан", "#FF1744")
            _ensure("story_drawing_no_translation", "Рисуется, нет перевода", "#26A69A")
            _ensure("story_ready", "Готов", "#66BB6A")
            _ensure("story_ready_no_translation", "Готов без перевода", "#66BB6A")
            _ensure("story_review", "На проверке", "#FFA726")
            _ensure("story_delayed", "Отложен", "#BDBDBD")
            _ensure("story_published", "Опубликован", "#FF7043")

            if changed:
                self._atomic_write_json(self.paths.story_statuses_path, cur)
        if not self.paths.stories_path.exists():
            self._atomic_write_json(self.paths.stories_path, {"stories": []})

        if not self.paths.story_taxonomy_path.exists():
            seed = [
                {"id": "season_all", "name": "Все", "kind": "season", "locked": True},
                {"id": "arc_all", "name": "Все", "kind": "arc", "locked": True},
                {"id": "section_actual", "name": "Актуальные", "kind": "section", "locked": True},
                {"id": "section_not_actual", "name": "Не актуальные", "kind": "section", "locked": True},
            ]
            self._atomic_write_json(self.paths.story_taxonomy_path, {"items": seed})

    # ----------- Stories (planner) -----------
    def get_story_statuses(self) -> list[dict[str, Any]]:
        data = self._json_root_cached(self.paths.story_statuses_path, default={"statuses": []})
        statuses = data.get("statuses", []) if isinstance(data, dict) else []
        return [copy.deepcopy(s) for s in statuses if isinstance(s, dict)]

    def get_story_default_status_id(self) -> str:
        for st in self.get_story_statuses():
            if bool(st.get("default")):
                return str(st.get("id") or "story_not_started")
        return "story_not_started"

    def get_stories(self) -> list[dict[str, Any]]:
        data = self._json_root_cached(self.paths.stories_path, default={"stories": []})
        stories = data.get("stories", []) if isinstance(data, dict) else []
        return [copy.deepcopy(s) for s in stories if isinstance(s, dict)]

    def save_stories(self, stories: list[dict[str, Any]]) -> None:
        self._atomic_write_json(self.paths.stories_path, {"stories": stories})

    def add_story(self, payload: dict[str, Any]) -> dict[str, Any]:
        story = copy.deepcopy(payload) if isinstance(payload, dict) else {}
        story_id = str(story.get("id") or uuid.uuid4())
        story["id"] = story_id
        if "created_at" not in story:
            story["created_at"] = utc_now_iso()
        if "archived" not in story:
            story["archived"] = False
        if not story.get("status_id"):
            story["status_id"] = self.get_story_default_status_id()
        # Taxonomy
        if "season_id" in story:
            story["season_id"] = str(story.get("season_id") or "season_all")
        else:
            story["season_id"] = "season_all"
        if "arc_id" in story:
            story["arc_id"] = str(story.get("arc_id") or "arc_all")
        else:
            story["arc_id"] = "arc_all"
        sec_ids = story.get("section_ids", [])
        if not isinstance(sec_ids, list):
            sec_ids = []
        story["section_ids"] = [str(x) for x in sec_ids if str(x)]
        # Normalize assignments: dict[role_id] -> list[person_id]
        assignments = story.get("assignments")
        if not isinstance(assignments, dict):
            assignments = {}
        norm_assignments: dict[str, list[str]] = {}
        for rk, rv in assignments.items():
            if not rk:
                continue
            if not isinstance(rv, list):
                rv = []
            norm_assignments[str(rk)] = [str(x) for x in rv if str(x)]
        story["assignments"] = norm_assignments
        # Manual ordering (used by "Персональная" sort on Stories page).
        if "order" in story:
            try:
                story["order"] = int(story.get("order"))
            except Exception:
                story["order"] = None
        else:
            try:
                existing = self.get_stories()
                max_order = max(
                    [int(s.get("order")) for s in existing if isinstance(s, dict) and isinstance(s.get("order"), int)],
                    default=-10,
                )
                story["order"] = int(max_order + 10)
            except Exception:
                story["order"] = 0
        stories = self.get_stories()
        stories.append(story)
        self.save_stories(stories)
        return copy.deepcopy(story)

    def update_story(self, story_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        sid = str(story_id or "")
        if not sid:
            raise ValueError("story_id is empty")
        stories = self.get_stories()
        for i, s in enumerate(stories):
            if str(s.get("id")) != sid:
                continue
            was_archived = bool(s.get("archived", False))
            merged = copy.deepcopy(s)
            merged.update(copy.deepcopy(patch) if isinstance(patch, dict) else {})
            if "season_id" in merged:
                merged["season_id"] = str(merged.get("season_id") or "season_all")
            if "arc_id" in merged:
                merged["arc_id"] = str(merged.get("arc_id") or "arc_all")
            if "section_ids" in merged:
                sec_ids = merged.get("section_ids")
                if not isinstance(sec_ids, list):
                    sec_ids = []
                merged["section_ids"] = [str(x) for x in sec_ids if str(x)]
            if "assignments" in merged:
                assignments = merged.get("assignments")
                if not isinstance(assignments, dict):
                    assignments = {}
                norm_assignments: dict[str, list[str]] = {}
                for rk, rv in assignments.items():
                    if not rk:
                        continue
                    if not isinstance(rv, list):
                        rv = []
                    norm_assignments[str(rk)] = [str(x) for x in rv if str(x)]
                merged["assignments"] = norm_assignments
            if "order" in merged and merged.get("order") is not None:
                try:
                    merged["order"] = int(merged.get("order"))
                except Exception:
                    merged["order"] = None
            stories[i] = merged
            self.save_stories(stories)
            # If the story becomes archived, automatically unlink tasks from it.
            if (not was_archived) and bool(merged.get("archived", False)):
                try:
                    self._unlink_tasks_from_story(sid)
                except Exception:
                    pass
            return copy.deepcopy(merged)
        raise ValueError("Story not found")

    def set_story_archived(self, story_id: str, archived: bool) -> dict[str, Any]:
        return self.update_story(str(story_id), {"archived": bool(archived)})

    def delete_story(self, story_id: str) -> None:
        sid = str(story_id or "")
        if not sid:
            raise ValueError("story_id is empty")
        stories = self.get_stories()
        target = next((s for s in stories if str(s.get("id")) == sid), None)
        if not target:
            raise ValueError("Story not found")

        # Remove story link from all tasks referencing it.
        try:
            self._unlink_tasks_from_story(sid)
        except Exception:
            # Best-effort: even if unlinking fails, still attempt story removal.
            pass

        stories = [s for s in stories if str(s.get("id")) != sid]
        self.save_stories(stories)

    def _unlink_tasks_from_story(self, story_id: str) -> None:
        """Remove story link from all tasks referencing the story (safe if none)."""
        sid = str(story_id or "")
        if not sid:
            return
        for kind in ("draft", "progress", "finished", "delayed"):
            path = self._tasks_path_for_kind(kind)
            root = self._read_json_mut(path, default={"tasks": []}) or {"tasks": []}
            if not isinstance(root, dict):
                continue
            tasks = root.get("tasks")
            if not isinstance(tasks, list):
                continue
            changed = False
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                if str(t.get("story_id") or "") == sid:
                    t["story_id"] = None
                    changed = True
            if changed:
                self._atomic_write_json(path, root)

    # ----------- Getters -----------
    def get_roles(self) -> list[Role]:
        data = self._json_root_cached(self.paths.roles_path, default={})
        if not isinstance(data, dict):
            data = {}
        roles = data.get("roles", [])
        result: list[Role] = []
        for r in roles:
            name = str(r.get("name"))
            # Backward-compat: infer for_stories for the common scenario roles.
            fs = r.get("for_stories")
            if fs is None:
                fs = name.strip().lower() in {"писатель", "редактор", "художник"}
            result.append(
                Role(
                    id=str(r.get("id")),
                    name=name,
                    color=str(r.get("color", "#BDBDBD")),
                    priority=int(r.get("priority", 9999)),
                    locked=bool(r.get("locked", False)),
                    for_stories=bool(fs),
                )
            )
        return result

    def get_statuses(self) -> list[Status]:
        data = self._json_root_cached(self.paths.statuses_path, default={})
        if not isinstance(data, dict):
            data = {}
        statuses = data.get("statuses", [])
        result: list[Status] = []
        for s in statuses:
            result.append(
                Status(
                    id=str(s.get("id")),
                    name=str(s.get("name")),
                    color=str(s.get("color", "#9E9E9E" if str(s.get("id")) == SYSTEM_STATUS_NONE_ID else "#4CAF50")),
                    locked=bool(s.get("locked", False)),
                )
            )
        return result

    def get_subjects(self) -> list[dict[str, Any]]:
        data = self._json_root_cached(self.paths.subjects_path, default={"subjects": []})
        subjects = data.get("subjects", []) if isinstance(data, dict) else []
        return [copy.deepcopy(x) for x in subjects]

    def save_subjects(self, subjects: list[dict[str, Any]]) -> None:
        self._atomic_write_json(self.paths.subjects_path, {"subjects": subjects})

    def get_profile(self) -> dict[str, Any]:
        root = self._json_root_cached(self.paths.profile_path, default={})
        return copy.deepcopy(root) if isinstance(root, dict) else {}

    def save_profile(self, profile: dict[str, Any]) -> None:
        self._atomic_write_json(self.paths.profile_path, profile)

    def get_ui_settings(self) -> dict[str, Any]:
        root = self._json_root_cached(self.paths.ui_settings_path, default={})
        return copy.deepcopy(root) if isinstance(root, dict) else {}

    def save_ui_settings(self, payload: dict[str, Any]) -> None:
        self._atomic_write_json(self.paths.ui_settings_path, payload)

    # ----------- Person extra settings -----------
    def get_person_settings(self, person_id: str) -> dict[str, Any]:
        """Extra settings not stored in profile/subjects (email + 2 links + preferred link + admin status)."""
        root = self._read_json_mut(self.paths.people_settings_path, default={"people": {}}) or {"people": {}}
        people = root.get("people", {}) if isinstance(root, dict) else {}
        data = people.get(str(person_id), {}) if isinstance(people, dict) else {}
        if not isinstance(data, dict):
            data = {}
        # Defaults
        return {
            "email": str(data.get("email", "") or ""),
            "link1": str(data.get("link1", "") or ""),
            "link2": str(data.get("link2", "") or ""),
            "preferred_link": (data.get("preferred_link") if data.get("preferred_link") in ("link1", "link2") else None),
            # For admin card only (subjects keep status_id in subjects.json)
            "admin_status_id": str(data.get("admin_status_id", SYSTEM_STATUS_NONE_ID) or SYSTEM_STATUS_NONE_ID),
        }

    def save_person_settings(self, person_id: str, payload: dict[str, Any]) -> None:
        if not str(person_id):
            raise ValueError("person_id is empty")
        root = self._read_json_mut(self.paths.people_settings_path, default={"people": {}}) or {"people": {}}
        if not isinstance(root, dict):
            root = {"people": {}}
        people = root.get("people")
        if not isinstance(people, dict):
            people = {}
            root["people"] = people
        people[str(person_id)] = {
            "email": str(payload.get("email", "") or ""),
            "link1": str(payload.get("link1", "") or ""),
            "link2": str(payload.get("link2", "") or ""),
            "preferred_link": payload.get("preferred_link") if payload.get("preferred_link") in ("link1", "link2") else None,
            "admin_status_id": str(payload.get("admin_status_id", SYSTEM_STATUS_NONE_ID) or SYSTEM_STATUS_NONE_ID),
        }
        self._atomic_write_json(self.paths.people_settings_path, root)

    def delete_person_settings(self, person_id: str) -> None:
        """Remove extra settings for a person (safe if missing)."""
        if not str(person_id):
            return
        root = self._read_json_mut(self.paths.people_settings_path, default={"people": {}}) or {"people": {}}
        if not isinstance(root, dict):
            return
        people = root.get("people")
        if not isinstance(people, dict):
            return
        if str(person_id) in people:
            people.pop(str(person_id), None)
            self._atomic_write_json(self.paths.people_settings_path, root)

    # ----------- Tasks -----------
    def _tasks_path_for_kind(self, kind: str) -> Path:
        mapping = {
            "draft": self.paths.tasks_draft_path,
            "progress": self.paths.tasks_progress_path,
            "finished": self.paths.tasks_finished_path,
            "delayed": self.paths.tasks_delayed_path,
        }
        if kind not in mapping:
            raise ValueError(f"Unknown tasks kind: {kind}")
        return mapping[kind]

    def load_tasks(self, kind: str) -> list[dict[str, Any]]:
        path = self._tasks_path_for_kind(kind)
        data = self._json_root_cached(path, default={"tasks": []})
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        return [copy.deepcopy(t) for t in tasks]

    def save_tasks(self, kind: str, tasks: list[dict[str, Any]]) -> None:
        path = self._tasks_path_for_kind(kind)
        self._atomic_write_json(path, {"tasks": tasks})

    def add_task(self, kind: str, task: dict[str, Any]) -> None:
        tasks = self.load_tasks(kind)
        tasks.append(copy.deepcopy(task))
        self.save_tasks(kind, tasks)

    def update_task(self, kind: str, task_id: str, patch: dict[str, Any]) -> None:
        tasks = self.load_tasks(kind)
        for i, t in enumerate(tasks):
            if str(t.get("id")) == str(task_id):
                merged = copy.deepcopy(t)
                merged.update(copy.deepcopy(patch))
                tasks[i] = merged
                self.save_tasks(kind, tasks)
                return
        raise ValueError("Task not found")

    def delete_task(self, kind: str, task_id: str) -> None:
        tasks = self.load_tasks(kind)
        new_tasks = [t for t in tasks if str(t.get("id")) != str(task_id)]
        if len(new_tasks) == len(tasks):
            raise ValueError("Task not found")
        self.save_tasks(kind, new_tasks)

    def move_task(self, task_id: str, from_kind: str, to_kind: str) -> None:
        if from_kind == to_kind:
            return
        src = self.load_tasks(from_kind)
        idx = next((i for i, t in enumerate(src) if str(t.get("id")) == str(task_id)), None)
        if idx is None:
            raise ValueError("Task not found")
        task = src.pop(int(idx))
        self.save_tasks(from_kind, src)
        dst = self.load_tasks(to_kind)
        dst.append(task)
        self.save_tasks(to_kind, dst)

    # Active tasks: not draft and not finished.
    def compute_active_tasks_count_for_subject(self, subject_id: str) -> int:
        pr = self._json_root_cached(self.paths.tasks_progress_path, {"tasks": []})
        dl = self._json_root_cached(self.paths.tasks_delayed_path, {"tasks": []})
        pt = pr.get("tasks", []) if isinstance(pr, dict) else []
        dt = dl.get("tasks", []) if isinstance(dl, dict) else []
        cnt = 0
        sid = str(subject_id)
        for t in pt + dt:
            # New format: multiple responsibles.
            ids = [str(x) for x in (t.get("responsible_subject_ids") or []) if x]
            if ids:
                if sid in ids:
                    cnt += 1
                continue
            # Backward compat: single responsible.
            if str(t.get("responsible_subject_id") or "") == sid:
                cnt += 1
        return cnt

    # ----------- Roles CRUD -----------
    def add_role(self, name: str, color: str, priority: int, for_stories: bool = False) -> Role:
        name = name.strip()
        if not name:
            raise ValueError("Role name is empty")

        # Priority rule: only the system Admin role may have priority 0.
        if int(priority) == 0:
            raise ValueError("Priority 0 is reserved for the Administrator role")

        roles = self.get_roles()
        if any(r.name.lower() == name.lower() for r in roles):
            raise ValueError("Role with this name already exists")
        if any(int(r.priority) == int(priority) for r in roles):
            taken_by = next((r for r in roles if int(r.priority) == int(priority)), None)
            who = f" ('{taken_by.name}')" if taken_by else ""
            raise ValueError(f"Priority {int(priority)} is already used{who}. Choose an unused priority.")

        role = Role(
            id=str(uuid.uuid4()),
            name=name,
            color=color,
            priority=int(priority),
            locked=False,
            for_stories=bool(for_stories),
        )
        payload = self._read_json_mut(self.paths.roles_path, default={"roles": []})
        payload["roles"].append(
            {
                "id": role.id,
                "name": role.name,
                "color": role.color,
                "priority": role.priority,
                "locked": role.locked,
                "for_stories": bool(role.for_stories),
            }
        )
        self._atomic_write_json(self.paths.roles_path, payload)
        return role

    def update_role(self, role_id: str, name: str, color: str, priority: int, for_stories: bool | None = None) -> Role:
        name = name.strip()
        if not name:
            raise ValueError("Role name is empty")

        roles = self.get_roles()
        target = next((r for r in roles if r.id == role_id), None)
        if not target:
            raise ValueError("Role not found")
        # Admin role: allow changing ONLY the color (name/priority remain fixed).
        if target.locked and role_id != SYSTEM_ADMIN_ROLE_ID:
            raise ValueError("This role is locked and cannot be edited")

        # Don't allow duplicate name (case-insensitive).
        if role_id != SYSTEM_ADMIN_ROLE_ID:
            if any(r.id != role_id and r.name.lower() == name.lower() for r in roles):
                raise ValueError("Role with this name already exists")
        else:
            # Force fixed fields for admin.
            name = target.name
            priority = target.priority

        # Priority rule: only Admin can be 0.
        if role_id != SYSTEM_ADMIN_ROLE_ID and int(priority) == 0:
            raise ValueError("Priority 0 is reserved for the Administrator role")

        # Priorities must be unique across roles (excluding the role being updated).
        if any(r.id != role_id and int(r.priority) == int(priority) for r in roles):
            taken_by = next((r for r in roles if r.id != role_id and int(r.priority) == int(priority)), None)
            who = f" ('{taken_by.name}')" if taken_by else ""
            raise ValueError(f"Priority {int(priority)} is already used{who}. Choose an unused priority.")

        new_role = Role(
            id=target.id,
            name=name,
            color=color,
            priority=int(priority),
            locked=bool(target.locked),
            for_stories=bool(target.for_stories) if for_stories is None else bool(for_stories),
        )
        payload = self._read_json_mut(self.paths.roles_path, default={"roles": []})
        payload["roles"] = [
            {
                "id": new_role.id,
                "name": new_role.name,
                "color": new_role.color,
                "priority": new_role.priority,
                "locked": bool(target.locked),
                "for_stories": bool(new_role.for_stories),
            }
            if r.get("id") == role_id
            else r
            for r in payload.get("roles", [])
        ]
        self._atomic_write_json(self.paths.roles_path, payload)
        return new_role

    # ----------- Story taxonomy (season/arc/section) -----------
    def get_story_taxonomy(self) -> list[dict[str, Any]]:
        root = self._json_root_cached(self.paths.story_taxonomy_path, default={"items": []})
        items = root.get("items", []) if isinstance(root, dict) else []
        return [copy.deepcopy(x) for x in items if isinstance(x, dict)]

    def save_story_taxonomy(self, items: list[dict[str, Any]]) -> None:
        self._atomic_write_json(self.paths.story_taxonomy_path, {"items": items})

    def add_story_taxonomy_item(self, *, name: str, kind: str) -> dict[str, Any]:
        name = str(name or "").strip()
        kind = str(kind or "").strip()
        if not name:
            raise ValueError("Название пустое")
        if kind not in ("season", "arc", "section"):
            raise ValueError("Некорректный тип")
        items = self.get_story_taxonomy()
        if any(str(x.get("kind")) == kind and str(x.get("name")).strip().lower() == name.lower() for x in items):
            raise ValueError("Элемент с таким названием уже существует")
        row = {"id": str(uuid.uuid4()), "name": name, "kind": kind, "locked": False}
        items.append(row)
        self.save_story_taxonomy(items)
        return copy.deepcopy(row)

    def update_story_taxonomy_item(self, item_id: str, *, name: str) -> dict[str, Any]:
        item_id = str(item_id or "")
        if not item_id:
            raise ValueError("id пустой")
        name = str(name or "").strip()
        if not name:
            raise ValueError("Название пустое")
        items = self.get_story_taxonomy()
        for i, it in enumerate(items):
            if str(it.get("id")) != item_id:
                continue
            if bool(it.get("locked")):
                raise ValueError("Этот элемент нельзя редактировать")
            kind = str(it.get("kind") or "")
            if any(str(x.get("kind")) == kind and str(x.get("name")).strip().lower() == name.lower() for x in items if str(x.get("id")) != item_id):
                raise ValueError("Элемент с таким названием уже существует")
            it2 = copy.deepcopy(it)
            it2["name"] = name
            items[i] = it2
            self.save_story_taxonomy(items)
            return copy.deepcopy(it2)
        raise ValueError("Элемент не найден")

    def delete_story_taxonomy_item(self, item_id: str) -> None:
        item_id = str(item_id or "")
        if not item_id:
            return
        items = self.get_story_taxonomy()
        target = next((x for x in items if str(x.get("id")) == item_id), None)
        if not target:
            raise ValueError("Элемент не найден")
        if bool(target.get("locked")):
            raise ValueError("Этот элемент нельзя удалить")
        items = [x for x in items if str(x.get("id")) != item_id]
        self.save_story_taxonomy(items)

    def delete_role(self, role_id: str) -> None:
        payload = self._read_json_mut(self.paths.roles_path, default={"roles": []})
        roles_payload = payload.get("roles", [])
        target = next((r for r in roles_payload if str(r.get("id")) == str(role_id)), None)
        if not target:
            raise ValueError("Role not found")
        if bool(target.get("locked")):
            raise ValueError("This role is locked and cannot be deleted")

        # Update subjects:
        # - Remove the deleted role from their role_ids
        # - If no other roles remain -> set the system role "Без роли"
        subjects = self.get_subjects()
        for s in subjects:
            role_ids = list(s.get("role_ids", []) or [])
            if role_id in role_ids:
                role_ids = [rid for rid in role_ids if rid != role_id]
                # "Без роли" should only exist when there are no other roles.
                role_ids = [rid for rid in role_ids if rid != SYSTEM_NONE_ROLE_ID]
                s["role_ids"] = role_ids if role_ids else [SYSTEM_NONE_ROLE_ID]
        self.save_subjects(subjects)

        payload["roles"] = [r for r in roles_payload if str(r.get("id")) != str(role_id)]
        self._atomic_write_json(self.paths.roles_path, payload)

    # ----------- Statuses CRUD -----------
    def add_status(self, name: str, color: str = "#4CAF50", locked: bool = False) -> Status:
        name = name.strip()
        if not name:
            raise ValueError("Status name is empty")
        statuses = self.get_statuses()
        if any(s.name.lower() == name.lower() for s in statuses):
            raise ValueError("Status with this name already exists")

        st = Status(id=str(uuid.uuid4()), name=name, color=str(color or "#4CAF50"), locked=locked)
        payload = self._read_json_mut(self.paths.statuses_path, default={"statuses": []})
        payload["statuses"].append({"id": st.id, "name": st.name, "color": st.color, "locked": st.locked})
        self._atomic_write_json(self.paths.statuses_path, payload)
        return st

    def update_status(self, status_id: str, name: str, color: str | None = None) -> Status:
        name = name.strip()
        if not name:
            raise ValueError("Status name is empty")

        statuses = self.get_statuses()
        target = next((s for s in statuses if s.id == status_id), None)
        if not target:
            raise ValueError("Status not found")
        if target.locked:
            raise ValueError("This status is locked and cannot be edited")
        if any(s.id != status_id and s.name.lower() == name.lower() for s in statuses):
            raise ValueError("Status with this name already exists")

        new_status = Status(id=target.id, name=name, color=str(color or target.color), locked=False)
        payload = self._read_json_mut(self.paths.statuses_path, default={"statuses": []})
        payload["statuses"] = [
            {"id": new_status.id, "name": new_status.name, "color": new_status.color, "locked": new_status.locked}
            if str(s.get("id")) == str(status_id)
            else s
            for s in payload.get("statuses", [])
        ]
        self._atomic_write_json(self.paths.statuses_path, payload)
        return new_status

    def delete_status(self, status_id: str) -> None:
        payload = self._read_json_mut(self.paths.statuses_path, default={"statuses": []})
        statuses_payload = payload.get("statuses", [])
        target = next((s for s in statuses_payload if str(s.get("id")) == str(status_id)), None)
        if not target:
            raise ValueError("Status not found")
        if bool(target.get("locked")):
            raise ValueError("This status is locked and cannot be deleted")

        # Update subjects: if subject has this status -> becomes system "Без статуса".
        subjects = self.get_subjects()
        for s in subjects:
            if str(s.get("status_id")) == str(status_id):
                s["status_id"] = SYSTEM_STATUS_NONE_ID
        self.save_subjects(subjects)

        payload["statuses"] = [s for s in statuses_payload if str(s.get("id")) != str(status_id)]
        self._atomic_write_json(self.paths.statuses_path, payload)

    # ----------- Subjects CRUD -----------
    def add_subject(self, nickname: str, role_ids: list[str], status_id: str) -> dict[str, Any]:
        nickname = nickname.strip()
        if not nickname:
            raise ValueError("Nickname is empty")
        role_ids = [str(r) for r in (role_ids or [])]
        # Normalize: "Без роли" appears only when there are no other roles.
        role_ids = [rid for rid in role_ids if rid != SYSTEM_NONE_ROLE_ID]
        if not role_ids:
            role_ids = [SYSTEM_NONE_ROLE_ID]
        if status_id is None or status_id == "":
            status_id = SYSTEM_STATUS_NONE_ID
        subj = {
            "id": str(uuid.uuid4()),
            "nickname": nickname,
            "created_at": utc_now_iso(),
            "role_ids": role_ids,
            "status_id": str(status_id),
            # avatar is optional for future pages
            "avatar_path": None,
        }
        subjects = self.get_subjects()
        subjects.append(subj)
        self.save_subjects(subjects)
        return subj

    def update_subject(
        self,
        subject_id: str,
        nickname: str,
        role_ids: list[str],
        status_id: str,
        avatar_path: str | None = None,
    ) -> None:
        nickname = nickname.strip()
        if not nickname:
            raise ValueError("Nickname is empty")

        role_ids = [str(r) for r in (role_ids or [])]
        role_ids = [rid for rid in role_ids if rid != SYSTEM_NONE_ROLE_ID]
        if not role_ids:
            role_ids = [SYSTEM_NONE_ROLE_ID]

        subjects = self.get_subjects()
        for s in subjects:
            if str(s.get("id")) == str(subject_id):
                s["nickname"] = nickname
                s["role_ids"] = role_ids
                s["status_id"] = str(status_id)
                if avatar_path is not None:
                    s["avatar_path"] = avatar_path
                self.save_subjects(subjects)
                return
        raise ValueError("Subject not found")

    def delete_subject(self, subject_id: str) -> None:
        subjects = self.get_subjects()
        target = next((s for s in subjects if str(s.get("id")) == str(subject_id)), None)
        if not target:
            raise ValueError("Subject not found")

        cnt = self.compute_active_tasks_count_for_subject(subject_id)
        if cnt > 0:
            raise ValueError("Cannot delete subject with active tasks")

        subjects = [s for s in subjects if str(s.get("id")) != str(subject_id)]
        self.save_subjects(subjects)

