"""A dependency-free BibTeX reader, good enough to decide whether a citation key exists.

The manuscript layer only needs identity and fields (Product 30.2), never rendering, so
this reads the file structure - entries, ``@string`` macros, ``@preamble``, ``@comment``,
brace and quote delimited values, and ``#`` concatenation - and leaves LaTeX markup inside
field values exactly as the author wrote it.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from research_harness.domain.errors import ResearchHarnessError

__all__ = [
    "MONTH_MACROS",
    "BibDatabase",
    "BibEntry",
    "BibtexError",
    "parse_bibtex",
    "parse_bibtex_file",
]

MONTH_MACROS: dict[str, str] = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "may": "May",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}
"""Built-in month abbreviations, defined by every standard style without an ``@string``."""

_CLOSERS = {"{": "}", "(": ")"}
_TYPE_RE = re.compile(r"[A-Za-z]+")
_NAME_RE = re.compile(r"[^\s=,{}()\"#]+")


class BibtexError(ResearchHarnessError):
    """Malformed BibTeX. Carries the 1-based source line so the author can find it."""

    def __init__(self, reason: str, line: int) -> None:
        super().__init__(f"line {line}: {reason}")
        self.reason = reason
        self.line = line


class BibEntry(BaseModel):
    """One bibliography entry. ``entry_type`` and field names are lowercased; values are not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    entry_type: str
    fields: dict[str, str] = {}
    line: int = 1

    def field(self, name: str) -> str | None:
        """Field value by case-insensitive name, or ``None``."""
        return self.fields.get(name.lower())


