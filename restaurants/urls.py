from django.urls import path

from restaurants import views

app_name = "restaurants"

urlpatterns = [
    path("", views.search, name="search"),
    path("photo/", views.photo, name="photo"),
]
