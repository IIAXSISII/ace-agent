# Requirements: F03 — Knowledge & RAG

> Implements: Req 5, 12, 17 from vision.md  
> Depends on: F01 (Core Orchestrator — LangGraph graph with mock `retrieve_knowledge` node), F02 (Foundation Infra — `data.yaml` and `storage.yaml` deployed)  
> Deferred to later features: Evaluation pipeline metrics (F09), production observability stack (F05), sub-agent integrations (F04+).  
> Local simplifications: When `KNOWLEDGE_BASE_ID` is unset, the `retrieve_knowledge` node falls back to the existing mock retriever — no AWS credentials required for local dev without a KB. When `RERANKER_ENABLED=false`, the re-ranking step is skipped (useful for local dev without a cross-encoder model).

---

## Introduction

F03 makes the Orchestrator knowledge-grounded. It provisions the Bedrock Knowledge Bases infrastructure (`cloudformation/stacks/platform/knowledge.yaml`), replaces the mock retriever in the `retrieve_knowledge` LangGraph node with the real `AmazonKnowledgeBasesRetriever`, adds a re-ranking step via `ContextualCompressionRetriever`, enforces a relevance threshold with exclusion logging, and records per-query RAG metrics (precision@K, recall@K) in execution traces and Langfuse.

The feature is complete when a request about a known service returns a plan that cites relevant runbook content from the Knowledge Base, with source title, URL, and retrieval timestamp included in the response.

**What F03 does NOT deliver:**
- Document ingestion tooling or connectors (Confluence, GitHub sync pipelines) — documents are loaded into the S3 source bucket manually or via external pipelines
- Offline RAGAS evaluation pipeline — deferred to F09
- Production observability dashboards — deferred to F05
- Sub-agent integrations — deferred to F04+

---

## Glossary

- **Knowledge_Stack**: The CloudFormation stack (`cloudformation/stacks/platform/knowledge.yaml`) that provisions the Bedrock Knowledge Base, S3 source bucket, S3 Vectors index, and IAM roles for F03.
- **Knowledge_Base**: The Amazon Bedrock Knowledge Base instance provisioned by the Knowledge_Stack, backed by S3 Vectors as the vector store and an S3 source bucket as the document source.
- **KB_Retriever**: The `AmazonKnowledgeBasesRetriever` instance from `langchain-aws` that queries the Knowledge_Base. Instantiated in `src/rag/retriever.py` and used by the `retrieve_knowledge` node.
- **Reranker**: The `ContextualCompressionRetriever` wrapping a `CrossEncoderReranker` (or `LLMChainFilter` as fallback) that re-orders KB retrieval results by relevance before they enter the context window. Implemented in `src/rag/reranker.py`.
- **Relevance_Threshold**: The minimum relevance score a retrieved document must meet to be included in the context window. Documents below this threshold are excluded and logged.
- **Exclusion_Log_Entry**: A structured log record written when a document is excluded due to falling below the Relevance_Threshold, containing the document ID and its relevance score.
- **RAG_Metrics**: Per-query precision@K and recall@K values computed after retrieval and re-ranking, recorded in the execution trace span and in Langfuse (local dev).
- **Chunking_Config**: The per-document-type ingestion configuration applied to the Bedrock KB managed pipeline, specifying chunking strategy, chunk size (tokens), and overlap (tokens).
- **S3_Source_Bucket**: The S3 bucket provisioned by the Knowledge_Stack that holds source documents for Bedrock KB ingestion. Documents placed here are indexed by the managed ingestion pipeline.
- **S3_Vectors_Index**: The Amazon S3 Vectors index provisioned by the Knowledge_Stack that stores the vector embeddings produced by the Bedrock KB embedding model.
- **Top_K**: The number of candidate documents returned by the KB_Retriever before re-ranking. Configurable via the `KB_TOP_K` environment variable; default is 5.
- **Citation**: A structured record attached to every KB-sourced claim in a response, containing the source document title, URL, and retrieval timestamp (UTC ISO-8601).
- **KB_KMS_Key**: The AWS KMS key provisioned by the Knowledge_Stack for encrypting the S3_Source_Bucket at rest. Managed via CloudFormation with `DeletionPolicy: Retain`.

---

## Requirements

### Requirement 1: Knowledge Stack — Bedrock KB, S3 Source, S3 Vectors

