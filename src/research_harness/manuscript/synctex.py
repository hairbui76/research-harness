"""SyncTeX: source line to PDF rectangle, and PDF point back to source line.

The parser is deliberately pure Python and reads the `.synctex(.gz)` file itself rather
than shelling out to the `synctex` command-line tool, because the tool ships with TeX Live
and a project compiled by `tectonic --synctex` may have no TeX Live at all. Bidirectional
navigation must work from the file the engine wrote, or not be offered.

"Not offered" is a first-class outcome. When the file is missing, unreadable, or in a
format this parser does not understand, the index reports
:class:`SynctexUnavailable` with a reason instead of guessing a location: the interface has
to be able to say honestly that source/PDF navigation is unavailable (LaTeX spec 6).

Coordinates. The file stores TeX scaled points; every value here is converted to PDF
points (1/72 inch) with the file's own unit, magnification, and offsets. The origin is the
**top-left of the page**, which is what SyncTeX measures from and what a PDF viewer's page
rectangle is easiest to map onto; a :class:`PdfLocation` is therefore the box's top-left
corner plus its width and its full height (the TeX height above the baseline plus the
depth below it).
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.errors import ResearchHarnessError

__all__ = [
    "MAX_FORWARD_LOCATIONS",
    "SP_PER_PDF_POINT",
    "PdfLocation",
    "SourceLocation",
    "SynctexIndex",
    "SynctexUnavailable",
    "SynctexUnavailableError",
    "SynctexUnavailableReason",
]

SP_PER_PDF_POINT = 65781.76
"""TeX scaled points in one PDF point: 65536 sp per TeX pt, times 72.27/72."""

MAX_FORWARD_LOCATIONS = 16
"""Cap on rectangles returned for one source line; a whole paragraph is not a location."""

_GZIP_MAGIC = b"\x1f\x8b"

#: ``(tag,line[,column]:x,y[:width[,height,depth]]`` for every record kind that carries a
#: position. ``[`` and ``(`` open boxes, ``]`` and ``)`` close them, and the rest are leaves.
_RECORD_RE = re.compile(
    r"^(?P<kind>[\[\(hvxkgr$])"
    r"(?P<tag>-?\d+),(?P<line>-?\d+)(?:,(?P<column>-?\d+))?"
    r":(?P<x>-?\d+),(?P<y>-?\d+)"
    r"(?::(?P<width>-?\d+)(?:,(?P<height>-?\d+),(?P<depth>-?\d+))?)?"
)
_BOX_KINDS = frozenset({"[", "(", "h", "v", "r"})


class SynctexUnavailableReason(StrEnum):
    """Why bidirectional navigation cannot be offered for this build."""

    NOT_REQUESTED = "not_requested"
    MISSING_FILE = "missing_file"
    UNREADABLE = "unreadable"
    UNSUPPORTED_FORMAT = "unsupported_format"
    NO_RECORDS = "no_records"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SynctexUnavailable(_Record):
    """The honest "no mapping" state, with a reason a user interface can show."""

    reason: SynctexUnavailableReason
    detail: str


class SynctexUnavailableError(ResearchHarnessError):
    """A lookup was attempted on an index that has no mapping."""

    def __init__(self, state: SynctexUnavailable) -> None:
        self.state = state
        super().__init__(f"SyncTeX mapping unavailable ({state.reason.value}): {state.detail}")


class PdfLocation(_Record):
    """A rectangle on one PDF page, in PDF points from the page's top-left corner."""

    page: int = Field(ge=1)
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class SourceLocation(_Record):
    """A place in the manuscript source, as SyncTeX recorded it."""

    file: str
    line: int = Field(ge=1)
    column: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, slots=True)
class _Node:
    """One positioned record: which source line produced which box on which page."""

    tag: int
    line: int
    column: int | None
    page: int
    x: int
    y: int
    width: int
    height: int
    depth: int
    box: bool


