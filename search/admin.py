from django.contrib import admin

from search.models import (
    AgencyPurchase,
    FarmersMarket,
    HealthyStore,
    MenuItem,
    ParkEatery,
    Place,
    RestaurantInspection,
    Review,
)


@admin.register(RestaurantInspection)
class RestaurantInspectionAdmin(admin.ModelAdmin):
    list_display = ("dba", "boro", "zipcode", "inspection_date", "grade")
    list_filter = ("boro", "grade")
    search_fields = ("dba", "camis", "zipcode")


admin.site.register([MenuItem, AgencyPurchase, FarmersMarket, HealthyStore, ParkEatery])


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "external_id")
    list_filter = ("kind",)
    search_fields = ("name", "external_id")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("place", "user", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("text", "place__name", "user__username")
