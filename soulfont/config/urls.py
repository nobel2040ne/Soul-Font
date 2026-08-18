"""
URL configuration for the Soul Font project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin #type: ignore
from django.urls import path, include, re_path #type: ignore
from django.views.static import serve #type: ignore
from django.views.generic import RedirectView #type: ignore
from pybo import views
from django.conf import settings #type: ignore
from django.conf.urls.static import static #type: ignore

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='desktop', permanent=False)),
    path('admin/', admin.site.urls),
    path('pybo/', include('pybo.urls')),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('create/', views.create_font, name='create_font'),
    path('letter/', views.letter, name='letter'),
    path('learning/', views.learning, name='learning'),
]

# Generated fonts are served by Django itself, at any DEBUG setting.
#
# django.conf.urls.static.static() — used here before, and still used in pybo/urls.py —
# returns an empty list whenever DEBUG is False. With debug off that silently left
# /media/ unrouted: the TTFs existed on disk, but every @font-face URL on the gallery
# and Letter pages 404'd, so the site came up looking like every font had failed.
#
# django.views.static.serve is not built for volume, and a real deployment behind nginx
# or a CDN should let those handle /media/ instead. At this scale — one process, a few
# font files per page — it is the difference between the site working and not.
urlpatterns += [
    re_path(r'^%s(?P<path>.*)$' % settings.MEDIA_URL.lstrip('/'),
            serve, {'document_root': settings.MEDIA_ROOT}),
]