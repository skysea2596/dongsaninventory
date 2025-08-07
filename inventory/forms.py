# forms.py
from django import forms

class UsageStatForm(forms.Form):
    start_date = forms.DateField(label="시작일", required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(label="종료일", required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    user = forms.ChoiceField(label="사용자", required=False)
    variant = forms.ChoiceField(label="품목+규격", required=False)

    def __init__(self, *args, **kwargs):
        user_choices = kwargs.pop('user_choices', [])
        variant_choices = kwargs.pop('variant_choices', [])
        super().__init__(*args, **kwargs)
        self.fields['user'].choices = [('', '전체')] + user_choices
        self.fields['variant'].choices = [('', '전체')] + variant_choices