class BibDatabase(BaseModel):
    """Parsed bibliography: entries by key, plus the macros and warnings found on the way."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: dict[str, BibEntry] = {}
    strings: dict[str, str] = {}
    preambles: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.entries

    def get(self, key: str) -> BibEntry | None:
        """The entry for ``key``, or ``None``. Keys match exactly, as BibTeX writes them."""
        return self.entries.get(key)

    def keys(self) -> tuple[str, ...]:
        """Entry keys in file order."""
        return tuple(self.entries)


def parse_bibtex(text: str) -> BibDatabase:
    """Parse a BibTeX database. Raises :class:`BibtexError` with a line number if malformed.

    Recoverable problems - a duplicate key, an undefined macro, a stray ``@`` - become
    warnings, because a bibliography with one bad entry should still answer questions about
    its good ones.
    """
    return _Parser(text).parse()


def parse_bibtex_file(path: Path) -> BibDatabase:
    """Parse the UTF-8 BibTeX file at ``path``."""
    return parse_bibtex(Path(path).read_text(encoding="utf-8"))


class _Parser:
    """A single left-to-right pass; ``pos`` is always an offset into the original text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.entries: dict[str, BibEntry] = {}
        self.strings: dict[str, str] = {}
        self.preambles: list[str] = []
        self.warnings: list[str] = []

    # -- driver --------------------------------------------------------------

    def parse(self) -> BibDatabase:
        while True:
            at = self.text.find("@", self.pos)
            if at == -1:
                break
            self.pos = at + 1
            self._skip_space()
            match = _TYPE_RE.match(self.text, self.pos)
            if match is None:
                self.warnings.append(f"line {self._line(at)}: stray '@' outside an entry")
                continue
            self.pos = match.end()
            self._object(match.group(0).lower(), at)
        return BibDatabase(
            entries=self.entries,
            strings=self.strings,
            preambles=tuple(self.preambles),
            warnings=tuple(self.warnings),
        )

    def _object(self, entry_type: str, at: int) -> None:
        if entry_type == "comment":
            self._comment()
            return
        closer = self._open()
        if entry_type == "preamble":
            self.preambles.append(self._value())
            self._expect(closer)
            return
        if entry_type == "string":
            self._string(closer)
            return
        self._entry(entry_type, closer, self._line(at))

    # -- objects -------------------------------------------------------------

    def _comment(self) -> None:
        self._skip_space()
        if self.pos < len(self.text) and self.text[self.pos] in _CLOSERS:
            closer = self._open()
            self._skip_balanced(closer)
            return
        end = self.text.find("\n", self.pos)
        self.pos = len(self.text) if end == -1 else end

    def _string(self, closer: str) -> None:
        name = self._name("a macro name")
        self._skip_space()
        self._expect("=")
        self.strings[name.lower()] = self._value()
        self._skip_space()
        if self._peek() == ",":
            self.pos += 1
        self._expect(closer)

    def _entry(self, entry_type: str, closer: str, line: int) -> None:
        key = self._key(closer)
        fields: dict[str, str] = {}
        while True:
            self._skip_space()
            char = self._peek()
            if char is None:
                raise BibtexError(f"unterminated entry {key!r}", self._line())
            if char == closer:
                self.pos += 1
                break
            name = self._name("a field name").lower()
            self._skip_space()
            self._expect("=")
            if name in fields:
                self.warnings.append(
                    f"line {self._line()}: duplicate field {name!r} in entry {key!r}; "
                    f"keeping the first"
                )
                self._value()
            else:
                fields[name] = self._value()
            self._skip_space()
            if self._peek() == ",":
                self.pos += 1
        if key in self.entries:
            self.warnings.append(
                f"line {line}: duplicate entry key {key!r} "
                f"(first defined on line {self.entries[key].line}); keeping the first"
            )
            return
        self.entries[key] = BibEntry(key=key, entry_type=entry_type, fields=fields, line=line)

    def _key(self, closer: str) -> str:
        self._skip_space()
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in f",{closer} \t\r\n":
            self.pos += 1
        key = self.text[start : self.pos]
        if not key:
            raise BibtexError("entry has no citation key", self._line())
        self._skip_space()
        char = self._peek()
        if char == ",":
            self.pos += 1
        elif char != closer:
            raise BibtexError(f"expected ',' after the key {key!r}", self._line())
        return key

    # -- values --------------------------------------------------------------

    def _value(self) -> str:
        parts: list[str] = []
        while True:
            self._skip_space()
            char = self._peek()
            if char == "{":
                parts.append(self._braced())
            elif char == '"':
                parts.append(self._quoted())
            elif char is not None and (char.isalnum() or char in "._-+"):
                parts.append(self._macro(self._name("a value")))
            else:
                raise BibtexError("expected a field value", self._line())
            self._skip_space()
            if self._peek() != "#":
                break
            self.pos += 1
        return " ".join("".join(parts).split())

    def _braced(self) -> str:
        start = self.pos
        self.pos += 1
        depth = 1
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "\\":
                self.pos += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    inner = self.text[start + 1 : self.pos]
                    self.pos += 1
                    return inner
            self.pos += 1
        raise BibtexError("unterminated '{' in a field value", self._line(start))

    def _quoted(self) -> str:
        start = self.pos
        self.pos += 1
        depth = 0
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "\\":
                self.pos += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
            elif char == '"' and depth == 0:
                inner = self.text[start + 1 : self.pos]
                self.pos += 1
                return inner
            self.pos += 1
        raise BibtexError("unterminated '\"' in a field value", self._line(start))

    def _macro(self, name: str) -> str:
        if name.isdigit():
            return name
        lowered = name.lower()
        if lowered in self.strings:
            return self.strings[lowered]
        if lowered in MONTH_MACROS:
            return MONTH_MACROS[lowered]
        self.warnings.append(
            f"line {self._line()}: undefined macro {name!r}; using the macro name verbatim"
        )
        return name

    # -- primitives ----------------------------------------------------------

    def _open(self) -> str:
        self._skip_space()
        char = self._peek()
        if char not in _CLOSERS:
            raise BibtexError("expected '{' or '(' after the entry type", self._line())
        self.pos += 1
        return _CLOSERS[char]

    def _skip_balanced(self, closer: str) -> None:
        opener = "{" if closer == "}" else "("
        depth = 1
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == "\\":
                self.pos += 1
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return
        raise BibtexError(f"unterminated '{opener}' in @comment", self._line())

    def _name(self, what: str) -> str:
        self._skip_space()
        match = _NAME_RE.match(self.text, self.pos)
        if match is None:
            raise BibtexError(f"expected {what}", self._line())
        self.pos = match.end()
        return match.group(0)

    def _expect(self, char: str) -> None:
        self._skip_space()
        if self._peek() != char:
            raise BibtexError(f"expected {char!r}", self._line())
        self.pos += 1

    def _peek(self) -> str | None:
        return self.text[self.pos] if self.pos < len(self.text) else None

    def _skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _line(self, pos: int | None = None) -> int:
        return self.text.count("\n", 0, self.pos if pos is None else pos) + 1
