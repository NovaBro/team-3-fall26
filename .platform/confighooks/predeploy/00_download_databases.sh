#!/bin/bash
# Configuration deploys (eb setenv) skip container_commands and replace the
# app directory. Download the canonical databases again before the app starts.
set -eu
mkdir -p /var/app/staging/database
aws s3 cp s3://elasticbeanstalk-us-east-1-322134621417/nyc_food.db /var/app/staging/database/nyc_food.db
aws s3 cp s3://elasticbeanstalk-us-east-1-322134621417/community.db /var/app/staging/database/community.db
# users.db holds accounts; on the first deploy after the split it may not be
# in S3 yet, so a missing file is fine (migrate --database=users creates it).
aws s3 cp s3://elasticbeanstalk-us-east-1-322134621417/users.db /var/app/staging/database/users.db || true
# Hooks run as root but gunicorn runs as webapp; SQLite needs write access to
# both the files and the directory (for its journal).
chown -R webapp:webapp /var/app/staging/database
