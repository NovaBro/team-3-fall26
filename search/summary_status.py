"""Use RestaurantSummary when it is ready; otherwise group the inspection rows.

Top picks and Explore more read RestaurantSummary (one row per restaurant).
Every deploy replaces the server DB with the copy from S3, which has no such
table; it only comes back when migrate runs. If that step is skipped, the home
page used to fail with "no such table: search_restaurantsummary" (500).

Now the home page never fails for that reason:

- table has rows -> use it (fast)
- table missing or empty -> group the inspection rows as before (slow, but the
  page works), and repair the table once in the background: migrate the
  search app if the table is missing, then fill it if it is empty.

Only one process repairs at a time (an OS file lock that is released even if
the process dies). Once a process sees the table ready it stops checking.

fcntl exists only on Linux/macOS. On Windows (local development) it is None
and the repair runs without the file lock; the server runs Linux.
"""

import logging
import os
import tempfile
import threading
import time

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

from django.conf import settings
from django.core.management import call_command
from django.db import DatabaseError, connections, transaction

logger = logging.getLogger(__name__)

READY, EMPTY, MISSING = "ready", "empty", "missing"
RECHECK_SECONDS = 30  # while not ready, look again at most this often
LOCK_PATH = os.path.join(tempfile.gettempdir(), "nycfood-restaurant-summary.lock")

_state = {"ready": False, "checked_at": None, "repairing": False}
_state_lock = threading.Lock()


def reset():
    """Forget what this process knows (for tests)."""
    with _state_lock:
        _state.update(ready=False, checked_at=None, repairing=False)


def table_status(using="default"):
    """READY, EMPTY (table but no rows while inspections exist) or MISSING."""
    from search.models import RestaurantInspection, RestaurantSummary

    connection = connections[using]
    try:
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
        if RestaurantSummary._meta.db_table not in tables:
            return MISSING
        if RestaurantSummary.objects.using(using).exists():
            return READY
        if RestaurantInspection.objects.using(using).exists():
            return EMPTY
    except DatabaseError:
        return MISSING
    return READY  # nothing to summarise yet: both ways give the same result


def summary_ready(using="default"):
    """True when RestaurantSummary can be used. May start a background repair."""
    if _state["ready"]:
        return True
    with _state_lock:
        if _state["ready"]:
            return True
        now = time.monotonic()
        checked_at = _state["checked_at"]
        if checked_at is not None and now - checked_at < RECHECK_SECONDS:
            return False
        _state["checked_at"] = now
        status = table_status(using)
        if status == READY:
            _state["ready"] = True
            return True
        logger.warning(
            "RestaurantSummary is %s; the home page uses the slower group-by "
            "query until it is repaired.",
            status,
        )
        if getattr(settings, "RESTAURANT_SUMMARY_SELF_REPAIR", True) and not (
            _state["repairing"]
        ):
            _state["repairing"] = True
            threading.Thread(target=repair, args=(using,), daemon=True).start()
        return False


def repair(using="default"):
    """Create and/or fill RestaurantSummary, at most one process at a time."""
    from search.models import RestaurantInspection, RestaurantSummary
    from search.summary import rebuild_all

    try:
        with open(LOCK_PATH, "a") as handle:
            if fcntl is not None:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return  # another process is repairing right now
            status = table_status(using)
            if status == MISSING:
                call_command(
                    "migrate", "search", database=using, interactive=False, verbosity=0
                )
                status = table_status(using)
            if status == EMPTY:
                with transaction.atomic(using=using):
                    total = rebuild_all(
                        RestaurantInspection, RestaurantSummary, using=using
                    )
                logger.warning("RestaurantSummary filled: %s restaurants.", total)
                status = table_status(using)
            if status == READY:
                logger.warning("RestaurantSummary is ready again.")
            else:
                logger.error("RestaurantSummary repair failed (still %s).", status)
    except Exception:
        logger.exception("RestaurantSummary repair failed.")
    finally:
        connections[using].close()  # this thread's connection
        with _state_lock:
            _state["repairing"] = False
            _state["checked_at"] = None  # look again on the next request
