from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count
from django.forms import ImageField
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from community.keys import DOHMH, KINDS
from community.models import (
    CommunitySubject,
    PlaceEnrichment,
    UserComment,
    UserPhoto,
    UserRating,
)

COMMENT_LIMIT = 50
PHOTO_LIMIT = 24
COMMENT_MAX_LENGTH = 2000


def _subject(kind, key, name="", address=""):
    if kind not in KINDS or not key:
        raise Http404("Unknown place")
    subject, created = CommunitySubject.objects.get_or_create(
        kind=kind,
        key=key,
        defaults={"name": (name or "")[:255], "address": (address or "")[:512]},
    )
    if not created and name and subject.name != name:
        subject.name = name[:255]
        subject.address = (address or "")[:512]
        subject.save(update_fields=["name", "address"])
    return subject


def _author_labels(user_ids):
    users = User.objects.filter(pk__in=user_ids).only(
        "id", "username", "first_name", "last_name"
    )
    return {user.pk: user.get_full_name() or user.username for user in users}


def _google_payload(kind, key):
    if kind != DOHMH or not key.startswith("camis:"):
        return None
    camis = key.split(":", 1)[1]
    place = (
        PlaceEnrichment.objects.filter(camis=camis)
        .prefetch_related("reviews")
        .first()
    )
    if place is None:
        return None
    return {
        "rating": place.rating,
        "user_rating_count": place.user_rating_count,
        "reviews": [
            {
                "author_name": review.author_name,
                "rating": review.rating,
                "text": review.text,
                "relative_time": review.relative_time,
            }
            for review in place.reviews.all()
        ],
    }


def panel_payload(request, subject):
    stats = subject.ratings.aggregate(average=Avg("score"), count=Count("id"))
    user_rating = None
    if request.user.is_authenticated:
        user_rating = (
            subject.ratings.filter(user_id=request.user.id)
            .values_list("score", flat=True)
            .first()
        )
    comments = list(subject.comments.all()[:COMMENT_LIMIT])
    photos = list(subject.photos.all()[:PHOTO_LIMIT])
    labels = _author_labels(
        {item.user_id for item in comments} | {item.user_id for item in photos}
    )
    average = stats["average"]
    return {
        "kind": subject.kind,
        "key": subject.key,
        "name": subject.name,
        "address": subject.address,
        "authenticated": request.user.is_authenticated,
        "login_url": reverse("accounts:login"),
        "user_rating": user_rating,
        "average_rating": round(average, 1) if average is not None else None,
        "rating_count": stats["count"],
        "comments": [
            {
                "author": labels.get(comment.user_id, "User"),
                "text": comment.text,
                "created_at": comment.created_at.isoformat(),
            }
            for comment in comments
        ],
        "photos": [
            {
                "url": photo.image.url,
                "author": labels.get(photo.user_id, "User"),
                "created_at": photo.created_at.isoformat(),
            }
            for photo in photos
            if photo.image
        ],
        "google": _google_payload(subject.kind, subject.key),
    }


@require_GET
def detail(request, kind, key):
    subject = _subject(
        kind,
        key,
        name=request.GET.get("name", ""),
        address=request.GET.get("address", ""),
    )
    return JsonResponse(panel_payload(request, subject))


@login_required
@require_POST
def rate(request, kind, key):
    subject = _subject(
        kind,
        key,
        name=request.POST.get("name", ""),
        address=request.POST.get("address", ""),
    )
    try:
        score = int(request.POST.get("rating", ""))
    except (TypeError, ValueError):
        score = None
    if score not in range(1, 6):
        return JsonResponse({"error": "Rating must be from 1 to 5."}, status=400)
    UserRating.objects.update_or_create(
        subject=subject,
        user_id=request.user.id,
        defaults={"score": score},
    )
    return JsonResponse(panel_payload(request, subject))


@login_required
@require_POST
def comment(request, kind, key):
    subject = _subject(
        kind,
        key,
        name=request.POST.get("name", ""),
        address=request.POST.get("address", ""),
    )
    text = (request.POST.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "Write a comment first."}, status=400)
    if len(text) > COMMENT_MAX_LENGTH:
        return JsonResponse(
            {"error": "Comment must be 2000 characters or fewer."}, status=400
        )
    UserComment.objects.create(subject=subject, user_id=request.user.id, text=text)
    return JsonResponse(panel_payload(request, subject))


@login_required
@require_POST
def photo(request, kind, key):
    subject = _subject(
        kind,
        key,
        name=request.POST.get("name", ""),
        address=request.POST.get("address", ""),
    )
    upload = request.FILES.get("photo")
    if upload is None:
        return JsonResponse({"error": "Choose an image to upload."}, status=400)
    try:
        cleaned = ImageField().clean(upload)
    except ValidationError:
        return JsonResponse({"error": "Upload an image file."}, status=400)
    UserPhoto.objects.create(subject=subject, user_id=request.user.id, image=cleaned)
    return JsonResponse(panel_payload(request, subject))
