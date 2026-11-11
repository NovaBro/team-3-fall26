from django.db import migrations, models


def fill_kind_key(apps, schema_editor):
    PlaceEnrichment = apps.get_model("community", "PlaceEnrichment")
    for row in PlaceEnrichment.objects.all().iterator():
        camis = (row.camis or "").strip()
        row.kind = "restaurant_dohmh"
        row.key = f"camis:{camis}" if camis else f"legacy:{row.pk}"
        row.save(update_fields=["kind", "key"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("community", "0002_locationlookup"),
    ]

    operations = [
        migrations.AddField(
            model_name="placeenrichment",
            name="kind",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=32
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="placeenrichment",
            name="key",
            field=models.CharField(blank=True, default="", max_length=512),
            preserve_default=False,
        ),
        migrations.RunPython(fill_kind_key, noop_reverse),
        migrations.AlterField(
            model_name="placeenrichment",
            name="camis",
            field=models.CharField(blank=True, db_index=True, max_length=20),
        ),
        migrations.AlterField(
            model_name="placeenrichment",
            name="kind",
            field=models.CharField(db_index=True, max_length=32),
        ),
        migrations.AlterField(
            model_name="placeenrichment",
            name="key",
            field=models.CharField(max_length=512),
        ),
        migrations.AddConstraint(
            model_name="placeenrichment",
            constraint=models.UniqueConstraint(
                fields=("kind", "key"), name="community_enrichment_kind_key"
            ),
        ),
    ]
