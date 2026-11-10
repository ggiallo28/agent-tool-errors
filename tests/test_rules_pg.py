"""One example test per database rule, on the local database (marker local_pg).

Expected results are written by hand from the requirements, never derived from the SQL and never
generated. Each failing statement is followed by a count that shows the table is unchanged.
"""
import uuid

import pytest

from tests.pghelpers import INSTALLATION, assert_rejected, config, connect_as, count, insert, new_run_id

pytestmark = pytest.mark.local_pg

CATALOG_TABLES = ["installations", "services", "source_fields", "signal_requests", "allowed_units"]


def admin():
    return connect_as("admin")


def table_counts(tables):
    return [admin().run(f"SELECT count(*) FROM {t}")[0][0] for t in tables]


def signal_name():
    return "sig_" + uuid.uuid4().hex[:12]


def status_of(config_id):
    return admin().run("SELECT status FROM collection_configs WHERE config_id = :i", i=config_id)[0][0]


# --- 12.1 catalog, defaults and status ---------------------------------------------------------

def test_catalog_constraints():
    before = table_counts(CATALOG_TABLES)
    a = admin()
    cases = [
        ("installations primary key", "INSERT INTO installations (installation_id, name) VALUES (:i, 'x')",
         dict(i=INSTALLATION), "23505", "installations_pkey"),
        ("services primary key", "INSERT INTO services (installation_id, service_id, name) VALUES (:i, 'api', 'x')",
         dict(i=INSTALLATION), "23505", "services_pkey"),
        ("source_fields primary key",
         "INSERT INTO source_fields VALUES (:i, 'api', 'api_p95', 's', 10, 300)", dict(i=INSTALLATION), "23505",
         "source_fields_pkey"),
        ("signal_requests primary key",
         "INSERT INTO signal_requests VALUES (:i, 'R1', 'media', 'latency', 10, 'x')", dict(i=INSTALLATION),
         "23505", "signal_requests_pkey"),
        ("allowed_units primary key", "INSERT INTO allowed_units VALUES ('latency', 'ms')", {}, "23505",
         "allowed_units_pkey"),
        ("services foreign key", "INSERT INTO services VALUES ('no-such-installation', 'api', 'x')", {}, "23503",
         "services_installation_id_fkey"),
        ("source_fields foreign key", "INSERT INTO source_fields VALUES (:i, 'no-such-service', 'zz', 's', 1, 2)",
         dict(i=INSTALLATION), "23503", "source_fields_installation_id_service_id_fkey"),
        ("signal_requests foreign key",
         "INSERT INTO signal_requests VALUES (:i, 'R99', 'no-such-service', 'latency', 10, 'x')",
         dict(i=INSTALLATION), "23503", "signal_requests_installation_id_service_id_fkey"),
        ("installations name not null", "INSERT INTO installations VALUES ('zz', NULL)", {}, "23502", None),
        ("services name not null", "INSERT INTO services VALUES (:i, 'zz', NULL)", dict(i=INSTALLATION), "23502", None),
        ("source_fields service_id not null", "INSERT INTO source_fields VALUES (:i, NULL, 'zz', 's', 1, 2)",
         dict(i=INSTALLATION), "23502", None),
        ("source_fields unit not null", "INSERT INTO source_fields VALUES (:i, 'api', 'zz', NULL, 1, 2)",
         dict(i=INSTALLATION), "23502", None),
        ("source_fields min_sample_s not null", "INSERT INTO source_fields VALUES (:i, 'api', 'zz', 's', NULL, 2)",
         dict(i=INSTALLATION), "23502", None),
        ("source_fields max_sample_s not null", "INSERT INTO source_fields VALUES (:i, 'api', 'zz', 's', 1, NULL)",
         dict(i=INSTALLATION), "23502", None),
        ("signal_requests service_id not null", "INSERT INTO signal_requests VALUES (:i, 'R98', NULL, 'count', 1, 'x')",
         dict(i=INSTALLATION), "23502", None),
        ("signal_requests signal_type not null", "INSERT INTO signal_requests VALUES (:i, 'R98', 'api', NULL, 1, 'x')",
         dict(i=INSTALLATION), "23502", None),
        ("signal_requests sample_s not null", "INSERT INTO signal_requests VALUES (:i, 'R98', 'api', 'count', NULL, 'x')",
         dict(i=INSTALLATION), "23502", None),
        ("signal_requests request_text not null", "INSERT INTO signal_requests VALUES (:i, 'R98', 'api', 'count', 1, NULL)",
         dict(i=INSTALLATION), "23502", None),
    ]
    for rule, sql, params, sqlstate, constraint in cases:
        assert_rejected(lambda: a.run(sql, **params), rule=rule, sqlstate=sqlstate, constraint=constraint)
    assert table_counts(CATALOG_TABLES) == before


