"""Shared helpers. Domain modules import from here; this module imports from no module."""

import decimal

# Token amounts are integers up to 2**256 - 1 (78 digits) scaled by up to ~77 decimals.
# The default decimal context rounds at 28 digits, so every conversion uses this one.
AMOUNT_CONTEXT = decimal.Context(prec=160)


def to_units(raw_amount, decimals):
    """Raw on-chain integer amount to exact human units (e.g. 1500000, 6 -> 1.5)."""
    return AMOUNT_CONTEXT.scaleb(decimal.Decimal(int(raw_amount)), -decimals)


def to_raw(units, decimals):
    """Human units to the raw integer amount; rejects precision finer than the token allows."""
    scaled = AMOUNT_CONTEXT.scaleb(decimal.Decimal(str(units)), decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{units} has more than {decimals} decimal places")
    return int(scaled)
