"""Data structures shared by the BOM pipeline.

Quantities and dimensions use Decimal rather than float so that the
thickness tolerance windows in the SPEC (+/- 0.005) are exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

THICKNESS_EIGHTH = '1/8"'
THICKNESS_THREE_SIXTEENTH = '3/16"'
THICKNESS_OTHER = "OTHER"

FITS = "T"
DOES_NOT_FIT = "F"


@dataclass(frozen=True)
class BomLine:
    """One SHEET,AL row kept from a bus section BOM."""

    part_number: str
    item_quantity: Decimal
    thickness: Decimal
    width: Decimal
    height: Decimal
    description: str
    source_file: str
    assembly_key: str
    line_number: int


@dataclass(frozen=True)
class IlLine:
    """One row of an indented list."""

    assembly_quantity: Decimal
    assembly_number: str
    assembly_key: str
    description: str
    source_file: str
    line_number: int


@dataclass(frozen=True)
class Part:
    """An aggregated output row, ready for a worksheet."""

    quantity: Decimal
    part_number: str
    thickness_label: str
    size: str
    fits_trumpf: str

    @property
    def is_eighth(self) -> bool:
        return self.thickness_label == THICKNESS_EIGHTH

    @property
    def is_three_sixteenth(self) -> bool:
        return self.thickness_label == THICKNESS_THREE_SIXTEENTH

    @property
    def is_other(self) -> bool:
        return self.thickness_label == THICKNESS_OTHER

    @property
    def fits(self) -> bool:
        return self.fits_trumpf == FITS


@dataclass
class ParseIssue:
    """A row that could not be interpreted, surfaced instead of dropped."""

    source_file: str
    line_number: int
    detail: str


@dataclass
class CrossCheck:
    """Result of PHASE 3."""

    # BOM files with no matching IL assembly number.
    boms_without_il: list[str] = field(default_factory=list)
    # IL assembly numbers with no matching BOM file.
    il_without_bom: list[str] = field(default_factory=list)

    @property
    def has_flags(self) -> bool:
        return bool(self.boms_without_il or self.il_without_bom)


@dataclass
class ProcessResult:
    parts: list[Part] = field(default_factory=list)
    cross_check: CrossCheck = field(default_factory=CrossCheck)
    other_parts: list[Part] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    bom_files: list[str] = field(default_factory=list)
    il_files: list[str] = field(default_factory=list)
