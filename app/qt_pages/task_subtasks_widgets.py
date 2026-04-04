from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont
from PySide6.QtWidgets import QWidget

from app.task_subtasks import get_subtasks_from_task, subtasks_done_count

_GRAY_LINE = QColor(120, 130, 120, 220)
_GREEN_LINE = QColor(80, 180, 100, 255)
_GRAY_DOT = QColor(100, 110, 100, 255)
_GREEN_DOT = QColor(70, 160, 90, 255)
_DOT_BORDER = QColor(255, 255, 255, 90)

# Above this count, the board strip is a single percentage bar (no per-subtask dots).
_COMPACT_DOT_THRESHOLD = 18

# SubtaskChainDetailWidget geometry (must stay in sync with paintEvent).
_DETAIL_PAD_EDGE = 10
_DETAIL_LABEL_H = 30
_DETAIL_DOT_R = 6.0
_DETAIL_ROW_GAP = 12
# Space between bottom of assignee line and top of dot (keeps names from sitting on the circle).
_DETAIL_LABEL_CLEAR = 5


def _detail_row_step_px() -> int:
    return int(_DETAIL_DOT_R * 2 + _DETAIL_ROW_GAP + _DETAIL_LABEL_H + _DETAIL_LABEL_CLEAR)


def _detail_first_row_center_y() -> int:
    return int(_DETAIL_PAD_EDGE + _DETAIL_LABEL_H + _DETAIL_DOT_R + _DETAIL_LABEL_CLEAR)


def _detail_chain_content_height(num_rows: int) -> int:
    """Total widget height for the snake chain; matches paintEvent vertical layout."""
    if num_rows <= 0:
        return 0
    step = _detail_row_step_px()
    y_last = _detail_first_row_center_y() + (num_rows - 1) * step
    return int(y_last + _DETAIL_DOT_R + _DETAIL_PAD_EDGE)


