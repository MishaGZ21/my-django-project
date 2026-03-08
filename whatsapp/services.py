import requests
from django.conf import settings
from django.utils import timezone
from .models import WhatsAppMessageLog, WhatsAppSettings

API_URL = "https://graph.facebook.com/v22.0/{phone_id}/messages"

def _headers():
    raw = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") or ""
    token = raw.strip().strip('"').strip("'")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

def is_configured() -> bool:
    return bool(getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") and getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", ""))

def send_template_ext(to_value: str, template_name: str, lang: str, *, body_vars=None, header_vars=None, button_url_vars=None):
    # Global kill switch: if disabled in settings, skip sending
    try:
        s = WhatsAppSettings.get_solo()
        if s and not s.enabled:
            log = WhatsAppMessageLog.objects.create(
                direction="out",
                to_number=str(to_value),
                template=str(template_name),
                body="",
                payload={"disabled": True, "reason": "Disabled by settings"},
                status="disabled",
            )
            return log
    except Exception:
        # If settings table not migrated yet, proceed (fail-open)
        pass

    body_vars = body_vars or []
    header_vars = header_vars or []
    button_url_vars = button_url_vars or []

    components = []
    if header_vars:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": str(v)} for v in header_vars]
        })
    if body_vars:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in body_vars]
        })
    for idx, v in enumerate(button_url_vars):
        components.append({
            "type": "button",
            "sub_type": "url",
            "index": str(idx),
            "parameters": [{"type": "text", "text": str(v)}]
        })

    data = {
        "messaging_product": "whatsapp",
        "to": to_value,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            **({"components": components} if components else {})
        }
    }

    log = WhatsAppMessageLog.objects.create(to_number=to_value, template=template_name, payload=data)

    if not is_configured():
        log.status = "failed"
        log.error_text = "WhatsApp is not configured in settings"
        log.save()
        return log

    url = API_URL.format(phone_id=settings.WHATSAPP_PHONE_NUMBER_ID)
    try:
        resp = requests.post(url, json=data, headers=_headers(), timeout=20)
        j = resp.json() if resp.content else {}
        if resp.ok:
            log.status = "sent"
            messages = j.get("messages") or []
            if messages:
                log.wa_message_id = messages[0].get("id", "")
        else:
            log.status = "failed"
            err = j.get("error", {}) if isinstance(j, dict) else {}
            log.error_code = str(err.get("code", ""))
            log.error_text = err.get("message", str(j))
    except Exception as e:
        log.status = "failed"
        log.error_text = str(e)
    finally:
        log.save()
    return log

# Backward-compatible wrapper
def send_template(to_value: str, template_name: str, lang: str, variables: list):
    return send_template_ext(to_value, template_name, lang, body_vars=variables)

def apply_status(wa_message_id: str, status: str):
    """Update message log status from webhook callbacks."""
    if not wa_message_id:
        return
    log = WhatsAppMessageLog.objects.filter(wa_message_id=wa_message_id).first()
    if not log:
        return
    if status:
        log.status = status
        now = timezone.now()
        if status == "delivered":
            log.delivered_at = now
        if status == "read":
            log.read_at = now
        log.save(update_fields=["status", "delivered_at", "read_at"])
