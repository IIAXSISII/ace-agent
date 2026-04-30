# Implementation Plan: F03 — Knowledge & RAG

## Overview

Implement the Bedrock Knowledge Base RAG pipeline end-to-end: provision the `knowledge.yaml` CloudFormation stack, implement `retriever.py` and `reranker.py`, fully rewrite `retrieve_knowledge.py`, apply targeted fixes to `aggregate_results.py`, wire all new env vars into `orchestrator.yaml` and `identity.yaml`, and add PBT tests for Properties 11, 18, 24, 25, 26.

Deploy order: `knowledge` → `identity` → `orchestrator` (cross-stack dependency chain).

## Tasks

- [x] 1. Create `cloudformation/stacks/platform/knowledge.yaml`
  - Provision `KnowledgeSourceBucketKmsKey` (`AWS::KMS::Key`, `DeletionPolicy: Retain`, `EnableKeyRotation: true`; key policy allows root + `s3.amazonaws.com`; alias `alias/${Application}-${Environment}-knowledge-source`)
  - Provision `KnowledgeSourceBucket` (`AWS::S3::Bucket`, `DeletionPolicy: Retain`; SSE with KMS key; all four `PublicAccessBlockConfiguration` flags `true`; versioning enabled; name `${Application}-${Environment}-knowledge-source-${AWS::AccountId}`)
  - Provision `KnowledgeVectorsIndex` (`AWS::S3Vectors::VectorBucket`, `DeletionPolicy: Retain`; dimension 1024; cosine distance)
  - Provision `BedrockKbServiceRole` (`AWS::IAM::Role`; trust `bedrock.amazonaws.com`; inline policy: `s3:GetObject`+`s3:ListBucket` on source bucket, `bedrock:InvokeModel` on Titan Embeddings V2 model ARN, `s3vectors:*` on vectors index, `kms:Decrypt`+`kms:GenerateDataKey` on KMS key)
  - Provision `KnowledgeBase` (`AWS::Bedrock::KnowledgeBase`; `Type: VECTOR`; Titan Embeddings V2 ARN; `StorageConfiguration.Type: S3_VECTORS`; `RoleArn: !GetAtt BedrockKbServiceRole.Arn`)
  - Provision five `AWS::Bedrock::DataSource` resources (one per document type): `DataSourceConfluence` (`confluence/`, `HIERARCHICAL`, parent 1500/child 300/overlap 60), `DataSourceIaC` (`iac/`, `FIXED_SIZE`, 512/64), `DataSourceCode` (`code/`, `FIXED_SIZE`, 512/64), `DataSourceReadme` (`readme/`, `HIERARCHICAL`, parent 1500/child 300/overlap 60), `DataSourceIncidents` (`incidents/`, `FIXED_SIZE`, 256/32); all with `ScheduleExpression: rate(60 minutes)`. Note: Bedrock KB enforces a limit of 5 data sources per KB — `DataSourceDefault` was removed to stay within this limit.
  - Provision `KnowledgeBaseIdParam` SSM parameter at `/${Application}/${Environment}/knowledge/knowledge-base-id`
  - Add `Outputs`: `KnowledgeBaseId`, `KnowledgeBaseArn`, `KnowledgeSourceBucketKmsKeyArn` — all exported as `${AWS::StackName}-<ResourceName>`
  - Tag every resource: `env`, `application`, `created-with: CloudFormation`, `owners: cloud-engineering`, `Stack: !Ref AWS::StackName`
  - Template must pass `cfn-lint` with zero errors
  - _Requirements: 1.1–1.14, 2.1–2.3, 3.1–3.4_

- [x] 2. Create `cloudformation/parameters/platform-knowledge-prod.json`
  - Create file with `Environment: prod` and `Application: ace-agent` entries, following the pattern of `platform-memory-prod.json`
  - _Requirements: 1.12_

- [x] 3. Update `cloudformation/Makefile` — add knowledge to `deploy-platform`
  - Add `$(STACKS_DIR)/platform/knowledge.yaml` to the `cfn-lint` list in `deploy-platform`
  - Add `$(call deploy-stack,$(call stack-name,platform,knowledge),$(STACKS_DIR)/platform/knowledge.yaml,$(call params-file,platform,knowledge))` after the `gateway` deploy line
  - _Requirements: 1.14_

