from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render

from accounts.forms import NameForm, PictureForm, SignupForm
from accounts.models import Profile


def signup(request):
    if request.user.is_authenticated:
        return redirect("search:index")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Account created successfully. Welcome, {user.username}!")
            return redirect("search:index")
        if "email" in form.errors and any("already exists" in e for e in form.errors["email"]):
            messages.error(request, "An account with this email already exists.")
        else:
            messages.error(request, "Unable to register. Please fix the errors below.")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})


@login_required
def edit_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        name_form = NameForm(request.POST, instance=request.user)
        picture_form = PictureForm(request.POST, request.FILES, instance=profile)
        if name_form.is_valid() and picture_form.is_valid():
            name_form.save()
            picture_form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:edit_profile")
        messages.error(request, "Unable to update profile. Please fix the errors below.")
    else:
        name_form = NameForm(instance=request.user)
        picture_form = PictureForm(instance=profile)
    return render(request, "accounts/edit_profile.html",
                  {"name_form": name_form, "picture_form": picture_form, "profile": profile})


def view_profile(request, username):
    user = get_object_or_404(User, username=username)
    profile, _ = Profile.objects.get_or_create(user=user)
    return render(request, "accounts/view_profile.html", {"profile_user": user, "profile": profile})
