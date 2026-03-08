from django.utils import timezone

STOP_WORDS = ("СТОП", "ОТЛОЖЕН")

def is_stopped(sch) -> bool:
    if not sch:
        return False
    if sch.stop_until:
        today = timezone.localdate()
        if today < sch.stop_until:
            return True
    # если статус руками поставили СТОП/ОТЛОЖЕН
    for s in (sch.status_ldsp, sch.status_film, sch.status_paint):
        if s and any(s.startswith(w) for w in STOP_WORDS):
            return True
    return False

def due_key(row):
    """Ключ для сортировки: просроченные вверх, потом ближайшие сроки"""
    # row содержит days_left по трём материалам
    candidates = []
    for k in ("ldsp_days_left", "film_days_left", "paint_days_left"):
        v = row.get(k)
        if v is None:
            continue
        candidates.append(v)
    if not candidates:
        return (1, 10**9)  # внизу
    min_left = min(candidates)  # если отрицательное -> просрочка
    return (0, min_left)
