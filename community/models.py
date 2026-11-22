import zlib

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

PRICE_LEVEL_LABELS = {
    "PRICE_LEVEL_FREE": "Free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


def shuffle_seed(place_id):
    """A stable 24-bit number per place, used to shuffle rankings in SQL.

    24 bits keeps seed x daily multiplier (< 2**31) inside SQLite's 64-bit
    integers.
    """
    return zlib.crc32((place_id or "").encode("utf-8")) & 0xFFFFFF


class Restaurant(models.Model):
    """One NYC restaurant from Google Places.

    This is the pool Top picks, Explore more, Find food and the assistant
    rank. Rows are written whenever a place's Google data is fetched
    (search/services/places.py) and refreshed by ``manage.py sync_restaurants``,
    which also discovers new places. ``cuisine`` uses the same labels as the
    rest of the ranking code (e.g. "Chinese", "Coffee/Tea"); see
    restaurants/cuisines.py for how Google place types map onto them.
    """

    OPERATIONAL = "OPERATIONAL"

    place_id = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=255, blank=True, db_index=True)
    address = models.CharField(max_length=512, blank=True)
    street = models.CharField(max_length=255, blank=True)
    zipcode = models.CharField(max_length=10, blank=True, db_index=True)
    boro = models.CharField(max_length=50, blank=True, db_index=True)
    cuisine = models.CharField(max_length=100, blank=True, db_index=True)
    primary_type = models.CharField(max_length=64, blank=True)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    rating = models.FloatField(null=True)
    rating_count = models.IntegerField(null=True)
    price_level = models.CharField(max_length=32, blank=True)
    business_status = models.CharField(max_length=32, blank=True)
    maps_url = models.CharField(max_length=512, blank=True)
    photo_name = models.CharField(max_length=512, blank=True)
    shuffle_seed = models.BigIntegerField(default=0)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "restaurant"

    def __str__(self):
        return f"{self.name} ({self.place_id})"

    def save(self, *args, **kwargs):
        self.shuffle_seed = shuffle_seed(self.place_id)
        super().save(*args, **kwargs)

    @property
    def price(self):
        return PRICE_LEVEL_LABELS.get(self.price_level, "")


class PlaceEnrichment(models.Model):
    """Google Places (New) data cached for one Find food pin.

    Keyed by the same (kind, key) identity as CommunitySubject; restaurants
    use ``google:<place_id>``. Rows are overwritten on each refresh; there is
    no automatic expiry.
    """

    PRICE_LEVEL_LABELS = PRICE_LEVEL_LABELS

    kind = models.CharField(max_length=32, db_index=True)
    key = models.CharField(max_length=512)
    place_id = models.CharField(max_length=255, blank=True, db_index=True)
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
        label = self.display_name or self.key
        return f"{label} ({self.place_id})"

    @property
    def price_level_display(self):
        return self.PRICE_LEVEL_LABELS.get(self.price_level, "")

    @property
    def review_summary(self):
        """Google's AI review summary from the last fetch, or None.

        Returns ``{"text", "disclosure", "reviews_uri", "flag_uri"}``. Google
        requires the disclosure text and the reviews link next to it. Places
        fetched before the field was requested have none until refreshed.
        """
        summary = (self.raw_json or {}).get("reviewSummary") or {}
        text = (summary.get("text") or {}).get("text", "")
        if not text:
            return None
        return {
            "text": text,
            "disclosure": (summary.get("disclosureText") or {}).get("text")
            or "Summarized with Gemini",
            "reviews_uri": summary.get("reviewsUri") or self.google_maps_uri,
            "flag_uri": summary.get("flagContentUri", ""),
        }


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
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="replies",
        on_delete=models.CASCADE,
    )
    google_review = models.ForeignKey(
        PlaceReview,
        null=True,
        blank=True,
        related_name="user_comments",
        on_delete=models.SET_NULL,
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
    comment = models.ForeignKey(
        UserComment,
        null=True,
        blank=True,
        related_name="photos",
        on_delete=models.CASCADE,
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

    Name and cuisine are copied from the Restaurant row when the button is
    pressed, so the scoring code has them at hand.
    """

    LIKE = 1
    NOT_INTERESTED = -1
    VALUE_CHOICES = [(LIKE, "Like"), (NOT_INTERESTED, "Not interested")]

    user_id = models.PositiveIntegerField()
    place_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255, blank=True)
    cuisine = models.CharField(max_length=255, blank=True)
    value = models.SmallIntegerField(choices=VALUE_CHOICES)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "place_id"], name="community_feedback_user_place"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.get_value_display()} {self.place_id}"


class HealthScore(models.Model):
    """AI health score (0–1) for a restaurant, computed offline.

    Filled by ``python manage.py score_health`` on a developer machine from
    Google reviews and MenuStat menu text (see search/health_ai.py). The web
    server only reads it; restaurants without a row use the keyword method.
    """

    place_id = models.CharField(max_length=255, unique=True)
    score = models.FloatField()
    sentences_used = models.PositiveIntegerField(default=0)
    model_name = models.CharField(max_length=128, blank=True)
    # {goal key: 0-1} from the same text (search/health_ai.GOAL_ANCHORS);
    # None = not worked out yet (rows made before goal scores existed).
    goal_scores = models.JSONField(null=True, blank=True, default=None)
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.place_id} {self.score:.2f}"


class ReasonBlurb(models.Model):
    """Gemini-written "why we recommend it" paragraph for a restaurant.

    Filled by ``python manage.py write_reasons`` on a developer machine from
    the restaurant's general (non-personal) reasons and a few review lines.
    The web server only reads it; restaurants without a row show the plain
    reason list.
    """

    place_id = models.CharField(max_length=255, unique=True)
    text = models.TextField()
    facts = models.TextField(blank=True)
    model_name = models.CharField(max_length=128, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.place_id} {self.text[:40]}"


class MenuEstimate(models.Model):
    """Gemini-estimated menu for a restaurant without a MenuStat menu.

    Filled by ``python manage.py estimate_menus`` from the restaurant's name,
    cuisine and borough only (see search/menu_estimate.py). These are guesses,
    not the real menu: the Menu box labels them, and ranking uses their
    calories only as a low-confidence nutrition input blended with the prior.
    """

    place_id = models.CharField(max_length=255, unique=True)
    # [{"name", "description", "kind": main|side|drink|dessert, "calories"}]
    items = models.JSONField(default=list)
    median_calories = models.FloatField(null=True, blank=True)
    meal_count = models.PositiveIntegerField(default=0)
    model_name = models.CharField(max_length=128, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.place_id} ({len(self.items)} items)"
