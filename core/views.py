import json
import os
import re
import io
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from io import BytesIO
from urllib.parse import quote
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from datetime import datetime, date
from django.utils.html import escape
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.staticfiles import finders
from django.db.models import Exists, OuterRef, Q, Sum, Value, DecimalField, Case, When, IntegerField, Q
from django.db.models.functions import Coalesce
from django.http import FileResponse, HttpResponse, HttpResponseForbidden, JsonResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import localtime
from django.utils.timezone import now
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.graphics.barcode import createBarcodeDrawing
from .forms import CalculationForm, ContractForm, OrderForm, PurchaseSheetForm
from .models import Calculation, CalculationFacadeItem, ChangeLog, Contract, FacadeSheet, Invoice, Order, Payment, PriceGroup, PriceItem, ProductionTask, PurchaseSheet, CalculationAdditionalItem
from core.models import Order, WarehouseReceipt
from core.charts import HANDLERS
from .utils import add_workdays_kz
from .models import Order, Payment, Calculation, PurchaseSheet, WarehouseReceipt, WarehouseDraft
import base64, uuid, re
from django.core.files.base import ContentFile
from datetime import timedelta
from datetime import date as _date
from django.db import transaction

CTP_PAT = re.compile(r"(countertop|tabletop|stolesh|столеш)", re.IGNORECASE)   # столешница
HDF_PAT = re.compile(r"(hdf|dvp|двп|хдф|back.*(wall|panel)|задн.*стен)", re.IGNORECASE)  # ХДФ/ДВП

# --- helpers ---
def in_group(user, group_names):
    return user.is_authenticated and (getattr(user, 'is_superuser', False) or user.groups.filter(name__in=group_names).exists())

def group_required(*group_names):
    return user_passes_test(lambda u: in_group(u, group_names))

def access_required(group_name):
    return user_passes_test(lambda u: u.is_authenticated and (getattr(u, 'is_superuser', False) or getattr(u, 'is_staff', False) or u.groups.filter(name=group_name).exists()))

# --- Brand colors ---
COMPANY_ORANGE = colors.HexColor("#F58220")
COMPANY_DARK   = colors.HexColor("#2D2D2D")
HEADER_BG      = colors.HexColor("#FFF3E6")  # light orange
GROUP_BG       = colors.HexColor("#FFE8D1")  # group header bg
ZEBRA_A        = colors.whitesmoke
ZEBRA_B        = colors.HexColor("#FFF9F3")



from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

CHART_TABS = [
    {"key": "general",      "title": "Общий график"},
    {"key": "technologist", "title": "График ТЕХНОЛОГ"},
    {"key": "workshop",     "title": "График ЦЕХ"},
    {"key": "paint",        "title": "График КРАСКА"},
    {"key": "film",         "title": "График ПЛЕНКА"},
]

TAB_ALLOWED_GROUPS = {
    "general":      {"Дизайнер_1", "Дизайнер_2", "Бухгалтер", "СУПЕР", "ACCESS_ADMIN"},
    "technologist": {"Технолог", "Бухгалтер", "СУПЕР", "ACCESS_ADMIN"},
    "workshop":     {"Производство", "Цех", "Бухгалтер", "СУПЕР", "ACCESS_ADMIN"},
    "paint":        {"Технолог", "Производство", "Цех", "Бухгалтер", "СУПЕР", "ACCESS_ADMIN"},
    "film":         {"Технолог", "Производство", "Цех", "Бухгалтер", "СУПЕР", "ACCESS_ADMIN"},
}

@login_required
@require_POST
def chart_note_save(request):
    # доступ: бухгалтер + админ
    if not (request.user.is_superuser or request.user.is_staff or request.user.groups.filter(name="Бухгалтер").exists()):
        return JsonResponse({"ok": False, "error": "no_access"}, status=403)

    order_id = request.POST.get("order_id")
    note = (request.POST.get("note") or "").strip()

    if not order_id:
        return JsonResponse({"ok": False, "error": "no_order_id"}, status=400)

    try:
        order = Order.objects.get(id=int(order_id))
    except Exception:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    order.chart_note = note
    order.save(update_fields=["chart_note"])
    return JsonResponse({"ok": True})

# универсально вытащить число из PriceItem (в проекте поле может называться price или value)
def _pi_amount(pi, default=0):
    if not pi:
        return Decimal(str(default))
    for attr in ("price", "value", "amount"):
        if hasattr(pi, attr):
            val = getattr(pi, attr)
            if val is not None:
                try:
                    return Decimal(str(val))
                except Exception:
                    pass
    return Decimal(str(default))

# получить цену/норму из ГРУППЫ "Быстрый расчёт — параметры"
def _param(title: str, default=0):
    grp = PriceGroup.objects.filter(title__iexact="Быстрый расчёт — параметры").first()
    if not grp:
        return Decimal(str(default))
    pi = PriceItem.objects.filter(group=grp, title__iexact=title).first()
    return _pi_amount(pi, default)

# получить цену операции из «Бухгалтерии» по заголовку (Распил, Присадка, ПВХ узкая, Столешница распил)
def _acct(title: str, default=0):
    pi = PriceItem.objects.filter(title__iexact=title).order_by("id").first()
    return _pi_amount(pi, default)






# --- PDF Fonts (DejaVuSans regular/bold) ---
PDF_FONT_REG = "DejaVuSans"
PDF_FONT_BLD = "DejaVuSans-Bold"
FONT_REGULAR = os.path.join(settings.BASE_DIR, "static", "fonts", "DejaVuSans.ttf")
FONT_BOLD    = os.path.join(settings.BASE_DIR, "static", "fonts", "DejaVuSans-Bold.ttf")

try:
    if os.path.exists(FONT_REGULAR):
        pdfmetrics.registerFont(TTFont(PDF_FONT_REG, FONT_REGULAR))
    if os.path.exists(FONT_BOLD):
        pdfmetrics.registerFont(TTFont(PDF_FONT_BLD, FONT_BOLD))
    registerFontFamily(
        PDF_FONT_REG,
        normal=PDF_FONT_REG, bold=PDF_FONT_BLD,
        italic=PDF_FONT_REG, boldItalic=PDF_FONT_BLD
    )
except Exception as e:
    print("[pdf] font registration error:", e)

# --- diff util (fallback) ---
def _to_str(v):
    if v is None:
        return ""
    return str(v)

def human_diff(instance, old_values: dict, fields: list[str]) -> str:
    lines = []
    for f in fields:
        before = old_values.get(f, None)
        after = getattr(instance, f, None)
        if before != after:
            lines.append(f"• {f}: «{_to_str(before)}» → «{_to_str(after)}»")
    return "\n".join(lines)



def _map_section(val: str):
    """
    Преобразуем любые подсказки в нормальную метку и цвет тега Bulma.
    Возвращаем (label, tag_class)
    """
    s = (str(val) if val is not None else "").lower()

    # прямые указания
    if "purchasesheet" in s or "purchase_sheet" in s or "лист закуп" in s:
        return "Лист закупа", "is-info"
    if "calculation" in s or "расчет" in s or "расчёт" in s:
        return "Расчёт", "is-link"
    if "contract" in s or "договор" in s:
        return "Договор", "is-warning"

    return "Заказ", ""  # по умолчанию

PURCHASE_HINTS = {"tabletop_length_3m", "lds", "ldsp", "pvc", "edge", "color", "thickness"}
CALC_HINTS     = {"total_price", "итоговая", "смета", "calculation", "note"}
CONTRACT_HINTS = {"contract", "договор", "contract_number", "signature", "печать"}

def _guess_section_by_text(text: str):
    t = (text or "").lower()
    if any(h in t for h in PURCHASE_HINTS):
        return "Лист закупа", "is-info"
    if any(h in t for h in CALC_HINTS):
        return "Расчёт", "is-link"
    if any(h in t for h in CONTRACT_HINTS):
        return "Договор", "is-warning"
    return "Заказ", ""
    
    
def _extract_payload(entry):
    """Достаём из записи любой полезный payload (dict) если он есть."""
    for attr in ("payload", "data", "meta", "changes"):
        val = getattr(entry, attr, None)
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                pass
    return None

# ===================== Orders =====================

@group_required("Бухгалтер", "Дизайнер_1", "Дизайнер_2")
@access_required("ACCESS_ORDERS")
def orders_all(request):
    # create new order from modal
    if request.method == "POST":
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.created_by = request.user
            order.save()
            Invoice.objects.create(order=order, amount=order.total, paid=False)
            for name in ("Резка", "Сборка", "Покраска"):
                ProductionTask.objects.create(order=order, name=name, status="todo")
            messages.success(request, "Заказ создан")
            return redirect(f"{reverse('orders_all')}?created={order.pk}")
    else:
        form = OrderForm()

    orders = (Order.objects.select_related("contract")
          .annotate(
              mdf_paint_m2=Sum("calculation__facade_items__area", filter=Q(calculation__facade_items__price_item__group__title="Фасады (краска)")),
              mdf_film_m2=Sum("calculation__facade_items__area", filter=Q(calculation__facade_items__price_item__group__title="Фасады (плёнка)")),
              has_payment=Exists(
                  Payment.objects.filter(order=OuterRef("pk"))
              ),
              has_accepted=Exists(
                  WarehouseReceipt.objects.filter(order=OuterRef("pk"), status="accepted")
              ),
              
          )
          .order_by("-created_at"))
    status = (request.GET.get("status") or "").strip()
    if status:
        orders = orders.filter(status=status)
    
    q = (request.GET.get("q") or "").strip()
    if q:
        # нормализуем телефон для поиска по цифрам
        phone_digits = "".join(ch for ch in q if ch.isdigit())
    
        conds = Q(customer_name__icontains=q)
        # поиск по номеру заказа
        if q.isdigit():
            conds |= Q(order_number=int(q))
        else:
            conds |= Q(order_number__icontains=q)
        # поиск по телефонам
        if phone_digits:
            conds |= Q(phone__icontains=phone_digits) | Q(whatsapp_phone__icontains=phone_digits)
    
        orders = orders.filter(conds)
    
    # --- Сортировка ---
    sort = (request.GET.get("sort") or "date").lower()      # date|order|status
    direction = (request.GET.get("dir") or "desc").lower()  # asc|desc
    
    if sort == "status":
        # Кастомный порядок: Новый → Расчёт → Закуп → Договор → В работе
        status_order = Case(
            When(status="new",       then=0),
            When(status="calc",      then=1),
            When(status="payment",   then=2),
            When(status="warehouse", then=3),
            When(status="work",      then=4),
            default=99,
            output_field=IntegerField(),
        )
        # применяем аннотацию и сортируем по ней
        orders = orders.annotate(_status_rank=status_order)
        orders = orders.order_by(("_status_rank" if direction == "asc" else "-_status_rank"))
    else:
        sort_map = {
            "date": "created_at",   # поправь, если поле даты у тебя называется иначе
            "order": "order_number",
        }
        order_by = sort_map.get(sort, "created_at")
        if direction == "desc":
            order_by = "-" + order_by
        orders = orders.order_by(order_by)
    
    # в контекст добавим текущие значения
    ctx = {
        "orders": orders,
        "form": form,
        "flt": {"status": status, "q": q},
        "sort": sort, "dir": direction,
    }
    return render(request, "orders_list.html", ctx)


def _user_groups_set(user):
    return set(user.groups.values_list("name", flat=True))


def _allowed_tabs_for_user(user):
    if user.is_superuser:
        return [t["key"] for t in CHART_TABS]

    user_groups = _user_groups_set(user)

    allowed = []
    for t in CHART_TABS:
        key = t["key"]
        allowed_groups = TAB_ALLOWED_GROUPS.get(key, set())
        if user_groups.intersection(allowed_groups):
            allowed.append(key)
    return allowed


@login_required
def order_info_json(request, order_id: int):
    from core.models import Order
    o = get_object_or_404(Order, pk=order_id)

    return JsonResponse({
        "order_number": o.order_number,
        "customer_name": o.customer_name or "",
        "last_name": o.last_name or "",
        "iin": o.iin or "",
        "phone": o.phone or "",
    })

@login_required
@access_required("ACCESS_CHART")
def orders_chart(request):
    tab = request.GET.get("tab")
    allowed_tabs = _allowed_tabs_for_user(request.user)

    if not allowed_tabs:
        return render(request, "orders_chart.html", {
            "tabs": [],
            "active_tab": None,
            "restricted": True,
            "restricted_text": "У вас нет доступа к графикам.",
            "can_edit_chart": False,
        }, status=403)

    if not tab or tab not in allowed_tabs:
        return redirect(f"{reverse('orders_chart')}?tab={allowed_tabs[0]}")

    restricted = (len(allowed_tabs) == 1)
    restricted_text = None
    if restricted:
        title = next((x["title"] for x in CHART_TABS if x["key"] == allowed_tabs[0]), allowed_tabs[0])
        restricted_text = f"Доступ только к вкладке: {title}"

    tabs_for_template = []
    for t in CHART_TABS:
        tabs_for_template.append({
            "key": t["key"],
            "title": t["title"],
            "allowed": (t["key"] in allowed_tabs),
        })

    can_edit_chart = (
        request.user.is_superuser
        or request.user.is_staff
        or request.user.groups.filter(name="Бухгалтер").exists()
    )

    return render(request, "orders_chart.html", {
        "tabs": tabs_for_template,
        "active_tab": tab,
        "restricted": restricted,
        "restricted_text": restricted_text,
        "can_edit_chart": can_edit_chart,
    })



@login_required
@access_required("ACCESS_CHART")
def orders_chart_data(request):
    tab = request.GET.get("tab")
    allowed_tabs = _allowed_tabs_for_user(request.user)

    if not allowed_tabs:
        return JsonResponse({"error": "forbidden"}, status=403)

    if not tab or tab not in allowed_tabs:
        return JsonResponse({"error": "forbidden"}, status=403)

    handler = HANDLERS.get(tab)
    if not handler:
        return JsonResponse({"error": "unknown_tab"}, status=400)

    payload = handler(request)
    return JsonResponse(payload)

@login_required
@require_http_methods(["GET"])
def chart_row_get(request, order_id: int):
    from core.models import Order, OrderSchedule
    o = get_object_or_404(Order, pk=order_id)

    sch, _ = OrderSchedule.objects.get_or_create(order=o)

    return JsonResponse({
        "order_id": o.id,
        "order_number": o.order_number,
        "customer": (o.customer_name or "") + (" " + (o.last_name or "") if o.last_name else ""),
        "status_ldsp": sch.status_ldsp,
        "status_film": sch.status_film,
        "status_paint": sch.status_paint,

        "due_ldsp_override": sch.due_ldsp_override.isoformat() if sch.due_ldsp_override else "",
        "due_film_override": sch.due_film_override.isoformat() if sch.due_film_override else "",
        "due_paint_override": sch.due_paint_override.isoformat() if sch.due_paint_override else "",

        "extra_days_ldsp": sch.extra_days_ldsp,
        "extra_days_film": sch.extra_days_film,
        "extra_days_paint": sch.extra_days_paint,

        "stop_until": sch.stop_until.isoformat() if sch.stop_until else "",
        "note": o.chart_note or "",
    })
@login_required
@require_http_methods(["POST"])
def chart_row_save(request, order_id: int):
    from core.models import Order, OrderSchedule
    from core.utils import add_workdays_kz

    o = get_object_or_404(Order, pk=order_id)
    sch, _ = OrderSchedule.objects.get_or_create(order=o)

    def as_int(v, default=0):
        try:
            return int((v or "").strip())
        except Exception:
            return default

    # статусы
    sch.status_ldsp = request.POST.get("status_ldsp", sch.status_ldsp)
    sch.status_film = request.POST.get("status_film", sch.status_film)
    sch.status_paint = request.POST.get("status_paint", sch.status_paint)

    # override даты
    def parse_date(key):
        s = (request.POST.get(key) or "").strip()
        if not s:
            return None
        try:
            return _date.fromisoformat(s)  # <-- ВАЖНО
        except ValueError:
            return None

    sch.due_ldsp_override = parse_date("due_ldsp_override")
    sch.due_film_override = parse_date("due_film_override")
    sch.due_paint_override = parse_date("due_paint_override")

    # extra days
    sch.extra_days_ldsp = as_int(request.POST.get("extra_days_ldsp"), sch.extra_days_ldsp)
    sch.extra_days_film = as_int(request.POST.get("extra_days_film"), sch.extra_days_film)
    sch.extra_days_paint = as_int(request.POST.get("extra_days_paint"), sch.extra_days_paint)

    # STOP/PLAY
    action = (request.POST.get("action") or "").lower()
    if action == "stop":
        n = as_int(request.POST.get("stop_days"), 0)
        if n > 0:
            today = timezone.localdate()
            sch.stop_until = add_workdays_kz(today, n)
    
            sch.status_ldsp = "ОТЛОЖЕН"
            sch.status_film = "ОТЛОЖЕН"
            sch.status_paint = "ОТЛОЖЕН"
    elif action == "play":
        sch.stop_until = None
        if sch.status_ldsp == "ОТЛОЖЕН": sch.status_ldsp = "ОЖИДАЕТ"
        if sch.status_film == "ОТЛОЖЕН": sch.status_film = "ОЖИДАЕТ"
        if sch.status_paint == "ОТЛОЖЕН": sch.status_paint = "ОЖИДАЕТ"


    sch.save()

    return JsonResponse({"ok": True})

@group_required("Цех")
@access_required("ACCESS_WORKSHOP")
def workshop(request):
    tasks = ProductionTask.objects.select_related("order").order_by("status", "-updated_at")
    return render(request, "workshop.html", {"tasks": tasks})


@group_required("Цех")
def update_task_status(request, pk, status):
    task = get_object_or_404(ProductionTask, pk=pk)
    if status in dict(ProductionTask._meta.get_field("status").choices):
        task.status = status
        task.save()
        messages.success(request, "Статус обновлён")
    return redirect("workshop")


# ===================== Purchase Sheet =====================




#from django.template.loader import render_to_string, render, get_object_or_404
@group_required("Бухгалтер", "Дизайнер_1", "Дизайнер_2")
def purchase_sheet(request, pk):
    order = get_object_or_404(Order, pk=pk)

    # Всегда корректно получаем/создаём лист закупа (OneToOne-safe)
    try:
        sheet = order.purchase_sheet
    except PurchaseSheet.DoesNotExist:
        sheet = PurchaseSheet(order=order)

    # Если форма открыта в модалке -> рендерим другой шаблон
    is_modal = (request.GET.get("modal") == "1") or (request.POST.get("modal") == "1")
    template_name = "purchase_sheet_modal.html" if is_modal else "purchase_sheet_form.html"

    if request.method == "POST":
        form = PurchaseSheetForm(request.POST, instance=sheet)
        if form.is_valid():
            # Поля для трекинга изменений
            track_fields = (
                [f"lds_name{i}" for i in range(1, 11)] +
                [f"lds_format{i}" for i in range(1, 11)] +
                [f"lds_color{i}" for i in range(1, 11)] +
                [f"pvc_color{i}" for i in range(1, 11)] +
                [f"pvc_wide_color{i}" for i in range(1, 11)] +
                [f"group{i}_facade" for i in range(1, 11)] +
                [f"group{i}_corpus" for i in range(1, 11)] +
                ["tabletop_count", "tabletop_length_3m", "hdf_count"]
            )

            def snapshot(obj):
                return {f: getattr(obj, f, None) for f in track_fields}

            # Снимок "до"
            if sheet.pk:
                try:
                    before = snapshot(PurchaseSheet.objects.get(pk=sheet.pk))
                except PurchaseSheet.DoesNotExist:
                    before = {f: None for f in track_fields}
            else:
                before = {f: None for f in track_fields}

            # Сохранение атомарно
            try:
                with transaction.atomic():
                    sheet_obj = form.save(commit=False)
                    sheet_obj.order = order
                    # нормализуем радио "3м/4м" в bool
                    _clean = form.cleaned_data.get("tabletop_length_3m")
                    if _clean is not None:
                        sheet_obj.tabletop_length_3m = bool(_clean)
                    sheet_obj.save()

                    # Обновим договор: lds_count = сумма листов ЛДСП
                    lds_total = sum((getattr(sheet_obj, f"lds_color{i}", 0) or 0) for i in range(1, 11))
                    contract, _ = Contract.objects.get_or_create(order=order)
                    if hasattr(contract, "lds_count"):
                        contract.lds_count = lds_total
                        contract.save()
            except Exception as e:
                messages.error(request, f"Ошибка при сохранении листа закупа: {e}")
                return render(request, template_name, {"order": order, "form": form})

            # Журнал изменений
            try:
                diff = human_diff(sheet_obj, before, track_fields)
            except Exception:
                diff = ""

            if (not diff) and getattr(form, "changed_data", None):
                _lines = []
                for fname in form.changed_data:
                    if fname in track_fields:
                        vb = _pretty_value(fname, before.get(fname, None)) if before else "—"
                        va = _pretty_value(fname, getattr(sheet_obj, fname, None))
                        label = _label_for_field(fname)
                        _lines.append(f"{label}  {vb} → {va}")
                diff = "\n".join(_lines)

            if diff:
                ChangeLog.objects.create(
                    order=order,
                    section="purchase_sheet",
                    action="updated" if any(before.values()) else "created",
                    diff_text=diff,
                    actor=request.user if request.user.is_authenticated else None,
                )


            # Без PRG: повторный рендер этой же страницы с флагом «just_saved»
            form = PurchaseSheetForm(instance=sheet_obj)
            return render(request, template_name, {
                "order": order,
                "form": form,
                "just_saved": True,   # покажем кнопки
            })

        # невалидный POST — упадём в общий рендер ниже

    else:
        form = PurchaseSheetForm(instance=sheet)

    # GET или невалидный POST — обычный рендер
    return render(request, template_name, {
        "order": order,
        "form": form,
    })







