"""Kalshi settings page — credentials + mean-reversion strategy knobs.

Same strategy settings as the Polymarket page (risk, timeframe, stretch band,
take-profit, death-trap filters) plus Kalshi's own credentials (API Key ID +
RSA private key PEM + environment). Secrets go to Windows Credential Manager;
numbers to SQLite (scoped to the "kalshi." prefix via ScopedDatabase).

The RSA private key may be pasted (stored in Credential Manager) or given as a
.pem file path (for keys too large for the ~2.5KB Credential Manager blob).
"""
from __future__ import annotations

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
    QPlainTextEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core import secrets
from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.settings_header import SettingsHeader, recommended_risk
from src.ui.widgets import Card, run_async

DEFAULTS = {
    "risk_usd": 5.0,  # maliit na default — ligtas sa unang subok
    "min_stretch_pct": 1.5,
    "max_stretch_pct": 2.5,
    "profit_target_pct": 100.0,
    "volume_spike_mult": 2.0,
    "premium_threshold_pct": 0.15,
    "paper_start_usd": 1000.0,
}


def _spin(value: float, suffix: str, maximum: float = 100_000.0,
          minimum: float = 0.01) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(2)
    box.setSuffix(f" {suffix}")
    box.setValue(value)
    return box


class KalshiSettingsPage(QWidget):
    modeSaved = Signal(str)             # "PAPER" | "LIVE"
    liveBalanceChecked = Signal(float)  # totoong USD mula sa save-check

    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db

        title = QLabel("Kalshi Bot Settings")
        title.setProperty("accent", True)
        g = self._db.get_setting

        form = QVBoxLayout()
        form.setSpacing(8)

        def add_field(label: str, widget) -> QLabel:
            lab = QLabel(label)
            lab.setProperty("muted", True)
            lab.setContentsMargins(0, 6, 0, 0)
            form.addWidget(lab)
            form.addWidget(widget)
            return lab

        # --- Trading mode -------------------------------------------------
        self._mode = QComboBox()
        self._mode.addItems(["Paper (simulated — no real money)",
                             "Live (REAL MONEY — Kalshi)"])
        self._mode.setCurrentIndex(
            1 if g("trading_mode", "paper") == "live" else 0)
        add_field("Trading Mode", self._mode)

        mode_warn = QLabel(
            "Live mode requires Kalshi API access (API Key ID + RSA private "
            "key) and a USD balance. If the connection fails, the bot "
            "automatically falls back to Paper mode."
        )
        mode_warn.setProperty("muted", True)
        mode_warn.setWordWrap(True)
        form.addWidget(mode_warn)

        # --- Market timeframe ---------------------------------------------
        # Kalshi's clean BTC up/down ladder (KXBTCD) is hourly; daily attempted
        # when listed. Shorter frames have no Kalshi up/down market.
        self._timeframe = QComboBox()
        self._timeframes = [("1 Hour", "1h"), ("Daily", "daily")]
        self._timeframe.addItems([label for label, _ in self._timeframes])
        saved_tf = str(g("market_timeframe", "1h"))
        self._timeframe.setCurrentIndex(next(
            (i for i, (_, v) in enumerate(self._timeframes) if v == saved_tf), 0
        ))
        add_field("Market Timeframe (Kalshi BTC Above/Below)", self._timeframe)

        tf_note = QLabel(
            "The bot pins the KXBTCD strike nearest the period open as the "
            "up/down pivot; stretch thresholds scale automatically to the "
            "timeframe (e.g. the 1.5% daily entry becomes ~0.31% on 1-hour)."
        )
        tf_note.setProperty("muted", True)
        tf_note.setWordWrap(True)
        form.addWidget(tf_note)

        # --- Environment --------------------------------------------------
        self._env = QComboBox()
        self._envs = [("Production (kalshi.com)", "prod"),
                      ("Demo (practice money — demo.kalshi.co)", "demo")]
        self._env.addItems([label for label, _ in self._envs])
        saved_env = str(g("env", "prod"))
        self._env.setCurrentIndex(
            next((i for i, (_, v) in enumerate(self._envs) if v == saved_env), 0)
        )
        env_lab = add_field("Environment", self._env)

        # --- Credentials (LIVE only) --------------------------------------
        key_container = QWidget()
        key_row = QHBoxLayout(key_container)
        key_row.setContentsMargins(0, 0, 0, 0)
        self._api_id = QLineEdit()
        self._api_id.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_id.setPlaceholderText(
            f"Currently: "
            f"{secrets.mask(secrets.get_secret(secrets.KEY_KALSHI_API_ID))}"
        )
        eye = QToolButton()
        eye.setIcon(qta.icon("fa6s.eye", color=theme.MUTED))
        eye.setCheckable(True)

        def _toggle(show: bool) -> None:
            self._api_id.setEchoMode(
                QLineEdit.EchoMode.Normal if show
                else QLineEdit.EchoMode.Password
            )
            eye.setIcon(qta.icon("fa6s.eye-slash" if show else "fa6s.eye",
                                 color=theme.MUTED))

        eye.toggled.connect(_toggle)
        key_row.addWidget(self._api_id)
        key_row.addWidget(eye)
        api_lab = add_field("Kalshi API Key ID", key_container)

        self._pem_paste = QPlainTextEdit()
        self._pem_paste.setPlaceholderText(
            "-----BEGIN RSA PRIVATE KEY-----\n… (paste your Kalshi RSA "
            "private key here; stored in Windows Credential Manager)\n"
            "-----END RSA PRIVATE KEY-----"
            + ("\n\nCurrently saved: yes"
               if secrets.get_secret(secrets.KEY_KALSHI_PEM) else "")
        )
        self._pem_paste.setFixedHeight(96)
        pem_lab = add_field("RSA Private Key (paste PEM)", self._pem_paste)

        self._pem_path = QLineEdit()
        self._pem_path.setText(str(g("pem_path", "")))
        self._pem_path.setPlaceholderText(
            r"C:\path\to\kalshi-key.pem  (alternative to pasting)"
        )
        path_lab = add_field("…or RSA Private Key File Path", self._pem_path)

        cred_note = QLabel(
            "Get both from kalshi.com → Account Settings → API Keys. "
            "Leave blank to keep the current value."
        )
        cred_note.setProperty("muted", True)
        cred_note.setWordWrap(True)
        form.addWidget(cred_note)

        self._live_only = [
            mode_warn, env_lab, self._env, api_lab, key_container,
            pem_lab, self._pem_paste, path_lab, self._pem_path, cred_note,
        ]

        # --- Strategy numbers ---------------------------------------------
        self._risk = _spin(float(g("risk_usd", DEFAULTS["risk_usd"])), "USD")
        add_field("Risk Per Trade (USD)", self._risk)

        self._min_stretch = _spin(
            float(g("min_stretch_pct", DEFAULTS["min_stretch_pct"])), "%", 10.0)
        add_field("Entry Stretch Band (%)", self._min_stretch)

        self._max_stretch = _spin(
            float(g("max_stretch_pct", DEFAULTS["max_stretch_pct"])), "%", 10.0)
        add_field("Max Stretch — Death Trap Limit (%)", self._max_stretch)

        self._profit = _spin(
            float(g("profit_target_pct", DEFAULTS["profit_target_pct"])),
            "%", 1000.0)
        add_field("Take Profit (%)", self._profit)

        self._volume_mult = _spin(
            float(g("volume_spike_mult", DEFAULTS["volume_spike_mult"])),
            "× baseline", 10.0)
        add_field("Volume Spike Filter — block entry above (×)",
                  self._volume_mult)

        self._premium = _spin(
            float(g("premium_threshold_pct", DEFAULTS["premium_threshold_pct"])),
            "%", 5.0)
        add_field("Coinbase Premium Filter — block entry above (±%)",
                  self._premium)

        self._econ_day = QCheckBox(
            "Economic Data Day — block entries TODAY (Fed meeting, CPI, etc.)")
        self._econ_day.setChecked(
            g("econ_block_date")
            == dt.datetime.now(dt.timezone.utc).date().isoformat())
        self._econ_day.setContentsMargins(2, 0, 2, 0)
        form.addSpacing(8)
        form.addWidget(self._econ_day)
        form.addSpacing(4)

        self._paper_start = _spin(
            float(g("paper_start_usd", DEFAULTS["paper_start_usd"])), "USD")
        self._paper_start_lab = add_field(
            "Paper Starting Balance (USD)", self._paper_start)

        def _toggle_mode_fields(index: int) -> None:
            paper = index == 0
            self._paper_start.setVisible(paper)
            self._paper_start_lab.setVisible(paper)
            for w in self._live_only:
                w.setVisible(not paper)

        self._mode.currentIndexChanged.connect(_toggle_mode_fields)
        self._toggle_mode_fields = _toggle_mode_fields

        # --- Sticky header (balance + Save/Reset/Recommended) -------------
        self.header = SettingsHeader(
            currency="USD",
            on_save=self._save,
            on_reset=self._reset,
            on_recommend=self._apply_recommended,
            on_refresh=self._fetch_balance,
        )
        self._last_balance: float | None = None
        self._balance_fetched_ts = 0.0
        self._mode.currentIndexChanged.connect(lambda _i: self._fetch_balance())

        note = QLabel(
            "API Key ID is stored in Windows Credential Manager. Large RSA "
            "keys that exceed its size limit are saved to "
            "data\\kalshi_key.pem instead.\nLeave a secret field blank to keep "
            "its current value."
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

        self._toggle_mode_fields(self._mode.currentIndex())

    # ------------------------------------------------------------------ save

    def _save(self) -> None:
        if self._api_id.text().strip():
            try:
                secrets.set_secret(secrets.KEY_KALSHI_API_ID,
                                   self._api_id.text().strip())
            except Exception as e:
                self._set_status(f"✗ Could not save API Key ID: {e}", theme.RED)
                return
            self._api_id.clear()

        self._db.set_setting("pem_path", self._pem_path.text().strip())
        pem = self._pem_paste.toPlainText().strip()
        if pem:
            try:
                secrets.set_secret(secrets.KEY_KALSHI_PEM, pem)
            except Exception:
                # RSA PEM often exceeds the ~2.5KB Credential Manager blob
                # limit (WinError 1783). Fallback: write to a protected file
                # in the data dir and use the path.
                from src.core.paths import DATA_DIR
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                key_file = DATA_DIR / "kalshi_key.pem"
                key_file.write_text(pem, encoding="utf-8")
                secrets.set_secret(secrets.KEY_KALSHI_PEM, "")
                self._db.set_setting("pem_path", str(key_file))
                self._pem_path.setText(str(key_file))
            self._pem_paste.clear()

        self._db.set_setting(
            "trading_mode", "live" if self._mode.currentIndex() == 1 else "paper")
        self._db.set_setting("env", self._envs[self._env.currentIndex()][1])
        self._db.set_setting(
            "market_timeframe",
            self._timeframes[self._timeframe.currentIndex()][1])
        self._db.set_setting("risk_usd", self._risk.value())
        self._db.set_setting("min_stretch_pct", self._min_stretch.value())
        self._db.set_setting("max_stretch_pct", self._max_stretch.value())
        self._db.set_setting("profit_target_pct", self._profit.value())
        self._db.set_setting("volume_spike_mult", self._volume_mult.value())
        self._db.set_setting("premium_threshold_pct", self._premium.value())
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        self._db.set_setting(
            "econ_block_date", today if self._econ_day.isChecked() else "")
        self._db.set_setting("paper_start_usd", self._paper_start.value())

        self._set_status("Settings saved ✓", theme.GREEN)
        self.modeSaved.emit(
            "LIVE" if self._mode.currentIndex() == 1 else "PAPER")
        if self._mode.currentIndex() == 1:
            self._validate_credentials()

    # -------------------------------------------------- credential check

    def _set_status(self, text: str, color: str) -> None:
        self.header.set_status(text, color)

    # ------------------------------------------------ balance + recommend

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        if time.monotonic() - self._balance_fetched_ts > 60:
            self._fetch_balance()

    def _fetch_balance(self) -> None:
        self._balance_fetched_ts = time.monotonic()

        if self._mode.currentIndex() == 0:
            start = float(self._db.get_setting(
                "paper_start_usd", DEFAULTS["paper_start_usd"]))
            bal = start + self._db.total_pnl()
            self._last_balance = bal
            self.header.set_balance(bal, "Paper balance (simulated)")
            return

        key_id = secrets.get_secret(secrets.KEY_KALSHI_API_ID)
        pem = secrets.get_secret(secrets.KEY_KALSHI_PEM)
        if not pem:
            pem = str(self._db.get_setting("pem_path", "")).strip() or None
        if not key_id or not pem:
            self.header.set_balance(
                None, "Add API Key ID + RSA key below, then Save")
            return
        env = self._envs[self._env.currentIndex()][1]
        self.header.set_balance(None, f"Fetching live balance… [{env}]")

        async def _run() -> None:
            from src.execution.kalshi_client import KalshiClient
            client = None
            try:
                client = KalshiClient(env=env, key_id=key_id,
                                      private_key_pem=pem)
                bal = await client.get_balance()
                self._last_balance = bal
                self.header.set_balance(bal, f"Real USD on Kalshi [{env}]")
            except Exception as e:
                self.header.set_balance(None, f"Balance fetch failed: {e}")
            finally:
                if client is not None:
                    await client.aclose()

        run_async(_run())

    def _apply_recommended(self) -> None:
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
            f"Recommended values applied — Risk ${rec:,.2f} (10% of your "
            f"{self._last_balance:,.2f} USD balance), stretch 1.5/2.5%, "
            "TP 100%. Click Save Settings to apply.",
            theme.AMBER,
        )

    def _validate_credentials(self) -> None:
        """Read-only check: GET /portfolio/balance gamit ang saved creds."""
        key_id = secrets.get_secret(secrets.KEY_KALSHI_API_ID)
        pem = secrets.get_secret(secrets.KEY_KALSHI_PEM)
        if not pem:
            pem = self._pem_path.text().strip() or None
        if not key_id or not pem:
            self._set_status(
                "Settings saved ✓ — add your API Key ID and RSA private key "
                "to enable Live mode.",
                theme.AMBER,
            )
            return
        env = self._envs[self._env.currentIndex()][1]

        async def _run() -> None:
            from src.execution.kalshi_client import KalshiClient
            client = None
            try:
                client = KalshiClient(env=env, key_id=key_id,
                                      private_key_pem=pem)
                balance = await client.get_balance()
                self._set_status(
                    f"✓ Settings saved — Kalshi credentials OK! "
                    f"Balance: {balance:,.2f} USD [{env}]",
                    theme.GREEN,
                )
                self._last_balance = balance
                self.header.set_balance(balance, f"Real USD on Kalshi [{env}]")
                self.liveBalanceChecked.emit(balance)
            except Exception as e:
                self._set_status(
                    f"✗ Settings saved, but the credential check failed: {e}",
                    theme.RED,
                )
            finally:
                if client is not None:
                    await client.aclose()

        self._set_status(
            "Settings saved ✓ — verifying Kalshi credentials…", theme.AMBER)
        run_async(_run())

    def _reset(self) -> None:
        self._risk.setValue(DEFAULTS["risk_usd"])
        self._min_stretch.setValue(DEFAULTS["min_stretch_pct"])
        self._max_stretch.setValue(DEFAULTS["max_stretch_pct"])
        self._profit.setValue(DEFAULTS["profit_target_pct"])
        self._volume_mult.setValue(DEFAULTS["volume_spike_mult"])
        self._premium.setValue(DEFAULTS["premium_threshold_pct"])
        self._econ_day.setChecked(False)
        self._paper_start.setValue(DEFAULTS["paper_start_usd"])
        self._set_status("Defaults restored — click Save Settings to apply",
                         theme.MUTED)
