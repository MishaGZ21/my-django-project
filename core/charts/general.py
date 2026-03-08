from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from core.models import Order, ChartConfig, OrderSchedule
from core.utils import add_workdays_kz, get_kz_holidays, shift_workdays_kz

DONE = {"ГОТОВО", "ВЫДАН"}
STOP = {"СТОП"}

def _get_facade_m2_from_calc(calc):
    paint = Decimal("0")
    film = Decimal("0")

    facade_items = getattr(calc, "facade_items", None)
    if not facade_items:
        return paint, film

    for fi in facade_items.all():
        area = getattr(fi, "area", None)
        if not area:
            continue

        try:
            area_dec = Decimal(str(area))
        except Exception:
            continue

        pi = getattr(fi, "price_item", None)
        grp = getattr(pi, "group", None) if pi else None
        title = (getattr(grp, "title", "") or "").strip() if grp else ""

        if title == "Фасады (краска)":
            paint += area_dec
        elif title == "Фасады (плёнка)":
            film += area_dec

    return paint, film


def _calc_ldsp_sheets(order):
    """
    Берём ЛДСП так же как бухгалтерия (чтобы не гадать склад).
    """
    try:
        from core.views_accounting import _calc_live_numbers
        need = _calc_live_numbers(order)
        return Decimal(str(need.get("ldsp", 0) or 0))
    except Exception:
        return Decimal("0")


def _material_status(order, has_material: bool, field_name: str):
    if not has_material:
        return "—"
    val = getattr(order, field_name, "—") or "—"
    if val == "—":
        return "Ожидает"
    return val

def workdays_left_kz(from_date, to_date):
    """
    Считает количество рабочих дней от from_date (не включая) до to_date (включая),
    исключая выходные и праздники KZ.
    Если срок уже прошёл/сегодня — вернёт 0.
    """
    if not to_date or to_date <= from_date:
        return 0

    cur = from_date
    left = 0
    # используем ту же логику праздников (БД/настройки), что и в add_workdays_kz
    holidays_cache = {}

    while cur < to_date:
        cur = cur + timedelta(days=1)

        # выходные
        if cur.weekday() >= 5:
            continue

        y = cur.year
        if y not in holidays_cache:
            holidays_cache[y] = get_kz_holidays(y)

        if cur in holidays_cache[y]:
            continue

        left += 1

    return left



