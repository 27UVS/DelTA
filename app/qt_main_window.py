from __future__ import annotations

import hashlib
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from app.assets import get_interface_assets
from app.loading_overlay import LoadingOverlay
from app.qt_pages.admin_page import AdminPage
from app.qt_pages.board_page import BoardPage
from app.qt_style import build_stylesheet
from app.storage import Storage
from app.task_background_notify import TaskBackgroundNotifier
from app.theme import get_palette
from app.win_notify_bridge import poll_win_notify_listener, start_win_notify_listener


def _activation_server_name(storage: Storage) -> str:
    raw = str(storage.paths.base_dir.resolve()).encode("utf-8")
    return "DelTA_" + hashlib.sha256(raw).hexdigest()[:32]


def _try_activate_running_instance(server_name: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if not sock.waitForConnected(900):
        return False
    sock.write(b"SHOW\n")
    ok = sock.waitForBytesWritten(900)
    sock.disconnectFromServer()
    return bool(ok)


def _raise_main_window(win: QMainWindow) -> None:
    st = win.windowState()
    if st & Qt.WindowState.WindowMinimized:
        win.setWindowState(st & ~Qt.WindowState.WindowMinimized)
    win.show()
    win.raise_()
    win.activateWindow()


def _on_activation_connected(server: QLocalServer, win: QMainWindow) -> None:
    conn = server.nextPendingConnection()
    if conn is None:
        return
    conn.waitForReadyRead(2000)
    conn.readAll()
    conn.disconnectFromServer()
    conn.deleteLater()
    _raise_main_window(win)


def _ensure_listen_or_handoff(server: QLocalServer, server_name: str) -> tuple[bool, bool]:
    """
    Returns (listening_ok, caller_should_exit).
    If caller_should_exit is True, a running instance acknowledged SHOW and this process must exit.
    """
    if server.listen(server_name):
        return True, False
    if _try_activate_running_instance(server_name):
        return False, True
    server.removeServer(server_name)
    if server.listen(server_name):
        return True, False
    return False, False


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self.setWindowTitle("DelTA | Delegation & Task Allocation")
        self.resize(1180, 720)
        self.setMinimumSize(980, 620)

        assets = get_interface_assets()
        if assets.icon_ico.exists():
            self.setWindowIcon(QIcon(str(assets.icon_ico)))
        elif assets.icon_png.exists():
            self.setWindowIcon(QIcon(str(assets.icon_png)))
        self._app_icon = self.windowIcon()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.board = BoardPage(storage=self.storage, on_open_admin=self._open_admin)
        self._admin: AdminPage | None = None
        self._overlay = LoadingOverlay(parent=self.stack)
        self._overlay.set_icon(self._app_icon)
        self._theme_apply_pending = False

        self.stack.addWidget(self.board)
        self._current = "board"
        self.show_page("board")

        self._last_theme: str | None = None
        # Defer expensive work until after the event loop starts (window can paint first).
        QTimer.singleShot(0, self._post_show_init)

    def _post_show_init(self) -> None:
        self.apply_theme(show_overlay=False)
        # Let the window paint once before loading data (reduces "Not responding" on startup).
        QTimer.singleShot(50, lambda: self.board.refresh_from_storage(force=True))

    def _ensure_admin(self) -> AdminPage:
        if self._admin is None:
            self._admin = AdminPage(
                storage=self.storage,
                on_back=self._back_to_board,
                on_settings_applied=self._on_settings_applied,
            )
            self.stack.addWidget(self._admin)
            self._admin.refresh_after_theme_change()
        return self._admin

    def apply_theme(self, *, show_overlay: bool = True) -> None:
        theme = self.storage.get_ui_settings().get("theme", "dark")
        if str(theme) == str(self._last_theme):
            return
        self._last_theme = str(theme)

        if show_overlay and not self._theme_apply_pending:
            self._theme_apply_pending = True
            self._overlay.show_over()
            QTimer.singleShot(0, lambda t=str(theme): self._apply_theme_impl(t))
            return

        self._apply_theme_impl(str(theme))

    def _apply_theme_impl(self, theme: str) -> None:
        p = get_palette(theme)
        # Style only the content stack — avoids re-styling the entire QMainWindow chrome on each theme change.
        self.stack.setStyleSheet(build_stylesheet(p))
        self.board.refresh_after_theme_change()
        if self._admin is not None:
            self._admin.refresh_after_theme_change()
        if self._theme_apply_pending:
            QTimer.singleShot(0, self._finish_theme_apply)

    def _finish_theme_apply(self) -> None:
        self._theme_apply_pending = False
        self._overlay.hide_overlay()

    def _on_settings_applied(self) -> None:
        self.apply_theme(show_overlay=True)
        # Theme application already refreshes pages; don't duplicate work here.

    def show_page(self, key: str) -> None:
        if key == "board":
            self._current = "board"
            self.stack.setCurrentWidget(self.board)
        elif key == "admin":
            self._current = "admin"
            self.stack.setCurrentWidget(self._ensure_admin())

    def _open_admin(self) -> None:
        self.show_page("admin")

    def _back_to_board(self) -> None:
        # Switch first; refresh runs after a short yield so the stack can paint.
        self.show_page("board")
        QTimer.singleShot(10, lambda: self.board.refresh_from_storage(force=False))

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        app = QApplication.instance()
        force_quit = bool(getattr(app, "_delta_force_full_quit", False)) if app is not None else False
        profile = self.storage.get_profile()
        full_shutdown = bool(getattr(app, "_delta_full_shutdown_ui", profile.get("full_shutdown", True)))
        if force_quit or full_shutdown:
            self.board.cleanup_threads()
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()


def run_app() -> None:
    storage = Storage()
    _set_windows_app_user_model_id("DelTA")
    app = QApplication.instance() or QApplication(sys.argv)
    setattr(app, "_delta_full_shutdown_ui", bool(storage.get_profile().get("full_shutdown", True)))

    winotify_notifier = start_win_notify_listener()
    if winotify_notifier is not None:
        _poller = QTimer(app)
        _poller.setInterval(150)
        _poller.timeout.connect(lambda: poll_win_notify_listener(winotify_notifier))
        _poller.start()

    # Windows taskbar icon typically follows the app/window icon, not only the embedded EXE icon.
    assets = get_interface_assets()
    if assets.icon_ico.exists():
        app.setWindowIcon(QIcon(str(assets.icon_ico)))
    elif assets.icon_png.exists():
        app.setWindowIcon(QIcon(str(assets.icon_png)))

    activation_name = _activation_server_name(storage)
    if _try_activate_running_instance(activation_name):
        sys.exit(0)

    server = QLocalServer(app)
    listening, handoff_exit = _ensure_listen_or_handoff(server, activation_name)
    if handoff_exit:
        sys.exit(0)

    win = MainWindow(storage=storage)
    if listening:
        server.newConnection.connect(lambda: _on_activation_connected(server, win))

    notifier = TaskBackgroundNotifier(storage=storage, parent=win)
    notifier.start()

    win.show()
    sys.exit(app.exec())


def _set_windows_app_user_model_id(app_id: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
    except Exception:
        return

