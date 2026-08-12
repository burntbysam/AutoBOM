from __future__ import annotations

from decimal import Decimal

import pytest

from autobom.core.classify import (
    classify_thickness,
    fits_trumpf,
    format_number,
    format_size,
    is_individual_part,
    quantity_value,
)
from autobom.core.models import (
    DOES_NOT_FIT,
    FITS,
    THICKNESS_EIGHTH,
    THICKNESS_OTHER,
    THICKNESS_THREE_SIXTEENTH,
)


class TestClassifyThickness:
    @pytest.mark.parametrize(
        "value,expected",
        [
            # 1/8" window: 0.120 to 0.130 inclusive.
            ("0.125", THICKNESS_EIGHTH),
            ("0.120", THICKNESS_EIGHTH),
            ("0.130", THICKNESS_EIGHTH),
            ("0.1199", THICKNESS_OTHER),
            ("0.1301", THICKNESS_OTHER),
            # 3/16" window: 0.1825 to 0.1925 inclusive.
            ("0.1875", THICKNESS_THREE_SIXTEENTH),
            ("0.1825", THICKNESS_THREE_SIXTEENTH),
            ("0.1925", THICKNESS_THREE_SIXTEENTH),
            ("0.190", THICKNESS_THREE_SIXTEENTH),
            ("0.1824", THICKNESS_OTHER),
            ("0.1926", THICKNESS_OTHER),
            # Well outside both windows.
            ("0.250", THICKNESS_OTHER),
            ("0.063", THICKNESS_OTHER),
        ],
    )
    def test_windows(self, value, expected):
        assert classify_thickness(Decimal(value)) == expected


class TestFitsTrumpf:
    @pytest.mark.parametrize(
        "width,height,expected",
        [
            # The machine's real maximum is 61.5 x 120, inclusive.
            ("60", "120", FITS),
            ("61.5", "120", FITS),
            ("61.5", "61.5", FITS),
            ("48", "96", FITS),
            # Orientation must not matter.
            ("120", "60", FITS),
            ("120", "61.5", FITS),
            # Smaller dimension over 61.5.
            ("61.51", "120", DOES_NOT_FIT),
            ("72", "120", DOES_NOT_FIT),
            ("120", "72", DOES_NOT_FIT),
            # Larger dimension over 120.
            ("60", "120.1", DOES_NOT_FIT),
            ("60", "144", DOES_NOT_FIT),
            ("72", "144", DOES_NOT_FIT),
            # Was T under the old 133.5 limit; the machine cannot take it.
            ("60", "133.13", DOES_NOT_FIT),
            ("60", "133.5", DOES_NOT_FIT),
        ],
    )
    def test_limits(self, width, height, expected):
        assert fits_trumpf(Decimal(width), Decimal(height)) == expected

    def test_the_exact_maximum_sheet_fits(self):
        assert fits_trumpf(Decimal("61.5"), Decimal("120")) == FITS

    def test_a_hair_over_either_limit_does_not(self):
        assert fits_trumpf(Decimal("61.6"), Decimal("120")) == DOES_NOT_FIT
        assert fits_trumpf(Decimal("61.5"), Decimal("120.01")) == DOES_NOT_FIT

    def test_independent_of_thickness(self):
        # fits_trumpf takes no thickness argument at all — the SPEC requires
        # the two classifications stay separate.
        assert fits_trumpf(Decimal(60), Decimal(120)) == FITS


class TestIsIndividualPart:
    @pytest.mark.parametrize(
        "value",
        [
            "JB-2724-06",
            "JB-2502-02",
            "JB-2706-16",
            "jb-2724-06",
            "8701-300-I",
            "8701-306-I",
            "8701-999-I",
            "8701-300-i",
        ],
    )
    def test_recognised(self, value):
        assert is_individual_part(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            # Bus sections: five digits with a leading zero.
            "8701-01101-I",
            "8701-02109-I",
            # A leading zero means it is not a 300-series number.
            "8701-030-I",
            # Missing the -I suffix.
            "8701-300",
            # Four digits is not the 300 series.
            "8701-3001-I",
            "",
        ],
    )
    def test_not_recognised(self, value):
        assert is_individual_part(value) is False

    def test_surrounding_whitespace_is_ignored(self):
        assert is_individual_part("  8701-300-I  ") is True


class TestFormatting:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("60", "60"),
            ("60.0", "60"),
            ("60.00", "60"),
            ("133.13", "133.13"),
            ("133.130", "133.13"),
            ("144", "144"),
        ],
    )
    def test_format_number(self, value, expected):
        assert format_number(Decimal(value)) == expected

    def test_format_size(self):
        assert format_size(Decimal("60.0"), Decimal("120.0")) == "60x120"
        assert format_size(Decimal("60"), Decimal("133.13")) == "60x133.13"

    def test_quantity_value_is_int_when_whole(self):
        assert quantity_value(Decimal("4")) == 4
        assert isinstance(quantity_value(Decimal("4.0")), int)
        assert quantity_value(Decimal("4.5")) == 4.5
