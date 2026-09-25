"""
URL configuration for ecommernce project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
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
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve as serve_media
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('shop.urls')),
    path('api/accounts/', include('accounts.urls')),
    path('api/admin/', include('adminpanel.api_urls')),
    path('panel/', include('adminpanel.urls')),
    path('sw.js', TemplateView.as_view(template_name='sw.js', content_type='application/javascript'), name='sw.js'),
    
    path('accounts/', include('allauth.urls')),
    
    # JWT refresh. Obtaining a token pair is done via /api/accounts/login/
    # (throttled); the old unthrottled /api/token/ duplicate was removed.
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

# Static files: runserver serves them in DEBUG; WhiteNoise in production.
if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(r'^%s(?P<path>.*)$' % settings.MEDIA_URL.lstrip('/'), serve_media, {'document_root': settings.MEDIA_ROOT}),
    ]