**User Story:** As a platform operator, I want the Bedrock Knowledge Base infrastructure provisioned as a CloudFormation stack, so that the Orchestrator has a managed, reproducible RAG backend without manual console operations.

> Implements: Req 12 (Vector Store and Semantic Search)

#### Acceptance Criteria

1. THE Knowledge_Stack SHALL provision a Bedrock Knowledge Base with Amazon S3 as the document source and Amazon S3 Vectors as the vector store backend.
2. THE Knowledge_Stack SHALL provision an S3_Source_Bucket for source documents with `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`.
3. THE Knowledge_Stack SHALL provision an S3_Vectors_Index for vector embeddings with `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`.
4. THE Knowledge_Stack SHALL enable server-side encryption on the S3_Source_Bucket using a KMS key (KB_KMS_Key) managed via the Knowledge_Stack (consistent with Req 28.2 from vision.md).
5. THE Knowledge_Stack SHALL block all public access on the S3_Source_Bucket (`BlockPublicAcls`, `BlockPublicPolicy`, `IgnorePublicAcls`, `RestrictPublicBuckets` all set to `true`) (consistent with Req 28.3 from vision.md).
6. THE Knowledge_Stack SHALL export the S3 source bucket KMS key ARN via `Outputs` as `KnowledgeSourceBucketKmsKeyArn` using the naming convention `${AWS::StackName}-KnowledgeSourceBucketKmsKeyArn`, and SHALL apply `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` to the KB_KMS_Key.
7. THE Knowledge_Stack SHALL provision a dedicated IAM role for the Bedrock KB service with the minimum permissions required: `s3:GetObject`, `s3:ListBucket` on the S3_Source_Bucket, `s3vectors:*` on the S3_Vectors_Index and its indexes, and `bedrock:InvokeModel` on the Titan Embeddings V2 foundation model ARN (`arn:aws:bedrock:${AWS::Region}::foundation-model/amazon.titan-embed-text-v2:0`) — required for the managed ingestion pipeline to embed documents.
8. THE Knowledge_Stack SHALL export `KnowledgeBaseId` and `KnowledgeBaseArn` via `Outputs` using the naming convention `${AWS::StackName}-<ResourceName>`.
9. THE Knowledge_Stack SHALL publish `KnowledgeBaseId` to SSM Parameter Store under `/${Application}/${Environment}/knowledge/knowledge-base-id`.
10. WHEN the Knowledge_Stack is deployed, THE Knowledge_Stack SHALL tag every resource with `env`, `application`, `created-with: CloudFormation`, `owners`, and `Stack: !Ref AWS::StackName` — matching the tagging convention used in all existing stacks (`storage.yaml`, `guardrails.yaml`, `memory.yaml`, etc.).
11. THE Knowledge_Stack SHALL pass `cfn-lint` with zero errors before deployment.
12. THE `cloudformation/parameters/platform-knowledge-prod.json` file SHALL be created with `Environment` and `Application` parameter entries, following the pattern of `platform-memory-prod.json` and `platform-guardrails-prod.json`. (Note: the Makefile `params-file` function resolves `platform-knowledge-prod.json` first before falling back to `prod.json` — the `KnowledgeStackName` export does not need to go into `prod.json` for the knowledge stack itself; it is only needed in the stacks that import from knowledge, i.e. orchestrator and identity.)
13. THE `cloudformation/parameters/local.json` fallback already covers `Environment` and `Application`, which is all the knowledge stack needs for local deployment. No change to `local.json` is required for the knowledge stack — the Makefile `params-file` function will fall back to `local.json` correctly since no `platform-knowledge-local.json` file exists (consistent with the pattern for all other platform stacks).
14. THE `deploy-platform` Makefile target in `cloudformation/Makefile` SHALL be updated to add `knowledge.yaml` to both the lint list and the deploy sequence. The knowledge stack has no inter-platform dependencies, so order within the platform tier does not matter; it SHALL be added after the existing three stacks (`guardrails`, `memory`, `gateway`) for consistency.

---

### Requirement 2: Chunking Strategy per Document Type

**User Story:** As a platform operator, I want the Bedrock KB ingestion pipeline configured with a per-document-type chunking strategy, so that each source type is split in a way that preserves semantic coherence and maximises retrieval quality.

> Implements: Req 12 (Vector Store and Semantic Search)

#### Acceptance Criteria

