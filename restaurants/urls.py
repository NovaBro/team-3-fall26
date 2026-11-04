from django.urls import path

from restaurants import views
from search.views import find_restaurants_redirect

app_name = "restaurants"

urlpatterns = [
    # Find restaurants is now part of the Find food page (issue #109).
    path("", find_restaurants_redirect, name="search"),
    path("photo/", views.photo, name="photo"),
]
