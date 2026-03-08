# factory_app/core/views_accounting.py

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import escape
from calendar import monthrange

from decimal import Decimal
from datetime import timedelta
from datetime import datetime
from datetime import date
from django.utils import timezone
from django.db.models import Sum, Max, Min, F, Q
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_POST

from .models import PriceGroup, PriceItem, Payment, Order, Employee, SalaryPayment, ChartConfig
from .views import group_required, access_required, _calc_live_numbers
from core.models import HolidayKZ

RU_MONTHS = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

def recompute_employee_advance_balance(employee: Employee):
    """
    Пересчитать баланс авансов сотрудника на основе всех выплат:
    баланс = сумма всех авансов - сумма всех удержаний аванса из ЗП.
    """
    totals = SalaryPayment.objects.filter(employee=employee).aggregate(
        total_advance=Coalesce(
            Sum("net_amount", filter=Q(kind=SalaryPayment.TYPE_ADVANCE)),
            Decimal("0"),
        ),
        total_deducted=Coalesce(
            Sum("deduction_amount", filter=Q(kind=SalaryPayment.TYPE_SALARY)),
            Decimal("0"),
        ),
    )

    balance = totals["total_advance"] - totals["total_deducted"]
    if balance < 0:
        balance = Decimal("0")

    employee.advance_balance = balance
    employee.save(update_fields=["advance_balance"])


def _employee_to_dict(emp: Employee):
    """Упаковать сотрудника в JSON-вид для UI."""
    # --- Статус ЗП за текущий месяц ---
    today = timezone.localdate()
    y, m = today.year, today.month
    # Название месяца (Январь, Февраль, ...)
    month_label = RU_MONTHS.get(m, today.strftime("%B"))

    has_first = False
    has_second = False

    # salary_payments уже префетчен в accounting_staff_list
    for p in getattr(emp, "salary_payments", []).all():
        if p.kind != SalaryPayment.TYPE_SALARY:
            continue
        if not p.period_start or not p.period_end:
            continue
        if p.period_start.year != y or p.period_start.month != m:
            continue

        # Первая половина месяца
        if p.period_start.day == 1:
            has_first = True
        # Вторая половина месяца
        elif p.period_start.day == 16:
            has_second = True

    status_parts = []
    if has_first:
        status_parts.append("1/2")
    if has_second:
        status_parts.append("2/2")
    current_month_status = ", ".join(status_parts)

    return {
        "id": emp.id,
        "full_name": emp.full_name,
        "position": emp.position or "",
        "base_salary": float(emp.base_salary or 0),
        "deduction_amount": float(emp.deduction_amount or 0),
        "net_salary": float(emp.net_salary or 0),
        "advance_balance": float(emp.advance_balance or 0),
        "is_active": emp.is_active,
        # Новые поля для UI
        "current_month_label": month_label,
        "current_month_status": current_month_status,
    }

@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_staff_list(request):
    """
    JSON: список сотрудников и их базовые данные/последние выплаты.
    """
    show_inactive = request.GET.get("inactive") == "1"

    qs = Employee.objects.all().prefetch_related("salary_payments")
    if not show_inactive:
        qs = qs.filter(is_active=True)

    employees = [_employee_to_dict(e) for e in qs.order_by("full_name")]
    return JsonResponse({"employees": employees})




@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
@require_POST
def accounting_staff_create(request):
    """
    Создать нового сотрудника: ФИО, должность, оклад, фиксированное удержание.
    """
    from decimal import Decimal

    name = (request.POST.get("full_name") or "").strip()
    position = (request.POST.get("position") or "").strip()

    salary_raw = (request.POST.get("base_salary") or "").replace(" ", "").replace(",", ".")
    deduction_raw = (request.POST.get("deduction_amount") or "").replace(" ", "").replace(",", ".")

    if not name:
        return JsonResponse(
            {"ok": False, "error": "Укажите ФИО сотрудника."}, status=400
        )

    try:
        base_salary = Decimal(salary_raw or "0")
        if base_salary < 0:
            raise ValueError
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "Неверный формат оклада."}, status=400
        )

    try:
        deduction_amount = Decimal(deduction_raw or "0")
        if deduction_amount < 0:
            raise ValueError
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "Неверный формат удержания."}, status=400
        )

    emp = Employee.objects.create(
        full_name=name,
        position=position,
        base_salary=base_salary,
        deduction_amount=deduction_amount,
        is_active=True,
    )

    return JsonResponse({"ok": True, "employee": _employee_to_dict(emp)})


@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
@require_POST
def accounting_staff_update(request, employee_id):
    """
    Обновить параметры сотрудника:
    ФИО, должность, оклад, удержание.
    """
    from decimal import Decimal

    emp = get_object_or_404(Employee, pk=employee_id)

    name = (request.POST.get("full_name") or "").strip()
    position = (request.POST.get("position") or "").strip()

    salary_raw = (request.POST.get("base_salary") or "").replace(" ", "").replace(",", ".")
    deduction_raw = (request.POST.get("deduction_amount") or "").replace(" ", "").replace(",", ".")

    if not name:
        return JsonResponse(
            {"ok": False, "error": "Укажите ФИО сотрудника."}, status=400
        )

    try:
        base_salary = Decimal(salary_raw or "0")
        if base_salary < 0:
            raise ValueError
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "Неверный формат оклада."}, status=400
        )

    try:
        deduction_amount = Decimal(deduction_raw or "0")
        if deduction_amount < 0:
            raise ValueError
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "Неверный формат удержания."}, status=400
        )

    emp.full_name = name
    emp.position = position
    emp.base_salary = base_salary
    emp.deduction_amount = deduction_amount
    emp.save()

    emp.refresh_from_db()
    return JsonResponse({"ok": True, "employee": _employee_to_dict(emp)})