class SynctexIndex:
    """In-memory SyncTeX map for one build, or the reason there isn't one."""

    def __init__(
        self,
        *,
        unavailable: SynctexUnavailable | None = None,
        files: dict[int, str] | None = None,
        nodes: Iterable[_Node] = (),
        unit: float = 1.0,
        x_offset: float = 0.0,
        y_offset: float = 0.0,
    ) -> None:
        self._unavailable = unavailable
        self._files = dict(files or {})
        self._nodes = tuple(nodes)
        self._unit = unit
        self._x_offset = x_offset
        self._y_offset = y_offset
        self._by_tag: dict[int, list[_Node]] = {}
        self._by_page: dict[int, list[_Node]] = {}
        for node in self._nodes:
            self._by_tag.setdefault(node.tag, []).append(node)
            self._by_page.setdefault(node.page, []).append(node)

    # -- construction --------------------------------------------------------

    @classmethod
    def load(
        cls, path: Path | str | None, *, source_root: Path | str | None = None
    ) -> SynctexIndex:
        """Read a `.synctex` or `.synctex.gz` file, never raising for a bad one.

        ``source_root`` rewrites the absolute paths engines record into paths relative to
        the manuscript directory, so a caller can ask for `sections/intro.tex` and get an
        answer whatever the compile's working directory was.
        """
        if path is None:
            return cls.unavailable(
                SynctexUnavailableReason.NOT_REQUESTED,
                "this build did not request SyncTeX data",
            )
        target = Path(path)
        if not target.is_file():
            return cls.unavailable(
                SynctexUnavailableReason.MISSING_FILE,
                f"no SyncTeX file at {target.name}; the engine produced none",
            )
        try:
            text = _read_text(target)
        except (OSError, gzip.BadGzipFile, EOFError, UnicodeDecodeError) as error:
            return cls.unavailable(
                SynctexUnavailableReason.UNREADABLE, f"cannot read {target.name}: {error}"
            )
        return cls.parse(text, source_root=source_root)

    @classmethod
    def parse(cls, text: str, *, source_root: Path | str | None = None) -> SynctexIndex:
        """Parse SyncTeX text; unknown or truncated content becomes an unavailable state."""
        return _Parser(text, source_root=source_root).build()

    @classmethod
    def unavailable(cls, reason: SynctexUnavailableReason, detail: str) -> SynctexIndex:
        """An index that answers nothing and says why."""
        return cls(unavailable=SynctexUnavailable(reason=reason, detail=detail))

    # -- state ---------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._unavailable is None

    @property
    def state(self) -> SynctexUnavailable | None:
        """The reason there is no mapping, or ``None`` when there is one."""
        return self._unavailable

    @property
    def files(self) -> tuple[str, ...]:
        """Source files the map knows about, as normalized relative POSIX paths."""
        return tuple(sorted(set(self._files.values())))

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(sorted(self._by_page))

    def __repr__(self) -> str:
        if self._unavailable is not None:
            return f"SynctexIndex(unavailable={self._unavailable.reason.value!r})"
        return f"SynctexIndex(files={len(self.files)}, pages={len(self._by_page)})"

    # -- lookups -------------------------------------------------------------

    def forward(self, file: str, line: int) -> tuple[PdfLocation, ...]:
        """PDF rectangles produced by ``file:line``, nearest matching line if it is empty.

        A source line that produced nothing of its own — a blank line, a comment, the line
        after a paragraph break — resolves to the closest line that did, which is what a
        reader means by "show me where I am".
        """
        self._require()
        tags = self._tags_for(file)
        if not tags:
            return ()
        candidates = [node for tag in tags for node in self._by_tag.get(tag, ())]
        target = _nearest_line(candidates, line)
        if target is None:
            return ()
        matches = [node for node in candidates if node.line == target]
        boxes = [node for node in matches if node.box and node.width > 0] or matches
        located = {self._to_pdf(node) for node in boxes}
        ordered = sorted(located, key=lambda item: (item.page, item.y, item.x))
        return tuple(ordered[:MAX_FORWARD_LOCATIONS])

    def inverse(self, page: int, x: float, y: float) -> SourceLocation | None:
        """The source line behind a point on a page, in PDF points from the top-left.

        A point inside several boxes belongs to the innermost one, so clicking a word in a
        paragraph lands on the word's line rather than the enclosing page body.
        """
        self._require()
        nodes = self._by_page.get(page)
        if not nodes:
            return None
        containing = [node for node in nodes if _contains(self._to_pdf(node), x, y)]
        chosen = (
            min(containing, key=lambda node: _area(self._to_pdf(node)))
            if containing
            else min(nodes, key=lambda node: _distance(self._to_pdf(node), x, y))
        )
        name = self._files.get(chosen.tag)
        if name is None or chosen.line < 1:
            return None
        return SourceLocation(file=name, line=chosen.line, column=chosen.column)

    # -- internals -----------------------------------------------------------

    def _require(self) -> None:
        if self._unavailable is not None:
            raise SynctexUnavailableError(self._unavailable)

    def _tags_for(self, file: str) -> tuple[int, ...]:
        wanted = _normalize_name(file)
        alternatives = {wanted}
        if not PurePosixPath(wanted).suffix:
            alternatives.add(f"{wanted}.tex")
        exact = tuple(tag for tag, name in self._files.items() if name in alternatives)
        if exact:
            return exact
        suffixed = tuple(
            tag
            for tag, name in self._files.items()
            if any(name.endswith(f"/{item}") or item.endswith(f"/{name}") for item in alternatives)
        )
        if suffixed:
            return suffixed
        bases = {PurePosixPath(item).name for item in alternatives}
        return tuple(tag for tag, name in self._files.items() if PurePosixPath(name).name in bases)

    def _to_pdf(self, node: _Node) -> PdfLocation:
        height = node.height * self._unit
        depth = node.depth * self._unit
        baseline = node.y * self._unit + self._y_offset
        return PdfLocation(
            page=node.page,
            x=node.x * self._unit + self._x_offset,
            y=baseline - height,
            width=max(node.width * self._unit, 0.0),
            height=max(height + depth, 0.0),
        )


