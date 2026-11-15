# Source this file, do not run it: source scripts/env.sh
# Exports the stack outputs the scripts need to reach Aurora through the RDS Data API.
# Reads output values (ARNs) only, never a secret value. Prints the cluster ARN and nothing else.
STACK="${STACK:-agent-tool-errors}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

_opsmem_output() {
  local value
  value="$(aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text)" || return 1
  if [ -z "$value" ] || [ "$value" = "None" ]; then
    echo "Missing stack output: $1" >&2
    return 1
  fi
  printf '%s\n' "$value"
}

CLUSTER_ARN="$(_opsmem_output ClusterArn)" || return 1
ADMIN_SECRET_ARN="$(_opsmem_output AdminSecretArn)" || return 1
AGENT_WRITER_SECRET_ARN="$(_opsmem_output AgentWriterSecretArn)" || return 1
APPROVER_SECRET_ARN="$(_opsmem_output ApproverSecretArn)" || return 1
export CLUSTER_ARN ADMIN_SECRET_ARN AGENT_WRITER_SECRET_ARN APPROVER_SECRET_ARN
unset -f _opsmem_output

echo "$CLUSTER_ARN"
