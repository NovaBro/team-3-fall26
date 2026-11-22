"""Google place ids replace DOHMH CAMIS ids for restaurants.

Adds the Restaurant pool, renames the camis columns to place_id, and re-keys
existing rows (see community/dohmh_conversion.py). Run this before migrating
the default database: it reads cuisine and borough from the inspection
summary there, which search/0008 deletes.
"""

from django.db import migrations, models


def forwards(apps, schema_editor):
    from community.dohmh_conversion import convert
    from community.models import shuffle_seed

    convert(lambda name: apps.get_model("community", name), shuffle_seed)


class Migration(migrations.Migration):

    dependencies = [
        ("community", "0010_menuestimate"),
    ]

    operations = [
        migrations.CreateModel(
            name="Restaurant",
            fields=[
                (
                    "place_id",
                    models.CharField(max_length=255, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(blank=True, db_index=True, max_length=255)),
                ("address", models.CharField(blank=True, max_length=512)),
                ("street", models.CharField(blank=True, max_length=255)),
                ("zipcode", models.CharField(blank=True, db_index=True, max_length=10)),
                ("boro", models.CharField(blank=True, db_index=True, max_length=50)),
                (
                    "cuisine",
                    models.CharField(blank=True, db_index=True, max_length=100),
                ),
                ("primary_type", models.CharField(blank=True, max_length=64)),
                ("latitude", models.FloatField(null=True)),
                ("longitude", models.FloatField(null=True)),
                ("rating", models.FloatField(null=True)),
                ("rating_count", models.IntegerField(null=True)),
                ("price_level", models.CharField(blank=True, max_length=32)),
                ("business_status", models.CharField(blank=True, max_length=32)),
                ("maps_url", models.CharField(blank=True, max_length=512)),
                ("photo_name", models.CharField(blank=True, max_length=512)),
                ("shuffle_seed", models.BigIntegerField(default=0)),
                ("fetched_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "restaurant"},
        ),
        migrations.RemoveConstraint(
            model_name="recommendationfeedback",
            name="community_feedback_user_camis",
        ),
        migrations.RenameField(
            model_name="recommendationfeedback", old_name="camis", new_name="place_id"
        ),
        migrations.AlterField(
            model_name="recommendationfeedback",
            name="place_id",
            field=models.CharField(max_length=255),
        ),
        migrations.RenameField(
            model_name="healthscore", old_name="camis", new_name="place_id"
        ),
        migrations.AlterField(
            model_name="healthscore",
            name="place_id",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.RenameField(
            model_name="reasonblurb", old_name="camis", new_name="place_id"
        ),
        migrations.AlterField(
            model_name="reasonblurb",
            name="place_id",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.RenameField(
            model_name="menuestimate", old_name="camis", new_name="place_id"
        ),
        migrations.AlterField(
            model_name="menuestimate",
            name="place_id",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="recommendationfeedback",
            constraint=models.UniqueConstraint(
                fields=("user_id", "place_id"), name="community_feedback_user_place"
            ),
        ),
        migrations.RemoveField(model_name="placeenrichment", name="camis"),
        migrations.AlterField(
            model_name="placeenrichment",
            name="place_id",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
    ]
