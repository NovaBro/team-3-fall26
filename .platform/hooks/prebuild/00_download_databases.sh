#!/bin/bash
# SQLite cannot open an s3:// path. Download the canonical databases onto
# local disk before container_commands run migrate.
set -eu
mkdir -p /var/app/staging/database
aws s3 cp s3://elasticbeanstalk-us-east-1-322134621417/nyc_food.db /var/app/staging/database/nyc_food.db
aws s3 cp s3://elasticbeanstalk-us-east-1-322134621417/community.db /var/app/staging/database/community.db
# Hooks run as root but gunicorn runs as webapp; SQLite needs write access to
# both the files and the directory (for its journal).
chown -R webapp:webapp /var/app/staging/database
