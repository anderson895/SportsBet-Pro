"""Generic exchange panel — isang buong "mini app" per exchange.

Bawat panel (Polymarket / Kalshi) ay may sariling:
- sub-navigation (Dashboard / Settings / Logs / Trades / Statistics / About)
- AlertBanner para sa errors
- BottomBar na may SARILING START/STOP button + uptime
- mga pages na naka-scope sa sariling exchange DB

Ang exchange-specific na dashboard at settings widgets ay ipinapasa ng
main_window; ang common wiring (state, trades, logs, alerts, uptime) ay
dito ginagawa para pareho ang behavior ng dalawang panel.
"""
from __future__ import annotations

import asyncio

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
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
from src.ui.alert_banner import AlertBanner
from src.ui.pages import AboutPage, LogsPage, StatsPage, TradesPage


class BottomBar(QFrame):
    """Status strip + START/STOP ng ISANG exchange (galing sa reference)."""

    def __init__(self, strategy_name: str, market_text: str) -> None:
        super().__init__()
        self.setProperty("card", True)

        strat_title = QLabel("Strategy")
        strat_title.setProperty("muted", True)
        strat_value = QLabel(strategy_name)
        strat_value.setStyleSheet("font-weight: bold")
        strat_col = QVBoxLayout()
        strat_col.setSpacing(1)
        strat_col.addWidget(strat_title)
        strat_col.addWidget(strat_value)

        market_title = QLabel("Market")
        market_title.setProperty("muted", True)
        self.market_label = QLabel(market_text)
        self.market_label.setStyleSheet("font-weight: bold")
        market_col = QVBoxLayout()
        market_col.setSpacing(1)
        market_col.addWidget(market_title)
        market_col.addWidget(self.market_label)

        risk_title = QLabel("Risk / Trade")
        risk_title.setProperty("muted", True)
        self.risk_label = QLabel("—")
        self.risk_label.setStyleSheet("font-weight: bold")
        risk_col = QVBoxLayout()
        risk_col.setSpacing(1)
        risk_col.addWidget(risk_title)
        risk_col.addWidget(self.risk_label)

        # Optional na extra column (hal. Timeframe sa Polymarket) —
        # idinadagdag via add_info_column() bago ang risk column
        self._info_title = QLabel("")
        self._info_title.setProperty("muted", True)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("font-weight: bold")
        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        info_col.addWidget(self._info_title)
        info_col.addWidget(self.info_label)
        self._info_title.hide()
        self.info_label.hide()

        self.start_btn = QPushButton("  START BOT")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setIcon(qta.icon("fa6s.play", color="white"))
        self.stop_btn = QPushButton("  STOP BOT")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setIcon(qta.icon("fa6s.stop", color=theme.RED))
        self.stop_btn.setEnabled(False)

        up_title = QLabel("Uptime")
        up_title.setProperty("muted", True)
        self.uptime_label = QLabel("00:00:00")
        self.uptime_label.setStyleSheet("font-weight: bold; font-size: 15px")
        up_col = QVBoxLayout()
        up_col.setSpacing(1)
        up_col.addWidget(up_title)
        up_col.addWidget(self.uptime_label)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.addLayout(strat_col)
        row.addSpacing(24)
        row.addLayout(market_col)
        row.addSpacing(24)
        row.addLayout(info_col)
        row.addSpacing(24)
        row.addLayout(risk_col)
        row.addStretch()
        row.addWidget(self.start_btn)
        row.addSpacing(8)
        row.addWidget(self.stop_btn)
        row.addStretch()
        row.addLayout(up_col)

    def set_info_column(self, title: str, value: str) -> None:
        self._info_title.setText(title)
        self.info_label.setText(value)
        self._info_title.show()
        self.info_label.show()


