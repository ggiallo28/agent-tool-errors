"""agent_input: the text the writer agent reads (the request texts and nothing else)."""
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem.manual import MANUAL, ManualError, agent_input
from tests.helpers import ROOT

EXPECTED = "\n".join([
    "Installation: install-07",
    "Requests:",
    "R1: Write latency of the media volume",
    "R2: How long files wait before encoding",
    "R3: API response time",
    "R4: API errors",
    "R5: Failed class creations",
    "R6: Depth of the job queue",
])

# Written by hand from the manual and the OpenAPI file of install-07. Service ids and signal types are
# not listed: each one also occurs as an ordinary word in a request text (media, queue, latency), so for
# them the equality with EXPECTED above is the check. Nothing but "<id>: <text>" lines can be there.
HIDDEN_FIELDS = ["mst_wr_lat", "mst_free_pct", "enc_q_wait", "enc_active", "api_p95", "api_5xx",
                 "cls_create_fail", "jq_depth", "jq_oldest"]
HIDDEN_UNITS = ["ms", "percent", "count"]
HIDDEN_SAMPLING = ["10 s", "60 s", "10", "60"]


def test_real_manual_gives_the_expected_text():
    assert agent_input(ROOT) == EXPECTED


def test_no_trailing_newline():
    assert not agent_input(ROOT).endswith("\n")


def test_real_manual_hides_catalog_facts():
    body = "\n".join(agent_input(ROOT).split("\n")[2:])
    words = set(re.findall(r"[A-Za-z0-9_]+", body))
    for hidden in HIDDEN_FIELDS + HIDDEN_UNITS:
        assert hidden not in words, hidden
    for hidden in HIDDEN_SAMPLING:
        assert hidden not in body, hidden


def test_installation_id_changes_only_the_first_line():
    other = agent_input(ROOT, "install-99").split("\n")
    assert other[0] == "Installation: install-99"
    assert other[1:] == EXPECTED.split("\n")[1:]


def test_missing_section_raises_manual_error(tmp_path):
    (tmp_path / MANUAL).parent.mkdir(parents=True)
    (tmp_path / MANUAL).write_text("# Manual\n\nNo requests here.\n", encoding="utf-8")
    with pytest.raises(ManualError):
        agent_input(tmp_path)


# --- properties --------------------------------------------------------------------------------

# Ids and texts never hold digits, `z` or `Z`, so the markers below cannot occur in them.
ids = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYabcdefghijklmnopqrstuvwxy", min_size=1, max_size=6)
texts = st.from_regex(r"[A-Ya-y]([A-Ya-y ]{0,18}[A-Ya-y])?", fullmatch=True)
installations = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12)
rows = st.lists(st.tuples(ids, texts), min_size=1, max_size=8)


def write_manual(root, requests, with_markers=False):
    lines = ["# Manual", "", "## Requests from operations", "",
             "| Request id | Service id | Signal type | Sampling | Request |", "|---|---|---|---|---|"]
    for i, (rid, text) in enumerate(requests):
        service, kind, sampling = ("media", "latency", "10 s")
        if with_markers:
            service, kind, sampling = f"ZZsvc{i}", f"ZZtype{i}", f"98765{i} s"
        lines.append(f"| `{rid}` | `{service}` | {kind} | {sampling} | {text} |")
    lines += ["", "## Next section", ""]
    path = root / MANUAL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    return tmp_path_factory.mktemp("manual")


# Feature: writer-agent, Property 1: Agent input has the fixed shape
@settings(max_examples=100, deadline=None)
@given(requests=rows, installation=installations)
def test_property_shape(workdir, requests, installation):
    write_manual(workdir, requests)
    expected = "\n".join([f"Installation: {installation}", "Requests:"] + [f"{r}: {t}" for r, t in requests])
    assert agent_input(workdir, installation) == expected


# Feature: writer-agent, Property 2: Agent input hides everything but the request texts
@settings(max_examples=100, deadline=None)
@given(requests=rows)
def test_property_hides_other_columns(workdir, requests):
    write_manual(workdir, requests, with_markers=True)
    result = agent_input(workdir)
    for marker in ("ZZ", "98765", "svc", "type"):
        assert marker not in result