def test_allowed_units_content():
    rows = admin().run("SELECT signal_type, unit FROM allowed_units")
    assert sorted(tuple(r) for r in rows) == sorted([("latency", "ms"), ("latency", "s"), ("ratio", "percent"),
                                                     ("count", "count"), ("age", "s")])
    assert len(rows) == 5
    assert ("latency", "percent") not in {tuple(r) for r in rows}


def test_config_defaults():
    run = new_run_id()
    config_id = insert("agent_writer", config(run, "R4"))
    row = admin().run("SELECT status, created_by, approved_by, is_bait FROM collection_configs "
                      "WHERE config_id = :i", i=config_id)[0]
    assert row == ["draft", "agent_writer", None, False]
    for column in ["run_id", "installation_id", "request_id", "service_id", "signal_name", "signal_type",
                   "source_field", "unit", "sample_s", "model_id"]:
        before = count("run_id = :r", r=run)
        assert_rejected(lambda: insert("agent_writer", config(new_run_id(), "R3", **{column: None})),
                        rule=f"NOT NULL {column}", sqlstate="23502")
        assert count("run_id = :r", r=run) == before
    for column in ["status", "created_by", "is_bait"]:
        assert_rejected(lambda: insert("admin", config(new_run_id(), "R2", **{column: None})),
                        rule=f"NOT NULL {column}", sqlstate="23502")


@pytest.mark.parametrize("status", ["draft", "needs_review", "approved", "rejected", "active"])
def test_status_values_accepted_on_insert(status):
    run = new_run_id()
    extra = {"approved_by": "someone"} if status in ("approved", "active") else {}
    config_id = insert("admin", config(run, "R4", status=status, **extra))
    assert status_of(config_id) == status


@pytest.mark.parametrize("bad", ["", "Draft", "archived", "draft "])
def test_status_values_rejected(bad):
    run = new_run_id()
    assert_rejected(lambda: insert("admin", config(run, "R4", status=bad)), rule="status check on INSERT",
                    constraint="collection_configs_status_check")
    assert count("run_id = :r", r=run) == 0
    config_id = insert("admin", config(run, "R3"))
    assert_rejected(lambda: admin().run("UPDATE collection_configs SET status = :s WHERE config_id = :i",
                                        s=bad, i=config_id),
                    rule="status check on UPDATE", constraint="collection_configs_status_check")
    assert status_of(config_id) == "draft"


@pytest.mark.parametrize("new", ["needs_review", "rejected"])
def test_status_update_to_valid_values(new):
    config_id = insert("admin", config(new_run_id(), "R4"))
    admin().run("UPDATE collection_configs SET status = :s WHERE config_id = :i", s=new, i=config_id)
    assert status_of(config_id) == new


# --- 12.2 review log and signals ---------------------------------------------------------------