# --------------------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------------------


class _Parser:
    """Reads the preamble, then the sheet records, in one pass over the text."""

    def __init__(self, text: str, *, source_root: Path | str | None) -> None:
        self._text = text
        self._root = _normalize_root(source_root)
        self._files: dict[int, str] = {}
        self._nodes: list[_Node] = []
        self._pre_unit = 1.0
        self._magnification = 1000.0
        self._pre_x_offset = 0.0
        self._pre_y_offset = 0.0

    def build(self) -> SynctexIndex:
        lines = self._text.splitlines()
        if not lines or not lines[0].startswith("SyncTeX Version:"):
            return SynctexIndex.unavailable(
                SynctexUnavailableReason.UNSUPPORTED_FORMAT,
                "the file does not start with a SyncTeX version header",
            )
        content_at = self._read_preamble(lines)
        if content_at is None:
            return SynctexIndex.unavailable(
                SynctexUnavailableReason.UNSUPPORTED_FORMAT,
                "the file has no Content: section, so the run was interrupted",
            )
        self._read_content(lines[content_at:])
        if not self._nodes:
            return SynctexIndex.unavailable(
                SynctexUnavailableReason.NO_RECORDS,
                "the SyncTeX file records no positions for any source line",
            )
        unit = self._pre_unit * (self._magnification / 1000.0) / SP_PER_PDF_POINT
        return SynctexIndex(
            files=self._files,
            nodes=self._nodes,
            unit=unit,
            x_offset=self._pre_x_offset * unit,
            y_offset=self._pre_y_offset * unit,
        )

    def _read_preamble(self, lines: list[str]) -> int | None:
        for index, line in enumerate(lines):
            if line.startswith("Content:"):
                return index + 1
            self._read_header(line)
        return None

    def _read_header(self, line: str) -> None:
        if line.startswith("Input:"):
            self._read_input(line)
        elif line.startswith("Magnification:"):
            self._magnification = _number(line.partition(":")[2], self._magnification)
        elif line.startswith("Unit:"):
            self._pre_unit = _number(line.partition(":")[2], self._pre_unit)
        elif line.startswith("X Offset:"):
            self._pre_x_offset = _number(line.partition(":")[2], self._pre_x_offset)
        elif line.startswith("Y Offset:"):
            self._pre_y_offset = _number(line.partition(":")[2], self._pre_y_offset)

    def _read_input(self, line: str) -> None:
        _, _, rest = line.partition(":")
        tag_text, _, name = rest.partition(":")
        if not name.strip():
            return
        try:
            tag = int(tag_text)
        except ValueError:
            return
        self._files[tag] = _relative_to(name.strip(), self._root)

    def _read_content(self, lines: list[str]) -> None:
        pages: list[int] = []
        for line in lines:
            if not line:
                continue
            head = line[0]
            if head == "{" or head == "<":
                page = _integer(line[1:])
                pages.append(page if page is not None and page >= 1 else 1)
                continue
            if head == "}" or head == ">":
                if pages:
                    pages.pop()
                continue
            if head == "!" or line.startswith(("Input:", "Postamble:", "Count:", "Post scriptum")):
                if line.startswith("Input:"):
                    self._read_input(line)
                continue
            if not pages:
                continue
            match = _RECORD_RE.match(line)
            if match is not None:
                self._nodes.append(_node_from(match, pages[-1]))


