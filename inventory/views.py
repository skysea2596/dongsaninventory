from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Q, Sum, ExpressionWrapper, IntegerField
from django.utils.dateparse import parse_date
from django.utils.timezone import localtime, now
from django.core.serializers.json import DjangoJSONEncoder
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from .forms import UsageStatForm

import json
import pandas as pd

# models/services/utils import (앱 경로에 맞게 수정)
from .models import (
    ProductVariant, InventoryLog, InventoryUser, UsageCategory, Item,
    PendingStockBatch, PendingStockItem, Spec
)
from .services.inventory import process_stock_in, process_stock_out
from .utils import (
    build_variant_map, response_success, response_error, safe_int, require_fields,
    extract_json, get_object_or_error, batch_process_stock, apply_filters,
    dataframe_to_excel_response, parse_grouped_rows
)

# === 기본 정보/품목 ajax ===
def get_variants_by_item(request, item_id):
    variants = ProductVariant.objects.filter(item_id=item_id).select_related('spec')
    data = [{'id': variant.id, 'spec_name': variant.spec.label} for variant in variants]
    return response_success({'variants': data})

@csrf_exempt
def add_item_ajax(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        required = require_fields(data, ['name', 'specs', 'category_id'])
        if required:
            return required

        category_id, err = safe_int(data.get('category_id'), "유효하지 않은 카테고리 ID입니다.")
        if err:
            return response_error(err)

        name = data.get('name')
        specs = data.get('specs')

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

        variants = list(ProductVariant.objects.filter(item=item)
                .select_related('spec')
                .values('id', 'spec__label'))

        return response_success({'item_id': item.id, 'variants': variants})

    return response_error('잘못된 요청입니다.')

@require_POST
def cancel_out_log(request, log_id):
    log = get_object_or_404(InventoryLog, id=log_id, type='OUT')
    variant = log.variant

    variant.current_quantity += log.quantity
    variant.save()
    log.delete()
    return redirect('inventory_history')


# === 입출고 엑셀/리스트 다운로드 ===
def export_inventory_log(request):
    logs = InventoryLog.objects.select_related('variant__item', 'variant__spec', 'user')
    field_map = {
        'type': lambda qs, v: qs.filter(type=v) if v in ['IN', 'OUT'] else qs,
        'user': 'user_id',
        'variant': 'variant_id',
        'start_date': lambda qs, v: qs.filter(timestamp__date__gte=parse_date(v)),
        'end_date': lambda qs, v: qs.filter(timestamp__date__lte=parse_date(v)),
    }
    logs = apply_filters(logs, request, field_map)
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
    return dataframe_to_excel_response(df, "입출고내역_다운로드.xlsx")


# === kiosk 소모 입력/출고 ===
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

        user, err = get_object_or_error(InventoryUser, user_id, "유효하지 않은 사용자입니다.")
        if err:
            messages.error(request, f"❌ {err}")
            return redirect('kiosk_input')

        if not variant_ids or not quantities:
            messages.error(request, "❌ 소모할 품목과 수량을 입력해주세요.")
            return redirect('kiosk_input')

        for variant_id, qty in zip(variant_ids, quantities):
            quantity, err = safe_int(qty)
            if err:
                messages.error(request, f"❌ {err}")
                return redirect('kiosk_input')
            variant, err = get_object_or_error(ProductVariant, variant_id, "품목을 찾을 수 없습니다.")
            if err:
                messages.error(request, f"❌ {err}")
                return redirect('kiosk_input')
            try:
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
    data, err = extract_json(request)
    if err:
        return response_error(err)

    user_id = data.get('user')
    variants = data.get('variants', [])

    if not user_id or not variants:
        return response_error('❌ 사용자 또는 품목이 누락되었습니다.')

    user, err = get_object_or_error(InventoryUser, user_id, "❌ 유효하지 않은 사용자입니다.")
    if err:
        return response_error(err)

    errors = batch_process_stock(ProductVariant, process_stock_out, variants, user, is_in=False)
    if errors:
        return response_error("\n".join(errors))

    return response_success("✅ 소모 처리가 완료되었습니다.")


# === 입고(add stock), 재고 현황, 입출고 이력 ===
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
            quantity, err = safe_int(qty_str)
            if err or quantity <= 0:
                continue
            variant, err = get_object_or_error(ProductVariant, variant_id, "품목을 찾을 수 없습니다.")
            if err:
                messages.error(request, f"❌ {err}")
                continue
            try:
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
            Q(spec__label__icontains=query)
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
    data, err = extract_json(request)
    if err:
        return response_error(err)

    user_id = data.get('user')
    variants = data.get('variants', [])

    if not user_id or not variants:
        return response_error('❌ 사용자 또는 품목이 누락되었습니다.')

    user, err = get_object_or_error(InventoryUser, user_id, "❌ 유효하지 않은 사용자입니다.")
    if err:
        return response_error(err)

    errors = batch_process_stock(ProductVariant, process_stock_in, variants, user, is_in=True)
    if errors:
        return response_error("\n".join(errors))

    return response_success("✅ 입고 처리가 완료되었습니다.")


# === pending (입고 대기) ===
def paste_table_upload(request):
    if request.method == 'POST':
        json_data = request.POST.get('json_data', '')
        try:
            rows = json.loads(json_data)
        except json.JSONDecodeError:
            messages.error(request, "❌ 잘못된 데이터 형식입니다.")
            return redirect('paste_table_upload')

        grouped, error_lines = parse_grouped_rows(rows)
        for (date, supplier), items in grouped.items():
            for (item_name, spec_label, quantity, idx) in items:
                try:
                    item = Item.objects.get(name=item_name.strip())
                except Item.DoesNotExist:
                    error_lines.append(f"{idx}행: 품목명 '{item_name}' 존재하지 않음")
                    continue
                try:
                    spec = Spec.objects.get(label=spec_label.strip())
                except Spec.DoesNotExist:
                    error_lines.append(f"{idx}행: 규격 '{spec_label}' 존재하지 않음")
                    continue
                try:
                    ProductVariant.objects.get(item=item, spec=spec)
                except ProductVariant.DoesNotExist:
                    error_lines.append(f"{idx}행: 품목 '{item_name}'에 규격 '{spec_label}' 연결 안 됨")
                    continue
        if error_lines:
            messages.error(request, "입고 대기 등록 실패.\n" + "\n".join(error_lines))
            return redirect('paste_table_upload')

        # 정상 데이터 batch로 저장
        for (date, supplier), items in grouped.items():
            batch = PendingStockBatch.objects.create(supplier=supplier, uploaded_at=date)
            for (item_name, spec_label, quantity, idx) in items:
                item = Item.objects.get(name=item_name.strip())
                spec = Spec.objects.get(label=spec_label.strip())
                PendingStockItem.objects.create(batch=batch, item=item, spec=spec, quantity=quantity)

        messages.success(request, "✅ 입고 대기 등록이 완료되었습니다.")
        return redirect('pending_stock_list')

    return render(request, 'inventory/paste_pending_stock.html')

def pending_stock_list(request):
    pending_batches = PendingStockBatch.objects.filter(status='PENDING').order_by('-uploaded_at')
    done_batches = PendingStockBatch.objects.filter(status='DONE').order_by('-uploaded_at')

    for batch in pending_batches:
        batch.formatted_date = localtime(batch.uploaded_at).strftime('%Y.%m.%d')
    for batch in done_batches:
        batch.formatted_date = localtime(batch.uploaded_at).strftime('%Y.%m.%d')

    return render(request, 'inventory/pending_stock_list.html', {
        'pending_batches': pending_batches,
        'done_batches': done_batches,
    })
    
def pending_stock_items(request, batch_id):
    try:
        batch = PendingStockBatch.objects.get(id=batch_id)
    except PendingStockBatch.DoesNotExist:
        return JsonResponse({"error": "입고 대기건을 찾을 수 없습니다."}, status=404)

    items = PendingStockItem.objects.filter(batch=batch)
    data = {
        "supplier": batch.supplier,
        "items": [
            {
                "id": item.id,
                "item": item.item.name,
                "spec_label": item.spec.label,
                "quantity": item.quantity,
            }
            for item in items
        ]
    }
    return JsonResponse(data)

def get_batch_items(request, batch_id):
    batch = get_object_or_404(PendingStockBatch, id=batch_id)
    items = batch.items.select_related('item', 'spec')
    data = [
        {
            'id': i.id,
            'item': f"{i.item.name} - {i.spec.label}",
            'quantity': i.quantity
        }
        for i in items
    ]
    return response_success({'batch_id': batch.id, 'supplier': batch.supplier, 'items': data})

def process_pending_stock(request, batch_id):
    if request.method != 'POST':
        return response_error('잘못된 요청입니다.')

    batch = get_object_or_404(PendingStockBatch, id=batch_id, status='PENDING')
    data, err = extract_json(request)
    if err:
        return response_error('데이터 파싱 오류')
    new_quantities = data.get('quantities', [])

    system_user, _ = InventoryUser.objects.get_or_create(name="system")
    update_map = {int(entry["id"]): int(entry["qty"]) for entry in new_quantities if int(entry["qty"]) > 0}
    entries = list(batch.items.select_related('item', 'spec'))
    db_ids = [entry.id for entry in entries if entry.id in update_map]

    if len(db_ids) != len(update_map):
        return response_error(
            f'❌ 전송된 항목 수와 실제 항목 수가 일치하지 않습니다. (전송 {len(update_map)}건, 매칭된 {len(db_ids)}건)'
        )

    with transaction.atomic():
        for entry in entries:
            new_qty = update_map.get(entry.id)
            if not new_qty:
                continue
            entry.quantity = new_qty
            entry.save()
            try:
                variant = ProductVariant.objects.get(item=entry.item, spec=entry.spec)
                process_stock_in(variant, new_qty, user=system_user)
            except ProductVariant.DoesNotExist:
                continue
            except ValidationError as ve:
                return response_error(f"❌ {ve}")

        batch.status = 'DONE'
        batch.processed_at = now()
        batch.processed_by = system_user
        batch.save()

    return response_success(f"✅ '{batch.supplier}' 입고건이 처리되었습니다.")

def update_pending_quantities(request):
    if request.method == 'POST':
        data, err = extract_json(request)
        if err:
            return response_error('데이터 파싱 오류')
        batch_id = data.get('batch_id')
        updates = data.get('updates', [])
        if not isinstance(updates, list):
            return response_error("updates는 리스트여야 합니다.")

        batch = PendingStockBatch.objects.get(id=batch_id, status='PENDING')
        update_map = {int(u['id']): int(u['quantity']) for u in updates}

        entries = batch.items.all()
        for entry in entries:
            if entry.id not in update_map:
                return response_error(f"ID {entry.id} 수량 누락")
            quantity = update_map[entry.id]
            if quantity <= 0:
                return response_error('수량은 1 이상이어야 합니다.')
            entry.quantity = quantity
            entry.save()

        return response_success('✅ 수량이 수정되었습니다.')
    return response_error('잘못된 요청입니다.')

def cancel_pending_stock(request, batch_id):
    batch = get_object_or_404(PendingStockBatch, id=batch_id, status='PENDING')
    batch.status = 'CANCELED'
    batch.save()
    return response_success('❌ 입고 대기 건이 취소되었습니다.')

def usage_stat_view(request):
    # 사용자, 품목+규격 목록 (폼 드롭다운용)
    user_choices = [(str(u.id), u.name) for u in InventoryUser.objects.exclude(name="system")]
    variant_choices = [(str(v.id), f"{v.item.name} - {v.spec.label}") for v in ProductVariant.objects.select_related('item', 'spec')]

    form = UsageStatForm(request.GET or None, user_choices=user_choices, variant_choices=variant_choices)

    stats = []
    total_amount = 0

    if form.is_valid():
        start = form.cleaned_data.get('start_date')
        end = form.cleaned_data.get('end_date')
        user_id = form.cleaned_data.get('user')
        variant_id = form.cleaned_data.get('variant')

        qs = InventoryLog.objects.filter(type='OUT')
        if start:
            qs = qs.filter(timestamp__date__gte=start)
        if end:
            qs = qs.filter(timestamp__date__lte=end)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if variant_id:
            qs = qs.filter(variant_id=variant_id)

        stats_qs = (
            qs.values('variant', 'variant__item__name', 'variant__spec__label', 'variant__unit_price')
            .annotate(
                total_quantity=Sum('quantity'),
                amount=ExpressionWrapper(
                    F('variant__unit_price') * Sum('quantity'),
                    output_field=IntegerField()
                ),
            )
            .order_by('-amount')
        )
        stats = list(stats_qs)
        total_amount = sum(row['amount'] for row in stats)
        
    return render(request, 'inventory/usage_stat.html', {
        'form': form,
        'stats': stats,
        'total_amount': total_amount,
    })
    
def export_usage_stat_excel(request):
    # 기존 통계 쿼리와 동일하게 필터 적용
    start = request.GET.get('start_date')
    end = request.GET.get('end_date')
    user_id = request.GET.get('user')
    variant_id = request.GET.get('variant')

    qs = InventoryLog.objects.filter(type='OUT')
    if start:
        qs = qs.filter(timestamp__date__gte=start)
    if end:
        qs = qs.filter(timestamp__date__lte=end)
    if user_id:
        qs = qs.filter(user_id=user_id)
    if variant_id:
        qs = qs.filter(variant_id=variant_id)

    stats = qs.values(
        'variant__item__name',
        'variant__spec__label',
        'variant__unit_price',
    ).annotate(
        total_quantity=Sum('quantity'),
        amount=ExpressionWrapper(
            F('variant__unit_price') * Sum('quantity'),
            output_field=IntegerField()
        ),
    ).order_by('-amount')

    # 집계 데이터를 pandas DataFrame으로 변환
    data = [
        {
            '품목': row['variant__item__name'],
            '규격': row['variant__spec__label'],
            '단가': row['variant__unit_price'],
            '사용수량': row['total_quantity'],
            '금액': row['amount'],
        }
        for row in stats
    ]
    df = pd.DataFrame(data)
    return dataframe_to_excel_response(df, "품목별소모통계_다운로드.xlsx")