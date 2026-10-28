from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Fixed, slowly-changing inputs a user sets once and edits occasionally."""

    GENDER_CHOICES = [
        ("female", "Female"),
        ("male", "Male"),
        ("non-binary", "Non-binary"),
        ("other", "Other"),
        ("prefer-not-to-say", "Prefer not to say"),
    ]

    HEALTH_GOALS = [
        ("weight-loss", "Weight loss"),
        ("muscle-gain", "Muscle gain"),
        ("heart-health", "Heart health"),
        ("more-energy", "More energy"),
        ("balanced-diet", "Balanced diet"),
        ("manage-condition", "Manage a medical condition"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="profile", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100, blank=True)
    picture = models.ImageField(upload_to="profile_pictures/", blank=True)
    home_address = models.CharField(max_length=255, blank=True)
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
        labels = dict(self.HEALTH_GOALS)
        return ", ".join(labels.get(goal, goal) for goal in self.health_goals)


class MoodLog(models.Model):
    """One timestamped mood/energy check-in. Variable inputs logged over time."""

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
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "mood log"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username}: mood {self.mood}, energy {self.energy_level}"

    @property
    def mood_display_label(self):
        return dict(self.MOOD_CHOICES).get(self.mood, str(self.mood))

    @property
    def energy_display_label(self):
        return dict(self.ENERGY_CHOICES).get(self.energy_level, str(self.energy_level))