- [x] 4. Update `cloudformation/stacks/foundation/identity.yaml` — add KB Retrieve permission
  - Add `KnowledgeStackName` parameter (`Type: String`, `Default: ace-agent-platform-knowledge-prod`, description matching existing parameter style)
  - Add `AllowKnowledgeBaseRetrieve` IAM statement to `OrchestratorPolicy`: `Action: bedrock-agent-runtime:Retrieve`, `Resource: Fn::ImportValue: !Sub "${KnowledgeStackName}-KnowledgeBaseArn"`
  - Template must pass `cfn-lint` with zero errors after change
  - _Requirements: 11.1, 11.2_

- [x] 5. Update `cloudformation/parameters/foundation-identity-prod.json`
  - Add `{"ParameterKey": "KnowledgeStackName", "ParameterValue": "ace-agent-platform-knowledge-prod"}` entry
  - _Requirements: 11.1_

- [x] 6. Update `cloudformation/stacks/application/agents/orchestrator.yaml` — add KB env vars
  - Add four new `Parameters`: `KnowledgeStackName` (`Default: ace-agent-platform-knowledge-prod`), `KB_TOP_K` (`Default: "5"`), `KB_RELEVANCE_THRESHOLD` (`Default: "0.5"`), `RERANKER_ENABLED` (`Default: "true"`, `AllowedValues: ["true", "false"]`)
  - Add four `EnvironmentVariables` entries to `OrchestratorRuntimeEndpoint`: `KNOWLEDGE_BASE_ID: Fn::ImportValue: !Sub "${KnowledgeStackName}-KnowledgeBaseId"`, `KB_TOP_K: !Ref KB_TOP_K`, `KB_RELEVANCE_THRESHOLD: !Ref KB_RELEVANCE_THRESHOLD`, `RERANKER_ENABLED: !Ref RERANKER_ENABLED`
  - Template must pass `cfn-lint` with zero errors after change
  - _Requirements: 10.1, 10.6, 10.7, 10.8_

- [x] 7. Update `cloudformation/parameters/application-orchestrator-prod.json`
  - Add four entries: `KnowledgeStackName: ace-agent-platform-knowledge-prod`, `KB_TOP_K: "5"`, `KB_RELEVANCE_THRESHOLD: "0.5"`, `RERANKER_ENABLED: "true"`
  - _Requirements: 10.2, 10.6, 10.7, 10.8_

- [x] 8. Checkpoint — validate all CloudFormation changes
  - Run `cfn-lint cloudformation/stacks/platform/knowledge.yaml cloudformation/stacks/foundation/identity.yaml cloudformation/stacks/application/agents/orchestrator.yaml` and confirm zero errors. Ask the user if questions arise.

- [x] 9. Add `sentence-transformers` to `pyproject.toml`
  - Add `"sentence-transformers>=2.0"` to the `dependencies` list in `[project]`
  - _Requirements: 5.2_

- [x] 10. Implement `src/rag/reranker.py`
  - Replace the `# TODO: implement` stub with the full `build_reranker` function
  - Import `ContextualCompressionRetriever` from `langchain.retrievers`, `CrossEncoderReranker` from `langchain.retrievers.document_compressors`, `BaseRetriever` from `langchain_core.retrievers`
  - Set `_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"`
  - Implement `build_reranker(base_retriever: BaseRetriever) -> ContextualCompressionRetriever`: instantiate `CrossEncoderReranker(model_name=_MODEL_NAME, top_n=None)`, wrap in `ContextualCompressionRetriever(base_compressor=compressor, base_retriever=base_retriever)`, return it
  - _Requirements: 5.2, 5.5_

- [x] 11. Implement `src/rag/retriever.py`
  - Replace the `# TODO: implement` stub with the full `build_kb_retriever` function
  - Import `AmazonKnowledgeBasesRetriever` from `langchain_aws`, `BaseRetriever` from `langchain_core.retrievers`
  - Implement `build_kb_retriever(knowledge_base_id: str, top_k: int = 5, metadata_filter: dict | None = None, reranker_enabled: bool = True) -> BaseRetriever`
  - Build `retrieval_config` with `vectorSearchConfiguration.numberOfResults = top_k`; if `metadata_filter` is provided, add it as `filter` inside `vectorSearchConfiguration`
  - Instantiate `AmazonKnowledgeBasesRetriever(knowledge_base_id=knowledge_base_id, retrieval_config=retrieval_config)` — no boto3 clients directly
  - When `reranker_enabled=True`: import `build_reranker` from `src.rag.reranker` and return `build_reranker(base_retriever)`; otherwise return `base_retriever`
  - _Requirements: 4.1, 4.3, 4.5, 5.5_

