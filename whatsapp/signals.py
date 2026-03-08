from decimal import Decimal
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db.models import Sum
from core.models import Order, Invoice, CalculationFacadeItem
from .services import send_template, is_configured
from .utils import to_e164
from .helpers import get_manager_numbers, get_template_name, get_lang

@receiver(post_save, sender=Order)
def notify_manager_order_created(sender, instance: Order, created: bool, **kwargs):
    if not created or not is_configured():
        return
    calc = getattr(instance, "calculation", None)
    ldsp = getattr(calc, "qty_ldsp_total", 0) if calc else 0
    mdf_area = Decimal("0")
    if calc:
        mdf_area = (CalculationFacadeItem.objects.filter(calculation=calc)
                    .aggregate(total=Sum("area"))["total"] or Decimal("0"))

    tpl = get_template_name("manager_order_created")
    lang = get_lang()
    for raw in get_manager_numbers():
        to = to_e164(raw)
        if tpl and to:
            send_template(to, tpl, lang, [instance.order_number, ldsp, mdf_area])

@receiver(pre_save, sender=Invoice)
def _invoice_paid_flag_track(sender, instance: Invoice, **kwargs):
    if not instance.pk:
        instance._was_paid = False
        return
    try:
        old_paid = sender.objects.filter(pk=instance.pk).values_list("paid", flat=True).first()
        instance._was_paid = bool(old_paid)
    except Exception:
        instance._was_paid = False

@receiver(post_save, sender=Invoice)
def notify_on_payment(sender, instance: Invoice, created: bool, **kwargs):
    if not is_configured():
        return
    became_paid = False
    if created and instance.paid:
        became_paid = True
    elif (not created) and instance.paid and (not getattr(instance, "_was_paid", False)):
        became_paid = True
    if not became_paid:
        return

    order = instance.order
    amount = getattr(instance, "amount", None) or getattr(instance, "sum", None) or 0

    client_tpl = get_template_name("client_order_paid")
    client_to  = getattr(order, "whatsapp_phone", None) or getattr(order, "phone", None)
    if client_tpl and client_to:
        send_template(to_e164(client_to), client_tpl, get_lang(), [order.order_number])

    mgr_tpl = get_template_name("manager_payment")
    for raw in get_manager_numbers():
        to = to_e164(raw)
        if mgr_tpl and to:
            send_template(to, mgr_tpl, get_lang(), [order.order_number, amount])
