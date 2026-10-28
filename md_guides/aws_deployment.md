# AWS Elastic Beanstalk deployment

The Django site runs on AWS Elastic Beanstalk (EB) as a single EC2 instance. Code and the SQLite database ship together in each deploy; API keys and the Django secret key live in SSM Parameter Store and are injected as environment variables at startup.

Live URL: http://nycfood-team3.us-east-1.elasticbeanstalk.com

For the day-to-day flow of pulling from GitHub and deploying, see `deploy_workflow.md`.

| Setting | Value |
|---------|-------|
| AWS account / region | `322134621417` / `us-east-1` |
| EB application | `nycfood` |
| EB environment | `nycfood-env` (CNAME prefix `nycfood-team3`) |
| Platform | Python 3.11 on 64-bit Amazon Linux 2023 |
| Instance | `t3.small`, single instance (no load balancer), Elastic IP |
| Instance role | `aws-elasticbeanstalk-ec2-role` |
| CLI user | `software-engineer-eb` |

## How a deploy works

```
eb deploy (your laptop)
   │  zips the working directory, filtered by .ebignore
   ▼
S3 bucket elasticbeanstalk-us-east-1-322134621417     (EB always stages bundles here)
   │
   ▼
EC2 instance
   1. fetch secrets from SSM Parameter Store  ──►  environment variables
   2. pip install -r requirements.txt
   3. container_commands: migrate, collectstatic
   4. start gunicorn (Procfile) on :8000
   │
   ▼
nginx :80
   ├── /static/*  ──►  staticfiles/ on disk
   └── everything else  ──►  gunicorn  ──►  Django (nycfood.wsgi)
```

`eb deploy` uploads the **working directory**, not the last git commit (because `.ebignore` exists). Uncommitted and gitignored files such as `database/nyc_food.db` are included unless `.ebignore` excludes them.

## AWS pieces

| Service | What it does here |
|---------|-------------------|
| Elastic Beanstalk | Orchestrates everything below; one environment = one running copy of the site |
| EC2 | The virtual machine running nginx + gunicorn + Django |
| S3 | Stores each uploaded app version (zip). Not used by the app itself |
| SSM Parameter Store | Encrypted storage for API keys and `DJANGO_SECRET_KEY` |
| IAM | Permissions for the CLI user (deploying) and the instance role (reading SSM) |
| CloudFormation | Created by EB behind the scenes; do not edit the `awseb-*` stacks directly |

## Repo files

| File | Purpose |
|------|---------|
| `Procfile` | `web: gunicorn nycfood.wsgi:application --bind :8000` |
| `requirements.txt` | Installed on the instance at every deploy; includes `gunicorn` |
| `.ebextensions/django.config` | Settings module, WSGI path, nginx `/static` mapping, `migrate` + `collectstatic` on deploy |
| `.ebextensions/secrets.config` | Maps env var names to SSM parameter ARNs |
| `.ebignore` | What is **left out** of the bundle (venv, `.env`, datasets, notebooks, `deploy/`, ...) |
| `.elasticbeanstalk/config.yml` | Local EB CLI settings from `eb init` (gitignored) |
| `deploy/push_ssm_params.sh` | Uploads keys from `.env` to SSM (not deployed) |
| `deploy/ssm-read-policy.json` | IAM policy letting the instance read `/nycfood/*` (not deployed) |

## Django settings (`nycfood/settings.py`)

Production behavior is driven entirely by environment variables; with none set, the app behaves like local dev.

| Env var | Local default | Production | Source on EB |
|---------|---------------|------------|--------------|
| `DJANGO_DEBUG` | `True` | `False` | EB environment property |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | `.elasticbeanstalk.com` | EB environment property |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | only needed for HTTPS / custom domain | EB environment property |
| `DJANGO_SECRET_KEY` | insecure dev key | random | SSM `/nycfood/DJANGO_SECRET_KEY` |
| `GOOGLE_API_KEY` | from `.env` | | SSM `/nycfood/GOOGLE_API_KEY` |
| `GOOGLE_PLACES_API_KEY` | from `.env` | | SSM `/nycfood/GOOGLE_PLACES_API_KEY` |
| `GOOGLE_MAPS_JS_KEY` | from `.env` | | SSM `/nycfood/GOOGLE_MAPS_JS_KEY` |

`STATIC_ROOT = BASE_DIR / 'staticfiles'` is where `collectstatic` gathers CSS/JS; nginx serves it directly.

`.env` is only for local development. It is excluded from git and from the deploy bundle; on EB, `load_dotenv` finds nothing and the real values come from the environment.

## Secrets (SSM Parameter Store)

EB reads the ARNs in `.ebextensions/secrets.config` when an instance boots and sets each value as an ordinary environment variable, so Django code just uses `os.environ.get(...)`.

- All four parameters are `SecureString` (encrypted with the default `alias/aws/ssm` key) under `/nycfood/`.
- **Every parameter listed in `secrets.config` must exist**, or instance bootstrap fails.
- Do **not** also set these names with `eb setenv`; they would conflict.
- Changing a value in SSM does not update a running instance. Run `eb restart` (or `eb deploy`) afterwards.

Create or update them either way:

- **Script:** `deploy/push_ssm_params.sh` reads the Google keys from `.env` and overwrites them; it creates `DJANGO_SECRET_KEY` only if missing. Needs `ssm:PutParameter` / `ssm:GetParameter` on `/nycfood/*`.
- **Console:** Systems Manager → Parameter Store → Create parameter → Standard tier, type SecureString, exact name (e.g. `/nycfood/GOOGLE_API_KEY`).

