import re
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import ProductVariant

def extract_initials(name):
    name = re.sub(r'[^가-힣A-Za-z]', '', name).upper()
    return ''.join([w[0] for w in name])[:2] or 'XX'

def extract_spec_number(spec):
    return re.sub(r'[^0-9]', '', spec)

@receiver(pre_save, sender=ProductVariant)
def generate_product_code(sender, instance, **kwargs):
    if not instance.code:
        item_initials = extract_initials(instance.item.name)
        spec_digits = extract_spec_number(instance.spec.name)
        base = f"{item_initials}{spec_digits}"

        # 중복 방지 번호
        similar = sender.objects.filter(code__startswith=base).order_by('-code')
        if similar.exists():
            last_code = similar.first().code
            try:
                number = int(last_code.split('-')[-1])
            except:
                number = 0
        else:
            number = 0

        instance.code = f"{base}-{number + 1:03d}"
