#!/usr/bin/env bash
# Upload the app's secrets to SSM Parameter Store as SecureString parameters under /nycfood/.
# Google keys are read from .env and overwritten on each run; DJANGO_SECRET_KEY is generated
# once and left alone afterwards so existing sessions stay valid.
#
# Usage: deploy/push_ssm_params.sh [path/to/.env]
# Needs AWS credentials allowed to call ssm:PutParameter on /nycfood/*.
set -euo pipefail

ENV_FILE="${1:-.env}"
PREFIX="/nycfood"
KEYS=(GOOGLE_API_KEY GOOGLE_PLACES_API_KEY GOOGLE_MAPS_JS_KEY)

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

read_env() {
  # Last assignment wins; strips optional surrounding quotes. Does not execute the file.
  local line
  line="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

for key in "${KEYS[@]}"; do
  value="$(read_env "$key")"
  if [[ -z "$value" ]]; then
    echo "Skipping $key: empty in $ENV_FILE (EB bootstrap fails if the parameter does not exist)" >&2
    continue
  fi
  aws ssm put-parameter --name "$PREFIX/$key" --type SecureString --value "$value" --overwrite >/dev/null
  echo "Set $PREFIX/$key"
done

if aws ssm get-parameter --name "$PREFIX/DJANGO_SECRET_KEY" >/dev/null 2>&1; then
  echo "Kept existing $PREFIX/DJANGO_SECRET_KEY"
else
  secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
  aws ssm put-parameter --name "$PREFIX/DJANGO_SECRET_KEY" --type SecureString --value "$secret" >/dev/null
  echo "Created $PREFIX/DJANGO_SECRET_KEY"
fi
