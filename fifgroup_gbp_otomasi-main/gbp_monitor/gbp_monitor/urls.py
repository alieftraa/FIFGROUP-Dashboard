"""
urls.py — Root URL configuration untuk GBP Monitor.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("gbp.urls")),
]
