"""SportsBet Pro main window — dalawang exchange panel (Polymarket + Kalshi).

Sa itaas may exchange switcher tabs; bawat tab ay isang buong ExchangePanel
na may sariling sub-navigation, dashboard, settings, logs, trades, stats,
at SARILING START/STOP. Independent ang dalawang bot — parehong pwedeng
tumakbo nang sabay sa iisang qasync event loop.
"""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
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
from src.ui import help_content, theme
from src.ui.exchange_panel import ExchangePanel
from src.ui.kalshi_dashboard import KalshiDashboard
from src.ui.kalshi_settings import KalshiSettingsPage
from src.ui.loading_overlay import LoadingOverlay
from src.ui.poly_dashboard import PolyDashboard
from src.ui.poly_settings import PolySettingsPage

APP_VERSION = "1.3.4"

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
            about_title=f"Help & Documentation  ·  v{APP_VERSION}",
            about_body="",
            accent=theme.POLY_ACCENT,
            accent_dim=theme.POLY_ACCENT_DIM,
            help_tag=help_content.POLYMARKET,
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
            about_title=f"Help & Documentation  ·  v{APP_VERSION}",
            about_body="",
            accent=theme.KALSHI_ACCENT,
            accent_dim=theme.KALSHI_ACCENT_DIM,
            help_tag=help_content.KALSHI,
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
        kalshi_engine.marketTick.connect(kalshi_dash.update_market_tick)
        kalshi_dash.focusRequested.connect(kalshi_engine.set_chart_focus)
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
        # Bawat tab ay may sariling accent underline kapag active
        self._tab_poly.setStyleSheet(
            f'QPushButton[exchangeTab="true"][active="true"] {{ '
            f'border-bottom: 3px solid {theme.POLY_ACCENT}; '
            f'color: {theme.TEXT}; }}'
        )
        self._tab_kalshi.setStyleSheet(
            f'QPushButton[exchangeTab="true"][active="true"] {{ '
            f'border-bottom: 3px solid {theme.KALSHI_ACCENT}; '
            f'color: {theme.TEXT}; }}'
        )
        for btn in (self._tab_poly, self._tab_kalshi):
            btn.setProperty("exchangeTab", True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_poly.clicked.connect(lambda: self._switch(0))
        self._tab_kalshi.clicked.connect(lambda: self._switch(1))

        version = QLabel(f"v{APP_VERSION}")
        version.setProperty("muted", True)

        # ---- Shared page nav (Dashboard/Settings/...) — nakasentro sa taas,
        #      kapantay ng brand; kontrolado ang page ng dalawang panel
        self._page_btns: list[QPushButton] = []
        page_nav = QHBoxLayout()
        page_nav.setSpacing(2)
        for i, (icon_name, label) in enumerate(ExchangePanel.PAGES):
            b = QPushButton(f"  {label}")
            b.setProperty("navItem", True)
            b.setIcon(qta.icon(icon_name, color=theme.MUTED))
            b.setIconSize(QSize(15, 15))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, idx=i: self._select_page(idx))
            self._page_btns.append(b)
            page_nav.addWidget(b)

        # Row 1: brand (left) + page nav (center) + version (right)
        top = QHBoxLayout()
        top.setContentsMargins(16, 8, 16, 0)
        top.setSpacing(10)
        top.addWidget(brand_icon)
        top.addWidget(brand)
        top.addStretch()
        top.addLayout(page_nav)
        top.addStretch()
        top.addWidget(version)

        # Row 2: exchange tabs (Polymarket / Kalshi) — LEFT side
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(16, 0, 16, 0)
        tabs_row.setSpacing(4)
        tabs_row.addWidget(self._tab_poly)
        tabs_row.addWidget(self._tab_kalshi)
        tabs_row.addStretch()

        # ---- Panel stack -------------------------------------------------
        self._stack = QStackedWidget()
        self._stack.addWidget(self.poly_panel)
        self._stack.addWidget(self.kalshi_panel)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 8, 8)
        root.addLayout(top)
        root.addLayout(tabs_row)
        root.addWidget(self._stack, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

        # Pointer cursor + wheel blocking sa lahat ng inputs (tulad ng dati)
        self._apply_pointer_cursors(container)

        # I-restore ang huling aktibong tab + default page
        self._active_page = 0
        self._current_accent = theme.POLY_ACCENT  # itatakda ng _switch
        start_tab = 1 if str(db.get_setting("active_exchange", "polymarket")) == "kalshi" else 0
        self._switch(start_tab)
        self._select_page(0)
        self._refresh_poly_labels()

        # ---- Startup gate: huwag ipagamit hangga't hindi pa handa ---------
        self._loading = LoadingOverlay(
            [
                ("internet", "Checking internet connection"),
                ("binance", "Connecting to Binance price feed"),
                ("polymarket", "Connecting to Polymarket"),
                ("kalshi", "Connecting to Kalshi"),
                ("markets", "Loading live sports markets"),
            ],
            parent=container,
        )
        # Tinatapos ng connection monitor at ng unang market scan ang mga
        # hakbang; may sariling timeout ang overlay kung may hindi tumugon.
        poly_engine.connectionChanged.connect(self._on_startup_connection)
        kalshi_engine.marketsScanned.connect(self._on_startup_markets)

    # --------------------------------------------------------- startup gate
    # (sinusundan mismo ng overlay ang sukat ng parent — tingnan ang
    #  LoadingOverlay.eventFilter)

    def _on_startup_connection(self, name: str, _up: bool) -> None:
        """Tapos na ang isang connection check — up man o down.

        Sinusukat natin ang "nalaman na natin ang estado", hindi ang
        "konektado" — kung hindi, mananatiling naka-lock ang app kapag
        offline ang isang service.
        """
        self._loading.mark_done(name)

    def _on_startup_markets(self, rows: list) -> None:
        # Kahit walang laman: nakausap na natin ang Kalshi, tapos na ang scan
        self._loading.mark_done("markets")

    @staticmethod
    def _exchange_accent(index: int) -> str:
        return theme.KALSHI_ACCENT if index == 1 else theme.POLY_ACCENT

    def _select_page(self, index: int) -> None:
        """Shared page nav — parehong panel ay lumilipat sa parehong page."""
        self._active_page = index
        self.poly_panel.set_page(index)
        self.kalshi_panel.set_page(index)
        self._highlight_page()

    def _highlight_page(self) -> None:
        """I-highlight ang aktibong page gamit ang accent ng KASALUKUYANG
        exchange (indigo sa Polymarket, mint sa Kalshi)."""
        for i, b in enumerate(self._page_btns):
            active = i == self._active_page
            b.setProperty("active", active)
            # Per-exchange underline color sa aktibong button
            b.setStyleSheet(
                f'QPushButton[navItem="true"][active="true"] {{ '
                f'border-bottom: 2px solid {self._current_accent}; '
                f'color: {theme.TEXT}; }}'
            )
            icon_name = ExchangePanel.PAGES[i][0]
            b.setIcon(qta.icon(
                icon_name,
                color=(self._current_accent if active else theme.MUTED)))
            b.style().unpolish(b)
            b.style().polish(b)

    # ------------------------------------------------------------------ tabs

    def _switch(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate((self._tab_poly, self._tab_kalshi)):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._db.set_setting("active_exchange", "kalshi" if index == 1 else "polymarket")
        # I-tint ang page nav ayon sa aktibong exchange
        self._current_accent = self._exchange_accent(index)
        self._highlight_page()

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
