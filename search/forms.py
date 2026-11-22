from django import forms

from restaurants.diet_filters import DIETS
from restaurants.forms import RestaurantFilterForm

FARMERS_MARKET = "farmers_market"
GROCERY = "grocery"
RESTAURANT = "restaurant"
STORE_TYPE_CHOICES = [
    (RESTAURANT, "Restaurants"),
    (FARMERS_MARKET, "Farmers markets"),
    (GROCERY, "Grocery (Shop Healthy)"),
]

SAVED = "saved"
GOOGLE = "google"
SOURCE_CHOICES = [
    (SAVED, "Saved NYC restaurants"),
    (GOOGLE, "Google Places (live)"),
]

MARKET_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
DAY_CHOICES = [("", "Any day"), *((day, day) for day in MARKET_DAYS)]
DIET_CHOICES = [("", "Any"), *((key, diet["label"]) for key, diet in DIETS.items())]

# Filters only a live Google search can apply; ignored for saved restaurants.
GOOGLE_ONLY_FIELDS = ("open_now",)


class FindFoodForm(RestaurantFilterForm):
    """Every filter from the old Restaurants and Find restaurants tabs, plus
    store types and a farmers market day."""

    types = forms.MultipleChoiceField(
        required=False,
        choices=STORE_TYPE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"invalid_choice": "%(value)s is not a valid store type."},
    )
    q = forms.CharField(
        required=False,
        max_length=100,
        strip=True,
        widget=forms.TextInput(attrs={"placeholder": "Any name"}),
    )
    zip = forms.RegexField(
        required=False,
        regex=r"^\d{1,5}$",
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. 11201", "inputmode": "numeric", "maxlength": 5}
        ),
        error_messages={"invalid": "Enter up to 5 digits for the ZIP code."},
    )
    source = forms.ChoiceField(
        required=False,
        choices=SOURCE_CHOICES,
        widget=forms.RadioSelect,
        error_messages={"invalid_choice": "Choose where restaurant results come from."},
    )
    day = forms.ChoiceField(
        required=False,
        choices=DAY_CHOICES,
        error_messages={"invalid_choice": "%(value)s is not a day of the week."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Saved restaurants filter diets by cuisine (e.g. kosher), live Google
        # results by place type (e.g. halal); offer both.
        self.fields["diet"].choices = DIET_CHOICES

    def clean(self):
        data = super().clean()
        data["types"] = data.get("types") or [
            value for value, _label in STORE_TYPE_CHOICES
        ]
        data["source"] = data.get("source") or SAVED
        if data["source"] == SAVED:
            for name in GOOGLE_ONLY_FIELDS:
                data[name] = self.fields[name].to_python(None)
        diet = data.get("diet")
        if diet and RESTAURANT in data["types"]:
            if data["source"] == SAVED and not DIETS[diet]["cuisines"]:
                self.add_error(
                    "diet",
                    f"{DIETS[diet]['label']} is only available with Google Places "
                    "restaurant results.",
                )
            if data["source"] == GOOGLE and not DIETS[diet]["google"]:
                self.add_error(
                    "diet",
                    f"{DIETS[diet]['label']} is only available with saved "
                    "restaurants.",
                )
        return data

    @property
    def google_only_filters_ignored(self):
        """True when live-only filters were sent but saved restaurants are used."""
        if self.cleaned_data.get("source") != SAVED:
            return False
        return any(self.data.get(name) for name in GOOGLE_ONLY_FIELDS)
