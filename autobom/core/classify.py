"""SPEC PHASE 4 classification and PHASE 5 value formatting."""

from __future__ import annotations

from decimal import Decimal

from .models import (
    DOES_NOT_FIT,
    FITS,
    THICKNESS_EIGHTH,
    THICKNESS_OTHER,
    THICKNESS_THREE_SIXTEENTH,
)

TOLERANCE = Decimal("0.005")
NOMINAL_EIGHTH = Decimal("0.125")
NOMINAL_THREE_SIXTEENTH = Decimal("0.1875")

# Trumpf bed limits; orientation does not matter, so the sheet's smaller and
# larger dimensions are compared rather than width and height.
TRUMPF_SHORT_LIMIT = Decimal("60")
TRUMPF_LONG_LIMIT = Decimal("133.5")


def classify_thickness(thickness: Decimal) -> str:
    """Bucket a thickness into 1/8", 3/16" or OTHER (+/- 0.005 inclusive)."""
    if abs(thickness - NOMINAL_EIGHTH) <= TOLERANCE:
        return THICKNESS_EIGHTH
    if abs(thickness - NOMINAL_THREE_SIXTEENTH) <= TOLERANCE:
        return THICKNESS_THREE_SIXTEENTH
    return THICKNESS_OTHER


def fits_trumpf(width: Decimal, height: Decimal) -> str:
    """T when the sheet fits the Trumpf in either orientation, otherwise F."""
    shorter, longer = sorted((width, height))
    if shorter <= TRUMPF_SHORT_LIMIT and longer <= TRUMPF_LONG_LIMIT:
        return FITS
    return DOES_NOT_FIT


def format_number(value: Decimal) -> str:
    """Render a Decimal without a trailing ``.0`` but keeping real decimals.

    60 -> ``60``, 60.0 -> ``60``, 133.13 -> ``133.13``.
    """
    quantized = value.normalize()
    if quantized == quantized.to_integral_value():
        quantized = quantized.to_integral_value()
    return format(quantized, "f")


def format_size(width: Decimal, height: Decimal) -> str:
    return f"{format_number(width)}x{format_number(height)}"


def quantity_value(quantity: Decimal) -> int | float:
    """Return an int for whole quantities so Excel shows ``4`` not ``4.0``."""
    if quantity == quantity.to_integral_value():
        return int(quantity)
    return float(quantity)
