from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from accounts.forms import MoodLogForm, SignupForm, UserProfileForm
from accounts.models import MoodLog, UserProfile
from accounts.tokens import email_verification_token
from community.models import UserComment, UserPhoto, UserRating

MOOD_HISTORY_LIMIT = 10
ADMIN_PAGE_SIZE = 25
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


@login_required
def admin_dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    tab = request.GET.get("tab", "overview")
    if tab not in {"overview", "users", "comments"}:
        tab = "overview"
    context = {
        "active_tab": tab,
        "user_count": User.objects.count(),
        "active_user_count": User.objects.filter(is_active=True).count(),
        "comment_count": UserComment.objects.count(),
        "rating_count": UserRating.objects.count(),
    }

    if tab == "users":
        query = request.GET.get("q", "").strip()
        users = User.objects.all().order_by("username")
        if query:
            users = users.filter(
                Q(username__icontains=query)
                | Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            )
        page = Paginator(users, ADMIN_PAGE_SIZE).get_page(request.GET.get("page"))
        user_ids = [user.pk for user in page.object_list]
        profiles = {
            profile.user_id: profile
            for profile in UserProfile.objects.filter(user_id__in=user_ids)
        }
        activity_counts = _admin_activity_counts(user_ids)
        context.update(
            {
                "query": query,
                "user_page": page,
                "user_rows": [
                    {
                        "account": user,
                        "name": (
                            profiles[user.pk].name
                            if user.pk in profiles and profiles[user.pk].name
                            else user.get_full_name() or "Not provided"
                        ),
                        "activity": activity_counts[user.pk],
                    }
                    for user in page.object_list
                ],
            }
        )

    if tab == "comments":
        query = request.GET.get("q", "").strip()
        comments = UserComment.objects.select_related("subject").all()
        if query:
            matching_user_ids = list(
                User.objects.filter(
                    Q(username__icontains=query)
                    | Q(email__icontains=query)
                    | Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                ).values_list("pk", flat=True)
            )
            comments = comments.filter(
                Q(user_id__in=matching_user_ids)
                | Q(text__icontains=query)
                | Q(subject__name__icontains=query)
            )
        comment_page = Paginator(comments, ADMIN_PAGE_SIZE).get_page(
            request.GET.get("page")
        )
        authors = _admin_author_labels(
            {comment.user_id for comment in comment_page.object_list}
        )
        context.update(
            {
                "query": query,
                "comment_page": comment_page,
                "admin_comments": [
                    {
                        "comment": comment,
                        "author": authors.get(comment.user_id, "Former account"),
                    }
                    for comment in comment_page.object_list
                ],
            }
        )

    return render(request, "accounts/admin_dashboard.html", context)


@login_required
def admin_user_detail(request, user_id):
    if not request.user.is_superuser:
        raise PermissionDenied

    managed_user = get_object_or_404(User, pk=user_id)
    profile = UserProfile.objects.filter(user_id=managed_user.pk).first()
    comments = UserComment.objects.filter(user_id=managed_user.pk).select_related(
        "subject"
    )
    comment_page = Paginator(comments, ADMIN_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    counts = _admin_activity_counts([managed_user.pk]).get(managed_user.pk, {})
    return render(
        request,
        "accounts/admin_user_detail.html",
        {
            "managed_user": managed_user,
            "profile": profile,
            "comment_page": comment_page,
            "counts": counts,
        },
    )


def _admin_activity_counts(user_ids):
    if not user_ids:
        return {}
    counts = {
        user_id: {"comments": 0, "ratings": 0, "photos": 0}
        for user_id in user_ids
    }
    for model, key in (
        (UserComment, "comments"),
        (UserRating, "ratings"),
        (UserPhoto, "photos"),
    ):
        for row in model.objects.filter(user_id__in=user_ids).values("user_id").annotate(
            total=Count("id")
        ):
            counts[row["user_id"]][key] = row["total"]
    return counts


def _admin_author_labels(user_ids):
    users = User.objects.filter(pk__in=user_ids).only(
        "id", "username", "first_name", "last_name"
    )
    return {user.pk: user.get_full_name() or user.username for user in users}


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("search:index")
