#!/bin/bash
# Warm up the app right after a deploy, so the first real visitor doesn't
# wait for the empty Google cache, the AI model load and the summary check
# (about 20 s on the first request otherwise). Runs in the background and
# never fails the deploy.
HOST=$(/opt/elasticbeanstalk/bin/get-config environment -k DJANGO_ALLOWED_HOSTS 2>/dev/null | cut -d, -f1)
HOST=${HOST:-localhost}
(
  sleep 5
  curl -s -o /dev/null -m 120 -H "Host: $HOST" http://127.0.0.1:8000/ || true
) >/dev/null 2>&1 &
exit 0
