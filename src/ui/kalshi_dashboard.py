"""Kalshi dashboard — Kalshi.com-inspired layout:

- status cards (Internet / Kalshi / Bot / Balance)
- "Featured Market" card: malalaking live outcome percentages + payout
  odds kada team, carousel, at estado ng straddle
- grid ng mga na-scan na sports market (ito ang kumukuha ng espasyo)
- recent logs
"""
from __future__ import annotations

import datetime as dt

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from src.ui.pages import local_time
from src.ui.widgets import Card, Pill, StatCard, StatusCard

GRID_COLS = 2  # ilang game card kada row

DEFAULT_PAPER_START = 1000.0

# Visual hierarchy: routine INFO ay muted (iwas wall-of-color);
# TRADE/WARN/ERROR lang ang pumupansin
LEVEL_COLORS = {
    "INFO": theme.MUTED,
    "TRADE": theme.ACCENT,
    "WARN": theme.AMBER,
    "ERROR": theme.RED,
}


class KalshiDashboard(QWidget):
    # Hiling na i-focus ng chart ang isang partikular na market (ticker, title)
    focusRequested = Signal(str, str)

    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self._live_mode = False
        self._chart_ticker: str | None = None
        self._all_games: list[dict] = []  # lahat ng scanned games (pre-search)
        self._games: list[dict] = []      # filtered (by search) na ipinapakita
        self._featured_idx = 0            # aling game ang naka-feature sa chart
        self._user_selected = False       # pinili ba ng user (huwag i-override)

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

        # Carousel: ‹  N of M  › — cycle sa mga featured market (kalshi-style)
        self._prev_btn = QPushButton()
        self._prev_btn.setIcon(qta.icon("fa6s.chevron-left", color=theme.TEXT))
        self._next_btn = QPushButton()
        self._next_btn.setIcon(qta.icon("fa6s.chevron-right", color=theme.TEXT))
        for b in (self._prev_btn, self._next_btn):
            b.setFixedSize(30, 28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._counter_lbl = QLabel("—")
        self._counter_lbl.setStyleSheet(
            f"color: {theme.MUTED}; font-size: 12px; font-weight: 700")
        self._counter_lbl.setMinimumWidth(56)
        self._counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prev_btn.clicked.connect(lambda: self._step_featured(-1))
        self._next_btn.clicked.connect(lambda: self._step_featured(1))

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(self._live_pill)
        head.addWidget(self._market_title, stretch=1)
        head.addWidget(self._prev_btn)
        head.addWidget(self._counter_lbl)
        head.addWidget(self._next_btn)
        head.addSpacing(6)
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

        self._strategy_label = QLabel("Strategy: idle (press START BOT)")
        self._strategy_label.setProperty("muted", True)
        self._strategy_label.setWordWrap(True)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"color: {theme.BORDER_SOFT};")

        # Walang chart: walang historical candles ang Kalshi para sa mga
        # market na ito, kaya live ticks lang ang maipapakita — halos
        # blangko ito at nauubos lang ang espasyo. Ang live na porsyento +
        # odds sa itaas ay parehong impormasyon, at napupunta na sa Live
        # Sports Markets ang natirang taas.
        featured = Card()
        fc = QVBoxLayout(featured)
        fc.setContentsMargins(18, 14, 18, 14)
        fc.setSpacing(10)
        fc.addLayout(head)
        fc.addLayout(outcomes)
        fc.addWidget(divider)
        fc.addWidget(self._strategy_label)

        # ---- Scanned markets — Kalshi-style game cards grid + search ----
        table_title = QLabel("Live Sports Markets")
        table_title.setProperty("accent", True)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search team or matchup…")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(260)
        self._search.textChanged.connect(self._apply_search)
        self._count_lbl = QLabel("")
        self._count_lbl.setProperty("muted", True)
        markets_head = QHBoxLayout()
        # +14px sa kanan: ang panel right margin ay 2px lang (binawasan para
        # ma-account ang 10px scrollbar sa GRID) — pero ang header row ay
        # nasa labas ng scroll area, kaya kailangan nitong bawiin ang
        # natitira para tumugma sa 16px na gilid ng mga card.
        markets_head.setContentsMargins(0, 0, 14, 0)
        markets_head.addWidget(table_title)
        markets_head.addWidget(self._count_lbl)
        markets_head.addStretch()
        markets_head.addWidget(self._search)

        self._grid_host = QWidget()
        # Transparent — kung hindi, mamamana nito ang ITIM na page background
        # (QWidget { background: BG }) at lalabas na itim ang mga puwang sa
        # pagitan ng cards sa loob ng mas mapusyaw na panel
        self._grid_host.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_host)
        # Ang mga margin dito ay tumatakbo KASAMA ang panel margins sa ibaba —
        # tingnan ang tala roon para sa kabuuang 16px sa bawat gilid.
        self._grid.setContentsMargins(0, 6, 4, 6)
        self._grid.setSpacing(14)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_hint = QLabel("Press START BOT to scan live sports "
                                  "markets…")
        self._empty_hint.setProperty("muted", True)
        self._grid.addWidget(self._empty_hint, 0, 0)

        mkt_scroll = QScrollArea()
        mkt_scroll.setWidgetResizable(True)
        mkt_scroll.setWidget(self._grid_host)
        mkt_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # LAGING nakalaan ang espasyo ng scrollbar — kung hindi, lumilipat
        # ang mga card ng 10px tuwing lalabas/mawawala ito, at nasisira ang
        # pagkakapantay ng kaliwa/kanan. Transparent ang track kaya hindi
        # ito nakikita kapag walang ma-scroll.
        mkt_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )

        # PANTAY na 16px sa paligid ng card grid. Ang bawat gilid ay
        # pinagsamang panel + grid margin — at ang 10px na scrollbar ay
        # BINIBILANG sa kanan dahil nasa labas ito ng viewport:
        #   kaliwa : 16 (panel) + 0 (grid)             = 16
        #   kanan  :  4 (grid) + 10 (scrollbar) + 2    = 16
        #   itaas  : 10 (spacing) + 6 (grid)           = 16  mula sa header
        #   ibaba  : 16 (panel)                        = 16
        markets_panel = Card()
        markets_panel.setMinimumHeight(280)
        markets_col = QVBoxLayout(markets_panel)
        markets_col.setContentsMargins(16, 14, 2, 16)
        markets_col.setSpacing(10)
        markets_col.addLayout(markets_head)
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
        self._log_list.setSpacing(3)  # hangin sa pagitan (readability)

        logs_panel = Card()
        logs_panel.setFixedWidth(RIGHT_COL_WIDTH)
        logs_col = QVBoxLayout(logs_panel)
        logs_col.setContentsMargins(16, 12, 16, 12)
        logs_col.addLayout(logs_head)
        logs_col.addWidget(self._log_list, stretch=1)

        # ---- Layout ------------------------------------------------------
        # Ang featured card ay kasing-taas lang ng laman nito (walang chart);
        # LAHAT ng natitirang taas ay napupunta sa game cards
        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        left_col.addWidget(featured)
        left_col.addWidget(markets_panel, stretch=1)

        body_row = QHBoxLayout()
        body_row.setSpacing(12)
        body_row.addLayout(left_col, stretch=1)
        body_row.addWidget(logs_panel)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 6)
        root.setSpacing(12)
        root.addLayout(cards_row)
        root.addLayout(body_row, stretch=1)

        self._load_recent_logs()
        self.refresh_balance()

    # ------------------------------------------------------------------ slots

    def update_market_tick(self, ticker: str, title: str,
                           yes_pct: float, no_pct: float) -> None:
        # I-plot LANG kung ito ang naka-feature na market (iwas mag-halo kapag
        # nag-navigate/nag-click ang user ng ibang market)
        featured = self._featured_ticker()
        if featured is not None and ticker != featured:
            return
        if ticker != self._chart_ticker:
            self._chart_ticker = ticker
            self._market_title.setText(title or ticker)
        # Team names + payout odds (kalshi-style) kung kilala ang game;
        # else fallback sa generic YES/NO
        game = next((g for g in self._games if g["ticker"] == ticker), None)
        teams = game.get("teams", []) if game else []
        if len(teams) >= 2:
            # Ang market na ito ay BINARY: "panalo ba si X?" Sa 2-way na
            # laro, ang NO = ang kalaban. Pero sa 3-way (soccer, may
            # TABLA), ang NO = "lahat maliban kay X" — mali kung
            # papangalanan ito ng isang kalaban lang.
            yes_name = teams[0][0]
            no_name = teams[1][0] if len(teams) == 2 else f"Not {yes_name}"
            self._yes_lbl.setText(f"{yes_name}  {yes_pct:.0f}%  ·  "
                                  f"{self._payout(yes_pct)}")
            self._no_lbl.setText(f"{no_name}  {no_pct:.0f}%  ·  "
                                 f"{self._payout(no_pct)}")
        else:
            self._yes_lbl.setText(f"YES {yes_pct:.0f}%")
            self._no_lbl.setText(f"NO {no_pct:.0f}%")

    @staticmethod
    def _payout(pct: float) -> str:
        """Payout multiplier kung mananalo (kalshi 'Pays out' column)."""
        if pct <= 0:
            return "—"
        return f"{100.0 / pct:.2f}x"

    def update_markets(self, rows: list) -> None:
        games = group_games(rows)
        # READY muna, tapos by volume — para nasa taas ang tradeable
        games.sort(key=lambda g: (not g["ready"], -g["vol"]))
        self._all_games = [g for g in games if len(g["teams"]) >= 2]
        self._has_scanned = bool(rows)
        self._apply_search()

    DISPLAY_CAP = 60  # ilang card ang irerender (search ay sa LAHAT pa rin)

    def _apply_search(self) -> None:
        """I-filter ang games ayon sa search text, tapos i-render.
        Sinasala sa LAHAT ng scanned games, pero cap ang irerender para
        hindi bumagal."""
        q = self._search.text().strip().lower()
        if q:
            matches = [
                g for g in self._all_games
                if q in g["matchup"].lower()
                or any(q in t[0].lower() for t in g.get("teams", []))
            ]
        else:
            matches = list(self._all_games)
        self._match_count = len(matches)
        self._games = matches[:self.DISPLAY_CAP]
        self._render_grid()

    def _render_grid(self) -> None:
        # Linisin ang grid. Ang takeAt() ay nag-aalis lang sa LAYOUT — hindi
        # nito binabago ang parent, at ang deleteLater() ay naghihintay pa ng
        # event loop. Kaya kailangan ng setParent(None): agad itong nagtatago,
        # kung hindi ay nananatiling nakikita ang lumang hint/cards sa ibabaw
        # ng bago.
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        games = self._games
        total = getattr(self, "_match_count", len(games))
        if not games:
            self._count_lbl.setText("")
        elif total > len(games):
            self._count_lbl.setText(f"({len(games)} of {total} — refine search)")
        else:
            self._count_lbl.setText(f"({total} shown)")

        if not games:
            self._counter_lbl.setText("—")
            if self._search.text().strip():
                msg = "No match for your search."
            elif getattr(self, "_has_scanned", False):
                msg = "Scanning… no candidate games yet."
            else:
                msg = "Press START BOT to scan live sports markets…"
            hint = QLabel(msg)
            hint.setProperty("muted", True)
            self._grid.addWidget(hint, 0, 0)
            return

        for i, game in enumerate(games):
            card = GameCard(game)
            card.clicked.connect(self._on_card_clicked)
            self._grid.addWidget(card, i // GRID_COLS, i % GRID_COLS)

        # Panatilihin ang piniling market ng user kung nandiyan pa; kung hindi
        # (o auto-mode), i-feature ang unang game (READY na 50/50)
        if self._user_selected:
            idx = next((i for i, g in enumerate(games)
                        if g["ticker"] == self._chart_ticker), None)
            if idx is None:
                self._user_selected = False
                self._featured_idx = 0
            else:
                self._featured_idx = idx
        else:
            self._featured_idx = 0
        self._counter_lbl.setText(f"{self._featured_idx + 1} of {len(games)}")

    # ---- featured market carousel / focus -----------------------------

    def _featured_ticker(self) -> str | None:
        if 0 <= self._featured_idx < len(self._games):
            return self._games[self._featured_idx]["ticker"]
        return None

    def _on_card_clicked(self, game: dict) -> None:
        idx = next((i for i, g in enumerate(self._games)
                    if g["ticker"] == game["ticker"]), None)
        if idx is not None:
            self._select_featured(idx)

    def _step_featured(self, delta: int) -> None:
        if not self._games:
            return
        self._select_featured((self._featured_idx + delta) % len(self._games))

    def _select_featured(self, idx: int) -> None:
        if not (0 <= idx < len(self._games)):
            return
        self._featured_idx = idx
        self._user_selected = True
        g = self._games[idx]
        self._counter_lbl.setText(f"{idx + 1} of {len(self._games)}")
        self._chart_ticker = g["ticker"]
        self._market_title.setText(g.get("title", g["matchup"]))
        # Ipa-poll sa engine ang piniling market para mag-update ang odds
        self.focusRequested.emit(g["ticker"], g.get("title", g["matchup"]))

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
        # local_time(): UTC ang naka-imbak, pero LOCAL ang mga live entry
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
