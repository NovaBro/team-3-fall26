from django import forms

from restaurants.diet_filters import ALLERGY_CHOICES, GOOGLE_DIET_CHOICES
from restaurants.places import METERS_PER_MILE, PRICE_LEVELS

# The five boroughs. The value is sent to Google as the search area.
AREA_CHOICES = [
    ("", "All boroughs"),
    ("Bronx", "Bronx"),
    ("Brooklyn", "Brooklyn"),
    ("Manhattan", "Manhattan"),
    ("Queens", "Queens"),
    ("Staten Island", "Staten Island"),
]
PRICE_CHOICES = [(p, p) for p in PRICE_LEVELS]
DIET_CHOICES = [("", "Any"), *GOOGLE_DIET_CHOICES]
# Miles; labels are roughly walking time for a student between classes.
DISTANCE_CHOICES = [
    ("", "Any distance"),
    ("0.25", "5 min walk (¼ mi)"),
    ("0.5", "10 min walk (½ mi)"),
    ("1", "20 min walk (1 mi)"),
    ("2", "2 mi"),
]
MIN_RATING_CHOICES = [
    ("", "Any rating"),
    ("3", "3+ stars"),
    ("3.5", "3.5+ stars"),
    ("4", "4+ stars"),
    ("4.5", "4.5+ stars"),
    ("5", "5 stars"),
]


CUISINE_CHOICES = [
    ("", "Any cuisine"),
    *((name, name) for name in (
        "American", "Caribbean", "Chinese", "French", "Greek", "Indian",
        "Italian", "Japanese", "Korean", "Mediterranean", "Mexican",
        "Spanish", "Thai", "Vietnamese",
    )),
]


class RestaurantFilterForm(forms.Form):
    cuisine = forms.ChoiceField(
        required=False,
        choices=CUISINE_CHOICES,
        error_messages={"invalid_choice": "Choose a cuisine from the list."},
    )
    area = forms.ChoiceField(
        required=False,
        choices=AREA_CHOICES,
        error_messages={"invalid_choice": "%(value)s is not a valid borough. Choose one from the list."},
    )
    price = forms.MultipleChoiceField(
        required=False,
        choices=PRICE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"invalid_choice": "%(value)s is not a valid price. Choose $, $$, $$$ or $$$$."},
    )
    diet = forms.ChoiceField(
        required=False,
        choices=DIET_CHOICES,
        error_messages={"invalid_choice": "%(value)s is not a valid diet option."},
    )
    avoid = forms.MultipleChoiceField(
        required=False,
        choices=ALLERGY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"invalid_choice": "%(value)s is not a valid allergy option."},
    )
    distance = forms.ChoiceField(
        required=False,
        choices=DISTANCE_CHOICES,
        error_messages={"invalid_choice": "%(value)s is not a valid distance."},
    )
    open_now = forms.BooleanField(required=False, label="Open now")
    min_rating = forms.ChoiceField(
        required=False,
        choices=MIN_RATING_CHOICES,
        error_messages={"invalid_choice": "Choose a minimum rating from the list."},
    )
    lat = forms.FloatField(
        required=False,
        min_value=-90,
        max_value=90,
        widget=forms.HiddenInput,
        error_messages={"invalid": "Your location is invalid. Click “Use my location” again."},
    )
    lng = forms.FloatField(
        required=False,
        min_value=-180,
        max_value=180,
        widget=forms.HiddenInput,
        error_messages={"invalid": "Your location is invalid. Click “Use my location” again."},
    )

    def clean(self):
        data = super().clean()
        lat, lng = data.get("lat"), data.get("lng")
        if "lat" in self.errors or "lng" in self.errors:
            return data
        if (lat is None) != (lng is None):
            raise forms.ValidationError("Your location is incomplete. Click “Use my location” again.")
        if data.get("distance") and lat is None:
            self.add_error("distance", "Click “Use my location” to filter by distance.")
        return data

    @property
    def radius_m(self):
        miles = self.cleaned_data.get("distance")
        return float(miles) * METERS_PER_MILE if miles else None
