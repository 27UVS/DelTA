from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.assets import get_interface_assets
from app.storage import (
    Storage,
    SYSTEM_ADMIN_ROLE_ID,
    SYSTEM_NONE_ROLE_ID,
    SYSTEM_STATUS_NONE_ID,
)

_ADMIN_PERSON_ID = "__admin__"
_NEW_PERSON_ID = "__new__"


class PersonSettingsDialog(QDialog):
    def __init__(self, parent: QWidget, storage: Storage, person_id: str) -> None:
        super().__init__(parent)
        self.storage = storage
        self.person_id = str(person_id)
        self.is_admin = self.person_id == _ADMIN_PERSON_ID
        self.is_new = self.person_id == _NEW_PERSON_ID

        if self.is_new:
            self.setWindowTitle("Добавить человека")
        else:
            self.setWindowTitle("Настройки человека" + (" (Админ)" if self.is_admin else ""))
        self.setModal(True)
        self.resize(520, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # --- Basic identity ---
        box_basic = QGroupBox("Основное")
        basic_l = QVBoxLayout(box_basic)
        basic_l.setSpacing(10)

        row_nick = QHBoxLayout()
        row_nick.addWidget(QLabel("Никнейм"), 0)
        self.nickname_edit = QLineEdit()
        row_nick.addWidget(self.nickname_edit, 1)
        basic_l.addLayout(row_nick)

        row_avatar = QHBoxLayout()
        row_avatar.addWidget(QLabel("Аватар"), 0)
        self.avatar_edit = QLineEdit()
        self.avatar_edit.setReadOnly(True)
        row_avatar.addWidget(self.avatar_edit, 1)
        self.avatar_btn = QPushButton("Выбрать…")
        self.avatar_btn.clicked.connect(self._choose_avatar)
        row_avatar.addWidget(self.avatar_btn, 0)
        basic_l.addLayout(row_avatar)

        root.addWidget(box_basic)

        # --- Roles ---
        roles_box = QGroupBox("Роли")
        roles_l = QVBoxLayout(roles_box)
        roles_l.setSpacing(8)
        self.roles_scroll = QScrollArea()
        self.roles_scroll.setWidgetResizable(True)
        roles_inner = QWidget()
        self.roles_inner_l = QVBoxLayout(roles_inner)
        self.roles_inner_l.setContentsMargins(0, 0, 0, 0)
        self.roles_inner_l.setSpacing(6)
        self.roles_inner_l.addStretch(1)
        self.roles_scroll.setWidget(roles_inner)
        roles_l.addWidget(self.roles_scroll, 1)
        root.addWidget(roles_box, 1)

        self._role_checks: dict[str, QCheckBox] = {}

        # --- Status ---
        box_status = QGroupBox("Статус")
        st_l = QHBoxLayout(box_status)
        st_l.addWidget(QLabel("Статус"), 0)
        self.status_combo = QComboBox()
        st_l.addWidget(self.status_combo, 1)
        root.addWidget(box_status)

        # --- Extra fields (email + links) ---
        extra_box = QGroupBox("Контакты и рабочие ссылки")
        extra_l = QVBoxLayout(extra_box)
        extra_l.setSpacing(10)

        row_email = QHBoxLayout()
        row_email.addWidget(QLabel("Почта"), 0)
        self.email_edit = QLineEdit()
        self._email_editing = False
        self.email_edit.setReadOnly(True)
        self.email_edit.installEventFilter(self)
        row_email.addWidget(self.email_edit, 1)
        self.email_edit_btn = QPushButton()
        self.email_edit_btn.setToolTip("Редактировать почту")
        self.email_edit_btn.setFixedSize(34, 30)
        assets = get_interface_assets()
        if assets.edit_button_png.exists():
            self.email_edit_btn.setIcon(QIcon(str(assets.edit_button_png)))
        self.email_edit_btn.clicked.connect(self._toggle_email_edit)
        row_email.addWidget(self.email_edit_btn, 0)
        extra_l.addLayout(row_email)

        row_l1 = QHBoxLayout()
        row_l1.addWidget(QLabel("Ссылка 1"), 0)
        self.link1_edit = QLineEdit()
        row_l1.addWidget(self.link1_edit, 1)
        self.pref1_cb = QCheckBox("Приоритет")
        self.pref1_cb.toggled.connect(lambda v: self._on_pref_toggle("link1", v))
        row_l1.addWidget(self.pref1_cb, 0)
        extra_l.addLayout(row_l1)

        row_l2 = QHBoxLayout()
        row_l2.addWidget(QLabel("Ссылка 2"), 0)
        self.link2_edit = QLineEdit()
        row_l2.addWidget(self.link2_edit, 1)
        self.pref2_cb = QCheckBox("Приоритет")
        self.pref2_cb.toggled.connect(lambda v: self._on_pref_toggle("link2", v))
        row_l2.addWidget(self.pref2_cb, 0)
        extra_l.addLayout(row_l2)

        root.addWidget(extra_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_save)
        self._deleted = False
        self.delete_btn = buttons.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
        show_delete = (not self.is_admin) and (not self.is_new)
        self.delete_btn.setVisible(show_delete)
        self.delete_btn.setStyleSheet("background:#C62828; color:#FFFFFF; padding:6px 12px;")
        self.delete_btn.clicked.connect(self._on_delete)
        root.addWidget(buttons)

        self._load_from_storage()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self.email_edit and event.type() == event.Type.MouseButtonPress:
            # When not in edit mode, clicking copies the email to clipboard (if present).
            if self.email_edit.isReadOnly():
                txt = self.email_edit.text().strip()
                if txt:
                    QApplication.clipboard().setText(txt)
                return True
        return super().eventFilter(obj, event)

    def _toggle_email_edit(self) -> None:
        self._email_editing = not self._email_editing
        self.email_edit.setReadOnly(not self._email_editing)
        if self._email_editing:
            self.email_edit.setFocus(Qt.FocusReason.MouseFocusReason)
            self.email_edit.selectAll()

    def _load_from_storage(self) -> None:
        # Roles/status sources
        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        statuses = self.storage.get_statuses()
        statuses = sorted(statuses, key=lambda s: s.name.lower())

        # Selected data
        if self.is_new:
            self.nickname_edit.setText("")
            self.avatar_edit.setText("")
            selected_roles = set()
            selected_status_id = SYSTEM_STATUS_NONE_ID
            extra = {"email": "", "link1": "", "link2": "", "preferred_link": None, "admin_status_id": SYSTEM_STATUS_NONE_ID}
        elif self.is_admin:
            profile = self.storage.get_profile()
            self.nickname_edit.setText(str(profile.get("nickname", "Администратор")))
            self.avatar_edit.setText(str(profile.get("avatar_path") or ""))
            selected_roles = {str(r) for r in (profile.get("role_ids") or [])}
            selected_roles.add(SYSTEM_ADMIN_ROLE_ID)
            extra = self.storage.get_person_settings(_ADMIN_PERSON_ID)
            selected_status_id = str(extra.get("admin_status_id") or SYSTEM_STATUS_NONE_ID)
        else:
            subjects = {str(s.get("id")): s for s in self.storage.get_subjects()}
            subj = subjects.get(self.person_id, {})
            self.nickname_edit.setText(str(subj.get("nickname", "")))
            self.avatar_edit.setText(str(subj.get("avatar_path") or ""))
            selected_roles = {str(r) for r in (subj.get("role_ids") or [])}
            selected_status_id = str(subj.get("status_id") or SYSTEM_STATUS_NONE_ID)
            extra = self.storage.get_person_settings(self.person_id)

        # Roles UI
        while self.roles_inner_l.count() > 1:
            it = self.roles_inner_l.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._role_checks.clear()

        if self.is_admin:
            admin_cb = QCheckBox("Администратор (фиксировано)")
            admin_cb.setChecked(True)
            admin_cb.setEnabled(False)
            self.roles_inner_l.insertWidget(self.roles_inner_l.count() - 1, admin_cb)

        for r in roles:
            if r.id in (SYSTEM_ADMIN_ROLE_ID, SYSTEM_NONE_ROLE_ID):
                continue
            cb = QCheckBox(r.name)
            cb.setChecked(r.id in selected_roles)
            self._role_checks[r.id] = cb
            self.roles_inner_l.insertWidget(self.roles_inner_l.count() - 1, cb)

        # Status UI
        self._status_id_by_name: dict[str, str] = {s.name: s.id for s in statuses}
        self.status_combo.clear()
        for s in statuses:
            self.status_combo.addItem(s.name)
        current_name = next((s.name for s in statuses if s.id == selected_status_id), "Без статуса")
        if current_name:
            self.status_combo.setCurrentText(current_name)

        # Extra fields
        self.email_edit.setText(str(extra.get("email", "") or ""))
        self._email_editing = False
        self.email_edit.setReadOnly(True)
        self.link1_edit.setText(str(extra.get("link1", "") or ""))
        self.link2_edit.setText(str(extra.get("link2", "") or ""))
        pref = extra.get("preferred_link")
        self.pref1_cb.blockSignals(True)
        self.pref2_cb.blockSignals(True)
        self.pref1_cb.setChecked(pref == "link1")
        self.pref2_cb.setChecked(pref == "link2")
        self.pref1_cb.blockSignals(False)
        self.pref2_cb.blockSignals(False)

    def _on_pref_toggle(self, which: str, checked: bool) -> None:
        # Only one priority checkbox can be active.
        if not checked:
            return
        if which == "link1":
            self.pref2_cb.blockSignals(True)
            self.pref2_cb.setChecked(False)
            self.pref2_cb.blockSignals(False)
        elif which == "link2":
            self.pref1_cb.blockSignals(True)
            self.pref1_cb.setChecked(False)
            self.pref1_cb.blockSignals(False)

    def _choose_avatar(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите изображение",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            src = Path(file_path)
            ext = src.suffix.lower() or ".png"
            prefix = "profile_avatar" if self.is_admin else "subject_avatar"
            dst = self.storage.paths.avatars_dir / f"{prefix}_{_uuid4_hex()}{ext}"
            shutil.copy2(src, dst)
            self.avatar_edit.setText(str(dst))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить аватар: {e}")

    def _on_save(self) -> None:
        nickname = self.nickname_edit.text().strip()
        if not nickname:
            QMessageBox.critical(self, "Ошибка", "Никнейм не может быть пустым.")
            return

        # Roles
        selected_roles: set[str] = set()
        if self.is_admin:
            selected_roles.add(SYSTEM_ADMIN_ROLE_ID)
        for rid, cb in self._role_checks.items():
            if cb.isChecked():
                selected_roles.add(rid)
        # If empty, Storage will normalize to "Без роли" for subjects.

        # Status
        status_name = self.status_combo.currentText()
        status_id = self._status_id_by_name.get(status_name, SYSTEM_STATUS_NONE_ID)

        avatar_path = self.avatar_edit.text().strip() or None

        # Extra fields saved separately
        preferred = "link1" if self.pref1_cb.isChecked() else ("link2" if self.pref2_cb.isChecked() else None)
        current_extra = (
            self.storage.get_person_settings(_ADMIN_PERSON_ID)
            if self.is_admin
            else (self.storage.get_person_settings(self.person_id) if not self.is_new else {"admin_status_id": SYSTEM_STATUS_NONE_ID})
        )
        # For new person, we save extra settings after we know the new id.
        if not self.is_new:
            self.storage.save_person_settings(
                _ADMIN_PERSON_ID if self.is_admin else self.person_id,
                {
                    "email": self.email_edit.text().strip(),
                    "link1": self.link1_edit.text().strip(),
                    "link2": self.link2_edit.text().strip(),
                    "preferred_link": preferred,
                    "admin_status_id": status_id if self.is_admin else str(current_extra.get("admin_status_id") or SYSTEM_STATUS_NONE_ID),
                },
            )

        # Persist nickname/avatar/roles/status in their canonical place.
        try:
            if self.is_new:
                subj = self.storage.add_subject(
                    nickname=nickname,
                    role_ids=list(selected_roles),
                    status_id=status_id,
                )
                new_id = str(subj.get("id"))
                if avatar_path is not None:
                    self.storage.update_subject(
                        subject_id=new_id,
                        nickname=nickname,
                        role_ids=list(selected_roles),
                        status_id=status_id,
                        avatar_path=avatar_path,
                    )
                # Save extra settings under the new person id.
                self.storage.save_person_settings(
                    new_id,
                    {
                        "email": self.email_edit.text().strip(),
                        "link1": self.link1_edit.text().strip(),
                        "link2": self.link2_edit.text().strip(),
                        "preferred_link": preferred,
                        "admin_status_id": SYSTEM_STATUS_NONE_ID,
                    },
                )
            elif self.is_admin:
                profile = self.storage.get_profile()
                profile["nickname"] = nickname
                profile["avatar_path"] = avatar_path
                profile["role_ids"] = list(selected_roles)
                self.storage.save_profile(profile)
            else:
                # Subjects keep status_id
                self.storage.update_subject(
                    subject_id=self.person_id,
                    nickname=nickname,
                    role_ids=list(selected_roles),
                    status_id=status_id,
                    avatar_path=avatar_path,
                )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return

        self.accept()

    def _on_delete(self) -> None:
        if self.is_admin or self.is_new:
            return
        if (
            QMessageBox.question(
                self,
                "Подтверждение удаления",
                "Вы уверены, что хотите удалить человека?\nЭто действие нельзя отменить.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.storage.delete_subject(self.person_id)
            self.storage.delete_person_settings(self.person_id)
            self._deleted = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))


def _uuid4_hex() -> str:
    import uuid as _uuid

    return _uuid.uuid4().hex