class ExchangePanel(QWidget):
    """Isang exchange = isang panel. Hawak nito ang common wiring."""

    PAGES = [
        ("fa6s.house", "Dashboard"),
        ("fa6s.gear", "Settings"),
        ("fa6s.file-lines", "Logs"),
        ("fa6s.chart-line", "Trades"),
        ("fa6s.chart-pie", "Statistics"),
        ("fa6s.circle-info", "About"),
    ]

    def __init__(
        self,
        engine,
        db: ScopedDatabase,
        dashboard: QWidget,
        settings_page: QWidget,
        strategy_name: str,
        market_text: str,
        currency: str,
        risk_setting: tuple[str, float],  # (settings key, default)
        about_title: str,
        about_body: str,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._db = db
        self._risk_key, self._risk_default = risk_setting
        self._currency = currency
        self._market_text = market_text

        self.dash = dashboard
        self.settings = settings_page
        self.logs = LogsPage(db)
        self.trades = TradesPage(db, currency)
        self.stats = StatsPage(db, currency)

        # ---- sub-navigation (kaliwa, icon list tulad ng reference sidebar)
        self._nav = QListWidget()
        self._nav.setObjectName("sidebar")
        self._nav.setIconSize(QSize(18, 18))
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for icon_name, label in self.PAGES:
            icon = qta.icon(icon_name, color=theme.MUTED, color_selected="#c7d2fe")
            item = QListWidgetItem(icon, label)
            item.setToolTip(label)
            self._nav.addItem(item)
        self._nav.setCurrentRow(0)
        self._nav.setFixedWidth(170)

        self._stack = QStackedWidget()
        for page in (
            self.dash, self.settings, self.logs, self.trades, self.stats,
            AboutPage(about_title, about_body),
        ):
            self._stack.addWidget(page)
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)

        # ---- alert banner + bottom bar
        self.alert = AlertBanner()
        self.bottom = BottomBar(strategy_name, market_text)
        self.bottom.start_btn.clicked.connect(self._on_start)
        self.bottom.stop_btn.clicked.connect(self._on_stop)

        # ---- layout
        content = QVBoxLayout()
        content.setContentsMargins(6, 0, 0, 0)
        content.addWidget(self.alert)
        content.addWidget(self._stack, stretch=1)
        content.addWidget(self.bottom)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._nav)
        root.addLayout(content, stretch=1)

        # ---- uptime timer
        self._uptime_secs = 0
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        # ---- common engine wiring
        engine.stateChanged.connect(self._on_state)
        engine.tradeExecuted.connect(self._on_trade)
        engine.logAdded.connect(self.logs.add_log)
        engine.logAdded.connect(self._on_log_alert)
        engine.modeChanged.connect(self._on_mode)
        if hasattr(self.dash, "add_log"):
            engine.logAdded.connect(self.dash.add_log)

        self.refresh_config_labels()

    # ------------------------------------------------------------------ slots

    def _on_start(self) -> None:
        self._engine.start()

    def _on_stop(self) -> None:
        asyncio.create_task(self._engine.stop())

    def _on_state(self, state: str) -> None:
        running = state == "RUNNING"
        if hasattr(self.dash, "set_bot_state"):
            self.dash.set_bot_state(state)
        self.bottom.start_btn.setEnabled(not running)
        self.bottom.stop_btn.setEnabled(running)
        if running:
            self._uptime_secs = 0
            self._uptime_timer.start()
        else:
            self._uptime_timer.stop()

    def _on_mode(self, mode: str) -> None:
        if hasattr(self.dash, "set_mode"):
            self.dash.set_mode(mode)
        self.bottom.market_label.setText(f"{self._market_text} [{mode}]")
        self.refresh_config_labels()

    def refresh_config_labels(self) -> None:
        risk = float(self._db.get_setting(self._risk_key, self._risk_default))
        self.bottom.risk_label.setText(f"{risk:,.2f} {self._currency}")

    def _on_log_alert(self, level: str, message: str) -> None:
        if level == "ERROR":
            self.alert.show_error(message)

    def _on_trade(self) -> None:
        self.trades.reload()
        self.stats.refresh()
        if hasattr(self.dash, "refresh_balance"):
            self.dash.refresh_balance()

    def _tick_uptime(self) -> None:
        self._uptime_secs += 1
        h, rem = divmod(self._uptime_secs, 3600)
        m, s = divmod(rem, 60)
        self.bottom.uptime_label.setText(f"{h:02d}:{m:02d}:{s:02d}")
