from __future__ import annotations

import math
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QDateTime
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.assets import get_interface_assets
from app.qt_icon_loader import QtIconLoader
from app.storage import Storage, APP_TZ
from app.task_subtasks import get_subtasks_from_task, get_subtasks_max_per_row_from_ui
from app.qt_pages.task_subtasks_widgets import SubtaskChainDetailWidget, _detail_chain_content_height

# Preview scroll: tall enough to show ~2 rows of the snake; max allows extra headroom.
_SUBTASK_CHAIN_PREVIEW_MIN_H = _detail_chain_content_height(2) + 36
_SUBTASK_CHAIN_PREVIEW_MAX_H = max(_SUBTASK_CHAIN_PREVIEW_MIN_H + 140, 420)


# Read-only chrome: no dropdown / spin arrows (view mode is non-interactive).
_VIEW_READ_ONLY_EXTRA_QSS = """
QComboBox::drop-down {
    width: 0px;
    border: none;
    padding: 0px;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
    border: none;
}
QDateTimeEdit::drop-down {
    width: 0px;
    border: none;
    padding: 0px;
}
QDateTimeEdit::up-button, QDateTimeEdit::down-button {
    width: 0px;
    height: 0px;
    border: none;
    padding: 0px;
    margin: 0px;
}
QDateTimeEdit::up-arrow, QDateTimeEdit::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
    border: none;
}
"""


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
    def __init__(
        self,
        parent: QWidget,
        storage: Storage,
        column_kind: str,
        *,
        task: dict,
        on_open_story: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.column_kind = str(column_kind)
        self._task = task or {}
        self._on_open_story = on_open_story

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

        # Story link (experimental mode only)
        self._story_box: QGroupBox | None = None
        self._story_btn: QPushButton | None = None
        self._maybe_build_story_box(root)

        # Responsible (read-only list)
        box_resp = QGroupBox("Ответственные")
        resp_l = QVBoxLayout(box_resp)
        self.resp_combo = QComboBox()
        self.resp_combo.setEditable(False)
        self.resp_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.resp_combo.view().setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.resp_combo.setEnabled(False)
        self.resp_combo.setStyleSheet(_VIEW_READ_ONLY_EXTRA_QSS)
        resp_l.addWidget(self.resp_combo)
        root.addWidget(box_resp)

        # Dates (read-only)
        box_dates = QGroupBox("Время")
        dates_l = QVBoxLayout(box_dates)

        min_dt = QDateTime.fromString("2000-01-01T00:00:00", Qt.DateFormat.ISODate)

        row_start = QHBoxLayout()
        row_start.addWidget(QLabel("Startline"), 0)
        self.start_dt = QDateTimeEdit()
        self.start_dt.setCalendarPopup(False)
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start_dt.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.start_dt.setMinimumDateTime(min_dt)
        self.start_dt.setSpecialValueText("не выбрано")
        self.start_dt.setDateTime(min_dt)
        self.start_dt.setEnabled(False)
        self.start_dt.setStyleSheet(_VIEW_READ_ONLY_EXTRA_QSS)
        row_start.addWidget(self.start_dt, 1)
        dates_l.addLayout(row_start)

        row_dead = QHBoxLayout()
        row_dead.addWidget(QLabel("Deadline"), 0)
        self.dead_dt = QDateTimeEdit()
        self.dead_dt.setCalendarPopup(False)
        self.dead_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dead_dt.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.dead_dt.setMinimumDateTime(min_dt)
        self.dead_dt.setSpecialValueText("не выбрано")
        self.dead_dt.setDateTime(min_dt)
        self.dead_dt.setEnabled(False)
        self.dead_dt.setStyleSheet(_VIEW_READ_ONLY_EXTRA_QSS)
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

        if get_subtasks_from_task(self._task):
            profile = self.storage.get_profile()
            name_by_id = {"__admin__": str(profile.get("nickname", "Администратор"))}
            for s in self.storage.get_subjects():
                sid = str(s.get("id") or "")
                if sid:
                    name_by_id[sid] = str(s.get("nickname") or "")
            max_row = get_subtasks_max_per_row_from_ui(self.storage.get_ui_settings())
            self._subtasks_name_by_id = name_by_id
            self._subtasks_max_row = max_row

            self._subtasks_detail = SubtaskChainDetailWidget(
                task=self._task, name_by_id=name_by_id, max_per_row=max_row, parent=self
            )

            box_st = QGroupBox("Цепочка подзадач")
            st_l = QVBoxLayout(box_st)
            st_l.setContentsMargins(12, 10, 12, 12)

            bar = QHBoxLayout()
            bar.addStretch(1)
            expand_btn = QPushButton("Развернуть")
            expand_btn.setToolTip("Открыть цепочку целиком в отдельном окне")
            expand_btn.clicked.connect(self._open_subtasks_chain_expanded)
            bar.addWidget(expand_btn)
            st_l.addLayout(bar)

            self._subtasks_scroll = QScrollArea()
            self._subtasks_scroll.setWidgetResizable(True)
            self._subtasks_scroll.setFrameShape(QFrame.Shape.NoFrame)
            self._subtasks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            n_sub = len(get_subtasks_from_task(self._task))
            mpr = max(2, min(24, int(max_row)))
            snake_rows = max(1, math.ceil(n_sub / mpr))
            content_h = _detail_chain_content_height(snake_rows) + 28
            if snake_rows <= 1:
                scroll_min = min(content_h, _SUBTASK_CHAIN_PREVIEW_MIN_H)
            else:
                scroll_min = _SUBTASK_CHAIN_PREVIEW_MIN_H
            scroll_max = max(scroll_min + 120, _SUBTASK_CHAIN_PREVIEW_MAX_H)
            self._subtasks_scroll.setMinimumHeight(scroll_min)
            self._subtasks_scroll.setMaximumHeight(scroll_max)
            self._subtasks_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            self._subtasks_scroll.setWidget(self._subtasks_detail)
            st_l.addWidget(self._subtasks_scroll)

            root.addWidget(box_st)

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

    def _maybe_build_story_box(self, root: QVBoxLayout) -> None:
        try:
            exp = bool(self.storage.get_profile().get("experimental_mode", False))
        except Exception:
            exp = False
        if not exp:
            return
        sid = str(self._task.get("story_id") or "").strip()
        title = "—"
        valid = False
        if sid:
            for st in self.storage.get_stories():
                if not isinstance(st, dict):
                    continue
                if str(st.get("id") or "") != sid:
                    continue
                if bool(st.get("archived", False)):
                    # archived => treat as missing
                    sid = ""
                    break
                title = str(st.get("title") or "Без названия")
                valid = True
                break

        box = QGroupBox("Связанная история")
        lay = QHBoxLayout(box)
        btn = QPushButton(title)
        btn.setEnabled(valid and bool(self._on_open_story))
        btn.setToolTip("Открыть историю" if btn.isEnabled() else "История не выбрана")
        btn.setStyleSheet("text-align: left;")
        if valid and callable(self._on_open_story):
            btn.clicked.connect(lambda: self._open_story_and_close(sid))
        lay.addWidget(btn, 1)
        self._story_box = box
        self._story_btn = btn
        root.addWidget(box)

    def _open_story_and_close(self, story_id: str) -> None:
        sid = str(story_id or "")
        if not sid or not callable(self._on_open_story):
            return
        try:
            self._on_open_story(sid)
        finally:
            self.accept()

    def _open_subtasks_chain_expanded(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Цепочка подзадач")
        dlg.setModal(True)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        w = 860
        h = 720
        if avail is not None:
            w = min(w, max(480, avail.width() - 80))
            h = min(h, max(400, int(avail.height() * 0.88)))
        dlg.resize(w, h)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chain = SubtaskChainDetailWidget(
            task=self._task,
            name_by_id=self._subtasks_name_by_id,
            max_per_row=self._subtasks_max_row,
            parent=dlg,
        )
        scroll.setWidget(chain)
        lay.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dlg.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

        dlg.exec()

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
        # Hide view immediately, then run edit as the only visible modal; finish with accept so board refreshes.
        try:
            from app.qt_pages.task_create_dialog import TaskCreateDialog
        except Exception:
            return
        parent = self.parent() if isinstance(self.parent(), QWidget) else self
        self.hide()
        dlg = TaskCreateDialog(parent=parent, storage=self.storage, column_kind=self.column_kind, task=self._task)
        dlg.exec()
        self.accept()

