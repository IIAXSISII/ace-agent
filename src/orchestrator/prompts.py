"""
Prompt template loader for the orchestrator.

Templates are loaded from the `prompt-template-registry` DynamoDB table.
When MOCK_PROMPTS=true, templates are loaded from local YAML files under
src/orchestrator/mock_templates/ instead.
"""

import os
import re
import yaml
from pathlib import Path
from functools import lru_cache
from langchain_core.prompts import ChatPromptTemplate
from src.storage.dynamodb import get_item

PROMPT_TABLE = "prompt-template-registry"
MOCK_TEMPLATES_DIR = Path(__file__).parent / "mock_templates"


class PromptTemplateLoadError(Exception):
    """Raised when a prompt template cannot be loaded from DynamoDB."""


class UnresolvedPlaceholderError(Exception):
    """Raised when a rendered prompt still contains unresolved {variable} placeholders."""


def _is_mock_prompts() -> bool:
    return os.getenv("MOCK_PROMPTS", "").lower() == "true"


def _load_from_yaml(task_category: str) -> dict:
    """Load a template dict from a local YAML file."""
    yaml_path = MOCK_TEMPLATES_DIR / f"{task_category}.yaml"
    if not yaml_path.exists():
        raise PromptTemplateLoadError(
            f"Mock template file not found: {yaml_path}"
        )
    with yaml_path.open("r") as f:
        return yaml.safe_load(f)


def _build_chat_prompt_template(item: dict) -> ChatPromptTemplate:
    """Build a ChatPromptTemplate from a DynamoDB item or YAML dict."""
    system_prompt = item.get("systemPrompt") or item.get("system_prompt", "")
    human_template = item.get("humanTemplate") or item.get("human_template", "{input}")
    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", human_template),
    ])


@lru_cache(maxsize=128)
def load_prompt_template(task_category: str, version: str = "active") -> ChatPromptTemplate:
    """
    Load a versioned prompt template for the given task category.

    When MOCK_PROMPTS=true, loads from local YAML files under mock_templates/.
    Otherwise, loads from the prompt-template-registry DynamoDB table.

    The template_id used for DynamoDB lookup is: f"{task_category}-v1"
    (the version param is reserved for future multi-version support).

    Caches results in-process after first load to avoid per-request DDB reads.

    Returns a ChatPromptTemplate ready for use with .format_messages().

    Raises:
        PromptTemplateLoadError: if the template cannot be found.
    """
    template_id = f"{task_category}-v1"

    if _is_mock_prompts():
        data = _load_from_yaml(task_category)
        template = _build_chat_prompt_template(data)
        # Attach metadata for execution log recording
        template.metadata = {
            "template_id": data.get("template_id", template_id),
            "template_version": data.get("version", "1.0.0"),
        }
        return template

    # Load from DynamoDB
    key = {"templateId": template_id}
    item = get_item(PROMPT_TABLE, key)

    if item is None:
        raise PromptTemplateLoadError(
            f"Prompt template not found in table '{PROMPT_TABLE}' for key {key}"
        )

    template = _build_chat_prompt_template(item)
    template.metadata = {
        "template_id": item.get("templateId", template_id),
        "template_version": item.get("version", "unknown"),
    }
    return template


def validate_rendered_prompt(rendered_text: str, template_id: str) -> None:
    """
    Validate that a rendered prompt contains no unresolved {variable} placeholders.

    Call this after ChatPromptTemplate.format_messages() has been invoked and
    the messages have been joined into a single string.

    Raises:
        UnresolvedPlaceholderError: if any {variable} placeholder remains.
    """
    matches = re.findall(r'\{(\w+)\}', rendered_text)
    if matches:
        # Report the first unresolved placeholder
        var_name = matches[0]
        raise UnresolvedPlaceholderError(
            f"Template '{template_id}' has unresolved placeholder: '{{{var_name}}}'"
        )
