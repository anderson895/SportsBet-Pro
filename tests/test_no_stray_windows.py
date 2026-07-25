"""Walang kumikislap na maliliit na window kapag nagre-render.

Ang bug: `w.setParent(None)` ay ginagamit para agad maalis ang lumang laman
bago ang `deleteLater()`. Pero sa Qt, ang pag-set ng parent sa None ay
ginagawang TOP-LEVEL WINDOW ang widget — kaya kumikislap sila bilang
maliliit na kahon sa screen tuwing bubuksan ang app o magsa-search.

Ang tamang paraan ay `hide()`: agad ding nagtatago, pero nananatiling
naka-parent kaya hindi nagiging window.

Kasama rin dito ang kabaligtarang panig: kailangang MAWALA AGAD ang lumang
laman, kung hindi ay nananatiling nakikita ito sa ibabaw ng bago.
"""
import unittest

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from src.storage.db import Database
from src.ui import help_content
from src.ui.about_page import AboutPage
from src.ui.kalshi_dashboard import KalshiDashboard
from src.ui.widgets import StatCard

_app = QApplication.instance() or QApplication([])

# Ang mga QMenu / pyqtgraph ViewBoxMenu ay lehitimong top-level popups
_OK_TOP_LEVEL = ("QMenu", "ViewBoxMenu", "QWidget")


def _visible_strays(root: QWidget) -> list[QWidget]:
    return [
        w for w in _app.topLevelWidgets()
        if w is not root
        and type(w).__name__ not in _OK_TOP_LEVEL
        and not w.isHidden()
    ]


def _markets(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        ev = f"KXMLBGAME-26JUL24G{i:02d}"
        for team, pct in ((f"Team A{i}", 60), (f"Team B{i}", 40)):
            rows.append({
                "ticker": f"{ev}-{team[-2:]}",
                "title": f"Team A{i} vs Team B{i} Winner? ({team})",
                "yes_bid": pct, "yes_ask": pct, "no_bid": 100 - pct,
                "no_ask": 100 - pct, "volume": 1_000_000, "status": "WATCH",
            })
    return rows


class AboutPageRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.page = AboutPage("Help", "", default_tag=help_content.KALSHI)
        self.page.resize(1000, 600)
        self.addCleanup(self.page.deleteLater)

    def test_searching_leaves_no_visible_stray_window(self) -> None:
        for query in ("hedge", "fees", "wallet type", "zzz", ""):
            self.page._on_search(query)
            _app.processEvents()
            self.assertEqual(
                _visible_strays(self.page), [],
                f"lumitaw ang stray window pagkatapos ng search {query!r}",
            )

    def test_old_cards_are_gone_from_the_layout(self) -> None:
        self.page._on_search("")
        first = self.page._body_col.count()
        self.page._on_search("hedge")
        self.assertLess(self.page._body_col.count(), first)
        self.assertEqual(self.page._body_col.count(),
                         len(self.page._visible_sections()))


class MarketGridRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dash = KalshiDashboard(Database().scope("kalshi"))
        self.dash.resize(1000, 600)
        self.addCleanup(self.dash.deleteLater)

    def test_market_search_leaves_no_visible_stray_window(self) -> None:
        self.dash.update_markets(_markets(6))
        _app.processEvents()
        for query in ("Team A1", "zzz", ""):
            self.dash._search.setText(query)
            _app.processEvents()
            self.assertEqual(
                _visible_strays(self.dash), [],
                f"lumitaw ang stray window pagkatapos ng search {query!r}",
            )

    def test_empty_hint_disappears_once_cards_arrive(self) -> None:
        """Ang kabaligtarang bug: dapat AGAD mawala ang hint, kung hindi ay
        nag-o-overlap ito sa unang card."""
        self.dash.update_markets(_markets(4))
        _app.processEvents()
        visible_hints = [
            w.text() for w in self.dash.findChildren(QLabel)
            if "START BOT to scan" in w.text() and w.isVisible()
        ]
        self.assertEqual(visible_hints, [])


class StatCardSubLabelTest(unittest.TestCase):
    """Ang label na hindi naidagdag sa layout ay top-level window — at
    ipapakita iyon ng set_sub() bilang kumikislap na kahon."""

    def test_sub_label_is_parented_even_when_empty(self) -> None:
        card = StatCard("Bot Status", "STOPPED")     # walang sub
        self.addCleanup(card.deleteLater)
        self.assertIsNotNone(card._sub.parent())
        self.assertFalse(card._sub.isVisible())

    def test_set_sub_shows_it_inside_the_card(self) -> None:
        card = StatCard("Bot Status", "STOPPED")
        self.addCleanup(card.deleteLater)
        card.set_sub("Real USD on Kalshi")
        self.assertIsNotNone(card._sub.parent(),
                             "hindi dapat top-level window")
        self.assertEqual(card._sub.text(), "Real USD on Kalshi")

    def test_clearing_sub_hides_it_again(self) -> None:
        card = StatCard("Balance", "—", "Simulated")
        self.addCleanup(card.deleteLater)
        card.set_sub("")
        self.assertFalse(card._sub.isVisible())


if __name__ == "__main__":
    unittest.main()
