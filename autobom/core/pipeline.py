"""Orchestration of the SPEC: parse, cross-check, multiply, classify, sort."""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

from .classify import (
    STANDARD_HEIGHT,
    STANDARD_THICKNESS,
    STANDARD_WIDTH,
    classify_thickness,
    fits_trumpf,
    format_size,
    is_individual_part,
)
from .models import (
    BomLine,
    CrossCheck,
    IlLine,
    Part,
    ParseIssue,
    ProcessResult,
    THICKNESS_OTHER,
)
from .parser import parse_bom, parse_il


def cross_check(bom_lines_by_key: dict[str, str], il_lines: list[IlLine]) -> CrossCheck:
    """PHASE 3.

    ``bom_lines_by_key`` maps a normalised assembly key to the filename it came
    from, so the flags can be reported using names the user recognises.
    """
    il_keys = {line.assembly_key for line in il_lines}

    boms_without_il = sorted(
        filename for key, filename in bom_lines_by_key.items() if key not in il_keys
    )

    seen: set[str] = set()
    il_without_bom: list[str] = []
    for line in il_lines:
        if line.assembly_key in bom_lines_by_key or line.assembly_key in seen:
            continue
        # 300-series and JB parts are individual pieces with no BOM by design,
        # so their absence is not a mismatch to report.
        if is_individual_part(line.assembly_number):
            continue
        seen.add(line.assembly_key)
        il_without_bom.append(line.assembly_number)

    return CrossCheck(
        boms_without_il=boms_without_il,
        il_without_bom=sorted(il_without_bom),
    )


def aggregate(bom_lines: list[BomLine], il_lines: list[IlLine]) -> list[Part]:
    """PHASE 2 rules 3-4 plus PHASE 4-5.

    Every IL row multiplies the BOM rows of the assembly it references, and
    quantities for a repeated part number are summed. A BOM whose assembly is
    absent from the IL contributes nothing -- it is reported as FLAG 1 instead.
    """
    by_assembly: dict[str, list[BomLine]] = {}
    for line in bom_lines:
        by_assembly.setdefault(line.assembly_key, []).append(line)

    totals: "OrderedDict[str, Decimal]" = OrderedDict()
    # part number -> (thickness, width, height)
    attributes: dict[str, tuple[Decimal, Decimal, Decimal]] = {}

    def add(part_number: str, quantity: Decimal, sheet: tuple[Decimal, Decimal, Decimal]):
        totals[part_number] = totals.get(part_number, Decimal(0)) + quantity
        attributes.setdefault(part_number, sheet)

    for il_line in il_lines:
        matches = by_assembly.get(il_line.assembly_key)
        if matches:
            for bom_line in matches:
                add(
                    bom_line.part_number,
                    bom_line.item_quantity * il_line.assembly_quantity,
                    (bom_line.thickness, bom_line.width, bom_line.height),
                )
        elif is_individual_part(il_line.assembly_number):
            # An individual part is one piece of standard stock; the IL's
            # assembly quantity is the final quantity, nothing to multiply.
            add(
                il_line.assembly_number.strip(),
                il_line.assembly_quantity,
                (STANDARD_THICKNESS, STANDARD_WIDTH, STANDARD_HEIGHT),
            )

    parts = [
        Part(
            quantity=total,
            part_number=part_number,
            thickness_label=classify_thickness(attributes[part_number][0]),
            size=format_size(attributes[part_number][1], attributes[part_number][2]),
            fits_trumpf=fits_trumpf(attributes[part_number][1], attributes[part_number][2]),
        )
        for part_number, total in totals.items()
    ]
    return sort_parts(parts)


def sort_parts(parts: list[Part]) -> list[Part]:
    """PHASE 5 sorting: alphanumeric (lexicographic) by Part #."""
    return sorted(parts, key=lambda part: part.part_number)


def process(bom_paths: list[Path], il_paths: list[Path]) -> ProcessResult:
    """Run the whole workflow over already-collected files."""
    issues: list[ParseIssue] = []
    excluded: list[ParseIssue] = []

    bom_lines: list[BomLine] = []
    key_to_filename: dict[str, str] = {}
    for path in bom_paths:
        bom_lines.extend(parse_bom(path, issues, excluded))
        # Recorded for every BOM handed in, even one with no SHEET,AL rows, so
        # that FLAG 1 still reports it when the IL never references it.
        key_to_filename.setdefault(path.stem.strip().upper(), path.name)

    il_lines: list[IlLine] = []
    for path in il_paths:
        il_lines.extend(parse_il(path, issues, excluded))

    parts = aggregate(bom_lines, il_lines)

    return ProcessResult(
        parts=parts,
        cross_check=cross_check(key_to_filename, il_lines),
        other_parts=[part for part in parts if part.thickness_label == THICKNESS_OTHER],
        issues=issues,
        excluded=excluded,
        bom_files=[path.name for path in bom_paths],
        il_files=[path.name for path in il_paths],
    )
