from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtCore import QTimer

from app.assets import get_interface_assets
from app.loading_overlay import LoadingOverlay
from app.qt_pages.admin_page import AdminPage
from app.qt_pages.board_page import BoardPage
from app.qt_style import build_stylesheet
from app.storage import Storage
from app.theme import get_palette


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


def run_app() -> None:
    storage = Storage()
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(storage=storage)
    win.show()
    sys.exit(app.exec())

