"""Pure tests for opsmem.errors: no database, no network."""

import pytest

from opsmem.errors import INSTRUCTIONS, classify, render

# Literal contract strings, kept independent from the module (Requirement 5.11).
EXPECTED = {
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


@pytest.mark.parametrize("rule,text", sorted(EXPECTED.items()))
def test_instruction_literal(rule, text):
    assert INSTRUCTIONS[rule] == text


def test_instruction_keys_exactly_14():
    assert len(EXPECTED) == 14
    assert set(INSTRUCTIONS) == set(EXPECTED)


def test_no_instruction_names_propose_config():
    assert all("propose_config" not in v for v in INSTRUCTIONS.values())


def test_raw_mode_returns_error_prefix_and_unchanged_message():
    msg = '  weird {valid} message\nwith "quotes"  '
    assert render("config_field_exists", ["a"], "raw", msg) == "ERROR: " + msg


def test_twelve_valid_values_show_first_ten():
    valid = [f"v{i}" for i in range(12)]
    out = render("config_field_exists", valid, "instructive", "x")
    assert out == (
        "REJECTED (config_field_exists). Not saved. "
        "Unknown source_field. Valid source_field: "
        + ", ".join(valid[:10])
        + "."
    )
    assert "v10" not in out and "v11" not in out


def test_no_valid_values_show_none_listed():
    out = render("config_field_exists", [], "instructive", "x")
    assert out.endswith("Valid source_field: none listed.")


def test_unknown_rule_renders_rejected():
    assert (
        render("not_a_rule", [], "instructive", "x")
        == "REJECTED (not_a_rule). Not saved. Rejected."
    )


@pytest.mark.parametrize("mode", ["RAW", "", "other"])
def test_invalid_mode_raises_with_value(mode):
    with pytest.raises(ValueError) as exc:
        render("config_field_exists", [], mode, "x")
    assert repr(mode) in str(exc.value)


@pytest.mark.parametrize(
    "message,rule",
    [
        (
            'ERROR: insert or update on table "collection_configs" violates foreign key '
            'constraint "config_field_exists"\nDETAIL: Key (source_field)=(nope) is not present.',
            "config_field_exists",
        ),
        (
            "ERROR: config_sampling_supported: sample_s 5 outside 10 to 300 for api_p95",
            "config_sampling_supported",
        ),
        (
            'ERROR: invalid input syntax for type integer: "every minute"',
            "integer_input",
        ),
        (
            'ERROR: new row for relation "collection_configs" violates check constraint '
            '"collection_configs_signal_name_check"',
            "signal_name_check",
        ),
        (
            "An error occurred (DatabaseErrorException): ErrorMessage: invalid input, "
            "SQLState: 22P02",
            "integer_input",
        ),
        ("ERROR: something unrelated went wrong", "unknown"),
    ],
)
def test_classify_examples(message, rule):
    assert classify(message) == rule


# ---------------------------------------------------------------------------
# Property-based tests for render (Properties 1 to 5)
# ---------------------------------------------------------------------------
import string  # noqa: E402

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

PBT = settings(max_examples=100)

rules = st.sampled_from(sorted(EXPECTED))
any_rule = st.one_of(rules, st.text())
# No ", " and no "{" in values, so the shown list can be split and cannot fake a placeholder.
valid_lists = st.lists(
    st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=1),
    max_size=30,
)
messages = st.text()
valid_rules = st.sampled_from(sorted(r for r, t in EXPECTED.items() if "{valid}" in t))
plain_rules = st.sampled_from(sorted(r for r, t in EXPECTED.items() if "{valid}" not in t))

# Test-local examples of tool names; the module holds no such list.
TOOL_NAMES = ("propose_config", "submit_config", "list_requests")


def _prefix(rule):
    return f"REJECTED ({rule}). Not saved. "


# Feature: instructive-rejections, Property 1: Raw mode returns the message unchanged
@PBT
@given(rule=any_rule, valid=valid_lists, message=messages)
def test_property_raw_mode_returns_message_unchanged(rule, valid, message):
    """**Validates: Requirements 2.1**"""
    assert render(rule, valid, "raw", message) == "ERROR: " + message


# Feature: instructive-rejections, Property 2: Instructive output is the prefix plus the filled template
@PBT
@given(rule=rules, valid=valid_lists, message=messages)
def test_property_instructive_prefix_and_filled_template(rule, valid, message):
    """**Validates: Requirements 2.2, 2.3, 2.4, 2.5**"""
    out = render(rule, valid, "instructive", message)
    template = EXPECTED[rule]
    assert out.startswith(_prefix(rule))
    assert "{valid}" not in out
    if "{valid}" not in template:
        assert out == _prefix(rule) + template


@PBT
@given(rule=st.text().filter(lambda r: r not in EXPECTED), valid=valid_lists, message=messages)
def test_property_instructive_unknown_rule_is_rejected(rule, valid, message):
    """Feature: instructive-rejections, Property 2: unknown rule gives Rejected.

    **Validates: Requirements 2.5**
    """
    assert render(rule, valid, "instructive", message) == _prefix(rule) + "Rejected."


