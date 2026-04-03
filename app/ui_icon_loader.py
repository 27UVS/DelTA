from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageTk


@dataclass(frozen=True)
class LoadedIcon:
    image: tk.PhotoImage
    path: Path


class IconLoader:
    """
    Tkinter requires keeping references to PhotoImage objects.
    This loader caches icons per-instance to avoid GC issues.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, int], LoadedIcon] = {}

    def load_png(self, path: Path, size: tuple[int, int]) -> tk.PhotoImage | None:
        key = (str(path), int(size[0]), int(size[1]))
        if key in self._cache:
            return self._cache[key].image
        if not path.exists():
            return None
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((int(size[0]), int(size[1])), Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            self._cache[key] = LoadedIcon(image=photo, path=path)
            return photo
        except Exception:
            return None

    def load_color_swatch(self, hex_color: str, size: tuple[int, int]) -> tk.PhotoImage:
        # Cache by a synthetic key.
        color = (hex_color or "#BDBDBD").strip()
        key = (f"swatch:{color}", int(size[0]), int(size[1]))
        if key in self._cache:
            return self._cache[key].image
        img = Image.new("RGBA", (int(size[0]), int(size[1])), color=color)
        photo = ImageTk.PhotoImage(img)
        self._cache[key] = LoadedIcon(image=photo, path=Path(key[0]))
        return photo

