"""
Property-Based Tests for feature-03-knowledge-rag.
Properties 11, 18, 24, 25, 26 from design.md verified with hypothesis.

Feature: feature-03-knowledge-rag
"""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

os.environ.setdefault("MOCK_STORAGE", "true")
os.environ.setdefault("MOCK_PROMPTS", "true")

# ── Stub langchain_aws before any node module is imported ─────────────────────
if "langchain_aws" not in sys.modules:
    _stub = ModuleType("langchain_aws")
    _stub.AmazonKnowledgeBasesRetriever = MagicMock()
    _stub.ChatBedrock = MagicMock()
    sys.modules["langchain_aws"] = _stub


# ─────────────────────────────────────────────────────────────────────────────
# Hypothesis strategies
# ─────────────────────────────────────────────────────────────────────────────

def st_document(with_url: bool = True, with_title: bool = True):
    """LangChain Document with optional metadata fields."""
    from langchain_core.documents import Document

    url_st = st.just("https://wiki.internal/doc") if with_url else st.just(None)
    title_st = st.text(min_size=1, max_size=80) if with_title else st.just(None)
    return st.fixed_dictionaries({
        "page_content": st.text(min_size=1, max_size=300),
        "title": title_st,
        "url": url_st,
        "source": st.text(min_size=1, max_size=100),
    }).map(lambda d: Document(
        page_content=d["page_content"],
        metadata={k: v for k, v in d.items() if k != "page_content" and v is not None},
    ))


def st_scored_docs(min_size: int = 1, max_size: int = 10):
    """List of (Document, float score) pairs."""
    return st.lists(
        st.tuples(
            st_document(),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        ),
        min_size=min_size,
        max_size=max_size,
    )


def st_threshold():
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


def st_top_k():
    return st.integers(min_value=1, max_value=10)


def st_context_window():
    return st.lists(st_document(), min_size=0, max_size=5)


