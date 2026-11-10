"""The shape of the applied schema, compared with the expected lists (marker local_pg)."""
import pytest

from tests.pghelpers import connect_as

pytestmark = pytest.mark.local_pg

T, I, N = "text", "integer", "NO"
EXPECTED_COLUMNS = {
    "installations": [("installation_id", T, N), ("name", T, N)],
    "services": [("installation_id", T, N), ("service_id", T, N), ("name", T, N)],
    "source_fields": [("installation_id", T, N), ("service_id", T, N), ("field_name", T, N), ("unit", T, N),
                      ("min_sample_s", I, N), ("max_sample_s", I, N)],
    "signal_requests": [("installation_id", T, N), ("request_id", T, N), ("service_id", T, N),
                        ("signal_type", T, N), ("sample_s", I, N), ("request_text", T, N)],
    "allowed_units": [("signal_type", T, N), ("unit", T, N)],
    "collection_configs": [("config_id", I, N), ("run_id", T, N), ("installation_id", T, N), ("request_id", T, N),
                           ("service_id", T, N), ("signal_name", T, N), ("signal_type", T, N),
                           ("source_field", T, N), ("unit", T, N), ("sample_s", I, N), ("model_id", T, N),
                           ("status", T, N), ("created_by", T, N), ("approved_by", T, "YES"),
                           ("is_bait", "boolean", N)],
    "review_log": [("config_id", I, N), ("reviewer", T, N), ("verdict", T, N), ("bait_expected", T, "YES"),
                   ("reviewed_at", "timestamp with time zone", N)],
    "signals": [("installation_id", T, N), ("signal_name", T, N), ("ts", "timestamp with time zone", N),
                ("value", "double precision", N)],
}
FOREIGN_KEYS = ["config_field_exists", "config_unit_matches_source", "config_answers_request",
                "config_service_matches_request", "config_field_in_service", "config_type_matches_request",
                "config_sampling_requested", "config_unit_allowed_for_type"]
UNIQUES = ["config_one_per_request", "config_one_per_signal", "config_one_per_field"]


@pytest.mark.parametrize("table", EXPECTED_COLUMNS)
def test_columns_types_and_nullability(table):
    rows = connect_as("admin").run(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position", t=table)
    assert [tuple(r) for r in rows] == EXPECTED_COLUMNS[table]


def names(kind):
    return [r[0] for r in connect_as("admin").run(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'collection_configs'::regclass AND contype = :k "
        "ORDER BY oid", k=kind)]


def test_foreign_keys_in_creation_order():
    assert names("f") == FOREIGN_KEYS


def test_unique_constraints_in_creation_order():
    assert names("u") == UNIQUES


def test_foreign_key_triggers_fire_in_declared_order():
    rows = connect_as("admin").run(
        "SELECT c.conname FROM pg_trigger t JOIN pg_constraint c ON c.oid = t.tgconstraint "
        "WHERE t.tgrelid = 'collection_configs'::regclass AND t.tgisinternal "
        "AND t.tgfoid = '\"RI_FKey_check_ins\"'::regproc ORDER BY t.tgname")
    assert [r[0] for r in rows] == FOREIGN_KEYS


def test_check_constraints_exist_by_name():
    assert sorted(names("c")) == ["collection_configs_signal_name_check", "collection_configs_status_check",
                                  "config_approval_signed"]


def test_catalog_keys():
    admin = connect_as("admin")
    pk = {r[0]: r[1] for r in admin.run(
        "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE contype = 'p' AND connamespace = 'public'::regnamespace")}
    assert pk["source_fields"] == "PRIMARY KEY (installation_id, field_name)"
    assert pk["services"] == "PRIMARY KEY (installation_id, service_id)"
    assert pk["signal_requests"] == "PRIMARY KEY (installation_id, request_id)"
    assert pk["signals"] == "PRIMARY KEY (installation_id, signal_name, ts)"
    assert pk["allowed_units"] == "PRIMARY KEY (signal_type, unit)"
    uniques = sorted(r[0] for r in admin.run(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE contype = 'u' "
        "AND conrelid IN ('source_fields'::regclass, 'signal_requests'::regclass)"))
    assert uniques == sorted([
        "UNIQUE (installation_id, field_name, unit)", "UNIQUE (installation_id, service_id, field_name)",
        "UNIQUE (installation_id, request_id, service_id)", "UNIQUE (installation_id, request_id, signal_type)",
        "UNIQUE (installation_id, request_id, sample_s)"])


def test_source_fields_foreign_keys():
    rows = connect_as("admin").run(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE contype = 'f' AND conrelid = 'source_fields'::regclass ORDER BY conname")
    assert [tuple(r) for r in rows] == [
        ("source_fields_installation_id_fkey",
         "FOREIGN KEY (installation_id) REFERENCES installations(installation_id)"),
        ("source_fields_installation_id_service_id_fkey",
         "FOREIGN KEY (installation_id, service_id) REFERENCES services(installation_id, service_id)"),
    ]


def test_trigger_definitions():
    rows = connect_as("admin").run("SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal ORDER BY tgname")
    assert [r[0] for r in rows] == [
        "CREATE TRIGGER config_sampling BEFORE INSERT OR UPDATE OF source_field, sample_s ON public.collection_configs "
        "FOR EACH ROW EXECUTE FUNCTION check_sampling()",
        "CREATE TRIGGER config_transition BEFORE UPDATE ON public.collection_configs "
        "FOR EACH ROW EXECUTE FUNCTION check_transition()",
        "CREATE TRIGGER signal_active BEFORE INSERT ON public.signals "
        "FOR EACH ROW EXECUTE FUNCTION check_signal_active()",
    ]
