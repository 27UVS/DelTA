from __future__ import annotations

import os
import sys
import subprocess
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
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
    QApplication,
    QSpinBox,
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

        # Experimental toggle (Stories planner etc.)
        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(0, 0, 0, 0)
        exp_row.setSpacing(10)
        exp_lbl = QLabel("Экспериментальный режим")
        exp_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.experimental_switch = _ToggleSwitch()
        self.experimental_switch.setToolTip("Включает/выключает экспериментальные разделы (например, Истории).")
        exp_row.addWidget(exp_lbl, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        exp_row.addStretch(1)
        exp_row.addWidget(self.experimental_switch, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Align with the left edge of the "Другие ссылки/контакты" input itself.
        fields.addLayout(exp_row)

        full_off_row = QHBoxLayout()
        full_off_row.setContentsMargins(0, 0, 0, 0)
        full_off_row.setSpacing(10)
        full_off_lbl = QLabel("Полное отключение")
        full_off_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.full_shutdown_switch = _ToggleSwitch()
        self.full_shutdown_switch.blockSignals(True)
        self.full_shutdown_switch.setChecked(True)
        self.full_shutdown_switch.blockSignals(False)
        self.full_shutdown_switch.toggled.connect(self._on_full_shutdown_toggled)
        full_off_row.addWidget(full_off_lbl, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        full_off_row.addStretch(1)
        full_off_row.addWidget(self.full_shutdown_switch, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fields.addLayout(full_off_row)

        self._notify_section = QWidget()
        ns_l = QVBoxLayout(self._notify_section)
        ns_l.setContentsMargins(0, 8, 0, 0)
        ns_l.setSpacing(6)
        ns_h = QLabel("Напоминания о заданиях «В процессе»")
        ns_h.setObjectName("H2")
        ns_l.addWidget(ns_h)
        interval_row = QHBoxLayout()
        interval_row.setSpacing(10)
        interval_row.addWidget(QLabel("Интервал повторения:"), 0)
        self.notify_interval_spin = QSpinBox()
        self.notify_interval_spin.setRange(1, 30)
        self.notify_interval_spin.setSuffix(" дн.")
        self.notify_interval_spin.valueChanged.connect(self._on_notify_interval_changed)
        interval_row.addWidget(self.notify_interval_spin, 0)
        interval_row.addStretch(1)
        ns_l.addLayout(interval_row)
        ns_hint = QLabel(
            "Пока «Полное отключение» выключено и программа работает (в том числе в фоне), "
            "приходят уведомления Windows только по заданиям в столбце «В процессе». "
            "Для заданий без дедлайна напоминания привязаны к дате из startline (или к дате создания, если нет startline); "
            "для заданий с дедлайном сначала — в момент deadline, затем цикл от даты дедлайна."
        )
        ns_hint.setWordWrap(True)
        ns_l.addWidget(ns_hint)
        fields.addWidget(self._notify_section)
        self._sync_notify_section_visibility()

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

    def _sync_notify_section_visibility(self) -> None:
        self._notify_section.setVisible(not self.full_shutdown_switch.isChecked())

    def _sync_app_full_shutdown_flag(self) -> None:
        app = QApplication.instance()
        if app is not None:
            setattr(app, "_delta_full_shutdown_ui", bool(self.full_shutdown_switch.isChecked()))

    def _on_full_shutdown_toggled(self, checked: bool) -> None:
        prof = self.storage.get_profile()
        prof["full_shutdown"] = bool(checked)
        self.storage.save_profile(prof)
        self._sync_app_full_shutdown_flag()
        self._sync_notify_section_visibility()

    def _on_notify_interval_changed(self, value: int) -> None:
        prof = self.storage.get_profile()
        prof["task_notify_interval_days"] = max(1, min(30, int(value)))
        self.storage.save_profile(prof)

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
        self.experimental_switch.setChecked(bool(profile.get("experimental_mode", False)))
        self.full_shutdown_switch.blockSignals(True)
        self.full_shutdown_switch.setChecked(bool(profile.get("full_shutdown", True)))
        self.full_shutdown_switch.blockSignals(False)
        self._sync_app_full_shutdown_flag()
        self._sync_notify_section_visibility()
        niv = int(profile.get("task_notify_interval_days", 7) or 7)
        niv = max(1, min(30, niv))
        self.notify_interval_spin.blockSignals(True)
        self.notify_interval_spin.setValue(niv)
        self.notify_interval_spin.blockSignals(False)

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
        prev_exp = bool(profile.get("experimental_mode", False))
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

        new_exp = bool(self.experimental_switch.isChecked())
        profile["experimental_mode"] = bool(new_exp)
        profile["full_shutdown"] = bool(self.full_shutdown_switch.isChecked())
        profile["task_notify_interval_days"] = max(1, min(30, int(self.notify_interval_spin.value())))

        self.storage.save_profile(profile)
        QMessageBox.information(self, "Готово", "Профиль сохранен.")
        if prev_exp != new_exp:
            # Restart so the main navigation can be rebuilt cleanly.
            QMessageBox.information(self, "Перезапуск", "Режим изменен. Приложение сейчас перезапустится.")
            QTimer.singleShot(50, self._restart_app)

    def _restart_app(self) -> None:
        # Graceful shutdown: stop background QThreads before exec restart.
        app = QApplication.instance()
        try:
            if app is not None:
                for w in list(app.topLevelWidgets() or []):
                    # MainWindow holds BoardPage which owns background threads.
                    board = getattr(w, "board", None)
                    if board is not None and hasattr(board, "cleanup_threads"):
                        try:
                            board.cleanup_threads()
                        except Exception:
                            pass
        except Exception:
            pass
        try:
            if app is not None:
                # Bypass "background/hide instead of quit" profile mode during restart.
                setattr(app, "_delta_force_full_quit", True)
                app.closeAllWindows()
                app.processEvents()
        except Exception:
            pass
        # Start a new process first, then quit this one. This avoids Qt warnings on Windows
        # like "QThreadStorage: entry destroyed before end of thread" that can appear with os.execl.
        try:
            subprocess.Popen([sys.executable, *sys.argv], cwd=os.getcwd())
        except Exception:
            # If we couldn't spawn, fall back to exec-replace.
            try:
                os.execl(sys.executable, sys.executable, *sys.argv)
            except Exception:
                pass
        try:
            if app is not None:
                app.quit()
        except Exception:
            pass


class _ToggleSwitch(QCheckBox):
    """Simple toggle switch based on QCheckBox (no external deps)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 24)
        # A lightweight "switch" look with a sliding knob.
        self.setStyleSheet(
            "QCheckBox{background: transparent; padding:0px; margin:0px;}"
            "QCheckBox::indicator{width:46px; height:24px;}"
            "QCheckBox::indicator:unchecked{"
            "  border-radius:12px; background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.20);"
            "}"
            "QCheckBox::indicator:checked{"
            "  border-radius:12px; background: rgba(90,160,255,0.55); border: 1px solid rgba(90,160,255,0.75);"
            "}"
        )

    def paintEvent(self, event) -> None:  # type: ignore[override]
        # Default paint draws only indicator; we also draw the knob on top.
        super().paintEvent(event)
        try:
            from PySide6.QtGui import QPainter
            from PySide6.QtCore import QRect

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            r = self.rect()
            knob_d = 18
            pad = 3
            x = (r.width() - knob_d - pad) if self.isChecked() else pad
            y = int((r.height() - knob_d) / 2)
            knob = QRect(int(x), int(y), int(knob_d), int(knob_d))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.white)
            painter.drawEllipse(knob)
            painter.end()
        except Exception:
            return


def _uuid4_hex() -> str:
    import uuid as _uuid

    return _uuid.uuid4().hex

