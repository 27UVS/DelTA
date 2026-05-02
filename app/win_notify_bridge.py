"""
Windows toast click → поднять главное окно DelTA.

Использует winotify: зарегистрированный URL-протокол (HKCU) и pipe к уже
запущенному процессу. Второй короткий процесс при клике передаёт имя callback
в основной; callback должен выполняться в GUI-потоке — см. notifier.update()
в qt_main_window.run_app.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

DELTA_TOAST_APP_ID = "DelTA"

_active_notifier: Any = None
_toast_activate_cb: Callable[[], None] | None = None


def _project_main_py() -> Path:
    return Path(__file__).resolve().parent.parent / "main.py"


def _argv_looks_like_winotify_protocol() -> bool:
    if len(sys.argv) < 2:
        return False
    try:
        from winotify._registry import format_name
    except Exception:
        return False
    arg = sys.argv[1]
    needle = format_name(DELTA_TOAST_APP_ID) + ":"
    return needle.lower() in arg.lower()


def _fix_shell_open_command(registry: Any) -> None:
    """winotify пишет команду без кавычек — пути с пробелами ломают активацию по клику."""
    if os.name != "nt":
        return
    try:
        import winreg
        exe = str(registry.executable).strip()
        scr = (getattr(registry, "path", None) or "").strip()
        if scr:
            line = subprocess.list2cmdline([exe, scr]) + " %1"
        else:
            line = subprocess.list2cmdline([exe]) + " %1"
        rel = registry._key + r"\shell\open\command"
        hk = winreg.OpenKey(registry.reg, rel, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(hk, "", 0, winreg.REG_SZ, line)
        finally:
            hk.Close()
    except Exception:
        return


def _make_registry():
    from winotify import Registry
    from winotify._registry import PYW_EXE, P

    if getattr(sys, "frozen", False):
        exe = P(str(Path(sys.executable).resolve()), "exe")
        script = ""
    else:
        exe = PYW_EXE
        script = str(_project_main_py())

    try:
        reg = Registry(DELTA_TOAST_APP_ID, executable=exe, script_path=script, force_override=False)
    except Exception:
        reg = Registry(DELTA_TOAST_APP_ID, executable=exe, script_path=script, force_override=True)
    _fix_shell_open_command(reg)
    return reg


def try_handle_notify_protocol_argv() -> None:
    """
    Если процесс запущен кликом по toast (DelTA:…), переслать callback в основной
    процесс и выйти. Иначе ничего не делать.
    """
    if os.name != "nt":
        return
    if not _argv_looks_like_winotify_protocol():
        return
    try:
        from winotify import Notifier
    except Exception:
        return
    try:
        Notifier(_make_registry())
    except SystemExit:
        raise
    except Exception:
        return
    # Протокол в argv, но основной процесс не найден (нет pid) — не поднимаем UI.
    sys.exit(0)


def start_win_notify_listener() -> Any | None:
    """
    Поднять listener и зарегистрировать callback поднятия окна.
    Вызывать один раз из GUI-процесса после QApplication.
    """
    global _active_notifier, _toast_activate_cb
    if os.name != "nt":
        return None
    try:
        from winotify import Notifier
    except Exception:
        return None
    try:
        reg = _make_registry()
        notifier = Notifier(reg)
    except Exception:
        return None

    @notifier.register_callback(run_in_main_thread=True)
    def bring_delta_to_foreground() -> None:
        from PySide6.QtWidgets import QApplication

        from app.qt_main_window import MainWindow, _raise_main_window

        app = QApplication.instance()
        if app is None:
            return
        for w in app.topLevelWidgets():
            if isinstance(w, MainWindow):
                _raise_main_window(w)
                return

    notifier.start()
    _active_notifier = notifier
    _toast_activate_cb = bring_delta_to_foreground
    return notifier


def poll_win_notify_listener(notifier: Any | None) -> None:
    if notifier is None:
        return
    try:
        notifier.update()
    except Exception:
        pass


def show_task_toast(title: str, message: str) -> None:
    if os.name != "nt":
        return
    try:
        nf = _active_notifier
        cb = _toast_activate_cb
        if nf is not None and cb is not None:
            nf.create_notification(title, msg=message, duration="short", launch=cb).show()
            return
        from winotify import Notification

        Notification(DELTA_TOAST_APP_ID, title, message, duration="short").show()
    except Exception:
        return
