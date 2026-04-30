from langchain_aws import AmazonKnowledgeBasesRetriever
from langchain_core.retrievers import BaseRetriever


def build_kb_retriever(
    knowledge_base_id: str,
    top_k: int = 5,
    metadata_filter: dict | None = None,
    reranker_enabled: bool = True,
) -> BaseRetriever:
    """
    Returns a retriever for the given KB ID.

    When reranker_enabled=True, wraps AmazonKnowledgeBasesRetriever in a
    ContextualCompressionRetriever (CrossEncoderReranker) via build_reranker()
    from src.rag.reranker. The retrieve_knowledge node imports only this
    function — never src.rag.reranker directly (Req 5.5).

    metadata_filter is passed as filter inside vectorSearchConfiguration.
    No boto3 clients are instantiated directly.
    """
    retrieval_config: dict = {
        "vectorSearchConfiguration": {"numberOfResults": top_k}
    }
    if metadata_filter:
        retrieval_config["vectorSearchConfiguration"]["filter"] = metadata_filter

    base_retriever = AmazonKnowledgeBasesRetriever(
        knowledge_base_id=knowledge_base_id,
        retrieval_config=retrieval_config,
    )

    if reranker_enabled:
        import src.rag.reranker as _reranker_mod
        return _reranker_mod.build_reranker(base_retriever)

    return base_retriever
