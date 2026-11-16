from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("community", "0008_reasonblurb"),
    ]

    operations = [
        migrations.AddField(
            model_name="healthscore",
            name="goal_scores",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
