from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from accounts.forms import MoodLogForm, SignupForm, UserProfileForm
from accounts.models import MoodLog, UserProfile
from accounts.tokens import email_verification_token

MOOD_HISTORY_LIMIT = 10
WIDE_FIELDS = {
    "home_address",
    "favorite_foods",
    "disliked_foods",
    "health_goals",
    "allergies",
}


def _send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verify_url = request.build_absolute_uri(
        reverse("accounts:verify_email", args=[uid, token])
    )
    send_mail(
        subject="Confirm your NYC Food Search account",
        message=(
            f"Hi {user.username},\n\n"
            "Confirm your email address to finish creating your account:\n"
            f"{verify_url}\n\n"
            "If you didn't sign up for NYC Food Search, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            UserProfile.objects.get_or_create(
                user=user, defaults={"name": form.cleaned_data["name"]}
            )
            _send_verification_email(request, user)
            messages.success(
                request,
                "Almost there! We emailed you a link to confirm your account.",
            )
            return redirect("accounts:login")
        if "email" in form.errors and any(
            "already exists" in error for error in form.errors["email"]
        ):
            messages.error(request, "An account with this email already exists.")
        else:
            messages.error(request, "Unable to register. Please fix the errors below.")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})


def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not email_verification_token.check_token(user, token):
        messages.error(request, "This verification link is invalid or has expired.")
        return redirect("accounts:login")

    if user.is_active:
        # Already confirmed (link opened twice): don't hand out a fresh
        # session on every replay, just send them to log in normally.
        messages.info(request, "This account is already confirmed. Please log in.")
        return redirect("accounts:login")

    user.is_active = True
    user.save(update_fields=["is_active"])
    login(
        request, user, backend="django.contrib.auth.backends.AllowAllUsersModelBackend"
    )
    messages.success(request, "Email confirmed. Welcome!")
    return redirect("accounts:profile")


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
            fixed_form = UserProfileForm(request.POST, request.FILES, instance=instance)
            mood_form = MoodLogForm()
            if fixed_form.is_valid():
                fixed = fixed_form.save(commit=False)
                fixed.user = request.user
                fixed.save()
                request.user.first_name = fixed_form.cleaned_data.get("first_name", "")
                request.user.last_name = fixed_form.cleaned_data.get("last_name", "")
                request.user.email = fixed_form.cleaned_data["email"]
                request.user.save(update_fields=["first_name", "last_name", "email"])
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
            "profile": instance,
        },
    )


def view_profile(request, username):
    user = get_object_or_404(User, username=username)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    return render(
        request,
        "accounts/view_profile.html",
        {"profile_user": user, "profile": profile},
    )


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("search:index")