1. THE Knowledge_Stack SHALL configure the Bedrock KB ingestion pipeline with the following chunking strategies per document type, using the valid Bedrock KB `ChunkingStrategy` values (`FIXED_SIZE`, `HIERARCHICAL`, `SEMANTIC`, `NONE`):
   - Confluence pages: `HIERARCHICAL`, max parent token size 1500, max child token size 300, overlap tokens 60
   - GitHub IaC files (Terraform, CloudFormation): `FIXED_SIZE`, 512 tokens, 64 token overlap
   - GitHub code files (Python, etc.): `FIXED_SIZE`, 512 tokens, 64 token overlap
   - GitHub README and documentation files: `HIERARCHICAL`, max parent token size 1500, max child token size 300, overlap tokens 60
   - Incident records: `FIXED_SIZE`, 256 tokens, 32 token overlap

   Note: Bedrock KB applies a single `ChunkingConfiguration` per data source — per-document-type chunking requires separate data sources per document type within the same Knowledge Base. THE Knowledge_Stack SHALL configure separate data source configurations for each document type category. **Service limit: Bedrock KB supports a maximum of 5 data sources per Knowledge Base. The original 6-type design (Confluence, IaC, Code, README, Incidents, Default) was reduced to 5 by removing the Default fallback data source. Miscellaneous documents should be placed in the most appropriate existing prefix.**
2. WHEN a source document does not match any of the 5 configured document type prefixes, the operator SHALL place it in the most semantically appropriate existing prefix (`confluence/`, `iac/`, `code/`, `readme/`, or `incidents/`). A separate default data source is not provisioned due to the Bedrock KB 5-data-source-per-KB service limit.
3. THE chunking configuration SHALL be expressed as CloudFormation resource properties on the Bedrock KB ingestion configuration — not as application code.

---

### Requirement 3: Incremental Ingestion and Source Sync

**User Story:** As a platform operator, I want the Knowledge Base to stay current with source documents, so that new runbooks and incident records are available for retrieval within 1 hour of being added to the S3 source bucket.

> Implements: Req 5.5, Req 12.4, Req 12.5

#### Acceptance Criteria

1. WHEN a new document is placed in the S3_Source_Bucket, THE Knowledge_Base managed ingestion pipeline SHALL index the document within 1 hour. Note: the 1-hour target is achieved by configuring the Bedrock KB data source sync schedule to run at least every 60 minutes; actual indexing latency depends on document size and Bedrock service capacity.
2. WHEN a document is deleted from the S3_Source_Bucket, THE Knowledge_Base managed ingestion pipeline SHALL remove the corresponding vectors from the S3_Vectors_Index within 1 hour. Note: the same 60-minute sync schedule applies; actual removal latency depends on Bedrock service capacity.
3. THE Knowledge_Base ingestion pipeline SHALL perform incremental ingestion — only new or modified documents SHALL be re-embedded on each sync cycle; unchanged documents SHALL NOT be re-processed.
4. THE Knowledge_Stack SHALL configure the Bedrock KB data source to point to the S3_Source_Bucket with the correct S3 prefix and sync schedule.

---

### Requirement 4: KB Retriever Integration in Orchestrator Graph

**User Story:** As a platform operator, I want the `retrieve_knowledge` LangGraph node to use the real `AmazonKnowledgeBasesRetriever` when a Knowledge Base is available, so that the Orchestrator grounds its plans in actual internal documentation.

> Implements: Req 5.2, Req 5.3, Req 12.2

#### Acceptance Criteria

1. WHEN `KNOWLEDGE_BASE_ID` is set, THE `retrieve_knowledge` node SHALL instantiate a KB_Retriever using `AmazonKnowledgeBasesRetriever` from `langchain-aws` with the configured `KNOWLEDGE_BASE_ID` and `Top_K` (default 5, overridable via `KB_TOP_K` env var). The existing hardcoded `numberOfResults: 5` in `retrieve_knowledge.py` SHALL be replaced with the value of `KB_TOP_K`.
2. WHEN `KNOWLEDGE_BASE_ID` is not set, THE `retrieve_knowledge` node SHALL fall back to the existing mock retriever (fixture documents) — no AWS credentials are required in this mode.
3. THE KB_Retriever SHALL support metadata filtering by source system, document type, team, and date range on all retrieval queries, passed as `filter` inside `vectorSearchConfiguration` in the `retrieval_config` parameter of `AmazonKnowledgeBasesRetriever`.
4. WHEN the KB_Retriever returns results, THE `retrieve_knowledge` node SHALL append all returned documents to `OrchestratorState.context_window`.
5. THE `retrieve_knowledge` node SHALL NOT instantiate boto3 clients directly — all AWS interactions SHALL go through `AmazonKnowledgeBasesRetriever` from `langchain-aws`.
6. THE `retrieve_knowledge` node SHALL use the `raw_request` field from `OrchestratorState` as the retrieval query.

