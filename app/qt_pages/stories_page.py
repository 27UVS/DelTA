from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape as _html_escape
import re
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, QSize, Signal, QMimeData, QItemSelectionModel
from PySide6.QtGui import QColor, QDesktopServices, QPalette, QTextOption, QFont, QTextCharFormat, QTextCursor, QTextFormat, QTextListFormat, QBrush, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QTextEdit,
    QInputDialog,
)

from app.assets import get_interface_assets
from app.storage import Storage, SYSTEM_NONE_ROLE_ID
from app.qt_widgets.flow_layout import FlowLayout


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


_RE_STYLE_BG = re.compile(r"background(?:-color)?\s*:\s*[^;\"']+;?", re.IGNORECASE)
_RE_BG_COLOR_ATTR = re.compile(r'\sbgcolor\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)
_RE_STYLE_COLOR = re.compile(r"color\s*:\s*[^;\"']+;?", re.IGNORECASE)
_RE_COLOR_ATTR = re.compile(r'\scolor\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)
_RE_STYLE_FONT = re.compile(
    r"(?:font-size|font-family|font-stretch|font-variant|font|line-height)\s*:\s*[^;\"']+;?",
    re.IGNORECASE,
)
_RE_FONT_ATTR = re.compile(r'\s(?:size|face)\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)


def _strip_background_html(html: str) -> str:
    """Remove pasted white backgrounds (background/background-color/bgcolor)."""
    s = str(html or "")
    if not s:
        return s
    s = _RE_BG_COLOR_ATTR.sub("", s)

    def _fix_style(m):
        val = m.group(0)
        cleaned = _RE_STYLE_BG.sub("", val)
        return cleaned

    s = re.sub(r'style\s*=\s*"[^"]*"', _fix_style, s, flags=re.IGNORECASE)
    s = re.sub(r"style\s*=\s*'[^']*'", _fix_style, s, flags=re.IGNORECASE)
    return s


def _sanitize_rich_html_for_dark(html: str) -> str:
    """
    Make pasted rich HTML readable on dark background:
    - remove backgrounds
    - remove forced text colors (so the editor's stylesheet can apply white)
    """
    s = _strip_background_html(html)
    if not s:
        return s
    s = _RE_COLOR_ATTR.sub("", s)
    s = _RE_FONT_ATTR.sub("", s)

    def _fix_style_color(m):
        val = m.group(0)
        cleaned = _RE_STYLE_COLOR.sub("", val)
        cleaned = _RE_STYLE_FONT.sub("", cleaned)
        return cleaned

    s = re.sub(r'style\s*=\s*"[^"]*"', _fix_style_color, s, flags=re.IGNORECASE)
    s = re.sub(r"style\s*=\s*'[^']*'", _fix_style_color, s, flags=re.IGNORECASE)
    return s


class _SanitizedRichTextEdit(QTextEdit):
    """QTextEdit that strips background styles on paste."""

    def insertFromMimeData(self, source) -> None:  # type: ignore[override]
        try:
            if source is not None and source.hasHtml():
                html = _sanitize_rich_html_for_dark(str(source.html() or ""))
                md = QMimeData()
                md.setHtml(html)
                if source.hasText():
                    md.setText(source.text())
                return super().insertFromMimeData(md)
        except Exception:
            pass
        super().insertFromMimeData(source)


@dataclass(frozen=True)
class _Person:
    id: str
    name: str
    role_ids: list[str]


class StoriesPage(QWidget):
    """
    MVP "Stories" planner page:
    - left: season/arc filters + archive switch + search
    - center: list of stories
    - right: story details + role-based assignment with search (writers/editors/artists)
    """

    stories_changed = Signal()

    def __init__(self, *, storage: Storage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.storage = storage

        self._stories: list[dict[str, Any]] = []
        self._selected_story_id: str | None = None
        self._role_rows: list[dict[str, str]] = []  # {id,name}
        self._editing: bool = False
        self._draft: dict[str, Any] | None = None
        self._all_sections: list[dict[str, Any]] = []
        self._last_sort_mode: str = "personal"

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ----- Left filters -----
        left = QFrame()
        left.setObjectName("StoriesLeft")
        left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        left.setMinimumWidth(260)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(10, 10, 10, 10)
        left_l.setSpacing(10)

        self.season_cb = QComboBox()
        self.season_cb.setToolTip("Сезон (фильтр)")
        self.arc_cb = QComboBox()
        self.arc_cb.setToolTip("Арка (фильтр)")
        self.show_archived_cb = QCheckBox("Показывать не актуальные (архив)")
        self.sections_filter = QListWidget()
        self.sections_filter.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.sections_filter.setMaximumHeight(220)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по историям…")
        self.sort_cb = QComboBox()
        self.sort_cb.addItem("Ранние", "early")
        self.sort_cb.addItem("Поздние", "late")
        self.sort_cb.addItem("Персональная", "personal")
        self.sort_cb.setToolTip("Порядок историй")
        # Default sort: personal (manual order / drag-reorder).
        try:
            self.sort_cb.setCurrentIndex(self.sort_cb.findData("personal"))
        except Exception:
            pass

        left_l.addWidget(QLabel("Сезон"))
        left_l.addWidget(self.season_cb)
        left_l.addWidget(QLabel("Арка"))
        left_l.addWidget(self.arc_cb)
        left_l.addWidget(QLabel("Раздел"))
        left_l.addWidget(self.sections_filter)
        left_l.addWidget(QLabel("Порядок"))
        left_l.addWidget(self.sort_cb)
        left_l.addWidget(self.show_archived_cb)
        left_l.addWidget(self.search_edit)
        left_l.addStretch(1)

        # ----- Center list -----
        center = QFrame()
        center.setObjectName("StoriesCenter")
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(10, 10, 10, 10)
        center_l.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(QLabel("Истории"), 0)
        head.addStretch(1)
        self.add_btn = QPushButton("＋")
        self.add_btn.setToolTip("Добавить историю")
        self.add_btn.setFixedSize(34, 28)
        head.addWidget(self.add_btn, 0)
        center_l.addLayout(head)

        self.list = _StoriesListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.order_dropped.connect(self._on_personal_order_dropped)
        center_l.addWidget(self.list, 1)

        # ----- Right details -----
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QFrame.Shape.NoFrame)
        self.details = QWidget()
        right.setWidget(self.details)
        d_l = QVBoxLayout(self.details)
        d_l.setContentsMargins(10, 10, 10, 10)
        d_l.setSpacing(10)

        # Edit controls
        edit_row = QHBoxLayout()
        edit_row.addStretch(1)
        self.edit_btn = QPushButton("Редактировать")
        self.delete_btn = QPushButton("Полное удаление")
        self.save_btn = QPushButton("Сохранить")
        self.cancel_btn = QPushButton("Отмена")
        self.save_btn.setVisible(False)
        self.cancel_btn.setVisible(False)
        edit_row.addWidget(self.edit_btn)
        edit_row.addWidget(self.delete_btn)
        edit_row.addWidget(self.save_btn)
        edit_row.addWidget(self.cancel_btn)
        d_l.addLayout(edit_row)

        # Story classification (season/arc + sections multi-select)
        self.story_season_cb = QComboBox()
        self.story_arc_cb = QComboBox()
        self.story_sections_list = QListWidget()
        self.story_sections_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.story_sections_list.setMaximumHeight(170)

        class_box = QGroupBox("Классификация")
        class_l = QGridLayout(class_box)
        class_l.addWidget(QLabel("Сезон"), 0, 0)
        class_l.addWidget(self.story_season_cb, 0, 1)
        class_l.addWidget(QLabel("Арка"), 1, 0)
        class_l.addWidget(self.story_arc_cb, 1, 1)
        class_l.addWidget(QLabel("Разделы"), 2, 0, Qt.AlignmentFlag.AlignTop)
        class_l.addWidget(self.story_sections_list, 2, 1)
        d_l.addWidget(class_box)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Название истории")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Ссылка на исходный документ")
        self.open_url_btn = QPushButton("Открыть ссылку")
        self.status_cb = QComboBox()

        top_box = QGroupBox("Детали")
        top_l = QGridLayout(top_box)
        top_l.addWidget(QLabel("Название"), 0, 0)
        top_l.addWidget(self.title_edit, 0, 1)
        top_l.addWidget(QLabel("Ссылка"), 1, 0)
        top_l.addWidget(self.url_edit, 1, 1)
        top_l.addWidget(self.open_url_btn, 2, 1, 1, 1, Qt.AlignmentFlag.AlignRight)
        top_l.addWidget(QLabel("Статус"), 3, 0)
        top_l.addWidget(self.status_cb, 3, 1)
        d_l.addWidget(top_box)

        # Synopsis (story description)
        synopsis_box = QGroupBox("Синопсис")
        synopsis_l = QVBoxLayout(synopsis_box)
        synopsis_tools = QHBoxLayout()

        def _mk_btn(text: str, tooltip: str, cb) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tooltip)
            b.setFixedHeight(28)
            b.clicked.connect(cb)
            return b

        self._syn_btn_bold = _mk_btn("B", "Жирный", self._syn_fmt_bold)
        self._syn_btn_italic = _mk_btn("I", "Курсив", self._syn_fmt_italic)
        self._syn_btn_underline = _mk_btn("U", "Подчёркнутый", self._syn_fmt_underline)
        self._syn_btn_strike = _mk_btn("S", "Зачёркнутый", self._syn_fmt_strike)
        self._syn_btn_left = _mk_btn("⟸", "По левому краю", lambda: self.synopsis_edit.setAlignment(Qt.AlignmentFlag.AlignLeft))
        self._syn_btn_center = _mk_btn("≡", "По центру", lambda: self.synopsis_edit.setAlignment(Qt.AlignmentFlag.AlignHCenter))
        self._syn_btn_right = _mk_btn("⟹", "По правому краю", lambda: self.synopsis_edit.setAlignment(Qt.AlignmentFlag.AlignRight))
        self._syn_btn_justify = _mk_btn("▤", "По ширине", lambda: self.synopsis_edit.setAlignment(Qt.AlignmentFlag.AlignJustify))
        self._syn_btn_bullets = _mk_btn("•", "Маркированный список", self._syn_fmt_bullets)
        self._syn_btn_numbers = _mk_btn("1.", "Нумерованный список", self._syn_fmt_numbers)
        self._syn_btn_link = _mk_btn("", "Вставить ссылку", self._syn_fmt_link)
        self._syn_btn_link.setFixedSize(34, 28)
        try:
            assets = get_interface_assets()
            if assets.link_button_png.exists():
                self._syn_btn_link.setIcon(QIcon(str(assets.link_button_png)))
                self._syn_btn_link.setIconSize(QSize(18, 18))
        except Exception:
            pass
        self._syn_btn_unlink = _mk_btn("⌧", "Убрать ссылку с выделенного текста", self._syn_fmt_unlink)
        self._syn_btn_unlink.setFixedSize(34, 28)

        for w in [
            self._syn_btn_bold,
            self._syn_btn_italic,
            self._syn_btn_underline,
            self._syn_btn_strike,
            self._syn_btn_left,
            self._syn_btn_center,
            self._syn_btn_right,
            self._syn_btn_justify,
            self._syn_btn_bullets,
            self._syn_btn_numbers,
            self._syn_btn_link,
            self._syn_btn_unlink,
        ]:
            synopsis_tools.addWidget(w, 0)
        synopsis_tools.addStretch(1)
        synopsis_l.addLayout(synopsis_tools)

        self.synopsis_edit = _SanitizedRichTextEdit()
        self.synopsis_edit.setAcceptRichText(True)
        self.synopsis_edit.setMinimumHeight(160)
        # Force readable text on dark background; pasted HTML colors are sanitized.
        self.synopsis_edit.setStyleSheet("QTextEdit{color:#FFFFFF; background: transparent;}")
        # Keep pasted / loaded text in the same font/size as user input.
        try:
            f = QFont(self.font())
            f.setPointSize(max(10, int(f.pointSize())))
            self.synopsis_edit.setFont(f)
            self.synopsis_edit.document().setDefaultFont(f)
        except Exception:
            pass
        try:
            self.synopsis_edit.document().setDefaultStyleSheet("a{color:#64B5F6;}")
        except Exception:
            pass
        synopsis_l.addWidget(self.synopsis_edit, 1)
        d_l.addWidget(synopsis_box)

        self.archive_btn = QPushButton("В архив")
        d_l.addWidget(self.archive_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.roles_box = QGroupBox("Роли")
        self.roles_box_l = QVBoxLayout(self.roles_box)
        self.roles_box_l.setContentsMargins(10, 10, 10, 10)
        self.roles_box_l.setSpacing(10)
        d_l.addWidget(self.roles_box)
        self._role_boxes: dict[str, dict[str, Any]] = {}  # role_id -> {box, search, chips}

        d_l.addStretch(1)

        root.addWidget(left, 0)
        root.addWidget(center, 1)
        root.addWidget(right, 1)

        # signals
        self.season_cb.currentIndexChanged.connect(self._refresh_story_list)
        self.arc_cb.currentIndexChanged.connect(self._refresh_story_list)
        self.show_archived_cb.toggled.connect(self._refresh_story_list)
        self.sections_filter.itemChanged.connect(self._refresh_story_list)
        self.sort_cb.currentIndexChanged.connect(self._on_sort_changed)
        self.search_edit.textChanged.connect(self._refresh_story_list)
        self.list.currentItemChanged.connect(self._on_story_selected)
        self.add_btn.clicked.connect(self._on_add_story)
        self.open_url_btn.clicked.connect(self._on_open_url)
        self.archive_btn.clicked.connect(self._on_toggle_archive)
        self.edit_btn.clicked.connect(self._enter_edit_mode)
        self.delete_btn.clicked.connect(self._on_delete_story)
        self.save_btn.clicked.connect(self._save_draft)
        self.cancel_btn.clicked.connect(self._cancel_edit_mode)

        self.reload_from_storage()

    # ---- public ----
    def reload_from_storage(self) -> None:
        # If admin changes arrive while editing, drop draft (no implicit writes).
        if self._editing:
            self._cancel_edit_mode()
        self._stories = self.storage.get_stories()
        self._rebuild_taxonomy_options()
        self._rebuild_status_options()
        self._rebuild_role_boxes()
        self._last_sort_mode = str(self.sort_cb.currentData() or "personal")
        self._apply_reorder_mode()
        self._refresh_story_list()
        self._select_story(self._selected_story_id)

    def select_story_by_id(self, story_id: str | None) -> None:
        """Public helper: switch selection in the center list by story id."""
        if self._editing:
            self._cancel_edit_mode()
        self._selected_story_id = str(story_id) if story_id else None
        self._refresh_story_list()
        self._select_story(self._selected_story_id)

    # ---- internals ----
    def _rebuild_status_options(self) -> None:
        self.status_cb.blockSignals(True)
        self.status_cb.clear()
        statuses = self.storage.get_story_statuses()
        for st in statuses:
            self.status_cb.addItem(str(st.get("name") or "—"), str(st.get("id") or ""))
        self.status_cb.blockSignals(False)

    def _rebuild_taxonomy_options(self) -> None:
        items = self.storage.get_story_taxonomy()
        seasons = [x for x in items if str(x.get("kind")) == "season"]
        arcs = [x for x in items if str(x.get("kind")) == "arc"]
        sections = [x for x in items if str(x.get("kind")) == "section"]

        def _sort(xs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(xs, key=lambda x: (0 if bool(x.get("locked")) else 1, str(x.get("name") or "").lower()))

        seasons = _sort(seasons)
        arcs = _sort(arcs)
        sections = _sort(sections)

        cur_season = str(self.season_cb.currentData() or "")
        cur_arc = str(self.arc_cb.currentData() or "")
        cur_story_season = str(self.story_season_cb.currentData() or "")
        cur_story_arc = str(self.story_arc_cb.currentData() or "")

        self.season_cb.blockSignals(True)
        self.arc_cb.blockSignals(True)
        self.story_season_cb.blockSignals(True)
        self.story_arc_cb.blockSignals(True)
        try:
            self.season_cb.clear()
            for s in seasons:
                self.season_cb.addItem(str(s.get("name") or "—"), str(s.get("id") or ""))
            self.arc_cb.clear()
            for a in arcs:
                self.arc_cb.addItem(str(a.get("name") or "—"), str(a.get("id") or ""))

            # restore if possible
            for cb, cur in [(self.season_cb, cur_season), (self.arc_cb, cur_arc)]:
                idx = cb.findData(cur)
                cb.setCurrentIndex(idx if idx >= 0 else 0)

            # story-level selectors mirror the same sources
            self.story_season_cb.clear()
            for s in seasons:
                self.story_season_cb.addItem(str(s.get("name") or "—"), str(s.get("id") or ""))
            self.story_arc_cb.clear()
            for a in arcs:
                self.story_arc_cb.addItem(str(a.get("name") or "—"), str(a.get("id") or ""))
            for cb, cur in [(self.story_season_cb, cur_story_season), (self.story_arc_cb, cur_story_arc)]:
                idx = cb.findData(cur)
                cb.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self.season_cb.blockSignals(False)
            self.arc_cb.blockSignals(False)
            self.story_season_cb.blockSignals(False)
            self.story_arc_cb.blockSignals(False)

        # Sections:
        # - "Актуальные/Не актуальные" do not participate (archive is a separate flag).
        self._all_sections = [x for x in sections if str(x.get("id")) not in ("section_actual", "section_not_actual")]
        self.sections_filter.blockSignals(True)
        try:
            prev_checked: set[str] = set()
            for i in range(self.sections_filter.count()):
                it = self.sections_filter.item(i)
                if it is not None and it.checkState() == Qt.CheckState.Checked:
                    prev_checked.add(str(it.data(Qt.ItemDataRole.UserRole) or ""))
            self.sections_filter.clear()
            for sec in self._all_sections:
                sec_id = str(sec.get("id") or "")
                sec_name = str(sec.get("name") or "—")
                it = QListWidgetItem(sec_name)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if sec_id in prev_checked else Qt.CheckState.Unchecked)
                it.setData(Qt.ItemDataRole.UserRole, sec_id)
                self.sections_filter.addItem(it)
        finally:
            self.sections_filter.blockSignals(False)

    def _rebuild_role_boxes(self) -> None:
        # Remove old role widgets
        while self.roles_box_l.count():
            it = self.roles_box_l.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._role_boxes.clear()

        roles = [r for r in self.storage.get_roles() if r.id not in ("role_admin", SYSTEM_NONE_ROLE_ID)]
        roles = [r for r in roles if bool(getattr(r, "for_stories", False))]
        roles = sorted(roles, key=lambda r: (r.priority, r.name.lower()))
        self._role_rows = [{"id": str(r.id), "name": str(r.name)} for r in roles]

        for rr in self._role_rows:
            role_id = rr["id"]
            role_title = rr["name"]
            gb = QGroupBox(role_title)
            gb_l = QVBoxLayout(gb)
            gb_l.setContentsMargins(10, 10, 10, 10)
            gb_l.setSpacing(8)
            se = QLineEdit()
            se.setPlaceholderText(f"Поиск: {role_title.lower()}…")
            gb_l.addWidget(se)
            chips = _ChipList()
            gb_l.addWidget(chips, 0)
            self.roles_box_l.addWidget(gb)
            self._role_boxes[role_id] = {"box": gb, "search": se, "chips": chips}
            se.textChanged.connect(lambda _=None, rid=role_id: self._refresh_role_chips(rid))

    def _filtered_stories(self) -> list[dict[str, Any]]:
        season_id = str(self.season_cb.currentData() or "")
        arc_id = str(self.arc_cb.currentData() or "")
        show_archived = bool(self.show_archived_cb.isChecked())
        selected_sections: set[str] = set()
        for i in range(self.sections_filter.count()):
            it = self.sections_filter.item(i)
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                selected_sections.add(str(it.data(Qt.ItemDataRole.UserRole) or ""))
        q = _norm(self.search_edit.text())
        out: list[dict[str, Any]] = []
        for s in self._stories:
            if bool(s.get("archived", False)) != bool(show_archived):
                continue
            if season_id and season_id != "season_all" and str(s.get("season_id") or "") != season_id:
                continue
            if arc_id and arc_id != "arc_all" and str(s.get("arc_id") or "") != arc_id:
                continue
            if selected_sections:
                sec_ids = s.get("section_ids")
                if not isinstance(sec_ids, list):
                    sec_ids = []
                if not any(str(x) in selected_sections for x in sec_ids):
                    continue
            if q:
                if q not in _norm(str(s.get("title") or "")):
                    continue
            out.append(s)
        mode = str(self.sort_cb.currentData() or "personal")
        return self._sorted_stories(out, mode=mode)

    def _sorted_stories(self, stories: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
        out = list(stories)

        def _created(x: dict[str, Any]) -> str:
            return str(x.get("created_at") or "")

        if mode == "late":
            out.sort(key=lambda x: (_created(x), str(x.get("id") or "")), reverse=True)
        elif mode == "personal":
            # Missing order -> fallback to file order to keep stable behavior.
            file_pos = {str(st.get("id") or ""): i for i, st in enumerate(self._stories)}
            out.sort(
                key=lambda x: (
                    int(x.get("order") if isinstance(x.get("order"), int) else (10**9)),
                    int(file_pos.get(str(x.get("id") or ""), 10**9)),
                )
            )
        else:
            out.sort(key=lambda x: (_created(x), str(x.get("id") or "")))
        return out

    def _on_sort_changed(self) -> None:
        new_mode = str(self.sort_cb.currentData() or "personal")
        prev_mode = str(self._last_sort_mode or "personal")
        # If user returns to "Персональная" after a different sort mode,
        # adopt the order currently shown by that previous sort mode.
        if new_mode == "personal" and prev_mode in ("early", "late"):
            # Build the set of filtered stories (without applying current mode sorting),
            # then sort them using the previous mode and persist as the new manual order.
            base = self._filtered_stories()
            prev_sorted = self._sorted_stories(base, mode=prev_mode)
            self._persist_personal_order([str(s.get("id") or "") for s in prev_sorted if isinstance(s, dict)])
        self._last_sort_mode = new_mode
        self._apply_reorder_mode()
        self._refresh_story_list()

    def _apply_reorder_mode(self) -> None:
        personal = str(self.sort_cb.currentData() or "") == "personal"
        if personal:
            self.list.setDragEnabled(True)
            self.list.setAcceptDrops(True)
            self.list.setDropIndicatorShown(True)
            self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        else:
            self.list.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
            self.list.setDragEnabled(False)
            self.list.setAcceptDrops(False)
            self.list.setDropIndicatorShown(False)

    def _on_personal_order_dropped(self) -> None:
        if str(self.sort_cb.currentData() or "") != "personal":
            return
        ids: list[str] = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it is None:
                continue
            sid = str(it.data(Qt.ItemDataRole.UserRole) or "")
            if sid:
                ids.append(sid)
        self._persist_personal_order(ids)

    def _persist_personal_order(self, ids: list[str]) -> None:
        ids = [str(x) for x in (ids or []) if str(x)]
        if not ids:
            return
        # Apply incremental order values.
        order_by_id = {sid: (idx * 10) for idx, sid in enumerate(ids)}
        changed = False
        new_all: list[dict[str, Any]] = []
        for st in self.storage.get_stories():
            if not isinstance(st, dict):
                continue
            sid = str(st.get("id") or "")
            if sid in order_by_id:
                cur = st.get("order")
                new_val = int(order_by_id[sid])
                if cur != new_val:
                    st = {**st, "order": new_val}
                    changed = True
            new_all.append(st)
        if not changed:
            return
        try:
            self.storage.save_stories(new_all)
        except Exception:
            return
        self._stories = self.storage.get_stories()
        self._refresh_story_list()
        self._select_story(self._selected_story_id)
        try:
            self.stories_changed.emit()
        except Exception:
            pass

    def _refresh_story_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        statuses = {str(s.get("id")): s for s in self.storage.get_story_statuses()}
        roles = [r for r in self.storage.get_roles() if r.id not in ("role_admin", SYSTEM_NONE_ROLE_ID)]
        role_color_by_id = {str(r.id): str(r.color or "#BDBDBD") for r in roles}

        # Build people name map once per refresh (admin + subjects).
        profile = self.storage.get_profile()
        people_name_by_id: dict[str, str] = {"__admin__": str(profile.get("nickname") or "Администратор")}
        for subj in self.storage.get_subjects():
            sid = str(subj.get("id") or "")
            if not sid:
                continue
            people_name_by_id[sid] = str(subj.get("nickname") or "")

        for s in self._filtered_stories():
            sid = str(s.get("id") or "")
            title = str(s.get("title") or "Без названия")
            st = statuses.get(str(s.get("status_id") or ""))
            st_name = str(st.get("name") or "—") if st else "—"
            st_color = str(st.get("color") or "#9E9E9E") if st else "#9E9E9E"
            assignments = s.get("assignments") if isinstance(s.get("assignments"), dict) else {}

            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, sid)
            card = _StoryCard(
                title=title,
                status_name=st_name,
                status_color=st_color,
                assignments=assignments,
                people_name_by_id=people_name_by_id,
                role_color_by_id=role_color_by_id,
                on_height_changed=lambda h, _it=it: _it.setSizeHint(QSize(0, int(h))),
            )
            it.setSizeHint(card.sizeHint())
            self.list.addItem(it)
            self.list.setItemWidget(it, card)
        self.list.blockSignals(False)
        self._select_story(self._selected_story_id)

    def _select_story(self, story_id: str | None) -> None:
        sid = str(story_id or "")
        if not sid:
            if self.list.count() > 0:
                self.list.setCurrentRow(0)
            else:
                self._apply_story_to_details(None)
            return
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it and str(it.data(Qt.ItemDataRole.UserRole)) == sid:
                self.list.setCurrentRow(i)
                return
        # not found in current filter -> clear
        self._apply_story_to_details(None)

    def _on_story_selected(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        next_sid = str(cur.data(Qt.ItemDataRole.UserRole)) if cur else ""
        prev_sid = str(prev.data(Qt.ItemDataRole.UserRole)) if prev else ""

        # If user tries to switch stories while editing, ask what to do with unsaved changes.
        if self._editing and next_sid and next_sid != str(self._selected_story_id or ""):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Несохранённые изменения")
            box.setText("Сохранить изменения в текущей истории?")
            box.setStandardButtons(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Save)
            try:
                b_save = box.button(QMessageBox.StandardButton.Save)
                if b_save is not None:
                    b_save.setText("Сохранить")
                b_discard = box.button(QMessageBox.StandardButton.Discard)
                if b_discard is not None:
                    b_discard.setText("Не сохранять")
                b_cancel = box.button(QMessageBox.StandardButton.Cancel)
                if b_cancel is not None:
                    b_cancel.setText("Отмена")
            except Exception:
                pass

            res = box.exec()
            if res == int(QMessageBox.StandardButton.Cancel):
                # Keep editing; revert list highlight to the currently edited story.
                keep_sid = str(self._selected_story_id or prev_sid or "")
                if keep_sid:
                    # Do it twice: immediately (best effort) and on next tick (Qt may re-apply the click selection).
                    self._force_select_story_item(keep_sid, scroll=False)
                    QTimer.singleShot(0, lambda sid=keep_sid: self._force_select_story_item(sid, scroll=True))
                    QTimer.singleShot(30, lambda sid=keep_sid: self._force_select_story_item(sid, scroll=False))
                return
            if res == int(QMessageBox.StandardButton.Save):
                self._save_draft()
                # Saving refreshes the list and may invalidate `cur`; switch by id on next tick.
                QTimer.singleShot(0, lambda sid=next_sid: self._switch_to_story_by_id(sid))
                return
            else:
                # Discard
                self._cancel_edit_mode()
                QTimer.singleShot(0, lambda sid=next_sid: self._switch_to_story_by_id(sid))
                return

            # Ensure in-memory stories are up-to-date after save/discard.
            try:
                self._stories = self.storage.get_stories()
            except Exception:
                pass

        sid = next_sid
        self._selected_story_id = sid or None
        story = next((s for s in self._stories if str(s.get("id")) == sid), None)
        self._apply_story_to_details(story if isinstance(story, dict) else None)

    def _force_select_story_item(self, story_id: str, *, scroll: bool) -> None:
        """Force list selection/highlight to a story id (used to cancel selection changes while editing)."""
        sid = str(story_id or "")
        if not sid:
            return
        self.list.blockSignals(True)
        try:
            try:
                self.list.clearSelection()
            except Exception:
                pass
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it is None:
                    continue
                if str(it.data(Qt.ItemDataRole.UserRole) or "") == sid:
                    self.list.setCurrentItem(it, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                    try:
                        self.list.setCurrentRow(i)
                    except Exception:
                        pass
                    if scroll:
                        try:
                            self.list.scrollToItem(it)
                        except Exception:
                            pass
                    break
        finally:
            self.list.blockSignals(False)

    def _switch_to_story_by_id(self, story_id: str) -> None:
        """Switch selection + details by story id (safe after list refresh)."""
        sid = str(story_id or "")
        if not sid:
            return
        # Refresh storage snapshot (in case we just saved).
        try:
            self._stories = self.storage.get_stories()
        except Exception:
            pass
        # Force list highlight and details without relying on stale QListWidgetItem objects.
        self._selected_story_id = sid
        self._force_select_story_item(sid, scroll=True)
        story = next((s for s in self._stories if isinstance(s, dict) and str(s.get("id")) == sid), None)
        self._apply_story_to_details(story if isinstance(story, dict) else None)

    def _apply_story_to_details(self, story: dict[str, Any] | None) -> None:
        self.details.setEnabled(bool(story))
        if not story:
            self.story_season_cb.setCurrentIndex(0)
            self.story_arc_cb.setCurrentIndex(0)
            self.story_sections_list.clear()
            self.title_edit.setText("")
            self.url_edit.setText("")
            self.status_cb.setCurrentIndex(0)
            for rid in self._role_boxes:
                self._role_boxes[rid]["chips"].set_items([], selected=set(), on_toggle=lambda _pid, _on: None)
            return

        self._draft = None
        self._set_editing(False)

        self.title_edit.setText(str(story.get("title") or ""))
        self.url_edit.setText(str(story.get("source_url") or ""))
        self._set_synopsis_from_storage(str(story.get("synopsis") or ""))

        # classification
        season_id = str(story.get("season_id") or "season_all")
        arc_id = str(story.get("arc_id") or "arc_all")
        idx = self.story_season_cb.findData(season_id)
        self.story_season_cb.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.story_arc_cb.findData(arc_id)
        self.story_arc_cb.setCurrentIndex(idx if idx >= 0 else 0)
        # sections multiselect
        self.story_sections_list.blockSignals(True)
        try:
            self.story_sections_list.clear()
            selected_secs = set([str(x) for x in (story.get("section_ids") or []) if str(x)])
            for sec in getattr(self, "_all_sections", []):
                sec_id = str(sec.get("id") or "")
                sec_name = str(sec.get("name") or "—")
                it = QListWidgetItem(sec_name)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if sec_id in selected_secs else Qt.CheckState.Unchecked)
                it.setData(Qt.ItemDataRole.UserRole, sec_id)
                self.story_sections_list.addItem(it)
        finally:
            self.story_sections_list.blockSignals(False)

        # status select
        stid = str(story.get("status_id") or "")
        idx = self.status_cb.findData(stid)
        if idx >= 0:
            self.status_cb.setCurrentIndex(idx)

        self.archive_btn.setText("Восстановить" if bool(story.get("archived", False)) else "В архив")

        for rid in self._role_boxes:
            self._refresh_role_chips(rid)

    def _set_editing(self, editing: bool) -> None:
        self._editing = bool(editing)
        self.edit_btn.setVisible(not self._editing)
        self.delete_btn.setVisible(not self._editing)
        self.save_btn.setVisible(self._editing)
        self.cancel_btn.setVisible(self._editing)

        enabled = self._editing
        # classification + details
        self.story_season_cb.setEnabled(enabled)
        self.story_arc_cb.setEnabled(enabled)
        self.story_sections_list.setEnabled(enabled)
        self.title_edit.setEnabled(enabled)
        self.url_edit.setEnabled(enabled)
        self.status_cb.setEnabled(enabled)
        self.archive_btn.setEnabled(enabled)
        self.synopsis_edit.setEnabled(enabled)
        for w in [
            self._syn_btn_bold,
            self._syn_btn_italic,
            self._syn_btn_underline,
            self._syn_btn_strike,
            self._syn_btn_left,
            self._syn_btn_center,
            self._syn_btn_right,
            self._syn_btn_justify,
            self._syn_btn_bullets,
            self._syn_btn_numbers,
            self._syn_btn_link,
            self._syn_btn_unlink,
        ]:
            w.setEnabled(enabled)
        # role assignment UI
        for rid, box in self._role_boxes.items():
            box["search"].setEnabled(enabled)
            box["chips"].setEnabled(enabled)

    def _on_delete_story(self) -> None:
        sid = str(self._selected_story_id or "")
        story = next((s for s in self._stories if str(s.get("id")) == sid), None)
        if not sid or not isinstance(story, dict):
            return
        if self._editing:
            return

        title = str(story.get("title") or "Без названия").strip()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Полное удаление")
        box.setText(
            "История будет удалена полностью и безвозвратно.\n"
            "Если она была привязана к задачам — связь будет снята.\n\n"
            f"Удалить «{title}»?"
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        try:
            btn_yes = box.button(QMessageBox.StandardButton.Yes)
            if btn_yes is not None:
                btn_yes.setText("Да")
            btn_no = box.button(QMessageBox.StandardButton.No)
            if btn_no is not None:
                btn_no.setText("Нет")
        except Exception:
            pass

        res = box.exec()
        if res != int(QMessageBox.StandardButton.Yes):
            return

        try:
            self.storage.delete_story(sid)
        except Exception:
            return

        self._selected_story_id = None
        self._stories = self.storage.get_stories()
        self._refresh_story_list()
        self._apply_story_to_details(None)
        try:
            self.stories_changed.emit()
        except Exception:
            pass

    def _enter_edit_mode(self) -> None:
        sid = str(self._selected_story_id or "")
        story = next((s for s in self._stories if str(s.get("id")) == sid), None)
        if not isinstance(story, dict):
            return
        self._draft = {
            "title": str(story.get("title") or ""),
            "source_url": str(story.get("source_url") or ""),
            "synopsis": str(story.get("synopsis") or ""),
            "status_id": str(story.get("status_id") or ""),
            "season_id": str(story.get("season_id") or "season_all"),
            "arc_id": str(story.get("arc_id") or "arc_all"),
            "section_ids": [str(x) for x in (story.get("section_ids") or []) if str(x)],
            "assignments": (story.get("assignments") if isinstance(story.get("assignments"), dict) else {}),
            "archived": bool(story.get("archived", False)),
        }
        self._set_editing(True)

    def _cancel_edit_mode(self) -> None:
        self._draft = None
        self._set_editing(False)
        # Reapply current story from storage (discard UI edits).
        sid = str(self._selected_story_id or "")
        story = next((s for s in self._stories if str(s.get("id")) == sid), None)
        self._apply_story_to_details(story if isinstance(story, dict) else None)

    def _save_draft(self) -> None:
        sid = str(self._selected_story_id or "")
        if not sid or not isinstance(self._draft, dict):
            return
        # Collect from current UI (authoritative)
        sec_ids: list[str] = []
        for i in range(self.story_sections_list.count()):
            it = self.story_sections_list.item(i)
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                sec_ids.append(str(it.data(Qt.ItemDataRole.UserRole) or ""))
        patch = {
            "title": str(self.title_edit.text() or "").strip(),
            "source_url": str(self.url_edit.text() or "").strip(),
            "synopsis": _sanitize_rich_html_for_dark(str(self.synopsis_edit.toHtml() or "").strip()),
            "status_id": str(self.status_cb.currentData() or ""),
            "season_id": str(self.story_season_cb.currentData() or "season_all"),
            "arc_id": str(self.story_arc_cb.currentData() or "arc_all"),
            "section_ids": [x for x in sec_ids if x],
            "assignments": self._draft.get("assignments", {}),
            "archived": bool(self._draft.get("archived", False)),
        }
        try:
            self.storage.update_story(sid, patch)
        except Exception:
            return
        self._stories = self.storage.get_stories()
        self._set_editing(False)
        self._refresh_story_list()
        self._select_story(sid)
        try:
            self.stories_changed.emit()
        except Exception:
            pass

    def _people_by_role_id(self, role_id: str) -> list[_Person]:
        target_role_id = str(role_id or "")
        if not target_role_id:
            return []

        # Build people list: admin + subjects, filtered by role id.
        profile = self.storage.get_profile()
        admin_name = str(profile.get("nickname") or "Администратор")
        admin_roles = [str(x) for x in (profile.get("role_ids") or []) if str(x)]
        people: list[_Person] = [_Person(id="__admin__", name=admin_name, role_ids=admin_roles)]
        for s in self.storage.get_subjects():
            sid = str(s.get("id") or "")
            if not sid:
                continue
            role_ids = [str(x) for x in (s.get("role_ids") or []) if str(x)]
            people.append(_Person(id=sid, name=str(s.get("nickname") or ""), role_ids=role_ids))
        # Exclude "Без роли"
        people = [
            p for p in people if target_role_id in [rid for rid in p.role_ids if rid != SYSTEM_NONE_ROLE_ID]
        ]
        people.sort(key=lambda p: (0 if p.id == "__admin__" else 1, _norm(p.name)))
        return people

    def _refresh_role_chips(self, role_id: str) -> None:
        sid = str(self._selected_story_id or "")
        story = next((s for s in self._stories if str(s.get("id")) == sid), None)
        if not isinstance(story, dict):
            return

        rid = str(role_id or "")
        people = self._people_by_role_id(rid)
        q = _norm(self._role_boxes[rid]["search"].text())
        if q:
            people = [p for p in people if q in _norm(p.name)]

        # While editing, selection lives in _draft; using saved story here drops unsaved picks
        # and rebuild-from-search fires toggled -> _toggle and corrupts the draft.
        if self._editing and isinstance(self._draft, dict):
            da = self._draft.get("assignments")
            assignments = da if isinstance(da, dict) else {}
        else:
            assignments = story.get("assignments") if isinstance(story.get("assignments"), dict) else {}
        selected = set([str(x) for x in (assignments.get(rid) or []) if str(x)])

        def _toggle(pid: str, on: bool) -> None:
            # Must read current draft each time — `selected` is frozen at last refresh;
            # otherwise the 2nd+ click in the same role rebuilds cur from stale set and drops prior picks.
            if not self._editing or not isinstance(self._draft, dict):
                return
            d_as = self._draft.get("assignments")
            if not isinstance(d_as, dict):
                d_as = {}
            cur_list = d_as.get(rid) or []
            if not isinstance(cur_list, list):
                cur_list = []
            cur = {str(x) for x in cur_list if str(x)}
            if on:
                cur.add(str(pid))
            else:
                cur.discard(str(pid))
            self._draft["assignments"] = {**d_as, rid: sorted(cur)}

        self._role_boxes[rid]["chips"].set_items(
            [(p.id, p.name) for p in people],
            selected=selected,
            on_toggle=_toggle,
        )

    def _on_add_story(self) -> None:
        # Minimal add: creates blank story in current season/arc filter.
        season_id = str(self.season_cb.currentData() or "").strip()
        arc_id = str(self.arc_cb.currentData() or "").strip()
        try:
            st = self.storage.add_story(
                {
                    "season_id": season_id if season_id and season_id != "season_all" else "season_all",
                    "arc_id": arc_id if arc_id and arc_id != "arc_all" else "arc_all",
                    "title": "Новая история",
                    "source_url": "",
                    "synopsis": "",
                    "assignments": {},
                    "archived": False,
                }
            )
        except Exception:
            return
        self._stories = self.storage.get_stories()
        self._rebuild_taxonomy_options()
        self._refresh_story_list()
        self._selected_story_id = str(st.get("id") or "")
        self._select_story(self._selected_story_id)
        # Auto-enter edit mode for newly created story.
        self._enter_edit_mode()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _on_open_url(self) -> None:
        url = str(self.url_edit.text() or "").strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        QDesktopServices.openUrl(url)

    def _on_toggle_archive(self) -> None:
        sid = str(self._selected_story_id or "")
        story = next((s for s in self._stories if str(s.get("id")) == sid), None)
        if not isinstance(story, dict):
            return
        if not self._editing or not isinstance(self._draft, dict):
            return
        new_val = not bool(self._draft.get("archived", False))
        self._draft["archived"] = bool(new_val)
        self.archive_btn.setText("Восстановить" if bool(new_val) else "В архив")

    # --- Synopsis (rich text like task description) ---
    def _set_synopsis_from_storage(self, text: str) -> None:
        s = _sanitize_rich_html_for_dark((text or "").strip())
        # Backward compat: allow plain text in older DBs.
        if "<" in s and ">" in s and ("</" in s or "<br" in s or "<p" in s):
            self.synopsis_edit.setHtml(s)
        else:
            self.synopsis_edit.setPlainText(s)

    def _syn_merge_char_format(self, fmt: QTextCharFormat) -> None:
        c = self.synopsis_edit.textCursor()
        if not c.hasSelection():
            self.synopsis_edit.mergeCurrentCharFormat(fmt)
        else:
            c.mergeCharFormat(fmt)
            self.synopsis_edit.setTextCursor(c)

    def _syn_fmt_bold(self) -> None:
        fmt = QTextCharFormat()
        w = self.synopsis_edit.fontWeight()
        fmt.setFontWeight(400 if int(w) >= 600 else 700)
        self._syn_merge_char_format(fmt)

    def _syn_fmt_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.synopsis_edit.fontItalic())
        self._syn_merge_char_format(fmt)

    def _syn_fmt_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.synopsis_edit.fontUnderline())
        self._syn_merge_char_format(fmt)

    def _syn_fmt_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not fmt.fontStrikeOut())
        cur = self.synopsis_edit.textCursor()
        if cur.hasSelection():
            fmt.setFontStrikeOut(not cur.charFormat().fontStrikeOut())
        else:
            fmt.setFontStrikeOut(not self.synopsis_edit.currentCharFormat().fontStrikeOut())
        self._syn_merge_char_format(fmt)

    def _syn_toggle_list(self, style: QTextListFormat.Style) -> None:
        cur = self.synopsis_edit.textCursor()
        cur.beginEditBlock()
        try:
            cur_list = cur.currentList()
            if cur_list is not None and cur_list.format().style() == style:
                # Remove list formatting from selected blocks (or current block).
                doc = cur.document()
                start = cur.selectionStart()
                end = cur.selectionEnd()
                tmp = QTextCursor(doc)
                tmp.setPosition(start)
                tmp.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                while True:
                    bf = tmp.blockFormat()
                    bf.setObjectIndex(-1)
                    tmp.setBlockFormat(bf)
                    if tmp.position() >= end:
                        break
                    if not tmp.movePosition(QTextCursor.MoveOperation.NextBlock):
                        break
                return

            lf = QTextListFormat()
            lf.setStyle(style)
            cur.createList(lf)
        finally:
            cur.endEditBlock()

    def _syn_fmt_bullets(self) -> None:
        self._syn_toggle_list(QTextListFormat.Style.ListDisc)

    def _syn_fmt_numbers(self) -> None:
        self._syn_toggle_list(QTextListFormat.Style.ListDecimal)

    def _syn_fmt_link(self) -> None:
        url, ok = QInputDialog.getText(self, "Вставить ссылку", "URL (например https://example.com):")
        if not ok:
            return
        url = str(url or "").strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        cur = self.synopsis_edit.textCursor()
        sel_text = cur.selectedText().replace("\u2029", "\n")
        text = sel_text.strip() or url
        cur.insertHtml(f'<a href="{_html_escape(url)}">{_html_escape(text)}</a>')

    def _syn_fmt_unlink(self) -> None:
        cur = self.synopsis_edit.textCursor()
        fmt = QTextCharFormat()
        fmt.setAnchor(False)
        fmt.clearProperty(QTextFormat.Property.AnchorHref)
        fmt.clearProperty(QTextFormat.Property.AnchorName)
        if cur.hasSelection():
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.NoUnderline)
            text_clr = self.synopsis_edit.palette().color(QPalette.ColorRole.Text)
            fmt.setForeground(QBrush(text_clr))
        if not cur.hasSelection():
            self.synopsis_edit.mergeCurrentCharFormat(fmt)
            return
        cur.beginEditBlock()
        cur.mergeCharFormat(fmt)
        cur.endEditBlock()
        self.synopsis_edit.setTextCursor(cur)


