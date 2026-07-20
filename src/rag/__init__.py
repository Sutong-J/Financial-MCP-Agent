"""RAG 模块 - 分析报告切块、向量索引与语义检索。"""
from src.rag.query_router import RetrievalScope, classify_retrieval_scope, scope_label

__all__ = [
    "ReportRAG",
    "RetrievedChunk",
    "RetrievalScope",
    "classify_retrieval_scope",
    "get_report_rag",
    "is_empty_retrieval",
    "scope_label",
]


def __getattr__(name: str):
    if name in {"ReportRAG", "get_report_rag", "is_empty_retrieval", "RetrievedChunk"}:
        from src.rag.service import ReportRAG, RetrievedChunk, get_report_rag, is_empty_retrieval

        mapping = {
            "ReportRAG": ReportRAG,
            "RetrievedChunk": RetrievedChunk,
            "get_report_rag": get_report_rag,
            "is_empty_retrieval": is_empty_retrieval,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
