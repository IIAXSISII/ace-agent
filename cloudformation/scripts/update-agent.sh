#!/usr/bin/env bash
# update-agent.sh — Fast path to deploy a single agent stack.
# Usage: ./update-agent.sh <AGENT> [ENV] [REGION] [PROFILE]
#   AGENT   — required; agent name matching stacks/application/agents/<AGENT>-agent.yaml
#   ENV     — optional; defaults to local
#   REGION  — optional; defaults to AWS_DEFAULT_REGION or us-east-1
#   PROFILE — optional; defaults to AWS_PROFILE or default
set -euo pipefail

AGENT=${1:?Usage: update-agent.sh <AGENT> [ENV] [REGION] [PROFILE]}
ENV=${2:-${ENV:-local}}
REGION=${3:-${AWS_DEFAULT_REGION:-us-east-1}}
PROFILE=${4:-${AWS_PROFILE:-default}}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CF_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Updating agent '${AGENT}' for ENV=${ENV} REGION=${REGION} PROFILE=${PROFILE}"

make -f "${CF_DIR}/Makefile" deploy-agent \
    AGENT="${AGENT}" \
    ENV="${ENV}" \
    REGION="${REGION}" \
    PROFILE="${PROFILE}"

echo "==> Agent '${AGENT}' deployed successfully."
