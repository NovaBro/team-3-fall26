import json

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from accounts.goal_icons import ENERGY_ICONS, MOOD_ICONS, goal_icon, icon
from accounts.models import MoodLog, UserProfile
from search.profile_options import (
    ALLERGY_LABELS,
    ALLERGY_OPTIONS,
    FOOD_OPTIONS,
    GOAL_HINTS,
    POPULAR_FOODS,
    normalize_goals,
    parse_allergies,
    parse_foods,
)
from search.recommend import bmi

FOOD_CHOICES_JSON = json.dumps([option.label for option in FOOD_OPTIONS])
POPULAR_JSON = json.dumps(list(POPULAR_FOODS))


class FoodPickerWidget(forms.TextInput):
    """Chips for popular foods plus a search box (search/static/search/
    food_picker.js). The value is a comma-separated list of option labels;
    without JavaScript it stays a plain text box."""

    def __init__(self, other="", placeholder="", attrs=None):
        super().__init__(attrs)
        self.other = other  # the paired field (favorite <-> disliked)
        self.placeholder = placeholder
        self.unknown = []  # older free text we could not match

    def render(self, name, value, attrs=None, renderer=None):
        box = super().render(name, value, attrs, renderer)
        note = ""
        if self.unknown:
            note = format_html(
                '<p class="field-errors">We couldn’t match: {}. '
                "Pick from the list instead.</p>",
                ", ".join(self.unknown),
            )
        return format_html(
            '<div class="food-picker" data-food-picker data-other="{}" '
            'data-placeholder="{}" data-options="{}" data-popular="{}">{}{}</div>',
            self.other,
            self.placeholder,
            FOOD_CHOICES_JSON,
            POPULAR_JSON,
            box,
            note,
        )


class GoalCardsWidget(forms.CheckboxSelectMultiple):
    """Health goals as cards: a title and a one-line hint each."""

    def render(self, name, value, attrs=None, renderer=None):
        chosen = {str(v) for v in value or []}
        base_id = (attrs or {}).get("id", f"id_{name}")
        cards = format_html_join(
            "",
            '<label class="goal-card" for="{0}_{1}">'
            '<input type="checkbox" name="{2}" value="{3}" id="{0}_{1}"{4}>{7}'
            '<span class="goal-card__text">'
            '<span class="goal-card__title">{5}</span>'
            '<span class="goal-card__hint">{6}</span></span></label>',
            (
                (
                    base_id,
                    index,
                    name,
                    key,
                    mark_safe(" checked") if key in chosen else "",
                    label,
                    GOAL_HINTS.get(key, ""),
                    goal_icon(key),
                )
                for index, (key, label) in enumerate(self.choices)
            ),
        )
        return format_html('<div class="goal-cards" id="{}">{}</div>', base_id, cards)

    def id_for_label(self, id_, index=None):
        return id_


def _food_labels(value):
    return ", ".join(option.label for option in parse_foods(value)[0])


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "inactive": (
            "Please confirm your email before logging in — "
            "check your inbox for the link."
        ),
    }


