from .models import UsageCategory

def common_categories(request):
    return {
        'categories': UsageCategory.objects.all()
    }
