"""Model managers shared across apps."""

from django.db import models


class ActiveManager(models.Manager):
    """Only rows ``manage.py curate_pool`` kept in the pool (``active=True``)."""

    def get_queryset(self):
        return super().get_queryset().filter(active=True)
