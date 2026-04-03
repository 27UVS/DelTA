from __future__ import annotations

from pathlib import Path
import shutil
import sys

from app.qt_main_window import run_app


def ensure_db_exists() -> None:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent

    db_dir = base_dir / "db"
    if db_dir.exists():
        return

    template_dir = base_dir / "db_template"
    if not template_dir.exists():
        return

    shutil.copytree(template_dir, db_dir)


if __name__ == "__main__":
    ensure_db_exists()
    run_app()

