.PHONY: dev test lint docker-up docker-down help \
        deploy-foundation deploy-platform deploy-agents deploy-agent \
        preview drift-detect destroy

include cloudformation/Makefile

help:
	@echo "Available targets:"
	@echo "  dev               Start the orchestrator locally with uvicorn on port 8080 (with reload)"
	@echo "  test              Run the test suite with pytest"
	@echo "  lint              Run ruff linter on src/ and tests/"
	@echo "  docker-up         Start the full local observability stack"
	@echo "  docker-down       Stop the local observability stack"
	@echo ""
	@echo "CloudFormation targets (ENV=local|production, default: local):"
	@echo "  deploy-foundation [ENV=]  Deploy foundation stacks (networking, identity, data, storage)"
	@echo "  deploy-platform   [ENV=]  Deploy platform stacks (knowledge, guardrails, memory, gateway, observability)"
	@echo "  deploy-agents     [ENV=]  Deploy all agent stacks"
	@echo "  deploy-agent      AGENT=<name> [ENV=]  Deploy a single agent stack"
	@echo "  preview           STACK=<name> TIER=<tier> [ENV=]  Preview changes (change set, no execute)"
	@echo "  drift-detect      [ENV=]  Detect drift across all deployed stacks"
	@echo "  destroy           [ENV=]  Destroy all stacks (agents → platform → foundation)"

dev:
	uvicorn src.orchestrator.main:app --port 8080 --reload

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

docker-up:
	docker compose up -d

docker-down:
	docker compose down
