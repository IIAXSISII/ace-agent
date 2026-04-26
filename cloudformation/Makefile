# ──────────────────────────────────────────────────────────────────────────────
# CloudFormation deployment targets
# ──────────────────────────────────────────────────────────────────────────────
# Usage:
#   make deploy-foundation ENV=production
#   make deploy-platform   ENV=production
#   make deploy-agents     ENV=production
#   make deploy-agent      AGENT=confluence ENV=production
#   make preview           STACK=confluence-agent TIER=application/agents ENV=production
#   make drift-detect      ENV=production
#   make destroy           ENV=production

# ── Variables ─────────────────────────────────────────────────────────────────
ENV     ?= local
REGION  ?= $(or $(AWS_DEFAULT_REGION),us-east-1)
PROFILE ?= $(or $(AWS_PROFILE),default)

CF_DIR    := cloudformation
STACKS_DIR := $(CF_DIR)/stacks
PARAMS    := $(CF_DIR)/parameters/$(ENV).json

APP_PREFIX := ace-agent

# Stack name helper: ace-agent-<tier>-<stack>-<env>
# $(call stack-name,<tier>,<stack>)
stack-name = $(APP_PREFIX)-$(subst /,-,$(1))-$(2)-$(ENV)

# Timestamp for change-set names (unique per invocation)
TIMESTAMP := $(shell date +%Y%m%d%H%M%S)

AWS := aws --region $(REGION) --profile $(PROFILE)

# ── cfn-lint guard ────────────────────────────────────────────────────────────
# Run cfn-lint on a glob of templates before any deploy.
# $(call lint-templates,<glob>)
define lint-templates
	@echo "==> cfn-lint $(1)"
	cfn-lint $(1)
endef

# ── Change-set deploy (production) ───────────────────────────────────────────
# Creates a change set, waits, describes it, then executes it.
# $(call deploy-changeset,<stack-name>,<template-file>)
define deploy-changeset
	$(eval CS_NAME := $(1)-cs-$(TIMESTAMP))
	@echo "==> Creating change set $(CS_NAME) for stack $(1)"
	$(AWS) cloudformation create-change-set \
		--stack-name $(1) \
		--template-body file://$(2) \
		--parameters file://$(PARAMS) \
		--change-set-name $(CS_NAME) \
		--change-set-type $(shell \
			$(AWS) cloudformation describe-stacks --stack-name $(1) \
				--query 'Stacks[0].StackStatus' --output text 2>/dev/null \
			| grep -q 'COMPLETE\|ROLLBACK_COMPLETE' && echo UPDATE || echo CREATE) \
		--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND
	@echo "==> Waiting for change set to be ready..."
	$(AWS) cloudformation wait change-set-create-complete \
		--stack-name $(1) \
		--change-set-name $(CS_NAME)
	@echo "==> Change set diff:"
	$(AWS) cloudformation describe-change-set \
		--stack-name $(1) \
		--change-set-name $(CS_NAME) \
		--query 'Changes[*].{Action:ResourceChange.Action,LogicalId:ResourceChange.LogicalId,Type:ResourceChange.ResourceType,Replace:ResourceChange.Replacement}' \
		--output table
	@echo "==> Executing change set..."
	$(AWS) cloudformation execute-change-set \
		--stack-name $(1) \
		--change-set-name $(CS_NAME)
	@echo "==> Waiting for stack operation to complete..."
	$(AWS) cloudformation wait stack-update-complete \
		--stack-name $(1) 2>/dev/null || \
	$(AWS) cloudformation wait stack-create-complete \
		--stack-name $(1)
	@echo "==> Stack $(1) deployed successfully."
endef

# ── Direct deploy (local / non-production) ───────────────────────────────────
# $(call deploy-direct,<stack-name>,<template-file>)
define deploy-direct
	@echo "==> Deploying stack $(1) ($(ENV))"
	$(AWS) cloudformation deploy \
		--stack-name $(1) \
		--template-file $(2) \
		--parameter-overrides file://$(PARAMS) \
		--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
		--no-fail-on-empty-changeset
	@echo "==> Stack $(1) deployed."
endef

# ── Deploy dispatcher ─────────────────────────────────────────────────────────
# Routes to change-set or direct deploy based on ENV.
# $(call deploy-stack,<stack-name>,<template-file>)
define deploy-stack
	$(if $(filter production,$(ENV)), \
		$(call deploy-changeset,$(1),$(2)), \
		$(call deploy-direct,$(1),$(2)))
endef