---

### Requirement 5: Re-Ranking Step

**User Story:** As a platform operator, I want retrieved documents re-ranked by a cross-encoder before they enter the context window, so that the most relevant documents appear first and lower-quality candidates are deprioritised.

> Implements: Req 17 (RAG Quality and Retrieval Evaluation)

#### Acceptance Criteria

1. WHEN `RERANKER_ENABLED` is `true` (default), THE `retrieve_knowledge` node SHALL pass KB_Retriever results through the Reranker before appending them to the context window.
2. THE Reranker SHALL be implemented as a `ContextualCompressionRetriever` wrapping a `CrossEncoderReranker` in `src/rag/reranker.py`. The `sentence-transformers` package is required for `CrossEncoderReranker` and SHALL be added to `pyproject.toml` dependencies.
3. WHEN `RERANKER_ENABLED` is `false`, THE `retrieve_knowledge` node SHALL skip the Reranker and append KB_Retriever results directly to the context window — this mode is intended for local dev without a cross-encoder model.
4. THE documents appended to `OrchestratorState.context_window` SHALL reflect the re-ranked order — not the original retrieval order — when the Reranker produces a different ordering.
5. THE Reranker SHALL be instantiated in `src/rag/reranker.py` and imported by `src/rag/retriever.py` — the `retrieve_knowledge` node SHALL not contain reranker logic directly.

---

### Requirement 6: Relevance Threshold Filtering

**User Story:** As a platform operator, I want documents below a minimum relevance score excluded from the context window, so that low-quality retrievals do not degrade plan quality or introduce noise.

> Implements: Req 17 (RAG Quality and Retrieval Evaluation)

#### Acceptance Criteria

1. WHEN a retrieved document's relevance score is below the configured `KB_RELEVANCE_THRESHOLD` (default 0.5, overridable via env var), THE `retrieve_knowledge` node SHALL exclude that document from `OrchestratorState.context_window`.
2. WHEN a document is excluded due to falling below the Relevance_Threshold, THE `retrieve_knowledge` node SHALL write an Exclusion_Log_Entry to the execution trace containing the document ID and its relevance score.
3. THE Exclusion_Log_Entry SHALL be emitted as an OTEL span event on the `knowledge.retrieve` span — it SHALL NOT be written to DynamoDB.
4. WHEN all retrieved documents fall below the Relevance_Threshold, THE `retrieve_knowledge` node SHALL append zero documents to the context window and SHALL emit a span event indicating zero documents passed the threshold.
5. IF `KNOWLEDGE_BASE_ID` is not set (mock mode), THE relevance threshold filtering SHALL be skipped — all mock fixture documents SHALL be included in the context window.

---

### Requirement 7: RAG Metrics — Precision@K and Recall@K

**User Story:** As a platform operator, I want per-query precision@K and recall@K recorded in execution traces, so that I can monitor retrieval quality over time and identify degradation.

> Implements: Req 17 (RAG Quality and Retrieval Evaluation)

#### Acceptance Criteria

