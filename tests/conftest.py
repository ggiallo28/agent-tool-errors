"""Fixtures for the local_pg tests: the container must be reachable, and the schema is applied once."""
import os
import subprocess
import sys

import pytest

from opsmem import db
from tests.helpers import ROOT


@pytest.fixture(scope="session")
def applied():
    """Check the container as admin and run the applier once when the schema is not there yet."""
    if not os.environ.get("OPSMEM_LOCAL_PG"):
        pytest.skip("local_pg tests need OPSMEM_LOCAL_PG")
    admin = db.connect("admin")
    try:
        found = admin.run("SELECT to_regclass('public.installations')")[0][0]
    except Exception as e:  # noqa: BLE001
        pytest.exit(f"the container opsmem-pg is not reachable as admin ({e}); "
                    f'run: eval "$(scripts/local_db.sh up)"', returncode=2)
    if found is None:
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "apply_schema.py")],
                              capture_output=True, text=True, env=os.environ.copy())
        if proc.returncode != 0:
            pytest.exit(f"apply_schema.py failed:\n{proc.stdout}\n{proc.stderr}", returncode=2)
    return admin


@pytest.fixture(autouse=True)
def _schema_for_local_pg(request):
    if request.node.get_closest_marker("local_pg"):
        request.getfixturevalue("applied")
