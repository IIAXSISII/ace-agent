# ──────────────────────────────────────────────────────────────────────────────
# CloudFormation deployment targets
# ──────────────────────────────────────────────────────────────────────────────
# Usage:
#   make deploy-foundation ENV=production
#   make deploy-platform   ENV=production
#   make deploy-agents     ENV=production
#   make deploy-agent      AGENT=orchestrator ENV=production
#   make preview           STACK=orchestrator TIER=application/agents ENV=production
#   make drift-detect      ENV=production
#   make destroy           ENV=production

# ── Variables ─────────────────────────────────────────────────────────────────
ENV     ?= local
REGION  ?= $(or $(AWS_DEFAULT_REGION),us-east-1)
PROFILE ?= $(or $(AWS_PROFILE),default)

CF_DIR    := cloudformation
STACKS_DIR := $(CF_DIR)/stacks
PARAMS_DIR := $(CF_DIR)/parameters

APP_PREFIX := ace-agent

SHELL := /bin/bash

stack-name = $(APP_PREFIX)-$(subst /,-,$(1))-$(2)-$(ENV)

params-file = $(shell \
	if [ -f $(PARAMS_DIR)/$(1)-$(2)-$(ENV).json ]; then \
		echo $(PARAMS_DIR)/$(1)-$(2)-$(ENV).json; \
	else \
		echo $(PARAMS_DIR)/$(ENV).json; \
	fi)

TIMESTAMP := $(shell date +%Y%m%d%H%M%S)

AWS := AWS_PAGER="" aws --region $(REGION) --profile $(PROFILE)

# ── cfn-lint guard ────────────────────────────────────────────────────────────
define lint-templates
	@echo "==> cfn-lint $(1)"
	cfn-lint $(1)
endef

# ── Change-set deploy (production) ───────────────────────────────────────────
# For existing stacks: creates a change set, shows diff, executes.
# For new stacks: uses direct deploy (change sets on CREATE leave stacks stuck).
# Handles empty change sets gracefully (no changes → skip and continue).
# $(call deploy-changeset,<stack-name>,<template-file>,<params-file>)
define deploy-changeset
	$(eval CS_NAME := $(1)-cs-$(TIMESTAMP))
	@STACK_EXISTS=$$($(AWS) cloudformation describe-stacks --stack-name $(1) \
		--query 'Stacks[0].StackStatus' --output text 2>/dev/null); \
	if echo "$$STACK_EXISTS" | grep -qE "ROLLBACK_FAILED|ROLLBACK_COMPLETE|REVIEW_IN_PROGRESS"; then \
		echo "==> Stack $(1) is in $$STACK_EXISTS state — deleting before recreating"; \
		$(AWS) cloudformation delete-stack --stack-name $(1) --deletion-mode FORCE_DELETE_STACK 2>/dev/null || \
		$(AWS) cloudformation delete-stack --stack-name $(1) 2>/dev/null || true; \
		$(AWS) cloudformation wait stack-delete-complete --stack-name $(1) 2>/dev/null || true; \
		STACK_EXISTS=""; \
	fi; \
	if [ -z "$$STACK_EXISTS" ] || echo "$$STACK_EXISTS" | grep -qE "DELETE_COMPLETE"; then \
		echo "==> Stack $(1) does not exist — creating directly"; \
		$(AWS) cloudformation deploy \
			--stack-name $(1) \
			--template-file $(2) \
			--parameter-overrides file://$(3) \
			--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
			--no-fail-on-empty-changeset; \
		echo "==> Stack $(1) created successfully."; \
	else \
		echo "==> Creating change set $(CS_NAME) for stack $(1)"; \
		$(AWS) cloudformation create-change-set \
			--stack-name $(1) \
			--template-body file://$(2) \
			--parameters file://$(3) \
			--change-set-name $(CS_NAME) \
			--change-set-type UPDATE \
			--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND; \
		echo "==> Waiting for change set to be ready..."; \
		$(AWS) cloudformation wait change-set-create-complete \
			--stack-name $(1) \
			--change-set-name $(CS_NAME) 2>/dev/null || true; \
		CS_STATUS=$$($(AWS) cloudformation describe-change-set \
			--stack-name $(1) \
			--change-set-name $(CS_NAME) \
			--query 'Status' --output text 2>/dev/null); \
		if [ "$$CS_STATUS" = "FAILED" ]; then \
			echo "==> No changes detected — stack $(1) is already up to date."; \
			$(AWS) cloudformation delete-change-set \
				--stack-name $(1) \
				--change-set-name $(CS_NAME) 2>/dev/null || true; \
		else \
			echo "==> Change set diff:"; \
			$(AWS) cloudformation describe-change-set \
				--stack-name $(1) \
				--change-set-name $(CS_NAME) \
				--query 'Changes[*].{Action:ResourceChange.Action,LogicalId:ResourceChange.LogicalId,Type:ResourceChange.ResourceType,Replace:ResourceChange.Replacement}' \
				--output table; \
			echo "==> Executing change set..."; \
			$(AWS) cloudformation execute-change-set \
				--stack-name $(1) \
				--change-set-name $(CS_NAME); \
			echo "==> Waiting for stack operation to complete..."; \
			$(AWS) cloudformation wait stack-update-complete \
				--stack-name $(1); \
			echo "==> Stack $(1) deployed successfully."; \
		fi; \
	fi
