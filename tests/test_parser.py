from __future__ import annotations

from decimal import Decimal

import pytest

from autobom.core.parser import (
    assembly_key,
    build_part_number,
    parse_bom,
    parse_il,
    parse_size,
    parse_thickness,
    read_rows,
)

from .conftest import write_csv


class TestBuildPartNumber:
    @pytest.mark.parametrize(
        "filename,item,expected",
        [
            # Both examples given verbatim in the SPEC.
            ("8551-07127-I.csv", "3", "8551-7127-3"),
            ("8551-06101-I.csv", "12", "8551-6101-12"),
            ("8701-01101-I.csv", "1", "8701-1101-1"),
            # Only one leading zero is stripped.
            ("8701-00101-I.csv", "2", "8701-0101-2"),
            # Assembly without a leading zero is left alone.
            ("8701-1101-I.csv", "4", "8701-1101-4"),
            # Lowercase extension and suffix still parse.
            ("8701-01101-i.CSV", "7", "8701-1101-7"),
        ],
    )
    def test_examples(self, filename, item, expected):
        assert build_part_number(filename, item) == expected

    def test_item_number_is_stripped(self):
        assert build_part_number("8701-01101-I.csv", "  9 ") == "8701-1101-9"


class TestParseThickness:
    @pytest.mark.parametrize(
        "description,expected",
        [
            ("SHEET,AL,SMOOTH,3003,.125,60x120", "0.125"),
            ("SHEET,AL,SMOOTH,5052,.1875,60x120", "0.1875"),
            ("SHEET,AL,SMOOTH,3003,.190,72x144", "0.190"),
            ("SHEET,AL,SMOOTH,3003,0.250,60x120", "0.250"),
        ],
    )
    def test_first_decimal_wins(self, description, expected):
        assert parse_thickness(description) == Decimal(expected)

    def test_integer_alloy_code_is_not_a_thickness(self):
        # 3003 must not be read as the thickness.
        assert parse_thickness("SHEET,AL,SMOOTH,3003,.125,60x120") == Decimal("0.125")

    def test_missing_thickness(self):
        assert parse_thickness("SHEET,AL,SMOOTH,3003,60x120") is None


class TestParseSize:
    @pytest.mark.parametrize(
        "description,expected",
        [
            ("SHEET,AL,SMOOTH,3003,.125,60x120", ("60", "120")),
            ("SHEET,AL,SMOOTH,3003,.125,72x144", ("72", "144")),
            ("SHEET,AL,SMOOTH,3003,.125,60x133.13", ("60", "133.13")),
            ("SHEET,AL,SMOOTH,3003,.125,60X120", ("60", "120")),
        ],
    )
    def test_dimensions(self, description, expected):
        width, height = parse_size(description)
        assert (width, height) == (Decimal(expected[0]), Decimal(expected[1]))

    def test_size_is_searched_after_the_thickness(self):
        # The thickness itself must not be mistaken for a WxH pair.
        assert parse_size("SHEET,AL,.125x2,60x120") == (Decimal("60"), Decimal("120"))

    def test_missing_size(self):
        assert parse_size("SHEET,AL,SMOOTH,3003,.125") is None


class TestAssemblyKey:
    @pytest.mark.parametrize(
        "value", ["8701-01101-I", " 8701-01101-i ", "8701-01101-I.csv", "8701-01101-i.CSV"]
    )
    def test_normalisation(self, value):
        assert assembly_key(value) == "8701-01101-I"


