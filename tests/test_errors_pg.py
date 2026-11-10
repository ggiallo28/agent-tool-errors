"""Rejection of an unknown source_field on the local database, classified and explained (marker local_pg)."""
import pytest

from opsmem import db
from opsmem.errors import classify, valid_values
from tests.pghelpers import INSTALLATION, config, connect_as, count, insert, new_run_id

pytestmark = pytest.mark.local_pg

# The 9 source fields of install-07, written by hand from the manual and sorted.
INSTALL_07_FIELDS = sorted([
    "mst_wr_lat", "mst_free_pct", "enc_q_wait", "enc_active", "api_p95", "api_5xx",
    "cls_create_fail", "jq_depth", "jq_oldest",
])


def test_unknown_source_field_is_classified_and_lists_the_valid_fields():
    run = new_run_id()
    row = config(run, "R4", source_field="no_such_field")
    with pytest.raises(db.DatabaseError) as caught:
        insert("agent_writer", row)
    assert classify(str(caught.value)) == "config_field_exists"
    assert count("run_id = :r", r=run) == 0

    agent = connect_as("agent_writer")
    values = valid_values(agent, "config_field_exists", row, INSTALLATION)
    assert len(values) == 9
    assert values == INSTALL_07_FIELDS