def test_review_log():
    approver = connect_as("approver")
    config_id = insert("admin", config(new_run_id(), "R4"))
    insert_sql = "INSERT INTO review_log (config_id, verdict, bait_expected) VALUES (:i, :v, :b)"

    def log_count():
        return admin().run("SELECT count(*) FROM review_log WHERE config_id = :i", i=config_id)[0][0]

    assert_rejected(lambda: approver.run(insert_sql, i=-1, v="approved", b=None), rule="review_log foreign key",
                    sqlstate="23503", constraint="review_log_config_id_fkey")
    assert_rejected(lambda: approver.run(insert_sql, i=config_id, v="pending", b=None), rule="verdict values",
                    constraint="review_log_verdict_check")
    assert_rejected(lambda: approver.run(insert_sql, i=config_id, v="approved", b="maybe"),
                    rule="bait_expected values", constraint="review_log_bait_expected_check")
    assert log_count() == 0
    for verdict, bait in [("approved", None), ("rejected", "approved"), ("approved", "rejected")]:
        approver.run(insert_sql, i=config_id, v=verdict, b=bait)
    assert log_count() == 3  # two or more reviews of one configuration are allowed
    row = approver.run("SELECT reviewer, reviewed_at IS NOT NULL FROM review_log WHERE config_id = :i LIMIT 1",
                       i=config_id)[0]
    assert row == ["approver", True]


def test_signals_primary_key():
    name = signal_name()
    insert("admin", config(new_run_id(), "R4", signal_name=name, status="active", approved_by="someone"))
    a = admin()
    sql = "INSERT INTO signals (installation_id, signal_name, ts, value) VALUES (:i, :n, CAST(:ts AS timestamptz), :v)"
    params = dict(i=INSTALLATION, n=name, ts="2026-01-01T00:00:00+00:00", v=1.5)

    def rows():
        return a.run("SELECT count(*) FROM signals WHERE signal_name = :n", n=name)[0][0]

    a.run(sql, **params)
    assert_rejected(lambda: a.run(sql, **params), rule="signals primary key", sqlstate="23505",
                    constraint="signals_pkey")
    assert rows() == 1
    a.run(sql, **{**params, "ts": "2026-01-01T00:00:10+00:00"})
    assert rows() == 2
    assert_rejected(lambda: a.run(sql, **{**params, "ts": "2026-01-01T00:00:20+00:00", "v": None}),
                    rule="signals value not null", sqlstate="23502")
    assert rows() == 2


# --- 12.3 foreign keys -------------------------------------------------------------------------

FOREIGN_KEY_CASES = {
    "config_field_exists": ("R4", dict(source_field="no_such_field")),
    "config_unit_matches_source": ("R3", dict(unit="ms")),
    "config_answers_request": ("R4", dict(request_id="R9")),
    "config_service_matches_request": ("R3", dict(service_id="media", source_field="mst_wr_lat", unit="ms")),
    "config_field_in_service": ("R4", dict(source_field="jq_depth")),
    "config_type_matches_request": ("R4", dict(signal_type="latency", source_field="api_p95", unit="s")),
    "config_sampling_requested": ("R4", dict(sample_s=20)),
    "config_unit_allowed_for_type": ("R4", dict(source_field="api_p95", unit="s")),
}


@pytest.mark.parametrize("name", list(FOREIGN_KEY_CASES))
def test_config_foreign_key(name):
    request, override = FOREIGN_KEY_CASES[name]
    run = new_run_id()
    insert("agent_writer", config(new_run_id(), request))  # the valid row passes
    assert_rejected(lambda: insert("agent_writer", config(run, request, **override)),
                    rule=f"foreign key {name}", sqlstate="23503", constraint=name)
    assert count("run_id = :r", r=run) == 0


# --- 12.4 unique constraints and approval ------------------------------------------------------

# The repeat may break a later foreign key as well. UNIQUE is reported first, so the name is stable.
UNIQUE_CASES = {
    "config_one_per_request": ("R4", dict(signal_name="sig_second", source_field="api_p95", unit="s")),
    "config_one_per_signal": ("R3", dict(signal_name="sig_r4")),
    "config_one_per_field": ("R3", dict(source_field="api_5xx", unit="count")),
}


