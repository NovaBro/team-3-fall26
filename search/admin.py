from django.contrib import admin

from search.models import (
    FarmersMarket,
    HealthyStore,
    MenuItem,
    RestaurantInspection,
)


@admin.register(RestaurantInspection)
class RestaurantInspectionAdmin(admin.ModelAdmin):
    list_display = ("dba", "boro", "zipcode", "inspection_date", "grade")
    list_filter = ("boro", "grade")
    search_fields = ("dba", "camis", "zipcode")


admin.site.register([MenuItem, FarmersMarket, HealthyStore])
