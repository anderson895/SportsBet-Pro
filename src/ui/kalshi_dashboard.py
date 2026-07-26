"""Kalshi dashboard — BTC mean-reversion view (Kalshi-branded).

Same strategy layout as the Polymarket dashboard (live BTC chart + stretch %,
status cards, strategy line, recent logs) but with Kalshi branding: a "Kalshi"
connection card and USD balances. The per-panel accent tint (mint) is applied
by ``ExchangePanel`` via ``panel_accent_qss``, so ``accent``-tagged labels pick
up the Kalshi color automatically.
"""
from __future__ import annotations

import datetime as dt
import logging

import qtawesome as qta
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.chart import PriceChart
from src.ui.pages import local_time
from src.ui.widgets import Card, StatCard, StatusCard

DEFAULT_PAPER_START = 1000.0

LEVEL_COLORS = {
    "INFO": theme.MUTED,
    "TRADE": theme.ACCENT,
    "WARN": theme.AMBER,
    "ERROR": theme.RED,
}


class KalshiDashboard(QWidget):
    # (interval, limit) — hiling na mas mahabang klines para sa Time filter
    rangeRequested = Signal(str, int)

    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self._live_mode = False

        # ---- Status cards row -------------------------------------------
        self.cards = {
            "internet": StatusCard("fa6s.globe", "Internet", "#3b82f6"),
            "binance": StatusCard("fa6b.bitcoin", "Binance (BTC)", "#f7931a"),
            "kalshi": StatusCard(
                "fa6s.building-columns", "Kalshi", theme.KALSHI_ACCENT),
        }
        self.bot_card = StatCard("Bot Status", "STOPPED")
        self.bot_card.set_value("STOPPED", theme.RED)
        self.balance_card = StatCard(
            "Paper Balance", "—", "Simulated — no real money")

        RIGHT_COL_WIDTH = 340
        self.balance_card.setFixedWidth(RIGHT_COL_WIDTH)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        for card in self.cards.values():
            cards_row.addWidget(card, stretch=1)
        cards_row.addWidget(self.bot_card, stretch=1)
        cards_row.addWidget(self.balance_card)

        # ---- Chart panel --------------------------------------------------
        chart_title = QLabel("BTC Price (USDT)")
        chart_title.setProperty("accent", True)
        self._price_label = QLabel("$ —")
        self._price_label.setProperty("h1", True)
        self._pct_label = QLabel("")
        self._pct_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 15px")

        self._window_combo = QComboBox()
        self._windows = [
            ("1s", 2, None),
            ("15m", 15, None),
            ("1H", 60, None),
            ("4H", 240, ("1m", 241)),
            ("1D", 1440, ("15m", 97)),
            ("1W", 10080, ("1h", 169)),
            ("YTD", None, None),
            ("All", None, ("1w", 500)),
        ]
        self._window_combo.addItems([label for label, _, _ in self._windows])
        self._window_combo.setCurrentIndex(1)  # default: 15m
        self._window_combo.setFixedWidth(76)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["Line", "Candles"])
        self._type_combo.setFixedWidth(96)

        price_row = QHBoxLayout()
        price_row.setSpacing(8)
        price_row.addWidget(self._price_label)
        price_row.addWidget(self._pct_label)
        price_row.addStretch()
        price_row.addWidget(self._type_combo)
        price_row.addWidget(self._window_combo)

        self.chart = PriceChart()
        self._candle_chart = None  # lazy
        self._history: list = []
        self._chart_stack = QStackedWidget()
        self._chart_stack.addWidget(self.chart)

        self._window_combo.currentIndexChanged.connect(self._on_window)
        self._type_combo.currentIndexChanged.connect(self._on_chart_type)
        if str(self._db.get_setting("chart_type", "line")) == "candles":
            self._type_combo.setCurrentIndex(1)

        self._strategy_label = QLabel("Strategy: idle (press START BOT)")
        self._strategy_label.setProperty("muted", True)
        self._strategy_label.setWordWrap(True)

        chart_panel = Card()
        chart_col = QVBoxLayout(chart_panel)
        chart_col.setContentsMargins(14, 12, 14, 12)
        chart_col.addWidget(chart_title)
        chart_col.addLayout(price_row)
        chart_col.addWidget(self._chart_stack, stretch=1)
        chart_col.addWidget(self._strategy_label)

        # ---- Recent logs panel --------------------------------------------
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
        self._log_list.setSpacing(3)

        logs_panel = Card()
        logs_panel.setFixedWidth(340)
        logs_col = QVBoxLayout(logs_panel)
        logs_col.setContentsMargins(14, 12, 14, 12)
        logs_col.addLayout(logs_head)
        logs_col.addWidget(self._log_list, stretch=1)

        # ---- Layout --------------------------------------------------------
        body_row = QHBoxLayout()
        body_row.setSpacing(10)
        body_row.addWidget(chart_panel, stretch=1)
        body_row.addWidget(logs_panel)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 6)
        root.setSpacing(10)
        root.addLayout(cards_row)
        root.addLayout(body_row, stretch=1)

        self._load_recent_logs()
        self.refresh_balance()

    # ------------------------------------------------------------------ slots

    def update_price(self, price: float) -> None:
        self._price_label.setText(f"${price:,.2f}")
        self.chart.add_point(price)
        if self._candle_chart is not None:
            self._candle_chart.add_point(price)

    def load_history(self, rows: list) -> None:
        self._history = rows
        self.chart.load_history(rows)
        if self._candle_chart is not None:
            self._candle_chart.load_history(rows)

    def update_candle(self, k: tuple) -> None:
        if self._candle_chart is not None:
            self._candle_chart.update_candle(k)

    def _on_window(self, index: int) -> None:
        label, minutes, fetch = self._windows[index]
        if label == "YTD":
            now = dt.datetime.now(dt.timezone.utc)
            jan1 = dt.datetime(now.year, 1, 1, tzinfo=dt.timezone.utc)
            days = (now - jan1).days + 1
            minutes = days * 1440
            fetch = ("1d", days + 2)

        self.chart.set_window_minutes(minutes)
        if fetch is not None:
            self.rangeRequested.emit(*fetch)

    def load_range_history(self, rows: list) -> None:
        self.chart.load_history(rows)

    def update_stretch(self, pct: float) -> None:
        color = theme.GREEN if pct >= 0 else theme.RED
        self._pct_label.setText(f"{pct:+.2f}%")
        self._pct_label.setStyleSheet(
            f"color: {color}; font-size: 15px; font-weight: bold")

    def _on_chart_type(self, index: int) -> None:
        if index == 1 and self._candle_chart is None:
            try:
                from src.ui.candle_chart import CandleChart
                self._candle_chart = CandleChart()
                if self._history:
                    self._candle_chart.load_history(self._history)
                self._chart_stack.addWidget(self._candle_chart)
            except Exception:
                logging.getLogger("sportsbet.ui").exception(
                    "Candlestick chart failed to load:")
                self._candle_chart = None
                self._type_combo.setCurrentIndex(0)
                return
        self._chart_stack.setCurrentIndex(index)
        self._window_combo.setVisible(index == 0)
        self._db.set_setting("chart_type", "candles" if index == 1 else "line")

    def set_connection(self, name: str, up: bool) -> None:
        key = "binance" if name == "binance_ws" else name
        if key in self.cards:
            self.cards[key].set_state(up)

    def set_bot_state(self, state: str) -> None:
        running = state == "RUNNING"
        self.bot_card.set_value(state, theme.GREEN if running else theme.RED)

    def set_strategy_status(self, text: str) -> None:
        self._strategy_label.setText(f"Strategy: {text}")

    def refresh_balance(self) -> None:
        if self._live_mode:
            return
        start = float(self._db.get_setting("paper_start_usd", DEFAULT_PAPER_START))
        open_cost = 0.0
        pos = self._db.load_open_position()
        if pos:
            open_cost = float(pos["entry_price"]) * float(pos["shares"])
        balance = start + self._db.total_pnl() - open_cost
        color = theme.GREEN if balance >= start else theme.RED
        self.balance_card.set_value(f"{balance:,.2f} USD", color)
        self.balance_card.set_sub(
            f"Simulated — {open_cost:,.0f} USD in open position"
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
            self._insert_log_item(local_time(row["ts"]), row["level"],
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
