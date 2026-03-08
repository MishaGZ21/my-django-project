# Factory App (Django)

Страницы:
- Новый заказ `/orders/new/`
- Все заказы `/orders/`
- График заказов `/orders/chart/` (+ JSON `/orders/chart-data/`)
- Бухгалтерия `/accounting/`
- Цех `/workshop/`
- Админка `/admin/`

## Быстрый старт

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

Войти: `/accounts/login/` (или используйте суперпользователя для входа в админку).