1. WHEN the `retrieve_knowledge` node completes retrieval and re-ranking, THE node SHALL compute approximated precision@K and recall@K for the query using the re-ranker relevance scores as a proxy for relevance: a document is considered "relevant" if its re-ranker score is >= `KB_RELEVANCE_THRESHOLD`. The formulas are: `precision@K = (docs with score >= threshold in top K) / K`, `recall@K = (docs with score >= threshold in top K) / (total docs with score >= threshold)`. WHEN `RERANKER_ENABLED=false`, precision@K and recall@K SHALL be set to `null` (no scores available to approximate relevance).
2. THE computed precision@K and recall@K values SHALL be recorded as attributes on the `knowledge.retrieve` OTEL span: `rag.precision_at_k` and `rag.recall_at_k`.
3. WHEN `OTEL_STACK=local`, THE `retrieve_knowledge` node SHALL record precision@K and recall@K in Langfuse by passing the handler returned by `get_langfuse_handler()` from `src/observability/langfuse.py` via `config={"callbacks": [handler]}` — consistent with the pattern used in `classify_request.py`, `generate_plan.py`, and `aggregate_results.py`.
4. THE `knowledge.retrieve` OTEL span SHALL also record: `rag.query_hash` (SHA-256 of the query string), `rag.k` (Top_K value), `rag.docs_retrieved` (count before threshold), `rag.docs_included` (count after threshold), and `rag.reranker_applied` (boolean).
5. WHEN `KNOWLEDGE_BASE_ID` is not set (mock mode), THE `retrieve_knowledge` node SHALL emit the span attributes with `rag.reranker_applied=false` and SHALL set `rag.precision_at_k` and `rag.recall_at_k` to `null` — mock results have no ground truth.

---

### Requirement 8: Knowledge Base Citation in Responses

**User Story:** As an internal team member, I want every piece of knowledge cited in a response to include the source document title, URL, and retrieval timestamp, so that I can verify the information and navigate to the original source.

> Implements: Req 5.6

#### Acceptance Criteria

1. WHEN the Orchestrator includes KB-retrieved content in a response, THE Orchestrator SHALL attach a Citation for each document used, containing: `title` (from document metadata), `url` (from document metadata), and `timestamp` (UTC ISO-8601 timestamp of the retrieval call). Note: the field name in `OrchestratorState.citations` is `timestamp`, consistent with the existing type definition in `graph.py`.
2. THE Citations SHALL be stored in `OrchestratorState.citations` and included in the final response payload.
3. WHEN a document's metadata does not contain a `url` field, THE Orchestrator SHALL use the S3 object key as the citation URL.
4. WHEN a document's metadata does not contain a `title` field, THE Orchestrator SHALL use the S3 object key as the citation title.
5. THE `retrieve_knowledge` node SHALL populate citation metadata on each `Document` object at retrieval time — the `aggregate_results` node SHALL read citations from `OrchestratorState.citations` populated by `retrieve_knowledge`, not rebuild them from the context window at aggregation time. The existing citation-building logic in `aggregate_results.py` (lines that iterate `context_window` to build citations) SHALL be removed and replaced with a read of `state.get("citations", [])`.

---

### Requirement 9: Context Window Accumulation Across Steps

**User Story:** As a platform operator, I want KB retrieval results to be present in every sub-agent's context window throughout the entire request lifecycle, so that sub-agents can reference internal documentation when executing their steps.

> Implements: Req 5.3, Req 5.4 — Correctness Property 11

#### Acceptance Criteria

1. THE `retrieve_knowledge` node SHALL execute before `generate_plan` in the LangGraph graph — KB results SHALL be available when the plan is generated.
2. WHEN a sub-agent is invoked, THE Orchestrator SHALL include all documents in `OrchestratorState.context_window` (KB results + prior step outputs) in the sub-agent's input context.
3. THE context window SHALL grow monotonically across steps — no document or prior step output SHALL be removed from `OrchestratorState.context_window` between steps.
4. WHEN a sub-agent returns a result, THE Orchestrator SHALL append the result to `OrchestratorState.context_window` before invoking the next sub-agent.

---

### Requirement 10: KNOWLEDGE_BASE_ID Environment Variable Wiring

**User Story:** As a platform operator, I want the `KNOWLEDGE_BASE_ID` environment variable sourced from the CloudFormation stack output in production and from a real Bedrock KB ID locally (when available), so that the retriever is wired correctly in both environments without code changes.

> Implements: Req 12.6

#### Acceptance Criteria

