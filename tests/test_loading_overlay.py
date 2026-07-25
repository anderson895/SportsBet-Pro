"""Startup loading gate.

Bakit ito kailangan: sa pagbukas ng app, "Checking…" pa ang mga connection
at wala pang na-scan na market. Kung magagamit agad ang UI, puwedeng
pindutin ng user ang START BOT bago malaman kung konektado nga, o
mag-navigate sa blangkong page at isipin na sira ang app.

Kritikal na detalye: kailangang MAGSARA ang overlay kahit BUMAGSAK ang
isang check — kung hinihintay natin ang "konektado", permanenteng
maka-lock ang app kapag offline.
"""
import unittest

from PySide6.QtWidgets import QApplication

from src.ui.loading_overlay import LoadingOverlay

_app = QApplication.instance() or QApplication([])

STEPS = [("a", "Step A"), ("b", "Step B"), ("c", "Step C")]


class LoadingOverlayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.done = []
        self.ov = LoadingOverlay(list(STEPS))
        self.ov.finished.connect(lambda: self.done.append(True))

    def tearDown(self) -> None:
        self.ov.deleteLater()

    def test_starts_with_all_steps_pending(self) -> None:
        self.assertEqual(self.ov._pending, {"a", "b", "c"})
        self.assertEqual(self.done, [])

    def test_finishes_only_after_every_step(self) -> None:
        self.ov.mark_done("a")
        self.ov.mark_done("b")
        self.assertEqual(self.done, [], "hindi pa dapat tapos")
        self.ov.mark_done("c")
        self.assertEqual(self.done, [True])
        self.assertFalse(self.ov.isVisible())

    def test_duplicate_marks_are_harmless(self) -> None:
        """Tuwing 15s ang connection monitor — paulit-ulit na darating ang
        parehong pangalan."""
        for _ in range(3):
            self.ov.mark_done("a")
        self.assertEqual(self.ov._pending, {"b", "c"})
        self.ov.mark_done("b")
        self.ov.mark_done("c")
        self.assertEqual(self.done, [True], "isang beses lang dapat mag-emit")

    def test_unknown_step_does_not_crash(self) -> None:
        self.ov.mark_done("hindi-kilala")
        self.assertEqual(self.ov._pending, {"a", "b", "c"})

    def test_timeout_releases_the_app(self) -> None:
        """Kung may hindi tumugon, hindi dapat ma-trap ang user."""
        self.ov._on_timeout()
        self.assertEqual(self.done, [True])
        self.assertFalse(self.ov.isVisible())

    def test_timeout_after_finish_does_not_emit_twice(self) -> None:
        for key in ("a", "b", "c"):
            self.ov.mark_done(key)
        self.ov._on_timeout()
        self.assertEqual(self.done, [True])

    def test_step_label_shows_a_tick_when_done(self) -> None:
        row = self.ov._rows["a"]
        self.assertTrue(row.text().startswith("○"))
        self.ov.mark_done("a")
        self.assertTrue(row.text().startswith("✓"))
        self.assertIn("Step A", row.text())

    def test_animation_stops_on_finish(self) -> None:
        """Walang timer na patuloy na tumatakbo pagkatapos — walang leak."""
        self.assertTrue(self.ov._anim.isActive())
        self.ov._on_timeout()
        self.assertFalse(self.ov._anim.isActive())
        self.assertFalse(self.ov._timeout.isActive())


if __name__ == "__main__":
    unittest.main()
