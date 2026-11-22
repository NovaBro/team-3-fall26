from django.contrib import admin

from community.models import (
    CommunitySubject,
    PlaceEnrichment,
    PlaceReview,
    Restaurant,
    UserComment,
    UserPhoto,
    UserRating,
)


@admin.register(PlaceEnrichment)
class PlaceEnrichmentAdmin(admin.ModelAdmin):
    list_display = ("display_name", "kind", "rating", "fetched_at")
    search_fields = ("display_name", "key", "place_id")


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "boro", "cuisine", "rating", "rating_count", "fetched_at")
    list_filter = ("boro", "business_status")
    search_fields = ("name", "place_id", "zipcode")


admin.site.register([PlaceReview, CommunitySubject, UserRating, UserComment, UserPhoto])
