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

    # ----------- Getters -----------
    def get_roles(self) -> list[Role]:
        data = self._json_root_cached(self.paths.roles_path, default={})
        if not isinstance(data, dict):
            data = {}
        roles = data.get("roles", [])
        result: list[Role] = []
        for r in roles:
            result.append(
                Role(
                    id=str(r.get("id")),
                    name=str(r.get("name")),
                    color=str(r.get("color", "#BDBDBD")),
                    priority=int(r.get("priority", 9999)),
                    locked=bool(r.get("locked", False)),
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
    def add_role(self, name: str, color: str, priority: int) -> Role:
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
        )
        payload = self._read_json_mut(self.paths.roles_path, default={"roles": []})
        payload["roles"].append(
            {"id": role.id, "name": role.name, "color": role.color, "priority": role.priority, "locked": role.locked}
        )
        self._atomic_write_json(self.paths.roles_path, payload)
        return role

    def update_role(self, role_id: str, name: str, color: str, priority: int) -> Role:
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
        )
        payload = self._read_json_mut(self.paths.roles_path, default={"roles": []})
        payload["roles"] = [
            {
                "id": new_role.id,
                "name": new_role.name,
                "color": new_role.color,
                "priority": new_role.priority,
                "locked": bool(target.locked),
            }
            if r.get("id") == role_id
            else r
            for r in payload.get("roles", [])
        ]
        self._atomic_write_json(self.paths.roles_path, payload)
        return new_role

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

