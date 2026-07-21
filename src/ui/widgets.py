"""Reusable card widgets para sa dashboard."""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from src.ui import theme


class WheelBlocker(QObject):
    """Hinaharangan ang mouse-wheel sa spinboxes/dropdowns.

    Kapag nag-i-scroll ang user sa page at nadaanan ng cursor ang isang
    input, nababago ang value nang hindi napapansin — delikado ito sa
    mga setting tulad ng Risk USDC o Trading Mode. Type, click, at ang
    +/− buttons pa rin ang paraan ng pagpalit.
    """

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if event.type() == QEvent.Type.Wheel:
            return True  # i-block — huwag baguhin ang value
        return super().eventFilter(obj, event)


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)


class StatusCard(Card):
    """Connection card: icon + pangalan + Connected/Disconnected + dot."""

    def __init__(self, icon: str, name: str, icon_color: str = theme.MUTED) -> None:
        super().__init__()
        self._icon = QLabel()
        self._icon.setPixmap(qta.icon(icon, color=icon_color).pixmap(26, 26))
        self._name = QLabel(name)
        self._name.setStyleSheet("font-weight: bold; font-size: 14px")
        self._sub = QLabel("Checking…")
        self._sub.setProperty("muted", True)
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {theme.MUTED}; font-size: 15px")

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(self._name)
        text_col.addWidget(self._sub)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.addWidget(self._icon)
        row.addLayout(text_col, stretch=1)
        row.addWidget(self._dot)

    def set_state(self, up: bool) -> None:
        color = theme.GREEN if up else theme.RED
        self._sub.setText("Connected" if up else "Disconnected")
        self._sub.setStyleSheet(f"color: {color}")
        self._dot.setStyleSheet(f"color: {color}; font-size: 15px")


class StatCard(Card):
    """Card na may title, malaking value, at optional sub-line."""

    def __init__(self, title: str, value: str = "—", sub: str = "") -> None:
        super().__init__()
        self._title = QLabel(title)
        self._title.setProperty("muted", True)
        self._value = QLabel(value)
        self._value.setStyleSheet("font-size: 20px; font-weight: bold")
        self._sub = QLabel(sub)
        self._sub.setProperty("muted", True)

        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(3)
        col.addWidget(self._title)
        col.addWidget(self._value)
        if sub:
            col.addWidget(self._sub)

    def set_value(self, text: str, color: str | None = None) -> None:
        self._value.setText(text)
        style = "font-size: 20px; font-weight: bold"
        if color:
            style += f"; color: {color}"
        self._value.setStyleSheet(style)

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_sub(self, text: str) -> None:
        self._sub.setText(text)
