from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PlaceEnrichment(models.Model):
    """Google Places (New) data cached for one Find food pin.

    Keyed by the same (kind, key) identity as CommunitySubject. For DOHMH
    restaurants, ``camis`` is also stored so older callers can still look up
    by inspection id. Rows are overwritten on each manual refresh; there is
    no automatic expiry.
    """

    PRICE_LEVEL_LABELS = {
        "PRICE_LEVEL_FREE": "Free",
        "PRICE_LEVEL_INEXPENSIVE": "$",
        "PRICE_LEVEL_MODERATE": "$$",
        "PRICE_LEVEL_EXPENSIVE": "$$$",
        "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
    }

    kind = models.CharField(max_length=32, db_index=True)
    key = models.CharField(max_length=512)
    camis = models.CharField(max_length=20, blank=True, db_index=True)
    place_id = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    formatted_address = models.CharField(max_length=512, blank=True)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    rating = models.FloatField(null=True)
    user_rating_count = models.IntegerField(null=True)
    price_level = models.CharField(max_length=32, blank=True)
    price_range = models.JSONField(null=True, blank=True)
    website_uri = models.CharField(max_length=512, blank=True)
    google_maps_uri = models.CharField(max_length=512, blank=True)
    business_status = models.CharField(max_length=32, blank=True)
    raw_json = models.JSONField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "place enrichment"
        verbose_name_plural = "place enrichments"
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "key"], name="community_enrichment_kind_key"
            ),
        ]

    def __str__(self):
        label = self.display_name or self.camis or self.key
        return f"{label} ({self.place_id})"

    @property
    def price_level_display(self):
        return self.PRICE_LEVEL_LABELS.get(self.price_level, "")


class PlaceReview(models.Model):
    """A single Google review captured for a PlaceEnrichment.

    Reviews are replaced wholesale whenever the owning place is refreshed.
    """

    place = models.ForeignKey(
        PlaceEnrichment, related_name="reviews", on_delete=models.CASCADE
    )
    author_name = models.CharField(max_length=255, blank=True)
    author_uri = models.CharField(max_length=512, blank=True)
    rating = models.IntegerField(null=True)
    relative_time = models.CharField(max_length=64, blank=True)
    text = models.TextField(blank=True)
    publish_time = models.DateTimeField(null=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "place review"

    def __str__(self):
        return f"{self.author_name} ({self.rating})"


class CommunitySubject(models.Model):
    """One combined-map pin that people can rate, comment on, or photograph."""

    kind = models.CharField(max_length=32)
    key = models.CharField(max_length=512)
    name = models.CharField(max_length=255, blank=True)
    address = models.CharField(max_length=512, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "key"], name="community_subject_kind_key"
            ),
        ]

    def __str__(self):
        return self.name or f"{self.kind}:{self.key}"


class UserRating(models.Model):
    """One 1–5 score per user per pin. A later save replaces the earlier score."""

    subject = models.ForeignKey(
        CommunitySubject, related_name="ratings", on_delete=models.CASCADE
    )
    user_id = models.PositiveIntegerField()
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "user_id"], name="community_rating_subject_user"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} rated {self.subject} {self.score}"


class UserComment(models.Model):
    subject = models.ForeignKey(
        CommunitySubject, related_name="comments", on_delete=models.CASCADE
    )
    user_id = models.PositiveIntegerField()
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} on {self.subject}"


class UserPhoto(models.Model):
    subject = models.ForeignKey(
        CommunitySubject, related_name="photos", on_delete=models.CASCADE
    )
    user_id = models.PositiveIntegerField()
    image = models.ImageField(upload_to="community/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} photo of {self.subject}"


class LocationLookup(models.Model):
    """Coordinates Google found for a dataset row that had none.

    Keyed by the same (kind, key) pin identity as CommunitySubject. Misses are
    stored too (found=False) so the same row is not looked up on every visit.
    Google's terms allow caching coordinates for 30 days, so older rows are
    treated as missing and looked up again.
    """

    kind = models.CharField(max_length=32)
    key = models.CharField(max_length=512)
    query = models.CharField(max_length=512, blank=True)
    found = models.BooleanField(default=False)
    place_id = models.CharField(max_length=255, blank=True)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    formatted_address = models.CharField(max_length=512, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "key"], name="community_location_kind_key"
            ),
        ]

    def __str__(self):
        return f"{self.kind}:{self.key} ({'found' if self.found else 'not found'})"


class RecommendationFeedback(models.Model):
    """A user's Like (+1) or Not interested (-1) on a Top picks restaurant.

    Name and cuisine are copied from the inspection data when the button is
    pressed, so scoring can use them without a cross-database join.
    """

    LIKE = 1
    NOT_INTERESTED = -1
    VALUE_CHOICES = [(LIKE, "Like"), (NOT_INTERESTED, "Not interested")]

    user_id = models.PositiveIntegerField()
    camis = models.CharField(max_length=32)
    name = models.CharField(max_length=255, blank=True)
    cuisine = models.CharField(max_length=255, blank=True)
    value = models.SmallIntegerField(choices=VALUE_CHOICES)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "camis"], name="community_feedback_user_camis"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.get_value_display()} {self.camis}"
