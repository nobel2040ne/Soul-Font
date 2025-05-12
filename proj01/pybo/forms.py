# pybo/forms.py

from django import forms #type: ignore
from .models import Font
from django.contrib.auth.forms import UserCreationForm #type: ignore
from django.contrib.auth.models import User #type: ignore

class FontForm(forms.ModelForm):
    class Meta:
        model = Font
        fields = ['text', 'font_description', 'ttf_file']

class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(
        max_length=30, required=True,
        widget=forms.TextInput(attrs={'placeholder': 'First name'})
    )
    last_name = forms.CharField(
        max_length=30, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Last name (optional)'})
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
        return user