"""Shared sub-pages ng bawat exchange panel: Trades, Logs, Statistics, About.

Galing sa PolyTradePro main_window.py — na-parameterize lang per exchange
(ScopedDatabase + currency label) para magamit ng Polymarket AT Kalshi panel.
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.widgets import Card


class TradesPage(QWidget):
    def __init__(self, db: ScopedDatabase, currency: str = "USD") -> None:
        super().__init__()
        self._db = db
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Market", "Side", "Action", "Price", f"Size ({currency})", "PnL"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        root = QVBoxLayout(self)
        title = QLabel("Trades")
        title.setProperty("accent", True)
        root.addWidget(title)
        root.addWidget(self.table, stretch=1)
        self.reload()

    def reload(self) -> None:
        self.table.setRowCount(0)
        for row in self._db.recent_trades(limit=200):
            r = self.table.rowCount()
            self.table.insertRow(r)
            pnl = row["pnl"]
            values = [
                row["ts"][11:19], row["market"], row["side"], row["action"],
                f"{row['price']:.2f}", f"{row['size']:.2f}",
                "" if pnl is None else f"{pnl:+.2f}",
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 6 and pnl is not None:
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

        for row in self._db.recent_logs(limit=500):
            self._add_row(row["ts"][11:19], row["level"], row["message"])

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
