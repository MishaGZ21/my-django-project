import os
import re
import phonenumbers

# Numbers listed here will be sent AS IS (no E.164 normalization).
# .env: WHATSAPP_BYPASS_E164=787016588859,79991234567
_BYPASS = {x.strip() for x in (os.getenv("WHATSAPP_BYPASS_E164", "") or "").split(",") if x.strip()}

def _clean(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[()\s-]+", "", s)
    if s.startswith("00"):
        s = "+" + s[2:]
    return s

def to_e164(raw: str, default_region: str = "KZ", *, allow_bypass: bool = True) -> str:
    s = _clean(raw)
    if allow_bypass and s in _BYPASS:
        return s

    # Common KZ/RU fixes
    if s.startswith("8") and len(s) >= 10:
        s = "+7" + s[1:]
    if s.startswith("+78") and len(s) >= 12:
        s = "+7" + s[3:]
    if s.startswith("78") and not s.startswith("+7"):
        s = "+7" + s[2:]
    if s.startswith("7") and not s.startswith("+7"):
        s = "+" + s

    try:
        n = phonenumbers.parse(s, default_region)
        if phonenumbers.is_valid_number(n):
            return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    return s or (raw or "").strip()
