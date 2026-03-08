@echo off
setlocal ENABLEDELAYEDEXPANSION
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py init_roles
echo Migrations done.
