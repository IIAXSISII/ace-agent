#!/usr/bin/env bash
# deploy.sh — Deploys all CloudFormation tiers in dependency order.
# Usage: ./deploy.sh <ENV> [REGION] [PROFILE]
#   ENV     — required; matches a parameters/<ENV>.json file (e.g. local, production)
#   REGION  — optional; defaults to AWS_DEFAULT_REGION or us-east-1
#   PROFILE — optional; defaults to AWS_PROFILE or default
set -euo pipefail

ENV=${1:?Usage: deploy.sh <ENV> [REGION] [PROFILE]}
REGION=${2:-${AWS_DEFAULT_REGION:-us-east-1}}
PROFILE=${3:-${AWS_PROFILE:-default}}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CF_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Deploying all tiers for ENV=${ENV} REGION=${REGION} PROFILE=${PROFILE}"

make -f "${CF_DIR}/Makefile" deploy-foundation ENV="${ENV}" REGION="${REGION}" PROFILE="${PROFILE}"
make -f "${CF_DIR}/Makefile" deploy-platform   ENV="${ENV}" REGION="${REGION}" PROFILE="${PROFILE}"
make -f "${CF_DIR}/Makefile" deploy-agents     ENV="${ENV}" REGION="${REGION}" PROFILE="${PROFILE}"

echo "==> All tiers deployed successfully for ENV=${ENV}."
