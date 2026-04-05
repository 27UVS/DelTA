from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from html import escape
from datetime import datetime, timezone
import math

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QThread, Signal, QSize, QPoint, QRect, QMimeData
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QIcon,
    QPixmap,
    QPainter,
    QFont,
    QImage,
    QImageReader,
    QDesktopServices,
    QDrag,
    QPainterPath,
    QTextOption,
)
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QMenu,
    QFrame,
    QSizePolicy,
    QTextEdit,
)

from app.assets import get_interface_assets
from app.board_prefetch import TASK_KINDS, BoardPrefetchThread
from app.qt_icon_loader import QtIconLoader
from app.storage import Role, Storage, Status, SYSTEM_ADMIN_ROLE_ID, SYSTEM_NONE_ROLE_ID, SYSTEM_STATUS_NONE_ID, APP_TZ
from app.theme import Palette, get_palette
from app.qt_pages.person_settings_dialog import PersonSettingsDialog
from app.qt_pages.task_create_dialog import TaskCreateDialog
from app.qt_pages.task_view_dialog import TaskViewDialog
from app.qt_pages.task_subtasks_widgets import SubtaskChainCompactWidget
from app.task_subtasks import get_subtasks_from_task

try:
    import shiboken6  # type: ignore
except Exception:  # pragma: no cover
    shiboken6 = None

# Batched UI updates; small chunks + non-zero timer so the OS gets to process window messages.
_TASKS_PER_TICK = 4
_PEOPLE_PER_TICK = 1
_CHUNK_TIMER_MS = 1
_PEOPLE_AVATAR_PX = 46
_ADMIN_PERSON_ID = "__admin__"
_NEW_PERSON_ID = "__new__"


class _PersonCard(QFrame):
    def __init__(self, *, on_open, on_activate) -> None:
        super().__init__()
        self._on_open = on_open
        self._on_activate = on_activate
        self._click_pending = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # Delay single-click action to avoid triggering on double-click.
        self._click_pending = True

        def _fire():
            if not self._click_pending:
                return
            self._click_pending = False
            if callable(self._on_activate):
                self._on_activate()

        QTimer.singleShot(220, _fire)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        super().mouseDoubleClickEvent(event)
        self._click_pending = False
        if callable(self._on_open):
            self._on_open()


class _TaskCard(QFrame):
    def __init__(self, *, task_id: str, from_kind: str, on_open) -> None:
        super().__init__()
        self._task_id = str(task_id)
        self._from_kind = str(from_kind)
        self._drag_start: QPoint | None = None
        self._on_open = on_open

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint() if hasattr(event, "position") else event.pos()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        super().mouseMoveEvent(event)
        if self._drag_start is None:
            return
        cur = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if (cur - self._drag_start).manhattanLength() < 10:
            return
        self._drag_start = None

        drag = QDrag(self)
        md = QMimeData()
        md.setData("application/x-delta-task", f"{self._task_id}|{self._from_kind}".encode("utf-8"))
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        super().mouseDoubleClickEvent(event)
        if callable(self._on_open):
            self._on_open()