class SubtaskChainCompactWidget(QWidget):
    """Thin progress strip with dots for task cards on the board."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TaskCardSubtaskStrip")
        self._subtasks: list[dict[str, Any]] = []
        self.setFixedHeight(24)
        self.setMinimumWidth(40)

    def set_task(self, task: dict[str, Any]) -> None:
        self._subtasks = get_subtasks_from_task(task)
        self.setVisible(bool(self._subtasks))
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        subs = self._subtasks
        if not subs:
            return
        n = len(subs)
        done = subtasks_done_count(subs)
        w, h = self.width(), self.height()
        cy = h // 2
        pad = 8
        usable = max(1, w - 2 * pad)
        show_dots = n <= _COMPACT_DOT_THRESHOLD

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # Baseline (gray full width)
            pen = QPen(_GRAY_LINE)
            pen.setWidthF(3.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(pad, cy, w - pad, cy)

            # Green segment = done/total (same length scale as the gray line)
            if n > 0 and done > 0:
                frac = done / float(n)
                x2 = pad + frac * usable
                pen = QPen(_GREEN_LINE)
                pen.setWidthF(3.0)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(pad, cy, x2, cy)

            if not show_dots:
                return

            # Per-subtask dots (only when count is small enough)
            dot_r = 4.5
            if n == 1:
                xs = [pad + usable / 2.0]
            else:
                xs = [pad + (i / (n - 1)) * usable for i in range(n)]
            for i, x in enumerate(xs):
                st = subs[i]
                done_i = bool(st.get("done"))
                c = _GREEN_DOT if done_i else _GRAY_DOT
                painter.setPen(QPen(_DOT_BORDER, 1.0))
                painter.setBrush(c)
                painter.drawEllipse(QRectF(x - dot_r, cy - dot_r, dot_r * 2, dot_r * 2))
        finally:
            painter.end()


class SubtaskChainDetailWidget(QWidget):
    """Multi-row snake chain with labels (dialogs)."""

    def __init__(
        self,
        *,
        task: dict[str, Any],
        name_by_id: dict[str, str],
        max_per_row: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._subs = get_subtasks_from_task(task)
        self._names = name_by_id
        self._max = max(2, min(24, int(max_per_row)))
        self.setMinimumWidth(320)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return self.minimumSizeHint()

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        subs = self._subs
        if not subs:
            return QSize(0, 0)
        rows = _chunk(subs, self._max)
        h = _detail_chain_content_height(len(rows))
        # Side insets for labels (must match paintEvent).
        side_reserve = 56
        min_w = max(400, side_reserve * 2 + 80)
        return QSize(min_w, h)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        subs = self._subs
        if not subs:
            return

        w = self.width()
        pad_edge = float(_DETAIL_PAD_EDGE)
        label_h = _DETAIL_LABEL_H
        dot_r = _DETAIL_DOT_R
        lbl_clear = float(_DETAIL_LABEL_CLEAR)
        row_step = _detail_row_step_px()

        chunks = _chunk(subs, self._max)
        # Precompute centers: (x, y, global_index, subtask)
        centers: list[tuple[float, float, int, dict[str, Any]]] = []
        y = float(_detail_first_row_center_y())
        gidx = 0
        for ri, chunk in enumerate(chunks):
            k = len(chunk)
            # Inset first/last dots so centered labels are not clipped at card edges.
            label_side_reserve = min(110.0, max(48.0, float(w) * 0.14))
            x0 = pad_edge + label_side_reserve
            x1 = float(w) - pad_edge - label_side_reserve
            if x1 <= x0:
                x0 = pad_edge + 20.0
                x1 = float(w) - pad_edge - 20.0
            span = max(1.0, x1 - x0)
            dx = span / max(k - 1, 1)
            if ri % 2 == 0:
                for j in range(k):
                    x = x0 + j * dx
                    centers.append((x, y, gidx, chunk[j]))
                    gidx += 1
            else:
                for j in range(k):
                    x = x0 + (k - 1 - j) * dx
                    centers.append((x, y, gidx, chunk[j]))
                    gidx += 1
            y += float(row_step)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            base_font = painter.font()
            small = QFont(base_font)
            small.setPointSize(max(7, small.pointSize() - 1))

            # Connectors + segments
            for i in range(len(centers) - 1):
                x1, y1, _, st1 = centers[i]
                x2, y2, _, st2 = centers[i + 1]
                seg_done = bool(st1.get("done"))
                col = _GREEN_LINE if seg_done else _GRAY_LINE
                pen = QPen(col)
                pen.setWidthF(2.8)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)

                same_row = abs(y1 - y2) < 1.0
                if same_row:
                    painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                else:
                    path = QPainterPath()
                    path.moveTo(x1, y1)
                    mx = (x1 + x2) / 2.0
                    # Nearly vertical run between rows: smooth outward bulge (semicircle-like).
                    if abs(x1 - x2) < 2.0 and abs(y1 - y2) > 4.0:
                        dy = y2 - y1
                        span = abs(dy)
                        bulge = min(span * 0.48, 36.0)
                        # Bulge outward (away from the middle of the chain), not inward.
                        on_right = mx > (w / 2.0)
                        cx = mx + bulge if on_right else mx - bulge
                        path.quadTo(cx, (y1 + y2) / 2.0, x2, y2)
                    else:
                        path.cubicTo(x1, y1 + 20, x2, y2 - 20, x2, y2)
                    painter.drawPath(path)

            # Labels fully above dots; bottom of assignee line sits lbl_clear px above dot top.
            for x, y, _, st in centers:
                title = str(st.get("title") or "")
                rid = str(st.get("responsible_subject_id") or "")
                if st.get("responsible_subject_ids"):
                    rid = str((st.get("responsible_subject_ids") or [rid])[0])
                rname = self._names.get(rid, "—")
                half_w = min(x - pad_edge, float(w) - pad_edge - x, 96.0)
                half_w = max(half_w, 22.0)
                tw = int(half_w * 2)
                text_bottom = y - dot_r - lbl_clear
                painter.setFont(small)
                sm_fm = painter.fontMetrics()
                t1 = sm_fm.elidedText(title, Qt.TextElideMode.ElideRight, tw)
                r2 = sm_fm.elidedText(rname, Qt.TextElideMode.ElideRight, tw)
                painter.setPen(QColor(220, 220, 220))
                painter.drawText(
                    QRectF(x - half_w, text_bottom - label_h, tw, label_h / 2),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    t1,
                )
                painter.drawText(
                    QRectF(x - half_w, text_bottom - label_h / 2, tw, label_h / 2),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    r2,
                )
                painter.setFont(base_font)

                done_i = bool(st.get("done"))
                c = _GREEN_DOT if done_i else _GRAY_DOT
                painter.setPen(QPen(_DOT_BORDER, 1.0))
                painter.setBrush(c)
                painter.drawEllipse(QRectF(x - dot_r, y - dot_r, dot_r * 2, dot_r * 2))
        finally:
            painter.end()


def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]
