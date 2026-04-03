from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QIcon, QImage, QPixmap, QColor


@dataclass(frozen=True)
class LoadedQtIcon:
    icon: QIcon
    path: Path


class QtIconLoader:
    """
    Small helper to load/caches icons for Qt widgets.
    """

    def __init__(self) -> None:
        self._icon_cache: dict[str, QIcon] = {}
        self._pix_cache: dict[tuple[str, int, int], QPixmap] = {}

    def load_icon(self, path: Path) -> QIcon:
        key = str(path)
        if key in self._icon_cache:
            return self._icon_cache[key]
        if not path.exists():
            icon = QIcon()
        else:
            icon = QIcon(str(path))
        self._icon_cache[key] = icon
        return icon

    def load_pixmap(self, path: Path, size: tuple[int, int] | None = None) -> QPixmap | None:
        if not path.exists():
            return None
        if size is None:
            key = (str(path), -1, -1)
        else:
            key = (str(path), int(size[0]), int(size[1]))
        if key in self._pix_cache:
            return self._pix_cache[key]

        img = QImage(str(path))
        if img.isNull():
            return None
        if size is not None:
            img = img.scaled(int(size[0]), int(size[1]))
        pix = QPixmap.fromImage(img)
        self._pix_cache[key] = pix
        return pix

    def color_swatch(self, hex_color: str, size: tuple[int, int]) -> QPixmap:
        color = (hex_color or "#BDBDBD").strip()
        key = (f"swatch:{color}", int(size[0]), int(size[1]))
        if key in self._pix_cache:
            return self._pix_cache[key]
        w, h = int(size[0]), int(size[1])
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor(color))
        pix = QPixmap.fromImage(img)
        self._pix_cache[key] = pix
        return pix

