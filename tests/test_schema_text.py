"""Offline checks of the text of sql/schema.sql (Requirements 6 to 14)."""
import re
from pathlib import Path

import pytest

TEXT = (Path(__file__).resolve().parents[1] / "sql" / "schema.sql").read_text()
SEPARATOR = "-- @@ --"

FOREIGN_KEYS = ["config_field_exists", "config_unit_matches_source", "config_answers_request",
                "config_service_matches_request", "config_field_in_service", "config_type_matches_request",
                "config_sampling_requested", "config_unit_allowed_for_type"]
UNIQUES = ["config_one_per_request", "config_one_per_signal", "config_one_per_field"]
CONFIG_COLUMNS = ["config_id", "run_id", "installation_id", "request_id", "service_id", "signal_name",
                  "signal_type", "source_field", "unit", "sample_s", "model_id", "status", "created_by",
                  "approved_by", "is_bait"]


def chunks():
    return TEXT.split("\n" + SEPARATOR + "\n")


def table_sql(name):
    return next(c for c in chunks() if re.search(rf"CREATE TABLE {name} \(", c))


def test_separator_only_as_whole_line():
    for line in TEXT.split("\n"):
        assert SEPARATOR not in line or line.strip() == SEPARATOR


def test_no_statement_is_empty():
    for c in chunks():
        body = re.sub(r"--[^\n]*", "", c).strip()
        assert body, "empty statement"


def test_no_password_and_no_double_colon():
    assert "password" not in TEXT.lower()
    assert "::" not in TEXT


def test_no_colon_followed_by_a_letter():
    assert not re.search(r":[A-Za-z_]", TEXT)


def test_foreign_keys_in_declared_order():
    sql = table_sql("collection_configs")
    positions = [sql.index(f"CONSTRAINT {n} FOREIGN KEY") for n in FOREIGN_KEYS]
    assert positions == sorted(positions)


def test_uniques_in_declared_order():
    sql = table_sql("collection_configs")
    positions = [re.search(rf"CONSTRAINT {n}\s+UNIQUE", sql).start() for n in UNIQUES]
    assert positions == sorted(positions)


def test_config_columns_match_requirement():
    sql = table_sql("collection_configs")
    body = sql[sql.index("(") + 1:sql.index("CONSTRAINT")]
    columns = [line.split()[0] for line in body.strip().split("\n") if line.strip()]
    assert columns == CONFIG_COLUMNS


def test_exactly_five_allowed_units_inserts():
    inserts = re.findall(r"INSERT INTO allowed_units \(signal_type, unit\) VALUES \('(\w+)', '(\w+)'\)", TEXT)
    assert inserts == [("latency", "ms"), ("latency", "s"), ("ratio", "percent"), ("count", "count"), ("age", "s")]
    assert TEXT.count("INSERT INTO") == 5


def test_roles_have_login_and_no_password_clause():
    assert re.search(r"CREATE ROLE agent_writer LOGIN\n", TEXT)
    assert re.search(r"CREATE ROLE approver LOGIN\n", TEXT)


# --- triggers (Requirements 10 to 12) ---

@pytest.mark.parametrize("fragment", [
    "'config_sampling_supported: sample_s % outside % to % for %'",
    "NEW.sample_s, lo, hi, NEW.source_field",
    "USING ERRCODE = '23514', CONSTRAINT = 'config_sampling_supported'",
    "'config_agent_cannot_approve: agent cannot move a configuration from % to %'",
    "USING ERRCODE = '42501', CONSTRAINT = 'config_agent_cannot_approve'",
    "'config_promote_only_approved: only approved configurations become active'",
    "USING ERRCODE = '23514', CONSTRAINT = 'config_promote_only_approved'",
    "'config_bait_never_active: bait configurations never become active'",
    "USING ERRCODE = '23514', CONSTRAINT = 'config_bait_never_active'",
    "'signal_needs_active_config: no active configuration for %'",
    "USING ERRCODE = '23503', CONSTRAINT = 'signal_needs_active_config'",
    "BEFORE INSERT OR UPDATE OF source_field, sample_s ON collection_configs",
    "BEFORE UPDATE ON collection_configs",
    "BEFORE INSERT ON signals",
])
def test_trigger_text_is_exact(fragment):
    assert fragment in TEXT


def test_check_sampling_is_security_definer_with_fixed_search_path():
    sql = next(c for c in chunks() if "CREATE FUNCTION check_sampling" in c)
    assert "SECURITY DEFINER" in sql and "SET search_path = public" in sql
    assert "SECURITY DEFINER" not in next(c for c in chunks() if "CREATE FUNCTION check_transition" in c)


def test_grants_list_exact_columns():
    assert "GRANT INSERT (run_id, installation_id, request_id, service_id, signal_name, signal_type, " \
           "source_field, unit, sample_s, model_id)\n    ON collection_configs TO agent_writer" in TEXT
    assert "GRANT UPDATE (status) ON collection_configs TO agent_writer" in TEXT
    assert "GRANT UPDATE (status, approved_by) ON collection_configs TO approver" in TEXT
    assert "GRANT USAGE ON SEQUENCE collection_configs_config_id_seq TO agent_writer" in TEXT
    assert "GRANT INSERT, SELECT ON review_log TO approver" in TEXT


def test_approver_has_no_grant_on_the_six_tables():
    for stmt in (c for c in chunks() if "GRANT" in c and "TO approver" in c):
        for table in ("installations", "services", "source_fields", "signal_requests", "allowed_units", "signals"):
            assert not re.search(rf"\bON\s+(?:[\w, ]*,\s*)?{table}\b", stmt)
