from django.urls import path
from .views import ContractView

app_name = "contracts"

urlpatterns = [
    path("order/<int:order_id>/", ContractView.as_view(), name="order"),
]
