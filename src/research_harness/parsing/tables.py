"""Flattened table text and cell -> character-span mapping (Product 12, 16).

A table is one block so an anchor keeps pointing at a table, not at a cell that a later
parser numbers differently. Row/column provenance survives because the block keeps its
`TableCell`s and because every cell's position in the flattened text is recomputable.
"""

from __future__ import annotations

from research_harness.domain.document import DocumentBlock, TableCell
from research_harness.domain.enums import DocumentBlockKind
from research_harness.parsing.base import ParseError

__all__ = [
    "CELL_SEPARATOR",
    "ROW_SEPARATOR",
    "cell_span",
    "cell_text",
    "column_headers",
    "find_cell",
    "flatten_cells",
    "row_label",
]

CELL_SEPARATOR = " | "
ROW_SEPARATOR = "\n"


def _ordered(cells: tuple[TableCell, ...]) -> list[list[TableCell]]:
    """Cells grouped into rows, rows and columns in ascending coordinate order."""
    rows: dict[int, list[TableCell]] = {}
    for cell in cells:
        rows.setdefault(cell.row, []).append(cell)
    return [sorted(rows[index], key=lambda cell: cell.col) for index in sorted(rows)]


def flatten_cells(cells: tuple[TableCell, ...]) -> str:
    """Table text as ``a | b`` rows joined by newlines, in row-major order."""
    return ROW_SEPARATOR.join(
        CELL_SEPARATOR.join(cell.text for cell in row) for row in _ordered(cells)
    )


def _require_table(block: DocumentBlock) -> None:
    if block.kind is not DocumentBlockKind.TABLE:
        raise ParseError(f"block {block.id} is a {block.kind.value}, not a table")


def find_cell(block: DocumentBlock, row: int, col: int) -> TableCell | None:
    """The cell at ``(row, col)``, or None when the table has no such cell."""
    _require_table(block)
    for cell in block.cells:
        if cell.row == row and cell.col == col:
            return cell
    return None


def cell_text(block: DocumentBlock, row: int, col: int) -> str:
    """Text of the cell at ``(row, col)``; raises `ParseError` when it does not exist."""
    cell = find_cell(block, row, col)
    if cell is None:
        raise ParseError(f"table block {block.id} has no cell at row {row}, column {col}")
    return cell.text


def cell_span(block: DocumentBlock, row: int, col: int) -> tuple[int, int]:
    """Character offsets of one cell inside the table block's flattened text.

    This is how numeric evidence keeps table/row/column provenance: the anchor points at
    the table block and at the exact characters of the measured value.
    """
    _require_table(block)
    offset = 0
    for row_cells in _ordered(block.cells):
        for position, cell in enumerate(row_cells):
            if position:
                offset += len(CELL_SEPARATOR)
            if cell.row == row and cell.col == col:
                return offset, offset + len(cell.text)
            offset += len(cell.text)
        offset += len(ROW_SEPARATOR)
    raise ParseError(f"table block {block.id} has no cell at row {row}, column {col}")


def column_headers(block: DocumentBlock) -> tuple[str, ...]:
    """Header row (row 0) of the table, left to right; empty when the table has no cells."""
    _require_table(block)
    rows = _ordered(block.cells)
    return tuple(cell.text for cell in rows[0]) if rows else ()


def row_label(block: DocumentBlock, row: int) -> str:
    """Leftmost cell of ``row``, the label numeric evidence records as `source_row`."""
    _require_table(block)
    for row_cells in _ordered(block.cells):
        if row_cells and row_cells[0].row == row:
            return row_cells[0].text
    raise ParseError(f"table block {block.id} has no row {row}")
