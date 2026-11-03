import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_userprofile_picture"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="phone_number",
            field=models.CharField(
                blank=True,
                max_length=20,
                validators=[
                    django.core.validators.RegexValidator(
                        "^\\+?[0-9\\s\\-()]{7,20}$", "Enter a valid phone number."
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="promo_opt_in",
            field=models.BooleanField(
                default=False, verbose_name="Send me promotions and updates"
            ),
        ),
    ]
