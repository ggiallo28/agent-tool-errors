"""Parsers of the manual and the OpenAPI schema (Requirements 15 to 17). Offline: files are read
here and their text is passed to the parsers; error cases use small inline texts."""
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem.manual import (MANUAL, OPENAPI, Field, ManualError, Request, Service, parse_fields,
                           parse_requests, parse_services)

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_TEXT = (ROOT / OPENAPI).read_text()
MANUAL_TEXT = (ROOT / MANUAL).read_text()


def test_services_from_tags_in_order():
    assert [s.service_id for s in parse_services(OPENAPI_TEXT)] == ["media", "encoding", "api", "classes", "queue"]


def test_nine_fields():
    assert len(parse_fields(OPENAPI_TEXT)) == 9


def test_api_p95_in_seconds_10_to_300():
    fields = {f.field_name: f for f in parse_fields(OPENAPI_TEXT)}
    assert fields["api_p95"] == Field("api", "api_p95", "s", 10, 300)


def test_mst_wr_lat_in_milliseconds():
    assert {f.field_name: f.unit for f in parse_fields(OPENAPI_TEXT)}["mst_wr_lat"] == "ms"


def test_six_requests_r5_at_60_seconds():
    requests = {r.request_id: r for r in parse_requests(MANUAL_TEXT)}
    assert len(requests) == 6
    assert requests["R5"].sample_s == 60


def test_every_request_points_to_a_known_service():
    services = {s.service_id for s in parse_services(OPENAPI_TEXT)}
    assert all(r.service_id in services for r in parse_requests(MANUAL_TEXT))


def test_dangling_ref_names_the_reference():
    text = """
tags: [{name: a, description: A}]
paths:
  /a/stats:
    get:
      tags: [a]
      responses: {"200": {content: {application/json: {schema: {$ref: "#/components/schemas/Missing"}}}}}
"""
    with pytest.raises(ManualError, match="#/components/schemas/Missing"):
        parse_fields(text)


def test_missing_section_is_named():
    with pytest.raises(ManualError, match="Requests from operations"):
        parse_requests("# Manual\n\nNo table here.\n")


def test_section_without_rows():
    text = "## Requests from operations\n\n| Request id | Service id | Signal type | Sampling | Request |\n|---|---|---|---|---|\n"
    with pytest.raises(ManualError, match=r"Requests from operations.*no request rows found"):
        parse_requests(text)


def test_no_tags():
    with pytest.raises(ManualError, match="tags"):
        parse_services("paths: {}\n")


def test_no_get_stats_responses():
    with pytest.raises(ManualError, match="GET stats responses"):
        parse_fields("tags: [{name: a, description: A}]\npaths: {}\n")


def test_parsers_return_frozen_values():
    assert isinstance(parse_services(OPENAPI_TEXT)[0], Service)
    assert isinstance(parse_requests(MANUAL_TEXT)[0], Request)


# --- generated documents -------------------------------------------------------------------

ident = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
text_cell = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9 ,.]{0,20}[A-Za-z0-9]", fullmatch=True)


@st.composite
def openapi_docs(draw):
    tags = draw(st.lists(ident, min_size=1, max_size=4, unique=True))
    spec = {"openapi": "3.0.3", "tags": [{"name": t, "description": f"{t} service"} for t in tags],
            "paths": {}, "components": {"schemas": {}}}
    services = [Service(t, f"{t} service") for t in tags]
    fields = []
    used = set()
    for i in range(draw(st.integers(min_value=1, max_value=4))):
        tag = draw(st.sampled_from(tags))
        props = {}
        for name in draw(st.lists(ident.filter(lambda n: n not in used), min_size=1, max_size=3, unique=True)):
            used.add(name)
            lo = draw(st.integers(min_value=1, max_value=100))
            hi = draw(st.integers(min_value=lo, max_value=1000))
            unit = draw(st.sampled_from(["ms", "s", "count", "percent"]))
            props[name] = {"type": "number", "x-unit": unit, "x-sampling-min-s": lo, "x-sampling-max-s": hi}
            fields.append(Field(tag, name, unit, lo, hi))
        schema = {"type": "object", "properties": props}
        if draw(st.booleans()):
            spec["components"]["schemas"][f"S{i}"] = schema
            schema = {"$ref": f"#/components/schemas/S{i}"}
        spec["paths"][f"/p{i}/stats"] = {"get": {"tags": [tag], "operationId": f"op{i}", "responses": {
            "200": {"content": {"application/json": {"schema": schema}}}}}}
    return yaml.safe_dump(spec, sort_keys=False), services, fields


# Feature: catalog-schema, Property 13: OpenAPI parse round trip
@settings(max_examples=100)
@given(openapi_docs())
def test_property_openapi_round_trip(doc):
    text, services, fields = doc
    assert parse_services(text) == services
    assert parse_fields(text) == fields
    assert parse_services(text) == parse_services(text) and parse_fields(text) == parse_fields(text)


# Feature: catalog-schema, Property 14: Dangling references are reported
@settings(max_examples=100)
@given(ident, ident)
def test_property_dangling_reference(tag, missing):
    ref = f"#/components/schemas/{missing}"
    spec = {"tags": [{"name": tag, "description": tag}], "components": {"schemas": {}},
            "paths": {"/x/stats": {"get": {"tags": [tag], "responses": {
                "200": {"content": {"application/json": {"schema": {"$ref": ref}}}}}}}}}
    with pytest.raises(ManualError) as err:
        parse_fields(yaml.safe_dump(spec))
    assert ref in str(err.value)


requests_lists = st.lists(st.builds(Request, request_id=st.from_regex(r"R[0-9]{1,3}", fullmatch=True),
                                    service_id=ident, signal_type=st.sampled_from(["latency", "count", "ratio", "age"]),
                                    sample_s=st.integers(min_value=1, max_value=86400), request_text=text_cell),
                          min_size=1, max_size=8)


def render(requests, short_row=None):
    lines = ["# Manual", "", "## Requests from operations", "", "Intro.", "",
             "| Request id | Service id | Signal type | Sampling | Request |", "|---|---|---|---|---|"]
    for i, r in enumerate(requests):
        cells = [f"`{r.request_id}`", f"`{r.service_id}`", r.signal_type, f"{r.sample_s} s", r.request_text]
        if i == short_row:
            cells = cells[:3]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines + ["", "## Next section", ""])


# Feature: catalog-schema, Property 15: Requests table round trip
@settings(max_examples=100)
@given(requests_lists, st.data())
def test_property_requests_round_trip(requests, data):
    text = render(requests)
    assert parse_requests(text) == requests
    assert parse_requests(text) == parse_requests(text)
    short = data.draw(st.integers(min_value=0, max_value=len(requests) - 1))
    with pytest.raises(ManualError, match="fewer cells") as err:
        parse_requests(render(requests, short_row=short))
    assert requests[short].request_id in str(err.value)
