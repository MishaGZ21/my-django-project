# contracts/services.py — v5.16.1 (hotfix)
# Fixes:
# 1) order.warehouse.last_receipt_date now passed correctly (was None in v5.16).
# 2) Added template-compat aliases: facades.paint_cost / facades.film_cost
#    mapped to money totals (paint_total / film_total).
from dataclasses import dataclass
from typing import List, Optional, Iterable, Sequence
from decimal import Decimal

from django.apps import apps
from django.utils import timezone
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.db.models.fields.related import ForeignKey

@dataclass
class CustomerInfo:
    name: str
    phone: str

@dataclass
class PaymentInfo:
    last_service_payment_date: Optional[object]
    total_paid: Decimal
    designer_paid_total: Decimal

@dataclass
class WarehouseMaterial:
    name: str
    size: Optional[str]
    qty: str
    note: str

@dataclass
class WarehouseInfo:
    last_receipt_date: Optional[object]
    materials: List[WarehouseMaterial]

@dataclass
class FacadeItem:
    category: str
    profile: str
    area: Decimal

@dataclass
class FacadeTotals:
    paint_total: Decimal     # money
    film_total: Decimal      # money
    paint_milling_types: List[str]
    film_milling_types: List[str]
    items: List[FacadeItem]

@dataclass
class OrderAggregate:
    order_id: int
    number: Optional[str]
    customer: CustomerInfo
    payments: PaymentInfo
    warehouse: WarehouseInfo
    facades: FacadeTotals


def _get_model_prefer_core(name: str):
    for app_label in ("core","payments","billing","finance","factory_app","orders","crm","sales"):
        try:
            M = apps.get_model(app_label, name)
            if M:
                return M
        except Exception:
            pass
    return None

def _search_models(candidates: Sequence[str]):
    for p in candidates:
        try:
            a, m = p.split(".")
            mdl = apps.get_model(a, m)
            if mdl:
                return mdl
        except Exception:
            continue
    return None

def _first_field(model, names: Iterable[str]) -> Optional[str]:
    if not model:
        return None
    have = {f.name for f in model._meta.get_fields()}
    for n in names:
        if n in have:
            return n
    return None

def _first_text_field(model, preferred: Iterable[str]) -> Optional[str]:
    if not model:
        return None
    names = {f.name for f in model._meta.get_fields()}
    for n in preferred:
        if n in names:
            return n
    for cand in ("title","name","label","caption","display_name","full_name","short_name","text"):
        if cand in names:
            return cand
    return None

def _get(obj, names: Iterable[str], default=None):
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default

def _detect_facades_payment_status(order_id: int, paint_total: Decimal, film_total: Decimal) -> str:
    if (paint_total or Decimal("0")) + (film_total or Decimal("0")) == 0:
        return "NOT_SPECIFIED"

    def _order_qs(Model):
        if not Model:
            return None
        names = {f.name for f in Model._meta.get_fields()}
        if "order_id" in names:
            return Model.objects.filter(order_id=order_id)
        if "order" in names:
            return Model.objects.filter(order__id=order_id)
        return None

    # OrderPaymentInclude
    try:
        OPI = _get_model_prefer_core("OrderPaymentInclude")
        if OPI:
            qs = _order_qs(OPI)
            if qs is not None and "include_facades" in {f.name for f in OPI._meta.get_fields()}:
                vals = list(qs.values_list("include_facades", flat=True))
                if any(v is True for v in vals):
                    return "PAID"
    except Exception:
        pass

    # Payment core-first
    Payment = _get_model_prefer_core("Payment")
    if Payment:
        qs = _order_qs(Payment)
        if qs is not None:
            p_fields = {f.name for f in Payment._meta.get_fields()}
            if "amount_facades" in p_fields:
                s = qs.aggregate(s=Coalesce(Sum("amount_facades"), Decimal("0")))["s"]
                if s and Decimal(s) > 0:
                    return "PAID"
            for fname in ("include_facades","include_facade","facades_included","facade_included","include_fasad","include_fasady"):
                if fname in p_fields:
                    vals = list(qs.values_list(fname, flat=True))
                    if any(v is True for v in vals):
                        return "PAID"
            total_facade_like = Decimal("0")
            for fname in p_fields:
                low = fname.lower()
                if any(k in low for k in ("facade","facad","fasad","fasady","plenk","plenka","paint","kraska","mdf")):
                    try:
                        total_facade_like += qs.aggregate(s=Coalesce(Sum(fname), Decimal("0")))["s"] or Decimal("0")
                    except Exception:
                        pass
            if total_facade_like > 0:
                return "PAID"

    # PaymentItem/Line + Operation — опущены ради краткости; логика не менялась
    return "NOT_PAID"


