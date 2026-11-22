"""Copy accounts from the dataset DB (nyc_food.db) into database/users.db.

Accounts, profiles, mood logs and sessions used to live in the dataset
database. They now live in users.db (see nycfood/routers.py). Run once per
machine after upgrading:

    python manage.py migrate --database=users
    python manage.py move_accounts_db [--source database/nyc_food.db] [--force]

User ids are kept, so community rows (ratings, comments, photos, likes), which
store a plain ``user_id``, still point at the same people. Permission and
content-type ids can differ between the two files, so links to them are
re-matched by (app_label, model, codename). The source file is only read.
"""

import os
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Copied as-is, in this order (parents before children).
PLAIN_TABLES = [
    "auth_group",
    "auth_user",
    "auth_user_groups",
    "accounts_userprofile",
    "accounts_moodlog",
    "django_session",
]

# Tables whose rows point at django_content_type / auth_permission ids.
PERMISSION_LINKS = {
    "auth_user_user_permissions": ("user_id",),
    "auth_group_permissions": ("group_id",),
}

TARGET_ORDER = [
    "django_admin_log",
    "auth_group_permissions",
    "auth_user_user_permissions",
    "django_session",
    "accounts_moodlog",
    "accounts_userprofile",
    "auth_user_groups",
    "auth_user",
    "auth_group",
]


def _columns(conn, schema, table):
    return [row[1] for row in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _has_table(conn, schema, table):
    return bool(
        conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


class Command(BaseCommand):
    help = "Copy users, profiles, mood logs and sessions into users.db."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=str(settings.DATABASES["default"]["NAME"]),
            help="Database file that currently holds the accounts.",
        )
        parser.add_argument("--dest", default=str(settings.DATABASES["users"]["NAME"]))
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace accounts already in the destination.",
        )

    def handle(self, *args, source, dest, force, **options):
        if os.path.abspath(source) == os.path.abspath(dest):
            raise CommandError("--source and --dest must differ.")
        if not os.path.exists(source):
            raise CommandError(f"Source database not found: {source}")
        if not os.path.exists(dest):
            raise CommandError(
                f"{dest} not found. Run: python manage.py migrate --database=users"
            )

        conn = sqlite3.connect(dest)
        conn.execute("ATTACH DATABASE ? AS src", (f"file:{source}?mode=ro",))
        if not _has_table(conn, "main", "auth_user"):
            raise CommandError(
                f"{dest} has no tables. Run: python manage.py migrate --database=users"
            )
        if not _has_table(conn, "src", "auth_user"):
            raise CommandError(f"{source} has no auth_user table; nothing to move.")
        if conn.execute("SELECT COUNT(*) FROM main.auth_user").fetchone()[0]:
            if not force:
                raise CommandError(
                    f"{dest} already has accounts. Pass --force to replace them."
                )

        counts = {}
        with conn:
            for table in TARGET_ORDER:
                conn.execute(f'DELETE FROM main."{table}"')
            for table in PLAIN_TABLES:
                if _has_table(conn, "src", table):
                    counts[table] = self._copy(conn, table)
            for table, keys in PERMISSION_LINKS.items():
                if _has_table(conn, "src", table):
                    counts[table] = self._copy_permission_links(conn, table, keys)
            if _has_table(conn, "src", "django_admin_log"):
                counts["django_admin_log"] = self._copy_admin_log(conn)
        conn.close()

        summary = ", ".join(f"{n} {table}" for table, n in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Copied into {dest}: {summary}."))

    def _copy(self, conn, table):
        src_cols = set(_columns(conn, "src", table))
        cols = [c for c in _columns(conn, "main", table) if c in src_cols]
        names = ", ".join(f'"{c}"' for c in cols)
        cur = conn.execute(
            f'INSERT INTO main."{table}" ({names}) SELECT {names} FROM src."{table}"'
        )
        return cur.rowcount

    def _copy_permission_links(self, conn, table, keys):
        (owner,) = keys
        cur = conn.execute(f"""
            INSERT INTO main."{table}" ("{owner}", permission_id)
            SELECT link."{owner}", new_perm.id
            FROM src."{table}" AS link
            JOIN src.auth_permission AS old_perm ON old_perm.id = link.permission_id
            JOIN src.django_content_type AS old_ct
              ON old_ct.id = old_perm.content_type_id
            JOIN main.django_content_type AS new_ct
              ON new_ct.app_label = old_ct.app_label AND new_ct.model = old_ct.model
            JOIN main.auth_permission AS new_perm
              ON new_perm.content_type_id = new_ct.id
             AND new_perm.codename = old_perm.codename
            """)
        return cur.rowcount

    def _copy_admin_log(self, conn):
        cols = [c for c in _columns(conn, "main", "django_admin_log")]
        src_cols = set(_columns(conn, "src", "django_admin_log"))
        cols = [c for c in cols if c in src_cols and c != "content_type_id"]
        names = ", ".join(f'"{c}"' for c in cols)
        picked = ", ".join(f'log."{c}"' for c in cols)
        cur = conn.execute(f"""
            INSERT INTO main.django_admin_log ({names}, content_type_id)
            SELECT {picked}, new_ct.id
            FROM src.django_admin_log AS log
            LEFT JOIN src.django_content_type AS old_ct
              ON old_ct.id = log.content_type_id
            LEFT JOIN main.django_content_type AS new_ct
              ON new_ct.app_label = old_ct.app_label AND new_ct.model = old_ct.model
            """)
        return cur.rowcount
