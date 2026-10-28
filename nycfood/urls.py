"""
URL configuration for nycfood project.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("restaurants/", include("restaurants.urls")),
    path("", include("search.urls")),
]
