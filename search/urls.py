from django.urls import path

from search import views

app_name = "search"

urlpatterns = [
    path("", views.index, name="index"),
    path("explore/", views.explore_index, name="explore_index"),
    path("explore/<slug:slug>/", views.explore, name="explore"),
    path("restaurant/<str:camis>/", views.restaurant_detail, name="restaurant_detail"),
]
