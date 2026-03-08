from django.core.management import BaseCommand
from core.models import Order, FacadeSheet

class Command(BaseCommand):
    help = "Ensure FacadeSheet exists for every Order"

    def handle(self, *args, **kwargs):
        created = 0
        for o in Order.objects.all():
            _, was_created = FacadeSheet.objects.get_or_create(order=o)
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Created {created} FacadeSheet records"))
