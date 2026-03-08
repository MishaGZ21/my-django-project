from django.utils import timezone
from core.models import Order, OrderSchedule, ChartConfig
from core.charts.general import build_general_row
from core.charts._base import is_stopped, due_key

def get_data(request):
    today = timezone.localdate()

    # настройки именно для вкладки technologist (если таблица ChartConfig у тебя общая)
    def _cfg_for_order(signed_date):
        return (
            ChartConfig.objects
            .filter(tab="technologist", enabled=True, effective_from__lte=signed_date)
            .order_by("-effective_from", "-id")
            .first()
        )
        
    def _cfg_general(signed_date):
        return (
            ChartConfig.objects
            .filter(tab="general", enabled=True, effective_from__lte=signed_date)
            .order_by("-effective_from", "-id")
            .first()
        )
    
    def _cfg_tech(signed_date):
        return (
            ChartConfig.objects
            .filter(tab="technologist", enabled=True, effective_from__lte=signed_date)
            .order_by("-effective_from", "-id")
            .first()
        )
    

    qs = (
        Order.objects
        .filter(main_contract_signed=True, contract_signed_at__isnull=False)
        .select_related("calculation")
        .order_by("-id")
    )

    rows = []
    for o in qs:
        sch, _ = OrderSchedule.objects.get_or_create(order=o)

        # СТОП/ОТЛОЖЕН — показываем только в общем графике
        if is_stopped(sch):
            continue

        # Если уже "выдан в цех" — из технолога убираем
        if (
            sch.status_ldsp == "ВЫДАН В ЦЕХ"
            or sch.status_film == "ВЫДАН В ЦЕХ"
            or sch.status_paint == "ВЫДАН В ЦЕХ"
        ):
            continue

        r = build_general_row(o, today, _cfg_general, _cfg_tech, tab_key="technologist")
        rows.append(r)

    # просроченные вверх (по min days_left)
    rows.sort(key=due_key)

    # убираем служебные поля (как в general.get_data)
    for r in rows:
        r.pop("_is_overdue", None)
        r.pop("_is_done", None)
        r.pop("_due_min", None)
        r.pop("_has_ldsp", None)
        r.pop("_has_film", None)
        r.pop("_has_paint", None)

    return {"tiles": rows}
