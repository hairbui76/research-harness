"""LaTeX manuscript model: the file graph, a sentence stream, and stable fingerprints.

The manuscript is downstream of the accepted research graph (Product 30), so the parser's
job is to produce sentences that can be anchored to Claims and re-found after an edit. It
is deliberately a *reader*: it never rewrites the manuscript, and an unresolvable
``\\input`` is a recorded warning rather than a failure, because a partially resolvable
project still yields anchorable text.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.base import Sha256
from research_harness.domain.errors import ResearchHarnessError
from research_harness.manuscript.protected import (
    CITATION_RE,
    ProtectedSpan,
    find_protected_spans,
)

__all__ = [
    "BLOCK_ENVIRONMENTS",
    "SENTENCE_ABBREVIATIONS",
    "Block",
    "BlockKind",
    "Heading",
    "LatexError",
    "LatexFile",
    "LatexProject",
    "Sentence",
    "citation_keys",
    "mask_comments",
    "normalize_sentence",
    "sentence_fingerprint",
    "strip_comments",
]


class LatexError(ResearchHarnessError):
    """A LaTeX project could not be read at all (the main file is missing or unreadable)."""


# --------------------------------------------------------------------------------------
# vocabularies
# --------------------------------------------------------------------------------------


class BlockKind(StrEnum):
    """Kinds of non-sentence material excluded from the sentence stream."""

    EQUATION = "equation"
    DISPLAY_MATH = "display_math"
    FIGURE = "figure"
    TABLE = "table"
    TABULAR = "tabular"
    VERBATIM = "verbatim"
    LISTING = "listing"


BLOCK_ENVIRONMENTS: dict[str, BlockKind] = {
    "align": BlockKind.EQUATION,
    "eqnarray": BlockKind.EQUATION,
    "equation": BlockKind.EQUATION,
    "gather": BlockKind.EQUATION,
    "multline": BlockKind.EQUATION,
    "displaymath": BlockKind.DISPLAY_MATH,
    "figure": BlockKind.FIGURE,
    "table": BlockKind.TABLE,
    "array": BlockKind.TABULAR,
    "tabular": BlockKind.TABULAR,
    "tabularx": BlockKind.TABULAR,
    "verbatim": BlockKind.VERBATIM,
    "lstlisting": BlockKind.LISTING,
    "minted": BlockKind.LISTING,
}
"""Environments whose body is never prose. A trailing ``*`` is ignored when matching."""

SENTENCE_ABBREVIATIONS: tuple[str, ...] = (
    "e.g.",
    "i.e.",
    "et al.",
    "al.",
    "approx.",
    "cf.",
    "ca.",
    "dr.",
    "eq.",
    "eqs.",
    "fig.",
    "figs.",
    "no.",
    "prof.",
    "ref.",
    "refs.",
    "resp.",
    "sec.",
    "tab.",
    "viz.",
    "vs.",
)
"""Compared case-insensitively against the text ending at a candidate ``.``."""

_SECTION_LEVELS: dict[str, int] = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
}

_INLINE_SKIP_WITH_GROUP = frozenset({"hspace", "index", "label", "nocite", "vspace"})
"""Invisible markup: skipped without ending the surrounding sentence."""

_BLOCK_SKIP = frozenset(
    {
        "appendix",
        "bigskip",
        "centering",
        "clearpage",
        "hline",
        "item",
        "linebreak",
        "maketitle",
        "medskip",
        "midrule",
        "newline",
        "newpage",
        "noindent",
        "pagebreak",
        "par",
        "printbibliography",
        "smallskip",
        "tableofcontents",
        "toprule",
        "bottomrule",
    }
)

_BLOCK_SKIP_WITH_GROUP = frozenset(
    {
        "addbibresource",
        "author",
        "bibliography",
        "bibliographystyle",
        "date",
        "documentclass",
        "title",
        "usepackage",
    }
)

_STYLE_WRAPPERS = (
    "emph",
    "textbf",
    "textit",
    "textrm",
    "textsc",
    "textsf",
    "texttt",
    "underline",
    "mbox",
    "text",
)

_TERMINATORS = ".?!"
_CLOSERS = ")]'\"\u201d\u2019"
_SENTENCE_STARTERS = '\\$`"([\u201c'

_BEGIN_RE = re.compile(r"\\begin\s*\{([^{}]*)\}")
_END_RE = re.compile(r"\\end\s*\{([^{}]*)\}")
_INCLUDE_RE = re.compile(r"\\(input|include)\s*\{([^{}]*)\}")
_SECTION_RE = re.compile(rf"\\({'|'.join(_SECTION_LEVELS)})\*?\s*(?:\[[^\[\]]*\])?\s*\{{")
_COMMAND_RE = re.compile(r"\\([A-Za-z]+)\*?|\\.", re.DOTALL)
_OPTIONAL_ARGS_RE = re.compile(r"\s*(?:\[[^\[\]]*\])*\s*")
_STYLE_WRAPPER_RE = re.compile(rf"\\(?:{'|'.join(_STYLE_WRAPPERS)})\s*\{{([^{{}}]*)\}}")
_DROPPED_RE = re.compile(r"\\(?:label|index|nocite)\s*\{[^{}]*\}")
_UNESCAPE_RE = re.compile(r"\\([%&#_])")
#: Removing a citation command leaves a gap before its punctuation; close it.
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?)\]])")
_DOCUMENT_BEGIN_RE = re.compile(r"\\begin\s*\{document\}")
_DOCUMENT_END_RE = re.compile(r"\\end\s*\{document\}")


# --------------------------------------------------------------------------------------
# text normalization
# --------------------------------------------------------------------------------------


def _comment_spans(text: str) -> list[tuple[int, int]]:
    """Half-open spans of ``%`` comments (excluding the newline); ``\\%`` is not one."""
    spans: list[tuple[int, int]] = []
    index = 0
    size = len(text)
    while index < size:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "%":
            end = text.find("\n", index)
            end = size if end == -1 else end
            spans.append((index, end))
            index = end
            continue
        index += 1
    return spans


def mask_comments(text: str) -> str:
    """Blank every comment body to spaces, keeping length so offsets still index ``text``."""
    if "%" not in text:
        return text
    characters = list(text)
    for start, end in _comment_spans(text):
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def strip_comments(text: str) -> str:
    """Remove comment bodies outright; for callers holding raw LaTeX, not file offsets."""
    if "%" not in text:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in _comment_spans(text):
        out.append(text[cursor:start])
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def normalize_sentence(text: str) -> str:
    """Reduce a sentence to the form whose hash identifies it across cosmetic edits.

    Citation commands are removed (their keys are tracked separately), invisible markup is
    dropped, font wrappers are unwrapped, ``--``/``---`` become dashes, ``\\%`` and friends
    are unescaped, and whitespace collapses. Math, numbers, and units survive verbatim
    because they are exactly what a style pass must not change (Product 30.4).

    The function expects comment-free text - :attr:`Sentence.text` already is, and
    :func:`strip_comments` makes raw source so. It is idempotent, so re-hashing a stored
    normalized sentence yields the same fingerprint.
    """
    out = CITATION_RE.sub(" ", text)
    out = _DROPPED_RE.sub(" ", out)
    for _ in range(4):
        unwrapped = _STYLE_WRAPPER_RE.sub(r"\1", out)
        if unwrapped == out:
            break
        out = unwrapped
    out = out.replace("---", "\u2014").replace("--", "\u2013")
    out = _UNESCAPE_RE.sub(r"\1", out)
    out = out.replace("~", " ")
    out = " ".join(out.split())
    return _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", out)


def sentence_fingerprint(text: str) -> Sha256:
    """``sha256:<hex>`` over :func:`normalize_sentence` of ``text``; the anchor identity."""
    digest = hashlib.sha256(normalize_sentence(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def citation_keys(text: str) -> tuple[str, ...]:
    """Citation keys cited in ``text``, in order of first appearance, deduplicated."""
    keys: list[str] = []
    for match in CITATION_RE.finditer(text):
        for raw in match.group(1).split(","):
            key = raw.strip()
            if key and key not in keys:
                keys.append(key)
    return tuple(keys)


# --------------------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------------------


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LatexFile(_Record):
    """One source file of the project; ``path`` is POSIX-relative to the project root."""

    path: str
    text: str
    lines: tuple[str, ...]


class Block(_Record):
    """Non-sentence material (math, floats, tabular, verbatim) excluded from the stream."""

    kind: BlockKind
    environment: str
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    text: str


class Heading(_Record):
    """A sectioning command; ``section_path`` ends with this heading's own title."""

    title: str
    level: int = Field(ge=0)
    file: str
    line: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    section_path: tuple[str, ...]


