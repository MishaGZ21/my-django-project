from django.contrib import admin
from .models import WhatsAppMessageLog, WhatsAppSettings, WhatsAppTemplate

@admin.register(WhatsAppMessageLog)
class WhatsAppMessageLogAdmin(admin.ModelAdmin):
    list_display  = ("created_at", "to_number", "template", "status", "wa_message_id")
    search_fields = ("to_number", "template", "wa_message_id", "status", "error_text")
    list_filter   = ("status", "template", "direction")
    readonly_fields = ("created_at", "delivered_at", "read_at", "payload", "error_text")

@admin.register(WhatsAppSettings)
class WhatsAppSettingsAdmin(admin.ModelAdmin):
    list_display = ("singleton_id", "enabled", "lang", "use_db_templates", "updated_at")
    readonly_fields = ("singleton_id",)

@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "template_name", "active", "updated_at")
    list_editable = ("template_name", "active")
    list_filter = ("active","key")
