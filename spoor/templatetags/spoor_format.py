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
