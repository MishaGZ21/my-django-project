@echo off
REM Активируем виртуальное окружение
call venv\Scripts\activate.bat

REM Запускаем сервер Django
python manage.py runserver

REM Открываем сайт в браузере
start http://127.0.0.1:8000

REM Оставляем окно открытым
pause
