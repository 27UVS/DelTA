from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from app.theme import get_palette
from app.storage import (
    Storage,
    SYSTEM_ADMIN_ROLE_ID,
    SYSTEM_NONE_ROLE_ID,
    SYSTEM_STATUS_NONE_ID,
)
from app.assets import get_interface_assets
from app.ui_icon_loader import IconLoader


def _format_dt(value: str | None) -> str:
    if not value:
        return "—"
    return str(value)


def _get_role_display_color(role_color: str) -> str:
    # Keep as hex string; UI can be enhanced later with colored dots.
    return role_color or "#BDBDBD"


def _apply_dialog_palette(dialog: tk.Toplevel, storage: Storage) -> dict[str, str]:
    theme = storage.get_ui_settings().get("theme", "dark")
    p = get_palette(theme)
    dialog.configure(background=p.bg)
    return {
        "bg": p.bg,
        "surface2": p.surface2,
        "fg": p.fg,
        "muted_fg": p.muted_fg,
        "accent": p.accent,
        "entry_bg": p.bg,  # "no background" look
        "entry_fg": p.fg,
    }


def _flat_entry(parent: tk.Misc, palette: dict[str, str], textvariable: tk.StringVar, width: int, state: str = "normal"):
    e = tk.Entry(
        parent,
        textvariable=textvariable,
        width=width,
        relief="flat",
        bg=palette["entry_bg"],
        fg=palette["entry_fg"],
        insertbackground=palette["entry_fg"],
        highlightthickness=1,
        highlightbackground=palette["surface2"],
        highlightcolor=palette["accent"],
        disabledbackground=palette["entry_bg"],
        disabledforeground=palette["muted_fg"],
    )
    e.configure(state=state)
    return e


def _flat_spinbox(parent: tk.Misc, palette: dict[str, str], variable: tk.IntVar, width: int, state: str = "normal"):
    s = tk.Spinbox(
        parent,
        from_=0,
        to=99999,
        textvariable=variable,
        width=width,
        relief="flat",
        bg=palette["entry_bg"],
        fg=palette["entry_fg"],
        insertbackground=palette["entry_fg"],
        highlightthickness=1,
        highlightbackground=palette["surface2"],
        highlightcolor=palette["accent"],
        disabledbackground=palette["entry_bg"],
        disabledforeground=palette["muted_fg"],
        buttonbackground=palette["surface2"],
    )
    s.configure(state=state)
    return s


