import re

def extract_number(label):
    match = re.search(r'\d+', label)
    return int(match.group()) if match else 0

def build_variant_map(variants):
    variant_map = {}
    for variant in variants:
        item_id = variant.item.id
        if item_id not in variant_map:
            variant_map[item_id] = []
        variant_map[item_id].append({
            'id': variant.id,
            'spec_label': variant.spec.label,
            'sort_key': extract_number(variant.spec.label)
        })
    for v_list in variant_map.values():
        v_list.sort(key=lambda x: x['sort_key'])
        for v in v_list:
            v.pop('sort_key')
    return variant_map
