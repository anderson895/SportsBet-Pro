"""Kalshi settings page — credentials + straddle strategy knobs.

Secrets (API Key ID + RSA private key PEM) -> Windows Credential Manager;
numbers -> SQLite (naka-scope sa "kalshi." prefix via ScopedDatabase).

Ang RSA private key ay pwedeng:
- i-PASTE ang buong PEM text (itinatago sa Credential Manager), O
- ituro ang path ng .pem file (kapag masyadong malaki ang 4096-bit PEM
  para sa ~2.5KB Credential Manager blob limit)
"""
from __future__ import annotations

import asyncio

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
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core import secrets
from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.widgets import Card

# Friendly na sport name -> Kalshi series ticker. Ito ang ipinapakita bilang
# checkboxes; hindi na kailangang alam ng user ang cryptic na ticker codes.
SPORT_OPTIONS = [
    ("Baseball — MLB", "KXMLBGAME"),
    ("Basketball — NBA", "KXNBAGAME"),
    ("Basketball — WNBA", "KXWNBAGAME"),
    ("Basketball — College", "KXNCAABGAME"),
    ("Football — NFL", "KXNFLGAME"),
    ("Football — College", "KXNCAAFGAME"),
    ("Hockey — NHL", "KXNHLGAME"),
    ("Soccer — EPL", "KXEPLGAME"),
    ("Soccer — Champions League", "KXUCLGAME"),
    ("Soccer — La Liga", "KXLALIGAGAME"),
    ("Soccer — Serie A", "KXSERIEAGAME"),
    ("Soccer — Ligue 1", "KXLIGUE1GAME"),
    ("Soccer — MLS", "KXMLSGAME"),
    ("Soccer — Liga MX", "KXLIGAMXGAME"),
]