class SignupForm(UserCreationForm):
    username = forms.CharField(
        error_messages={"required": "Pick a username."},
    )
    name = forms.CharField(
        max_length=100,
        label="Full name",
        error_messages={"required": "Enter your name."},
    )
    email = forms.EmailField(
        required=True,
        error_messages={"required": "Enter an email address."},
    )

    class Meta:
        model = User
        fields = ("username", "email")

    field_order = ("username", "name", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class UserProfileForm(forms.ModelForm):
    email = forms.EmailField(required=False, label="Email address")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = getattr(self.instance, "user", None)
        if user is not None and getattr(user, "pk", None):
            self.fields["email"].initial = user.email
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
        value = bmi(self.instance.weight_lbs, self.instance.height_in)
        self.fields["bmi"].initial = f"{value:.1f}" if value else ""
        # Older free-text values: show what we can match; list the rest.
        for field in ("favorite_foods", "disliked_foods"):
            saved = getattr(self.instance, field, "") or ""
            if not self.is_bound:
                self.initial[field] = _food_labels(saved)
            self.fields[field].widget.unknown = parse_foods(saved)[1]
        self.initial["health_goals"] = normalize_goals(self.instance.health_goals)
        self.initial["allergies"] = parse_allergies(self.instance.allergies)

    # Declared so an empty checkbox list doesn't hit JSONField.bound_data,
    # which crashes on non-string values (Django quirk with CheckboxSelectMultiple).
    health_goals = forms.MultipleChoiceField(
        choices=UserProfile.HEALTH_GOALS,
        required=False,
        widget=GoalCardsWidget,
        label="Health goals",
        help_text="Pick any. They count toward the Personal fit part of your " "picks.",
    )
    favorite_foods = forms.CharField(
        required=False,
        label="Favorite foods",
        widget=FoodPickerWidget(
            other="id_disliked_foods", placeholder="Search more: ramen, peruvian"
        ),
    )
    disliked_foods = forms.CharField(
        required=False,
        label="Disliked foods",
        widget=FoodPickerWidget(
            other="id_favorite_foods", placeholder="Search more: seafood, indian"
        ),
    )
    allergies = forms.MultipleChoiceField(
        choices=ALLERGY_OPTIONS,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Allergies & restrictions",
        help_text=mark_safe(
            "Nuts, shellfish and fish leave out cuisines where they are common. "
            "Others only lower Personal fit and show a warning.<br>"
            "We can&#x27;t see restaurant ingredients, so always confirm with "
            "the restaurant."
        ),
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
    # Shown only, never saved or typed: worked out from weight and height (the
    # page updates it as they change). Disabled fields ignore posted values.
    bmi = forms.CharField(
        required=False,
        disabled=True,
        label="BMI (auto)",
        help_text="25 or more leans your picks to lighter meals, unless you "
        "pick Muscle gain.",
        widget=forms.TextInput(
            attrs={"readonly": "readonly", "tabindex": "-1", "placeholder": "—"}
        ),
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
            "picture",
            "phone_number",
            "promo_opt_in",
            "home_address",
            "age",
            "gender",
            "weight_lbs",
            "height_in",
            "favorite_foods",
            "disliked_foods",
            "health_goals",
            "allergies",
        )
        widgets = {
            "phone_number": forms.TextInput(attrs={"placeholder": "(555) 555-0100"}),
            "home_address": forms.TextInput(
                attrs={"placeholder": "Street, Brooklyn, NY"}
            ),
        }
        labels = {
            "picture": "Profile picture",
            "phone_number": "Phone number",
            "home_address": "Place (home address)",
        }
        error_messages = {
            "name": {"max_length": "Name must be 100 characters or fewer."},
            "home_address": {"max_length": "Address must be 255 characters or fewer."},
        }

    field_order = [
        "first_name",
        "last_name",
        "name",
        "email",
        "phone_number",
        "promo_opt_in",
        "home_address",
        "age",
        "gender",
        "weight_lbs",
        "height_in",
        "bmi",
        "favorite_foods",
        "disliked_foods",
        "health_goals",
        "allergies",
        "picture",
    ]

    def _clean_foods(self, field):
        options, unknown = parse_foods(self.cleaned_data.get(field, ""))
        if unknown:
            raise forms.ValidationError(
                "We don't know %(foods)s. Pick from the list.",
                params={"foods": ", ".join(unknown)},
            )
        return ", ".join(option.label for option in options)

    def clean_favorite_foods(self):
        return self._clean_foods("favorite_foods")

    def clean_disliked_foods(self):
        return self._clean_foods("disliked_foods")

    def clean_allergies(self):
        keys = self.cleaned_data.get("allergies") or []
        return ", ".join(ALLERGY_LABELS[key] for key in keys)

    def clean(self):
        cleaned = super().clean()
        liked = set(filter(None, (cleaned.get("favorite_foods") or "").split(", ")))
        disliked = set(filter(None, (cleaned.get("disliked_foods") or "").split(", ")))
        both = sorted(liked & disliked)
        if both:
            self.add_error(
                "disliked_foods",
                f"{', '.join(both)} can't be both a favorite and disliked.",
            )
        return cleaned

    def clean_email(self):
        email = self.cleaned_data["email"]
        if (
            email
            and User.objects.filter(email__iexact=email)
            .exclude(pk=self.instance.user_id)
            .exists()
        ):
            raise forms.ValidationError("An account with this email already exists.")
        return email


class IconScaleWidget(forms.RadioSelect):
    """A 1-5 scale as a row of icon buttons (radio inputs hidden by CSS)."""

    def __init__(self, icons, attrs=None):
        super().__init__(attrs)
        self.icons = icons  # value -> Tabler icon name

    def render(self, name, value, attrs=None, renderer=None):
        base_id = (attrs or {}).get("id", f"id_{name}")
        options = format_html_join(
            "",
            '<label class="checkin-option" for="{0}_{1}">'
            '<input type="radio" name="{2}" value="{3}" id="{0}_{1}"{4}>'
            "{5}<span>{6}</span></label>",
            (
                (
                    base_id,
                    index,
                    name,
                    key,
                    mark_safe(" checked") if str(key) == str(value) else "",
                    icon(self.icons.get(key, ""), "checkin-option__icon", 28),
                    label,
                )
                for index, (key, label) in enumerate(self.choices)
            ),
        )
        return format_html(
            '<div class="checkin-scale" id="{}" role="radiogroup">{}</div>',
            base_id,
            options,
        )

    def id_for_label(self, id_, index=None):
        return id_


class MoodLogForm(forms.ModelForm):
    # Declared without Django's blank "---------" choice: nothing is picked
    # until the user taps one.
    mood = forms.TypedChoiceField(
        choices=MoodLog.MOOD_CHOICES,
        coerce=int,
        label="Mood",
        widget=IconScaleWidget(MOOD_ICONS),
        error_messages={
            "invalid_choice": "Pick a mood from the list.",
            "required": "Pick a mood.",
        },
    )
    energy_level = forms.TypedChoiceField(
        choices=MoodLog.ENERGY_CHOICES,
        coerce=int,
        label="Energy level",
        widget=IconScaleWidget(ENERGY_ICONS),
        error_messages={
            "invalid_choice": "Pick an energy level from the list.",
            "required": "Pick an energy level.",
        },
    )

    class Meta:
        model = MoodLog
        fields = ("mood", "energy_level")