def _node_from(match: re.Match[str], page: int) -> _Node:
    column = match.group("column")
    parsed = int(column) if column is not None else -1
    return _Node(
        tag=int(match.group("tag")),
        line=int(match.group("line")),
        column=parsed if parsed >= 0 else None,
        page=page,
        x=int(match.group("x")),
        y=int(match.group("y")),
        width=abs(int(match.group("width") or 0)),
        height=int(match.group("height") or 0),
        depth=int(match.group("depth") or 0),
        box=match.group("kind") in _BOX_KINDS,
    )


def _read_text(path: Path) -> str:
    with path.open("rb") as handle:
        head = handle.read(2)
    if head == _GZIP_MAGIC:
        with gzip.open(path, "rb") as stream:
            raw = stream.read()
    else:
        raw = path.read_bytes()
    return raw.decode("utf-8", errors="replace")


def _normalize_root(source_root: Path | str | None) -> str | None:
    if source_root is None:
        return None
    candidate = Path(source_root)
    portable = candidate.as_posix()
    if portable.startswith("/") and not candidate.is_absolute():
        # A recorded POSIX root remains meaningful when its fixture is parsed on Windows;
        # resolving it there would silently attach the current drive.
        return portable.rstrip("/")
    try:
        return candidate.resolve().as_posix()
    except OSError:  # pragma: no cover - unresolvable root
        return portable


def _relative_to(name: str, root: str | None) -> str:
    """Normalize a recorded input path, making it relative to the project root if possible."""
    cleaned = name.replace("\\", "/").strip()
    prefix = f"{root}/" if root is not None else None
    if prefix is not None and cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix) :]
    return _normalize_name(cleaned)


def _normalize_name(name: str) -> str:
    cleaned = name.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _nearest_line(nodes: Iterable[_Node], line: int) -> int | None:
    """The recorded line to answer with: the one asked for, else the closest below, else above."""
    recorded = sorted({node.line for node in nodes if node.line >= 1})
    if not recorded:
        return None
    if line in recorded:
        return line
    after = [item for item in recorded if item > line]
    if after:
        return after[0]
    return recorded[-1]


def _contains(box: PdfLocation, x: float, y: float) -> bool:
    return box.x <= x <= box.x + box.width and box.y <= y <= box.y + box.height


def _area(box: PdfLocation) -> float:
    return max(box.width, 1e-6) * max(box.height, 1e-6)


def _distance(box: PdfLocation, x: float, y: float) -> float:
    dx = max(box.x - x, 0.0, x - (box.x + box.width))
    dy = max(box.y - y, 0.0, y - (box.y + box.height))
    return dx * dx + dy * dy


def _number(text: str, fallback: float) -> float:
    try:
        return float(text.strip())
    except ValueError:
        return fallback


def _integer(text: str) -> int | None:
    try:
        return int(text.strip())
    except ValueError:
        return None
