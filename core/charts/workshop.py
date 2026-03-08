from core.models import Order, OrderSchedule
from core.charts.general import build_general_row
from core.charts._base import is_stopped, due_key

def get_data(request):
    qs = Order.objects.filter(main_contract_signed=True).order_by("-id").select_related()
    rows = []

    for o in qs:
        sch, _ = OrderSchedule.objects.get_or_create(order=o)
        if is_stopped(sch):
            continue

        # заказ появляется в цехе после "ВЫДАН В ЦЕХ"
        in_workshop = (
            sch.status_ldsp == "ВЫДАН В ЦЕХ"
            or sch.status_film == "ВЫДАН В ЦЕХ"
            or sch.status_paint == "ВЫДАН В ЦЕХ"
        )
        if not in_workshop:
            continue

        r = build_general_row(o, sch)
        rows.append(r)

    rows.sort(key=due_key)
    return {"tiles": rows}
