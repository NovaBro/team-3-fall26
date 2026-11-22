from django.db import migrations, models


def build(apps, schema_editor):
    # Filled the summary table from inspection rows; both tables were removed
    # in 0008 (restaurants now come from Google), so there is nothing to do.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0005_place_review"),
    ]

    operations = [
        migrations.CreateModel(
            name="RestaurantSummary",
            fields=[
                (
                    "camis",
                    models.CharField(max_length=20, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(blank=True, max_length=255)),
                ("boro", models.CharField(blank=True, db_index=True, max_length=50)),
                ("street", models.CharField(blank=True, max_length=255)),
                ("zipcode", models.CharField(blank=True, max_length=10)),
                (
                    "cuisine",
                    models.CharField(blank=True, db_index=True, max_length=100),
                ),
                ("last_date", models.DateField(null=True)),
                (
                    "latest_grade",
                    models.CharField(blank=True, db_index=True, max_length=2),
                ),
            ],
            options={
                "verbose_name": "restaurant summary",
                "verbose_name_plural": "restaurant summaries",
            },
        ),
        migrations.RunPython(build, migrations.RunPython.noop),
    ]
