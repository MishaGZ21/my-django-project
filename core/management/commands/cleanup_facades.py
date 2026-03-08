from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

def _is_empty_facadesheet(fs):
    """Heuristic: facadesheet считается пустым, если все его 'полезные' поля пусты/нулевые.
    Не учитываем: id, order, created_at.
    """
    from core.models import FacadeSheet
    empty = True
    for field in FacadeSheet._meta.concrete_fields:
        if field.name in ('id', 'order', 'created_at'):
            continue
        val = getattr(fs, field.name, None)
        # Любое 'непустое' значение считаем как наличие данных
        if val not in (None, "", 0):
            try:
                # Для Decimal и т.п.
                if getattr(val, 'quantize', None):
                    if val != 0:
                        empty = False
                        break
                else:
                    empty = False
                    break
            except Exception:
                empty = False
                break
    return empty

class Command(BaseCommand):
    help = "Чистит FacadeSheet с order=NULL: удаляет полностью пустые и показывает список остальных для ручной привязки через админку."

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete-empty', action='store_true', default=False,
            help='Удалить пустые FacadeSheet (order IS NULL и без данных)',
        )
        parser.add_argument(
            '--dry-run', action='store_true', default=False,
            help='Только показать, ничего не менять',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        from core.models import FacadeSheet
        qs = FacadeSheet.objects.filter(order__isnull=True)
        total = qs.count()
        self.stdout.write(self.style.NOTICE(f"Найдено FacadeSheet без order: {total}"))

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Нечего чистить — можно делать поле order обязательным."))
            return

        empty_ids = []
        nonempty_ids = []
        for fs in qs:
            if _is_empty_facadesheet(fs):
                empty_ids.append(fs.id)
            else:
                nonempty_ids.append(fs.id)

        self.stdout.write(f"Пустые (будут удалены при --delete-empty): {len(empty_ids)} -> {empty_ids[:20]}{'...' if len(empty_ids) > 20 else ''}")
        self.stdout.write(f"С данными (привязать вручную в админке): {len(nonempty_ids)} -> {nonempty_ids[:20]}{'...' if len(nonempty_ids) > 20 else ''}")

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING("Dry-run: изменений не вносили."))
            return

        if opts['delete_empty'] and empty_ids:
            deleted, _ = FacadeSheet.objects.filter(id__in=empty_ids).delete()
            self.stdout.write(self.style.SUCCESS(f"Удалено пустых FacadeSheet: {deleted}"))
        else:
            self.stdout.write(self.style.WARNING("Пустые НЕ удалялись (нет --delete-empty)."))

        # Итоговая проверка
        remaining = FacadeSheet.objects.filter(order__isnull=True).count()
        if remaining == 0:
            self.stdout.write(self.style.SUCCESS("Готово! Все FacadeSheet имеют order — можно делать поле обязательным."))
        else:
            self.stdout.write(self.style.WARNING(f"Осталось FacadeSheet без order: {remaining}. "
                                                 f"Привяжи их вручную, затем повтори команду или сразу делай поле обязательным после привязки."))