@group_required("Бухгалтер", "Дизайнер_1", "Дизайнер_2")
def purchase_sheet_pdf(request, pk):
        # Шрифты (кириллица)
    try:
        font_regular = finders.find("fonts/DejaVuSans.ttf")
        font_bold    = finders.find("fonts/DejaVuSans-Bold.ttf")
        pdfmetrics.registerFont(TTFont("DejaVuSans", font_regular))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", font_bold))
        registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold")
        base_font = "DejaVuSans"
        bold_font = "DejaVuSans-Bold"
    except Exception:
        base_font = "Helvetica"
        bold_font = "Helvetica-Bold"

    # Палитра (та же, что в PDF «Расчёт»)
    ACCENT = colors.HexColor("#6B4E2E")      # фирменный коричневый (для линий/акцентов)
    ORANGE = colors.HexColor("#F59E0B")      # фон заголовков секций (оранжевый)
    ORANGE_DARK = colors.HexColor("#D97706") # тень/линия под заголовком
    INK    = colors.HexColor("#111827")      # почти чёрный
    SUB    = colors.HexColor("#374151")      # тёмно-серый текст
    LINES  = colors.HexColor("#4B5563")      # тёмные линии таблиц
    
    
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontName=bold_font, fontSize=15, leading=18, textColor=INK))
    styles.add(ParagraphStyle(name="H2", fontName=bold_font, fontSize=11, leading=14, textColor=INK))
    styles.add(ParagraphStyle(name="P",  fontName=base_font, fontSize=9.5, leading=12, textColor=INK))
    styles.add(ParagraphStyle(name="S",  fontName=base_font, fontSize=8.5, leading=11, textColor=SUB))
    styles.add(ParagraphStyle(name="R",  fontName=base_font, fontSize=9,   leading=11, textColor=INK))
    styles.add(ParagraphStyle(name="Rr", parent=styles["R"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="Cell", parent=styles["P"]))  # ← вернули стиль Cell




    order = get_object_or_404(Order, pk=pk)
    sheet = getattr(order, "purchase_sheet", None)
    if not sheet:
        return HttpResponseForbidden("Лист закупа не заполнен")

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24,
        title=f"Лист закупа #{order.order_number}"
    )


    elements = []

    # Title + logo
    title_para = Paragraph(f"<font color='{ACCENT.hexval()}'>Лист закупа</font> — заказ №{order.order_number}", styles["H1"])


    # Ищем логотип через staticfiles (работает в DEV и после collectstatic)
    logo_file = None
    for candidate in (
        "img/logo.png", "img/logo.jpg", "img/logo.svg",
        "images/logo.png", "images/logo.jpg", "images/logo.svg",
        "logo.png", "logo.jpg", "logo.svg",
    ):
        p = finders.find(candidate)
        if p:
            logo_file = p
            break

    # Готовим Image с сохранением пропорций (макс. 50мм × 14мм)
    logo_img = ""
    if logo_file:
        try:
            ir = ImageReader(logo_file)
            iw, ih = ir.getSize()
            max_w, max_h = 50*mm, 14*mm
            scale = min(max_w / float(iw), max_h / float(ih)) if iw and ih else 1.0
            # Используем Image (он у тебя уже импортирован из reportlab.platypus)
            logo_img = Image(logo_file, width=iw * scale, height=ih * scale, hAlign="RIGHT")
        except Exception:
            logo_img = ""

    # Шапка: заголовок слева, логотип справа (фиксированная правая колонка 40мм)
    header_tbl = Table(
        [[title_para, logo_img]],
        colWidths=[doc.width - 40*mm, 40*mm],
        hAlign="LEFT",
    )
    
    def section_caption(text: str):
        bar = Table([[Paragraph(text, styles["H2"])]], colWidths=[doc.width], hAlign="LEFT")
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), ORANGE),
            ("TEXTCOLOR", (0,0), (-1,-1), colors.black),
            ("LINEBELOW", (0,0), (-1,-1), 0.8, ORANGE_DARK),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
            ("RIGHTPADDING",(0,0), (-1,-1), 5),
            ("TOPPADDING",  (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ]))
        return bar

    
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",  (1,0), (1,0), "RIGHT"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING",(0,0), (-1,-1), 0),
        ("TOPPADDING",  (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
    ]))
    elements.append(header_tbl)

    elements.append(Paragraph(f"Клиент: {order.customer_name}   Телефон: {order.phone}", styles["Cell"]))
    if order.item:
        elements.append(Paragraph(f"Изделие: {order.item}", styles["Cell"]))
    elements.append(Spacer(1, 8))

    # Table (Параметр / Значение / Примечание)
    data = [["Наименование", "Значение", "Примечание"]]

    def add_row(label, value, note=""):
        if value not in (None, "", 0, False):
            data.append([label, str(value), note])

    group_header_rows = []

    for i in range(1, 11):
        name = getattr(sheet, f"lds_name{i}", None)
        fmt = getattr(sheet, f"lds_format{i}", None)
        lds = getattr(sheet, f"lds_color{i}", None)
        pvc = getattr(sheet, f"pvc_color{i}", None)
        pvcw = getattr(sheet, f"pvc_wide_color{i}", None)

        tag_facade = getattr(sheet, f"group{i}_facade", False)
        tag_corpus = getattr(sheet, f"group{i}_corpus", False)
        tags = []
        if tag_facade: tags.append("ФАСАДЫ")
        if tag_corpus: tags.append("КОРПУС")
        tags_str = (" — " + " · ".join(tags)) if tags else ""

        if any([name, fmt, lds, pvc, pvcw, tag_facade, tag_corpus]):
            if len(data) > 1:
                data.append(["", "", ""])
            data.append([f"ЛДСП цвет {i}{tags_str}", "", ""])
            group_header_rows.append(len(data) - 1)

            add_row(f"ЛДСП цвет {i} (Наименование)", name, " ")
            add_row(f"ЛДСП цвет {i} (Формат)", fmt, " ")
            add_row(f"ЛДСП цвет {i} (листов)", lds, " ")
            add_row(f"ПВХ цвет {i} (метров)", pvc, " ")
            add_row(f"ПВХ ШИРОКАЯ цвет {i} (метров)", pvcw, " ")

    # Прочее
    if len(data) > 1:
        data.append(["", "", ""])
    data.append(["Прочее", "", ""])
    group_header_rows.append(len(data) - 1)

    if getattr(sheet, "tabletop_count", None):
        add_row("Столешница",
                f"{sheet.tabletop_count} шт., {'3м' if sheet.tabletop_length_3m else '4м'}",
                " ")
    add_row("ХДФ (задняя стенка, листов)", getattr(sheet, "hdf_count", None), " ")

    if len(data) == 1:
        add_row("Нет данных", "-", "")

    table = Table(data, colWidths=[180, 160, 180])
    ts = TableStyle([
        # Шапка
        ("FONTNAME",   (0,0), (-1,0), bold_font),
        ("FONTSIZE",   (0,0), (-1,0), 9.5),
        ("TEXTCOLOR",  (0,0), (-1,0), ACCENT),
        ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
        ("LINEBELOW",  (0,0), (-1,0), 0.9, LINES),
        ("ALIGN",      (0,0), (-1,0), "LEFT"),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),

        # Тело
        ("FONTNAME",   (0,1), (-1,-1), base_font),
        ("FONTSIZE",   (0,1), (-1,-1), 9),
        ("ALIGN",      (0,1), (0,-1), "LEFT"),
        ("ALIGN",      (1,1), (1,-1), "LEFT"),
        ("ALIGN",      (2,1), (2,-1), "LEFT"),
        ("VALIGN",     (0,1), (-1,-1), "MIDDLE"),
        ("LINEABOVE",  (0,1), (-1,-1), 0.6, LINES),

        # Паддинги
        ("LEFTPADDING",  (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING",   (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
    ])


    for r in group_header_rows:
        ts.add("SPAN", (0, r), (-1, r))
        ts.add("BACKGROUND", (0, r), (-1, r), ORANGE)          # фон секции
        ts.add("TEXTCOLOR",  (0, r), (-1, r), colors.black)    # белый текст
        ts.add("FONTNAME",   (0, r), (-1, r), bold_font)
        ts.add("FONTSIZE",   (0, r), (-1, r), 11)
        ts.add("TOPPADDING",    (0, r), (-1, r), 6)
        ts.add("BOTTOMPADDING", (0, r), (-1, r), 6)
        ts.add("LINEBELOW",  (0, r), (-1, r), 0.8, ORANGE_DARK)  # тонкая линия под плашкой


    for row_idx in range(1, len(data)):
        if row_idx in group_header_rows:
            continue
        row = data[row_idx]
        if row == ["", "", ""]:
            continue
        ts.add("LINEBELOW", (2, row_idx), (2, row_idx), 0.6, LINES)


    table.setStyle(ts)

    elements.append(Spacer(1, 10))
    elements.append(table)
    elements.append(Spacer(1, 12))
    created_dt  = timezone.localtime(timezone.now())
    created_str = created_dt.strftime("%d.%m.%Y %H:%M")  # например: 08.10.2025 12:34
    
    elements.append(Paragraph(
        f"Подпись:&nbsp;______________________&nbsp;&nbsp;Дата:&nbsp;<b>{created_str}</b>",
        styles["Cell"]
    ))
    
    # 1) Предупреждение в рамке (на всю ширину)
    elements.append(Spacer(1, 6))
    warn_para = Paragraph(
        "<b>Внимание:</b> оплата за дизайн-проект является оплатой интеллектуальной услуги и "
        "после начала работ не подлежит возврату. Оплата подтверждает согласие с ТЗ и составом работ.",
        styles["Cell"]
    )
    warn_box = Table([[warn_para]], colWidths=[doc.width], hAlign="LEFT")
    warn_box.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.whitesmoke),
        ("BOX",        (0,0), (-1,-1), 0.8, ACCENT),
        ("LEFTPADDING",(0,0), (-1,-1), 6),
        ("RIGHTPADDING",(0,0),(-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
    ]))
    elements.append(warn_box)
    
    # --- Карточка контактов и QR (современный стиль) ---


    ACCENT       = colors.HexColor("#f59e0b")   # ваш фирменный коричневый (уже используется выше)
    TITLE_BG     = colors.HexColor("#EFE9E3")   # светлый беж для шапки
    BORDER       = colors.HexColor("#D6CCC2")   # тонкая рамка карточки
    SUB_TXT      = colors.HexColor("#6B7280")   # приглушённый серый для вторичного текста
    DIVIDER      = colors.HexColor("#E7E1DA")   # вертикальный разделитель колонок
    
    elements.append(Spacer(1, 10))
    
    # Заголовок карточки на всю ширину
    card_title = Paragraph("<b>Контакты и быстрые ссылки</b>", styles["Cell"])
    
    # «Лейбл» слева с тонкой цветной полоской (не похоже на инпут)
    label_w = 32*mm  # ширина лейбла, чтобы «Производство» помещалось в одну строку
    def label_with_bar(text: str) -> Table:
        t = Table(
            [[ "", Paragraph(text, styles["Cell"]) ]],
            colWidths=[2.2*mm, label_w - 2.2*mm],
            hAlign="LEFT",
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,0), ACCENT),      # узкая цветная полоса слева
            ("BACKGROUND", (1,0), (1,0), TITLE_BG),    # мягкий фон под текстом лейбла
            ("TEXTCOLOR",  (1,0), (1,0), colors.black),
            ("ALIGN",      (0,0), (-1,-1), "LEFT"),
            ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
            ("FONTSIZE",   (1,0), (1,0), 9),
            ("LEFTPADDING",(0,0), (-1,-1), 0),
            ("RIGHTPADDING",(0,0),(-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0),(-1,-1), 3),
        ]))
        return t
    
    # Левая колонка (контакты)
    left_rows = [
        [label_with_bar("&nbsp;Телефон"), Paragraph("&nbsp;+7‒778‒533‒00‒33", styles["Cell"])],
        [label_with_bar("&nbsp;Офис"), Paragraph(
            "&nbsp;ул. Толстого 22а, этаж&nbsp;2<br/>"
            f"<font color='{SUB_TXT.hexval()}'>&nbsp;ежедневно 10:00–18:00</font> · "
            f"<font color='{SUB_TXT.hexval()}'>&nbsp;перерыв 13:00–14:00</font>",
            styles["Cell"]
        )],
        [label_with_bar("&nbsp;Производство"), Paragraph(
            "&nbsp;ул. Толстого 22а<br/>"
            f"<font color='{SUB_TXT.hexval()}'>&nbsp;ПН–ПТ 9:00–18:00 (перерыв 13:00–14:00)</font><br/>"
            f"<font color='{SUB_TXT.hexval()}'>&nbsp;СБ 9:00–14:00</font>",
            styles["Cell"]
        )],
    ]
    left_w  = doc.width * 0.58      # чуть шире слева — адреса читаются ровнее
    right_w = doc.width - left_w
    left_tbl = Table(left_rows, colWidths=[label_w, left_w - label_w], hAlign="LEFT")
    left_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",(0,0), (-1,-1), 0),
        ("RIGHTPADDING",(0,0),(-1,-1), 10),
        ("TOPPADDING",(0,0), (-1,-1), 2),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("ROWSPACING",(0,0), (-1,-1), 5),
    ]))
    
    # Правая колонка (QR)
    qr_size = 26*mm
    qr_insta = createBarcodeDrawing("QR", value="https://www.instagram.com/wooddecor.kz/",
                                    barWidth=qr_size, barHeight=qr_size)
    qr_site  = createBarcodeDrawing("QR", value="https://wooddecor.kz/",
                                    barWidth=qr_size, barHeight=qr_size)
    qr_2gis  = createBarcodeDrawing("QR", value="https://go.2gis.com/tbtmZ",
                                    barWidth=qr_size, barHeight=qr_size)
    
    def cap(text: str) -> Paragraph:
        return Paragraph(f"<font size='8' color='{SUB_TXT.hexval()}'>{text}</font>", styles["Cell"])
    
    qr_grid = Table(
        [
            [qr_insta, qr_site, qr_2gis],
            [cap("Instagram"), cap("Сайт"), cap("2GIS")]
        ],
        colWidths=[(right_w - 18)/3]*3,
        hAlign="CENTER"
    )
    qr_grid.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN",(0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING",(0,0), (-1,0), 6),
        ("TOPPADDING",(0,1), (-1,1), 2),
    ]))
    
    right_tbl = Table([[qr_grid]], colWidths=[right_w], hAlign="LEFT")
    right_tbl.setStyle(TableStyle([
        ("LEFTPADDING",(0,0), (-1,-1), 0),
        ("RIGHTPADDING",(0,0),(-1,-1), 0),
        ("TOPPADDING",(0,0), (-1,-1), 2),
        ("BOTTOMPADDING",(0,0), (-1,-1), 2),
    ]))
    
    # Общая карточка
    card = Table(
        [[card_title, ""],
         [left_tbl,   right_tbl]],
        colWidths=[left_w, right_w],
        hAlign="LEFT"
    )
    card.setStyle(TableStyle([
        # заголовок на всю ширину
        ("SPAN", (0,0), (-1,0)),
        ("BACKGROUND",(0,0), (-1,0), TITLE_BG),
        ("TEXTCOLOR", (0,0), (-1,0), colors.black),
    
        # рамка карточки
        ("BOX", (0,0), (-1,-1), 0.8, BORDER),
    
        # вертикальный разделитель между колонками
        ("LINEBEFORE", (1,1), (1,1), 0.8, DIVIDER),
    
        # отступы шапки
        ("LEFTPADDING",(0,0), (-1,0), 10),
        ("RIGHTPADDING",(0,0),(-1,0), 10),
        ("TOPPADDING",(0,0), (-1,0), 7),
        ("BOTTOMPADDING",(0,0), (-1,0), 7),
    
        # отступы контента
        ("LEFTPADDING",(0,1), (-1,-1), 10),
        ("RIGHTPADDING",(0,1),(-1,-1), 10),
        ("TOPPADDING",(0,1), (-1,-1), 8),
        ("BOTTOMPADDING",(0,1), (-1,-1), 10),
    ]))
    elements.append(card)
    elements.append(Spacer(1, 6))





    doc.build(elements)
    buffer.seek(0)
    # Имя заказчика — чистим для имени файла
    customer = (getattr(order, "customer_name", "") or "").strip() or "Без_имени"
    customer = re.sub(r'[\\/*?:"<>|]+', "_", customer)  # запрещённые символы -> _
    customer = re.sub(r"\s+", "_", customer)            # пробелы -> подчёркивания
    return FileResponse(buffer, as_attachment=True, filename=f"{order.order_number}_{customer}_ЛИСТ_ЗАКУПА.pdf")


# ===================== Contract =====================
from contracts.services import get_order_aggregate

@group_required("Бухгалтер", "Дизайнер_1", "Дизайнер_2")
@login_required
def contract_view(request, pk):
    # Заказ по PK (тот самый pk из URL /orders/<pk>/contract/)
    order = get_object_or_404(Order, pk=pk)

    # Проверка доступа как у тебя было
    if not (request.user.is_staff or getattr(order, "created_by_id", None) == request.user.id):
        return HttpResponseForbidden("Нет доступа")

    # Гарантируем, что есть объект Contract для этого заказа
    contract_obj, _ = Contract.objects.get_or_create(order=order)

    # ---------- POST: сохранение в БД ----------
    if request.method == "POST":
        spec_raw = request.POST.get("spec_json") or "[]"
        alloc_raw = request.POST.get("materials_alloc_json") or "[]"

        # Разбираем JSON из скрытых полей
        try:
            spec_data = json.loads(spec_raw)
            if not isinstance(spec_data, list):
                spec_data = []
        except Exception:
            spec_data = []

        try:
            alloc_data = json.loads(alloc_raw)
            if not isinstance(alloc_data, list):
                alloc_data = []
        except Exception:
            alloc_data = []

        # Сохраняем в модель
        contract_obj.spec_json = spec_data

        # Если в модели есть поле materials_alloc_json – пишем туда
        if hasattr(contract_obj, "materials_alloc_json"):
            contract_obj.materials_alloc_json = alloc_data

        contract_obj.save()

        # PRG-паттерн: после POST делаем redirect, чтобы не было повторной отправки формы
        return redirect("contract_view", pk=order.pk)

    # ---------- GET: отображение договора ----------

    # Агрегат для шаблона (как у тебя было)
    agg = get_order_aggregate(pk)

    # Подготовка JSON-данных для JS в шаблоне
    spec_initial = getattr(contract_obj, "spec_json", [])
    if not isinstance(spec_initial, list):
        spec_initial = []

    if hasattr(contract_obj, "materials_alloc_json"):
        alloc_initial = getattr(contract_obj, "materials_alloc_json", [])
        if not isinstance(alloc_initial, list):
            alloc_initial = []
    else:
        alloc_initial = []

    ctx = {
        "order": agg,
        # сумма “как в Оплате”
        "paid_sum": getattr(agg.payments, "total_paid", 0),
        "today": timezone.localdate(),
        "header_left_lines": ['8 (778) 533-00-33','8 (701) 65-888-59','8 (7172) 20-06-73'],
        "header_right_lines": ['г. Астана,','Толстого 22 А.','wooddecor.kz'],
        "pdf_mode": request.GET.get("pdf") == "1",
        "show_print_button": True,

        # Эти два поля нужны твоему contract.html:
        #    window.__CONTRACT_SPEC_INITIAL = {{ contract_spec_json|default:"[]"|safe }};
        #    window.__CONTRACT_MATERIALS_ALLOC_INITIAL = {{ contract_materials_alloc_json|default:"[]"|safe }};
        "contract_spec_json": json.dumps(spec_initial, ensure_ascii=False),
        "contract_materials_alloc_json": json.dumps(alloc_initial, ensure_ascii=False),
    }

    return render(request, "orders/contract.html", ctx)




