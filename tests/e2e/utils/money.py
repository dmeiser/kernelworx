"""Money/currency helpers for E2E assertions.

The frontend uses ``Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'})``
which produces strings like ``$12.50`` or ``$1,234.56``.  These helpers parse such
strings back into comparable numeric values so tests can assert exact amounts
without hard-coding formatted text.
"""

from __future__ import annotations

import re
from decimal import Decimal


def parse_currency(value: str) -> Decimal:
    """Parse a US currency string into a :class:`~decimal.Decimal`.

    Handles leading ``$``, comma separators, and negative values.

    Args:
        value: Currency text such as ``$12.50`` or ``($1.00)``.

    Returns:
        Decimal representation of the value.

    Raises:
        ValueError: If the text cannot be parsed as a currency value.
    """
    cleaned = value.strip()
    negative = cleaned.startswith('(') or cleaned.startswith('-')
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if not cleaned:
        raise ValueError(f"No numeric value found in currency string: {value!r}")
    amount = Decimal(cleaned)
    return -amount if negative else amount


def format_cents(cents: int) -> str:
    """Return a USD string for an integer number of cents.

    Args:
        cents: Amount in cents (e.g., ``1250`` for ``$12.50``).

    Returns:
        Formatted currency string such as ``$12.50``.
    """
    return f"${cents / 100:,.2f}"


def assert_currency(actual: str, expected_cents: int) -> None:
    """Assert that a displayed currency string equals an expected cent amount.

    Args:
        actual: Currency text displayed by the frontend.
        expected_cents: Expected value in cents.

    Raises:
        AssertionError: If the parsed value does not match.
    """
    parsed = parse_currency(actual)
    expected = Decimal(expected_cents) / 100
    assert parsed == expected, f"Expected {format_cents(expected_cents)}, got {actual!r} ({parsed})"
