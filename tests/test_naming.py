from __future__ import annotations

import pytest

from autobom.core.naming import default_workbook_name, job_number


class TestJobNumber:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("8701-01101-I.csv", "8701"),
            ("8701-02109-I.csv", "8701"),
            ("8551-07127-I.csv", "8551"),
            ("  8701-01101-I.csv  ", "8701"),
            ("/some/path/8701-01101-I.csv", "8701"),
        ],
    )
    def test_extracts_the_leading_job(self, filename, expected):
        assert job_number(filename) == expected


class TestDefaultWorkbookName:
    def test_uses_spaces_not_underscores(self):
        name = default_workbook_name(["8701-01101-I.csv"])
        assert name == "8701 BOM Quantities.xlsx"
        assert "_" not in name

    def test_no_output_prefix(self):
        assert not default_workbook_name(["8701-01101-I.csv"]).startswith("OUTPUT")

    def test_one_job_across_many_boms(self):
        name = default_workbook_name(
            ["8701-01101-I.csv", "8701-02109-I.csv", "8701-01103-I.csv"]
        )
        assert name == "8701 BOM Quantities.xlsx"

    def test_two_jobs_drops_the_number_rather_than_guessing(self):
        name = default_workbook_name(["8701-01101-I.csv", "8551-07127-I.csv"])
        assert name == "BOM Quantities.xlsx"

    def test_no_files(self):
        assert default_workbook_name([]) == "BOM Quantities.xlsx"

    def test_always_xlsx(self):
        assert default_workbook_name(["8701-01101-I.csv"]).endswith(".xlsx")