class TestReadRows:
    def test_skips_sep_directive_and_blanks(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("sep=|\n1|1|A|B|\n\n2|2|C|D|\n", encoding="utf-8")
        rows = read_rows(path)
        assert [number for number, _ in rows] == [2, 4]
        assert rows[0][1][:3] == ["1", "1", "A"]


class TestParseBom:
    def test_keeps_only_sheet_al_rows(self, tmp_path):
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            [
                "1|1|SHEET,AL,SMOOTH,3003,.125,72x120|CAL41022004|HOUSING|",
                "2|2|SHEET,AL,SMOOTH,3003,.125,60x120|CAL41022006|COVER|",
                "3|4|SUPPORT BLOCK ASSEMBLY|8701-011-A|SUPPORT|",
                "4|3|BAR,RE,CU,3/8X10|CAL12002061|CONDUCTOR|",
            ],
        )
        lines = parse_bom(path)
        assert [line.part_number for line in lines] == ["8701-1101-1", "8701-1101-2"]
        assert [line.item_quantity for line in lines] == [Decimal(1), Decimal(2)]
        assert lines[0].width == Decimal(72)

    def test_filter_is_case_sensitive(self, tmp_path):
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            [
                "1|1|sheet,al,smooth,3003,.125,60x120|X||",
                "2|1|Sheet,Al,SMOOTH,3003,.125,60x120|X||",
                "3|1|SHEET,ALUMINUM,.125,60x120|X||",
            ],
        )
        # Only the third row starts with the exact "SHEET,AL" prefix.
        assert [line.part_number for line in parse_bom(path)] == ["8701-1101-3"]

    def test_unparseable_rows_become_issues_not_silent_drops(self, tmp_path):
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            [
                "1|x|SHEET,AL,SMOOTH,3003,.125,60x120|X||",
                "2|1|SHEET,AL,SMOOTH,3003,60x120|X||",
            ],
        )
        issues: list = []
        assert parse_bom(path, issues) == []
        assert len(issues) == 2
        assert "quantity" in issues[0].detail
        assert "thickness" in issues[1].detail


class TestMissingSizeDefaults:
    """A SHEET,AL row with no WxH is counted at 60x120, never skipped.

    A skipped row is a missing part on the shop floor; an assumed one is at
    least visible and correctable.
    """

    def test_counted_at_the_standard_sheet(self, tmp_path):
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            ["1|2|SHEET,AL,SMOOTH,3003,.125|X|COVER|"],
        )
        lines = parse_bom(path)
        assert len(lines) == 1
        assert (lines[0].width, lines[0].height) == (Decimal(60), Decimal(120))
        assert lines[0].item_quantity == Decimal(2)

    def test_reported_not_silent(self, tmp_path):
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            ["1|2|SHEET,AL,SMOOTH,3003,.125|X|COVER|"],
        )
        defaulted: list = []
        parse_bom(path, defaulted=defaulted)
        assert len(defaulted) == 1
        assert defaulted[0].line_number == 2
        assert "SHEET,AL" in defaulted[0].detail

    def test_not_treated_as_a_parse_issue(self, tmp_path):
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            ["1|2|SHEET,AL,SMOOTH,3003,.125|X|COVER|"],
        )
        issues: list = []
        parse_bom(path, issues)
        assert issues == []

    def test_a_row_with_a_real_size_is_not_defaulted(self, tmp_path):
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            ["1|1|SHEET,AL,SMOOTH,3003,.125,72x144|X|COVER|"],
        )
        defaulted: list = []
        lines = parse_bom(path, defaulted=defaulted)
        assert defaulted == []
        assert (lines[0].width, lines[0].height) == (Decimal(72), Decimal(144))

    def test_missing_thickness_is_still_skipped(self, tmp_path):
        # Only the size defaults; a row with no thickness has no bucket at all
        # and stays a reported skip.
        path = write_csv(
            tmp_path,
            "8701-01101-I.csv",
            ["1|1|SHEET,AL,SMOOTH,3003|X|COVER|"],
        )
        issues: list = []
        assert parse_bom(path, issues) == []
        assert len(issues) == 1
        assert "thickness" in issues[0].detail


class TestParseIl:
    def test_reads_quantity_and_assembly_only(self, tmp_path):
        path = write_csv(
            tmp_path,
            "IL-8701-011.csv",
            [
                "1|1|BUS SECTION 11A-11B|8701-01101-I|",
                "2|3|BUS SECTION 11B-11C|8701-01102-I|",
            ],
        )
        lines = parse_il(path)
        assert [line.assembly_number for line in lines] == ["8701-01101-I", "8701-01102-I"]
        assert [line.assembly_quantity for line in lines] == [Decimal(1), Decimal(3)]

    def test_blank_assembly_number_is_an_issue(self, tmp_path):
        path = write_csv(tmp_path, "IL-8701-011.csv", ["1|1|SOMETHING||"])
        issues: list = []
        assert parse_il(path, issues) == []
        assert "blank assembly number" in issues[0].detail
