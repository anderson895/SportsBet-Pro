"""Polymarket settings page — Bot Settings panel (port ng PolyTradePro).

Secrets -> Windows Credential Manager (keyring); numbers -> SQLite.
May 👁 toggle ang secret fields; blank = keep current value.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

import qtawesome as qta
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core import secrets
from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.settings_header import SettingsHeader, recommended_risk
from src.ui.widgets import Card

DEFAULTS = {
    "risk_usdc": 10.0,  # maliit na default — ligtas sa unang subok
    "min_stretch_pct": 1.5,
    "max_stretch_pct": 2.5,
    "profit_target_pct": 100.0,
    "volume_spike_mult": 2.0,
    "premium_threshold_pct": 0.15,
    "paper_start_usdc": 1000.0,
}


def _secret_field(current_key: str) -> tuple[QWidget, QLineEdit]:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText(f"Currently: {secrets.mask(secrets.get_secret(current_key))}")

    eye = QToolButton()
    eye.setIcon(qta.icon("fa6s.eye", color=theme.MUTED))
    eye.setCheckable(True)

    def _toggle(show: bool) -> None:
        edit.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )
        eye.setIcon(
            qta.icon("fa6s.eye-slash" if show else "fa6s.eye", color=theme.MUTED)
        )

    eye.toggled.connect(_toggle)
    container = QWidget()  # widget para pwedeng itago (hal. sa Paper mode)
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(edit)
    row.addWidget(eye)
    return container, edit


def _spin(value: float, suffix: str, maximum: float = 100_000.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0.01, maximum)
    box.setDecimals(2)
    box.setSuffix(f" {suffix}")
    box.setValue(value)
    return box


class PolySettingsPage(QWidget):
    # Para agad mag-update ang Dashboard balance card pag-Save —
    # hindi na kailangang i-START ang bot
    modeSaved = Signal(str)           # "PAPER" | "LIVE"
    liveBalanceChecked = Signal(float)  # totoong USDC mula sa save-check

    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db

        title = QLabel("Polymarket Bot Settings")
        title.setProperty("accent", True)
        g = self._db.get_setting

        form = QVBoxLayout()
        form.setSpacing(8)

        def add_field(label: str, widget_or_layout) -> QLabel:
            lab = QLabel(label)
            lab.setProperty("muted", True)
            lab.setContentsMargins(0, 6, 0, 0)
            form.addWidget(lab)
            if isinstance(widget_or_layout, QHBoxLayout):
                form.addLayout(widget_or_layout)
            else:
                form.addWidget(widget_or_layout)
            return lab

        # --- Trading mode ---------------------------------------------------
        self._mode = QComboBox()
        self._mode.addItems(["Paper (simulated — no real money)",
                             "Live (REAL MONEY — Polymarket)"])
        self._mode.setCurrentIndex(1 if g("trading_mode", "paper") == "live" else 0)
        add_field("Trading Mode", self._mode)

        mode_warn = QLabel(
            "Live mode requires Polymarket network access, a Private Key + "
            "Funder Address, and a USDC balance. If the connection fails, "
            "the bot automatically falls back to Paper mode."
        )
        mode_warn.setProperty("muted", True)
        mode_warn.setWordWrap(True)
        form.addWidget(mode_warn)

        # --- Market timeframe ----------------------------------------------
        # Aling Polymarket BTC Up/Down market ang ite-trade (dati daily lang)
        self._timeframe = QComboBox()
        self._timeframes = [
            ("Daily", "daily"),
            ("4 Hours", "4h"),
            ("1 Hour", "1h"),
            ("15 Minutes", "15m"),
        ]
        self._timeframe.addItems([label for label, _ in self._timeframes])
        saved_tf = str(g("market_timeframe", "daily"))
        self._timeframe.setCurrentIndex(next(
            (i for i, (_, v) in enumerate(self._timeframes) if v == saved_tf), 0
        ))
        add_field("Market Timeframe (Polymarket BTC Up/Down)", self._timeframe)

        tf_note = QLabel(
            "Strategy timings and stretch thresholds scale automatically to "
            "the selected timeframe (e.g., the 1.5% daily entry stretch "
            "becomes ~0.31% on 1-hour markets)."
        )
        tf_note.setProperty("muted", True)
        tf_note.setWordWrap(True)
        form.addWidget(tf_note)

        # --- Secrets (para sa LIVE mode lang — nakatago sa Paper) ----------
        # Walang Binance API key field — public data lang ang binabasa
        # ng app (charts/klines), hindi kailangan ng key
        pm_row, self._pm_private = _secret_field(secrets.KEY_PM_PRIVATE)
        pm_lab = add_field("Polymarket Private Key", pm_row)

        self._pm_funder = QLineEdit()
        self._pm_funder.setPlaceholderText(
            secrets.get_secret(secrets.KEY_PM_FUNDER) or "0x… (Polymarket profile address)"
        )
        funder_lab = add_field("Funder / Proxy Address", self._pm_funder)

        # Uri ng Polymarket wallet — nagdidikta ng signature_type
        # (1 = email/Magic proxy, 2 = MetaMask/browser wallet,
        #  3 = Deposit Wallet — mga account na ginawa pagkatapos ng
        #  CLOB V2 migration, Abril 2026; ang Funder ay ang "Address
        #  (For API use only)" sa polymarket.com Settings)
        self._sig_types = [
            ("Email / Google (Magic) — old account", "1"),
            ("MetaMask / browser wallet", "2"),
            ("Deposit Wallet (accounts after Apr 2026)", "3"),
        ]
        self._wallet_type = QComboBox()
        self._wallet_type.addItems([label for label, _ in self._sig_types])
        saved_sig = str(g("pm_signature_type", "1"))
        self._wallet_type.setCurrentIndex(
            next((i for i, (_, v) in enumerate(self._sig_types)
                  if v == saved_sig), 0)
        )
        wallet_lab = add_field("Polymarket Wallet Type", self._wallet_type)

        # Mga field na para sa LIVE mode lang — itinatago sa Paper (demo)
        self._live_only = [
            mode_warn,
            pm_lab, pm_row,
            funder_lab, self._pm_funder,
            wallet_lab, self._wallet_type,
        ]

        # --- Numbers ------------------------------------------------------
        self._risk = _spin(float(g("risk_usdc", DEFAULTS["risk_usdc"])), "USDC")
        add_field("Risk Per Trade (USDC)", self._risk)

        self._min_stretch = _spin(
            float(g("min_stretch_pct", DEFAULTS["min_stretch_pct"])), "%", 10.0
        )
        add_field("Entry Stretch Band (%)", self._min_stretch)

        self._max_stretch = _spin(
            float(g("max_stretch_pct", DEFAULTS["max_stretch_pct"])), "%", 10.0
        )
        add_field("Max Stretch — Death Trap Limit (%)", self._max_stretch)

        self._profit = _spin(
            float(g("profit_target_pct", DEFAULTS["profit_target_pct"])), "%", 1000.0
        )
        add_field("Take Profit (%)", self._profit)

        self._volume_mult = _spin(
            float(g("volume_spike_mult", DEFAULTS["volume_spike_mult"])), "× baseline", 10.0
        )
        add_field("Volume Spike Filter — block entry above (×)", self._volume_mult)

        self._premium = _spin(
            float(g("premium_threshold_pct", DEFAULTS["premium_threshold_pct"])), "%", 5.0
        )
        add_field("Coinbase Premium Filter — block entry above (±%)", self._premium)

        self._econ_day = QCheckBox(
            "Economic Data Day — block entries TODAY (Fed meeting, CPI, etc.)"
        )
        self._econ_day.setChecked(
            g("econ_block_date") == dt.datetime.now(dt.timezone.utc).date().isoformat()
        )
        self._econ_day.setContentsMargins(2, 0, 2, 0)
        form.addSpacing(8)  # breathing room mula sa spinbox sa itaas
        form.addWidget(self._econ_day)
        form.addSpacing(4)

        self._paper_start = _spin(
            float(g("paper_start_usdc", DEFAULTS["paper_start_usdc"])), "USDC"
        )
        self._paper_start_lab = add_field(
            "Paper Starting Balance (USDC)", self._paper_start
        )

        # Ipakita lang ang mga field na para sa napiling mode:
        # Paper (demo)  -> nakatago ang Private Key/Funder/Sign-up Method
        # Live          -> nakatago ang Paper Starting Balance
        def _toggle_mode_fields(index: int) -> None:
            paper = index == 0
            self._paper_start.setVisible(paper)
            self._paper_start_lab.setVisible(paper)
            for w in self._live_only:
                w.setVisible(not paper)

        self._mode.currentIndexChanged.connect(_toggle_mode_fields)
        _toggle_mode_fields(self._mode.currentIndex())

        # --- Sticky header (balance + Save/Reset/Recommended) -------------
        # Nasa LABAS ng scroll area para laging kita ang Save — hindi na
        # makakalimutang i-save bago pindutin ang START BOT.
        self.header = SettingsHeader(
            currency="USDC",
            on_save=self._save,
            on_reset=self._reset,
            on_recommend=self._apply_recommended,
            on_refresh=self._fetch_balance,
        )
        self._last_balance: float | None = None
        self._balance_fetched_ts = 0.0
        # Pag-palit ng Paper/Live: ibang balance ang dapat ipakita
        self._mode.currentIndexChanged.connect(
            lambda _i: self._fetch_balance()
        )

        note = QLabel(
            "Secrets are stored in Windows Credential Manager, never in files.\n"
            "Leave a secret field blank to keep its current value."
        )
        note.setProperty("muted", True)
        note.setWordWrap(True)

        panel = Card()
        panel_col = QVBoxLayout(panel)
        panel_col.setContentsMargins(18, 16, 18, 16)
        panel_col.setSpacing(10)
        panel_col.addWidget(title)
        panel_col.addLayout(form)
        panel_col.addWidget(note)

        # Scroll para hindi masiksik (at ma-clip) ang mga input sa maliliit
        # na window — mag-i-scroll sa halip na mag-compress
        wrapper = QWidget()
        wrapper_col = QVBoxLayout(wrapper)
        wrapper_col.setContentsMargins(0, 0, 8, 0)
        wrapper_col.addWidget(panel)
        wrapper_col.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(wrapper)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self.header)
        root.addWidget(scroll)

    # ------------------------------------------------------------------ save

    def _save(self) -> None:
        if self._pm_private.text().strip():
            secrets.set_secret(secrets.KEY_PM_PRIVATE, self._pm_private.text().strip())
            self._pm_private.clear()
        if self._pm_funder.text().strip():
            secrets.set_secret(secrets.KEY_PM_FUNDER, self._pm_funder.text().strip())

        self._db.set_setting(
            "trading_mode", "live" if self._mode.currentIndex() == 1 else "paper"
        )
        self._db.set_setting(
            "pm_signature_type",
            self._sig_types[self._wallet_type.currentIndex()][1],
        )
        self._db.set_setting(
            "market_timeframe",
            self._timeframes[self._timeframe.currentIndex()][1],
        )
        self._db.set_setting("risk_usdc", self._risk.value())
        self._db.set_setting("min_stretch_pct", self._min_stretch.value())
        self._db.set_setting("max_stretch_pct", self._max_stretch.value())
        self._db.set_setting("profit_target_pct", self._profit.value())
        self._db.set_setting("volume_spike_mult", self._volume_mult.value())
        self._db.set_setting("premium_threshold_pct", self._premium.value())
        # Econ day: itinatabi ang PETSA para awtomatikong mag-expire bukas
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        self._db.set_setting("econ_block_date", today if self._econ_day.isChecked() else "")
        self._db.set_setting("paper_start_usdc", self._paper_start.value())
        self._set_status("Settings saved ✓", theme.GREEN)
        # I-update agad ang Dashboard balance card ayon sa napiling mode
        self.modeSaved.emit(
            "LIVE" if self._mode.currentIndex() == 1 else "PAPER"
        )
        self._validate_credentials()

    # -------------------------------------------------- credential check

    def _set_status(self, text: str, color: str) -> None:
        self.header.set_status(text, color)

    # ------------------------------------------------ balance + recommend

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Unang bukas ng page (o balik dito): i-fetch ang balance para
        UNA itong makita bago mag-configure."""
        super().showEvent(event)
        if time.monotonic() - self._balance_fetched_ts > 60:
            self._fetch_balance()

    def _fetch_balance(self) -> None:
        self._balance_fetched_ts = time.monotonic()

        # Paper mode: paper balance = starting balance + naipong PnL
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
            self.header.set_balance(
                None, "Add Private Key + Funder below, then Save")
            return
        sig_type = int(self._sig_types[self._wallet_type.currentIndex()][1])
        self.header.set_balance(None, "Fetching live balance…")

        def _check() -> float:
            from src.execution.polymarket import PolymarketClient
            client = PolymarketClient(
                private_key=pk, funder=funder, signature_type=sig_type
            )
            client.connect()
            return client.get_usdc_balance()

        async def _run() -> None:
            try:
                bal = await asyncio.to_thread(_check)
                self._last_balance = bal
                self.header.set_balance(bal, "Real USDC on Polymarket")
            except Exception as e:
                self.header.set_balance(None, f"Balance fetch failed: {e}")

        try:
            asyncio.create_task(_run())
        except RuntimeError:
            pass  # walang running event loop (hal. sa UI tests)

    def _apply_recommended(self) -> None:
        """Isang click: ligtas na testing values na pasok sa balance.

        Risk ≈ 10% ng balance (min 2 USDC); ibang strategy knobs ay
        binabalik sa proven defaults.
        """
        # Walang balance = hindi pa masasabi kung magkano ang ligtas.
        # Mag-fetch muna kaysa mag-alok ng maling maliit na halaga.
        if self._last_balance is None:
            self._fetch_balance()
            self._set_status(
                "Fetching your balance first — click Apply Recommended "
                "again in a moment so the risk can be sized to it.",
                theme.AMBER,
            )
            return

        rec = recommended_risk(self._last_balance, minimum=2.0)
        self._risk.setValue(rec)
        self._min_stretch.setValue(DEFAULTS["min_stretch_pct"])
        self._max_stretch.setValue(DEFAULTS["max_stretch_pct"])
        self._profit.setValue(DEFAULTS["profit_target_pct"])
        self._volume_mult.setValue(DEFAULTS["volume_spike_mult"])
        self._premium.setValue(DEFAULTS["premium_threshold_pct"])
        self._set_status(
            f"Recommended values applied — Risk {rec:,.2f} USDC (10% of your "
            f"{self._last_balance:,.2f} USDC balance), stretch 1.5/2.5%, "
            "TP 100%. Click Save Settings to apply.",
            theme.AMBER,
        )

    def _validate_credentials(self) -> None:
        """Pagkatapos mag-Save: i-verify ang Polymarket credentials at
        ipakita ang resulta (✓ may balance / ✗ may dahilan).

        Read-only ito (derive creds + basahin ang balance) — WALANG order.
        May 3 retries dahil may panandaliang network errors minsan.
        """
        pk = secrets.get_secret(secrets.KEY_PM_PRIVATE)
        funder = secrets.get_secret(secrets.KEY_PM_FUNDER)
        if not pk or not funder:
            return  # wala pang creds — walang ive-verify
        sig_type = int(self._sig_types[self._wallet_type.currentIndex()][1])

        def _check() -> float:
            from src.execution.polymarket import PolymarketClient
            last: Exception | None = None
            for _ in range(3):
                try:
                    client = PolymarketClient(
                        private_key=pk, funder=funder, signature_type=sig_type
                    )
                    client.connect()
                    return client.get_usdc_balance()
                except Exception as e:  # transient network errors
                    last = e
                    time.sleep(2)
            raise last

        async def _run() -> None:
            try:
                balance = await asyncio.to_thread(_check)
                if balance > 0:
                    self._set_status(
                        f"✓ Settings saved — Polymarket credentials OK! "
                        f"Balance: {balance:,.2f} USDC",
                        theme.GREEN,
                    )
                else:
                    # Tanggap ng Polymarket ang KAHIT ANONG valid na key —
                    # ang 0 balance ang tanging senyales na baka mali ang
                    # key/funder (o wala lang talagang deposit)
                    self._set_status(
                        "✓ Settings saved — credentials accepted, but the "
                        "balance is 0.00 USDC. If you have funds on "
                        "Polymarket, the Private Key or Funder Address "
                        "may be incorrect.",
                        theme.AMBER,
                    )
                if self._mode.currentIndex() == 1:  # Live ang naka-save
                    self._last_balance = balance
                    self.header.set_balance(balance, "Real USDC on Polymarket")
                    self.liveBalanceChecked.emit(balance)
            except Exception as e:
                self._set_status(
                    f"✗ Settings saved, but the credential check failed: {e}",
                    theme.RED,
                )

        self._set_status(
            "Settings saved ✓ — verifying Polymarket credentials…",
            theme.AMBER,
        )
        try:
            asyncio.create_task(_run())
        except RuntimeError:
            pass  # walang running event loop (hal. sa UI tests)

    def _reset(self) -> None:
        # I-restore lang ang STRATEGY VALUES sa defaults — HINDI ginagalaw
        # ang Trading Mode at Sign-up Method (account configuration iyon,
        # hindi tunable values)
        self._risk.setValue(DEFAULTS["risk_usdc"])
        self._min_stretch.setValue(DEFAULTS["min_stretch_pct"])
        self._max_stretch.setValue(DEFAULTS["max_stretch_pct"])
        self._profit.setValue(DEFAULTS["profit_target_pct"])
        self._volume_mult.setValue(DEFAULTS["volume_spike_mult"])
        self._premium.setValue(DEFAULTS["premium_threshold_pct"])
        self._econ_day.setChecked(False)
        self._paper_start.setValue(DEFAULTS["paper_start_usdc"])
        self._set_status("Defaults restored — click Save Settings to apply",
                         theme.MUTED)
