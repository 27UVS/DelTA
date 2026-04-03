from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class LoadingOverlay(QWidget):
    """
    Simple full-window overlay to show progress text while the UI thread is busy.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        backdrop = QFrame()
        backdrop.setObjectName("LoadingOverlayBackdrop")
        root.addWidget(backdrop, 1)

        b = QVBoxLayout(backdrop)
        b.setContentsMargins(24, 24, 24, 24)
        b.setSpacing(14)
        b.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("LoadingOverlayCard")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(18, 18, 18, 18)
        card_l.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)

        self.icon = QLabel()
        self.icon.setFixedSize(48, 48)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.icon, 0)

        self.title = QLabel("Подождите. Настройки применяются")
        self.title.setObjectName("LoadingOverlayTitle")
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)

        card_l.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # indefinite
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(360)
        card_l.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignCenter)

        b.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)

        self.hide()

    def set_icon(self, icon: QIcon | None) -> None:
        if not icon or icon.isNull():
            self.icon.clear()
            return
        pm = icon.pixmap(48, 48)
        self.icon.setPixmap(pm)

    def show_over(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        QApplication.processEvents()

    def hide_overlay(self) -> None:
        self.hide()

