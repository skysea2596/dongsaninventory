from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect
from ..models import ProductVariant, InventoryLog, UsageCategory, Spec, Item, InventoryUser
from ..services.inventory import process_stock_out
from django.core.exceptions import ValidationError
import json

def get_variants_by_item(request, item_id):
    variants = ProductVariant.objects.filter(item_id=item_id).select_related('spec')
    data = [{'id': variant.id, 'spec_name': variant.spec.label} for variant in variants]
    return JsonResponse({'variants': data})

@csrf_exempt
def add_item_ajax(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        specs = data.get('specs')
        category_id = data.get('category_id')

        if not name or not specs or not category_id:
            return JsonResponse({'success': False, 'message': '입력 값이 누락되었습니다.'})

        try:
            category_id = int(category_id)  # 🔸 문자열로 받은 카테고리 ID를 정수로 변환
        except ValueError:
            return JsonResponse({'success': False, 'message': '유효하지 않은 카테고리 ID입니다.'})

        item, created = Item.objects.get_or_create(
            name=name,
            category_id=category_id,
            defaults={'description': None}
        )

        existing_specs = set(
            ProductVariant.objects.filter(item=item).values_list('spec__label', flat=True)
        )
        for label in [s.strip() for s in specs.split(',') if s.strip() and s.strip() not in existing_specs]:
            spec_obj, _ = Spec.objects.get_or_create(label=label)
            ProductVariant.objects.create(item=item, spec=spec_obj, current_quantity=0, min_quantity=0)

        return JsonResponse({
            'success': True,
            'item_id': item.id,
            'variants': list(ProductVariant.objects.filter(item=item)
                .select_related('spec')
                .values('id', 'spec__label'))
        })

    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})

@require_POST
def cancel_out_log(request, log_id):
    log = get_object_or_404(InventoryLog, id=log_id, type='OUT')
    variant = log.variant

    variant.current_quantity += log.quantity
    variant.save()

    log.delete()
    return redirect('inventory_history')