"""Accounts live in their own database (users.db)."""

import sqlite3
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections, router
from django.test import SimpleTestCase, TestCase

from accounts.models import MoodLog, UserProfile
from community.models import UserRating
from nycfood.test_utils import ALL_DATABASES
from search.models import FarmersMarket, MenuItem


class UsersRouterTests(SimpleTestCase):
    def test_account_models_use_users_db(self):
        for model in (User, UserProfile, MoodLog, Session):
            self.assertEqual(router.db_for_read(model), "users", model)
            self.assertEqual(router.db_for_write(model), "users", model)

    def test_other_models_keep_their_db(self):
        self.assertEqual(router.db_for_read(MenuItem), "default")
        self.assertEqual(router.db_for_read(FarmersMarket), "default")
        self.assertEqual(router.db_for_read(UserRating), "community")

    def test_migrations_stay_in_their_db(self):
        self.assertTrue(router.allow_migrate("users", "auth"))
        self.assertFalse(router.allow_migrate("default", "auth"))
        self.assertFalse(router.allow_migrate("default", "accounts"))
        self.assertFalse(router.allow_migrate("users", "search"))
        self.assertFalse(router.allow_migrate("users", "community"))
        self.assertTrue(router.allow_migrate("default", "search"))


class MoveAccountsDbTests(TestCase):
    databases = ALL_DATABASES

    def _source(self, folder):
        path = Path(folder) / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE auth_user (
                id INTEGER PRIMARY KEY, password TEXT, last_login TEXT,
                is_superuser BOOL, username TEXT, last_name TEXT, email TEXT,
                is_staff BOOL, is_active BOOL, date_joined TEXT, first_name TEXT);
            INSERT INTO auth_user VALUES
                (7, 'x', NULL, 0, 'kept', '', 'k@example.com', 0, 1,
                 '2026-01-01 00:00:00', 'Kim');
            """)
        conn.commit()
        conn.close()
        return path

    def test_copies_users_keeping_ids(self):
        dest = Path(self.databases_dir) / "users.db"
        with tempfile.TemporaryDirectory() as folder:
            source = self._source(folder)
            call_command(
                "move_accounts_db",
                source=str(source),
                dest=str(dest),
                stdout=StringIO(),
            )
        conn = sqlite3.connect(dest)
        rows = conn.execute("SELECT id, username FROM auth_user").fetchall()
        conn.close()
        self.assertEqual(rows, [(7, "kept")])

    def test_refuses_to_overwrite_without_force(self):
        dest = Path(self.databases_dir) / "users.db"
        with tempfile.TemporaryDirectory() as folder:
            source = self._source(folder)
            call_command(
                "move_accounts_db",
                source=str(source),
                dest=str(dest),
                stdout=StringIO(),
            )
            with self.assertRaises(CommandError):
                call_command(
                    "move_accounts_db",
                    source=str(source),
                    dest=str(dest),
                    stdout=StringIO(),
                )

    def setUp(self):
        # A throwaway users.db with the real schema: copy the test database's
        # auth tables into a file the command can open.
        self._dir = tempfile.TemporaryDirectory()
        self.databases_dir = self._dir.name
        dest = sqlite3.connect(Path(self.databases_dir) / "users.db")
        for table in (
            "auth_group",
            "auth_user",
            "auth_user_groups",
            "auth_permission",
            "auth_user_user_permissions",
            "auth_group_permissions",
            "django_content_type",
            "django_admin_log",
            "django_session",
            "accounts_userprofile",
            "accounts_moodlog",
        ):
            with connections["users"].cursor() as cursor:
                cursor.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=%s",
                    [table],
                )
                (sql,) = cursor.fetchone()
            dest.execute(sql)
        dest.commit()
        dest.close()

    def tearDown(self):
        self._dir.cleanup()
