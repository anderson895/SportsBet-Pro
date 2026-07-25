"""About / Help page — buong dokumentasyon na may search at tag filter.

Dati: dalawang linyang paragraph kada panel. Ngayon: lahat ng kailangang
malaman tungkol sa dalawang exchange, sa mga setting, at sa mga karaniwang
problema — na mabilis mahanap.
"""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.ui import help_content
from src.ui import theme
from src.ui.widgets import Card

ALL = "All"

# Kulay ng tag chip kada exchange, para agad makita kung saan nauukol
_TAG_COLORS = {
    help_content.KALSHI: theme.KALSHI_ACCENT,
    help_content.POLYMARKET: theme.POLY_ACCENT,
    help_content.GENERAL: theme.MUTED,
}


class AboutPage(QWidget):
    """Naghahanap sa lahat ng seksyon; opsyonal na naka-filter sa tag."""

    def __init__(self, title_text: str, body_text: str = "",
                 default_tag: str = ALL) -> None:
        """`title_text` at `body_text` ay galing sa panel (per-exchange na
        buod). Ang `default_tag` ay nagpi-preselect ng chip para makita
        agad ng user ang sariling exchange."""
        super().__init__()
        self._query = ""
        self._tag = default_tag if default_tag in (
            [ALL] + help_content.tags()) else ALL

        title = QLabel(title_text)
        title.setProperty("h1", True)

        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Search help — e.g. hedge, fees, wallet type, why no trade…")
        self._search.setClearButtonEnabled(True)
        self._search.addAction(
            qta.icon("fa6s.magnifying-glass", color=theme.MUTED),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self._search.textChanged.connect(self._on_search)

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._search, stretch=1)

        # ---- tag filter chips -------------------------------------------
        self._chips: dict[str, QPushButton] = {}
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        for name in [ALL] + help_content.tags():
            chip = QPushButton(name)
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(
                lambda _checked, n=name: self._on_tag(n))
            self._chips[name] = chip
            chips_row.addWidget(chip)
        chips_row.addStretch()
        self._count = QLabel("")
        self._count.setProperty("muted", True)
        chips_row.addWidget(self._count)

        # ---- scrollable body --------------------------------------------
        self._body_host = QWidget()
        self._body_host.setObjectName("helpBody")
        # Naka-scope sa #objectName: ang walang-selector na rule ay
        # kumakalat sa lahat ng anak at sisirain ang card backgrounds
        self._body_host.setStyleSheet(
            "#helpBody { background: transparent; }")
        self._body_col = QVBoxLayout(self._body_host)
        self._body_col.setContentsMargins(0, 4, 8, 6)
        self._body_col.setSpacing(12)
        self._body_col.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._body_host)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll = scroll

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addLayout(head)
        root.addLayout(chips_row)
        root.addWidget(scroll, stretch=1)

        self._render()

    # ------------------------------------------------------------- slots

    def _on_search(self, text: str) -> None:
        self._query = text
        self._render()

    def _on_tag(self, name: str) -> None:
        self._tag = name
        self._render()

    # ----------------------------------------------------------- render

    def _visible_sections(self) -> list[help_content.Section]:
        found = help_content.search(self._query)
        if self._tag != ALL:
            found = [s for s in found if s.tag == self._tag]
        return found

    def _render(self) -> None:
        # hide() bago ang deleteLater: ang deleteLater lang ay naghihintay pa
        # ng event loop, kaya nananatiling nakikita ang lumang laman sa
        # ibabaw ng bago.
        #
        # hide(), HINDI setParent(None): ang pag-set ng parent sa None ay
        # ginagawang TOP-LEVEL WINDOW ang widget, at kumikislap ito bilang
        # maliliit na kahon sa screen tuwing magsa-search.
        while self._body_col.count():
            item = self._body_col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

        for name, chip in self._chips.items():
            chip.setChecked(name == self._tag)

        sections = self._visible_sections()
        total = len(help_content.SECTIONS)
        self._count.setText(
            f"{len(sections)} of {total} topics"
            if len(sections) != total else f"{total} topics"
        )

        if not sections:
            empty = QLabel(
                f'No help topic matches "{self._query}".\n\n'
                "Try a shorter word, or switch the filter back to All."
            )
            empty.setProperty("muted", True)
            empty.setWordWrap(True)
            self._body_col.addWidget(empty)
            return

        for section in sections:
            self._body_col.addWidget(self._section_card(section))
        self._scroll.verticalScrollBar().setValue(0)

    def _section_card(self, section: help_content.Section) -> QWidget:
        card = Card()
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(8)

        heading = QLabel(section.title)
        heading.setStyleSheet("font-size: 15px; font-weight: 800")
        heading.setWordWrap(True)

        tag = QLabel(section.tag.upper())
        color = _TAG_COLORS.get(section.tag, theme.MUTED)
        tag.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.8px"
        )

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(heading, stretch=1)
        head.addWidget(tag, alignment=Qt.AlignmentFlag.AlignTop)
        col.addLayout(head)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"color: {theme.BORDER_SOFT};")
        col.addWidget(divider)

        body = QLabel(section.body)
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet(
            f"color: {theme.MUTED}; font-size: 13px;"
            " font-family: 'Segoe UI', 'Segoe UI Variable';"
        )
        col.addWidget(body)
        return card
