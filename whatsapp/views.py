import json
from django.conf import settings as djsettings
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from .services import send_template_ext, apply_status, is_configured
from .utils import to_e164
from .models import WhatsAppMessageLog, WhatsAppSettings, WhatsAppTemplate, TEMPLATE_KEYS
from .forms import WhatsAppSettingsForm, WhatsAppTemplateForm
from .helpers import get_template_name, get_lang

@staff_member_required
def dashboard(request):
    stats = {
        "total": WhatsAppMessageLog.objects.count(),
        "sent": WhatsAppMessageLog.objects.filter(status="sent").count(),
        "failed": WhatsAppMessageLog.objects.filter(status="failed").count(),
        "delivered": WhatsAppMessageLog.objects.filter(status="delivered").count(),
        "read": WhatsAppMessageLog.objects.filter(status="read").count(),
    }
    latest = WhatsAppMessageLog.objects.order_by("-created_at")[:10]
    return render(request, "whatsapp/dashboard.html", {"stats": stats, "latest": latest, "configured": is_configured(), "enabled": WhatsAppSettings.get_solo().enabled})

@csrf_exempt
def webhook(request):
    if request.method == "GET":
        if request.GET.get("hub.verify_token") == getattr(djsettings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", ""):
            return HttpResponse(request.GET.get("hub.challenge",""))
        return HttpResponseForbidden("Bad verify token")
    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            entries = payload.get("entry", [])
            for e in entries:
                for ch in e.get("changes", []):
                    val = ch.get("value", {})
                    for st in val.get("statuses", []):
                        wa_id = st.get("id") or st.get("message_id")
                        status = st.get("status")
                        apply_status(wa_id, status)
        except Exception:
            pass
        return JsonResponse({"ok": True})

@staff_member_required
def test_send(request):
    if not is_configured():
        return JsonResponse({"error":"Not configured"}, status=500)

    to_raw = request.GET.get("to")
    use_raw = request.GET.get("raw") == "1"
    tpl = request.GET.get("tpl") or "hello_world"  # ← default as in Meta example
    lang = request.GET.get("lang") or get_lang() or "en_US"

    # Body vars (?vars=a,b,c)
    vars_raw = request.GET.get("vars", "").strip()
    body_vars = [x for x in vars_raw.split(",")] if vars_raw else []

    # Header vars (?header=h1,h2)
    header_raw = request.GET.get("header", "").strip()
    header_vars = [x for x in header_raw.split(",")] if header_raw else []

    # URL buttons (?btn0=XXX&btn1=YYY)
    button_url_vars = []
    for i in range(3):
        v = request.GET.get(f"btn{i}", "").strip()
        if v:
            button_url_vars.append(v)

    if not (to_raw and tpl):
        return JsonResponse({"error":"params: ?to=+7...&tpl=name[&lang=en_US][&vars=a,b,c][&header=h1][&btn0=u0][&raw=1]"}, status=400)

    to_final = to_raw.strip() if use_raw else to_e164(to_raw, allow_bypass=True)

    log = send_template_ext(to_final, tpl, lang, body_vars=body_vars, header_vars=header_vars, button_url_vars=button_url_vars)
    return JsonResponse({"status": log.status, "id": log.wa_message_id, "to": to_final, "error": log.error_text})

@staff_member_required
def logs(request):
    qs = WhatsAppMessageLog.objects.all()
    q = request.GET.get("q","").strip()
    if q:
        qs = qs.filter(to_number__icontains=q)
    p = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "whatsapp/log_list.html", {"page": p, "q": q, "configured": is_configured(), "enabled": WhatsAppSettings.get_solo().enabled})

@staff_member_required
def settings_view(request):
    s = WhatsAppSettings.get_solo()
    if request.method == "POST":
        form = WhatsAppSettingsForm(request.POST, instance=s)
        if form.is_valid():
            form.save()
            return redirect("whatsapp_settings")
    else:
        form = WhatsAppSettingsForm(instance=s)

    env_state = {
        "configured": is_configured(), "enabled": WhatsAppSettings.get_solo().enabled,
        "phone_number_id": getattr(djsettings, "WHATSAPP_PHONE_NUMBER_ID","") or "—",
        "access_token_set": bool(getattr(djsettings, "WHATSAPP_ACCESS_TOKEN","")),
    }
    return render(request, "whatsapp/settings.html", {"form": form, "env": env_state})

@staff_member_required
def templates_view(request):
    existing = {x.key for x in WhatsAppTemplate.objects.all()}
    for k,_ in TEMPLATE_KEYS:
        if k not in existing:
            from .helpers import get_template_name
            WhatsAppTemplate.objects.create(key=k, template_name=get_template_name(k), active=True)

    if request.method == "POST":
        for k,_ in TEMPLATE_KEYS:
            name = request.POST.get(f"name__{k}","").strip()
            active = request.POST.get(f"active__{k}") == "on"
            obj = WhatsAppTemplate.objects.filter(key=k).first()
            if obj:
                obj.template_name = name
                obj.active = active
                obj.save(update_fields=["template_name","active"])
        return redirect("whatsapp_templates")

    rows = list(WhatsAppTemplate.objects.order_by("key"))
    return render(request, "whatsapp/templates.html", {"rows": rows, "keys": dict(TEMPLATE_KEYS)})
