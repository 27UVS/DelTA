from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QDateTime
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.assets import get_interface_assets
from app.qt_icon_loader import QtIconLoader
from app.storage import Storage, APP_TZ


def _dt_from_iso_local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(APP_TZ)


class TaskViewDialog(QDialog):
    def __init__(self, parent: QWidget, storage: Storage, column_kind: str, *, task: dict) -> None:
        super().__init__(parent)
        self.storage = storage
        self.column_kind = str(column_kind)
        self._task = task or {}

        self.setWindowTitle("Просмотр задания")
        self.setModal(True)
        self.resize(760, 680)

        self._icons = QtIconLoader()
        self._assets = get_interface_assets()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Header with edit button
        header = QHBoxLayout()
        title = QLabel("Задание")
        title.setObjectName("H2")
        header.addWidget(title, 0)
        header.addStretch(1)
        self.edit_btn = QPushButton("")
        self.edit_btn.setToolTip("Редактировать")
        edit_pix = self._icons.load_pixmap(self._assets.edit_button_png, (18, 18))
        if edit_pix is not None:
            self.edit_btn.setIcon(QIcon(edit_pix))
        self.edit_btn.setFixedSize(34, 28)
        self.edit_btn.setIconSize(QSize(18, 18))
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        header.addWidget(self.edit_btn, 0)
        root.addLayout(header)

        # Title
        row_title = QHBoxLayout()
        row_title.addWidget(QLabel("Название"), 0)
        self.title_edit = QLineEdit()
        self.title_edit.setReadOnly(True)
        self.title_edit.setText(str(self._task.get("title") or self._task.get("name") or ""))
        row_title.addWidget(self.title_edit, 1)
        root.addLayout(row_title)

        # Responsible (read-only list)
        box_resp = QGroupBox("Ответственные")
        resp_l = QVBoxLayout(box_resp)
        self.resp_combo = QComboBox()
        self.resp_combo.setEditable(False)
        self.resp_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.resp_combo.view().setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.resp_combo.setEnabled(False)
        resp_l.addWidget(self.resp_combo)
        root.addWidget(box_resp)

        # Dates (read-only)
        box_dates = QGroupBox("Время")
        dates_l = QVBoxLayout(box_dates)

        min_dt = QDateTime.fromString("2000-01-01T00:00:00", Qt.DateFormat.ISODate)

        row_start = QHBoxLayout()
        row_start.addWidget(QLabel("Startline"), 0)
        self.start_dt = QDateTimeEdit()
        self.start_dt.setCalendarPopup(True)
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start_dt.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.start_dt.setMinimumDateTime(min_dt)
        self.start_dt.setSpecialValueText("не выбрано")
        self.start_dt.setDateTime(min_dt)
        self.start_dt.setEnabled(False)
        row_start.addWidget(self.start_dt, 1)
        dates_l.addLayout(row_start)

        row_dead = QHBoxLayout()
        row_dead.addWidget(QLabel("Deadline"), 0)
        self.dead_dt = QDateTimeEdit()
        self.dead_dt.setCalendarPopup(True)
        self.dead_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dead_dt.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.dead_dt.setMinimumDateTime(min_dt)
        self.dead_dt.setSpecialValueText("не выбрано")
        self.dead_dt.setDateTime(min_dt)
        self.dead_dt.setEnabled(False)
        row_dead.addWidget(self.dead_dt, 1)
        dates_l.addLayout(row_dead)

        row_flags = QHBoxLayout()
        self.no_deadline_cb = QCheckBox("Задание без deadline")
        self.recurring_cb = QCheckBox("Постоянное задание")
        self.no_deadline_cb.setEnabled(False)
        self.recurring_cb.setEnabled(False)
        row_flags.addWidget(self.no_deadline_cb, 0)
        row_flags.addWidget(self.recurring_cb, 0)
        row_flags.addStretch(1)
        dates_l.addLayout(row_flags)

        root.addWidget(box_dates)

        # Description
        box_desc = QGroupBox("Описание")
        desc_l = QVBoxLayout(box_desc)
        self.desc_edit = QTextBrowser()
        self.desc_edit.setOpenExternalLinks(True)
        self.desc_edit.setMinimumHeight(160)
        self._set_desc_from_storage(str(self._task.get("description") or ""))
        desc_l.addWidget(self.desc_edit, 1)
        root.addWidget(box_desc, 1)

        self._populate()

    def _populate(self) -> None:
        t = self._task or {}
        # responsibles: show a summary text (same semantics as create dialog)
        ids = [str(x) for x in (t.get("responsible_subject_ids") or []) if x]
        if not ids and t.get("responsible_subject_id"):
            ids = [str(t.get("responsible_subject_id"))]
        # Build names map
        subjects = self.storage.get_subjects()
        profile = self.storage.get_profile()
        subj_name = {"__admin__": str(profile.get("nickname", "Администратор"))}
        subj_name.update({str(s.get("id")): str(s.get("nickname")) for s in subjects})
        names = [subj_name.get(pid, "—") for pid in ids] if ids else []
        self.resp_combo.clear()
        self.resp_combo.addItem("—" if not names else ", ".join(names))

        self.no_deadline_cb.setChecked(bool(t.get("no_deadline", False)))
        self.recurring_cb.setChecked(bool(t.get("recurring", False)) or (not t.get("start_due") and not t.get("end_due")))

        sd = _dt_from_iso_local(t.get("start_due"))
        ed = _dt_from_iso_local(t.get("end_due"))
        if sd is not None:
            self.start_dt.setDateTime(QDateTime(sd))
        if ed is not None:
            self.dead_dt.setDateTime(QDateTime(ed))

    def _set_desc_from_storage(self, text: str) -> None:
        s = (text or "").strip()
        # Backward compat: old data used plain text; new uses HTML from QTextEdit.
        if "<" in s and ">" in s and ("</" in s or "<br" in s or "<p" in s):
            self.desc_edit.setHtml(s)
        else:
            self.desc_edit.setPlainText(s)

    def _on_edit_clicked(self) -> None:
        # Replace view with edit dialog. No return to view after save/cancel.
        try:
            from app.qt_pages.task_create_dialog import TaskCreateDialog
        except Exception:
            return
        dlg = TaskCreateDialog(parent=self.parent() if isinstance(self.parent(), QWidget) else self, storage=self.storage, column_kind=self.column_kind, task=self._task)
        dlg.exec()
        self.accept()

