from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name='WhatsAppMessageLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('direction', models.CharField(choices=[('out', 'Outbound'), ('in', 'Inbound')], default='out', max_length=3)),
                ('to_number', models.CharField(max_length=32)),
                ('template', models.CharField(blank=True, max_length=120)),
                ('body', models.TextField(blank=True)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('wa_message_id', models.CharField(blank=True, db_index=True, max_length=120)),
                ('status', models.CharField(default='created', max_length=40)),
                ('error_code', models.CharField(blank=True, max_length=40)),
                ('error_text', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={'ordering': ['-created_at'], 'verbose_name': 'Сообщение WhatsApp', 'verbose_name_plural': 'Сообщения WhatsApp'},
        ),
    ]