@pytest.mark.parametrize("name", list(UNIQUE_CASES))
def test_config_unique(name):
    request, override = UNIQUE_CASES[name]
    run = new_run_id()
    insert("agent_writer", config(run, "R4"))
    assert_rejected(lambda: insert("agent_writer", config(run, request, **override)),
                    rule=f"unique {name}", sqlstate="23505", constraint=name)
    assert count("run_id = :r", r=run) == 1
    # the same value in another run_id passes
    other = new_run_id()
    insert("agent_writer", config(other, "R3", signal_name="sig_r4") if name == "config_one_per_signal"
           else config(other, "R4"))
    assert count("run_id = :r", r=other) == 1


@pytest.mark.parametrize("status,approved_by,passes", [
    ("approved", None, False), ("active", None, False), ("approved", "someone", True), ("active", "someone", True),
    ("draft", None, True), ("needs_review", None, True), ("rejected", None, True)])
def test_approval_signed(status, approved_by, passes):
    run = new_run_id()
    row = config(run, "R4", status=status, **({"approved_by": approved_by} if approved_by else {}))
    if passes:
        insert("admin", row)
        assert count("run_id = :r", r=run) == 1
    else:
        assert_rejected(lambda: insert("admin", row), rule="approval signed", constraint="config_approval_signed")
        assert count("run_id = :r", r=run) == 0


# --- 12.5 signal name pattern ------------------------------------------------------------------

NAME_CASES = [
    ("ab", False), ("abc", True), ("a" * 41, True), ("a" * 42, False),
    ("1abc", False), ("Abc", False), ("_abc", False), ("a-bc", False), ("a bc", False),
    ("abc\n", False), ("a_1", True), ("abC", False),
]


@pytest.mark.parametrize("name,passes", NAME_CASES, ids=[repr(c[0]) for c in NAME_CASES])
def test_signal_name_pattern(name, passes):
    run = new_run_id()
    row = config(run, "R4", signal_name=name)
    if passes:
        insert("agent_writer", row)
        assert count("run_id = :r", r=run) == 1
    else:
        assert_rejected(lambda: insert("agent_writer", row), rule="signal name pattern",
                        constraint="collection_configs_signal_name_check")
        assert count("run_id = :r", r=run) == 0


# --- 13.1 precedence ---------------------------------------------------------------------------

ALL_WRONG = dict(request_id="R9", source_field="nope", service_id="zzz", signal_type="zzz", unit="zzz", sample_s=20)
FK_PRECEDENCE = [
    # (case, request, overrides, expected). Several foreign keys can fail together, the first one is reported.
    ("fk1 alone: unknown field (also breaks 2 and 5)", "R4", dict(source_field="no_such_field"), "config_field_exists"),
    ("fk2 alone", "R3", dict(unit="ms"), "config_unit_matches_source"),
    ("fk3 alone: unknown request (also breaks 4, 6, 7)", "R4", dict(request_id="R9"), "config_answers_request"),
    ("fk4 alone", "R3", dict(service_id="media", source_field="mst_wr_lat", unit="ms"),
     "config_service_matches_request"),
    ("fk5 alone", "R4", dict(source_field="jq_depth"), "config_field_in_service"),
    ("fk6 alone", "R4", dict(signal_type="latency", source_field="api_p95", unit="s"), "config_type_matches_request"),
    ("fk7 alone", "R4", dict(sample_s=20), "config_sampling_requested"),
    ("fk8 alone", "R4", dict(source_field="api_p95", unit="s"), "config_unit_allowed_for_type"),
    ("pair 1-2", "R4", dict(source_field="no_such_field", unit="ms"), "config_field_exists"),
    ("pair 2-3", "R4", dict(request_id="R9", source_field="api_p95", unit="ms", signal_type="latency"),
     "config_unit_matches_source"),
    ("pair 3-4", "R4", dict(request_id="R9", service_id="media"), "config_answers_request"),
    ("pair 4-5", "R4", dict(service_id="media"), "config_service_matches_request"),
    ("pair 5-6", "R4", dict(source_field="jq_depth", signal_type="latency"), "config_field_in_service"),
    ("pair 6-7", "R4", dict(signal_type="latency", source_field="api_p95", unit="s", sample_s=20),
     "config_type_matches_request"),
    ("pair 7-8", "R4", dict(source_field="api_p95", unit="s", sample_s=20), "config_sampling_requested"),
    ("all eight", "R4", ALL_WRONG, "config_field_exists"),
]


