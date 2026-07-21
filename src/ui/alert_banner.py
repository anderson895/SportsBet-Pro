"""Alert banner — kapansin-pansing (pero non-blocking) na error alert sa UI.

Lumalabas sa taas ng panel tuwing may ERROR-level event (failed order,
live setup failure, atbp.). Hindi popup/dialog para hindi ma-block ang bot
loop; dismissible via ✕ at nagpapakita ng bilang kapag sunud-sunod ang errors.
"""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton

from src.ui import theme


class AlertBanner(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("alertBanner")
        self.setStyleSheet(
            f"""
            QFrame#alertBanner {{
                background: #7f1d1d;
                border: 1px solid {theme.RED};
                border-radius: 8px;
            }}
            QFrame#alertBanner QLabel {{
                color: #fecaca;
                font-weight: bold;
            }}
            """
        )

        icon = QLabel()
        icon.setPixmap(
            qta.icon("fa6s.triangle-exclamation", color="#fecaca").pixmap(18, 18)
        )
        self._label = QLabel("")
        self._label.setWordWrap(True)

        close = QToolButton()
        close.setIcon(qta.icon("fa6s.xmark", color="#fecaca"))
        close.setStyleSheet("border: none; background: transparent")
        close.clicked.connect(self.dismiss)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.addWidget(icon)
        row.addWidget(self._label, stretch=1)
        row.addWidget(close)

        self._count = 0
        self.hide()

    def show_error(self, message: str) -> None:
        self._count += 1
        prefix = f"({self._count} errors) " if self._count > 1 else ""
        self._label.setText(f"{prefix}{message}")
        self.show()

    def dismiss(self) -> None:
        self._count = 0
        self.hide()
