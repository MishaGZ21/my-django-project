from django.utils import timezone
from core.models import Order, OrderSchedule, ChartConfig
from core.charts.general import build_general_row
from core.charts._base import is_stopped, due_key

DONE_STATUSES = {"ВЫДАН В ЦЕХ", "ГОТОВО", "ВЫДАН"}


def get_data(request):
    today = timezone.localdate()

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

        if is_stopped(sch):
            continue

        r = build_general_row(o, today, _cfg_general, _cfg_tech, tab_key="technologist")

        # Определяем какие материалы у этого заказа есть
        has_ldsp = r.get("_has_ldsp", False)
        has_film = r.get("_has_film", False)
        has_paint = r.get("_has_paint", False)

        # Собираем статусы только тех материалов которые есть у заказа
        material_statuses = []
        if has_ldsp:
            material_statuses.append(sch.status_ldsp)
        if has_film:
            material_statuses.append(sch.status_film)
        if has_paint:
            material_statuses.append(sch.status_paint)

        # Если нет материалов вообще — пропускаем
        if not material_statuses:
            continue

        # Убираем заказ только если ВСЕ материалы выданы/готовы
        all_done = all(s in DONE_STATUSES for s in material_statuses)
        if all_done:
            continue

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