class _TaskCardTitleEdit(QTextEdit):
    """Read-only title: wraps at any character, height grows with text; does not force huge min width."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("TaskCardTitle")
        self.setPlainText(text)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.setTabChangesFocus(False)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("font-weight:700; background: transparent;")
        self.textChanged.connect(self._update_height)
        self._last_h = 28

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(0, self._last_h)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(0, self._last_h)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_height()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self._update_height)

    def _update_height(self) -> None:
        w = self.viewport().width()
        if w <= 0:
            w = max(0, self.width() - 8)
        if w <= 0:
            return
        doc = self.document()
        doc.setTextWidth(float(w))
        h = int(doc.size().height()) + 4
        self._last_h = max(28, h)
        self.setFixedHeight(self._last_h)


def _circle_avatar_pixmap(size: int, *, avatar_path: str | None, fallback_text: str, bg_hex: str) -> QPixmap:
    """Circle avatar: image if present, else initial on colored bg."""
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        painter.fillRect(out.rect(), QColor(bg_hex or "#3A7CFF"))
        if avatar_path and Path(avatar_path).exists():
            pix = QPixmap(str(avatar_path))
            if not pix.isNull():
                pm = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap(0, 0, pm)
                return out
        # Fallback letter
        painter.setClipping(False)
        painter.setPen(Qt.GlobalColor.white)
        f = QFont("Segoe UI", max(9, int(size * 0.42)))
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, (fallback_text or "?")[:1].upper())
    finally:
        painter.end()
    return out

def _fmt(value: str | None) -> str:
    if not value:
        return "—"
    return str(value)


def _initials(name: str) -> str:
    parts = [p for p in str(name).split() if p]
    letters = [p[0] for p in parts if p[0].isalpha()]
    return ("".join(letters)[:2].upper() or "?")


def _placeholder_avatar(size: int, initials: str, bg_hex: str) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(bg_hex))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.GlobalColor.white)
    f = QFont("Segoe UI", max(10, size // 3))
    f.setBold(True)
    painter.setFont(f)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, initials[:2])
    painter.end()
    return pix


class BackgroundImageLoader(QThread):
    loaded = Signal(object, object)  # QImage|None, key

    def __init__(self, *, path: str, target_size: QSize, key: tuple[str, str | None]) -> None:
        super().__init__()
        self._path = str(path)
        self._target_size = QSize(target_size)
        self._key = key

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            reader = QImageReader(self._path)
            reader.setAutoTransform(True)
            img = reader.read()
            if self.isInterruptionRequested():
                return
            if img.isNull():
                self.loaded.emit(None, self._key)
                return

            # Scale in the worker thread so the UI thread stays responsive.
            # We want a "cover" effect: fully fill the target rect, crop overflow.
            if self._target_size.width() > 0 and self._target_size.height() > 0:
                img = img.scaled(
                    self._target_size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if self.isInterruptionRequested():
                    return
                # Center-crop to exact target size.
                if img.width() > 0 and img.height() > 0:
                    x = max(int((img.width() - self._target_size.width()) / 2), 0)
                    y = max(int((img.height() - self._target_size.height()) / 2), 0)
                    w = min(self._target_size.width(), img.width())
                    h = min(self._target_size.height(), img.height())
                    img = img.copy(x, y, w, h)
            if not self.isInterruptionRequested():
                self.loaded.emit(img, self._key)
        except Exception:
            if not self.isInterruptionRequested():
                self.loaded.emit(None, self._key)


class BackgroundFrame(QFrame):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bg_color = QColor("#1F1F1F")
        self._bg_image: QImage | None = None

    def set_background(self, *, color: str, image: QImage | None) -> None:
        self._bg_color = QColor(str(color) or "#1F1F1F")
        self._bg_image = image
        self.update()

    def paintEvent(self, event) -> None:
        # Custom paint avoids `background-image: url(...)` in stylesheets,
        # which can block the UI thread when decoding large images.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), self._bg_color)
        img = self._bg_image
        if img is not None and not img.isNull():
            # The worker pre-crops to widget size ("cover"), so we can draw 1:1.
            painter.drawImage(self.rect(), img)
        painter.end()
        super().paintEvent(event)


class _ColumnBody(QFrame):
    """A 'window' that shows the shared board background image behind it."""

    def __init__(self, *, board_area: QWidget, get_bg_image) -> None:
        super().__init__(board_area)
        self._board_area = board_area
        self._get_bg_image = get_bg_image
        self.setObjectName("ColumnBody")

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        img: QImage | None = self._get_bg_image()
        if img is not None and not img.isNull():
            dpr = float(img.devicePixelRatio() or 1.0)
            top_left = self.mapTo(self._board_area, QPoint(0, 0))
            src = QRect(
                int(top_left.x() * dpr),
                int(top_left.y() * dpr),
                int(self.width() * dpr),
                int(self.height() * dpr),
            )
            painter.drawImage(self.rect(), img, src)
        painter.end()
        super().paintEvent(event)


class _TaskDropBody(_ColumnBody):
    def __init__(self, *, board_area: QWidget, get_bg_image, kind: str, on_drop) -> None:
        super().__init__(board_area=board_area, get_bg_image=get_bg_image)
        self._kind = str(kind)
        self._on_drop = on_drop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        md = event.mimeData()
        if md and md.hasFormat("application/x-delta-task"):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        md = event.mimeData()
        if not md or not md.hasFormat("application/x-delta-task"):
            return
        raw = bytes(md.data("application/x-delta-task")).decode("utf-8", errors="ignore")
        # format: task_id|from_kind
        parts = raw.split("|", 1)
        if len(parts) != 2:
            return
        task_id, from_kind = parts[0], parts[1]
        if callable(self._on_drop):
            self._on_drop(task_id, from_kind, self._kind)
        event.acceptProposedAction()


@dataclass(frozen=True)
class TaskColumn:
    kind: str
    title: str


class BoardPage(QWidget):
    """
    Qt port of the main board: people panel + 4 task columns.
    """

    def __init__(self, storage: Storage, on_open_admin=None):
        super().__init__()
        self.storage = storage
        self.on_open_admin = on_open_admin
        self._icons = QtIconLoader()
        self._assets = get_interface_assets()
        self._arrow_open_path = self._assets.interface_dir / "icon-arrow-5176734.png"
        self._arrow_close_path = self._assets.interface_dir / "icon-arrow-5176969.png"

        self._people_target_w = 380
        self._anim: QPropertyAnimation | None = None
        self._bg_path: str | None = None
        self._bg_css: str | None = None
        self._bg_applied_css: str | None = None
        self._bg_key: tuple[str, str | None] | None = None
        self._bg_loader: BackgroundImageLoader | None = None
        self._bg_image: QImage | None = None
        self._bg_load_key: tuple[str, str | None, int, int] | None = None
        self._bg_restart_apply_after_load: bool = False
        self._bg_resize_timer = QTimer(self)
        self._bg_resize_timer.setSingleShot(True)
        self._bg_resize_timer.setInterval(80)
        self._bg_resize_timer.timeout.connect(self._apply_background)
        self._column_bodies: list[_ColumnBody] = []
        self._person_avatar_by_id: dict[str, str | None] = {}
        self._person_name_by_id: dict[str, str] = {}
        self._person_color_by_id: dict[str, str] = {}
        self._avatar_cache: dict[str, QPixmap] = {}
        self._refresh_gen: int = 0
        self._pending_tasks: deque[tuple[str, dict]] = deque()
        self._pending_subj_name: dict[str, str] = {}
        self._people_rows: deque[tuple[str, str, str, str | None]] = deque()
        self._people_palette: Palette | None = None
        self._people_filter_role_ids: set[str] = set()
        self._people_filter_status_ids: set[str] = set()
        # People panel: task count — None | "zero" | "nonzero"; sort — None | "desc" | "asc"
        self._people_filter_task_count: str | None = None
        self._people_sort_tasks: str | None = None
        self._task_filter_resp_ids_by_kind: dict[str, set[str]] = {k: set() for k in TASK_KINDS}
        self._task_filter_time_mode_by_kind: dict[str, str | None] = {k: None for k in TASK_KINDS}
        self._prefetch_thread: BoardPrefetchThread | None = None
        self._prefetch_snapshot: dict | None = None
        self._last_seen_storage_rev: int = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Container for manual overlay layout.
        self.container = QFrame()
        self.container.setObjectName("BoardContainer")
        root.addWidget(self.container, 1)

        # People panel (collapsible overlay).
        self.people_panel = QFrame(self.container)
        self.people_panel.setObjectName("PeoplePanel")
        self.people_panel.setMaximumWidth(0)
        self.people_panel.setMinimumWidth(0)
        self.people_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        people_layout = QVBoxLayout(self.people_panel)
        people_layout.setContentsMargins(14, 14, 14, 14)
        people_layout.setSpacing(10)

        header = QHBoxLayout()
        lbl = QLabel("Люди")
        lbl.setObjectName("H2")
        header.addWidget(lbl)
        self.filter_people_btn = QPushButton("")
        self.filter_people_btn.setToolTip("Фильтр людей")
        fpm = self._icons.load_pixmap(self._assets.filter_button_png, (18, 18))
        if fpm is not None:
            self.filter_people_btn.setIcon(QIcon(fpm))
        self.filter_people_btn.setFixedSize(34, 28)
        self.filter_people_btn.setIconSize(QSize(18, 18))
        self.filter_people_btn.clicked.connect(self._open_people_filter_menu)
        header.addWidget(self.filter_people_btn, 0)
        header.addStretch(1)
        self.add_person_btn = QPushButton("")
        self.add_person_btn.setToolTip("Добавить человека")
        add_pix = self._icons.load_pixmap(self._assets.add_button_png, (20, 20))
        if add_pix is not None:
            self.add_person_btn.setIcon(QIcon(add_pix))
        self.add_person_btn.setFixedSize(36, 30)
        self.add_person_btn.clicked.connect(self._on_add_person)
        header.addWidget(self.add_person_btn)
        self.pin_btn = QPushButton("Закрепить")
        self.pin_btn.setCheckable(True)
        self.pin_btn.clicked.connect(self._on_pin_toggle)
        header.addWidget(self.pin_btn)
        people_layout.addLayout(header)

        self.people_scroll = QScrollArea()
        self.people_scroll.setWidgetResizable(True)
        self.people_list = QWidget()
        self.people_list_l = QVBoxLayout(self.people_list)
        self.people_list_l.setContentsMargins(0, 0, 0, 0)
        self.people_list_l.setSpacing(10)
        self.people_list_l.addStretch(1)
        self.people_scroll.setWidget(self.people_list)
        people_layout.addWidget(self.people_scroll, 1)

        # Board area (background lives here).
        self.board_area = BackgroundFrame(self.container)
        board_l = QVBoxLayout(self.board_area)
        board_l.setContentsMargins(0, 0, 0, 0)
        board_l.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(14, 12, 14, 0)
        title = QLabel("Доска задач")
        title.setObjectName("H1")
        top.addWidget(title)
        top.addStretch(1)
        self.admin_btn = QPushButton("")
        self.admin_btn.setToolTip("Администрирование")
        pix = self._icons.load_pixmap(self._assets.settings_default_png, (24, 24))
        if pix is not None:
            self.admin_btn.setIcon(pix)
        self.admin_btn.clicked.connect(self._open_admin)
        self.admin_btn.setFixedSize(40, 34)
        top.addWidget(self.admin_btn)
        board_l.addLayout(top)

        # Main content row: (pinned people panel) + columns.
        self.content_row = QFrame(self.board_area)
        self.content_row.setObjectName("ContentRow")
        content_l = QHBoxLayout(self.content_row)
        content_l.setContentsMargins(14, 12, 14, 14)
        content_l.setSpacing(12)
        self._content_l = content_l

        self.columns_inner = QWidget()
        self.columns_l = QHBoxLayout(self.columns_inner)
        self.columns_l.setContentsMargins(0, 0, 0, 0)
        self.columns_l.setSpacing(12)

        self._columns: dict[str, QVBoxLayout] = {}
        self._column_frames: list[QFrame] = []
        for col in [
            TaskColumn("draft", "Черновик"),
            TaskColumn("progress", "В процессе"),
            TaskColumn("finished", "Завершено"),
            TaskColumn("delayed", "Отложено"),
        ]:
            col_card = QFrame()
            col_card.setObjectName("ColumnCard")
            col_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            col_l = QVBoxLayout(col_card)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(0)

            header = QFrame()
            header.setObjectName("ColumnHeader")
            header_l = QHBoxLayout(header)
            header_l.setContentsMargins(12, 10, 12, 10)
            header_l.setSpacing(6)
            h = QLabel(col.title)
            h.setObjectName("ColumnTitle")
            header_l.addWidget(h)
            header_l.addStretch(1)
            filter_btn = QPushButton("")
            filter_btn.setToolTip("Фильтр задач")
            fpm = self._icons.load_pixmap(self._assets.filter_button_png, (18, 18))
            if fpm is not None:
                filter_btn.setIcon(QIcon(fpm))
            filter_btn.setFixedSize(34, 28)
            filter_btn.setIconSize(QSize(18, 18))
            filter_btn.clicked.connect(lambda _=False, k=col.kind, b=filter_btn: self._open_task_filter_menu(k, b))
            header_l.addWidget(filter_btn, 0)
            edit_btn = QPushButton("")
            edit_btn.setToolTip("Редактировать")
            edit_pix = self._icons.load_pixmap(self._assets.edit_button_png, (18, 18))
            if edit_pix is not None:
                edit_btn.setIcon(edit_pix)
            edit_btn.setFixedSize(34, 28)
            edit_btn.setIconSize(QSize(18, 18))
            edit_btn.clicked.connect(lambda _=False, k=col.kind: self._open_create_task(k))
            header_l.addWidget(edit_btn, 0)
            col_l.addWidget(header, 0)

            body_scroll = QScrollArea()
            body_scroll.setWidgetResizable(True)
            body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            body_scroll.setFrameShape(QFrame.Shape.NoFrame)
            body = _TaskDropBody(
                board_area=self.board_area,
                get_bg_image=lambda: self._bg_image,
                kind=col.kind,
                on_drop=self._on_task_dropped,
            )
            self._column_bodies.append(body)
            body_l = QVBoxLayout(body)
            body_l.setContentsMargins(10, 10, 10, 10)
            body_l.setSpacing(10)
            body_l.addStretch(1)
            body_scroll.setWidget(body)
            col_l.addWidget(body_scroll, 1)

            self._columns[col.kind] = body_l
            self._column_frames.append(col_card)
            self.columns_l.addWidget(col_card, 1)

        content_l.addWidget(self.columns_inner, 1)
        board_l.addWidget(self.content_row, 1)

        # Left-side arrow to open/close people panel.
        self.people_arrow_btn = QPushButton("")
        self.people_arrow_btn.setObjectName("PeopleArrow")
        self.people_arrow_btn.setFixedSize(30, 72)
        self.people_arrow_btn.clicked.connect(self.toggle_people_panel)
        self.people_arrow_btn.setParent(self.container)
        self.people_arrow_btn.raise_()
        self.people_arrow_btn.setIconSize(QSize(24, 24))
        # Brighter "hump" button attached to the panel edge (rounded on the outside only).
        self.people_arrow_btn.setStyleSheet(
            "QPushButton{background: rgba(255,255,255,0.40); border: 1px solid rgba(255,255,255,0.26);"
            "border-left: none; border-top-left-radius: 0px; border-bottom-left-radius: 0px;"
            "border-top-right-radius: 18px; border-bottom-right-radius: 18px;}"
            "QPushButton:hover{background: rgba(255,255,255,0.52); border-color: rgba(255,255,255,0.32);}"
            "QPushButton:pressed{background: rgba(255,255,255,0.62);}"
        )
        self._set_people_arrow_icon(0)

    # --- Public API (kept similar to tkinter version) ---
    def refresh_after_theme_change(self) -> None:
        ui = self.storage.get_ui_settings()
        self.pin_btn.setChecked(bool(ui.get("people_panel_pinned", False)))
        self._update_pin_button_text()
        open_ = bool(ui.get("people_panel_open", False)) or self.pin_btn.isChecked()
        self._set_people_panel_width(self._people_target_w if open_ else 0, animate=False)
        self._apply_pinned_mode_layout()
        self._update_people_arrow()
        self._layout_overlay()
        self._apply_background()

    def refresh_from_storage(self, *, force: bool = False) -> None:
        """Reload board: JSON is read off the UI thread; widgets are built in small batches."""
        if not force and self._last_seen_storage_rev == self.storage.rev:
            # Data hasn't changed; keep it lightweight.
            self._update_pin_button_text()
            self._apply_pinned_mode_layout()
            self._update_people_arrow()
            self._layout_overlay()
            self._apply_background()
            return
        self._refresh_gen += 1
        gen = self._refresh_gen
        self._prefetch_snapshot = None

        self._update_pin_button_text()
        self._apply_pinned_mode_layout()
        self._update_people_arrow()
        self._layout_overlay()
        self._apply_background()

        self._start_prefetch_thread(gen)

    def refresh_from_storage_async(self) -> None:
        self.refresh_from_storage()

    def _start_prefetch_thread(self, gen: int) -> None:
        if gen != self._refresh_gen:
            return
        thread = BoardPrefetchThread(self.storage.paths)
        self._prefetch_thread = thread
        thread.loaded.connect(lambda d, g=gen: self._on_prefetch_loaded(d, g))
        thread.failed.connect(lambda e, g=gen: self._on_prefetch_failed(g, e))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _warm_storage_from_prefetch(self, data: dict) -> None:
        paths = self.storage.paths
        for kind in TASK_KINDS:
            p = {
                "draft": paths.tasks_draft_path,
                "progress": paths.tasks_progress_path,
                "finished": paths.tasks_finished_path,
                "delayed": paths.tasks_delayed_path,
            }[kind]
            self.storage.warm_cache(p, {"tasks": data["tasks_by_kind"][kind]})
        self.storage.warm_cache(paths.subjects_path, {"subjects": data["subjects"]})
        self.storage.warm_cache(paths.profile_path, data["profile"])
        self.storage.warm_cache(paths.roles_path, data["roles_doc"])
        if "statuses_doc" in data:
            self.storage.warm_cache(paths.statuses_path, data["statuses_doc"])
        if "people_settings_doc" in data:
            self.storage.warm_cache(paths.people_settings_path, data["people_settings_doc"])

    def _on_prefetch_loaded(self, data: dict, gen: int) -> None:
        if gen != self._refresh_gen:
            return
        self._prefetch_thread = None
        # Mark data as up-to-date for change detection.
        self._last_seen_storage_rev = self.storage.rev
        self._warm_storage_from_prefetch(data)
        self._prefetch_snapshot = {
            "profile": copy.deepcopy(data["profile"]),
            "subjects": copy.deepcopy(data["subjects"]),
            "roles_doc": copy.deepcopy(data["roles_doc"]),
            "statuses_doc": copy.deepcopy(data.get("statuses_doc") or {"statuses": []}),
            "people_settings_doc": copy.deepcopy(data.get("people_settings_doc") or {"people": {}}),
        }
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        prof_avatar = profile.get("avatar_path") if isinstance(profile, dict) else None
        prof_name = str(profile.get("nickname", "Администратор")) if isinstance(profile, dict) else "Администратор"
        self._person_avatar_by_id = {_ADMIN_PERSON_ID: str(prof_avatar) if prof_avatar else None}
        self._person_name_by_id = {_ADMIN_PERSON_ID: prof_name}

        # Build roles map for per-person color (best role = minimal priority).
        roles_map: dict[str, Role] = {}
        for r in (data.get("roles_doc") or {}).get("roles", []) if isinstance(data.get("roles_doc"), dict) else []:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("id"))
            roles_map[rid] = Role(
                id=rid,
                name=str(r.get("name")),
                color=str(r.get("color", "#BDBDBD")),
                priority=int(r.get("priority", 9999)),
                locked=bool(r.get("locked", False)),
            )
        admin_role = roles_map.get(SYSTEM_ADMIN_ROLE_ID)
        self._person_color_by_id = {_ADMIN_PERSON_ID: (admin_role.color if admin_role else "#3A7CFF")}
        for s in data.get("subjects", []) or []:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "")
            if sid:
                self._person_avatar_by_id[sid] = str(s.get("avatar_path") or "") or None
                self._person_name_by_id[sid] = str(s.get("nickname") or "")
                # best role color
                role_ids = [str(rid) for rid in (s.get("role_ids") or []) if rid not in (SYSTEM_NONE_ROLE_ID,)]
                role_objs = [roles_map[rid] for rid in role_ids if rid in roles_map]
                role_objs = sorted(role_objs, key=lambda rr: (rr.priority, rr.name.lower()))
                self._person_color_by_id[sid] = (role_objs[0].color if role_objs else "#3A7CFF")

        # Used by task cards (id -> nickname). Include admin too.
        self._pending_subj_name = {_ADMIN_PERSON_ID: prof_name}
        self._pending_subj_name.update({str(s.get("id")): str(s.get("nickname")) for s in data["subjects"]})
        for layout in self._columns.values():
            self._clear_layout_items(layout)
        self._pending_tasks.clear()
        for kind in TASK_KINDS:
            for t in reversed(data["tasks_by_kind"][kind]):
                self._pending_tasks.append((kind, t))
        QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._process_tasks_chunk, gen))

    def _on_prefetch_failed(self, gen: int, _err: str = "") -> None:
        if gen != self._refresh_gen:
            return
        self._prefetch_thread = None
        self._prefetch_snapshot = None
        # We attempted a refresh; treat revision as seen to prevent loops, but we will rebuild from Storage below.
        self._last_seen_storage_rev = self.storage.rev
        subjects = self.storage.get_subjects()
        self._pending_subj_name = {str(s.get("id")): str(s.get("nickname")) for s in subjects}
        for layout in self._columns.values():
            self._clear_layout_items(layout)
        self._pending_tasks.clear()
        for kind in TASK_KINDS:
            for t in reversed(self.storage.load_tasks(kind)):
                self._pending_tasks.append((kind, t))
        QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._process_tasks_chunk, gen))

    # --- Internals ---
    def _process_tasks_chunk(self, gen: int) -> None:
        if gen != self._refresh_gen:
            return
        subj_name = self._pending_subj_name
        for _ in range(_TASKS_PER_TICK):
            if not self._pending_tasks:
                QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._start_people_refresh, gen))
                return
            kind, task = self._pending_tasks.popleft()
            if not self._task_passes_filters(kind, task):
                continue
            layout = self._columns[kind]
            layout.insertWidget(layout.count() - 1, self._task_card(kind, task, subj_name))
        QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._process_tasks_chunk, gen))

    def _start_people_refresh(self, gen: int) -> None:
        if gen != self._refresh_gen:
            return
        self._clear_layout_items(self.people_list_l)
        snap = self._prefetch_snapshot
        if snap is not None:
            profile = snap["profile"]
            subjects = snap["subjects"]
            roles: dict[str, Role] = {}
            for r in snap["roles_doc"].get("roles", []):
                if not isinstance(r, dict):
                    continue
                rid = str(r.get("id"))
                roles[rid] = Role(
                    id=rid,
                    name=str(r.get("name")),
                    color=str(r.get("color", "#BDBDBD")),
                    priority=int(r.get("priority", 9999)),
                    locked=bool(r.get("locked", False)),
                )
            theme = self.storage.get_ui_settings().get("theme", "dark")
            p = get_palette(theme)
            statuses: dict[str, Status] = {}
            for st in (snap.get("statuses_doc") or {}).get("statuses", []) or []:
                if not isinstance(st, dict):
                    continue
                sid = str(st.get("id"))
                statuses[sid] = Status(
                    id=sid,
                    name=str(st.get("name")),
                    color=str(st.get("color", "#9E9E9E" if sid == SYSTEM_STATUS_NONE_ID else "#4CAF50")),
                    locked=bool(st.get("locked", False)),
                )
        else:
            profile = self.storage.get_profile()
            subjects = self.storage.get_subjects()
            roles = {r.id: r for r in self.storage.get_roles()}
            statuses = {s.id: s for s in self.storage.get_statuses()}
            theme = self.storage.get_ui_settings().get("theme", "dark")
            p = get_palette(theme)

        rows: list[tuple[str, str, list[tuple[str, str]], list[str], str | None, str, str, str, int]] = []
        admin_name = str(profile.get("nickname", "Администратор"))
        admin_role_ids = [str(rid) for rid in (profile.get("role_ids") or []) if rid not in (SYSTEM_NONE_ROLE_ID,)]
        # Ensure Admin role is always present for the admin profile card.
        if SYSTEM_ADMIN_ROLE_ID not in admin_role_ids:
            admin_role_ids = [SYSTEM_ADMIN_ROLE_ID] + admin_role_ids
        admin_role_objs = [roles[rid] for rid in admin_role_ids if rid in roles]
        admin_role_objs = sorted(admin_role_objs, key=lambda rr: (rr.priority, rr.name.lower()))
        if admin_role_objs:
            admin_role_parts = [(rr.name, rr.color or p.muted_fg) for rr in admin_role_objs]
        else:
            admin_role_parts = [("Администратор", p.muted_fg)]

        # Admin status comes from people_settings (separate from profile links).
        admin_st_id = SYSTEM_STATUS_NONE_ID
        try:
            if snap:
                ps = (snap.get("people_settings_doc") or {}).get("people", {}).get(_ADMIN_PERSON_ID, {})
                if isinstance(ps, dict):
                    admin_st_id = str(ps.get("admin_status_id") or SYSTEM_STATUS_NONE_ID)
            else:
                ps = self.storage.get_person_settings(_ADMIN_PERSON_ID)
                if isinstance(ps, dict):
                    admin_st_id = str(ps.get("admin_status_id") or SYSTEM_STATUS_NONE_ID)
        except Exception:
            admin_st_id = SYSTEM_STATUS_NONE_ID
        admin_st = statuses.get(admin_st_id) or statuses.get(SYSTEM_STATUS_NONE_ID)
        admin_status_name = admin_st.name if admin_st else "Без статуса"
        admin_status_color = (admin_st.color if admin_st else "#9E9E9E") or "#9E9E9E"
        def _passes_filters(role_ids: list[str], status_id: str) -> bool:
            if self._people_filter_role_ids:
                if not any(rid in self._people_filter_role_ids for rid in role_ids):
                    return False
            if self._people_filter_status_ids:
                if str(status_id) not in self._people_filter_status_ids:
                    return False
            return True

        admin_tasks_cnt = self.storage.compute_active_tasks_count_for_subject(_ADMIN_PERSON_ID)
        if _passes_filters(admin_role_ids, str(admin_st_id)):
            rows.append(
                (
                    _ADMIN_PERSON_ID,
                    admin_name,
                    admin_role_parts,
                    admin_role_ids,
                    profile.get("avatar_path"),
                    admin_status_name,
                    admin_status_color,
                    str(admin_st_id),
                    int(admin_tasks_cnt),
                )
            )

        def _subject_sort_key(subj: dict) -> tuple[int, str]:
            # Sort by the best (highest importance) role: minimal priority number.
            role_ids = [str(rid) for rid in (subj.get("role_ids") or []) if rid not in (SYSTEM_NONE_ROLE_ID,)]
            prios = []
            for rid in role_ids:
                rr = roles.get(rid)
                if rr is not None:
                    prios.append(int(rr.priority))
            best_pr = min(prios) if prios else 99999
            nick = str(subj.get("nickname", "")).lower()
            return best_pr, nick

        for s in sorted(subjects, key=_subject_sort_key):
            sid = str(s.get("id") or "")
            nickname = str(s.get("nickname", ""))
            role_ids = [str(rid) for rid in (s.get("role_ids") or []) if rid not in (SYSTEM_NONE_ROLE_ID,)]
            role_objs = [roles[rid] for rid in role_ids if rid in roles]
            role_objs = sorted(role_objs, key=lambda rr: (rr.priority, rr.name.lower()))
            if role_objs:
                role_parts = [(rr.name, rr.color or p.muted_fg) for rr in role_objs]
            else:
                role_parts = [("Без роли", p.muted_fg)]

            # Backward compat: older saves may use "status" instead of "status_id".
            status_id = str(s.get("status_id") or s.get("status") or SYSTEM_STATUS_NONE_ID)
            st = statuses.get(status_id) or statuses.get(SYSTEM_STATUS_NONE_ID)
            status_name = st.name if st else "Без статуса"
            status_color = (st.color if st else "#9E9E9E") or "#9E9E9E"
            tasks_cnt = self.storage.compute_active_tasks_count_for_subject(sid) if sid else 0
            if _passes_filters(role_ids, status_id):
                rows.append(
                    (
                        sid,
                        nickname,
                        role_parts,
                        role_ids,
                        s.get("avatar_path"),
                        status_name,
                        status_color,
                        status_id,
                    int(tasks_cnt),
                )
            )

        if self._people_filter_task_count == "zero":
            rows = [r for r in rows if r[-1] == 0]
        elif self._people_filter_task_count == "nonzero":
            rows = [r for r in rows if r[-1] > 0]

        if self._people_sort_tasks == "desc":
            rows.sort(key=lambda r: (-r[-1], r[1].lower()))
        elif self._people_sort_tasks == "asc":
            rows.sort(key=lambda r: (r[-1], r[1].lower()))

        self._people_rows = deque(rows)
        self._people_palette = p
        QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._process_people_chunk, gen))

    def _process_people_chunk(self, gen: int) -> None:
        if gen != self._refresh_gen:
            return
        p = self._people_palette
        if p is None:
            return
        for _ in range(_PEOPLE_PER_TICK):
            if not self._people_rows:
                self._people_palette = None
                QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._finalize_cooperative_refresh, gen))
                return
            pid, name, role_parts, _role_ids, avatar_path, status_name, status_color, _status_id, tasks_cnt = self._people_rows.popleft()
            self._add_person_card(pid, name, role_parts, avatar_path, status_name, status_color, tasks_cnt, p)
        QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._process_people_chunk, gen))

    def _open_people_filter_menu(self) -> None:
        """Popup menu with multi-select filters (roles + statuses)."""
        menu = QMenu(self)

        clear_act = QAction("Без фильтра", menu)
        clear_act.triggered.connect(self._clear_people_filters)
        menu.addAction(clear_act)
        menu.addSeparator()

        # Roles submenu
        roles_menu = menu.addMenu("Роли")
        roles = sorted(self.storage.get_roles(), key=lambda r: (r.priority, r.name.lower()))
        roles = [r for r in roles if r.id not in (SYSTEM_NONE_ROLE_ID,)]
        for r in roles:
            a = QAction(r.name, roles_menu)
            a.setCheckable(True)
            a.setChecked(str(r.id) in self._people_filter_role_ids)
            a.toggled.connect(lambda checked, rid=str(r.id): self._toggle_people_role_filter(rid, checked))
            roles_menu.addAction(a)

        # Statuses submenu
        st_menu = menu.addMenu("Статусы")
        statuses = sorted(self.storage.get_statuses(), key=lambda s: s.name.lower())
        for st in statuses:
            a = QAction(st.name, st_menu)
            a.setCheckable(True)
            a.setChecked(str(st.id) in self._people_filter_status_ids)
            a.toggled.connect(lambda checked, sid=str(st.id): self._toggle_people_status_filter(sid, checked))
            st_menu.addAction(a)

        menu.addSeparator()
        tasks_menu = menu.addMenu("Задачи")
        # QActionGroup must not be parented on the submenu QMenu — on Windows the nested
        # menu can fail to open. Parent on the root menu; actions stay on tasks_menu.
        sort_group = QActionGroup(menu)
        sort_group.setExclusive(True)
        a_sort_roles = QAction("Стандартный порядок", tasks_menu)
        a_sort_roles.setCheckable(True)
        sort_group.addAction(a_sort_roles)
        a_sort_roles.setChecked(self._people_sort_tasks is None)
        a_sort_roles.toggled.connect(partial(self._on_people_sort_tasks_toggled, None))
        tasks_menu.addAction(a_sort_roles)

        a_sort_most = QAction("С большим числом", tasks_menu)
        a_sort_most.setCheckable(True)
        sort_group.addAction(a_sort_most)
        a_sort_most.setChecked(self._people_sort_tasks == "desc")
        a_sort_most.toggled.connect(partial(self._on_people_sort_tasks_toggled, "desc"))
        tasks_menu.addAction(a_sort_most)

        a_sort_least = QAction("С наименьшим числом", tasks_menu)
        a_sort_least.setCheckable(True)
        sort_group.addAction(a_sort_least)
        a_sort_least.setChecked(self._people_sort_tasks == "asc")
        a_sort_least.toggled.connect(partial(self._on_people_sort_tasks_toggled, "asc"))
        tasks_menu.addAction(a_sort_least)

        tasks_menu.addSeparator()

        vis_group = QActionGroup(menu)
        vis_group.setExclusive(True)
        a_vis_all = QAction("Все", tasks_menu)
        a_vis_all.setCheckable(True)
        vis_group.addAction(a_vis_all)
        a_vis_all.setChecked(self._people_filter_task_count is None)
        a_vis_all.toggled.connect(partial(self._on_people_task_count_filter_toggled, None))
        tasks_menu.addAction(a_vis_all)

        a_vis_none = QAction("Нет задач", tasks_menu)
        a_vis_none.setCheckable(True)
        vis_group.addAction(a_vis_none)
        a_vis_none.setChecked(self._people_filter_task_count == "zero")
        a_vis_none.toggled.connect(partial(self._on_people_task_count_filter_toggled, "zero"))
        tasks_menu.addAction(a_vis_none)

        a_vis_some = QAction("Есть задачи", tasks_menu)
        a_vis_some.setCheckable(True)
        vis_group.addAction(a_vis_some)
        a_vis_some.setChecked(self._people_filter_task_count == "nonzero")
        a_vis_some.toggled.connect(partial(self._on_people_task_count_filter_toggled, "nonzero"))
        tasks_menu.addAction(a_vis_some)

        menu.exec(self.filter_people_btn.mapToGlobal(QPoint(0, self.filter_people_btn.height())))

    def _toggle_people_role_filter(self, role_id: str, checked: bool) -> None:
        rid = str(role_id)
        if checked:
            self._people_filter_role_ids.add(rid)
        else:
            self._people_filter_role_ids.discard(rid)
        self._refresh_people_after_filter_change()

    def _toggle_people_status_filter(self, status_id: str, checked: bool) -> None:
        sid = str(status_id)
        if checked:
            self._people_filter_status_ids.add(sid)
        else:
            self._people_filter_status_ids.discard(sid)
        self._refresh_people_after_filter_change()

    def _clear_people_filters(self) -> None:
        self._people_filter_role_ids.clear()
        self._people_filter_status_ids.clear()
        self._people_filter_task_count = None
        self._people_sort_tasks = None
        self._refresh_people_after_filter_change()

    def _on_people_sort_tasks_toggled(self, mode: str | None, checked: bool) -> None:
        if not checked:
            return
        if self._people_sort_tasks == mode:
            return
        self._people_sort_tasks = mode
        self._refresh_people_after_filter_change()

    def _on_people_task_count_filter_toggled(self, mode: str | None, checked: bool) -> None:
        if not checked:
            return
        if self._people_filter_task_count == mode:
            return
        self._people_filter_task_count = mode
        self._refresh_people_after_filter_change()

    def _refresh_people_after_filter_change(self) -> None:
        # Stop any in-flight cooperative refresh by bumping generation.
        self._refresh_gen += 1
        gen = self._refresh_gen
        self._people_palette = None
        self._people_rows.clear()
        self._prefetch_snapshot = None
        self._clear_layout_items(self.people_list_l)
        # Rebuild people list from storage (fast) with current filters.
        QTimer.singleShot(0, partial(self._start_people_refresh, gen))

    # ---------------- Tasks filters ----------------
    def _open_task_filter_menu(self, kind: str, anchor_btn: QPushButton) -> None:
        kind = str(kind)
        menu = QMenu(self)

        clear_act = QAction("Без фильтра", menu)
        clear_act.triggered.connect(lambda: self._clear_task_filters(kind))
        menu.addAction(clear_act)
        menu.addSeparator()

        # Responsibles submenu (multi-select)
        resp_menu = menu.addMenu("Ответственные")
        profile = self.storage.get_profile()
        admin_name = str(profile.get("nickname", "Администратор"))
        people: list[tuple[str, str]] = [(_ADMIN_PERSON_ID, admin_name)]
        for s in self.storage.get_subjects():
            sid = str(s.get("id") or "")
            if not sid:
                continue
            people.append((sid, str(s.get("nickname") or "")))
        people = sorted(people, key=lambda x: (0 if x[0] == _ADMIN_PERSON_ID else 1, x[1].lower()))

        selected_resp = self._task_filter_resp_ids_by_kind.get(kind, set())
        for pid, name in people:
            a = QAction(name or "—", resp_menu)
            a.setCheckable(True)
            a.setChecked(str(pid) in selected_resp)
            a.toggled.connect(lambda checked, k=kind, p=str(pid): self._toggle_task_resp_filter(k, p, checked))
            resp_menu.addAction(a)

        # Time-type submenu (single-select). Not available for "finished".
        time_menu = menu.addMenu("Тип по времени")
        time_menu.setEnabled(kind != "finished")
        group = QActionGroup(time_menu)
        group.setExclusive(True)

        def _add_time(label: str, mode: str | None) -> None:
            act = QAction(label, time_menu)
            act.setCheckable(True)
            act.setData(mode)
            cur = self._task_filter_time_mode_by_kind.get(kind)
            act.setChecked(cur == mode)
            group.addAction(act)
            time_menu.addAction(act)

        _add_time("Любой", None)
        _add_time("Актуальные задачи", "actual")
        _add_time("Запланированные задачи", "planned")
        _add_time("Просроченные задачи", "overdue")
        _add_time("Недавние задачи (≤ 21 дн.)", "recent")
        _add_time("Длительные задачи (> 21 дн.)", "long")
        _add_time("Постоянные задачи", "permanent")

        def _on_time_triggered(act: QAction) -> None:
            mode = act.data()
            self._set_task_time_filter(kind, None if mode in (None, "None") else str(mode))

        group.triggered.connect(_on_time_triggered)

        menu.exec(anchor_btn.mapToGlobal(QPoint(0, anchor_btn.height())))

    def _toggle_task_resp_filter(self, kind: str, person_id: str, checked: bool) -> None:
        k = str(kind)
        pid = str(person_id)
        s = self._task_filter_resp_ids_by_kind.setdefault(k, set())
        if checked:
            s.add(pid)
        else:
            s.discard(pid)
        self._refresh_tasks_after_filter_change()

    def _set_task_time_filter(self, kind: str, mode: str | None) -> None:
        k = str(kind)
        if k == "finished":
            self._task_filter_time_mode_by_kind[k] = None
        else:
            self._task_filter_time_mode_by_kind[k] = (str(mode) if mode else None)
        self._refresh_tasks_after_filter_change()

    def _clear_task_filters(self, kind: str) -> None:
        k = str(kind)
        self._task_filter_resp_ids_by_kind.setdefault(k, set()).clear()
        self._task_filter_time_mode_by_kind[k] = None
        self._refresh_tasks_after_filter_change()

    def _refresh_tasks_after_filter_change(self) -> None:
        # Rebuild only task cards (avoid expensive prefetch thread).
        self._refresh_gen += 1
        gen = self._refresh_gen
        for layout in self._columns.values():
            self._clear_layout_items(layout)
        self._pending_tasks.clear()

        # Name map for task cards (admin + subjects)
        profile = self.storage.get_profile()
        prof_name = str(profile.get("nickname", "Администратор"))
        subj = self.storage.get_subjects()
        self._pending_subj_name = {_ADMIN_PERSON_ID: prof_name}
        self._pending_subj_name.update({str(s.get("id")): str(s.get("nickname")) for s in subj})

        for kind in TASK_KINDS:
            for t in reversed(self.storage.load_tasks(kind)):
                if self._task_passes_filters(kind, t):
                    self._pending_tasks.append((kind, t))
        QTimer.singleShot(_CHUNK_TIMER_MS, partial(self._process_tasks_chunk, gen))

    def _task_passes_filters(self, kind: str, task: dict) -> bool:
        k = str(kind)
        t = task if isinstance(task, dict) else {}
        # Responsible filter
        selected = self._task_filter_resp_ids_by_kind.get(k) or set()
        if selected:
            ids = [str(x) for x in (t.get("responsible_subject_ids") or []) if x]
            if not ids:
                rid = str(t.get("responsible_subject_id") or "")
                ids = [rid] if rid else []
            if not any(pid in selected for pid in ids):
                return False

        # Time filter (disabled for finished)
        mode = None if k == "finished" else (self._task_filter_time_mode_by_kind.get(k) or None)
        if not mode:
            return True

        no_deadline = bool(t.get("no_deadline", False))
        start_due = str(t.get("start_due") or "").strip() or None
        end_due = str(t.get("end_due") or "").strip() or None
        recurring = bool(t.get("recurring", False)) or (not start_due and not end_due)
        if recurring:
            return mode == "permanent"

        def _parse(s: str | None):
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(str(s))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=APP_TZ)
                return dt.astimezone(APP_TZ)
            except Exception:
                return None

        now = datetime.now(APP_TZ)
        sd = _parse(start_due)
        ed = _parse(end_due) if (end_due and not no_deadline) else None

        has_both = (sd is not None) and (ed is not None)
        has_only_start = (sd is not None) and (ed is None)

        if mode == "actual":
            return bool(has_both and sd <= now <= ed)
        if mode == "planned":
            return bool(has_both and sd > now)
        if mode == "overdue":
            return bool(has_both and ed < now)
        if mode == "recent":
            if not has_only_start:
                return False
            if sd > now:
                return False
            days = (now - sd).total_seconds() / 86400.0
            return days <= 21.0
        if mode == "long":
            if not has_only_start:
                return False
            if sd > now:
                return False
            days = (now - sd).total_seconds() / 86400.0
            return days > 21.0
        if mode == "permanent":
            return False
        return True

    def _finalize_cooperative_refresh(self, gen: int) -> None:
        if gen != self._refresh_gen:
            return
        self._prefetch_snapshot = None
        self._update_people_arrow()
        self._layout_overlay()

    def _add_person_card(
        self,
        person_id: str,
        name: str,
        role_parts: list[tuple[str, str]],
        avatar_path: str | None,
        status_name: str,
        status_color: str,
        tasks_cnt: int,
        p: Palette,
    ) -> None:
        card = _PersonCard(
            on_open=lambda pid=str(person_id): self._open_person_settings(pid),
            on_activate=lambda pid=str(person_id): self._open_preferred_link(pid),
        )
        card.setObjectName("Card")
        card_l = QHBoxLayout(card)
        card_l.setContentsMargins(14, 14, 14, 14)
        card_l.setSpacing(12)

        initials = _initials(name)
        pix: QPixmap
        if avatar_path and Path(avatar_path).exists():
            ap_key = str(avatar_path)
            cached = self._avatar_cache.get(ap_key)
            if cached is None:
                ap = QPixmap(ap_key)
                cached = (
                    ap.scaled(_PEOPLE_AVATAR_PX, _PEOPLE_AVATAR_PX, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    if not ap.isNull()
                    else _placeholder_avatar(_PEOPLE_AVATAR_PX, initials, p.accent)
                )
                self._avatar_cache[ap_key] = cached
            pix = cached
        else:
            pix = _placeholder_avatar(_PEOPLE_AVATAR_PX, initials, p.accent)

        ava = QLabel()
        ava.setPixmap(pix)
        ava.setFixedSize(_PEOPLE_AVATAR_PX + 6, _PEOPLE_AVATAR_PX + 6)
        card_l.addWidget(ava, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        n = QLabel(str(name))
        n.setStyleSheet("font-weight:700; background: transparent;")
        # Each role has its own color; render as rich text so one line can contain multiple colors.
        role_html = ", ".join([f"<span style='color:{escape(str(c))}'>{escape(str(t))}</span>" for t, c in role_parts])
        r = QLabel(role_html)
        r.setTextFormat(Qt.TextFormat.RichText)
        r.setWordWrap(True)
        r.setStyleSheet("background: transparent;")
        text_col.addWidget(n)
        text_col.addWidget(r)
        card_l.addLayout(text_col, 1)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        cnt = QLabel(str(int(tasks_cnt)))
        cnt.setToolTip("Активных задач (В процессе + Отложено)")
        cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        cnt.setStyleSheet("font-weight:900; font-size: 12pt; background: transparent;")

        st = QLabel()
        st.setToolTip(f"Статус: {status_name}")
        st_size = 18
        st.setFixedSize(st_size, st_size)
        st.setStyleSheet(
            f"background:{status_color}; border-radius:{int(st_size/2)}px; border: 2px solid rgba(255,255,255,0.22);"
        )

        # Right side: tasks count top-right, status dot bottom-right.
        right_col.addWidget(cnt, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right_col.addStretch(1)
        right_col.addWidget(st, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        card_l.addLayout(right_col, 0)

        self.people_list_l.insertWidget(self.people_list_l.count() - 1, card)

    def _open_person_settings(self, person_id: str) -> None:
        dlg = PersonSettingsDialog(parent=self, storage=self.storage, person_id=str(person_id))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        # Settings changed: refresh people panel from storage (cheaply).
        # If something changed (including delete), do a full refresh.
        self.refresh_from_storage(force=True)

    def _on_add_person(self) -> None:
        dlg = PersonSettingsDialog(parent=self, storage=self.storage, person_id=_NEW_PERSON_ID)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.refresh_from_storage(force=True)

    def _open_create_task(self, kind: str) -> None:
        dlg = TaskCreateDialog(parent=self, storage=self.storage, column_kind=str(kind))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        # New task written to disk; refresh board.
        self.refresh_from_storage(force=True)

    def _open_edit_task(self, kind: str, task_id: str) -> None:
        tasks = self.storage.load_tasks(str(kind))
        t = next((x for x in tasks if str(x.get("id")) == str(task_id)), None)
        if not isinstance(t, dict):
            return
        dlg = TaskCreateDialog(parent=self, storage=self.storage, column_kind=str(kind), task=t)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.refresh_from_storage(force=True)

    def _open_view_task(self, kind: str, task_id: str) -> None:
        tasks = self.storage.load_tasks(str(kind))
        t = next((x for x in tasks if str(x.get("id")) == str(task_id)), None)
        if not isinstance(t, dict):
            return
        dlg = TaskViewDialog(parent=self, storage=self.storage, column_kind=str(kind), task=t)
        # Accepted means user pressed "Edit" (which may have changed the task).
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.refresh_from_storage(force=True)

    def _on_task_dropped(self, task_id: str, from_kind: str, to_kind: str) -> None:
        try:
            self.storage.move_task(task_id=str(task_id), from_kind=str(from_kind), to_kind=str(to_kind))
        except Exception:
            return
        self.refresh_from_storage(force=True)

    def _open_preferred_link(self, person_id: str) -> None:
        extra = self.storage.get_person_settings(str(person_id))
        pref = extra.get("preferred_link")
        if pref not in ("link1", "link2"):
            return
        url = str(extra.get(pref, "") or "").strip()
        if not url:
            return
        # Add scheme if missing (so Windows opens it in a browser).
        if "://" not in url:
            url = "https://" + url
        QDesktopServices.openUrl(QUrl(url))

    # --- Internals ---
    def _apply_background(self) -> None:
        ui = self.storage.get_ui_settings()
        theme = ui.get("theme", "dark")
        p = get_palette(theme)
        bg = ui.get("background_color", p.bg)
        path = ui.get("background_image_path")
        key = (str(bg), str(path) if path else None)

        # Page background stays dark; the image is revealed through column windows.
        self.board_area.set_background(color="#141414", image=None)
        for b in self._column_bodies:
            b.update()

        # Background image: load/scale off the UI thread.
        ts = self.board_area.size()
        if ts.width() <= 0 or ts.height() <= 0:
            ts = QSize(1280, 720)
        # HiDPI: render to physical pixels to keep background crisp.
        dpr = float(self.board_area.devicePixelRatioF() or 1.0)
        tw = max(1, int(ts.width() * dpr))
        th = max(1, int(ts.height() * dpr))
        # Quantize so tiny per-pixel size changes during resize do not each spawn a new loader.
        _qstep = 32
        tw = max(_qstep, (tw // _qstep) * _qstep)
        th = max(_qstep, (th // _qstep) * _qstep)
        ts_phys = QSize(tw, th)
        load_key = (str(bg), str(path) if path else None, int(ts_phys.width()), int(ts_phys.height()))

        if self._bg_load_key == load_key:
            return
        self._bg_key = key

        if not path or not Path(path).is_file():
            if self._bg_loader is not None and self._bg_loader.isRunning():
                try:
                    self._bg_loader.loaded.disconnect()
                except Exception:
                    pass
                self._bg_loader.requestInterruption()
                self._bg_restart_apply_after_load = True
                return
            if self._bg_loader is not None:
                old = self._bg_loader
                self._bg_loader = None
                try:
                    old.loaded.disconnect()
                except Exception:
                    pass
                old.deleteLater()
            self._bg_load_key = load_key
            self._bg_image = None
            for b in self._column_bodies:
                b.update()
            return

        if self._bg_loader is not None and self._bg_loader.isRunning():
            try:
                self._bg_loader.loaded.disconnect()
            except Exception:
                pass
            self._bg_loader.requestInterruption()
            self._bg_restart_apply_after_load = True
            return

        if self._bg_loader is not None:
            old = self._bg_loader
            self._bg_loader = None
            try:
                old.loaded.disconnect()
            except Exception:
                pass
            old.deleteLater()

        self._bg_load_key = load_key
        loader = BackgroundImageLoader(path=str(path), target_size=ts_phys, key=key)
        self._bg_loader = loader
        _lid = loader

        def _on_loaded(img, loaded_key) -> None:
            # Ignore stale loads (settings changed while loading).
            if loaded_key != self._bg_key:
                return
            qimg = img if isinstance(img, QImage) else None
            if qimg is not None and not qimg.isNull():
                try:
                    qimg.setDevicePixelRatio(dpr)
                except Exception:
                    pass
            self._bg_image = qimg
            for b in self._column_bodies:
                b.update()

        def _on_bg_thread_finished() -> None:
            if self._bg_loader is _lid:
                self._bg_loader = None
            if self._bg_restart_apply_after_load:
                self._bg_restart_apply_after_load = False
                QTimer.singleShot(0, self._apply_background)

        loader.loaded.connect(_on_loaded)
        loader.finished.connect(_on_bg_thread_finished)
        loader.finished.connect(loader.deleteLater)
        loader.start()

    def _clear_layout_items(self, layout: QVBoxLayout) -> None:
        # Remove all widgets except the last stretch.
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _task_card(self, kind: str, task: dict, subj_name: dict[str, str]) -> QWidget:
        theme = self.storage.get_ui_settings().get("theme", "dark")
        p = get_palette(theme)
        task_id = str(task.get("id") or "")
        card = _TaskCard(
            task_id=task_id,
            from_kind=str(kind),
            on_open=lambda k=str(kind), tid=task_id: self._open_view_task(k, tid),
        )
        card.setObjectName("Card")
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        l = QVBoxLayout(card)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(6)

        title = str(task.get("title") or task.get("name") or "Без названия")
        t = _TaskCardTitleEdit(title)
        l.addWidget(t, 0)

        responsible_ids = [str(x) for x in (task.get("responsible_subject_ids") or []) if x]
        if not responsible_ids:
            rid = str(task.get("responsible_subject_id") or "")
            responsible_ids = [rid] if rid else []

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        ava_size = 26

        if len(responsible_ids) <= 1:
            responsible_id = responsible_ids[0] if responsible_ids else ""
            resp = subj_name.get(responsible_id, "—")
            name = self._person_name_by_id.get(responsible_id, resp)
            ap = self._person_avatar_by_id.get(responsible_id)
            color = self._person_color_by_id.get(responsible_id, "#3A7CFF")

            pm = _circle_avatar_pixmap(ava_size, avatar_path=ap, fallback_text=name[:1], bg_hex=color)
            ava = QLabel()
            ava.setPixmap(pm)
            ava.setFixedSize(ava_size, ava_size)
            row.addWidget(ava, 0)

            r = QLabel(name)
            r.setStyleSheet(f"color:{p.muted_fg}; background: transparent;")
            row.addWidget(r, 1)
        else:
            # Multiple responsibles -> only circles, no names.
            max_show = 7
            for pid in responsible_ids[:max_show]:
                name = self._person_name_by_id.get(pid, subj_name.get(pid, ""))
                ap = self._person_avatar_by_id.get(pid)
                color = self._person_color_by_id.get(pid, "#3A7CFF")
                pm = _circle_avatar_pixmap(ava_size, avatar_path=ap, fallback_text=name[:1], bg_hex=color)
                ava = QLabel()
                ava.setPixmap(pm)
                ava.setFixedSize(ava_size, ava_size)
                ava.setToolTip(name)
                row.addWidget(ava, 0)
            row.addStretch(1)

        l.addLayout(row)

        # Subtask progress: between assignees and time.
        # Do NOT gate on QWidget.isVisible() here — while the card is being built its
        # ancestors are not shown yet, so isVisible() is false and the strip would stay
        # a non-layout child of the card at (0,0), drawn on top of the title.
        if get_subtasks_from_task(task):
            strip_holder = QWidget(card)
            strip_holder.setObjectName("TaskCardSubtaskStripHolder")
            sh_l = QVBoxLayout(strip_holder)
            sh_l.setContentsMargins(0, 4, 0, 8)
            sh_l.setSpacing(0)
            sub_strip = SubtaskChainCompactWidget(strip_holder)
            sub_strip.set_task(task)
            sh_l.addWidget(sub_strip)
            l.addWidget(strip_holder)

        # Time label (wekan-like)
        recurring = bool(task.get("recurring", False)) or (not task.get("start_due") and not task.get("end_due"))
        no_deadline = bool(task.get("no_deadline", False))
        start_due = str(task.get("start_due") or "").strip() or None
        end_due = str(task.get("end_due") or "").strip() or None

        def _parse_iso(s: str) -> datetime | None:
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=APP_TZ)
                return dt.astimezone(APP_TZ)
            except Exception:
                return None

        now = datetime.now(APP_TZ)
        if kind == "finished":
            d = QLabel("Завершено")
            d.setStyleSheet(f"color:{p.muted_fg}; background: transparent;")
        elif recurring:
            d = QLabel("Постоянное")
            d.setStyleSheet("font-weight:800; background: transparent;")
        else:
            sd = _parse_iso(start_due) if start_due else None
            ed = _parse_iso(end_due) if (end_due and not no_deadline) else None
            if sd and ed:
                delta_days = (ed - now).total_seconds() / 86400.0
                if delta_days >= 0:
                    x = int(math.ceil(delta_days))
                    d = QLabel(f"осталось {x} дн.")
                    d.setStyleSheet("color:#4CAF50; background: transparent; font-weight:700;")
                else:
                    x = int(math.ceil(abs(delta_days)))
                    d = QLabel(f"просрочено на {x} дн.")
                    d.setStyleSheet("color:#EF5350; background: transparent; font-weight:700;")
            elif sd:
                delta = (now - sd).total_seconds() / 86400.0
                x = int(max(0, math.floor(delta)))
                d = QLabel(f"{x} дн.")
                d.setStyleSheet(f"color:{p.muted_fg}; background: transparent;")
            else:
                d = QLabel("Постоянное")
                d.setStyleSheet("font-weight:800; background: transparent;")

        d.setWordWrap(True)
        l.addWidget(d)
        return card

    def _set_people_panel_width(self, w: int, *, animate: bool) -> None:
        w = max(0, int(w))
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None

        if not animate:
            self.people_panel.setMaximumWidth(w)
            self.people_panel.setMinimumWidth(w)
            self._update_people_arrow()
            # Recompute overlay height immediately (fixes occasional clipping after reparent).
            self._layout_overlay()
            return

        self._anim = QPropertyAnimation(self.people_panel, b"maximumWidth")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(self.people_panel.maximumWidth())
        self._anim.setEndValue(w)

        def _sync_min(v):
            self.people_panel.setMinimumWidth(int(v))
            # Keep geometry in sync during animation.
            self._layout_overlay()
            self._reposition_people_arrow()

        self._anim.valueChanged.connect(_sync_min)

        def _done():
            self.people_panel.setMinimumWidth(w)
            self._update_people_arrow()
            self._layout_overlay()
            self._reposition_people_arrow()

        self._anim.finished.connect(_done)
        self._anim.start()

    def toggle_people_panel(self) -> None:
        if self.pin_btn.isChecked():
            return
        open_ = self.people_panel.maximumWidth() == 0
        self._set_people_panel_width(self._people_target_w if open_ else 0, animate=True)
        ui = self.storage.get_ui_settings()
        ui["people_panel_open"] = bool(open_)
        self.storage.save_ui_settings(ui)

    def _on_pin_toggle(self) -> None:
        pinned = bool(self.pin_btn.isChecked())
        ui = self.storage.get_ui_settings()
        ui["people_panel_pinned"] = pinned
        if pinned:
            ui["people_panel_open"] = True
            self.storage.save_ui_settings(ui)
            self._update_pin_button_text()
            self._apply_pinned_mode_layout()
            self._set_people_panel_width(self._people_target_w, animate=True)
        else:
            # If the panel was pinned, users expect it to remain visible after unpinning.
            ui["people_panel_open"] = True
            self.storage.save_ui_settings(ui)
            self._update_pin_button_text()
            open_ = True
            self._apply_pinned_mode_layout()
            self._set_people_panel_width(self._people_target_w if open_ else 0, animate=True)

    def _apply_pinned_mode_layout(self) -> None:
        pinned = bool(self.pin_btn.isChecked())

        # Remove the panel from content layout if it is there.
        if hasattr(self, "_content_l"):
            for i in range(self._content_l.count()):
                item = self._content_l.itemAt(i)
                if item and item.widget() is self.people_panel:
                    self._content_l.takeAt(i)
                    break

        if pinned:
            # Insert as a "5th column" left of task columns.
            self.people_panel.setParent(self.content_row)
            self.people_panel.setMaximumWidth(self.people_panel.maximumWidth() or self._people_target_w)
            self.people_panel.setMinimumWidth(self.people_panel.minimumWidth() or self._people_target_w)
            self._content_l.insertWidget(0, self.people_panel, 0)
            self.people_panel.show()
        else:
            # Overlay mode.
            self.people_panel.setParent(self.container)
            self.people_panel.raise_()
            self.people_arrow_btn.raise_()
            # Ensure it becomes visible again (width may be > 0).
            self.people_panel.show()
            # Force a relayout on the next tick after reparent;
            # otherwise Qt can report a stale container height and clip the panel
            # until the window is resized.
            QTimer.singleShot(0, self._layout_overlay)

    def _update_pin_button_text(self) -> None:
        self.pin_btn.setText("Открепить" if self.pin_btn.isChecked() else "Закрепить")

    def _open_admin(self) -> None:
        if callable(self.on_open_admin):
            self.on_open_admin()

    def _update_people_arrow(self) -> None:
        w = int(self.people_panel.maximumWidth())
        self._set_people_arrow_icon(w)
        self._reposition_people_arrow()

    def _set_people_arrow_icon(self, panel_w: int) -> None:
        # User requested to swap the icons.
        use_path = self._arrow_close_path if int(panel_w) == 0 else self._arrow_open_path
        pix = self._icons.load_pixmap(use_path, (22, 22))
        if pix is not None:
            self.people_arrow_btn.setIcon(pix)
            self.people_arrow_btn.setText("")
        else:
            self.people_arrow_btn.setText(">" if int(panel_w) == 0 else "<")

    def _reposition_people_arrow(self) -> None:
        pinned = bool(self.pin_btn.isChecked())
        self.people_arrow_btn.setVisible(not pinned)
        if pinned:
            return

        # Place arrow on the left edge or panel edge.
        panel_w = int(self.people_panel.maximumWidth())
        x = panel_w
        y = max(int((self.container.height() - self.people_arrow_btn.height()) / 2), 0)
        self.people_arrow_btn.move(x, y)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_overlay()
        self._reposition_people_arrow()
        # One debounced apply (avoids stacking timers and piling up background loader threads).
        self._bg_resize_timer.start()

    def cleanup_threads(self) -> None:
        """Wait for worker threads before shutdown (avoids 'QThread destroyed while still running')."""
        self._bg_resize_timer.stop()
        if self._bg_loader is not None:
            try:
                self._bg_loader.loaded.disconnect()
            except Exception:
                pass
            if self._bg_loader.isRunning():
                self._bg_loader.requestInterruption()
                self._bg_loader.wait(5000)
            self._bg_loader = None
        if self._prefetch_thread is not None:
            if self._prefetch_thread.isRunning():
                self._prefetch_thread.requestInterruption()
                self._prefetch_thread.wait(5000)
            self._prefetch_thread = None

    def _layout_overlay(self) -> None:
        # Manual geometry: people panel overlays the board (unless pinned).
        w = self.container.width()
        h = self.container.height()
        panel_w = int(self.people_panel.maximumWidth())
        pinned = bool(self.pin_btn.isChecked())

        if pinned:
            # In pinned mode the people panel lives inside the content layout,
            # so we must NOT reserve overlay space on the left.
            self.board_area.setGeometry(0, 0, max(w, 1), max(h, 1))
            return
        else:
            self.board_area.setGeometry(0, 0, w, h)
            self.people_panel.setGeometry(0, 0, panel_w, h)
            self.people_panel.raise_()
            self.people_arrow_btn.raise_()
            self._reposition_people_arrow()

