# From GitHub to the live site

How code gets from GitHub to http://nycfood-team3.us-east-1.elasticbeanstalk.com. For the AWS setup itself (SSM secrets, IAM, troubleshooting), see `aws_deployment.md`.

Deploys are **manual**: GitHub and Elastic Beanstalk are not connected. Someone pulls the code to their laptop and runs `eb deploy`; the site then runs whatever was in that person's project folder.

```
GitHub (develop)
   │  git pull
   ▼
your laptop: working directory  (+ local database/nyc_food.db, + uncommitted edits)
   │  eb deploy nycfood-env
   ▼
S3 bundle  ──►  EC2 instance  ──►  live site
```

## Deploy checklist

```bash
git checkout develop
git pull origin develop
.venv/bin/python -m pip install -r requirements.txt   # if requirements changed
.venv/bin/python manage.py migrate                    # if there are new migrations
.venv/bin/python manage.py test
git status                                            # must be clean
eb deploy nycfood-env
eb open
```

After deploying, click through search, the combined map, and login/signup. If something is wrong, check `eb status`, `eb events`, and `eb logs`.

## What actually gets deployed

Because `.ebignore` exists, `eb deploy` zips the **working directory as it is on disk**, minus what `.ebignore` excludes. It does not deploy a GitHub commit or branch.

| On your laptop | Goes live? |
|----------------|------------|
| Uncommitted edits | Yes |
| Commits not yet pushed to GitHub | Yes |
| `database/nyc_food.db` (gitignored, never on GitHub) | Yes, and it replaces the live database |
| `.env` | No (excluded); live keys come from SSM |
| `.venv/`, `database/datasets/`, notebooks, `md_guides/`, `deploy/` | No (excluded) |

So a clean `git status` on an up-to-date `develop` is what makes "the site matches GitHub" true.

**The live database is overwritten on every deploy.** User accounts created on the site and Google data cached there are replaced by the deployer's local `nyc_food.db`. This lasts until the database moves to RDS.

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

- **Deploy only from an up-to-date `develop`** with a clean `git status`.
- **One deployer at a time.** Announce deploys in the team chat. Two people deploying from different laptops overwrite each other's code and database.
- **Merge first, deploy second.** Feature branches go through a PR into `develop`; don't deploy unmerged branches to `nycfood-env`.
- **Run the tests before deploying.**
- **Changing an API key** doesn't need a deploy: update it in SSM Parameter Store, then run `eb restart`.

## Rolling back

Every deploy is kept as an application version in S3. To go back to an earlier one:

```bash
eb appversion          # lists versions; pick one and deploy it from the menu
```

Or: EB console → `nycfood` → Application versions → select a version → Deploy. Rolling back code also rolls back the bundled database to that version's copy.

## Optional: automatic deploys with GitHub Actions

A workflow could deploy on every push to `develop`:

1. Check out the code.
2. Install requirements and run `manage.py test`.
3. Run `eb deploy nycfood-env` using AWS credentials stored as GitHub repository secrets.

The site would then always match `develop`. The blocker today is `nyc_food.db`: GitHub doesn't have it, so the workflow would have to rebuild it with `import_datasets` on every run (slow, and it would wipe live accounts anyway). Moving the database to RDS solves both problems and makes automatic deploys straightforward.
