from django.urls import path, include
from . import views, views_accounting
from django.conf import settings
from django.conf.urls.static import static




urlpatterns = [
    path('orders/<int:pk>/history/', views.order_history, name='order_history'),
    path("orders/<int:order_id>/calculation/", views.calculation_edit, name="calculation_edit"),
    path("orders/<int:order_id>/payment/", views.payment_view, name="payment_new"),
    path("orders/<int:order_id>/payment/receipt/", views.payment_receipt, name="payment_receipt"),
    path("orders/<int:order_id>/payment/refresh/", views.payment_refresh, name="payment_refresh"),
    path("orders/<int:order_id>/payment/<int:payment_id>/receipt/", views.payment_receipt_id, name="payment_receipt_id"),
    path("orders/chart-row/<int:order_id>/", views.chart_row_get, name="chart_row_get"),
    path("orders/chart-row/<int:order_id>/save/", views.chart_row_save, name="chart_row_save"),


    # Главная / список заказов
    path('', views.orders_all, name='orders_all'),
    path('orders/', views.orders_all, name='orders_all'),

    # Создание нового заказа (совместимость со старым URL — просто открывает модалку)
    path('orders/new/', views.order_new, name='order_new'),

    # Лист закупа
    path('orders/<int:pk>/purchase-sheet/', views.purchase_sheet, name='purchase_sheet'),
    path('orders/<int:pk>/purchase-sheet/pdf/', views.purchase_sheet_pdf, name='purchase_sheet_pdf'),
    path("orders/<int:pk>/main-contract/sign/", views.main_contract_sign_flow, name="main_contract_sign_flow"),
    path("orders/<int:order_id>/main-contract/pdf/", views.main_contract_pdf, name="main_contract_pdf"),
    path("orders/chart-note/save/", views.chart_note_save, name="chart_note_save"),
    path("orders/info/<int:order_id>/", views.order_info_json, name="order_info_json"),




    # Договор
    path('orders/<int:pk>/contract/', views.contract_view, name='contract_view'),
    

    # Диаграммы/данные
    path('orders/chart/', views.orders_chart, name='orders_chart'),
    path('orders/chart-data/', views.orders_chart_data, name='orders_chart_data'),

    # Бухгалтерия
    path("accounting/reports-data/", views_accounting.accounting_reports_data, name="accounting_reports_data"),
    path("accounting/reports-summary/", views_accounting.accounting_reports_summary, name="accounting_reports_summary"),
    path("accounting/reports-designers-data/", views_accounting.accounting_reports_designers_data, name="accounting_reports_designers_data"),
    path("accounting/prices/add/", views_accounting.accounting_price_add, name="accounting_price_add"),
    path("accounting/", views_accounting.accounting, name="accounting"),
    path(
        "accounting/reports/orders-table/",
        views_accounting.accounting_reports_orders_table,
        name="accounting_reports_orders_table",
    ),
    path(
        "accounting/reports/services-summary/",
        views_accounting.accounting_reports_services_summary,
        name="accounting_reports_services_summary",
    ),
    path(
        "accounting/stats/staff/",
        views_accounting.accounting_staff_list,
        name="accounting_staff_list",
    ),
    path(
        "accounting/stats/staff/create/",
        views_accounting.accounting_staff_create,
        name="accounting_staff_create",
    ),
    path(
        "accounting/stats/staff/<int:employee_id>/pay/",
        views_accounting.accounting_staff_pay,
        name="accounting_staff_pay",
    ),
    path(
        "accounting/stats/staff/<int:employee_id>/update/",
        views_accounting.accounting_staff_update,
        name="accounting_staff_update",
    ),
    path(
        "accounting/stats/salary-payments/",
        views_accounting.accounting_salary_payments_list,
        name="accounting_salary_payments_list",
    ),
    path(
        "accounting/stats/staff/advance/",
        views_accounting.accounting_staff_advance_create,
        name="accounting_staff_advance_create",
    ),
    path(
        "accounting/stats/staff/advance-list/",
        views_accounting.accounting_staff_advance_list,
        name="accounting_staff_advance_list",
    ),
    path(
        "accounting/stats/payment/<int:payment_id>/delete/",
        views_accounting.accounting_salary_payment_delete,
        name="accounting_salary_payment_delete",
    ),
    
    
    # Цех / Workshop
    path('workshop/', views.workshop, name='workshop'),
    
    path("warehouse/", views.warehouse, name="warehouse"),
    path("warehouse/accept/start/<int:order_id>/", views.warehouse_start_accept, name="warehouse_start_accept"),
    path("warehouse/accept/<int:receipt_id>/", views.warehouse_accept, name="warehouse_accept"),
    path("warehouse/save-draft/<int:receipt_id>/", views.warehouse_save_draft, name="warehouse_save_draft"),
    
    path("warehouse/accept/add/<int:order_id>/", views.warehouse_start_additional, name="warehouse_start_additional"),
    path("warehouse/receipts-json/<int:order_id>/", views.warehouse_receipts_json, name="warehouse_receipts_json"),
    # PDF отчёт по приёмкам заказа
    path("warehouse/order/<int:order_id>/pdf/", views.warehouse_order_pdf, name="warehouse_order_pdf"),




    
    path("post-login/", views.post_login_redirect, name="post_login_redirect"),
    
    
    path("orders/<int:order_id>/purchase-pdf/", views.purchase_pdf, name="purchase_pdf"),
    
    path("whatsapp/", include("whatsapp.urls")),
    
    path("quick-quote/", views.quick_quote, name="quick_quote"),
    path("quick-quote/history/", views.quick_quote_history, name="quick_quote_history"),
    path("quick-quote/<int:pk>/", views.quick_quote_detail, name="quick_quote_detail"),
    path("quick-quote/<int:pk>/pdf/", views.quick_quote_pdf, name="quick_quote_pdf"),
    path(
        "contracts/order/<int:order_id>/pdf/",
        views.contract_pdf,
        name="contract_pdf",
    ),
    
    path(
        "orders/<int:pk>/main-contract/",
        views.main_contract_view,
        name="main_contract_view",
    ),
    path(
        "contracts/order/<int:order_id>/main-pdf/",
        views.main_contract_pdf,
        name="main_contract_pdf",
    ),
    path(
        "orders/<int:pk>/update-field/<str:field>/",
        views.order_update_field,
        name="order_update_field",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
