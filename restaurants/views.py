from django.http import Http404
from django.shortcuts import redirect

from restaurants.places import get_photo_url
from search.services.places import forget_photo


def photo(request):
    """Redirect to a place photo; keeps the server API key out of the browser.

    An expired stored reference is cleared so Top picks fetch a new one.
    """
    url = get_photo_url(request.GET.get("name", ""), on_gone=forget_photo)
    if not url:
        raise Http404("No photo")
    response = redirect(url)
    response["Cache-Control"] = "public, max-age=86400"
    return response
