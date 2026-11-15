#!/usr/bin/env bash
# Delete the stack template.yaml created: cluster, writer instance and the two role secrets.
# Run it yourself. It asks no confirmation.
set -euo pipefail
STACK="${STACK:-agent-tool-errors}"
sam delete --stack-name "$STACK" --no-prompts
echo "No final snapshot is kept: the database content is gone."
echo "Secrets Manager keeps deleted secrets for a recovery window before removing them."
