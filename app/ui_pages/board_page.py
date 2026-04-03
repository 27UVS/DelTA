from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.storage import Storage, SYSTEM_ADMIN_ROLE_ID, SYSTEM_NONE_ROLE_ID
from app.theme import get_palette
from PIL import Image, ImageTk, ImageDraw, ImageFont
import time


def _fmt(s: str | None) -> str:
    if not s:
        return "—"
    return str(s)


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)

        self.inner = ttk.Frame(self.canvas)
        self._inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")

        def _on_inner_configure(_):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def _on_canvas_configure(event):
            # Keep inner width equal to canvas width.
            self.canvas.itemconfigure(self._inner_id, width=event.width)

        self.inner.bind("<Configure>", _on_inner_configure)
        self.canvas.bind("<Configure>", _on_canvas_configure)


def _make_avatar(size: int, initials: str, bg: str) -> ImageTk.PhotoImage:
    img = Image.new("RGB", (size, size), color=bg)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", max(10, size // 2))
    except Exception:
        font = ImageFont.load_default()
    text = initials[:2].upper() or "?"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2), text, fill=(255, 255, 255), font=font)
    return ImageTk.PhotoImage(img)


class BoardPage(ttk.Frame):
    """
    Main page: Wekan-like board with columns and a slide-out people panel.
    """

    def __init__(self, parent: tk.Misc, storage: Storage, on_open_admin=None):
        super().__init__(parent)
        self.storage = storage
        self.on_open_admin = on_open_admin

        self._people_target_w = 280
        self._people_w = 0
        self._anim_after = None
        self._people_avatars: list[ImageTk.PhotoImage] = []
        self._board_bg_photo = None
        self._board_bg_label = None
        self._board_bg_path = None
        self._col_width = 320
        self._hscroll_visible = True
        self._anim_start_t = 0.0
        self._anim_from_w = 0
        self._anim_to_w = 0
        self._anim_duration_s = 0.18

        self._build()
        self.refresh_after_theme_change()
        self.refresh_from_storage()

    def _build(self) -> None:
        # Root containers
        self.root = ttk.Frame(self)
        self.root.pack(fill="both", expand=True)

        # People panel (left) + board (right)
        self.people_panel = ttk.Frame(self.root)
        self.board_area = ttk.Frame(self.root)

        self.people_panel.place(x=0, y=0, relheight=1, width=0)
        self.board_area.place(x=0, y=0, relheight=1, relwidth=1)

        # Board background image (per settings). Must be behind everything in board_area.
        self._board_bg_label = tk.Label(self.board_area, borderwidth=0)
        self._board_bg_label.place(x=0, y=0, relwidth=1, relheight=1)

        # Scrim (darken the board when panel overlays it).
        # Canvas stipple over an image can produce visual artifacts on Windows, so we use
        # a semi-transparent RGBA image as a Label instead.
        self._scrim_photo = None
        self.scrim = tk.Label(self.root, borderwidth=0)
        self.scrim.place_forget()
        self.scrim.bind("<Button-1>", lambda _e: self.toggle_people_panel())

        # People header
        self.people_header = ttk.Frame(self.people_panel)
        self.people_header.pack(fill="x", padx=10, pady=(10, 6))
        self.people_title = ttk.Label(self.people_header, text="Люди", font=("Segoe UI", 12, "bold"))
        self.people_title.pack(side="left")

        self.pin_var = tk.BooleanVar(value=False)
        self.pin_btn = ttk.Checkbutton(self.people_header, text="Закрепить", variable=self.pin_var, command=self._on_pin_toggle)
        self.pin_btn.pack(side="right")

        # People cards list
        self.people_cards = ScrollableFrame(self.people_panel)
        self.people_cards.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Side "tab" arrow to open/close people panel (like a bookmark).
        self.people_tab_btn = ttk.Button(self.root, text=">", command=self.toggle_people_panel)
        self.people_tab_btn.place(x=0, rely=0.5, anchor="w")

        # Board header (no "Люди" button; people panel uses side tab)
        self.board_header = ttk.Frame(self.board_area)
        self.board_header.pack(fill="x", padx=12, pady=(10, 8))
        self.board_title = ttk.Label(self.board_header, text="Доска задач", font=("Segoe UI", 14, "bold"))
        self.board_title.pack(side="left")

        # Columns (4) in a horizontal scroll canvas
        self.columns_canvas = tk.Canvas(self.board_area, highlightthickness=0, borderwidth=0)
        self.columns_hscroll = ttk.Scrollbar(self.board_area, orient="horizontal", command=self.columns_canvas.xview)
        self.columns_canvas.configure(xscrollcommand=self.columns_hscroll.set)

        self.columns_canvas.pack(fill="both", expand=True, padx=12)
        self.columns_hscroll.pack(fill="x", padx=12, pady=(6, 12))

        self.columns_inner = ttk.Frame(self.columns_canvas)
        self._columns_inner_id = self.columns_canvas.create_window((0, 0), window=self.columns_inner, anchor="nw")

        def _on_inner_configure(_):
            self.columns_canvas.configure(scrollregion=self.columns_canvas.bbox("all"))

        self.columns_inner.bind("<Configure>", _on_inner_configure)

        def _on_canvas_configure(event):
            # Allow columns inner to be at least canvas width.
            self.columns_canvas.itemconfigure(self._columns_inner_id, height=event.height)
            self._update_columns_layout(event.width)

        self.columns_canvas.bind("<Configure>", _on_canvas_configure)
        self.board_area.bind("<Configure>", self._on_board_area_configure)

        # Create columns
        self._columns: dict[str, ScrollableFrame] = {}
        self._column_frames: dict[str, ttk.Frame] = {}
        for kind, title in [
            ("draft", "Черновик"),
            ("progress", "В процессе"),
            ("finished", "Завершено"),
            ("delayed", "Отложено"),
        ]:
            col = ttk.Frame(self.columns_inner)
            padx = (0, 12) if kind != "delayed" else (0, 0)
            col.pack(side="left", fill="y", padx=padx)
            col.configure(width=self._col_width)

            head = ttk.Frame(col)
            head.pack(fill="x", pady=(0, 8))
            ttk.Label(head, text=title, font=("Segoe UI", 12, "bold")).pack(anchor="w")

            body = ScrollableFrame(col)
            body.pack(fill="both", expand=True)

            self._columns[kind] = body
            self._column_frames[kind] = col

    def refresh_after_theme_change(self) -> None:
        theme = self.storage.get_ui_settings().get("theme", "dark")
        p = get_palette(theme)

        # tk widgets need manual styling
        try:
            self.columns_canvas.configure(background=p.bg)
        except Exception:
            pass
        try:
            self.people_cards.canvas.configure(background=p.bg)
        except Exception:
            pass

        self._apply_board_background()

        # Panel open/pin state
        ui = self.storage.get_ui_settings()
        self.pin_var.set(bool(ui.get("people_panel_pinned", False)))
        open_ = bool(ui.get("people_panel_open", False)) or self.pin_var.get()
        self._people_w = self._people_target_w if open_ else 0
        self._layout_people_panel()
        self._update_people_tab()

    def refresh_from_storage(self) -> None:
        self._refresh_people()
        self._refresh_tasks()
        self._apply_board_background()

    def _refresh_people(self) -> None:
        profile = self.storage.get_profile()
        subjects = self.storage.get_subjects()
        roles = {r.id: r for r in self.storage.get_roles()}

        for child in self.people_cards.inner.winfo_children():
            child.destroy()
        self._people_avatars.clear()

        theme = self.storage.get_ui_settings().get("theme", "dark")
        p = get_palette(theme)

        def add_person_card(name: str, role_name: str, role_color: str, avatar_path: str | None):
            card = tk.Frame(self.people_cards.inner, bg=p.surface2, highlightthickness=1, highlightbackground=p.surface)
            card.pack(fill="x", pady=6)

            row = tk.Frame(card, bg=p.surface2)
            row.pack(fill="x", padx=10, pady=8)

            initials = "".join([w[0] for w in name.split() if w][:2]) or "?"
            if avatar_path:
                try:
                    img = Image.open(avatar_path).convert("RGB")
                    img.thumbnail((34, 34), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                except Exception:
                    photo = _make_avatar(34, initials, p.accent)
            else:
                photo = _make_avatar(34, initials, p.accent)
            self._people_avatars.append(photo)

            tk.Label(row, image=photo, bg=p.surface2).pack(side="left")

            text_col = tk.Frame(row, bg=p.surface2)
            text_col.pack(side="left", padx=(10, 0), fill="x", expand=True)
            tk.Label(text_col, text=name, bg=p.surface2, fg=p.fg, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(text_col, text=role_name, bg=p.surface2, fg=role_color or p.muted_fg, font=("Segoe UI", 9)).pack(anchor="w")

        # Admin card
        admin_name = str(profile.get("nickname", "Администратор"))
        admin_role = roles.get(SYSTEM_ADMIN_ROLE_ID)
        admin_color = admin_role.color if admin_role else p.fg
        add_person_card(admin_name, "Администратор", admin_color, profile.get("avatar_path"))

        # Subjects cards
        for s in sorted(subjects, key=lambda x: str(x.get("nickname", "")).lower()):
            nickname = str(s.get("nickname", ""))
            role_ids = [rid for rid in (s.get("role_ids") or []) if rid not in (SYSTEM_NONE_ROLE_ID,)]
            # Pick highest-priority role as "должность"
            best_role = None
            for rid in role_ids:
                r = roles.get(str(rid))
                if not r:
                    continue
                if best_role is None or r.priority < best_role.priority:
                    best_role = r
            role_name = best_role.name if best_role else "Без роли"
            role_color = best_role.color if best_role else p.muted_fg
            add_person_card(nickname, role_name, role_color, s.get("avatar_path"))

    def _update_people_tab(self) -> None:
        # If pinned, the panel is always visible and the arrow-tab is hidden.
        if self.pin_var.get():
            self.people_tab_btn.place_forget()
            return
        # Place the tab at the left edge of the board / panel edge.
        if self._people_w <= 0:
            self.people_tab_btn.configure(text=">")
            self.people_tab_btn.place(x=0, rely=0.5, anchor="w")
        else:
            self.people_tab_btn.configure(text="<")
            self.people_tab_btn.place(x=self._people_w, rely=0.5, anchor="w")

    def _refresh_tasks(self) -> None:
        subjects = self.storage.get_subjects()
        subj_name = {str(s.get("id")): str(s.get("nickname")) for s in subjects}

        for kind, container in self._columns.items():
            for child in container.inner.winfo_children():
                child.destroy()

            tasks = self.storage.load_tasks(kind)
            # Most recent on top
            for t in reversed(tasks):
                self._add_task_card(container.inner, kind, t, subj_name)

    def _add_task_card(self, parent: tk.Misc, kind: str, task: dict, subj_name: dict[str, str]) -> None:
        theme = self.storage.get_ui_settings().get("theme", "dark")
        p = get_palette(theme)

        card = tk.Frame(parent, bg=p.surface2, highlightthickness=1, highlightbackground=p.surface, highlightcolor=p.accent)
        card.pack(fill="x", pady=6, padx=4)

        title = str(task.get("title") or task.get("name") or "Без названия")
        wrap = max(int(self._col_width) - 60, 180)
        tk.Label(card, text=title, bg=p.surface2, fg=p.fg, font=("Segoe UI", 11, "bold"), wraplength=wrap, justify="left").pack(
            anchor="w", padx=10, pady=(8, 2)
        )

        responsible_id = str(task.get("responsible_subject_id") or "")
        resp = subj_name.get(responsible_id, "—")
        tk.Label(card, text=f"Ответственный: {resp}", bg=p.surface2, fg=p.muted_fg, wraplength=wrap, justify="left").pack(
            anchor="w", padx=10, pady=2
        )

        start_due = task.get("start_due")
        end_due = task.get("end_due")
        if kind != "finished":
            tk.Label(
                card,
                text=f"Начало: {_fmt(start_due)} · Конец: {_fmt(end_due)}",
                bg=p.surface2,
                fg=p.muted_fg,
                wraplength=wrap,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(2, 8))
        else:
            tk.Label(card, text="Завершено", bg=p.surface2, fg=p.muted_fg).pack(anchor="w", padx=10, pady=(2, 8))

    # --- People panel behavior ---
    def _layout_people_panel(self) -> None:
        self.people_panel.place_configure(width=self._people_w)
        # If pinned -> panel takes layout space; otherwise it overlays the board.
        if self.pin_var.get():
            self.board_area.place_configure(x=self._people_w)
            self._hide_scrim()
        else:
            self.board_area.place_configure(x=0)
            if self._people_w > 0:
                self._show_scrim()
                # Ensure panel is above scrim/board.
                try:
                    self.people_panel.tkraise()
                except Exception:
                    pass
            else:
                self._hide_scrim()
        self._update_people_tab()
        self._update_columns_layout(self.columns_canvas.winfo_width())

    def _update_columns_layout(self, canvas_width: int) -> None:
        # Hide horizontal scrollbar when all 4 columns fit.
        gap = 12
        min_w = 260
        max_w = 99999
        # In overlay mode columns should use full width; in pinned mode board is already shifted.
        available = max(int(canvas_width) - 4, 0)
        # Prefer even columns when possible
        even = int((available - gap * 3) / 4) if available else min_w
        even = max(min_w, min(max_w, even))
        total_needed = even * 4 + gap * 3

        if total_needed <= available and available > 0:
            # No need to scroll horizontally.
            self._col_width = even
            for col in self._column_frames.values():
                col.configure(width=self._col_width)
            # Stretch the inner window to the full canvas width so there is no "empty tail".
            try:
                self.columns_canvas.itemconfigure(self._columns_inner_id, width=available)
            except Exception:
                pass
            if self._hscroll_visible:
                self.columns_hscroll.pack_forget()
                self._hscroll_visible = False
            try:
                self.columns_canvas.xview_moveto(0)
            except Exception:
                pass
        else:
            # Enable horizontal scrolling.
            self._col_width = 320
            for col in self._column_frames.values():
                col.configure(width=self._col_width)
            try:
                self.columns_canvas.itemconfigure(self._columns_inner_id, width=self._col_width * 4 + gap * 3)
            except Exception:
                pass
            if not self._hscroll_visible:
                self.columns_hscroll.pack(fill="x", padx=12, pady=(6, 12))
                self._hscroll_visible = True

    def _on_board_area_configure(self, event) -> None:
        # Keep background image scaled to board area.
        try:
            w, h = int(event.width), int(event.height)
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        self._apply_board_background(target_size=(w, h))
        # Resize scrim smoothly if visible.
        if self.scrim.winfo_ismapped():
            self._show_scrim()

    def _apply_board_background(self, target_size: tuple[int, int] | None = None) -> None:
        if self._board_bg_label is None:
            return
        ui = self.storage.get_ui_settings()
        path = ui.get("background_image_path")
        if not path:
            self._board_bg_label.configure(image="", background=ui.get("background_color", "#1F1F1F"))
            self._board_bg_photo = None
            self._board_bg_path = None
            return
        if path != self._board_bg_path:
            self._board_bg_path = path
        try:
            img = Image.open(path).convert("RGB")
        except Exception:
            self._board_bg_label.configure(image="", background=ui.get("background_color", "#1F1F1F"))
            self._board_bg_photo = None
            return
        if target_size is None:
            # Best effort size
            w = max(self.board_area.winfo_width(), 1)
            h = max(self.board_area.winfo_height(), 1)
            target_size = (w, h)
        img = img.resize((max(1, target_size[0]), max(1, target_size[1])), Image.LANCZOS)
        self._board_bg_photo = ImageTk.PhotoImage(img)
        self._board_bg_label.configure(image=self._board_bg_photo)
        # Keep bg behind header and columns
        try:
            self._board_bg_label.lower(self.board_header)
        except Exception:
            self._board_bg_label.lower()

    def toggle_people_panel(self) -> None:
        if self.pin_var.get():
            return
        target_open = self._people_w == 0
        self._animate_people_panel(open_=target_open)
        ui = self.storage.get_ui_settings()
        ui["people_panel_open"] = bool(target_open)
        self.storage.save_ui_settings(ui)

    def _on_pin_toggle(self) -> None:
        pinned = bool(self.pin_var.get())
        ui = self.storage.get_ui_settings()
        ui["people_panel_pinned"] = pinned
        if pinned:
            ui["people_panel_open"] = True
            self.storage.save_ui_settings(ui)
            self._animate_people_panel(open_=True)
        else:
            self.storage.save_ui_settings(ui)
            # When unpinning, panel becomes overlay; show arrow-tab again.
            self._update_people_tab()
            self._layout_people_panel()

    def _animate_people_panel(self, open_: bool) -> None:
        if self._anim_after is not None:
            try:
                self.after_cancel(self._anim_after)
            except Exception:
                pass
            self._anim_after = None

        self._anim_from_w = int(self._people_w)
        self._anim_to_w = int(self._people_target_w if open_ else 0)
        self._anim_start_t = time.perf_counter()

        def ease_out_cubic(t: float) -> float:
            t = max(0.0, min(1.0, t))
            return 1 - (1 - t) ** 3

        def step():
            now = time.perf_counter()
            dt = now - self._anim_start_t
            t = dt / self._anim_duration_s if self._anim_duration_s > 0 else 1.0
            if t >= 1.0:
                self._people_w = self._anim_to_w
                self._layout_people_panel()
                self._anim_after = None
                return

            k = ease_out_cubic(t)
            w = int(self._anim_from_w + (self._anim_to_w - self._anim_from_w) * k)
            self._people_w = w
            self._layout_people_panel()
            self._anim_after = self.after(16, step)  # ~60fps

        step()

    def _show_scrim(self) -> None:
        w = max(self.root.winfo_width() - 1, 1)
        h = max(self.root.winfo_height() - 1, 1)
        self.scrim.place(x=0, y=0, width=w, height=h)
        # Build a semi-transparent overlay image (no stipple artifacts).
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 120))
        self._scrim_photo = ImageTk.PhotoImage(overlay)
        self.scrim.configure(image=self._scrim_photo)
        try:
            self.scrim.tkraise()
        except Exception:
            pass
        try:
            self.people_panel.tkraise()
        except Exception:
            pass

    def _hide_scrim(self) -> None:
        self.scrim.place_forget()

