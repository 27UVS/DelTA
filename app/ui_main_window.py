from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path

from app.storage import Storage
from app.assets import get_interface_assets

from app.ui_icon_loader import IconLoader
from app.ui_pages.board_page import BoardPage
from app.ui_pages.admin_page import AdminPage

from PIL import Image, ImageTk

from app.theme import get_palette


def _apply_theme(style: ttk.Style, theme: str) -> None:
    # Use a theme that reliably supports custom colors on Windows.
    try:
        style.theme_use("clam")
    except Exception:
        pass

    p = get_palette(theme)

    style.configure(".", background=p.bg, foreground=p.fg)
    style.configure("TFrame", background=p.bg)
    style.configure("TLabel", background=p.bg, foreground=p.fg)

    # Buttons.
    style.configure("TButton", background=p.surface2, foreground=p.fg, borderwidth=0, padding=(10, 6))
    style.map(
        "TButton",
        background=[("active", p.surface), ("pressed", p.surface)],
        foreground=[("disabled", p.muted_fg)],
    )

    # Navigation buttons (left sidebar).
    style.configure(
        "Nav.TButton",
        background=p.nav_btn_bg,
        foreground=p.nav_btn_fg,
        padding=(12, 10),
        anchor="w",
    )
    style.map(
        "Nav.TButton",
        background=[("active", p.surface2), ("pressed", p.nav_btn_bg_active)],
        foreground=[("pressed", "#FFFFFF")],
    )

    # Inputs.
    style.configure("TEntry", fieldbackground=p.entry_bg, foreground=p.entry_fg)
    style.configure("TCombobox", fieldbackground=p.entry_bg, foreground=p.entry_fg)

    # Notebook tabs.
    style.configure("TNotebook", background=p.bg, borderwidth=0)
    style.configure("TNotebook.Tab", background=p.surface2, foreground=p.fg, padding=(12, 6))
    style.map(
        "TNotebook.Tab",
        background=[("selected", p.surface), ("active", p.surface)],
        foreground=[("selected", p.fg)],
    )

    # Tables.
    style.configure("Treeview", background=p.entry_bg, foreground=p.entry_fg, fieldbackground=p.entry_bg)
    style.configure("Treeview.Heading", background=p.surface2, foreground=p.fg)
    style.map("Treeview", background=[("selected", p.accent)], foreground=[("selected", "#FFFFFF")])

    # Scrollbars (more modern look than default Windows classic).
    style.configure(
        "TScrollbar",
        troughcolor=p.bg,
        background=p.surface2,
        bordercolor=p.bg,
        lightcolor=p.bg,
        darkcolor=p.bg,
        arrowcolor=p.fg,
        gripcount=0,
        relief="flat",
    )
    style.map(
        "TScrollbar",
        background=[("active", p.surface), ("pressed", p.surface)],
        arrowcolor=[("disabled", p.muted_fg)],
    )


