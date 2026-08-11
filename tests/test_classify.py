from __future__ import annotations

from decimal import Decimal

import pytest

from autobom.core.classify import (
    classify_thickness,
    fits_trumpf,
    format_number,
    format_size,
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
            ("60", "120", FITS),
            ("60", "133.5", FITS),
            ("60", "133.13", FITS),
            # Orientation must not matter.
            ("120", "60", FITS),
            ("133.5", "60", FITS),
            # Smaller dimension over 60.
            ("72", "120", DOES_NOT_FIT),
            ("120", "72", DOES_NOT_FIT),
            # Larger dimension over 133.5.
            ("60", "144", DOES_NOT_FIT),
            ("60", "133.51", DOES_NOT_FIT),
            ("72", "144", DOES_NOT_FIT),
        ],
    )
    def test_limits(self, width, height, expected):
        assert fits_trumpf(Decimal(width), Decimal(height)) == expected

    def test_independent_of_thickness(self):
        # fits_trumpf takes no thickness argument at all — the SPEC requires
        # the two classifications stay separate.
        assert fits_trumpf(Decimal(60), Decimal(120)) == FITS


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
