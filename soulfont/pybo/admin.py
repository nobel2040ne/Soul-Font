from django.contrib import admin #type: ignore
from .models import Font, UserData, Template #type: ignore

admin.site.register(Font)
admin.site.register(UserData)