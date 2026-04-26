#!/usr/bin/env bash
# drift-detect.sh — Detect drift across all deployed ACE Agent stacks for a given ENV.
#
# Usage: drift-detect.sh <env> <region> <profile> <app-prefix>
#
# Exit codes:
#   0 — no drift detected on any stack
#   1 — drift detected on one or more stacks (or detection failed)

set -euo pipefail

ENV="${1:?ENV is required}"
REGION="${2:?REGION is required}"
PROFILE="${3:?PROFILE is required}"
APP_PREFIX="${4:?APP_PREFIX is required}"

AWS="aws --region ${REGION} --profile ${PROFILE}"

# Ordered list of stack name suffixes (foundation → platform → agents)
FOUNDATION_STACKS=(networking identity data storage)
PLATFORM_STACKS=(knowledge guardrails memory gateway observability)

echo "==> Drift detection for ENV=${ENV} in ${REGION}"
echo ""

DRIFT_FOUND=0

detect_stack_drift() {
    local stack_name="$1"

    # Check the stack exists first
    if ! ${AWS} cloudformation describe-stacks \
            --stack-name "${stack_name}" \
            --query 'Stacks[0].StackStatus' \
            --output text 2>/dev/null | grep -q 'COMPLETE'; then
        echo "  [SKIP] ${stack_name} — not deployed or not in a stable state"
        return 0
    fi

    echo "  [CHECK] ${stack_name}"

    # Initiate drift detection
    local detection_id
    detection_id=$(${AWS} cloudformation detect-stack-drift \
        --stack-name "${stack_name}" \
        --query 'StackDriftDetectionId' \
        --output text)

    # Poll until detection completes (max 60s)
    local status="DETECTION_IN_PROGRESS"
    local attempts=0
    while [ "${status}" = "DETECTION_IN_PROGRESS" ] && [ "${attempts}" -lt 30 ]; do
        sleep 2
        status=$(${AWS} cloudformation describe-stack-drift-detection-status \
            --stack-drift-detection-id "${detection_id}" \
            --query 'DetectionStatus' \
            --output text)
        attempts=$((attempts + 1))
    done

    if [ "${status}" != "DETECTION_COMPLETE" ]; then
        echo "  [WARN]  ${stack_name} — drift detection did not complete (status: ${status})"
        return 0
    fi

    local drift_status
    drift_status=$(${AWS} cloudformation describe-stack-drift-detection-status \
        --stack-drift-detection-id "${detection_id}" \
        --query 'StackDriftStatus' \
        --output text)

    if [ "${drift_status}" = "DRIFTED" ]; then
        echo "  [DRIFT] ${stack_name} — DRIFTED"
        # Show drifted resources
        ${AWS} cloudformation describe-stack-resource-drifts \
            --stack-name "${stack_name}" \
            --stack-resource-drift-status-filters MODIFIED DELETED \
            --query 'StackResourceDrifts[*].{LogicalId:LogicalResourceId,Type:ResourceType,Status:StackResourceDriftStatus}' \
            --output table 2>/dev/null || true
        DRIFT_FOUND=1
    else
        echo "  [OK]    ${stack_name} — ${drift_status}"
    fi
}

echo "--- Foundation stacks ---"
for stack in "${FOUNDATION_STACKS[@]}"; do
    detect_stack_drift "${APP_PREFIX}-foundation-${stack}-${ENV}"
done

echo ""
echo "--- Platform stacks ---"
for stack in "${PLATFORM_STACKS[@]}"; do
    detect_stack_drift "${APP_PREFIX}-platform-${stack}-${ENV}"
done

echo ""
echo "--- Agent stacks ---"
# Discover deployed agent stacks by listing stacks with the app prefix
agent_stacks=$(${AWS} cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE \
    --query "StackSummaries[?starts_with(StackName, '${APP_PREFIX}-application-agents-') && ends_with(StackName, '-${ENV}')].StackName" \
    --output text 2>/dev/null || true)

if [ -z "${agent_stacks}" ]; then
    echo "  [SKIP] No agent stacks found for ENV=${ENV}"
else
    for stack in ${agent_stacks}; do
        detect_stack_drift "${stack}"
    done
fi

echo ""
if [ "${DRIFT_FOUND}" -eq 1 ]; then
    echo "==> RESULT: Drift detected on one or more stacks. Review the output above."
    exit 1
else
    echo "==> RESULT: No drift detected across all stacks for ENV=${ENV}."
    exit 0
fi
