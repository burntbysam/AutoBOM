"""Pure BOM-processing logic; imports no GUI toolkit."""

from .classify import classify_thickness, fits_trumpf, format_size
from .excel import SHEET_ORDER, build_workbook, select_sheets, write_workbook
from .models import CrossCheck, Part, ProcessResult
from .pipeline import aggregate, cross_check, process, sort_parts

__all__ = [
    "CrossCheck",
    "Part",
    "ProcessResult",
    "SHEET_ORDER",
    "aggregate",
    "build_workbook",
    "classify_thickness",
    "cross_check",
    "fits_trumpf",
    "format_size",
    "process",
    "select_sheets",
    "sort_parts",
    "write_workbook",
]
