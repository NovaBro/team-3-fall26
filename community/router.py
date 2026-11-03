class CommunityRouter:
    """Keep community models in the community database."""

    app_label = "community"
    db = "community"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.db
        return None

    def allow_relation(self, obj1, obj2, **hints):
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        if self.app_label in labels:
            return labels == {self.app_label}
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.app_label:
            return db == self.db
        if db == self.db:
            return False
        return None
