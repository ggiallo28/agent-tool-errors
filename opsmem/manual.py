"""Deterministic parsers of an installation's documentation.

Services and fields come from the source's OpenAPI schema, requests from the manual's
"Requests from operations" table. The parsers take the text of a file and read no file:
the Catalog_Loader in scripts/apply_schema.py reads MANUAL and OPENAPI and passes the text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

MANUAL = "manuals/course-platform-install-07.md"
OPENAPI = "manuals/course-platform-install-07.openapi.yaml"

REQUESTS_HEADING = "## Requests from operations"
MAX_REF_DEPTH = 32
SAMPLING_CELL = re.compile(r"^(\d+)\s*s$")


@dataclass(frozen=True)
class Service:
    service_id: str
    name: str


@dataclass(frozen=True)
class Field:
    service_id: str
    field_name: str
    unit: str
    min_sample_s: int
    max_sample_s: int


@dataclass(frozen=True)
class Request:
    request_id: str
    service_id: str
    signal_type: str
    sample_s: int
    request_text: str


class ManualError(ValueError):
    """The manual or the OpenAPI schema does not have what the catalog needs."""


def _load(openapi_text: str) -> dict:
    spec = yaml.safe_load(openapi_text)
    if not isinstance(spec, dict):
        raise ManualError("the OpenAPI text is not a YAML mapping")
    return spec


def _resolve(spec: dict, node, depth: int = 0):
    """Follow local $ref pointers (#/a/b/c) until a schema without $ref is reached."""
    if not isinstance(node, dict) or "$ref" not in node:
        return node
    ref = node["$ref"]
    if depth >= MAX_REF_DEPTH:
        raise ManualError(f"$ref chain too deep or cyclic at {ref}")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ManualError(f"unresolved $ref: {ref}")
    target = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            raise ManualError(f"unresolved $ref: {ref}")
        target = target[part]
    return _resolve(spec, target, depth + 1)


def _tags(spec: dict) -> list[dict]:
    tags = spec.get("tags")
    if not tags:
        raise ManualError("tags missing")
    return tags


def parse_services(openapi_text: str) -> list[Service]:
    """One service per OpenAPI tag, in file order: id from the tag name, name from its description."""
    spec = _load(openapi_text)
    return [Service(service_id=str(t["name"]), name=str(t.get("description", t["name"]))) for t in _tags(spec)]


def _stats_operations(spec: dict):
    for path, ops in (spec.get("paths") or {}).items():
        if isinstance(ops, dict) and str(path).endswith("/stats") and isinstance(ops.get("get"), dict):
            yield path, ops["get"]


def _sampling(value, name: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManualError(f"property {name}: {key} must be an integer")
    return value


def parse_fields(openapi_text: str) -> list[Field]:
    """One field per property of each GET stats response, owned by the operation's first tag."""
    spec = _load(openapi_text)
    known = {str(t["name"]) for t in _tags(spec)}
    out: list[Field] = []
    found = False
    for path, op in _stats_operations(spec):
        found = True
        label = op.get("operationId") or f"GET {path}"
        tags = op.get("tags") or []
        if not tags:
            raise ManualError(f"operation {label} has no tag")
        service = str(tags[0])
        if service not in known:
            raise ManualError(f"operation {label} uses tag {service}, which is not in tags")
        try:
            schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        except (KeyError, TypeError):
            raise ManualError(f"operation {label} has no 200 application/json schema") from None
        schema = _resolve(spec, schema)
        for name, prop in (schema.get("properties") or {}).items():
            prop = _resolve(spec, prop)
            for key in ("x-unit", "x-sampling-min-s", "x-sampling-max-s"):
                if key not in prop:
                    raise ManualError(f"property {name} of operation {label} has no {key}")
            out.append(Field(service_id=service, field_name=str(name), unit=str(prop["x-unit"]),
                             min_sample_s=_sampling(prop["x-sampling-min-s"], name, "x-sampling-min-s"),
                             max_sample_s=_sampling(prop["x-sampling-max-s"], name, "x-sampling-max-s")))
    if not found:
        raise ManualError("GET stats responses missing")
    return out


def _cells(line: str) -> list[str]:
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [c.strip().replace("`", "").strip() for c in inner.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(c and set(c) <= set("-: ") for c in cells)


def parse_requests(manual_text: str) -> list[Request]:
    """One request per data row of the first table under the 'Requests from operations' heading."""
    lines = manual_text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == REQUESTS_HEADING)
    except StopIteration:
        raise ManualError(f"section '{REQUESTS_HEADING}' not found in the manual") from None
    table: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.strip().startswith("|"):
            table.append(line)
        elif table:
            break
    header, rows = (_cells(table[0]), table[1:]) if table else ([], [])
    out: list[Request] = []
    for line in rows:
        cells = _cells(line)
        if _is_separator(cells):
            continue
        if len(cells) < len(header) or len(cells) < 5:
            raise ManualError(f"row with fewer cells than the header in '{REQUESTS_HEADING}': {line.strip()}")
        sampling = SAMPLING_CELL.match(cells[3])
        if not sampling:
            raise ManualError(f"row with a sampling cell that is not '<seconds> s': {line.strip()}")
        out.append(Request(request_id=cells[0], service_id=cells[1], signal_type=cells[2],
                           sample_s=int(sampling.group(1)), request_text=cells[4]))
    if not out:
        raise ManualError(f"section '{REQUESTS_HEADING}': no request rows found")
    return out
