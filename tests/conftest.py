"""
Root conftest.py — pre-imports real source modules before any test stubs
can replace them in sys.modules.

Several test files stub out heavy dependencies at module level using
`if "module" not in sys.modules` guards. By importing the real modules
here first, those guards will skip stubbing and tests that need real
implementations will work correctly regardless of collection order.
"""
import os

os.environ.setdefault("MOCK_STORAGE", "true")
os.environ.setdefault("MOCK_PROMPTS", "true")

# Pre-import all node modules that get stubbed by test_graph_routing.py
# This ensures the real implementations are cached in sys.modules first.
import src.orchestrator.nodes.classify_request  # noqa: F401, E402
import src.orchestrator.nodes.retrieve_knowledge  # noqa: F401, E402
import src.orchestrator.nodes.detect_missing_inputs  # noqa: F401, E402
import src.orchestrator.nodes.prompt_user  # noqa: F401, E402
import src.orchestrator.nodes.generate_plan  # noqa: F401, E402
import src.orchestrator.nodes.present_plan  # noqa: F401, E402
import src.orchestrator.nodes.validate_step_pre  # noqa: F401, E402
import src.orchestrator.nodes.invoke_subagent  # noqa: F401, E402
import src.orchestrator.nodes.validate_step_post  # noqa: F401, E402
import src.orchestrator.nodes.aggregate_results  # noqa: F401, E402
import src.orchestrator.nodes.scan_output_guardrails  # noqa: F401, E402
import src.orchestrator.nodes.write_execution_log  # noqa: F401, E402
import src.orchestrator.memory  # noqa: F401, E402

# Pre-import guardrails to prevent stub interference
import src.guardrails.bedrock  # noqa: F401, E402
