from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface2: str
    fg: str
    muted_fg: str
    accent: str
    danger: str

    entry_bg: str
    entry_fg: str

    nav_bg: str
    nav_btn_bg: str
    nav_btn_bg_active: str
    nav_btn_fg: str


def get_palette(theme: str) -> Palette:
    if theme == "light":
        return Palette(
            bg="#F6F7FB",
            surface="#FFFFFF",
            surface2="#EEF1F7",
            fg="#121317",
            muted_fg="#5B606B",
            accent="#2D6CDF",
            danger="#C62828",
            entry_bg="#FFFFFF",
            entry_fg="#121317",
            nav_bg="#FFFFFF",
            nav_btn_bg="#EEF1F7",
            nav_btn_bg_active="#2D6CDF",
            nav_btn_fg="#121317",
        )
    return Palette(
        bg="#1F1F1F",
        surface="#242424",
        surface2="#2F2F2F",
        fg="#F1F1F1",
        muted_fg="#B7B7B7",
        accent="#3A7CFF",
        danger="#EF5350",
        entry_bg="#242424",
        entry_fg="#F1F1F1",
        nav_bg="#1B1B1B",
        nav_btn_bg="#2A2A2A",
        nav_btn_bg_active="#3A7CFF",
        nav_btn_fg="#F1F1F1",
    )

