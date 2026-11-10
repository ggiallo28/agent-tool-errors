"""Apply sql/schema.sql to an empty database as the admin role, set the role passwords and load
the catalog from manuals/.

    uv run scripts/apply_schema.py

Local mode (OPSMEM_LOCAL_PG set) uses the local Docker database. Otherwise Aurora is used through
the Data API. The schema is written for an empty database: a second run is refused.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opsmem import db, manual  # noqa: E402

SCHEMA = ROOT / "sql" / "schema.sql"
SEPARATOR = "-- @@ --"
INSTALLATION_ID = "install-07"
INSTALLATION_NAME = "Course platform, installation 07"
PASSWORD_ROLES = ("agent_writer", "approver")
PASSWORD_FORMAT = re.compile(r"[A-Za-z0-9]+")
PROBE = "SELECT to_regclass('public.installations')"
AURORA_REQUIRED = ["CLUSTER_ARN", "ADMIN_SECRET_ARN", "AGENT_WRITER_SECRET_ARN", "APPROVER_SECRET_ARN",
                   "AWS_REGION"]


@dataclass(frozen=True)
class Statement:
    sql: str
    index: int       # 1-based, among the statements that are kept
    start_line: int  # 1-based line of the first non-blank line of the statement


class LoaderError(Exception):
    """The catalog cannot be loaded; the message names the offending item."""


def _only_comments(chunk: str) -> bool:
    return not re.sub(r"--[^\n]*", "", re.sub(r"/\*.*?\*/", "", chunk, flags=re.DOTALL)).strip()


def split_statements(text: str) -> list[Statement]:
    """Split on lines that hold only the separator. Chunks with only comments or blanks are dropped."""
    chunks: list[tuple[int, list[str]]] = [(1, [])]
    for number, line in enumerate(text.split("\n"), start=1):
        if line.strip() == SEPARATOR:
            chunks.append((number + 1, []))
        else:
            chunks[-1][1].append(line)
    out: list[Statement] = []
    for first_line, lines in chunks:
        chunk = "\n".join(lines)
        if _only_comments(chunk):
            continue
        lead = next(i for i, line in enumerate(lines) if line.strip())
        out.append(Statement(chunk.strip(), len(out) + 1, first_line + lead))
    return out


# --- catalog ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Catalog:
    services: list
    fields: list
    requests: list


def read_catalog(root: Path = ROOT) -> Catalog:
    """Read both files as text and parse everything before anything is written."""
    texts = {}
    for label, rel in (("OPENAPI", manual.OPENAPI), ("MANUAL", manual.MANUAL)):
        path = root / rel
        try:
            texts[label] = path.read_text(encoding="utf-8")
        except OSError as e:
            raise LoaderError(f"cannot read {rel}: {e.strerror or e}") from e
    try:
        return Catalog(manual.parse_services(texts["OPENAPI"]), manual.parse_fields(texts["OPENAPI"]),
                       manual.parse_requests(texts["MANUAL"]))
    except manual.ManualError as e:
        raise LoaderError(str(e)) from e


def insert_catalog(database, catalog: Catalog, out=None) -> None:
    """Plain INSERTs in dependency order, no upsert, then print the four counts."""
    out = out or sys.stdout
    database.run("INSERT INTO installations (installation_id, name) VALUES (:installation_id, :name)",
                 installation_id=INSTALLATION_ID, name=INSTALLATION_NAME)
    for s in catalog.services:
        database.run("INSERT INTO services (installation_id, service_id, name) "
                     "VALUES (:installation_id, :service_id, :name)",
                     installation_id=INSTALLATION_ID, service_id=s.service_id, name=s.name)
    for f in catalog.fields:
        database.run("INSERT INTO source_fields (installation_id, service_id, field_name, unit, "
                     "min_sample_s, max_sample_s) VALUES (:installation_id, :service_id, :field_name, "
                     ":unit, :min_sample_s, :max_sample_s)",
                     installation_id=INSTALLATION_ID, service_id=f.service_id, field_name=f.field_name,
                     unit=f.unit, min_sample_s=f.min_sample_s, max_sample_s=f.max_sample_s)
    for r in catalog.requests:
        database.run("INSERT INTO signal_requests (installation_id, request_id, service_id, signal_type, "
                     "sample_s, request_text) VALUES (:installation_id, :request_id, :service_id, "
                     ":signal_type, :sample_s, :request_text)",
                     installation_id=INSTALLATION_ID, request_id=r.request_id, service_id=r.service_id,
                     signal_type=r.signal_type, sample_s=r.sample_s, request_text=r.request_text)
    for label, count in (("installations", 1), ("services", len(catalog.services)),
                         ("fields", len(catalog.fields)), ("requests", len(catalog.requests))):
        print(f"{label}: {count}", file=out)


def schema_exists(database) -> bool:
    rows = database.run(PROBE)
    return bool(rows) and rows[0][0] is not None


def load_catalog(database, root: Path = ROOT, out=None, err=None) -> int:
    """Standalone Catalog_Loader: probe, read, parse, insert. Returns the exit status."""
    out, err = out or sys.stdout, err or sys.stderr
    try:
        if not schema_exists(database):
            print("Error: the schema has not been applied (installations table not found).", file=err)
            return 1
        catalog = read_catalog(root)
    except LoaderError as e:
        print(f"Error: {e}", file=err)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Error: cannot check the schema: {e}", file=err)
        return 1
    try:
        insert_catalog(database, catalog, out)
    except Exception as e:  # noqa: BLE001
        print(f"Error: catalog load failed: {e}", file=err)
        return 1
    return 0


# --- passwords -------------------------------------------------------------------------------

def aurora_password(role: str) -> str:
    """Read the `password` field of the role secret from Secrets Manager."""
    import boto3

    arn = os.environ[db.SECRET_VARS[role]]
    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION"))
    return str(json.loads(client.get_secret_value(SecretId=arn)["SecretString"])["password"])


def resolve_passwords(local: bool, read_password=aurora_password) -> dict[str, str]:
    """Local passwords equal the role names. Aurora passwords come from the role secrets and must
    match [A-Za-z0-9]+, because ALTER ROLE cannot bind a value."""
    passwords = {}
    for role in PASSWORD_ROLES:
        if local:
            passwords[role] = role
            continue
        password = read_password(role)
        if not PASSWORD_FORMAT.fullmatch(password or ""):
            raise LoaderError(f"the password in the secret {db.SECRET_VARS[role]} must match [A-Za-z0-9]+; "
                              f"regenerate that secret without punctuation")
        passwords[role] = password
    return passwords


# --- main ------------------------------------------------------------------------------------

def main(argv=None, *, connect=db.connect, schema_path: Path = SCHEMA, root: Path = ROOT,
         read_password=aurora_password, out=None, err=None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    local = bool(os.environ.get("OPSMEM_LOCAL_PG"))
    db.check_config(AURORA_REQUIRED)

    admin = connect("admin")
    try:
        exists = schema_exists(admin)
    except Exception as e:  # noqa: BLE001
        print(f"Error: cannot connect to the database as admin, nothing was run: {e}", file=err)
        return 1
    if exists:
        hint = "scripts/local_db.sh up" if local else "a new stack"
        print(f"Error: the database is not empty, the schema already exists. Nothing was applied. "
              f"To start again, recreate the database with {hint}.", file=err)
        return 1

    try:
        catalog = read_catalog(root)
        passwords = resolve_passwords(local, read_password)
    except LoaderError as e:
        print(f"Error: {e}. Nothing was applied.", file=err)
        return 1

    for st in split_statements(Path(schema_path).read_text(encoding="utf-8")):
        try:
            admin.run(st.sql)
        except Exception as e:  # noqa: BLE001
            print(f"Error: statement {st.index} (line {st.start_line} of {Path(schema_path).name}) failed.\n"
                  f"{st.sql}\n{e}", file=err)
            return 1

    for role, password in passwords.items():
        try:
            admin.run(f"ALTER ROLE {role} PASSWORD '{password}'")
        except Exception as e:  # noqa: BLE001
            print(f"Error: cannot set the password of {role}: {e}", file=err)
            return 1

    try:
        insert_catalog(admin, catalog, out)
    except Exception as e:  # noqa: BLE001
        print(f"Error: catalog load failed, recreate the database to start again: {e}", file=err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
