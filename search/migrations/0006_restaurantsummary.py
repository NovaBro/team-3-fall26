from django.db import migrations, models


def build(apps, schema_editor):
    from search.summary import rebuild_all

    rebuild_all(
        apps.get_model("search", "RestaurantInspection"),
        apps.get_model("search", "RestaurantSummary"),
        using=schema_editor.connection.alias,
    )


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
