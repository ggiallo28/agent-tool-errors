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
    """Every Run_File of a directory, sorted by file name, with `_label` (file stem) and `_file` (file name)."""
    runs = []
    for path in sorted(Path(directory).glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        run["_label"] = path.stem
        run["_file"] = path.name
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


# --- Repeated runs and modes ----------------------------------------------------------------

MODES = ("raw", "instructive")
DEFAULT_MODE = "instructive"
# In mode `raw` the tool returns "ERROR: " and the database message, with no REJECTED prefix.
RAW_REJECTED_PREFIX = "ERROR: "

REPEATS_HEADER = ("| Model | Mode | Runs | Saved 6 of 6 | Same rows as the first complete run "
                  "| Tool calls (min to max) | Rejections (min to max) |")
REPEATS_RULE = "|---|---|---|---|---|---|---|"
REPEATS_NOTE = ("The signal name is not compared: two runs have the same rows when request, service, "
                "field, type, unit and sampling are equal.")
DIFFERING_TITLE = "Differing rows:"
_ROW_FIELDS = ("service", "field", "type", "unit", "sampling")


def is_repeated(run: dict) -> bool:
    """A Repeated_Run holds `repeat` and `repeat_count`. The file name is never read."""
    return "repeat" in run and "repeat_count" in run


def run_mode(run: dict) -> str:
    """The Mode of a run; a Run_File without `mode` is instructive."""
    return str(run.get("mode", DEFAULT_MODE))


def results_runs(runs) -> list[dict]:
    """The Single_Runs with Mode instructive: the only runs of the Results_Table and of the gists."""
    return [r for r in runs if not is_repeated(r) and run_mode(r) == DEFAULT_MODE]


def base_name(label: str, mode: str) -> str:
    return f"{label}-raw" if mode == "raw" else label


def run_file_name(label: str, mode: str, repeat: int, repeat_count: int) -> str:
    """`<base>.json` for a single run, `<base>-NN.json` for a repetition."""
    base = base_name(label, mode)
    return f"{base}.json" if repeat_count == 1 else f"{base}-{repeat:02d}.json"


def make_run_id(label: str, mode: str, repeat: int, unix_seconds: int) -> str:
    """Unique inside one command whatever the clock: label, Mode and repetition number."""
    return f"eval-{label}-{mode}-{repeat:02d}-{unix_seconds}"


def is_complete(run: dict) -> bool:
    return not is_failed(run) and count_saved(run.get("trace", [])) == FULL_SAVE


def row_keys(run: dict) -> dict[str, tuple]:
    """request -> (service, field, type, unit, sampling). The signal name is not part of it."""
    return {row[0]: row[1:] for row in saved_rows(run.get("trace", []))}


def count_rejections_any_mode(trace) -> int:
    """Rejection_Entries of a run in either Mode. A STOPPED reply is not a rejection."""
    return sum(1 for r in _results(trace) if r.startswith((REJECTED_PREFIX, RAW_REJECTED_PREFIX)))


def span(values: list[int]) -> str:
    """`none`, a single number, or `min to max`."""
    if not values:
        return "none"
    low, high = min(values), max(values)
    return str(low) if low == high else f"{low} to {high}"


def _file_of(run: dict) -> str:
    return str(run.get("_file", ""))


def repeat_groups(runs, catalog) -> list[tuple[ModelEntry, str, list[dict]]]:
    """Runs grouped by (label, Mode), for the groups with a Repeated_Run or Mode raw.

    Each group holds every run of that label and Mode, sorted by file name. Groups are ordered
    by catalog position, then instructive before raw.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        groups.setdefault((entry_for(run, catalog).label, run_mode(run)), []).append(run)
    position = {entry.label: i for i, entry in enumerate(catalog)}
    by_label = {entry.label: entry for entry in catalog}
    kept = [(label, mode, sorted(group, key=_file_of)) for (label, mode), group in groups.items()
            if mode == "raw" or any(is_repeated(r) for r in group)]
    kept.sort(key=lambda g: (position[g[0]], 0 if g[1] == DEFAULT_MODE else 1, g[1]))
    return [(by_label[label], mode, group) for label, mode, group in kept]


def _first_complete(runs) -> dict | None:
    complete = [r for r in runs if is_complete(r)]
    return complete[0] if complete else None


def repeats_row(entry: ModelEntry, mode: str, runs) -> list[str]:
    """One Repeats_Table line: Model, Mode, Runs, Saved 6 of 6, Same rows, Tool calls, Rejections."""
    complete = [r for r in runs if is_complete(r)]
    started = [r for r in runs if not is_failed(r)]
    if complete:
        first = row_keys(complete[0])
        same = f"{sum(1 for r in complete if row_keys(r) == first)} of {len(complete)}"
    else:
        same = "none"
    return [
        entry.name,
        mode,
        str(len(runs)),
        f"{len(complete)} of {len(runs)}",
        same,
        span([int(r.get("tool_calls", 0)) for r in started]),
        span([count_rejections_any_mode(r.get("trace", [])) for r in started]),
    ]


def _row_text(key: tuple | None) -> str:
    if key is None:
        return "not saved"
    return ", ".join(f"{name} {_cell(value)}" for name, value in zip(_ROW_FIELDS, key))


def differing_rows(entry: ModelEntry, mode: str, runs) -> list[str]:
    """One line per complete run and request whose Row_Key differs from the first complete run."""
    first_run = _first_complete(runs)
    if first_run is None:
        return []
    first = row_keys(first_run)
    lines = []
    for run in runs:
        if run is first_run or not is_complete(run):
            continue
        keys = row_keys(run)
        for request in sorted(set(first) | set(keys)):
            if keys.get(request) != first.get(request):
                lines.append(f"- {entry.name}, {mode}, {_file_of(run)}, {request}: {_row_text(keys.get(request))} "
                             f"(first complete run {_file_of(first_run)}: {_row_text(first.get(request))})")
    return lines


def render_repeats(runs, catalog) -> str:
    """The Repeats_Table, its note, and the Differing_Rows_Listing when complete runs differ."""
    groups = repeat_groups(runs, catalog)
    lines = [REPEATS_HEADER, REPEATS_RULE]
    lines += ["| " + " | ".join(repeats_row(entry, mode, group)) + " |" for entry, mode, group in groups]
    lines += ["", REPEATS_NOTE]
    differing = [line for entry, mode, group in groups for line in differing_rows(entry, mode, group)]
    if differing:
        lines += ["", DIFFERING_TITLE, *differing]
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
