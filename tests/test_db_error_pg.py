"""DatabaseError keeps the native PostgreSQL text (Requirement 18.1, 18.2). Marker local_pg."""
import pytest

from tests.pghelpers import config, connect_as, insert, new_run_id

pytestmark = pytest.mark.local_pg


def test_unique_violation_error_text_and_attributes():
    psycopg = pytest.importorskip("psycopg")
    run = new_run_id()
    insert("agent_writer", config(run, "R4"))
    agent = connect_as("agent_writer")
    with pytest.raises(agent.DatabaseError) as caught:
        insert("agent_writer", config(run, "R4", signal_name="sig_other"))
    err = caught.value
    assert isinstance(err.__cause__, psycopg.Error)
    assert str(err) == str(err.__cause__)
    assert "DETAIL" in str(err)
    assert err.sqlstate == "23505"
    assert err.constraint == "config_one_per_request"
