from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.contrib import messages
from ..models import ProductVariant, InventoryLog, InventoryUser, UsageCategory, Item
from ..utils import build_variant_map
from django.core.serializers.json import DjangoJSONEncoder
import json
from django.core.exceptions import ValidationError
from ..services.inventory import process_stock_in
from django.http import JsonResponse
from django.views.decorators.http import require_POST

def add_stock(request):
    categories = UsageCategory.objects.all()
    selected_category = request.GET.get('category')
    users = InventoryUser.objects.exclude(name="system")

    variants = ProductVariant.objects.select_related('item', 'spec', 'item__category') \
        .order_by('item__name', 'spec__label')

    if selected_category and selected_category != 'all':
        variants = variants.filter(item__category__id=selected_category)

    if request.method == 'POST':
        variant_ids = request.POST.getlist('variant_ids')
        quantities = request.POST.getlist('quantities')

        if not variant_ids or not quantities or len(variant_ids) != len(quantities):
            messages.error(request, "❌ 잘못된 요청입니다.")
            return redirect('add_stock')

        for variant_id, qty_str in zip(variant_ids, quantities):
            try:
                quantity = int(qty_str)
                if quantity <= 0:
                    continue
                variant = ProductVariant.objects.get(id=variant_id)
                process_stock_in(variant, quantity)
            except Exception as e:
                messages.error(request, f"❌ 오류 발생: {e}")
                continue

        messages.success(request, "✅ 입고가 완료되었습니다.")
        return redirect('add_stock')

    item_ids = variants.values_list('item_id', flat=True).distinct()
    items = Item.objects.filter(id__in=item_ids).order_by('name')
    variant_map = build_variant_map(variants)

    return render(request, 'inventory/add_stock.html', {
        'variants': variants,
        'items': items,
        'categories': categories,
        'selected_category': selected_category,
        'users': users,
        'page_title': '📥 입고 추가',
        'variant_json': json.dumps(variant_map, cls=DjangoJSONEncoder)
    })

def inventory_status(request):
    category_id = request.GET.get('category')
    show_low_stock = request.GET.get('low_stock') == '1'
    query = request.GET.get('q', '')

    variants = ProductVariant.objects.select_related('item', 'spec', 'item__category')

    if category_id:
        variants = variants.filter(item__category_id=category_id)

    if show_low_stock:
        variants = variants.filter(current_quantity__lt=F('min_quantity'))

    if query:
        variants = variants.filter(
            Q(item__name__icontains=query) |
            Q(item__description__icontains=query) |
            Q(spec__label__icontains=query)  # ✅ ForeignKey 경로 수정
        )

    categories = UsageCategory.objects.all()
    context = {
        'variants': variants,
        'categories': categories,
        'selected_category': category_id,
        'show_low_stock': show_low_stock,
        'q': query,
    }
    return render(request, 'inventory/inventory_status.html', context)

def inventory_history(request):
    filter_type = request.GET.get('type')
    user_id = request.GET.get('user')
    variant_id = request.GET.get('variant')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    logs = InventoryLog.objects.select_related('user', 'variant', 'variant__item', 'variant__spec').order_by('-timestamp')

    if filter_type in ['IN', 'OUT']:
        logs = logs.filter(type=filter_type)
    if user_id:
        logs = logs.filter(user__id=user_id)
    if variant_id:
        logs = logs.filter(variant__id=variant_id)
    if start_date:
        logs = logs.filter(timestamp__date__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__date__lte=end_date)

    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'inventory/inventory_history.html', {
        'logs': page_obj,
        'filter_type': filter_type,
        'page_obj': page_obj,
        'users': InventoryUser.objects.all(),
        'selected_user': user_id,
        'selected_variant': variant_id,
        'variants': ProductVariant.objects.select_related('item', 'spec'),
        'start_date': start_date,
        'end_date': end_date,
    })

@require_POST
def add_stock_ajax(request):
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

            # ✅ 입고 처리 함수 호출
            process_stock_in(variant, quantity, user)

        except ValidationError as ve:
            errors.append(str(ve))
        except ProductVariant.DoesNotExist:
            errors.append(f"{variant_id}: 품목을 찾을 수 없습니다.")
        except Exception as e:
            errors.append(f"{variant_id}: 오류 발생 - {e}")

    if errors:
        return JsonResponse({'success': False, 'message': "\n".join(errors)})

    return JsonResponse({'success': True, 'message': "✅ 입고 처리가 완료되었습니다."})