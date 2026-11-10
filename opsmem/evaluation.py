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
