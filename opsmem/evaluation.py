"""Pure core of the model evaluation: catalog, cost and dirty-tree helpers.

No I/O except reading the catalog JSON file from a given path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

PRICE_NOTE = (
    "US cross-region inference profiles can be billed slightly higher "
    "than the list price."
)

# Same limit as the writer (opsmem.writer.MAX_TOOL_CALLS).
MAX_TOOL_CALLS = 40

# Per-call token budget used only for the Cost_Upper_Bound. Each tool call
# re-sends the system prompt, the agent input and the conversation so far, so
# the input side is budgeted at 4,000 tokens per call; the model answers with
# one short tool call, budgeted at 400 output tokens. These are deliberately
# generous round numbers: the bound is a ceiling shown before any model call,
# not a prediction.
TOKENS_IN_PER_CALL = 4_000
TOKENS_OUT_PER_CALL = 400

# Number of requests the agent must save for a run to count as a full save.
FULL_SAVE = 6

CLOSING_LINE = (
    "Companion to the article *Predictability, not eloquence* "
    "on AWS Builder Center."
)

_MILLION = Decimal(1_000_000)
_FOUR_DECIMALS = Decimal("0.0001")


@dataclass(frozen=True)
class ModelEntry:
    label: str
    name: str
    model_id: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    price_source: str


def load_catalog(path: Path) -> list[ModelEntry]:
    """Read the Model_Catalog; prices become exact Decimals."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        ModelEntry(
            label=item["label"],
            name=item["name"],
            model_id=item["model_id"],
            input_usd_per_million=Decimal(str(item["input_usd_per_million"])),
            output_usd_per_million=Decimal(str(item["output_usd_per_million"])),
            price_source=item["price_source"],
        )
        for item in data
    ]


def cost_usd(input_tokens: int, output_tokens: int, entry: ModelEntry) -> Decimal:
    """Unrounded cost in USD."""
    return (
        Decimal(input_tokens) * entry.input_usd_per_million
        + Decimal(output_tokens) * entry.output_usd_per_million
    ) / _MILLION


def format_cost(value: Decimal) -> str:
    """Format as `$0.0022`: 4 decimals, ROUND_HALF_UP."""
    return "$" + str(value.quantize(_FOUR_DECIMALS, rounding=ROUND_HALF_UP))


def cost_upper_bound(entries: list[ModelEntry]) -> Decimal:
    """Maximum cost of a run of every entry: MAX_TOOL_CALLS calls each."""
    return sum(
        (
            MAX_TOOL_CALLS
            * (
                TOKENS_IN_PER_CALL * e.input_usd_per_million
                + TOKENS_OUT_PER_CALL * e.output_usd_per_million
            )
            / _MILLION
            for e in entries
        ),
        Decimal(0),
    )


def is_dirty(porcelain: str) -> bool:
    """True when any non-empty line of `git status --porcelain` is not untracked."""
    return any(
        line and not line.startswith("?? ") for line in porcelain.splitlines()
    )


# --- Run analysis ---------------------------------------------------------------------------

SAVED_PREFIX = "Saved as draft"
REJECTED_PREFIX = "REJECTED"
STOPPED_PREFIX = "STOPPED"

REPOSITORY_URL = "https://github.com/ggiallo28/agent-tool-errors"
TABLE_HEADER = "| Model | Saved | Tool calls | Rejections | Tokens in / out | Cost | Escalated |"
TABLE_RULE = "|---|---|---|---|---|---|---|"
ROWS_HEADER = "| Request | Service | Field | Type | Unit | Sampling (s) |"
ROWS_RULE = "|---|---|---|---|---|---|"

GIST_LEARNS = "agent-learns-from-rejections.md"
GIST_MODELS = "five-models.md"
GIST_FAIL_SAFE = "small-models-fail-safe.md"
GIST_FILES = (GIST_LEARNS, GIST_MODELS, GIST_FAIL_SAFE)


def _results(trace) -> list[str]:
    return [str(entry.get("result", "")) for entry in trace or []]


def is_failed(run: dict) -> bool:
    """A Failed_Run holds the error text of a model that did not start, and no trace."""
    return "error" in run and "trace" not in run


def count_saved(trace) -> int:
    return sum(1 for r in _results(trace) if r.startswith(SAVED_PREFIX))


def count_rejections(trace) -> int:
    """Rejection_Entries only: a STOPPED reply is not a rejection."""
    return sum(1 for r in _results(trace) if r.startswith(REJECTED_PREFIX))


