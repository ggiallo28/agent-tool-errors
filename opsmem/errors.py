"""Turn a database rejection of a configuration row into the text the model reads.

Two modes: ``raw`` shows the database message untouched, ``instructive`` shows
the violated rule, a statement that nothing was saved, and a one-line
instruction that names the parameter to change. No instruction names a tool.

The valid-values lookup reads the catalog tables, so it needs the
``agent_writer`` Database_Object (the role that holds SELECT on them). An
``approver`` object has no such grant and every lookup would fail.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

MODES = ("raw", "instructive")
MAX_VALID = 10
NONE_LISTED = "none listed"
UNKNOWN = "unknown"
UNKNOWN_INSTRUCTION = "Rejected."

# External contract: keep every string byte for byte.
INSTRUCTIONS: dict[str, str] = {
    "config_field_exists": "Unknown source_field. Valid source_field: {valid}.",
    "config_unit_matches_source": "Wrong unit for this source_field. Valid unit: {valid}.",
    "config_answers_request": "Unknown request_id. Valid request_id: {valid}.",
    "config_service_matches_request": "Wrong service_id for this request. Valid service_id: {valid}.",
    "config_field_in_service": "This source_field is not in this service. Valid source_field: {valid}.",
    "config_type_matches_request": "Wrong signal_type for this request. Valid signal_type: {valid}.",
    "config_sampling_requested": "Wrong sample_seconds for this request. Valid sample_seconds: {valid}.",
    "config_one_per_request": "This request_id is already configured.",
    "config_unit_allowed_for_type": "This unit is not allowed for this signal_type. Valid unit: {valid}.",
    "config_sampling_supported": "sample_seconds not supported by this source_field. Valid range: {valid}.",
    "config_one_per_signal": "This signal_name is already used. Choose another signal_name.",
    "config_one_per_field": "This source_field is already configured.",
    "signal_name_check": "signal_name must be lowercase letters, digits and underscores, 3 to 41 characters.",
    "integer_input": "sample_seconds must be a whole number of seconds.",
}


_NAME = re.compile(
    r'constraint "([^"]+)"'  # PostgreSQL / psycopg text
    r"|CONSTRAINT: ([A-Za-z0-9_]+)"  # DETAIL-style text
    r"|CONSTRAINT=([A-Za-z0-9_]+)"  # key=value style text
    r"|\b(config_[A-Za-z0-9_]*)"  # bare word, as in the sampling trigger message
)
_SQLSTATE = re.compile(r"SQLState: ([0-9A-Z]{5})")


def classify(message: str) -> str:
    """Return the violated rule named in a database message, or ``unknown``."""
    for m in _NAME.finditer(message):
        name = next(g for g in m.groups() if g is not None)
        if name in INSTRUCTIONS:
            return name
        if name.endswith("signal_name_check"):
            return "signal_name_check"
    codes = _SQLSTATE.findall(message)
    if "22P02" in codes or "invalid input syntax for type integer" in message:
        return "integer_input"
    if "signal_name" in message and "check" in message.lower():
        return "signal_name_check"
    return UNKNOWN


def render(rule: str, valid: Sequence[str], mode: str, raw_message: str) -> str:
    """Build the text the model reads for one rejection."""
    if mode == "raw":
        return "ERROR: " + raw_message
    if mode == "instructive":
        return f"REJECTED ({rule}). Not saved. " + _instruction(rule, valid)
    raise ValueError(f"Invalid mode: {mode!r}")


def _instruction(rule: str, valid: Sequence[str]) -> str:
    template = INSTRUCTIONS.get(rule)
    if template is None:
        return UNKNOWN_INSTRUCTION
    shown = ", ".join(str(v) for v in valid[:MAX_VALID]) or NONE_LISTED
    return template.replace("{valid}", shown)


def _first_column(rows) -> list[str]:
    return [str(row[0]) for row in rows]


def _sorted_first_column(rows) -> list[str]:
    return sorted(_first_column(rows))


def _range_text(rows) -> list[str]:
    if not rows:
        return []
    return [f"{rows[0][0]} to {rows[0][1]} seconds"]


# rule -> (SQL, Proposal keys bound, uses_installation, row shaper). SELECT only.
_LOOKUPS = {
    "config_answers_request": (
        "SELECT request_id FROM signal_requests WHERE installation_id = :installation_id",
        (),
        True,
        _sorted_first_column,
    ),
    "config_service_matches_request": (
        "SELECT service_id FROM signal_requests "
        "WHERE installation_id = :installation_id AND request_id = :request_id",
        ("request_id",),
        True,
        _first_column,
    ),
    "config_type_matches_request": (
        "SELECT signal_type FROM signal_requests "
        "WHERE installation_id = :installation_id AND request_id = :request_id",
        ("request_id",),
        True,
        _first_column,
    ),
    "config_sampling_requested": (
        "SELECT sample_s FROM signal_requests "
        "WHERE installation_id = :installation_id AND request_id = :request_id",
        ("request_id",),
        True,
        _first_column,
    ),
    "config_field_in_service": (
        "SELECT field_name FROM source_fields "
        "WHERE installation_id = :installation_id AND service_id = :service_id",
        ("service_id",),
        True,
        _sorted_first_column,
    ),
    "config_field_exists": (
        "SELECT field_name FROM source_fields WHERE installation_id = :installation_id",
        (),
        True,
        _sorted_first_column,
    ),
    "config_unit_matches_source": (
        "SELECT unit FROM source_fields "
        "WHERE installation_id = :installation_id AND field_name = :source_field",
        ("source_field",),
        True,
        _first_column,
    ),
    "config_unit_allowed_for_type": (
        "SELECT unit FROM allowed_units WHERE signal_type = :signal_type",
        ("signal_type",),
        False,
        _sorted_first_column,
    ),
    "config_sampling_supported": (
        "SELECT min_sample_s, max_sample_s FROM source_fields "
        "WHERE installation_id = :installation_id AND field_name = :source_field",
        ("source_field",),
        True,
        _range_text,
    ),
}


def valid_values(db, rule: str, proposal: Mapping[str, object], installation_id: str) -> list[str]:
    """Read the valid values for a rejected rule from the catalog (SELECT only).

    ``db`` must be connected as ``agent_writer``. Returns ``[]`` when the rule has
    no lookup, the needed Proposal value is missing or not a str, the catalog has
    no row, or the database raises ``db.DatabaseError``.
    """
    entry = _LOOKUPS.get(rule)
    if entry is None:
        return []
    sql, keys, uses_installation, shape = entry
    params: dict[str, str] = {}
    for key in keys:
        value = proposal.get(key)
        if not isinstance(value, str):
            return []
        params[key] = value
    if uses_installation:
        params["installation_id"] = installation_id
    try:
        rows = db.run(sql, **params)
    except db.DatabaseError:
        return []
    return shape(rows)