@pytest.mark.parametrize("case,request_,override,expected", FK_PRECEDENCE, ids=[c[0] for c in FK_PRECEDENCE])
def test_precedence_foreign_keys(case, request_, override, expected):
    run = new_run_id()
    assert_rejected(lambda: insert("agent_writer", config(run, request_, **override)), rule=case, constraint=expected)
    assert count("run_id = :r", r=run) == 0


def test_precedence_unique_before_foreign_key():
    run = new_run_id()
    insert("agent_writer", config(run, "R4"))
    assert_rejected(lambda: insert("agent_writer", config(run, "R4", unit="ms", signal_name="sig_second")),
                    rule="UNIQUE before foreign key", constraint="config_one_per_request")
    assert count("run_id = :r", r=run) == 1


def test_precedence_among_unique_constraints():
    run = new_run_id()
    insert("agent_writer", config(run, "R4"))
    assert_rejected(lambda: insert("agent_writer", config(run, "R4")),
                    rule="request and signal and field repeat", constraint="config_one_per_request")
    assert_rejected(lambda: insert("agent_writer", config(run, "R3", signal_name="sig_r4", source_field="api_5xx",
                                                          unit="count")),
                    rule="signal and field repeat", constraint="config_one_per_signal")
    assert count("run_id = :r", r=run) == 1


def test_precedence_check_before_unique():
    run = new_run_id()
    insert("agent_writer", config(run, "R4"))
    assert_rejected(lambda: insert("agent_writer", config(run, "R4", signal_name="AB")),
                    rule="CHECK before UNIQUE", constraint="collection_configs_signal_name_check")
    assert count("run_id = :r", r=run) == 1


def test_precedence_sampling_before_everything():
    run = new_run_id()
    insert("agent_writer", config(run, "R4"))
    # sample_s 5 is below 10 for api_5xx. The row also has a bad name, repeats the request and breaks a foreign key.
    assert_rejected(lambda: insert("agent_writer", config(run, "R4", sample_s=5, signal_name="AB", unit="ms")),
                    rule="sampling before CHECK, UNIQUE and foreign key", sqlstate="23514",
                    constraint="config_sampling_supported")
    assert count("run_id = :r", r=run) == 1


# --- 13.2 sampling -----------------------------------------------------------------------------
# api_p95 accepts 10 to 300. Request R3 asks for 10, so a value other than 10 that the trigger lets
# through is then stopped by config_sampling_requested, which comes later in the order. Seeing that
# later name shows the sampling rule accepted the value.

@pytest.mark.parametrize("value,expected", [
    (9, "config_sampling_supported"), (10, None), (11, "config_sampling_requested"),
    (299, "config_sampling_requested"), (300, "config_sampling_requested"), (301, "config_sampling_supported")])
def test_sampling_bounds_on_insert(value, expected):
    run = new_run_id()
    row = config(run, "R3", sample_s=value)
    if expected is None:
        insert("agent_writer", row)
        assert count("run_id = :r", r=run) == 1
        return
    e = assert_rejected(lambda: insert("agent_writer", row), rule=f"sampling bound {value}", constraint=expected)
    if expected == "config_sampling_supported":
        assert e.sqlstate == "23514"
        assert f"config_sampling_supported: sample_s {value} outside 10 to 300 for api_p95" in str(e)
    assert count("run_id = :r", r=run) == 0


@pytest.mark.parametrize("value,expected", [
    (9, "config_sampling_supported"), (301, "config_sampling_supported"), (11, "config_sampling_requested"),
    (300, "config_sampling_requested")])
