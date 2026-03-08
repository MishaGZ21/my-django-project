#!/usr/bin/env bash
set -e
if [ -d ".venv" ]; then source .venv/bin/activate; fi
python -m pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py init_roles || true
echo "Migrations done."