endef

# ── Direct deploy (local / non-production) ───────────────────────────────────
define deploy-direct
	@echo "==> Deploying stack $(1) ($(ENV))"
	$(AWS) cloudformation deploy \
		--stack-name $(1) \
		--template-file $(2) \
		--parameter-overrides file://$(3) \
		--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
		--no-fail-on-empty-changeset
	@echo "==> Stack $(1) deployed."
endef

# ── Deploy dispatcher ─────────────────────────────────────────────────────────
define deploy-stack
	$(if $(filter prod production,$(ENV)), \
		$(call deploy-changeset,$(1),$(2),$(3)), \
		$(call deploy-direct,$(1),$(2),$(3)))
endef

# ──────────────────────────────────────────────────────────────────────────────
# deploy-foundation
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deploy-foundation
deploy-foundation:
	$(call lint-templates,$(STACKS_DIR)/foundation/*.yaml)
	$(call deploy-stack,$(call stack-name,foundation,networking),$(STACKS_DIR)/foundation/networking.yaml,$(call params-file,foundation,networking))
	$(call deploy-stack,$(call stack-name,foundation,identity),$(STACKS_DIR)/foundation/identity.yaml,$(call params-file,foundation,identity))
	$(call deploy-stack,$(call stack-name,foundation,data),$(STACKS_DIR)/foundation/data.yaml,$(call params-file,foundation,data))
	$(call deploy-stack,$(call stack-name,foundation,storage),$(STACKS_DIR)/foundation/storage.yaml,$(call params-file,foundation,storage))

# ──────────────────────────────────────────────────────────────────────────────
# deploy-platform
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deploy-platform
deploy-platform:
	$(call lint-templates,$(STACKS_DIR)/platform/guardrails.yaml $(STACKS_DIR)/platform/memory.yaml $(STACKS_DIR)/platform/gateway.yaml $(STACKS_DIR)/platform/knowledge.yaml)
	$(call deploy-stack,$(call stack-name,platform,guardrails),$(STACKS_DIR)/platform/guardrails.yaml,$(call params-file,platform,guardrails))
	$(call deploy-stack,$(call stack-name,platform,memory),$(STACKS_DIR)/platform/memory.yaml,$(call params-file,platform,memory))
	$(call deploy-stack,$(call stack-name,platform,gateway),$(STACKS_DIR)/platform/gateway.yaml,$(call params-file,platform,gateway))
	$(call deploy-stack,$(call stack-name,platform,knowledge),$(STACKS_DIR)/platform/knowledge.yaml,$(call params-file,platform,knowledge))

# ──────────────────────────────────────────────────────────────────────────────
# deploy-agents
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deploy-agents
deploy-agents:
	$(call lint-templates,$(STACKS_DIR)/application/agents/*.yaml)
	@for template in $(STACKS_DIR)/application/agents/*.yaml; do \
		stack_file=$$(basename $$template .yaml); \
		stack_name=$(APP_PREFIX)-application-agents-$$stack_file-$(ENV); \
		echo "==> Deploying agent stack: $$stack_name"; \
		$(MAKE) -f $(CF_DIR)/Makefile _deploy-one-stack \
			STACK_NAME=$$stack_name TEMPLATE=$$template ENV=$(ENV) \
			REGION=$(REGION) PROFILE=$(PROFILE); \
	done

.PHONY: _deploy-one-stack
_deploy-one-stack:
	$(call deploy-stack,$(STACK_NAME),$(TEMPLATE))

# ──────────────────────────────────────────────────────────────────────────────
# deploy-agent
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deploy-agent
deploy-agent:
ifndef AGENT
	$(error AGENT is required. Usage: make deploy-agent AGENT=<name> ENV=<env>)
endif
	$(call lint-templates,$(STACKS_DIR)/application/agents/$(AGENT).yaml)
	$(call deploy-stack, \
		$(call stack-name,application-agents,$(AGENT)), \
		$(STACKS_DIR)/application/agents/$(AGENT).yaml, \
		$(call params-file,application,$(AGENT)))

# ──────────────────────────────────────────────────────────────────────────────
# preview
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: preview
preview:
ifndef STACK
	$(error STACK is required. Usage: make preview STACK=<name> TIER=<tier> ENV=<env>)
endif
ifndef TIER
	$(error TIER is required. Usage: make preview STACK=<name> TIER=<tier> ENV=<env>)
endif
	$(eval PREVIEW_STACK_NAME := $(call stack-name,$(subst /,-,$(TIER)),$(STACK)))
	$(eval PREVIEW_TEMPLATE   := $(STACKS_DIR)/$(TIER)/$(STACK).yaml)
	$(eval PREVIEW_PARAMS     := $(call params-file,$(subst /,-,$(TIER)),$(STACK)))
	$(eval PREVIEW_CS         := $(PREVIEW_STACK_NAME)-preview-$(TIMESTAMP))
	$(call lint-templates,$(PREVIEW_TEMPLATE))
	@echo "==> Creating preview change set $(PREVIEW_CS)"; \
	$(AWS) cloudformation create-change-set \
		--stack-name $(PREVIEW_STACK_NAME) \
		--template-body file://$(PREVIEW_TEMPLATE) \
		--parameters file://$(PREVIEW_PARAMS) \
		--change-set-name $(PREVIEW_CS) \
		--change-set-type $$($(AWS) cloudformation describe-stacks --stack-name $(PREVIEW_STACK_NAME) \
			--query 'Stacks[0].StackStatus' --output text 2>/dev/null | \
			grep -q 'COMPLETE\|ROLLBACK_COMPLETE' && echo UPDATE || echo CREATE) \
		--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND; \
	echo "==> Waiting for change set..."; \
	$(AWS) cloudformation wait change-set-create-complete \
		--stack-name $(PREVIEW_STACK_NAME) \
		--change-set-name $(PREVIEW_CS) 2>/dev/null || true; \
	echo "==> Proposed changes:"; \
	$(AWS) cloudformation describe-change-set \
		--stack-name $(PREVIEW_STACK_NAME) \
		--change-set-name $(PREVIEW_CS) \
		--query 'Changes[*].{Action:ResourceChange.Action,LogicalId:ResourceChange.LogicalId,Type:ResourceChange.ResourceType,Replace:ResourceChange.Replacement}' \
		--output table; \
	echo ""; \
	echo "Change set $(PREVIEW_CS) was NOT executed. To apply:"; \
	echo "  aws cloudformation execute-change-set --stack-name $(PREVIEW_STACK_NAME) --change-set-name $(PREVIEW_CS)"; \
	echo "To delete:"; \
	echo "  aws cloudformation delete-change-set --stack-name $(PREVIEW_STACK_NAME) --change-set-name $(PREVIEW_CS)"

# ──────────────────────────────────────────────────────────────────────────────
# drift-detect
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: drift-detect
drift-detect:
	@echo "==> Detecting drift for ENV=$(ENV) in region $(REGION)"
	@bash $(CF_DIR)/scripts/drift-detect.sh $(ENV) $(REGION) $(PROFILE) $(APP_PREFIX)

# ──────────────────────────────────────────────────────────────────────────────
# destroy
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: destroy
destroy:
	@echo ""; \
	echo "WARNING: This will DELETE all $(APP_PREFIX) stacks for ENV=$(ENV) in $(REGION)."; \
	echo "Stacks will be destroyed in reverse order: agents → platform → foundation."; \
	echo ""; \
	read -p "Type the environment name to confirm destruction [$(ENV)]: " confirm; \
	if [ "$$confirm" != "$(ENV)" ]; then \
		echo "Aborted — confirmation did not match '$(ENV)'."; \
		exit 1; \
	fi; \
	bash $(CF_DIR)/scripts/destroy.sh $(ENV) $(REGION) $(PROFILE) $(APP_PREFIX)
