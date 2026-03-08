from django.db import migrations

PRICE_SEED = [
    {"group": "Дизайнер", "items": [
        "Дизайн проект",
    ]},
    {"group": "ЛДСП", "items": [
        "Распил",
        "Присадка",
        "ПВХ узкая",
        "ПВХ широкая",
        "Пазы Gola",
        "Столешница распил",
        "Столешница кромка",
    ]},
    {"group": "Фасады (краска)", "items": [
        "Фасад краска модерн",
        "Фасад краска выборка",
        "Фасад краска выборка узкая",
        "Фасад краска волна",
        "Фасад краска волна узкая",
        "Фасад краска волна образец",
        "Фасад краска полосы",
        "Фасад краска полосы образец",
        "Фасад краска квадро",
        "Фасад краска инт. ручка",
        "Фасад краска образец",
    ]},
    {"group": "Фасады (плёнка)", "items": [
        "Фасад пленка модерн",
        "Фасад пленка выборка",
        "Фасад пленка выборка узкая",
        "Фасад пленка волна",
        "Фасад пленка волна узкая",
        "Фасад пленка волна образец",
        "Фасад пленка полосы",
        "Фасад пленка полосы образец",
        "Фасад пленка квадро",
        "Фасад пленка образец",
    ]},
    {"group": "Прочее", "items": [
        "Упаковка межгород",
    ]},
]

def seed_prices(apps, schema_editor):
    PriceGroup = apps.get_model("core", "PriceGroup")
    PriceItem = apps.get_model("core", "PriceItem")

    for idx, block in enumerate(PRICE_SEED, start=1):
        group, _ = PriceGroup.objects.get_or_create(
            title=block["group"],
            defaults={"sort_order": idx},
        )
        for title in block["items"]:
            PriceItem.objects.get_or_create(group=group, title=title, defaults={"value": 0})

def unseed_prices(apps, schema_editor):
    PriceGroup = apps.get_model("core", "PriceGroup")
    PriceItem = apps.get_model("core", "PriceItem")
    # безопасно: просто удалим группы по нашим названиям (каскадно удалятся и items)
    for block in PRICE_SEED:
        PriceGroup.objects.filter(title=block["group"]).delete()

class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_pricegroup_priceitem"),
    ]

    operations = [
        migrations.RunPython(seed_prices, reverse_code=unseed_prices),
    ]