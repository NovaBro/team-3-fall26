from django.urls import path

from search import views

app_name = "search"

urlpatterns = [
    path("", views.index, name="index"),
    path("home/", views.home, name="home"),
    path("explore/", views.explore_index, name="explore_index"),
    path("explore/<slug:slug>/", views.explore, name="explore"),
    path("farmers-markets/", views.farmers_markets_map, name="farmers_markets_map"),
    path("combined-map/", views.combined_map, name="combined_map"),
    path("combined-map/google/", views.combined_map_google, name="combined_map_google"),
    path("restaurant/<str:camis>/", views.restaurant_detail, name="restaurant_detail"),
    path(
        "restaurant/<str:camis>/refresh-google/",
        views.refresh_place,
        name="refresh_place",
    ),
]
