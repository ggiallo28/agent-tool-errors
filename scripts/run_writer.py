"""Run the writer agent once on install-07, print the trace and a summary line, save the result.

    uv run scripts/run_writer.py --model <bedrock model id> [--mode raw|instructive]

Local mode (OPSMEM_LOCAL_PG set) uses the local Docker database. Otherwise Aurora is used.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opsmem import db, manual  # noqa: E402
from opsmem.writer import RunContext, run_writer  # noqa: E402

INSTALLATION_ID = "install-07"
REQUIRED = ["CLUSTER_ARN", "AGENT_WRITER_SECRET_ARN", "AWS_REGION"]
MODES = ("raw", "instructive")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the writer agent once on install-07.")
    parser.add_argument("--model", required=True, help="Bedrock model id")
    parser.add_argument("--mode", choices=MODES, default="instructive", help="rejection text: raw or instructive")
    return parser.parse_args(argv)


def main(argv=None, *, results_dir: Path | None = None) -> int:
    args = parse_args(argv)
    db.check_config(REQUIRED)
    run_id = f"single-{args.mode}-{int(time.time())}"
    ctx = RunContext(run_id, INSTALLATION_ID, args.model, args.mode, db.connect("agent_writer"))
    result = run_writer(ctx, manual.agent_input(ROOT, INSTALLATION_ID))
    for entry in result["trace"]:
        print(json.dumps(entry))
    print(f"run={run_id} calls={result['tool_calls']} follow_ups={result['follow_ups']} "
          f"escalated={result['escalated']} input_tokens={result['input_tokens']} "
          f"output_tokens={result['output_tokens']}")
    folder = Path(results_dir) if results_dir is not None else ROOT / "results"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{run_id}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
