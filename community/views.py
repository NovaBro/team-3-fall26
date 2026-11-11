from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count
from django.forms import ImageField
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from community.keys import DOHMH, FARMERS_MARKET, GROCERY, KINDS
from community.models import (
    CommunitySubject,
    PlaceEnrichment,
    PlaceReview,
    UserComment,
    UserPhoto,
    UserRating,
)

GOOGLE_ENRICHMENT_KINDS = {DOHMH, FARMERS_MARKET, GROCERY}

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

def _google_payload(
    kind,
    key,
    comments_by_review=None,
    labels=None,
    photos_by_comment=None,
    replies_by_parent=None,
):
    if kind != DOHMH or not key.startswith("camis:"):
        return None
    place = (
        PlaceEnrichment.objects.filter(kind=kind, key=key)
        .prefetch_related("reviews")
        .first()
    )
    if place is None:
        return None
    comments_by_review = comments_by_review or {}
    labels = labels or {}
    photos_by_comment = photos_by_comment or {}
    replies_by_parent = replies_by_parent or {}
    return {
        "rating": place.rating,
        "user_rating_count": place.user_rating_count,
        "reviews": [
            {
                "id": review.id,
                "author_name": review.author_name,
                "rating": review.rating,
                "text": review.text,
                "relative_time": review.relative_time,
                "comments": [
                    _comment_dict(
                        comment, labels, photos_by_comment, replies_by_parent
                    )
                    for comment in comments_by_review.get(review.id, [])
                ],
            }
            for review in place.reviews.all()
        ],
    }


def _photo_dict(photo, labels):
    if not photo.image:
        return None
    return {
        "id": photo.id,
        "url": photo.image.url,
        "author": labels.get(photo.user_id, "User"),
        "created_at": photo.created_at.isoformat(),
    }


def _comment_dict(comment, labels, photos_by_comment, replies_by_parent=None):
    photos = [
        item
        for item in (
            _photo_dict(photo, labels)
            for photo in photos_by_comment.get(comment.id, [])
        )
        if item is not None
    ]
    payload = {
        "id": comment.id,
        "author": labels.get(comment.user_id, "User"),
        "text": comment.text,
        "created_at": comment.created_at.isoformat(),
        "photos": photos,
    }
    if replies_by_parent is not None:
        payload["replies"] = [
            _comment_dict(reply, labels, photos_by_comment)
            for reply in replies_by_parent.get(comment.id, [])
        ]
    return payload


def panel_payload(request, subject):
    stats = subject.ratings.aggregate(average=Avg("score"), count=Count("id"))
    user_rating = None
    if request.user.is_authenticated:
        user_rating = (
            subject.ratings.filter(user_id=request.user.id)
            .values_list("score", flat=True)
            .first()
        )
    comments = list(
        subject.comments.select_related("parent", "google_review").order_by(
            "created_at"
        )[:COMMENT_LIMIT]
    )
    photos = list(subject.photos.select_related("comment").all()[:PHOTO_LIMIT])
    labels = _author_labels(
        {item.user_id for item in comments} | {item.user_id for item in photos}
    )
    photos_by_comment = {}
    pin_photos = []
    for photo in photos:
        if photo.comment_id:
            photos_by_comment.setdefault(photo.comment_id, []).append(photo)
        else:
            pin_photos.append(photo)
    replies_by_parent = {}
    top_level = []
    comments_by_review = {}
    for comment in comments:
        if comment.parent_id:
            replies_by_parent.setdefault(comment.parent_id, []).append(comment)
        elif comment.google_review_id:
            comments_by_review.setdefault(comment.google_review_id, []).append(comment)
        else:
            top_level.append(comment)
    top_level.reverse()
    for review_comments in comments_by_review.values():
        review_comments.reverse()
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
            _comment_dict(comment, labels, photos_by_comment, replies_by_parent)
            for comment in top_level
        ],
        "photos": [
            item
            for item in (_photo_dict(photo, labels) for photo in pin_photos)
            if item is not None
        ],
        "google": _google_payload(
            subject.kind,
            subject.key,
            comments_by_review=comments_by_review,
            labels=labels,
            photos_by_comment=photos_by_comment,
            replies_by_parent=replies_by_parent,
        ),
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


def _parent_comment(subject, raw_parent_id):
    """Return a top-level comment on *subject*, or an error response."""
    if raw_parent_id in (None, ""):
        return None, None
    try:
        parent_id = int(raw_parent_id)
    except (TypeError, ValueError):
        return None, JsonResponse({"error": "Invalid parent comment."}, status=400)
    parent = UserComment.objects.filter(pk=parent_id, subject=subject).first()
    if parent is None:
        return None, JsonResponse({"error": "Parent comment not found."}, status=400)
    if parent.parent_id is not None:
        return None, JsonResponse(
            {"error": "Replies can only be added to top-level comments."}, status=400
        )
    return parent, None


def _comment_for_photo(subject, raw_comment_id):
    if raw_comment_id in (None, ""):
        return None, None
    try:
        comment_id = int(raw_comment_id)
    except (TypeError, ValueError):
        return None, JsonResponse({"error": "Invalid comment."}, status=400)
    comment = UserComment.objects.filter(pk=comment_id, subject=subject).first()
    if comment is None:
        return None, JsonResponse({"error": "Comment not found."}, status=400)
    return comment, None


def _google_review_for_subject(subject, raw_review_id):
    if raw_review_id in (None, ""):
        return None, None
    try:
        review_id = int(raw_review_id)
    except (TypeError, ValueError):
        return None, JsonResponse({"error": "Invalid Google review."}, status=400)
    if subject.kind != DOHMH or not subject.key.startswith("camis:"):
        return None, JsonResponse(
            {"error": "Google reviews are not available here."}, status=400
        )
    camis = subject.key.split(":", 1)[1]
    review = (
        PlaceReview.objects.filter(pk=review_id, place__camis=camis)
        .select_related("place")
        .first()
    )
    if review is None:
        return None, JsonResponse({"error": "Google review not found."}, status=400)
    return review, None


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
    parent, error = _parent_comment(subject, request.POST.get("parent_id"))
    if error is not None:
        return error
    google_review, error = _google_review_for_subject(
        subject, request.POST.get("google_review_id")
    )
    if error is not None:
        return error
    if parent is not None and google_review is not None:
        return JsonResponse(
            {"error": "A reply cannot also target a Google review."}, status=400
        )
    created = UserComment.objects.create(
        subject=subject,
        parent=parent,
        google_review=google_review,
        user_id=request.user.id,
        text=text,
    )
    payload = panel_payload(request, subject)
    payload["created_comment_id"] = created.id
    return JsonResponse(payload)


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
    linked_comment, error = _comment_for_photo(subject, request.POST.get("comment_id"))
    if error is not None:
        return error
    UserPhoto.objects.create(
        subject=subject,
        comment=linked_comment,
        user_id=request.user.id,
        image=cleaned,
    )
    return JsonResponse(panel_payload(request, subject))
