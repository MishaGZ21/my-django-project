# Быстрый запуск (Windows/macOS)

## 1) Виртуальное окружение и зависимости
```bash
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
# macOS/Linux
. .venv/bin/activate && pip install -r requirements.txt
```

## 2) Миграции и суперпользователь
```bash
python manage.py makemigrations core
python manage.py migrate
python manage.py createsuperuser
```

## 3) .env
Скопируйте/правьте `.env` (в репо уже есть минимальный, DEBUG=true).  
Добавьте в `ALLOWED_HOSTS` IP машины, если открываете с другого устройства.

## 4) Старт
```bash
python manage.py runserver 0.0.0.0:8000
```

## 5) Логин
- Пользователь из `createsuperuser` или `/accounts/login/`.
