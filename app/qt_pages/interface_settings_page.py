from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QSize
from PySide6.QtGui import QFontMetrics, QPixmap, QShowEvent, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QColorDialog,
    QGroupBox,
    QSpinBox,
)

from app.assets import get_interface_assets
from app.storage import Storage
from app.theme import get_palette


class InterfaceSettingsPage(QWidget):
    def __init__(self, storage: Storage, on_apply):
        super().__init__()
        self.storage = storage
        self.on_apply = on_apply
        self._preview_pix: QPixmap | None = None
        self._preview_key: tuple[str, str | None] | None = None
        self._initial_load_done = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        h = QLabel("Настройки интерфейса")
        h.setObjectName("H1")
        root.addWidget(h)

        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(10)
        form_grid.setVerticalSpacing(10)
        form_grid.setColumnStretch(1, 1)
        _label_texts = ("Тема:", "Цвет фона:", "Фон-картинка:", "Подзадач в строке:")
        fm = QFontMetrics(self.font())
        label_w = max(fm.horizontalAdvance(t) for t in _label_texts) + 16

        lbl_theme = QLabel("Тема:")
        lbl_theme.setFixedWidth(label_w)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setFixedWidth(140)
        form_grid.addWidget(lbl_theme, 0, 0)
        form_grid.addWidget(self.theme_combo, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lbl_bg = QLabel("Цвет фона:")
        lbl_bg.setFixedWidth(label_w)
        self.bg_color_edit = QLineEdit()
        self.bg_color_edit.setMinimumWidth(160)
        self.color_btn = QPushButton("")
        self.color_btn.setToolTip("Выбрать цвет")
        assets = get_interface_assets()
        if assets.color_button_png.exists():
            self.color_btn.setIcon(QIcon(str(assets.color_button_png)))
            self.color_btn.setIconSize(QSize(18, 18))
        self.color_btn.setFixedSize(34, 28)
        self.color_btn.clicked.connect(self._choose_color)
        bg_row = QHBoxLayout()
        bg_row.setContentsMargins(0, 0, 0, 0)
        bg_row.setSpacing(8)
        bg_row.addWidget(self.bg_color_edit, 0)
        bg_row.addWidget(self.color_btn, 0)
        bg_row.addStretch(1)
        bg_wrap = QWidget()
        bg_wrap.setLayout(bg_row)
        form_grid.addWidget(lbl_bg, 1, 0)
        form_grid.addWidget(bg_wrap, 1, 1)

        lbl_img = QLabel("Фон-картинка:")
        lbl_img.setFixedWidth(label_w)
        self.bg_image_edit = QLineEdit()
        self.image_btn = QPushButton("Выбрать…")
        self.image_btn.clicked.connect(self._choose_image)
        img_row = QHBoxLayout()
        img_row.setContentsMargins(0, 0, 0, 0)
        img_row.setSpacing(8)
        img_row.addWidget(self.bg_image_edit, 1)
        img_row.addWidget(self.image_btn, 0)
        img_wrap = QWidget()
        img_wrap.setLayout(img_row)
        form_grid.addWidget(lbl_img, 2, 0)
        form_grid.addWidget(img_wrap, 2, 1)

        lbl_sub = QLabel("Подзадач в строке:")
        lbl_sub.setFixedWidth(label_w)
        lbl_sub.setToolTip("Максимум точек подзадач на одной линии в окне просмотра задачи (остальные переносятся на следующую).")
        self.subtasks_per_row_spin = QSpinBox()
        self.subtasks_per_row_spin.setRange(2, 24)
        self.subtasks_per_row_spin.setValue(6)
        form_grid.addWidget(lbl_sub, 3, 0)
        form_grid.addWidget(self.subtasks_per_row_spin, 3, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        root.addLayout(form_grid)

        box = QGroupBox("Превью")
        box_l = QVBoxLayout(box)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(160)
        box_l.addWidget(self.preview_label)
        root.addWidget(box, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.apply_btn = QPushButton("Применить")
        self.apply_btn.clicked.connect(self._on_apply)
        actions.addWidget(self.apply_btn)
        root.addLayout(actions)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_load_done:
            self._initial_load_done = True
            self._load_from_storage()

    def refresh_after_theme_change(self) -> None:
        # Theme change should not force re-decoding the preview image.
        # Keep it lightweight so the UI thread stays responsive.
        settings = self.storage.get_ui_settings()
        theme = str(settings.get("theme", "dark"))
        self.theme_combo.setCurrentText(theme if theme in ("dark", "light") else "dark")

        # Background preview is driven by the chosen color/path; refresh is cached.
        self._refresh_preview()

    def _load_from_storage(self) -> None:
        settings = self.storage.get_ui_settings()
        theme = str(settings.get("theme", "dark"))
        bg = str(settings.get("background_color", "#1F1F1F"))
        path = settings.get("background_image_path") or ""
        self.theme_combo.setCurrentText(theme if theme in ("dark", "light") else "dark")
        self.bg_color_edit.setText(bg)
        self.bg_image_edit.setText(str(path))
        try:
            self.subtasks_per_row_spin.setValue(int(settings.get("subtasks_max_per_row", 6)))
        except Exception:
            self.subtasks_per_row_spin.setValue(6)
        self._refresh_preview()

    def _choose_color(self) -> None:
        cur = self.bg_color_edit.text().strip() or "#1F1F1F"
        c = QColorDialog.getColor()
        if not c.isValid():
            return
        self.bg_color_edit.setText(c.name())
        self._refresh_preview()

    def _choose_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите фон-картинку",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)",
        )
        if not file_path:
            return
        self.bg_image_edit.setText(file_path)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        path = self.bg_image_edit.text().strip()
        bg = self.bg_color_edit.text().strip() or "#1F1F1F"
        key = (str(bg), str(path) if path else None)
        if key == self._preview_key:
            return
        self._preview_key = key
        if path and Path(path).exists():
            pix = QPixmap(path)
            if not pix.isNull():
                self._preview_pix = pix.scaled(360, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
                self.preview_label.setPixmap(self._preview_pix)
                self.preview_label.setStyleSheet(f"background:{bg};")
                return
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setStyleSheet(f"background:{bg};")

    def _on_apply(self) -> None:
        theme = self.theme_combo.currentText().strip() or "dark"
        bg_color = self.bg_color_edit.text().strip() or "#1F1F1F"
        bg_image_path = self.bg_image_edit.text().strip() or None
        if bg_image_path and not Path(bg_image_path).exists():
            QMessageBox.critical(self, "Ошибка", "Файл фона не найден.")
            return

        prev = self.storage.get_ui_settings()
        self.storage.save_ui_settings(
            {
                "theme": theme,
                "background_color": bg_color,
                "background_image_path": bg_image_path,
                # preserve board flags
                "people_panel_open": bool(prev.get("people_panel_open", True)),
                "people_panel_pinned": bool(prev.get("people_panel_pinned", False)),
                "subtasks_max_per_row": int(self.subtasks_per_row_spin.value()),
            }
        )
        QMessageBox.information(self, "Готово", "Настройки применены.")
        if callable(self.on_apply):
            self.on_apply()

