from django.db import migrations
from decimal import Decimal

def ensure_quick_quote_params(apps, schema_editor):
    PriceGroup = apps.get_model("core", "PriceGroup")
    PriceItem  = apps.get_model("core", "PriceItem")

    # найти имена полей для цены и ед.изм. — в разных проектах они могут называться по-разному
    item_fields = {f.name for f in PriceItem._meta.get_fields() if hasattr(f, "attname")}
    price_field = "price" if "price" in item_fields else ("value" if "value" in item_fields else None)
    unit_field  = "unit"  if "unit"  in item_fields else None

    # создаём/находим группу
    grp_defaults = {}
    group_fields = {f.name for f in PriceGroup._meta.get_fields() if hasattr(f, "attname")}
    if "color" in group_fields:
        grp_defaults["color"] = "#F59E0B"  # выделим другим цветом (оранжевый)
    if "sort_order" in group_fields:
        grp_defaults.setdefault("sort_order", 999)

    group, _ = PriceGroup.objects.get_or_create(
        title="Быстрый расчёт — параметры",
        defaults=grp_defaults
    )

    def upsert(title, amount, unit_text):
        defaults = {}
        if price_field:
            defaults[price_field] = Decimal(str(amount))
        if unit_field:
            defaults[unit_field]  = unit_text

        item, created = PriceItem.objects.get_or_create(
            group=group, title=title, defaults=defaults
        )
        if not created:
            # обновим цену/ед.изм. если поля существуют
            if price_field:
                setattr(item, price_field, Decimal(str(amount)))
            if unit_field:
                setattr(item, unit_field, unit_text)
            item.save(update_fields=[f for f in [price_field, unit_field] if f])

    # ПВХ (метров на лист ЛДСП)
    upsert("ПВХ_Кухня (м/лист)",    40,   "м/лист")
    upsert("ПВХ_Шкаф (м/лист)",     25,   "м/лист")
    upsert("ПВХ_Гардероб (м/лист)", 25,   "м/лист")
    upsert("ПВХ_Разное (м/лист)",   30,   "м/лист")

    # Фурнитура (тг за лист)
    upsert("Кухня_min (тг/лист)",    5000, "тг/лист")
    upsert("Кухня_max (тг/лист)",    7500, "тг/лист")
    upsert("Шкафы_min (тг/лист)",    4900, "тг/лист")
    upsert("Шкафы_max (тг/лист)",    6490, "тг/лист")
    upsert("Гардероб_min (тг/лист)", 2500, "тг/лист")
    upsert("Гардероб_max (тг/лист)", 6490, "тг/лист")
    upsert("Разное_min (тг/лист)",   2500, "тг/лист")
    upsert("Разное_max (тг/лист)",   7500, "тг/лист")

    # Закуп (материалы)
    upsert("Лист_ЛДСП (тг/лист)", 15000, "тг/лист")
    upsert("Лист_ХДФ (тг/лист)",  7000,  "тг/лист")
    upsert("Столешница (тг/шт)",  40000, "тг/шт")


def remove_quick_quote_params(apps, schema_editor):
    PriceGroup = apps.get_model("core", "PriceGroup")
    PriceItem  = apps.get_model("core", "PriceItem")
    try:
        group = PriceGroup.objects.get(title="Быстрый расчёт — параметры")
    except PriceGroup.DoesNotExist:
        return
    # удалим только наши позиции этой группы и саму группу
    PriceItem.objects.filter(group=group).delete()
    group.delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0026_alter_quickquote_phone_quickquotefacade_and_more")]

    operations = [
        migrations.RunPython(ensure_quick_quote_params, remove_quick_quote_params),
    ]
