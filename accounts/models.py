from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from accounts.goal_icons import ENERGY_ICONS, MOOD_ICONS, icon
from search.profile_options import GOAL_LABELS, normalize_goals
from search.profile_options import HEALTH_GOALS as GOAL_OPTIONS

phone_validator = RegexValidator(
    r"^\+?[0-9\s\-()]{7,20}$", "Enter a valid phone number."
)


class UserProfile(models.Model):
    """Fixed, slowly-changing inputs a user sets once and edits occasionally."""

    GENDER_CHOICES = [
        ("female", "Female"),
        ("male", "Male"),
        ("non-binary", "Non-binary"),
        ("other", "Other"),
        ("prefer-not-to-say", "Prefer not to say"),
    ]

    # Keys and labels live in search/profile_options.py (also used by scoring).
    HEALTH_GOALS = [(key, label) for key, label, _hint in GOAL_OPTIONS]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="profile", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100, blank=True)
    picture = models.ImageField(upload_to="profile_pictures/", blank=True)
    phone_number = models.CharField(
        max_length=20, blank=True, validators=[phone_validator]
    )
    promo_opt_in = models.BooleanField(
        default=False, verbose_name="Send me promotions and updates"
    )
    home_address = models.CharField(max_length=255, blank=True)
    location_lat = models.FloatField(null=True, blank=True)
    location_lng = models.FloatField(null=True, blank=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=32, blank=True, choices=GENDER_CHOICES)
    weight_lbs = models.FloatField(null=True, blank=True)
    height_in = models.FloatField(null=True, blank=True)
    favorite_foods = models.TextField(blank=True)
    disliked_foods = models.TextField(blank=True)
    health_goals = models.JSONField(default=list, blank=True)
    allergies = models.TextField(blank=True)

    class Meta:
        verbose_name = "user profile"

    def __str__(self):
        return f"Profile of {self.user.username}"

    @property
    def health_goals_display(self):
        goals = normalize_goals(self.health_goals)
        return ", ".join(GOAL_LABELS[goal] for goal in goals)


class MoodLog(models.Model):
    """One mood/energy check-in per user per America/New_York calendar day."""

    MOOD_CHOICES = [
        (1, "Awful"),
        (2, "Bad"),
        (3, "Okay"),
        (4, "Good"),
        (5, "Great"),
    ]
    ENERGY_CHOICES = [
        (1, "Exhausted"),
        (2, "Tired"),
        (3, "Okay"),
        (4, "Alert"),
        (5, "Energized"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="mood_logs", on_delete=models.CASCADE
    )
    mood = models.PositiveSmallIntegerField(choices=MOOD_CHOICES)
    energy_level = models.PositiveSmallIntegerField(choices=ENERGY_CHOICES)
    log_date = models.DateField(
        db_index=True,
        help_text="America/New_York calendar day for this check-in.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "mood log"
        ordering = ["-log_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "log_date"],
                name="accounts_moodlog_user_log_date_uniq",
            )
        ]

    def __str__(self):
        return f"{self.user.username}: mood {self.mood}, energy {self.energy_level}"

    def save(self, *args, **kwargs):
        if self.log_date is None:
            from accounts.mood import today_ny

            self.log_date = today_ny(timezone.now())
        super().save(*args, **kwargs)

    @property
    def mood_display_label(self):
        return dict(self.MOOD_CHOICES).get(self.mood, str(self.mood))

    @property
    def energy_display_label(self):
        return dict(self.ENERGY_CHOICES).get(self.energy_level, str(self.energy_level))

    @property
    def mood_icon(self):
        return icon(MOOD_ICONS.get(self.mood, ""), "checkin-history__icon", 18)

    @property
    def energy_icon(self):
        return icon(
            ENERGY_ICONS.get(self.energy_level, ""), "checkin-history__icon", 18
        )
