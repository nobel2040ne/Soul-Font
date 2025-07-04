from django.conf import settings #type: ignore
from django.conf.urls.static import static #type: ignore
from django.urls import path #type: ignore
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('pw_reset/', views.pw_reset_view, name='pw_reset'),
    path('logout/', views.logout_view, name='logout'),
    path('user/<int:user_id>/', views.user_page, name='user_page'),
    path('admin/', views.admin_page, name='admin_page'),
    path('create/', views.create_font, name='create_font'),
    path('learning/', views.learning, name='learning'),
    path('result/', views.result, name='result'),
    path('download-template/', views.download_template, name='download_template'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)