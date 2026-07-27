"""Kalshi.com-style game cards — bawat card ay isang matchup na may
dalawang team, kanya-kanyang win % (green-outlined pill), volume, at
READY badge kung candidate ito para sa straddle.

Ang scanner ay nagbibigay ng ISANG row kada market (kada team side);
pinagsasama-sama dito ang dalawang side ng iisang laban gamit ang event
ticker (ticker na walang huling segment)."""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from src.ui import theme
from src.ui.widgets import Card, Pill

_TEAM_DOTS = ("#f75d6b", "#4c8dff", "#b0b7c3")  # red / blue / grey (tabla)

# League -> (sport icon, display label). qtawesome (Font Awesome 6) —
# offline, walang network fetch na kailangan.
_SPORT = {
    "MLB": ("fa6s.baseball", "PRO BASEBALL"),
    "WNBA": ("fa6s.basketball", "WNBA"),
    "NBA": ("fa6s.basketball", "PRO BASKETBALL"),
    "NFL": ("fa6s.football", "PRO FOOTBALL"),
    "NCAAF": ("fa6s.football", "COLLEGE FOOTBALL"),
    "NHL": ("fa6s.hockey-puck", "NHL"),
}


def _sport(ticker: str) -> tuple[str, str]:
    t = ticker.upper()
    for key, val in _SPORT.items():
        if key in t:
            return val
    return ("fa6s.trophy", "SPORTS")


def _event_key(ticker: str) -> str:
    parts = ticker.split("-")
    return "-".join(parts[:-1]) if len(parts) > 1 else ticker


def group_games(rows: list[dict]) -> list[dict]:
    """Pagsama-samahin ang per-market rows sa per-GAME dicts.

    Bawat game: {matchup, league, vol, ready, teams: [(name, yes_pct), ...]}.
    """
    games: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        title = str(row.get("title", ""))
        matchup = title.split(" (")[0].replace(" Winner?", "")
        if "(" in title and ")" in title:
            team = title[title.rfind("(") + 1:title.rfind(")")]
        else:
            team = title
        ev = _event_key(str(row.get("ticker", "")))
        yes_mid = (row.get("yes_bid", 0) + row.get("yes_ask", 0)) / 2.0
        g = games.get(ev)
        if g is None:
            icon, league = _sport(str(row.get("ticker", "")))
            # `ticker` = representative market (unang team side) na pino-poll
            # ng chart; `title` = titulo nito para sa featured header
            g = {"matchup": matchup, "league": league, "icon": icon,
                 "ticker": str(row.get("ticker", "")), "title": title,
                 "vol": 0, "ready": False, "teams": []}
            games[ev] = g
            order.append(ev)
        g["teams"].append((team, yes_mid))
        g["vol"] = max(g["vol"], int(row.get("volume", 0)))
        if row.get("status") == "READY":
            g["ready"] = True
    return [games[k] for k in order]


class GameCard(Card):
    """Isang matchup card — kagaya ng kalshi.com game tiles. Clickable:
    kapag pinindot, iea-emit ang game dict para i-feature sa chart."""

    clicked = Signal(dict)

    def __init__(self, game: dict) -> None:
        super().__init__()
        self._game = game
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Pinapagana ang QSS :hover para sa QFrame (kailangan ng WA_Hover —
        # ang mga button lang ang awtomatikong nakakakuha ng hover events)
        self.setProperty("gameCard", True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(10)

        # Header: sport icon + league badge + READY pill
        icon_name = game.get("icon", "fa6s.trophy")
        badge_icon = QLabel()
        badge_icon.setPixmap(
            qta.icon(icon_name, color=theme.MUTED).pixmap(16, 16))
        league = QLabel(game["league"])
        league.setStyleSheet(
            f"color: {theme.FAINT}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.8px")
        head = QHBoxLayout()
        head.setSpacing(7)
        head.addWidget(badge_icon)
        head.addWidget(league)
        head.addStretch()
        if game.get("ready"):
            head.addWidget(Pill("✓ READY", "ok"))
        col.addLayout(head)

        # Matchup title
        title = QLabel(game["matchup"])
        title.setStyleSheet("font-size: 15px; font-weight: 800")
        title.setWordWrap(True)
        col.addWidget(title)

        # Team rows: sport-icon "logo" + name + green-outlined % pill.
        # IPAKITA ANG LAHAT ng outcome — ang soccer ay 3-way (panalo /
        # TABLA / panalo). Kung 2 lang ang ipapakita, mukhang mali ang
        # porsyento dahil hindi umaabot sa 100%.
        for i, (team, pct) in enumerate(game["teams"]):
            logo = QLabel()
            logo.setPixmap(
                qta.icon(icon_name,
                         color=_TEAM_DOTS[min(i, len(_TEAM_DOTS) - 1)]
                         ).pixmap(20, 20))
            name = QLabel(team)
            name.setStyleSheet("font-size: 14px; font-weight: 600")
            pill = Pill(f"{pct:.0f}%", "outline")
            pill.setMinimumWidth(56)
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(logo)
            row.addWidget(name, stretch=1)
            row.addWidget(pill)
            col.addLayout(row)

        # Footer: volume lang — ang pagka-clickable ay ipinapahiwatig ng
        # hover state (tingnan ang QFrame[gameCard] sa theme.py) at ng
        # pointing-hand cursor, hindi ng dagdag na text
        vol = QLabel(f"${game['vol']:,} vol")
        vol.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px")
        col.addWidget(vol)

    def _set_hovered(self, on: bool) -> None:
        """Itakda ang `hovered` property at i-repolish para tumalab ang QSS.

        Kailangan ng manu-manong pag-toggle: ang QSS `:hover` sa QFrame ay
        hindi maaasahan (mga button lang ang laging nakakakuha ng hover
        state), kaya dynamic property ang gamit.
        """
        if self.property("cardHover") == on:
            return
        self.setProperty("cardHover", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._set_hovered(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit(self._game)
        super().mousePressEvent(event)
