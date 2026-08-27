"""Readers for the two pipe-delimited CSV flavours the tool accepts.

Both file types are exported with a leading ``sep=|`` line and may carry a
trailing empty field, so rows are split manually rather than through the csv
module's dialect sniffing.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .classify import STANDARD_HEIGHT, STANDARD_WIDTH
from .models import BomLine, IlLine, ParseIssue

SHEET_AL_PREFIX = "SHEET,AL"
# Different jobs export the same prefix with different spacing: job 8701 wrote
# "SHEET,AL,..." and job 8763 wrote "SHEET, AL, ...". The comma may carry
# whitespace on either side; the words stay case-sensitive per the spec.
_SHEET_AL_RE = re.compile(r"^SHEET\s*,\s*AL")

# Descriptions that never reach the workbook, whichever file they arrive in.
# Matched on the whole description, case-insensitively, after collapsing runs
# of whitespace.
EXCLUDED_DESCRIPTIONS = ("COVER JOINER CHANNEL",)

# First decimal number in the description: .125, 0.190, 1.25 all match.
_THICKNESS_RE = re.compile(r"\d*\.\d+")
# Dimensions in WxH form; either side may carry decimals (60x133.13) and
# inch marks (92"X120"), and the separator may be either case.
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[\"”]?\s*[xX]\s*(\d+(?:\.\d+)?)")

_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def read_rows(path: Path) -> list[tuple[int, list[str]]]:
    """Return ``(line_number, fields)`` for every data row of a pipe CSV.

    The ``sep=|`` directive and blank lines are skipped. Line numbers are
    1-based and count every physical line, so they match what the user sees
    in a text editor.
    """
    text = _read_text(path)
    rows: list[tuple[int, list[str]]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.lower().replace(" ", "").startswith("sep="):
            continue
        rows.append((number, [field.strip() for field in line.split("|")]))
    return rows


def _read_text(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in _ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:  # pragma: no cover - depends on file
            last_error = exc
    raise last_error  # pragma: no cover


def is_excluded_description(description: str) -> bool:
    """True for a description on the never-count list."""
    normalised = " ".join(description.split()).upper()
    return normalised in {value.upper() for value in EXCLUDED_DESCRIPTIONS}


def assembly_key(value: str) -> str:
    """Normalise an assembly identifier so IL rows and filenames compare equal.

    The IL names assemblies exactly as the BOM files are named
    (``8701-01101-I``), but casing, surrounding whitespace and a stray
    ``.csv`` suffix should not defeat the match.
    """
    key = value.strip().upper()
    if key.endswith(".CSV"):
        key = key[: -len(".CSV")]
    return key


def build_part_number(filename: str, item_number: str) -> str:
    """Apply SPEC PHASE 1 rule 4.

    ``8551-07127-I.csv`` + item ``3`` -> ``8551-7127-3``: drop the extension,
    drop the trailing ``-I``, drop one leading zero from the assembly number,
    then append the item number.
    """
    stem = Path(filename).stem.strip()
    if stem.upper().endswith("-I"):
        stem = stem[:-2]
    job, dash, assembly = stem.partition("-")
    if dash and assembly.startswith("0"):
        assembly = assembly[1:]
        stem = f"{job}-{assembly}"
    return f"{stem}-{item_number.strip()}"


def parse_thickness(description: str) -> Decimal | None:
    match = _THICKNESS_RE.search(description)
    if match is None:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:  # pragma: no cover - regex guarantees validity
        return None


def parse_size(description: str) -> tuple[Decimal, Decimal] | None:
    """Return the WxH dimensions, skipping a match that is only the thickness.

    Searching from the end of the thickness match avoids a description such as
    ``SHEET,AL,.125x2`` being read as a sheet size.
    """
    start = 0
    thickness = _THICKNESS_RE.search(description)
    if thickness is not None:
        start = thickness.end()
    match = _SIZE_RE.search(description, start) or _SIZE_RE.search(description)
    if match is None:
        return None
    return Decimal(match.group(1)), Decimal(match.group(2))


def _parse_quantity(value: str) -> Decimal | None:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return None


def parse_bom(
    path: Path,
    issues: list[ParseIssue] | None = None,
    excluded: list[ParseIssue] | None = None,
    defaulted: list[ParseIssue] | None = None,
) -> list[BomLine]:
    """Read one bus section BOM, keeping only sheet aluminium rows.

    Columns: ITEM NUMBER | ITEM QUANTITY | DESCRIPTION | INVENTORY CODE | SHOP TYPE
    """
    issues = issues if issues is not None else []
    excluded = excluded if excluded is not None else []
    defaulted = defaulted if defaulted is not None else []
    filename = path.name
    key = assembly_key(path.stem)
    lines: list[BomLine] = []

    for number, fields in read_rows(path):
        if len(fields) < 3:
            issues.append(ParseIssue(filename, number, "fewer than 3 columns"))
            continue
        item_number, quantity_text, description = fields[0], fields[1], fields[2]
        # Case-sensitive per SPEC rule 1; spacing around the comma is not
        # meaningful (see _SHEET_AL_RE).
        if not _SHEET_AL_RE.match(description):
            continue
        # Checked after the SHEET,AL filter so the report only mentions rows
        # the exclusion actually removed.
        if is_excluded_description(description):
            excluded.append(ParseIssue(filename, number, description.strip()))
            continue

        quantity = _parse_quantity(quantity_text)
        if quantity is None:
            issues.append(
                ParseIssue(filename, number, f"unreadable item quantity {quantity_text!r}")
            )
            continue
        thickness = parse_thickness(description)
        if thickness is None:
            issues.append(
                ParseIssue(filename, number, f"no thickness in {description!r}")
            )
            continue
        size = parse_size(description)
        if size is None:
            # A sheet row with no WxH in its description is counted at the
            # standard sheet, not dropped — a skipped row is a missing part on
            # the floor. Recorded so the run can say which rows it assumed.
            defaulted.append(ParseIssue(filename, number, description.strip()))
            size = (STANDARD_WIDTH, STANDARD_HEIGHT)

        lines.append(
            BomLine(
                part_number=build_part_number(filename, item_number),
                item_quantity=quantity,
                thickness=thickness,
                width=size[0],
                height=size[1],
                description=description,
                source_file=filename,
                assembly_key=key,
                line_number=number,
            )
        )
    return lines


def parse_il(
    path: Path,
    issues: list[ParseIssue] | None = None,
    excluded: list[ParseIssue] | None = None,
) -> list[IlLine]:
    """Read one indented list.

    Columns: LINE NUMBER | ASSEMBLY QUANTITY | DESCRIPTION | ASSEMBLY NUMBER | SHOP CODE
    Only assembly quantity and assembly number are used, per SPEC rule 1.
    """
    issues = issues if issues is not None else []
    excluded = excluded if excluded is not None else []
    filename = path.name
    lines: list[IlLine] = []

    for number, fields in read_rows(path):
        if len(fields) < 4:
            issues.append(ParseIssue(filename, number, "fewer than 4 columns"))
            continue
        if is_excluded_description(fields[2]):
            excluded.append(ParseIssue(filename, number, fields[2].strip()))
            continue
        quantity = _parse_quantity(fields[1])
        assembly_number = fields[3].strip()
        if not assembly_number:
            issues.append(ParseIssue(filename, number, "blank assembly number"))
            continue
        if quantity is None:
            issues.append(
                ParseIssue(filename, number, f"unreadable assembly quantity {fields[1]!r}")
            )
            continue
        lines.append(
            IlLine(
                assembly_quantity=quantity,
                assembly_number=assembly_number,
                assembly_key=assembly_key(assembly_number),
                description=fields[2],
                source_file=filename,
                line_number=number,
            )
        )
    return lines


def looks_like_il(path: Path) -> bool:
    """Heuristic used by the GUI to pre-sort dropped files into the two lists."""
    return path.stem.upper().startswith("IL")
