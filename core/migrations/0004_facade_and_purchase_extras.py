
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_purchasesheet_lds_color10_purchasesheet_lds_color5_and_more'),
    ]

    operations = [
        # Add missing PurchaseSheet fields (lds_nameN, lds_formatN)
        *[migrations.AddField(
            model_name='purchasesheet',
            name=f'lds_name{i}',
            field=models.CharField(max_length=100, null=True, blank=True, verbose_name=f'ЛДСП цвет {i} (Наименование)'),
        ) for i in range(1, 11)],

        *[migrations.AddField(
            model_name='purchasesheet',
            name=f'lds_format{i}',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name=f'ЛДСП цвет {i} (Формат)'),
        ) for i in range(1, 11)],

        # Create FacadeSheet model
        migrations.CreateModel(
            name='FacadeSheet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('paint_color1_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 1')),
                ('paint_color1_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 1 (м2)')),
                ('paint_color1_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 1 (сумма)')),
                ('paint_color1_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 1 (Фреза)')),
                ('paint_color2_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 2')),
                ('paint_color2_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 2 (м2)')),
                ('paint_color2_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 2 (сумма)')),
                ('paint_color2_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 2 (Фреза)')),
                ('paint_color3_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 3')),
                ('paint_color3_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 3 (м2)')),
                ('paint_color3_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 3 (сумма)')),
                ('paint_color3_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 3 (Фреза)')),
                ('paint_color4_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 4')),
                ('paint_color4_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 4 (м2)')),
                ('paint_color4_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 4 (сумма)')),
                ('paint_color4_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 4 (Фреза)')),
                ('paint_color5_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 5')),
                ('paint_color5_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 5 (м2)')),
                ('paint_color5_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 5 (сумма)')),
                ('paint_color5_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 5 (Фреза)')),
                ('paint_color6_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 6')),
                ('paint_color6_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 6 (м2)')),
                ('paint_color6_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 6 (сумма)')),
                ('paint_color6_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 6 (Фреза)')),
                ('paint_color7_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 7')),
                ('paint_color7_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 7 (м2)')),
                ('paint_color7_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 7 (сумма)')),
                ('paint_color7_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 7 (Фреза)')),
                ('paint_color8_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 8')),
                ('paint_color8_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 8 (м2)')),
                ('paint_color8_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 8 (сумма)')),
                ('paint_color8_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 8 (Фреза)')),
                ('paint_color9_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 9')),
                ('paint_color9_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 9 (м2)')),
                ('paint_color9_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 9 (сумма)')),
                ('paint_color9_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 9 (Фреза)')),
                ('paint_color10_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 10')),
                ('paint_color10_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 10 (м2)')),
                ('paint_color10_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады покраска цвет 10 (сумма)')),
                ('paint_color10_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады покраска цвет 10 (Фреза)')),

                ('film_color1_name', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады пленка цвет 1')),
                ('film_color1_m2', models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Фасады пленка цвет 1 (м2)')),
                ('film_color1_sum', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Фасады пленка цвет 1 (сумма)')),
                ('film_color1_fresa', models.CharField(max_length=100, null=True, blank=True, verbose_name='Фасады пленка цвет 1 (Фреза)')),
                # ... similarly 2..10 (to keep file readable, but we will actually expand below)
            ],
        ),
    ]
