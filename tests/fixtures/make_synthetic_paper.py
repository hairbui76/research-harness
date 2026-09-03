"""Deterministic synthetic research PDFs with recorded ground truth (Roadmap 5).

Integration tests need documents whose pages, tables, and section structure are known
exactly, without coupling CI to publisher PDFs. Running this module regenerates all three
fixtures; `GROUND_TRUTH` is what the tests assert against.

The third fixture reproduces the two ways a real publisher PDF defeats a naive extractor:
one paragraph draws its words at computed pen positions with no space glyph between them,
and one font writes its text already displaced by `CIPHER_SHIFT`, so the file literally
contains `VHUYLFH` where it means `SERVICE`.

Usage::

    uv run python -m tests.fixtures.make_synthetic_paper
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pymupdf

__all__ = [
    "CIPHER_SHIFT",
    "GROUND_TRUTH",
    "PUBLISHER_QUIRKS_PDF",
    "SINGLE_COLUMN_PDF",
    "TWO_COLUMN_PDF",
    "build_publisher_quirks_paper",
    "build_single_column_paper",
    "build_two_column_paper",
    "caesar",
    "main",
    "render",
]

FIXTURES_DIR = Path(__file__).resolve().parent
SINGLE_COLUMN_PDF = FIXTURES_DIR / "synthetic_research_paper.pdf"
TWO_COLUMN_PDF = FIXTURES_DIR / "synthetic_two_column_paper.pdf"
PUBLISHER_QUIRKS_PDF = FIXTURES_DIR / "synthetic_publisher_quirks.pdf"

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0
MARGIN = 54.0
GUTTER = 18.0
COLUMN_WIDTH = (PAGE_WIDTH - 2 * MARGIN - GUTTER) / 2

BODY_FONT = "helv"
BOLD_FONT = "hebo"
BODY_SIZE = 10.0
TITLE_SIZE = 17.0
HEADING_SIZE = 12.0
SUBHEADING_SIZE = 11.0
CAPTION_SIZE = 9.0
REFERENCE_SIZE = 9.5
FOOTNOTE_SIZE = 7.5
LEADING = 1.32

_FIXED_DATE = "D:20240101000000Z"

#: MuPDF derives the second half of the trailer /ID from the save, so it is rewritten to a
#: constant afterwards; both halves are 32 hex digits, so byte offsets never move.
_FIXED_ID = "[<0123456789ABCDEF0123456789ABCDEF><FEDCBA9876543210FEDCBA9876543210>]"
_ID_PATTERN = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]")


class _Column:
    """A text cursor down one column of one page; y is the next baseline."""

    def __init__(self, page: pymupdf.Page, left: float, width: float, top: float) -> None:
        self.page = page
        self.left = left
        self.width = width
        self.y = top

    def write(
        self,
        text: str,
        *,
        size: float = BODY_SIZE,
        font: str = BODY_FONT,
        space_before: float = 0.0,
        space_after: float = 4.0,
        indent: float = 0.0,
    ) -> pymupdf.Rect:
        """Write wrapped text and return the rectangle it occupied."""
        self.y += space_before
        top = self.y - size
        for index, line in enumerate(_wrap(text, self.width - indent, font, size)):
            offset = indent if index else 0.0
            self.page.insert_text((self.left + offset, self.y), line, fontsize=size, fontname=font)
            self.y += size * LEADING
        bottom = self.y - size * LEADING + size * 0.3
        self.y += space_after
        return pymupdf.Rect(self.left, top, self.left + self.width, bottom)


def _wrap(text: str, width: float, font: str, size: float) -> list[str]:
    """Greedy word wrap using the real glyph widths, so line breaks are reproducible."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and pymupdf.get_text_length(candidate, fontname=font, fontsize=size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_table(
    page: pymupdf.Page,
    left: float,
    top: float,
    rows: list[list[str]],
    col_widths: list[float],
    *,
    row_height: float = 17.0,
    size: float = CAPTION_SIZE,
) -> pymupdf.Rect:
    """Draw a fully ruled grid so `page.find_tables()` recovers the exact cell geometry."""
    width = sum(col_widths)
    height = row_height * len(rows)
    for index in range(len(rows) + 1):
        y = top + index * row_height
        page.draw_line((left, y), (left + width, y), width=0.7)
    x = left
    for index in range(len(col_widths) + 1):
        page.draw_line((x, top), (x, top + height), width=0.7)
        if index < len(col_widths):
            x += col_widths[index]
    for row_index, row in enumerate(rows):
        x = left
        for col_index, cell in enumerate(row):
            font = BOLD_FONT if row_index == 0 else BODY_FONT
            page.insert_text(
                (x + 4.0, top + row_index * row_height + row_height - 5.0),
                cell,
                fontsize=size,
                fontname=font,
            )
            x += col_widths[col_index]
    return pymupdf.Rect(left, top, left + width, top + height)


