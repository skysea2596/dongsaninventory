# inventory/services/inventory.py
from django.core.exceptions import ValidationError
from inventory.models import ProductVariant, InventoryLog, InventoryUser

def process_stock_in(variant: ProductVariant, quantity: int, user: InventoryUser = None):
    if quantity <= 0:
        raise ValidationError("입고 수량은 1 이상이어야 합니다.")

    variant.current_quantity += quantity
    variant.save()

    InventoryLog.objects.create(
        user=user,
        variant=variant,
        quantity=quantity,
        type='IN'
    )

def process_stock_out(variant: ProductVariant, quantity: int, user: InventoryUser):
    if quantity <= 0:
        raise ValidationError("소모 수량은 1 이상이어야 합니다.")
    if quantity > variant.current_quantity:
        raise ValidationError(f"{variant} 재고 부족")

    variant.current_quantity -= quantity
    variant.save()

    InventoryLog.objects.create(
        user=user,
        variant=variant,
        quantity=quantity,
        type='OUT'
    )