class _ChipList(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []
        self._selected: set[str] = set()
        self._on_toggle: Callable[[str, bool], None] | None = None

        self._wrap = QWidget()
        self._flow = FlowLayout(self._wrap, margin=0, h_spacing=8, v_spacing=8)
        self._wrap.setLayout(self._flow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._wrap)

    def set_items(self, items: list[tuple[str, str]], *, selected: set[str], on_toggle: Callable[[str, bool], None]) -> None:
        self._items = list(items)
        self._selected = set([str(x) for x in selected])
        self._on_toggle = on_toggle
        self._rebuild()

    def _rebuild(self) -> None:
        while self._flow.count():
            it = self._flow.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

        for pid, name in self._items:
            b = QPushButton(str(name or "—"))
            b.setCheckable(True)
            b.blockSignals(True)
            b.setChecked(str(pid) in self._selected)
            b.blockSignals(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{padding:6px 10px; border-radius:14px; text-align:left;}"
                "QPushButton:checked{background: rgba(90,160,255,0.35); border: 1px solid rgba(90,160,255,0.55);}"
            )

            def _mk(pid_=str(pid)) -> Callable[[bool], None]:
                return lambda on: self._on_toggle(pid_, bool(on)) if callable(self._on_toggle) else None

            b.toggled.connect(_mk())
            self._flow.addWidget(b)


class _StoriesListWidget(QListWidget):
    order_dropped = Signal()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        super().dropEvent(event)
        try:
            self.order_dropped.emit()
        except Exception:
            pass


class _StoryCardTitleEdit(QTextEdit):
    """Read-only multi-line title that wraps like task titles."""

    def __init__(self, text: str, *, color_hex: str | None = None) -> None:
        super().__init__()
        self.setObjectName("StoryCardTitle")
        self.setPlainText(str(text or ""))
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(False)
        # QTextEdit has its own viewport + internal padding; force to zero so it aligns with QLabel below.
        self.setViewportMargins(0, 0, 0, 0)
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
        # Force transparency: some global stylesheets may still paint QTextEdit background.
        f = QFont()
        # Make title noticeably larger than status, but keep wrapping behavior intact.
        f.setPointSize(max(13, int(f.pointSize() * 1.45)))
        f.setBold(True)
        self.setFont(f)
        try:
            self.document().setDefaultFont(f)
        except Exception:
            pass

        # Force font size at stylesheet level too (some global styles override QTextEdit font).
        fs_pt = max(13, int(f.pointSize()))
        c = str(color_hex or "").strip() or None
        color_css = f"color:{c};" if c else ""
        self.setStyleSheet(
            "QTextEdit#StoryCardTitle{"
            "background: transparent; border: none; font-weight:800; padding:0px; margin:0px;"
            f"font-size:{fs_pt}pt;"
            f"{color_css}"
            "}"
        )

        self.textChanged.connect(self._update_height)
        self._last_h = 40

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
        self._last_h = max(40, h)
        self.setFixedHeight(self._last_h)
        # Ask the card to recompute its size (and update QListWidget item sizeHint).
        p = self.parent()
        if p is not None and hasattr(p, "_sync_height"):
            try:
                p._sync_height()  # type: ignore[attr-defined]
            except Exception:
                pass


class _StoryCard(QFrame):
    def __init__(
        self,
        *,
        title: str,
        status_name: str,
        status_color: str,
        assignments: dict[str, Any],
        people_name_by_id: dict[str, str],
        role_color_by_id: dict[str, str],
        on_height_changed: Callable[[int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StoryCard")
        self._on_height_changed = on_height_changed
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        # Left: title (big, multi-line) + status (smaller)
        self._left = QWidget()
        self._left.setStyleSheet("background: transparent;")
        self._left_l = QVBoxLayout(self._left)
        self._left_l.setContentsMargins(0, 0, 0, 0)
        self._left_l.setSpacing(4)

        self._title = _StoryCardTitleEdit(title, color_hex=str(status_color or "").strip() or None)
        self._status = QLabel(str(status_name or "—"))
        self._status.setStyleSheet(
            f"color:{str(status_color or '#9E9E9E')}; background: transparent; border: none; font-size: 9pt; font-weight:800; padding:0px; margin:0px;"
        )
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._status.setContentsMargins(0, 0, 0, 0)

        self._left_l.addWidget(self._title, 0)
        self._left_l.addWidget(self._status, 0)
        self._left_l.addStretch(1)

        # Left must keep its share; otherwise it can shrink to 1-char width.
        outer.addWidget(self._left, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # Right: assignees, colored by role colors (no role labels).
        self._assignees = QLabel(self._format_assignees(assignments, people_name_by_id, role_color_by_id))
        self._assignees.setTextFormat(Qt.TextFormat.RichText)
        self._assignees.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._assignees.setWordWrap(True)
        # Use muted fg if possible, but keep background transparent.
        pal = self.palette()
        muted = pal.color(QPalette.ColorRole.Mid).name() if pal else "#BDBDBD"
        self._assignees.setStyleSheet(f"color:{muted}; background: transparent; font-size: 9pt;")
        outer.addWidget(self._assignees, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        # Card-like feel without relying on the global "Card" styles.
        self.setStyleSheet(
            "QFrame#StoryCard{border-radius:12px; border:1px solid rgba(255,255,255,0.14); background: rgba(0,0,0,0.10);}"
        )

        # Initial sizing (QTextEdit will refine after show/resize).
        self._sync_height()

    def sizeHint(self) -> QSize:  # type: ignore[override]
        # Slightly taller than default list rows.
        return QSize(320, max(96, int(self.minimumHeight() or 96)))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Limit title line length to ~middle of the card (keep room for assignees on the right).
        w = max(0, int(self.width()))
        left_w = max(260, int(w * 0.55))
        self._left.setMinimumWidth(min(left_w, max(260, int(w * 0.70))))
        self._left.setMaximumWidth(left_w)
        self._title.setMaximumWidth(left_w)
        self._status.setMaximumWidth(left_w)
        self._sync_height()

    def _sync_height(self) -> None:
        # Compute required height so content never gets clipped:
        # - left side: title + status
        # - right side: assignees (wrapped)
        m = self.layout().contentsMargins() if self.layout() is not None else None
        top = int(m.top()) if m else 0
        bottom = int(m.bottom()) if m else 0
        spacing = int(self.layout().spacing()) if self.layout() is not None else 0
        title_h = int(self._title.height() or self._title.sizeHint().height() or 34)
        status_h = int(self._status.sizeHint().height() or 16)

        left_h = title_h + spacing + status_h

        # QLabel height depends on its width when wordWrap is on; prefer heightForWidth.
        try:
            aw = int(self._assignees.width() or 0)
            right_h = int(self._assignees.heightForWidth(aw)) if aw > 0 else int(self._assignees.sizeHint().height() or 0)
        except Exception:
            right_h = int(self._assignees.sizeHint().height() or 0)

        content_h = max(int(left_h), int(right_h))
        h = top + bottom + content_h + 8
        h = max(96, int(h))
        self.setMinimumHeight(int(h))
        if callable(self._on_height_changed):
            try:
                self._on_height_changed(int(h))
            except Exception:
                pass
        self.updateGeometry()

    @staticmethod
    def _format_assignees(
        assignments: dict[str, Any],
        people_name_by_id: dict[str, str],
        role_color_by_id: dict[str, str],
    ) -> str:
        parts: list[str] = []
        if not isinstance(assignments, dict):
            return ""
        # Deterministic order: sort by role_id so it doesn't "jump".
        for rid in sorted([str(x) for x in assignments.keys() if str(x)]):
            pids = assignments.get(rid)
            if not isinstance(pids, list):
                continue
            color = str(role_color_by_id.get(rid) or "#BDBDBD")
            for pid in [str(x) for x in pids if str(x)]:
                name = str(people_name_by_id.get(pid) or "")
                if not name:
                    continue
                safe = (
                    name.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#39;")
                )
                parts.append(f"<span style='color:{color}; font-weight:700'>{safe}</span>")
        # Wrap automatically; keep it compact.
        return ", ".join(parts)
