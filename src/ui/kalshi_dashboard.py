"""Kalshi dashboard — Kalshi.com-inspired layout:

- status cards (Internet / Kalshi / Bot / Balance)
- "Featured Market" card na may LIVE two-line probability chart (YES mint,
  NO rose) + malalaking outcome percentages, tulad ng kalshi.com
- scanned sports markets table (may pill status)
- recent logs
"""
from __future__ import annotations

import datetime as dt

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.kalshi_cards import GameCard, group_games
from src.ui.kalshi_chart import KalshiChart
from src.ui.widgets import Card, Pill, StatCard, StatusCard

GRID_COLS = 2  # ilang game card kada row

DEFAULT_PAPER_START = 1000.0

LEVEL_COLORS = {
    "INFO": theme.ACCENT,
    "TRADE": theme.ACCENT,
    "WARN": theme.AMBER,
    "ERROR": theme.RED,
}


class KalshiDashboard(QWidget):
    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self._live_mode = False
        self._chart_ticker: str | None = None

        # ---- Status cards row -------------------------------------------
        self.cards = {
            "internet": StatusCard("fa6s.globe", "Internet", "#4c8dff"),
            "kalshi": StatusCard("fa6s.chart-column", "Kalshi",
                                 theme.KALSHI_ACCENT),
        }
        self.bot_card = StatCard("Bot Status", "STOPPED")
        self.bot_card.set_value("STOPPED", theme.RED)
        self.balance_card = StatCard("Paper Balance", "—",
                                     "Simulated — no real money")
        RIGHT_COL_WIDTH = 340
        self.balance_card.setFixedWidth(RIGHT_COL_WIDTH)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        for card in self.cards.values():
            cards_row.addWidget(card, stretch=1)
        cards_row.addWidget(self.bot_card, stretch=1)
        cards_row.addWidget(self.balance_card)

        # ---- Featured market card (chart) -------------------------------
        self._live_pill = Pill("● LIVE", "bad")
        self._market_title = QLabel("Waiting for a market…")
        self._market_title.setProperty("h2", True)
        self._straddle_pill = Pill("IDLE", "muted")

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(self._live_pill)
        head.addWidget(self._market_title, stretch=1)
        head.addWidget(self._straddle_pill)

        # Outcome percentages (YES mint, NO rose) — parang kalshi.com
        self._yes_lbl = QLabel("YES —")
        self._yes_lbl.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 20px; font-weight: 800")
        self._no_lbl = QLabel("NO —")
        self._no_lbl.setStyleSheet(
            f"color: {theme.RED}; font-size: 20px; font-weight: 800")
        outcomes = QHBoxLayout()
        outcomes.setSpacing(22)
        outcomes.addWidget(self._yes_lbl)
        outcomes.addWidget(self._no_lbl)
        outcomes.addStretch()

        self.chart = KalshiChart()

        self._strategy_label = QLabel("Strategy: idle (press START BOT)")
        self._strategy_label.setProperty("muted", True)
        self._strategy_label.setWordWrap(True)

        featured = Card()
        fc = QVBoxLayout(featured)
        fc.setContentsMargins(16, 14, 16, 14)
        fc.setSpacing(10)
        fc.addLayout(head)
        fc.addLayout(outcomes)
        fc.addWidget(self.chart, stretch=1)
        fc.addWidget(self._strategy_label)

        # ---- Scanned markets — Kalshi-style game cards grid -------------
        table_title = QLabel("Live Sports Markets (50/50 candidates)")
        table_title.setProperty("accent", True)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_hint = QLabel("Press START BOT to scan live sports "
                                  "markets…")
        self._empty_hint.setProperty("muted", True)
        self._grid.addWidget(self._empty_hint, 0, 0)

        mkt_scroll = QScrollArea()
        mkt_scroll.setWidgetResizable(True)
        mkt_scroll.setWidget(self._grid_host)
        mkt_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        markets_panel = Card()
        markets_panel.setMinimumHeight(280)
        markets_col = QVBoxLayout(markets_panel)
        markets_col.setContentsMargins(16, 12, 16, 12)
        markets_col.addWidget(table_title)
        markets_col.addWidget(mkt_scroll, stretch=1)

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
        logs_col.setContentsMargins(16, 12, 16, 12)
        logs_col.addLayout(logs_head)
        logs_col.addWidget(self._log_list, stretch=1)

        # ---- Layout ------------------------------------------------------
        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        left_col.addWidget(featured, stretch=1)
        left_col.addWidget(markets_panel)

        body_row = QHBoxLayout()
        body_row.setSpacing(12)
        body_row.addLayout(left_col, stretch=1)
        body_row.addWidget(logs_panel)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addLayout(cards_row)
        root.addLayout(body_row, stretch=1)

        self._load_recent_logs()
        self.refresh_balance()

    # ------------------------------------------------------------------ slots

    def update_market_tick(self, ticker: str, title: str,
                           yes_pct: float, no_pct: float) -> None:
        if ticker != self._chart_ticker:
            self._chart_ticker = ticker
            self._market_title.setText(title or ticker)
            self.chart.reset()
        self.chart.add_tick(yes_pct, no_pct)
        self._yes_lbl.setText(f"YES {yes_pct:.0f}%")
        self._no_lbl.setText(f"NO {no_pct:.0f}%")

    def update_markets(self, rows: list) -> None:
        # Linisin ang grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        games = group_games(rows)
        # READY muna, tapos by volume — para nasa taas ang tradeable
        games.sort(key=lambda g: (not g["ready"], -g["vol"]))
        games = [g for g in games if len(g["teams"]) >= 2][:12]

        if not games:
            hint = QLabel("Scanning… no 50/50 candidate games yet."
                          if rows else
                          "Press START BOT to scan live sports markets…")
            hint.setProperty("muted", True)
            self._grid.addWidget(hint, 0, 0)
            return

        for i, game in enumerate(games):
            self._grid.addWidget(GameCard(game), i // GRID_COLS,
                                 i % GRID_COLS)

    def set_straddle_status(self, text: str) -> None:
        # I-derive ang pill level mula sa state keyword. IMPORTANTE:
        # unahin ang UNHEDGED (naglalaman ito ng "HEDGED" bilang substring
        # kaya mamali ang LOCKED/HEDGED check kung mauna).
        upper = text.upper()
        if "UNHEDGED" in upper or "ERROR" in upper:
            level, label = "bad", "UNHEDGED"
        elif "LOCKED" in upper:
            level, label = "ok", "LOCKED"
        elif "HEDGED" in upper:
            level, label = "ok", "HEDGED"
        elif "HEDGING" in upper or "SENTINEL" in upper or "ONE_FILLED" in upper:
            level, label = "warn", "HEDGING"
        elif "CANCEL" in upper:
            level, label = "muted", "CANCELLED"
        elif "RESTING" in upper or "WORKING" in upper:
            level, label = "info", "WORKING"
        elif text.strip() in ("", "—"):
            level, label = "muted", "IDLE"
        else:
            level, label = "info", "ACTIVE"
        self._straddle_pill.set(label, level)
        self._straddle_pill.setToolTip(text)

    def set_strategy_status(self, text: str) -> None:
        self._strategy_label.setText(f"Strategy: {text}")

    def set_connection(self, name: str, up: bool) -> None:
        if name in self.cards:
            self.cards[name].set_state(up)

    def set_bot_state(self, state: str) -> None:
        running = state == "RUNNING"
        self.bot_card.set_value(state, theme.ACCENT if running else theme.RED)
        if not running:
            self._straddle_pill.set("IDLE", "muted")

    def refresh_balance(self) -> None:
        if self._live_mode:
            return  # sa live mode, ang engine ang nagpapadala ng balance
        start = float(self._db.get_setting("paper_start_usd",
                                           DEFAULT_PAPER_START))
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
        color = theme.ACCENT if balance >= start else theme.RED
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
        self.balance_card.set_value(f"{balance:,.2f} USD", theme.ACCENT)

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
