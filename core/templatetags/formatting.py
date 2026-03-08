# core/templatetags/formatting.py
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django import template

register = template.Library()

def _to_decimal(val):
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return None

@register.filter
def fmt_money(val, currency="₸"):
    """
    12_345 -> '12 345 ₸'
    12_345.50 -> '12 345.5 ₸'
    12_345.00 -> '12 345 ₸'
    """
    q = _to_decimal(val)
    if q is None:
        return val
    q = q.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{q:,.2f}".replace(",", " ")
    s = s.rstrip("0").rstrip(".")  # убираем хвост .00 / .10 -> .1
    return f"{s} {currency}"

@register.filter
def fmt_num(val):
    """
    10.00 -> '10'
    10.50 -> '10.5'
    10.56 -> '10.56'
    """
    q = _to_decimal(val)
    if q is None:
        return val
    s = f"{q.normalize()}"
    # normalize может вывести в экспоненциальной форме — защитим:
    if "E" in s or "e" in s:
        s = f"{q:.2f}".rstrip("0").rstrip(".")
    return s
