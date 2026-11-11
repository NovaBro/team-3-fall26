from django.contrib import admin
from django.contrib.auth.models import User
from django.db.models import Count

from accounts.models import MoodLog, UserProfile


admin.site.unregister(User)


@admin.register(User)
class UserManagementAdmin(admin.ModelAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "date_joined",
        "mood_log_count",
    )
    list_filter = ("is_active", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)
    fieldsets = (
        (
            "Account details",
            {
                "fields": (
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "is_active",
                    "date_joined",
                    "last_login",
                    "mood_log_count",
                )
            },
        ),
    )
    readonly_fields = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "date_joined",
        "last_login",
        "mood_log_count",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _mood_log_count=Count("mood_logs", distinct=True)
        )

    @admin.display(description="Mood check-ins", ordering="_mood_log_count")
    def mood_log_count(self, obj):
        return obj._mood_log_count

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "phone_number", "home_address", "age", "gender")
    search_fields = ("user__username", "name", "home_address")


@admin.register(MoodLog)
class MoodLogAdmin(admin.ModelAdmin):
    list_display = ("user", "mood", "energy_level", "created_at")
    list_filter = ("mood", "energy_level")
    date_hierarchy = "created_at"