DEFAULTS = {
    "risk_usd": 100.0,
    "entry_price_cents": 49,
    "hedge_timeout_secs": 90.0,
    "hedge_max_price": 51,
    "hedge_retries": 3,
    "min_volume": 5000,
    "min_close_mins": 45.0,
    "max_close_hours": 12.0,
    "paper_start_usd": 1000.0,
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
            maximum: int = 1_000_000) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
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
            1 if g("trading_mode", "paper") == "live" else 0
        )
        add_field("Trading Mode", self._mode)

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

        # --- Credentials --------------------------------------------------
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

        self._live_only = [env_lab, self._env, api_lab, key_container,
                           pem_lab, self._pem_paste, path_lab,
                           self._pem_path, cred_note]

        # --- Strategy numbers --------------------------------------------
        self._risk = _spin_f(float(g("risk_usd", DEFAULTS["risk_usd"])), "USD")
        add_field("Risk Per Straddle (USD)", self._risk)

        self._entry = _spin_i(
            int(float(g("entry_price_cents", DEFAULTS["entry_price_cents"]))),
            "¢ per side", 1, 99,
        )
        add_field("Entry Price (resting bid per side)", self._entry)

        self._hedge_max = _spin_i(
            int(float(g("hedge_max_price", DEFAULTS["hedge_max_price"]))),
            "¢ max", 1, 99,
        )
        add_field("Hedge Sentinel — max hedge price", self._hedge_max)

        self._hedge_timeout = _spin_f(
            float(g("hedge_timeout_secs", DEFAULTS["hedge_timeout_secs"])),
            "seconds", 3600.0, 5.0,
        )
        add_field("Hedge Sentinel — single-sided timeout", self._hedge_timeout)

        self._min_volume = _spin_i(
            int(float(g("min_volume", DEFAULTS["min_volume"]))),
            "contracts", 0,
        )
        add_field("Minimum Market Volume", self._min_volume)

        self._min_close = _spin_f(
            float(g("min_close_mins", DEFAULTS["min_close_mins"])),
            "minutes", 100_000.0, 1.0,
        )
        add_field("Skip markets closing sooner than", self._min_close)

        self._max_close = _spin_f(
            float(g("max_close_hours", DEFAULTS["max_close_hours"])),
            "hours", 10_000.0, 0.1,
        )
        add_field("Skip markets closing later than", self._max_close)

        # Sports to trade — friendly na checkboxes (walang cryptic tickers)
        saved_series = {t.strip() for t in
                        str(g("series_tickers", "")).split(",") if t.strip()}
        self._sport_cbs: list[QCheckBox] = []
        sports_grid = QGridLayout()
        sports_grid.setContentsMargins(0, 2, 0, 0)
        sports_grid.setHorizontalSpacing(20)
        sports_grid.setVerticalSpacing(6)
        for i, (label, ticker) in enumerate(SPORT_OPTIONS):
            cb = QCheckBox(label)
            cb.setChecked(ticker in saved_series)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            self._sport_cbs.append(cb)
            sports_grid.addWidget(cb, i // 2, i % 2)  # 2 columns
        sports_wrap = QWidget()
        sports_wrap.setLayout(sports_grid)
        sports_lab = add_field("Sports to Trade", sports_wrap)
        sports_hint = QLabel(
            "Pick the leagues to scan for 50/50 games. Leave all unchecked "
            "to auto-discover whatever is active."
        )
        sports_hint.setProperty("muted", True)
        sports_hint.setWordWrap(True)
        form.addWidget(sports_hint)

        self._paper_start = _spin_f(
            float(g("paper_start_usd", DEFAULTS["paper_start_usd"])), "USD"
        )
        self._paper_start_lab = add_field(
            "Paper Starting Balance (USD)", self._paper_start
        )

        def _toggle_mode_fields(index: int) -> None:
            paper = index == 0
            self._paper_start.setVisible(paper)
            self._paper_start_lab.setVisible(paper)
            for w in self._live_only:
                w.setVisible(not paper)

        self._mode.currentIndexChanged.connect(_toggle_mode_fields)
        _toggle_mode_fields(self._mode.currentIndex())

        # --- Buttons ------------------------------------------------------
        save_btn = QPushButton("  Save Settings")
        save_btn.setIcon(qta.icon("fa6s.floppy-disk", color="white"))
        save_btn.setObjectName("accentBtn")
        reset_btn = QPushButton("  Reset")
        reset_btn.setIcon(qta.icon("fa6s.rotate", color=theme.TEXT))
        save_btn.clicked.connect(self._save)
        reset_btn.clicked.connect(self._reset)

        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn, stretch=1)
        btn_row.addWidget(reset_btn)

        self._status = QLabel("")
        self._status.setProperty("muted", True)
        self._status.setWordWrap(True)

        note = QLabel(
            "API Key ID is stored in Windows Credential Manager. Large RSA "
            "keys that exceed its size limit are saved to "
            "data\\kalshi_key.pem instead.\nEntry at 49¢ + 49¢ with a $1.00 "
            "settlement leaves ~+1.1% per completed cycle after maker fees."
        )
        note.setProperty("muted", True)
        note.setWordWrap(True)

        panel = Card()
        panel_col = QVBoxLayout(panel)
        panel_col.setContentsMargins(18, 16, 18, 16)
        panel_col.setSpacing(10)
        panel_col.addWidget(title)
        panel_col.addLayout(form)
        panel_col.addSpacing(4)
        panel_col.addLayout(btn_row)
        panel_col.addWidget(self._status)
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
        root.addWidget(scroll)

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
                # Ang RSA PEM ay madalas lumampas sa ~2.5KB blob limit ng
                # Windows Credential Manager (WinError 1783). Fallback:
                # isulat sa protektadong file sa data dir at gamitin ang path.
                from src.core.paths import DATA_DIR
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                key_file = DATA_DIR / "kalshi_key.pem"
                key_file.write_text(pem, encoding="utf-8")
                secrets.set_secret(secrets.KEY_KALSHI_PEM, "")  # linisin
                self._db.set_setting("pem_path", str(key_file))
                self._pem_path.setText(str(key_file))
            self._pem_paste.clear()

        self._db.set_setting(
            "trading_mode", "live" if self._mode.currentIndex() == 1 else "paper"
        )
        self._db.set_setting("env", self._envs[self._env.currentIndex()][1])
        self._db.set_setting("risk_usd", self._risk.value())
        self._db.set_setting("entry_price_cents", self._entry.value())
        self._db.set_setting("hedge_max_price", self._hedge_max.value())
        self._db.set_setting("hedge_timeout_secs", self._hedge_timeout.value())
        self._db.set_setting("min_volume", self._min_volume.value())
        self._db.set_setting("min_close_mins", self._min_close.value())
        self._db.set_setting("max_close_hours", self._max_close.value())
        chosen = [ticker for (label, ticker), cb
                  in zip(SPORT_OPTIONS, self._sport_cbs) if cb.isChecked()]
        self._db.set_setting("series_tickers", ",".join(chosen))
        self._db.set_setting("paper_start_usd", self._paper_start.value())

        self._set_status("Settings saved ✓", theme.GREEN)
        self.modeSaved.emit(
            "LIVE" if self._mode.currentIndex() == 1 else "PAPER"
        )
        if self._mode.currentIndex() == 1:
            self._validate_credentials()

    # -------------------------------------------------- credential check

    def _set_status(self, text: str, color: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color}")

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
            "Settings saved ✓ — verifying Kalshi credentials…", theme.AMBER
        )
        try:
            asyncio.create_task(_run())
        except RuntimeError:
            pass  # walang running event loop (hal. sa UI tests)

    def _reset(self) -> None:
        self._risk.setValue(DEFAULTS["risk_usd"])
        self._entry.setValue(DEFAULTS["entry_price_cents"])
        self._hedge_max.setValue(DEFAULTS["hedge_max_price"])
        self._hedge_timeout.setValue(DEFAULTS["hedge_timeout_secs"])
        self._min_volume.setValue(DEFAULTS["min_volume"])
        self._min_close.setValue(DEFAULTS["min_close_mins"])
        self._max_close.setValue(DEFAULTS["max_close_hours"])
        self._paper_start.setValue(DEFAULTS["paper_start_usd"])
        self._status.setText("Defaults restored — click Save Settings to apply")
