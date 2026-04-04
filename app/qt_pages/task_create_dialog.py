from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from html import escape as _html_escape

from PySide6.QtCore import Qt, QDateTime, QDate, QTime
from PySide6.QtCore import QSize
from PySide6.QtGui import (
    QPixmap,
    QPainter,
    QBrush,
    QColor,
    QStandardItemModel,
    QStandardItem,
    QPainterPath,
    QTextCharFormat,
    QTextCursor,
    QTextListFormat,
    QIcon,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QScrollArea,
    QFrame,
)

from app.storage import Storage, utc_now_iso, SYSTEM_STATUS_NONE_ID, APP_TZ
from app.assets import get_interface_assets
from app.qt_icon_loader import QtIconLoader
from app.task_subtasks import (
    get_subtasks_from_task,
    normalize_subtask_row,
    subtasks_sequential_dones_flags,
    validate_subtasks_sequential_order,
)

_ADMIN_PERSON_ID = "__admin__"


@dataclass(frozen=True)
class PersonRef:
    id: str
    name: str
    avatar_path: str | None
    color: str


def _now_local() -> datetime:
    return datetime.now(APP_TZ)


def _dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(APP_TZ).isoformat(timespec="seconds")


def _datetime_to_qdt(dt: datetime) -> QDateTime:
    """Wall clock in APP_TZ for QDateTimeEdit."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    dt = dt.astimezone(APP_TZ)
    from_py = getattr(QDateTime, "fromPython", None)
    if callable(from_py):
        return from_py(dt)
    return QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute, dt.second))


def _circular_avatar(pix: QPixmap, size: int) -> QPixmap:
    pm = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pm)
    finally:
        painter.end()
    return out


def _circle_fallback_letter(size: int, *, letter: str, bg_hex: str) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        painter.fillRect(out.rect(), QColor(bg_hex or "#3A7CFF"))
        painter.setClipping(False)
        painter.setPen(Qt.GlobalColor.white)
        f = painter.font()
        f.setFamily("Segoe UI")
        f.setBold(True)
        f.setPointSize(max(9, int(size * 0.42)))
        painter.setFont(f)
        painter.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, (letter or "?")[:1].upper())
    finally:
        painter.end()
    return out


class TaskCreateDialog(QDialog):
    def __init__(self, parent: QWidget, storage: Storage, column_kind: str, *, task: dict | None = None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.column_kind = str(column_kind)
        self._task = task or None
        self._task_id = str((task or {}).get("id") or "")
        self._icons = QtIconLoader()
        self._assets = get_interface_assets()

        self.setWindowTitle("Создать задание" if self._task is None else "Редактировать задание")
        self.setModal(True)
        self.resize(760, 740)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Title
        row_title = QHBoxLayout()
        row_title.addWidget(QLabel("Название"), 0)
        self.title_edit = QLineEdit()
        row_title.addWidget(self.title_edit, 1)
        root.addLayout(row_title)

        # Responsible
        box_resp = QGroupBox("Ответственные")
        resp_l = QVBoxLayout(box_resp)
        self.resp_combo = QComboBox()
        self.resp_combo.setEditable(False)
        self.resp_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.resp_combo.view().setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        resp_l.addWidget(self.resp_combo)
        root.addWidget(box_resp)

        # Dates
        box_dates = QGroupBox("Время")
        dates_l = QVBoxLayout(box_dates)

        min_dt = QDateTime.fromString("2000-01-01T00:00:00", Qt.DateFormat.ISODate)
        self._dates_min_dt = min_dt
        self._dates_max_dt = QDateTime(QDate(7999, 12, 31), QTime(23, 59, 59))
        today = QDate.currentDate()

        row_start = QHBoxLayout()
        row_start.addWidget(QLabel("Startline"), 0)
        self.start_dt = QDateTimeEdit()
        self.start_dt.setCalendarPopup(True)
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        # Hide step buttons (they can visually glitch with some styles/DPI).
        self.start_dt.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.start_dt.setMinimumDateTime(min_dt)
        self.start_dt.setSpecialValueText("не выбрано")
        self.start_dt.setDateTime(min_dt)
        try:
            self.start_dt.calendarWidget().setCurrentPage(today.year(), today.month())
        except Exception:
            pass
        row_start.addWidget(self.start_dt, 1)
        dates_l.addLayout(row_start)

        row_dead = QHBoxLayout()
        row_dead.addWidget(QLabel("Deadline"), 0)
        self.dead_dt = QDateTimeEdit()
        self.dead_dt.setCalendarPopup(True)
        self.dead_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        # Hide step buttons (they can visually glitch with some styles/DPI).
        self.dead_dt.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.dead_dt.setMinimumDateTime(min_dt)
        self.dead_dt.setSpecialValueText("не выбрано")
        self.dead_dt.setDateTime(min_dt)
        try:
            self.dead_dt.calendarWidget().setCurrentPage(today.year(), today.month())
        except Exception:
            pass
        row_dead.addWidget(self.dead_dt, 1)
        dates_l.addLayout(row_dead)

        self.start_dt.dateTimeChanged.connect(self._sync_start_deadline_relation)
        self.dead_dt.dateTimeChanged.connect(self._sync_start_deadline_relation)

        row_flags = QHBoxLayout()
        self.no_deadline_cb = QCheckBox("Задание без deadline")
        self.recurring_cb = QCheckBox("Постоянное задание")
        self.no_deadline_cb.toggled.connect(self._on_flags_changed)
        self.recurring_cb.toggled.connect(self._on_flags_changed)
        row_flags.addWidget(self.no_deadline_cb, 0)
        row_flags.addWidget(self.recurring_cb, 0)
        row_flags.addStretch(1)
        dates_l.addLayout(row_flags)

        root.addWidget(box_dates)

        # Subtasks (optional chain)
        box_sub = QGroupBox("Подзадачи")
        sub_outer = QVBoxLayout(box_sub)
        sub_outer.setSpacing(10)
        self._subtask_rows: list[dict] = []
        self._subtasks_inner = QWidget()
        self._subtasks_layout = QVBoxLayout(self._subtasks_inner)
        self._subtasks_layout.setContentsMargins(0, 0, 0, 0)
        self._subtasks_layout.setSpacing(8)
        sub_scroll = QScrollArea()
        sub_scroll.setWidgetResizable(True)
        sub_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sub_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sub_scroll.setWidget(self._subtasks_inner)
        # Taller editor so several rows + scrollbar do not fight with the add button.
        sub_scroll.setMinimumHeight(300)
        sub_scroll.setMaximumHeight(480)
        sub_outer.addWidget(sub_scroll, 1)
        self.add_sub_btn = QPushButton("Добавить подзадачу")
        self.add_sub_btn.clicked.connect(self._on_add_subtask_row)
        sub_outer.addWidget(self.add_sub_btn)
        root.addWidget(box_sub)

        # Description
        box_desc = QGroupBox("Описание")
        desc_l = QVBoxLayout(box_desc)
        tools = QHBoxLayout()

        def _mk_btn(text: str, tooltip: str, cb) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tooltip)
            b.setFixedHeight(28)
            b.clicked.connect(cb)
            return b

        self._btn_bold = _mk_btn("B", "Жирный", self._fmt_bold)
        self._btn_italic = _mk_btn("I", "Курсив", self._fmt_italic)
        self._btn_underline = _mk_btn("U", "Подчёркнутый", self._fmt_underline)
        self._btn_strike = _mk_btn("S", "Зачёркнутый", self._fmt_strike)
        self._btn_left = _mk_btn("⟸", "По левому краю", lambda: self.desc_edit.setAlignment(Qt.AlignmentFlag.AlignLeft))
        self._btn_center = _mk_btn("≡", "По центру", lambda: self.desc_edit.setAlignment(Qt.AlignmentFlag.AlignHCenter))
        self._btn_right = _mk_btn("⟹", "По правому краю", lambda: self.desc_edit.setAlignment(Qt.AlignmentFlag.AlignRight))
        self._btn_justify = _mk_btn("▤", "По ширине", lambda: self.desc_edit.setAlignment(Qt.AlignmentFlag.AlignJustify))
        self._btn_bullets = _mk_btn("•", "Маркированный список", self._fmt_bullets)
        self._btn_numbers = _mk_btn("1.", "Нумерованный список", self._fmt_numbers)
        self._btn_link = _mk_btn("", "Вставить ссылку", self._fmt_link)
        pm = self._icons.load_pixmap(self._assets.link_button_png, (18, 18))
        if pm is not None:
            self._btn_link.setIcon(QIcon(pm))
            self._btn_link.setIconSize(QSize(18, 18))
        self._btn_link.setFixedSize(34, 28)

        for w in [
            self._btn_bold,
            self._btn_italic,
            self._btn_underline,
            self._btn_strike,
            self._btn_left,
            self._btn_center,
            self._btn_right,
            self._btn_justify,
            self._btn_bullets,
            self._btn_numbers,
            self._btn_link,
        ]:
            tools.addWidget(w, 0)
        tools.addStretch(1)
        desc_l.addLayout(tools)

        self.desc_edit = QTextEdit()
        self.desc_edit.setAcceptRichText(True)
        self.desc_edit.setMinimumHeight(160)
        desc_l.addWidget(self.desc_edit, 1)
        root.addWidget(box_desc, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_save)
        self.delete_btn = buttons.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_btn.setVisible(self._task is not None)
        self.delete_btn.setStyleSheet("background:#C62828; color:#FFFFFF; padding:6px 12px;")
        self.delete_btn.clicked.connect(self._on_delete)
        root.addWidget(buttons)

        self._people: list[PersonRef] = []
        self._resp_model = QStandardItemModel(self)
        self.resp_combo.setModel(self._resp_model)
        self._load_people()
        self._update_resp_summary()
        if self._task is not None:
            self._load_task()
        else:
            self._apply_new_task_default_times()
            self._sync_start_deadline_relation()

    def _apply_new_task_default_times(self) -> None:
        """New task: start = now, deadline = now + 24h (visible defaults, not 'не выбрано')."""
        now = _now_local()
        qs = _datetime_to_qdt(now)
        qe = _datetime_to_qdt(now + timedelta(days=1))
        # Set both under blocked signals: if only start is set first, _sync would use deadline still at
        # calendar "today 00:00" and clamp start's time down to midnight via setMaximumDateTime.
        self.start_dt.blockSignals(True)
        self.dead_dt.blockSignals(True)
        self.dead_dt.setDateTime(qe)
        self.start_dt.setDateTime(qs)
        self.start_dt.blockSignals(False)
        self.dead_dt.blockSignals(False)
        try:
            self.start_dt.calendarWidget().setCurrentPage(qs.date().year(), qs.date().month())
            self.dead_dt.calendarWidget().setCurrentPage(qe.date().year(), qe.date().month())
        except Exception:
            pass

    def _sync_start_deadline_relation(self) -> None:
        """Keep startline <= deadline when both apply; relax limits for recurring / no deadline."""
        if self.recurring_cb.isChecked() or self.no_deadline_cb.isChecked():
            self.start_dt.blockSignals(True)
            self.dead_dt.blockSignals(True)
            self.start_dt.setMaximumDateTime(self._dates_max_dt)
            self.dead_dt.setMinimumDateTime(self._dates_min_dt)
            self.start_dt.blockSignals(False)
            self.dead_dt.blockSignals(False)
            return

        d = self.dead_dt.dateTime()
        s = self.start_dt.dateTime()
        dead_chosen = d > self.dead_dt.minimumDateTime()
        start_chosen = s > self.start_dt.minimumDateTime()

        self.start_dt.blockSignals(True)
        self.dead_dt.blockSignals(True)
        if dead_chosen:
            self.start_dt.setMaximumDateTime(d)
        else:
            self.start_dt.setMaximumDateTime(self._dates_max_dt)
        if start_chosen:
            self.dead_dt.setMinimumDateTime(s if s >= self._dates_min_dt else self._dates_min_dt)
        else:
            self.dead_dt.setMinimumDateTime(self._dates_min_dt)
        if dead_chosen and start_chosen and s > d:
            self.start_dt.setDateTime(d)
        if dead_chosen and start_chosen and d < s:
            self.dead_dt.setDateTime(self.start_dt.dateTime())
        self.start_dt.blockSignals(False)
        self.dead_dt.blockSignals(False)

    def _load_task(self) -> None:
        t = self._task or {}
        self.title_edit.setText(str(t.get("title") or t.get("name") or ""))
        self._set_desc_from_storage(str(t.get("description") or ""))
        # responsibles
        selected = set([str(x) for x in (t.get("responsible_subject_ids") or []) if x])
        if not selected and t.get("responsible_subject_id"):
            selected.add(str(t.get("responsible_subject_id")))
        for i in range(self._resp_model.rowCount()):
            it = self._resp_model.item(i)
            if it is None:
                continue
            pid = str(it.data(Qt.ItemDataRole.UserRole))
            it.setCheckState(Qt.CheckState.Checked if pid in selected else Qt.CheckState.Unchecked)
        self._update_resp_summary()

        # flags and dates (apply datetimes before _on_flags_changed/_sync so limits are not clamped to placeholders)
        self.no_deadline_cb.setChecked(bool(t.get("no_deadline", False)))
        self.recurring_cb.setChecked(bool(t.get("recurring", False)))

        def _set_dt(edit: QDateTimeEdit, iso: str | None) -> None:
            if not iso:
                edit.setDateTime(edit.minimumDateTime())
                return
            try:
                dt = datetime.fromisoformat(str(iso))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=APP_TZ)
                qdt = QDateTime(dt.astimezone(APP_TZ))
                edit.setDateTime(qdt)
            except Exception:
                edit.setDateTime(edit.minimumDateTime())

        _set_dt(self.start_dt, t.get("start_due"))
        _set_dt(self.dead_dt, t.get("end_due"))
        self._on_flags_changed()
        self._load_subtasks()
        self._sync_start_deadline_relation()

    def _default_subtask_responsible(self) -> str:
        ids = self._selected_responsibles()
        if ids:
            return str(ids[0])
        if self._people:
            return str(self._people[0].id)
        return _ADMIN_PERSON_ID

    def _clear_subtask_rows(self) -> None:
        for row in list(self._subtask_rows):
            w = row["w"]
            self._subtasks_layout.removeWidget(w)
            w.deleteLater()
        self._subtask_rows.clear()

    def _load_subtasks(self) -> None:
        self._clear_subtask_rows()
        if self._task is None:
            return
        raw = get_subtasks_from_task(self._task)
        dones = subtasks_sequential_dones_flags(raw)
        for st, done in zip(raw, dones):
            rid = str(st.get("responsible_subject_id") or "")
            ids = st.get("responsible_subject_ids")
            if isinstance(ids, list) and ids:
                rid = str(ids[0])
            self._append_subtask_row(str(st.get("title") or ""), rid, done, str(st.get("id") or ""))

    def _on_add_subtask_row(self) -> None:
        self._append_subtask_row("", self._default_subtask_responsible(), False, "")

    def _append_subtask_row(self, title: str, responsible_id: str, done: bool, existing_id: str) -> None:
        row_w = QWidget()
        hl = QHBoxLayout(row_w)
        hl.setContentsMargins(0, 0, 0, 0)
        te = QLineEdit()
        te.setPlaceholderText("Название подзадачи")
        te.setText(title)
        cb = QComboBox()
        for p in self._people:
            cb.addItem(p.name, p.id)
        idx = 0
        rid = str(responsible_id or "")
        for i in range(cb.count()):
            if str(cb.itemData(i)) == rid:
                idx = i
                break
        cb.setCurrentIndex(idx)
        done_cb = QCheckBox("Готово")
        done_cb.setChecked(done)
        done_cb.stateChanged.connect(partial(self._on_subtask_done_state_changed, row_w))
        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        rm.setToolTip("Удалить подзадачу")
        rm.clicked.connect(partial(self._remove_subtask_row, row_w))
        hl.addWidget(te, 2)
        hl.addWidget(cb, 1)
        hl.addWidget(done_cb, 0)
        hl.addWidget(rm, 0)
        self._subtasks_layout.addWidget(row_w)
        self._subtask_rows.append({"w": row_w, "title": te, "person": cb, "done": done_cb, "sid": (existing_id or None)})

    def _remove_subtask_row(self, w: QWidget) -> None:
        for i, row in enumerate(self._subtask_rows):
            if row["w"] is w:
                self._subtasks_layout.removeWidget(w)
                w.deleteLater()
                self._subtask_rows.pop(i)
                return

    def _on_subtask_done_state_changed(self, row_w: QWidget, state: int) -> None:
        idx = next((i for i, r in enumerate(self._subtask_rows) if r["w"] is row_w), None)
        if idx is None:
            return
        cb = self._subtask_rows[idx]["done"]
        if Qt.CheckState(state) == Qt.CheckState.Checked:
            for i in range(idx):
                if not self._subtask_rows[i]["done"].isChecked():
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
                    QMessageBox.warning(
                        self,
                        "Порядок подзадач",
                        "Сначала отметьте выполненными все предыдущие пункты цепочки.",
                    )
                    return
        else:
            for j in range(idx + 1, len(self._subtask_rows)):
                o = self._subtask_rows[j]["done"]
                if not o.isChecked():
                    continue
                o.blockSignals(True)
                o.setChecked(False)
                o.blockSignals(False)

    def _collect_subtasks_payload(self) -> list[dict]:
        out: list[dict] = []
        for row in self._subtask_rows:
            title = row["title"].text().strip()
            if not title:
                continue
            pid = str(row["person"].currentData() or "")
            if not pid:
                raise ValueError("Для каждой подзадачи нужен ответственный.")
            sid = row.get("sid")
            out.append(
                normalize_subtask_row(
                    title=title,
                    responsible_id=pid,
                    done=bool(row["done"].isChecked()),
                    existing_id=str(sid) if sid else None,
                )
            )
        validate_subtasks_sequential_order(out)
        return out

    def _load_people(self) -> None:
        # Admin + subjects (the same set as people panel)
        profile = self.storage.get_profile()
        admin_name = str(profile.get("nickname", "Администратор"))
        admin_avatar = str(profile.get("avatar_path") or "") or None
        roles = {r.id: r for r in self.storage.get_roles()}
        admin_role = roles.get("role_admin")
        admin_color = (admin_role.color if admin_role else "#3A7CFF") if admin_role else "#3A7CFF"
        people: list[PersonRef] = [PersonRef(id=_ADMIN_PERSON_ID, name=admin_name, avatar_path=admin_avatar, color=admin_color)]
        for s in self.storage.get_subjects():
            sid = str(s.get("id") or "")
            if not sid:
                continue
            role_ids = [str(rid) for rid in (s.get("role_ids") or []) if rid not in ("role_none",)]
            role_objs = [roles[rid] for rid in role_ids if rid in roles]
            role_objs = sorted(role_objs, key=lambda rr: (rr.priority, rr.name.lower()))
            color = (role_objs[0].color if role_objs else "#3A7CFF") if role_objs else "#3A7CFF"
            people.append(
                PersonRef(
                    id=sid,
                    name=str(s.get("nickname") or ""),
                    avatar_path=str(s.get("avatar_path") or "") or None,
                    color=color,
                )
            )

        self._people = people
        self._resp_model.clear()
        for p in people:
            it = QStandardItem(p.name)
            it.setData(p.id, Qt.ItemDataRole.UserRole)
            it.setCheckable(True)
            it.setCheckState(Qt.CheckState.Unchecked)
            # avatar icon
            if p.avatar_path and Path(p.avatar_path).exists():
                pix = QPixmap(p.avatar_path)
                if not pix.isNull():
                    it.setIcon(_circular_avatar(pix, 24))
                else:
                    it.setIcon(_circle_fallback_letter(24, letter=p.name[:1], bg_hex=p.color))
            else:
                it.setIcon(_circle_fallback_letter(24, letter=p.name[:1], bg_hex=p.color))
            self._resp_model.appendRow(it)

        # Toggle by click
        view = self.resp_combo.view()
        view.pressed.connect(self._on_resp_pressed)

    def _on_resp_pressed(self, idx) -> None:
        it = self._resp_model.itemFromIndex(idx)
        if it is None:
            return
        it.setCheckState(Qt.CheckState.Checked if it.checkState() != Qt.CheckState.Checked else Qt.CheckState.Unchecked)
        self._update_resp_summary()

    def _selected_responsibles(self) -> list[str]:
        ids: list[str] = []
        for i in range(self._resp_model.rowCount()):
            it = self._resp_model.item(i)
            if it is None:
                continue
            if it.checkState() == Qt.CheckState.Checked:
                ids.append(str(it.data(Qt.ItemDataRole.UserRole)))
        return ids

    def _update_resp_summary(self) -> None:
        n = len(self._selected_responsibles())
        self.resp_combo.setCurrentText("Не выбрано" if n == 0 else f"Выбрано: {n}")

    def _on_flags_changed(self) -> None:
        # Mutual exclusion
        if self.no_deadline_cb.isChecked():
            self.recurring_cb.blockSignals(True)
            self.recurring_cb.setChecked(False)
            self.recurring_cb.blockSignals(False)
        if self.recurring_cb.isChecked():
            self.no_deadline_cb.blockSignals(True)
            self.no_deadline_cb.setChecked(False)
            self.no_deadline_cb.blockSignals(False)

        no_dead = self.no_deadline_cb.isChecked()
        recur = self.recurring_cb.isChecked()
        self.dead_dt.setEnabled((not no_dead) and (not recur))
        self.start_dt.setEnabled(not recur)
        self._sync_start_deadline_relation()

    def _date_or_none(self, edit: QDateTimeEdit) -> datetime | None:
        # If at minimum => treat as "not chosen"
        if edit.dateTime() == edit.minimumDateTime():
            return None
        dt = edit.dateTime().toPython()
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=APP_TZ)
            return dt.astimezone(APP_TZ)
        return None

    def _on_save(self) -> None:
        title = self.title_edit.text().strip()
        resp_ids = self._selected_responsibles()
        if not title:
            QMessageBox.critical(self, "Ошибка", "Название задания не может быть пустым.")
            return
        if not resp_ids:
            QMessageBox.critical(self, "Ошибка", "Выберите хотя бы одного ответственного.")
            return

        recur = bool(self.recurring_cb.isChecked())
        no_dead = bool(self.no_deadline_cb.isChecked())

        now = _now_local()
        start = None if recur else (self._date_or_none(self.start_dt) or now)
        deadline = None
        if not recur and not no_dead:
            deadline = self._date_or_none(self.dead_dt) or (now + timedelta(days=1))

        if not recur and not no_dead and start is not None and deadline is not None and start > deadline:
            QMessageBox.critical(
                self,
                "Ошибка",
                "Startline не может быть позже deadline. Укажите дату начала не позже срока окончания.",
            )
            return

        task_id = self._task_id or str(uuid.uuid4())
        created_at = str((self._task or {}).get("created_at") or utc_now_iso())
        try:
            subtasks = self._collect_subtasks_payload()
        except ValueError as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return
        payload: dict = {
            "id": task_id,
            "title": title,
            "description": self.desc_edit.toHtml().strip(),
            "created_at": created_at,
            # compatibility with existing UI/admin table
            "responsible_subject_id": resp_ids[0],
            "responsible_subject_ids": resp_ids,
            "start_due": _dt_to_iso(start) if start else None,
            "end_due": _dt_to_iso(deadline) if deadline else None,
            "no_deadline": bool(no_dead),
            "recurring": bool(recur),
            "status_id": SYSTEM_STATUS_NONE_ID,
            "subtasks": subtasks,
        }

        try:
            if self._task is None:
                self.storage.add_task(self.column_kind, payload)
            else:
                self.storage.update_task(self.column_kind, task_id, payload)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return

        self.accept()

    def _set_desc_from_storage(self, text: str) -> None:
        s = (text or "").strip()
        # Backward compat: old data used plain text; new uses HTML from QTextEdit.
        if "<" in s and ">" in s and ("</" in s or "<br" in s or "<p" in s):
            self.desc_edit.setHtml(s)
        else:
            self.desc_edit.setPlainText(s)

    def _merge_char_format(self, fmt: QTextCharFormat) -> None:
        c = self.desc_edit.textCursor()
        if not c.hasSelection():
            # Apply to current position for next typed text.
            self.desc_edit.mergeCurrentCharFormat(fmt)
        else:
            c.mergeCharFormat(fmt)
            self.desc_edit.setTextCursor(c)

    def _fmt_bold(self) -> None:
        fmt = QTextCharFormat()
        w = self.desc_edit.fontWeight()
        fmt.setFontWeight(400 if int(w) >= 600 else 700)
        self._merge_char_format(fmt)

    def _fmt_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.desc_edit.fontItalic())
        self._merge_char_format(fmt)

    def _fmt_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.desc_edit.fontUnderline())
        self._merge_char_format(fmt)

    def _fmt_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not fmt.fontStrikeOut())
        # Need current state from selection/cursor:
        cur = self.desc_edit.textCursor()
        if cur.hasSelection():
            fmt.setFontStrikeOut(not cur.charFormat().fontStrikeOut())
        else:
            fmt.setFontStrikeOut(not self.desc_edit.currentCharFormat().fontStrikeOut())
        self._merge_char_format(fmt)

    def _fmt_bullets(self) -> None:
        cur = self.desc_edit.textCursor()
        cur.beginEditBlock()
        lf = QTextListFormat()
        lf.setStyle(QTextListFormat.Style.ListDisc)
        cur.createList(lf)
        cur.endEditBlock()

    def _fmt_numbers(self) -> None:
        cur = self.desc_edit.textCursor()
        cur.beginEditBlock()
        lf = QTextListFormat()
        lf.setStyle(QTextListFormat.Style.ListDecimal)
        cur.createList(lf)
        cur.endEditBlock()

    def _fmt_link(self) -> None:
        url, ok = QInputDialog.getText(self, "Вставить ссылку", "URL (например https://example.com):")
        if not ok:
            return
        url = str(url or "").strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        cur = self.desc_edit.textCursor()
        sel_text = cur.selectedText().replace("\u2029", "\n")
        text = sel_text.strip() or url
        # Insert HTML anchor (works well for QTextEdit HTML storage)
        cur.insertHtml(f'<a href="{_html_escape(url)}">{_html_escape(text)}</a>')

    def _on_delete(self) -> None:
        if self._task is None or not self._task_id:
            return
        if (
            QMessageBox.question(
                self,
                "Подтверждение удаления",
                "Вы уверены, что хотите удалить задание?\nЭто действие нельзя отменить.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.storage.delete_task(self.column_kind, self._task_id)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

