"""SPEC PHASE 4 classification and PHASE 5 value formatting."""

from __future__ import annotations

import re
from decimal import Decimal

from .models import (
    DOES_NOT_FIT,
    FITS,
    THICKNESS_EIGHTH,
    THICKNESS_OTHER,
    THICKNESS_THREE_SIXTEENTH,
)

# Individual parts appear on the IL but have no BOM of their own, because they
# are single pieces cut from a standard sheet rather than assemblies. Two
# families are recognised:
#   JB-2724-06    -- JB parts, matched on the prefix
#   8701-300-I    -- the 300 series: three digits with no leading zero
# A bus section is 8701-01101-I: five digits *with* a leading zero, so it never
# matches these patterns and a genuinely missing bus section BOM is still
# flagged rather than quietly turned into one standard sheet.
INDIVIDUAL_PART_PATTERNS = (
    re.compile(r"^JB-", re.IGNORECASE),
    re.compile(r"^[A-Za-z0-9]+-[1-9]\d{2}-I$", re.IGNORECASE),
)

# Every individual part is cut from the same stock.
STANDARD_THICKNESS = Decimal("0.125")
STANDARD_WIDTH = Decimal("60")
STANDARD_HEIGHT = Decimal("120")


def is_individual_part(assembly_number: str) -> bool:
    """True for a 300-series or JB part, which needs no BOM of its own."""
    value = assembly_number.strip()
    return any(pattern.match(value) for pattern in INDIVIDUAL_PART_PATTERNS)

TOLERANCE = Decimal("0.005")
NOMINAL_EIGHTH = Decimal("0.125")
NOMINAL_THREE_SIXTEENTH = Decimal("0.1875")

# The largest sheet the Trumpf actually takes is 61.5 x 120. Orientation does
# not matter, so the sheet's smaller and larger dimensions are compared rather
# than its width and height. Both limits are inclusive: 61.5x120 fits, anything
# over it is an F part.
TRUMPF_SHORT_LIMIT = Decimal("61.5")
TRUMPF_LONG_LIMIT = Decimal("120")


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