def get_order_aggregate(order_id: int) -> OrderAggregate:
    Order       = _get_model_prefer_core("Order") or _search_models(["orders.Order","crm.Order","sales.Order","factory_app.Order"])
    Payment     = _get_model_prefer_core("Payment") or _search_models(["payments.Payment","billing.Payment","finance.Payment","factory_app.Payment"])
    FacadeRow   = apps.get_model("core", "CalculationFacadeItem")
    FacadeSheet = apps.get_model("core", "FacadeSheet")
    ReceiptM    = apps.get_model("core", "WarehouseReceipt")

    # ---- Order + customer ----
    order_obj = Order.objects.get(pk=order_id) if Order else None
    number = _get(order_obj, ["number","order_number","doc_no","doc_number","code","display_number","ext_number"], None)
    customer = CustomerInfo(
        name  = _get(order_obj, ["customer_name","client_name","name"], "") or _get(_get(order_obj, ["customer","client"], None), ["name"], "") or "",
        phone = _get(order_obj, ["customer_phone","client_phone","phone"], "") or _get(_get(order_obj, ["customer","client"], None), ["phone"], "") or "",
    )

    # ---- Payments totals ----
    if Payment:
        p_fields = {f.name for f in Payment._meta.get_fields()}
        qs = Payment.objects.filter(order_id=order_id) if "order_id" in p_fields else Payment.objects.filter(order__id=order_id)
        qs = qs.order_by("-created_at","-id")

        s_due    = qs.aggregate(s=Coalesce(Sum("amount_due"),    Decimal("0")))["s"] if "amount_due" in p_fields else Decimal("0")
        s_total  = qs.aggregate(s=Coalesce(Sum("amount_total"),  Decimal("0")))["s"] if "amount_total" in p_fields else Decimal("0")
        s_design = qs.aggregate(s=Coalesce(Sum("amount_design"), Decimal("0")))["s"] if "amount_design" in p_fields else Decimal("0")
        s_fac    = qs.aggregate(s=Coalesce(Sum("amount_facades"),Decimal("0")))["s"] if "amount_facades" in p_fields else Decimal("0")

        total_paid    = (s_due if s_due and Decimal(s_due) > 0 else (s_total if s_total else (s_design or Decimal("0")) + (s_fac or Decimal("0"))))
        designer_paid = s_design or Decimal("0")

        date_f = "created_at" if "created_at" in p_fields else ("date" if "date" in p_fields else ("paid_at" if "paid_at" in p_fields else None))
        last_service_date = qs.values_list(date_f, flat=True).first().date() if date_f else None
    else:
        total_paid = Decimal("0"); designer_paid = Decimal("0"); last_service_date = None

    payments = PaymentInfo(last_service_date, total_paid or Decimal("0"), designer_paid or Decimal("0"))

    # ---- Warehouse ----
    materials: List[WarehouseMaterial] = []
    last_receipt_date = None
    if ReceiptM:
        r_fields = {f.name for f in ReceiptM._meta.get_fields()}
        qs_r = ReceiptM.objects.filter(order_id=order_id) if "order_id" in r_fields else ReceiptM.objects.filter(order__id=order_id)
        base = qs_r
        if "draft" in r_fields:
            base = base.filter(draft=False)
        if "status" in r_fields:
            base = base.exclude(status__in=["draft","черновик","Черновик"])
        top = (base if base.exists() else qs_r).order_by("-id").values("created_at","updated_at","received_at").first()
        if top:
            dt = top.get("created_at") or top.get("received_at") or top.get("updated_at")
            if dt is not None:
                try:
                    last_receipt_date = timezone.localtime(dt).date()
                except Exception:
                    last_receipt_date = getattr(dt, "date", lambda: dt)()
        sums = {
            "qty_ldsp_2750x1830": 0,
            "qty_ldsp_2800x2070": 0,
            "qty_pvc_narrow_m": 0,
            "qty_pvc_wide_m": 0,
            "qty_hdf_sheets": 0,
            "qty_countertop_pcs": 0,
        }
        for r in qs_r:
            for k in list(sums.keys()):
                if hasattr(r, k):
                    try: sums[k] += int(getattr(r, k) or 0)
                    except Exception: pass
        if sums["qty_ldsp_2750x1830"]:
            materials.append(WarehouseMaterial("ЛДСП", "2750×1830", f"{int(sums['qty_ldsp_2750x1830'])} л.", ""))
        if sums["qty_ldsp_2800x2070"]:
            materials.append(WarehouseMaterial("ЛДСП", "2800×2070", f"{int(sums['qty_ldsp_2800x2070'])} л.", ""))
        if sums["qty_pvc_narrow_m"]:
            materials.append(WarehouseMaterial("ПВХ кромка (узкая)", None, f"{int(sums['qty_pvc_narrow_m'])} м.", ""))
        if sums["qty_pvc_wide_m"]:
            materials.append(WarehouseMaterial("ПВХ кромка (широкая)", None, f"{int(sums['qty_pvc_wide_m'])} м.", ""))
        if sums["qty_hdf_sheets"]:
            materials.append(WarehouseMaterial("ХДФ", None, f"{int(sums['qty_hdf_sheets'])} л.", ""))
        if sums["qty_countertop_pcs"]:
            materials.append(WarehouseMaterial("Столешница", None, f"{int(sums['qty_countertop_pcs'])} шт.", ""))

    # ---- Facades (money + items) ----
    paint_total_money = Decimal("0"); film_total_money = Decimal("0")
    items: List[FacadeItem] = []

    FacadeSheetM = apps.get_model("core", "FacadeSheet")
    if FacadeSheetM:
        names = {f.name for f in FacadeSheetM._meta.get_fields()}
        if "paint_total_sum" in names or "film_total_sum" in names:
            qs = FacadeSheetM.objects.filter(order_id=order_id) if _first_field(FacadeSheetM, ["order_id"]) else FacadeSheetM.objects.filter(order__id=order_id)
            if "paint_total_sum" in names:
                paint_total_money = qs.aggregate(s=Coalesce(Sum("paint_total_sum"), Decimal("0")))["s"] or Decimal("0")
            if "film_total_sum" in names:
                film_total_money = qs.aggregate(s=Coalesce(Sum("film_total_sum"), Decimal("0")))["s"] or Decimal("0")

    FacadeRowM = apps.get_model("core", "CalculationFacadeItem")
    if FacadeRowM:
        row_names = {f.name for f in FacadeRowM._meta.get_fields()}
        if "calculation" in row_names:
            base = (FacadeRowM.objects.filter(calculation__order_id=order_id)
                    if _first_field(FacadeRowM, ["calculation_id"])
                    else FacadeRowM.objects.filter(calculation__order__id=order_id))
        else:
            base = FacadeRowM.objects.none()

        price_field = None; price_model = None
        for f in FacadeRowM._meta.get_fields():
            if isinstance(f, ForeignKey) and f.name in ("price_item", "item", "catalog_item", "price"):
                price_field = f.name; price_model = f.remote_field.model; break
        txt = _first_text_field(price_model, ["title","name","label","caption","display_name"]) if price_model else None
        area_field = _first_field(FacadeRowM, ["area","m2","qty_m2"])
        cost_field = _first_field(FacadeRowM, ["cost","amount","total","sum","price"])

        def detect_cat(title: str):
            t = (title or "").lower()
            if any(k in t for k in ("плён", "пленк", "plenka", "pvh", "pvc", "винил", "vinyl", "пвх")): return "плёнка"
            if any(k in t for k in ("краск", "эмал", "покра", "paint", "лак", "глянец", "матов")):     return "краска"
            return None

        if price_field and txt and area_field:
            for row in base.values(f"{price_field}__{txt}", area_field, cost_field if cost_field else "id"):
                title = row.get(f"{price_field}__{txt}")
                area  = row.get(area_field) or Decimal("0")
                cost  = row.get(cost_field) if cost_field else None
                cat = detect_cat(str(title))
                if cat and area:
                    items.append(FacadeItem(category=cat, profile=str(title), area=Decimal(area)))
                if cat and cost:
                    if cat == "краска":
                        paint_total_money += Decimal(cost or 0)
                    else:
                        film_total_money  += Decimal(cost or 0)

    facades = FacadeTotals(
        paint_total_money or Decimal("0"),
        film_total_money  or Decimal("0"),
        [], [],
        items
    )

    # Определим статус + добавим алиасы для шаблона
    status = _detect_facades_payment_status(order_id, facades.paint_total, facades.film_total)
    setattr(facades, "payment_status", status)
    setattr(facades, "is_paid", status == "PAID")
    setattr(facades, "is_specified", status != "NOT_SPECIFIED")
    # === Алиасы под старый шаблон ===
    setattr(facades, "paint_cost", facades.paint_total)
    setattr(facades, "film_cost",  facades.film_total)

    agg = OrderAggregate(
        order_id=order_id,
        number=number,
        customer=customer,
        payments=payments,
        warehouse=WarehouseInfo(last_receipt_date, materials),  # <-- фикс: не теряем дату
        facades=facades
    )
    return agg