def _new_document(title: str, author: str) -> pymupdf.Document:
    doc: pymupdf.Document = pymupdf.open()
    doc.set_metadata(
        {
            "title": title,
            "author": author,
            "subject": "synthetic fixture",
            "keywords": "research-harness fixture",
            "creator": "make_synthetic_paper.py",
            "producer": "research-harness",
            "creationDate": _FIXED_DATE,
            "modDate": _FIXED_DATE,
            "trapped": "",
            "format": "PDF 1.7",
            "encryption": None,
        }
    )
    return doc


def _page(doc: pymupdf.Document) -> pymupdf.Page:
    return doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)


# --- paper 1: single column -------------------------------------------------------

TITLE_1 = "Deep Representations for Encrypted Network Traffic"
AUTHORS_1 = "A. Researcher, B. Collaborator, C. Advisor"
DOI_1 = "10.1000/xyz123"
ARXIV_1 = "arXiv:2401.12345"
TABLE_1_CAPTION = "Table 1: Detection performance on CICIDS2017."
FIGURE_1_CAPTION = "Figure 1: Confusion matrix for TrafficLM on the held-out split."
EQUATION_1 = "L(theta) = - sum_i y_i log p_i(x; theta) + lambda ||theta||^2   (1)"
TABLE_1_ROWS = [
    ["Model", "Dataset", "F1", "Precision"],
    ["TrafficLM", "CICIDS2017", "94.32", "93.10"],
    ["FlowBERT", "CICIDS2017", "91.75", "90.44"],
    ["BaselineRF", "CICIDS2017", "88.10", "87.02"],
]
REFERENCES_1 = [
    "[1] A. Author and B. Coauthor. Learning traffic representations. "
    "In Proceedings of the Example Conference on Networking, pages 11-24, 2023.",
    "[2] C. Researcher. A survey of encrypted traffic classification. "
    "Journal of Example Studies, 41(3):188-207, 2022.",
    "[3] D. Scientist and E. Engineer. A labelled dataset for intrusion detection. "
    "arXiv:2312.00001, 2024.",
]


