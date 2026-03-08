from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count
from django.urls import reverse
from .models import Payment
from .models import Contract, FacadeSheet, Invoice, Order, ProductionTask, PurchaseSheet
from .models import Calculation, CalculationFacadeItem
from .models import QuickQuote, QuickQuoteFacade

# Фильтр по способу оплаты для списка Заказов
class MethodFilter(admin.SimpleListFilter):
    title = "Способ оплаты"
    parameter_name = "method"

    def lookups(self, request, model_admin):
        return getattr(Payment, "METHODS", (("cash","Наличные"),("card","Карта"),("qr","QR")))

    def queryset(self, request, queryset):
        val = self.value()
        if not val:
            return queryset
        try:
            return queryset.filter(payments__methods__contains=[val]).distinct()
        except Exception:
            return queryset

# --- Чеки (proxy к Payment) ---
class Receipt(Payment):
    class Meta:
        proxy = True
        verbose_name = "Чек"
        verbose_name_plural = "Чеки"



class PurchaseSheetInline(admin.StackedInline):
    model = PurchaseSheet
    can_delete = False
    extra = 0

class FacadeSheetInline(admin.StackedInline):
    model = FacadeSheet
    can_delete = False
    extra = 0

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number", "customer_name", "status", "due_date",
        "has_purchase_sheet", "has_facade_sheet",
        "created_at",
    )
    list_filter = ("created_by", "created_at", MethodFilter)
    search_fields = ("customer_name", "item", "order_number", "phone")
    inlines = [PurchaseSheetInline, FacadeSheetInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Аннотируем наличие OneToOne связей, чтобы не ловить DoesNotExist в шаблонах/админке
        return qs.annotate(
            ps_count=Count("purchase_sheet"),
            fs_count=Count("facade_sheet"),
        )

    @admin.display(boolean=True, description="Лист закупа")
    def has_purchase_sheet(self, obj: Order):
        return getattr(obj, "ps_count", 0) > 0

    @admin.display(boolean=True, description="Facade sheet")
    def has_facade_sheet(self, obj: Order):
        return getattr(obj, "fs_count", 0) > 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "amount", "paid", "issued_at")
    list_filter = ("paid", "issued_at")


@admin.register(ProductionTask)
class ProductionTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "name", "assignee", "status", "updated_at")
    list_filter = ("status", "updated_at")


@admin.register(PurchaseSheet)
class PurchaseSheetAdmin(admin.ModelAdmin):
    list_display = ("order", "created_at",)
    search_fields = ("order__order_number", "order__customer_name")


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("order", "status", "due_date", "lds_count", "material_type", "facades_m2")
    list_filter = ("status", "material_type", "due_date")
    search_fields = ("order__order_number", "order__customer_name")


@admin.register(FacadeSheet)
class FacadeSheetAdmin(admin.ModelAdmin):
    list_display = ("order", "paint_total_sum", "film_total_sum", "created_at")
    search_fields = ("order__order_number", "order__customer_name")
    
    
class CalculationFacadeItemInline(admin.TabularInline):
    model = CalculationFacadeItem
    extra = 0

@admin.register(Calculation)
class CalculationAdmin(admin.ModelAdmin):
    inlines = [CalculationFacadeItemInline]

# --- Prices management (Accounting -> Prices) ---
from .models import PriceGroup, PriceItem

class PriceItemInline(admin.TabularInline):
    model = PriceItem
    extra = 0
    fields = ("title", "value")
    show_change_link = True

@admin.register(PriceGroup)
class PriceGroupAdmin(admin.ModelAdmin):
    list_display = ("title", "sort_order", "items_count")
    list_editable = ("sort_order",)
    search_fields = ("title",)
    ordering = ("sort_order", "id")
    inlines = [PriceItemInline]

    def items_count(self, obj):
        return obj.items.count()
    items_count.short_description = "Позиций"

@admin.register(PriceItem)
class PriceItemAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "value")
    list_filter = ("group",)
    search_fields = ("title",)
    autocomplete_fields = ("group",)
    ordering = ("group", "id")



@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = (
        "id", "order_link", "order_number", "customer",
        "amount_due", "amount_total", "amount_design",
        "methods_display", "created_by", "created_at", "receipt_pdf_link"
    )
    list_display_links = ("id", "order_link")
    search_fields = ("order__order_number", "order__customer_name", "order__phone", "created_by__username")
    list_filter = ("created_by", "created_at",)
    readonly_fields = ("order", "amount_total", "amount_design", "amount_due", "methods", "created_at", "created_by")

    @admin.display(description="Заказ", ordering="order__id")
    def order_link(self, obj):
        try:
            url = reverse("admin:core_order_change", args=[obj.order_id])
            return format_html('<a href="{}">#{}</a>', url, obj.order.order_number)
        except Exception:
            return f"#{getattr(obj.order, 'order_number', obj.order_id)}"

    @admin.display(description="№ заказа", ordering="order__order_number")
    def order_number(self, obj):
        return getattr(obj.order, "order_number", "-")

    @admin.display(description="Клиент / Телефон", ordering="order__customer_name")
    def customer(self, obj):
        if not getattr(obj, "order", None):
            return "-"
        name = getattr(obj.order, "customer_name", "-")
        phone = getattr(obj.order, "phone", "-")
        return f"{name} / {phone}"

    @admin.display(description="Способ оплаты")
    def methods_display(self, obj):
        labels = dict(getattr(Payment, "METHODS", ()))
        items = [labels.get(m, m) for m in (obj.methods or [])]
        return ", ".join(items) if items else "-"

    @admin.display(description="Чек (PDF)")
    def receipt_pdf_link(self, obj):
        try:
            url = reverse("payment_receipt", kwargs={"order_id": obj.order_id})
            return format_html('<a class="button" target="_blank" href="{}">PDF</a>', url)
        except Exception:
            return "-"


class QuickQuoteFacadeInline(admin.TabularInline):
    model = QuickQuoteFacade
    extra = 0

@admin.register(QuickQuote)
class QuickQuoteAdmin(admin.ModelAdmin):
    list_display  = ("created_at", "phone", "category", "grand_total")
    list_filter   = ("category",)
    search_fields = ("phone",)
    inlines       = [QuickQuoteFacadeInline]