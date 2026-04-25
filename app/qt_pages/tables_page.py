from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtGui import QColor, QIcon, QPixmap, QPainter, QBrush
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QHeaderView,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QSpinBox,
    QAbstractSpinBox,
    QColorDialog,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QFileDialog,
)

from app.assets import get_interface_assets
from app.qt_icon_loader import QtIconLoader
from app.storage import (
    Storage,
    SYSTEM_ADMIN_ROLE_ID,
    SYSTEM_NONE_ROLE_ID,
    SYSTEM_STATUS_NONE_ID,
)

_ADMIN_PERSON_ID = "__admin__"


def _format_dt(value: str | None) -> str:
    if not value:
        return "—"
    return str(value)


def _task_responsible_display(task: dict, subj_name: dict[str, str]) -> str:
    ids = [str(x) for x in (task.get("responsible_subject_ids") or []) if x]
    if not ids:
        rid = str(task.get("responsible_subject_id") or "")
        if rid:
            ids = [rid]
    if not ids:
        return "—"
    return ", ".join(subj_name.get(pid, "—") for pid in ids)


def _get_role_display_color(role_color: str) -> str:
    return role_color or "#BDBDBD"


@dataclass(frozen=True)
class _RowRef:
    id: str


class _SpinBoxOutsideArrows(QWidget):
    def __init__(self, minimum: int, maximum: int, value: int):
        super().__init__()
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.spin = QSpinBox()
        self.spin.setRange(int(minimum), int(maximum))
        self.spin.setValue(int(value))
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        root.addWidget(self.spin, 1)

        btns = QVBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(6)
        self.up_btn = QPushButton("▲")
        self.down_btn = QPushButton("▼")
        self.up_btn.setFixedSize(36, 18)
        self.down_btn.setFixedSize(36, 18)
        self.up_btn.clicked.connect(lambda: self.spin.stepUp())
        self.down_btn.clicked.connect(lambda: self.spin.stepDown())
        btns.addWidget(self.up_btn)
        btns.addWidget(self.down_btn)
        root.addLayout(btns, 0)

    def setEnabled(self, enabled: bool) -> None:  # type: ignore[override]
        super().setEnabled(enabled)
        self.spin.setEnabled(enabled)
        self.up_btn.setEnabled(enabled)
        self.down_btn.setEnabled(enabled)

    def value(self) -> int:
        return int(self.spin.value())


