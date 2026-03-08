def _to_str(v):
    if v is None:
        return ""
    return str(v)

def human_diff(instance, old_values: dict, fields: list[str]) -> str:
    """Формирует человекочитаемый список изменений по указанным полям."""
    lines = []
    for f in fields:
        before = old_values.get(f, None)
        after = getattr(instance, f, None)
        if before != after:
            lines.append(f"• {f}: «{_to_str(before)}» → «{_to_str(after)}»")
    return "\n".join(lines)


from datetime import date, timedelta
from django.conf import settings

def _parse_dates(dates):
    out = set()
    for s in dates or []:
        try:
            parts = [int(x) for x in str(s).split("-")]
            out.add(date(parts[0], parts[1], parts[2]))
        except Exception:
            continue
    return out

def get_kz_holidays(year=None):
    """
    Возвращает множество date праздничных дней.
    Источник: БД (HolidayKZ). Если БД недоступна/пусто — fallback на settings.KZ_HOLIDAYS.
    """
    holidays = set()

    # 1) Пытаемся взять из БД
    try:
        from core.models import HolidayKZ
        qs = HolidayKZ.objects.all()
        if year:
            qs = qs.filter(date__year=year)
        holidays.update(qs.values_list("date", flat=True))
    except Exception:
        pass

    # 2) fallback на settings (не обязателен, но удобно)
    if not holidays:
        raw = getattr(settings, "KZ_HOLIDAYS", [])
        holidays.update(_parse_dates(raw))

    return holidays

def add_workdays_kz(start: date, days: int) -> date:
    """Добавляет рабочие дни, исключая суб/вс и праздники Казахстана (БД/настройки)."""
    remain = int(days)
    cur = start

    holidays_cache = {}  # year -> set(date)

    while remain > 0:
        cur += timedelta(days=1)

        if cur.weekday() >= 5:  # 5=суббота, 6=воскресенье
            continue

        y = cur.year
        if y not in holidays_cache:
            holidays_cache[y] = get_kz_holidays(y)

        if cur in holidays_cache[y]:
            continue

        remain -= 1

    return cur

def shift_workdays_kz(start: date, delta_days: int) -> date:
    """Сдвигает дату на delta_days рабочих дней (может быть отрицательным)."""
    delta = int(delta_days)
    if delta == 0:
        return start

    step = 1 if delta > 0 else -1
    remain = abs(delta)
    cur = start
    holidays = get_kz_holidays(start.year)

    while remain > 0:
        cur += timedelta(days=step)

        # если год поменялся — обновим праздники
        if cur.year != start.year:
            holidays = get_kz_holidays(cur.year)

        if cur.weekday() >= 5:
            continue
        if cur in holidays:
            continue
        remain -= 1

    return cur