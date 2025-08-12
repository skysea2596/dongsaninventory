import re

def extract_number(label):
    match = re.search(r'\d+', label)
    return int(match.group()) if match else 0

def build_variant_map(variants):
    variant_map = {}
    for variant in variants:
        item_id = str(variant.item.id)
        if item_id not in variant_map:
            variant_map[item_id] = []
        variant_map[item_id].append({
            'id': variant.id,
            'spec_label': variant.spec.label,
            'stock': variant.current_quantity,
            'sort_key': extract_number(variant.spec.label)
        })
    for v_list in variant_map.values():
        v_list.sort(key=lambda x: x['sort_key'])
        for v in v_list:
            v.pop('sort_key')
    return variant_map

# utils.py
from django.http import JsonResponse, HttpResponse

def response_success(message=None, data=None):
    """
    표준 성공 응답 반환
    """
    resp = {'success': True}
    if message:
        resp['message'] = message
    if data is not None:
        resp['data'] = data
    return JsonResponse(resp)

def response_error(message, status=400):
    """
    표준 실패 응답 반환
    """
    return JsonResponse({'success': False, 'message': message}, status=status)

def safe_int(val, errmsg="유효하지 않은 값입니다."):
    """
    안전하게 int 변환 (실패시 에러 메시지 리턴)
    """
    try:
        return int(val), None
    except (TypeError, ValueError):
        return None, errmsg

def require_fields(data, fields):
    """
    필수 필드 누락 검사 (POST/JSON dict, fields: ['name', ...])
    """
    missing = [f for f in fields if not data.get(f)]
    if missing:
        return response_error(f"입력 값이 누락되었습니다: {', '.join(missing)}")
    return None

def extract_json(request):
    """
    request.body → dict (JSONDecodeError 시 에러 메시지)
    """
    import json
    try:
        return json.loads(request.body), None
    except Exception:
        return None, "❌ 데이터 형식이 잘못되었습니다."

def get_object_or_error(model, id, errmsg):
    """
    id로 모델 조회, 없으면 (None, errmsg) 반환
    """
    try:
        return model.objects.get(id=id), None
    except model.DoesNotExist:
        return None, errmsg

def safe_list(val, errmsg="입력 값이 누락되었습니다."):
    """
    리스트 타입 및 비어있음 검사
    """
    if not isinstance(val, list) or not val:
        return None, errmsg
    return val, None

def apply_filters(queryset, request, field_map):
    """
    여러 필터 파라미터를 한 번에 적용
    field_map = {param: 'field' or lambda qs, v: qs.filter(...) }
    """
    for param, f in field_map.items():
        value = request.GET.get(param)
        if value:
            if callable(f):
                queryset = f(queryset, value)
            else:
                queryset = queryset.filter(**{f: value})
    return queryset

def dataframe_to_excel_response(df, filename="export.xlsx"):
    """
    Pandas DataFrame을 엑셀 다운로드로 반환
    """
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    df.to_excel(response, index=False, engine='openpyxl')
    return response

def batch_process_stock(model, func, variant_entries, user, is_in=True):
    """
    입출고(배치) 처리, 반복 에러 메시지 통일
    model: ProductVariant 등
    func: process_stock_in/out
    variant_entries: [{'id': id, 'qty': qty}, ...]
    user: 유저객체
    is_in: 입고/출고 구분 (True: 입고)
    """
    errors = []
    for entry in variant_entries:
        variant_id = entry.get('id')
        quantity = entry.get('qty')
        if not variant_id or not quantity:
            errors.append("항목 정보가 부족합니다.")
            continue
        qty, err = safe_int(quantity)
        if err:
            errors.append(err)
            continue
        try:
            variant = model.objects.get(id=variant_id)
            func(variant, qty, user)
        except Exception as e:
            errors.append(f"{variant_id}: 오류 발생 - {e}")
    return errors

def parse_grouped_rows(rows):
    """
    표 붙여넣기 대량 데이터(행단위) 그룹+검증 (pending.py 등에서 활용)
    """
    from collections import defaultdict
    from django.utils.dateparse import parse_date

    def _norm_supplier(v):
        v = (v or "").strip()
        return v if v else "미지정"

    def _to_int_clean(v):
        s = str(v).replace(',', '').strip()
        return int(s)

    def _normalize_date_str(ds):
        ds = (ds or "").strip()
        if len(ds) == 8 and ds.isdigit():  # YYYYMMDD → YYYY-MM-DD
            return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
        return ds

    grouped = defaultdict(list)
    error_lines = []

    for idx, row in enumerate(rows, start=1):
        if not row or not any(row):
            continue

        if len(row) != 5:
            error_lines.append(f"{idx}행: 열 개수 오류")
            continue

        date_str, supplier, item_name, spec_label, qty_raw = row

        date_str = _normalize_date_str(date_str)
        supplier_norm = _norm_supplier(supplier)
        item_name = (item_name or "").strip()
        spec_label = (spec_label or "").strip()

        if not (date_str and item_name and spec_label and (qty_raw is not None and str(qty_raw).strip() != "")):
            error_lines.append(f"{idx}행: 누락된 값이 있음")
            continue

        try:
            date = parse_date(date_str)
            if not date:
                error_lines.append(f"{idx}행: 날짜 형식 오류")
                continue
            quantity = _to_int_clean(qty_raw)
            if quantity <= 0:
                error_lines.append(f"{idx}행: 수량이 1 미만")
                continue
        except Exception:
            error_lines.append(f"{idx}행: 수량 또는 날짜 파싱 오류")
            continue

        grouped[(date, supplier_norm)].append((item_name, spec_label, quantity, idx))

    return grouped, error_lines
