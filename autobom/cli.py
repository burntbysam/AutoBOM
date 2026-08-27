"""Headless entry point, used for batch runs and by the test suite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import build_summary, process, select_sheets, write_workbook
from .core.parser import looks_like_il
from .core.selftest import run_selftest
from .version import describe


def split_inputs(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """Sort a mixed pile of CSVs into (bom_paths, il_paths) by filename."""
    boms = [path for path in paths if not looks_like_il(path)]
    ils = [path for path in paths if looks_like_il(path)]
    return sorted(boms), sorted(ils)


def _collect(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.csv")))
        else:
            paths.append(path)
    return paths


def _selftest() -> int:
    """Prove this copy works, on a synthetic job needing no customer files."""
    print(describe())
    ok, report = run_selftest()
    for line in report:
        print(line)
    print()
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autobom",
        description="Process CNC sheet metal BOMs into a 5-sheet Excel workbook.",
    )
    parser.add_argument(
        "inputs", nargs="*", help="CSV files or directories of CSVs"
    )
    parser.add_argument("-o", "--output", help="destination .xlsx path")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="verify this copy of AutoBOM end to end and exit",
    )
    parser.add_argument(
        "--bom", action="append", default=[], help="explicitly mark a file as a bus section BOM"
    )
    parser.add_argument(
        "--il", action="append", default=[], help="explicitly mark a file as an IL"
    )
    parser.add_argument(
        "--ignore-flags",
        action="store_true",
        help="write the workbook even when cross-check flags exist",
    )
    parser.add_argument("--version", action="version", version=describe())
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.inputs:
        parser.error("give at least one CSV file or directory (or use --selftest)")
    if not args.output:
        parser.error("-o/--output is required")

    boms, ils = split_inputs(_collect(args.inputs))
    boms.extend(Path(value) for value in args.bom)
    ils.extend(Path(value) for value in args.il)
    boms, ils = sorted(set(boms)), sorted(set(ils))

    missing = [path for path in boms + ils if not path.is_file()]
    if missing:
        for path in missing:
            print(f"error: no such file: {path}", file=sys.stderr)
        return 2
    if not boms:
        print("error: no bus section BOMs found", file=sys.stderr)
        return 2
    if not ils:
        print("error: no IL CSVs found", file=sys.stderr)
        return 2

    result = process(boms, ils)

    for issue in result.issues:
        print(
            f"warning: {issue.source_file} line {issue.line_number}: {issue.detail}",
            file=sys.stderr,
        )

    for row in result.excluded:
        print(
            f"excluded: {row.source_file} line {row.line_number}: {row.detail}",
            file=sys.stderr,
        )

    for row in result.defaulted:
        print(
            f"no size given, counted as 60x120: {row.source_file} "
            f"line {row.line_number}: {row.detail}",
            file=sys.stderr,
        )

    if result.cross_check.has_flags:
        print("\n⚠️  FLAGS — REVIEW REQUIRED")
        for filename in result.cross_check.boms_without_il:
            print(f"  FLAG 1  BOM with no matching IL assembly: {filename}")
        for assembly in result.cross_check.il_without_bom:
            print(f"  FLAG 2  IL assembly with no matching BOM: {assembly}")
        if not args.ignore_flags:
            print("\nNothing was written. Supply the missing files or pass --ignore-flags.")
            return 1

    if result.other_parts:
        print(f"\nnote: {len(result.other_parts)} part(s) classified OTHER — review the Other sheet.")

    destination = write_workbook(result.parts, Path(args.output))
    counts = {name: len(rows) for name, rows in select_sheets(result.parts).items()}
    sheets = ", ".join(f"{name}: {count}" for name, count in counts.items())
    print(f"\nWrote {destination} ({sheets})")
    print()
    print(f"{'Category':<22}{'Line items':>12}{'Pieces':>10}")
    for label, line_items, pieces in build_summary(result.parts):
        print(f"{label:<22}{line_items:>12}{pieces:>10}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
