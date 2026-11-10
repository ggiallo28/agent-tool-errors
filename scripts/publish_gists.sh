#!/usr/bin/env bash
# Publish gists/*.md as public GitHub gists, or update the ones already published.
# Run it yourself from any directory, after reviewing gists/. Needs gh, logged in.
# gists/index.json maps each file name to its gist URL.
set -euo pipefail
cd "$(dirname "$0")/.."

INDEX=gists/index.json
[ -f "$INDEX" ] || echo '{}' > "$INDEX"

shopt -s nullglob
files=(gists/*.md)
if [ ${#files[@]} -eq 0 ]; then
  echo "No gists/*.md to publish. Run scripts/make_gists.py first." >&2
  exit 1
fi

index_get() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$INDEX" "$1"; }
index_set() {
  python3 - "$INDEX" "$1" "$2" <<'PY'
import json, sys
path, name, url = sys.argv[1:]
data = json.load(open(path))
data[name] = url
with open(path, "w") as handle:
    json.dump(dict(sorted(data.items())), handle, indent=2)
    handle.write("\n")
PY
}

for file in "${files[@]}"; do
  name=$(basename "$file")
  url=$(index_get "$name")
  if [ -z "$url" ]; then
    url=$(gh gist create --public "$file" | tail -n 1)
    echo "Created $name: $url"
  else
    gh gist edit "${url##*/}" --filename "$name" "$file"
    echo "Updated $name: $url"
  fi
  index_set "$name" "$url"   # written after each gist, so a later failure loses no URL
done
