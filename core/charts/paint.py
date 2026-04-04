from django.utils import timezone
from core.models import Order, OrderSchedule, ChartConfig
from core.charts.general import build_general_row
from core.charts._base import is_stopped, due_key


def _get_paint_colors(order):
    """Собирает цвета краски из Contract.spec_json (mdf_paint_list по всем группам)."""
    contract = getattr(order, "contract", None)
    if not contract:
        return []
    spec = contract.spec_json or []
    colors = []
    for group in spec:
        for item in group.get("mdf_paint_list", []):
            color = (item.get("color") or "").strip()
            value = (item.get("value") or "").strip()   # тип/фреза
            area  = (item.get("area")  or "").strip().replace(",", ".")
            if color or value:
                colors.append({
                    "name":  color or value,
                    "m2":    area or "—",
                    "fresa": value if color else "—",
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
        .select_related("calculation", "contract")   # ← contract вместо facade_sheet
    )

    rows = []
    for o in qs:
        sch, _ = OrderSchedule.objects.get_or_create(order=o)
        if is_stopped(sch):
            continue

        r = build_general_row(o, today, _cfg_general, _cfg_paint, tab_key="paint")

        if r.get("paint_m2") in (None, 0, "", "—"):
            continue
        if sch.status_paint != "ВЫДАН В ЦЕХ":
            continue

        r["paint_colors"] = _get_paint_colors(o)
        rows.append(r)

    rows.sort(key=due_key)

    for r in rows:
        r.pop("_is_overdue", None)
        r.pop("_is_done",    None)
        r.pop("_due_min",    None)
        r.pop("_has_ldsp",   None)
        r.pop("_has_film",   None)
        r.pop("_has_paint",  None)

    return {"tiles": rows}
