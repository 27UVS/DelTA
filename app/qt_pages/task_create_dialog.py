from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from html import escape as _html_escape

from PySide6.QtCore import Qt, QDateTime, QDate
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
)

from app.storage import Storage, utc_now_iso, SYSTEM_STATUS_NONE_ID, APP_TZ
from app.assets import get_interface_assets
from app.qt_icon_loader import QtIconLoader

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
        self.resize(760, 680)

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
            self.start_dt.calendarWidget().setSelectedDate(today)
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
            self.dead_dt.calendarWidget().setSelectedDate(today)
        except Exception:
            pass
        row_dead.addWidget(self.dead_dt, 1)
        dates_l.addLayout(row_dead)

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

        # flags and dates
        self.no_deadline_cb.setChecked(bool(t.get("no_deadline", False)))
        self.recurring_cb.setChecked(bool(t.get("recurring", False)))
        self._on_flags_changed()

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

        task_id = self._task_id or str(uuid.uuid4())
        created_at = str((self._task or {}).get("created_at") or utc_now_iso())
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

