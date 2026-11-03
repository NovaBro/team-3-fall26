# From GitHub to the live site

How code gets from GitHub to http://nycfood-team3.us-east-1.elasticbeanstalk.com. For the AWS setup itself (SSM secrets, IAM, troubleshooting), see `aws_deployment.md`.

A push to `develop` on `gcivil-nyu-org/team-3-fall26` runs the test job, then the deploy job in `.github/workflows/ci.yml`. That job assumes the IAM role `github-nycfood-deploy` and runs `eb deploy nycfood-env`. Pull requests run tests only. The same workflow on a fork cannot assume the role.

```
GitHub (gcivil-nyu-org develop)
   │  push
   ▼
GitHub Actions: test, then eb deploy nycfood-env
   │
   ▼
S3 bundle  ──►  EC2 instance
                 │  download nyc_food.db and community.db
                 ▼
               live site
```

## Deploy checklist

Merge into `develop` on `gcivil-nyu-org/team-3-fall26`. The Actions deploy job runs after tests pass. After it finishes, click through search, the combined map, and login/signup. If something is wrong, check the Actions log, then `eb status`, `eb events`, and `eb logs`.

A laptop `eb deploy nycfood-env` still deploys the working directory, with the same `.ebignore` rules. The instance then replaces `database/*.db` with the S3 copies.

## What actually gets deployed

Because `.ebignore` exists, `eb deploy` zips the working directory, minus what `.ebignore` excludes. On GitHub Actions that directory is the `develop` commit. On a laptop it is whatever is on disk, including uncommitted edits.

| On your laptop | Goes live? |
|----------------|------------|
| Uncommitted edits, on a laptop `eb deploy` | Yes |
| Commits not yet pushed to GitHub, on a laptop `eb deploy` | Yes |
| `database/nyc_food.db` and `database/community.db` | No. `.ebignore` excludes `database/*.db`. The instance downloads both from `s3://nycfood-databases-322134621417` |
| `.env` | No (excluded); live keys come from SSM |
| `.venv/`, `database/datasets/`, notebooks, `md_guides/`, `deploy/` | No (excluded) |

Actions deploys the Git commit, so uncommitted laptop files are not in that bundle. The live SQLite files are whatever was last uploaded to the database bucket. Rows written on the instance, and files in `media/`, are replaced on the next deploy. Upload new canonical databases with:

```bash
aws s3 cp database/nyc_food.db s3://nycfood-databases-322134621417/nyc_food.db
aws s3 cp database/community.db s3://nycfood-databases-322134621417/community.db
```

## Branches and environments

`eb init` stores a branch-to-environment mapping in `.elasticbeanstalk/config.yml` (local, gitignored):

```yaml
branch-defaults:
  feature/combined-map-and-profile:
    environment: nycfood-env
```

A bare `eb deploy` only knows where to go on a mapped branch. Either always name the environment (`eb deploy nycfood-env`), or map your current branch once with `eb use nycfood-env`.

## First-time setup for a teammate

1. Clone the repo and create the virtualenv:
   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements-dev.txt
   ```
2. Build the database, which is not in git:
   ```bash
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py import_datasets
   ```
3. Install the EB CLI and configure AWS credentials that have the deploy permissions (see "IAM permissions" in `aws_deployment.md`):
   ```bash
   pip install awsebcli
   aws configure
   ```
4. Connect to the existing app and environment:
   ```bash
   eb init        # choose region us-east-1 and the existing "nycfood" application
   eb use nycfood-env
   ```

A `.env` file is only needed to run the site locally with Google features, not to deploy.

## Team rules

- **Deploy from `develop` on `gcivil-nyu-org/team-3-fall26`.** A push there runs tests, then deploys. Announce laptop `eb deploy`s in the team chat so they do not overlap an Actions run.
- **Merge first, deploy second.** Feature branches go through a PR into `develop`; don't deploy unmerged branches to `nycfood-env`.
- **Changing an API key** doesn't need a deploy: update it in SSM Parameter Store, then run `eb restart`.
- **Changing the canonical databases** is an `aws s3 cp`, then a deploy so the instance downloads the new objects.

## Rolling back

Every deploy is kept as an application version in S3. To go back to an earlier one:

```bash
eb appversion          # lists versions; pick one and deploy it from the menu
```

Or: EB console → `nycfood` → Application versions → select a version → Deploy. Rolling back code does not change the S3 database objects. The instance downloads those objects again during the rollback deploy.

## GitHub Actions

`.github/workflows/ci.yml` deploys only when all of these are true: the `test` job succeeded, the event is a push, the branch is `develop`, and the repository is `gcivil-nyu-org/team-3-fall26`. The job assumes `arn:aws:iam::322134621417:role/github-nycfood-deploy` through GitHub's OIDC provider and runs `eb deploy nycfood-env`. No AWS access keys are stored in the repository.
