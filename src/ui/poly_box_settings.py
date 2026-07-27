"""Polymarket Box-Arbitrage settings page — credentials + straddle knobs.

Polymarket credentials (Private Key + Funder + Wallet Type) plus the same
box-arbitrage knobs as the Kalshi panel (entry price, Hedge Sentinel, volume,
time-to-close). Secrets → Windows Credential Manager; numbers → SQLite
(scoped to the "polymarket." prefix).
"""
from __future__ import annotations

import asyncio
import time

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core import secrets
from src.execution.poly_box import SPORT_LEAGUES
from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.settings_header import SettingsHeader, recommended_risk
from src.ui.widgets import Card, run_async

DEFAULTS = {
    "risk_usdc": 10.0,
    "entry_price_cents": 49,
    "hedge_max_price": 51,
    "hedge_timeout_secs": 90.0,
    "min_volume_usd": 10000,
    "min_close_mins": 30.0,
    "max_close_hours": 24.0,
    "paper_start_usdc": 1000.0,
}


def _spin_f(value: float, suffix: str, maximum: float = 100_000.0,
            minimum: float = 0.01) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(2)
    box.setSuffix(f" {suffix}")
    box.setValue(value)
    return box


def _spin_i(value: int, suffix: str, minimum: int = 1,
            maximum: int = 10_000_000) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setSuffix(f" {suffix}")
    box.setValue(value)
    return box


