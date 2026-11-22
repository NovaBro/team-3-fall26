"""Keep user accounts in their own database (database/users.db).

Accounts used to sit in the dataset database, so rebuilding or swapping that
file lost or forked them. Everything about a person (login, profile, mood log,
sessions, admin history) now lives in users.db; the dataset DB only holds
data that ``import_datasets`` can rebuild.
"""


class UsersRouter:
    db = "users"
    app_labels = {"auth", "contenttypes", "sessions", "admin", "accounts"}

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.app_labels:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        return self.db_for_read(model, **hints)

    def allow_relation(self, obj1, obj2, **hints):
        inside = [o._meta.app_label in self.app_labels for o in (obj1, obj2)]
        if any(inside):
            return all(inside)
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.app_labels:
            return db == self.db
        if db == self.db:
            return False
        return None
