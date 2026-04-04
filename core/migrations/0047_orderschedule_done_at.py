from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0046_orderschedule_base_due_film_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderschedule',
            name='done_at_ldsp',
            field=models.DateField(blank=True, null=True, verbose_name='Дата фактической готовности ЛДСП'),
        ),
        migrations.AddField(
            model_name='orderschedule',
            name='done_at_film',
            field=models.DateField(blank=True, null=True, verbose_name='Дата фактической готовности Плёнка'),
        ),
        migrations.AddField(
            model_name='orderschedule',
            name='done_at_paint',
            field=models.DateField(blank=True, null=True, verbose_name='Дата фактической готовности Краска'),
        ),
    ]
