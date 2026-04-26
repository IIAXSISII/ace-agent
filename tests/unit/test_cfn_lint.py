"""
Integration tests that invoke cfn-lint as a subprocess on each CloudFormation template
introduced in F02 and assert exit code 0.

Each test is independent and reports cfn-lint stdout+stderr on failure so the developer
can see exactly what failed.
"""
import subprocess
from pathlib import Path

import pytest

# Repo root is three levels up from this file: tests/unit/test_cfn_lint.py
REPO_ROOT = Path(__file__).parent.parent.parent


def _run_cfn_lint(template_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["cfn-lint", str(template_path)],
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
def test_cfn_lint_networking():
    template = REPO_ROOT / "cloudformation/stacks/foundation/networking.yaml"
    result = _run_cfn_lint(template)
    assert result.returncode == 0, (
        f"cfn-lint failed for {template}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.integration
def test_cfn_lint_identity():
    template = REPO_ROOT / "cloudformation/stacks/foundation/identity.yaml"
    result = _run_cfn_lint(template)
    assert result.returncode == 0, (
        f"cfn-lint failed for {template}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.integration
def test_cfn_lint_guardrails():
    template = REPO_ROOT / "cloudformation/stacks/platform/guardrails.yaml"
    result = _run_cfn_lint(template)
    assert result.returncode == 0, (
        f"cfn-lint failed for {template}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.integration
def test_cfn_lint_memory():
    template = REPO_ROOT / "cloudformation/stacks/platform/memory.yaml"
    result = _run_cfn_lint(template)
    assert result.returncode == 0, (
        f"cfn-lint failed for {template}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.integration
def test_cfn_lint_gateway():
    template = REPO_ROOT / "cloudformation/stacks/platform/gateway.yaml"
    result = _run_cfn_lint(template)
    assert result.returncode == 0, (
        f"cfn-lint failed for {template}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.integration
def test_cfn_lint_orchestrator():
    template = REPO_ROOT / "cloudformation/stacks/application/agents/orchestrator.yaml"
    result = _run_cfn_lint(template)
    assert result.returncode == 0, (
        f"cfn-lint failed for {template}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.integration
def test_cfn_lint_agent_runtime_endpoint_module():
    template = REPO_ROOT / "cloudformation/modules/agent-runtime-endpoint/module.yaml"
    result = _run_cfn_lint(template)
    assert result.returncode == 0, (
        f"cfn-lint failed for {template}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
