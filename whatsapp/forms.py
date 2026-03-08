from django import forms
from .models import WhatsAppSettings, WhatsAppTemplate

class WhatsAppSettingsForm(forms.ModelForm):
    class Meta:
        model = WhatsAppSettings
        fields = ("enabled","manager_numbers","lang","use_db_templates")
        widgets = {
            "manager_numbers": forms.Textarea(attrs={"rows":3, "placeholder":"+7701..., +7702..."}),
        }

class WhatsAppTemplateForm(forms.ModelForm):
    class Meta:
        model = WhatsAppTemplate
        fields = ("key","template_name","active")