def test_sampling_bounds_on_update_of_sample_s(value, expected):
    config_id = insert("agent_writer", config(new_run_id(), "R3"))
    assert_rejected(lambda: admin().run("UPDATE collection_configs SET sample_s = :v WHERE config_id = :i",
                                        v=value, i=config_id),
                    rule=f"sampling bound {value} on UPDATE", constraint=expected)
    assert admin().run("SELECT sample_s FROM collection_configs WHERE config_id = :i", i=config_id) == [[10]]


def test_sampling_on_update_of_source_field():
    config_id = insert("agent_writer", config(new_run_id(), "R3"))  # sample_s 10
    e = assert_rejected(lambda: admin().run("UPDATE collection_configs SET source_field = 'cls_create_fail' "
                                            "WHERE config_id = :i", i=config_id),
                        rule="sampling on UPDATE of source_field", constraint="config_sampling_supported",
                        sqlstate="23514")
    assert "sample_s 10 outside 30 to 600 for cls_create_fail" in str(e)
    assert admin().run("SELECT source_field FROM collection_configs WHERE config_id = :i", i=config_id) == [["api_p95"]]


def test_sampling_passthrough():
    run = new_run_id()
    assert_rejected(lambda: insert("agent_writer", config(run, "R4", source_field="no_such_field")),
                    rule="unknown field passes the sampling rule", constraint="config_field_exists")
    assert_rejected(lambda: insert("agent_writer", config(run, "R4", sample_s=None)),
                    rule="NULL sample_s passes the sampling rule", sqlstate="23502")
    assert count("run_id = :r", r=run) == 0


def test_sampling_trigger_definition():
    a = admin()
    definition = a.run("SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname = 'config_sampling'")[0][0]
    assert "BEFORE INSERT OR UPDATE OF source_field, sample_s" in definition and "FOR EACH ROW" in definition
    assert a.run("SELECT prosecdef, proconfig FROM pg_proc WHERE proname = 'check_sampling'") == [
        [True, ["search_path=public"]]]
    assert a.run("SELECT has_table_privilege('approver', 'source_fields', 'SELECT')") == [[False]]


# --- 13.3 transitions --------------------------------------------------------------------------

AGENT, APPROVER, ADMIN = "agent_writer", "approver", "admin"
AGENT_RULE, PROMOTE_RULE, BAIT_RULE = "config_agent_cannot_approve", "config_promote_only_approved", "config_bait_never_active"
# role, old status, new status, bait, expected (None means the update passes)
TRANSITIONS = [
    (AGENT, "draft", "draft", False, None), (APPROVER, "draft", "draft", False, None),
    (ADMIN, "draft", "draft", False, None), (AGENT, "approved", "approved", False, None),
    (AGENT, "draft", "needs_review", False, None),
    (AGENT, "draft", "approved", False, AGENT_RULE), (AGENT, "needs_review", "draft", False, AGENT_RULE),
    (AGENT, "draft", "active", False, AGENT_RULE), (AGENT, "draft", "rejected", False, AGENT_RULE),
    (AGENT, "approved", "active", False, AGENT_RULE),
    (APPROVER, "approved", "active", False, None),
    (APPROVER, "draft", "active", False, PROMOTE_RULE), (APPROVER, "rejected", "active", False, PROMOTE_RULE),
    (APPROVER, "needs_review", "active", False, PROMOTE_RULE),
    (APPROVER, "approved", "active", True, BAIT_RULE), (ADMIN, "approved", "active", True, BAIT_RULE),
    (ADMIN, "draft", "active", False, PROMOTE_RULE),
    (AGENT, "draft", "active", True, AGENT_RULE),        # agent rule wins over promote and bait
    (APPROVER, "draft", "active", True, PROMOTE_RULE),   # promote rule wins over bait
    (APPROVER, "draft", "needs_review", False, None), (APPROVER, "needs_review", "rejected", False, None),
]


@pytest.mark.parametrize("role,old,new,bait,expected", TRANSITIONS,
                         ids=[f"{r}:{o}->{n}{':bait' if b else ''}" for r, o, n, b, _ in TRANSITIONS])