class Sentence(_Record):
    """One manuscript sentence, addressable by file, line range, and byte-exact offsets.

    ``text`` is the LaTeX source of the sentence with comment bodies blanked to spaces;
    ``file_text[char_start:char_end]`` returns the same span with its comments intact.
    """

    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    text: str
    normalized_text: str
    fingerprint: Sha256
    citation_keys: tuple[str, ...] = ()
    section_path: tuple[str, ...] = ()
    in_environment: str | None = None
    protected_spans: tuple[ProtectedSpan, ...] = ()


class _Segment(NamedTuple):
    """A contiguous slice of one file, in document order after include expansion."""

    file: str
    start: int
    end: int


class LatexProject(_Record):
    """A main file plus everything it includes, parsed into sentences, blocks, headings."""

    root: Path
    main: str
    files: tuple[LatexFile, ...] = ()
    sentences: tuple[Sentence, ...] = ()
    blocks: tuple[Block, ...] = ()
    headings: tuple[Heading, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def load(cls, main_tex: Path) -> LatexProject:
        """Read ``main_tex`` and every ``\\input``/``\\include`` reachable from its body.

        Include targets resolve relative to the main file's directory. A missing target, a
        target outside the project root, an include cycle, and a repeated include are all
        recorded in :attr:`warnings`; none of them stops the parse.
        """
        return _Loader(Path(main_tex)).build()

    def file(self, path: str) -> LatexFile | None:
        """The loaded file at ``path``, or ``None`` when the project does not contain it."""
        return next((item for item in self.files if item.path == path), None)

    def sentences_for_file(self, path: str) -> tuple[Sentence, ...]:
        """Sentences of one file, in ascending offset order."""
        return tuple(sentence for sentence in self.sentences if sentence.file == path)

    def cited_keys(self) -> tuple[str, ...]:
        """Every citation key used anywhere in the manuscript, in document order."""
        keys: list[str] = []
        for sentence in self.sentences:
            for key in sentence.citation_keys:
                if key not in keys:
                    keys.append(key)
        return tuple(keys)


# --------------------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------------------


class _Loader:
    """Reads the include graph and lays its bodies out in document order."""

    def __init__(self, main_tex: Path) -> None:
        self.main_path = main_tex
        self.root = main_tex.parent
        self.files: dict[str, LatexFile] = {}
        self.masked: dict[str, str] = {}
        self.segments: list[_Segment] = []
        self.warnings: list[str] = []
        self.active: list[str] = []

    def build(self) -> LatexProject:
        try:
            main = self._read(self.main_path)
        except OSError as error:
            raise LatexError(f"cannot read main LaTeX file {self.main_path}: {error}") from error
        main_rel = self._relative(self.main_path)
        self._register(main_rel, main)
        self.active.append(main_rel)
        self._expand(main_rel)
        self.active.pop()

        scanner = _Scanner(self.masked, self.files, self.warnings)
        scanner.run(self.segments)
        return LatexProject(
            root=self.root,
            main=main_rel,
            files=tuple(self.files.values()),
            sentences=tuple(scanner.sentences),
            blocks=tuple(scanner.blocks),
            headings=tuple(scanner.headings),
            warnings=tuple(self.warnings),
        )

    # -- file graph ----------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def _register(self, rel: str, text: str) -> None:
        self.files[rel] = LatexFile(path=rel, text=text, lines=tuple(text.splitlines()))
        self.masked[rel] = mask_comments(text)

    def _body_range(self, rel: str) -> tuple[int, int]:
        masked = self.masked[rel]
        begin = _DOCUMENT_BEGIN_RE.search(masked)
        start = begin.end() if begin else 0
        end_match = _DOCUMENT_END_RE.search(masked, start)
        return start, end_match.start() if end_match else len(masked)

    def _expand(self, rel: str) -> None:
        masked = self.masked[rel]
        start, end = self._body_range(rel)
        cursor = start
        for match in _INCLUDE_RE.finditer(masked, start, end):
            self.segments.append(_Segment(rel, cursor, match.start()))
            cursor = match.end()
            self._include(rel, match.group(2).strip(), masked, match.start())
        self.segments.append(_Segment(rel, cursor, end))

    def _include(self, parent: str, target: str, masked: str, offset: int) -> None:
        where = f"{parent}:{masked.count(chr(10), 0, offset) + 1}"
        if not target:
            self.warnings.append(f"{where}: empty include target")
            return
        name = target if target.endswith(".tex") else f"{target}.tex"
        path = self.root / name
        try:
            rel = self._relative(path)
        except ValueError:
            self.warnings.append(f"{where}: include target {target!r} escapes the project root")
            return
        if rel in self.active:
            self.warnings.append(f"{where}: include cycle at {rel!r}; skipped")
            return
        if rel in self.files:
            self.warnings.append(f"{where}: {rel!r} is already included; skipped")
            return
        try:
            text = self._read(path)
        except OSError:
            self.warnings.append(f"{where}: cannot read included file {rel!r}")
            return
        self._register(rel, text)
        self.active.append(rel)
        self._expand(rel)
        self.active.pop()


# --------------------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------------------


class _Scanner:
    """Turns include-expanded segments into sentences, blocks, and headings.

    Section and environment state carries across segments because ``\\input`` is a textual
    splice: a ``\\section`` in an included file governs the sentences that follow it.
    """

    def __init__(
        self,
        masked: dict[str, str],
        files: dict[str, LatexFile],
        warnings: list[str],
    ) -> None:
        self.masked = masked
        self.files = files
        self.warnings = warnings
        self.sentences: list[Sentence] = []
        self.blocks: list[Block] = []
        self.headings: list[Heading] = []
        self.line_starts: dict[str, tuple[int, ...]] = {
            path: _line_starts(item.text) for path, item in files.items()
        }
        self.sections: list[tuple[int, str]] = []
        self.environments: list[str] = []
        self._file = ""
        self._text = ""
        self._start: int | None = None
        self._depth = 0

    # -- driver --------------------------------------------------------------

    def run(self, segments: list[_Segment]) -> None:
        for segment in segments:
            if segment.end <= segment.start:
                continue
            self._file = segment.file
            self._text = self.masked[segment.file]
            self._start = None
            self._depth = 0
            self._scan(segment.start, segment.end)
            self._flush(segment.end)

    def _scan(self, begin: int, end: int) -> None:
        text = self._text
        index = begin
        while index < end:
            char = text[index]
            if char == "\\":
                index = self._command(index, end)
            elif char == "$":
                index = self._dollar(index, end)
            elif char == "{":
                self._open(index)
                self._depth += 1
                index += 1
            elif char == "}":
                self._depth = max(0, self._depth - 1)
                index += 1
            elif char.isspace():
                index = self._whitespace(index, end)
            elif char in _TERMINATORS:
                self._open(index)
                stop = self._boundary(index, end)
                if stop is None:
                    index += 1
                else:
                    self._flush(stop)
                    index = stop
            else:
                self._open(index)
                index += 1

    # -- handlers ------------------------------------------------------------

    def _command(self, index: int, end: int) -> int:
        text = self._text
        begin = _BEGIN_RE.match(text, index)
        if begin is not None:
            return self._begin_environment(begin, end)
        closing = _END_RE.match(text, index)
        if closing is not None:
            self._flush(index)
            name = closing.group(1).strip()
            if self.environments and self.environments[-1] == _base_environment(name):
                self.environments.pop()
            return closing.end()
        if text.startswith("\\[", index):
            return self._display_math(index, end, "\\[", "\\]")
        if text.startswith("\\(", index):
            self._open(index)
            return _find_after(text, "\\)", index + 2, end)
        heading = _SECTION_RE.match(text, index)
        if heading is not None:
            return self._heading(heading, end)
        command = _COMMAND_RE.match(text, index)
        if command is None:  # pragma: no cover - a lone trailing backslash
            self._open(index)
            return index + 1
        name = command.group(1) or ""
        if name in _INLINE_SKIP_WITH_GROUP:
            return _skip_arguments(text, command.end(), end)
        if name in _BLOCK_SKIP:
            self._flush(index)
            return command.end()
        if name in _BLOCK_SKIP_WITH_GROUP:
            self._flush(index)
            return _skip_arguments(text, command.end(), end)
        self._open(index)
        return command.end()

    def _begin_environment(self, match: re.Match[str], end: int) -> int:
        name = match.group(1).strip()
        base = _base_environment(name)
        self._flush(match.start())
        kind = BLOCK_ENVIRONMENTS.get(base)
        if kind is None:
            if base != "document":
                self.environments.append(base)
            return match.end()
        stop = _environment_end(self._text, match.start(), name, end)
        if stop is None:
            self.warnings.append(
                f"{self._file}:{self._line(match.start())}: unterminated environment {name!r}"
            )
            stop = end
        self._add_block(kind, name, match.start(), stop)
        return stop

    def _display_math(self, index: int, end: int, opener: str, closer: str) -> int:
        self._flush(index)
        stop = _find_after(self._text, closer, index + len(opener), end)
        self._add_block(BlockKind.DISPLAY_MATH, opener, index, stop)
        return stop

    def _dollar(self, index: int, end: int) -> int:
        if self._text.startswith("$$", index):
            return self._display_math(index, end, "$$", "$$")
        self._open(index)
        cursor = index + 1
        while cursor < end:
            if self._text[cursor] == "\\":
                cursor += 2
                continue
            if self._text[cursor] == "$":
                return cursor + 1
            cursor += 1
        return end

    def _heading(self, match: re.Match[str], end: int) -> int:
        self._flush(match.start())
        title_start = match.end()
        title_end = _group_end(self._text, title_start, end)
        title = normalize_sentence(self._text[title_start : title_end - 1])
        level = _SECTION_LEVELS[match.group(1)]
        while self.sections and self.sections[-1][0] >= level:
            self.sections.pop()
        self.sections.append((level, title))
        self.headings.append(
            Heading(
                title=title,
                level=level,
                file=self._file,
                line=self._line(match.start()),
                char_start=match.start(),
                char_end=title_end,
                section_path=self._section_path(),
            )
        )
        return title_end

    def _whitespace(self, index: int, end: int) -> int:
        cursor = index
        text = self._text
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if self._start is not None and _has_blank_line(self.files[self._file].text, index, cursor):
            self._flush(index)
        return cursor

    # -- sentence bookkeeping ------------------------------------------------

    def _open(self, index: int) -> None:
        if self._start is None:
            self._start = index

    def _flush(self, end: int) -> None:
        start = self._start
        self._start = None
        if start is None or end <= start:
            return
        raw = self._text[start:end].rstrip()
        if not raw:
            return
        normalized = normalize_sentence(raw)
        if not normalized:
            return
        stop = start + len(raw)
        self.sentences.append(
            Sentence(
                file=self._file,
                line_start=self._line(start),
                line_end=self._line(stop - 1),
                char_start=start,
                char_end=stop,
                text=raw,
                normalized_text=normalized,
                fingerprint=sentence_fingerprint(normalized),
                citation_keys=citation_keys(raw),
                section_path=self._section_path(),
                in_environment=self.environments[-1] if self.environments else None,
                protected_spans=find_protected_spans(raw),
            )
        )

    def _boundary(self, index: int, end: int) -> int | None:
        """Offset just past a sentence-ending ``.``/``?``/``!``, or ``None``."""
        text = self._text
        if self._depth > 0:
            return None
        if text[index] == ".":
            after = text[index + 1] if index + 1 < end else ""
            if index and text[index - 1].isdigit() and after.isdigit():
                return None
            window = text[max(0, index - 16) : index + 1].lower()
            if any(window.endswith(abbreviation) for abbreviation in SENTENCE_ABBREVIATIONS):
                return None
        stop = index + 1
        while stop < end and text[stop] in _CLOSERS:
            stop += 1
        if stop >= end:
            return stop
        if not text[stop].isspace():
            return None
        cursor = stop
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if cursor >= end or "\n" in text[stop:cursor]:
            return stop
        following = text[cursor]
        if following.isupper() or following.isdigit() or following in _SENTENCE_STARTERS:
            return stop
        return None

    def _add_block(self, kind: BlockKind, environment: str, start: int, stop: int) -> None:
        self.blocks.append(
            Block(
                kind=kind,
                environment=environment,
                file=self._file,
                line_start=self._line(start),
                line_end=self._line(max(start, stop - 1)),
                char_start=start,
                char_end=stop,
                text=self._text[start:stop],
            )
        )
        self._nested_blocks(start + 1, stop)

    def _nested_blocks(self, begin: int, end: int) -> None:
        """Record block environments nested inside a block, e.g. a ``tabular`` in a float."""
        cursor = begin
        while True:
            match = _BEGIN_RE.search(self._text, cursor, end)
            if match is None:
                return
            name = match.group(1).strip()
            kind = BLOCK_ENVIRONMENTS.get(_base_environment(name))
            if kind is None:
                cursor = match.end()
                continue
            stop = _environment_end(self._text, match.start(), name, end) or end
            self._add_block(kind, name, match.start(), stop)
            cursor = max(stop, match.end())

    def _section_path(self) -> tuple[str, ...]:
        return tuple(title for _, title in self.sections if title)

    def _line(self, offset: int) -> int:
        return bisect_right(self.line_starts[self._file], offset)


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------


def _line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return tuple(starts)


def _base_environment(name: str) -> str:
    return name.rstrip("*")


def _find_after(text: str, closer: str, start: int, end: int) -> int:
    found = text.find(closer, start, end)
    return end if found == -1 else found + len(closer)


def _environment_end(text: str, start: int, name: str, end: int) -> int | None:
    pattern = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
    depth = 0
    for match in pattern.finditer(text, start, end):
        depth += 1 if match.group(1) == "begin" else -1
        if depth == 0:
            return match.end()
    return None


def _group_end(text: str, start: int, end: int) -> int:
    """Offset just past the ``}`` closing the group that starts at ``start``."""
    depth = 1
    cursor = start
    while cursor < end:
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    return end


def _skip_arguments(text: str, start: int, end: int) -> int:
    """Skip optional ``[...]`` arguments and at most one ``{...}`` group."""
    optional = _OPTIONAL_ARGS_RE.match(text, start, end)
    cursor = optional.end() if optional is not None else start
    if cursor < end and text[cursor] == "{":
        return _group_end(text, cursor + 1, end)
    return max(start, cursor)


def _has_blank_line(raw: str, start: int, end: int) -> bool:
    """True when the raw source between two content characters contains an empty line.

    Blankness is judged on the raw text, so adding a full-line ``%`` comment inside a
    sentence does not split it and does not change its fingerprint.
    """
    span = raw[start:end]
    first = span.find("\n")
    last = span.rfind("\n")
    if first == -1 or first == last:
        return False
    return any(not part.strip() for part in span[first + 1 : last].split("\n"))
