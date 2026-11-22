#!/bin/bash
# Config deploys (eb setenv) download the databases again (00_) and skip
# container_commands, so tables added by migrations (e.g. the restaurant
# summary) would be missing. Run migrate here too.
set -eu
cd /var/app/staging
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-nycfood.settings}"
source /var/app/venv/*/bin/activate
# community first: its 0011 reads restaurant data that search/0008 deletes.
python manage.py migrate --database=community --noinput
python manage.py migrate --database=users --noinput
# Copies accounts out of nyc_food.db only while users.db has none.
python manage.py move_accounts_db || true
python manage.py migrate --noinput
chown -R webapp:webapp /var/app/staging/database