### Google key restrictions

The Maps JavaScript key is rendered into page HTML (`<script src="...maps/api/js?key=...">`), so every visitor can see it. It cannot be hidden, only restricted. The Places keys are used server-side only and never reach the browser.

| Key | Application restriction | API restriction |
|-----|-------------------------|-----------------|
| `GOOGLE_MAPS_JS_KEY` | Websites: `http://nycfood-team3.us-east-1.elasticbeanstalk.com/*`, `http://localhost:8000/*`, `http://127.0.0.1:8000/*` | Maps JavaScript API |
| `GOOGLE_API_KEY`, `GOOGLE_PLACES_API_KEY` | None (do not use a website restriction on server keys) | Places API (New) |

Also set a billing budget alert in Google Cloud.

## IAM permissions

### CLI user `software-engineer-eb` (deploying)

- AWS managed policy `AdministratorAccess-AWSElasticBeanstalk`.
- Inline policy `eb-multipart-upload`. The managed policy lacks multipart permissions, and the EB CLI switches to multipart upload for bundles over 7 MB (ours is ~150 MB because of `nyc_food.db`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "s3:ListBucketMultipartUploads",
      "Resource": "arn:aws:s3:::elasticbeanstalk-us-east-1-322134621417" },
    { "Effect": "Allow", "Action": ["s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::elasticbeanstalk-us-east-1-322134621417/*" }
  ]
}
```

This user has **no** SSM or IAM-write permissions; create parameters and attach role policies as root/admin (or in the console).

### Instance role `aws-elasticbeanstalk-ec2-role` (running)

Inline policy `nycfood-ssm-read` = `deploy/ssm-read-policy.json` (`ssm:GetParameter(s)` on `/nycfood/*`). This role is shared by every EB environment in the account (including the old `django-tutorial` app's `django-env`).

## First-time setup (already done)

1. Create the four SSM parameters (above).
2. Attach `nycfood-ssm-read` to `aws-elasticbeanstalk-ec2-role`.
3. Add the Google key restrictions.
4. From the repo root:

```bash
eb init -p "python-3.11" nycfood --region us-east-1
eb create nycfood-env --cname nycfood-team3 --single --instance_type t3.small \
  --envvars DJANGO_DEBUG=False,DJANGO_ALLOWED_HOSTS=.elasticbeanstalk.com
```

A teammate deploying from their own machine needs the EB CLI (`pip install awsebcli`), AWS credentials with the CLI user's permissions, and `eb init` (pick the existing `nycfood` application, region `us-east-1`), then `eb use nycfood-env`.

## Everyday commands

| Task | Command |
|------|---------|
| Deploy current code | `eb deploy` |
| Open the site | `eb open` |
| Health / status | `eb status`, `eb health` |
| Recent events | `eb events` |
| Logs | `eb logs` (look at `web.stdout.log`, `eb-engine.log`) |
| Set non-secret env vars | `eb setenv NAME=value` (restarts the app) |
| Pick up new SSM values | `eb restart` |
| Shut everything down | `eb terminate nycfood-env` |

Before deploying, run the tests locally:

```bash
.venv/bin/python manage.py test
DJANGO_DEBUG=False DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=.elasticbeanstalk.com \
  .venv/bin/python manage.py check --deploy
```

The four remaining `check --deploy` warnings (HSTS, SSL redirect, secure cookies) are HTTPS-only settings. The site is plain HTTP for now; enabling them without HTTPS breaks login.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `NotAuthorizedError ... s3:ListBucketMultipartUploads` on deploy | CLI user missing the `eb-multipart-upload` inline policy |
| Instance fails to start right after creation / deploy | An SSM parameter in `secrets.config` is missing, misspelled, or the instance role cannot read it |
| `Bad Request (400)` | Host not in `DJANGO_ALLOWED_HOSTS` |
| Pages load without CSS | `collectstatic` failed or `/static` mapping missing; check `eb-engine.log` |
| Map says to set `GOOGLE_MAPS_JS_KEY` | Parameter missing / empty, or instance not restarted after changing it |
| Map shows a Google error | Site URL not in the Maps JS key's referrer list (changes take a few minutes) |
| `502 Bad Gateway` | gunicorn crashed; check `web.stdout.log` |

`eb ssh` is not set up (no EC2 key pair was chosen during `eb init`). Run `eb ssh --setup` if shell access is needed.

## Costs

Roughly $15/month for a `t3.small` running 24/7, plus the Elastic IP while the environment exists. SSM standard parameters are free. S3 keeps every uploaded app version (~150 MB each); delete old versions in the EB console under Application versions, or configure a version lifecycle policy. `eb terminate nycfood-env` stops all charges except stored S3 versions.

## Known limitations

- **The database resets on every deploy.** `database/nyc_food.db` is shipped inside the bundle and replaces the instance's copy, so user accounts and cached Google enrichments created on the live site are lost on `eb deploy`, and also if EB replaces the instance. Fix planned: move to RDS PostgreSQL.
- Single instance only; SQLite cannot be shared across instances.
- HTTP only. HTTPS needs a load balancer + ACM certificate (or a certificate on the instance), then the secure-cookie settings above.
- Large bundles (~150 MB) make deploys slow; moving the DB to RDS removes it from the bundle.
