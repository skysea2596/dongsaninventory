from django.urls import path
from inventory.views.kiosk import kiosk_input, kiosk_input_ajax
from inventory.views.stock import add_stock, inventory_status, inventory_history, add_stock_ajax
from inventory.views.pending import (
    paste_table_upload, pending_stock_list, get_batch_items,
    process_pending_stock, update_pending_quantities, cancel_pending_stock
)
from inventory.views.api import get_variants_by_item, add_item_ajax, cancel_out_log
from inventory.views.export import export_inventory_log

urlpatterns = [
    path('', kiosk_input, name='kiosk_input'),
    path('status/', inventory_status, name='inventory_status'),
    path('history/', inventory_history, name='inventory_history'),
    path('add/', add_stock, name='add_stock'),
    path('add_stock_ajax/', add_stock_ajax, name='add_stock_ajax'),
    path('add-item-ajax/', add_item_ajax, name='add_item_ajax'),
    path('export/', export_inventory_log, name='export_inventory_log'),

    # ✅ 입고 대기 관련
    path('pending_stock/paste/', paste_table_upload, name='paste_table_upload'),
    path('pending_stock/', pending_stock_list, name='pending_stock_list'),
    path('pending_stock/<int:batch_id>/items/', get_batch_items, name='get_batch_items'),
    path('pending_stock/<int:batch_id>/process/', process_pending_stock, name='process_pending_stock'),
    path('pending_stock/update_quantities/', update_pending_quantities, name='update_pending_quantities'),
    path('pending_stock/<int:batch_id>/cancel/', cancel_pending_stock, name='cancel_pending_stock'),

    # 기타
    path('history/cancel/<int:log_id>/', cancel_out_log, name='cancel_out_log'),
    path('kiosk_input_ajax/', kiosk_input_ajax, name='kiosk_input_ajax'),
]
