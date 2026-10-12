from django import forms
from django.core.validators import RegexValidator

from restaurants.places import METERS_PER_MILE, PRICE_LEVELS

PRICE_CHOICES = [(p, p) for p in PRICE_LEVELS]
DIET_CHOICES = [("", "Any"), ("vegetarian", "Vegetarian"), ("vegan", "Vegan"), ("halal", "Halal")]
# Miles; labels are roughly walking time for a student between classes.
DISTANCE_CHOICES = [
    ("", "Any distance"),
    ("0.25", "5 min walk (¼ mi)"),
    ("0.5", "10 min walk (½ mi)"),
    ("1", "20 min walk (1 mi)"),
    ("2", "2 mi"),
]


class RestaurantFilterForm(forms.Form):
    area = forms.CharField(
        required=False,
        max_length=100,
        strip=True,
        validators=[
            RegexValidator(
                r"^[\w\s,.'&#/-]*$",
                "Area can only contain letters, numbers, spaces and , . ' & # / -",
            )
        ],
        widget=forms.TextInput(attrs={"placeholder": "Neighborhood or street, e.g. East Village"}),
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
    distance = forms.ChoiceField(
        required=False,
        choices=DISTANCE_CHOICES,
        error_messages={"invalid_choice": "%(value)s is not a valid distance."},
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
