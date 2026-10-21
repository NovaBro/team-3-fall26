from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Public-facing personal info: name and picture, so others know who you are."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    picture = models.ImageField(upload_to="profiles/", blank=True)

    def __str__(self):
        return self.user.get_username()