class RoleDialog(tk.Toplevel):
    def __init__(self, master, storage: Storage, role: dict | None, on_saved):
        super().__init__(master)
        self.storage = storage
        self.role = role
        self.on_saved = on_saved
        self.title("Роль" if role is None else "Редактировать роль")
        self.resizable(False, False)
        palette = _apply_dialog_palette(self, storage)

        self.name_var = tk.StringVar(value=(role or {}).get("name", ""))
        self.color_var = tk.StringVar(value=(role or {}).get("color", "#BDBDBD"))
        self.priority_var = tk.IntVar(value=int((role or {}).get("priority", 9999)))

        locked = bool((role or {}).get("locked", False))
        is_admin = bool(role and role.get("id") == SYSTEM_ADMIN_ROLE_ID)
        # Admin role: allow editing color, but keep name/priority locked.
        name_priority_locked = locked
        color_locked = locked and not is_admin

        root = tk.Frame(self, bg=palette["bg"])
        root.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self.columnconfigure(0, weight=1)

        lbl_name = tk.Label(root, text="Название", bg=palette["bg"], fg=palette["fg"])
        lbl_name.grid(row=0, column=0, sticky="w", pady=(0, 6))
        name_state = "disabled" if name_priority_locked else "normal"
        _flat_entry(root, palette, self.name_var, width=34, state=name_state).grid(row=0, column=1, sticky="ew", pady=(0, 6))

        lbl_color = tk.Label(root, text="Цвет", bg=palette["bg"], fg=palette["fg"])
        lbl_color.grid(row=1, column=0, sticky="w", pady=6)
        color_btn = ttk.Button(root, text="Выбрать…", command=self._choose_color)
        color_btn.grid(row=1, column=1, sticky="w", pady=6)
        self.color_value_label = tk.Label(root, textvariable=self.color_var, bg=palette["bg"], fg=palette["fg"])
        self.color_value_label.grid(row=1, column=2, sticky="w", padx=(10, 0), pady=6)
        if color_locked:
            color_btn.state(["disabled"])

        lbl_pr = tk.Label(root, text="Приоритет (меньше = выше)", bg=palette["bg"], fg=palette["fg"])
        lbl_pr.grid(row=2, column=0, sticky="w", pady=6)
        pr_state = "disabled" if name_priority_locked else "normal"
        _flat_spinbox(root, palette, self.priority_var, width=8, state=pr_state).grid(row=2, column=1, sticky="w", pady=6)

        btns = tk.Frame(root, bg=palette["bg"])
        btns.grid(row=3, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=(10, 0))
        self.save_btn = ttk.Button(
            btns,
            text="Сохранить",
            command=self._on_save,
            state=("disabled" if (locked and not is_admin) else "normal"),
        )
        self.save_btn.pack(side="right")

        self.grab_set()

    def _choose_color(self) -> None:
        c = colorchooser.askcolor(title="Выберите цвет", initialcolor=self.color_var.get())
        if not c or not c[1]:
            return
        self.color_var.set(c[1])

    def _on_save(self) -> None:
        try:
            name = self.name_var.get()
            color = self.color_var.get()
            priority = int(self.priority_var.get())
            if self.role is None:
                self.storage.add_role(name=name, color=color, priority=priority)
            else:
                self.storage.update_role(role_id=self.role["id"], name=name, color=color, priority=priority)
            self.on_saved()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e), parent=self)


class StatusDialog(tk.Toplevel):
    def __init__(self, master, storage: Storage, status: dict | None, on_saved):
        super().__init__(master)
        self.storage = storage
        self.status = status
        self.on_saved = on_saved
        self.title("Статус" if status is None else "Редактировать статус")
        self.resizable(False, False)
        palette = _apply_dialog_palette(self, storage)

        self.name_var = tk.StringVar(value=(status or {}).get("name", ""))
        locked = bool((status or {}).get("locked", False))

        root = tk.Frame(self, bg=palette["bg"])
        root.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self.columnconfigure(0, weight=1)

        tk.Label(root, text="Название", bg=palette["bg"], fg=palette["fg"]).grid(row=0, column=0, sticky="w", pady=(0, 6))
        st_state = "disabled" if locked else "normal"
        _flat_entry(root, palette, self.name_var, width=34, state=st_state).grid(row=0, column=1, sticky="ew", pady=(0, 6))

        btns = tk.Frame(root, bg=palette["bg"])
        btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=(10, 0))
        ttk.Button(
            btns,
            text="Сохранить",
            command=self._on_save,
            state=("disabled" if locked else "normal"),
        ).pack(side="right")

        self.grab_set()

    def _on_save(self) -> None:
        try:
            name = self.name_var.get()
            if self.status is None:
                self.storage.add_status(name=name)
            else:
                self.storage.update_status(status_id=self.status["id"], name=name)
            self.on_saved()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e), parent=self)


