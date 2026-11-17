#!/bin/bash
# Config deploys (eb setenv) download the databases again (00_) and skip
# container_commands, so tables added by migrations (e.g. the restaurant
# summary) would be missing. Run migrate here too.
set -eu
cd /var/app/staging
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-nycfood.settings}"
source /var/app/venv/*/bin/activate
python manage.py migrate --noinput
python manage.py migrate --database=community --noinput
chown -R webapp:webapp /var/app/staging/database
