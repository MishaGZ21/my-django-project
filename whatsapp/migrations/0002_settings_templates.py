from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('whatsapp', '0001_initial'),
    ]
    operations = [
        migrations.CreateModel(
            name='WhatsAppSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_id', models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ('manager_numbers', models.TextField(blank=True, help_text='+7701..., +7702...', verbose_name='Номера руководителей (через запятую)')),
                ('lang', models.CharField(default='ru', max_length=8, verbose_name='Язык шаблонов')),
                ('use_db_templates', models.BooleanField(default=True, verbose_name='Использовать шаблоны из БД (иначе из .env)')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Настройки WhatsApp', 'verbose_name_plural': 'Настройки WhatsApp'},
        ),
        migrations.CreateModel(
            name='WhatsAppTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(choices=[('client_order_paid', 'Клиент: заказ оплачен'), ('manager_order_created', 'Руководитель: новый заказ создан'), ('manager_payment', 'Руководитель: оплата по заказу')], max_length=64, unique=True)),
                ('template_name', models.CharField(help_text='Имя утверждённого шаблона в Meta (точно как в Business Manager)', max_length=120)),
                ('active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Шаблон WhatsApp', 'verbose_name_plural': 'Шаблоны WhatsApp'},
        ),
    ]
