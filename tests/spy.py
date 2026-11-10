"""A spy Database_Object for the applier tests."""
from opsmem import db


class SpyDatabase:
    DatabaseError = db.DatabaseError

    def __init__(self, probe=None, fail_on=None, probe_error=None):
        self.probe, self.fail_on, self.probe_error = probe, fail_on, probe_error
        self.calls = []

    def run(self, sql, **params):
        self.calls.append((sql, params))
        if sql.startswith("SELECT to_regclass"):
            if self.probe_error:
                raise self.probe_error
            return [[self.probe]]
        if self.fail_on is not None and sql == self.fail_on:
            raise db.DatabaseError(f"syntax error near {sql!r}")
        return []

    @property
    def sqls(self):
        return [sql for sql, _ in self.calls]