@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
@require_POST
def accounting_staff_pay(request, employee_id):
    """
    Зачислить ЗП (зарплату за половину месяца) с учётом аванса.
    ...
    """
    emp = get_object_or_404(Employee, pk=employee_id, is_active=True)

    # текущая дата выплаты
    today = timezone.localdate()

    # определяем период (1–15 / 16–конец месяца)
    y, m = today.year, today.month
    first_day = timezone.datetime(y, m, 1).date()
    last_day = timezone.datetime(y, m, monthrange(y, m)[1]).date()
    if today.day <= 15:
        period_start = first_day
        period_end = timezone.datetime(y, m, 15).date()
    else:
        period_start = timezone.datetime(y, m, 16).date()
        period_end = last_day

    # --- Защита от повторной выплаты за тот же период ---
    force = (request.POST.get("force") == "1")
    already_exists = SalaryPayment.objects.filter(
        employee=emp,
        kind=SalaryPayment.TYPE_SALARY,
        period_start=period_start,
        period_end=period_end,
    ).exists()

    if already_exists and not force:
        month_name = RU_MONTHS.get(period_end.month, period_end.strftime("%B"))
        if period_start.day == 1:
            period_label = f"1-15 {month_name}"
        else:
            period_label = f"16-{period_end.day} {month_name}"
        return JsonResponse(
            {
                "ok": False,
                "need_confirm": True,
                "error": f"Зарплата за период {period_label} этому сотруднику уже выплачена. Выдать ещё раз?",
            },
            status=400,
        )

    from decimal import Decimal

    def _parse_dec(value, default):
        value = (value or "").replace(" ", "").replace(",", ".")
        if not value:
            return default
        try:
            return Decimal(value)
        except Exception:
            return default

    # базовая ЗП за половину месяца: (оклад - удержание) / 2
    net_salary_month = emp.net_salary or Decimal("0")
    base_half = net_salary_month / Decimal("2")

    # можно переопределить сумму выплаты за период (если нужно)
    gross = _parse_dec(request.POST.get("amount"), base_half)
    if gross < 0:
        return JsonResponse(
            {"ok": False, "error": "Сумма начисления не может быть отрицательной."},
            status=400,
        )

    # рекомендуемая сумма аванса к удержанию
    default_advance_to_deduct = min(
        emp.advance_balance or Decimal("0"),
        gross,
    )

    # пользователь может ввести свою сумму удержания аванса
    advance_deduction = _parse_dec(
        request.POST.get("advance_deduction"),
        default_advance_to_deduct,
    )
    if advance_deduction < 0:
        advance_deduction = Decimal("0")

    # не даём удержать больше остатка аванса или начисления
    max_possible = min(emp.advance_balance or Decimal("0"), gross)
    if advance_deduction > max_possible:
        advance_deduction = max_possible

    # доп. вычеты (штрафы и т.п.)
    extra_deduction = _parse_dec(request.POST.get("extra_deduction"), Decimal("0"))
    if extra_deduction < 0:
        extra_deduction = Decimal("0")

    net_amount = gross - advance_deduction - extra_deduction
    if net_amount < 0:
        net_amount = Decimal("0")

    # для истории можно посчитать условный % удержаний (не обязателен)
    pct = Decimal("0")
    if gross > 0 and (advance_deduction + extra_deduction) > 0:
        pct = (advance_deduction + extra_deduction) / gross * Decimal("100")

    comment = (request.POST.get("comment") or "").strip()
    if not comment:
        month_name = RU_MONTHS.get(period_end.month, period_end.strftime("%B"))
        # первая половина месяца
        if period_start.day == 1:
            comment = f"ЗП 1-15 {month_name}"
        else:
            # вторая половина
            comment = f"ЗП 16-{period_end.day} {month_name}"

    SalaryPayment.objects.create(
        employee=emp,
        period_start=period_start,
        period_end=period_end,
        pay_date=today,
        kind=SalaryPayment.TYPE_SALARY,
        gross_amount=gross,
        deduction_percent=pct,
        deduction_amount=advance_deduction,
        extra_deduction_amount=extra_deduction,
        net_amount=net_amount,
        comment=comment,
    )

    # пересчёт баланса аванса на основе всех выплат
    recompute_employee_advance_balance(emp)

    emp.refresh_from_db()
    return JsonResponse({"ok": True, "employee": _employee_to_dict(emp)})








