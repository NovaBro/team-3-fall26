#!/bin/bash
# eb setenv redeploys the zip and skips container_commands, which deletes
# staticfiles/. Collect them again before staging is moved to /var/app/current.
set -eu
cd /var/app/staging
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-nycfood.settings}"
source /var/app/venv/*/bin/activate
python manage.py collectstatic --noinput
