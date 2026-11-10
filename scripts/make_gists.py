"""Write the gists of a directory of run files into gists/.

    uv run scripts/make_gists.py runs/<date>

Generated only from the run files, models.json, agent_input and SYSTEM_PROMPT. No clock: the
date is the UTC date of the earliest run, so the same inputs always give the same files.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opsmem import evaluation, manual  # noqa: E402
from opsmem.writer import SYSTEM_PROMPT  # noqa: E402

INSTALLATION_ID = "install-07"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate the gists from a directory of run files.")
    parser.add_argument("run_dir", type=Path, help="directory of run files, for example runs/2026-11-10")
    return parser.parse_args(argv)


def main(argv=None, *, catalog_path=None, root=None, gists_dir=None, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    root = Path(root) if root is not None else ROOT
    gists_dir = Path(gists_dir) if gists_dir is not None else root / "gists"
    args = parse_args(argv)
    runs = evaluation.load_runs(args.run_dir) if args.run_dir.is_dir() else []
    if not runs:
        print(f"No run files in {args.run_dir}", file=stderr)
        return 1
    commits = sorted({str(run.get("commit")) for run in runs})
    if len(commits) != 1:
        print("The run files hold different commits:", file=stderr)
        for commit in commits:
            print(f"- {commit}", file=stderr)
        return 1
    catalog = evaluation.load_catalog(catalog_path or root / "models.json")
    date = min(str(run.get("started_at", "")) for run in runs)[:10]
    gists = evaluation.render_gists(runs, catalog, manual.agent_input(root, INSTALLATION_ID), SYSTEM_PROMPT, date)
    gists_dir.mkdir(parents=True, exist_ok=True)
    for name in evaluation.GIST_FILES:
        path = gists_dir / name
        if name in gists:
            path.write_text(gists[name], encoding="utf-8")
            print(f"Wrote {path}", file=stdout)
        else:
            if path.exists():
                path.unlink()  # a gist the data no longer supports must not stay behind
            print(f"Skipped {name}: the run files do not support it.", file=stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
