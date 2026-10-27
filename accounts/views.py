from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.forms import MoodLogForm, SignupForm, UserProfileForm
from accounts.models import MoodLog, UserProfile

MOOD_HISTORY_LIMIT = 10
WIDE_FIELDS = {
    "home_address",
    "favorite_foods",
    "disliked_foods",
    "health_goals",
    "allergies",
}


def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.get_or_create(
                user=user, defaults={"name": form.cleaned_data["name"]}
            )
            login(request, user)
            messages.success(request, "Welcome! Tell us a bit about yourself below.")
            return redirect("accounts:profile")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})


@login_required
def profile(request):
    instance, _created = UserProfile.objects.get_or_create(user=request.user)
    mood_history = MoodLog.objects.filter(user=request.user)[:MOOD_HISTORY_LIMIT]

    if request.method == "POST":
        if request.POST.get("action") == "log_mood":
            mood_form = MoodLogForm(request.POST)
            fixed_form = UserProfileForm(instance=instance)
            if mood_form.is_valid():
                log = mood_form.save(commit=False)
                log.user = request.user
                log.save()
                messages.success(request, "Check-in saved.")
                return redirect("accounts:profile")
            messages.error(request, "Please fix the errors below.")
        else:
            fixed_form = UserProfileForm(
                request.POST, request.FILES, instance=instance
            )
            mood_form = MoodLogForm()
            if fixed_form.is_valid():
                fixed = fixed_form.save(commit=False)
                fixed.user = request.user
                fixed.save()
                request.user.email = fixed_form.cleaned_data["email"]
                request.user.save(update_fields=["email"])
                messages.success(request, "Profile updated.")
                return redirect("accounts:profile")
            messages.error(request, "Please fix the errors below.")
    else:
        fixed_form = UserProfileForm(instance=instance)
        mood_form = MoodLogForm()

    return render(
        request,
        "accounts/profile.html",
        {
            "fixed_form": fixed_form,
            "mood_form": mood_form,
            "mood_history": mood_history,
            "wide_fields": WIDE_FIELDS,
        },
    )


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("search:index")