# Feature: instructive-rejections, Property 3: The Valid_List holds the first 10 values in order
@PBT
@given(rule=valid_rules, valid=valid_lists)
def test_property_valid_list_first_ten_in_order(rule, valid):
    """**Validates: Requirements 2.6, 2.7, 2.8**"""
    out = render(rule, valid, "instructive", "x")
    shown = ", ".join(valid[:10]) if valid else "none listed"
    assert out == _prefix(rule) + EXPECTED[rule].replace("{valid}", shown)
    if valid:
        head, tail = EXPECTED[rule].split("{valid}")
        body = out[len(_prefix(rule)) + len(head) : len(out) - len(tail)]
        assert body.split(", ") == valid[:10]


# Feature: instructive-rejections, Property 4: An invalid mode is rejected with its value
@PBT
@given(
    mode=st.text().filter(lambda m: m not in ("raw", "instructive")),
    rule=any_rule,
    valid=valid_lists,
    message=messages,
)
def test_property_invalid_mode_raises_with_value(mode, rule, valid, message):
    """**Validates: Requirements 2.9**"""
    with pytest.raises(ValueError) as exc:
        render(rule, valid, mode, message)
    assert repr(mode) in str(exc.value)


# Feature: instructive-rejections, Property 5: Instructions never name a tool
@PBT
@given(
    rule=any_rule,
    valid=valid_lists.map(lambda vs: [v for v in vs if not any(t in v for t in TOOL_NAMES)]),
    message=messages,
)
def test_property_instructions_never_name_a_tool(rule, valid, message):
    """**Validates: Requirements 1.16, 1.17, 2.10**"""
    out = render(rule, valid, "instructive", message)
    after_prefix = out[len(_prefix(rule)) :]
    assert out.startswith(_prefix(rule))
    assert not any(t in after_prefix for t in TOOL_NAMES)
    assert not any(t in text for t in TOOL_NAMES for text in INSTRUCTIONS.values())


# ---------------------------------------------------------------------------
# Property-based tests for classify (Properties 6 to 9)
# ---------------------------------------------------------------------------
# No underscore, quote, colon or equals sign: cannot hold a rule name or a marker.
filler = st.text(alphabet=string.ascii_letters + string.digits + " .,")

SIGNAL_NAME_CONSTRAINT = "collection_configs_signal_name_check"

# Templates with a {name} hole; real shapes. Separators keep filler from fusing with the name.
SHAPES = (
    'insert or update on table "collection_configs" violates foreign key constraint "{name}"',
    'duplicate key value violates unique constraint "{name}"',
    'new row for relation "collection_configs" violates check constraint "{name}"',
    "CONSTRAINT: {name}",
    "CONSTRAINT={name}",
    "{name}: sample_s 5 outside 10 to 300 for api_p95",
)
shapes = st.sampled_from(SHAPES)
rules_no_integer = st.sampled_from(sorted(r for r in EXPECTED if r != "integer_input"))


# Feature: instructive-rejections, Property 6: Classification is total and stays inside the table
@PBT
@given(text=st.text())
def test_property_classify_is_total_and_in_table(text):
    """**Validates: Requirements 3.7, 3.12**"""
    assert classify(text) in set(EXPECTED) | {"unknown"}


# Feature: instructive-rejections, Property 6: filler-only text is unknown
@PBT
@given(text=filler)
def test_property_classify_filler_only_is_unknown(text):
    """**Validates: Requirements 3.7, 3.12**"""
    assert classify(text) == "unknown"


# Feature: instructive-rejections, Property 7: A message built around a rule name is classified as that rule
@PBT
@given(rule=rules_no_integer, shape=shapes, before=filler, after=filler)
def test_property_message_around_rule_name_is_classified(rule, shape, before, after):
    """**Validates: Requirements 3.1, 3.2, 3.3, 3.8, 3.9, 3.10**"""
    name = SIGNAL_NAME_CONSTRAINT if rule == "signal_name_check" else rule
    message = before + "\n" + shape.format(name=name) + "\n" + after
    assert classify(message) == rule


# Feature: instructive-rejections, Property 8: The first qualifying name wins
@PBT
@given(
    pair=st.lists(st.sampled_from(sorted(EXPECTED)), min_size=2, max_size=2, unique=True),
    before=filler,
    middle=filler,
    after=filler,
)
def test_property_first_qualifying_name_wins(pair, before, middle, after):
    """**Validates: Requirements 3.2**"""
    a, b = pair

    def build(x, y):
        return f'{before} constraint "{x}" {middle} constraint "{y}" {after}'

    assert classify(build(a, b)) == a
    assert classify(build(b, a)) == b


# Feature: instructive-rejections, Property 9: Integer fallback applies only without a constraint name
@PBT
@given(
    marker=st.sampled_from(["SQLState: 22P02", "invalid input syntax for type integer"]),
    before=filler,
    after=filler,
)
def test_property_integer_fallback_without_constraint_name(marker, before, after):
    """**Validates: Requirements 3.4, 3.5, 3.11**"""
    assert classify(f"{before} {marker} {after}") == "integer_input"


# Feature: instructive-rejections, Property 9: signal_name fallback applies only without a constraint name
@PBT
@given(
    word=st.sampled_from(["check", "CHECK", "Check", "cHeCk"]),
    before=filler,
    middle=filler,
    after=filler,
)
def test_property_signal_name_fallback_without_constraint_name(word, before, middle, after):
    """**Validates: Requirements 3.6, 3.11**"""
    assert classify(f"{before} signal_name {middle} {word} {after}") == "signal_name_check"
