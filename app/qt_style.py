from __future__ import annotations

from app.theme import Palette


def build_stylesheet(p: Palette) -> str:
    # Keep it simple: apply a modern dark/light look using Qt stylesheets.
    return f"""
    QWidget {{
        background: {p.bg};
        color: {p.fg};
        font-family: "Segoe UI";
        font-size: 10pt;
    }}

    QLabel {{
        background: transparent;
    }}

    QMainWindow::separator {{
        background: {p.surface2};
        width: 1px;
        height: 1px;
    }}

    QFrame#Card {{
        background: rgba(18,18,18,0.95);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 10px;
    }}

    /* Prevent "label blocks" inside cards (transparent text background) */
    QFrame#Card QLabel {{
        background: transparent;
    }}

    QFrame#PeoplePanel {{
        background: {p.bg};
        border-right: 1px solid {p.surface2};
    }}

    QFrame#ColumnCard {{
        background: transparent;
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 12px;
    }}

    QFrame#ColumnHeader {{
        background: transparent;
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        border-bottom: 1px solid rgba(255,255,255,0.10);
    }}

    /* Column body is a "window" showing the page background image */
    QFrame#ColumnBody {{
        background: transparent;
        border-bottom-left-radius: 12px;
        border-bottom-right-radius: 12px;
    }}

    QFrame#ColumnCard QScrollArea {{
        background: transparent;
    }}
    /* Only the scroll area viewport should be transparent (not the task cards inside). */
    QFrame#ColumnCard QScrollArea QWidget#qt_scrollarea_viewport {{
        background: transparent;
    }}

    QLabel#ColumnTitle {{
        font-size: 14pt;
        font-weight: 800;
        color: {p.fg};
    }}

    QPushButton#PeopleArrow {{
        background: {p.surface2};
        border: 1px solid {p.surface};
        border-radius: 10px;
        padding: 0px;
        font-size: 14pt;
        font-weight: 900;
    }}
    QPushButton#PeopleArrow:hover {{
        background: {p.surface};
    }}

    QLabel#H1 {{
        font-size: 18pt;
        font-weight: 700;
    }}

    QLabel#H2 {{
        font-size: 13pt;
        font-weight: 700;
    }}

    QPushButton {{
        background: {p.surface2};
        border: 1px solid {p.surface};
        border-radius: 8px;
        padding: 6px 10px;
    }}
    QPushButton:hover {{
        background: {p.surface};
    }}
    QPushButton:pressed {{
        background: {p.surface};
        border-color: {p.accent};
    }}
    QPushButton:disabled {{
        color: {p.muted_fg};
    }}

    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateTimeEdit {{
        background: {p.entry_bg};
        color: {p.entry_fg};
        border: 1px solid {p.surface2};
        border-radius: 8px;
        padding: 6px 8px;
        selection-background-color: {p.accent};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus, QDateTimeEdit:focus {{
        border-color: {p.accent};
    }}

    /* Task card title (overrides generic QTextEdit above) */
    QFrame#Card QTextEdit#TaskCardTitle {{
        background: transparent;
        border: none;
        padding: 0px;
        font-weight: 700;
        color: {p.fg};
        selection-background-color: {p.accent};
        selection-color: #FFFFFF;
    }}
    QFrame#Card QTextEdit#TaskCardTitle:focus {{
        border: none;
    }}

    /* Spinbox: keep native arrows visible and easy to click */
    QSpinBox {{
        padding-right: 10px;
        min-height: 32px;
    }}

    /* Calendar popup (QDateTimeEdit -> QCalendarWidget) */
    QCalendarWidget {{
        background: {p.surface};
        border: 1px solid {p.surface2};
        border-radius: 10px;
    }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{
        min-height: 34px;
        background: {p.surface2};
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
    }}
    QCalendarWidget QToolButton {{
        background: transparent;
        border: none;
        padding: 2px 6px;
        margin: 0px;
        color: {p.fg};
        font-weight: 600;
    }}
    QCalendarWidget QToolButton:hover {{
        background: rgba(255,255,255,0.08);
        border-radius: 8px;
    }}
    /* Override global spinbox sizing inside calendar to prevent layout glitches */
    QCalendarWidget QSpinBox {{
        min-height: 26px;
        padding-right: 0px;
        padding-left: 6px;
        padding-top: 0px;
        padding-bottom: 0px;
        margin: 0px;
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 8px;
        background: {p.entry_bg};
        color: {p.entry_fg};
    }}
    QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button {{
        width: 0px;
        height: 0px;
    }}
    QCalendarWidget QSpinBox::up-arrow, QCalendarWidget QSpinBox::down-arrow {{
        width: 0px;
        height: 0px;
    }}

    QTabWidget::pane {{
        border: 1px solid {p.surface2};
        border-radius: 10px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: {p.surface2};
        border: 1px solid {p.surface2};
        padding: 8px 12px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        margin-right: 4px;
    }}
    QTabBar::tab:selected {{
        background: {p.surface};
        border-color: {p.surface};
    }}

    QTableWidget, QTreeWidget {{
        background: {p.entry_bg};
        border: 1px solid {p.surface2};
        border-radius: 10px;
        gridline-color: {p.surface2};
        selection-background-color: {p.accent};
        selection-color: #FFFFFF;
    }}

    QHeaderView::section {{
        background: {p.surface2};
        color: {p.fg};
        padding: 6px 8px;
        border: none;
        border-bottom: 1px solid {p.surface};
    }}
    """