def test_transitions(role, old, new, bait, expected):
    signed = {"approved_by": "someone"} if old in ("approved", "active") else {}
    config_id = insert("admin", config(new_run_id(), "R4", status=old, is_bait=bait, **signed))
    # the approver signs when it approves, as the check config_approval_signed requires
    sets, params = "status = :s", dict(s=new, i=config_id)
    if role != AGENT and new in ("approved", "active"):
        sets += ", approved_by = :a"
        params["a"] = "approver"
    call = lambda: connect_as(role).run(f"UPDATE collection_configs SET {sets} WHERE config_id = :i", **params)
    if expected is None:
        call()
        assert status_of(config_id) == new
        return
    e = assert_rejected(call, rule=f"transition {role} {old}->{new}", constraint=expected)
    if expected == AGENT_RULE:
        assert e.sqlstate == "42501"
        assert f"agent cannot move a configuration from {old} to {new}" in str(e)
    else:
        assert e.sqlstate == "23514"
    assert status_of(config_id) == old


# --- 13.4 signal admission ---------------------------------------------------------------------

SIGNAL_SQL = ("INSERT INTO signals (installation_id, signal_name, ts, value) "
              "VALUES (:i, :n, CAST('2026-01-01T00:00:00+00:00' AS timestamptz), 1.0)")


def signals_stored(name):
    return admin().run("SELECT count(*) FROM signals WHERE signal_name = :n", n=name)[0][0]


def reject_signal(name, installation=INSTALLATION, rule="signal admission"):
    e = assert_rejected(lambda: admin().run(SIGNAL_SQL, i=installation, n=name), rule=rule, sqlstate="23503",
                        constraint="signal_needs_active_config")
    assert f"signal_needs_active_config: no active configuration for {name}" in str(e)
    assert signals_stored(name) == 0


def test_signal_without_a_configuration_is_rejected():
    reject_signal(signal_name())


@pytest.mark.parametrize("status", ["draft", "needs_review", "approved", "rejected"])
def test_signal_with_a_non_active_configuration_is_rejected(status):
    name = signal_name()
    extra = {"approved_by": "someone"} if status == "approved" else {}
    insert("admin", config(new_run_id(), "R4", signal_name=name, status=status, **extra))
    reject_signal(name, rule=f"configuration in status {status}")


def test_signal_with_an_active_configuration_is_stored():
    name = signal_name()
    insert("admin", config(new_run_id(), "R4", signal_name=name, status="active", approved_by="someone"))
    admin().run(SIGNAL_SQL, i=INSTALLATION, n=name)
    assert signals_stored(name) == 1


def test_active_configuration_of_another_name_or_installation_does_not_count():
    name = signal_name()
    insert("admin", config(new_run_id(), "R4", signal_name=name, status="active", approved_by="someone"))
    reject_signal(signal_name(), rule="another signal name")
    reject_signal(name, installation="another-installation", rule="another installation")


def test_draft_and_active_configurations_together_admit_the_signal():
    name = signal_name()
    insert("admin", config(new_run_id(), "R4", signal_name=name))
    insert("admin", config(new_run_id(), "R4", signal_name=name, status="active", approved_by="someone"))
    admin().run(SIGNAL_SQL, i=INSTALLATION, n=name)
    assert signals_stored(name) == 1


# --- 13.5 grants and forbidden statements ------------------------------------------------------

COLUMNS = ["config_id", "run_id", "installation_id", "request_id", "service_id", "signal_name", "signal_type",
           "source_field", "unit", "sample_s", "model_id", "status", "created_by", "approved_by", "is_bait"]
AGENT_INSERT = ["run_id", "installation_id", "request_id", "service_id", "signal_name", "signal_type",
                "source_field", "unit", "sample_s", "model_id"]
SIX_TABLES = ["installations", "services", "source_fields", "signal_requests", "allowed_units", "signals"]


