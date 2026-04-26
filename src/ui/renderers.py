from typing import List, Dict, Any


def render_plan(plan: List[Dict[str, Any]]) -> str:
    """Render execution plan as a collapsible markdown list with confidence badges."""
    if not plan:
        return "_No execution plan generated._"

    lines = ["### 📋 Execution Plan\n"]
    for step in plan:
        confidence = step.get("confidence_score", 0.0)
        badge = render_confidence(confidence)
        is_flagged = step.get("is_flagged", False)
        flag_icon = " ⚠️" if is_flagged else ""
        requires_approval = step.get("requires_approval", False)
        approval_icon = " 🔒" if requires_approval else ""

        lines.append(
            f"{step.get('step_index', 0) + 1}. **{step.get('tool_name', 'unknown')}** "
            f"{badge}{flag_icon}{approval_icon}\n"
            f"   - {step.get('description', '')}\n"
            f"   - Agent: `{step.get('expected_category', 'unknown')}`\n"
        )
        if is_flagged and step.get("flag_rationale"):
            lines.append(f"   - ⚠️ *{step['flag_rationale']}*\n")

    return "\n".join(lines)


def render_citations(citations: List[Dict[str, Any]]) -> str:
    """Render citations as inline [title](url) links."""
    if not citations:
        return ""
    return "\n".join(
        f"- [{c.get('title', 'Source')}]({c.get('url', '#')})"
        for c in citations
        if c.get("url")
    )


def render_confidence(score: float) -> str:
    """Render confidence score as 🟢/🟡/🔴 badge."""
    if score >= 0.8:
        return f"🟢 **High** ({score:.0%})"
    elif score >= 0.6:
        return f"🟡 **Medium** ({score:.0%})"
    else:
        return f"🔴 **Low** ({score:.0%})"
