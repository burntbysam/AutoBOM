"""Integration checks against the real job 8701 files.

These files are customer data and are not committed (.gitignore covers
tests/data), so every test here skips when the directory is empty.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from autobom.core import process, select_sheets

REFERENCE = "REFERENCE_8701_prior_llm_run.xlsx"


@pytest.fixture
def result(sample_data_dir):
    boms = sorted(
        path
        for path in sample_data_dir.glob("*.csv")
        if not path.stem.upper().startswith("IL")
    )
    ils = sorted(sample_data_dir.glob("IL-*.csv"))
    return process(boms, ils)


class TestJob8701:
    def test_every_row_parsed_cleanly(self, result):
        assert result.issues == []

    def test_no_bom_is_missing_from_the_il(self, result):
        assert result.cross_check.boms_without_il == []

    def test_il_calls_assemblies_with_no_bom(self, result):
        # The IL references splice covers and joiner channels whose BOMs were
        # never supplied; they are FLAG 2, not output rows.
        assert "JB-2724-06" in result.cross_check.il_without_bom
        assert "8701-300-I" in result.cross_check.il_without_bom

    def test_unmatched_il_assemblies_are_never_output_rows(self, result):
        numbers = {part.part_number for part in result.parts}
        for assembly in result.cross_check.il_without_bom:
            assert assembly not in numbers

    def test_expected_totals(self, result):
        sheets = select_sheets(result.parts)
        assert len(sheets["All"]) == 26
        assert len(sheets["1-8"]) == 23
        assert len(sheets["3-16"]) == 0
        assert len(sheets["F Parts"]) == 3
        assert len(sheets["Other"]) == 0

    def test_the_three_f_parts_are_the_72_inch_sheets(self, result):
        f_parts = select_sheets(result.parts)["F Parts"]
        assert [part.part_number for part in f_parts] == [
            "8701-1101-1",
            "8701-1102-1",
            "8701-1103-1",
        ]
        assert all(part.size == "72x120" for part in f_parts)

    def test_all_quantities_are_one(self, result):
        # Every IL line for these assemblies has assembly quantity 1.
        assert all(part.quantity == Decimal(1) for part in result.parts)


class TestAgainstPriorRun:
    """The reference workbook came from an LLM run and is a sanity check only.

    Every part this pipeline emits must match it exactly. The reference
    additionally contains fabricated rows for assemblies that had no BOM;
    those are asserted to be absent here on purpose.
    """

    @pytest.fixture
    def reference_rows(self, sample_data_dir):
        openpyxl = pytest.importorskip("openpyxl")
        path = sample_data_dir / REFERENCE
        if not path.is_file():
            pytest.skip(f"{REFERENCE} not present")
        workbook = openpyxl.load_workbook(path)
        return {
            name: [
                tuple(str(value) for value in row)
                for row in workbook[name].iter_rows(min_row=2, values_only=True)
                if any(value is not None for value in row)
            ]
            for name in ("1-8", "3-16", "F Parts", "Other", "All")
        }

    def test_our_rows_are_a_subset_of_the_reference(self, result, reference_rows):
        sheets = select_sheets(result.parts)
        for name, rows in sheets.items():
            mine = {
                (
                    str(int(part.quantity)),
                    part.part_number,
                    part.thickness_label,
                    part.size,
                    part.fits_trumpf,
                )
                for part in rows
            }
            assert mine <= set(reference_rows[name]), f"{name} has rows the prior run lacked"

    def test_reference_extras_are_exactly_the_flag_2_assemblies(self, result, reference_rows):
        mine = {
            (
                str(int(part.quantity)),
                part.part_number,
                part.thickness_label,
                part.size,
                part.fits_trumpf,
            )
            for part in select_sheets(result.parts)["All"]
        }
        extras = {row[1] for row in reference_rows["All"] if row not in mine}
        assert extras == set(result.cross_check.il_without_bom)
