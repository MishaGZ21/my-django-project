from django.conf import settings
from .models import WhatsAppSettings, WhatsAppTemplate

def get_manager_numbers() -> list[str]:
    s = WhatsAppSettings.get_solo()
    nums = s.manager_list()
    if nums:
        return nums
    return getattr(settings, "WHATSAPP_MANAGER_NUMBERS", [])

def get_lang() -> str:
    s = WhatsAppSettings.get_solo()
    return s.lang or getattr(settings, "WHATSAPP_LANG", "ru")

def get_template_name(key: str) -> str:
    s = WhatsAppSettings.get_solo()
    if s.use_db_templates:
        row = WhatsAppTemplate.objects.filter(key=key, active=True).first()
        if row and row.template_name:
            return row.template_name
    m = {
        "client_order_paid":      getattr(settings, "WHATSAPP_TPL_CLIENT_ORDER_PAID", ""),
        "manager_order_created":  getattr(settings, "WHATSAPP_TPL_MANAGER_ORDER_CREATED", ""),
        "manager_payment":        getattr(settings, "WHATSAPP_TPL_MANAGER_PAYMENT", ""),
    }
    return m.get(key, "")
