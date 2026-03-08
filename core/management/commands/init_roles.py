from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

class Command(BaseCommand):
    help = "Создаёт группы ролей (Бухгалтер, Дизайнер_1, Дизайнер_2, Цех)"

    def handle(self, *args, **kwargs):
        roles = ["Бухгалтер", "Дизайнер_1", "Дизайнер_2", "Цех"]
        for role in roles:
            Group.objects.get_or_create(name=role)
        self.stdout.write(self.style.SUCCESS("Группы ролей созданы"))
