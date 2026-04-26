#!/usr/bin/env bash
# destroy.sh — Tear down all ACE Agent stacks in reverse dependency order.
#              agents → platform → foundation
#
# Usage: destroy.sh <env> <region> <profile> <app-prefix>
#
# NOTE: Confirmation is handled by the Makefile before this script is called.

set -euo pipefail

ENV="${1:?ENV is required}"
REGION="${2:?REGION is required}"
PROFILE="${3:?PROFILE is required}"
APP_PREFIX="${4:?APP_PREFIX is required}"

AWS="aws --region ${REGION} --profile ${PROFILE}"

delete_stack() {
    local stack_name="$1"

    # Check the stack exists
    local stack_status
    stack_status=$(${AWS} cloudformation describe-stacks \
        --stack-name "${stack_name}" \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null || echo "DOES_NOT_EXIST")

    if [ "${stack_status}" = "DOES_NOT_EXIST" ] || [ -z "${stack_status}" ]; then
        echo "  [SKIP] ${stack_name} — not found"
        return 0
    fi

    echo "  [DELETE] ${stack_name} (current status: ${stack_status})"
    ${AWS} cloudformation delete-stack --stack-name "${stack_name}"

    echo "  [WAIT]   ${stack_name} — waiting for deletion..."
    if ! ${AWS} cloudformation wait stack-delete-complete --stack-name "${stack_name}"; then
        echo "  [ERROR]  ${stack_name} — deletion failed. Check the CloudFormation console."
        # Print failure events
        ${AWS} cloudformation describe-stack-events \
            --stack-name "${stack_name}" \
            --query 'StackEvents[?ResourceStatus==`DELETE_FAILED`].{Resource:LogicalResourceId,Reason:ResourceStatusReason}' \
            --output table 2>/dev/null || true
        return 1
    fi

    echo "  [DONE]   ${stack_name} — deleted."
}

echo "==> Destroying all ${APP_PREFIX} stacks for ENV=${ENV} in ${REGION}"
echo "    Order: agents → platform → foundation"
echo ""

# ── 1. Agent stacks (discover dynamically) ───────────────────────────────────
echo "--- Deleting agent stacks ---"
agent_stacks=$(${AWS} cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE ROLLBACK_COMPLETE \
    --query "StackSummaries[?starts_with(StackName, '${APP_PREFIX}-application-agents-') && ends_with(StackName, '-${ENV}')].StackName" \
    --output text 2>/dev/null || true)

if [ -z "${agent_stacks}" ]; then
    echo "  [SKIP] No agent stacks found for ENV=${ENV}"
else
    for stack in ${agent_stacks}; do
        delete_stack "${stack}"
    done
fi

# ── 2. Platform stacks (reverse order) ───────────────────────────────────────
echo ""
echo "--- Deleting platform stacks ---"
PLATFORM_STACKS_REVERSE=(observability gateway memory guardrails knowledge)
for stack in "${PLATFORM_STACKS_REVERSE[@]}"; do
    delete_stack "${APP_PREFIX}-platform-${stack}-${ENV}"
done

# ── 3. Foundation stacks (reverse order) ─────────────────────────────────────
echo ""
echo "--- Deleting foundation stacks ---"
FOUNDATION_STACKS_REVERSE=(storage data identity networking)
for stack in "${FOUNDATION_STACKS_REVERSE[@]}"; do
    delete_stack "${APP_PREFIX}-foundation-${stack}-${ENV}"
done

echo ""
echo "==> All stacks for ENV=${ENV} have been destroyed."
