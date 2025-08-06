from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from ..models import ProductVariant, InventoryLog, InventoryUser, UsageCategory, Item
from ..utils import build_variant_map
from ..services.inventory import process_stock_out
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError
import json

def kiosk_input(request):
    users = InventoryUser.objects.exclude(name="system")
    categories = UsageCategory.objects.all()
    selected_category = request.GET.get('category')

    if selected_category and selected_category != "all":
        variants = ProductVariant.objects.select_related('item', 'spec', 'item__category') \
            .filter(item__category_id=selected_category) \
            .order_by('item__name', 'spec__label')
    else:
        variants = ProductVariant.objects.select_related('item', 'spec', 'item__category') \
            .order_by('item__name', 'spec__label')

    if request.method == 'POST':
        user_id = request.POST.get('user')
        variant_ids = request.POST.getlist('variant_ids')
        quantities = request.POST.getlist('quantities')

        user = InventoryUser.objects.get(id=user_id)

        if not variant_ids or not quantities:
            messages.error(request, "❌ 소모할 품목과 수량을 입력해주세요.")
            return redirect('kiosk_input')

        for variant_id, qty in zip(variant_ids, quantities):
            try:
                quantity = int(qty)
                variant = ProductVariant.objects.get(id=variant_id)
                process_stock_out(variant, quantity, user)
            except ValidationError as ve:
                messages.error(request, f"❌ {ve}")
                return redirect('kiosk_input')
            except Exception as e:
                messages.error(request, f"❌ 오류: {e}")
                return redirect('kiosk_input')

        messages.success(request, "✅ 선택한 품목이 성공적으로 소모 처리되었습니다.")
        return redirect('kiosk_input')

    variant_map = build_variant_map(variants)
    item_ids = variants.values_list('item_id', flat=True).distinct()
    items = Item.objects.filter(id__in=item_ids).order_by('name')

    return render(request, 'inventory/kiosk_input.html', {
        'users': users,
        'variants': variants,
        'items': items,
        'categories': categories,
        'selected_category': selected_category,
        'page_title': '🔧 소모 입력',
        'variant_json': json.dumps(variant_map, cls=DjangoJSONEncoder)
    })


@require_POST
def kiosk_input_ajax(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '❌ 데이터 형식이 잘못되었습니다.'})

    user_id = data.get('user')
    variants = data.get('variants', [])

    if not user_id or not variants:
        return JsonResponse({'success': False, 'message': '❌ 사용자 또는 품목이 누락되었습니다.'})

    try:
        user = InventoryUser.objects.get(id=user_id)
    except InventoryUser.DoesNotExist:
        return JsonResponse({'success': False, 'message': '❌ 유효하지 않은 사용자입니다.'})

    errors = []
    for entry in variants:
        variant_id = entry.get('id')
        quantity = entry.get('qty')
        if not variant_id or not quantity:
            errors.append("항목 정보가 부족합니다.")
            continue

        try:
            quantity = int(quantity)
            variant = ProductVariant.objects.get(id=variant_id)
            process_stock_out(variant, quantity, user)
        except ValidationError as ve:
            errors.append(str(ve))
        except ProductVariant.DoesNotExist:
            errors.append(f"{variant_id}: 품목을 찾을 수 없습니다.")
        except Exception as e:
            errors.append(f"{variant_id}: 오류 발생 - {e}")

    if errors:
        return JsonResponse({'success': False, 'message': "\n".join(errors)})

    return JsonResponse({'success': True, 'message': "✅ 소모 처리가 완료되었습니다."})