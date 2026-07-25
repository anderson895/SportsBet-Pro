"""Shared sub-pages ng bawat exchange panel: Trades, Logs, Statistics, About.

Galing sa PolyTradePro main_window.py — na-parameterize lang per exchange
(ScopedDatabase + currency label) para magamit ng Polymarket AT Kalshi panel.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.widgets import Card

# Ang isang "trade" row ay naitatala pagka-PLACE ng order, hindi pagka-fill.
# Kailangang malinaw ito sa table — kung hindi, mukhang nagastos na ang pera
# gayong nakapila pa lang ang order at buo pa ang balance.
STATUS_LABELS = {
    "OPEN": "RESTING (not filled)",
    "FILLED": "FILLED",
    "CANCELLED": "CANCELLED",
}
STATUS_COLORS = {
    "OPEN": theme.AMBER,
    "FILLED": theme.GREEN,
    "CANCELLED": theme.MUTED,
}
# Napalitan na ng totoong exchange fills — nasa DB pa para sa audit pero
# hindi na ipinapakita, kung hindi ay doble ang parehong straddle
HIDDEN_STATUSES = {"SUPERSEDED"}


def local_time(ts: str) -> str:
    """ISO timestamp -> HH:MM:SS sa LOCAL time ng user.

    Ang mga ts ay naka-UTC (galing sa app o sa Kalshi) at may iba-ibang
    hugis: "…+00:00" mula sa atin, "…Z" na may microseconds mula sa
    Kalshi. Kapag hindi ma-parse, ibabalik ang hilaw na hiwa kaysa
    magkamali ng oras.
    """
    raw = (ts or "").strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[11:19]
    if parsed.tzinfo is None:            # walang zone = UTC ang assume
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone().strftime("%H:%M:%S")


class TradesPage(QWidget):
    def __init__(self, db: ScopedDatabase, currency: str = "USD",
                 on_sync: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self._db = db
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Market", "Side", "Action", "Price",
             f"Size ({currency})", "Status", "PnL"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        title = QLabel("Trades")
        title.setProperty("accent", True)

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        # Ang lokal na tala ay isinusulat pagka-PLACE ng order; ang exchange
        # ang may ground truth kung ano talaga ang na-fill. Ito ang paraan
        # para ma-reconcile ang dalawa.
        if on_sync is not None:
            sync_btn = QPushButton("  Sync from exchange")
            sync_btn.setIcon(qta.icon("fa6s.cloud-arrow-down",
                                      color=theme.TEXT))
            sync_btn.setToolTip(
                "Import the real fill history from the exchange so this "
                "table matches your account exactly."
            )
            sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            sync_btn.clicked.connect(on_sync)
            head.addWidget(sync_btn)
        self.status = QLabel("")
        self.status.setProperty("muted", True)

        root = QVBoxLayout(self)
        root.addLayout(head)
        root.addWidget(self.table, stretch=1)
        root.addWidget(self.status)
        self.reload()

    def set_status(self, text: str, color: str = theme.MUTED) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}")

    def reload(self) -> None:
        self.table.setRowCount(0)
        for row in self._db.recent_trades(limit=200):
            status = row["status"] or ""
            if status in HIDDEN_STATUSES:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            pnl = row["pnl"]
            values = [
                local_time(row["ts"]), row["market"], row["side"], row["action"],
                f"{row['price']:.2f}", f"{row['size']:.2f}",
                STATUS_LABELS.get(status, status),
                "" if pnl is None else f"{pnl:+.2f}",
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 6:
                    item.setForeground(QColor(STATUS_COLORS.get(status,
                                                                theme.MUTED)))
                elif col == 7 and pnl is not None:
                    item.setForeground(QColor(theme.GREEN if pnl >= 0 else theme.RED))
                self.table.setItem(r, col, item)


class LogsPage(QWidget):
    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time", "Level", "Message"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        root = QVBoxLayout(self)
        title = QLabel("Logs")
        title.setProperty("accent", True)
        root.addWidget(title)
        root.addWidget(self.table, stretch=1)

        # local_time(): ang mga naka-imbak na ts ay UTC, pero LOCAL ang
        # gamit ng add_log() sa mga live entry — dapat pareho ang basehan
        for row in self._db.recent_logs(limit=500):
            self._add_row(local_time(row["ts"]), row["level"], row["message"])

    def add_log(self, level: str, message: str) -> None:
        self._add_row(dt.datetime.now().strftime("%H:%M:%S"), level, message, prepend=True)

    def _add_row(self, ts: str, level: str, message: str, prepend: bool = False) -> None:
        r = 0 if prepend else self.table.rowCount()
        self.table.insertRow(r)
        for col, val in enumerate([ts, level, message]):
            self.table.setItem(r, col, QTableWidgetItem(val))


class StatsPage(QWidget):
    def __init__(self, db: ScopedDatabase, currency: str = "USD") -> None:
        super().__init__()
        self._db = db
        self._currency = currency
        title = QLabel("Statistics")
        title.setProperty("accent", True)

        self._labels: dict[str, QLabel] = {}
        panel = Card()
        col = QVBoxLayout(panel)
        col.setContentsMargins(16, 14, 16, 14)
        for key in ("Closed Trades", "Wins", "Losses", "Win Rate", "Total PnL"):
            lab = QLabel(f"{key}: —")
            lab.setStyleSheet("font-size: 15px")
            self._labels[key] = lab
            col.addWidget(lab)

        root = QVBoxLayout(self)
        root.addWidget(title)
        root.addWidget(panel)
        root.addStretch()
        self.refresh()

    def refresh(self) -> None:
        stats = self._db.trade_stats()
        pnl = self._db.total_pnl()
        closed = stats["closed"]
        win_rate = (stats["wins"] / closed * 100) if closed else 0.0
        self._labels["Closed Trades"].setText(f"Closed Trades: {closed}")
        self._labels["Wins"].setText(f"Wins: {stats['wins']}")
        self._labels["Losses"].setText(f"Losses: {stats['losses']}")
        self._labels["Win Rate"].setText(f"Win Rate: {win_rate:.0f}%")
        color = theme.GREEN if pnl >= 0 else theme.RED
        self._labels["Total PnL"].setText(f"Total PnL: {pnl:+,.2f} {self._currency}")
        self._labels["Total PnL"].setStyleSheet(f"font-size: 15px; color: {color}")


class AboutPage(QWidget):
    def __init__(self, title_text: str, body_text: str) -> None:
        super().__init__()
        title = QLabel(title_text)
        title.setProperty("h1", True)
        body = QLabel(body_text)
        body.setProperty("muted", True)
        body.setWordWrap(True)
        root = QVBoxLayout(self)
        root.addWidget(title)
        root.addWidget(body)
        root.addStretch()