def ended_stopped(trace) -> bool:
    results = _results(trace)
    return bool(results) and results[-1].startswith(STOPPED_PREFIX)


def saved_rows(trace) -> list[tuple]:
    """(request, service, field, type, unit, sampling) of each Saved_Entry, sorted by request."""
    rows = []
    for entry in trace or []:
        if str(entry.get("result", "")).startswith(SAVED_PREFIX):
            call = entry.get("call", {})
            rows.append(tuple(str(call.get(key, "")) for key in (
                "request_id", "service_id", "source_field", "signal_type", "unit", "sample_seconds")))
    return sorted(rows)


def load_runs(directory: Path) -> list[dict]:
    """Every Run_File of a directory, sorted by file name, with `_label` taken from the file stem."""
    runs = []
    for path in sorted(Path(directory).glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        run["_label"] = path.stem
        runs.append(run)
    return runs


def run_label(run: dict) -> str:
    return str(run.get("label") or run.get("_label"))


def entry_for(run: dict, catalog: list[ModelEntry]) -> ModelEntry:
    label = run_label(run)
    for entry in catalog:
        if entry.label == label:
            return entry
    raise ValueError(f"model label not in the catalog: {label}")


def run_cost(run: dict, entry: ModelEntry) -> Decimal:
    if is_failed(run):
        return Decimal(0)
    return cost_usd(int(run.get("input_tokens", 0)), int(run.get("output_tokens", 0)), entry)


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def row_for(run: dict, entry: ModelEntry) -> list[str]:
    """One Results_Table row: Model, Saved, Tool calls, Rejections, Tokens in / out, Cost, Escalated."""
    if is_failed(run):
        return [entry.name, f"0 of {FULL_SAVE}", "0", "0", "0 / 0", format_cost(Decimal(0)), _cell(run["error"])]
    trace = run.get("trace", [])
    return [
        entry.name,
        f"{count_saved(trace)} of {FULL_SAVE}",
        str(int(run.get("tool_calls", 0))),
        str(count_rejections(trace)),
        f"{int(run.get('input_tokens', 0)):,} / {int(run.get('output_tokens', 0)):,}",
        format_cost(run_cost(run, entry)),
        "yes" if ended_stopped(trace) else "no",
    ]


def _ordered(runs, catalog):
    pairs = [(run, entry_for(run, catalog)) for run in runs]
    return sorted(pairs, key=lambda p: (-run_cost(p[0], p[1]), p[1].label))


def render_table(runs, catalog) -> str:
    """The Results_Table, ordered by cost descending then label, with the price note below it."""
    lines = [TABLE_HEADER, TABLE_RULE]
    lines += ["| " + " | ".join(row_for(run, entry)) + " |" for run, entry in _ordered(runs, catalog)]
    return "\n".join(lines + ["", PRICE_NOTE]) + "\n"


def full_save_runs(runs) -> list[dict]:
    return [r for r in runs if not is_failed(r) and count_saved(r.get("trace", [])) == FULL_SAVE]


def identical_rows_statement(runs) -> str:
    """Whether every Full_Save_Model saved the same rows (compared after sorting by request)."""
    full = full_save_runs(runs)
    if not full:
        return f"No model saved all {FULL_SAVE} configurations."
    if len(full) == 1:
        return f"Only one model saved all {FULL_SAVE} configurations, so there is nothing to compare."
    same = len({tuple(saved_rows(r["trace"])) for r in full}) == 1
    verdict = "identical rows" if same else "different rows"
    return f"The {len(full)} models that saved all {FULL_SAVE} configurations saved {verdict}."


def render_rows(rows) -> str:
    lines = [ROWS_HEADER, ROWS_RULE] + ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


# --- Gists ----------------------------------------------------------------------------------

def summary_line(run: dict) -> str:
    """The last line printed by scripts/run_writer.py for a run."""
    return (f"run={run.get('run_id', run_label(run))} calls={run.get('tool_calls')} "
            f"follow_ups={run.get('follow_ups')} escalated={run.get('escalated')} "
            f"input_tokens={run.get('input_tokens')} output_tokens={run.get('output_tokens')}")


def raw_trace(run: dict) -> str:
    """One unedited JSON line per tool call, as scripts/run_writer.py prints them."""
    return "\n".join(json.dumps(entry) for entry in run.get("trace", []))


def _trace_block(run: dict) -> str:
    """The raw trace followed by the summary line; no empty line when the trace is empty."""
    return "\n".join(part for part in (raw_trace(run), summary_line(run)) if part)


def _fence(text: str, lang: str = "text") -> str:
    return f"```{lang}\n{text}\n```"


def _header(title: str, intro: str, commit: str, date: str, agent_input_text: str, system_prompt: str) -> list[str]:
    setup = (f"Setup: [agent-tool-errors]({REPOSITORY_URL}) at commit [`{commit}`]({REPOSITORY_URL}/commit/{commit}), "
             f"Strands Agents, Amazon Bedrock in `us-east-1`, local PostgreSQL 16 in Docker, {date}. "
             "The installation is fictional.")
    return [f"# {title}", "", intro, "", setup, "", "The agent receives only this input:", "",
            _fence(agent_input_text), "", "and this system prompt:", "", _fence(system_prompt), ""]


def _finish(lines: list[str]) -> str:
    return "\n".join(lines + ["", CLOSING_LINE]) + "\n"


def _number_word(n: int) -> str:
    words = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]
    return words[n] if 0 <= n < len(words) else str(n)