def _make_state(**overrides) -> dict:
    """Build a minimal OrchestratorState dict for testing."""
    base = {
        "raw_request": "investigate high CPU on EC2",
        "task_category": "monitoring_query",
        "entities": {"service": "EC2"},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt-rag",
        "user_id": "user-pbt-rag",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    return {**base, **overrides}


# ─────────────────────────────────────────────────────────────────────────────
# Property 11: Context Window Monotonic Growth
# Validates: Requirements 9.2, 9.3, 9.4
# ─────────────────────────────────────────────────────────────────────────────

@given(
    initial_cw=st_context_window(),
    new_docs=st.lists(st_document(), min_size=0, max_size=5),
)
@settings(max_examples=100)
def test_property11_context_window_grows_monotonically(initial_cw, new_docs):
    # Feature: feature-03-knowledge-rag, Property 11: context window grows monotonically
    # Strategy: mock the KB retriever to return new_docs with scores all above threshold,
    # call retrieve_knowledge, assert output context_window is a superset of initial_cw.
    os.environ["KNOWLEDGE_BASE_ID"] = "kb-test-id"
    os.environ["KB_TOP_K"] = "10"
    os.environ["KB_RELEVANCE_THRESHOLD"] = "0.0"
    os.environ["RERANKER_ENABLED"] = "false"

    for doc in new_docs:
        doc.metadata["relevance_score"] = 1.0

    state = _make_state(context_window=list(initial_cw))

    with patch("src.rag.retriever.AmazonKnowledgeBasesRetriever") as mock_cls:
        mock_cls.return_value.invoke.return_value = new_docs
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
        result = retrieve_knowledge(state)

    output_cw = result["context_window"]
    for doc in initial_cw:
        assert doc in output_cw, "Initial context window doc missing from output — monotonicity violated"

    del os.environ["KNOWLEDGE_BASE_ID"]


# ─────────────────────────────────────────────────────────────────────────────
# Property 18: Citation Completeness for Every Retrieved Document
# Validates: Requirements 8.1, 8.2, 8.3, 8.4
# ─────────────────────────────────────────────────────────────────────────────

@given(
    docs=st.lists(
        st.one_of(
            st_document(with_url=True, with_title=True),
            st_document(with_url=False, with_title=True),
            st_document(with_url=True, with_title=False),
            st_document(with_url=False, with_title=False),
        ),
        min_size=1,
        max_size=8,
    )
)
@settings(max_examples=100)
def test_property18_citation_completeness(docs):
    # Feature: feature-03-knowledge-rag, Property 18: every included doc has a complete citation
    os.environ["KNOWLEDGE_BASE_ID"] = "kb-test-id"
    os.environ["KB_RELEVANCE_THRESHOLD"] = "0.0"
    os.environ["RERANKER_ENABLED"] = "false"

    for doc in docs:
        doc.metadata["relevance_score"] = 1.0

    state = _make_state()

    with patch("src.rag.retriever.AmazonKnowledgeBasesRetriever") as mock_cls:
        mock_cls.return_value.invoke.return_value = docs
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
        result = retrieve_knowledge(state)

    citations = result["citations"]
    assert len(citations) == len(docs), f"Expected {len(docs)} citations, got {len(citations)}"
    for citation in citations:
        assert citation.get("title"), f"citation title must be non-empty: {citation}"
        assert citation.get("url"), f"citation url must be non-empty: {citation}"
        assert citation.get("timestamp"), f"citation timestamp must be non-empty: {citation}"

    del os.environ["KNOWLEDGE_BASE_ID"]


# ─────────────────────────────────────────────────────────────────────────────
# Property 24: RAG Metric Computation Correctness
# Validates: Requirements 7.1, 7.2
# ─────────────────────────────────────────────────────────────────────────────

@given(
    scored_docs=st_scored_docs(min_size=1, max_size=10),
    threshold=st_threshold(),
    top_k=st_top_k(),
)
@settings(max_examples=100)
def test_property24_rag_metric_computation_correctness(scored_docs, threshold, top_k):
    # Feature: feature-03-knowledge-rag, Property 24: precision@K and recall@K are mathematically correct
    from src.orchestrator.nodes.retrieve_knowledge import _compute_rag_metrics

    precision, recall = _compute_rag_metrics(scored_docs, threshold, top_k)

    # Reference computation
    relevant_in_top_k = sum(1 for _, s in scored_docs[:top_k] if s >= threshold)
    total_relevant = sum(1 for _, s in scored_docs if s >= threshold)
    expected_precision = relevant_in_top_k / top_k if top_k > 0 else 0.0
    expected_recall = relevant_in_top_k / total_relevant if total_relevant > 0 else 0.0

    assert abs(precision - expected_precision) < 1e-9, (
        f"precision@K mismatch: got {precision}, expected {expected_precision}"
    )
    assert abs(recall - expected_recall) < 1e-9, (
        f"recall@K mismatch: got {recall}, expected {expected_recall}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Property 25: Re-Ranked Order Preserved in Context Window
# Validates: Requirements 5.1, 5.4
# ─────────────────────────────────────────────────────────────────────────────

@given(scored_docs=st_scored_docs(min_size=2, max_size=8))
@settings(max_examples=100)
def test_property25_reranked_order_preserved_in_context_window(scored_docs):
    # Feature: feature-03-knowledge-rag, Property 25: re-ranked order is preserved in context window
    os.environ["KNOWLEDGE_BASE_ID"] = "kb-test-id"
    os.environ["KB_RELEVANCE_THRESHOLD"] = "0.0"
    os.environ["RERANKER_ENABLED"] = "true"

    # Sort descending by score — this is the order the reranker would produce
    sorted_pairs = sorted(scored_docs, key=lambda x: x[1], reverse=True)
    reranked_docs = []
    for doc, score in sorted_pairs:
        doc.metadata["relevance_score"] = score
        reranked_docs.append(doc)

    state = _make_state()

    # Stub langchain.retrievers modules so reranker.py is importable in test env
    import importlib
    import sys
    from types import ModuleType as _ModuleType
    _lc = _ModuleType("langchain")
    _lc_ret = _ModuleType("langchain.retrievers")
    _lc_comp = _ModuleType("langchain.retrievers.document_compressors")
    _lc_comp.CrossEncoderReranker = MagicMock()
    _lc_ret.ContextualCompressionRetriever = MagicMock()
    _lc_ret.document_compressors = _lc_comp
    _lc.retrievers = _lc_ret
    sys.modules.setdefault("langchain", _lc)
    sys.modules.setdefault("langchain.retrievers", _lc_ret)
    sys.modules.setdefault("langchain.retrievers.document_compressors", _lc_comp)

    import src.rag.reranker as reranker_mod
    importlib.reload(reranker_mod)

    # Patch base retriever and reranker; reranker returns docs in sorted order
    with patch("src.rag.retriever.AmazonKnowledgeBasesRetriever") as mock_cls, \
         patch.object(reranker_mod, "build_reranker") as mock_build_reranker:
        mock_cls.return_value = MagicMock()

        mock_reranker = MagicMock()
        mock_reranker.invoke.return_value = reranked_docs
        mock_build_reranker.return_value = mock_reranker

        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
        result = retrieve_knowledge(state)

    output_cw = result["context_window"]
    assert output_cw == reranked_docs, (
        "Context window order does not match reranked order — re-ranking not preserved"
    )

    del os.environ["KNOWLEDGE_BASE_ID"]


# ─────────────────────────────────────────────────────────────────────────────
# Property 26: Below-Threshold Documents Excluded from Context Window
# Validates: Requirements 6.1, 6.4
# ─────────────────────────────────────────────────────────────────────────────

@given(
    scored_docs=st_scored_docs(min_size=1, max_size=10),
    threshold=st_threshold(),
)
@settings(max_examples=100)
def test_property26_below_threshold_docs_excluded(scored_docs, threshold):
    # Feature: feature-03-knowledge-rag, Property 26: below-threshold docs excluded from context window
    os.environ["KNOWLEDGE_BASE_ID"] = "kb-test-id"
    os.environ["KB_RELEVANCE_THRESHOLD"] = str(threshold)
    os.environ["RERANKER_ENABLED"] = "false"

    docs_with_scores = []
    for doc, score in scored_docs:
        doc.metadata["relevance_score"] = score
        docs_with_scores.append(doc)

    state = _make_state()

    with patch("src.rag.retriever.AmazonKnowledgeBasesRetriever") as mock_cls:
        mock_cls.return_value.invoke.return_value = docs_with_scores
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
        result = retrieve_knowledge(state)

    output_cw = result["context_window"]
    for doc in output_cw:
        score = doc.metadata.get("relevance_score", 1.0)
        assert score >= threshold, (
            f"Below-threshold doc (score={score}) found in context window (threshold={threshold})"
        )

    del os.environ["KNOWLEDGE_BASE_ID"]