@group_required("Бухгалтер", "Дизайнер_1", "Дизайнер_2")
@login_required
def contract_pdf(request, order_id: int):
    """
    PDF 'Бланк заказа' — шапка + 1. Информация + Материалы + 3. Спецификация по подгруппам
    + подпись на каждой странице и отдельная страница «Условия работы».
    """
    from reportlab.platypus import PageBreak
    from django.utils import timezone

    agg = get_order_aggregate(order_id)
    order = get_object_or_404(Order, pk=order_id)

    # --- проверка доступа (как в contract_view) ---
    if not (request.user.is_staff or getattr(order, "created_by_id", None) == request.user.id):
        return HttpResponseForbidden("Нет доступа")

    # --- отмечаем, что PDF бланка был сформирован хотя бы один раз ---
    if not getattr(order, "contract_blank_generated", False):
        order.contract_blank_generated = True
        order.save(update_fields=["contract_blank_generated"])

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=5 * mm,
        bottomMargin=18 * mm,  # чуть больше места снизу под подпись
    )

    # ---- ШРИФТЫ ----
    try:
        font_regular = finders.find("fonts/DejaVuSans.ttf")
        font_bold = finders.find("fonts/DejaVuSans-Bold.ttf")
        if font_regular:
            pdfmetrics.registerFont(TTFont("DejaVuSans", font_regular))
        if font_bold:
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", font_bold))
        registerFontFamily(
            "DejaVuSans",
            normal="DejaVuSans",
            bold="DejaVuSans-Bold",
            italic="DejaVuSans",
            boldItalic="DejaVuSans-Bold",
        )
        base_font = "DejaVuSans"
        bold_font = "DejaVuSans-Bold"
    except Exception as e:
        print("[contract_pdf] font registration error:", e)
        base_font = "Helvetica"
        bold_font = "Helvetica-Bold"

    # ---- ПАЛИТРА ----
    ACCENT = COMPANY_ORANGE
    INK = COMPANY_DARK
    SUB = colors.HexColor("#4B5563")
    LABEL_BG = colors.HexColor("#f7f9fc")
    LINES = colors.HexColor("#D1D5DB")

    # ---- СТИЛИ ----
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontName=bold_font, fontSize=15,
                              leading=18, textColor=INK, alignment=1))
    styles.add(ParagraphStyle(name="H3", fontName=bold_font, fontSize=11,
                              leading=14, textColor=INK))
    styles.add(ParagraphStyle(name="H4", fontName=bold_font, fontSize=10,
                              leading=13, textColor=colors.white))
    styles.add(ParagraphStyle(name="P", fontName=base_font, fontSize=9.5,
                              leading=12, textColor=INK))
    styles.add(ParagraphStyle(name="S", fontName=base_font, fontSize=8.5,
                              leading=11, textColor=SUB))

    h3 = styles["H3"]
    h4 = styles["H4"]

    story = []

    # ---- ШАПКА ----
    left_lines = ["8 (778) 533-00-33", "8 (701) 65-888-59", "8 (7172) 20-06-73"]
    right_lines = ["г. Астана,", "Толстого 22 А.", "wooddecor.kz"]

    def lines_to_paragraph(lines, align="LEFT"):
        st = styles["S"].clone("S_" + align)
        st.alignment = {"LEFT": 0, "CENTER": 1, "RIGHT": 2}[align]
        return Paragraph("<br/>".join(escape(str(x)) for x in lines), st)

    logo_path = finders.find("img/logo.png")
    logo = Image(logo_path, width=65 * mm, height=13 * mm, hAlign="CENTER") if logo_path \
        else Paragraph("WoodDecor", styles["H1"])

    header_tbl = Table(
        [[lines_to_paragraph(left_lines, "LEFT"),
          logo,
          lines_to_paragraph(right_lines, "RIGHT")]],
        colWidths=[doc.width * 0.25, doc.width * 0.5, doc.width * 0.25],
        hAlign="CENTER",
    )
    header_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), -14),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header_tbl)
    story.append(Spacer(1, 0.1 * mm))
    story.append(
        Table(
            [[""]],
            colWidths=[doc.width],
            style=[("LINEBELOW", (0, 0), (-1, -1), 1, ACCENT)],
            hAlign="CENTER",
        )
    )
    story.append(Spacer(1, 1.2 * mm))

    # ---- ЗАГОЛОВОК ----
    order_no = getattr(agg, "number", None) or agg.order_id
    story.append(Paragraph(f"Бланк заказа № {order_no}", styles["H1"]))
    story.append(Spacer(1, 2 * mm))

    # ---- 1. ИНФОРМАЦИЯ ----
    def fmt_date(d):
        if not d:
            return "—"
        return d.strftime("%d.%m.%Y")

    def fmt_money(val):
        try:
            dec = Decimal(str(val or 0)).quantize(Decimal("0.01"))
        except Exception:
            dec = Decimal("0.00")
        return f"{dec:,.0f}".replace(",", " ")

    ps = getattr(agg.facades, "payment_status", "") or ""

    def facade_value(kind: str) -> str:
        if ps == "NOT_SPECIFIED":
            return "0"
        if ps == "NOT_PAID":
            return "НЕ оплачено"
        cost_attr = "paint_cost" if kind == "paint" else "film_cost"
        total_attr = "paint_total" if kind == "paint" else "film_total"
        cost = getattr(agg.facades, cost_attr, None)
        if cost is None:
            cost = getattr(agg.facades, total_attr, None)
        return fmt_money(cost)

    paint_val = facade_value("paint")
    film_val = facade_value("film")

    label_w = 45 * mm
    value_w = 55 * mm
    info_total_width = label_w * 2 + value_w * 2

    info_data = [
        [
            "Дата оплаты услуг:",
            fmt_date(getattr(agg.payments, "last_service_payment_date", None)),
            "Дата завоза материалов:",
            fmt_date(getattr(agg.warehouse, "last_receipt_date", None)),
        ],
        [
            "Заказчик:",
            getattr(agg.customer, "name", "") or "—",
            "Тел.:",
            getattr(agg.customer, "phone", "") or "—",
        ],
        [
            "Сумма заказа (тг.):",
            fmt_money(getattr(agg.payments, "total_paid", None)),
            "Услуги дизайнера (тг.):",
            fmt_money(getattr(agg.payments, "designer_paid_total", None)),
        ],
        [
            "Фасады покраска (тг.):",
            paint_val,
            "Фасады плёнка (тг.):",
            film_val,
        ],
    ]

    info_tbl = Table(
        info_data,
        colWidths=[label_w, value_w, label_w, value_w],
        hAlign="CENTER",
    )
    info_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), base_font),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                ("GRID", (0, 0), (-1, -1), 0.4, LINES),
                ("BACKGROUND", (0, 0), (0, -1), LABEL_BG),
                ("BACKGROUND", (2, 0), (2, -1), LABEL_BG),
                ("BACKGROUND", (1, 0), (1, -1), colors.white),
                ("BACKGROUND", (3, 0), (3, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(info_tbl)

    # Запомним место, куда нужно будет вставить "Материалы"
    materials_anchor_index = len(story)

    # ---- 3. СПЕЦИФИКАЦИЯ (и заодно разбор spec для материалов) ----
    story.append(Spacer(1, 1))

    raw_spec = request.GET.get("spec")
    spec_groups = []
    if raw_spec:
        try:
            decoded = json.loads(raw_spec)
            if isinstance(decoded, list):
                spec_groups = decoded
        except Exception as e:
            print("[contract_pdf] bad spec param:", e)

    def _clean(val) -> str:
        return escape(str(val or "")).strip()

    TOGGLE_LABELS = {
        "gola": "GOLA-профиль",
        "tipon": "Tip-On",
        "legs": "Регулируемые ножки",
        "nonstd": "Не станд. изделие",
    }

    # ---- 2. МАТЕРИАЛЫ (чипы, максимально компактно) ----
    materials_elements = []

    def _s(v):
        return escape(str(v or "")).strip()

    mat_rows = []

    # 2.1. Принято на складе — чипы 2 строки (материал+размер / количество с заливкой)
    wh = getattr(agg, "warehouse", None)
    if wh is not None:
        mats = getattr(wh, "materials", None) or []
        pill_cells = []
        for m in mats:
            name = _s(getattr(m, "name", ""))
            size = _s(getattr(m, "size", ""))
            qty = getattr(m, "qty", getattr(m, "quantity", ""))
            qty = "" if qty in (None, "", 0, "0") else str(qty)

            # верхняя строка: ЛДСП • 2750×1830
            top_parts = []
            if name:
                top_parts.append(name)
            if size:
                top_parts.append(size)
            top_line = "  •  ".join(top_parts)

            # нижняя строка: 5 л. (если есть количество)
            bottom_line = qty

            if not top_line and not bottom_line:
                continue

            rows_chip = []
            if top_line:
                rows_chip.append([Paragraph(top_line, styles["S"])])
            if bottom_line:
                rows_chip.append([Paragraph(bottom_line, styles["S"])])

            chip_tbl = Table(rows_chip, hAlign="LEFT")
            chip_style = [
                ("FONTNAME", (0, 0), (-1, -1), base_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("GRID", (0, 0), (-1, -1), 0.4, LINES),
            ]
            if bottom_line:
                last_row = len(rows_chip) - 1
                chip_style.append(
                    ("BACKGROUND", (0, last_row), (0, last_row), colors.HexColor("#FFF4CC"))
                )

            chip_tbl.setStyle(TableStyle(chip_style))
            pill_cells.append(chip_tbl)

        if pill_cells:
            wh_tbl = Table([pill_cells], hAlign="LEFT")
            wh_tbl.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            mat_rows.append(
                [
                    Paragraph("<b>Принято на складе</b>", styles["S"]),
                    wh_tbl,
                ]
            )

    # 2.2. МДФ / Фасады — суммарная квадратура по цветам из СПЕЦИФИКАЦИИ
    fac = getattr(agg, "facades", None)
    if fac is not None:
        status = str(getattr(fac, "payment_status", "") or "").upper()
        if status not in ("NOT_SPECIFIED", "NOT_PAID") and spec_groups:
            paint_totals = {}  # color -> Decimal
            film_totals = {}   # color -> Decimal

            def add_area(bucket: dict, color_val, area_val):
                color = (_s(color_val) or "").strip()
                if not color:
                    return
                try:
                    dec = Decimal(str(area_val).replace(",", "."))
                except (InvalidOperation, TypeError, ValueError):
                    return
                if dec <= 0:
                    return
                bucket[color] = bucket.get(color, Decimal("0")) + dec

            for g in spec_groups:
                for it in g.get("mdf_paint_list") or []:
                    add_area(paint_totals, it.get("color"), it.get("area"))
                for it in g.get("mdf_film_list") or []:
                    add_area(film_totals, it.get("color"), it.get("area"))

            lines = []

            def fmt_area(dec: Decimal) -> str:
                s = f"{dec.quantize(Decimal('0.01'))}".rstrip("0").rstrip(".")
                return f"{s} м²"

            for color, total in paint_totals.items():
                lines.append(f"Краска: {color} — {fmt_area(total)}")
            for color, total in film_totals.items():
                lines.append(f"Плёнка: {color} — {fmt_area(total)}")

            if lines:
                mat_rows.append(
                    [
                        Paragraph("<b>МДФ / Фасады</b>", styles["S"]),
                        Paragraph("<br/>".join(_s(l) for l in lines), styles["S"]),
                    ]
                )

    if mat_rows:
        materials_elements.append(Spacer(1, 2 * mm))
        materials_elements.append(Paragraph("Материалы:", h3))
        materials_elements.append(Spacer(1, 1 * mm))

        mats_tbl = Table(
            mat_rows,
            colWidths=[label_w, info_total_width - label_w],
            hAlign="CENTER",
        )
        mats_tbl.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), base_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, LINES),
                    ("BACKGROUND", (0, 0), (0, -1), LABEL_BG),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ]
            )
        )
        materials_elements.append(mats_tbl)
        materials_elements.append(Spacer(1, 3 * mm))

    if materials_elements:
        story[materials_anchor_index:materials_anchor_index] = materials_elements

    # ---- СПЕЦИФИКАЦИЯ (как была) ----
    if spec_groups:
        story.append(Paragraph("Спецификация:", h3))
        story.append(Spacer(1, 2 * mm))

        for g in spec_groups:
            name = _clean(g.get("name", ""))
            if not name:
                continue

            header_tbl = Table(
                [[Paragraph(f"<b>{name}</b>", h4)]],
                colWidths=[info_total_width],
                hAlign="CENTER",
            )
            header_tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )

            rows = []
            spans = []
            highlight_cells = []

            def _p(text: str):
                return Paragraph(_clean(text), styles["S"])

            def add_text_row(label: str, text: str):
                text = _clean(text)
                if not text:
                    return
                row_idx = len(rows)
                rows.append(
                    [
                        _p(label),
                        Paragraph(text, styles["S"]),
                        Paragraph("", styles["S"]),
                        Paragraph("", styles["S"]),
                        Paragraph("", styles["S"]),
                    ]
                )
                spans.append(("SPAN", (1, row_idx), (4, row_idx)))

            def add_ldsp_row(label: str, value: str, note: str = "", bold_value: bool = True):
                value = _clean(value)
                note = _clean(note)
                if not value and not note:
                    return
                main_txt = f"<b>{value}</b>" if bold_value and value else value
                rows.append(
                    [
                        _p(label),
                        Paragraph(main_txt or "", styles["S"]),
                        Paragraph(note or "", styles["S"]),
                        Paragraph("", styles["S"]),
                        Paragraph("", styles["S"]),
                    ]
                )
                row_idx = len(rows) - 1
                spans.append(("SPAN", (2, row_idx), (4, row_idx)))

            def add_mdf_row(label: str, value: str, note: str = "", color: str = "", area: str = "", bold_value: bool = True):
                value = _clean(value)
                note = _clean(note)
                color = _clean(color)
                area = _clean(area)
                if not value and not note and not color and not area:
                    return
                if area:
                    area = f"{area} м²"
                main_txt = f"<b>{value}</b>" if bold_value and value else value
                rows.append(
                    [
                        _p(label),
                        Paragraph(main_txt or "", styles["S"]),
                        Paragraph(color or "", styles["S"]),
                        Paragraph(note or "", styles["S"]),
                        Paragraph(area or "", styles["S"]),
                    ]
                )
                row_idx = len(rows) - 1
                highlight_cells.append((2, row_idx))

            def add_hardware_row(label: str, brand: str, note: str = ""):
                brand = _clean(brand)
                note = _clean(note)
                if not brand and not note:
                    return
                main_txt = f"<b>{brand}</b>" if brand else ""
                rows.append(
                    [
                        _p(label),
                        Paragraph(main_txt or "", styles["S"]),
                        Paragraph(note or "", styles["S"]),
                        Paragraph("", styles["S"]),
                        Paragraph("", styles["S"]),
                    ]
                )
                row_idx = len(rows) - 1
                spans.append(("SPAN", (2, row_idx), (4, row_idx)))

            def add_free_row(name_f: str, desc: str, qty):
                name_f = _clean(name_f)
                desc = _clean(desc)
                if not name_f:
                    return
                qty_str = ""
                if qty not in (None, "", 0):
                    qty_str = f"× {qty}"
                main_txt = name_f or desc
                rows.append(
                    [
                        _p("Доп. строка"),
                        Paragraph(main_txt or "", styles["S"]),
                        Paragraph("", styles["S"]),
                        Paragraph(qty_str, styles["S"]),
                        Paragraph("", styles["S"]),
                    ]
                )
                row_idx = len(rows) - 1
                spans.append(("SPAN", (1, row_idx), (2, row_idx)))

            def add_options_row(labels):
                labels = [str(x) for x in labels or []]
                if not labels:
                    return
                row_idx = len(rows)
                pill_cells = []
                for lbl in labels:
                    safe = escape(lbl)
                    pill_cells.append(
                        Paragraph(f'<font color="#16A34A">●</font>&nbsp;{safe}', styles["S"])
                    )
                pills_tbl = Table([pill_cells], hAlign="LEFT")
                pills_tbl.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                            ("GRID", (0, 0), (-1, -1), 0.4, ACCENT),
                        ]
                    )
                )
                rows.append(
                    [
                        _p("Опции"),
                        pills_tbl,
                        Paragraph("", styles["S"]),
                        Paragraph("", styles["S"]),
                        Paragraph("", styles["S"]),
                    ]
                )
                spans.append(("SPAN", (1, row_idx), (4, row_idx)))

            # ЛДСП
            for item in g.get("ldsp_body_list") or []:
                add_ldsp_row("ЛДСП корпус", item.get("value"), item.get("note"))
            for item in g.get("ldsp_fas_list") or []:
                add_ldsp_row("ЛДСП фасады", item.get("value"), item.get("note"))

            # МДФ
            for item in g.get("mdf_paint_list") or []:
                add_mdf_row(
                    "МДФ (краска)",
                    item.get("value"),
                    item.get("note"),
                    item.get("color"),
                    item.get("area"),
                )
            for item in g.get("mdf_film_list") or []:
                add_mdf_row(
                    "МДФ (плёнка)",
                    item.get("value"),
                    item.get("note"),
                    item.get("color"),
                    item.get("area"),
                )

            # Фурнитура
            if g.get("hardware") or g.get("hardware_note"):
                add_hardware_row("Фурнитура", g.get("hardware"), g.get("hardware_note"))

            # Дополнительно
            if g.get("extra"):
                add_text_row("Дополнительно", g.get("extra"))

            # Доп. строки
            for item in g.get("free") or []:
                add_free_row(item.get("name"), item.get("desc"), item.get("qty"))

            # Опции
            toggles = g.get("toggles") or {}
            active_opts = [label for key, label in TOGGLE_LABELS.items() if toggles.get(key)]
            if active_opts:
                add_options_row(active_opts)

            if rows:
                spec_label_w = 30 * mm
                value_total_w = info_total_width - spec_label_w
                area_w = 14 * mm
                main_total = max(value_total_w - area_w, 10 * mm)
                col_main = main_total / 3.0

                spec_tbl = Table(
                    rows,
                    colWidths=[spec_label_w, col_main, col_main, col_main, area_w],
                    hAlign="CENTER",
                )
                base_style = [
                    ("FONTNAME", (0, 0), (-1, -1), base_font),
                    ("FONTNAME", (0, 0), (0, -1), bold_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("LEADING", (0, 0), (-1, -1), 10),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, LINES),
                    ("BACKGROUND", (0, 0), (0, -1), LABEL_BG),
                    ("BACKGROUND", (1, 0), (-1, -1), colors.white),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
                for col, row in highlight_cells:
                    base_style.append(
                        ("BACKGROUND", (col, row), (col, row), colors.HexColor("#FFF4CC"))
                    )
                spec_tbl.setStyle(TableStyle(base_style + spans))

                # --- НОВОЕ: собираем группу в единый блок и не даём ей рваться ---
                group_block = [
                    header_tbl,             # шапка группы
                    spec_tbl,               # таблица спецификации
                    Spacer(1, 2 * mm),      # отступ после группы
                ]
                story.append(KeepTogether(group_block))
            else:
                # если по какой-то причине в группе нет строк,
                # всё равно добавим шапку и небольшой отступ (необязательно)
                story.append(header_tbl)
                story.append(Spacer(1, 2 * mm))

    # ---- ОТДЕЛЬНАЯ СТРАНИЦА «Условия работы» ----
    story.append(PageBreak())
    # ---- ШАПКА ----
    left_lines = ["8 (778) 533-00-33", "8 (701) 65-888-59", "8 (7172) 20-06-73"]
    right_lines = ["г. Астана,", "Толстого 22 А.", "wooddecor.kz"]

    def lines_to_paragraph(lines, align="LEFT"):
        st = styles["S"].clone("S_" + align)
        st.alignment = {"LEFT": 0, "CENTER": 1, "RIGHT": 2}[align]
        return Paragraph("<br/>".join(escape(str(x)) for x in lines), st)

    logo_path = finders.find("img/logo.png")
    logo = Image(logo_path, width=65 * mm, height=13 * mm, hAlign="CENTER") if logo_path \
        else Paragraph("WoodDecor", styles["H1"])

    header_tbl = Table(
        [[lines_to_paragraph(left_lines, "LEFT"),
          logo,
          lines_to_paragraph(right_lines, "RIGHT")]],
        colWidths=[doc.width * 0.25, doc.width * 0.5, doc.width * 0.25],
        hAlign="CENTER",
    )
    header_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), -14),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header_tbl)
    story.append(Spacer(1, 0.1 * mm))
    story.append(
        Table(
            [[""]],
            colWidths=[doc.width],
            style=[("LINEBELOW", (0, 0), (-1, -1), 1, ACCENT)],
            hAlign="CENTER",
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Условия работы", h3))
    story.append(Spacer(1, 3 * mm))

    cond_style = styles["P"]

    bullets = [
        (
            "СРОКИ.",
            "Корпусная часть, фасады из ЛДСП, черновые/плёночные МДФ фасады «Модерн» — "
            "14 рабочих дней. Фасады МДФ крашенные и черновые с фрезеровкой — "
            "25 рабочих дней."
        ),
        (
            "ФУРНИТУРА.",
            "Фурнитура, выбранная по Проекту, оплачивается отдельно, по готовности заказа, "
            "согласно выставленному счёту на оплату от Исполнителя. Забрать комплект "
            "фурнитуры можно вместе с готовым заказом. Исключение: ручки и анкера – "
            "приобретаются Заказчиком самостоятельно в магазинах."
        ),
        (
            "ЗАМЕРЫ И ОТВЕТСТВЕННОСТЬ.",
            "Проект и эскиз составлены согласно предоставленных размеров и замеров Заказчика. "
            "За совпадение/несовпадение всех размеров, предоставленных Заказчиком, ответственность "
            "несёт Заказчик. При заборе/вывозе заказа из цеха Заказчик проверяет детали "
            "на наличие/отсутствие брака, сколов; при наличии – сразу показывает в цеху."
        ),
        (
            "ТЕХНИКА.",
            "Если в проекте имеется техника, Заказчик обязуется предоставить все артикулы техники "
            "в течение 3 (трёх) дней после оформления Бланка заказа. В противном случае сроки "
            "изготовления заказа могут быть перенесены."
        ),
        (
            "СТОЛЕШНИЦА.",
            "Распил и закатка кромкой столешницы выполняются по фактическим размерам, "
            "предоставленным Заказчиком после выставления корпусной части. Вырезы в столешнице "
            "Заказчик выполняет самостоятельно."
        ),
        (
            "ЧЕРНОВЫЕ МДФ ФАСАДЫ.",
            "При заказе черновых МДФ фасадов материал МДФ завозит Заказчик в нужном количестве. "
            "При выдаче в цеху Заказчик принимает фасады: проверяет количество, тип фрезеровки "
            "и качество работы. Остатки материалов выдаются Заказчику с заказом либо "
            "утилизируются сразу после передачи заказа."
        ),
    ]

    for title, text in bullets:
        story.append(
            Paragraph(f"<b>{escape(title)}</b> {escape(text)}", cond_style)
        )
        story.append(Spacer(1, 2 * mm))

    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "<b>ЗАКАЗ ВЫДАЁТСЯ ТОЛЬКО ПРИ НАЛИЧИИ ДАННОГО БЛАНКА ЗАКАЗА! "
            "БЕЗ БЛАНКА ЦЕХ ЗАКАЗ НЕ ВЫДАЁТ.</b>",
            cond_style
        )
    )

    # ---- ПОДПИСЬ НА КАЖДОЙ СТРАНИЦЕ ----
    doc_date = timezone.localdate()
    doc_date_str = doc_date.strftime("%d.%m.%Y")

    # ФИО из заказа: Фамилия + Имя
    last_name = (getattr(order, "last_name", "") or "").strip()
    first_name = (getattr(order, "customer_name", "") or "").strip()
    fio = f"{last_name} {first_name}".strip()
    if not fio:
        # запасной вариант — имя из агрегата, если вдруг что-то не заполнено
        fio = (getattr(agg.customer, "name", "") or "").strip()
    if not fio:
        fio = "________________"

    # ИИН из заказа
    customer_iin = (getattr(order, "iin", "") or "").strip()
    if not customer_iin:
        # на всякий случай попробуем ещё возможные поля, как было
        customer_iin = (
            getattr(agg.customer, "iin", None)
            or getattr(agg.customer, "iin_number", None)
            or getattr(agg, "customer_iin", None)
            or ""
        )
        customer_iin = str(customer_iin).strip()

    if not customer_iin:
        customer_iin = "________________"

    def _draw_footer(canvas, doc_):
        canvas.saveState()
        try:
            canvas.setFont(base_font, 8.5)
        except Exception:
            canvas.setFont("Helvetica", 8.5)
    
        y = 12 * mm
    
        # Лево: дата оформления
        canvas.drawString(
            doc_.leftMargin,
            y + 4,
            f"Дата оформления: {doc_date_str}",
        )
    
        # Право: номер страницы
        page_text = f"Стр. {doc_.page}"
        canvas.drawRightString(
            doc_.pagesize[0] - doc_.rightMargin,
            y + 4,
            page_text,
        )
    
        # Нижняя строка: согласие + подпись + ИИН
        line = (
            f"С вышеизложенным согласен(-на). {fio}  ______________________  ИИН: {customer_iin}"
        )
        canvas.drawString(doc_.leftMargin, y - 4, line)
    
        canvas.restoreState()

    # --- СБОРКА PDF ---
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    buf.seek(0)

    customer_name_for_file = (
        (getattr(agg.customer, "name", "") or "Клиент").strip().replace("/", "_")
    )
    filename = f"{order_no}_{customer_name_for_file}_Бланк_заказа.pdf"
    return FileResponse(buf, as_attachment=True, filename=filename)
    
    

# ===================== Основной договор (заглушка) =====================
@group_required("Бухгалтер", "Дизайнер_1", "Дизайнер_2")
@login_required
def main_contract_view(request, pk):
    """
    Просмотр основного договора по заказу.
    Пока показывает только HTML-заглушку с данными по заказу.
    Позже сюда можно будет добавить формирование PDF.
    """
    order = get_object_or_404(Order, pk=pk)

    # Те же правила доступа, что и в contract_view
    if not (request.user.is_staff or getattr(order, "created_by_id", None) == request.user.id):
        return HttpResponseForbidden("Нет доступа")

    context = {
        "order": order,
        "today": timezone.localdate(),
    }
    return render(request, "orders/main_contract.html", context)

def main_contract_pdf(request, order_id: int):
    """
    PDF основного договора (пока заглушка).
    Использует те же шрифты DejaVuSans, что и 'Бланк заказа',
    чтобы корректно отображалась кириллица.
    """
    from reportlab.lib.styles import ParagraphStyle

    order = get_object_or_404(Order, pk=order_id)

    # Те же правила доступа, что и для contract_pdf
    if not (request.user.is_staff or getattr(order, "created_by_id", None) == request.user.id):
        return HttpResponseForbidden("Нет доступа")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    # Базовые имена шрифтов из общих настроек PDF
    base_font = globals().get("PDF_FONT_REG", "Helvetica")
    bold_font = globals().get("PDF_FONT_BLD", "Helvetica-Bold")

    # Свой стиль заголовка и текста с кириллицей
    styles.add(ParagraphStyle(
        name="MainContractTitle",
        parent=styles["Heading1"],
        fontName=bold_font,
        fontSize=16,
        leading=20,
        alignment=1,  # центр
    ))
    styles.add(ParagraphStyle(
        name="MainContractBase",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=11,
        leading=14,
    ))

    title_style = styles["MainContractTitle"]
    base_style = styles["MainContractBase"]

    story = []

    # Заголовок
    title = f"ОСНОВНОЙ ДОГОВОР по заказу №{order.order_number}"
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 12 * mm))

    # Блок с данными клиента
    client_lines = [
        f"Клиент: {order.customer_name} {order.last_name or ''}".strip(),
        f"Телефон: {order.phone or ''}",
    ]
    if getattr(order, "iin", None):
        client_lines.append(f"ИИН: {order.iin}")

    for line in client_lines:
        story.append(Paragraph(line, base_style))
        story.append(Spacer(1, 2 * mm))

    story.append(Spacer(1, 10 * mm))

    # Текст-заглушка договора
    story.append(Paragraph(
        "Здесь будет располагаться основной текст договора на изготовление "
        "и установку корпусной мебели. На данный момент используется "
        "временный текст-заглушка. После утверждения окончательной "
        "редакции договора этот блок будет заменён на реальный текст.",
        base_style,
    ))

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Заказ №{} считается принятым в производство после подписания "
        "Бланка заказа и настоящего договора обеими сторонами."
        .format(order.order_number),
        base_style,
    ))

    doc.build(story)

    pdf = buf.getvalue()
    buf.close()

    filename = f"{order.order_number}_Основной_договор.pdf"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename=\"{filename}\"'
    return response

@group_required("Бухгалтер", "Дизайнер_1", "Дизайнер_2")
@login_required
@require_http_methods(["GET", "POST"])
def main_contract_sign_flow(request, pk):
    """
    Поток кнопки "Подписать" из "Все заказы":
    - если договор уже подписан -> показываем дату + кнопки Скачать/Редактировать
    - если нет -> показываем подтверждение и даём подписать (1 раз)
    """
    order = get_object_or_404(Order, pk=pk)

    if not (request.user.is_staff or getattr(order, "created_by_id", None) == request.user.id):
        return HttpResponseForbidden("Нет доступа")

    # Уже подписан — показываем готовое
    if getattr(order, "main_contract_signed", False) and order.contract_signed_at:
        return render(request, "orders/main_contract_signed.html", {
            "order": order,
            "signed_at": order.contract_signed_at,
            "download_url": reverse("main_contract_pdf", kwargs={"order_id": order.id}),
            "edit_url": reverse("contract_view", kwargs={"pk": order.id}),  # редактирование через /contract
        })

    # GET — показать страницу подтверждения
    if request.method == "GET":
        return render(request, "orders/main_contract_confirm.html", {
            "order": order,
        })

    # POST — финальное "Да, подписан" -> фиксируем дату и блокируем повторное подписание
    if not order.contract_signed_at:
        order.contract_signed_at = timezone.localdate()

    order.main_contract_signed = True
    if hasattr(order, "main_contract_signed_by"):
        order.main_contract_signed_by = request.user

    # важно: статус/стартовые статусы производства можно поставить тут
    # например если у тебя есть поле status (как в списке заказов)
    if hasattr(order, "status"):
        # у тебя в accounting JSON проверяется статус_label == "Договор":contentReference[oaicite:2]{index=2}
        # значит логично сюда ставить "Договор" (если у тебя именно так)
        order.status = "work" if str(order.status) == "work" else order.status  # не ломаем если другое
        # ⚠️ если у тебя есть конкретный код статуса "contract"/"work" — скажешь, поставим правильно

    order.save(update_fields=[
        "contract_signed_at",
        "main_contract_signed",
        "main_contract_signed_by",
        *(["status"] if hasattr(order, "status") else []),
    ])

    messages.success(request, f"Договор зафиксирован как подписанный: {order.contract_signed_at.strftime('%d.%m.%Y')}")
    return redirect("main_contract_sign_flow", pk=order.id)


