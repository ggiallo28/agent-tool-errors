"""Test doubles for the writer agent: a database that records statements and an agent that needs no model."""
import threading
import time
from types import SimpleNamespace

from opsmem import db

CATALOG_ROWS = [("alpha",), ("beta",)]


def rejection_message(rule: str) -> str:
    """A native-looking database message that names the rule."""
    if rule == "integer_input":
        return 'invalid input syntax for type integer: "every minute"'
    if rule == "signal_name_check":
        return ('new row for relation "collection_configs" violates check constraint '
                '"collection_configs_signal_name_check"')
    return f'insert or update on table "collection_configs" violates foreign key constraint "{rule}"'


class FakeDatabase:
    """Records (sql, params) in order. Inserts are accepted or rejected by `reject(params)`:
    it returns None to accept, or the message to raise as a DatabaseError."""

    DatabaseError = db.DatabaseError

    def __init__(self, reject=None, open_ids=(), delay=0.0, catalog=None):
        self.statements: list[tuple[str, dict]] = []
        self._lock = threading.Lock()
        self.reject = reject or (lambda params: None)
        self.open_ids = open_ids if callable(open_ids) else list(open_ids)
        self.delay = delay
        self.catalog = CATALOG_ROWS if catalog is None else catalog

    def run(self, sql, **params):
        with self._lock:
            self.statements.append((sql, dict(params)))
        head = sql.lstrip().split(None, 1)[0].upper()
        if head == "INSERT":
            if self.delay:
                time.sleep(self.delay)
            message = self.reject(params)
            if message is not None:
                raise db.DatabaseError(message)
            return []
        if head == "UPDATE":
            return []
        if "NOT IN (SELECT request_id FROM collection_configs" in sql:
            ids = self.open_ids() if callable(self.open_ids) else self.open_ids
            return [(i,) for i in ids]
        if "min_sample_s" in sql:
            return [(1, 60)]
        return list(self.catalog)

    def of_kind(self, kind):
        return [(s, p) for s, p in self.statements if s.lstrip().upper().startswith(kind)]


class FakeResult:
    def __init__(self, text="done", usage=None, with_metrics=True):
        self.text = text
        if with_metrics:
            self.metrics = SimpleNamespace(accumulated_usage=usage)

    def __str__(self):
        return self.text


class FakeAgent:
    """Callable stand-in for the Strands agent. `behavior(message, index)` may call the real tools."""

    def __init__(self, behavior=None, result=None):
        self.messages: list[str] = []
        self.behavior = behavior or (lambda message, index: None)
        self.result = result or FakeResult()

    def __call__(self, message):
        index = len(self.messages)
        self.messages.append(message)
        self.behavior(message, index)
        return self.result


def args(request_id="R1", **over):
    """Seven propose_config arguments."""
    base = dict(request_id=request_id, service_id="svc", signal_name="sig_one", signal_type="latency",
                source_field="field_a", unit="ms", sample_seconds="10")
    base.update(over)
    return base