class SubjectDialog(tk.Toplevel):
    def __init__(self, master, storage: Storage, subject: dict | None, on_saved):
        super().__init__(master)
        self.storage = storage
        self.subject = subject
        self.on_saved = on_saved
        self.title("Субъект" if subject is None else "Редактировать субъект")
        self.resizable(False, False)
        palette = _apply_dialog_palette(self, storage)

        self.nickname_var = tk.StringVar(value=(subject or {}).get("nickname", ""))
        self.status_var = tk.StringVar(value=(subject or {}).get("status_id", SYSTEM_STATUS_NONE_ID))

        selected_role_ids = set((subject or {}).get("role_ids", []) or [])
        if not selected_role_ids:
            selected_role_ids = {SYSTEM_NONE_ROLE_ID}

        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        statuses = self.storage.get_statuses()

        root = tk.Frame(self, bg=palette["bg"])
        root.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)

        tk.Label(root, text="Никнейм", bg=palette["bg"], fg=palette["fg"]).grid(row=0, column=0, sticky="w", pady=(0, 6))
        _flat_entry(root, palette, self.nickname_var, width=34).grid(row=0, column=1, sticky="ew", pady=(0, 6))

        # Status selector (flat dropdown).
        tk.Label(root, text="Статус", bg=palette["bg"], fg=palette["fg"]).grid(row=1, column=0, sticky="w", pady=6)
        status_names = {s.id: s.name for s in statuses}
        status_values = [status_names[s.id] for s in statuses if s.id != SYSTEM_STATUS_NONE_ID] or ["Доступен"]
        self.status_name_var = tk.StringVar()
        cur_name = status_names.get(self.status_var.get(), "Доступен")
        if cur_name not in status_values:
            cur_name = status_values[0]
        self.status_name_var.set(cur_name)

        # Map name -> id on save. (System none is implicit.)
        name_to_status_id = {s.name: s.id for s in statuses if s.id != SYSTEM_STATUS_NONE_ID}

        status_menu = tk.OptionMenu(root, self.status_name_var, *status_values)
        status_menu.configure(
            bg=palette["surface2"],
            fg=palette["fg"],
            activebackground=palette["accent"],
            activeforeground="#FFFFFF",
            highlightthickness=0,
            relief="flat",
            padx=8,
            pady=2,
        )
        try:
            status_menu["menu"].configure(
                bg=palette["surface2"],
                fg=palette["fg"],
                activebackground=palette["accent"],
                activeforeground="#FFFFFF",
                relief="flat",
                borderwidth=0,
            )
        except Exception:
            pass
        status_menu.grid(row=1, column=1, sticky="w", pady=6)

        tk.Label(root, text="Роли (можно несколько)", bg=palette["bg"], fg=palette["fg"]).grid(
            row=2, column=0, sticky="nw", pady=(12, 6)
        )
        roles_frame = tk.Frame(root, bg=palette["bg"])
        roles_frame.grid(row=2, column=1, sticky="w", pady=(12, 6))

        self._role_vars: dict[str, tk.BooleanVar] = {}
        self._none_role_var = tk.BooleanVar(value=(SYSTEM_NONE_ROLE_ID in selected_role_ids))

        def _on_none_changed() -> None:
            if self._none_role_var.get():
                for rid, var in self._role_vars.items():
                    if rid != SYSTEM_NONE_ROLE_ID:
                        var.set(False)
            # If none role unchecked, keep current selection (user can pick roles).

        self._none_role_cb = tk.Checkbutton(
            roles_frame,
            text="Без роли",
            variable=self._none_role_var,
            command=_on_none_changed,
            bg=palette["bg"],
            fg=palette["fg"],
            activebackground=palette["bg"],
            activeforeground=palette["fg"],
            selectcolor=palette["bg"],
        )
        self._none_role_cb.pack(anchor="w", pady=2)

        # Other roles excluding none.
        for r in roles:
            if r.id == SYSTEM_NONE_ROLE_ID:
                continue
            var = tk.BooleanVar(value=(r.id in selected_role_ids))
            self._role_vars[r.id] = var
            cb = tk.Checkbutton(
                roles_frame,
                text=r.name,
                variable=var,
                bg=palette["bg"],
                fg=palette["fg"],
                activebackground=palette["bg"],
                activeforeground=palette["fg"],
                selectcolor=palette["bg"],
            )
            cb.pack(anchor="w", pady=2)

        def _on_other_changed() -> None:
            # If any other role selected => uncheck "Без роли".
            if any(v.get() for v in self._role_vars.values()):
                self._none_role_var.set(False)
            else:
                # If user unchecks all roles, revert to "Без роли".
                self._none_role_var.set(True)

        for v in self._role_vars.values():
            v.trace_add("write", lambda *_: _on_other_changed())

        btns = tk.Frame(root, bg=palette["bg"])
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=(10, 0))
        ttk.Button(btns, text="Сохранить", command=lambda: self._on_save(name_to_status_id)).pack(side="right")

        self.grab_set()

    def _on_save(self, name_to_status_id: dict[str, str]) -> None:
        try:
            nickname = self.nickname_var.get().strip()
            if not nickname:
                raise ValueError("Никнейм не может быть пустым.")

            # Status is selected by name -> id.
            status_name = self.status_name_var.get()
            status_id = name_to_status_id.get(status_name, SYSTEM_STATUS_NONE_ID)

            if self._none_role_var.get():
                role_ids = [SYSTEM_NONE_ROLE_ID]
            else:
                role_ids = [rid for rid, var in self._role_vars.items() if var.get()]
                if not role_ids:
                    role_ids = [SYSTEM_NONE_ROLE_ID]

            if self.subject is None:
                self.storage.add_subject(nickname=nickname, role_ids=role_ids, status_id=status_id)
            else:
                self.storage.update_subject(
                    subject_id=self.subject["id"],
                    nickname=nickname,
                    role_ids=role_ids,
                    status_id=status_id,
                )
            self.on_saved()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e), parent=self)