def build_general_row(o, today, cfg_general_for_order, cfg_tab_for_order=None, tab_key="general"):
    """
    Возвращает одну строку (dict) для общего графика/плиток.

    Логика:
    - Якорь (base_due_*) хранится в OrderSchedule и рассчитывается по настройкам GENERAL.
    - manual override (due_*_override) трактуем как изменение якоря (то есть двигает ВСЕ графики).
    - extra_days_* добавляются к якорю (двигают ВСЕ графики одинаково).
    - Для вкладок technologist/workshop/paint/film: due = base_general + extra + offset(tab-general) в рабочих днях.
    """

    calc = getattr(o, "calculation", None)

    ldsp_qty = _calc_ldsp_sheets(o)
    paint_m2 = Decimal("0")
    film_m2 = Decimal("0")

    if calc is not None:
        paint_m2, film_m2 = _get_facade_m2_from_calc(calc)

    has_ldsp = ldsp_qty > 0
    has_paint = paint_m2 > 0
    has_film = film_m2 > 0

    start = o.contract_signed_at

    # schedule (создаём, если нет)
    sch = getattr(o, "schedule", None)
    if sch is None:
        sch, _ = OrderSchedule.objects.get_or_create(order=o)

    extra_ldsp = sch.extra_days_ldsp or 0
    extra_film = sch.extra_days_film or 0
    extra_paint = sch.extra_days_paint or 0

    # cfg для общего графика (это база/якорь)
    cfg_general = cfg_general_for_order(start)
    gen_days_ldsp = (cfg_general.days_ldsp if cfg_general else 10)
    gen_days_film = (cfg_general.days_film if cfg_general else 10)
    gen_days_paint = (cfg_general.days_paint if cfg_general else 14)

    # cfg для текущей вкладки (если не передан — считаем как general)
    if cfg_tab_for_order is None:
        cfg_tab_for_order = cfg_general_for_order

    cfg_tab = cfg_tab_for_order(start)
    tab_days_ldsp = (cfg_tab.days_ldsp if cfg_tab else gen_days_ldsp)
    tab_days_film = (cfg_tab.days_film if cfg_tab else gen_days_film)
    tab_days_paint = (cfg_tab.days_paint if cfg_tab else gen_days_paint)

    def _get_or_init_base_due(has_mat: bool, base_field: str, override_date, gen_days: int):
        """
        Возвращает base_due по материалу:
        - если override есть -> это новый якорь (сохраняем в base_field)
        - иначе если base_field заполнен -> берём его
        - иначе -> считаем от start + gen_days и сохраняем в base_field
        """
        if not has_mat or not start:
            return None

        current_base = getattr(sch, base_field, None)

        if override_date:
            if current_base != override_date:
                setattr(sch, base_field, override_date)
                sch.save(update_fields=[base_field])
            return override_date

        if current_base:
            return current_base

        # посчитать якорь по GENERAL
        computed = add_workdays_kz(start, int(gen_days))
        setattr(sch, base_field, computed)
        sch.save(update_fields=[base_field])
        return computed

    # 1) получаем якоря GENERAL (по материалам)
    base_ldsp = _get_or_init_base_due(has_ldsp, "base_due_ldsp", sch.due_ldsp_override, gen_days_ldsp)
    base_film = _get_or_init_base_due(has_film, "base_due_film", sch.due_film_override, gen_days_film)
    base_paint = _get_or_init_base_due(has_paint, "base_due_paint", sch.due_paint_override, gen_days_paint)

    def _final_due_for_tab(has_mat: bool, base_due, extra_days: int, tab_days: int, gen_days: int):
        if not has_mat or not base_due:
            return None

        # extra_days двигают ВСЕ графики одинаково
        due = shift_workdays_kz(base_due, int(extra_days or 0))

        # offset = tab - general (может быть отрицательным)
        offset = int(tab_days) - int(gen_days)
        if offset:
            due = shift_workdays_kz(due, offset)

        return due

    # 2) финальные due для текущей вкладки
    due_ldsp = _final_due_for_tab(has_ldsp, base_ldsp, extra_ldsp, tab_days_ldsp, gen_days_ldsp)
    due_film = _final_due_for_tab(has_film, base_film, extra_film, tab_days_film, gen_days_film)
    due_paint = _final_due_for_tab(has_paint, base_paint, extra_paint, tab_days_paint, gen_days_paint)

    # STOP: если стоп активен, "замораживаем" расчёт остатка дней
    freeze_from = today
    if sch and sch.stop_until and today < sch.stop_until:
        freeze_from = sch.stop_until

    stop_left = None
    if sch and sch.stop_until and today < sch.stop_until:
        stop_left = workdays_left_kz(today, sch.stop_until)

    def fmt_status(base_status: str) -> str:
        if stop_left is not None:
            return f"ОТЛОЖЕН ({stop_left})"
        return base_status

    # Остаток рабочих дней считаем от freeze_from
    ldsp_days_left = workdays_diff_kz(freeze_from, due_ldsp) if due_ldsp else None
    film_days_left = workdays_diff_kz(freeze_from, due_film) if due_film else None
    paint_days_left = workdays_diff_kz(freeze_from, due_paint) if due_paint else None

    # статусы из schedule
    status_ldsp = fmt_status((sch.status_ldsp if sch else "ОЖИДАЕТ")) if has_ldsp else "—"
    status_film = fmt_status((sch.status_film if sch else "ОЖИДАЕТ")) if has_film else "—"
    status_paint = fmt_status((sch.status_paint if sch else "ОЖИДАЕТ")) if has_paint else "—"

    def overdue(due, st):
        if not due:
            return False
        if st in DONE or st in STOP:
            return False
        return today > due

    is_overdue = (
        overdue(due_ldsp, status_ldsp) or
        overdue(due_film, status_film) or
        overdue(due_paint, status_paint)
    )

    def finished(has_mat, st):
        if not has_mat:
            return True
        return st in DONE or st in STOP

    is_done = (
        finished(has_ldsp, status_ldsp) and
        finished(has_film, status_film) and
        finished(has_paint, status_paint)
    )

    dates = [d for d in (due_ldsp, due_film, due_paint) if d]
    due_min = min(dates) if dates else start

    return {
        "order_id": o.id,
        "order_number": o.order_number,
        "customer": (o.customer_name or "").strip(),
        "created_at": start.strftime("%d.%m.%Y") if start else "—",
        "ldsp_qty": str(ldsp_qty) if has_ldsp else "—",
        "paint_m2": str(paint_m2) if has_paint else "—",
        "film_m2": str(film_m2) if has_film else "—",
        "due_ldsp": due_ldsp.strftime("%d.%m.%Y") if due_ldsp else "—",
        "due_film": due_film.strftime("%d.%m.%Y") if due_film else "—",
        "due_paint": due_paint.strftime("%d.%m.%Y") if due_paint else "—",
        "note": o.chart_note or "",
        "ldsp_days_left": ldsp_days_left,
        "film_days_left": film_days_left,
        "paint_days_left": paint_days_left,
        "status_ldsp": status_ldsp,
        "status_film": status_film,
        "status_paint": status_paint,

        # служебное для сортировки
        "_is_overdue": is_overdue,
        "_is_done": is_done,
        "_due_min": due_min.isoformat() if due_min else "",
        "_has_ldsp": has_ldsp,
        "_has_film": has_film,
        "_has_paint": has_paint,
    }






def get_data(request):
    """
    Общий график:
    - только заказы с подписанным основным договором
    - старт = contract_signed_at
    - сроки: отдельно ЛДСП, отдельно Плёнка, отдельно Краска
    """
    today = timezone.localdate()
    
    def _cfg_for_order(signed_date):
        return (ChartConfig.objects
                .filter(tab="general", enabled=True, effective_from__lte=signed_date)
                .order_by("-effective_from", "-id")
                .first())


    qs = (
        Order.objects
        .filter(main_contract_signed=True, contract_signed_at__isnull=False)
        .select_related("calculation")
    )

    rows = []
    for o in qs:
        rows.append(build_general_row(o, today, _cfg_for_order, tab_key="general"))

    # просроченные вверх, готовые вниз
    rows.sort(key=lambda r: (r["_is_done"], not r["_is_overdue"], r["_due_min"]))

    for r in rows:
        r.pop("_is_overdue", None)
        r.pop("_is_done", None)
        r.pop("_due_min", None)
        r.pop("_has_ldsp", None)
        r.pop("_has_film", None)
        r.pop("_has_paint", None)

    return {"rows": rows}


def workdays_diff_kz(from_date, to_date):
    """
    Возвращает signed число рабочих дней от from_date до to_date:
    - будущее: +N
    - сегодня: 0
    - просрочка: -N
    """
    if not from_date or not to_date:
        return None

    if to_date == from_date:
        return 0

    # если срок в будущем
    if to_date > from_date:
        return workdays_left_kz(from_date, to_date)

    # если срок в прошлом: считаем сколько рабочих дней прошло после срока до today
    # например: today=10, due=8 => -2 (с учётом выходных/праздников)
    return -workdays_left_kz(to_date, from_date)
