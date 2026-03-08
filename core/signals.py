from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from django.conf import settings

# Импортируйте вашу фактическую модель заказа
try:
    from core.models import Order
except Exception:
    raise

from whatsapp.utils import to_e164
from whatsapp.services import send_template_ext, is_configured

DEFAULT_MANAGER_RAW = "+787016588859"

def get_lang():
    return getattr(settings, "WHATSAPP_LANG", "ru")

def get_manager_numbers():
    raw = getattr(settings, "WHATSAPP_MANAGER_NUMBERS", [])
    if isinstance(raw, (list, tuple)) and raw:
        return list(raw)
    import os
    env = os.getenv("WHATSAPP_MANAGER_NUMBERS", "").strip()
    nums = [x.strip() for x in env.split(",") if x.strip()]
    if nums:
        return nums
    return [DEFAULT_MANAGER_RAW]

def _get_order_number(order):
    # Берём именно «№ заказа», НЕ id.
    # Поддерживаем распространённые варианты полей:
    candidates = (
        "number", "order_number", "order_no", "orderNum",
        "doc_number", "doc_no", "code"
    )
    for name in candidates:
        val = getattr(order, name, None)
        if val not in (None, ""):
            return str(val)
    # Если поля нет — лучше отправить пустую «—», чем id
    return "—"

def _build_vars(order):
    # Шаблон manager_order_created ожидает ОДНУ переменную: {{1}} — № заказа
    order_no = _get_order_number(order)
    return [order_no]

@receiver(post_save, sender=Order)
def notify_manager_on_order_created(sender, instance, created, **kwargs):
    if not created:
        return
    if not is_configured():
        return

    managers = get_manager_numbers() or [DEFAULT_MANAGER_RAW]
    body_vars = _build_vars(instance)
    lang = get_lang()

    def _send():
        for raw in managers:
            to_value = to_e164(raw, allow_bypass=True)
            send_template_ext(
                to_value=to_value,
                template_name="manager_order_created",
                lang=lang,
                body_vars=body_vars
            )
    transaction.on_commit(_send)