@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting(request):
    # Вкладки: reports | stats | prices | schedule | other
    tab = (request.GET.get("tab") or "reports").lower()
    if tab not in {"reports", "stats", "prices", "schedule", "other", "chart_settings", "holidays"}:
        tab = "reports"

    context = {"tab": tab}

    # ---- Вкладка Цены ----
    if tab == "prices":
        groups = PriceGroup.objects.prefetch_related("items").order_by("sort_order", "id")

        if request.method == "POST":
            updated = 0
            for g in groups:
                for it in g.items.all():
                    field = f"price_{it.id}"
                    if field in request.POST:
                        raw = (request.POST.get(field) or "").strip()
                        if raw == "":
                            continue
                        # убираем все виды пробелов и приводим запятую к точке
                        raw = (
                            raw.replace(" ", "")
                            .replace("\u00A0", "")   # NBSP
                            .replace("\u202F", "")   # THIN NBSP
                            .replace(",", ".")
                        )
                        try:
                            val = round(float(raw), 2)
                        except ValueError:
                            continue
                        if it.value != val:
                            it.value = val
                            it.save(update_fields=["value"])
                            updated += 1
            messages.success(request, f"Цены сохранены. Обновлено позиций: {updated}")
            return redirect(f"{request.path}?tab=prices")

        context["price_groups"] = groups
    
        # ---- Вкладка Настройки графиков ----
    # ---- Вкладка Настройки графиков ----
    if tab == "chart_settings":
        today = timezone.localdate()
    
        def get_cfg_for_today(tab_key: str):
            return (ChartConfig.objects
                    .filter(tab=tab_key, effective_from__lte=today)
                    .order_by("-effective_from", "-id")
                    .first())
    
        def ensure_default(tab_key: str):
            cfg = get_cfg_for_today(tab_key)
            if cfg:
                return cfg
            # если вообще пусто — создаём первую версию
            return ChartConfig.objects.create(
                tab=tab_key,
                enabled=True,
                effective_from=today,
                days_ldsp=10,
                days_film=10,
                days_paint=14,
            )
    
        def parse_int(raw, default):
            raw = (raw or "").strip()
            try:
                v = int(raw)
                if v < 1:
                    v = 1
                if v > 365:
                    v = 365
                return v
            except Exception:
                return default
    
        def save_new_version(tab_key: str, enabled: bool, ldsp: int, film: int, paint: int):
            current = get_cfg_for_today(tab_key)
            # если не изменилось — не создаём новую запись
            if current and current.enabled == enabled and current.days_ldsp == ldsp and current.days_film == film and current.days_paint == paint:
                return False
    
            ChartConfig.objects.create(
                tab=tab_key,
                enabled=enabled,
                effective_from=today,   # ✅ новая версия действует с сегодня
                days_ldsp=ldsp,
                days_film=film,
                days_paint=paint,
            )
            return True
    
        # текущие настройки (по одной активной версии на вкладку)
        cfg_map = {
            "general": ensure_default("general"),
            "technologist": ensure_default("technologist"),
            "workshop": ensure_default("workshop"),
            "paint": ensure_default("paint"),
            "film": ensure_default("film"),
        }
    
        if request.method == "POST":
            updated = 0
    
            # general
            updated += 1 if save_new_version(
                "general",
                enabled=(request.POST.get("general_enabled") == "1"),
                ldsp=parse_int(request.POST.get("general_days_ldsp"), cfg_map["general"].days_ldsp),
                film=parse_int(request.POST.get("general_days_film"), cfg_map["general"].days_film),
                paint=parse_int(request.POST.get("general_days_paint"), cfg_map["general"].days_paint),
            ) else 0
    
            # technologist
            updated += 1 if save_new_version(
                "technologist",
                enabled=(request.POST.get("technologist_enabled") == "1"),
                ldsp=parse_int(request.POST.get("technologist_days_ldsp"), cfg_map["technologist"].days_ldsp),
                film=parse_int(request.POST.get("technologist_days_film"), cfg_map["technologist"].days_film),
                paint=parse_int(request.POST.get("technologist_days_paint"), cfg_map["technologist"].days_paint),
            ) else 0
    
            # workshop
            updated += 1 if save_new_version(
                "workshop",
                enabled=(request.POST.get("workshop_enabled") == "1"),
                ldsp=parse_int(request.POST.get("workshop_days_ldsp"), cfg_map["workshop"].days_ldsp),
                film=parse_int(request.POST.get("workshop_days_film"), cfg_map["workshop"].days_film),
                paint=parse_int(request.POST.get("workshop_days_paint"), cfg_map["workshop"].days_paint),
            ) else 0
    
            # paint (только краска)
            updated += 1 if save_new_version(
                "paint",
                enabled=(request.POST.get("paint_enabled") == "1"),
                ldsp=cfg_map["paint"].days_ldsp,
                film=cfg_map["paint"].days_film,
                paint=parse_int(request.POST.get("paint_days_paint"), cfg_map["paint"].days_paint),
            ) else 0
    
            # film (только плёнка)
            updated += 1 if save_new_version(
                "film",
                enabled=(request.POST.get("film_enabled") == "1"),
                ldsp=cfg_map["film"].days_ldsp,
                film=parse_int(request.POST.get("film_days_film"), cfg_map["film"].days_film),
                paint=cfg_map["film"].days_paint,
            ) else 0
    
            messages.success(request, f"Настройки графиков сохранены. Новых версий создано: {updated}")
            return redirect(f"{request.path}?tab=chart_settings")
    
        context["cfg_map"] = cfg_map

    if tab == "holidays":
        # доступ: бухгалтер или админ
        can_edit = request.user.is_superuser or request.user.is_staff or request.user.groups.filter(name="Бухгалтер").exists()
        if not can_edit:
            messages.error(request, "Нет доступа.")
            return redirect(f"{request.path}?tab=main")
    
        if request.method == "POST":
            action = request.POST.get("action")
    
            if action == "add":
                d = (request.POST.get("date") or "").strip()
                title = (request.POST.get("title") or "").strip()
                if d:
                    try:
                        # HTML date input отдаёт YYYY-MM-DD
                        HolidayKZ.objects.update_or_create(date=d, defaults={"title": title})
                        messages.success(request, "Дата добавлена/обновлена.")
                    except Exception:
                        messages.error(request, "Ошибка добавления даты.")
                return redirect(f"{request.path}?tab=holidays")
    
            if action == "save":
                # массовое сохранение: holiday_<id>_date / holiday_<id>_title / delete_<id>
                ids = list(HolidayKZ.objects.values_list("id", flat=True))
                for hid in ids:
                    if request.POST.get(f"delete_{hid}") == "1":
                        HolidayKZ.objects.filter(id=hid).delete()
                        continue
    
                    new_date = (request.POST.get(f"holiday_{hid}_date") or "").strip()
                    new_title = (request.POST.get(f"holiday_{hid}_title") or "").strip()
    
                    if not new_date:
                        continue
    
                    try:
                        obj = HolidayKZ.objects.get(id=hid)
                        # если меняем дату — следим за unique
                        if str(obj.date) != new_date:
                            # чтобы не словить дубль — update_or_create
                            HolidayKZ.objects.update_or_create(
                                date=new_date,
                                defaults={"title": new_title}
                            )
                            obj.delete()
                        else:
                            obj.title = new_title
                            obj.save(update_fields=["title"])
                    except Exception:
                        pass
    
                messages.success(request, "Сохранено.")
                return redirect(f"{request.path}?tab=holidays")
                
            if action == "bulk_add":
                text = (request.POST.get("bulk_text") or "").strip()
                added = 0
                updated = 0
            
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # допускаем комментарии после даты
                    parts = line.split(maxsplit=1)
                    d = parts[0].strip()
                    title = parts[1].strip() if len(parts) > 1 else ""
            
                    try:
                        obj, created = HolidayKZ.objects.update_or_create(
                            date=d,
                            defaults={"title": title}
                        )
                        if created:
                            added += 1
                        else:
                            updated += 1
                    except Exception:
                        # пропускаем мусорные строки
                        continue
            
                messages.success(request, f"Импорт завершён. Добавлено: {added}, обновлено: {updated}")
                return redirect(f"{request.path}?tab=holidays")

    
        context["holidays"] = HolidayKZ.objects.order_by("date")

    # ВАЖНО: рендерим НОВЫЙ шаблон с вкладками
    return render(request, "accounting/index.html", context)


