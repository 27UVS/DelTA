from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """
    Minimal wrapping layout for "chips" (pill buttons).
    Avoids rebuilding widgets on resize (prevents jitter/oscillation).
    """

    def __init__(self, parent: QWidget | None = None, margin: int = 0, h_spacing: int = 8, v_spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h = int(h_spacing)
        self._v = int(v_spacing)
        self.setContentsMargins(int(margin), int(margin), int(margin), int(margin))

    def addItem(self, item: QLayoutItem) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:  # type: ignore[override]
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:  # type: ignore[override]
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        return self._do_layout(QRect(0, 0, int(width), 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # type: ignore[override]
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        l, t, r, b = self.getContentsMargins()
        s += QSize(l + r, t + b)
        return s

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        l, t, r, b = self.getContentsMargins()
        x = rect.x() + l
        y = rect.y() + t
        line_h = 0
        effective_w = max(1, rect.width() - l - r)
        right_edge = rect.x() + l + effective_w

        for it in self._items:
            w = it.widget()
            if w is not None:
                w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            hint = it.sizeHint()
            next_x = x + hint.width() + self._h
            if next_x - self._h > right_edge and line_h > 0:
                x = rect.x() + l
                y += line_h + self._v
                next_x = x + hint.width() + self._h
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())

        return y + line_h + b - rect.y()

