"""Model evaluation core: catalog, cost and dirty-tree helpers. Offline."""
from decimal import Decimal

from opsmem import evaluation
from opsmem.evaluation import (
    ModelEntry,
    cost_upper_bound,
    format_cost,
    is_dirty,
    load_catalog,
)
from tests.helpers import ROOT

# Requirement 1, criteria 1 to 6: label, name, model_id, input, output, source.
EXPECTED = [
    ("claude-sonnet-4-6", "Claude Sonnet 4.6", "us.anthropic.claude-sonnet-4-6",
     "3.00", "15.00", "Bedrock pricing page"),
    ("claude-haiku-4-5", "Claude Haiku 4.5", "us.anthropic.claude-haiku-4-5-20251001-v1:0",
     "1.00", "5.00", "Bedrock pricing page"),
    ("nova-2-lite", "Amazon Nova 2 Lite", "us.amazon.nova-2-lite-v1:0",
     "0.33", "2.75", "AWS Price List API"),
    ("nova-micro", "Amazon Nova Micro", "us.amazon.nova-micro-v1:0",
     "0.035", "0.14", "AWS Price List API"),
    ("ministral-3-3b", "Ministral 3 3B", "mistral.ministral-3-3b-instruct",
     "0.10", "0.10", "AWS Price List API"),
]


def test_catalog_matches_requirement_1():
    got = [
        (e.label, e.name, e.model_id, e.input_usd_per_million,
         e.output_usd_per_million, e.price_source)
        for e in load_catalog(ROOT / "models.json")
    ]
    want = [(a, b, c, Decimal(d), Decimal(e), f) for a, b, c, d, e, f in EXPECTED]
    assert got == want


def test_format_cost_nova_micro_example():
    entry = next(e for e in load_catalog(ROOT / "models.json") if e.label == "nova-micro")
    value = evaluation.cost_usd(51_844, 2_454, entry)
    assert format_cost(value) == "$0.0022"


def test_is_dirty():
    assert not is_dirty("")
    assert not is_dirty("?? new_file\n?? other\n")
    assert is_dirty(" M file")
    assert is_dirty("A  file")
    assert is_dirty("?? new_file\n M file\n")


def test_cost_upper_bound_single_entry_hand_computed():
    entry = ModelEntry("x", "X", "x-id", Decimal("0.035"), Decimal("0.14"), "src")
    # 40 calls * (4,000 * 0.035 + 400 * 0.14) / 1e6 = 40 * 196 / 1e6
    assert cost_upper_bound([entry]) == Decimal("0.00784")