class TablesPage(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage):
        super().__init__(parent)
        self.storage = storage
        self._icons = IconLoader()
        self._assets = get_interface_assets()

        header = ttk.Label(self, text="Параметры", font=("Segoe UI", 16, "bold"))
        header.pack(anchor="w", padx=18, pady=(16, 10))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        self.roles_tab = ttk.Frame(self.notebook)
        self.statuses_tab = ttk.Frame(self.notebook)
        self.tasks_tab = ttk.Frame(self.notebook)
        self.subjects_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.roles_tab, text="Роли")
        self.notebook.add(self.statuses_tab, text="Статусы")
        self.notebook.add(self.tasks_tab, text="Задачи")
        self.notebook.add(self.subjects_tab, text="Субъекты")

        self._build_roles_tab()
        self._build_statuses_tab()
        self._build_tasks_tab()
        self._build_subjects_tab()

        self.refresh_all()

    def refresh_after_theme_change(self) -> None:
        # Recreate trees to update colors properly.
        self.refresh_all()

    # ---------------- Roles ----------------
    def _build_roles_tab(self) -> None:
        top = ttk.Frame(self.roles_tab)
        top.pack(fill="x", pady=(0, 10))
        add_img = self._icons.load_png(self._assets.add_button_png, (18, 18))
        edit_img = self._icons.load_png(self._assets.edit_button_png, (18, 18))
        del_img = self._icons.load_png(self._assets.delete_button_png, (18, 18))
        ttk.Button(top, text="Добавить", image=add_img, compound="left", command=self._on_add_role).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(top, text="Редактировать", image=edit_img, compound="left", command=self._on_edit_role).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(top, text="Удалить", image=del_img, compound="left", command=self._on_delete_role).pack(side="left")

        columns = ("name", "color", "priority")
        # Use a tree column (#0) to display a color swatch.
        self.roles_tree = ttk.Treeview(
            self.roles_tab, columns=columns, show=("tree", "headings"), selectmode="browse", height=12
        )
        self.roles_tree.heading("#0", text="")
        self.roles_tree.column("#0", width=26, anchor="center", stretch=False)
        self.roles_tree.heading("name", text="Название")
        self.roles_tree.heading("color", text="Цвет (HEX)")
        self.roles_tree.heading("priority", text="Приоритет")
        self.roles_tree.column("name", width=260, anchor="w")
        self.roles_tree.column("color", width=140, anchor="w")
        self.roles_tree.column("priority", width=120, anchor="center")
        self.roles_tree.pack(fill="x")

    def refresh_roles(self) -> None:
        for item in self.roles_tree.get_children():
            self.roles_tree.delete(item)
        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        for r in roles:
            # Hide system "Без роли" from the roles table (system-only).
            if r.id == SYSTEM_NONE_ROLE_ID:
                continue
            swatch = self._icons.load_color_swatch(r.color, (14, 14))
            self.roles_tree.insert(
                "",
                "end",
                iid=str(r.id),
                image=swatch,
                values=(r.name, _get_role_display_color(r.color), str(r.priority)),
            )

    def _selected_role_id(self) -> str | None:
        sel = self.roles_tree.selection()
        if not sel:
            return None
        return str(sel[0])

    def _on_add_role(self) -> None:
        RoleDialog(self, self.storage, role=None, on_saved=self.refresh_all)

    def _on_edit_role(self) -> None:
        rid = self._selected_role_id()
        if not rid:
            messagebox.showinfo("Инфо", "Выберите роль.")
            return
        roles = {r.id: r for r in self.storage.get_roles()}
        role = roles.get(rid)
        if not role:
            return
        RoleDialog(
            self,
            self.storage,
            role={"id": role.id, "name": role.name, "color": role.color, "priority": role.priority, "locked": role.locked},
            on_saved=self.refresh_all,
        )

    def _on_delete_role(self) -> None:
        rid = self._selected_role_id()
        if not rid:
            messagebox.showinfo("Инфо", "Выберите роль.")
            return
        roles = {r.id: r for r in self.storage.get_roles()}
        role = roles.get(rid)
        if not role:
            return
        if role.locked:
            messagebox.showwarning("Запрещено", "Системную роль нельзя удалить.")
            return

        if not messagebox.askyesno("Подтверждение", f"Удалить роль '{role.name}'?"):
            return
        try:
            self.storage.delete_role(rid)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # ---------------- Statuses ----------------
    def _build_statuses_tab(self) -> None:
        top = ttk.Frame(self.statuses_tab)
        top.pack(fill="x", pady=(0, 10))
        add_img = self._icons.load_png(self._assets.add_button_png, (18, 18))
        edit_img = self._icons.load_png(self._assets.edit_button_png, (18, 18))
        del_img = self._icons.load_png(self._assets.delete_button_png, (18, 18))
        ttk.Button(top, text="Добавить", image=add_img, compound="left", command=self._on_add_status).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(top, text="Редактировать", image=edit_img, compound="left", command=self._on_edit_status).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(top, text="Удалить", image=del_img, compound="left", command=self._on_delete_status).pack(side="left")

        columns = ("name",)
        self.status_tree = ttk.Treeview(self.statuses_tab, columns=columns, show="headings", selectmode="browse", height=12)
        self.status_tree.heading("name", text="Название")
        self.status_tree.column("name", width=420, anchor="w")
        self.status_tree.pack(fill="x")

    def refresh_statuses(self) -> None:
        for item in self.status_tree.get_children():
            self.status_tree.delete(item)
        for s in sorted(self.storage.get_statuses(), key=lambda st: st.name.lower()):
            # Hide system "Без статуса" from the statuses table (system-only).
            if s.id == SYSTEM_STATUS_NONE_ID:
                continue
            self.status_tree.insert("", "end", iid=str(s.id), values=(s.name,))

    def _selected_status_id(self) -> str | None:
        sel = self.status_tree.selection()
        if not sel:
            return None
        return str(sel[0])

    def _on_add_status(self) -> None:
        StatusDialog(self, self.storage, status=None, on_saved=self.refresh_all)

    def _on_edit_status(self) -> None:
        sid = self._selected_status_id()
        if not sid:
            messagebox.showinfo("Инфо", "Выберите статус.")
            return
        statuses = {s.id: s for s in self.storage.get_statuses()}
        status = statuses.get(sid)
        if not status:
            return
        StatusDialog(
            self,
            self.storage,
            status={"id": status.id, "name": status.name, "locked": status.locked},
            on_saved=self.refresh_all,
        )

    def _on_delete_status(self) -> None:
        sid = self._selected_status_id()
        if not sid:
            messagebox.showinfo("Инфо", "Выберите статус.")
            return
        statuses = {s.id: s for s in self.storage.get_statuses()}
        status = statuses.get(sid)
        if not status:
            return
        if status.locked:
            messagebox.showwarning("Запрещено", "Системный статус нельзя удалить.")
            return
        if not messagebox.askyesno("Подтверждение", f"Удалить статус '{status.name}'?"):
            return
        try:
            self.storage.delete_status(sid)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # ---------------- Subjects ----------------
    def _build_subjects_tab(self) -> None:
        top = ttk.Frame(self.subjects_tab)
        top.pack(fill="x", pady=(0, 10))
        add_img = self._icons.load_png(self._assets.add_button_png, (18, 18))
        edit_img = self._icons.load_png(self._assets.edit_button_png, (18, 18))
        del_img = self._icons.load_png(self._assets.delete_button_png, (18, 18))
        ttk.Button(top, text="Добавить", image=add_img, compound="left", command=self._on_add_subject).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(top, text="Редактировать", image=edit_img, compound="left", command=self._on_edit_subject).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(top, text="Удалить", image=del_img, compound="left", command=self._on_delete_subject).pack(side="left")

        columns = ("nickname", "tasks", "created_at")
        self.subjects_tree = ttk.Treeview(self.subjects_tab, columns=columns, show="headings", selectmode="browse", height=14)
        self.subjects_tree.heading("nickname", text="Никнейм")
        self.subjects_tree.heading("tasks", text="Активных задач")
        self.subjects_tree.heading("created_at", text="Добавлен")
        self.subjects_tree.column("nickname", width=260, anchor="w")
        self.subjects_tree.column("tasks", width=140, anchor="center")
        self.subjects_tree.column("created_at", width=240, anchor="w")
        self.subjects_tree.pack(fill="x")

    def refresh_subjects(self) -> None:
        for item in self.subjects_tree.get_children():
            self.subjects_tree.delete(item)

        subjects = self.storage.get_subjects()
        # Cache active counts for speed.
        active_counts = {
            str(s.get("id")): self.storage.compute_active_tasks_count_for_subject(s.get("id"))
            for s in subjects
        }

        for s in sorted(subjects, key=lambda ss: str(ss.get("nickname", "")).lower()):
            sid = str(s.get("id"))
            self.subjects_tree.insert(
                "",
                "end",
                iid=sid,
                values=(s.get("nickname", ""), str(active_counts.get(sid, 0)), s.get("created_at", "")),
            )

    def _selected_subject_id(self) -> str | None:
        sel = self.subjects_tree.selection()
        if not sel:
            return None
        return str(sel[0])

    def _get_subject_by_id(self, subject_id: str) -> dict | None:
        for s in self.storage.get_subjects():
            if str(s.get("id")) == str(subject_id):
                return s
        return None

    def _on_add_subject(self) -> None:
        SubjectDialog(self, self.storage, subject=None, on_saved=self.refresh_all)

    def _on_edit_subject(self) -> None:
        sid = self._selected_subject_id()
        if not sid:
            messagebox.showinfo("Инфо", "Выберите субъект.")
            return
        subject = self._get_subject_by_id(sid)
        if not subject:
            return
        SubjectDialog(self, self.storage, subject=subject, on_saved=self.refresh_all)

    def _on_delete_subject(self) -> None:
        sid = self._selected_subject_id()
        if not sid:
            messagebox.showinfo("Инфо", "Выберите субъект.")
            return

        active = self.storage.compute_active_tasks_count_for_subject(sid)
        if active > 0:
            messagebox.showerror("Запрещено", "Нельзя удалить субъект с активными задачами.")
            return

        subject = self._get_subject_by_id(sid)
        nick = subject.get("nickname", "") if subject else sid
        if not messagebox.askyesno("Подтверждение", f"Удалить субъект '{nick}'?"):
            return

        try:
            self.storage.delete_subject(sid)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # ---------------- Tasks ----------------
    def _build_tasks_tab(self) -> None:
        # Read-only tasks view in a nested notebook.
        self.tasks_notebook = ttk.Notebook(self.tasks_tab)
        self.tasks_notebook.pack(fill="both", expand=True)

        self.tasks_trees: dict[str, ttk.Treeview] = {}
        for kind, title in [
            ("draft", "Черновик"),
            ("progress", "В процессе"),
            ("finished", "Завершено"),
            ("delayed", "Отложено"),
        ]:
            frame = ttk.Frame(self.tasks_notebook)
            self.tasks_notebook.add(frame, text=title)

            columns = ("title", "created_at", "start_due", "end_due", "responsible", "description")
            tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="none", height=14)
            tree.heading("title", text="Название")
            tree.heading("created_at", text="Создано")
            tree.heading("start_due", text="Срок начала")
            tree.heading("end_due", text="Срок конца")
            tree.heading("responsible", text="Ответственный")
            tree.heading("description", text="Описание")
            # Use stretch to avoid clipping issues on resize (Windows ttk can mis-measure until maximize).
            tree.column("title", width=200, minwidth=140, anchor="w", stretch=True)
            tree.column("created_at", width=140, minwidth=120, anchor="w", stretch=False)
            tree.column("start_due", width=140, minwidth=120, anchor="w", stretch=False)
            tree.column("end_due", width=120, minwidth=110, anchor="w", stretch=False)
            tree.column("responsible", width=160, minwidth=120, anchor="w", stretch=False)
            tree.column("description", width=380, minwidth=200, anchor="w", stretch=True)
            tree.pack(fill="both", expand=True)
            self.tasks_trees[kind] = tree

            # Auto-resize the description column to the remaining width.
            def _on_frame_configure(event, _tree=tree):
                self._autosize_tasks_tree(_tree, event.width)

            frame.bind("<Configure>", _on_frame_configure)

    def _autosize_tasks_tree(self, tree: ttk.Treeview, total_width: int) -> None:
        # Reserve some padding for borders/scrollbars.
        available = max(int(total_width) - 24, 200)
        fixed = 0
        for col in ("created_at", "start_due", "end_due", "responsible"):
            try:
                fixed += int(tree.column(col, "width"))
            except Exception:
                pass
        # Title gets a baseline; the rest goes to description.
        title_w = int(tree.column("title", "width"))
        desc_w = max(available - fixed - title_w, 220)
        try:
            tree.column("description", width=desc_w)
        except Exception:
            pass

    def refresh_tasks(self) -> None:
        subjects = self.storage.get_subjects()
        subj_name = {str(s.get("id")): str(s.get("nickname")) for s in subjects}

        for kind, tree in self.tasks_trees.items():
            for item in tree.get_children():
                tree.delete(item)

            tasks = self.storage.load_tasks(kind)
            for idx, t in enumerate(tasks):
                tid = str(t.get("id") or "").strip()
                iid = tid if tid else f"row_{kind}_{idx}"
                responsible_id = str(t.get("responsible_subject_id") or "")
                tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        str(t.get("title") or ""),
                        _format_dt(t.get("created_at")),
                        _format_dt(t.get("start_due")),
                        _format_dt(t.get("end_due")),
                        subj_name.get(responsible_id, "—"),
                        str(t.get("description") or ""),
                    ),
                )

    # ---------------- Refresh ----------------
    def refresh_all(self) -> None:
        self.refresh_roles()
        self.refresh_statuses()
        self.refresh_subjects()
        self.refresh_tasks()

