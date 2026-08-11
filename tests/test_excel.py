from __future__ import annotations

from decimal import Decimal

from openpyxl import load_workbook

from autobom.core.excel import COLUMNS, SHEET_ORDER, select_sheets, write_workbook
from autobom.core.models import Part


def part(number, thickness='1/8"', fits="T", quantity="1", size="60x120") -> Part:
    return Part(
        quantity=Decimal(quantity),
        part_number=number,
        thickness_label=thickness,
        size=size,
        fits_trumpf=fits,
    )


PARTS = [
    part("8701-1101-1", fits="F", size="72x120"),
    part("8701-1101-2"),
    part("8701-1101-3", thickness='3/16"'),
    part("8701-1101-4", thickness="OTHER"),
    part("8701-1101-5", thickness="OTHER", fits="F", size="72x144"),
    part("8701-1101-6", thickness='3/16"', fits="F", size="72x120"),
]


class TestSheetRouting:
    def test_eighth_and_t_only(self):
        sheets = select_sheets(PARTS)
        assert [p.part_number for p in sheets["1-8"]] == ["8701-1101-2"]

    def test_three_sixteenth_and_t_only(self):
        sheets = select_sheets(PARTS)
        assert [p.part_number for p in sheets["3-16"]] == ["8701-1101-3"]

    def test_f_parts_includes_all_thicknesses(self):
        sheets = select_sheets(PARTS)
        assert [p.part_number for p in sheets["F Parts"]] == [
            "8701-1101-1",
            "8701-1101-5",
            "8701-1101-6",
        ]

    def test_other_includes_both_fits(self):
        sheets = select_sheets(PARTS)
        assert [p.part_number for p in sheets["Other"]] == ["8701-1101-4", "8701-1101-5"]

    def test_all_contains_everything(self):
        assert len(select_sheets(PARTS)["All"]) == len(PARTS)

    def test_other_never_lands_on_a_thickness_sheet(self):
        sheets = select_sheets(PARTS)
        for name in ("1-8", "3-16"):
            assert all(p.thickness_label != "OTHER" for p in sheets[name])

    def test_f_never_lands_on_a_thickness_sheet(self):
        sheets = select_sheets(PARTS)
        for name in ("1-8", "3-16"):
            assert all(p.fits_trumpf == "T" for p in sheets[name])


class TestWorkbook:
    def test_exactly_five_sheets_in_order(self, tmp_path):
        path = write_workbook(PARTS, tmp_path / "out.xlsx")
        workbook = load_workbook(path)
        assert workbook.sheetnames == list(SHEET_ORDER)

    def test_headers_on_every_sheet(self, tmp_path):
        workbook = load_workbook(write_workbook(PARTS, tmp_path / "out.xlsx"))
        for name in SHEET_ORDER:
            header = [cell.value for cell in workbook[name][1]]
            assert header == list(COLUMNS)

    def test_no_extra_columns(self, tmp_path):
        workbook = load_workbook(write_workbook(PARTS, tmp_path / "out.xlsx"))
        for name in SHEET_ORDER:
            assert workbook[name].max_column == len(COLUMNS)

    def test_alignment_matches_spec(self, tmp_path):
        workbook = load_workbook(write_workbook(PARTS, tmp_path / "out.xlsx"))
        sheet = workbook["All"]
        expected = ["left", "center", "center", "center", "left"]
        for row in sheet.iter_rows(min_row=2, max_row=2):
            assert [cell.alignment.horizontal for cell in row] == expected

    def test_whole_quantities_written_as_integers(self, tmp_path):
        workbook = load_workbook(
            write_workbook([part("8701-1101-1", quantity="4")], tmp_path / "out.xlsx")
        )
        value = workbook["All"].cell(row=2, column=1).value
        assert value == 4
        assert isinstance(value, int)

    def test_empty_sheets_still_exist_with_headers(self, tmp_path):
        workbook = load_workbook(write_workbook([], tmp_path / "out.xlsx"))
        assert workbook.sheetnames == list(SHEET_ORDER)
        for name in SHEET_ORDER:
            assert workbook[name].max_row == 1