1. THE Orchestrator_Stack SHALL set the `KNOWLEDGE_BASE_ID` environment variable on the Orchestrator AgentCore Runtime endpoint by importing `KnowledgeBaseId` from the Knowledge_Stack output via `Fn::ImportValue` using the `KnowledgeStackName` parameter. The `orchestrator.yaml` template SHALL add `KnowledgeStackName` as a new `Parameters` entry alongside the existing `NetworkingStackName`, `IdentityStackName`, etc. The default value in the template SHALL be `ace-agent-platform-knowledge-prod` — consistent with the prod.json naming convention. (Note: the existing template defaults such as `ace-agent-foundation-networking-production` use a stale `production` suffix; the new parameter SHALL use `prod` to match the actual prod.json stack name values.)
2. THE `cloudformation/parameters/application-orchestrator-prod.json` file SHALL be updated to include a `KnowledgeStackName` parameter entry (value: `ace-agent-platform-knowledge-prod`). (Note: the Makefile `params-file` function resolves `application-orchestrator-prod.json` first for the orchestrator stack — this file already exists and is the correct target, not `prod.json`.)
3. WHEN `KNOWLEDGE_BASE_ID` is set in the local environment (`.env` file), THE `retrieve_knowledge` node SHALL use the real KB_Retriever — this requires valid AWS credentials with `bedrock-agent-runtime:Retrieve` permission.
4. WHEN `KNOWLEDGE_BASE_ID` is not set in the local environment, THE `retrieve_knowledge` node SHALL use the mock retriever — no AWS credentials are required for this path.
5. THE `cloudformation/parameters/local.json` file SHALL NOT include a `KNOWLEDGE_BASE_ID` value — local KB usage is opt-in via the developer's `.env` file.
6. THE Orchestrator_Stack SHALL set the `KB_TOP_K` environment variable on the Orchestrator AgentCore Runtime endpoint, sourced from the `KB_TOP_K` CloudFormation parameter added to `application-orchestrator-prod.json` (default: `5`).
7. THE Orchestrator_Stack SHALL set the `KB_RELEVANCE_THRESHOLD` environment variable on the Orchestrator AgentCore Runtime endpoint, sourced from the `KB_RELEVANCE_THRESHOLD` CloudFormation parameter added to `application-orchestrator-prod.json` (default: `0.5`).
8. THE Orchestrator_Stack SHALL set the `RERANKER_ENABLED` environment variable on the Orchestrator AgentCore Runtime endpoint, sourced from the `RERANKER_ENABLED` CloudFormation parameter added to `application-orchestrator-prod.json` (default: `true`). Note: `KB_TOP_K`, `KB_RELEVANCE_THRESHOLD`, and `RERANKER_ENABLED` are CloudFormation Parameters on `orchestrator.yaml` that the template then sets as `EnvironmentVariables` on the runtime endpoint — they are added to `application-orchestrator-prod.json` as CloudFormation parameter overrides, not as raw environment variable entries.

---

### Requirement 11: IAM Permissions for KB Retrieval

**User Story:** As a platform operator, I want the Orchestrator's IAM execution role updated with the minimum permissions required to query the Knowledge Base, so that retrieval works in production without over-privileged access.

> Implements: Req 12.6

#### Acceptance Criteria

1. THE Identity_Stack SHALL add `bedrock-agent-runtime:Retrieve` to the `OrchestratorExecutionRole` inline policy in `cloudformation/stacks/foundation/identity.yaml`, scoped to the Knowledge_Stack's `KnowledgeBaseArn` via `Fn::ImportValue`. The update goes to `identity.yaml` because that stack owns the `OrchestratorExecutionRole` — `orchestrator.yaml` only imports the role ARN. `identity.yaml` SHALL add a `KnowledgeStackName` parameter (alongside existing parameters) to resolve the `Fn::ImportValue` reference. THE `cloudformation/parameters/foundation-identity-prod.json` file SHALL be updated to include a `KnowledgeStackName` parameter entry (value: `ace-agent-platform-knowledge-prod`).
2. THE Orchestrator IAM role SHALL NOT be granted `bedrock-agent-runtime:*` — only the `Retrieve` action is required for F03.
3. THE Knowledge_Stack IAM role for the Bedrock KB service SHALL be granted `s3:GetObject` and `s3:ListBucket` on the S3_Source_Bucket, `bedrock:InvokeModel` scoped to the Titan Embeddings V2 foundation model ARN (required for the KB service to generate vector embeddings during ingestion), and the minimum S3 Vectors permissions required for indexing — no broader S3 or Bedrock permissions.
4. THE Knowledge_Stack IAM role for the Bedrock KB service SHALL have a trust policy allowing `bedrock.amazonaws.com` to assume it — consistent with the trust policy pattern in `identity.yaml` for `bedrock-agentcore.amazonaws.com`.

---

### Requirement 12: KB Retrieval Error Handling

