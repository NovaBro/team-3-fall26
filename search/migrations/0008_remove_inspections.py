"""Restaurants come from Google Places now (community.Restaurant).

Migrate the community database first: its 0011 reads cuisine and borough
from the summary table this migration deletes.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0007_remove_unused_datasets"),
    ]

    operations = [
        migrations.DeleteModel(name="RestaurantInspection"),
        migrations.DeleteModel(name="RestaurantSummary"),
    ]
