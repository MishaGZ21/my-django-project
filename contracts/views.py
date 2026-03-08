from django.views.generic import TemplateView
from django.utils import timezone

from .services import get_order_aggregate


class ContractView(TemplateView):
    """
    Просмотр договора / бланка заказа.

    URL: /contracts/order/<order_id>/
    Параметры:
      ?pdf=1  — включает компактный режим для печати / сохранения в PDF.
    """
    template_name = "contracts/contract.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        order_id = int(kwargs.get("order_id"))
        order = get_order_aggregate(order_id)

        ctx["order"] = order
        ctx["today"] = timezone.localdate()
        ctx["ui_version"] = "v3.6.1"

        # ?pdf=1 — компактный режим для печати (A4)
        ctx["pdf_mode"] = self.request.GET.get("pdf") == "1"

        # Пока показываем кнопку печати всегда.
        # Если позже понадобится логика "есть сохранённая спецификация" —
        # сюда можно добавить реальную проверку.
        ctx["show_print_button"] = True

        # Тексты в шапке (можно переопределять из других мест)
        ctx.setdefault(
            "header_left_lines",
            [
                "8 (778) 533-00-33",
                "8 (701) 65-888-59",
                "8 (7172) 20-06-73",
            ],
        )
        ctx.setdefault(
            "header_right_lines",
            [
                "г. Астана,",
                "Толстого 22 А.",
                "wooddecor.kz",
            ],
        )

        return ctx
