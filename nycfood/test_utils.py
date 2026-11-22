"""Shared test helpers."""

# Every database a test may touch: datasets, community data, user accounts.
ALL_DATABASES = {"default", "community", "users"}


def make_restaurant(place_id="place-1", name="Test Kitchen", **fields):
    """Create a community.Restaurant (Google-backed) row for a test.

    Defaults describe an open, well-rated Manhattan restaurant; pass any
    Restaurant field to change it.
    """
    from community.models import Restaurant

    values = {
        "name": name,
        "address": "1 Main St, New York, NY 10001",
        "street": "1 Main St",
        "zipcode": "10001",
        "boro": "Manhattan",
        "cuisine": "American",
        "latitude": 40.75,
        "longitude": -73.99,
        "rating": 4.5,
        "rating_count": 120,
        "business_status": "OPERATIONAL",
    }
    values.update(fields)
    return Restaurant.objects.create(place_id=place_id, **values)
