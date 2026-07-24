"""Sticky settings header — laging kita sa itaas ng Settings page.

Dahilan: dati nasa DULO ng mahabang form ang Save button, kaya madalas
makalimutang i-scroll pababa ng user — nagse-START ng bot na hindi pala
na-save ang mga pagbabago. Ngayon:

- Balance ang UNANG nakikita (live fetch) para alam agad kung magkano
  ang pondo bago mag-configure
- "Apply Recommended" — isang click para sa ligtas na testing values
  na nakabatay sa balance (~10% risk per trade)
- Save / Reset ay nasa itaas at HINDI nagsi-scroll palayo
"""
from __future__ import annotations

from typing import Callable, Optional

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.ui import theme
from src.ui.widgets import Card


class SettingsHeader(Card):
    """Balance + Apply Recommended + Save/Reset — nasa itaas, hindi
    kasama sa scroll area para laging abot-kamay."""

    def __init__(
        self,
        currency: str,
        on_save: Callable[[], None],
        on_reset: Callable[[], None],
        on_recommend: Callable[[], None],
        on_refresh: Callable[[], None],
    ) -> None:
        super().__init__()
        self._currency = currency

        # --- balance block (kaliwa)
        wallet_icon = QLabel()
        wallet_icon.setPixmap(
            qta.icon("fa6s.wallet", color=theme.MUTED).pixmap(20, 20)
        )
        bal_title = QLabel("AVAILABLE BALANCE")
        bal_title.setStyleSheet(
            f"color: {theme.FAINT}; font-weight: 700; font-size: 10px;"
            " letter-spacing: 0.6px"
        )
        self._bal_value = QLabel("—")
        self._bal_value.setStyleSheet("font-size: 19px; font-weight: 800")
        self._bal_sub = QLabel("Checking balance…")
        self._bal_sub.setProperty("muted", True)

        refresh_btn = QPushButton()
        refresh_btn.setIcon(qta.icon("fa6s.rotate", color=theme.MUTED))
        refresh_btn.setToolTip("Refresh balance")
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(on_refresh)

        bal_col = QVBoxLayout()
        bal_col.setSpacing(1)
        bal_col.addWidget(bal_title)
        bal_col.addWidget(self._bal_value)
        bal_col.addWidget(self._bal_sub)

        # --- action buttons (kanan)
        rec_btn = QPushButton("  Apply Recommended")
        rec_btn.setIcon(qta.icon("fa6s.wand-magic-sparkles", color=theme.TEXT))
        rec_btn.setToolTip(
            "Fill the form with safe testing values sized to your balance "
            "(~10% risk per trade). Review, then click Save Settings."
        )
        rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rec_btn.clicked.connect(on_recommend)

        save_btn = QPushButton("  Save Settings")
        save_btn.setIcon(qta.icon("fa6s.floppy-disk", color="white"))
        save_btn.setObjectName("accentBtn")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(on_save)

        reset_btn = QPushButton("  Reset")
        reset_btn.setIcon(qta.icon("fa6s.rotate-left", color=theme.TEXT))
        reset_btn.setToolTip("Restore default strategy values (not saved yet)")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(on_reset)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(wallet_icon)
        top.addLayout(bal_col)
        top.addWidget(refresh_btn)
        top.addStretch()
        top.addWidget(rec_btn)
        top.addWidget(save_btn)
        top.addWidget(reset_btn)

        # --- status line (save result / credential check / warnings)
        self._status = QLabel("")
        self._status.setProperty("muted", True)
        self._status.setWordWrap(True)

        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(6)
        col.addLayout(top)
        col.addWidget(self._status)

    # ----------------------------------------------------------------- API

    def set_balance(self, amount: Optional[float], sub: str = "") -> None:
        """Ipakita ang balance; None = hindi pa alam / bigo ang fetch."""
        if amount is None:
            self._bal_value.setText("—")
            self._bal_value.setStyleSheet(
                f"font-size: 19px; font-weight: 800; color: {theme.MUTED}"
            )
        else:
            self._bal_value.setText(f"{amount:,.2f} {self._currency}")
            self._bal_value.setStyleSheet("font-size: 19px; font-weight: 800")
        self._bal_sub.setText(sub)

    def set_status(self, text: str, color: str = theme.MUTED) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color}")


def recommended_risk(balance: Optional[float], minimum: float = 2.0,
                     fraction: float = 0.10) -> float:
    """Ligtas na risk para sa testing: ~10% ng balance (whole units),
    hindi bababa sa `minimum`. Kung walang alam na balance, ang minimum
    na mismo ang ibinabalik."""
    if balance is None or balance <= 0:
        return minimum
    return max(minimum, float(round(balance * fraction)))
