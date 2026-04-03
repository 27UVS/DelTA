from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from PIL import Image, ImageTk

from app.storage import Storage
from app.theme import get_palette


class InterfaceSettingsPage(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage, on_apply):
        super().__init__(parent)
        self.storage = storage
        self.on_apply = on_apply

        self._preview_photo = None

        header = ttk.Label(self, text="Настройки интерфейса", font=("Segoe UI", 16, "bold"))
        header.pack(anchor="w", padx=18, pady=(16, 10))

        form = ttk.Frame(self)
        form.pack(fill="x", padx=18)

        # Theme.
        ttk.Label(form, text="Тема:").grid(row=0, column=0, sticky="w", pady=6)
        self.theme_var = tk.StringVar()
        theme_combo = ttk.Combobox(form, textvariable=self.theme_var, values=["dark", "light"], state="readonly", width=18)
        theme_combo.grid(row=0, column=1, sticky="w", pady=6)

        # Background color.
        ttk.Label(form, text="Цвет фона:").grid(row=1, column=0, sticky="w", pady=6)
        self.bg_color_var = tk.StringVar()
        self.bg_color_entry = ttk.Entry(form, textvariable=self.bg_color_var, width=22)
        self.bg_color_entry.grid(row=1, column=1, sticky="w", pady=6)
        self.color_btn = ttk.Button(form, text="Выбрать...", command=self._choose_color)
        self.color_btn.grid(row=1, column=2, sticky="w", padx=8, pady=6)

        # Background image.
        ttk.Label(form, text="Фон-картинка:").grid(row=2, column=0, sticky="w", pady=6)
        self.bg_image_path_var = tk.StringVar()
        self.bg_image_entry = ttk.Entry(form, textvariable=self.bg_image_path_var, width=40)
        self.bg_image_entry.grid(row=2, column=1, sticky="w", pady=6)
        self.image_btn = ttk.Button(form, text="Выбрать...", command=self._choose_image)
        self.image_btn.grid(row=2, column=2, sticky="w", padx=8, pady=6)

        self.preview_box = ttk.LabelFrame(self, text="Превью")
        self.preview_box.pack(fill="x", padx=18, pady=(12, 6))
        self.preview_label = ttk.Label(self.preview_box)
        self.preview_label.pack(padx=10, pady=10)

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=18, pady=(16, 10))
        self.save_btn = ttk.Button(actions, text="Применить", command=self._on_apply)
        self.save_btn.pack(side="right")

        self._load_from_storage()

    def _load_from_storage(self) -> None:
        settings = self.storage.get_ui_settings()
        self.theme_var.set(str(settings.get("theme", "dark")))
        self.bg_color_var.set(str(settings.get("background_color", "#1F1F1F")))
        self.bg_image_path_var.set(str(settings.get("background_image_path") or ""))
        self._refresh_preview()

    def refresh_after_theme_change(self) -> None:
        self._load_from_storage()
        theme = self.storage.get_ui_settings().get("theme", "dark")
        p = get_palette(theme)
        try:
            self.preview_label.configure(background=p.bg)
        except Exception:
            pass

    def _choose_color(self) -> None:
        from tkinter import colorchooser

        color = colorchooser.askcolor(title="Выберите цвет фона", initialcolor=self.bg_color_var.get())
        if not color or not color[1]:
            return
        self.bg_color_var.set(color[1])
        self._refresh_preview()

    def _choose_image(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Выберите фон-картинку",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("All files", "*.*")],
        )
        if not file_path:
            return
        self.bg_image_path_var.set(file_path)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        path = self.bg_image_path_var.get().strip()
        bg = self.bg_color_var.get().strip() or "#1F1F1F"
        if path and Path(path).exists():
            try:
                img = Image.open(path).convert("RGB")
                img.thumbnail((360, 180), Image.LANCZOS)
                self._preview_photo = ImageTk.PhotoImage(img)
                self.preview_label.configure(image=self._preview_photo, background=bg)
                return
            except Exception:
                pass
        self.preview_label.configure(image="", background=bg)

    def _on_apply(self) -> None:
        theme = self.theme_var.get().strip() or "dark"
        bg_color = self.bg_color_var.get().strip() or "#1F1F1F"
        bg_image_path = self.bg_image_path_var.get().strip()
        if not bg_image_path:
            bg_image_path = None
        elif not Path(bg_image_path).exists():
            messagebox.showerror("Ошибка", "Файл фона не найден.")
            return

        self.storage.save_ui_settings(
            {
                "theme": theme,
                "background_color": bg_color,
                "background_image_path": bg_image_path,
            }
        )
        messagebox.showinfo("Готово", "Настройки применены.")
        if callable(self.on_apply):
            self.on_apply()