def privilege(role, column, kind):
    return admin().run("SELECT has_column_privilege(:r, 'collection_configs', :c, :p)", r=role, c=column, p=kind)[0][0]


@pytest.mark.parametrize("column", COLUMNS)
def test_role_grants_on_every_column(column):
    expected = {
        ("agent_writer", "INSERT"): column in AGENT_INSERT, ("agent_writer", "SELECT"): True,
        ("agent_writer", "UPDATE"): column == "status",
        ("approver", "INSERT"): False, ("approver", "SELECT"): True,
        ("approver", "UPDATE"): column in ("status", "approved_by"),
    }
    actual = {(role, kind): privilege(role, column, kind) for role, kind in expected}
    assert actual == expected, f"column {column}"


def test_role_grants_on_the_other_tables_and_login():
    a = admin()
    for table in SIX_TABLES:
        for kind in ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]:
            has = lambda role: a.run("SELECT has_table_privilege(:r, :t, :p)", r=role, t=table, p=kind)[0][0]
            assert has("approver") is False, f"approver {kind} on {table}"
            assert has("agent_writer") is (kind == "SELECT"), f"agent_writer {kind} on {table}"
        assert a.run("SELECT has_any_column_privilege('approver', :t, 'SELECT')", t=table) == [[False]]
    assert a.run("SELECT has_table_privilege('approver', 'review_log', 'INSERT'), "
                 "has_table_privilege('approver', 'review_log', 'SELECT'), "
                 "has_table_privilege('agent_writer', 'review_log', 'SELECT')") == [[True, True, False]]
    assert a.run("SELECT has_sequence_privilege('agent_writer', 'collection_configs_config_id_seq', 'USAGE')") == [[True]]
    logins = a.run("SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('agent_writer', 'approver') "
                   "ORDER BY rolname")
    assert logins == [["agent_writer", True], ["approver", True]]


@pytest.mark.parametrize("column,value", [("config_id", 999999), ("status", "draft"), ("created_by", "me"),
                                          ("approved_by", "me"), ("is_bait", False)])
def test_agent_cannot_insert_forbidden_columns(column, value):
    run = new_run_id()
    assert_rejected(lambda: insert("agent_writer", config(run, "R4", **{column: value}), returning=False),
                    rule=f"agent INSERT of {column}", sqlstate="42501")
    assert count("run_id = :r", r=run) == 0


def test_agent_cannot_update_other_columns():
    config_id = insert("agent_writer", config(new_run_id(), "R4"))
    assert_rejected(lambda: connect_as("agent_writer").run(
        "UPDATE collection_configs SET signal_name = 'changed_name' WHERE config_id = :i", i=config_id),
        rule="agent UPDATE of signal_name", sqlstate="42501")
    assert admin().run("SELECT signal_name FROM collection_configs WHERE config_id = :i", i=config_id) == [["sig_r4"]]
    connect_as("agent_writer").run("UPDATE collection_configs SET status = 'needs_review' WHERE config_id = :i", i=config_id)
    assert status_of(config_id) == "needs_review"


def test_approver_cannot_insert_delete_or_update_other_columns():
    approver = connect_as("approver")
    run = new_run_id()
    config_id = insert("admin", config(run, "R4", status="needs_review"))
    assert_rejected(lambda: insert("approver", config(new_run_id(), "R3"), returning=False),
                    rule="approver INSERT", sqlstate="42501")
    assert_rejected(lambda: approver.run("DELETE FROM collection_configs WHERE config_id = :i", i=config_id),
                    rule="approver DELETE", sqlstate="42501")
    assert_rejected(lambda: approver.run("UPDATE collection_configs SET signal_name = 'changed_name' "
                                         "WHERE config_id = :i", i=config_id),
                    rule="approver UPDATE of signal_name", sqlstate="42501")
    assert count("run_id = :r", r=run) == 1
    approver.run("UPDATE collection_configs SET status = 'approved', approved_by = 'approver' WHERE config_id = :i",
                 i=config_id)
    assert status_of(config_id) == "approved"
