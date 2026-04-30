from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_core.retrievers import BaseRetriever

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def build_reranker(base_retriever: BaseRetriever) -> ContextualCompressionRetriever:
    """
    Wraps base_retriever in a ContextualCompressionRetriever backed by a
    CrossEncoderReranker using cross-encoder/ms-marco-MiniLM-L-6-v2.

    Requires sentence-transformers in pyproject.toml dependencies.
    Returns a retriever whose .invoke(query) returns documents sorted by
    descending cross-encoder relevance score.
    """
    compressor = CrossEncoderReranker(model_name=_MODEL_NAME, top_n=None)
    return ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,
    )
