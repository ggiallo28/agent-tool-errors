"""Connections per role, on Aurora (RDS Data API) or on local PostgreSQL in Docker.

`connect(role)` returns a Database object with `run(sql, **params) -> list[list]` and the
attribute `DatabaseError`. All SQL in the repository uses Data API style `:name` parameters;
the local backend translates them to psycopg style.

The Local_Backend is for local Docker only. It logs in with fixed development passwords and
must never be pointed at Aurora or any shared database.
"""
from __future__ import annotations

import os
import re
import sys
import time

ROLES = ("admin", "agent_writer", "approver")

DATABASE = "opsmemory"
RETRY_WAITS = (5, 10, 15, 20, 25, 30)
SECRET_VARS = {
    "admin": "ADMIN_SECRET_ARN",
    "agent_writer": "AGENT_WRITER_SECRET_ARN",
    "approver": "APPROVER_SECRET_ARN",
}
LOCAL_LOGINS = {
    "admin": ("postgres", "postgres"),
    "agent_writer": ("agent_writer", "agent_writer"),
    "approver": ("approver", "approver"),
}

_sleep = time.sleep  # a module attribute so tests can replace it


class DatabaseError(Exception):
    """A SQL error from the database.

    str(err) is str() of the native exception, character for character, DETAIL lines included.
    Built as `raise DatabaseError(str(native), ...) from native`, so err.__cause__ is the native
    exception. `sqlstate` and `constraint` are None when the backend does not report them.
    """

    def __init__(self, text, *, sqlstate=None, constraint=None):
        super().__init__(text)
        self.sqlstate = sqlstate
        self.constraint = constraint


class ConfigError(Exception):
    """A required setting is missing or malformed."""


class ConnectionFailed(Exception):
    """The local database cannot be reached or refused the login."""


class Database:
    """What connect(role) returns. Both backends share the same DatabaseError class."""

    DatabaseError = DatabaseError

    def __init__(self, role: str):
        self.role = role

    def run(self, sql: str, **params) -> list[list]:
        raise NotImplementedError


# --- parameter scanning ---------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z0-9_]")
_NAME_START = re.compile(r"[A-Za-z_]")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOLLAR = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _quoted_end(sql: str, start: int, quote: str) -> int:
    i, n = start + 1, len(sql)
    while i < n:
        if sql[i] == quote:
            if i + 1 < n and sql[i + 1] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return n


def scan_params(sql: str) -> list[tuple[str, str]]:
    """Split SQL into ("text", s) and ("param", name) tokens.

    Quoted strings, quoted identifiers, dollar-quoted bodies and comments are text. `::` is text.
    `:name` is a parameter when the previous character is not a colon or a word character.
    """
    tokens: list[tuple[str, str]] = []
    text: list[str] = []
    i, n = 0, len(sql)

    def flush():
        if text:
            tokens.append(("text", "".join(text)))
            text.clear()

    while i < n:
        c = sql[i]
        if c in "'\"":
            j = _quoted_end(sql, i, c)
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif c == "$" and (i == 0 or not _WORD.match(sql[i - 1])) and (m := _DOLLAR.match(sql, i)):
            end = sql.find(m.group(0), m.end())
            j = n if end < 0 else end + len(m.group(0))
        elif c == ":" and (i == 0 or (sql[i - 1] != ":" and not _WORD.match(sql[i - 1]))) \
                and i + 1 < n and _NAME_START.match(sql[i + 1]):
            name = _NAME.match(sql, i + 1).group(0)
            flush()
            tokens.append(("param", name))
            i += 1 + len(name)
            continue
        else:
            text.append(c)
            i += 1
            continue
        text.append(sql[i:j])
        i = j
    flush()
    return tokens


def param_names(sql: str) -> list[str]:
    """The distinct `:name` parameters of the SQL, in order of first appearance."""
    seen: list[str] = []
    for kind, value in scan_params(sql):
        if kind == "param" and value not in seen:
            seen.append(value)
    return seen


def to_psycopg(sql: str) -> str:
    """`:name` becomes `%(name)s` and every literal `%` becomes `%%`."""
    return "".join(f"%({v})s" if kind == "param" else v.replace("%", "%%") for kind, v in scan_params(sql))


def check_missing(sql: str, params: dict) -> None:
    for name in param_names(sql):
        if name not in params:
            raise ValueError(f"Missing parameter: {name}")


# --- Local_Backend ---------------------------------------------------------------------------

_LOCAL_PG = re.compile(r"([^:\s]+):([0-9]+)")


