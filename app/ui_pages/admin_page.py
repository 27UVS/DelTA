from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.storage import Storage

from app.ui_pages.profile_page import ProfilePage
from app.ui_pages.tables_page import TablesPage
from app.ui_pages.interface_settings_page import InterfaceSettingsPage


class AdminPage(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage, on_back, on_settings_applied):
        super().__init__(parent)
        self.storage = storage
        self.on_back = on_back
        self.on_settings_applied = on_settings_applied

        header = ttk.Frame(self)
        header.pack(fill="x", padx=14, pady=(12, 8))

        ttk.Button(header, text="Назад", command=self._back).pack(side="left")
        ttk.Label(header, text="Администрирование", font=("Segoe UI", 14, "bold")).pack(side="left", padx=(12, 0))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.profile_tab = ProfilePage(self.nb, storage=self.storage)
        self.tables_tab = TablesPage(self.nb, storage=self.storage)
        self.interface_tab = InterfaceSettingsPage(
            self.nb,
            storage=self.storage,
            on_apply=self._on_interface_apply,
        )

        self.nb.add(self.profile_tab, text="Профиль")
        self.nb.add(self.tables_tab, text="Таблицы")
        self.nb.add(self.interface_tab, text="Настройки интерфейса")

    def _back(self) -> None:
        if callable(self.on_back):
            self.on_back()

    def _on_interface_apply(self) -> None:
        # Let the app update theme/background globally.
        if callable(self.on_settings_applied):
            self.on_settings_applied()

    def refresh_after_theme_change(self) -> None:
        self.profile_tab.refresh_after_theme_change()
        self.tables_tab.refresh_after_theme_change()
        self.interface_tab.refresh_after_theme_change()

