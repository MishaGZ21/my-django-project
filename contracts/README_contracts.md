# Раздел «Договор» — прототип

## Шаги интеграции
1) Добавьте 'contracts' в INSTALLED_APPS:
```python
INSTALLED_APPS += ['contracts']
```
2) Подключите urls в factory_app/factory_app/urls.py:
```python
from django.urls import path, include
urlpatterns = [
    path('admin/', admin.site.urls),
    path('contracts/', include('contracts.urls', namespace='contracts')),
]
```
3) Откройте страницу:
`http://127.0.0.1:8000/contracts/order/1001/`

Данные подтягиваются через `contracts/services.py:get_order_aggregate` (пока заглушки).