class PolyBoxSettingsPage(QWidget):
    modeSaved = Signal(str)
    liveBalanceChecked = Signal(float)

    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        title = QLabel("Polymarket Bot Settings")
        title.setProperty("accent", True)
        g = self._db.get_setting

        form = QVBoxLayout()
        form.setSpacing(8)

        def add_field(label: str, widget) -> QLabel:
            lab = QLabel(label)
            lab.setProperty("muted", True)
            lab.setContentsMargins(0, 6, 0, 0)
            form.addWidget(lab)
            if isinstance(widget, QHBoxLayout):
                form.addLayout(widget)
            else:
                form.addWidget(widget)
            return lab

        # --- Trading mode -------------------------------------------------
        self._mode = QComboBox()
        self._mode.addItems(["Paper (simulated — no real money)",
                             "Live (REAL MONEY — Polymarket)"])
        self._mode.setCurrentIndex(1 if g("trading_mode", "paper") == "live" else 0)
        add_field("Trading Mode", self._mode)

        mode_warn = QLabel(
            "Live mode requires Polymarket network access, a Private Key + "
            "Funder Address, and a USDC balance. If the connection fails, the "
            "bot automatically falls back to Paper mode.")
        mode_warn.setProperty("muted", True)
        mode_warn.setWordWrap(True)
        form.addWidget(mode_warn)

        # --- Credentials (LIVE only) --------------------------------------
        pk_container = QWidget()
        pk_row = QHBoxLayout(pk_container)
        pk_row.setContentsMargins(0, 0, 0, 0)
        self._pm_private = QLineEdit()
        self._pm_private.setEchoMode(QLineEdit.EchoMode.Password)
        self._pm_private.setPlaceholderText(
            f"Currently: {secrets.mask(secrets.get_secret(secrets.KEY_PM_PRIVATE))}")
        eye = QToolButton()
        eye.setIcon(qta.icon("fa6s.eye", color=theme.MUTED))
        eye.setCheckable(True)
        eye.toggled.connect(lambda s: self._pm_private.setEchoMode(
            QLineEdit.EchoMode.Normal if s else QLineEdit.EchoMode.Password))
        pk_row.addWidget(self._pm_private)
        pk_row.addWidget(eye)
        pk_lab = add_field("Polymarket Private Key", pk_container)

        self._pm_funder = QLineEdit()
        self._pm_funder.setPlaceholderText(
            secrets.get_secret(secrets.KEY_PM_FUNDER)
            or "0x… (Polymarket 'Address for API use only')")
        funder_lab = add_field("Funder / Proxy Address", self._pm_funder)

        self._sig_types = [
            ("Email / Google (Magic) — old account", "1"),
            ("MetaMask / browser wallet", "2"),
            ("Deposit Wallet (accounts after Apr 2026)", "3"),
        ]
        self._wallet_type = QComboBox()
        self._wallet_type.addItems([l for l, _ in self._sig_types])
        saved_sig = str(g("pm_signature_type", "1"))
        self._wallet_type.setCurrentIndex(
            next((i for i, (_, v) in enumerate(self._sig_types)
                  if v == saved_sig), 0))
        wallet_lab = add_field("Polymarket Wallet Type", self._wallet_type)

        self._live_only = [mode_warn, pk_lab, pk_container, funder_lab,
                           self._pm_funder, wallet_lab, self._wallet_type]

        # --- Box-arbitrage knobs ------------------------------------------
        self._risk = _spin_f(float(g("risk_usdc", DEFAULTS["risk_usdc"])), "USDC")
        add_field("Risk Per Straddle (USDC)", self._risk)

        self._entry = _spin_i(int(float(g("entry_price_cents",
                              DEFAULTS["entry_price_cents"]))), "¢ per side", 1, 99)
        add_field("Entry Price (resting bid per side)", self._entry)

        self._hedge_max = _spin_i(int(float(g("hedge_max_price",
                                 DEFAULTS["hedge_max_price"]))), "¢ max", 1, 99)
        add_field("Hedge Sentinel — max hedge price", self._hedge_max)

        self._hedge_timeout = _spin_f(float(g("hedge_timeout_secs",
                              DEFAULTS["hedge_timeout_secs"])), "seconds", 3600.0, 5.0)
        add_field("Hedge Sentinel — single-sided timeout", self._hedge_timeout)

        self._min_volume = _spin_i(int(float(g("min_volume_usd",
                              DEFAULTS["min_volume_usd"]))), "USD volume", 0)
        add_field("Minimum Market Volume", self._min_volume)

        self._min_close = _spin_f(float(g("min_close_mins",
                                 DEFAULTS["min_close_mins"])), "minutes", 100_000.0, 1.0)
        add_field("Skip markets closing sooner than", self._min_close)

        self._max_close = _spin_f(float(g("max_close_hours",
                                 DEFAULTS["max_close_hours"])), "hours", 10_000.0, 0.1)
        add_field("Skip markets closing later than", self._max_close)

        # Sports to trade — same friendly checkboxes as the Kalshi panel.
        # Without this the scan pulled Polymarket's top markets platform-wide,
        # which is elections and crypto, not sport.
        saved_leagues = {s.strip() for s in
                         str(g("sport_leagues", "")).split("|") if s.strip()}
        self._sport_cbs: list[QCheckBox] = []
        sports_grid = QGridLayout()
        sports_grid.setContentsMargins(0, 2, 0, 0)
        sports_grid.setHorizontalSpacing(20)
        sports_grid.setVerticalSpacing(6)
        for i, (label, _prefixes) in enumerate(SPORT_LEAGUES):
            cb = QCheckBox(label)
            cb.setChecked(label in saved_leagues)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            self._sport_cbs.append(cb)
            sports_grid.addWidget(cb, i // 2, i % 2)  # 2 columns
        sports_wrap = QWidget()
        sports_wrap.setLayout(sports_grid)
        # Transparent so it blends into the card (no black box behind it)
        sports_wrap.setStyleSheet("background: transparent;")
        add_field("Sports to Trade", sports_wrap)
        sports_hint = QLabel(
            "Pick the leagues to scan for 50/50 games. Leave all unchecked "
            "to scan every sport.")
        sports_hint.setProperty("muted", True)
        sports_hint.setWordWrap(True)
        form.addWidget(sports_hint)

        self._paper_start = _spin_f(float(g("paper_start_usdc",
                                   DEFAULTS["paper_start_usdc"])), "USDC")
        self._paper_start_lab = add_field(
            "Paper Starting Balance (USDC)", self._paper_start)

        def _toggle_mode_fields(index: int) -> None:
            paper = index == 0
            self._paper_start.setVisible(paper)
            self._paper_start_lab.setVisible(paper)
            for w in self._live_only:
                w.setVisible(not paper)

        self._mode.currentIndexChanged.connect(_toggle_mode_fields)
        self._toggle_mode_fields = _toggle_mode_fields

        # --- Sticky header ------------------------------------------------
        self.header = SettingsHeader(
            currency="USDC", on_save=self._save, on_reset=self._reset,
            on_recommend=self._apply_recommended, on_refresh=self._fetch_balance)
        self._last_balance: float | None = None
        self._balance_fetched_ts = 0.0
        self._mode.currentIndexChanged.connect(lambda _i: self._fetch_balance())

        note = QLabel(
            "Secrets are stored in Windows Credential Manager, never in files.\n"
            "Leave a secret field blank to keep its current value.")
        note.setProperty("muted", True)
        note.setWordWrap(True)

        panel = Card()
        pcol = QVBoxLayout(panel)
        pcol.setContentsMargins(18, 16, 18, 16)
        pcol.setSpacing(10)
        pcol.addWidget(title)
        pcol.addLayout(form)
        pcol.addWidget(note)

        wrapper = QWidget()
        wcol = QVBoxLayout(wrapper)
        wcol.setContentsMargins(0, 0, 8, 0)
        wcol.addWidget(panel)
        wcol.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(wrapper)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self.header)
        root.addWidget(scroll)
        self._toggle_mode_fields(self._mode.currentIndex())

    # ------------------------------------------------------------------ save

    def _save(self) -> None:
        if self._pm_private.text().strip():
            secrets.set_secret(secrets.KEY_PM_PRIVATE, self._pm_private.text().strip())
            self._pm_private.clear()
        if self._pm_funder.text().strip():
            secrets.set_secret(secrets.KEY_PM_FUNDER, self._pm_funder.text().strip())
        self._db.set_setting(
            "trading_mode", "live" if self._mode.currentIndex() == 1 else "paper")
        self._db.set_setting("pm_signature_type",
                             self._sig_types[self._wallet_type.currentIndex()][1])
        self._db.set_setting("risk_usdc", self._risk.value())
        self._db.set_setting("entry_price_cents", self._entry.value())
        self._db.set_setting("hedge_max_price", self._hedge_max.value())
        self._db.set_setting("hedge_timeout_secs", self._hedge_timeout.value())
        self._db.set_setting("min_volume_usd", self._min_volume.value())
        self._db.set_setting("min_close_mins", self._min_close.value())
        self._db.set_setting("max_close_hours", self._max_close.value())
        chosen = [label for (label, _p), cb
                  in zip(SPORT_LEAGUES, self._sport_cbs) if cb.isChecked()]
        self._db.set_setting("sport_leagues", "|".join(chosen))
        self._db.set_setting("paper_start_usdc", self._paper_start.value())
        self._set_status("Settings saved ✓", theme.GREEN)
        self.modeSaved.emit("LIVE" if self._mode.currentIndex() == 1 else "PAPER")
        if self._mode.currentIndex() == 1:
            self._validate_credentials()

    def _set_status(self, text: str, color: str) -> None:
        self.header.set_status(text, color)

    # ------------------------------------------------ balance + recommend

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if time.monotonic() - self._balance_fetched_ts > 60:
            self._fetch_balance()

    def _fetch_balance(self) -> None:
        self._balance_fetched_ts = time.monotonic()
        if self._mode.currentIndex() == 0:
            start = float(self._db.get_setting(
                "paper_start_usdc", DEFAULTS["paper_start_usdc"]))
            bal = start + self._db.total_pnl()
            self._last_balance = bal
            self.header.set_balance(bal, "Paper balance (simulated)")
            return
        pk = secrets.get_secret(secrets.KEY_PM_PRIVATE)
        funder = secrets.get_secret(secrets.KEY_PM_FUNDER)
        if not pk or not funder:
            self.header.set_balance(None, "Add Private Key + Funder, then Save")
            return
        sig = int(self._sig_types[self._wallet_type.currentIndex()][1])
        self.header.set_balance(None, "Fetching live balance…")

        def _check() -> float:
            from src.execution.polymarket import PolymarketClient
            c = PolymarketClient(private_key=pk, funder=funder, signature_type=sig)
            c.connect()
            return c.get_usdc_balance()

        async def _run() -> None:
            try:
                bal = await asyncio.to_thread(_check)
                self._last_balance = bal
                self.header.set_balance(bal, "Real USDC on Polymarket")
            except Exception as e:
                self.header.set_balance(None, f"Balance fetch failed: {e}")

        run_async(_run())

    def _apply_recommended(self) -> None:
        if self._last_balance is None:
            self._fetch_balance()
            self._set_status("Fetching your balance first — click Apply "
                             "Recommended again in a moment.", theme.AMBER)
            return
        rec = recommended_risk(self._last_balance, minimum=2.0)
        self._risk.setValue(rec)
        self._entry.setValue(DEFAULTS["entry_price_cents"])
        self._hedge_max.setValue(DEFAULTS["hedge_max_price"])
        self._hedge_timeout.setValue(DEFAULTS["hedge_timeout_secs"])
        self._min_volume.setValue(DEFAULTS["min_volume_usd"])
        self._set_status(
            f"Recommended values applied — Risk {rec:,.2f} USDC, entry 49¢, "
            "hedge 51¢/90s. Click Save Settings to apply.", theme.AMBER)

    def _validate_credentials(self) -> None:
        pk = secrets.get_secret(secrets.KEY_PM_PRIVATE)
        funder = secrets.get_secret(secrets.KEY_PM_FUNDER)
        if not pk or not funder:
            self._set_status("Settings saved ✓ — add Private Key + Funder to "
                             "enable Live mode.", theme.AMBER)
            return
        sig = int(self._sig_types[self._wallet_type.currentIndex()][1])

        def _check() -> float:
            from src.execution.polymarket import PolymarketClient
            c = PolymarketClient(private_key=pk, funder=funder, signature_type=sig)
            c.connect()
            return c.get_usdc_balance()

        async def _run() -> None:
            try:
                bal = await asyncio.to_thread(_check)
                self._set_status(
                    f"✓ Settings saved — Polymarket credentials OK! "
                    f"Balance: {bal:,.2f} USDC", theme.GREEN)
                self._last_balance = bal
                self.header.set_balance(bal, "Real USDC on Polymarket")
                self.liveBalanceChecked.emit(bal)
            except Exception as e:
                self._set_status(
                    f"✗ Settings saved, but the credential check failed: {e}",
                    theme.RED)

        self._set_status("Settings saved ✓ — verifying Polymarket credentials…",
                         theme.AMBER)
        run_async(_run())

    def _reset(self) -> None:
        self._risk.setValue(DEFAULTS["risk_usdc"])
        self._entry.setValue(DEFAULTS["entry_price_cents"])
        self._hedge_max.setValue(DEFAULTS["hedge_max_price"])
        self._hedge_timeout.setValue(DEFAULTS["hedge_timeout_secs"])
        self._min_volume.setValue(DEFAULTS["min_volume_usd"])
        self._min_close.setValue(DEFAULTS["min_close_mins"])
        self._max_close.setValue(DEFAULTS["max_close_hours"])
        self._paper_start.setValue(DEFAULTS["paper_start_usdc"])
        self._set_status("Defaults restored — click Save Settings to apply",
                         theme.MUTED)
