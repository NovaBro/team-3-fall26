from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from accounts.models import Profile


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class NameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name")


class PictureForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ("picture",)
