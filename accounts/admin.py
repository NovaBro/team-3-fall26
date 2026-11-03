from django.contrib import admin

from accounts.models import MoodLog, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "home_address", "age", "gender")
    search_fields = ("user__username", "name", "home_address")


@admin.register(MoodLog)
class MoodLogAdmin(admin.ModelAdmin):
    list_display = ("user", "mood", "energy_level", "created_at")
    list_filter = ("mood", "energy_level")
    date_hierarchy = "created_at"
