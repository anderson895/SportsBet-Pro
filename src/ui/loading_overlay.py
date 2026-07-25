"""Startup loading overlay — hinaharangan ang app hanggang handa ang data.

Bakit: sa pagbukas ng app, ang mga connection check ay "Checking…" pa at
wala pang na-scan na market. Kung magagamit agad ang UI sa estadong iyon,
puwedeng pindutin ng user ang START BOT bago pa malaman kung konektado
nga, o mag-navigate sa mga blangkong page at isipin na sira ang app.

Kaya inilalagay ito sa IBABAW ng buong window: nakikita ang progreso ng
bawat hakbang, at dahil nasa itaas ito ng lahat, naka-block din ang mga
click sa likod.
"""
from __future__ import annotations

from typing import Iterable

import qtawesome as qta
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.ui import theme

# Kung may hindi tumugon (hal. patay ang network), huwag i-trap ang user —
# awtomatikong isasara ang overlay pagkatapos ng ganitong tagal.
TIMEOUT_MS = 20_000


class LoadingOverlay(QWidget):
    """Semi-transparent na overlay na may spinner at checklist ng hakbang."""

    finished = Signal()

    def __init__(self, steps: Iterable[tuple[str, str]],
                 parent: QWidget | None = None) -> None:
        """`steps` = [(key, label), …] sa pagkakasunod-sunod ng pagpapakita."""
        super().__init__(parent)
        self._pending = {key for key, _ in steps}
        self._done_shown = False

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        # Kumukuha ng mouse/keyboard para hindi maabot ang UI sa likod
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Sinusundan ang sukat ng parent. Ginagawa ito ng overlay MISMO sa
        # pamamagitan ng event filter — hindi puwedeng basta itakda sa
        # __init__ dahil wala pang laid-out na sukat ang parent sa oras na
        # iyon (640x480 pa ang default), at hindi lahat ng resize ay
        # dumadaan sa window na nagtayo nito.
        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())

        self._spinner = QLabel()
        self._spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_angle = 0

        title = QLabel("Starting SportsBet Pro")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 800;"
                            f" color: {theme.TEXT}; background: transparent")

        sub = QLabel("Connecting to the exchanges and loading live markets…")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {theme.MUTED}; background: transparent")

        col = QVBoxLayout(self)
        col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.setSpacing(9)
        col.addWidget(self._spinner)
        col.addSpacing(4)
        col.addWidget(title)
        col.addWidget(sub)
        col.addSpacing(10)

        # Ang mga hakbang ay nasa SARILING kahon na kasukat lang ng
        # pinakamahabang row, at ang kahon ang isinesentro. Kung ang bawat
        # label ay direktang inilagay sa centered column, ang mga ito ay
        # nagiging kasing-lapad ng buong column at ang teksto (left-aligned
        # para pantay ang mga bullet) ay nagsisimula sa MALAYONG kaliwa —
        # kaya mukhang nakahilig ang listahan kumpara sa naka-center na title.
        steps_box = QWidget()
        steps_box.setObjectName("loadingSteps")
        steps_box.setStyleSheet(
            "#loadingSteps { background: transparent; }"
        )
        steps_col = QVBoxLayout(steps_box)
        steps_col.setContentsMargins(0, 0, 0, 0)
        steps_col.setSpacing(9)

        self._rows: dict[str, QLabel] = {}
        for key, label in steps:
            row = QLabel(f"○   {label}")
            row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            row.setStyleSheet(f"color: {theme.FAINT}; font-size: 13px;"
                              " background: transparent")
            self._rows[key] = row
            steps_col.addWidget(row)
        col.addWidget(steps_box, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Spinner animation
        self._anim = QTimer(self)
        self._anim.setInterval(70)
        self._anim.timeout.connect(self._tick_spinner)
        self._anim.start()
        self._tick_spinner()

        # Safety net: huwag i-trap ang user kung may hindi tumugon
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)
        self._timeout.start(TIMEOUT_MS)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Manatiling kasukat ng parent at nasa ibabaw ng mga kapatid."""
        if (watched is self.parentWidget()
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Show)):
            self.setGeometry(self.parentWidget().rect())
            self.raise_()
        return super().eventFilter(watched, event)

    # -------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Manu-manong pintura ng SOLID na backdrop.

        Solid, hindi semi-transparent: kapag nakikita pa ang kalahating
        handa nang UI sa likod, mukhang sirang app ito kaysa loading
        screen — at nakakatukso pa ring pindutin.
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG))

    def _tick_spinner(self) -> None:
        self._spin_angle = (self._spin_angle + 30) % 360
        icon = qta.icon("fa6s.spinner", color=theme.ACCENT,
                        rotated=self._spin_angle)
        self._spinner.setPixmap(icon.pixmap(34, 34))

    # ------------------------------------------------------------------- API

    def mark_done(self, key: str) -> None:
        """Markahan bilang tapos ang isang hakbang; isasara kapag wala nang
        natitira."""
        row = self._rows.get(key)
        if row is not None and key in self._pending:
            row.setText(f"✓   {row.text()[4:]}")
            row.setStyleSheet(f"color: {theme.ACCENT}; font-size: 13px;"
                              " background: transparent")
        self._pending.discard(key)
        if not self._pending:
            self._finish()

    def _on_timeout(self) -> None:
        """Nag-timeout: ipagamit ang app kahit hindi kumpleto — mas mabuti
        ang bahagyang UI kaysa naka-lock na app."""
        self._finish()

    def _finish(self) -> None:
        if self._done_shown:
            return
        self._done_shown = True
        self._anim.stop()
        self._timeout.stop()
        self.hide()
        self.finished.emit()

    # Sinasalo ang input habang nakikita — dagdag na proteksyon bukod sa
    # pagiging nasa itaas ng stack
    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        event.accept()
