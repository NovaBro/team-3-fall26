from django.contrib import admin

from community.models import (
    CommunitySubject,
    PlaceEnrichment,
    PlaceReview,
    UserComment,
    UserPhoto,
    UserRating,
)


@admin.register(PlaceEnrichment)
class PlaceEnrichmentAdmin(admin.ModelAdmin):
    list_display = ("display_name", "camis", "rating", "fetched_at")
    search_fields = ("display_name", "camis", "place_id")


admin.site.register([PlaceReview, CommunitySubject, UserRating, UserComment, UserPhoto])