@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_price_add(request):
    def _is_ajax(req):
        return req.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method != "POST":
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)
        return redirect(f"{reverse('accounting')}?tab=prices")

    group_id = request.POST.get("group_id")
    title = (request.POST.get("title") or "").strip()
    value_raw = (request.POST.get("value") or "").strip()

    if not group_id or not title or not value_raw:
        if _is_ajax(request):
            return JsonResponse(
                {"ok": False, "error": "Заполните Наименование и Стоимость."},
                status=400,
            )
        messages.error(request, "Заполните Наименование и Стоимость.")
        return redirect(f"{reverse('accounting')}?tab=prices")

    # normalize value
    value_raw = (
        value_raw.replace(" ", "")
        .replace("\u00A0", "")
        .replace("\u202F", "")
        .replace(",", ".")
    )
    try:
        val = round(float(value_raw), 2)
    except Exception:
        if _is_ajax(request):
            return JsonResponse(
                {"ok": False, "error": "Неверный формат стоимости."},
                status=400,
            )
        messages.error(request, "Неверный формат стоимости.")
        return redirect(f"{reverse('accounting')}?tab=prices")

    group = get_object_or_404(PriceGroup, pk=group_id)
    # duplicate name check within group (case-insensitive)
    if PriceItem.objects.filter(group=group, title__iexact=title).exists():
        if _is_ajax(request):
            return JsonResponse(
                {"ok": False, "error": "Такая позиция уже существует в группе."},
                status=400,
            )
        messages.error(request, "Такая позиция уже существует в группе.")
        return redirect(f"{reverse('accounting')}?tab=prices#group-{group.id}")
    item = PriceItem.objects.create(group=group, title=title, value=val)

    if _is_ajax(request):
        try:
            html = render_to_string(
                "accounting/_price_row.html", {"item": item}, request=request
            )
        except Exception:
            html = f'''
<div class="column is-6-tablet is-4-desktop">
  <label class="label" for="id_price_{item.id}">
    {escape(item.title)}
    <small class="tag is-light ml-2 js-was" data-val="{int(item.value)}">
      Было: {int(item.value)}
    </small>
  </label>
  <div class="control has-icons-left">
    <input id="id_price_{item.id}"
           name="price_{item.id}"
           type="text"
           inputmode="decimal"
           class="input js-price"
           value="{int(item.value)}"
           autocomplete="off">
    <span class="icon is-small is-left">₸</span>
  </div>
</div>
'''
        return JsonResponse({"ok": True, "group_id": group.id, "html": html})

    messages.success(request, f"Позиция «{title}» добавлена в «{group.title}».")
    return redirect(f"{reverse('accounting')}?tab=prices#group-{group.id}")