# ===================== Other helpers/views =====================

def post_login_redirect(request):
    user = request.user
    if not user.is_authenticated:
        return redirect("login")
    if user.groups.filter(name="ACCESS_WORKSHOP").exists():
        return redirect("/workshop/")
    if user.groups.filter(name="ACCESS_ACCOUNTING").exists():
        return redirect("/accounting/")
    if user.groups.filter(name="ACCESS_ORDERS").exists():
        return redirect("/orders/")
    return redirect("/")


from django.http import HttpResponseForbidden as _Http403
from django.template import loader

def custom_permission_denied_view(request, exception=None):
    template = loader.get_template("403.html")
    return _Http403(template.render({}, request))


def order_new(request):
    order.status = Order.STATUS_NEW
    order.save()
    # legacy link fallback
    return redirect("orders_all")


# ===================== History modal =====================

# Человекочитаемое имя поля (verbose_name) по знакомым моделям
def _field_label(field_name: str) -> str:
    for model_name in ("Order", "PurchaseSheet", "Calculation"):
        try:
            Model = apps.get_model("core", model_name)
            f = Model._meta.get_field(field_name)
            # verbose_name может быть lazy — приводим к str
            return str(f.verbose_name)
        except Exception:
            continue
    # запасной вариант
    return field_name.replace("_", " ").capitalize()
    
from decimal import Decimal
# Форматируем значение для вывода
def _fmt_value(field: str, val):
    if val is None or val == "":
        return "—"
    # спец-случай: булевы
    if isinstance(val, bool):
        # пример: для твоей галки 3м/4м показываем явно
        if field == "tabletop_length_3m":
            return "3 м" if val else "4 м"
        return "Да" if val else "Нет"
    # числа/Decimal отображаем как есть
    try:
        if isinstance(val, (int, float, Decimal)):
            return f"{val}"
    except Exception:
        pass
    # списки/наборы
    if isinstance(val, (list, tuple, set)):
        return ", ".join(map(str, val)) if val else "—"
    # словари (на всякий)
    if isinstance(val, dict):
        try:
            return json.dumps(val, ensure_ascii=False)
        except Exception:
            return str(val)
    return str(val)
    
    
# Преобразуем запись лога в читаемый текст, поддерживая разные схемы хранения
def _render_log_text(entry) -> str:
    # 1) Прямой текстовый diff
    text = getattr(entry, "diff", None)
    if text:
        return text

    # 2) Попробуем найти полезный payload в разных полях
    for attr in ("changes", "data", "payload", "meta"):
        payload = getattr(entry, attr, None)
        if payload:
            if isinstance(payload, str):
                # попробуем распарсить JSON
                try:
                    payload = json.loads(payload)
                except Exception:
                    # оставляем как сырой текст
                    return payload

            if isinstance(payload, dict):
                lines = []

                # формат: {"changed": {"field": {"old":..., "new":...}, ...}}
                changed = payload.get("changed")
                if isinstance(changed, dict):
                    for field, change in changed.items():
                        old = change.get("old")
                        new = change.get("new")
                        if old != new:
                            label = _field_label(field)
                            lines.append(f"{label}: {_fmt_value(field, old)} → {_fmt_value(field, new)}")
                    if lines:
                        return "\n".join(lines)

                # формат: {"before": {...}, "after": {...}}
                before = payload.get("before")
                after = payload.get("after")
                if isinstance(before, dict) and isinstance(after, dict):
                    keys = sorted(set(before.keys()) | set(after.keys()))
                    for field in keys:
                        if before.get(field) != after.get(field):
                            label = _field_label(field)
                            lines.append(f"{label}: {_fmt_value(field, before.get(field))} → {_fmt_value(field, after.get(field))}")
                    if lines:
                        return "\n".join(lines)

                # формат: {"diff": "текст"} и т.п.
                if "diff" in payload and isinstance(payload["diff"], str):
                    return payload["diff"]

                # ничего не подошло — вернём весь JSON
                try:
                    return json.dumps(payload, ensure_ascii=False, indent=2)
                except Exception:
                    return str(payload)

    # 3) Фолбэк: сообщение, если есть
    msg = getattr(entry, "message", None)
    if msg:
        return str(msg)

    # 4) Совсем нечего — прочерк
    return "—"
    


@login_required
def order_history(request, order_id=None, pk=None):
    oid = order_id or pk
    order = get_object_or_404(Order, pk=oid)

    logs = ChangeLog.objects.filter(order=order).order_by("-created_at")

    items = []
    for lg in logs:
        # основной текст (как договорились ранее)
        text = getattr(lg, "diff_text", None) or getattr(lg, "message", None) or getattr(lg, "diff", None) or "—"

        # 1) Явные поля для определения раздела (если такие есть в модели логов)
        for attr in ("section", "scope", "area", "model_name", "model", "object_model"):
            val = getattr(lg, attr, None)
            if val:
                label, tag = _map_section(val)
                break
        else:
            # 2) content_type, если GenericForeignKey
            ct = getattr(lg, "content_type", None)
            if ct:
                label, tag = _map_section(ct.model)
            else:
                # 3) по содержимому текста/диффа
                label, tag = _guess_section_by_text(text)

                # 4) пробуем payload (before/after/changed) — по ключам полей
                if label == "Заказ":
                    payload = _extract_payload(lg)
                    if isinstance(payload, dict):
                        blob = json.dumps(payload, ensure_ascii=False).lower()
                        label, tag = _guess_section_by_text(blob)

        items.append({
            "dt": lg.created_at,
            "user": getattr(lg, "actor", None) or getattr(lg, "user", None),
            "text": text,
            "section": label,
            "section_tag": tag,
        })

    ctx = {"order": order, "items": items}

    # модальный режим
    if request.GET.get("modal") == "1" or request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(request, "orders/history_fragment.html", ctx)

    # полноценная страница
    return render(request, "orders/history.html", ctx)


# ===================== Signals =====================

from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Order)
def ensure_facade_sheet(sender, instance: Order, created, **kwargs):
    if created:
        FacadeSheet.objects.get_or_create(order=instance)

import re as _re
def _label_for_field(f: str) -> str:
    m = _re.match(r"lds_name(\d+)$", f)
    if m: return f"ЛДСП цвет {m.group(1)} (Наименование)"
    m = _re.match(r"lds_format(\d+)$", f)
    if m: return f"ЛДСП цвет {m.group(1)} (Формат)"
    m = _re.match(r"lds_color(\d+)$", f)
    if m: return f"ЛДСП цвет {m.group(1)} (листов)"
    m = _re.match(r"pvc_color(\d+)$", f)
    if m: return f"ПВХ цвет {m.group(1)} (метров)"
    m = _re.match(r"pvc_wide_color(\d+)$", f)
    if m: return f"ПВХ ШИРОКАЯ цвет {m.group(1)} (метров)"
    m = _re.match(r"group(\d+)_facade$", f)
    if m: return f"Группа {m.group(1)} — ФАСАДЫ"
    m = _re.match(r"group(\d+)_corpus$", f)
    if m: return f"Группа {m.group(1)} — КОРПУС"
    if f == "tabletop_count": return "Столешница (шт.)"
    if f == "tabletop_length_3m": return "Длина столешницы"
    if f == "hdf_count": return "ХДФ (листов)"
    return f

def _pretty_value(field: str, value):
    if field == "tabletop_length_3m":
        if value is None:
            return "—"
        return "3м" if bool(value) else "4м"
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if value in (None, ""):
        return "—"
    return str(value)

def human_diff(instance, old_values: dict, fields: list[str]) -> str:
    lines = []
    for f in fields:
        before = old_values.get(f, None)
        after = getattr(instance, f, None)
        if before != after:
            label = _label_for_field(f)
            vb = _pretty_value(f, before)
            va = _pretty_value(f, after)
            lines.append(f"{label}  {vb} → {va}")
    return "\n".join(lines)



# --- NEW: edit/create Calculation ---
COLOR_RE = re.compile(r"color[_\-]?(\d+)", re.IGNORECASE)

def _extract_color_key(field_name: str) -> str:
    m = COLOR_RE.search(field_name)
    if m:
        return f"Цвет {m.group(1)}"
    return "Прочие"

def _is_number(val) -> bool:
    try:
        Decimal(str(val))
        return True
    except Exception:
        return False

# вверху файла
from decimal import Decimal, InvalidOperation

def _dec(val) -> Decimal:
    """
    Безопасно приводит любое значение к Decimal.
    Поддерживает None, пустые строки, пробелы/неразрывные пробелы, запятые,
    символ '₸' и уже-Decimal значения.
    """
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val

    s = str(val).strip()
    if s == "":
        return Decimal("0")

    # нормализуем формат денег
    s = (
        s.replace("₸", "")
         .replace("\u00A0", "")  # nbsp
         .replace("\u202F", "")  # narrow nbsp
         .replace(" ", "")
         .replace(",", ".")
    )
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")

def _get_price(title: str) -> Decimal:
    try:
        p = PriceItem.objects.get(title=title)
        return _dec(p.value)
    except PriceItem.DoesNotExist:
        return Decimal("0")
        
        
        