# ──────────────────────────────────────────────────────────────────────────────
# deploy-foundation
# Deploys all stacks under cloudformation/stacks/foundation/
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deploy-foundation
deploy-foundation:
	$(call lint-templates,$(STACKS_DIR)/foundation/*.yaml)
	$(call deploy-stack,$(call stack-name,foundation,networking),$(STACKS_DIR)/foundation/networking.yaml)
	$(call deploy-stack,$(call stack-name,foundation,identity),$(STACKS_DIR)/foundation/identity.yaml)
	$(call deploy-stack,$(call stack-name,foundation,data),$(STACKS_DIR)/foundation/data.yaml)
	$(call deploy-stack,$(call stack-name,foundation,storage),$(STACKS_DIR)/foundation/storage.yaml)

# ──────────────────────────────────────────────────────────────────────────────
# deploy-platform
# Deploys all stacks under cloudformation/stacks/platform/
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deploy-platform
deploy-platform:
	$(call lint-templates,$(STACKS_DIR)/platform/*.yaml)
	$(call deploy-stack,$(call stack-name,platform,knowledge),$(STACKS_DIR)/platform/knowledge.yaml)
	$(call deploy-stack,$(call stack-name,platform,guardrails),$(STACKS_DIR)/platform/guardrails.yaml)
	$(call deploy-stack,$(call stack-name,platform,memory),$(STACKS_DIR)/platform/memory.yaml)
	$(call deploy-stack,$(call stack-name,platform,gateway),$(STACKS_DIR)/platform/gateway.yaml)
	$(call deploy-stack,$(call stack-name,platform,observability),$(STACKS_DIR)/platform/observability.yaml)

# ──────────────────────────────────────────────────────────────────────────────
# deploy-agents
# Deploys all stacks under cloudformation/stacks/application/agents/
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

# Internal target used by deploy-agents loop
.PHONY: _deploy-one-stack
_deploy-one-stack:
	$(call deploy-stack,$(STACK_NAME),$(TEMPLATE))

# ──────────────────────────────────────────────────────────────────────────────
# deploy-agent
# Deploys a single agent stack. Requires AGENT=<name>.
# Example: make deploy-agent AGENT=confluence ENV=production
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deploy-agent
deploy-agent:
ifndef AGENT
	$(error AGENT is required. Usage: make deploy-agent AGENT=<name> ENV=<env>)
endif
	$(call lint-templates,$(STACKS_DIR)/application/agents/$(AGENT)-agent.yaml)
	$(call deploy-stack, \
		$(call stack-name,application-agents,$(AGENT)-agent), \
		$(STACKS_DIR)/application/agents/$(AGENT)-agent.yaml)

# ──────────────────────────────────────────────────────────────────────────────
# preview
# Creates a change set and shows the diff WITHOUT executing it.
# Requires STACK=<stack-name> and TIER=<tier-path>.
# Example: make preview STACK=confluence-agent TIER=application/agents ENV=production
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
	$(eval PREVIEW_CS         := $(PREVIEW_STACK_NAME)-preview-$(TIMESTAMP))
	$(call lint-templates,$(PREVIEW_TEMPLATE))
	@echo "==> Creating preview change set $(PREVIEW_CS)"
	$(AWS) cloudformation create-change-set \
		--stack-name $(PREVIEW_STACK_NAME) \
		--template-body file://$(PREVIEW_TEMPLATE) \
		--parameters file://$(PARAMS) \
		--change-set-name $(PREVIEW_CS) \
		--change-set-type $(shell \
			$(AWS) cloudformation describe-stacks --stack-name $(PREVIEW_STACK_NAME) \
				--query 'Stacks[0].StackStatus' --output text 2>/dev/null \
			| grep -q 'COMPLETE\|ROLLBACK_COMPLETE' && echo UPDATE || echo CREATE) \
		--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND
	@echo "==> Waiting for change set..."
	$(AWS) cloudformation wait change-set-create-complete \
		--stack-name $(PREVIEW_STACK_NAME) \
		--change-set-name $(PREVIEW_CS)
	@echo "==> Proposed changes:"
	$(AWS) cloudformation describe-change-set \
		--stack-name $(PREVIEW_STACK_NAME) \
		--change-set-name $(PREVIEW_CS) \
		--query 'Changes[*].{Action:ResourceChange.Action,LogicalId:ResourceChange.LogicalId,Type:ResourceChange.ResourceType,Replace:ResourceChange.Replacement}' \
		--output table
	@echo ""
	@echo "Change set $(PREVIEW_CS) was NOT executed. To apply, run:"
	@echo "  aws cloudformation execute-change-set --stack-name $(PREVIEW_STACK_NAME) --change-set-name $(PREVIEW_CS)"
	@echo ""
	@echo "To delete this preview change set:"
	@echo "  aws cloudformation delete-change-set --stack-name $(PREVIEW_STACK_NAME) --change-set-name $(PREVIEW_CS)"

# ──────────────────────────────────────────────────────────────────────────────
# drift-detect
# Runs drift detection on all deployed stacks for the given ENV.
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: drift-detect
drift-detect:
	@echo "==> Detecting drift for ENV=$(ENV) in region $(REGION)"
	@bash $(CF_DIR)/scripts/drift-detect.sh $(ENV) $(REGION) $(PROFILE) $(APP_PREFIX)

# ──────────────────────────────────────────────────────────────────────────────
# destroy
# Tears down all stacks in reverse dependency order (agents → platform → foundation).
# Prompts for confirmation before proceeding.
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: destroy
destroy:
	@echo ""
	@echo "WARNING: This will DELETE all $(APP_PREFIX) stacks for ENV=$(ENV) in $(REGION)."
	@echo "Stacks will be destroyed in reverse order: agents → platform → foundation."
	@echo ""
	@read -p "Type the environment name to confirm destruction [$(ENV)]: " confirm; \
	if [ "$$confirm" != "$(ENV)" ]; then \
		echo "Aborted — confirmation did not match '$(ENV)'."; \
		exit 1; \
	fi
	@bash $(CF_DIR)/scripts/destroy.sh $(ENV) $(REGION) $(PROFILE) $(APP_PREFIX)
