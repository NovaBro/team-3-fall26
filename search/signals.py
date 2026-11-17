"""Keep RestaurantSummary in step when single inspection rows change.

Bulk loads (bulk_create, update) send no signals; run
``python manage.py rebuild_restaurant_summary`` after them, or wrap the load
in ``paused()`` and rebuild once at the end (as import_datasets does).
"""

import threading
from contextlib import contextmanager

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from search.models import RestaurantInspection, RestaurantSummary
from search.summary import refresh

_state = threading.local()


@contextmanager
def paused():
    """Skip per-row refreshes (e.g. while deleting 300,000 rows)."""
    _state.paused = True
    try:
        yield
    finally:
        _state.paused = False


@receiver(post_save, sender=RestaurantInspection)
@receiver(post_delete, sender=RestaurantInspection)
def refresh_summary(sender, instance, using="default", **kwargs):
    if getattr(_state, "paused", False):
        return
    refresh(RestaurantInspection, RestaurantSummary, [instance.camis], using=using)
