from __future__ import annotations

import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from PIL import Image, ImageTk, ImageDraw, ImageFont

from app.storage import Storage, SYSTEM_ADMIN_ROLE_ID, SYSTEM_NONE_ROLE_ID
from app.theme import get_palette


def _make_placeholder_avatar(size: int, initials: str) -> ImageTk.PhotoImage:
    img = Image.new("RGB", (size, size), color="#3A7CFF")
    draw = ImageDraw.Draw(img)
    # White-ish text.
    text_color = (255, 255, 255)
    # Try to use a default font.
    try:
        font = ImageFont.truetype("arial.ttf", size // 3)
    except Exception:
        font = ImageFont.load_default()

    # Center text.
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2), initials, fill=text_color, font=font)
    return ImageTk.PhotoImage(img)


class ProfilePage(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage):
        super().__init__(parent)
        self.storage = storage

        self._avatar_photo = None
        self._roles_vars: dict[str, tk.BooleanVar] = {}

        self._build()
        self.refresh_from_storage()

    def _build(self) -> None:
        header = ttk.Label(self, text="Профиль (админ)", font=("Segoe UI", 16, "bold"))
        header.pack(anchor="w", padx=18, pady=(16, 10))

        form = ttk.Frame(self)
        form.pack(fill="x", padx=18)

        # Avatar column.
        self.avatar_box = ttk.Frame(form, width=150)
        self.avatar_box.pack(side="left", padx=(0, 22), pady=8)
        self.avatar_label = ttk.Label(self.avatar_box)
        self.avatar_label.pack()
        self.avatar_hint = ttk.Label(
            self.avatar_box, text="Аватар влияет на внешний вид профиля", wraplength=160
        )
        self.avatar_hint.pack(pady=(6, 0))

        choose_btn = ttk.Button(self.avatar_box, text="Выбрать аватар", command=self._on_choose_avatar)
        choose_btn.pack(pady=(10, 0))

        # Main fields.
        fields = ttk.Frame(form)
        fields.pack(side="left", fill="x", expand=True)

        row = 0
        ttk.Label(fields, text="Никнейм:").grid(row=row, column=0, sticky="w", pady=4)
        self.nickname_var = tk.StringVar()
        ttk.Entry(fields, textvariable=self.nickname_var, width=42).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        # Links.
        links = [
            ("YouTube", "youtube"),
            ("Instagram", "instagram"),
            ("Tumblr", "tumblr"),
            ("X (Twitter)", "x"),
            ("Telegram", "telegram"),
            ("VK", "vk"),
        ]
        self._link_vars: dict[str, tk.StringVar] = {}
        for label, key in links:
            ttk.Label(fields, text=f"{label}:").grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            self._link_vars[key] = var
            ttk.Entry(fields, textvariable=var, width=42).grid(row=row, column=1, sticky="w", pady=4)
            row += 1

        ttk.Label(fields, text="Другие ссылки/контакты:").grid(row=row, column=0, sticky="nw", pady=(6, 4))
        self.other_text = tk.Text(fields, width=45, height=3)
        self.other_text.grid(row=row, column=1, sticky="w", pady=(6, 4))
        row += 1

        # Roles.
        roles_title = ttk.Label(self, text="Роли (кроме администратора):", font=("Segoe UI", 12, "bold"))
        roles_title.pack(anchor="w", padx=18, pady=(18, 6))

        # Roles in a scroll area (so it won't break for many roles).
        self.roles_container = ttk.Frame(self)
        self.roles_container.pack(fill="x", padx=18)

        self.roles_scroll = tk.Canvas(self.roles_container, highlightthickness=0)
        self.roles_scroll.pack(side="left", fill="x", expand=True)
        self.roles_scrollbar = ttk.Scrollbar(self.roles_container, orient="vertical", command=self.roles_scroll.yview)
        self.roles_scrollbar.pack(side="right", fill="y")
        self.roles_scroll.configure(yscrollcommand=self.roles_scrollbar.set)

        self._roles_inner = ttk.Frame(self.roles_scroll)
        self.roles_scroll.create_window((0, 0), window=self._roles_inner, anchor="nw")
        self._roles_inner.bind(
            "<Configure>",
            lambda e: self.roles_scroll.configure(scrollregion=self.roles_scroll.bbox("all")),
        )

        # Save button.
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=18, pady=(14, 10))
        self.save_btn = ttk.Button(btn_row, text="Сохранить профиль", command=self._on_save)
        self.save_btn.pack(side="right")

    def refresh_after_theme_change(self) -> None:
        # ttk handles most changes, but tk widgets need manual styling.
        self._apply_non_ttk_colors()
        self.refresh_from_storage()

    def _apply_non_ttk_colors(self) -> None:
        theme = self.storage.get_ui_settings().get("theme", "dark")
        p = get_palette(theme)
        try:
            self.other_text.configure(
                bg=p.entry_bg,
                fg=p.entry_fg,
                insertbackground=p.entry_fg,
                selectbackground=p.accent,
                selectforeground="#FFFFFF",
                relief="flat",
                highlightthickness=1,
                highlightbackground=p.surface2,
                highlightcolor=p.accent,
            )
        except Exception:
            pass
        try:
            self.roles_scroll.configure(background=p.bg)
        except Exception:
            pass

    def refresh_from_storage(self) -> None:
        self._apply_non_ttk_colors()
        profile = self.storage.get_profile()
        nickname = str(profile.get("nickname", "Администратор"))
        self.nickname_var.set(nickname)

        links = profile.get("links", {}) or {}
        for key, var in self._link_vars.items():
            var.set(str(links.get(key, "")))

        self.other_text.delete("1.0", "end")
        self.other_text.insert("1.0", str(links.get("other", "")))

        # Avatar.
        avatar_path = profile.get("avatar_path")
        initials = "".join([p[0] for p in nickname.split() if p and p[0].isalpha()][:2]).upper() or "AD"
        if avatar_path and Path(avatar_path).exists():
            try:
                img = Image.open(avatar_path)
                img = img.convert("RGB")
                img.thumbnail((140, 140), Image.LANCZOS)
                self._avatar_photo = ImageTk.PhotoImage(img)
            except Exception:
                self._avatar_photo = _make_placeholder_avatar(140, initials)
        else:
            self._avatar_photo = _make_placeholder_avatar(140, initials)
        self.avatar_label.configure(image=self._avatar_photo)

        # Roles checkboxes.
        for child in self._roles_inner.winfo_children():
            child.destroy()
        self._roles_vars.clear()

        role_ids_selected = {str(r) for r in (profile.get("role_ids") or [])}
        # Admin is always present for profile.
        role_ids_selected.add(SYSTEM_ADMIN_ROLE_ID)

        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        # Admin checkbox (disabled, always checked).
        admin_var = tk.BooleanVar(value=True)
        admin_cb = ttk.Checkbutton(
            self._roles_inner,
            text="Администратор (фиксировано)",
            variable=admin_var,
            state="disabled",
        )
        admin_cb.pack(anchor="w", pady=2)

        # Other roles excluding "Без роли" system and admin.
        for role in roles:
            if role.id in (SYSTEM_ADMIN_ROLE_ID, SYSTEM_NONE_ROLE_ID):
                continue
            var = tk.BooleanVar(value=role.id in role_ids_selected)
            self._roles_vars[role.id] = var
            cb = ttk.Checkbutton(self._roles_inner, text=f"{role.name}", variable=var)
            cb.pack(anchor="w", pady=2)

    def _on_choose_avatar(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("All files", "*.*")],
        )
        if not file_path:
            return

        profile = self.storage.get_profile()
        nickname = str(self.nickname_var.get().strip() or profile.get("nickname", "Администратор"))

        try:
            src = Path(file_path)
            ext = src.suffix.lower() or ".png"
            dst = self.storage.paths.avatars_dir / f"profile_avatar_{uuid4().hex}{ext}"
            # Copy original for future use; resize happens only for UI.
            shutil.copy2(src, dst)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить аватар: {e}")
            return

        profile["avatar_path"] = str(dst)
        self.storage.save_profile(profile)
        self.refresh_from_storage()

    def _on_save(self) -> None:
        nickname = self.nickname_var.get().strip()
        if not nickname:
            messagebox.showerror("Ошибка", "Никнейм не может быть пустым.")
            return

        profile = self.storage.get_profile()
        profile["nickname"] = nickname
        links = profile.get("links", {}) or {}

        for key, var in self._link_vars.items():
            links[key] = var.get().strip()
        links["other"] = self.other_text.get("1.0", "end").strip()
        profile["links"] = links

        # Role selection:
        selected = {SYSTEM_ADMIN_ROLE_ID}
        for role_id, var in self._roles_vars.items():
            if var.get():
                selected.add(role_id)
        profile["role_ids"] = list(selected)

        self.storage.save_profile(profile)
        messagebox.showinfo("Готово", "Профиль сохранен.")


# local helper to avoid importing uuid at module top with tkinter startup.
def uuid4():
    import uuid as _uuid

    return _uuid.uuid4()