@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_reports_data(request):
    """
    JSON-данные для графика «Отчёты»:
    - диапазон: week | month | 6m | year | all
    - группировка по 1 / 3 / 7 / 30 дням (bucket)
    """

    # --- 1. Диапазон ---
    range_key = (request.GET.get("range") or "month").lower()
    today = timezone.localdate()

    # будем работать с календарными периодами
    if range_key == "week":
        # последние 7 дней, включая сегодня
        start_date = today - timedelta(days=6)
        range_key = "week"
    elif range_key == "month":
        # текущий календарный месяц: с 1 числа
        start_date = today.replace(day=1)
        range_key = "month"
    elif range_key in {"6m", "6months", "6"}:
        # 6 календарных месяцев: от первого числа месяца 5 месяцев назад
        base = today.replace(day=1)
        month_index = base.year * 12 + (base.month - 1) - 5
        start_year = month_index // 12
        start_month = month_index % 12 + 1
        start_date = base.replace(year=start_year, month=start_month)
        range_key = "6m"
    elif range_key == "year":
        # текущий календарный год
        start_date = today.replace(month=1, day=1)
        range_key = "year"
    elif range_key == "all":
        first_ts = (
            Payment.objects.filter(amount_due__gt=0)
            .order_by("created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if first_ts:
            # с первого числа месяца, когда появились первые оплаты
            start_date = first_ts.date().replace(day=1)
        else:
            return JsonResponse(
                {
                    "labels": [],
                    "values": [],
                    "buckets": [],
                    "range": range_key,
                    "bucket": None,
                }
            )
    else:
        # по умолчанию — текущий месяц
        start_date = today.replace(day=1)
        range_key = "month"

    # --- 2. Размер корзины (bucket) ---
    bucket_param = (request.GET.get("bucket") or "3").lower()
    if bucket_param == "1":
        bucket_size = 1
    elif bucket_param == "7":
        bucket_size = 7
    elif bucket_param in {"30", "month"}:
        bucket_size = 30
        bucket_param = "30"
    else:
        # по умолчанию 3
        bucket_size = 3
        bucket_param = "3"

    # Ограничение из ТЗ: Месяц нельзя на недельном диапазоне
    if range_key == "week" and bucket_size > 7:
        bucket_size = 7
        bucket_param = "7"

    # --- 3. Достаём платежи ---
    qs = (
        Payment.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=today,
            amount_due__gt=0,
        )
        .select_related("order")
        .order_by("created_at")
    )

    if not qs.exists():
        return JsonResponse(
            {
                "labels": [],
                "values": [],
                "buckets": [],
                "range": range_key,
                "bucket": bucket_param,
            }
        )

    # --- 4. Разбиваем на интервалы по bucket_size дней ---
    total_days = (today - start_date).days + 1
    bucket_count = (total_days + bucket_size - 1) // bucket_size

    buckets = []
    for i in range(bucket_count):
        b_start = start_date + timedelta(days=i * bucket_size)
        b_end = min(b_start + timedelta(days=bucket_size - 1), today)
        buckets.append(
            {
                "start": b_start,
                "end": b_end,
                "total": Decimal("0.00"),
                "orders": {},  # order_number -> Decimal
            }
        )

    for p in qs:
        d = p.created_at.date()
        idx = (d - start_date).days // bucket_size
        if idx < 0 or idx >= bucket_count:
            continue

        bucket = buckets[idx]
        amt = Decimal(str(p.amount_due or 0))
        order = getattr(p, "order", None)
        order_no = getattr(order, "order_number", None) or p.order_id

        bucket["total"] += amt
        if order_no not in bucket["orders"]:
            bucket["orders"][order_no] = Decimal("0.00")
        bucket["orders"][order_no] += amt

    labels = []
    values = []
    bucket_payload = []

    for b in buckets:
        # подпись под точкой: 10.11 или 10.11–12.11
        if b["start"] == b["end"]:
            label = b["start"].strftime("%d.%m")
        else:
            label = f'{b["start"].strftime("%d.%m")}–{b["end"].strftime("%d.%m")}'

        labels.append(label)
        values.append(float(b["total"]))

        orders_list = []
        for order_no, total in sorted(
            b["orders"].items(), key=lambda x: str(x[0])
        ):
            try:
                num = int(order_no)
            except Exception:
                num = str(order_no)
            orders_list.append(
                {
                    "order": num,
                    "amount": float(total),
                }
            )

        bucket_payload.append(
            {
                "range": (
                    f'{b["start"].strftime("%d.%m.%Y")}–'
                    f'{b["end"].strftime("%d.%m.%Y")}'
                    if b["start"] != b["end"]
                    else b["start"].strftime("%d.%m.%Y")
                ),
                "total": float(b["total"]),
                "orders": orders_list,
            }
        )

    return JsonResponse(
        {
            "labels": labels,
            "values": values,
            "buckets": bucket_payload,
            "range": range_key,
            "bucket": bucket_param,
        }
    )
    
    
    
@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_reports_designers_data(request):
    """
    JSON-данные для графика «Сравнение дизайнеров»:
    - диапазон: week | month | 6m | year | all (как в основном графике)
    - группировка по bucket дням: 1 / 3 / 7 / 30
    - по каждому дизайнеру отдельная линия
    """

    # --- 1. Диапазон ---
    range_key = (request.GET.get("range") or "month").lower()
    today = timezone.localdate()

    if range_key == "week":
        # последние 7 дней, включая сегодня
        start_date = today - timedelta(days=6)
        range_key = "week"

    elif range_key == "month":
        # текущий календарный месяц: с 1 числа
        start_date = today.replace(day=1)
        range_key = "month"

    elif range_key in {"6m", "6months", "6"}:
        # 6 календарных месяцев: от первого числа месяца 5 месяцев назад
        base = today.replace(day=1)
        month_index = base.year * 12 + (base.month - 1) - 5
        start_year = month_index // 12
        start_month = month_index % 12 + 1
        start_date = base.replace(year=start_year, month=start_month)
        range_key = "6m"

    elif range_key == "year":
        # текущий календарный год
        start_date = today.replace(month=1, day=1)
        range_key = "year"

    elif range_key == "all":
        first_ts = (
            Payment.objects.filter(amount_due__gt=0)
            .order_by("created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if first_ts:
            # с первого числа месяца, когда появились первые оплаты
            start_date = first_ts.date().replace(day=1)
        else:
            return JsonResponse(
                {
                    "labels": [],
                    "series": [],
                    "buckets": [],
                    "range": range_key,
                    "bucket": None,
                }
            )
    else:
        # по умолчанию — текущий месяц
        start_date = today.replace(day=1)
        range_key = "month"

    # --- 2. Размер корзины (bucket) ---
    bucket_param = (request.GET.get("bucket") or "3").lower()
    if bucket_param == "1":
        bucket_size = 1
    elif bucket_param == "7":
        bucket_size = 7
    elif bucket_param in {"30", "month"}:
        bucket_size = 30
        bucket_param = "30"
    else:
        bucket_size = 3
        bucket_param = "3"

    # Ограничение: месяц нельзя на недельном диапазоне
    if range_key == "week" and bucket_size > 7:
        bucket_size = 7
        bucket_param = "7"

    # --- 3. Достаём платежи (только положительные) ---
    qs = (
        Payment.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=today,
            amount_due__gt=0,
        )
        .select_related("order")
        .order_by("created_at")
    )

    if not qs.exists():
        return JsonResponse(
            {
                "labels": [],
                "series": [],
                "buckets": [],
                "range": range_key,
                "bucket": bucket_param,
            }
        )

    total_days = (today - start_date).days + 1
    bucket_count = (total_days + bucket_size - 1) // bucket_size

    # buckets[i] = {
    #   "start": date,
    #   "end": date,
    #   "designers": {
    #       designer_key: {
    #           "name": str,
    #           "total": Decimal,
    #           "orders": { order_no: Decimal, ... }
    #       }
    #   }
    # }
    buckets = []
    for i in range(bucket_count):
        b_start = start_date + timedelta(days=i * bucket_size)
        b_end = min(b_start + timedelta(days=bucket_size - 1), today)
        buckets.append(
            {
                "start": b_start,
                "end": b_end,
                "designers": {},
            }
        )

    designers_meta = {}  # designer_key -> name

    def get_designer_key_and_name(order):
        """
        Определяем дизайнера заказа.

        1) Основной источник — Order.created_by (кто создал заказ).
        2) Запасной вариант — order.designer, если вдруг такое поле есть.
        3) Если никого нет — "Без дизайнера".
        """
        # 1. Основной вариант — пользователь, создавший заказ
        designer_obj = getattr(order, "created_by", None)

        # 2. Если вдруг есть отдельное поле designer — тоже используем
        if designer_obj is None and hasattr(order, "designer"):
            designer_obj = getattr(order, "designer")

        # 3. Совсем никого нет
        if designer_obj is None:
            return ("__none__", "Без дизайнера")

        # Красивое имя: Имя Фамилия (как у тебя Анна Дьяченко)
        if hasattr(designer_obj, "get_full_name"):
            try:
                name = (designer_obj.get_full_name() or "").strip()
            except Exception:
                name = ""
        else:
            name = ""

        if not name:
            # fallback: str(user) или username
            name = (str(designer_obj) or "").strip() or "Без имени"

        pk = getattr(designer_obj, "pk", None)
        if pk is not None:
            key = f"{designer_obj.__class__.__name__}:{pk}"
        else:
            key = f"{designer_obj.__class__.__name__}:{name}"

        return (key, name)

    for p in qs:
        d = p.created_at.date()
        idx = (d - start_date).days // bucket_size
        if idx < 0 or idx >= bucket_count:
            continue

        order = getattr(p, "order", None)
        if not order:
            continue

        designer_key, designer_name = get_designer_key_and_name(order)
        designers_meta.setdefault(designer_key, designer_name)

        bucket = buckets[idx]
        designers_dict = bucket["designers"]
        if designer_key not in designers_dict:
            designers_dict[designer_key] = {
                "name": designer_name,
                "total": Decimal("0.00"),
                "orders": {},  # order_no -> Decimal
            }

        amt = Decimal(str(p.amount_due or 0))
        designers_dict[designer_key]["total"] += amt

        order_no = getattr(order, "order_number", None) or order.pk
        if order_no not in designers_dict[designer_key]["orders"]:
            designers_dict[designer_key]["orders"][order_no] = Decimal("0.00")
        designers_dict[designer_key]["orders"][order_no] += amt

    # --- 4. Формируем labels и series для графика ---
    labels = []
    # подготовим ключи дизайнеров в стабильном порядке
    all_keys = sorted(designers_meta.keys(), key=lambda k: designers_meta[k].lower())

    # для каждого дизайнера — список значений по bucket-ам
    series_map = {k: [] for k in all_keys}

    buckets_payload = []  # данные для подсказок

    for b in buckets:
        # подпись по оси X
        if b["start"] == b["end"]:
            label = b["start"].strftime("%d.%m")
        else:
            label = f'{b["start"].strftime("%d.%m")}–{b["end"].strftime("%d.%m")}'
        labels.append(label)

        designers_dict = b["designers"]

        # значения для каждого дизайнера
        for key in all_keys:
            info = designers_dict.get(key)
            value = float(info["total"]) if info else 0.0
            series_map[key].append(value)

        # payload для тултипов
        designers_list = []
        for key in all_keys:
            info = designers_dict.get(key)
            if not info:
                continue
            orders_list = []
            for order_no, total in sorted(
                info["orders"].items(), key=lambda x: str(x[0])
            ):
                try:
                    num = int(order_no)
                except Exception:
                    num = str(order_no)
                orders_list.append(
                    {
                        "order": num,
                        "amount": float(total),
                    }
                )
            designers_list.append(
                {
                    "key": key,
                    "name": info["name"],
                    "total": float(info["total"]),
                    "orders": orders_list,
                }
            )

        buckets_payload.append(
            {
                "range": (
                    f'{b["start"].strftime("%d.%m.%Y")}–'
                    f'{b["end"].strftime("%d.%m.%Y")}'
                    if b["start"] != b["end"]
                    else b["start"].strftime("%d.%m.%Y")
                ),
                "designers": designers_list,
            }
        )

    # превращаем series_map в список для JSON
    series = []
    for key in all_keys:
        series.append(
            {
                "key": key,
                "name": designers_meta[key],
                "values": series_map[key],
            }
        )

    return JsonResponse(
        {
            "labels": labels,
            "series": series,
            "buckets": buckets_payload,
            "range": range_key,
            "bucket": bucket_param,
        }
    )
    
from django.db.models import Sum, Max, F, Q
from django.db.models.functions import Coalesce
from django.urls import reverse
# ... декораторы уже есть: group_required, access_required

@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_reports_orders_table(request):
    """
    JSON-данные для таблицы оплаченных заказов в разделе Бухгалтерия → Отчёты.
    """
    # --- Фильтры из GET ---
    date_from_str = (request.GET.get("date_from") or "").strip()
    date_to_str = (request.GET.get("date_to") or "").strip()
    sort = (request.GET.get("sort") or "date").lower()       # date | order | amount
    direction = (request.GET.get("dir") or "desc").lower()   # asc | desc

    # --- Базовый queryset: считаем только платежи ---
    orders = (
        Order.objects
        .select_related("calculation")
        .annotate(
            # сумма всех оплат по заказу
            paid_sum=Coalesce(Sum("payments__amount_due"), Decimal("0.00")),
            # дата последней оплаты
            last_payment_date=Max("payments__created_at"),
        )
        .filter(paid_sum__gt=0)
        .prefetch_related(
            "payments",
            "calculation__facade_items__price_item__group",
        )
    )

    # --- Фильтр по дате оплаты ---
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
            orders = orders.filter(payments__created_at__date__gte=date_from)
        except ValueError:
            pass

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()
            orders = orders.filter(payments__created_at__date__lte=date_to)
        except ValueError:
            pass

    # --- Сортировка ---
    sort_map = {
        "date": "last_payment_date",
        "order": "order_number",
        "amount": "paid_sum",
    }
    order_by = sort_map.get(sort, "last_payment_date")
    if direction == "desc":
        order_by = "-" + order_by
    orders = orders.order_by(order_by)

    # --- Формирование JSON ---
    rows = []
    for o in orders:
        # Клиент + телефон
        customer_name = (o.customer_name or "").strip()
        phone = (o.phone or o.whatsapp_phone or "").strip()

        # Дата оплаты (последней)
        paid_date = ""
        if getattr(o, "last_payment_date", None):
            paid_date = o.last_payment_date.strftime("%d.%m.%Y")

        # Методы оплаты — по всем платежам
        methods_set = set()
        for p in o.payments.all():
            for m in (p.methods or []):
                methods_set.add(m)
        methods = sorted(methods_set)

        # ---- ЛДСП и МДФ ----
        ldsp_qty = Decimal("0")
        mdf_paint_m2 = Decimal("0")
        mdf_film_m2 = Decimal("0")

        calc = getattr(o, "calculation", None)
        if calc is not None:
            # ЛДСП (листы) — как в «Все заказы»
            need = _calc_live_numbers(o)
            try:
                ldsp_qty = Decimal(str(need.get("ldsp", 0) or 0))
            except Exception:
                ldsp_qty = Decimal("0")

            # квадратуры фасадов по группам
            facade_items = getattr(calc, "facade_items", None)
            if facade_items is not None:
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
                        mdf_paint_m2 += area_dec
                    elif title == "Фасады (плёнка)":
                        mdf_film_m2 += area_dec

        # ---- Признак «Договор» ----
        status_label = ""
        if hasattr(o, "get_status_display"):
            try:
                status_label = (o.get_status_display() or "").strip()
            except Exception:
                status_label = ""
        if not status_label:
            status_label = str(getattr(o, "status", "") or "").strip()

        has_contract = (status_label == "Договор")

        # Ссылка на «Оплата»
        payment_url = reverse("payment_new", kwargs={"order_id": o.id})

        # Ссылка на «Все заказы» с фильтром по номеру
        order_q = (str(o.order_number or "")).strip()
        orders_url = f"{reverse('orders_all')}?q={order_q}" if order_q else reverse("orders_all")

        rows.append(
            {
                "order_id": o.id,
                "order_number": o.order_number,
                "customer_name": customer_name,
                "phone": phone,
                "paid_date": paid_date,
                "ldsp_qty": float(ldsp_qty),
                "mdf_paint_m2": float(mdf_paint_m2),
                "mdf_film_m2": float(mdf_film_m2),
                "amount": float(o.paid_sum or 0),
                "methods": methods,
                "has_contract": has_contract,
                "payment_url": payment_url,
                "order_url": orders_url,
            }
        )

    return JsonResponse({"rows": rows})

    
    
    
@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_reports_summary(request):
    """
    Итоги по оплаченным заказам за период:
    - общая сумма оплат
    - суммарное кол-во листов ЛДСП
    - суммарная квадратура МДФ фасады (краска)
    - суммарная квадратура МДФ фасады (плёнка)
    """

    date_from_str = (request.GET.get("date_from") or "").strip()
    date_to_str = (request.GET.get("date_to") or "").strip()

    # --- базовый queryset по платежам (только положительные) ---
    pay_qs = Payment.objects.filter(amount_due__gt=0)

    if date_from_str:
        try:
            d_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
            pay_qs = pay_qs.filter(created_at__date__gte=d_from)
        except ValueError:
            d_from = None
    else:
        d_from = None

    if date_to_str:
        try:
            d_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()
            pay_qs = pay_qs.filter(created_at__date__lte=d_to)
        except ValueError:
            d_to = None
    else:
        d_to = None

    # если дат нет — берём весь период, который есть в БД
    if not date_from_str and not date_to_str:
        first = pay_qs.order_by("created_at").values_list("created_at", flat=True).first()
        last = pay_qs.order_by("-created_at").values_list("created_at", flat=True).first()
        if first and last:
            d_from = first.date()
            d_to = last.date()

    # если после фильтров платежей нет — возвращаем нули
    if not pay_qs.exists():
        return JsonResponse({
            "date_from": d_from.strftime("%Y-%m-%d") if d_from else None,
            "date_to": d_to.strftime("%Y-%m-%d") if d_to else None,
            "total_amount": 0,
            "total_ldsp": 0,
            "total_mdf_paint": 0,
            "total_mdf_film": 0,
        })

    # --- Общая сумма оплат за период ---
    from django.db.models import Sum
    from django.db.models.functions import Coalesce

    agg = pay_qs.aggregate(total=Coalesce(Sum("amount_due"), Decimal("0.00")))
    total_amount = agg["total"] or Decimal("0.00")

    # --- Находим заказы, у которых были оплаты в этом периоде ---
    order_ids = list(
        pay_qs.exclude(order_id__isnull=True)
              .values_list("order_id", flat=True)
              .distinct()
    )

    orders = (
        Order.objects.filter(id__in=order_ids)
        .select_related("calculation")
        .prefetch_related("calculation__facade_items__price_item__group")
    )

    total_ldsp = Decimal("0")
    total_mdf_paint = Decimal("0")
    total_mdf_film = Decimal("0")

    for o in orders:
        calc = getattr(o, "calculation", None)

        # ЛДСП (листы) — как в «Все заказы»
        if calc is not None:
            need = _calc_live_numbers(o)
            try:
                ldsp_val = Decimal(str(need.get("ldsp", 0) or 0))
            except Exception:
                ldsp_val = Decimal("0")
            total_ldsp += ldsp_val

            # МДФ краска / плёнка: суммарные площади фасадов по группам
            facade_items = getattr(calc, "facade_items", None)
            if facade_items is not None:
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
                        total_mdf_paint += area_dec
                    elif title == "Фасады (плёнка)":
                        total_mdf_film += area_dec

    return JsonResponse({
        "date_from": d_from.strftime("%Y-%m-%d") if d_from else None,
        "date_to": d_to.strftime("%Y-%m-%d") if d_to else None,
        "total_amount": float(total_amount),
        "total_ldsp": float(total_ldsp),
        "total_mdf_paint": float(total_mdf_paint),
        "total_mdf_film": float(total_mdf_film),
    })



@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_reports_services_summary(request):
    """
    Сводный отчёт по услугам:
    - Сумма Обработка (Payment.amount_total)
    - Сумма Фасады (Payment.amount_facades)
    - Сумма Дизайн (Payment.amount_design)
    - Итоговая сумма (Payment.amount_due)
    только по платежам за выбранный период (amount_due > 0).
    """
    from datetime import date, timedelta

    period = (request.GET.get("period") or "month").lower()
    valid_periods = {"day", "week", "month", "quarter", "halfyear", "year", "all"}
    if period not in valid_periods:
        period = "month"

    # Базовая дата (конец диапазона)
    end_date = timezone.localdate()
    date_str = request.GET.get("date")
    if date_str:
        try:
            end_date = date.fromisoformat(date_str)
        except Exception:
            pass

    # Берём только положительные платежи (оплаченные)
    qs = Payment.objects.filter(amount_due__gt=0)
    date_from = None

    if period == "all":
        # Отчёт за всё время — берём минимальную и максимальную дату платежей
        agg_dates = qs.aggregate(min_date=Min("created_at"), max_date=Max("created_at"))
        min_dt = agg_dates["min_date"]
        max_dt = agg_dates["max_date"]
        if min_dt and max_dt:
            date_from = min_dt.date()
            end_date = max_dt.date()
            qs = qs.filter(
                created_at__date__gte=date_from,
                created_at__date__lte=end_date,
            )
        else:
            qs = qs.none()
    else:
        # Диапазон назад от выбранной даты
        days_map = {
            "day": 0,        # 1 день (только выбранная дата)
            "week": 6,       # 7 дней
            "month": 29,     # ~30 дней
            "quarter": 89,   # ~3 месяца
            "halfyear": 181, # ~6 месяцев
            "year": 364,     # ~12 месяцев
        }
        delta_days = days_map.get(period, 29)
        date_from = end_date - timedelta(days=delta_days)
        qs = qs.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=end_date,
        )

    # --- Агрегация без Coalesce, None обработаем вручную ---
    sums = qs.aggregate(
        processing=Sum("amount_total"),
        facades=Sum("amount_facades"),
        design=Sum("amount_design"),
        total=Sum("amount_due"),
    )

    def _to_float(val):
        if val is None:
            return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    data = {
        "period": period,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": end_date.isoformat() if end_date else None,
        "summary": {
            "processing": _to_float(sums["processing"]),
            "facades": _to_float(sums["facades"]),
            "design": _to_float(sums["design"]),
            "total": _to_float(sums["total"]),
        },
    }
    return JsonResponse(data)

@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_salary_payments_list(request):
    """
    Журнал выплат зарплаты/аванса.

    GET-параметры:
    - month: YYYY-MM (обязательный месячный фильтр, если нет — берём текущий)
    - employee_id: фильтр по сотруднику
    """
    employee_id = request.GET.get("employee_id")
    month_str = request.GET.get("month")

    qs = SalaryPayment.objects.select_related("employee").order_by("-pay_date", "-id")

    # месячный диапазон
    if month_str:
        try:
            y, m = map(int, month_str.split("-"))
            start = date(y, m, 1)
            end = date(y, m, monthrange(y, m)[1])
            qs = qs.filter(pay_date__range=(start, end))
        except Exception:
            pass
    else:
        today = timezone.localdate()
        y, m = today.year, today.month
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        qs = qs.filter(pay_date__range=(start, end))

    if employee_id:
        try:
            emp_id_int = int(employee_id)
            qs = qs.filter(employee_id=emp_id_int)
        except (TypeError, ValueError):
            pass



    qs = qs[:500]

    items = []
    for p in qs:
        items.append(
            {
                "id": p.id,
                "employee_id": p.employee_id,
                "employee_name": p.employee.full_name,
                "pay_date": p.pay_date.isoformat(),
                "kind": p.kind,
                "kind_label": p.get_kind_display(),
                "gross_amount": float(p.gross_amount),
                "deduction_amount": float(p.deduction_amount),
                "extra_deduction_amount": float(p.extra_deduction_amount),
                "net_amount": float(p.net_amount),
                "comment": p.comment or "",
            }
        )

    return JsonResponse({"payments": items})



@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
@require_POST
def accounting_staff_advance_create(request):
    """
    Выдать аванс сотруднику: фиксируем выплату вида 'advance',
    а баланс авансов пересчитываем по всей истории.
    """
    emp_id = request.POST.get("employee_id")
    emp = get_object_or_404(Employee, pk=emp_id, is_active=True)

    raw_amount = (request.POST.get("amount") or "").replace(" ", "").replace(",", ".")
    comment = (request.POST.get("comment") or "").strip()

    try:
        amount = Decimal(raw_amount or "0")
        if amount <= 0:
            raise ValueError
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "Укажите корректную сумму аванса."},
            status=400,
        )

    today = timezone.localdate()

    SalaryPayment.objects.create(
        employee=emp,
        period_start=None,
        period_end=None,
        pay_date=today,
        kind=SalaryPayment.TYPE_ADVANCE,
        gross_amount=amount,
        deduction_percent=Decimal("0"),
        deduction_amount=Decimal("0"),
        extra_deduction_amount=Decimal("0"),
        net_amount=amount,
        comment=comment or "Аванс",
    )

    # пересчитываем баланс аванса с учётом нового аванса
    recompute_employee_advance_balance(emp)

    emp.refresh_from_db()
    return JsonResponse({"ok": True, "employee": _employee_to_dict(emp)})

    
