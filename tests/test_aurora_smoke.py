"""Smoke test on a deployed Aurora cluster. Skipped unless CLUSTER_ARN is set.

It applies nothing. It checks the connection as admin and sends one insert that the database must
reject, to record what the Data API error text contains (the SQLSTATE and the constraint name are
only in the text, not in structured fields).
"""
import pytest

from opsmem import db

pytestmark = pytest.mark.aurora


def test_connection_and_one_rejected_insert():
    admin = db.connect("admin")
    assert admin.run("SELECT 1") == [[1]]
    with pytest.raises(admin.DatabaseError) as caught:
        admin.run("INSERT INTO services (installation_id, service_id, name) VALUES (:i, 'x', 'x')",
                  i="no-such-installation")
    print("Data API error text:", str(caught.value))
    assert "services_installation_id_fkey" in str(caught.value)
    assert caught.value.__cause__ is not None
