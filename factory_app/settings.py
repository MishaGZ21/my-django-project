import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
#ALLOWED_HOSTS = ["*"]


MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

WHATSAPP_MANAGER_NUMBERS = [
    x.strip() for x in os.getenv("WHATSAPP_MANAGER_NUMBERS", "").split(",") if x.strip()
]
WHATSAPP_LANG = os.getenv("WHATSAPP_LANG", "ru")
WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")

WHATSAPP_TPL_CLIENT_ORDER_PAID     = os.getenv("WHATSAPP_TPL_CLIENT_ORDER_PAID", "")
WHATSAPP_TPL_MANAGER_ORDER_CREATED = os.getenv("WHATSAPP_TPL_MANAGER_ORDER_CREATED", "")
WHATSAPP_TPL_MANAGER_PAYMENT       = os.getenv("WHATSAPP_TPL_MANAGER_PAYMENT", "")



INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core.apps.CoreConfig',
    'whatsapp',
    'contracts'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'factory_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'factory_app.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]



LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Asia/Almaty'
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = "\u00A0"  # NBSP
NUMBER_GROUPING = 3

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'core' / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = "/post-login/"
LOGOUT_REDIRECT_URL = 'login'

handler403 = "core.views.custom_permission_denied_view"

CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h and h not in ("localhost","127.0.0.1")]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- CONTRACTS model mapping (optional, can be overridden via ENV CONTRACTS_MODEL_MAP as JSON) ---
import json as _json
_env_map = os.getenv("CONTRACTS_MODEL_MAP", "").strip()
try:
    CONTRACTS_MODEL_MAP = _json.loads(_env_map) if _env_map else {}
except Exception:
    CONTRACTS_MODEL_MAP = {}
# Example (fill with your exact app.Model names if авто-детектор не находит нужные):
# CONTRACTS_MODEL_MAP.update({
#     "order": "orders.Order",
#     "payment": "payments.Payment",
#     "warehouse_receipt": "core.WarehouseReceipt",
#     "warehouse_item": "core.WarehouseReceiptItem",
#     "calculation": "calc.Calculation",
#     "calculation_row": "calc.FacadeItem",
# })
