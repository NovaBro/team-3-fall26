from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0003_restaurantinspection_cuisine"),
    ]

    operations = [
        migrations.DeleteModel(name="PlaceReview"),
        migrations.DeleteModel(name="PlaceEnrichment"),
    ]
