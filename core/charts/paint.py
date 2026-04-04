from django.utils import timezone
from core.models import Order, OrderSchedule, ChartConfig
from core.charts.general import build_general_row
from core.charts._base import is_stopped, due_key


def _get_paint_colors(order):
    """Собирает список цветов краски из FacadeSheet (до 10 цветов)."""
    fs = getattr(order, "facade_sheet", None)
    if not fs:
        return []
    colors = []
    for i in range(1, 11):
        name  = getattr(fs, f"paint_color{i}_name",  None)
        m2    = getattr(fs, f"paint_color{i}_m2",    None)
        fresa = getattr(fs, f"paint_color{i}_fresa", None)
        if name and str(name).strip():
            colors.append({
                "name":  str(name).strip(),
                "m2":    str(m2) if m2 is not None else "—",
                "fresa": str(fresa).strip() if fresa and str(fresa).strip() else "—",
            })
    return colors


def get_data(request):
    today = timezone.localdate()

    def _cfg_general(signed_date):
        return (
            ChartConfig.objects
            .filter(tab="general", enabled=True, effective_from__lte=signed_date)
            .order_by("-effective_from", "-id")
            .first()
        )

    def _cfg_paint(signed_date):
        return (
            ChartConfig.objects
            .filter(tab="paint", enabled=True, effective_from__lte=signed_date)
            .order_by("-effective_from", "-id")
            .first()
        )

    qs = (
        Order.objects
        .filter(main_contract_signed=True, contract_signed_at__isnull=False)
        .order_by("-id")
        .select_related("calculation", "facade_sheet")   # ← добавлен facade_sheet
    )

    rows = []
    for o in qs:
        sch, _ = OrderSchedule.objects.get_or_create(order=o)
        if is_stopped(sch):
            continue

        r = build_general_row(o, today, _cfg_general, _cfg_paint, tab_key="paint")

        # показываем только если есть краска
        if r.get("paint_m2") in (None, 0, "", "—"):
            continue

        # показываем только если выдано в цех покраски
        if sch.status_paint != "ВЫДАН В ЦЕХ":
            continue

        # ← добавляем цвета краски и фрезы
        r["paint_colors"] = _get_paint_colors(o)

        rows.append(r)

    rows.sort(key=due_key)

    # убираем служебные поля
    for r in rows:
        r.pop("_is_overdue", None)
        r.pop("_is_done",    None)
        r.pop("_due_min",    None)
        r.pop("_has_ldsp",   None)
        r.pop("_has_film",   None)
        r.pop("_has_paint",  None)

    return {"tiles": rows}
