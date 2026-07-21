"""Kalshi dashboard: status cards, market scanner table, straddle status,
recent logs — parehong dark look ng Polymarket panel."""
from __future__ import annotations

import datetime as dt

import qtawesome as qta
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.widgets import Card, StatCard, StatusCard

DEFAULT_PAPER_START = 1000.0

LEVEL_COLORS = {
    "INFO": theme.GREEN,
    "TRADE": theme.ACCENT,
    "WARN": theme.AMBER,
    "ERROR": theme.RED,
}


class KalshiDashboard(QWidget):
    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self._live_mode = False

        # ---- Status cards row -------------------------------------------
        self.cards = {
            "internet": StatusCard("fa6s.globe", "Internet", "#3b82f6"),
            "kalshi": StatusCard("fa6s.chart-column", "Kalshi",
                                 theme.KALSHI_TEAL),
        }
        self.bot_card = StatCard("Bot Status", "STOPPED")
        self.bot_card.set_value("STOPPED", theme.RED)
        self.balance_card = StatCard("Paper Balance", "—",
                                     "Simulated — no real money")
        RIGHT_COL_WIDTH = 340
        self.balance_card.setFixedWidth(RIGHT_COL_WIDTH)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        for card in self.cards.values():
            cards_row.addWidget(card, stretch=1)
        cards_row.addWidget(self.bot_card, stretch=1)
        cards_row.addWidget(self.balance_card)

        # ---- Active straddle card ---------------------------------------
        straddle_title = QLabel("Active Straddle")
        straddle_title.setProperty("accent", True)
        self._straddle_label = QLabel("—")
        self._straddle_label.setWordWrap(True)
        self._straddle_label.setStyleSheet("font-size: 14px; font-weight: bold")

        self._strategy_label = QLabel("Strategy: idle (press START BOT)")
        self._strategy_label.setProperty("muted", True)
        self._strategy_label.setWordWrap(True)

        straddle_panel = Card()
        straddle_col = QVBoxLayout(straddle_panel)
        straddle_col.setContentsMargins(14, 12, 14, 12)
        straddle_col.setSpacing(6)
        straddle_col.addWidget(straddle_title)
        straddle_col.addWidget(self._straddle_label)
        straddle_col.addWidget(self._strategy_label)

        # ---- Scanned markets table --------------------------------------
        table_title = QLabel("Scanned Sports Markets (50/50 candidates)")
        table_title.setProperty("accent", True)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Ticker", "Market", "YES bid/ask", "NO bid/ask",
             "Volume", "Status", ""]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnHidden(6, True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        markets_panel = Card()
        markets_col = QVBoxLayout(markets_panel)
        markets_col.setContentsMargins(14, 12, 14, 12)
        markets_col.addWidget(table_title)
        markets_col.addWidget(self.table, stretch=1)

        # ---- Recent logs panel ------------------------------------------
        logs_title = QLabel("Recent Logs")
        logs_title.setProperty("accent", True)
        clear_btn = QPushButton(" Clear")
        clear_btn.setIcon(qta.icon("fa6s.trash-can", color=theme.MUTED))
        clear_btn.clicked.connect(self._clear_logs)

        logs_head = QHBoxLayout()
        logs_head.addWidget(logs_title)
        logs_head.addStretch()
        logs_head.addWidget(clear_btn)

        self._log_list = QListWidget()
        self._log_list.setWordWrap(True)

        logs_panel = Card()
        logs_panel.setFixedWidth(RIGHT_COL_WIDTH)
        logs_col = QVBoxLayout(logs_panel)
        logs_col.setContentsMargins(14, 12, 14, 12)
        logs_col.addLayout(logs_head)
        logs_col.addWidget(self._log_list, stretch=1)

        # ---- Layout ------------------------------------------------------
        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        left_col.addWidget(straddle_panel)
        left_col.addWidget(markets_panel, stretch=1)

        body_row = QHBoxLayout()
        body_row.setSpacing(10)
        body_row.addLayout(left_col, stretch=1)
        body_row.addWidget(logs_panel)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addLayout(cards_row)
        root.addLayout(body_row, stretch=1)

        self._load_recent_logs()
        self.refresh_balance()

    # ------------------------------------------------------------------ slots

    def update_markets(self, rows: list) -> None:
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            ready = row.get("status") == "READY"
            values = [
                row.get("ticker", ""),
                row.get("title", ""),
                f"{row.get('yes_bid', 0)}¢ / {row.get('yes_ask', 0)}¢",
                f"{row.get('no_bid', 0)}¢ / {row.get('no_ask', 0)}¢",
                f"{row.get('volume', 0):,}",
                "✓ READY" if ready else str(row.get("status", "")),
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 5:
                    item.setForeground(
                        QColor(theme.GREEN if ready else theme.MUTED)
                    )
                self.table.setItem(r, col, item)

    def set_straddle_status(self, text: str) -> None:
        self._straddle_label.setText(text)

    def set_strategy_status(self, text: str) -> None:
        self._strategy_label.setText(f"Strategy: {text}")

    def set_connection(self, name: str, up: bool) -> None:
        if name in self.cards:
            self.cards[name].set_state(up)

    def set_bot_state(self, state: str) -> None:
        running = state == "RUNNING"
        self.bot_card.set_value(state, theme.GREEN if running else theme.RED)

    def refresh_balance(self) -> None:
        if self._live_mode:
            return  # sa live mode, ang engine ang nagpapadala ng balance
        start = float(self._db.get_setting("paper_start_usd",
                                           DEFAULT_PAPER_START))
        # Cash-style: ibawas ang cost ng aktibong straddle (open orders)
        open_cost = 0.0
        import json
        raw = self._db.get_setting("open_straddle", "")
        if raw:
            try:
                s = json.loads(raw)
                pairs = int(s.get("count", 0))
                entry = int(s.get("entry_cents", 0))
                open_cost = pairs * entry * 2 / 100.0
            except (ValueError, TypeError):
                pass
        balance = start + self._db.total_pnl() - open_cost
        color = theme.GREEN if balance >= start else theme.RED
        self.balance_card.set_value(f"{balance:,.2f} USD", color)
        self.balance_card.set_sub(
            f"Simulated — ${open_cost:,.0f} in working straddle"
            if open_cost else "Simulated — no real money"
        )

    def set_mode(self, mode: str) -> None:
        self._live_mode = mode == "LIVE"
        if self._live_mode:
            self.balance_card.set_title("Account Balance (LIVE)")
            self.balance_card.set_sub("Real USD on Kalshi")
            self.balance_card.set_value("…", theme.AMBER)
        else:
            self.balance_card.set_title("Paper Balance")
            self.balance_card.set_sub("Simulated — no real money")
            self.refresh_balance()

    def set_live_balance(self, balance: float) -> None:
        self.balance_card.set_value(f"{balance:,.2f} USD", theme.GREEN)

    def add_log(self, level: str, message: str) -> None:
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self._insert_log_item(ts, level, message, prepend=True)

    # ---------------------------------------------------------------- helpers

    def _load_recent_logs(self) -> None:
        for row in self._db.recent_logs(limit=50):
            self._insert_log_item(row["ts"][11:19], row["level"],
                                  row["message"])

    def _insert_log_item(
        self, ts: str, level: str, message: str, prepend: bool = False
    ) -> None:
        item = QListWidgetItem(f"●  [{ts}]  {message}")
        item.setForeground(QColor(LEVEL_COLORS.get(level, theme.TEXT)))
        if prepend:
            self._log_list.insertItem(0, item)
        else:
            self._log_list.addItem(item)

    def _clear_logs(self) -> None:
        self._db.clear_logs()
        self._log_list.clear()
