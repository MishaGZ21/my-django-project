from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()


class Order(models.Model):
    # core/models.py (класс Order)
    STATUS_NEW      = "new"
    STATUS_CALC     = "calc"
    STATUS_PAYMENT  = "payment"
    STATUS_WAREHOUSE= "warehouse"
    STATUS_WORK     = "work"
    # Дата подписания договора (фиксируем один раз!)
    contract_signed_at = models.DateField(null=True, blank=True, db_index=True)
    # Примечание (для общего графика)
    chart_note = models.TextField(blank=True, default="")
    # Основной договор подписан (фикс)
    main_contract_signed = models.BooleanField(default=False)
    main_contract_signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="signed_main_contracts",
    )
    # Статусы по направлениям
    STATUS_TECH_CHOICES = [
        ("—", "—"),
        ("Ожидает", "Ожидает"),
        ("Корректировка", "Корректировка"),
        ("СТОП", "СТОП"),
        ("Выдан в ЦЕХ", "Выдан в ЦЕХ"),
    ]

    STATUS_PROD_CHOICES = [
        ("—", "—"),
        ("Ожидает", "Ожидает"),
        ("ВЫДАН", "ВЫДАН"),
        ("СТОП", "СТОП"),
        ("ГОТОВО", "ГОТОВО"),
    ]
    
    status_tech = models.CharField(max_length=32, choices=STATUS_TECH_CHOICES, default="—")
    status_workshop = models.CharField(max_length=32, choices=STATUS_PROD_CHOICES, default="—")  # ЛДСП/Цех
    status_paint = models.CharField(max_length=32, choices=STATUS_PROD_CHOICES, default="—")
    status_film = models.CharField(max_length=32, choices=STATUS_PROD_CHOICES, default="—")
    
    STATUS_CHOICES = [
        (STATUS_NEW,       "Новый"),
        (STATUS_CALC,      "Расчёт"),
        (STATUS_PAYMENT,   "Закуп"),
        (STATUS_WAREHOUSE, "Договор"),
        (STATUS_WORK,      "В работе"),
    ]
    
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
    )

    contract_blank_generated = models.BooleanField(
        default=False,
        verbose_name="Бланк договора сформирован (PDF)"
    )
    created_date = models.DateField("Дата создания", default=timezone.localdate, editable=False)
    order_number = models.PositiveIntegerField("Номер заказа", unique=True, editable=False)
    customer_name = models.CharField("Клиент", max_length=200)
    phone = models.CharField("Телефон", max_length=20)
    last_name = models.CharField("Фамилия", max_length=150, blank=True)
    iin = models.CharField("ИИН", max_length=12, blank=True)
    has_whatsapp = models.BooleanField("Есть WhatsApp", default=True)
    whatsapp_phone = models.CharField("Телефон WhatsApp", max_length=20, blank=True)
    item = models.CharField("Изделие", max_length=200, blank=True, default="")
    quantity = models.PositiveIntegerField("Кол-во", default=1)
    price = models.DecimalField("Цена за единицу", max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField("Срок готовности", null=True, blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Кем создан")

    def save(self, *args, **kwargs):
        if not self.order_number:
            last = Order.objects.order_by("-order_number").first()
            self.order_number = last.order_number + 1 if last else 2500
        if self.has_whatsapp:
            self.whatsapp_phone = self.phone
        super().save(*args, **kwargs)
    
    

    def __str__(self):
        return f"#{self.order_number} {self.item} x{self.quantity}"

    @property
    def total(self):
        return self.quantity * self.price


class Invoice(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='invoices', verbose_name="Заказ")
    issued_at = models.DateTimeField("Выставлен", auto_now_add=True)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    paid = models.BooleanField("Оплачен", default=False)

    def __str__(self):
        return f"Счёт #{self.id} по заказу #{self.order_id}"


class ProductionTask(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='tasks', verbose_name="Заказ")
    name = models.CharField("Операция", max_length=200)
    assignee = models.CharField("Ответственный", max_length=200, blank=True)
    status = models.CharField("Статус", max_length=50, choices=[
        ('todo', 'К выполнению'),
        ('doing', 'Выполняется'),
        ('done', 'Готово'),
    ], default='todo')
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    def __str__(self):
        return f"{self.name} (заказ #{self.order_id})"


class PurchaseSheet(models.Model):
    order = models.OneToOneField("Order", on_delete=models.CASCADE, related_name="purchase_sheet")

    # Пилюли ФАСАДЫ/КОРПУС по группам 1..10
    group1_facade = models.BooleanField(default=False)
    group1_corpus = models.BooleanField(default=False)
    group2_facade = models.BooleanField(default=False)
    group2_corpus = models.BooleanField(default=False)
    group3_facade = models.BooleanField(default=False)
    group3_corpus = models.BooleanField(default=False)
    group4_facade = models.BooleanField(default=False)
    group4_corpus = models.BooleanField(default=False)
    group5_facade = models.BooleanField(default=False)
    group5_corpus = models.BooleanField(default=False)
    group6_facade = models.BooleanField(default=False)
    group6_corpus = models.BooleanField(default=False)
    group7_facade = models.BooleanField(default=False)
    group7_corpus = models.BooleanField(default=False)
    group8_facade = models.BooleanField(default=False)
    group8_corpus = models.BooleanField(default=False)
    group9_facade = models.BooleanField(default=False)
    group9_corpus = models.BooleanField(default=False)
    group10_facade = models.BooleanField(default=False)
    group10_corpus = models.BooleanField(default=False)

    # ЛДСП/ПВХ 1..10
    lds_color1 = models.PositiveIntegerField("ЛДСП цвет 1 (листов)", blank=True, null=True)
    pvc_color1 = models.PositiveIntegerField("ПВХ цвет 1 (метров)", blank=True, null=True)
    lds_color2 = models.PositiveIntegerField("ЛДСП цвет 2 (листов)", blank=True, null=True)
    pvc_color2 = models.PositiveIntegerField("ПВХ цвет 2 (метров)", blank=True, null=True)
    lds_color3 = models.PositiveIntegerField("ЛДСП цвет 3 (листов)", blank=True, null=True)
    pvc_color3 = models.PositiveIntegerField("ПВХ цвет 3 (метров)", blank=True, null=True)
    lds_color4 = models.PositiveIntegerField("ЛДСП цвет 4 (листов)", blank=True, null=True)
    pvc_color4 = models.PositiveIntegerField("ПВХ цвет 4 (метров)", blank=True, null=True)
    lds_color5 = models.PositiveIntegerField("ЛДСП цвет 5 (листов)", blank=True, null=True)
    pvc_color5 = models.PositiveIntegerField("ПВХ цвет 5 (метров)", blank=True, null=True)
    lds_color6 = models.PositiveIntegerField("ЛДСП цвет 6 (листов)", blank=True, null=True)
    pvc_color6 = models.PositiveIntegerField("ПВХ цвет 6 (метров)", blank=True, null=True)
    lds_color7 = models.PositiveIntegerField("ЛДСП цвет 7 (листов)", blank=True, null=True)
    pvc_color7 = models.PositiveIntegerField("ПВХ цвет 7 (метров)", blank=True, null=True)
    lds_color8 = models.PositiveIntegerField("ЛДСП цвет 8 (листов)", blank=True, null=True)
    pvc_color8 = models.PositiveIntegerField("ПВХ цвет 8 (метров)", blank=True, null=True)
    lds_color9 = models.PositiveIntegerField("ЛДСП цвет 9 (листов)", blank=True, null=True)
    pvc_color9 = models.PositiveIntegerField("ПВХ цвет 9 (метров)", blank=True, null=True)
    lds_color10 = models.PositiveIntegerField("ЛДСП цвет 10 (листов)", blank=True, null=True)
    pvc_color10 = models.PositiveIntegerField("ПВХ цвет 10 (метров)", blank=True, null=True)

    lds_name1 = models.CharField("ЛДСП цвет 1 (Наименование)", max_length=100, blank=True, null=True)
    lds_format1 = models.CharField("ЛДСП цвет 1 (Формат)", max_length=50, blank=True, null=True)
    lds_name2 = models.CharField("ЛДСП цвет 2 (Наименование)", max_length=100, blank=True, null=True)
    lds_format2 = models.CharField("ЛДСП цвет 2 (Формат)", max_length=50, blank=True, null=True)
    lds_name3 = models.CharField("ЛДСП цвет 3 (Наименование)", max_length=100, blank=True, null=True)
    lds_format3 = models.CharField("ЛДСП цвет 3 (Формат)", max_length=50, blank=True, null=True)
    lds_name4 = models.CharField("ЛДСП цвет 4 (Наименование)", max_length=100, blank=True, null=True)
    lds_format4 = models.CharField("ЛДСП цвет 4 (Формат)", max_length=50, blank=True, null=True)
    lds_name5 = models.CharField("ЛДСП цвет 5 (Наименование)", max_length=100, blank=True, null=True)
    lds_format5 = models.CharField("ЛДСП цвет 5 (Формат)", max_length=50, blank=True, null=True)
    lds_name6 = models.CharField("ЛДСП цвет 6 (Наименование)", max_length=100, blank=True, null=True)
    lds_format6 = models.CharField("ЛДСП цвет 6 (Формат)", max_length=50, blank=True, null=True)
    lds_name7 = models.CharField("ЛДСП цвет 7 (Наименование)", max_length=100, blank=True, null=True)
    lds_format7 = models.CharField("ЛДСП цвет 7 (Формат)", max_length=50, blank=True, null=True)
    lds_name8 = models.CharField("ЛДСП цвет 8 (Наименование)", max_length=100, blank=True, null=True)
    lds_format8 = models.CharField("ЛДСП цвет 8 (Формат)", max_length=50, blank=True, null=True)
    lds_name9 = models.CharField("ЛДСП цвет 9 (Наименование)", max_length=100, blank=True, null=True)
    lds_format9 = models.CharField("ЛДСП цвет 9 (Формат)", max_length=50, blank=True, null=True)
    lds_name10 = models.CharField("ЛДСП цвет 10 (Наименование)", max_length=100, blank=True, null=True)
    lds_format10 = models.CharField("ЛДСП цвет 10 (Формат)", max_length=50, blank=True, null=True)

    # ПВХ ШИРОКАЯ 1..10 (необязательные)
    pvc_wide_color1 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color2 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color3 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color4 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color5 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color6 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color7 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color8 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color9 = models.PositiveIntegerField(null=True, blank=True, default=None)
    pvc_wide_color10 = models.PositiveIntegerField(null=True, blank=True, default=None)

    tabletop_count = models.PositiveIntegerField("Столешница (шт.)", blank=True, null=True)
    # False = 4 м (по умолчанию), True = 3 м
    tabletop_length_3m = models.BooleanField("3 метра", default=False)

    hdf_count = models.PositiveIntegerField("ХДФ задняя стенка (листов)", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Лист закупа для заказа #{self.order.order_number}"



# --- NEW: Calculation model ---

class Calculation(models.Model):
    order = models.OneToOneField("core.Order", on_delete=models.CASCADE, related_name="calculation")
    price_snapshot = models.JSONField(default=dict, blank=True)           # снимок цен
    last_price_sync_at = models.DateTimeField(null=True, blank=True) 

    # --- агрегаты из Лист закупа ---
    sums_ldsp = models.JSONField("Суммы ЛДСП по цветам (листов)", default=dict, blank=True)
    sums_pvc = models.JSONField("Суммы ПВХ (узкая) по цветам (м)", default=dict, blank=True)
    sums_pvc_wide = models.JSONField("Суммы ПВХ (широкая) по цветам (м)", default=dict, blank=True)

    qty_ldsp_total = models.DecimalField("Итого ЛДСП (листов)", max_digits=12, decimal_places=2, default=0)
    qty_pvc_total = models.DecimalField("Итого ПВХ узкая (м)", max_digits=12, decimal_places=2, default=0)
    qty_pvc_wide_total = models.DecimalField("Итого ПВХ широкая (м)", max_digits=12, decimal_places=2, default=0)

    # --- Стоимость ЛДСП: распил + присадка ---
    cost_ldsp_raspil   = models.DecimalField("Стоимость ЛДСП (распил)",   max_digits=14, decimal_places=2, default=0)
    cost_ldsp_prisadka = models.DecimalField("Стоимость ЛДСП (присадка)", max_digits=14, decimal_places=2, default=0)
    cost_ldsp          = models.DecimalField("Стоимость ЛДСП (итого)",    max_digits=14, decimal_places=2, default=0)

    # --- ПВХ ---
    cost_pvc       = models.DecimalField("Стоимость ПВХ узкая", max_digits=14, decimal_places=2, default=0)
    cost_pvc_wide  = models.DecimalField("Стоимость ПВХ широкая", max_digits=14, decimal_places=2, default=0)

    # --- Прочее: вводимые количества + стоимости ---
    countertop_qty = models.DecimalField("Столешница (шт.)", max_digits=12, decimal_places=2, default=0)
    hdf_qty        = models.DecimalField("ХДФ задняя стенка (листов)", max_digits=12, decimal_places=2, default=0)

    cost_countertop = models.DecimalField("Стоимость столешниц", max_digits=14, decimal_places=2, default=0)
    cost_hdf        = models.DecimalField("Стоимость ХДФ",       max_digits=14, decimal_places=2, default=0)
    cost_misc       = models.DecimalField("Стоимость прочее (итого)", max_digits=14, decimal_places=2, default=0)

    # --- Фасады ---
    cost_facades   = models.DecimalField("Стоимость фасадов (итого)", max_digits=14, decimal_places=2, default=0)
    cost_additional = models.DecimalField("Стоимость дополнительно (итого)", max_digits=14, decimal_places=2, default=0)
    
    # --- Проект / Дизайн-проект ---
    design_ldsp_cost = models.DecimalField(
        "ЛДСП — дизайн (стоимость)", max_digits=14, decimal_places=2, default=0
    )
    design_facade_sheets = models.PositiveIntegerField(
        "Фасады — листов (по 5 м²)", default=0
    )
    design_facade_cost = models.DecimalField(
        "Фасады — дизайн (стоимость)", max_digits=14, decimal_places=2, default=0
    )
    cost_design_total = models.DecimalField(
        "Стоимость «Дизайн проект» (итого)", max_digits=14, decimal_places=2, default=0
    )
    was_saved = models.BooleanField(
        "Пользователь сохранял расчёт", default=False
    )

    # --- Итог ---
    total_price = models.DecimalField("Итоговая стоимость", max_digits=14, decimal_places=2, default=0)

    note = models.TextField("Заметка", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Расчёт"
        verbose_name_plural = "Расчёты"

    def __str__(self):
        return f"Расчёт #{self.order.order_number}"


class CalculationFacadeItem(models.Model):
    calculation = models.ForeignKey(Calculation, on_delete=models.CASCADE, related_name="facade_items")
    price_item  = models.ForeignKey("core.PriceItem", on_delete=models.PROTECT)
    area        = models.DecimalField("Квадратура, м²", max_digits=12, decimal_places=2, default=0)
    cost        = models.DecimalField("Стоимость",      max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Строка фасада"
        verbose_name_plural = "Строки фасадов"

    def __str__(self):
        return f"{self.price_item.title} — {self.area} м²"





class CalculationAdditionalItem(models.Model):
    calculation = models.ForeignKey("Calculation", on_delete=models.CASCADE, related_name="additional_items")
    price_item  = models.ForeignKey("PriceItem", on_delete=models.PROTECT)
    qty         = models.DecimalField("Количество", max_digits=12, decimal_places=2, default=0)
    cost        = models.DecimalField("Стоимость", max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Доп. позиция (расчёт)"
        verbose_name_plural = "Доп. позиции (расчёт)"


class Contract(models.Model):
    STATUS_CHOICES = [
        ("procurement", "Закуп"),
        ("design", "Оформление"),
        ("production", "Производство"),
    ]
    materials_alloc_json = models.JSONField("Распределение материалов (JSON)", default=list, blank=True)

    order = models.OneToOneField("Order", on_delete=models.CASCADE, related_name="contract")
    lds_count = models.PositiveIntegerField("Кол-во ЛДСП", blank=True, null=True)
    facades_m2 = models.DecimalField("м² фасады", max_digits=8, decimal_places=2, blank=True, null=True)
    material_type = models.CharField("Материал", max_length=20, choices=[
        ("lds", "ЛДСП"),
        ("paint", "Краска"),
        ("film", "Плёнка"),
    ], blank=True, null=True)
    spec_json = models.JSONField("Спецификация (JSON)", default=list, blank=True)
    due_date = models.DateField("Срок сдачи", blank=True, null=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default="procurement")

    @property
    def days_left(self):
        if self.due_date:
            return (self.due_date - timezone.localdate()).days
        return None

    def __str__(self):
        return f"Договор для заказа #{self.order.order_number}"


class FacadeSheet(models.Model):
    # Важно: одна связь, без дублей; временно допускаем NULL, чтобы миграции проходили без вопросов
    order = models.OneToOneField('Order', on_delete=models.CASCADE,
                             related_name='facade_sheet',
                             null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Покраска
    paint_color1_name = models.CharField("Фасады покраска цвет 1", max_length=100, blank=True, null=True)
    paint_color1_m2 = models.DecimalField("Фасады покраска цвет 1 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color1_sum = models.DecimalField("Фасады покраска цвет 1 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color1_fresa = models.CharField("Фасады покраска цвет 1 (Фреза)", max_length=100, blank=True, null=True)

    paint_color2_name = models.CharField("Фасады покраска цвет 2", max_length=100, blank=True, null=True)
    paint_color2_m2 = models.DecimalField("Фасады покраска цвет 2 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color2_sum = models.DecimalField("Фасады покраска цвет 2 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color2_fresa = models.CharField("Фасады покраска цвет 2 (Фреза)", max_length=100, blank=True, null=True)

    paint_color3_name = models.CharField("Фасады покраска цвет 3", max_length=100, blank=True, null=True)
    paint_color3_m2 = models.DecimalField("Фасады покраска цвет 3 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color3_sum = models.DecimalField("Фасады покраска цвет 3 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color3_fresa = models.CharField("Фасады покраска цвет 3 (Фреза)", max_length=100, blank=True, null=True)

    paint_color4_name = models.CharField("Фасады покраска цвет 4", max_length=100, blank=True, null=True)
    paint_color4_m2 = models.DecimalField("Фасады покраска цвет 4 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color4_sum = models.DecimalField("Фасады покраска цвет 4 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color4_fresa = models.CharField("Фасады покраска цвет 4 (Фреза)", max_length=100, blank=True, null=True)

    paint_color5_name = models.CharField("Фасады покраска цвет 5", max_length=100, blank=True, null=True)
    paint_color5_m2 = models.DecimalField("Фасады покраска цвет 5 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color5_sum = models.DecimalField("Фасады покраска цвет 5 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color5_fresa = models.CharField("Фасады покраска цвет 5 (Фреза)", max_length=100, blank=True, null=True)

    paint_color6_name = models.CharField("Фасады покраска цвет 6", max_length=100, blank=True, null=True)
    paint_color6_m2 = models.DecimalField("Фасады покраска цвет 6 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color6_sum = models.DecimalField("Фасады покраска цвет 6 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color6_fresa = models.CharField("Фасады покраска цвет 6 (Фреза)", max_length=100, blank=True, null=True)

    paint_color7_name = models.CharField("Фасады покраска цвет 7", max_length=100, blank=True, null=True)
    paint_color7_m2 = models.DecimalField("Фасады покраска цвет 7 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color7_sum = models.DecimalField("Фасады покраска цвет 7 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color7_fresa = models.CharField("Фасады покраска цвет 7 (Фреза)", max_length=100, blank=True, null=True)

    paint_color8_name = models.CharField("Фасады покраска цвет 8", max_length=100, blank=True, null=True)
    paint_color8_m2 = models.DecimalField("Фасады покраска цвет 8 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color8_sum = models.DecimalField("Фасады покраска цвет 8 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color8_fresa = models.CharField("Фасады покраска цвет 8 (Фреза)", max_length=100, blank=True, null=True)

    paint_color9_name = models.CharField("Фасады покраска цвет 9", max_length=100, blank=True, null=True)
    paint_color9_m2 = models.DecimalField("Фасады покраска цвет 9 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color9_sum = models.DecimalField("Фасады покраска цвет 9 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color9_fresa = models.CharField("Фасады покраска цвет 9 (Фреза)", max_length=100, blank=True, null=True)

    paint_color10_name = models.CharField("Фасады покраска цвет 10", max_length=100, blank=True, null=True)
    paint_color10_m2 = models.DecimalField("Фасады покраска цвет 10 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    paint_color10_sum = models.DecimalField("Фасады покраска цвет 10 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    paint_color10_fresa = models.CharField("Фасады покраска цвет 10 (Фреза)", max_length=100, blank=True, null=True)

    paint_total_sum = models.DecimalField("Фасады покраска сумма (общая)", max_digits=12, decimal_places=2, blank=True, null=True)

    # Плёнка
    film_color1_name = models.CharField("Фасады пленка цвет 1", max_length=100, blank=True, null=True)
    film_color1_m2 = models.DecimalField("Фасады пленка цвет 1 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color1_sum = models.DecimalField("Фасады пленка цвет 1 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color1_fresa = models.CharField("Фасады пленка цвет 1 (Фреза)", max_length=100, blank=True, null=True)

    film_color2_name = models.CharField("Фасады пленка цвет 2", max_length=100, blank=True, null=True)
    film_color2_m2 = models.DecimalField("Фасады пленка цвет 2 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color2_sum = models.DecimalField("Фасады пленка цвет 2 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color2_fresa = models.CharField("Фасады пленка цвет 2 (Фреза)", max_length=100, blank=True, null=True)

    film_color3_name = models.CharField("Фасады пленка цвет 3", max_length=100, blank=True, null=True)
    film_color3_m2 = models.DecimalField("Фасады пленка цвет 3 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color3_sum = models.DecimalField("Фасады пленка цвет 3 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color3_fresa = models.CharField("Фасады пленка цвет 3 (Фреза)", max_length=100, blank=True, null=True)

    film_color4_name = models.CharField("Фасады пленка цвет 4", max_length=100, blank=True, null=True)
    film_color4_m2 = models.DecimalField("Фасады пленка цвет 4 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color4_sum = models.DecimalField("Фасады пленка цвет 4 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color4_fresa = models.CharField("Фасады пленка цвет 4 (Фреза)", max_length=100, blank=True, null=True)

    film_color5_name = models.CharField("Фасады пленка цвет 5", max_length=100, blank=True, null=True)
    film_color5_m2 = models.DecimalField("Фасады пленка цвет 5 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color5_sum = models.DecimalField("Фасады пленка цвет 5 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color5_fresa = models.CharField("Фасады пленка цвет 5 (Фреза)", max_length=100, blank=True, null=True)

    film_color6_name = models.CharField("Фасады пленка цвет 6", max_length=100, blank=True, null=True)
    film_color6_m2 = models.DecimalField("Фасады пленка цвет 6 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color6_sum = models.DecimalField("Фасады пленка цвет 6 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color6_fresa = models.CharField("Фасады пленка цвет 6 (Фреза)", max_length=100, blank=True, null=True)

    film_color7_name = models.CharField("Фасады пленка цвет 7", max_length=100, blank=True, null=True)
    film_color7_m2 = models.DecimalField("Фасады пленка цвет 7 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color7_sum = models.DecimalField("Фасады пленка цвет 7 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color7_fresa = models.CharField("Фасады пленка цвет 7 (Фреза)", max_length=100, blank=True, null=True)

    film_color8_name = models.CharField("Фасады пленка цвет 8", max_length=100, blank=True, null=True)
    film_color8_m2 = models.DecimalField("Фасады пленка цвет 8 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color8_sum = models.DecimalField("Фасады пленка цвет 8 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color8_fresa = models.CharField("Фасады пленка цвет 8 (Фреза)", max_length=100, blank=True, null=True)

    film_color9_name = models.CharField("Фасады пленка цвет 9", max_length=100, blank=True, null=True)
    film_color9_m2 = models.DecimalField("Фасады пленка цвет 9 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color9_sum = models.DecimalField("Фасады пленка цвет 9 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color9_fresa = models.CharField("Фасады пленка цвет 9 (Фреза)", max_length=100, blank=True, null=True)

    film_color10_name = models.CharField("Фасады пленка цвет 10", max_length=100, blank=True, null=True)
    film_color10_m2 = models.DecimalField("Фасады пленка цвет 10 (м2)", max_digits=10, decimal_places=2, blank=True, null=True)
    film_color10_sum = models.DecimalField("Фасады пленка цвет 10 (сумма)", max_digits=12, decimal_places=2, blank=True, null=True)
    film_color10_fresa = models.CharField("Фасады пленка цвет 10 (Фреза)", max_length=100, blank=True, null=True)

    film_total_sum = models.DecimalField("Фасады пленка сумма (общая)", max_digits=12, decimal_places=2, blank=True, null=True)

    # Прочее
    designer_services_cost = models.DecimalField("Услуги дизайнера", max_digits=12, decimal_places=2, blank=True, null=True)
    spec_text = models.TextField("Спецификация", blank=True, null=True)
    services_paid_date = models.DateField("Дата оплаты услуг", blank=True, null=True)
    material_delivery_date = models.DateField("Дата завоза материала", blank=True, null=True)

    def __str__(self):
        return f'Фасады для заказа #{self.order.order_number if self.order_id else "?"}'


from django.conf import settings
# --- СКЛАД: частичные приёмки ---
class WarehouseReceipt(models.Model):
    """
    Частичная приёмка материалов на склад по заказу.
    Для одного заказа может быть несколько приёмок (из разных мест/дат).
    """
    order = models.ForeignKey("core.Order", on_delete=models.CASCADE, related_name="warehouse_receipts")
    status = models.CharField(max_length=20, default="draft", choices=[("draft", "Черновик"), ("accepted", "Принято")])
    received_at = models.DateTimeField(null=True, blank=True)

    # ФАКТИЧЕСКИ ПРИВЕЗЕНО
    qty_ldsp_2750x1830 = models.DecimalField(max_digits=8, decimal_places=2, default=0)   # листов
    qty_ldsp_2800x2070 = models.DecimalField(max_digits=8, decimal_places=2, default=0)   # листов
    qty_pvc_narrow_m   = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # метры
    qty_pvc_wide_m     = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # метры
    qty_hdf_sheets     = models.DecimalField(max_digits=8, decimal_places=2, default=0)   # листов
    qty_countertop_pcs = models.DecimalField(max_digits=8, decimal_places=2, default=0)   # шт.
    countertop_edge_present = models.BooleanField(default=False)

    # ПОДПИСЬ ВОДИТЕЛЯ
    signature = models.ImageField(upload_to="signatures/", null=True, blank=True)
    driver_name  = models.CharField(max_length=255, blank=True, default="")
    driver_phone = models.CharField(max_length=64,  blank=True, default="")

    # СЛУЖЕБНОЕ
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"Приёмка #{self.pk} по заказу {self.order_id} [{self.status}]"


class WarehouseDraft(models.Model):
    """
    Серверный черновик значений формы для конкретной приёмки (автосохранение).
    """
    receipt = models.OneToOneField("core.WarehouseReceipt", on_delete=models.CASCADE, related_name="draft")
    payload = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Черновик приёмки #{self.receipt_id}"

        
# ⬇️ В конец файла (или рядом с Order/PurchaseSheet/Contract)
from django.conf import settings
from django.db import models

class ChangeLog(models.Model):
    SECTION_CHOICES = [
        ("purchase_sheet", "Лист закупа"),
        ("contract", "Договор"),
    ]
    ACTION_CHOICES = [
        ("created", "Создание"),
        ("updated", "Изменение"),
    ]

    order = models.ForeignKey("core.Order", on_delete=models.CASCADE, related_name="change_logs")
    section = models.CharField(max_length=32, choices=SECTION_CHOICES)
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default="updated")
    # Краткий человекочитаемый дифф; можно расширить до JSON при желании
    diff_text = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_section_display()}] {self.get_action_display()} от {self.created_at:%Y-%m-%d %H:%M}"
        
        
        
class PriceGroup(models.Model):
    title = models.CharField("Группа", max_length=100)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Группа цен"
        verbose_name_plural = "Группы цен"

    def __str__(self):
        return self.title


class PriceItem(models.Model):
    group = models.ForeignKey(PriceGroup, on_delete=models.CASCADE, related_name="items")
    title = models.CharField("Название позиции", max_length=200)
    value = models.DecimalField("Цена", max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]
        verbose_name = "Цена"
        verbose_name_plural = "Цены"
        constraints = [
            models.UniqueConstraint(fields=['group', 'title'], name='unique_priceitem_title_per_group')
        ]

    def __str__(self):
        return f"{self.group.title}: {self.title}"





class Payment(models.Model):
    METHODS = (
        ("cash", "Наличные"),
        ("card", "Карта"),
        ("qr",   "QR"),
    )
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments", verbose_name="Заказ")
    amount_total = models.DecimalField("Итоговая стоимость", max_digits=14, decimal_places=2, default=0)
    amount_design = models.DecimalField("Итого «Дизайн проект»", max_digits=14, decimal_places=2, default=0)
    amount_facades = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_due = models.DecimalField("Итого к оплате", max_digits=14, decimal_places=2, default=0)
    methods = models.JSONField("Вид оплаты", default=list, blank=True)
    created_at = models.DateTimeField("Дата/время оплаты", auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Кассир")

    # ← ЭТИ НОВЫЕ ПОЛЯ ДОЛЖНЫ БЫТЬ ЗДЕСЬ (в теле модели), НЕ в Meta!
    calc_snapshot = models.JSONField("Снимок расчёта на момент оплаты", default=dict, blank=True)
    mode = models.CharField("Режим оплаты", max_length=10, choices=(("full","Полная"),("diff","Разница")), default="full")

    class Meta:
        ordering = ["-created_at", "id"]
        verbose_name = "Оплата"
        verbose_name_plural = "Оплаты"
        # УДАЛЕНО:
        # constraints = [
        #     models.UniqueConstraint(fields=["order"], name="unique_payment_per_order")
        # ]

    def __str__(self):
        return f"Оплата заказа #{self.order.order_number} на {self.amount_due}"
        
class OrderPaymentInclude(models.Model):
    order = models.OneToOneField('core.Order', on_delete=models.CASCADE, related_name='payment_include')
    include_services = models.BooleanField(default=True)
    include_design   = models.BooleanField(default=True)
    include_facades  = models.BooleanField(default=True)
    updated_at       = models.DateTimeField(auto_now=True)
        
class QuickQuote(models.Model):
    CATEGORY_CHOICES = [
        ("kitchen",  "Кухня"),
        ("wardrobe", "Шкаф"),
        ("closet",   "Гардероб"),
        ("misc",     "Разное"),
    ]
    created_at       = models.DateTimeField(auto_now_add=True)
    phone            = models.CharField(max_length=32)
    category         = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="kitchen")

    # введённые количества
    qty_ldsp         = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    qty_hdf          = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    qty_countertops  = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    # рассчитанные суммы (показываются в quick_quote*.html)
    amt_processing     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    amt_pvc            = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    amt_facades        = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    amt_services_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    amt_materials      = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    furn_min           = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    furn_max           = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    furn_avg           = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    grand_total        = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    def __str__(self):
        return f"QQ #{self.id} {self.get_category_display()} {self.phone}"


class QuickQuoteFacade(models.Model):
    quick_quote = models.ForeignKey("QuickQuote", related_name="facades", on_delete=models.CASCADE)
    # ВАЖНО: FK на EXISTING PriceItem из вашей «Бухгалтерии»
    price_item  = models.ForeignKey("PriceItem", on_delete=models.PROTECT)
    area        = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    cost        = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = "БР фасад"
        verbose_name_plural = "БР фасады"
        
        
        
class Employee(models.Model):
    """Сотрудник для расчёта заработной платы."""
    full_name = models.CharField("ФИО", max_length=255)

    position = models.CharField(
        "Должность",
        max_length=255,
        blank=True,
        default="",
    )

    base_salary = models.DecimalField(
        "Оклад",
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Месячная заработная плата (брутто)",
    )

    deduction_amount = models.DecimalField(
        "Удержание, тг",
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Фиксированная сумма удержаний в месяц (пенсионка, медстраховка и т.п.)",
    )
    
    deduction_amount = models.DecimalField(
        "Удержание, тг",
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Фиксированная сумма удержаний в месяц (пенсионка, медстраховка и т.п.)",
    )

    advance_balance = models.DecimalField(
        "Баланс авансов, тг",
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Текущий долг по авансам (что ещё нужно удержать из ЗП)",
    )

    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    @property
    def net_salary(self):
        """Ежемесячная сумма к выплате: оклад минус удержание."""
        salary = self.base_salary or Decimal("0")
        deduction = self.deduction_amount or Decimal("0")
        net = salary - deduction
        if net < 0:
            net = Decimal("0")
        return net



class SalaryPayment(models.Model):
    """Фактическая выплата заработной платы (зарплата или аванс)."""

    TYPE_SALARY = "salary"
    TYPE_ADVANCE = "advance"
    TYPE_CHOICES = [
        (TYPE_SALARY, "Зарплата"),
        (TYPE_ADVANCE, "Аванс"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="salary_payments",
        verbose_name="Сотрудник",
    )

    # Период можно оставить на будущее, но в UI сейчас не используем
    period_start = models.DateField("Начало периода", null=True, blank=True)
    period_end = models.DateField("Конец периода", null=True, blank=True)

    pay_date = models.DateField("Дата выплаты", default=timezone.localdate)

    kind = models.CharField(
        "Тип выплаты",
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_SALARY,
    )

    gross_amount = models.DecimalField(
        "Начислено (брутто)", max_digits=12, decimal_places=2
    )
    deduction_percent = models.DecimalField(
        "Процент удержаний", max_digits=5, decimal_places=2
    )
    deduction_amount = models.DecimalField(
        "Сумма удержаний", max_digits=12, decimal_places=2
    )

    extra_deduction_amount = models.DecimalField(
        "Доп. вычет (штраф и т.п.)",
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    net_amount = models.DecimalField(
        "К выплате (нетто)", max_digits=12, decimal_places=2
    )

    comment = models.CharField(
        "Комментарий", max_length=255, blank=True, default=""
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Выплата зарплаты"
        verbose_name_plural = "Выплаты зарплат"
        ordering = ["-pay_date", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.employee} — {self.pay_date} — {self.net_amount}"

class ChartConfig(models.Model):
    TAB_CHOICES = [
        ("general", "Общий график"),
        ("technologist", "График ТЕХНОЛОГ"),
        ("workshop", "График ЦЕХ"),
        ("paint", "График КРАСКА"),
        ("film", "График ПЛЕНКА"),
    ]

    # ❗ убрали unique=True чтобы можно было хранить версии
    tab = models.CharField(max_length=32, choices=TAB_CHOICES, db_index=True)

    enabled = models.BooleanField(default=True)

    # ✅ версия: действует с этой даты (для "только новых заказов")
    effective_from = models.DateField(default=timezone.localdate, db_index=True)

    # ✅ сроки (рабочие дни)
    days_ldsp = models.PositiveIntegerField(default=10)
    days_film = models.PositiveIntegerField(default=10)
    days_paint = models.PositiveIntegerField(default=14)

    # старые поля пока оставим (не используем в графиках)
    days_default = models.PositiveIntegerField(default=30)
    group_by = models.CharField(max_length=16, default="day")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tab", "effective_from"]),
        ]
        ordering = ["tab", "-effective_from", "-id"]

    def __str__(self):
        return f"{self.get_tab_display()} с {self.effective_from}"

class HolidayKZ(models.Model):
    date = models.DateField(unique=True, db_index=True)
    title = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.title}".strip()
        
        
class OrderSchedule(models.Model):
    STATUS_CHOICES = [
        ("ОТЛОЖЕН", "ОТЛОЖЕН"),
        ("ОЖИДАЕТ", "ОЖИДАЕТ"),
        ("КОРРЕКТИРОВКА", "КОРРЕКТИРОВКА"),
        ("СТОП", "СТОП"),
        ("ВЫДАН В ЦЕХ", "ВЫДАН В ЦЕХ"),
        ("ГОТОВО", "ГОТОВО"),
        ("ВЫДАН", "ВЫДАН"),
    ]

    order = models.OneToOneField("Order", on_delete=models.CASCADE, related_name="schedule")
    
    # ✅ ЯКОРНЫЕ (базовые) сроки общего графика по материалам
    base_due_ldsp = models.DateField(null=True, blank=True)
    base_due_film = models.DateField(null=True, blank=True)
    base_due_paint = models.DateField(null=True, blank=True)

    # Статусы по материалам
    status_ldsp = models.CharField(max_length=32, choices=STATUS_CHOICES, default="ОЖИДАЕТ")
    status_film = models.CharField(max_length=32, choices=STATUS_CHOICES, default="ОЖИДАЕТ")
    status_paint = models.CharField(max_length=32, choices=STATUS_CHOICES, default="ОЖИДАЕТ")

    # Ручные сроки (если нужно “назначить дату” вручную)
    due_ldsp_override = models.DateField(null=True, blank=True)
    due_film_override = models.DateField(null=True, blank=True)
    due_paint_override = models.DateField(null=True, blank=True)

    # Ручная добавка к срокам (рабочие дни)
    extra_days_ldsp = models.IntegerField(default=0)
    extra_days_film = models.IntegerField(default=0)
    extra_days_paint = models.IntegerField(default=0)

    # Фактические даты готовности (фиксируются при статусе ГОТОВО/ВЫДАН)
    done_at_ldsp  = models.DateField("Дата готовности ЛДСП",   null=True, blank=True)
    done_at_film  = models.DateField("Дата готовности Плёнка", null=True, blank=True)
    done_at_paint = models.DateField("Дата готовности Краска", null=True, blank=True)

    # STOP (общий для заказа)
    stop_until = models.DateField(null=True, blank=True)  # если today < stop_until — “заморозка”

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Schedule for order {self.order_id}"