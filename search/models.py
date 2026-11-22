from django.db import models

from nycfood.managers import ActiveManager


class MenuItem(models.Model):
    """One menu item per restaurant per year (DOHMH MenuStat)."""

    menu_item_id = models.CharField(max_length=32, db_index=True)
    year = models.IntegerField(null=True, db_index=True)
    restaurant_item_name = models.CharField(max_length=255, blank=True)
    restaurant = models.CharField(max_length=255, blank=True, db_index=True)
    restaurant_id = models.CharField(max_length=32, blank=True, db_index=True)
    item_name = models.CharField(max_length=255, blank=True)
    item_description = models.TextField(blank=True)
    food_category = models.CharField(max_length=100, blank=True, db_index=True)
    serving_size = models.CharField(max_length=64, blank=True)

    calories = models.FloatField(null=True)
    total_fat = models.FloatField(null=True)
    saturated_fat = models.FloatField(null=True)
    trans_fat = models.FloatField(null=True)
    cholesterol = models.FloatField(null=True)
    sodium = models.FloatField(null=True)
    potassium = models.FloatField(null=True)
    carbohydrates = models.FloatField(null=True)
    protein = models.FloatField(null=True)
    sugar = models.FloatField(null=True)
    dietary_fiber = models.FloatField(null=True)
    calories_100g = models.FloatField(null=True)

    kids_meal = models.BooleanField(default=False)
    limited_time_offer = models.BooleanField(default=False)
    regional = models.BooleanField(default=False)
    shareable = models.BooleanField(default=False)

    class Meta:
        verbose_name = "menu item"

    def __str__(self):
        return f"{self.restaurant} - {self.item_name}"


class FarmersMarket(models.Model):
    """One NYC farmers market per year."""

    year = models.IntegerField(null=True, db_index=True)
    market_name = models.CharField(max_length=255, blank=True, db_index=True)
    borough = models.CharField(max_length=50, blank=True, db_index=True)
    street_address = models.CharField(max_length=255, blank=True)
    community_district = models.CharField(max_length=64, blank=True)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    days_of_operation = models.CharField(max_length=255, blank=True)
    hours_of_operations = models.CharField(max_length=255, blank=True)
    season_dates = models.CharField(max_length=255, blank=True)
    accepts_ebt = models.CharField(max_length=32, blank=True)
    open_year_round = models.CharField(max_length=32, blank=True)
    stellar_cooking_demonstrations = models.CharField(max_length=64, blank=True)

    # Kept in the pool by ``manage.py curate_pool`` (best rated per borough).
    active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    pool = ActiveManager()

    class Meta:
        verbose_name = "farmers market"

    def __str__(self):
        return self.market_name


class HealthyStore(models.Model):
    """One Shop Healthy recognized store."""

    store_name = models.CharField(max_length=255, blank=True, db_index=True)
    street_address = models.CharField(max_length=255, blank=True)
    borough = models.CharField(max_length=50, blank=True, db_index=True)
    zip_code = models.CharField(max_length=10, blank=True, db_index=True)
    year_awarded = models.IntegerField(null=True, db_index=True)
    program_wave = models.CharField(max_length=64, blank=True)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    community_board = models.CharField(max_length=64, blank=True)
    council_district = models.CharField(max_length=64, blank=True)
    bin = models.CharField(max_length=32, blank=True)
    bbl = models.CharField(max_length=32, blank=True)
    census_tract = models.CharField(max_length=64, blank=True)
    nta = models.CharField(max_length=128, blank=True)

    # Kept in the pool by ``manage.py curate_pool`` (best rated per borough).
    active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    pool = ActiveManager()

    class Meta:
        verbose_name = "healthy store"

    def __str__(self):
        return self.store_name
