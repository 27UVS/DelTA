from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTabWidget

from app.storage import Storage
from app.qt_pages.profile_page import ProfilePage
from app.qt_pages.tables_page import TablesPage
from app.qt_pages.interface_settings_page import InterfaceSettingsPage


class AdminPage(QWidget):
    def __init__(self, storage: Storage, on_back, on_settings_applied):
        super().__init__()
        self.storage = storage
        self.on_back = on_back
        self.on_settings_applied = on_settings_applied

        self._tables_page: TablesPage | None = None
        self._interface_page: InterfaceSettingsPage | None = None
        self._last_admin_tab_idx: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        back = QPushButton("Назад")
        back.clicked.connect(self._back)
        header.addWidget(back, 0)
        title = QLabel("Администрирование")
        title.setObjectName("H1")
        header.addWidget(title, 0)
        header.addStretch(1)
        root.addLayout(header)

        self.nb = QTabWidget()
        self.nb.setTabPosition(QTabWidget.TabPosition.West)
        self.nb.setElideMode(Qt.TextElideMode.ElideRight)
        self.nb.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.nb, 1)

        self.profile_tab = ProfilePage(storage=self.storage)
        self._tables_host = QWidget()
        self._interface_host = QWidget()

        self.nb.addTab(self.profile_tab, "Профиль")
        self.nb.addTab(self._tables_host, "Таблицы")
        self.nb.addTab(self._interface_host, "Настройки интерфейса")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Board may have changed tasks while we were away; keep tables in sync when returning.
        if self._tables_page is not None:
            self._tables_page.refresh_all()

    def _on_tab_changed(self, index: int) -> None:
        if index == 0 and self._last_admin_tab_idx not in (None, 0):
            self.profile_tab.refresh_from_storage()
        self._last_admin_tab_idx = index
        if index == 1:
            self._ensure_tables()
            if self._tables_page is not None:
                self._tables_page.refresh_all()
        elif index == 2:
            self._ensure_interface()

    def _ensure_tables(self) -> None:
        if self._tables_page is not None:
            return
        lay = QVBoxLayout(self._tables_host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._tables_page = TablesPage(self.storage)
        lay.addWidget(self._tables_page)

    def _ensure_interface(self) -> None:
        if self._interface_page is not None:
            return
        lay = QVBoxLayout(self._interface_host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._interface_page = InterfaceSettingsPage(storage=self.storage, on_apply=self._on_interface_apply)
        lay.addWidget(self._interface_page)

    def _back(self) -> None:
        if callable(self.on_back):
            self.on_back()

    def _on_interface_apply(self) -> None:
        if callable(self.on_settings_applied):
            self.on_settings_applied()

    def refresh_after_theme_change(self) -> None:
        self.profile_tab.refresh_after_theme_change()
        if self._tables_page is not None:
            self._tables_page.refresh_after_theme_change()
        if self._interface_page is not None:
            self._interface_page.refresh_after_theme_change()