class RoleDialog(QDialog):
    def __init__(self, parent: QWidget, storage: Storage, role: dict | None):
        super().__init__(parent)
        self.storage = storage
        self.role = role
        self.setWindowTitle("Роль" if role is None else "Редактировать роль")
        self.setModal(True)
        self._icons = QtIconLoader()
        self._assets = get_interface_assets()

        locked = bool((role or {}).get("locked", False))
        is_admin = bool(role and role.get("id") == SYSTEM_ADMIN_ROLE_ID)
        name_priority_locked = locked
        color_locked = locked and not is_admin

        root = QVBoxLayout(self)
        form = QVBoxLayout()

        self.name_edit = QLineEdit(str((role or {}).get("name", "")))
        self.color_edit = QLineEdit(str((role or {}).get("color", "#BDBDBD")))
        # Only Admin role may have priority 0.
        min_pr = 0 if is_admin else 1
        self.priority_spin = _SpinBoxOutsideArrows(minimum=min_pr, maximum=99999, value=int((role or {}).get("priority", 9999)))

        self.name_edit.setEnabled(not name_priority_locked)
        self.priority_spin.setEnabled(not name_priority_locked)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Название"), 0)
        row1.addWidget(self.name_edit, 1)
        form.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Цвет"), 0)
        row2.addWidget(self.color_edit, 0)
        self.pick_color_btn = QPushButton("")
        self.pick_color_btn.setToolTip("Выбрать цвет")
        pm = self._icons.load_pixmap(self._assets.color_button_png, (18, 18))
        if pm is not None:
            self.pick_color_btn.setIcon(QIcon(pm))
        self.pick_color_btn.setFixedSize(34, 28)
        self.pick_color_btn.setIconSize(QSize(18, 18))
        self.pick_color_btn.setEnabled(not color_locked)
        self.pick_color_btn.clicked.connect(self._choose_color)
        row2.addWidget(self.pick_color_btn, 0)
        row2.addStretch(1)
        form.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Приоритет (меньше = выше)"), 0)
        row3.addWidget(self.priority_spin, 0)
        row3.addStretch(1)
        form.addLayout(row3)

        self.for_stories_cb = QCheckBox("Использовать в сценариях (страница историй)")
        self.for_stories_cb.setChecked(bool((role or {}).get("for_stories", False)))
        self.for_stories_cb.setEnabled(not locked)
        form.addWidget(self.for_stories_cb)

        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        if locked and not is_admin:
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def accept(self) -> None:  # type: ignore[override]
        # Enforce unique priorities for roles.
        # Keep the dialog open and show a friendly warning if the priority is already used.
        try:
            pr = int(self.priority_spin.value())
            current_id = str((self.role or {}).get("id") or "")
            # Admin role's priority is fixed; if it's being edited, priority is locked anyway.
            roles = self.storage.get_roles()
            conflict = next((r for r in roles if int(r.priority) == pr and str(r.id) != current_id), None)
            if conflict is not None:
                QMessageBox.warning(
                    self,
                    "Приоритет занят",
                    f"Приоритет {pr} уже занят ролью '{conflict.name}'.\n"
                    "Пожалуйста, выберите не занятый приоритет.",
                )
                return
        except Exception:
            # If anything unexpected happens, fall back to default accept and let Storage validate too.
            pass
        super().accept()

    def _choose_color(self) -> None:
        c = QColorDialog.getColor()
        if not c.isValid():
            return
        self.color_edit.setText(c.name())

    def payload(self) -> tuple[str, str, int, bool]:
        return (self.name_edit.text(), self.color_edit.text(), int(self.priority_spin.value()), bool(self.for_stories_cb.isChecked()))


class StatusDialog(QDialog):
    def __init__(self, parent: QWidget, storage: Storage, status: dict | None):
        super().__init__(parent)
        self.storage = storage
        self.status = status
        self.setWindowTitle("Статус" if status is None else "Редактировать статус")
        self.setModal(True)
        self._icons = QtIconLoader()
        self._assets = get_interface_assets()

        locked = bool((status or {}).get("locked", False))
        root = QVBoxLayout(self)
        self.name_edit = QLineEdit(str((status or {}).get("name", "")))
        self.name_edit.setEnabled(not locked)
        root.addWidget(QLabel("Название"))
        root.addWidget(self.name_edit)

        self.color_edit = QLineEdit(str((status or {}).get("color", "#4CAF50")))
        self.color_edit.setEnabled(not locked)
        row_color = QHBoxLayout()
        row_color.addWidget(QLabel("Цвет (HEX)"), 0)
        row_color.addWidget(self.color_edit, 0)
        self.pick_color_btn = QPushButton("")
        self.pick_color_btn.setToolTip("Выбрать цвет")
        pm = self._icons.load_pixmap(self._assets.color_button_png, (18, 18))
        if pm is not None:
            self.pick_color_btn.setIcon(QIcon(pm))
        self.pick_color_btn.setFixedSize(34, 28)
        self.pick_color_btn.setIconSize(QSize(18, 18))
        self.pick_color_btn.setEnabled(not locked)
        self.pick_color_btn.clicked.connect(self._choose_color)
        row_color.addWidget(self.pick_color_btn, 0)
        row_color.addStretch(1)
        root.addLayout(row_color)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        if locked:
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def _choose_color(self) -> None:
        c = QColorDialog.getColor()
        if not c.isValid():
            return
        self.color_edit.setText(c.name())

    def payload(self) -> tuple[str, str]:
        return self.name_edit.text(), self.color_edit.text()


