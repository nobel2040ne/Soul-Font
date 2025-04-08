from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('create/', views.create_font, name='create_font'),
    path('learning/', views.learning, name='learning'),
    path('result/', views.result, name='result'),
    path('download-template1/', views.download_template1, name='download_template1'),
    path('download-template2/', views.download_template2, name='download_template2'),
    path('download-template3/', views.download_template3, name='download_template3'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)