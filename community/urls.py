from django.urls import path

from community import views

app_name = "community"

urlpatterns = [
    path("<slug:kind>/<path:key>/rating/", views.rate, name="rate"),
    path("<slug:kind>/<path:key>/comment/", views.comment, name="comment"),
    path("<slug:kind>/<path:key>/photo/", views.photo, name="photo"),
    path("<slug:kind>/<path:key>/", views.detail, name="detail"),
]
