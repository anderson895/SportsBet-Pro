"""Hover state ng game cards — walang "View details" na text.

Dalawang bug ang binabantayan dito:

1. Ang QSS `:hover` sa QFrame ay HINDI maaasahan (mga button lang ang
   laging nakakakuha ng hover state), kaya dynamic property + repolish ang
   gamit. Kung babalik sa `:hover`, walang mangyayari sa hover.

2. Ang `widget.setStyleSheet("background: transparent")` ay KUMAKALAT sa
   lahat ng anak. Noong ganito ang grid host, nawala ang sariling
   background ng mga card at hindi tumalab ang hover — kaya kailangang
   naka-scope sa #objectName ang rule.
"""
import unittest

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel

from src.ui import theme
from src.ui.kalshi_cards import GameCard

_app = QApplication.instance() or QApplication([])

_GAME = {
    "matchup": "Los Angeles A vs San Francisco",
    "league": "PRO BASEBALL",
    "icon": "fa6s.baseball",
    "ticker": "KXMLBGAME-26JUL24LAASF-SF",
    "title": "Los Angeles A vs San Francisco Winner? (San Francisco)",
    "vol": 3825322,
    "ready": False,
    "teams": [("San Francisco", 72.0), ("Los Angeles A", 28.0)],
}


def _enter(card: GameCard) -> None:
    pt = QPoint(10, 10)
    card.enterEvent(QEnterEvent(pt, pt, pt))


def _leave(card: GameCard) -> None:
    card.leaveEvent(QEvent(QEvent.Type.Leave))


class GameCardHoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.card = GameCard(dict(_GAME))

    def test_no_view_details_text(self) -> None:
        texts = [w.text() for w in self.card.findChildren(QLabel)]
        self.assertNotIn("View details ›", texts)
        self.assertFalse(any("View details" in t for t in texts))

    def test_volume_still_shown(self) -> None:
        texts = [w.text() for w in self.card.findChildren(QLabel)]
        self.assertIn("$3,825,322 vol", texts)

    def test_hover_sets_property(self) -> None:
        self.assertFalse(bool(self.card.property("cardHover")))
        _enter(self.card)
        self.assertTrue(self.card.property("cardHover"))

    def test_leave_clears_property(self) -> None:
        _enter(self.card)
        _leave(self.card)
        self.assertFalse(self.card.property("cardHover"))

    def test_repeated_enter_is_idempotent(self) -> None:
        _enter(self.card)
        _enter(self.card)
        self.assertTrue(self.card.property("cardHover"))

    def test_theme_has_a_rule_for_the_hover_property(self) -> None:
        """Walang saysay ang property kung walang QSS na tumutugma dito."""
        self.assertIn('QFrame[cardHover="true"]', theme.STYLESHEET)
        self.assertIn(theme.CARD_HOVER, theme.STYLESHEET)

    def test_card_keeps_its_own_background(self) -> None:
        """Dapat may sariling `card` property pa rin — kung mananalo ang
        naipasang transparent na background, nawawala ang hover."""
        self.assertTrue(self.card.property("card"))

    def test_click_still_emits_the_game(self) -> None:
        got = []
        self.card.clicked.connect(got.append)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.card.mousePressEvent(press)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["ticker"], _GAME["ticker"])


if __name__ == "__main__":
    unittest.main()
