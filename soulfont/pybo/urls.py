from django.conf import settings #type: ignore
from django.conf.urls.static import static #type: ignore
from django.urls import path #type: ignore
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('desktop/', views.desktop, name='desktop'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('pw_reset/', views.pw_reset_view, name='pw_reset'),
    path('logout/', views.logout_view, name='logout'),
    path('me/', views.my_page, name='my_page'),
    path('user/<int:font_id>/', views.user_page, name='user_page'),
    path('user/<int:font_id>/editor/', views.font_editor, name='font_editor'),
    path('admin/', views.admin_page, name='admin_page'),
    path('create/', views.create_font, name='create_font'),
    path('letter/', views.letter, name='letter'),
    path('about/', views.about, name='about'),
    path('learning/', views.learning, name='learning'),
    path('download-template/', views.download_template, name='download_template'),
    path('user/<int:font_id>/download/', views.download_font, name='download_font'),
    path('user/<int:font_id>/status/', views.font_status, name='font_status'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
