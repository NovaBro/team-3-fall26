from django.urls import path

from search import views

app_name = "search"

urlpatterns = [
    path("", views.index, name="index"),
    path("explore/", views.explore_index, name="explore_index"),
    path("explore/<slug:slug>/", views.explore, name="explore"),
    path("farmers-markets/", views.farmers_markets_map, name="farmers_markets_map"),
    path("restaurant/<str:camis>/", views.restaurant_detail, name="restaurant_detail"),
    path(
        "restaurant/<str:camis>/refresh-google/",
        views.refresh_place,
        name="refresh_place",
    ),
]
