from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    db_dir: Path

    roles_path: Path
    statuses_path: Path
    subjects_path: Path
    profile_path: Path
    tasks_draft_path: Path
    tasks_progress_path: Path
    tasks_finished_path: Path
    tasks_delayed_path: Path
    ui_settings_path: Path
    people_settings_path: Path
    stories_path: Path
    story_statuses_path: Path
    story_taxonomy_path: Path

    avatars_dir: Path


def get_app_paths() -> AppPaths:
    # For the prototype we keep data in a local `db/` folder next to the app.
    # When packaged into an EXE, prefer the directory where the executable resides.
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent.parent
    db_dir = base_dir / "db"
    avatars_dir = db_dir / "images" / "avatars"

    return AppPaths(
        base_dir=base_dir,
        db_dir=db_dir,
        roles_path=db_dir / "roles.json",
        statuses_path=db_dir / "statuses.json",
        subjects_path=db_dir / "subjects.json",
        profile_path=db_dir / "profile.json",
        tasks_draft_path=db_dir / "tasks_draft.json",
        tasks_progress_path=db_dir / "tasks_progress.json",
        tasks_finished_path=db_dir / "tasks_finished.json",
        tasks_delayed_path=db_dir / "tasks_delayed.json",
        ui_settings_path=db_dir / "ui_settings.json",
        people_settings_path=db_dir / "people_settings.json",
        stories_path=db_dir / "stories.json",
        story_statuses_path=db_dir / "story_statuses.json",
        story_taxonomy_path=db_dir / "story_taxonomy.json",
        avatars_dir=avatars_dir,
    )

