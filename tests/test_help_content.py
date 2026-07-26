"""Nilalaman at search ng About / Help page.

Ang dokumentasyon ay mabuti lang kung MAHANAP. Ang mga test na ito ay
nagsisiguro na (a) naroon ang mahahalagang paksa, (b) matatagpuan sila sa
mga salitang aktwal na itatype ng user, at (c) tumutugma pa rin ang mga
numero sa totoong DEFAULTS ng app — para hindi mapag-iwanan ang help kapag
nagbago ang code.
"""
import unittest

from src.ui import help_content
from src.ui.help_content import GENERAL, KALSHI, POLYMARKET, SECTIONS, search
from src.ui.kalshi_settings import DEFAULTS as KALSHI_DEFAULTS


class ContentShapeTest(unittest.TestCase):
    def test_every_section_is_filled_in(self) -> None:
        for s in SECTIONS:
            self.assertTrue(s.title.strip(), "walang title")
            self.assertTrue(s.body.strip(), f"walang body: {s.title}")
            self.assertIn(s.tag, (GENERAL, KALSHI, POLYMARKET),
                          f"hindi kilalang tag: {s.tag}")

    def test_titles_are_unique(self) -> None:
        titles = [s.title for s in SECTIONS]
        self.assertEqual(len(titles), len(set(titles)))

    def test_both_exchanges_are_documented(self) -> None:
        tags = {s.tag for s in SECTIONS}
        self.assertIn(KALSHI, tags)
        self.assertIn(POLYMARKET, tags)
        self.assertIn(GENERAL, tags)

    def test_tags_helper_lists_each_tag_once(self) -> None:
        tags = help_content.tags()
        self.assertEqual(len(tags), len(set(tags)))
        self.assertEqual(set(tags), {s.tag for s in SECTIONS})


class SearchTest(unittest.TestCase):
    def test_empty_query_returns_everything(self) -> None:
        self.assertEqual(len(search("")), len(SECTIONS))
        self.assertEqual(len(search("   ")), len(SECTIONS))

    def test_search_is_case_insensitive(self) -> None:
        self.assertEqual([s.title for s in search("HEDGE")],
                         [s.title for s in search("hedge")])

    def test_finds_by_body_text_not_just_title(self) -> None:
        """'rubber band' ay nasa body ng mean-reversion section."""
        found = [s.title for s in search("rubber band")]
        self.assertTrue(found)
        self.assertTrue(any("Mean Reversion" in t for t in found))

    def test_finds_by_keyword_synonym(self) -> None:
        """Hindi lumalabas ang salitang 'idle' sa ibang title — dapat
        mahanap sa keywords ang tanong na 'nothing happening'."""
        self.assertTrue([s for s in search("nothing happening")])

    def test_all_words_must_match(self) -> None:
        """Multi-word na query = AND, hindi OR."""
        self.assertTrue(search("mean reversion"))
        self.assertEqual(search("mean zzzznotarealword"), [])

    def test_unknown_query_returns_nothing(self) -> None:
        self.assertEqual(search("qqqzzzxyz"), [])

    def test_results_keep_document_order(self) -> None:
        found = search("kalshi")
        order = [SECTIONS.index(s) for s in found]
        self.assertEqual(order, sorted(order))


class UserQuestionsTest(unittest.TestCase):
    """Mga totoong tanong na lumitaw habang ginagamit ang app — bawat isa
    dapat may masasagot na paksa."""

    QUESTIONS = {
        "mean reversion": "how the strategy works",
        "stretch": "entry conditions",
        "wallet type": "Wallet Type / balance 0.00",
        "why no trade": "entry conditions",
        "idle": "why the bot sits idle",
        "resting": "reading the Trades page",
        "signer": "rejected Polymarket orders",
        "stop": "safety notes",
        "timeframe": "settings reference",
    }

    def test_each_question_finds_a_topic(self) -> None:
        for query, why in self.QUESTIONS.items():
            with self.subTest(query=query):
                self.assertTrue(
                    search(query),
                    f"walang tumugma sa {query!r} (inaasahan: {why})",
                )


class StaysInSyncWithCodeTest(unittest.TestCase):
    """Ang stale na dokumentasyon ay mas masahol pa sa wala."""

    def _kalshi_body(self, needle: str) -> str:
        for s in SECTIONS:
            if s.tag == KALSHI and needle in s.title:
                return s.body
        self.fail(f"walang Kalshi section na may {needle!r} sa title")

    def test_documented_entry_stretch_matches_default(self) -> None:
        body = self._kalshi_body("settings reference")
        self.assertIn(f"{KALSHI_DEFAULTS['min_stretch_pct']:g}%", body)

    def test_documented_take_profit_matches_default(self) -> None:
        body = self._kalshi_body("settings reference")
        self.assertIn(f"{int(KALSHI_DEFAULTS['profit_target_pct'])}%", body)


if __name__ == "__main__":
    unittest.main()