**User Story:** As a platform operator, I want KB retrieval failures handled gracefully, so that a transient Bedrock API error does not silently fall back to stale fixture documents in production.

> Implements: Req 5.2

#### Acceptance Criteria

1. WHEN `KNOWLEDGE_BASE_ID` is set and the `AmazonKnowledgeBasesRetriever` raises an exception, THE `retrieve_knowledge` node SHALL NOT silently fall back to fixture documents — it SHALL propagate the error to `OrchestratorState.error` and emit an OTEL span event with the exception type and message.
2. WHEN a KB retrieval error is recorded in `OrchestratorState.error`, THE `aggregate_results` node SHALL detect the error in state, include a diagnostic message in `final_response` indicating that knowledge retrieval failed and the plan may be less accurate, and surface it to the user in the final response payload.
3. THE silent fixture fallback on exception (currently present in `src/orchestrator/nodes/retrieve_knowledge.py`) SHALL be removed when `KNOWLEDGE_BASE_ID` is set — the fallback is only valid when `KNOWLEDGE_BASE_ID` is unset.
4. WHEN `KNOWLEDGE_BASE_ID` is not set, THE `retrieve_knowledge` node SHALL use fixture documents without error — this is the intended local dev path, not a fallback from a failure.

---

## Correctness Properties

The following correctness properties from `architecture.md` are validated by F03. Each maps to one or more acceptance criteria above.

### Property 11: Context Window Accumulation

*For any* multi-step execution, each sub-agent invocation SHALL receive a context window that includes all KB retrieval results from request intake and all outputs from all previously completed steps. The context window SHALL grow monotonically — no prior information SHALL be dropped between steps.

**Validated by:** Requirement 9 (all criteria)  
**Test approach:** Property-based test — generate arbitrary sequences of retrieval results and step outputs; assert that each successive context window is a superset of the previous one.

---

### Property 18: Knowledge Base Citation Completeness

*For any* response that uses knowledge retrieved from the Knowledge Base, every piece of cited knowledge SHALL include the source document title, URL, and retrieval timestamp. No KB-sourced claim SHALL appear in a response without a citation.

**Validated by:** Requirement 8 (criteria 1–5)  
**Test approach:** Property-based test — generate arbitrary sets of retrieved documents with varying metadata completeness; assert that every document in the context window has a corresponding Citation with non-empty `title`, `url`, and `timestamp` fields (matching the `OrchestratorState.citations` schema).

---

### Property 24: RAG Metric Computation Correctness

*For any* Knowledge Base query result, the computed precision@K and recall@K values SHALL be mathematically correct approximations using re-ranker relevance scores as a proxy for relevance (a document is "relevant" if its score >= `KB_RELEVANCE_THRESHOLD`): `precision@K = (docs with score >= threshold in top K) / K`, `recall@K = (docs with score >= threshold in top K) / (total docs with score >= threshold)`. WHEN `RERANKER_ENABLED=false`, both values SHALL be `null`.

**Validated by:** Requirement 7 (criteria 1–2)  
**Test approach:** Property-based test — generate arbitrary (retrieved_docs_with_scores, threshold, K) triples; assert that the computed precision@K and recall@K match the reference formula exactly. When reranker is disabled, assert both values are null. Round-trip: compute metrics, verify against manual calculation.

---

### Property 25: Re-Ranking Applied Before Context Inclusion

*For any* set of KB retrieval results, the Reranker SHALL be invoked and the results included in the context window SHALL reflect the re-ranked order — not the original retrieval order — when the Reranker produces a different ordering.

**Validated by:** Requirement 5 (criteria 1, 4)  
**Test approach:** Property-based test — generate arbitrary lists of documents with assigned relevance scores; assert that the order of documents in the context window matches the descending relevance score order produced by the Reranker, not the original retrieval order.

---

### Property 26: Below-Threshold Documents Excluded and Logged

*For any* retrieved document whose relevance score falls below the configured minimum threshold, that document SHALL be excluded from the context window AND an Exclusion_Log_Entry SHALL be written containing the document ID and score. No below-threshold document SHALL silently appear in the context window.

**Validated by:** Requirement 6 (criteria 1–4)  
**Test approach:** Property-based test — generate arbitrary lists of documents with scores spanning above and below the threshold; assert that (a) no document with score < threshold appears in the context window, and (b) every excluded document has a corresponding Exclusion_Log_Entry with matching document ID and score.
