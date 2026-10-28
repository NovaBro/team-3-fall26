from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from accounts.models import MoodLog, UserProfile


class SignupForm(UserCreationForm):
    username = forms.CharField(
        error_messages={"required": "Pick a username."},
    )
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email")

    field_order = ["username", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class UserProfileForm(forms.ModelForm):
    # Declared so an empty checkbox list doesn't hit JSONField.bound_data,
    # which crashes on non-string values (Django quirk with CheckboxSelectMultiple).
    health_goals = forms.MultipleChoiceField(
        choices=UserProfile.HEALTH_GOALS,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Health goals",
    )
    first_name = forms.CharField(required=False, max_length=150, label="First name")
    last_name = forms.CharField(required=False, max_length=150, label="Last name")
    age = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=120,
        error_messages={
            "invalid": "Age must be a whole number.",
            "min_value": "Age must be at least 1.",
            "max_value": "Age must be 120 or less.",
        },
    )
    weight_lbs = forms.FloatField(
        required=False,
        min_value=1,
        max_value=1000,
        label="Weight (lbs)",
        error_messages={
            "invalid": "Weight must be a number.",
            "min_value": "Weight must be at least 1 lb.",
            "max_value": "Weight must be 1000 lbs or less.",
        },
    )
    height_in = forms.FloatField(
        required=False,
        min_value=1,
        max_value=96,
        label="Height (in)",
        error_messages={
            "invalid": "Height must be a number.",
            "min_value": "Height must be at least 1 inch.",
            "max_value": "Height must be 96 inches or less.",
        },
    )

    class Meta:
        model = UserProfile
        fields = (
            "name",
            "home_address",
            "age",
            "gender",
            "weight_lbs",
            "height_in",
            "favorite_foods",
            "disliked_foods",
            "health_goals",
            "allergies",
            "picture",
        )
        widgets = {
            "home_address": forms.TextInput(
                attrs={"placeholder": "Street, Brooklyn, NY"}
            ),
            "favorite_foods": forms.TextInput(
                attrs={"placeholder": "pizza, dumplings, tacos"}
            ),
            "disliked_foods": forms.TextInput(
                attrs={"placeholder": "mushrooms, olives"}
            ),
            "allergies": forms.TextInput(attrs={"placeholder": "peanuts, shellfish"}),
            "health_goals": forms.CheckboxSelectMultiple,
        }
        labels = {
            "home_address": "Place (home address)",
            "favorite_foods": "Favorite foods (comma separated)",
            "disliked_foods": "Disliked foods (comma separated)",
            "allergies": "Allergies (comma separated)",
            "picture": "Profile picture",
        }
        error_messages = {
            "name": {"max_length": "Name must be 100 characters or fewer."},
            "home_address": {"max_length": "Address must be 255 characters or fewer."},
        }

    field_order = [
        "first_name",
        "last_name",
        "name",
        "home_address",
        "age",
        "gender",
        "weight_lbs",
        "height_in",
        "favorite_foods",
        "disliked_foods",
        "health_goals",
        "allergies",
        "picture",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = getattr(self.instance, "user", None)
        if user is not None and getattr(user, "pk", None):
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name


class MoodLogForm(forms.ModelForm):
    class Meta:
        model = MoodLog
        fields = ("mood", "energy_level")
        widgets = {
            "mood": forms.RadioSelect,
            "energy_level": forms.RadioSelect,
        }
        error_messages = {
            "mood": {
                "invalid_choice": "Pick a mood from the list.",
                "required": "Pick a mood.",
            },
            "energy_level": {
                "invalid_choice": "Pick an energy level from the list.",
                "required": "Pick an energy level.",
            },
        }
