"""
Unit tests for src/orchestrator/prompts.py — tasks 5.1, 5.2, 5.3, 5.4.
"""

import os
import pytest
from unittest.mock import patch
from langchain_core.prompts import ChatPromptTemplate

# Clear lru_cache between tests
from src.orchestrator import prompts as prompts_module


def _clear_cache():
    prompts_module.load_prompt_template.cache_clear()


# ---------------------------------------------------------------------------
# Task 5.3 — YAML files exist and are valid
# ---------------------------------------------------------------------------

TASK_CATEGORIES = [
    "incident_investigation",
    "infrastructure_change",
    "cost_analysis",
    "deployment",
    "monitoring_query",
    "knowledge_retrieval",
    "code_review",
]


@pytest.mark.parametrize("category", TASK_CATEGORIES)
def test_yaml_files_exist(category):
    yaml_path = prompts_module.MOCK_TEMPLATES_DIR / f"{category}.yaml"
    assert yaml_path.exists(), f"Missing YAML file: {yaml_path}"


@pytest.mark.parametrize("category", TASK_CATEGORIES)
def test_yaml_files_have_required_fields(category):
    import yaml
    yaml_path = prompts_module.MOCK_TEMPLATES_DIR / f"{category}.yaml"
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    assert "template_id" in data
    assert "task_category" in data
    assert "version" in data
    assert "system_prompt" in data
    assert "human_template" in data
    assert "input_variables" in data
    assert data["task_category"] == category
    assert data["template_id"] == f"{category}-v1"


# ---------------------------------------------------------------------------
# Task 5.1 — load_prompt_template with MOCK_PROMPTS=true
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("category", TASK_CATEGORIES)
def test_load_prompt_template_mock_returns_chat_prompt_template(category):
    _clear_cache()
    with patch.dict(os.environ, {"MOCK_PROMPTS": "true"}):
        template = prompts_module.load_prompt_template(category)
    assert isinstance(template, ChatPromptTemplate)


@pytest.mark.parametrize("category", TASK_CATEGORIES)
def test_load_prompt_template_mock_has_metadata(category):
    _clear_cache()
    with patch.dict(os.environ, {"MOCK_PROMPTS": "true"}):
        template = prompts_module.load_prompt_template(category)
    assert template.metadata is not None
    assert "template_id" in template.metadata
    assert "template_version" in template.metadata
    assert template.metadata["template_id"] == f"{category}-v1"


def test_load_prompt_template_is_cached():
    _clear_cache()
    with patch.dict(os.environ, {"MOCK_PROMPTS": "true"}):
        t1 = prompts_module.load_prompt_template("deployment")
        t2 = prompts_module.load_prompt_template("deployment")
    # lru_cache returns the same object
    assert t1 is t2


# ---------------------------------------------------------------------------
# Task 5.1 — load_prompt_template with MOCK_STORAGE=true (DynamoDB mock)
# ---------------------------------------------------------------------------

def test_load_prompt_template_from_dynamodb_mock():
    _clear_cache()
    with patch.dict(os.environ, {"MOCK_PROMPTS": "false", "MOCK_STORAGE": "true"}):
        template = prompts_module.load_prompt_template("incident_investigation")
    assert isinstance(template, ChatPromptTemplate)
    assert template.metadata["template_id"] == "incident_investigation-v1"


# ---------------------------------------------------------------------------
# Task 5.2 — PromptTemplateLoadError when item not found
# ---------------------------------------------------------------------------

def test_load_prompt_template_raises_when_not_found():
    _clear_cache()
    with patch.dict(os.environ, {"MOCK_PROMPTS": "false", "MOCK_STORAGE": "false"}):
        with patch("src.orchestrator.prompts.get_item", return_value=None):
            with pytest.raises(prompts_module.PromptTemplateLoadError) as exc_info:
                prompts_module.load_prompt_template("nonexistent_category")
    assert "prompt-template-registry" in str(exc_info.value)
    assert "nonexistent_category-v1" in str(exc_info.value)


def test_prompt_template_load_error_message_includes_table_and_key():
    _clear_cache()
    with patch.dict(os.environ, {"MOCK_PROMPTS": "false"}):
        with patch("src.orchestrator.prompts.get_item", return_value=None):
            with pytest.raises(prompts_module.PromptTemplateLoadError) as exc_info:
                prompts_module.load_prompt_template("cost_analysis")
    msg = str(exc_info.value)
    assert "prompt-template-registry" in msg
    assert "cost_analysis-v1" in msg


# ---------------------------------------------------------------------------
# Task 5.4 — validate_rendered_prompt
# ---------------------------------------------------------------------------

def test_validate_rendered_prompt_passes_clean_text():
    # Should not raise
    prompts_module.validate_rendered_prompt(
        "You are a cloud engineer. Analyze the incident.", "incident_investigation-v1"
    )


def test_validate_rendered_prompt_raises_on_unresolved_placeholder():
    with pytest.raises(prompts_module.UnresolvedPlaceholderError) as exc_info:
        prompts_module.validate_rendered_prompt(
            "Analyze this: {input}", "incident_investigation-v1"
        )
    assert "incident_investigation-v1" in str(exc_info.value)
    assert "{input}" in str(exc_info.value)


def test_validate_rendered_prompt_error_includes_variable_name():
    with pytest.raises(prompts_module.UnresolvedPlaceholderError) as exc_info:
        prompts_module.validate_rendered_prompt(
            "Service: {service_name} is down", "monitoring_query-v1"
        )
    assert "service_name" in str(exc_info.value)


def test_validate_rendered_prompt_passes_empty_string():
    # Empty string has no placeholders — should not raise
    prompts_module.validate_rendered_prompt("", "some-template-v1")


def test_validate_rendered_prompt_passes_text_with_braces_in_code():
    # JSON-like content with numeric keys should not trigger the regex
    prompts_module.validate_rendered_prompt(
        'Response: {"status": "ok", "count": 42}', "code_review-v1"
    )
