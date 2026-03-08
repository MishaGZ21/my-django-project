from django.db import models
from django.utils import timezone

class WhatsAppMessageLog(models.Model):
    DIRECTION = (("out", "Outbound"), ("in", "Inbound"))
    direction     = models.CharField(max_length=3, choices=DIRECTION, default="out")
    to_number     = models.CharField(max_length=32)
    template      = models.CharField(max_length=120, blank=True)
    body          = models.TextField(blank=True)
    payload       = models.JSONField(default=dict, blank=True)
    wa_message_id = models.CharField(max_length=120, blank=True, db_index=True)
    status        = models.CharField(max_length=40, default="created")
    error_code    = models.CharField(max_length=40, blank=True)
    error_text    = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    delivered_at  = models.DateTimeField(null=True, blank=True)
    read_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Сообщение WhatsApp"
        verbose_name_plural = "Сообщения WhatsApp"

    def __str__(self):
        return f"[{self.status}] to {self.to_number} ({self.template})"


class WhatsAppSettings(models.Model):
    singleton_id    = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    manager_numbers = models.TextField("Номера руководителей (через запятую)", blank=True, help_text="+7701..., +7702...")
    lang            = models.CharField("Язык шаблонов", max_length=8, default="ru")
    enabled         = models.BooleanField("Включить отправку WhatsApp", default=True)
    use_db_templates = models.BooleanField("Использовать шаблоны из БД (иначе из .env)", default=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки WhatsApp"
        verbose_name_plural = "Настройки WhatsApp"

    def __str__(self):
        return "Настройки WhatsApp"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj

    def manager_list(self):
        return [x.strip() for x in (self.manager_numbers or "").split(",") if x.strip()]


TEMPLATE_KEYS = (
    ("client_order_paid", "Клиент: заказ оплачен"),
    ("manager_order_created", "Руководитель: новый заказ создан"),
    ("manager_payment", "Руководитель: оплата по заказу"),
)

class WhatsAppTemplate(models.Model):
    key           = models.CharField(max_length=64, choices=TEMPLATE_KEYS, unique=True)
    template_name = models.CharField(max_length=120, help_text="Имя утверждённого шаблона в Meta (точно как в Business Manager)")
    active        = models.BooleanField(default=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Шаблон WhatsApp"
        verbose_name_plural = "Шаблоны WhatsApp"

    def __str__(self):
        return f"{self.get_key_display()} → {self.template_name}"
