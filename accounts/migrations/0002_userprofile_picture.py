from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="picture",
            field=models.ImageField(
                blank=True, upload_to="profile_pictures/"
            ),
        ),
    ]