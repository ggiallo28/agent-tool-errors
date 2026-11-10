"""Print the Results_Table of a directory of run files.

    uv run scripts/summarize_runs.py runs/<date> [--rows]

Every number comes from the run files and models.json. The output is deterministic.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opsmem import evaluation  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Summarize a directory of run files.")
    parser.add_argument("run_dir", type=Path, help="directory of run files, for example runs/2026-11-10")
    parser.add_argument("--rows", action="store_true", help="also print the rows saved by each model that saved all six")
    return parser.parse_args(argv)


def main(argv=None, *, catalog_path=None, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = parse_args(argv)
    runs = evaluation.load_runs(args.run_dir) if args.run_dir.is_dir() else []
    if not runs:
        print(f"No run files in {args.run_dir}", file=stderr)
        return 1
    catalog = evaluation.load_catalog(catalog_path or ROOT / "models.json")
    stdout.write(evaluation.render_table(runs, catalog))
    if args.rows:
        for run in sorted(evaluation.full_save_runs(runs), key=evaluation.run_label):
            entry = evaluation.entry_for(run, catalog)
            stdout.write(f"\n### {entry.name}\n\n")
            stdout.write(evaluation.render_rows(evaluation.saved_rows(run["trace"])))
        stdout.write("\n" + evaluation.identical_rows_statement(runs) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
