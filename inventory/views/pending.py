# inventory/views/pending.py
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.utils.timezone import localtime, now
from ..models import PendingStockBatch, PendingStockItem, ProductVariant, InventoryLog, Item, Spec, InventoryUser
from django.utils.dateparse import parse_date
from collections import defaultdict
import json
from ..services.inventory import process_stock_in
from django.core.exceptions import ValidationError

def paste_table_upload(request):
    if request.method == 'POST':
        json_data = request.POST.get('json_data', '')
        try:
            rows = json.loads(json_data)
        except json.JSONDecodeError:
            messages.error(request, "❌ 잘못된 데이터 형식입니다.")
            return redirect('paste_table_upload')

        grouped = defaultdict(list)
        error_lines = []
        for idx, row in enumerate(rows, start=1):
            if not any(row):
                continue
            if len(row) != 5:
                error_lines.append(f"{idx}행: 열 개수 오류")
                continue
            date_str, supplier, item_name, spec_label, qty_str = row
            if not (date_str and supplier and item_name and spec_label and qty_str):
                error_lines.append(f"{idx}행: 누락된 값이 있음")
                continue
            try:
                quantity = int(qty_str)
                if quantity <= 0:
                    error_lines.append(f"{idx}행: 수량이 1 미만")
                    continue
                date = parse_date(date_str)
                if not date:
                    error_lines.append(f"{idx}행: 날짜 형식 오류")
                    continue
            except:
                error_lines.append(f"{idx}행: 수량 또는 날짜 파싱 오류")
                continue
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
                variant = ProductVariant.objects.get(item=item, spec=spec)
            except ProductVariant.DoesNotExist:
                error_lines.append(f"{idx}행: 품목 '{item_name}'에 규격 '{spec_label}' 연결 안 됨")
                continue
            grouped[(date, supplier)].append((item, spec, quantity))

        if error_lines:
            messages.error(request, "입고 대기 등록 실패.\n" + "\n".join(error_lines))
            return redirect('paste_table_upload')

        for (date, supplier), items in grouped.items():
            batch = PendingStockBatch.objects.create(supplier=supplier, uploaded_at=date)
            for item, spec, quantity in items:
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
    return JsonResponse({'batch_id': batch.id, 'supplier': batch.supplier, 'items': data})


def process_pending_stock(request, batch_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})

    batch = get_object_or_404(PendingStockBatch, id=batch_id, status='PENDING')
    try:
        data = json.loads(request.body)
        new_quantities = data.get('quantities', [])
    except:
        return JsonResponse({'success': False, 'message': '데이터 파싱 오류'})

    # ✅ system 사용자 불러오기 (없으면 생성)
    system_user, _ = InventoryUser.objects.get_or_create(name="system")

    update_map = {int(entry["id"]): int(entry["qty"]) for entry in new_quantities if int(entry["qty"]) > 0}
    entries = list(batch.items.select_related('item', 'spec'))
    db_ids = [entry.id for entry in entries if entry.id in update_map]

    if len(db_ids) != len(update_map):
        return JsonResponse({
            'success': False,
            'message': f'❌ 전송된 항목 수와 실제 항목 수가 일치하지 않습니다. (전송 {len(update_map)}건, 매칭된 {len(db_ids)}건)'
        })

    # ✅ 트랜잭션으로 안정성 확보
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
                return JsonResponse({'success': False, 'message': f"❌ {ve}"})

        batch.status = 'DONE'
        batch.processed_at = now()
        batch.processed_by = system_user
        batch.save()

    return JsonResponse({'success': True, 'message': f"✅ '{batch.supplier}' 입고건이 처리되었습니다."})

def update_pending_quantities(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            batch_id = data.get('batch_id')
            updates = data.get('updates', [])
            if not isinstance(updates, list):
                raise ValueError("updates는 리스트여야 합니다.")

            batch = PendingStockBatch.objects.get(id=batch_id, status='PENDING')
            update_map = {int(u['id']): int(u['quantity']) for u in updates}

            entries = batch.items.all()
            for entry in entries:
                if entry.id not in update_map:
                    return JsonResponse({'success': False, 'message': f"ID {entry.id} 수량 누락"})
                quantity = update_map[entry.id]
                if quantity <= 0:
                    return JsonResponse({'success': False, 'message': '수량은 1 이상이어야 합니다.'})
                entry.quantity = quantity
                entry.save()

            return JsonResponse({'success': True, 'message': '✅ 수량이 수정되었습니다.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'오류: {str(e)}'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})

def cancel_pending_stock(request, batch_id):
    batch = get_object_or_404(PendingStockBatch, id=batch_id, status='PENDING')
    batch.status = 'CANCELED'
    batch.save()
    return JsonResponse({'success': True, 'message': '❌ 입고 대기 건이 취소되었습니다.'})
