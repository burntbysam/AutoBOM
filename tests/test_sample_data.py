"""Integration checks against the real job 8701 files.

These files are customer data and are not committed (.gitignore covers
tests/data), so every test here skips when the directory is empty.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from autobom.core import process, select_sheets
from autobom.core.classify import is_individual_part

from .conftest import DATA_DIR

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

    def test_no_flags_at_all(self, result):
        # Every unmatched assembly on this job is a 300-series or JB part.
        assert result.cross_check.has_flags is False

    def test_individual_parts_are_counted_as_standard_sheet(self, result):
        parts = {part.part_number: part for part in result.parts}
        assert parts["8701-300-I"].quantity == Decimal(6)
        assert parts["JB-2724-06"].quantity == Decimal(2)
        assert parts["JB-2706-15"].quantity == Decimal(15)
        for number in ("8701-300-I", "JB-2724-06", "JB-2706-15"):
            assert parts[number].thickness_label == '1/8"'
            assert parts[number].size == "60x120"
            assert parts[number].fits_trumpf == "T"

    def test_cover_joiner_channels_are_excluded(self, result):
        numbers = {part.part_number for part in result.parts}
        # The only two COVER JOINER CHANNEL rows on this job.
        assert "8701-302-I" not in numbers
        assert "JB-2705-27" not in numbers
        assert len(result.excluded) == 2
        assert {row.detail for row in result.excluded} == {"COVER JOINER CHANNEL"}

    def test_expected_totals(self, result):
        sheets = select_sheets(result.parts)
        # 26 bus section parts + 14 individual parts - 2 joiner channels.
        assert len(sheets["All"]) == 38
        assert len(sheets["1-8"]) == 35
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

    def test_bus_section_quantities_are_one(self, result):
        # Every IL line for the bus section assemblies has quantity 1; the
        # individual parts carry their own quantities and are excluded here.
        bus_sections = [
            part for part in result.parts if not is_individual_part(part.part_number)
        ]
        assert len(bus_sections) == 26
        assert all(part.quantity == Decimal(1) for part in bus_sections)


@pytest.fixture
def result_8763():
    directory = DATA_DIR / "8763"
    boms = sorted(
        path
        for path in directory.glob("*.csv")
        if not path.stem.upper().startswith("IL")
    )
    if not boms:
        pytest.skip("no local 8763 sample data in tests/data/8763 (not committed)")
    return process(boms, sorted(directory.glob("IL-*.csv")))


class TestJob8763:
    """Regression: this job once produced a single line item.

    Its descriptions use spaces after commas and inch-marked sizes
    (``SHEET, AL, .190, 3003, 92"X120"``), and the old strict prefix filtered
    every sheet row out, leaving only the IL's individual part.
    """

    def test_every_sheet_row_survives_the_filter(self, result_8763):
        # 4 sheet rows in 01101 + 10 in 01102 + the JB individual part.
        assert len(result_8763.parts) == 15

    def test_no_row_needed_a_defaulted_size(self, result_8763):
        # The inch-marked sizes must parse as real sizes, not fall back to
        # 60x120 -- a 92-inch sheet counted as a standard one goes to the
        # wrong machine.
        assert result_8763.defaulted == []

    def test_no_flags_and_no_issues(self, result_8763):
        assert result_8763.issues == []
        assert result_8763.cross_check.has_flags is False

    def test_the_190_housings_are_three_sixteenth_f_parts(self, result_8763):
        parts = {part.part_number: part for part in result_8763.parts}
        for number in (
            "8763-1101-1",
            "8763-1102-1",
            "8763-1102-2",
            "8763-1102-3",
            "8763-1102-4",
        ):
            assert parts[number].thickness_label == '3/16"'
            assert parts[number].size == "92x120"
            assert parts[number].fits_trumpf == "F"

    def test_the_decimal_covers_keep_their_real_size(self, result_8763):
        parts = {part.part_number: part for part in result_8763.parts}
        for number in ("8763-1102-5", "8763-1102-6"):
            assert parts[number].size == "69.5x120"
            assert parts[number].fits_trumpf == "F"

    def test_sheet_totals(self, result_8763):
        sheets = select_sheets(result_8763.parts)
        assert {name: len(rows) for name, rows in sheets.items()} == {
            "1-8": 8,
            "3-16": 0,
            "F Parts": 7,
            "Other": 0,
            "All": 15,
        }

    def test_the_individual_part_is_present(self, result_8763):
        parts = {part.part_number: part for part in result_8763.parts}
        assert parts["JB-2401-01"].quantity == Decimal(1)


class TestAgainstPriorRun:
    """The reference workbook came from an LLM run and is a sanity check only.

    Everything this pipeline emits must appear in it. The reference differs
    only by the COVER JOINER CHANNEL rows, which are excluded here on purpose.
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

    def test_the_only_difference_is_the_excluded_joiner_channels(
        self, result, reference_rows
    ):
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
        assert extras == {"8701-302-I", "JB-2705-27"}