@login_required
def calculation_edit(request, order_id: int):
    order = get_object_or_404(Order, pk=order_id)
    # Требуем сохранённый Лист закупа
    if not hasattr(order, "purchase_sheet") or order.purchase_sheet is None:
        messages.warning(request, "Сначала заполните и сохраните «Лист закупа».")
        return redirect("purchase_sheet", order_id=order.id)
    calc = getattr(order, "calculation", None) or Calculation(order=order)
    if not getattr(calc, "pk", None):
        calc.save()

    def _build_price_snapshot_for_calc() -> dict:
        labels = ["Распил","Присадка","ПВХ узкая","ПВХ широкая","Столешница распил","Дизайн проект"]
        snap = {}
        for lbl in labels:
            try:
                snap[lbl] = str(_get_price(lbl))
            except Exception:
                snap[lbl] = "0"
        return snap

    def _price(lbl: str, snap: dict) -> Decimal:
        """
        Цена берётся из снимка price_snapshot, если он есть.
        Если снимка ещё нет (первое сохранение) — берём текущую цену из PriceItem.
        """
        try:
            if snap and lbl in snap and snap[lbl] is not None:
                return _dec(snap[lbl])  # из снимка
        except Exception:
            pass
        # ← критично: фолбэк к живым ценам вместо нуля
        return _get_price(lbl)

    has_snapshot_fields = hasattr(calc, "price_snapshot") and hasattr(calc, "last_price_sync_at")
    snap = (calc.price_snapshot or {}) if has_snapshot_fields else {}
    price_snapshot_missing = bool(has_snapshot_fields) and not bool(snap)

    action = request.POST.get("action", "")
    if request.method == "POST" and action == "reload_prices" and has_snapshot_fields:
        snap = _build_price_snapshot_for_calc()
        calc.price_snapshot = snap
        calc.last_price_sync_at = timezone.now()
        calc.save(update_fields=["price_snapshot","last_price_sync_at"])
        messages.success(request, "Цены обновлены из «Бухгалтерии».")

    ps = order.purchase_sheet
    sums_ldsp, sums_pvc, sums_pvc_wide = {}, {}, {}
    qty_ldsp_total = qty_pvc_total = qty_pvc_wide_total = Decimal("0")
    countertop_qty_ps = Decimal("0")
    hdf_qty_ps = Decimal("0")

    for f in ps._meta.get_fields():
        if not hasattr(ps, f.name):
            continue
        try:
            val = getattr(ps, f.name)
        except Exception:
            continue
        if val in (None, "") or not _is_number(val):
            continue
        name = f.name.lower()
        dval = _dec(val)
        if ("lds" in name) or ("ldsp" in name):
            key = _extract_color_key(name)
            sums_ldsp[key] = _dec(sums_ldsp.get(key, 0)) + dval
            qty_ldsp_total += dval
        elif ("pvc" in name or "pvh" in name) and ("wide" in name or "шир" in name):
            key = _extract_color_key(name)
            sums_pvc_wide[key] = _dec(sums_pvc_wide.get(key, 0)) + dval
            qty_pvc_wide_total += dval
        elif ("pvc" in name or "pvh" in name):
            key = _extract_color_key(name)
            sums_pvc[key] = _dec(sums_pvc.get(key, 0)) + dval
            qty_pvc_total += dval
        if CTP_PAT.search(name):
            countertop_qty_ps += dval
        if HDF_PAT.search(name):
            hdf_qty_ps += dval

    price_raspil     = _price("Распил", snap)
    price_prisadka   = _price("Присадка", snap)
    price_pvh_narrow = _price("ПВХ узкая", snap)
    price_pvh_wide   = _price("ПВХ широкая", snap)
    price_countertop = _price("Столешница распил", snap)
    price_hdf_by_sheet = _price("Распил", snap)
    price_design     = _price("Дизайн проект", snap)

    cost_ldsp_raspil   = (qty_ldsp_total * price_raspil).quantize(Decimal("0.01"))
    cost_ldsp_prisadka = (qty_ldsp_total * price_prisadka).quantize(Decimal("0.01"))
    cost_ldsp          = (cost_ldsp_raspil + cost_ldsp_prisadka).quantize(Decimal("0.01"))
    cost_pvc           = (qty_pvc_total * price_pvh_narrow).quantize(Decimal("0.01"))
    cost_pvc_wide      = (qty_pvc_wide_total * price_pvh_wide).quantize(Decimal("0.01"))

    form = CalculationForm(request.POST or None, instance=calc)

    calc.sums_ldsp = {k: float(v) for k, v in sums_ldsp.items()}
    calc.sums_pvc = {k: float(v) for k, v in sums_pvc.items()}
    calc.sums_pvc_wide = {k: float(v) for k, v in sums_pvc_wide.items()}
    calc.qty_ldsp_total = qty_ldsp_total
    calc.qty_pvc_total = qty_pvc_total
    calc.qty_pvc_wide_total = qty_pvc_wide_total
    calc.cost_ldsp_raspil = cost_ldsp_raspil
    calc.cost_ldsp_prisadka = cost_ldsp_prisadka
    calc.cost_ldsp = cost_ldsp
    calc.cost_pvc = cost_pvc
    calc.cost_pvc_wide = cost_pvc_wide

    facade_area_total = Decimal("0")
    facade_total = Decimal("0")
    facade_rows = []
    if request.method == "POST":
        ids = request.POST.getlist("facade_item_id[]")
        areas = request.POST.getlist("facade_area[]")
        for pid, area_str in zip(ids, areas):
            if not pid:
                continue
            try:
                p = PriceItem.objects.select_related("group").get(pk=int(pid))
            except (PriceItem.DoesNotExist, ValueError):
                continue
            grp_norm = (p.group.title or "").lower().replace("ё", "е")
            if not (grp_norm.startswith("фасады (краска") or grp_norm.startswith("фасады (пленка")):
                continue
            s = (area_str or "").replace(" ", "").replace("\u00A0", "").replace("\u202F", "").replace(",", ".")
            try:
                area = Decimal(s).quantize(Decimal("0.01"))
            except InvalidOperation:
                area = Decimal("0.00")
            facade_area_total += area
            price = _dec(p.value)
            cost = (area * price).quantize(Decimal("0.01"))
            facade_total += cost
            facade_rows.append({"id": p.id, "title": p.title, "area": area, "cost": cost})
        calc.cost_facades = facade_total
    else:
        saved = list(calc.facade_items.select_related("price_item").all())
        for fi in saved:
            facade_rows.append({
                "id": fi.price_item_id,
                "title": fi.price_item.title,
                "area": fi.area.quantize(Decimal("0.01")),
                "cost": fi.cost.quantize(Decimal("0.01")),
            })
            facade_area_total += fi.area
        facade_total = (sum((row["cost"] for row in facade_rows), Decimal("0"))).quantize(Decimal("0.01"))
        calc.cost_facades = facade_total

    c_qty_ps = locals().get("countertop_qty_ps", Decimal("0"))
    h_qty_ps = locals().get("hdf_qty_ps", Decimal("0"))
    if request.method == "POST" and action != "reload_prices" and form.is_valid():
        c_qty = form.cleaned_data.get("countertop_qty")
        h_qty = form.cleaned_data.get("hdf_qty")
        c_qty = (c_qty if c_qty and c_qty > 0 else c_qty_ps)
        h_qty = (h_qty if h_qty and h_qty > 0 else h_qty_ps)
    else:
        c_qty = calc.countertop_qty if calc.countertop_qty and calc.countertop_qty > 0 else c_qty_ps
        h_qty = calc.hdf_qty if calc.hdf_qty and calc.hdf_qty > 0 else h_qty_ps

    calc.countertop_qty = c_qty or Decimal("0")
    calc.hdf_qty = h_qty or Decimal("0")

    cost_countertop = (c_qty * price_countertop).quantize(Decimal("0.01"))
    cost_hdf = (h_qty * price_hdf_by_sheet).quantize(Decimal("0.01"))
    cost_misc = (cost_countertop + cost_hdf).quantize(Decimal("0.01"))
    calc.cost_countertop = cost_countertop
    calc.cost_hdf = cost_hdf
    calc.cost_misc = cost_misc

    design_ldsp_cost = (qty_ldsp_total * price_design).quantize(Decimal("0.01"))
    facade_sheets = int(((facade_area_total / Decimal("5")).to_integral_value(rounding=ROUND_CEILING))) if facade_area_total > 0 else 0
    design_facade_cost = (Decimal(facade_sheets) * price_design).quantize(Decimal("0.01"))
    cost_design_total = (design_ldsp_cost + design_facade_cost).quantize(Decimal("0.01"))
    calc.design_ldsp_cost = design_ldsp_cost
    calc.design_facade_sheets = facade_sheets
    calc.design_facade_cost = design_facade_cost
    calc.cost_design_total = cost_design_total

    try:
        _facade_sheets_int = int(calc.design_facade_sheets or 0)
    except Exception:
        _facade_sheets_int = 0
    qty_ldsp_total_effective = (qty_ldsp_total or Decimal("0")) + Decimal(str(_facade_sheets_int))
    cost_ldsp_raspil = (qty_ldsp_total_effective * price_raspil).quantize(Decimal("0.01"))
    cost_ldsp_prisadka = (qty_ldsp_total_effective * price_prisadka).quantize(Decimal("0.01"))
    cost_ldsp = (cost_ldsp_raspil + cost_ldsp_prisadka).quantize(Decimal("0.01"))
    calc.qty_ldsp_total = qty_ldsp_total_effective
    calc.cost_ldsp_raspil = cost_ldsp_raspil
    calc.cost_ldsp_prisadka = cost_ldsp_prisadka
    calc.cost_ldsp = cost_ldsp

    total_price = (calc.cost_ldsp + calc.cost_pvc + calc.cost_pvc_wide + calc.cost_misc + calc.cost_additional).quantize(Decimal("0.01"))
    calc.total_price = total_price

    if request.method == "POST" and action != "reload_prices" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.order = order
        if has_snapshot_fields and not (calc.price_snapshot or {}):
            obj.price_snapshot = _build_price_snapshot_for_calc()
            obj.last_price_sync_at = timezone.now()
        snap = obj.price_snapshot  # чтобы _price(...) ниже мог брать из него
        obj.sums_ldsp = calc.sums_ldsp
        obj.sums_pvc = calc.sums_pvc
        obj.sums_pvc_wide = calc.sums_pvc_wide
        obj.qty_ldsp_total = calc.qty_ldsp_total
        obj.qty_pvc_total = calc.qty_pvc_total
        obj.qty_pvc_wide_total = calc.qty_pvc_wide_total
        obj.cost_ldsp_raspil = calc.cost_ldsp_raspil
        obj.cost_ldsp_prisadka = calc.cost_ldsp_prisadka
        obj.cost_ldsp = calc.cost_ldsp
        obj.cost_pvc = calc.cost_pvc
        obj.cost_pvc_wide = calc.cost_pvc_wide
        obj.cost_countertop = cost_countertop
        obj.cost_hdf = cost_hdf
        obj.cost_misc = cost_misc
        obj.cost_facades = calc.cost_facades
        obj.design_ldsp_cost = design_ldsp_cost
        obj.design_facade_sheets = facade_sheets
        obj.design_facade_cost = design_facade_cost
        obj.cost_design_total = cost_design_total
        obj.cost_additional = calc.cost_additional
        obj.total_price = (
            (obj.cost_ldsp or 0) + (obj.cost_pvc or 0) + (obj.cost_pvc_wide or 0) +
            (obj.cost_additional or 0) + (obj.cost_misc or 0)
        )
        obj.was_saved = True
        obj.save()
        try:
            if order.status in (Order.STATUS_NEW,):
                order.status = Order.STATUS_CALC
                order.save(update_fields=["status"])
        except Exception:
            pass
        # Сохраняем «Дополнительно» — очищаем и пересоздаём (как фасады)
        obj.additional_items.all().delete()
        obj.facade_items.all().delete()
        ids   = request.POST.getlist("additional_item_id[]")
        qtys  = request.POST.getlist("additional_qty[]")
        for pid, qty_str in zip(ids, qtys):
            if not pid:
                continue
            try:
                p = PriceItem.objects.select_related("group").get(pk=int(pid))
            except (PriceItem.DoesNotExist, ValueError):
                continue
            grp_norm = (p.group.title or "").lower().replace("ё", "е")
            if grp_norm != "прочее":
                continue
            s = (qty_str or "").replace(" ", "").replace("\u00A0", "").replace("\u202F", "").replace(",", ".")
            try:
                q = Decimal(s).quantize(Decimal("0.01"))
            except InvalidOperation:
                q = Decimal("0.00")
            cost = (q * _dec(p.value)).quantize(Decimal("0.01"))
            CalculationAdditionalItem.objects.create(
                calculation=obj, price_item=p, qty=q, cost=cost
            )
        
        
        
        
        
        for row in []:
            pass
        for row in locals().get("additional_rows", []):
            CalculationAdditionalItem.objects.create(
                calculation=obj, price_item_id=row["id"], qty=row["qty"], cost=row["cost"]
            )
        
        for row in facade_rows:
            CalculationFacadeItem.objects.create(
                calculation=obj, price_item_id=row["id"], area=row["area"], cost=row["cost"]
            )
        agg_add = obj.additional_items.aggregate(s=Sum("cost"))
        agg_fac = obj.facade_items.aggregate(s=Sum("cost"))
        add_cost = agg_add["s"] or Decimal("0")
        fac_cost = agg_fac["s"] or Decimal("0")
        
        obj.cost_additional = add_cost
        obj.cost_facades   = fac_cost
       
        obj.total_price = (
            (obj.cost_ldsp or 0) + (obj.cost_pvc or 0) + (obj.cost_pvc_wide or 0) +
            (obj.cost_additional or 0) + (obj.cost_misc or 0)
        )
        obj.save(update_fields=[
            "cost_additional", "cost_facades", "total_price", "was_saved",
            # при необходимости добавьте сюда другие изменённые поля
        ])
        
        messages.success(request, "Лист расчёта сохранен.", extra_tags="calc_saved")
        return redirect("calculation_edit", order_id=order.id)
    else:
        if calc.pk is None:
            calc.save()

    additional_options = list(
        PriceItem.objects.filter(group__title__iexact="Прочее").select_related("group").order_by("group__sort_order","id").values("id","title","group__title")
    )
    facade_options = list(
        PriceItem.objects.filter(group__title__in=["Фасады (краска)","Фасады (плёнка)","Фасады (пленка)"]).select_related("group").order_by("group__sort_order","id").values("id","title","group__title")
    )
    existing_facades = [
        {"id": fi.price_item_id, "title": fi.price_item.title, "area": fi.area, "cost": fi.cost}
        for fi in calc.facade_items.select_related("price_item").all()
    ]

    sums_ldsp_view = dict(calc.sums_ldsp or {})
    if _facade_sheets_int > 0:
        sums_ldsp_view["Фасады (листов по 5 м²)"] = _facade_sheets_int
    qty_ldsp_total_view = (calc.qty_ldsp_total or 0)
    
    
    
    ldsp_rows_view = []
    import re as _re  # локально, чтобы не ломать импорты выше
    for _key, _qty in (sums_ldsp or {}).items():
        # _key обычно вида "Цвет 1", "Цвет 2", ... — вытащим номер
        _raw = str(_key)
        _m = _re.search(r'(\d+)', _raw)
        _idx = _m.group(1) if _m else _raw

        # читаем PurchaseSheet.lds_nameN и PurchaseSheet.lds_formatN
        _name = getattr(ps, f'lds_name{_idx}', None) or "—"
        _fmt  = getattr(ps, f'lds_format{_idx}', None) or "—"

        # требуемый формат метки:
        _label = f'Цвет {_idx} - {_name} - {_fmt}'
        ldsp_rows_view.append((_label, _qty))
        


    # GET: подтягиваем сумму ДОПОЛНИТЕЛЬНО из БД (если не POST)
    if request.method != "POST":
        calc.cost_additional = sum(
            (ai.cost for ai in calc.additional_items.all()),
            Decimal("0")
        ).quantize(Decimal("0.01"))
     
        # Единая формула: используем cost_misc, не добавляем отдельно countertop/hdf
        calc.cost_facades = Decimal(calc.cost_facades or 0)
        calc.total_price = (
            (calc.cost_ldsp or 0) + (calc.cost_pvc or 0) + (calc.cost_pvc_wide or 0) +
            (calc.cost_additional or 0) + (calc.cost_misc or 0)
        ).quantize(Decimal("0.01"))

    return render(request, "calculation/edit.html", {
        "ldsp_rows_view": ldsp_rows_view,
        "order": order,
        "form": form,
        "calc": calc,
        "sums_ldsp_view": sums_ldsp_view,
        "qty_ldsp_total_view": qty_ldsp_total_view,
        "grand_total": (calc.total_price or 0) + (calc.cost_design_total or 0) + (calc.cost_facades or 0),
        "price_raspil": price_raspil,
        "price_prisadka": price_prisadka,
        "price_pvh_narrow": price_pvh_narrow,
        "price_pvh_wide": price_pvh_wide,
        "price_countertop": price_countertop,
        "price_hdf_by_sheet": price_hdf_by_sheet,
        "additional_options": additional_options,
        "existing_additionals": (
            additional_rows if (request.method == "POST" and action != "reload_prices") else [
                {"id": ai.price_item_id, "title": ai.price_item.title, "qty": ai.qty, "cost": ai.cost}
                for ai in calc.additional_items.select_related("price_item").all()
            ]
        ),
        "facade_options": facade_options,
        "existing_facades": facade_rows,
        "price_snapshot_missing": price_snapshot_missing,
        "price_design": price_design,
        "project_qty_ldsp": qty_ldsp_total,
        
    })
    def _build_price_snapshot_for_calc() -> dict:
        labels = [
            "Распил", "Присадка", "ПВХ узкая", "ПВХ широкая", "Столешница распил"
        ]
        snap = {}
        for lbl in labels:
            try:
                snap[lbl] = str(_get_price(lbl))  # Decimal -> str (JSON-safe)
            except Exception:
                snap[lbl] = "0"
        return snap

    def _price(lbl: str, snap: dict) -> Decimal:
        # если в снимке есть — берём из него, иначе текущая «Бухгалтерия»
        if snap and lbl in snap:
            try:
                return _dec(snap[lbl])
            except Exception:
                return Decimal("0")
        return Decimal("0")

    # читаем снимок (если поле есть в модели)
    has_snapshot_fields = hasattr(calc, "price_snapshot") and hasattr(calc, "last_price_sync_at")
    snap = (calc.price_snapshot or {}) if has_snapshot_fields else {}
    price_snapshot_missing = bool(has_snapshot_fields) and not bool(snap)

    # Обработка кнопки "Загрузить новые цены"
    action = request.POST.get("action", "")
    if request.method == "POST" and action == "reload_prices" and has_snapshot_fields:
        snap = _build_price_snapshot_for_calc()
        calc.price_snapshot = snap
        calc.last_price_sync_at = timezone.now()
        calc.save(update_fields=["price_snapshot", "last_price_sync_at"])
        messages.success(request, "Цены обновлены из «Бухгалтерии».")
        # продолжаем ниже: расчёты уже пойдут с учётом нового snap

    # ------------------ НОВОЕ: helpers для снимка цен ------------------
    def _build_price_snapshot_for_calc() -> dict:
        """
        Снимаем актуальные цены из «Бухгалтерии» и сохраняем как строки (JSON-safe).
        Ключи — те самые «ярлыки», которыми ты пользуешься в _get_price(...)
        """
        labels = [
            "Распил",
            "Присадка",
            "ПВХ узкая",
            "ПВХ широкая",
            "Столешница распил",
            "Дизайн проект",
        ]
        snap = {}
        for lbl in labels:
            try:
                snap[lbl] = str(_get_price(lbl))  # Decimal -> str (JSON-safe)
            except Exception:
                snap[lbl] = "0"
        return snap


    # ------------------ НОВОЕ: обработка action=reload_prices ------------------
    action = request.POST.get("action", "")
    if request.method == "POST" and action == "reload_prices" and has_snapshot_fields:
        snap = _build_price_snapshot_for_calc()
        calc.price_snapshot = snap
        calc.last_price_sync_at = timezone.now()
        calc.save(update_fields=["price_snapshot", "last_price_sync_at"])
        messages.success(request, "Цены обновлены из «Бухгалтерии».")
        # Не делаем redirect здесь, чтобы сразу отрендерить пересчитанные значения ниже

    # --- 1) Суммируем по Листу закупа ---
    ps = order.purchase_sheet
    sums_ldsp, sums_pvc, sums_pvc_wide = {}, {}, {}
    qty_ldsp_total = qty_pvc_total = qty_pvc_wide_total = Decimal("0")

    countertop_qty_ps = Decimal("0")  # Столешница (шт.) из Лист закупа
    hdf_qty_ps        = Decimal("0")  # ХДФ задняя стенка (листов) из Лист закупа

    for f in ps._meta.get_fields():
        if not hasattr(ps, f.name):
            continue
        try:
            val = getattr(ps, f.name)
        except Exception:
            continue
        if val in (None, "") or not _is_number(val):
            continue

        name = f.name.lower()
        dval = _dec(val)

        # --- ЛДСП (листов) ---
        if ("lds" in name) or ("ldsp" in name):
            key = _extract_color_key(name)
            sums_ldsp[key] = _dec(sums_ldsp.get(key, 0)) + dval
            qty_ldsp_total += dval

        # --- ПВХ широкая (метров) ---
        elif ("pvc" in name or "pvh" in name) and ("wide" in name or "шир" in name):
            key = _extract_color_key(name)
            sums_pvc_wide[key] = _dec(sums_pvc_wide.get(key, 0)) + dval
            qty_pvc_wide_total += dval

        # --- ПВХ узкая (метров) ---
        elif ("pvc" in name or "pvh" in name):
            key = _extract_color_key(name)
            sums_pvc[key] = _dec(sums_pvc.get(key, 0)) + dval
            qty_pvc_total += dval

        # --- Прочее: авто-количества из Лист закупа ---
        if CTP_PAT.search(name):
            countertop_qty_ps += dval

        if HDF_PAT.search(name):
            hdf_qty_ps += dval

    # --- 2) Цены: из снимка если он есть, иначе как раньше ---
    price_raspil        = _price("Распил", snap)
    price_prisadka      = _price("Присадка", snap)
    price_pvh_narrow    = _price("ПВХ узкая", snap)
    price_pvh_wide      = _price("ПВХ широкая", snap)
    price_countertop    = _price("Столешница распил", snap)
    price_hdf_by_sheet  = _price("Распил", snap)
    price_design        = _price("Дизайн проект", snap) 

    
    # --- 3) Стоимость ЛДСП: распил + присадка ---
    cost_ldsp_raspil   = (qty_ldsp_total * price_raspil).quantize(Decimal("0.01"))
    cost_ldsp_prisadka = (qty_ldsp_total * price_prisadka).quantize(Decimal("0.01"))
    cost_ldsp          = (cost_ldsp_raspil + cost_ldsp_prisadka).quantize(Decimal("0.01"))

    # --- 4) Стоимость ПВХ ---
    cost_pvc      = (qty_pvc_total * price_pvh_narrow).quantize(Decimal("0.01"))
    cost_pvc_wide = (qty_pvc_wide_total * price_pvh_wide).quantize(Decimal("0.01"))

    # --- 5) Форма: вводимые количества для «Прочее» и заметка ---
    if request.method == "POST":
        form = CalculationForm(request.POST, instance=calc)
    else:
        form = CalculationForm(instance=calc)

    # Сначала проставим агрегаты (из Лист закупа) в объект calc — для шаблона
    calc.sums_ldsp = {k: float(v) for k, v in sums_ldsp.items()}
    calc.sums_pvc = {k: float(v) for k, v in sums_pvc.items()}
    calc.sums_pvc_wide = {k: float(v) for k, v in sums_pvc_wide.items()}
    calc.qty_ldsp_total = qty_ldsp_total
    calc.qty_pvc_total = qty_pvc_total
    calc.qty_pvc_wide_total = qty_pvc_wide_total

    calc.cost_ldsp_raspil = cost_ldsp_raspil
    calc.cost_ldsp_prisadka = cost_ldsp_prisadka
    calc.cost_ldsp = cost_ldsp
    calc.cost_pvc = cost_pvc
    calc.cost_pvc_wide = cost_pvc_wide
    facade_area_total = Decimal("0")

    # --- 6) ФАСАДЫ: как у тебя было ---
    facade_total = Decimal("0")
    facade_rows = []

    if request.method == "POST":
        ids   = request.POST.getlist("facade_item_id[]")
        areas = request.POST.getlist("facade_area[]")

        for pid, area_str in zip(ids, areas):
            if not pid:
                continue
            try:
                p = PriceItem.objects.select_related("group").get(pk=int(pid))
            except (PriceItem.DoesNotExist, ValueError):
                continue

            grp_norm = (p.group.title or "").lower().replace("ё", "е")
            if not (grp_norm.startswith("фасады (краска") or grp_norm.startswith("фасады (пленка")):
                continue

            s = (area_str or "").replace(" ", "").replace("\u00A0", "").replace("\u202F", "").replace(",", ".")
            try:
                area = Decimal(s).quantize(Decimal("0.01"))
            except InvalidOperation:
                area = Decimal("0.00")
                
            facade_area_total += area

            price = _dec(p.value)  # цена из "Цены"
            cost = (area * price).quantize(Decimal("0.01"))

            facade_total += cost
            facade_rows.append({"id": p.id, "title": p.title, "area": area, "cost": cost})

        calc.cost_facades = facade_total

    else:
        saved = list(calc.facade_items.select_related("price_item").all())
        for fi in saved:
            facade_rows.append({
                "id": fi.price_item_id,
                "title": fi.price_item.title,
                "area": fi.area.quantize(Decimal("0.01")),
                "cost": fi.cost.quantize(Decimal("0.01")),
            })
            facade_area_total += fi.area
        facade_total = (sum((row["cost"] for row in facade_rows), Decimal("0"))).quantize(Decimal("0.01"))
        calc.cost_facades = facade_total

    # --- 7) Прочее (столешницы/ХДФ), ровно как у тебя ---
    c_qty_ps = locals().get("countertop_qty_ps", Decimal("0"))
    h_qty_ps = locals().get("hdf_qty_ps", Decimal("0"))

    if request.method == "POST" and action != "reload_prices" and form.is_valid():
        obj = form.save(commit=False)
        obj.order = order
    
        # 1) переноcим ВСЕ вычисленные поля из calc -> obj
        obj.sums_ldsp = dict(calc.sums_ldsp or {})
        obj.sums_pvc = dict(calc.sums_pvc or {})
        obj.sums_pvc_wide = dict(calc.sums_pvc_wide or {})
    
        obj.qty_ldsp_total = calc.qty_ldsp_total
        obj.qty_pvc_total = calc.qty_pvc_total
        obj.qty_pvc_wide_total = calc.qty_pvc_wide_total
    
        obj.cost_ldsp_raspil = calc.cost_ldsp_raspil
        obj.cost_ldsp_prisadka = calc.cost_ldsp_prisadka
        obj.cost_ldsp = calc.cost_ldsp
        obj.cost_pvc = calc.cost_pvc
        obj.cost_pvc_wide = calc.cost_pvc_wide
    
        obj.cost_countertop = calc.cost_countertop
        obj.cost_hdf = calc.cost_hdf
        obj.cost_misc = calc.cost_misc
    
        obj.cost_facades = calc.cost_facades
        obj.cost_additional = calc.cost_additional
    
        # Проект/дизайн
        obj.design_ldsp_cost = design_ldsp_cost
        obj.design_facade_sheets = facade_sheets
        obj.design_facade_cost = design_facade_cost
        obj.cost_design_total = cost_design_total
    
        # Итог по обработке
        obj.total_price = (obj.cost_ldsp + obj.cost_pvc + obj.cost_pvc_wide
                           + obj.cost_misc + obj.cost_facades + obj.cost_additional)
    
        # Зафиксировать снимок цен при первом сохранении, если его нет
        if has_snapshot_fields and not (calc.price_snapshot or {}):
            obj.price_snapshot = _build_price_snapshot_for_calc()
            obj.last_price_sync_at = timezone.now()
    
        obj.was_saved = True
        obj.save()  # ← суммы точно в БД после первой кнопки
    
        # Пересохранить строки "Дополнительно" и "Фасады"
        obj.additional_items.all().delete()
        for row in additional_rows:
            CalculationAdditionalItem.objects.create(
                calculation=obj, price_item_id=row["id"], qty=row["qty"], cost=row["cost"]
            )
        obj.facade_items.all().delete()
        for row in facade_rows:
            CalculationFacadeItem.objects.create(
                calculation=obj, price_item_id=row["id"], area=row["area"], cost=row["cost"]
            )
    
        # Статус заказа (не обязательно, но оставим)
        try:
            if order.status in (Order.STATUS_NEW,):
                order.status = Order.STATUS_CALC
                order.save(update_fields=["status"])
        except Exception:
            pass
    
        messages.success(request, "Лист расчёта сохранен.", extra_tags="calc_saved")
        return redirect("calculation_edit", order_id=order.id)

    else:
        if calc.pk is None:
            calc.save()

    # Список прайс-позиций для селекта фасадов (только нужные группы)
    
    # Список прайс-позиций для «Дополнительно» (только группа "Прочее")
    additional_options = list(
        PriceItem.objects.filter(group__title__iexact="Прочее")
        .select_related("group")
        .order_by("group__sort_order", "id")
        .values("id", "title", "group__title")
    )

    facade_options = list(
        PriceItem.objects.filter(
            group__title__in=["Фасады (краска)", "Фасады (плёнка)", "Фасады (пленка)"]
        )
        .select_related("group")
        .order_by("group__sort_order", "id")
        .values("id", "title", "group__title")
    )

    existing_facades = [
        {"id": fi.price_item_id, "title": fi.price_item.title, "area": fi.area, "cost": fi.cost}
        for fi in calc.facade_items.select_related("price_item").all()
    ]

    return 
    # --- Витринные поля для ЛДСП с учётом фасадов (листов по 5 м²) ---
    sums_ldsp_view = dict(calc.sums_ldsp or {})  # копия словаря для шаблона
    try:
        _facade_sheets_int = int(calc.design_facade_sheets or 0)
    except Exception:
        _facade_sheets_int = 0
    if _facade_sheets_int > 0:
    # Добавляем отдельной строкой в конце таблицы ЛДСП
        sums_ldsp_view["Фасады (листов по 5 м²)"] = _facade_sheets_int
    try:
        qty_ldsp_total_view = (calc.qty_ldsp_total or 0)  # уже включает фасады
    except Exception:
        qty_ldsp_total_view = (calc.qty_ldsp_total or 0)
        render(request, "calculation/edit.html", {
            "order": order,
            "form": form,
            "calc": calc,
            "sums_ldsp_view": sums_ldsp_view,
            "qty_ldsp_total_view": qty_ldsp_total_view,
            "grand_total": (calc.total_price or 0) + (calc.cost_design_total or 0) + (calc.cost_facades or 0),
            # Цены отражаем с учётом снимка:
            "price_raspil": price_raspil,
            "price_prisadka": price_prisadka,
            "price_pvh_narrow": price_pvh_narrow,
            "price_pvh_wide": price_pvh_wide,
            "price_countertop": price_countertop,
            "price_hdf_by_sheet": price_hdf_by_sheet,
            "additional_options": additional_options,
            "existing_additionals": additional_rows,
            "facade_options": facade_options,
            "existing_facades": facade_rows,
            "price_snapshot_missing": price_snapshot_missing,
            "price_design": price_design,
            
        })

    from reportlab.lib.utils import ImageReader  # для калки пропорций логотипа
    
    
    