def build_single_column_paper() -> pymupdf.Document:
    """Five-page single-column paper with one ruled table, a figure caption, and references."""
    doc = _new_document(TITLE_1, AUTHORS_1)
    content_width = PAGE_WIDTH - 2 * MARGIN

    page = _page(doc)
    col = _Column(page, MARGIN, content_width, MARGIN + TITLE_SIZE)
    col.write(TITLE_1, size=TITLE_SIZE, font=BOLD_FONT, space_after=10)
    col.write(AUTHORS_1, size=BODY_SIZE, space_after=14)
    col.write("Abstract", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    col.write(
        "Encrypted network traffic hides payload content from classical signature "
        "detectors, so modern intrusion detection relies on flow level features. We "
        "study whether a pretrained sequence model learns representations of traffic "
        "that transfer across capture conditions, and we report detection quality on a "
        "public benchmark under a fixed evaluation protocol.",
        space_after=16,
    )
    col.write("1 Introduction", size=HEADING_SIZE, font=BOLD_FONT, space_before=4, space_after=5)
    col.write(
        "Network intrusion detection systems must decide, from headers and timing alone, "
        "whether a flow is benign. Payload inspection is unavailable once transport "
        "encryption is in use, and hand engineered features age badly as protocols "
        "change. Representation learning offers an alternative: train once on unlabelled "
        "captures, then fine tune on a small labelled corpus.",
        space_after=8,
    )
    col.write(
        "This paper asks a narrow question. Given the same benchmark, the same split, and "
        "the same budget, does a pretrained model beat a tuned tree ensemble? We describe "
        "the tokenization scheme, the evaluation protocol, and the limitations that follow "
        "from studying a single capture environment.",
        space_after=8,
    )

    page = _page(doc)
    col = _Column(page, MARGIN, content_width, MARGIN + HEADING_SIZE)
    col.write("2 Method", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    col.write(
        "Our model consumes a flow as an ordered sequence of packet descriptors. Each "
        "descriptor carries direction, inter arrival time bucket, and payload length "
        "bucket. The encoder is a twelve layer transformer trained with a masked "
        "descriptor objective on unlabelled captures.",
        space_after=10,
    )
    col.write(
        "2.1 Tokenization", size=SUBHEADING_SIZE, font=BOLD_FONT, space_before=4, space_after=5
    )
    col.write(
        "Tokenization maps each packet descriptor to one of 4096 discrete tokens. "
        "Continuous quantities are bucketed with quantile boundaries estimated on the "
        "pretraining corpus, which keeps the vocabulary stable when the capture rate "
        "changes. The loss is the usual masked cross entropy with weight decay:",
        space_after=10,
    )
    col.write(EQUATION_1, space_before=2, space_after=10, indent=0.0)
    col.write(
        "Bucket boundaries are frozen after pretraining so that a fine tuned checkpoint "
        "and its pretrained parent agree on the meaning of every token.",
        space_before=6,
        space_after=8,
    )

    page = _page(doc)
    col = _Column(page, MARGIN, content_width, MARGIN + HEADING_SIZE)
    col.write("3 Experiments", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    col.write(
        "We evaluate detection quality under a single fixed protocol: one training split, "
        "one validation split for early stopping, and one held out test split that is "
        "never inspected during development.",
        space_after=10,
    )
    col.write("3.1 Dataset", size=SUBHEADING_SIZE, font=BOLD_FONT, space_before=4, space_after=5)
    col.write(
        f"All experiments use CICIDS2017, a labelled capture of benign and attack traffic "
        f"released with DOI {DOI_1} and mirrored as {ARXIV_1}. We keep the official day "
        f"boundaries, discard flows shorter than three packets, and report macro averaged "
        f"scores over the five attack families that remain after filtering. The resulting "
        f"corpus contains 1.2 million flows.",
        space_after=8,
    )
    col.write(
        "Class imbalance is severe: benign flows outnumber attack flows by roughly forty "
        "to one, so accuracy is uninformative and we report F1 and precision instead.",
        space_after=8,
    )
    footnote = _Column(page, MARGIN, content_width, PAGE_HEIGHT - MARGIN - 6.0)
    footnote.write(
        "1 The CICIDS2017 archive is distributed by its original authors and is not "
        "redistributed here.",
        size=FOOTNOTE_SIZE,
        space_after=0,
    )

    page = _page(doc)
    col = _Column(page, MARGIN, content_width, MARGIN + HEADING_SIZE)
    col.write("4 Results", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    col.write(
        "Table 1 reports detection quality for the pretrained model and two baselines "
        "under the protocol of Section 3. The pretrained encoder improves F1 by 2.57 "
        "points over the strongest baseline, and the gain is concentrated in the two "
        "rarest attack families.",
        space_after=12,
    )
    col.write(TABLE_1_CAPTION, size=CAPTION_SIZE, space_after=6)
    table_rect = _draw_table(
        page,
        MARGIN + 40.0,
        col.y,
        TABLE_1_ROWS,
        [110.0, 110.0, 70.0, 90.0],
    )
    col.y = table_rect.y1 + 18.0
    col.write(FIGURE_1_CAPTION, size=CAPTION_SIZE, space_after=10)
    col.write(
        "Errors concentrate on short lived flows, where the descriptor sequence is too "
        "brief for the encoder to use its context window.",
        space_after=8,
    )

    page = _page(doc)
    col = _Column(page, MARGIN, content_width, MARGIN + HEADING_SIZE)
    col.write("5 Limitations", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    col.write(
        "Every result here concerns encrypted traffic captured in one environment over "
        "one week. We do not claim transfer to other networks, and we did not evaluate "
        "adversarial evasion. Reported gains are within benchmark noise for the two "
        "largest attack families.",
        space_after=16,
    )
    col.write("References", size=HEADING_SIZE, font=BOLD_FONT, space_before=6, space_after=6)
    for entry in REFERENCES_1:
        col.write(entry, size=REFERENCE_SIZE, space_after=6, indent=14.0)
    return doc


# --- paper 2: two columns ---------------------------------------------------------

TITLE_2 = "Flow Level Anomaly Detection under Domain Shift"
AUTHORS_2 = "D. Analyst, E. Reviewer"
LEFT_MARKER_2 = "We study anomaly detectors that must survive a change of capture site."
RIGHT_MARKER_2 = "The encoder maps each flow record to a dense vector of fixed width."
TABLE_2A_CAPTION = "Table 1: Detection quality per capture site."
TABLE_2B_CAPTION = "Table 2: Ablation over encoder depth."
TABLE_2A_ROWS = [
    ["Site", "AUC", "Recall"],
    ["Site A", "0.971", "0.884"],
    ["Site B", "0.902", "0.771"],
]
TABLE_2B_ROWS = [
    ["Depth", "AUC", "Params"],
    ["6", "0.944", "21M"],
    ["12", "0.971", "42M"],
]
REFERENCES_2 = [
    "[1] F. Observer. Domain shift in network telemetry. Example Letters, 2021.",
    "[2] G. Practitioner. Deployment notes for flow detectors. Example Reports, 2023.",
]


def build_two_column_paper() -> pymupdf.Document:
    """Three-page two-column paper with two ruled tables and headings in both columns."""
    doc = _new_document(TITLE_2, AUTHORS_2)
    content_width = PAGE_WIDTH - 2 * MARGIN
    right_left = MARGIN + COLUMN_WIDTH + GUTTER

    page = _page(doc)
    banner = _Column(page, MARGIN, content_width, MARGIN + TITLE_SIZE)
    banner.write(TITLE_2, size=TITLE_SIZE, font=BOLD_FONT, space_after=8)
    banner.write(AUTHORS_2, size=BODY_SIZE, space_after=18)
    top = banner.y

    left = _Column(page, MARGIN, COLUMN_WIDTH, top)
    left.write("Abstract", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    left.write(
        "Anomaly detectors trained on one capture site degrade when deployed on another. "
        "We quantify that degradation and test whether a shared encoder narrows the gap.",
        space_after=12,
    )
    left.write("1 Introduction", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    left.write(
        f"{LEFT_MARKER_2} Operational telemetry differs between sites in packet rate, "
        "protocol mix, and the prevalence of tunnelling, so a detector tuned on one "
        "capture rarely keeps its operating point on another.",
        space_after=8,
    )

    right = _Column(page, right_left, COLUMN_WIDTH, top)
    right.write("2 Approach", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    right.write(
        f"{RIGHT_MARKER_2} Vectors are compared with cosine distance against a reference "
        "population drawn from the deployment site itself, which removes the need for "
        "labelled attacks at deployment time.",
        space_after=10,
    )
    right.write("2.1 Encoder", size=SUBHEADING_SIZE, font=BOLD_FONT, space_after=5)
    right.write(
        "The encoder is a six layer residual network over bucketed packet descriptors, "
        "trained with a contrastive objective on unlabelled flows from both sites.",
        space_after=8,
    )

    page = _page(doc)
    left = _Column(page, MARGIN, COLUMN_WIDTH, MARGIN + HEADING_SIZE)
    left.write("3 Evaluation", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    left.write(
        "We report area under the ROC curve and recall at a fixed alert budget for both "
        "capture sites, using the same threshold selection procedure throughout.",
        space_after=10,
    )
    left.write(TABLE_2A_CAPTION, size=CAPTION_SIZE, space_after=6)
    rect_a = _draw_table(page, MARGIN, left.y, TABLE_2A_ROWS, [80.0, 70.0, 70.0])
    left.y = rect_a.y1 + 16.0
    left.write(
        "Site B is the harder deployment: its benign population is broader and its alert "
        "budget is smaller.",
        space_after=8,
    )

    right = _Column(page, right_left, COLUMN_WIDTH, MARGIN + HEADING_SIZE)
    right.write("3.1 Ablation", size=SUBHEADING_SIZE, font=BOLD_FONT, space_after=5)
    right.write(
        "Depth helps until it does not: doubling the encoder doubles parameters for a "
        "modest gain, which matters when the detector runs on a capture appliance.",
        space_after=10,
    )
    right.write(TABLE_2B_CAPTION, size=CAPTION_SIZE, space_after=6)
    rect_b = _draw_table(page, right_left, right.y, TABLE_2B_ROWS, [70.0, 70.0, 70.0])
    right.y = rect_b.y1 + 16.0
    right.write(
        "We therefore keep the six layer encoder for all deployment experiments.",
        space_after=8,
    )

    page = _page(doc)
    left = _Column(page, MARGIN, COLUMN_WIDTH, MARGIN + HEADING_SIZE)
    left.write("4 Discussion", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    left.write(
        "A shared encoder narrows but does not close the cross site gap. The remaining "
        "difference tracks the prevalence of tunnelled traffic, which suggests a data "
        "problem rather than a modelling one.",
        space_after=8,
    )
    right = _Column(page, right_left, COLUMN_WIDTH, MARGIN + HEADING_SIZE)
    right.write("References", size=HEADING_SIZE, font=BOLD_FONT, space_after=6)
    for entry in REFERENCES_2:
        right.write(entry, size=REFERENCE_SIZE, space_after=6, indent=12.0)
    return doc


# --- paper 3: publisher quirks ----------------------------------------------------

TITLE_3 = "Justified Layout and Subset Fonts in Traffic Papers"
AUTHORS_3 = "H. Typesetter, I. Compositor"

#: The offset a broken subset font displaces its character codes by in this fixture. The
#: text below is written already shifted, so the PDF literally contains `VHUYLFH`, exactly
#: as a real subsetted font with no ToUnicode CMap hands `SERVICE` to an extractor.
CIPHER_SHIFT = 3
CIPHER_FONT = "cour"

#: Drawn one word at a time at computed pen positions with no space glyph between them,
#: which is how a justified line encodes its inter-word gaps.
JUSTIFIED_3 = (
    "The major limitation of existing solutions is that they highly rely on the deep "
    "features, which are overly dependent on data size and hard to generalize on unseen "
    "data collected at a second capture site."
)
#: Gap between two positioned words, in ems. Wider than the parser's 0.15 em space rule and
#: narrower than a drawn space, so only the gap rule can put the words back together.
JUSTIFIED_GAP_EM = 0.24

CIPHER_HEADING_3 = "3 SERVICE FINGERPRINT RECOVERY"
CIPHER_SUBHEADING_3 = "3.1 Service Fingerprint Matching"
CIPHER_BODY_3 = (
    "The service fingerprint of a session is recovered when the parser detects the offset "
    "that the subset font displaced every character code by, so the same heading reads the "
    "same on every machine."
)
#: No shift of the alphabet turns this into English, so it stays exactly as extracted and
#: must never open a section however bold and short it is.
UNDECODABLE_3 = "Zxqj Vkpf Wbtn Zxqj"
AFTER_UNDECODABLE_3 = (
    "Recovery is reported rather than assumed, so a reviewer can see which blocks the "
    "parser could not read before quoting any of them."
)


def caesar(text: str, shift: int) -> str:
    """Displace every visible ASCII code point by ``shift``, the way a broken subset font does."""
    return "".join(
        chr(ord(char) + shift) if 0x21 <= ord(char) + shift <= 0x7E and ord(char) >= 0x20 else char
        for char in text
    )


def _write_ciphered(
    column: _Column,
    text: str,
    *,
    shift: int = CIPHER_SHIFT,
    size: float = BODY_SIZE,
    font: str = CIPHER_FONT,
    space_before: float = 0.0,
    space_after: float = 4.0,
) -> pymupdf.Rect:
    """Wrap ``text`` normally, then draw each line displaced, the way a broken subset font is
    handed back by an extractor: the layout is real, only the character codes are wrong."""
    column.y += space_before
    top = column.y - size
    for line in _wrap(text, column.width, font, size):
        column.page.insert_text(
            (column.left, column.y), caesar(line, shift), fontsize=size, fontname=font
        )
        column.y += size * LEADING
    bottom = column.y - size * LEADING + size * 0.3
    column.y += space_after
    return pymupdf.Rect(column.left, top, column.left + column.width, bottom)


def _write_positioned(
    column: _Column,
    text: str,
    *,
    size: float = BODY_SIZE,
    font: str = BODY_FONT,
    gap_em: float = JUSTIFIED_GAP_EM,
    space_after: float = 8.0,
) -> pymupdf.Rect:
    """Write wrapped text one word at a time, with positioning instead of space glyphs."""
    top = column.y - size
    for line in _wrap(text, column.width, font, size):
        x = column.left
        for word in line.split():
            column.page.insert_text((x, column.y), word, fontsize=size, fontname=font)
            x += pymupdf.get_text_length(word, fontname=font, fontsize=size) + gap_em * size
        column.y += size * LEADING
    bottom = column.y - size * LEADING + size * 0.3
    column.y += space_after
    return pymupdf.Rect(column.left, top, column.left + column.width, bottom)


def build_publisher_quirks_paper() -> pymupdf.Document:
    """Two-page paper carrying the two failure modes real publisher PDFs show.

    Page 1 loses every space in one paragraph to positioning; page 2 sets three lines in a
    font whose codes are displaced by `CIPHER_SHIFT`, plus one short bold line that no shift
    recovers and that must therefore never become a heading.
    """
    doc = _new_document(TITLE_3, AUTHORS_3)
    content_width = PAGE_WIDTH - 2 * MARGIN

    page = _page(doc)
    col = _Column(page, MARGIN, content_width, MARGIN + TITLE_SIZE)
    col.write(TITLE_3, size=TITLE_SIZE, font=BOLD_FONT, space_after=10)
    col.write(AUTHORS_3, size=BODY_SIZE, space_after=14)
    col.write("Abstract", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    col.write(
        "Publisher PDFs encode inter word gaps as positioning and ship subset fonts with no "
        "character map, so a parser that trusts the extractor loses spaces and reads "
        "headings as nonsense. This fixture carries one instance of each fault.",
        space_after=16,
    )
    col.write("1 Introduction", size=HEADING_SIZE, font=BOLD_FONT, space_before=4, space_after=5)
    _write_positioned(col, JUSTIFIED_3, space_after=10)
    col.write(
        "The paragraph above contains no space glyph at all: every gap in it is a pen "
        "movement, and only the geometry says where one word ends.",
        space_after=8,
    )

    page = _page(doc)
    col = _Column(page, MARGIN, content_width, MARGIN + HEADING_SIZE)
    col.write("2 Method", size=HEADING_SIZE, font=BOLD_FONT, space_after=5)
    col.write(
        "We record the offset each font displaces its codes by, validate it on that font's "
        "own words, and apply it only to the spans of that font.",
        space_after=12,
    )
    _write_ciphered(col, CIPHER_HEADING_3, size=HEADING_SIZE, space_before=4, space_after=5)
    _write_ciphered(col, CIPHER_SUBHEADING_3, size=SUBHEADING_SIZE, space_before=2, space_after=5)
    _write_ciphered(col, CIPHER_BODY_3, size=BODY_SIZE, space_after=10)
    col.write(UNDECODABLE_3, size=HEADING_SIZE, font="tibo", space_after=6)
    col.write(AFTER_UNDECODABLE_3, space_after=8)
    return doc


# --- ground truth -----------------------------------------------------------------

GROUND_TRUTH: dict[str, dict[str, Any]] = {
    "synthetic_research_paper": {
        "path": SINGLE_COLUMN_PDF,
        "page_count": 5,
        "columns": 1,
        "strings_on_pages": {
            TITLE_1: 1,
            "1 Introduction": 1,
            "2.1 Tokenization": 2,
            DOI_1: 3,
            ARXIV_1: 3,
            "94.32": 4,
            "5 Limitations": 5,
        },
        "section_path_probe": {
            "contains": DOI_1,
            "section_path": ("3 Experiments", "3.1 Dataset"),
        },
        "table": {
            "page": 4,
            "caption": TABLE_1_CAPTION,
            "row_count": 4,
            "col_count": 4,
            "cells": {
                (0, 0): "Model",
                (0, 1): "Dataset",
                (0, 2): "F1",
                (0, 3): "Precision",
                (1, 0): "TrafficLM",
                (1, 1): "CICIDS2017",
                (1, 2): "94.32",
                (1, 3): "93.10",
                (2, 0): "FlowBERT",
                (2, 2): "91.75",
                (3, 0): "BaselineRF",
                (3, 2): "88.10",
            },
            "numeric_cell": {"row": 1, "col": 2, "text": "94.32"},
        },
        "figure_caption": {"page": 4, "text": FIGURE_1_CAPTION},
        "equation": {"page": 2, "contains": "(1)"},
        "footnote": {"page": 3, "contains": "CICIDS2017 archive"},
        "reference_count": 3,
        "reference_keys": ("1", "2", "3"),
        "headings": (
            TITLE_1,
            "Abstract",
            "1 Introduction",
            "2 Method",
            "2.1 Tokenization",
            "3 Experiments",
            "3.1 Dataset",
            "4 Results",
            "5 Limitations",
            "References",
        ),
    },
    "synthetic_two_column_paper": {
        "path": TWO_COLUMN_PDF,
        "page_count": 3,
        "columns": 2,
        "strings_on_pages": {
            TITLE_2: 1,
            LEFT_MARKER_2: 1,
            RIGHT_MARKER_2: 1,
            "0.971": 2,
            "4 Discussion": 3,
        },
        "reading_order": {"page": 1, "first": LEFT_MARKER_2, "then": RIGHT_MARKER_2},
        "tables": (
            {
                "page": 2,
                "caption": TABLE_2A_CAPTION,
                "cells": {(0, 0): "Site", (0, 1): "AUC", (1, 0): "Site A", (1, 1): "0.971"},
            },
            {
                "page": 2,
                "caption": TABLE_2B_CAPTION,
                "cells": {(0, 0): "Depth", (0, 2): "Params", (2, 0): "12", (2, 2): "42M"},
            },
        ),
        "reference_count": 2,
        "headings_by_column": {"left": "1 Introduction", "right": "2 Approach"},
    },
    "synthetic_publisher_quirks": {
        "path": PUBLISHER_QUIRKS_PDF,
        "page_count": 2,
        "columns": 1,
        "justified": {"page": 1, "text": JUSTIFIED_3, "opening": "The major limitation of"},
        "cipher": {
            "shift": -CIPHER_SHIFT,
            "font": "Courier",
            "page": 2,
            "literal": caesar("SERVICE", CIPHER_SHIFT),
            "heading": CIPHER_HEADING_3,
            "subheading": CIPHER_SUBHEADING_3,
            "body": CIPHER_BODY_3,
        },
        "undecodable": {"page": 2, "text": UNDECODABLE_3},
        "section_path_probe": {
            "contains": "Recovery is reported rather than assumed",
            "section_path": (CIPHER_HEADING_3, CIPHER_SUBHEADING_3),
        },
        "headings": (
            TITLE_3,
            "Abstract",
            "1 Introduction",
            "2 Method",
            CIPHER_HEADING_3,
            CIPHER_SUBHEADING_3,
        ),
    },
}


def render(document: pymupdf.Document) -> bytes:
    """Serialize a fixture reproducibly: same source, same bytes, on every run."""
    document.xref_set_key(-1, "ID", _FIXED_ID)
    data: bytes = document.tobytes(garbage=4, deflate=True, clean=True)
    pinned, count = _ID_PATTERN.subn(f"/ID{_FIXED_ID}".encode("ascii"), data)
    if count != 1 or len(pinned) != len(data):
        raise RuntimeError("could not pin the PDF trailer id without moving byte offsets")
    return pinned


def main() -> None:
    """Regenerate every fixture PDF in place."""
    for document, path in (
        (build_single_column_paper(), SINGLE_COLUMN_PDF),
        (build_two_column_paper(), TWO_COLUMN_PDF),
        (build_publisher_quirks_paper(), PUBLISHER_QUIRKS_PDF),
    ):
        path.write_bytes(render(document))
        document.close()


if __name__ == "__main__":
    main()
