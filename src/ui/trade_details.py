"""Detail modal ng isang trade — buong straddle sa iisang market.

Ang Trades table ay flat na listahan ng cryptic na ticker
(KXMLBGAME-26JUL241840CHCPIT-CHC). Mahirap makita roon kung ano ang
nangyari: alin ang magkasamang legs, ilan ang nabili kada panig, at
magkano ang totoong kinita. Dito pinagsasama-sama iyon.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.pages import STATUS_COLORS, STATUS_LABELS, local_time

# Series ticker -> pangalan na naiintindihan ng tao
SERIES_NAMES = {
    "KXMLBGAME": "Baseball — MLB",
    "KXNBAGAME": "Basketball — NBA",
    "KXWNBAGAME": "Basketball — WNBA",
    "KXNCAABGAME": "Basketball — College",
    "KXNFLGAME": "Football — NFL",
    "KXNCAAFGAME": "Football — College",
    "KXNHLGAME": "Hockey — NHL",
    "KXEPLGAME": "Soccer — EPL",
    "KXUCLGAME": "Soccer — Champions League",
    "KXLALIGAGAME": "Soccer — La Liga",
    "KXSERIEAGAME": "Soccer — Serie A",
    "KXLIGUE1GAME": "Soccer — Ligue 1",
    "KXMLSGAME": "Soccer — MLS",
    "KXLIGAMXGAME": "Soccer — Liga MX",
}

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def parse_ticker(ticker: str) -> dict:
    """Kalshi game ticker -> mga bahaging mababasa ng tao.

    Halimbawa: "KXMLBGAME-26JUL241840CHCPIT-CHC"
        series="KXMLBGAME"  sport="Baseball — MLB"
        starts="Jul 24, 2026 18:40 UTC"
        matchup="CHC vs PIT"  side_team="CHC"

    Laging nagbabalik ng dict — kung hindi kilala ang hugis, ang hilaw na
    ticker ang ipapakita sa halip na mag-crash.
    """
    out = {"ticker": ticker, "series": "", "sport": "", "starts": "",
           "matchup": "", "side_team": "", "opponent": ""}
    parts = (ticker or "").split("-")
    if len(parts) < 2:
        return out

    out["series"] = parts[0]
    out["sport"] = SERIES_NAMES.get(parts[0], parts[0])
    if len(parts) >= 3:
        out["side_team"] = parts[2]

    middle = parts[1]
    # "26JUL241840CHCPIT" -> YY MON DD HHMM TEAMS
    if len(middle) >= 11 and middle[2:5].upper() in _MONTHS:
        try:
            year = 2000 + int(middle[0:2])
            month = _MONTHS[middle[2:5].upper()]
            day = int(middle[5:7])
            hour, minute = int(middle[7:9]), int(middle[9:11])
            out["starts"] = dt.datetime(
                year, month, day, hour, minute, tzinfo=dt.timezone.utc
            ).strftime("%b %d, %Y %H:%M UTC")
        except ValueError:
            pass
        teams = middle[11:]
        side = out["side_team"]
        # Magkadikit ang dalawang team code; ang YES side ang susi para
        # malaman kung saan sila naghihiwalay
        if side and teams.startswith(side):
            out["opponent"] = teams[len(side):]
            out["matchup"] = f"{side} vs {out['opponent']}"
        elif side and teams.endswith(side):
            out["opponent"] = teams[: -len(side)]
            out["matchup"] = f"{out['opponent']} vs {side}"
        elif teams:
            out["matchup"] = teams
    return out


def summarise(rows: list) -> dict:
    """Buuin ang isang market mula sa mga trade row nito.

    Ibinabalik: yes/no (bilang ng contracts, BILOG na), cost, pnl
    (None kung wala pang naitalang resulta).

    Ang bilang ng contracts ay hinahango sa size ÷ price dahil ang
    itinatago natin ay halaga sa dollars. Ang mga size ay naka-round sa
    sentimo, kaya 6.63/0.49 + 0.23/0.49 + … = 27.99999… — kailangang
    ibilog BAGO ihambing, kung hindi ay magbabala ng "unbalanced" ang
    isang perpektong balanseng straddle.
    """
    yes = no = cost = 0.0
    pnl: Optional[float] = None
    for r in rows:
        if r["action"] == "BUY" and r["price"]:
            contracts = r["size"] / r["price"]
            cost += r["size"]
            if r["side"] == "YES":
                yes += contracts
            elif r["side"] == "NO":
                no += contracts
        if r["pnl"] is not None:
            pnl = (pnl or 0.0) + r["pnl"]
    return {"yes": round(yes), "no": round(no),
            "cost": round(cost, 2), "pnl": pnl}


class TradeDetailDialog(QDialog):
    """Lahat ng aktibidad sa ISANG market: legs, laki, at totoong PnL."""

    def __init__(self, db: ScopedDatabase, market: str, currency: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        info = parse_ticker(market)
        self.setWindowTitle(info["matchup"] or market)
        self.setMinimumWidth(680)
        self.setModal(True)

        rows = [r for r in db.recent_trades(limit=500)
                if r["market"] == market and r["status"] != "SUPERSEDED"]

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addWidget(self._header(info))
        root.addWidget(self._summary(rows, currency))
        root.addWidget(self._activity(rows, currency), stretch=1)

        close = QPushButton("Close")
        close.setObjectName("accentBtn")
        close.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close)
        root.addLayout(btn_row)

    # ------------------------------------------------------------- sections

    def _header(self, info: dict) -> QWidget:
        title = QLabel(info["matchup"] or info["ticker"])
        title.setStyleSheet("font-size: 19px; font-weight: 800")

        bits = [b for b in (info["sport"], info["starts"]) if b]
        sub = QLabel("  ·  ".join(bits))
        sub.setProperty("muted", True)

        ticker = QLabel(info["ticker"])
        ticker.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px")
        ticker.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        col.addWidget(title)
        if bits:
            col.addWidget(sub)
        col.addWidget(ticker)
        if info["side_team"]:
            note = QLabel(
                f"This market settles YES if {info['side_team']} wins. "
                "The bot buys BOTH sides, so the winner does not matter."
            )
            note.setProperty("muted", True)
            note.setWordWrap(True)
            col.addWidget(note)
        return box

    def _summary(self, rows: list, currency: str) -> QWidget:
        totals = summarise(rows)
        yes_n, no_n = totals["yes"], totals["no"]
        cost, pnl = totals["cost"], totals["pnl"]

        card = QFrame()
        card.setProperty("card", True)
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 13, 16, 13)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(7)

        pairs = int(min(yes_n, no_n))
        cells = [
            ("YES bought", f"{yes_n} contracts"),
            ("NO bought", f"{no_n} contracts"),
            ("Matched pairs", f"{pairs}"),
            ("Total cost", f"{cost:,.2f} {currency}"),
        ]
        for i, (label, value) in enumerate(cells):
            lab = QLabel(label.upper())
            lab.setStyleSheet(
                f"color: {theme.FAINT}; font-weight: 700; font-size: 10px;"
                " letter-spacing: 0.5px"
            )
            val = QLabel(value)
            val.setStyleSheet("font-weight: 700; font-size: 14px")
            grid.addWidget(lab, 0, i)
            grid.addWidget(val, 1, i)

        lab = QLabel("NET P&L")
        lab.setStyleSheet(
            f"color: {theme.FAINT}; font-weight: 700; font-size: 10px;"
            " letter-spacing: 0.5px"
        )
        if pnl is None:
            val = QLabel("— still open")
            val.setStyleSheet(f"color: {theme.MUTED}; font-weight: 700;"
                              " font-size: 14px")
        else:
            color = theme.GREEN if pnl >= 0 else theme.RED
            val = QLabel(f"{pnl:+,.4f} {currency}")
            val.setStyleSheet(f"color: {color}; font-weight: 800;"
                              " font-size: 16px")
        grid.addWidget(lab, 0, len(cells))
        grid.addWidget(val, 1, len(cells))

        if pairs and yes_n != no_n:
            warn = QLabel(
                f"⚠ Unbalanced: {yes_n} YES vs {no_n} NO — "
                "this leaves a real bet on the game."
            )
            warn.setStyleSheet(f"color: {theme.AMBER}")
            warn.setWordWrap(True)
            grid.addWidget(warn, 2, 0, 1, len(cells) + 1)
        return card

    def _activity(self, rows: list, currency: str) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(5)

        head = QLabel(f"Activity ({len(rows)})")
        head.setProperty("accent", True)
        col.addWidget(head)

        for r in rows:
            status = r["status"] or ""
            pnl = "" if r["pnl"] is None else f"{r['pnl']:+,.4f}"
            price = f"{r['price']:.2f}" if r["price"] else "—"
            line = QLabel(
                f"{local_time(r['ts'])}   {r['action']:<7} {r['side']:<5} "
                f"@ {price}   {r['size']:>7,.2f} {currency}   "
                f"{STATUS_LABELS.get(status, status)}   {pnl}"
            )
            line.setStyleSheet(
                "font-family: Consolas, monospace; font-size: 12px; color: "
                + (theme.GREEN if (r["pnl"] or 0) > 0
                   else STATUS_COLORS.get(status, theme.TEXT))
            )
            col.addWidget(line)
        col.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll
