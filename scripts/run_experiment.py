"""Run the writer once per model and save each result as a run file.

    uv run scripts/run_experiment.py [--models label,...] [--out runs/<date>]
                                     [--repeat N] [--mode raw|instructive] [--yes]

--repeat N runs each model N times (1 to 20) and names the files <label>-01.json to <label>-NN.json.
--mode raw returns the database message untouched and names the files <label>-raw[-NN].json.

Without --yes it only prints the models and the cost upper bound: no model is called.
With --yes it refuses to start if tracked files have uncommitted changes, so every run
file points to a commit that holds exactly the code that produced it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opsmem import db, evaluation, manual  # noqa: E402

INSTALLATION_ID = "install-07"
MODES = evaluation.MODES
MIN_REPEAT, MAX_REPEAT = 1, 20
REQUIRED = ["CLUSTER_ARN", "AGENT_WRITER_SECRET_ARN", "AWS_REGION"]


class GitError(RuntimeError):
    """A git command exited with a non-zero code."""


def real_git(root: Path):
    def git(args: list[str]) -> str:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
        if done.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
        return done.stdout
    return git


def real_run_model(entry, task: str, run_id: str, mode: str) -> dict:
    """One writer run for one model, on the agent_writer connection."""
    from opsmem.writer import RunContext, run_writer
    ctx = RunContext(run_id, INSTALLATION_ID, entry.model_id, mode, db.connect("agent_writer"))
    return run_writer(ctx, task)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def repeat_arg(text: str) -> int:
    """argparse type: a whole number from 1 to 20."""
    message = f"must be a whole number from {MIN_REPEAT} to {MAX_REPEAT}, got {text!r}"
    if not (text.isascii() and text.isdigit()):
        raise argparse.ArgumentTypeError(message)
    value = int(text)
    if not MIN_REPEAT <= value <= MAX_REPEAT:
        raise argparse.ArgumentTypeError(message)
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the writer agent on several Bedrock models.")
    parser.add_argument("--models", help="comma-separated labels from models.json (default: all)")
    parser.add_argument("--out", type=Path, help="output directory (default: runs/<UTC date>)")
    parser.add_argument("--repeat", type=repeat_arg, default=1,
                        help=f"runs per model, {MIN_REPEAT} to {MAX_REPEAT} (default: 1)")
    parser.add_argument("--mode", choices=MODES, default=evaluation.DEFAULT_MODE,
                        help="rejection text of the runs: raw or instructive (default: instructive)")
    parser.add_argument("--yes", action="store_true", help="call the models; without it nothing is called")
    return parser.parse_args(argv)


def main(argv=None, *, run_model=None, git=None, now=None, check_config=None,
         catalog_path=None, root=None, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    root = Path(root) if root is not None else ROOT
    run_model = run_model or real_run_model
    git = git or real_git(root)
    now = now or utc_now
    check_config = check_config or db.check_config

    args = parse_args(argv)
    check_config(REQUIRED)

    catalog = evaluation.load_catalog(catalog_path or root / "models.json")
    known = {e.label for e in catalog}
    wanted = [label.strip() for label in args.models.split(",") if label.strip()] if args.models else list(known)
    unknown = [label for label in wanted if label not in known]
    if unknown:
        print(f"Unknown model label: {', '.join(unknown)}", file=stderr)
        return 2
    selected = [e for e in catalog if e.label in wanted]

    print("Models:", file=stdout)
    for entry in selected:
        print(f"- {entry.name} ({entry.model_id})", file=stdout)
    repeats = f" for {args.repeat} runs of each model" if args.repeat > 1 else ""
    print(f"Cost upper bound: {evaluation.format_cost(evaluation.cost_upper_bound(selected) * args.repeat)} "
          f"({evaluation.MAX_TOOL_CALLS} tool calls per run, {evaluation.TOKENS_IN_PER_CALL:,} input and "
          f"{evaluation.TOKENS_OUT_PER_CALL:,} output tokens per call){repeats}. {evaluation.PRICE_NOTE}",
          file=stdout)
    if not args.yes:
        print("Dry run: no model was called. Add --yes to run.", file=stdout)
        return 0

    try:
        if evaluation.is_dirty(git(["status", "--porcelain"])):
            print("Uncommitted changes to tracked files: commit first, then run again.", file=stderr)
            return 1
        commit = git(["rev-parse", "HEAD"]).strip()
    except GitError as err:
        print(str(err), file=stderr)
        return 1

    out = args.out if args.out is not None else root / "runs" / now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    task = manual.agent_input(root, INSTALLATION_ID)
    for entry in selected:
        for repeat in range(1, args.repeat + 1):
            path = out / evaluation.run_file_name(entry.label, args.mode, repeat, args.repeat)
            if path.exists():
                print(f"Skipped {path}: the file already exists.", file=stdout)
                continue
            started = now()
            meta = {"model_id": entry.model_id, "label": entry.label, "mode": args.mode, "commit": commit,
                    "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "run_id": evaluation.make_run_id(entry.label, args.mode, repeat, int(started.timestamp()))}
            if args.repeat > 1:
                meta.update(repeat=repeat, repeat_count=args.repeat)
            try:
                data = {**meta, **run_model(entry, task, meta["run_id"], args.mode)}
            except Exception as err:  # a run that fails to start is recorded and the next one runs
                data = {**meta, "error": f"{type(err).__name__}: {err}"}
            try:
                with open(path, "x", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2)
            except FileExistsError:
                print(f"Skipped {path}: the file already exists.", file=stdout)
                continue
            print(f"Wrote {path}", file=stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
