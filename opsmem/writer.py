"""The writer agent: proposes one collection configuration per request, as drafts.

The Database_Object held by the RunContext must be the ``agent_writer`` one: it is the role that may
insert the ten columns, move a draft to ``needs_review`` and read the catalog for the valid values.

The rejection text is never built here. ``classify``, ``valid_values`` and ``render`` of
``opsmem.errors`` are called in that order.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from strands import Agent, tool
from strands.models import BedrockModel

from opsmem import errors

SYSTEM_PROMPT = (
    "Configure one signal per request with propose_config. If a call is rejected, use the valid values "
    "in the rejection and call the tool again. Stop only when every request is saved."
)
MAX_TOOL_CALLS = 40
ESCALATE_AFTER = 3
FOLLOW_UPS = 2
MAX_FINAL_TEXT = 2000

INSERT_SQL = (
    "INSERT INTO collection_configs (run_id, installation_id, request_id, service_id, signal_name,"
    " signal_type, source_field, unit, sample_s, model_id)"
    " VALUES (:run_id, :installation_id, :request_id, :service_id, :signal_name, :signal_type,"
    " :source_field, :unit, CAST(:sample_seconds AS integer), :model_id)"
)
MOVE_SQL = (
    "UPDATE collection_configs SET status = 'needs_review' "
    "WHERE run_id = :run_id AND installation_id = :installation_id AND status = 'draft'"
)
OPEN_SQL = (
    "SELECT request_id FROM signal_requests WHERE installation_id = :installation_id "
    "AND request_id NOT IN (SELECT request_id FROM collection_configs "
    "WHERE run_id = :run_id AND installation_id = :installation_id)"
)


@dataclass
class RunContext:
    run_id: str
    installation_id: str
    model_id: str
    mode: str  # "raw" or "instructive"
    db: object  # Database_Object of the role agent_writer
    rejections: dict[tuple[str, str], int] = field(default_factory=dict)
    tool_calls: int = 0
    escalation_reason: str | None = None
    flagged: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    last_db_message: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _stop(ctx: RunContext, reason: str) -> None:
    """Stop the run. The first reason stays."""
    if ctx.escalation_reason is None:
        ctx.escalation_reason = reason


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _stopped_reply(ctx: RunContext) -> str:
    return (f"STOPPED. This run is waiting for a person ({ctx.escalation_reason}). "
            "Do not propose more configurations.")


def _propose(ctx: RunContext, call: dict) -> tuple[str, str | None]:
    ctx.tool_calls += 1
    if ctx.tool_calls > MAX_TOOL_CALLS:
        _stop(ctx, f"more than {MAX_TOOL_CALLS} tool calls")
    if ctx.escalation_reason is not None:
        return _stopped_reply(ctx), None
    try:
        ctx.db.run(INSERT_SQL, run_id=ctx.run_id, installation_id=ctx.installation_id,
                   model_id=ctx.model_id, **call)
    except ctx.db.DatabaseError as err:
        return _rejected(ctx, call, str(err)), str(err)
    return (f"Saved as draft: {call['signal_name']} <- {call['source_field']} "
            f"({call['unit']}, every {call['sample_seconds']} s). A person will review it."), None


def _rejected(ctx: RunContext, call: dict, message: str) -> str:
    ctx.last_db_message = message
    rule = errors.classify(message)
    key = (call["request_id"], rule)
    ctx.rejections[key] = ctx.rejections.get(key, 0) + 1
    if ctx.rejections[key] >= ESCALATE_AFTER:
        _stop(ctx, f"rule {rule} rejected {ESCALATE_AFTER} times")
        ctx.db.run(MOVE_SQL, run_id=ctx.run_id, installation_id=ctx.installation_id)
        return "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."
    valid: list[str] = []
    if ctx.mode == "instructive":
        proposal = {**call, "sample_s": call["sample_seconds"]}
        valid = errors.valid_values(ctx.db, rule, proposal, ctx.installation_id)
    return errors.render(rule, valid, ctx.mode, message)


def make_tools(ctx: RunContext) -> list:
    @tool
    def propose_config(request_id: str, service_id: str, signal_name: str, signal_type: str,
                       source_field: str, unit: str, sample_seconds: str) -> str:
        """Propose one signal configuration as a draft.

        Args:
            request_id: request id
            service_id: service id
            signal_name: signal name
            signal_type: signal type
            source_field: source field
            unit: unit
            sample_seconds: sampling interval in seconds
        """
        call = {"request_id": request_id, "service_id": service_id, "signal_name": signal_name,
                "signal_type": signal_type, "source_field": source_field, "unit": unit,
                "sample_seconds": sample_seconds}
        with ctx.lock:
            result, db_message = _propose(ctx, call)
            ctx.trace.append({"ts": _now(), "call": call, "result": result, "db_message": db_message})
            return result

    @tool
    def flag_for_review(reason: str) -> str:
        """Ask a person to decide something you cannot.

        Args:
            reason: what you cannot decide
        """
        with ctx.lock:
            ctx.flagged.append(reason)
        return "Noted for a person. Continue with the signals you can configure."

    return [propose_config, flag_for_review]


# --- agent and run loop ----------------------------------------------------------------------

def build_agent(ctx: RunContext):
    model = BedrockModel(model_id=ctx.model_id, region_name=os.environ["AWS_REGION"], temperature=0)
    return Agent(model=model, tools=make_tools(ctx), system_prompt=SYSTEM_PROMPT, callback_handler=None)


def _open_requests(ctx: RunContext) -> list[str]:
    rows = ctx.db.run(OPEN_SQL, installation_id=ctx.installation_id, run_id=ctx.run_id)
    return sorted(str(row[0]) for row in rows)


def _result(ctx: RunContext, result, follow_ups: int) -> dict:
    usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None) or {}
    return {
        "tool_calls": ctx.tool_calls,
        "rejections": {f"{rid}:{rule}": n for (rid, rule), n in ctx.rejections.items()},
        "follow_ups": follow_ups,
        "escalated": ctx.escalation_reason,
        "flagged": list(ctx.flagged),
        "trace": list(ctx.trace),
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "final_text": str(result)[:MAX_FINAL_TEXT],
    }


def run_writer(ctx: RunContext, task: str, agent=None) -> dict:
    agent = agent or build_agent(ctx)
    result = agent(task)
    follow_ups = 0
    while ctx.escalation_reason is None:
        open_ids = _open_requests(ctx)
        if not open_ids:
            break
        ids = ", ".join(open_ids)
        if follow_ups == FOLLOW_UPS:
            _stop(ctx, f"agent stopped with requests not configured: {ids}")
            break
        result = agent(f"Not configured yet: {ids}. Call propose_config for each.")
        follow_ups += 1
    return _result(ctx, result, follow_ups)