# PDF Расчёт - формирование файла PDF
@login_required
def purchase_pdf(request, order_id: int):

    order = get_object_or_404(Order, pk=order_id)
    calc = getattr(order, "calculation", None)
    if calc is None:
        messages.warning(request, "Сначала выполните и сохраните «Расчёт», затем сформируйте PDF-закуп.")
        return redirect("calculation_edit", order_id=order.id)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=5*mm, bottomMargin=5*mm
    )

    # Шрифты (кириллица)
    try:
        font_regular = finders.find("fonts/DejaVuSans.ttf")
        font_bold    = finders.find("fonts/DejaVuSans-Bold.ttf")
        pdfmetrics.registerFont(TTFont("DejaVuSans", font_regular))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", font_bold))
        registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold")
        base_font = "DejaVuSans"
        bold_font = "DejaVuSans-Bold"
    except Exception:
        base_font = "Helvetica"
        bold_font = "Helvetica-Bold"

    # Палитра
    ACCENT = colors.HexColor("#6b4e2e")      # фирменный коричневый (для линий/акцентов)
    ORANGE = colors.HexColor("#F59E0B")      # фон заголовков секций (оранжевый)
    ORANGE_DARK = colors.HexColor("#D97706") # чуть темнее для разделительной линии
    INK    = colors.HexColor("#111827")      # почти чёрный
    SUB    = colors.HexColor("#374151")      # тёмно-серый
    LINES  = colors.HexColor("#4B5563")      # ЕЩЁ темнее линии таблиц (фикс 5)
    # HDR_BG больше не используем как фон заголовка — теперь ORANGE

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontName=bold_font, fontSize=15, leading=18, textColor=INK))
    styles.add(ParagraphStyle(name="H2", fontName=bold_font, fontSize=11, leading=14, textColor=INK))
    styles.add(ParagraphStyle(name="P",  fontName=base_font, fontSize=9.5, leading=12, textColor=INK))
    styles.add(ParagraphStyle(name="S",  fontName=base_font, fontSize=8.5, leading=11, textColor=SUB))
    styles.add(ParagraphStyle(name="R",  fontName=base_font, fontSize=9,   leading=11, textColor=INK))
    styles.add(ParagraphStyle(name="Rr", parent=styles["R"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="TotalAmount", fontName=bold_font, fontSize=15, leading=18, textColor=INK))  # (фикс 2)

    def fmt_money(x: Decimal, currency: str = "₸") -> str:
        q = (x or Decimal("0")).quantize(Decimal("0.01"))
        s = f"{q:,.2f}".replace(",", " ")
        return f"{s} {currency}"

    # Шапка с логотипом (право, сохраняем пропорции) — (фикс 4)
    logo = None
    for candidate in ("img/logo.png", "img/logo.jpg", "img/logo.svg",
                      "images/logo.png", "images/logo.jpg", "images/logo.svg",
                      "logo.png", "logo.jpg", "logo.svg"):
        p = finders.find(candidate)
        if p:
            logo = p
            break
    logo_flowable = Paragraph("&nbsp;", styles["P"])
    if logo:
        try:
            ir = ImageReader(logo)
            iw, ih = ir.getSize()
            max_w, max_h = 50*mm, 14*mm
            scale = min(max_w/iw, max_h/ih)
            logo_flowable = Image(logo, width=iw*scale, height=ih*scale, hAlign="RIGHT")
        except Exception:
            pass

    title = Paragraph(
        f"<font color='{ACCENT.hexval()}'>Расчёт стоимости</font> заказа №{order.order_number}",
        styles["H1"]
    )
    subtitle = Paragraph(
        f"Клиент: <b>{getattr(order, 'customer_name', '') or '—'}</b>",
        styles["P"]
    )
    
    # --- дата документа ---
    generated_dt = timezone.localtime(timezone.now())
    doc_date_str = generated_dt.strftime("%d.%m.%Y %H:%M")
    
    # --- ФИО дизайнера ---
    def _full_name(u):
        if not u:
            return ""
        fn = (getattr(u, "first_name", "") or "").strip()
        ln = (getattr(u, "last_name", "") or "").strip()
        if fn or ln:
            return f"{ln} {fn}".strip()
        return (getattr(u, "username", "") or "").strip()
    
    designer_user = (
        getattr(calc, "created_by", None)
        or getattr(order, "created_by", None)
        or (request.user if request.user.is_authenticated else None)
    )
    designer_name = _full_name(designer_user) or "—"
    
    # таблица шапки: добавили две строки под Клиент
    header_tbl_data = [
        [title, logo_flowable],
        [subtitle, Paragraph("&nbsp;", styles["P"])],
        [Paragraph(f"Дата документа: {doc_date_str}", styles["P"]), Paragraph("&nbsp;", styles["P"])],
        [Paragraph(f"Дизайнер: {designer_name}", styles["P"]), Paragraph("&nbsp;", styles["P"])],
    ]
    
    header_tbl = Table(header_tbl_data, colWidths=[doc.width - 40*mm, 40*mm], hAlign="LEFT")
        
        
    
    
    
    
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1),
    ]))
    
    
    # Добавляет секцию только если в таблице есть строки-данные (кроме заголовка)
    def add_section_if_rows(title: str, rows: list, builder, *b_args, **b_kwargs):
        """
        rows: список строк таблицы, где rows[0] — заголовок (thead).
        builder: функция построения таблицы (table_full или table_facades).
        """
        if rows and len(rows) > 1:  # есть хотя бы одна строка данных
            story.extend([Spacer(1, 6*mm), section_caption(title), Spacer(1, 2*mm)])
            story.append(builder(rows, *b_args, **b_kwargs))
            return True
        return False
    
    # Заголовок секции — выравнивание и фон (фиксы 1 и 3)
    def section_caption(text: str):
        bar = Table([[Paragraph(text, styles["H2"])]], colWidths=[doc.width], hAlign="LEFT")
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), ORANGE),       # оранжевый фон
            ("TEXTCOLOR", (0,0), (-1,-1), colors.white),  # белый текст на оранжевом
            ("LINEBELOW", (0,0), (-1,-1), 0.8, ORANGE_DARK),
            ("LEFTPADDING", (0,0), (-1,-1), 5),           # паддинги = таблицам (ровное поле)
            ("RIGHTPADDING",(0,0), (-1,-1), 5),
            ("TOPPADDING",  (0,0), (-1,-1), 2),
            ("BOTTOMPADDING",(0,0), (-1,-1), 2),
        ]))
        return bar

    # Универсальная таблица групп — тёмные линии и полная ширина (фикс 1 и 5)
    def table_full(data, right_cols=()):
        # Позиция | Кол-во | Цена | Сумма — растянуто на всю ширину
        colWidths = [0.52*doc.width, 0.14*doc.width, 0.16*doc.width, 0.18*doc.width]
        t = Table(data, colWidths=colWidths, hAlign="LEFT")
        ts = [
            ("FONT", (0,0), (-1,0), bold_font, 9.5),
            ("TEXTCOLOR", (0,0), (-1,0), ACCENT),
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            ("LINEBELOW", (0,0), (-1,0), 0.9, LINES),
            ("FONT", (0,1), (-1,-1), base_font, 9),
            ("LINEABOVE", (0,1), (-1,-1), 0.6, LINES),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
            ("RIGHTPADDING",(0,0), (-1,-1), 5),
            ("TOPPADDING",  (0,0), (-1,-1), 1),
            ("BOTTOMPADDING",(0,0), (-1,-1), 1),
        ]
        for c in right_cols:
            ts.append(("ALIGN", (c,1), (c,-1), "RIGHT"))
        # Итог (последняя строка)
        n = len(data)
        if n >= 2:
            ts += [
                ("FONT", (0,n-1), (-1,n-1), bold_font, 9.5),
                ("LINEABOVE", (0,n-1), (-1,n-1), 1.0, ACCENT),
            ]
        t.setStyle(TableStyle(ts))
        return t

    # Таблица фасадов (3 колонки) — полная ширина и тёмные линии
    def table_facades(data):
        colWidths = [0.60*doc.width, 0.20*doc.width, 0.20*doc.width]
        t = Table(data, colWidths=colWidths, hAlign="LEFT")
        ts = [
            ("FONT", (0,0), (-1,0), bold_font, 9.5),
            ("TEXTCOLOR", (0,0), (-1,0), ACCENT),
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            ("LINEBELOW", (0,0), (-1,0), 0.9, LINES),
            ("FONT", (0,1), (-1,-1), base_font, 9),
            ("LINEABOVE", (0,1), (-1,-1), 0.6, LINES),
            ("ALIGN", (1,1), (2,-1), "RIGHT"),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
            ("RIGHTPADDING",(0,0), (-1,-1), 5),
            ("TOPPADDING",  (0,0), (-1,-1), 1),
            ("BOTTOMPADDING",(0,0), (-1,-1), 1),
        ]
        n = len(data)
        if n >= 2:
            ts += [
                ("FONT", (0,n-1), (-1,n-1), bold_font, 9.5),
                ("LINEABOVE", (0,n-1), (-1,n-1), 1.0, ACCENT),
            ]
        t.setStyle(TableStyle(ts))
        return t

    story = [header_tbl, Spacer(1, 4*mm), Paragraph("Сформировано автоматически на основе «Листа закупа».", styles["S"])]

    # --- ЛДСП ---
    qty_ldsp = (calc.qty_ldsp_total or Decimal("0"))
    ldsp_rows = [["Позиция", "Кол-во", "Цена", "Сумма"]]
    if qty_ldsp > 0:
        price_raspil_unit   = (calc.cost_ldsp_raspil   / qty_ldsp).quantize(Decimal("0.01")) if qty_ldsp > 0 else Decimal("0.00")
        price_prisadka_unit = (calc.cost_ldsp_prisadka / qty_ldsp).quantize(Decimal("0.01")) if qty_ldsp > 0 else Decimal("0.00")
        ldsp_rows.append(["Распил ЛДСП",   f"{qty_ldsp.quantize(Decimal('0.00'))}", fmt_money(price_raspil_unit),   fmt_money(calc.cost_ldsp_raspil)])
        ldsp_rows.append(["Присадка ЛДСП", f"{qty_ldsp.quantize(Decimal('0.00'))}", fmt_money(price_prisadka_unit), fmt_money(calc.cost_ldsp_prisadka)])
        ldsp_rows.append(["Итого ЛДСП", "", "", fmt_money(calc.cost_ldsp)])
        
    add_section_if_rows("ЛДСП", ldsp_rows, table_full, right_cols=(1,2,3))
    
    # Подпись под секцией ЛДСП без Paragraph — однострочная таблица
    try:
        _facade_sheets = int(getattr(calc, "design_facade_sheets", 0) or 0)
    except Exception:
        _facade_sheets = 0

    if _facade_sheets > 0:
        note_rows = [[f'В том числе: «Фасады (листов по 5 м²)»: {_facade_sheets} шт.']]
        note_tbl = Table(note_rows, colWidths=[doc.width], hAlign="LEFT")
        note_tbl.setStyle(TableStyle([
            ("FONT", (0,0), (-1,-1), base_font, 8),  # используем ваш кириллический шрифт
            ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#666666")),
            ("LEFTPADDING",   (0,0), (-1,-1), 0),
            ("RIGHTPADDING",  (0,0), (-1,-1), 0),
            ("TOPPADDING",    (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        story.append(Spacer(1, 1*mm))
        story.append(note_tbl)


    # --- ПВХ (узкая) ---
    qty_pvc = (calc.qty_pvc_total or Decimal("0"))
    pvc_rows = [["Позиция", "Кол-во", "Цена", "Сумма"]]
    if qty_pvc > 0:
        price_pvc_unit = (calc.cost_pvc / qty_pvc).quantize(Decimal("0.01")) if qty_pvc > 0 else Decimal("0.00")
        pvc_rows.append(["ПВХ узкая", f"{qty_pvc.quantize(Decimal('0.00'))}", fmt_money(price_pvc_unit), fmt_money(calc.cost_pvc)])
        pvc_rows.append(["Итого ПВХ (узкая)", "", "", fmt_money(calc.cost_pvc)])

    add_section_if_rows("ПВХ (узкая)", pvc_rows, table_full, right_cols=(1,2,3))


    # --- ПВХ (широкая) ---
    qty_pvcw = (calc.qty_pvc_wide_total or Decimal("0"))
    pvcw_rows = [["Позиция", "Кол-во", "Цена", "Сумма"]]
    if qty_pvcw > 0:
        price_pvcw_unit = (calc.cost_pvc_wide / qty_pvcw).quantize(Decimal("0.01")) if qty_pvcw > 0 else Decimal("0.00")
        pvcw_rows.append(["ПВХ широкая", f"{qty_pvcw.quantize(Decimal('0.00'))}", fmt_money(price_pvcw_unit), fmt_money(calc.cost_pvc_wide)])
        pvcw_rows.append(["Итого ПВХ (широкая)", "", "", fmt_money(calc.cost_pvc_wide)])
    
    add_section_if_rows("ПВХ (широкая)", pvcw_rows, table_full, right_cols=(1,2,3))


    # --- Прочее ---
    misc_rows = [["Позиция", "Кол-во", "Цена", "Сумма"]]
    cqty = (calc.countertop_qty or Decimal("0"))
    hqty = (calc.hdf_qty or Decimal("0"))

    if cqty > 0:
        price_c_unit = (calc.cost_countertop / cqty).quantize(Decimal("0.01")) if cqty > 0 else Decimal("0.00")
        misc_rows.append(["Столешница (шт.)", f"{cqty.quantize(Decimal('0.00'))}", fmt_money(price_c_unit), fmt_money(calc.cost_countertop)])

    if hqty > 0:
        price_h_unit = (calc.cost_hdf / hqty).quantize(Decimal("0.01")) if hqty > 0 else Decimal("0.00")
        misc_rows.append(["ХДФ задняя стенка (листов)", f"{hqty.quantize(Decimal('0.00'))}", fmt_money(price_h_unit), fmt_money(calc.cost_hdf)])

    if len(misc_rows) > 1:
        misc_rows.append(["Итого «Прочее»", "", "", fmt_money(calc.cost_misc)])

    add_section_if_rows("Прочее", misc_rows, table_full, right_cols=(1,2,3))

    
    # --- Дополнительно ---
    add_rows = [["Позиция", "Кол-во", "Цена", "Сумма"]]
    for ai in calc.additional_items.select_related("price_item").all():
        qty = (ai.qty or Decimal("0"))
        if qty <= 0 and not (ai.cost or Decimal("0")) > 0:
            continue
        unit = (ai.cost / qty).quantize(Decimal("0.01")) if qty > 0 else Decimal("0.00")
        add_rows.append([ai.price_item.title, f"{qty.quantize(Decimal('0.00'))}", fmt_money(unit), fmt_money(ai.cost or Decimal('0'))])

    if len(add_rows) > 1:
        add_rows.append(["Итого «Дополнительно»", "", "", fmt_money(calc.cost_additional or Decimal("0"))])

    add_section_if_rows("Дополнительно", add_rows, table_full, right_cols=(1,2,3))



    # --- Фасады ---
    fac_rows = [["Позиция", "Площадь, м²", "Сумма"]]
    fac_qs = list(calc.facade_items.select_related("price_item").all())
    for fi in fac_qs:
        area = (fi.area or Decimal("0")).quantize(Decimal("0.01"))
        fac_rows.append([fi.price_item.title, f"{area}", fmt_money(fi.cost or Decimal("0"))])

    # Добавим итоговую строку только если есть хотя бы одна позиция ИЛИ есть общая стоимость
    if len(fac_rows) > 1 or (calc.cost_facades or Decimal("0")) > 0:
        if len(fac_rows) == 1:  # нет позиций, но есть сумма — покажем только итог
            fac_rows.append(["Итого фасады", "", fmt_money(calc.cost_facades or Decimal("0"))])
        else:
            fac_rows.append(["Итого фасады", "", fmt_money(calc.cost_facades or Decimal("0"))])

    add_section_if_rows("Фасады", fac_rows, table_facades)

    
    
    # --- Проект / Дизайн-проект ---
    design_rows = [["Позиция", "Кол-во", "Цена", "Сумма"]]
    dl = (calc.design_ldsp_cost or Decimal("0"))
    df = (calc.design_facade_cost or Decimal("0"))
    dt = (calc.cost_design_total  or Decimal("0"))

    if dl > 0: design_rows.append(["ЛДСП — дизайн", "", "", fmt_money(dl)])
    if df > 0: design_rows.append(["Фасады — дизайн", "", "", fmt_money(df)])
    if dt > 0: design_rows.append(["Итого «Дизайн-проект»", "", "", fmt_money(dt)])
        

    add_section_if_rows("Проект / Дизайн-проект", design_rows, table_full, right_cols=(1,2,3))
    # Предупреждение под «Итого Дизайн-проект» на всю ширину
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Внимание: оплата за дизайн-проект является оплатой интеллектуальной услуги и после начала работ "
        "не подлежит возврату. Оплата подтверждает согласие с ТЗ и составом работ.",
        styles.get("S") or styles["P"]  # маленький шрифт, если есть; иначе обычный
    ))


    

    # Итог
    # ВНИМАНИЕ: total_price считается БЕЗ фасадов (см. вычисление выше)
    amt_ops     = (calc.total_price or Decimal("0.00"))          # ЛДСП/ПВХ/прочее/доп. — без фасадов
    amt_design  = (calc.cost_design_total or Decimal("0.00"))    # Проект / Дизайн-проект
    amt_facades = (calc.cost_facades or Decimal("0.00"))         # Фасады
    total_to_pay = (amt_ops + amt_design + amt_facades).quantize(Decimal("0.01"))

    story += [Spacer(1, 10*mm)]
    total_tbl = Table(
        [[Paragraph("Итого к оплате", styles["P"]),
          Paragraph(f"<b>{fmt_money(total_to_pay)}</b>", styles["TotalAmount"])]],
        colWidths=[0.70*doc.width, 0.30*doc.width], hAlign="RIGHT"
    )
    total_tbl.setStyle(TableStyle([
        ("LINEABOVE", (0,0), (-1,0), 1.0, ACCENT),
        ("ALIGN", (1,0), (1,0), "RIGHT"),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING",(0,0), (-1,-1), 4),
        ("TOPPADDING",  (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 2),
    ]))
    story.append(total_tbl)

    # Заметка
    if (calc.note or "").strip():
        story += [Spacer(1, 6*mm)]
        note = Paragraph(f"Заметка: {calc.note}", styles['R'])
        note_box = Table([[note]], colWidths=[doc.width], hAlign="LEFT")
        note_box.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.whitesmoke),
            ("BOX", (0,0), (-1,-1), 0.6, LINES),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING",(0,0), (-1,-1), 6),
            ("TOPPADDING",  (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ]))
        story.append(note_box)

    # Номер страницы
    def _add_page_number(canvas, doc_):
        canvas.setFont(base_font, 8)
        canvas.setFillColor(SUB)
        canvas.drawRightString(A4[0] - 18*mm, 12*mm, f"Стр. {doc_.page}")

    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
    
    
    pdf = buf.getvalue()
    buf.close()

    # Имя клиента (чистим для файлового имени)
    customer = (getattr(order, "customer_name", "") or "").strip() or "Без имени"
    # Запрещённые в именах файлов символы → "_"
    customer = re.sub(r'[\\/*?:"<>|]+', "_", customer)
    # Пробелы → подчёркивания
    customer = re.sub(r"\s+", "_", customer)

    # Итоговое имя файла (кириллица) + ASCII-фолбэк
    fname_display = f"{order.order_number}_{customer}_ЛИСТ_РАСЧЁТА.pdf"
    fname_ascii   = f"order_{order.order_number}_LIST_RASCHETA.pdf"

    resp = HttpResponse(pdf, content_type="application/pdf")
    # attachment → скачивание; filename* даёт корректное имя на кириллице по RFC 5987
    resp["Content-Disposition"] = (
        f"attachment; filename={fname_ascii}; filename*=UTF-8''{quote(fname_display)}"
    )
    return resp

# =======================
#  Оплата: форма и чек PDF
# =======================
from .forms import PaymentForm
from django.utils import timezone as _tz



def _flag(post, name: str) -> bool:
    # True only if the field is present and equals 1/on/true/yes
    v = post.get(name, None)
    return str(v).strip().lower() in {"1", "on", "true", "yes"}


@login_required
def payment_view(request, order_id: int):
    """
    Маска include_mask ("total,design,facades") определяет активные категории.
    Цели берём из текущего расчёта; дельты = target - уже_оплачено.
    Выключенные пилюлей категории в текущей операции просто игнорируем (дельта=0).
    """
    order = get_object_or_404(Order, pk=order_id)
    calc = getattr(order, "calculation", None)
    if not calc:
        return HttpResponseForbidden("Сначала заполните Расчёт")

    try:
        calc.refresh_from_db()
    except Exception:
        pass

    # фасады из позиций
    agg = calc.facade_items.aggregate(s=Sum("cost"))
    calc.cost_facades = agg["s"] or Decimal("0")

    # обработка БЕЗ фасадов (по компонентам)
    ops_total = (
        _dec(getattr(calc, "cost_ldsp", 0)) +
        _dec(getattr(calc, "cost_pvc", 0)) +
        _dec(getattr(calc, "cost_pvc_wide", 0)) +
        _dec(getattr(calc, "cost_misc", 0)) +
        _dec(getattr(calc, "cost_additional", 0))
    )

    # текущий расчёт
    cur_total   = ops_total
    cur_design  = _dec(getattr(calc, "cost_design_total", 0))
    cur_facades = _dec(getattr(calc, "cost_facades", 0))

    last = Payment.objects.filter(order=order).order_by("-created_at", "-id").first()

    if request.method == "POST":
        form = PaymentForm(request.POST)

        # методы оплаты
        methods = (request.POST.getlist("methods") or request.POST.getlist("methods[]") or [])

        # маска пилюль
        mask_raw = (request.POST.get("include_mask") or "").strip()
        mask = set(s.strip() for s in mask_raw.split(",") if s.strip())
        if not mask:
            if request.POST.get("inc_total"):   mask.add("total")
            if request.POST.get("inc_design"):  mask.add("design")
            if request.POST.get("inc_facades"): mask.add("facades")

        inc_total   = "total"   in mask
        inc_design  = "design"  in mask
        inc_facades = "facades" in mask

        # 1) цели — ВСЕГДА из текущего расчёта
        target_total   = cur_total
        target_design  = cur_design
        target_facades = cur_facades
        
        # 2) сколько уже оплачено
        paid_agg = order.payments.aggregate(
            t=Sum("amount_total"),
            d=Sum("amount_design"),
            f=Sum("amount_facades"),
        )
        paid_total   = _dec(paid_agg["t"])
        paid_design  = _dec(paid_agg["d"])
        paid_facades = _dec(paid_agg["f"])
        
        # 3) "сколько доплатить/вернуть" по каждой категории (сырой расчёт)
        delta_total   = target_total   - paid_total
        delta_design  = target_design  - paid_design
        delta_facades = target_facades - paid_facades
        
        # 4) МАСКА пилюль: выключенные категории не трогаем (дельта=0)
        if not inc_total:
            delta_total = Decimal("0")
        if not inc_design:
            delta_design = Decimal("0")
        if not inc_facades:
            delta_facades = Decimal("0")
        
        # 5) ПРАВИЛО НЕВОЗВРАТНОСТИ ДИЗАЙНА:
        #    если по дизайну получилась отрицательная дельта — обнуляем её (возврат нельзя)
        if delta_design < 0:
            delta_design = Decimal("0")
        
        # 6) итог к оплате/возврату
        delta_due = delta_total + delta_design + delta_facades


        # нечего проводить
        if delta_total == 0 and delta_design == 0 and delta_facades == 0:
            messages.info(request, "По выбранным категориям нечего проводить.")
            return redirect("payment_new", order_id=order.id)

        # первый POST — модалка
        if not request.POST.get("confirm"):
            if not methods:
                messages.error(request, "Отметьте хотя бы один способ оплаты.")
                return redirect("payment_new", order_id=order.id)

            payments_qs = order.payments.order_by("-created_at", "-id")
            paid_sum = payments_qs.aggregate(s=Sum("amount_due"))["s"] or Decimal("0")
            return render(request, "payment_form.html", {
                "order": order,
                "form": form,
                "calc": calc,
                "has_payment": bool(last),
                "existing": last,
                "payments": payments_qs,
                "paid_sum": paid_sum,
                "show_confirm_modal": True,
                "delta": {
                    "total":   delta_total,
                    "design":  delta_design,
                    "facades": delta_facades,
                    "due":     delta_due,
                },
                "inc_total": inc_total,
                "inc_design": inc_design,
                "inc_facades": inc_facades,
                "include_mask": ",".join(
                    name for name, flag in (("total", inc_total), ("design", inc_design), ("facades", inc_facades))
                    if flag
                ),
            })

        # подтверждение — создаём чек ровно на дельты
        if not methods:
            messages.error(request, "Отметьте хотя бы один способ оплаты.")
            return redirect("payment_new", order_id=order.id)

        amount_total   = delta_total
        amount_design  = delta_design
        amount_facades = delta_facades
        amount_due     = delta_due

        # антидубликат (5 мин)
        if last:
            same_methods = (sorted(last.methods or []) == sorted(methods or []))
            same_mode = (getattr(last, "mode", None) == "diff")
            is_exact_duplicate = (
                last.amount_total == amount_total and
                last.amount_design == amount_design and
                last.amount_facades == amount_facades and
                last.amount_due == amount_due and
                same_methods and
                same_mode
            )
            if is_exact_duplicate and (timezone.now() - last.created_at) < timedelta(minutes=5):
                messages.info(request, "Похоже, такой же чек уже создан недавно — дубликат не создан.")
                return redirect("payment_new", order_id=order.id)

        extra = {}
        if hasattr(Payment, "calc_snapshot"):
            extra["calc_snapshot"] = {
                "total":   str(cur_total),
                "design":  str(cur_design),
                "facades": str(cur_facades),
            }
        if hasattr(Payment, "mode"):
            extra["mode"] = "diff"

        Payment.objects.create(
            order=order,
            amount_total=amount_total,
            amount_design=amount_design,
            amount_facades=amount_facades,
            amount_due=amount_due,
            methods=methods,
            created_by=request.user if request.user.is_authenticated else None,
            **extra,
        )
        messages.success(request, "Оплата принята. Создан новый чек.")
        return redirect("payment_new", order_id=order.id)

    # GET — инициализируем от текущего расчёта
    initial = {
        "amount_total":   cur_total,
        "amount_design":  cur_design,
        "amount_facades": cur_facades,
    }
    form = PaymentForm(initial=initial)

    payments_qs = order.payments.order_by("-created_at", "-id")
    paid_sum = payments_qs.aggregate(s=Sum("amount_due"))["s"] or Decimal("0")

    sel_id = request.GET.get("p")
    selected_payment = None
    if sel_id and sel_id.isdigit():
        try:
            selected_payment = order.payments.get(id=int(sel_id))
        except Payment.DoesNotExist:
            selected_payment = None
    if not selected_payment:
        selected_payment = Payment.objects.filter(order=order).order_by("-created_at", "-id").first()

    payments_short = order.payments.order_by("-created_at", "-id")
    

    return render(request, "payment_form.html", {
        "order": order,
        "form": form,
        "calc": calc,
        "has_payment": bool(selected_payment),
        "existing": selected_payment,
        "payments": payments_qs,
        "paid_sum": paid_sum,
        "selected_payment": selected_payment,
        "payments_short": payments_short,
        "show_confirm_modal": False,
        "inc_total": True, "inc_design": True, "inc_facades": True,
    })




def payment_receipt_id(request, order_id: int, payment_id: int):
    order = get_object_or_404(Order, pk=order_id)
    payment = get_object_or_404(Payment, pk=payment_id, order=order)
    return payment_receipt_pdf(payment)


def payment_receipt_pdf(payment: Payment):
    """
    Красивый PDF-чек: шапка с бренд-полосой и логотипом, блок метаданных,
    читаемая таблица позиций, акцент на ИТОГО, подпись кассира.
    """
    buf = BytesIO()

    # --- Документ ---
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=24, rightMargin=24, topMargin=40, bottomMargin=28,
        title=f"Чек оплаты #{payment.id}"
    )

    # --- Палитра/бренд ---
    BRAND_ORANGE = colors.HexColor("#E67E22")
    HEADER_BG    = colors.HexColor("#FFF4E5")
    ZEBRA_BG     = colors.HexColor("#FEF6ED")
    GRID         = colors.HexColor("#E5E7EB")
    MUTED        = colors.HexColor("#6B7280")

    # --- Стили (используем зарегистрированные вверху DejaVuSans/DejaVuSans-Bold) ---
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="H1", parent=styles["Normal"],
        fontName=PDF_FONT_BLD, fontSize=16, leading=20, textColor=colors.black
    ))
    styles.add(ParagraphStyle(
        name="Sub", parent=styles["Normal"],
        fontName=PDF_FONT_REG, fontSize=10.5, leading=14, textColor=MUTED
    ))
    styles.add(ParagraphStyle(
        name="Base", parent=styles["Normal"],
        fontName=PDF_FONT_REG, fontSize=11, leading=14
    ))
    styles.add(ParagraphStyle(
        name="Emph", parent=styles["Normal"],
        fontName=PDF_FONT_BLD, fontSize=13, leading=18
    ))

    # --- Шапка с оранжевой плашкой и логотипом ---
    def draw_header(canv, _doc):
        canv.saveState()
        # оранжевая полоска по верху
        canv.setFillColor(BRAND_ORANGE)
        canv.rect(0, A4[1] - 42, A4[0], 42, stroke=0, fill=1)

        # белая подложка под логотип
        canv.setFillColor(colors.white)
        canv.roundRect(18, A4[1] - 38, 165, 34, 5, stroke=0, fill=1)

        # логотип (ищем через staticfiles)
        logo_path = None
        for p in (
            "img/company_logo.png",
            "core/static/img/company_logo.png",
            "static/img/company_logo.png",
            "core/static/img/logo.png",
            "static/img/logo.png",
        ):
            lp = finders.find(p)
            if lp:
                logo_path = lp
                break
        if logo_path:
            try:
                canv.drawImage(logo_path, 35, A4[1]-36, width=130, height=28,
                               preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        # служебная надпись справа
        canv.setFillColor(colors.white)
        try:
            canv.setFont(PDF_FONT_BLD, 11)
        except Exception:
            canv.setFont("Helvetica-Bold", 11)
        canv.drawRightString(A4[0]-24, A4[1]-36, "Не является фискальным чеком")
        canv.restoreState()

    # --- Контент чека ---
    items = []

    # Заголовок
    title = Paragraph(f"Чек оплаты № {payment.id}", styles["H1"])
    subtitle = Paragraph(f"Заказ № {payment.order.order_number}", styles["Sub"])
    items += [title, subtitle, Spacer(1, 8)]

    # Метаданные
    dt_str = _tz.localtime(payment.created_at).strftime("%d.%m.%Y %H:%M")
    staff = getattr(payment, "created_by", None)
    if staff:
        ln = (getattr(staff, "last_name", "") or "").strip()
        fn = (getattr(staff, "first_name", "") or "").strip()
        if ln or fn:
            staff_name = f"{ln} {fn}".strip()
        else:
            staff_name = (getattr(staff, "username", "") or "—").strip()
    else:
        staff_name = "—"

    meta = [
        ["Дата и время", dt_str],
        ["Клиент",       payment.order.customer_name or "—"],
        ["Телефон",      payment.order.phone or "—"],
        ["Способ оплаты", ", ".join(dict(Payment.METHODS).get(m, m) for m in (payment.methods or [])) or "—"],
    ]
    meta_tbl = Table(meta, colWidths=[38*mm, None], hAlign="LEFT")
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), PDF_FONT_REG),
        ("FONTSIZE", (0,0), (-1,-1), 10.5),
        ("TEXTCOLOR",(0,0), (0,-1), MUTED),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    items += [meta_tbl, Spacer(1, 8)]

    # Таблица позиций
    def fmt_money(val):
        from decimal import Decimal
        try:
            q = Decimal(str(val or 0))
        except Exception:
            q = Decimal(0)
        q = q.quantize(Decimal("1"))
        s = f"{int(q):,}".replace(",", " ")
        return f"{s}\u00A0₸"   # ← неразрывный пробел + тенге

    data = [
        ["Позиция", "Сумма"],
        ["Обработка материала", fmt_money(payment.amount_total)],
        ["Фасады",              fmt_money(getattr(payment, "amount_facades", 0))],
        ["Дизайн проект",       fmt_money(payment.amount_design)],
        ["ИТОГО К ОПЛАТЕ",     fmt_money(payment.amount_due)],
    ]
    tbl = Table(data, colWidths=[150*mm, None], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        # шапка
        ("FONTNAME", (0,0), (-1,0), PDF_FONT_BLD),
        ("FONTSIZE", (0,0), (-1,0), 11),
        ("BACKGROUND", (0,0), (-1,0), HEADER_BG),
        ("LINEBELOW", (0,0), (-1,0), 0.6, GRID),

        # тело
        ("FONTNAME", (0,1), (-1,-2), PDF_FONT_REG),
        ("FONTSIZE", (0,1), (-1,-2), 11),
        ("GRID", (0,0), (-1,-2), 0.3, GRID),
        ("ALIGN", (1,1), (1,-2), "RIGHT"),

        # итог
        ("FONTNAME", (0,-1), (-1,-1), PDF_FONT_BLD),
        ("FONTSIZE", (0,-1), (-1,-1), 13),
        ("BACKGROUND", (0,-1), (-1,-1), ZEBRA_BG),
        ("ALIGN", (1,-1), (1,-1), "RIGHT"),
        ("LINEABOVE", (0,-1), (-1,-1), 0.8, BRAND_ORANGE),

        # отступы
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING",(0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
    ]))
    items += [tbl, Spacer(1, 8)]

    # --- Примечание перед подписью (добавлено) ---
    items += [
        Paragraph(
            "Оплата подтверждает согласие с ТЗ и составом работ. "
            "Данный документ не является фискальным чеком.",
            styles["Sub"]
        ),
        Spacer(1, 10),
    ]  # ← добавлено

    # Подпись
    sign_tbl = Table(
        [[
            Paragraph("Подпись плательщика: __________________________", styles["Base"]),
            Paragraph(f"Принял(а) оплату: {staff_name}", styles["Base"])
        ]],
        colWidths=[140*mm, None], hAlign="LEFT"
    )
    sign_tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), PDF_FONT_REG),
        ("FONTSIZE", (0,0), (-1,-1), 11),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    items.append(sign_tbl)

    # Сборка
    doc.build(items, onFirstPage=draw_header, onLaterPages=draw_header)
    pdf = buf.getvalue()
    buf.close()

    # Отдаём файл
    resp = HttpResponse(pdf, content_type="application/pdf")
    fname_display = f"{payment.order.order_number}_Чек оплаты № {payment.id}.pdf"
    fname_ascii   = f"order_{payment.order.order_number}_receipt_{payment.id}.pdf"
    resp["Content-Disposition"] = (
        f'attachment; filename="{fname_ascii}"; filename*=UTF-8\'\'{quote(fname_display)}'
    )
    return resp