@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
def accounting_staff_advance_list(request):
    """
    Мини-журнал авансов с расчётом, сколько по каждому авансу уже удержано.
    Погашение считаем FIFO: сначала гасим самые старые авансы.
    """
    from decimal import Decimal
    from django.db.models import Sum
    from django.db.models.functions import Coalesce

    emp_id = request.GET.get("employee_id")

    # все авансы (пока без лимита), сгруппируем по сотруднику
    adv_qs = (
        SalaryPayment.objects.filter(kind=SalaryPayment.TYPE_ADVANCE)
        .select_related("employee")
        .order_by("employee_id", "pay_date", "id")
    )
    if emp_id:
        try:
            emp_id_int = int(emp_id)
            adv_qs = adv_qs.filter(employee_id=emp_id_int)
        except (TypeError, ValueError):
            pass

    advances_by_emp = {}
    for p in adv_qs:
        advances_by_emp.setdefault(p.employee_id, []).append(p)

    # общие удержания авансов по ЗП для каждого сотрудника
    ded_rows = (
        SalaryPayment.objects.filter(kind=SalaryPayment.TYPE_SALARY)
        .values("employee_id")
        .annotate(total_deducted=Coalesce(Sum("deduction_amount"), Decimal("0")))
    )
    ded_map = {row["employee_id"]: row["total_deducted"] for row in ded_rows}

    items = []
    for emp_id_key, adv_list in advances_by_emp.items():
        remaining = ded_map.get(emp_id_key, Decimal("0"))
        for p in adv_list:
            amount = p.net_amount or Decimal("0")
            paid = min(amount, remaining)
            remaining -= paid
            if remaining < 0:
                remaining = Decimal("0")
            items.append(
                {
                    "id": p.id,
                    "employee_id": p.employee_id,
                    "employee_name": p.employee.full_name,
                    "pay_date": p.pay_date.isoformat(),
                    "amount": float(amount),
                    "paid_amount": float(paid),
                    "is_closed": paid >= amount and amount > 0,
                    "comment": p.comment or "",
                }
            )

    # сортируем по дате убыванию, показываем последние 50
    items.sort(
        key=lambda x: (x["pay_date"], x["id"]),
        reverse=True,
    )
    items = items[:50]

    return JsonResponse({"ok": True, "items": items})




@group_required("Бухгалтер")
@access_required("ACCESS_ACCOUNTING")
@require_POST
def accounting_salary_payment_delete(request, payment_id):
    """
    Удаление записи из журнала выплат/авансов.
    Требует пароль 'Maxim'.
    После удаления баланс авансов пересчитывается
    по всем оставшимся записям сотрудника.
    """
    password = (request.POST.get("password") or "").strip()
    if password != "Maxim":
        return JsonResponse(
            {"ok": False, "error": "Неверный пароль."},
            status=403,
        )

    payment = get_object_or_404(SalaryPayment, pk=payment_id)
    emp = payment.employee

    # сначала удаляем запись
    payment.delete()

    # потом пересчитываем баланс авансов по всей истории
    recompute_employee_advance_balance(emp)

    return JsonResponse({"ok": True})

