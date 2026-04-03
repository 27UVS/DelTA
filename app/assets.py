from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class InterfaceAssets:
    base_dir: Path
    interface_dir: Path

    add_button_png: Path
    edit_button_png: Path
    delete_button_png: Path
    color_button_png: Path
    filter_button_png: Path
    link_button_png: Path
    settings_active_png: Path
    settings_default_png: Path

    icon_png: Path
    icon_ico: Path


def get_interface_assets() -> InterfaceAssets:
    if getattr(sys, "frozen", False):
        # In PyInstaller onefile builds, resources live under sys._MEIPASS (temp dir).
        # In onedir builds, this usually points to the app directory as well.
        base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base_dir = Path(__file__).resolve().parent.parent
    interface_dir = base_dir / "assets" / "interface"
    return InterfaceAssets(
        base_dir=base_dir,
        interface_dir=interface_dir,
        add_button_png=interface_dir / "add_button.png",
        edit_button_png=interface_dir / "edit_button.png",
        delete_button_png=interface_dir / "delete_button.png",
        color_button_png=interface_dir / "color_button.png",
        filter_button_png=interface_dir / "filter_button.png",
        link_button_png=interface_dir / "link_button.png",
        settings_active_png=interface_dir / "settings_active_button.png",
        settings_default_png=interface_dir / "settings_default_button.png",
        icon_png=interface_dir / "icon.png",
        icon_ico=interface_dir / "icon_small.ico",
    )

