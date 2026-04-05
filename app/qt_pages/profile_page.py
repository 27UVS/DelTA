from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QCheckBox,
    QFrame,
    QSizePolicy,
)

from app.storage import Storage, SYSTEM_ADMIN_ROLE_ID, SYSTEM_NONE_ROLE_ID


def _line_edit_min_height(edit: QLineEdit) -> int:
    m = edit.fontMetrics()
    return max(32, m.height() + 14)


class ProfilePage(QWidget):
    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self._role_checks: dict[str, QCheckBox] = {}
        self._avatar_pix: QPixmap | None = None
        self._initial_load_done = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        h = QLabel("Профиль (админ)")
        h.setObjectName("H1")
        root.addWidget(h)

        # Scroll the form so a short window gets scrollbars instead of squashing rows.
        profile_scroll = QScrollArea()
        profile_scroll.setWidgetResizable(True)
        profile_scroll.setFrameShape(QFrame.Shape.NoFrame)
        profile_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        profile_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        profile_inner = QWidget()
        profile_inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        inner_l = QVBoxLayout(profile_inner)
        inner_l.setContentsMargins(0, 0, 0, 0)
        inner_l.setSpacing(12)

        form_row = QHBoxLayout()
        form_row.setSpacing(16)
        form_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Avatar col
        avatar_col = QVBoxLayout()
        avatar_col.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(140, 140)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_col.addWidget(self.avatar_label, 0, Qt.AlignmentFlag.AlignTop)
        avatar_col.addWidget(QLabel("Аватар влияет на внешний вид профиля"))
        self.choose_avatar_btn = QPushButton("Выбрать аватар")
        self.choose_avatar_btn.clicked.connect(self._on_choose_avatar)
        avatar_col.addWidget(self.choose_avatar_btn)
        form_row.addLayout(avatar_col, 0)

        # Fields
        fields = QVBoxLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(8)
        fields.setAlignment(Qt.AlignmentFlag.AlignTop)

        form_grid = QGridLayout()
        form_grid.setContentsMargins(0, 0, 0, 0)
        form_grid.setHorizontalSpacing(10)
        form_grid.setVerticalSpacing(8)
        form_grid.setColumnStretch(1, 1)

        label_w = 90

        nick_lbl = QLabel("Никнейм:")
        nick_lbl.setFixedWidth(label_w)
        nick_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.nickname_edit = QLineEdit()
        self.nickname_edit.setMinimumWidth(200)
        self.nickname_edit.setMinimumHeight(_line_edit_min_height(self.nickname_edit))
        self.nickname_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form_grid.addWidget(nick_lbl, 0, 0)
        form_grid.addWidget(self.nickname_edit, 0, 1)

        self.link_edits: dict[str, QLineEdit] = {}
        row = 1
        for label, key in [
            ("YouTube", "youtube"),
            ("Instagram", "instagram"),
            ("Tumblr", "tumblr"),
            ("X (Twitter)", "x"),
            ("Telegram", "telegram"),
            ("VK", "vk"),
        ]:
            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(label_w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            e = QLineEdit()
            e.setMinimumHeight(_line_edit_min_height(e))
            e.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.link_edits[key] = e
            form_grid.addWidget(lbl, row, 0)
            form_grid.addWidget(e, row, 1)
            row += 1
        fields.addLayout(form_grid)

        fields.addWidget(QLabel("Другие ссылки/контакты:"))
        self.other_text = QTextEdit()
        self.other_text.setFixedHeight(70)
        self.other_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        fields.addWidget(self.other_text)
        form_row.addLayout(fields, 1)
        inner_l.addLayout(form_row)
        profile_scroll.setWidget(profile_inner)
        root.addWidget(profile_scroll, 1)

        roles_h = QLabel("Роли (кроме администратора):")
        roles_h.setObjectName("H2")
        root.addWidget(roles_h)

        self.roles_scroll = QScrollArea()
        self.roles_scroll.setWidgetResizable(True)
        self.roles_inner = QWidget()
        self.roles_inner_l = QVBoxLayout(self.roles_inner)
        self.roles_inner_l.setContentsMargins(0, 0, 0, 0)
        self.roles_inner_l.setSpacing(6)
        self.roles_inner_l.addStretch(1)
        self.roles_scroll.setWidget(self.roles_inner)
        self.roles_scroll.setFixedHeight(200)
        root.addWidget(self.roles_scroll)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_btn = QPushButton("Сохранить профиль")
        self.save_btn.clicked.connect(self._on_save)
        actions.addWidget(self.save_btn)
        root.addLayout(actions)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_load_done:
            self._initial_load_done = True
            self.refresh_from_storage()

    def refresh_after_theme_change(self) -> None:
        self.refresh_from_storage()

    def refresh_from_storage(self) -> None:
        profile = self.storage.get_profile()
        nickname = str(profile.get("nickname", "Администратор"))
        self.nickname_edit.setText(nickname)

        links = profile.get("links", {}) or {}
        for key, edit in self.link_edits.items():
            edit.setText(str(links.get(key, "")))
        self.other_text.setPlainText(str(links.get("other", "")))

        # Avatar
        avatar_path = profile.get("avatar_path")
        if avatar_path and Path(avatar_path).exists():
            pix = QPixmap(str(avatar_path))
            if not pix.isNull():
                self._avatar_pix = pix.scaled(140, 140, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
            else:
                self._avatar_pix = None
        else:
            self._avatar_pix = None
        self.avatar_label.setPixmap(self._avatar_pix or QPixmap())

        # Roles
        while self.roles_inner_l.count() > 1:
            it = self.roles_inner_l.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._role_checks.clear()

        role_ids_selected = {str(r) for r in (profile.get("role_ids") or [])}
        role_ids_selected.add(SYSTEM_ADMIN_ROLE_ID)

        admin_cb = QCheckBox("Администратор (фиксировано)")
        admin_cb.setChecked(True)
        admin_cb.setEnabled(False)
        self.roles_inner_l.insertWidget(self.roles_inner_l.count() - 1, admin_cb)

        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        for role in roles:
            if role.id in (SYSTEM_ADMIN_ROLE_ID, SYSTEM_NONE_ROLE_ID):
                continue
            cb = QCheckBox(role.name)
            cb.setChecked(role.id in role_ids_selected)
            self._role_checks[role.id] = cb
            self.roles_inner_l.insertWidget(self.roles_inner_l.count() - 1, cb)

    def _on_choose_avatar(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите изображение",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)",
        )
        if not file_path:
            return

        profile = self.storage.get_profile()
        try:
            src = Path(file_path)
            ext = src.suffix.lower() or ".png"
            dst = self.storage.paths.avatars_dir / f"profile_avatar_{_uuid4_hex()}{ext}"
            shutil.copy2(src, dst)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить аватар: {e}")
            return

        profile["avatar_path"] = str(dst)
        self.storage.save_profile(profile)
        self.refresh_from_storage()

    def _on_save(self) -> None:
        nickname = self.nickname_edit.text().strip()
        if not nickname:
            QMessageBox.critical(self, "Ошибка", "Никнейм не может быть пустым.")
            return

        profile = self.storage.get_profile()
        profile["nickname"] = nickname
        links = profile.get("links", {}) or {}
        for key, edit in self.link_edits.items():
            links[key] = edit.text().strip()
        links["other"] = self.other_text.toPlainText().strip()
        profile["links"] = links

        selected = {SYSTEM_ADMIN_ROLE_ID}
        for role_id, cb in self._role_checks.items():
            if cb.isChecked():
                selected.add(role_id)
        profile["role_ids"] = list(selected)

        self.storage.save_profile(profile)
        QMessageBox.information(self, "Готово", "Профиль сохранен.")


def _uuid4_hex() -> str:
    import uuid as _uuid

    return _uuid.uuid4().hex

