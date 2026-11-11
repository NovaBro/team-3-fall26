from django.http import Http404
from django.shortcuts import redirect

from restaurants.places import get_photo_url


def photo(request):
    """Redirect to a place photo; keeps the server API key out of the browser."""
    url = get_photo_url(request.GET.get("name", ""))
    if not url:
        raise Http404("No photo")
    response = redirect(url)
    response["Cache-Control"] = "public, max-age=86400"
    return response
