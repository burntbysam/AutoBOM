"""PHASE 6 workbook writer: five sheets, identical columns and formatting."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .classify import quantity_value
from .models import Part

COLUMNS = ("Qty", "Part #", "Thickness", "Size", "Fits Trumpf")
# PHASE 5 alignment, one entry per column above.
ALIGNMENTS = ("left", "center", "center", "center", "left")
COLUMN_WIDTHS = (10, 20, 12, 16, 13)

SHEET_ORDER = ("1-8", "3-16", "F Parts", "Other", "All")


def select_sheets(parts: list[Part]) -> dict[str, list[Part]]:
    """Route each part to its sheets per the SPEC's critical reminders.

    A part reaches "1-8" or "3-16" only when it is both that thickness and a
    Trumpf fit; anything F goes to "F Parts" and anything OTHER goes to
    "Other". Every part appears on "All".
    """
    return {
        "1-8": [part for part in parts if part.is_eighth and part.fits],
        "3-16": [part for part in parts if part.is_three_sixteenth and part.fits],
        "F Parts": [part for part in parts if not part.fits],
        "Other": [part for part in parts if part.is_other],
        "All": list(parts),
    }


def _write_sheet(sheet: Worksheet, parts: list[Part]) -> None:
    sheet.append(list(COLUMNS))
    for index, (alignment, width) in enumerate(zip(ALIGNMENTS, COLUMN_WIDTHS), start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = width
        header = sheet.cell(row=1, column=index)
        header.font = Font(bold=True)
        header.alignment = Alignment(horizontal=alignment, vertical="center")

    for part in parts:
        sheet.append(
            [
                quantity_value(part.quantity),
                part.part_number,
                part.thickness_label,
                part.size,
                part.fits_trumpf,
            ]
        )

    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=len(COLUMNS)):
        for cell, alignment in zip(row, ALIGNMENTS):
            cell.alignment = Alignment(horizontal=alignment, vertical="center")

    sheet.freeze_panes = "A2"


def build_workbook(parts: list[Part]) -> Workbook:
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = select_sheets(parts)
    for name in SHEET_ORDER:
        _write_sheet(workbook.create_sheet(title=name), sheets[name])
    return workbook


def write_workbook(parts: list[Part], destination: Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(parts).save(destination)
    return destination
