from django.urls import path

from search import views

app_name = "search"

urlpatterns = [
    path("", views.home, name="home"),
    path("rerank/", views.rerank_top_picks, name="rerank_top_picks"),
    path("location/", views.save_location, name="save_location"),
    path("search/", views.index, name="index"),
    path(
        "restaurant/<str:place_id>/", views.restaurant_detail, name="restaurant_detail"
    ),
    path(
        "restaurant/<str:place_id>/feedback/",
        views.pick_feedback,
        name="pick_feedback",
    ),
    path(
        "restaurant/<str:place_id>/what-to-order/",
        views.restaurant_what_to_order,
        name="what_to_order",
    ),
    path(
        "restaurant/<str:place_id>/refresh-google/",
        views.refresh_place,
        name="refresh_place",
    ),
    # Tabs merged into the Find food page (issue #109); old links redirect.
    path("combined-map/", views.combined_map_redirect, name="combined_map"),
    path("farmers-markets/", views.farmers_markets_redirect),
    path("explore/", views.explore_redirect),
    path("explore/<slug:slug>/", views.explore_redirect),
]