def render_gists(runs, catalog, agent_input_text: str, system_prompt: str, date: str) -> dict[str, str]:
    """The Gist_Files, from the Run_Files only. Which model goes in which gist is read from the data."""
    commits = sorted({str(r.get("commit")) for r in runs})
    if len(commits) != 1:
        raise ValueError(f"run files hold different commits: {', '.join(commits)}")
    commit = commits[0]
    head = lambda title, intro: _header(title, intro, commit, date, agent_input_text, system_prompt)  # noqa: E731
    gists: dict[str, str] = {}

    full = full_save_runs(runs)
    if full:
        run = min(full, key=lambda r: (run_cost(r, entry_for(r, catalog)), entry_for(r, catalog).label))
        entry = entry_for(run, catalog)
        trace = run["trace"]
        intro = (f"{entry.name} on Amazon Bedrock gets the requests in plain language and no schema. "
                 f"Every field name, unit, service and sampling interval reaches it through PostgreSQL "
                 f"rejections, and it saved all {FULL_SAVE} configurations after {count_rejections(trace)} "
                 f"rejections in {run.get('tool_calls')} tool calls.")
        lines = head(f"{entry.name} learns a schema from database rejections", intro)
        lines += ["## Raw trace", "", "One JSON line per tool call, unedited: UTC timestamp, the call, "
                  "what the agent got back, the raw database message.", "",
                  _fence(_trace_block(run)), "",
                  "## Rows the database kept", "", render_rows(saved_rows(trace)).rstrip("\n")]
        gists[GIST_LEARNS] = _finish(lines)

    finished = [r for r in runs if not is_failed(r)]
    intro = (f"The same requests and the same database rules, {len(runs)} models. "
             f"{_number_word(len(full))} of them saved all {FULL_SAVE} configurations. "
             f"{identical_rows_statement(runs)}")
    lines = head(f"{_number_word(len(runs))} Bedrock models, one database", intro)
    lines += ["## Results", "", render_table(runs, catalog).rstrip("\n"), "", "## Rows kept", ""]
    for run, entry in _ordered(finished, catalog):
        rows = saved_rows(run.get("trace", []))
        lines += [f"### {entry.name}", "", render_rows(rows).rstrip("\n") if rows else "No rows kept.", ""]
    lines += [identical_rows_statement(runs)]
    gists[GIST_MODELS] = _finish(lines)

    partial = [r for r in finished if count_saved(r.get("trace", [])) < FULL_SAVE]
    if partial:
        intro = (f"{_number_word(len(partial))} of the {len(runs)} models saved fewer than {FULL_SAVE} "
                 "configurations. For each one: the raw trace, why the run stopped, and the rows kept, "
                 "counted from the trace.")
        lines = head(f"Models that did not save all {FULL_SAVE} configurations", intro)
        for run, entry in _ordered(partial, catalog):
            trace = run.get("trace", [])
            lines += [f"## {entry.name}", "", f"Escalation: {run.get('escalated') or 'none'}.", "",
                      f"Rows kept: {count_saved(trace)} of {FULL_SAVE}, counted from the trace.", "",
                      _fence(_trace_block(run)), ""]
        gists[GIST_FAIL_SAFE] = _finish(lines)
    return gists
