#!/usr/bin/env python3
import argparse, os, re, sys, textwrap

RELPATH = os.path.join("core", "templates", "orders_list.html")

REPLACEMENT = """{% with dl=order.contract.days_left %}
  {% if dl != None %}
    {{ dl }}
  {% else %}
    -
  {% endif %}
{% endwith %}"""

def main():
    ap = argparse.ArgumentParser(description="Fix orders_list.html: replace default_if_none usage with a safe block.")
    ap.add_argument("--project-root", default=".", help="Path to project root (where 'core/' lives). Default: current dir.")
    args = ap.parse_args()

    target = os.path.join(args.project_root, RELPATH)
    if not os.path.exists(target):
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(2)

    with open(target, "r", encoding="utf-8") as f:
        s = f.read()

    changed = False

    # Direct patterns
    patterns = [
        '{{ order.contract.days_left|default_if_none:"-" }}',
        "{{ order.contract.days_left|default_if_none:'-' }}",
    ]
    for pat in patterns:
        if pat in s:
            s = s.replace(pat, REPLACEMENT)
            changed = True

    # Regex fallback
    regex = re.compile(r"\{\{\s*order\.contract\.days_left\s*\|\s*default_if_none\s*:\s*(['\"]).*?\1\s*\}\}")
    if regex.search(s):
        s = regex.sub(REPLACEMENT, s)
        changed = True

    if not changed:
        print("No occurrences found to replace. File unchanged.")
        return 0

    with open(target, "w", encoding="utf-8") as f:
        f.write(s)

    print(f"Patched: {target}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
