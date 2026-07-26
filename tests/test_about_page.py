"""About page — search box + tag filter chips.

Ang panel ay nagpi-preselect ng sariling exchange (nasa Kalshi ka, Kalshi
ang unang makikita), pero puwedeng palitan ng user papuntang All.
"""
import unittest

from PySide6.QtWidgets import QApplication

from src.ui import help_content
from src.ui.about_page import ALL, AboutPage

_app = QApplication.instance() or QApplication([])


class AboutPageTest(unittest.TestCase):
    def _page(self, tag: str = ALL) -> AboutPage:
        page = AboutPage("Help", "", default_tag=tag)
        self.addCleanup(page.deleteLater)
        return page

    def test_shows_everything_by_default(self) -> None:
        page = self._page()
        self.assertEqual(len(page._visible_sections()),
                         len(help_content.SECTIONS))

    def test_panel_preselects_its_own_exchange(self) -> None:
        page = self._page(help_content.KALSHI)
        tags = {s.tag for s in page._visible_sections()}
        self.assertEqual(tags, {help_content.KALSHI})
        self.assertTrue(page._chips[help_content.KALSHI].isChecked())

    def test_unknown_default_tag_falls_back_to_all(self) -> None:
        page = self._page("NotATag")
        self.assertEqual(page._tag, ALL)

    def test_search_narrows_the_list(self) -> None:
        page = self._page()
        page._on_search("stretch")
        found = page._visible_sections()
        self.assertTrue(found)
        self.assertLess(len(found), len(help_content.SECTIONS))

    def test_search_and_tag_filter_combine(self) -> None:
        """Ang tag ay dapat mag-narrow pa sa search, hindi palitan."""
        page = self._page()
        page._on_search("settings")
        both = len(page._visible_sections())
        page._on_tag(help_content.KALSHI)
        kalshi_only = page._visible_sections()
        self.assertTrue(kalshi_only)
        self.assertLessEqual(len(kalshi_only), both)
        self.assertEqual({s.tag for s in kalshi_only}, {help_content.KALSHI})

    def test_no_match_does_not_crash_and_reports_it(self) -> None:
        page = self._page()
        page._on_search("qqqzzzxyz")
        self.assertEqual(page._visible_sections(), [])
        self.assertIn("0 of", page._count.text())

    def test_clearing_search_restores_everything(self) -> None:
        page = self._page()
        page._on_search("stretch")
        page._on_search("")
        self.assertEqual(len(page._visible_sections()),
                         len(help_content.SECTIONS))

    def test_switching_back_to_all_shows_everything(self) -> None:
        page = self._page(help_content.KALSHI)
        page._on_tag(ALL)
        self.assertEqual(len(page._visible_sections()),
                         len(help_content.SECTIONS))

    def test_only_one_chip_is_checked_at_a_time(self) -> None:
        page = self._page()
        page._on_tag(help_content.POLYMARKET)
        checked = [n for n, c in page._chips.items() if c.isChecked()]
        self.assertEqual(checked, [help_content.POLYMARKET])

    def test_rerender_does_not_leave_stale_cards(self) -> None:
        """Ang setParent(None) ay nag-aalis agad — kung deleteLater lang,
        nananatiling nakikita ang lumang laman sa ibabaw ng bago."""
        page = self._page()
        page._on_search("stretch")
        expected = len(page._visible_sections())
        self.assertEqual(page._body_col.count(), expected)


if __name__ == "__main__":
    unittest.main()
