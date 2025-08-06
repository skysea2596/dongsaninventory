from django.contrib import admin
from .models import (
    UsageCategory, Item, Spec, ProductVariant,
    InventoryUser, InventoryLog,
    PendingStockBatch, PendingStockItem
)

@admin.register(UsageCategory)
class UsageCategoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'category']
    list_filter = ['category']
    search_fields = ['name']
    autocomplete_fields = ['category']


@admin.register(Spec)
class SpecAdmin(admin.ModelAdmin):
    list_display = ['id', 'label']
    search_fields = ['label']


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['id', 'item', 'spec', 'code', 'min_quantity', 'current_quantity']
    list_filter = ['item', 'spec']
    search_fields = ['code', 'item__name', 'spec__label']
    autocomplete_fields = ['item', 'spec']
    readonly_fields = ['code']


@admin.register(InventoryUser)
class InventoryUserAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'user', 'variant', 'quantity', 'timestamp']
    list_filter = ['type', 'user', 'variant']
    search_fields = ['user__name', 'variant__code', 'variant__item__name']
    ordering = ['-timestamp']
    autocomplete_fields = ['user', 'variant']
    readonly_fields = ['timestamp']


# 🔽 입고 대기 품목 Inline
class PendingStockItemInline(admin.TabularInline):
    model = PendingStockItem
    extra = 0


@admin.register(PendingStockBatch)
class PendingStockBatchAdmin(admin.ModelAdmin):
    list_display = ['id', 'supplier', 'status', 'uploaded_at', 'processed_by', 'processed_at']
    list_filter = ['status', 'supplier']
    search_fields = ['supplier']
    inlines = [PendingStockItemInline]
    autocomplete_fields = ['processed_by']
    readonly_fields = ['uploaded_at', 'processed_at']
