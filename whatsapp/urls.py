from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="whatsapp_dashboard"),
    path("webhook/", views.webhook, name="whatsapp_webhook"),
    path("test-send/", views.test_send, name="whatsapp_test_send"),
    path("logs/", views.logs, name="whatsapp_logs"),
    path("settings/", views.settings_view, name="whatsapp_settings"),
    path("templates/", views.templates_view, name="whatsapp_templates"),
]