- [x] 12. Fully rewrite `src/orchestrator/nodes/retrieve_knowledge.py`
  - Read env vars at node entry: `KNOWLEDGE_BASE_ID`, `KB_TOP_K` (int, default 5), `KB_RELEVANCE_THRESHOLD` (float, default 0.5), `RERANKER_ENABLED` (bool, default true)
  - Open OTEL span `knowledge.retrieve` via `opentelemetry.trace.get_tracer(__name__)`
  - Extract `_compute_rag_metrics(scored_docs: list[tuple[Document, float]], threshold: float, top_k: int) -> tuple[float, float]` as a pure module-level helper: `relevant_in_top_k = sum(1 for _, s in scored_docs[:top_k] if s >= threshold)`, `total_relevant = sum(1 for _, s in scored_docs if s >= threshold)`, return `(relevant_in_top_k / top_k if top_k > 0 else 0.0, relevant_in_top_k / total_relevant if total_relevant > 0 else 0.0)`
  - **KB path** (when `KNOWLEDGE_BASE_ID` is set):
    - Call `build_kb_retriever(knowledge_base_id, top_k=top_k, reranker_enabled=reranker_enabled)` from `src.rag.retriever`
    - Call `retriever.invoke(query)` → `docs`; when `OTEL_STACK=local`, pass `config={"callbacks": [get_langfuse_handler()]}` on the invoke call
    - Apply threshold filter: keep docs where `doc.metadata.get("relevance_score", 1.0) >= threshold`; emit `span.add_event("doc_excluded", attributes={"doc_id": ..., "score": ..., "threshold": ...})` for each excluded doc
    - When all docs excluded, emit `span.add_event("all_docs_excluded", attributes={"threshold": threshold, "docs_retrieved": len(docs)})`
    - Build `scored_docs` list of `(doc, doc.metadata.get("relevance_score", 1.0))` for included docs
    - Compute `precision_at_k`, `recall_at_k` via `_compute_rag_metrics`; set to `None` when `RERANKER_ENABLED=false`
    - Build `citations` list: for each included doc, `{"title": meta.get("title") or meta.get("source", "unknown"), "url": meta.get("url") or meta.get("source", "unknown"), "timestamp": now_iso}`
    - Set span attributes: `rag.query_hash` (SHA-256 first 16 chars), `rag.k`, `rag.docs_retrieved`, `rag.docs_included`, `rag.reranker_applied`, `rag.precision_at_k`, `rag.recall_at_k`
    - On any exception: set `state["error"] = {"type": exc.__class__.__name__, "message": str(exc)}`; emit `span.add_event("kb_retrieval_error", ...)`; do NOT fall back to `FIXTURE_DOCS`; return `{**state, "error": {...}}`
  - **Mock path** (when `KNOWLEDGE_BASE_ID` is not set): use `FIXTURE_DOCS`; skip threshold; set `precision_at_k=None`, `recall_at_k=None`; set span attributes with `rag.reranker_applied=false`
  - Return `{**state, "context_window": initial_cw + included_docs, "citations": citations}` on success
  - Remove the silent `except: docs = list(FIXTURE_DOCS)` fallback that currently exists when `KNOWLEDGE_BASE_ID` is set
  - _Requirements: 4.1–4.6, 5.1–5.5, 6.1–6.5, 7.1–7.5, 8.1–8.5, 9.1–9.4, 10.3–10.4, 12.1, 12.3–12.4_

- [x] 13. Apply targeted changes to `src/orchestrator/nodes/aggregate_results.py`
  - Replace the citation-building loop (the `for doc in context_window` block that builds `citations`) with `citations = state.get("citations", [])`
  - Remove the `now_iso` variable and the `_kb_docs` variable if they are only used by the removed citation loop
  - Add error detection before the LLM call: `if state.get("error"): err = state["error"]; diagnostic = f"⚠️ Knowledge retrieval failed ({err.get('type', 'unknown')}): {err.get('message', '')}. The plan below may be less accurate — no KB context was available."`; prepend `diagnostic + "\n\n"` to `final_response` after it is built (both mock and LLM paths)
  - _Requirements: 8.5, 12.2_

