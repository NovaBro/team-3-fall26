import django.utils.timezone
from django.db import migrations, models
from zoneinfo import ZoneInfo


def backfill_and_dedupe(apps, schema_editor):
    MoodLog = apps.get_model("accounts", "MoodLog")
    nyc = ZoneInfo("America/New_York")
    for log in MoodLog.objects.all().iterator():
        created = log.created_at
        if created.tzinfo is None:
            created = django.utils.timezone.make_aware(
                created, django.utils.timezone.utc
            )
        MoodLog.objects.filter(pk=log.pk).update(
            log_date=created.astimezone(nyc).date()
        )

    seen = set()
    for log in MoodLog.objects.order_by("-created_at", "-pk").iterator():
        key = (log.user_id, log.log_date)
        if key in seen:
            log.delete()
        else:
            seen.add(key)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_userprofile_contact_info"),
    ]

    operations = [
        migrations.AddField(
            model_name="moodlog",
            name="log_date",
            field=models.DateField(
                db_index=True,
                help_text="America/New_York calendar day for this check-in.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="moodlog",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_and_dedupe, noop_reverse),
        migrations.AlterField(
            model_name="moodlog",
            name="log_date",
            field=models.DateField(
                db_index=True,
                help_text="America/New_York calendar day for this check-in.",
            ),
        ),
        migrations.AlterModelOptions(
            name="moodlog",
            options={
                "ordering": ["-log_date", "-created_at"],
                "verbose_name": "mood log",
            },
        ),
        migrations.AddConstraint(
            model_name="moodlog",
            constraint=models.UniqueConstraint(
                fields=("user", "log_date"),
                name="accounts_moodlog_user_log_date_uniq",
            ),
        ),
    ]
