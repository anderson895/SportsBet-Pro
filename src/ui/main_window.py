"""SportsBet Pro main window — dalawang exchange panel (Polymarket + Kalshi).

Sa itaas may exchange switcher tabs; bawat tab ay isang buong ExchangePanel
na may sariling sub-navigation, dashboard, settings, logs, trades, stats,
at SARILING START/STOP. Independent ang dalawang bot — parehong pwedeng
tumakbo nang sabay sa iisang qasync event loop.
"""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import Database, ScopedDatabase
from src.ui import theme
from src.ui.exchange_panel import ExchangePanel
from src.ui.kalshi_dashboard import KalshiDashboard
from src.ui.kalshi_settings import KalshiSettingsPage
from src.ui.poly_dashboard import PolyDashboard
from src.ui.poly_settings import PolySettingsPage

APP_VERSION = "1.0.0"

TF_LABELS = {"daily": "Daily", "4h": "4 Hours", "1h": "1 Hour", "15m": "15 Minutes"}


class MainWindow(QMainWindow):
    def __init__(
        self,
        db: Database,
        poly_engine,
        kalshi_engine,
        poly_db: ScopedDatabase,
        kalshi_db: ScopedDatabase,
    ) -> None:
        super().__init__()
        self._db = db
        self.setWindowTitle("SportsBet Pro — Polymarket + Kalshi Trading Bot")
        self.setMinimumSize(1200, 720)
        self.setStyleSheet(theme.STYLESHEET)

        # ---- Polymarket panel -------------------------------------------
        poly_dash = PolyDashboard(poly_db)
        poly_settings = PolySettingsPage(poly_db)
        self.poly_panel = ExchangePanel(
            engine=poly_engine,
            db=poly_db,
            dashboard=poly_dash,
            settings_page=poly_settings,
            strategy_name="Mean Reversion",
            market_text="BTC (Binance) → Polymarket",
            currency="USDC",
            risk_setting=("risk_usdc", 200.0),
            about_title="Polymarket Bot",
            about_body=(
                f"SportsBet Pro v{APP_VERSION} — Polymarket panel\n\n"
                "Strategy: Mean Reversion (\"Rubber Band\") on daily BTC Up/Down markets.\n"
                "Data: Binance (read-only BTC price feed).\n\n"
                "Paper mode simulates every trade with no real money.\n"
                "Switch to Live mode in Settings to trade with real USDC on Polymarket."
            ),
        )

        # ---- Kalshi panel -----------------------------------------------
        kalshi_dash = KalshiDashboard(kalshi_db)
        kalshi_settings = KalshiSettingsPage(kalshi_db)
        self.kalshi_panel = ExchangePanel(
            engine=kalshi_engine,
            db=kalshi_db,
            dashboard=kalshi_dash,
            settings_page=kalshi_settings,
            strategy_name="Internal Straddle (Box Arb)",
            market_text="Kalshi Sports 50/50",
            currency="USD",
            risk_setting=("risk_usd", 100.0),
            about_title="Kalshi Bot",
            about_body=(
                f"SportsBet Pro v{APP_VERSION} — Kalshi panel\n\n"
                "Strategy: Internal Straddle / Box Arbitrage on high-liquidity 50/50\n"
                "sports markets — buy YES @49¢ + NO @49¢ as resting maker orders;\n"
                "one side must settle at $1.00, locking ~1.1% per cycle after fees.\n"
                "A Hedge Sentinel closes single-sided fills at ≤51¢ to avoid\n"
                "directional sports risk.\n\n"
                "Paper mode uses live public Kalshi market data with simulated fills.\n"
                "Live mode needs your Kalshi API Key ID + RSA private key (Settings)."
            ),
        )

        # ---- Poly-specific signal wiring (chart, stretch, atbp.) --------
        poly_engine.priceUpdated.connect(poly_dash.update_price)
        poly_engine.historyLoaded.connect(poly_dash.load_history)
        poly_engine.klineUpdated.connect(poly_dash.update_candle)
        poly_engine.rangeHistoryLoaded.connect(poly_dash.load_range_history)
        poly_dash.rangeRequested.connect(poly_engine.fetch_range_history)
        poly_engine.stretchUpdated.connect(poly_dash.update_stretch)
        poly_engine.strategyStatus.connect(poly_dash.set_strategy_status)
        poly_engine.liveBalance.connect(poly_dash.set_live_balance)
        poly_settings.modeSaved.connect(self.poly_panel._on_mode)
        poly_settings.modeSaved.connect(lambda _m: self._refresh_poly_labels())
        poly_settings.liveBalanceChecked.connect(poly_dash.set_live_balance)

        # ---- Kalshi-specific wiring -------------------------------------
        kalshi_engine.marketsScanned.connect(kalshi_dash.update_markets)
        kalshi_engine.strategyStatus.connect(kalshi_dash.set_strategy_status)
        kalshi_engine.straddleStatus.connect(kalshi_dash.set_straddle_status)
        kalshi_engine.liveBalance.connect(kalshi_dash.set_live_balance)
        kalshi_settings.modeSaved.connect(self.kalshi_panel._on_mode)
        kalshi_settings.liveBalanceChecked.connect(kalshi_dash.set_live_balance)

        # ---- Connection status: isang monitor (nasa poly engine),
        #      naka-fan-out sa parehong dashboard --------------------------
        poly_engine.connectionChanged.connect(poly_dash.set_connection)
        poly_engine.connectionChanged.connect(kalshi_dash.set_connection)

        # ---- Exchange switcher (top tabs) --------------------------------
        brand_icon = QLabel()
        brand_icon.setPixmap(qta.icon("fa6s.cube", color=theme.ACCENT).pixmap(24, 24))
        brand = QLabel("SportsBet Pro")
        brand.setProperty("h2", True)

        self._tab_poly = QPushButton("Polymarket")
        self._tab_kalshi = QPushButton("Kalshi")
        for btn in (self._tab_poly, self._tab_kalshi):
            btn.setProperty("exchangeTab", True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_poly.clicked.connect(lambda: self._switch(0))
        self._tab_kalshi.clicked.connect(lambda: self._switch(1))

        version = QLabel(f"v{APP_VERSION}")
        version.setProperty("muted", True)

        top = QHBoxLayout()
        top.setContentsMargins(16, 8, 16, 0)
        top.setSpacing(10)
        top.addWidget(brand_icon)
        top.addWidget(brand)
        top.addSpacing(24)
        top.addWidget(self._tab_poly)
        top.addWidget(self._tab_kalshi)
        top.addStretch()
        top.addWidget(version)

        # ---- Panel stack -------------------------------------------------
        self._stack = QStackedWidget()
        self._stack.addWidget(self.poly_panel)
        self._stack.addWidget(self.kalshi_panel)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 8, 8)
        root.addLayout(top)
        root.addWidget(self._stack, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

        # Pointer cursor + wheel blocking sa lahat ng inputs (tulad ng dati)
        self._apply_pointer_cursors(container)

        # I-restore ang huling aktibong tab
        start_tab = 1 if str(db.get_setting("active_exchange", "polymarket")) == "kalshi" else 0
        self._switch(start_tab)
        self._refresh_poly_labels()

    # ------------------------------------------------------------------ tabs

    def _switch(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate((self._tab_poly, self._tab_kalshi)):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._db.set_setting("active_exchange", "kalshi" if index == 1 else "polymarket")

    def _refresh_poly_labels(self) -> None:
        """Timeframe column sa poly bottom bar — mula sa saved settings."""
        tf = str(self.poly_panel._db.get_setting("market_timeframe", "daily"))
        self.poly_panel.bottom.set_info_column("Timeframe", TF_LABELS.get(tf, tf))
        self.poly_panel.refresh_config_labels()

    # --------------------------------------------------------------- helpers

    def _apply_pointer_cursors(self, container: QWidget) -> None:
        """Hand cursor sa bawat clickable; block ang wheel sa spinbox/combo."""
        from PySide6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QDoubleSpinBox,
            QListWidget,
            QSpinBox,
            QToolButton,
        )

        from src.ui.widgets import WheelBlocker

        for cls in (QPushButton, QToolButton, QComboBox, QCheckBox):
            for widget in container.findChildren(cls):
                widget.setCursor(Qt.CursorShape.PointingHandCursor)
        for nav in container.findChildren(QListWidget, "sidebar"):
            nav.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        self._wheel_blocker = WheelBlocker(self)
        for cls in (QDoubleSpinBox, QSpinBox, QComboBox):
            for widget in container.findChildren(cls):
                widget.installEventFilter(self._wheel_blocker)
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