- [x] 14. Checkpoint — verify Python implementation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Create `tests/unit/test_pbt_rag_properties.py`
  - [x] 15.1 Add module-level setup: `os.environ.setdefault` stubs for `MOCK_STORAGE` and `MOCK_PROMPTS`; inject `langchain_aws` stub into `sys.modules` with `AmazonKnowledgeBasesRetriever = MagicMock()` and `ChatBedrock = MagicMock()` before any node import
  - [x] 15.2 Add Hypothesis strategies: `st_document(with_url, with_title)`, `st_scored_docs(min_size, max_size)`, `st_threshold()`, `st_top_k()`, `st_context_window()`; add `_make_state(**overrides)` helper matching the full `OrchestratorState` schema
  - [x] 15.3 Write property test for Property 11 — Context Window Monotonic Growth
    - **Property 11: Context Window Monotonic Growth**
    - **Validates: Requirements 9.2, 9.3, 9.4**
    - `@given(initial_cw=st_context_window(), new_docs=st.lists(st_document(), min_size=0, max_size=5))`; set `KNOWLEDGE_BASE_ID`, `KB_RELEVANCE_THRESHOLD=0.0`, `RERANKER_ENABLED=false`; attach `relevance_score=1.0` to all `new_docs`; patch `build_kb_retriever` to return a mock retriever that returns `new_docs`; call `retrieve_knowledge(state)`; assert `all(doc in result["context_window"] for doc in initial_cw)`
  - [x] 15.4 Write property test for Property 18 — Citation Completeness
    - **Property 18: Citation Completeness for Every Retrieved Document**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    - `@given(docs=st.lists(st.one_of(st_document(True,True), st_document(False,True), st_document(True,False), st_document(False,False)), min_size=1, max_size=8))`; set `KNOWLEDGE_BASE_ID`, `KB_RELEVANCE_THRESHOLD=0.0`, `RERANKER_ENABLED=false`; attach `relevance_score=1.0`; patch `build_kb_retriever`; call `retrieve_knowledge`; assert `len(citations) == len(docs)` and each citation has non-empty `title`, `url`, `timestamp`
  - [x] 15.5 Write property test for Property 24 — RAG Metric Computation Correctness
    - **Property 24: RAG Metric Computation Correctness**
    - **Validates: Requirements 7.1, 7.2**
    - `@given(scored_docs=st_scored_docs(min_size=1, max_size=10), threshold=st_threshold(), top_k=st_top_k())`; import `_compute_rag_metrics` from `src.orchestrator.nodes.retrieve_knowledge`; compute reference values inline; assert `abs(precision - expected_precision) < 1e-9` and `abs(recall - expected_recall) < 1e-9`
  - [x] 15.6 Write property test for Property 25 — Re-Ranked Order Preserved in Context Window
    - **Property 25: Re-Ranked Order Preserved in Context Window**
    - **Validates: Requirements 5.1, 5.4**
    - `@given(scored_docs=st_scored_docs(min_size=2, max_size=8))`; set `KNOWLEDGE_BASE_ID`, `KB_RELEVANCE_THRESHOLD=0.0`, `RERANKER_ENABLED=true`; sort `scored_docs` descending by score; attach `relevance_score` to each doc metadata; patch `build_kb_retriever` and `src.rag.retriever.build_reranker` so the reranker mock returns docs in sorted order; call `retrieve_knowledge`; assert `result["context_window"] == reranked_docs`
  - [x] 15.7 Write property test for Property 26 — Below-Threshold Documents Excluded
    - **Property 26: Below-Threshold Documents Excluded from Context Window**
    - **Validates: Requirements 6.1, 6.4**
    - `@given(scored_docs=st_scored_docs(min_size=1, max_size=10), threshold=st_threshold())`; set `KNOWLEDGE_BASE_ID`, `KB_RELEVANCE_THRESHOLD=str(threshold)`, `RERANKER_ENABLED=false`; attach `relevance_score` from scored pair to each doc; patch `build_kb_retriever`; call `retrieve_knowledge`; assert every doc in `result["context_window"]` has `relevance_score >= threshold`

- [x] 16. Final checkpoint — Ensure all tests pass
  - Run `python -m pytest tests/unit/test_pbt_rag_properties.py -v --tb=short` and confirm all property tests pass. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Deploy order is strictly: `knowledge.yaml` → `identity.yaml` → `orchestrator.yaml` (cross-stack `Fn::ImportValue` dependency chain)
- `_compute_rag_metrics` must be a module-level pure function in `retrieve_knowledge.py` — Property 24 imports it directly
- The `retrieve_knowledge` node imports only from `src.rag.retriever` — never from `src.rag.reranker` directly (Req 5.5)
- `KNOWLEDGE_BASE_ID` is not added to `local.json` — local KB usage is opt-in via `.env`
- The silent `except: docs = list(FIXTURE_DOCS)` fallback in the current `retrieve_knowledge.py` is removed when `KNOWLEDGE_BASE_ID` is set (Task 12)
- Property tests require no AWS credentials — all AWS interactions are mocked via `unittest.mock.patch`