def payment_receipt(request, order_id: int):
    order = get_object_or_404(Order, pk=order_id)
    payment = Payment.objects.filter(order=order).first()
    if not payment:
        return HttpResponseForbidden("Оплата не найдена")
    return payment_receipt_pdf(payment)

@login_required
def payment_refresh(request, order_id: int):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    order = get_object_or_404(Order, pk=order_id)
    calc = getattr(order, "calculation", None)
    if not calc:
        return HttpResponseForbidden("Сначала заполните Расчёт")

    try:
        calc.refresh_from_db()
    except Exception:
        pass

    agg = calc.facade_items.aggregate(s=Sum("cost"))
    calc.cost_facades = agg["s"] or Decimal("0.00")

    existing = Payment.objects.filter(order=order).first()

    initial = {
        "amount_total":   (calc.total_price or 0),
        "amount_design":  (calc.cost_design_total or 0),
        "amount_facades": (calc.cost_facades or 0),
    }
    form = PaymentForm(initial=initial)

    # ДОБАВИЛИ историю и итог
    payments_qs = order.payments.order_by("-created_at", "-id")
    paid_sum = payments_qs.aggregate(s=Sum("amount_due"))["s"] or Decimal("0")

    return render(request, "payment_form.html", {
        "order": order,
        "form": form,
        "calc": calc,
        "has_payment": bool(existing),
        "existing": existing,
        "payments": payments_qs,
        "paid_sum": paid_sum,
        "show_choice_modal": False,
    })
    
    
    

def _calc_live_numbers(order):
    """
    Возвращает «живые» суммы из Calculation с ЕДИНЫМИ ключами:
    ldsp, pvc_narrow, pvc_wide, hdf, countertop
    """
    calc = getattr(order, "calculation", None)
    D = Decimal
    out = {
        "ldsp": D("0.00"),         # ЛДСП (листов) — группа «Проект»
        "pvc_narrow": D("0.00"),   # ПВХ узкая (м) — «Итого»
        "pvc_wide": D("0.00"),     # ПВХ широкая (м) — «Итого»
        "hdf": D("0.00"),          # ХДФ (листов) — «Прочее»
        "countertop": D("0.00"),   # Столешница (шт.) — «Прочее»
    }
    if not calc:
        return out

    # Нормализуем разные возможные имена полей в Calculation:
    ldsp_total = (getattr(calc, "qty_ldsp_total", None) or D("0.00"))
    facade_sheets = D(str(getattr(calc, "design_facade_sheets", 0) or 0))
    # На склад: только листы ЛДСП без фасадов
    out["ldsp"] = (ldsp_total - facade_sheets)
    if out["ldsp"] < D("0"):
        out["ldsp"] = D("0.00")
    
    out["pvc_narrow"]  = (getattr(calc, "qty_pvc_total", None) or D("0.00"))
    out["pvc_wide"]    = (getattr(calc, "qty_pvc_wide_total", None) or D("0.00"))
    out["hdf"]         = (getattr(calc, "hdf_qty", None) or D("0.00"))
    out["countertop"]  = (getattr(calc, "countertop_qty", None) or D("0.00"))

    # Квантование до 2 знаков
    for k in out:
        out[k] = (Decimal(str(out[k]))).quantize(Decimal("0.00"))
    return out
    
    
def _has_ops_payment(order) -> bool:
    """
    Возврат True, если по заказу суммарная оплата за «Обработка материала»
    (amount_total) положительная. Возвраты (отрицательные чеки) учитываются.
    """
    agg = order.payments.aggregate(s=Sum("amount_total"))
    s = Decimal(str(agg["s"] or 0))
    return s > 0

def _ldsp_formats_from_purchase(order):
    """
    Группируем ЛДСП по форматам на основании PurchaseSheet.
    Понимаем разделители: 'x', '×', '*', а также кириллическую 'х'.
    Возвращает {'2750x1830': count, '2800x2070': count}
    """
    ps = getattr(order, "purchase_sheet", None) or getattr(order, "purchasesheet", None)
    res = {"2750x1830": Decimal("0.00"), "2800x2070": Decimal("0.00")}
    if not ps:
        return res

    for i in range(1, 11):
        qty = getattr(ps, f"lds_color{i}", None) or 0
        fmt_raw = (getattr(ps, f"lds_format{i}", "") or "")
        # нормализация: убрать пробелы, привести вариант разделителя к 'x'
        fmt = fmt_raw.strip().lower()
        fmt = fmt.replace("×", "x").replace("х", "x")  # кириллическая 'х'
        fmt = fmt.replace("*", "x")
        fmt = re.sub(r"\s+", "", fmt)  # убрать пробелы

        if not qty or not fmt:
            continue

        if "2750" in fmt and "1830" in fmt:
            res["2750x1830"] += Decimal(str(qty))
        elif "2800" in fmt and "2070" in fmt:
            res["2800x2070"] += Decimal(str(qty))

    return res
    
    
    
def _dec0(v):
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0")


def _needed_for_order(order):
    """
    Возвращает кортеж «сколько нужно по расчёту»:
    (ldsp_total, pvc_narrow, pvc_wide, hdf, countertop)

    ldsp_total = fmt_2750 + fmt_2800  (листов)
    Остальные — как есть.
    Если расчёта нет — нули.
    """
    calc = getattr(order, "calculation", None)
    if not calc:
        return (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))

    fmt_2750 = _dec0(getattr(calc, "fmt_2750", 0))
    fmt_2800 = _dec0(getattr(calc, "fmt_2800", 0))

    need_pvc_narrow = _dec0(getattr(calc, "need_pvc_narrow", 0))
    need_pvc_wide   = _dec0(getattr(calc, "need_pvc_wide", 0))
    need_hdf        = _dec0(getattr(calc, "need_hdf", 0))
    need_countertop = _dec0(getattr(calc, "need_countertop", 0))

    ldsp_total = fmt_2750 + fmt_2800
    return (ldsp_total, need_pvc_narrow, need_pvc_wide, need_hdf, need_countertop)

def warehouse(request):
    cutoff = timezone.now() - timedelta(hours=2)
    for wr in WarehouseReceipt.objects.filter(status="draft", created_at__lt=cutoff):
        if _is_empty_draft_receipt(wr):
            wr.delete()
    # Отсекаем черновые приёмки-призраки (оставляем как есть)
    cutoff = timezone.now() - timedelta(hours=2)
    for wr in WarehouseReceipt.objects.filter(status="draft", created_at__lt=cutoff):
        if _is_empty_draft_receipt(wr):
            wr.delete()
    
    waiting, accepted = [], []
    
    # Берём только те заказы, где есть ЛЮБЫЕ оплаты (чтобы не тянуть весь список),
    # дальше будем фильтровать по нашим правилам.
    candidate_orders = (Order.objects
        .filter(payments__isnull=False)
        .distinct()
        .select_related("calculation", "purchase_sheet"))
    
    for o in candidate_orders:
        if o.warehouse_receipts.filter(status="accepted").exists():
            sums = _sum_accepted_receipts(o)
            row = {"order": o, **sums}
    
            # ← вот здесь была ошибка: было _calc_live_numbers(order)
            need = _calc_live_numbers(o)
            row["need_ldsp"]       = need.get("ldsp", Decimal("0"))
            row["need_pvc_narrow"] = need.get("pvc_narrow", Decimal("0"))
            row["need_pvc_wide"]   = need.get("pvc_wide", Decimal("0"))
            row["need_hdf"]        = need.get("hdf", Decimal("0"))
            row["need_countertop"] = need.get("countertop", Decimal("0"))
    
            last = (o.warehouse_receipts.filter(status="accepted")
                    .order_by("-received_at", "-created_at")
                    .first())
            row["received_date"] = getattr(last, "received_at", None) or getattr(last, "created_at", None)
    
            accepted.append(row)
            continue
    
        # Живые количества из расчёта
        live = _calc_live_numbers(o)
        ldsp_sheets = live.get("ldsp")  # это ЛДСП (листов) БЕЗ «фасадных листов»
    
        # Наши два условия для «Ожидают»:
        # 1) ЛДСП листы > 0
        # 2) Есть положительная суммарная оплата за «Обработка материала»
        if (ldsp_sheets and ldsp_sheets > 0) and _has_ops_payment(o):
            waiting.append({
                "order": o,
                "ldsp": ldsp_sheets,
                "pvc_narrow": live.get("pvc_narrow"),
                "pvc_wide": live.get("pvc_wide"),
                "hdf": live.get("hdf"),
                "countertop": live.get("countertop"),
            })
        # иначе — не добавляем заказ вовсе (ни оплат по обработке, ни ЛДСП, либо был возврат)

    # ИТОГО по складу: суммируем только принятые завозы
    ZERO_DEC = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))

    agg = WarehouseReceipt.objects.filter(status="accepted").aggregate(
        ldsp_2750 = Coalesce(Sum("qty_ldsp_2750x1830"), ZERO_DEC),
        ldsp_2800 = Coalesce(Sum("qty_ldsp_2800x2070"), ZERO_DEC),
        hdf       = Coalesce(Sum("qty_hdf_sheets"),     ZERO_DEC),
        counter   = Coalesce(Sum("qty_countertop_pcs"), ZERO_DEC),
    )
    
    total_ldsp       = (agg["ldsp_2750"] or Decimal("0")) + (agg["ldsp_2800"] or Decimal("0"))
    total_hdf        = agg["hdf"] or Decimal("0")
    total_countertop = agg["counter"] or Decimal("0")
    
    return render(request, "warehouse/warehouse.html", {"waiting": waiting, "accepted": accepted, "total_ldsp": total_ldsp, "total_hdf": total_hdf, "total_countertop": total_countertop})

def warehouse_accept(request, receipt_id: int):
    wr = get_object_or_404(WarehouseReceipt, pk=receipt_id)
    order = wr.order

    live = _calc_live_numbers(order)
    formats = _ldsp_formats_from_purchase(order)
    stock = _sum_accepted_receipts(order)
    stock_split = _sum_accepted_receipts_split(order)

    if request.method == "POST":
        D = Decimal
        q = lambda k: D(str(request.POST.get(k) or "0"))
      
        # 1) значения из формы
        wr.qty_ldsp_2750x1830 = q("qty_ldsp_2750x1830")
        wr.qty_ldsp_2800x2070 = q("qty_ldsp_2800x2070")
        wr.qty_pvc_narrow_m   = q("qty_pvc_narrow_m")
        wr.qty_pvc_wide_m     = q("qty_pvc_wide_m")
        wr.qty_hdf_sheets     = q("qty_hdf_sheets")
        wr.qty_countertop_pcs = q("qty_countertop_pcs")
        wr.countertop_edge_present = bool(request.POST.get("countertop_edge_present"))
        wr.driver_name  = (request.POST.get("driver_name") or "").strip()
        wr.driver_phone = (request.POST.get("driver_phone") or "").strip()
      
        # 2) подпись
        sig_b64 = request.POST.get("signature_png") or ""
        # принимаем PNG/JPEG/WEBP и т.п.
        m = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", sig_b64, re.I)
        if m:
            ext = m.group(1).lower()
            b64 = m.group(2)
            if ext == "jpg":  # унифицируем
                ext = "jpeg"
            try:
                content = ContentFile(base64.b64decode(b64))
                fname = f"sig_{uuid.uuid4().hex}.{ext}"
                # не делаем отдельный save до общего wr.save(); привязываем файл к полю
                wr.signature.save(fname, content, save=False)
            except Exception:
                pass
      
        action = request.POST.get("action")
      
        # 3) атомарно сохраняем ВСЁ
        with transaction.atomic():
            if action == "accept":
                wr.status = "accepted"
                wr.received_at = timezone.now()
            wr.save()
        
            if action == "accept":
                # Переводим заказ в статус «Договор»
                try:
                    order.status = Order.STATUS_WAREHOUSE
                    order.save(update_fields=["status"])
                except Exception:
                    pass
                # удаляем черновик только при финализации
                WarehouseDraft.objects.filter(receipt=wr).delete()
        
      
        # 5) редирект
        return redirect("warehouse" if action == "accept" else "warehouse_accept", **({} if action=="accept" else {"receipt_id": wr.id}))

    # draft + пилюля «Кромка»
    draft = getattr(wr, "draft", None)
    draft_payload = draft.payload if draft else {}
    
    edge_selected = bool(
        wr.countertop_edge_present or draft_payload.get("countertop_edge_present")
    )
    
    if not edge_selected:
        last_acc = (
            order.warehouse_receipts
            .filter(status="accepted")
            .order_by("-received_at", "-created_at")
            .first()
        )
        if last_acc and last_acc.countertop_edge_present:
            edge_selected = True

    # ЕДИНСТВЕННЫЙ render — в самом конце:
    return render(request, "warehouse/accept.html", {
        "order": order,
        "wr": wr,
        "receipt_id": wr.id,
        "live": live,
        "fmt_2750": formats.get("2750x1830"),
        "fmt_2800": formats.get("2800x2070"),
        "draft": draft_payload,
        "edge_selected": edge_selected,
        # подсказки «в закупе:» — через .get с дефолтом
        "need_pvc_narrow":  live.get("pvc_narrow",  Decimal("0.00")),
        "need_pvc_wide":    live.get("pvc_wide",    Decimal("0.00")),
        "need_hdf":         live.get("hdf",         Decimal("0.00")),
        "need_countertop":  live.get("countertop",  Decimal("0.00")),
        "stock_ldsp":       stock.get("ldsp"),
        "stock_pvc_narrow": stock.get("pvc_narrow"),
        "stock_pvc_wide":   stock.get("pvc_wide"),
        "stock_hdf":        stock.get("hdf"),
        "stock_countertop": stock.get("countertop"),
        "stock_ldsp_2750":  stock_split.get("ldsp_2750"),
        "stock_ldsp_2800":  stock_split.get("ldsp_2800"),
    })