def parse_local_pg(value) -> tuple[str, int]:
    """Parse `host:port` from OPSMEM_LOCAL_PG, or raise ConfigError."""
    m = _LOCAL_PG.fullmatch(value) if isinstance(value, str) else None
    if m is None or not 1 <= int(m.group(2)) <= 65535:
        raise ConfigError(f"OPSMEM_LOCAL_PG is missing or malformed (expected host:port): {value!r}")
    return m.group(1), int(m.group(2))


def _psycopg():
    import psycopg  # lazy: Aurora users do not need the `local` dependency group

    return psycopg


class LocalBackend(Database):
    def __init__(self, role: str):
        super().__init__(role)
        self.host, self.port = parse_local_pg(os.environ.get("OPSMEM_LOCAL_PG"))
        self._conn = None

    def _connection(self):
        if self._conn is None:
            psycopg = _psycopg()
            user, password = LOCAL_LOGINS[self.role]
            try:
                self._conn = psycopg.connect(host=self.host, port=self.port, dbname=DATABASE, user=user,
                                             password=password, autocommit=True, connect_timeout=10)
            except psycopg.Error as e:
                raise ConnectionFailed(f"cannot connect to {self.host}:{self.port} as {self.role}: {e}") from e
        return self._conn

    def run(self, sql: str, **params) -> list[list]:
        check_missing(sql, params)
        conn = self._connection()
        psycopg = _psycopg()
        values = {name: params[name] for name in param_names(sql)}
        cur = conn.cursor()
        try:
            cur.execute(to_psycopg(sql), values)
            return [] if cur.description is None else [list(row) for row in cur.fetchall()]
        except psycopg.Error as e:
            diag = getattr(e, "diag", None)
            raise DatabaseError(str(e), sqlstate=getattr(diag, "sqlstate", None),
                                constraint=getattr(diag, "constraint_name", None)) from e
        finally:
            cur.close()


# --- Aurora_Backend --------------------------------------------------------------------------

def to_field(value) -> dict:
    """A Python value as a Data API field. bool is tested before int."""
    if value is None:
        return {"isNull": True}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"longValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    raise TypeError(f"Unsupported parameter type: {type(value).__name__}")


def from_field(field: dict):
    """A Data API result cell as a Python value, by the key present."""
    if field.get("isNull"):
        return None
    for key in ("booleanValue", "longValue", "doubleValue", "stringValue", "blobValue", "arrayValue"):
        if key in field:
            return field[key]
    raise ValueError(f"Unknown Data API field: {field!r}")


def _need(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing environment variable: {name}")
    return value


class AuroraBackend(Database):
    def __init__(self, role: str, client=None):
        super().__init__(role)
        self._client = client

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("rds-data", region_name=os.environ.get("AWS_REGION"))
        return self._client

    def run(self, sql: str, **params) -> list[list]:
        check_missing(sql, params)
        request = {"resourceArn": _need("CLUSTER_ARN"), "secretArn": _need(SECRET_VARS[self.role]),
                   "database": DATABASE, "sql": sql}
        names = param_names(sql)
        if names:
            request["parameters"] = [{"name": n, "value": to_field(params[n])} for n in names]
        response = self._execute(self._get_client(), request)
        return [[from_field(cell) for cell in row] for row in response.get("records") or []]

    @staticmethod
    def _execute(client, request: dict) -> dict:
        for attempt in range(len(RETRY_WAITS) + 1):
            try:
                return client.execute_statement(**request)
            except client.exceptions.DatabaseResumingException:
                if attempt == len(RETRY_WAITS):
                    raise
                _sleep(RETRY_WAITS[attempt])
            except client.exceptions.BadRequestException as e:
                raise DatabaseError(str(e), sqlstate=getattr(e, "sqlstate", None),
                                    constraint=getattr(e, "constraint", None)) from e
        raise AssertionError("unreachable")


# --- entry points ----------------------------------------------------------------------------

def connect(role) -> Database:
    if not (type(role) is str and role in ROLES):
        raise ValueError(f"Invalid role: {role!r}")
    if os.environ.get("OPSMEM_LOCAL_PG"):
        return LocalBackend(role)
    return AuroraBackend(role)


def check_config(required: list[str]) -> None:
    """Stop the process at startup when a required variable is absent or empty."""
    if os.environ.get("OPSMEM_LOCAL_PG"):
        required = ["OPSMEM_LOCAL_PG", "AWS_REGION"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        sys.stderr.write("Configuration error, agent not started. Missing: " + ", ".join(missing) + "\n")
        raise SystemExit(1)
