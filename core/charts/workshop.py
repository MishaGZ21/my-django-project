from django.utils import timezone
from core.models import Order, OrderSchedule, ChartConfig
from core.charts.general import build_general_row
from core.charts._base import is_stopped, due_key


def get_data(request):
    today = timezone.localdate()

    def _cfg_general(signed_date):
        return (
            ChartConfig.objects
            .filter(tab="general", enabled=True, effective_from__lte=signed_date)
            .order_by("-effective_from", "-id")
            .first()
        )

    def _cfg_workshop(signed_date):
        return (
            ChartConfig.objects
            .filter(tab="workshop", enabled=True, effective_from__lte=signed_date)
            .order_by("-effective_from", "-id")
            .first()
        )

    qs = (
        Order.objects
        .filter(main_contract_signed=True, contract_signed_at__isnull=False)
        .order_by("-id")
        .select_related("calculation")
    )

    rows = []
    for o in qs:
        sch, _ = OrderSchedule.objects.get_or_create(order=o)

        if is_stopped(sch):
            continue

        # заказ появляется в цехе после "ВЫДАН В ЦЕХ" хотя бы по одному материалу
        in_workshop = (
            sch.status_ldsp == "ВЫДАН В ЦЕХ" or
            sch.status_film == "ВЫДАН В ЦЕХ" or
            sch.status_paint == "ВЫДАН В ЦЕХ"
        )
        if not in_workshop:
            continue

        r = build_general_row(o, today, _cfg_general, _cfg_workshop, tab_key="workshop")
        rows.append(r)

    rows.sort(key=due_key)

    # убираем служебные поля
    for r in rows:
        r.pop("_is_overdue", None)
        r.pop("_is_done", None)
        r.pop("_due_min", None)
        r.pop("_has_ldsp", None)
        r.pop("_has_film", None)
        r.pop("_has_paint", None)

    return {"tiles": rows}