class MainApp(tk.Tk):
    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self.title("DelTA | Delegation & Task Allocation")
        self.geometry("1180x720")
        self.minsize(980, 620)

        self._bg_photo = None
        self._bg_label = None
        self._app_icon_photo = None
        self._icons = IconLoader()
        self._settings_default_img = None
        self._settings_active_img = None

        self._apply_window_icon()

        self.style = ttk.Style(self)
        self._load_ui_settings_and_apply()

        self._build_layout()
        self._create_pages()
        self._enable_clipboard_shortcuts()
        self.show_page("board")

    def _enable_clipboard_shortcuts(self) -> None:
        # Fix two issues:
        # - Non-English layouts change keysym (e.g. Ctrl+м instead of Ctrl+v) -> paste stops working.
        # - Binding Ctrl+V directly can cause double paste (our handler + default class binding).
        #
        # Strategy:
        # - Do NOT bind to <Control-v>/<Control-c>/... (let Tk defaults handle English layouts).
        # - Intercept Control+KeyPress by keycode (physical key) and only when keysym isn't latin.

        def _is_text_widget(w) -> bool:
            return isinstance(w, tk.Text)

        def _is_entry_widget(w) -> bool:
            return isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox))

        def _select_all_for_widget(w) -> None:
            if isinstance(w, tk.Text):
                w.tag_add("sel", "1.0", "end-1c")
                w.mark_set("insert", "1.0")
                w.see("insert")
            elif isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox)):
                w.selection_range(0, "end")
                w.icursor("end")

        # Typical Windows keycodes for A/C/V/X are 65/67/86/88 (virtual-key codes).
        vk_to_action = {
            65: "select_all",
            67: "copy",
            86: "paste",
            88: "cut",
        }
        latin_keysyms = {"a", "A", "c", "C", "v", "V", "x", "X"}

        def _on_ctrl_keypress(event):
            w = event.widget
            if not (_is_text_widget(w) or _is_entry_widget(w)):
                return None

            # Control modifier.
            if not (event.state & 0x0004):
                return None

            action = vk_to_action.get(int(getattr(event, "keycode", -1)))
            if not action:
                return None

            # If we're already on Latin keysym, let Tk defaults handle it (avoids double action).
            if getattr(event, "keysym", "") in latin_keysyms:
                return None

            try:
                if action == "paste":
                    w.event_generate("<<Paste>>")
                elif action == "copy":
                    w.event_generate("<<Copy>>")
                elif action == "cut":
                    w.event_generate("<<Cut>>")
                elif action == "select_all":
                    _select_all_for_widget(w)
            except Exception:
                return "break"
            return "break"

        def _on_shift_insert(event):
            w = event.widget
            if _is_text_widget(w) or _is_entry_widget(w):
                try:
                    w.event_generate("<<Paste>>")
                except Exception:
                    pass
                return "break"
            return None

        self.bind_all("<Control-KeyPress>", _on_ctrl_keypress, add=True)
        self.bind_all("<Shift-Insert>", _on_shift_insert, add=True)

    def _apply_window_icon(self) -> None:
        assets = get_interface_assets()
        # Prefer .ico on Windows.
        if assets.icon_ico.exists():
            try:
                self.iconbitmap(str(assets.icon_ico))
                return
            except Exception:
                pass
        # Fallback to PNG.
        if assets.icon_png.exists():
            try:
                img = Image.open(assets.icon_png).convert("RGBA")
                img = img.resize((64, 64), Image.LANCZOS)
                self._app_icon_photo = ImageTk.PhotoImage(img)
                self.iconphoto(True, self._app_icon_photo)
            except Exception:
                pass

    def _load_ui_settings_and_apply(self) -> None:
        settings = self.storage.get_ui_settings()
        theme = settings.get("theme", "dark")
        _apply_theme(self.style, theme)

        p = get_palette(theme)
        bg_color = settings.get("background_color", p.bg)
        self.configure(background=bg_color)

        bg_image_path = settings.get("background_image_path")
        if bg_image_path and Path(bg_image_path).exists():
            img = Image.open(bg_image_path)
            # Fit image roughly to window.
            img = img.resize((1180, 720), Image.LANCZOS)
            self._bg_photo = ImageTk.PhotoImage(img)
            if self._bg_label is None:
                self._bg_label = tk.Label(self, image=self._bg_photo, borderwidth=0)
                self._bg_label.place(x=0, y=0, relwidth=1, relheight=1)
            else:
                self._bg_label.configure(image=self._bg_photo)
        else:
            # Remove background image (if any).
            if self._bg_label is not None:
                self._bg_label.destroy()
                self._bg_label = None
                self._bg_photo = None

    def _build_layout(self) -> None:
        # Single content area; navigation is done via settings button/back.
        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True)

        # Ensure background label (if any) stays behind content.
        if self._bg_label is not None:
            try:
                self._bg_label.lower(self.content)
            except Exception:
                self._bg_label.lower()

        # Settings button (top-right) is visible only on the main board.
        assets = get_interface_assets()
        self._settings_default_img = self._icons.load_png(assets.settings_default_png, (24, 24))
        self._settings_active_img = self._icons.load_png(assets.settings_active_png, (24, 24))
        self.settings_btn = ttk.Button(
            self,
            image=self._settings_default_img,
            command=self._open_admin,
            text="",
        )
        self.settings_btn.place_forget()

    def _create_pages(self) -> None:
        self.pages: dict[str, tk.Frame] = {}
        self.pages["board"] = BoardPage(self.content, storage=self.storage, on_open_admin=self._open_admin)
        self.pages["admin"] = AdminPage(
            self.content,
            storage=self.storage,
            on_back=self._back_to_board,
            on_settings_applied=self._on_settings_applied,
        )

        for page in self.pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _on_settings_applied(self) -> None:
        self._load_ui_settings_and_apply()
        # Apply theme changes for each child frame.
        for page in self.pages.values():
            page.refresh_after_theme_change()

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if not page:
            return
        page.tkraise()
        self._update_settings_button_visibility()

    def _update_settings_button_visibility(self) -> None:
        # Only show settings button on the board page.
        top = None
        try:
            top = self.content.winfo_children()[-1]
        except Exception:
            top = None
        # Determine visible page by checking which one is above via focus order isn't reliable.
        # Track via a simple attribute.
        current = getattr(self, "_current_page", "board")
        if current == "board":
            img = self._settings_default_img
            if self._settings_active_img is not None and getattr(self, "_admin_open", False):
                img = self._settings_active_img
            self.settings_btn.configure(image=img)
            self.settings_btn.place(relx=1.0, x=-12, y=10, anchor="ne")
        else:
            self.settings_btn.place_forget()

    def _open_admin(self) -> None:
        self._admin_open = True
        self._current_page = "admin"
        if self._settings_active_img is not None:
            self.settings_btn.configure(image=self._settings_active_img)
        self.show_page("admin")

    def _back_to_board(self) -> None:
        self._admin_open = False
        self._current_page = "board"
        if self._settings_default_img is not None:
            self.settings_btn.configure(image=self._settings_default_img)
        # Refresh board content after admin changes (profile, subjects, roles, etc).
        try:
            board = self.pages.get("board")
            if board is not None:
                board.refresh_from_storage()
                board.refresh_after_theme_change()
        except Exception:
            pass
        self.show_page("board")


def run_app() -> None:
    storage = Storage()
    app = MainApp(storage=storage)
    app.mainloop()

