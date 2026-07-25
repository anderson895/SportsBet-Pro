"""Reusable card / badge widgets para sa dashboard."""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from src.ui import theme


def panel_accent_qss(accent: str, accent_dim: str) -> str:
    """Stylesheet na ipinapatong sa isang exchange panel para ma-tint ang
    accent nito (sidebar selection, accent headers, Save button, sub-nav)
    nang hindi ginagalaw ang base palette."""
    return f"""
    QLabel[accent="true"] {{ color: {accent}; }}
    QListWidget#sidebar::item:selected {{
        background: {accent_dim}; color: {accent};
    }}
    QPushButton[navItem="true"][active="true"] {{
        color: {theme.TEXT}; border-bottom: 2px solid {accent};
    }}
    QPushButton#accentBtn {{ background: {accent}; color: #04160f; }}
    QPushButton#accentBtn:hover {{ background: {accent}; }}
    QPushButton#startBtn {{ background: {accent}; border: 1px solid {accent};
        color: #04160f; }}
    QPushButton#startBtn:hover {{ background: {accent}; }}
    QPushButton#startBtn:disabled {{ background: {accent_dim};
        color: {theme.FAINT}; border-color: {accent_dim}; }}
    QLabel[pill="ok"] {{ background: {accent_dim}; color: {accent}; }}
    QLabel[pill="outline"] {{ color: {accent}; border: 1px solid {accent}; }}
    /* Input focus + selection accents — per-exchange (indigo poly / mint kalshi) */
    QComboBox:focus, QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
    QPlainTextEdit:focus {{ border-color: {accent}; }}
    QLineEdit {{ selection-background-color: {accent_dim}; }}
    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {{
        background: {accent_dim}; color: {accent};
    }}
    QCheckBox::indicator:hover {{ border-color: {accent}; }}
    QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
    QTableWidget::item:selected {{ background: {accent_dim}; }}
    QPushButton[chip="true"]:hover {{ border-color: {accent}; }}
    QPushButton[chip="true"]:checked {{
        background: {accent_dim}; border: 1px solid {accent}; color: {accent};
    }}
    """


def run_async(coro) -> bool:
    """Patakbuhin ang coroutine sa qasync loop; True kung nag-schedule.

    Kapag walang running loop (hal. sa UI tests), isinasara ang coroutine —
    kung hindi ay maglalabas ng "coroutine was never awaited" na warning at
    matatagpuan ang tunay na warning sa dami ng ingay.
    """
    import asyncio

    try:
        asyncio.create_task(coro)
        return True
    except RuntimeError:
        coro.close()
        return False


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


class Pill(QLabel):
    """Maliit na colored badge para sa status (READY, RUNNING, atbp.)."""

    def __init__(self, text: str = "", level: str = "muted") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_level(level)

    def set(self, text: str, level: str) -> None:
        self.setText(text)
        self.set_level(level)

    def set_level(self, level: str) -> None:
        self.setProperty("pill", level)
        self.style().unpolish(self)
        self.style().polish(self)


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)


class StatusCard(Card):
    """Connection card: icon + pangalan + Connected/Disconnected + dot.

    Habang "Checking…" (wala pang alam na estado), ang dot ay dahan-dahang
    kumukurap (amber pulse); tumitigil kapag na-set na ang totoong estado.
    """

    def __init__(self, icon: str, name: str, icon_color: str = theme.MUTED) -> None:
        super().__init__()
        self._icon = QLabel()
        self._icon.setPixmap(qta.icon(icon, color=icon_color).pixmap(24, 24))
        self._name = QLabel(name)
        self._name.setStyleSheet("font-weight: 700; font-size: 14px")
        self._sub = QLabel("Checking…")
        self._sub.setProperty("muted", True)
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {theme.AMBER}; font-size: 16px")

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(self._name)
        text_col.addWidget(self._sub)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(12)
        row.addWidget(self._icon)
        row.addLayout(text_col, stretch=1)
        row.addWidget(self._dot)

        # Pulse timer para sa "Checking…" state
        self._pulse_on = True
        self._pulse = QTimer(self)
        self._pulse.setInterval(600)
        self._pulse.timeout.connect(self._tick_pulse)
        self._pulse.start()

    def _tick_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        color = theme.AMBER if self._pulse_on else theme.BORDER
        self._dot.setStyleSheet(f"color: {color}; font-size: 16px")

    def set_state(self, up: bool) -> None:
        self._pulse.stop()
        color = theme.GREEN if up else theme.RED
        self._sub.setText("Connected" if up else "Disconnected")
        self._sub.setStyleSheet(f"color: {color}; font-weight: 600")
        self._dot.setStyleSheet(f"color: {color}; font-size: 16px")


class StatCard(Card):
    """Card na may title, malaking value, at optional sub-line."""

    def __init__(self, title: str, value: str = "—", sub: str = "") -> None:
        super().__init__()
        self._title = QLabel(title.upper())
        self._title.setStyleSheet(
            f"color: {theme.FAINT}; font-weight: 700; font-size: 11px;"
            " letter-spacing: 0.6px"
        )
        self._value = QLabel(value)
        self._value.setStyleSheet("font-size: 21px; font-weight: 800")
        self._sub = QLabel(sub)
        self._sub.setProperty("muted", True)

        col = QVBoxLayout(self)
        col.setContentsMargins(16, 13, 16, 13)
        col.setSpacing(4)
        col.addWidget(self._title)
        col.addWidget(self._value)
        # LAGING idinadagdag, itinatago lang kapag walang laman. Kung hindi
        # ito idinagdag sa layout, mananatiling WALANG PARENT ang label —
        # ibig sabihin isa itong top-level window, at ang set_sub() sa
        # bandang huli ay magpapakita nito bilang kumikislap na kahon.
        col.addWidget(self._sub)
        self._sub.setVisible(bool(sub))

    def set_value(self, text: str, color: str | None = None) -> None:
        self._value.setText(text)
        style = "font-size: 21px; font-weight: 800"
        if color:
            style += f"; color: {color}"
        self._value.setStyleSheet(style)

    def set_title(self, text: str) -> None:
        self._title.setText(text.upper())

    def set_sub(self, text: str) -> None:
        self._sub.setText(text)
        self._sub.setVisible(bool(text))
