import json
from decimal import ROUND_HALF_EVEN, Decimal

from django import template

register = template.Library()


@register.filter
def short(value, keep=6):
    """Middle-truncate a hash or address: 0x1234ab…cd5678. Put the full value in a title."""
    value = str(value)
    if len(value) <= keep * 2 + 1:
        return value
    return f"{value[:keep]}…{value[-keep:]}"


@register.filter
def units(value):
    """Group thousands without dropping or rounding any of a token amount's decimals."""
    whole, _, fraction = f"{value:f}".partition(".")
    grouped = f"{int(whole):,}"
    return f"{grouped}.{fraction}" if fraction else grouped


DISPLAY_PLACES = Decimal("0.000001")


@register.filter
def amount(value):
    """Readable token amount: at most 6 decimals, trailing zeros dropped. Pair with a title
    holding the exact `units` value, since rounding is for display only."""
    rounded = value.quantize(DISPLAY_PLACES, rounding=ROUND_HALF_EVEN)
    whole, _, fraction = f"{rounded:f}".partition(".")
    fraction = fraction.rstrip("0")
    grouped = f"{int(whole):,}"
    return f"{grouped}.{fraction}" if fraction else grouped


@register.filter
def address_url(chain, address):
    """Explorer link for an address on a chain: {{ chain|address_url:address }}."""
    return chain.address_url(address)


@register.filter
def as_json(value):
    """Compact, key-sorted JSON, as stored request parameters should be cited."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