class SubjectDialog(QDialog):
    def __init__(self, parent: QWidget, storage: Storage, subject: dict | None):
        super().__init__(parent)
        self.storage = storage
        self.subject = subject
        self.setWindowTitle("Субъект" if subject is None else "Редактировать субъект")
        self.setModal(True)

        root = QVBoxLayout(self)
        self.nickname_edit = QLineEdit(str((subject or {}).get("nickname", "")))
        root.addWidget(QLabel("Никнейм"))
        root.addWidget(self.nickname_edit)

        # Avatar (optional)
        self.avatar_path: str | None = str((subject or {}).get("avatar_path")) if (subject or {}).get("avatar_path") else None
        avatar_row = QHBoxLayout()
        avatar_row.addWidget(QLabel("Картинка"), 0)
        self.avatar_edit = QLineEdit(self.avatar_path or "")
        self.avatar_edit.setReadOnly(True)
        avatar_row.addWidget(self.avatar_edit, 1)
        self.avatar_btn = QPushButton("Выбрать аватар…")
        self.avatar_btn.clicked.connect(self._choose_avatar)
        avatar_row.addWidget(self.avatar_btn, 0)
        root.addLayout(avatar_row)

        # Status (by name)
        statuses = [s for s in self.storage.get_statuses() if s.id != SYSTEM_STATUS_NONE_ID]
        statuses = sorted(statuses, key=lambda s: s.name.lower())
        self._status_id_by_name = {s.name: s.id for s in statuses}
        status_id = str((subject or {}).get("status_id", SYSTEM_STATUS_NONE_ID))
        default_name = next((s.name for s in self.storage.get_statuses() if s.id == status_id), "Без статуса")

        row_status = QHBoxLayout()
        row_status.addWidget(QLabel("Статус"), 0)
        self.status_combo = QComboBox()
        self.status_combo.addItem("Без статуса")
        for s in statuses:
            self.status_combo.addItem(s.name)
        self.status_combo.setCurrentText(default_name)
        row_status.addWidget(self.status_combo, 1)
        root.addLayout(row_status)

        roles_box = QGroupBox("Роли")
        roles_l = QVBoxLayout(roles_box)

        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        selected = set((subject or {}).get("role_ids", []) or [])
        self._role_checks: dict[str, QCheckBox] = {}
        for r in roles:
            if r.id in (SYSTEM_NONE_ROLE_ID, SYSTEM_ADMIN_ROLE_ID):
                continue
            cb = QCheckBox(r.name)
            cb.setChecked(r.id in selected)
            self._role_checks[r.id] = cb
            roles_l.addWidget(cb)

        root.addWidget(roles_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

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
            dst = self.storage.paths.avatars_dir / f"subject_avatar_{_uuid4_hex()}{ext}"
            shutil.copy2(src, dst)
            self.avatar_path = str(dst)
            self.avatar_edit.setText(self.avatar_path)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить аватар: {e}")

    def payload(self) -> tuple[str, list[str], str]:
        nickname = self.nickname_edit.text().strip()
        status_name = self.status_combo.currentText()
        status_id = self._status_id_by_name.get(status_name, SYSTEM_STATUS_NONE_ID)
        # System role "Без роли" is assigned automatically when nothing is selected.
        role_ids = [rid for rid, cb in self._role_checks.items() if cb.isChecked()]
        if not role_ids:
            role_ids = [SYSTEM_NONE_ROLE_ID]
        return nickname, role_ids, status_id

    def avatar(self) -> str | None:
        return self.avatar_path


def _uuid4_hex() -> str:
    import uuid as _uuid

    return _uuid.uuid4().hex


class TablesPage(QWidget):
    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self._icons = QtIconLoader()
        self._assets = get_interface_assets()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        h = QLabel("Параметры")
        h.setObjectName("H1")
        root.addWidget(h)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.roles_tab = QWidget()
        self.statuses_tab = QWidget()
        self.tasks_tab = QWidget()
        self.subjects_tab = QWidget()
        self.story_tab = QWidget()
        self.tabs.addTab(self.roles_tab, "Роли")
        self.tabs.addTab(self.statuses_tab, "Статусы")
        self.tabs.addTab(self.tasks_tab, "Задачи")
        self.tabs.addTab(self.subjects_tab, "Субъекты")
        self.tabs.addTab(self.story_tab, "Сюжет")

        self._build_roles_tab()
        self._build_statuses_tab()
        self._build_tasks_tab()
        self._build_subjects_tab()
        self._build_story_tab()

    def _apply_icon_button(self, btn: QPushButton, path: Path, *, tooltip: str) -> None:
        btn.setText("")
        btn.setToolTip(str(tooltip))
        pm = self._icons.load_pixmap(path, (18, 18))
        if pm is not None:
            btn.setIcon(QIcon(pm))
        btn.setFixedSize(34, 28)
        btn.setIconSize(QSize(18, 18))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Refresh whenever this page becomes visible (e.g. after task edits on the board).
        self.refresh_all()

    def refresh_after_theme_change(self) -> None:
        self.refresh_all()

    # ---------------- Roles ----------------
    def _build_roles_tab(self) -> None:
        root = QVBoxLayout(self.roles_tab)
        top = QHBoxLayout()
        root.addLayout(top)

        self.btn_add_role = QPushButton("Добавить")
        self.btn_add_role.clicked.connect(self._on_add_role)
        self.btn_edit_role = QPushButton("Редактировать")
        self.btn_edit_role.clicked.connect(self._on_edit_role)
        self.btn_del_role = QPushButton("Удалить")
        self.btn_del_role.clicked.connect(self._on_delete_role)
        self._apply_icon_button(self.btn_add_role, self._assets.add_button_png, tooltip="Добавить")
        self._apply_icon_button(self.btn_edit_role, self._assets.edit_button_png, tooltip="Редактировать")
        self._apply_icon_button(self.btn_del_role, self._assets.delete_button_png, tooltip="Удалить")
        top.addWidget(self.btn_add_role)
        top.addWidget(self.btn_edit_role)
        top.addWidget(self.btn_del_role)
        top.addStretch(1)

        self.roles_table = QTableWidget(0, 4)
        self.roles_table.setHorizontalHeaderLabels(["Название", "Сценарии", "Цвет (HEX)", "Приоритет"])
        self.roles_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.roles_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.roles_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.roles_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.roles_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.roles_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.roles_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.roles_table, 1)

    def refresh_roles(self) -> None:
        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        roles = [r for r in roles if r.id != SYSTEM_NONE_ROLE_ID]
        self.roles_table.setRowCount(len(roles))
        self._roles_row_id = []
        for i, r in enumerate(roles):
            self._roles_row_id.append(str(r.id))
            it_name = QTableWidgetItem(r.name)
            it_fs = QTableWidgetItem("Да" if bool(getattr(r, "for_stories", False)) else "Нет")
            it_color = QTableWidgetItem(_get_role_display_color(r.color))
            it_pr = QTableWidgetItem(str(r.priority))
            # subtle color preview
            try:
                it_color.setBackground(QColor(r.color))
                it_color.setForeground(QColor("#FFFFFF"))
            except Exception:
                pass

            self.roles_table.setItem(i, 0, it_name)
            self.roles_table.setItem(i, 1, it_fs)
            self.roles_table.setItem(i, 2, it_color)
            self.roles_table.setItem(i, 3, it_pr)

    def _selected_role_id(self) -> str | None:
        row = self.roles_table.currentRow()
        if row < 0:
            return None
        if row >= len(getattr(self, "_roles_row_id", [])):
            return None
        return str(self._roles_row_id[row])

    def _on_add_role(self) -> None:
        dlg = RoleDialog(self, self.storage, role=None)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, color, pr, for_stories = dlg.payload()
        try:
            self.storage.add_role(name=name, color=color, priority=pr, for_stories=bool(for_stories))
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_edit_role(self) -> None:
        rid = self._selected_role_id()
        if not rid:
            QMessageBox.information(self, "Инфо", "Выберите роль.")
            return
        roles = {r.id: r for r in self.storage.get_roles()}
        role = roles.get(rid)
        if not role:
            return
        dlg = RoleDialog(
            self,
            self.storage,
            role={
                "id": role.id,
                "name": role.name,
                "color": role.color,
                "priority": role.priority,
                "locked": role.locked,
                "for_stories": bool(getattr(role, "for_stories", False)),
            },
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, color, pr, for_stories = dlg.payload()
        try:
            self.storage.update_role(role_id=rid, name=name, color=color, priority=pr, for_stories=bool(for_stories))
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_delete_role(self) -> None:
        rid = self._selected_role_id()
        if not rid:
            QMessageBox.information(self, "Инфо", "Выберите роль.")
            return
        roles = {r.id: r for r in self.storage.get_roles()}
        role = roles.get(rid)
        if not role:
            return
        if role.locked:
            QMessageBox.warning(self, "Запрещено", "Системную роль нельзя удалить.")
            return
        if QMessageBox.question(self, "Подтверждение", f"Удалить роль '{role.name}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.storage.delete_role(rid)
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    # ---------------- Statuses ----------------
    def _build_statuses_tab(self) -> None:
        root = QVBoxLayout(self.statuses_tab)
        top = QHBoxLayout()
        root.addLayout(top)
        self.btn_add_status = QPushButton("Добавить")
        self.btn_add_status.clicked.connect(self._on_add_status)
        self.btn_edit_status = QPushButton("Редактировать")
        self.btn_edit_status.clicked.connect(self._on_edit_status)
        self.btn_del_status = QPushButton("Удалить")
        self.btn_del_status.clicked.connect(self._on_delete_status)
        self._apply_icon_button(self.btn_add_status, self._assets.add_button_png, tooltip="Добавить")
        self._apply_icon_button(self.btn_edit_status, self._assets.edit_button_png, tooltip="Редактировать")
        self._apply_icon_button(self.btn_del_status, self._assets.delete_button_png, tooltip="Удалить")
        top.addWidget(self.btn_add_status)
        top.addWidget(self.btn_edit_status)
        top.addWidget(self.btn_del_status)
        top.addStretch(1)

        self.status_table = QTableWidget(0, 2)
        self.status_table.setHorizontalHeaderLabels(["Название", "Цвет"])
        self.status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.status_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.status_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.status_table, 1)

    def refresh_statuses(self) -> None:
        statuses = sorted(self.storage.get_statuses(), key=lambda s: s.name.lower())
        # Include "Без статуса" but keep it locked/system and always gray.
        self.status_table.setRowCount(len(statuses))
        self._status_row_id: list[str] = []
        for i, s in enumerate(statuses):
            self._status_row_id.append(str(s.id))
            self.status_table.setItem(i, 0, QTableWidgetItem(s.name))

            hex_color = "#9E9E9E" if s.id == SYSTEM_STATUS_NONE_ID else (s.color or "#4CAF50")
            it_color = QTableWidgetItem(str(hex_color))
            # Draw a small colored circle icon next to the hex code.
            pm = QPixmap(14, 14)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setBrush(QBrush(QColor(hex_color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(1, 1, 12, 12)
            painter.end()
            it_color.setIcon(QIcon(pm))
            self.status_table.setItem(i, 1, it_color)

    def _selected_status_id(self) -> str | None:
        row = self.status_table.currentRow()
        if row < 0:
            return None
        if row >= len(getattr(self, "_status_row_id", [])):
            return None
        return str(self._status_row_id[row])

    def _on_add_status(self) -> None:
        dlg = StatusDialog(self, self.storage, status=None)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, color = dlg.payload()
        try:
            self.storage.add_status(name=name, color=color)
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_edit_status(self) -> None:
        sid = self._selected_status_id()
        if not sid:
            QMessageBox.information(self, "Инфо", "Выберите статус.")
            return
        statuses = {s.id: s for s in self.storage.get_statuses()}
        st = statuses.get(sid)
        if not st:
            return
        dlg = StatusDialog(self, self.storage, status={"id": st.id, "name": st.name, "color": st.color, "locked": st.locked})
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, color = dlg.payload()
        try:
            self.storage.update_status(status_id=sid, name=name, color=color)
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_delete_status(self) -> None:
        sid = self._selected_status_id()
        if not sid:
            QMessageBox.information(self, "Инфо", "Выберите статус.")
            return
        statuses = {s.id: s for s in self.storage.get_statuses()}
        st = statuses.get(sid)
        if not st:
            return
        if st.locked:
            QMessageBox.warning(self, "Запрещено", "Системный статус нельзя удалить.")
            return
        if QMessageBox.question(self, "Подтверждение", f"Удалить статус '{st.name}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.storage.delete_status(sid)
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    # ---------------- Subjects ----------------
    def _build_subjects_tab(self) -> None:
        root = QVBoxLayout(self.subjects_tab)
        top = QHBoxLayout()
        root.addLayout(top)
        self.btn_add_subject = QPushButton("Добавить")
        self.btn_add_subject.clicked.connect(self._on_add_subject)
        self.btn_edit_subject = QPushButton("Редактировать")
        self.btn_edit_subject.clicked.connect(self._on_edit_subject)
        self.btn_del_subject = QPushButton("Удалить")
        self.btn_del_subject.clicked.connect(self._on_delete_subject)
        self._apply_icon_button(self.btn_add_subject, self._assets.add_button_png, tooltip="Добавить")
        self._apply_icon_button(self.btn_edit_subject, self._assets.edit_button_png, tooltip="Редактировать")
        self._apply_icon_button(self.btn_del_subject, self._assets.delete_button_png, tooltip="Удалить")
        top.addWidget(self.btn_add_subject)
        top.addWidget(self.btn_edit_subject)
        top.addWidget(self.btn_del_subject)
        top.addStretch(1)

        self.subjects_table = QTableWidget(0, 4)
        self.subjects_table.setHorizontalHeaderLabels(["Никнейм", "Картинка", "Активных задач", "Создан"])
        self.subjects_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.subjects_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.subjects_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.subjects_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.subjects_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.subjects_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.subjects_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.subjects_table, 1)

    def refresh_subjects(self) -> None:
        subjects = sorted(self.storage.get_subjects(), key=lambda s: str(s.get("nickname", "")).lower())
        self.subjects_table.setRowCount(len(subjects))
        self._subj_row_id: list[str] = []
        for i, s in enumerate(subjects):
            sid = str(s.get("id"))
            self._subj_row_id.append(sid)
            nickname = str(s.get("nickname", ""))
            avatar_path = str(s.get("avatar_path") or "")
            cnt = self.storage.compute_active_tasks_count_for_subject(sid)
            created = str(s.get("created_at", ""))
            self.subjects_table.setItem(i, 0, QTableWidgetItem(nickname))
            self.subjects_table.setItem(i, 1, QTableWidgetItem(avatar_path))
            self.subjects_table.setItem(i, 2, QTableWidgetItem(str(cnt)))
            self.subjects_table.setItem(i, 3, QTableWidgetItem(created))

    def _selected_subject_id(self) -> str | None:
        row = self.subjects_table.currentRow()
        if row < 0:
            return None
        if row >= len(getattr(self, "_subj_row_id", [])):
            return None
        return str(self._subj_row_id[row])

    def _on_add_subject(self) -> None:
        dlg = SubjectDialog(self, self.storage, subject=None)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        nickname, role_ids, status_id = dlg.payload()
        try:
            subj = self.storage.add_subject(nickname=nickname, role_ids=role_ids, status_id=status_id)
            if dlg.avatar():
                self.storage.update_subject(
                    subject_id=str(subj.get("id")),
                    nickname=str(subj.get("nickname", "")),
                    role_ids=list(subj.get("role_ids") or []),
                    status_id=str(subj.get("status_id") or SYSTEM_STATUS_NONE_ID),
                    avatar_path=dlg.avatar(),
                )
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_edit_subject(self) -> None:
        sid = self._selected_subject_id()
        if not sid:
            QMessageBox.information(self, "Инфо", "Выберите субъекта.")
            return
        subjects = {str(s.get("id")): s for s in self.storage.get_subjects()}
        subj = subjects.get(sid)
        if not subj:
            return
        dlg = SubjectDialog(self, self.storage, subject=subj)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        nickname, role_ids, status_id = dlg.payload()
        try:
            self.storage.update_subject(
                subject_id=sid,
                nickname=nickname,
                role_ids=role_ids,
                status_id=status_id,
                avatar_path=dlg.avatar(),
            )
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_delete_subject(self) -> None:
        sid = self._selected_subject_id()
        if not sid:
            QMessageBox.information(self, "Инфо", "Выберите субъекта.")
            return
        subjects = {str(s.get("id")): s for s in self.storage.get_subjects()}
        subj = subjects.get(sid)
        if not subj:
            return
        if QMessageBox.question(self, "Подтверждение", f"Удалить субъекта '{subj.get('nickname','')}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.storage.delete_subject(sid)
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    # ---------------- Tasks (read-only) ----------------
    def _build_tasks_tab(self) -> None:
        root = QVBoxLayout(self.tasks_tab)
        hint = QLabel("Задачи (read-only). Редактирование задач — через доску/файлы прототипа.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.tasks_table = QTableWidget(0, 6)
        self.tasks_table.setHorizontalHeaderLabels(["Колонка", "Название", "Ответственный", "Начало", "Конец", "Создан"])
        self.tasks_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tasks_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tasks_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tasks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.tasks_table, 1)

    def refresh_tasks(self) -> None:
        subjects = self.storage.get_subjects()
        profile = self.storage.get_profile()
        admin_name = str(profile.get("nickname", "Администратор"))
        subj_name = {_ADMIN_PERSON_ID: admin_name}
        subj_name.update({str(s.get("id")): str(s.get("nickname")) for s in subjects})
        rows: list[tuple[str, dict]] = []
        for kind, title in [
            ("draft", "Черновик"),
            ("progress", "В процессе"),
            ("finished", "Завершено"),
            ("delayed", "Отложено"),
        ]:
            for t in self.storage.load_tasks(kind):
                rows.append((title, t))

        self.tasks_table.setRowCount(len(rows))
        for i, (col_title, t) in enumerate(rows):
            title = str(t.get("title") or t.get("name") or "Без названия")
            resp = _task_responsible_display(t, subj_name)
            self.tasks_table.setItem(i, 0, QTableWidgetItem(col_title))
            self.tasks_table.setItem(i, 1, QTableWidgetItem(title))
            self.tasks_table.setItem(i, 2, QTableWidgetItem(resp))
            self.tasks_table.setItem(i, 3, QTableWidgetItem(_format_dt(t.get("start_due"))))
            self.tasks_table.setItem(i, 4, QTableWidgetItem(_format_dt(t.get("end_due"))))
            self.tasks_table.setItem(i, 5, QTableWidgetItem(str(t.get("created_at") or "—")))

    # ---------------- Common ----------------
    def refresh_all(self) -> None:
        self.refresh_roles()
        self.refresh_statuses()
        self.refresh_subjects()
        self.refresh_tasks()
        self.refresh_story_taxonomy()

    # ---------------- Story taxonomy ----------------
    def _build_story_tab(self) -> None:
        root = QVBoxLayout(self.story_tab)
        top = QHBoxLayout()
        root.addLayout(top)

        self.btn_add_story_item = QPushButton("Добавить")
        self.btn_edit_story_item = QPushButton("Редактировать")
        self.btn_del_story_item = QPushButton("Удалить")
        self._apply_icon_button(self.btn_add_story_item, self._assets.add_button_png, tooltip="Добавить")
        self._apply_icon_button(self.btn_edit_story_item, self._assets.edit_button_png, tooltip="Редактировать")
        self._apply_icon_button(self.btn_del_story_item, self._assets.delete_button_png, tooltip="Удалить")
        self.btn_add_story_item.clicked.connect(self._on_add_story_tax_item)
        self.btn_edit_story_item.clicked.connect(self._on_edit_story_tax_item)
        self.btn_del_story_item.clicked.connect(self._on_delete_story_tax_item)
        top.addWidget(self.btn_add_story_item)
        top.addWidget(self.btn_edit_story_item)
        top.addWidget(self.btn_del_story_item)
        top.addStretch(1)

        self.story_table = QTableWidget(0, 2)
        self.story_table.setHorizontalHeaderLabels(["Название", "Тип"])
        self.story_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.story_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.story_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.story_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.story_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.story_table, 1)

    def refresh_story_taxonomy(self) -> None:
        items = self.storage.get_story_taxonomy()
        # order: seasons, arcs, sections; locked first inside each group
        kind_order = {"season": 0, "arc": 1, "section": 2}
        def _k(x: dict) -> tuple[int, int, str]:
            k = str(x.get("kind") or "")
            locked = 0 if bool(x.get("locked")) else 1
            return (kind_order.get(k, 99), locked, str(x.get("name") or "").lower())
        items = sorted(items, key=_k)
        self._story_row_id: list[str] = []
        self.story_table.setRowCount(len(items))
        kind_label = {"season": "Сезон", "arc": "Арка", "section": "Раздел"}
        for i, it in enumerate(items):
            self._story_row_id.append(str(it.get("id") or ""))
            name = str(it.get("name") or "")
            k = str(it.get("kind") or "")
            locked = bool(it.get("locked", False))
            it_name = QTableWidgetItem(name)
            if locked:
                it_name.setForeground(QColor("#BDBDBD"))
            self.story_table.setItem(i, 0, it_name)
            self.story_table.setItem(i, 1, QTableWidgetItem(kind_label.get(k, k or "—")))

    def _selected_story_tax_id(self) -> str | None:
        row = self.story_table.currentRow()
        if row < 0:
            return None
        if row >= len(getattr(self, "_story_row_id", [])):
            return None
        return str(self._story_row_id[row])

    def _on_add_story_tax_item(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Добавить элемент сюжета")
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)
        name_edit = QLineEdit()
        kind_cb = QComboBox()
        kind_cb.addItem("Сезон", "season")
        kind_cb.addItem("Арка", "arc")
        kind_cb.addItem("Раздел", "section")
        lay.addWidget(QLabel("Название"))
        lay.addWidget(name_edit)
        lay.addWidget(QLabel("Тип"))
        lay.addWidget(kind_cb)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.storage.add_story_taxonomy_item(name=name_edit.text(), kind=str(kind_cb.currentData() or ""))
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_edit_story_tax_item(self) -> None:
        tid = self._selected_story_tax_id()
        if not tid:
            QMessageBox.information(self, "Инфо", "Выберите строку.")
            return
        items = {str(x.get("id")): x for x in self.storage.get_story_taxonomy()}
        cur = items.get(tid)
        if not isinstance(cur, dict):
            return
        if bool(cur.get("locked", False)):
            QMessageBox.warning(self, "Запрещено", "Этот элемент нельзя редактировать.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Редактировать")
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)
        name_edit = QLineEdit(str(cur.get("name") or ""))
        lay.addWidget(QLabel("Название"))
        lay.addWidget(name_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.storage.update_story_taxonomy_item(tid, name=name_edit.text())
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_delete_story_tax_item(self) -> None:
        tid = self._selected_story_tax_id()
        if not tid:
            QMessageBox.information(self, "Инфо", "Выберите строку.")
            return
        items = {str(x.get("id")): x for x in self.storage.get_story_taxonomy()}
        cur = items.get(tid)
        if not isinstance(cur, dict):
            return
        if bool(cur.get("locked", False)):
            QMessageBox.warning(self, "Запрещено", "Этот элемент нельзя удалить.")
            return
        if QMessageBox.question(self, "Подтверждение", f"Удалить '{cur.get('name','')}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.storage.delete_story_taxonomy_item(tid)
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

