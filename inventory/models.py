import re
from django.db import models
from django.utils import timezone

# 🔹 사용처 (카테고리)
class UsageCategory(models.Model):
    name = models.CharField("사용처 이름", max_length=100)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "사용처"
        verbose_name_plural = "사용처"

# 🔹 품목
class Item(models.Model):
    name = models.CharField("품목명", max_length=100)
    category = models.ForeignKey(UsageCategory, verbose_name="사용처", on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.category.name})" if self.category else self.name

    class Meta:
        verbose_name = "품목"
        verbose_name_plural = "품목"

# 🔹 규격
class Spec(models.Model):
    label = models.CharField("규격 라벨", max_length=100)

    def __str__(self):
        return self.label

    class Meta:
        verbose_name = "규격"
        verbose_name_plural = "규격"

# 🔹 품목 + 규격 조합
class ProductVariant(models.Model):
    item = models.ForeignKey(Item, verbose_name="품목", on_delete=models.CASCADE)
    spec = models.ForeignKey(Spec, verbose_name="규격", on_delete=models.CASCADE)
    code = models.CharField("품목 코드", max_length=20, unique=True, null=True, blank=True)

    current_quantity = models.PositiveIntegerField("현재 재고", default=0)
    min_quantity = models.PositiveIntegerField("안전 재고", default=0, help_text="재고 부족 경고 기준 수량")

    def __str__(self):
        return f"{self.item.name} [{self.spec.label}]"

    def save(self, *args, **kwargs):
        if not self.code:
            item_initials = extract_initials(self.item.name)
            spec_digits = extract_spec_number(self.spec.label)
            base = f"{item_initials}{spec_digits or '00'}"

            suffix = 1
            while True:
                candidate = f"{base}-{suffix:03d}"
                if not ProductVariant.objects.filter(code=candidate).exists():
                    self.code = candidate
                    break
                suffix += 1

        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('item', 'spec')
        ordering = ['item__name', 'spec__label']
        verbose_name = "품목 규격"
        verbose_name_plural = "품목 규격"

# 🔹 사용자
class InventoryUser(models.Model):
    name = models.CharField("이름", max_length=100)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "사용자"
        verbose_name_plural = "사용자"

# 🔹 입출고 기록
class InventoryLog(models.Model):
    LOG_TYPE = (
        ('IN', '입고'),
        ('OUT', '소모'),
    )
    user = models.ForeignKey(InventoryUser, verbose_name="담당자", on_delete=models.SET_NULL, null=True, blank=True)
    variant = models.ForeignKey(ProductVariant, verbose_name="품목 규격", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField("수량")
    type = models.CharField("입출고 구분", max_length=3, choices=LOG_TYPE)
    timestamp = models.DateTimeField("일시", default=timezone.now)
    reason = models.CharField("사유", max_length=200, blank=True, null=True)

    def __str__(self):
        return f"[{self.get_type_display()}] {self.variant} - {self.quantity}"

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "입출고 기록"
        verbose_name_plural = "입출고 기록"

# 🔹 입고 대기 건
class PendingStockBatch(models.Model):
    supplier = models.CharField("거래처", max_length=100)
    uploaded_at = models.DateTimeField("등록일", auto_now_add=True)
    status = models.CharField("상태", max_length=10, choices=[('PENDING', '대기'), ('DONE', '완료'), ('CANCELED', '취소')], default='PENDING')
    processed_by = models.ForeignKey(InventoryUser, verbose_name="처리자", null=True, blank=True, on_delete=models.SET_NULL)
    processed_at = models.DateTimeField("처리일시", null=True, blank=True)

    def __str__(self):
        return f"{self.uploaded_at.strftime('%Y-%m-%d')} - {self.supplier} 입고건"

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = "입고 대기건"
        verbose_name_plural = "입고 대기건"

# 🔹 입고 대기 품목
class PendingStockItem(models.Model):
    batch = models.ForeignKey(PendingStockBatch, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, verbose_name="품목", on_delete=models.CASCADE)
    spec = models.ForeignKey(Spec, verbose_name="규격", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField("수량")

    def __str__(self):
        return f"{self.item.name} - {self.spec.label} ({self.quantity})"

    class Meta:
        verbose_name = "입고 대기 품목"
        verbose_name_plural = "입고 대기 품목"

# 🔹 코드 생성 유틸 함수
def extract_initials(name):
    name = re.sub(r'[^가-힣A-Za-z]', '', name).upper()
    return ''.join([w[0] for w in name])[:2] or 'XX'

def extract_spec_number(spec):
    digits = re.sub(r'[^0-9]', '', spec)
    return digits if digits else '00'  # 숫자가 없으면 '00' 반환
