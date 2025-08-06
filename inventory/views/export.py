# inventory/views/export.py
from django.http import HttpResponse
from ..models import InventoryLog
from django.utils.dateparse import parse_date
import pandas as pd

def export_inventory_log(request):
    logs = InventoryLog.objects.select_related('variant__item', 'variant__spec', 'user')

    type_filter = request.GET.get('type')
    if type_filter == 'IN':
        logs = logs.filter(type='IN')
    elif type_filter == 'OUT':
        logs = logs.filter(type='OUT')

    user_id = request.GET.get('user')
    if user_id:
        logs = logs.filter(user_id=user_id)

    variant_id = request.GET.get('variant')
    if variant_id:
        logs = logs.filter(variant_id=variant_id)

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        logs = logs.filter(timestamp__date__gte=parse_date(start_date))
    if end_date:
        logs = logs.filter(timestamp__date__lte=parse_date(end_date))

    logs = logs.order_by('-timestamp')

    data = [{
        '일자': log.timestamp.strftime('%Y-%m-%d'),
        '출하창고': '1',
        '담당자': log.user.name if log.user else '',
        '품목코드': log.variant.code or '',
        '품목명': log.variant.item.name,
        '규격': log.variant.spec.label,
        '수량': log.quantity,
        '사용유형': '',
        '적요': '',
    } for log in logs]

    df = pd.DataFrame(data)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=\"입출고내역_다운로드.xlsx\"'
    df.to_excel(response, index=False, engine='openpyxl')
    return response
