# pybo/forms.py

from django import forms
from .models import Font

class FontForm(forms.ModelForm):
    class Meta:
        model = Font
        fields = ['text', 'font_description', 'ttf_file']
