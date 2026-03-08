from django import forms
from .models import Order
from .models import Calculation

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            "customer_name",  # Имя
            "last_name",      # Фамилия
            "iin",            # ИИН
            "phone",          # Телефон
            "has_whatsapp",
            "whatsapp_phone",
        ]
        labels = {
            "customer_name": "Имя заказчика",
            "last_name": "Фамилия",
            "iin": "ИИН",
            "phone": "Телефон заказчика",
            "has_whatsapp": "Есть WhatsApp",
            "whatsapp_phone": "Номер WhatsApp",
        }

        

    def clean(self):
        cleaned = super().clean()
        has_whatsapp = cleaned.get("has_whatsapp")
        phone = cleaned.get("phone")
        whatsapp_phone = cleaned.get("whatsapp_phone")

        if not has_whatsapp and not whatsapp_phone:
            raise forms.ValidationError("Введите телефон с WhatsApp, если основной номер без WhatsApp.")
        return cleaned

from .models import PurchaseSheet
from decimal import InvalidOperation
class PurchaseSheetForm(forms.ModelForm):

    
    class Meta:
        model = PurchaseSheet
        fields = "__all__"
        exclude = ["order"]
        tabletop_length_3m = forms.TypedChoiceField(
            choices=[('False','4 м'), ('True','3 м')],
            widget=forms.RadioSelect,
            coerce=lambda v: v=='True',
            required=False
        )
    @staticmethod
    def _parse_int(value, *, required=False, allow_zero=False):
        """
        Разрешаем ТОЛЬКО целые числа.
        - убираем обычные/неразрывные/узкие пробелы;
        - запятая/точка недопустимы (дробные — ошибка).
        """
        if value in (None, ""):
            if required:
                raise InvalidOperation("required")
            return None
        s = str(value).strip()
        s = (s
             .replace(" ", "")
             .replace("\u00A0", "")  # NBSP
             .replace("\u202F", "")) # thin space
        if not s.isdigit():
            raise InvalidOperation("not-integer")
        n = int(s)
        if not allow_zero and n <= 0:
            raise InvalidOperation("gt0")
        return n

    def clean(self):
        cleaned = super().clean()

        for i in range(1, 11):
            name   = cleaned.get(f"lds_name{i}")
            fmt    = cleaned.get(f"lds_format{i}")
            lds    = cleaned.get(f"lds_color{i}")       # ЛДСП (листов)
            pvc    = cleaned.get(f"pvc_color{i}")       # ПВХ (метров, узкая)
            pvcw   = cleaned.get(f"pvc_wide_color{i}")  # ПВХ ШИРОКАЯ (метров) — НЕобязательно
            facade = cleaned.get(f"group{i}_facade")    # bool
            corpus = cleaned.get(f"group{i}_corpus")    # bool

            # строка задействована?
            row_used = any(v not in (None, "", 0, 0.0, False)
                           for v in (name, fmt, lds, pvc, pvcw, facade, corpus))
            if not row_used:
                continue

            # хотя бы одна «пилюля»
            if not (bool(facade) or bool(corpus)):
                msg = "Укажите «ФАСАДЫ» или «КОРПУС»."
                self.add_error(f"group{i}_facade", msg)
                self.add_error(f"group{i}_corpus", msg)

            # обязательные поля
            if not name:
                self.add_error(f"lds_name{i}", "Обязательное поле.")
            if not fmt:
                self.add_error(f"lds_format{i}", "Обязательное поле.")

            # ЛДСП (листов) — целое > 0
            try:
                lds_val = self._parse_int(lds, required=True, allow_zero=False)
            except InvalidOperation as e:
                self.add_error(f"lds_color{i}", "Должно быть целым числом > 0." if str(e) != "not-integer" else "Некорректное число.")
            else:
                cleaned[f"lds_color{i}"] = lds_val

            # ПВХ (метров, узкая) — целое > 0
            try:
                pvc_val = self._parse_int(pvc, required=True, allow_zero=False)
            except InvalidOperation as e:
                self.add_error(f"pvc_color{i}", "Должно быть целым числом > 0." if str(e) in ("required", "gt0") else "Некорректное число.")
            else:
                cleaned[f"pvc_color{i}"] = pvc_val

            # ПВХ ШИРОКАЯ — НЕобязательная; если введено, то целое >= 0
            try:
                pvcw_val = self._parse_int(pvcw, required=False, allow_zero=True)
            except InvalidOperation:
                self.add_error(f"pvc_wide_color{i}", "Некорректное число.")
            else:
                if pvcw_val is not None:
                    cleaned[f"pvc_wide_color{i}"] = pvcw_val

        # «Прочее» (tabletop_count/hdf_count) оставляем необязательным;
        # при желании можно добить проверку целого >=0 аналогично, если нужно.
        return cleaned


class CalculationForm(forms.ModelForm):
    class Meta:
        model = Calculation
        fields = ["countertop_qty", "hdf_qty", "note"]  # добавили количества + заметка
        widgets = {
            "countertop_qty": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "hdf_qty":        forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "note":           forms.Textarea(attrs={"class": "textarea", "rows": 4}),
        }



    class Meta:
        model = PurchaseSheet
        exclude = ["order"]
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        # Если радио не пришло (редкий случай), придерживаемся текущего значения instance
        if 'tabletop_length_3m' not in cleaned or cleaned.get('tabletop_length_3m') is None:
            inst = getattr(self, 'instance', None)
            if inst is not None and hasattr(inst, 'tabletop_length_3m'):
                cleaned['tabletop_length_3m'] = bool(inst.tabletop_length_3m)
        return cleaned

from .models import Contract

class ContractForm(forms.ModelForm):
    class Meta:
        model = Contract
        exclude = ["order"]

class PaymentForm(forms.Form):
    amount_total = forms.DecimalField(label="Обработка материала", max_digits=12, decimal_places=2, required=False)
    amount_design = forms.DecimalField(label="Дизайн проект", max_digits=12, decimal_places=2, required=False)
    amount_facades = forms.DecimalField(label="Фасады", max_digits=12, decimal_places=2, required=False)
    METHODS = (
        ("cash", "Наличные"),
        ("card", "Карта"),
        ("qr", "QR"),
    )
    methods = forms.MultipleChoiceField(
        label="Вид оплаты",
        required=True,
        choices=METHODS,
        widget=forms.CheckboxSelectMultiple
    )

    def clean_methods(self):
        data = self.cleaned_data.get("methods")
        if not data:
            raise forms.ValidationError("Выберите хотя бы один вариант оплаты.")
        return data