@require_POST
def warehouse_save_draft(request, receipt_id: int):
    wr = get_object_or_404(WarehouseReceipt, pk=receipt_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("invalid json")

    wd, _ = WarehouseDraft.objects.get_or_create(receipt=wr)
    wd.payload = data
    wd.save(update_fields=["payload", "updated_at"])
    return JsonResponse({"ok": True})
    
def warehouse_start_accept(request, order_id: int):
    order = get_object_or_404(Order, pk=order_id)
    # если есть незавершённая — переиспользуем
    wr = WarehouseReceipt.objects.filter(order=order, status="draft").order_by("-id").first()
    if not wr:
        wr = WarehouseReceipt.objects.create(order=order, created_by=request.user if request.user.is_authenticated else None)
        WarehouseDraft.objects.get_or_create(receipt=wr, defaults={"payload": {}})
    return redirect("warehouse_accept", receipt_id=wr.id)


def warehouse_start_additional(request, order_id: int):
    """
    Создать НОВУЮ частичную приёмку (довоз) даже если уже есть принятые.
    """
    order = get_object_or_404(Order, pk=order_id)
    wr = WarehouseReceipt.objects.create(
        order=order,
        created_by=request.user if request.user.is_authenticated else None,
        status="draft",
    )
    WarehouseDraft.objects.get_or_create(receipt=wr, defaults={"payload": {}})
    return redirect("warehouse_accept", receipt_id=wr.id)


def warehouse_receipts_json(request, order_id: int):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    order = get_object_or_404(Order, pk=order_id)
    items = []
    for r in (order.warehouse_receipts
              .filter(status="accepted")
              .order_by("-received_at", "-created_at")):
        # подпись может отсутствовать → берём URL аккуратно
        sig_url = ""
        try:
            if getattr(r, "signature", None) and getattr(r.signature, "name", ""):
                sig_url = r.signature.url
        except Exception:
            sig_url = ""

        items.append({
            "id": r.id,
            "status": r.status,
            "created_at": localtime(r.created_at).strftime("%d.%m.%Y %H:%M"),
            "qty_ldsp_2750x1830": str(r.qty_ldsp_2750x1830 or 0),
            "qty_ldsp_2800x2070": str(r.qty_ldsp_2800x2070 or 0),
            "qty_pvc_narrow_m":   str(r.qty_pvc_narrow_m   or 0),
            "qty_pvc_wide_m":     str(r.qty_pvc_wide_m     or 0),
            "qty_hdf_sheets":     str(r.qty_hdf_sheets     or 0),
            "qty_countertop_pcs": str(r.qty_countertop_pcs or 0),
            "edge": bool(r.countertop_edge_present),
            "driver_name":  r.driver_name  or "",
            "driver_phone": r.driver_phone or "",
            "signature_url": sig_url,
        })

    return JsonResponse({
        "order_id": order.id,
        "order_number": order.order_number,
        "receipts": items,
    })
    

def warehouse_order_pdf(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    receipts = (WarehouseReceipt.objects
                .filter(order=order, status="accepted")
                .order_by("received_at"))

    if not receipts.exists():
        # Можно отдать пустой PDF или 404 — выберем аккуратный PDF с пометкой
        pass

    # ---------- ШРИФТЫ ----------
    # Попробуем зарегистрировать DejaVu, если не зарегистрирован
    registered_fonts = set(pdfmetrics.getRegisteredFontNames())
    
    # ---------- ШРИФТЫ: ищем проектные, иначе системные Arial ----------
    def first_existing(paths):
        for p in paths:
            if p and os.path.exists(p):
                return p
        return None
    
    font_reg = first_existing([
        os.path.join(settings.BASE_DIR, "static", "fonts", "DejaVuSans.ttf"),
        os.path.join(settings.BASE_DIR, "core", "static", "fonts", "DejaVuSans.ttf"),
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\ARIAL.TTF",
    ])
    font_bld = first_existing([
        os.path.join(settings.BASE_DIR, "static", "fonts", "DejaVuSans-Bold.ttf"),
        os.path.join(settings.BASE_DIR, "core", "static", "fonts", "DejaVuSans-Bold.ttf"),
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\ARIALBD.TTF",
    ])
    
    APP_REG = "AppSans"
    APP_BLD = "AppSans-Bold"
    if not font_reg or not font_bld:
        raise RuntimeError("Не найдены TTF шрифты для PDF. Проверь пути DejaVuSans/Arial.")
    
    if APP_REG not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(APP_REG, font_reg))
    if APP_BLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(APP_BLD, font_bld))
    registerFontFamily("AppSans", normal=APP_REG, bold=APP_BLD, italic=APP_REG, boldItalic=APP_BLD)
    
    
    # ---------- СТИЛИ ----------
    styles = getSampleStyleSheet()

    def PStyle(name, **kw):
        base = styles["Normal"]
        kw.setdefault("fontSize", 10)
        kw.setdefault("leading", 13)
        kw["name"] = name
        kw["parent"] = base
        kw["fontName"] = APP_REG
        return ParagraphStyle(**kw)
    
    # цвета (нейтральные, «журнальные»)
    C_BG_HEADER = colors.HexColor("#f3f4f6")  # светлый фон шапки
    C_BG_ZEBRA1 = colors.white
    C_BG_ZEBRA2 = colors.HexColor("#fafafa")
    C_GRID      = colors.HexColor("#e5e7eb")
    C_MUTED     = colors.HexColor("#6b7280")
    C_TEXT      = colors.HexColor("#111827")
    
    st_title   = PStyle("Title",  fontSize=15, leading=19)
    st_muted   = PStyle("Muted",  textColor=C_MUTED)
    st_bold    = ParagraphStyle("Bold", parent=styles["Normal"], fontName=APP_BLD, fontSize=10, leading=13, textColor=C_TEXT)
    st_small   = PStyle("Small",      fontSize=9,  leading=11)
    st_small_m = PStyle("SmallMuted", fontSize=9,  leading=11, textColor=C_MUTED)
    st_th      = ParagraphStyle("TH", parent=styles["Normal"], fontName=APP_BLD, fontSize=9.5, leading=11, textColor=C_TEXT)
    st_cell    = ParagraphStyle("TD", parent=styles["Normal"], fontName=APP_REG, fontSize=10,  leading=13, textColor=C_TEXT)

    # ---------- Подсчёты ----------
    agg = receipts.aggregate(
        ldsp_2750=Sum("qty_ldsp_2750x1830"),
        ldsp_2800=Sum("qty_ldsp_2800x2070"),
        pvc_narrow_m=Sum("qty_pvc_narrow_m"),
        pvc_wide_m=Sum("qty_pvc_wide_m"),
        hdf=Sum("qty_hdf_sheets"),
        counter=Sum("qty_countertop_pcs"),
    )
    for k in list(agg.keys()):
        agg[k] = agg[k] or 0
    agg["ldsp_total"] = (agg["ldsp_2750"] or 0) + (agg["ldsp_2800"] or 0)

    def fmt(x):
        try:
            d = Decimal(str(x or 0))
            s = f"{d:.2f}".rstrip("0").rstrip(".")
            return s or "0"
        except Exception:
            return str(x or 0)

    # ---------- Документ ----------
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm,
        topMargin=16*mm, bottomMargin=16*mm,
        title=f"Журнал регистрации — заказ №{order.order_number}",
    )
    story = []
    
    # ---------- ШАПКА С ЛОГОТИПОМ ----------
    # логотип ищем через staticfiles
    logo_path = finders.find("img/logo.png") or first_existing([
        os.path.join(settings.BASE_DIR, "static", "img", "logo.png"),
        os.path.join(settings.BASE_DIR, "core", "static", "img", "logo.png"),
    ])
    left = []
    if logo_path and os.path.exists(logo_path):
        left = [Image(logo_path, width=34*mm, height=10*mm, hAlign="LEFT")]
    else:
        left = [Paragraph("<b>Журнал регистрации</b>", st_title)]
    
    right = [
        Paragraph("Журнал регистрации — приёмка на склад", st_title),
        Spacer(1, 2),
        Paragraph(
            f'Отчёт по заказу <b>№ {order.order_number}</b><br/>'
            f'<font color="#6b7280">Сформировано: {timezone.localtime():%d.%m.%Y %H:%M}</font>',
            st_cell
        ),
    ]
    head_tbl = Table([[left, right]], colWidths=[40*mm, None])
    head_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
    ]))
    story.append(head_tbl)
    story.append(Spacer(1, 6))

    
    



    # Клиент
    info_tbl = Table([
        [Paragraph("<b>Клиент</b>", st_cell),   Paragraph(order.customer_name or "—", st_cell)],
        [Paragraph("<b>Телефон</b>", st_cell),  Paragraph(order.phone or "—", st_cell)],
    ], colWidths=[30*mm, None])
    info_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), C_BG_HEADER),
        ("FONTNAME", (0,0), (0,-1), APP_BLD),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.25, C_GRID),
        ("LEFTPADDING",  (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING",   (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 8))

    # итоги
    story.append(Paragraph("Итоги по материалам", st_bold))
    
    th = lambda s: Paragraph(s, st_th)
    td = lambda s: Paragraph(s, st_cell)
    
    totals_data = [
        [th("ЛДСП 2750×1830"),
         th("ЛДСП 2800×2070"),
         th("ЛДСП (итого)"),
         th("ПВХ узкая"),
         th("ПВХ широкая"),
         th("ХДФ"),
         th("Столеш.")],
        [td(f"{agg['ldsp_2750']:.2f}".rstrip("0").rstrip(".")),
         td(f"{agg['ldsp_2800']:.2f}".rstrip("0").rstrip(".")),
         td(f"{agg['ldsp_total']:.2f}".rstrip("0").rstrip(".")),
         td(f"{agg['pvc_narrow_m']:.2f}".rstrip("0").rstrip(".")),
         td(f"{agg['pvc_wide_m']:.2f}".rstrip("0").rstrip(".")),
         td(f"{agg['hdf']:.2f}".rstrip("0").rstrip(".")),
         td(f"{agg['counter']:.2f}".rstrip("0").rstrip("."))]
    ]
    totals_tbl = Table(
        totals_data,
        colWidths=[32*mm, 32*mm, 30*mm, 28*mm, 28*mm, 26*mm, 28*mm]
    )
    totals_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), C_BG_HEADER),
        ("FONTNAME",   (0,0), (-1,0), APP_BLD),
        ("FONTNAME",   (0,1), (-1,-1), APP_REG),
        ("ALIGN",      (0,0), (-1,0), "CENTER"),
        ("ALIGN",      (0,1), (-1,-1), "RIGHT"),
        ("GRID",       (0,0), (-1,-1), 0.25, C_GRID),
        ("TOPPADDING",    (0,0), (-1,0), 6),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        ("TOPPADDING",    (0,1), (-1,-1), 5),
        ("BOTTOMPADDING", (0,1), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 10))


    # Завозы
    story.append(Paragraph("Завозы (принятые)", st_bold))
    story.append(Spacer(1, 4))
    
    # помощник: первое непустое поле
    def _first_attr(obj, names, default="—"):
        for n in names:
            if hasattr(obj, n):
                v = getattr(obj, n)
                if v not in (None, ""):
                    return str(v)
        return default
    
    for i, r in enumerate(receipts, start=1):
        hdr = f"Завоз № {i} — {r.received_at:%d.%m.%Y %H:%M}" if r.received_at else f"Завоз № {i}"
        story.append(Paragraph(hdr, st_small))
    
        row_data = [
            [th("ЛДСП 2750×1830"),
             th("ЛДСП 2800×2070"),
             th("ПВХ узк"),
             th("ПВХ шир"),
             th("ХДФ"),
             th("Столеш."),
             th("Статус")],
            [td(f"{(r.qty_ldsp_2750x1830 or 0):.2f}".rstrip("0").rstrip(".")),
             td(f"{(r.qty_ldsp_2800x2070 or 0):.2f}".rstrip("0").rstrip(".")),
             td(f"{(r.qty_pvc_narrow_m   or 0):.2f}".rstrip("0").rstrip(".")),
             td(f"{(r.qty_pvc_wide_m     or 0):.2f}".rstrip("0").rstrip(".")),
             td(f"{(r.qty_hdf_sheets     or 0):.2f}".rstrip("0").rstrip(".")),
             td(f"{(r.qty_countertop_pcs or 0):.2f}".rstrip("0").rstrip(".")),
             td(getattr(r, "get_status_display", lambda: r.status)())],
        ]
        row_tbl = Table(row_data, colWidths=[32*mm, 32*mm, 28*mm, 28*mm, 26*mm, 28*mm, 28*mm])
        row_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), C_BG_HEADER),
            ("FONTNAME",   (0,0), (-1,0), APP_BLD),
            ("FONTNAME",   (0,1), (-1,-1), APP_REG),
            ("ALIGN",      (0,0), (-1,0), "CENTER"),
            ("ALIGN",      (0,1), (-1,-1), "RIGHT"),
            ("ALIGN",      (-1,1), (-1,-1), "LEFT"),  # колонку «Статус» влево
            ("GRID",       (0,0), (-1,-1), 0.25, C_GRID),
            ("TOPPADDING",    (0,0), (-1,0), 5),
            ("BOTTOMPADDING", (0,0), (-1,0), 5),
            ("TOPPADDING",    (0,1), (-1,-1), 4),
            ("BOTTOMPADDING", (0,1), (-1,-1), 4),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("RIGHTPADDING",  (0,0), (-1,-1), 6),
            # зебра для тела (тут всего 1 строка — на будущее, если будет несколько)
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_BG_ZEBRA1, C_BG_ZEBRA2]),
        ]))
        story.append(row_tbl)
    
        # подпись + мета
        sign_img = None
        try:
            path = None
            if getattr(r, "signature", None):
                path = getattr(r.signature, "path", None)
                if not path and isinstance(r.signature, str):
                    path = os.path.join(settings.MEDIA_ROOT, r.signature.lstrip("/\\"))
            if path and os.path.exists(path):
                sign_img = Image(path, width=72*mm, height=26*mm)
        except Exception:
            sign_img = None
    
        meta_lines = [
            f"<b>Водитель:</b> {getattr(r, 'driver_name', '') or '—'}",
            f"<b>Телефон:</b> {getattr(r, 'driver_phone', '') or '—'}",
            f"<b>Комментарий:</b> " + _first_attr(r, ["comment", "note", "notes", "description", "driver_comment"], "—"),
        ]
        meta_par = Paragraph("<br/>".join(meta_lines), st_small_m)
    
        sig_tbl = Table([[sign_img or Paragraph("Подпись не приложена", st_small_m), meta_par]],
                        colWidths=[78*mm, None])
        sig_tbl.setStyle(TableStyle([
            ("BOX", (0,0), (0,0), 0.25, C_GRID),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING",  (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING",   (0,0), (-1,-1), 6),
            ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ]))
        story.append(sig_tbl)
        story.append(Spacer(1, 10))


    # ---------- Сборка ----------
    doc.build(story)

    pdf = buf.getvalue()
    buf.close()
    filename = f"order-{order.order_number}-warehouse.pdf"
    resp = HttpResponse(pdf, content_type="application/pdf")
    # attachment — сразу скачивание; если хочешь открывать во вкладке — поменяй на inline
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


    
    
    
    
def _sum_accepted_receipts(order):
    """Суммарные фактически принятые количества по заказу (только status='accepted')."""
    D = Decimal
    totals = {
        "ldsp": D("0.00"),
        "pvc_narrow": D("0.00"),
        "pvc_wide": D("0.00"),
        "hdf": D("0.00"),
        "countertop": D("0.00"),
    }
    for r in order.warehouse_receipts.filter(status="accepted"):
        totals["ldsp"]        += (r.qty_ldsp_2750x1830 or D("0")) + (r.qty_ldsp_2800x2070 or D("0"))
        totals["pvc_narrow"]  += (r.qty_pvc_narrow_m   or D("0"))
        totals["pvc_wide"]    += (r.qty_pvc_wide_m     or D("0"))
        totals["hdf"]         += (r.qty_hdf_sheets     or D("0"))
        totals["countertop"]  += (r.qty_countertop_pcs or D("0"))
    # двухзнаковое отображение
    for k, v in totals.items():
        totals[k] = D(str(v)).quantize(D("0.00"))
    return totals
    
# Раздельные суммы по форматам ЛДСП из принятых приёмок
def _sum_accepted_receipts_split(order):
    D = Decimal
    totals = {
        "ldsp_2750": D("0.00"),
        "ldsp_2800": D("0.00"),
        "pvc_narrow": D("0.00"),
        "pvc_wide": D("0.00"),
        "hdf": D("0.00"),
        "countertop": D("0.00"),
    }
    for r in order.warehouse_receipts.filter(status="accepted"):
        totals["ldsp_2750"]  += (r.qty_ldsp_2750x1830 or D("0"))
        totals["ldsp_2800"]  += (r.qty_ldsp_2800x2070 or D("0"))
        totals["pvc_narrow"] += (r.qty_pvc_narrow_m   or D("0"))
        totals["pvc_wide"]   += (r.qty_pvc_wide_m     or D("0"))
        totals["hdf"]        += (r.qty_hdf_sheets     or D("0"))
        totals["countertop"] += (r.qty_countertop_pcs or D("0"))
    # округление до 2 знаков для единообразия
    for k, v in totals.items():
        totals[k] = D(str(v)).quantize(D("0.00"))
    return totals
    
def _is_empty_draft_receipt(wr):
    D = Decimal
    return (
        (wr.qty_ldsp_2750x1830 or D("0")) == 0 and
        (wr.qty_ldsp_2800x2070 or D("0")) == 0 and
        (wr.qty_pvc_narrow_m   or D("0")) == 0 and
        (wr.qty_pvc_wide_m     or D("0")) == 0 and
        (wr.qty_hdf_sheets     or D("0")) == 0 and
        (wr.qty_countertop_pcs or D("0")) == 0 and
        not wr.signature and
        not (wr.driver_name or "").strip() and
        not (wr.driver_phone or "").strip()
    )
    
    
    
#--------<Быстрый Расчёт>--------#
# ===== Быстрый расчёт =====





from math import ceil
from django.shortcuts import get_object_or_404, render, redirect
from .models import PriceGroup, PriceItem, QuickQuote, QuickQuoteFacade

@login_required
def quick_quote(request):
    # гарантируем наличие группы и дефолтных позиций
    try:
        _ensure_quick_calc_group()
    except Exception:
        pass

    # фасады из двух групп (как в «Расчёт»)
    facade_options = list(
        PriceItem.objects.filter(
            group__title__in=["Фасады (краска)", "Фасады (плёнка)"]
        ).order_by("group__sort_order", "id").values("id", "title", "group__title")
    )

    category = (request.GET.get("tab") or "kitchen")
    context = {
        "facade_options": facade_options,
        "category": (request.GET.get("tab") or "kitchen"),
        "result": None,
        "phone": "",
        "tabs": ["wardrobe", "closet", "misc"],  # список вкладок кроме Кухни
    }

    if request.method == "POST":
        category = (request.POST.get("category") or "kitchen").strip()
        phone = (request.POST.get("phone") or "").strip()
        if not phone:
            messages.error(request, "Укажите номер телефона.")
            return render(request, "quick_quote.html", context | {"category": category, "phone": phone})

        # кол-ва
        def _dec2(v):
            try:
                return _dec(v).quantize(Decimal("0.01"))
            except Exception:
                return Decimal("0.00")

        qty_ldsp = _dec2(request.POST.get("qty_ldsp"))
        qty_hdf = _dec2(request.POST.get("qty_hdf"))
        qty_ctp = _dec2(request.POST.get("qty_countertops"))

        # фасады
        f_ids = request.POST.getlist("facade_item_id[]")
        f_area = request.POST.getlist("facade_area[]")
        fac_rows = []
        total_area = Decimal("0")
        for fid, ar in zip(f_ids, f_area):
            try:
                pi = PriceItem.objects.get(pk=int(fid))
            except Exception:
                continue
            area = _dec2(ar)
            if area <= 0:
                continue
            cost = (area * _dec(pi.value)).quantize(Decimal("0.01"))
            fac_rows.append({"id": pi.id, "title": pi.title, "area": area, "cost": cost})
            total_area += area

        facade_sheets = int(ceil(float(total_area / Decimal("5")))) if total_area > 0 else 0

        # тарифы бухгалтерии
        price_raspil = _get_price("Распил")
        price_prisadka = _get_price("Присадка")
        price_pvh = _get_price("ПВХ узкая")
        price_ctp_raspil = _get_price("Столешница распил")

        # нормы/закуп из новой группы
        consts = {}

        grp = PriceGroup.objects.filter(title__iexact="Быстрый расчёт — параметры").first()
        if grp:
            for it in grp.items.all():
                # важно: у PriceItem поле value (Decimal/число)
                try:
                    consts[it.title] = Decimal(str(it.value))
                except Exception:
                    pass
        
        def C(key: str, default):
            # универсальный геттер константы с дефолтом
            try:
                return Decimal(str(consts.get(key, default)))
            except Exception:
                return Decimal(str(default))
        
        # Норма ПВХ (м/лист) по категории — тянем из группы
        pvc_norm = {
            "kitchen":  C("ПВХ_Кухня (м/лист)",   40),
            "wardrobe": C("ПВХ_Шкаф (м/лист)",    25),
            "closet":   C("ПВХ_Гардероб (м/лист)",25),
            "misc":     C("ПВХ_Разное (м/лист)",  30),
        }[category]
        
        # Фурнитура min/max по категории — тоже из группы
        furn_min = {
            "kitchen":  C("Кухня_min (тг/лист)",     5000),
            "wardrobe": C("Шкафы_min (тг/лист)",     4900),
            "closet":   C("Гардероб_min (тг/лист)",  2500),
            "misc":     C("Разное_min (тг/лист)",    2500),
        }[category]
        
        furn_max = {
            "kitchen":  C("Кухня_max (тг/лист)",     7500),
            "wardrobe": C("Шкафы_max (тг/лист)",     6490),
            "closet":   C("Гардероб_max (тг/лист)",  6490),
            "misc":     C("Разное_max (тг/лист)",    7500),
        }[category]
        
        # Закупочные цены материалов
        price_ldsp_sheet = C("Лист_ЛДСП (тг/лист)", 15000)
        price_hdf_sheet  = C("Лист_ХДФ (тг/лист)",   7000)
        price_ctp_sheet  = C("Столешница (тг/шт)",  40000)
        price_pvh_meter_buy = C("ПВХ тг/м", 0)
        

        # 1) обработка
        qty_ldsp_eff = (qty_ldsp + Decimal(str(facade_sheets)))
        amt_processing = (
            qty_ldsp_eff * (price_raspil + price_prisadka)
            + qty_hdf * price_raspil
            + qty_ctp * price_ctp_raspil
        ).quantize(Decimal("0.01"))

        # 2) пвх (узкая) — только по ЛДСП
        pvc_meters = (qty_ldsp * pvc_norm).quantize(Decimal("0.01"))
        amt_pvc = (pvc_meters * price_pvh).quantize(Decimal("0.01"))
        pvc_buy_cost = (pvc_meters * price_pvh_meter_buy).quantize(Decimal("0.01"))
        
        # объединяем услугу ПВХ с «Обработка материалов»
        amt_processing = (amt_processing + amt_pvc).quantize(Decimal("0.01"))
        
        # 3) фасады
        amt_facades = sum((r["cost"] for r in fac_rows), Decimal("0")).quantize(Decimal("0.01"))
        
        # 4) услуги: теперь это «обработка (уже с ПВХ-услугой) + фасады»
        amt_services_total = (amt_processing + amt_facades).quantize(Decimal("0.01"))


        # 5) материалы и фурнитура
        amt_materials = (
            qty_ldsp * price_ldsp_sheet
          + qty_hdf  * price_hdf_sheet
          + qty_ctp  * price_ctp_sheet
          + pvc_buy_cost
        ).quantize(Decimal("0.01"))
        fmin = ((qty_ldsp + Decimal(str(facade_sheets))) * furn_min).quantize(Decimal("0.01"))
        fmax = ((qty_ldsp + Decimal(str(facade_sheets))) * furn_max).quantize(Decimal("0.01"))
        favg = ((fmin + fmax) / Decimal("2")).quantize(Decimal("0.01"))
        amt_procure_total = (amt_materials + favg).quantize(Decimal("0.01"))
        grand_total = (amt_services_total + amt_procure_total).quantize(Decimal("0.01"))


        grand_total = (amt_services_total + amt_materials + favg).quantize(Decimal("0.01"))

        result = {
            "phone": phone,
            "category": category,
            "qty_ldsp": qty_ldsp,
            "qty_hdf": qty_hdf,
            "qty_countertops": qty_ctp,
            "facades": fac_rows,
            "facade_area_total": total_area,
            "facade_sheets": facade_sheets,
            "amt_processing": amt_processing,
            "amt_pvc": amt_pvc,
            "amt_facades": amt_facades,
            "amt_services_total": amt_services_total,
            "amt_materials": amt_materials,
            "furn_min": fmin,
            "furn_max": fmax,
            "furn_avg": favg,
            "furn_range": f"{fmin} — {fmax}",
            "grand_total": grand_total,
            "pvc_meters": pvc_meters,
            "pvc_norm": pvc_norm,
            "amt_procure_total": amt_procure_total,
            "price_snapshot": {
                "Распил": str(price_raspil),
                "Присадка": str(price_prisadka),
                "ПВХ узкая": str(price_pvh),
                "Столешница распил": str(price_ctp_raspil),
                "Нормы/закуп": {k: str(v) for k, v in consts.items()},
            },
        }

        # Сохранение в историю
        if request.POST.get("save") == "1":
            qq = QuickQuote.objects.create(
                phone=phone,
                category=category,
                qty_ldsp=qty_ldsp,
                qty_hdf=qty_hdf,
                qty_countertops=qty_ctp,
                price_snapshot=result["price_snapshot"],
                amt_processing=amt_processing,
                amt_pvc=amt_pvc,
                amt_facades=amt_facades,
                amt_services_total=amt_services_total,
                amt_materials=amt_materials,
                furn_min=fmin,
                furn_max=fmax,
                furn_avg=favg,
                grand_total=grand_total,
                created_by=request.user,
            )
            for r in fac_rows:
                QuickQuoteFacadeItem.objects.create(
                    quote=qq, price_item_id=r["id"], area=r["area"], cost=r["cost"]
                )
            messages.success(request, "Быстрый расчёт сохранён.")
            return redirect("quick_quote_detail", quote_id=qq.id)

        context.update({"result": result, "phone": phone, "category": category})
        return render(request, "quick_quote.html", context)

    return render(request, "quick_quote.html", context)


@login_required
def quick_quote_detail(request, quote_id: int):
    qq = get_object_or_404(QuickQuote.objects.select_related("created_by"), pk=quote_id)
    return render(request, "quick_quote_detail.html", {"qq": qq})


@login_required
def quick_quote_history(request):
    qs = QuickQuote.objects.all()
    phone = (request.GET.get("phone") or "").strip()
    if phone:
        qs = qs.filter(phone__icontains=phone)
    return render(request, "quick_quote_history.html", {"items": qs, "phone": phone})


@login_required
def quick_quote_pdf(request, quote_id: int):
    qq = get_object_or_404(QuickQuote, pk=quote_id)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=12 * mm, bottomMargin=12 * mm
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontName=PDF_FONT_BLD, fontSize=15, leading=18))
    styles.add(ParagraphStyle(name="P", fontName=PDF_FONT_REG, fontSize=10.5, leading=13))
    ACCENT = COMPANY_ORANGE

    story = []
    title = Paragraph(
        f"<font color='{ACCENT.hexval()}'>Быстрый расчёт</font> — {qq.get_category_display()}",
        styles["H1"],
    )
    sub = Paragraph(
        f"Телефон: <b>{qq.phone}</b>&nbsp;&nbsp;&nbsp;Дата: {localtime(qq.created_at).strftime('%d.%m.%Y %H:%M')}",
        styles["P"],
    )
    story += [title, sub, Spacer(1, 6 * mm)]

    # Количества
    info = Table(
        [["ЛДСП (листов)", f"{qq.qty_ldsp}"], ["ХДФ (листов)", f"{qq.qty_hdf}"], ["Столешницы (шт.)", f"{qq.qty_countertops}"]],
        colWidths=[60 * mm, 30 * mm],
    )
    info.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), PDF_FONT_REG, 10.5), ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    story += [info, Spacer(1, 4 * mm)]

    # Фасады
    if qq.facades.exists():
        rows = [["Фасады", "Площадь, м²", "Сумма"]]
        total_area = Decimal("0")
        for fi in qq.facades.select_related("price_item").all():
            rows.append([fi.price_item.title, f"{fi.area}", f"{fi.cost}"])
            total_area += fi.area
        rows.append(["Итого", f"{total_area}", f"{qq.amt_facades}"])
        t = Table(rows, colWidths=[0.55 * doc.width, 0.2 * doc.width, 0.25 * doc.width], hAlign="LEFT")
        t.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, 0), PDF_FONT_BLD, 10.5),
                    ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                    ("ALIGN", (1, 1), (2, -1), "RIGHT"),
                    ("FONT", (0, 1), (-1, -1), PDF_FONT_REG, 10),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.grey),
                ]
            )
        )
        story += [t, Spacer(1, 4 * mm)]

    # Итоги
    tot = Table(
        [
            ["Обработка материалов", f"{qq.amt_processing}"],
            ["ПВХ (узкая)", f"{qq.amt_pvc}"],
            ["Фасады", f"{qq.amt_facades}"],
            ["Сумма закупа (материалы)", f"{qq.amt_materials}"],
            ["Фурнитура min / max / avg", f"{qq.furn_min} / {qq.furn_max} / {qq.furn_avg}"],
            ["ИТОГО", f"{qq.grand_total}"],
        ],
        colWidths=[0.55 * doc.width, 0.45 * doc.width],
        hAlign="LEFT",
    )
    tot.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -2), PDF_FONT_REG, 10.5),
                ("FONT", (0, -1), (-1, -1), PDF_FONT_BLD, 12),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 1.0, ACCENT),
            ]
        )
    )
    story.append(tot)

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    resp = HttpResponse(pdf, content_type="application/pdf")
    fname_display = f"Быстрый расчёт — {qq.get_category_display()} — {qq.phone}.pdf"
    fname_ascii = f"quick_quote_{qq.id}.pdf"
    resp["Content-Disposition"] = f'attachment; filename="{fname_ascii}"; filename*=UTF-8\'\'{quote(fname_display)}'
    return resp


@require_POST
def order_update_field(request, pk, field):
    """
    Обновление одного текстового поля заказа (имя, фамилия, ИИН, телефон).
    Ожидает POST с полем 'value'.
    Возвращает JSON: {"status": "ok", "value": "<новое_значение>"} либо 400.
    """
    # Разрешаем менять только эти поля:
    allowed_fields = {"customer_name", "last_name", "iin", "phone"}
    if field not in allowed_fields:
        return HttpResponseBadRequest("Нельзя редактировать это поле")

    order = get_object_or_404(Order, pk=pk)
    new_value = (request.POST.get("value") or "").strip()

    # Обновляем поле
    setattr(order, field, new_value)

    # Если меняем телефон и стоит флаг has_whatsapp, синхронизируем whatsapp_phone
    update_fields = [field]
    if field == "phone" and order.has_whatsapp:
        order.whatsapp_phone = new_value
        update_fields.append("whatsapp_phone")

    order.save(update_fields=update_fields)

    return JsonResponse({"status": "ok", "value": new_value})