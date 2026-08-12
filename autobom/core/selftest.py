"""End-to-end self-check the shipped executable can run on itself.

CI will not publish a build that fails this, and anyone on the shop floor can
run ``AutoBOM.exe --selftest`` to prove the copy they hold is sound. The job is
synthetic and built in a temp directory, so it needs no customer files -- which
matters because the real BOMs are deliberately not committed.
"""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

from .excel import SHEET_ORDER, build_summary, select_sheets
from .pipeline import process

# One assembly exercising every classification branch, plus the individual
# parts and the exclusion rule.
_BOM_ROWS = [
    "1|1|SHEET,AL,SMOOTH,3003,.125,60x120|CAL1|COVER|",   # 1/8" and fits
    "2|2|SHEET,AL,SMOOTH,3003,.125,72x120|CAL2|HOUSING|",  # 1/8" but too wide
    "3|1|SHEET,AL,SMOOTH,5052,.1875,60x120|CAL3|COVER|",   # 3/16" and fits
    "4|1|SHEET,AL,SMOOTH,5052,.250,60x120|CAL4|COVER|",    # OTHER thickness
    "5|9|BAR,RE,CU,3/8X10|CAL5|CONDUCTOR|",                # not sheet aluminium
]
_IL_ROWS = [
    "1|2|BUS SECTION|8701-01101-I|",
    "2|3|ENCLOSURE TOP SPLICE COVER|JB-2724-06|",   # individual part
    "3|6|ENCLOSURE TOP SPLICE COVER|8701-300-I|",   # individual part
    "4|4|COVER JOINER CHANNEL|JB-2705-27|",         # never counted
]

# (part number, quantity, thickness, size, fits)
_EXPECTED_ROWS = {
    "8701-1101-1": (Decimal(2), '1/8"', "60x120", "T"),
    "8701-1101-2": (Decimal(4), '1/8"', "72x120", "F"),
    "8701-1101-3": (Decimal(2), '3/16"', "60x120", "T"),
    "8701-1101-4": (Decimal(2), "OTHER", "60x120", "T"),
    "JB-2724-06": (Decimal(3), '1/8"', "60x120", "T"),
    "8701-300-I": (Decimal(6), '1/8"', "60x120", "T"),
}
_EXPECTED_SHEET_COUNTS = {"1-8": 3, "3-16": 1, "F Parts": 1, "Other": 1, "All": 6}

# label -> (line items, pieces). Grouped by thickness, so the 1/8" row includes
# the F part that does not fit the Trumpf.
_EXPECTED_SUMMARY = {
    '1/8"': (4, 15),
    '3/16"': (1, 2),
    '1/8" + 3/16" total': (5, 17),
    "OTHER thickness": (1, 2),
    "Grand total": (6, 19),
}


def _write(directory: Path, name: str, rows: list[str]) -> Path:
    path = directory / name
    path.write_text("sep=|\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def run_selftest() -> tuple[bool, list[str]]:
    """Process a synthetic job and verify every published rule end to end."""
    report: list[str] = []
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="autobom-selftest-") as raw:
        directory = Path(raw)
        bom = _write(directory, "8701-01101-I.csv", _BOM_ROWS)
        il = _write(directory, "IL-8701-011.csv", _IL_ROWS)

        result = process([bom], [il])

        if result.issues:
            failures.append(f"{len(result.issues)} row(s) failed to parse")
        report.append(f"parse issues:        {len(result.issues)}")

        if len(result.excluded) != 1:
            failures.append(f"expected 1 excluded row, got {len(result.excluded)}")
        report.append(f"excluded rows:       {len(result.excluded)} (COVER JOINER CHANNEL)")

        if result.cross_check.has_flags:
            failures.append("unexpected cross-check flags on the synthetic job")
        report.append("cross-check flags:   none")

        actual = {part.part_number: part for part in result.parts}
        for number, (quantity, thickness, size, fits) in _EXPECTED_ROWS.items():
            part = actual.get(number)
            if part is None:
                failures.append(f"missing part {number}")
                continue
            got = (part.quantity, part.thickness_label, part.size, part.fits_trumpf)
            if got != (quantity, thickness, size, fits):
                failures.append(
                    f"{number}: expected {(quantity, thickness, size, fits)}, got {got}"
                )
        for number in set(actual) - set(_EXPECTED_ROWS):
            failures.append(f"unexpected part {number}")
        report.append(f"parts:               {len(actual)}")

        if "JB-2705-27" in actual:
            failures.append("COVER JOINER CHANNEL reached the output")

        counts = {name: len(rows) for name, rows in select_sheets(result.parts).items()}
        for name in SHEET_ORDER:
            if counts[name] != _EXPECTED_SHEET_COUNTS[name]:
                failures.append(
                    f"sheet {name}: expected {_EXPECTED_SHEET_COUNTS[name]}, "
                    f"got {counts[name]}"
                )
        report.append(
            "sheets:              "
            + ", ".join(f"{name}: {counts[name]}" for name in SHEET_ORDER)
        )

        summary = {
            label: (line_items, pieces)
            for label, line_items, pieces in build_summary(result.parts)
        }
        for label, expected in _EXPECTED_SUMMARY.items():
            if summary.get(label) != expected:
                failures.append(
                    f"summary {label}: expected {expected}, got {summary.get(label)}"
                )
        report.append(
            "totals:              "
            + ", ".join(
                f"{label} {items}/{pieces}"
                for label, (items, pieces) in summary.items()
            )
        )

        # Writing the workbook proves openpyxl is bundled and working, which a
        # pure in-memory check would not.
        destination = directory / "selftest.xlsx"
        try:
            from .excel import write_workbook

            write_workbook(result.parts, destination)
            size = destination.stat().st_size
            if size <= 0:
                failures.append("workbook written but empty")
            report.append(f"workbook:            {size} bytes")
        except Exception as exc:  # noqa: BLE001 - report any failure, never crash
            failures.append(f"could not write the workbook: {exc}")

    return not failures, report + ([""] + failures if failures else [])
