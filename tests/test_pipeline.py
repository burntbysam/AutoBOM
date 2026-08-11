from __future__ import annotations

from decimal import Decimal

import pytest

from autobom.core import process
from autobom.core.models import THICKNESS_OTHER

from .conftest import write_csv

EIGHTH_FITS = "SHEET,AL,SMOOTH,3003,.125,60x120"
EIGHTH_TOO_BIG = "SHEET,AL,SMOOTH,3003,.125,72x120"
THREE_SIXTEENTH_FITS = "SHEET,AL,SMOOTH,5052,.1875,60x120"
QUARTER_FITS = "SHEET,AL,SMOOTH,5052,.250,60x120"


@pytest.fixture
def job(tmp_path):
    """A two-assembly job exercising every classification branch."""
    write_csv(
        tmp_path,
        "8701-01101-I.csv",
        [
            f"1|1|{EIGHTH_FITS}|X|A|",
            f"2|2|{EIGHTH_TOO_BIG}|X|A|",
            f"3|1|{THREE_SIXTEENTH_FITS}|X|A|",
            f"4|1|{QUARTER_FITS}|X|A|",
            "5|9|NOT A SHEET|X|A|",
        ],
    )
    write_csv(tmp_path, "8701-01102-I.csv", [f"1|3|{EIGHTH_FITS}|X|A|"])
    write_csv(
        tmp_path,
        "IL-8701-011.csv",
        [
            "1|2|BUS SECTION|8701-01101-I|",
            "2|5|BUS SECTION|8701-01102-I|",
        ],
    )
    return tmp_path


def run(directory):
    boms = sorted(p for p in directory.glob("*.csv") if not p.stem.upper().startswith("IL"))
    ils = sorted(directory.glob("IL-*.csv"))
    return process(boms, ils)


class TestQuantities:
    def test_multiplied_by_assembly_quantity(self, job):
        result = run(job)
        quantities = {part.part_number: part.quantity for part in result.parts}
        # Assembly 1101 appears 2x on the IL.
        assert quantities["8701-1101-1"] == Decimal(2)  # 1 x 2
        assert quantities["8701-1101-2"] == Decimal(4)  # 2 x 2
        # Assembly 1102 appears 5x.
        assert quantities["8701-1102-1"] == Decimal(15)  # 3 x 5

    def test_repeated_assembly_sums(self, tmp_path):
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(
            tmp_path,
            "IL-8701-011.csv",
            ["1|2|BUS SECTION|8701-01101-I|", "2|3|BUS SECTION|8701-01101-I|"],
        )
        result = run(tmp_path)
        assert [part.quantity for part in result.parts] == [Decimal(5)]

    def test_same_assembly_across_two_ils_sums(self, tmp_path):
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(tmp_path, "IL-8701-011.csv", ["1|2|BUS|8701-01101-I|"])
        write_csv(tmp_path, "IL-8701-021.csv", ["1|4|BUS|8701-01101-I|"])
        result = run(tmp_path)
        assert [part.quantity for part in result.parts] == [Decimal(6)]


class TestClassificationRouting:
    def test_labels(self, job):
        result = run(job)
        by_number = {part.part_number: part for part in result.parts}
        assert by_number["8701-1101-1"].thickness_label == '1/8"'
        assert by_number["8701-1101-1"].fits_trumpf == "T"
        assert by_number["8701-1101-2"].fits_trumpf == "F"
        assert by_number["8701-1101-3"].thickness_label == '3/16"'
        assert by_number["8701-1101-4"].thickness_label == THICKNESS_OTHER

    def test_other_parts_reported(self, job):
        result = run(job)
        assert [part.part_number for part in result.other_parts] == ["8701-1101-4"]


class TestSorting:
    def test_parts_sorted_alphanumerically_by_part_number(self, job):
        result = run(job)
        numbers = [part.part_number for part in result.parts]
        assert numbers == sorted(numbers)


class TestCrossCheck:
    def test_no_flags_when_everything_matches(self, tmp_path):
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(tmp_path, "IL-8701-011.csv", ["1|1|BUS|8701-01101-I|"])
        assert run(tmp_path).cross_check.has_flags is False

    def test_flag_1_bom_without_il(self, tmp_path):
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(tmp_path, "8701-01102-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(tmp_path, "IL-8701-011.csv", ["1|1|BUS|8701-01101-I|"])
        cross = run(tmp_path).cross_check
        assert cross.boms_without_il == ["8701-01102-I.csv"]
        assert cross.il_without_bom == []

    def test_flag_2_il_without_bom(self, tmp_path):
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(
            tmp_path,
            "IL-8701-011.csv",
            ["1|1|BUS|8701-01101-I|", "2|2|SPLICE COVER|JB-2724-06|"],
        )
        cross = run(tmp_path).cross_check
        assert cross.boms_without_il == []
        assert cross.il_without_bom == ["JB-2724-06"]

    def test_il_only_assembly_produces_no_part_row(self, tmp_path):
        """An IL assembly with no BOM must never become an invented part row."""
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(
            tmp_path,
            "IL-8701-011.csv",
            ["1|1|BUS|8701-01101-I|", "2|2|SPLICE COVER|JB-2724-06|"],
        )
        result = run(tmp_path)
        assert [part.part_number for part in result.parts] == ["8701-1101-1"]

    def test_bom_with_no_sheet_al_still_flagged(self, tmp_path):
        """A BOM absent from the IL is FLAG 1 even if it had nothing to keep."""
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(tmp_path, "8701-01199-I.csv", ["1|1|BAR,RE,CU,3/8X10|X|A|"])
        write_csv(tmp_path, "IL-8701-011.csv", ["1|1|BUS|8701-01101-I|"])
        assert run(tmp_path).cross_check.boms_without_il == ["8701-01199-I.csv"]

    def test_duplicate_missing_assembly_listed_once(self, tmp_path):
        write_csv(tmp_path, "8701-01101-I.csv", [f"1|1|{EIGHTH_FITS}|X|A|"])
        write_csv(
            tmp_path,
            "IL-8701-011.csv",
            ["1|1|BUS|8701-01101-I|", "2|1|X|JB-1|", "3|1|X|JB-1|"],
        )
        assert run(tmp_path).cross_check.il_without_bom == ["JB-1"]
