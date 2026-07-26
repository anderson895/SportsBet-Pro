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

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from src.storage.db import Database
from src.ui import help_content
from src.ui.about_page import AboutPage
from src.ui.kalshi_settings import KalshiSettingsPage
from src.ui.poly_settings import PolySettingsPage
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


class AboutPageRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.page = AboutPage("Help", "", default_tag=help_content.KALSHI)
        self.page.resize(1000, 600)
        self.addCleanup(self.page.deleteLater)

    def test_searching_leaves_no_visible_stray_window(self) -> None:
        for query in ("stretch", "idle", "wallet type", "zzz", ""):
            self.page._on_search(query)
            _app.processEvents()
            self.assertEqual(
                _visible_strays(self.page), [],
                f"lumitaw ang stray window pagkatapos ng search {query!r}",
            )

    def test_old_cards_are_gone_from_the_layout(self) -> None:
        self.page._on_search("")
        first = self.page._body_col.count()
        self.page._on_search("stretch")
        self.assertLess(self.page._body_col.count(), first)
        self.assertEqual(self.page._body_col.count(),
                         len(self.page._visible_sections()))


class _WindowShowSpy(QObject):
    """Nagre-record ng bawat widget na IPINAPAKITA bilang top-level window.

    Kailangan ang event filter, hindi snapshot ng topLevelWidgets(): ang
    kislap ay panandalian — pagkatapos ma-reparent ang widget, hindi na ito
    top-level, kaya wala nang makikita ang snapshot pagkatapos ng
    construction.
    """

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[str] = []

    def eventFilter(self, obj, event):  # noqa: N802
        if (event.type() == QEvent.Type.Show
                and isinstance(obj, QWidget) and obj.isWindow()):
            label = type(obj).__name__
            if hasattr(obj, "text"):
                try:
                    label += f"({obj.text()[:32]!r})"
                except Exception:
                    pass
            self.shown.append(label)
        return False


class SettingsPageConstructionTest(unittest.TestCase):
    """Ang `form` ay standalone na QVBoxLayout habang binubuo ang page, at
    ang layout na walang parent widget ay hindi pa nagre-reparent ng mga
    widget nito. Ang setVisible(True) sa gitna ng construction ay
    nagpapakita ng mga field bilang top-level WINDOW — 16 na kumikislap na
    kahon tuwing bubuksan ang app.
    """

    def _build(self, factory) -> list[str]:
        spy = _WindowShowSpy()
        _app.installEventFilter(spy)
        try:
            page = factory()
            self.addCleanup(page.deleteLater)
            _app.processEvents()
        finally:
            _app.removeEventFilter(spy)
        return spy.shown

    def test_kalshi_settings_shows_no_window(self) -> None:
        shown = self._build(
            lambda: KalshiSettingsPage(Database().scope("kalshi")))
        self.assertEqual(shown, [], f"kumislap ang mga window: {shown}")

    def test_poly_settings_shows_no_window(self) -> None:
        shown = self._build(
            lambda: PolySettingsPage(Database().scope("polymarket")))
        self.assertEqual(shown, [], f"kumislap ang mga window: {shown}")

    def test_mode_fields_still_get_toggled(self) -> None:
        """Ang fix ay pag-antala ng tawag — kailangang gumana pa rin ito."""
        page = KalshiSettingsPage(Database().scope("kalshi"))
        self.addCleanup(page.deleteLater)
        page._mode.setCurrentIndex(0)          # Paper
        self.assertTrue(page._paper_start.isVisibleTo(page))
        page._mode.setCurrentIndex(1)          # Live
        self.assertFalse(page._paper_start.isVisibleTo(page))
        self.assertTrue(page._pem_path.isVisibleTo(page))


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
