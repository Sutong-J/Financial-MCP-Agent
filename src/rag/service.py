from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from pathlib import Path

from src.rag.chunker import chunk_for_rag, make_chunk_id
from src.rag.hybrid import BM25Index, rrf_fuse
from src.rag.query_router import RetrievalScope
from src.rag.rerank import rerank_pairs

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAG_DIR = PROJECT_ROOT / "data" / "rag" / "chroma"
DEFAULT_TOP_K = 4
TOP_K_BY_SCOPE = {
    RetrievalScope.SESSION: 4,
    RetrievalScope.CROSS_SESSION: 6,
    RetrievalScope.COMPARE: 8,
}
DEFAULT_CANDIDATE_K = 20

EMPTY_RETRIEVAL_MARKERS = (
    "（未启用 RAG 检索或无可用向量库）",
    "（未检索到相关历史片段）",
    "（RAG 检索失败",
    "（未启用 RAG 检索）",
)

SOURCE_FIELDS = (
    ("final_report", "综合报告"),
    ("fundamental_analysis", "基本面"),
    ("technical_analysis", "技术面"),
    ("value_analysis", "估值"),
    ("news_analysis", "新闻"),
)


def _rag_enabled() -> bool:
    return os.getenv("RAG_ENABLED", "true").lower() not in {"0", "false", "no"}


def _embedding_configured() -> bool:
    return bool(
        os.getenv("OPENAI_COMPATIBLE_API_KEY")
        and os.getenv("OPENAI_COMPATIBLE_BASE_URL")
    )


def _hybrid_enabled() -> bool:
    return os.getenv("RAG_HYBRID_ENABLED", "true").lower() not in {"0", "false", "no"}


def _rag_backend() -> str:
    return (os.getenv("RAG_BACKEND") or "chroma").strip().lower()


def _candidate_k(final_k: int) -> int:
    configured = os.getenv("RAG_CANDIDATE_K")
    if configured and configured.isdigit():
        return max(int(configured), final_k)
    return max(DEFAULT_CANDIDATE_K, final_k * 4)


def _embed_texts(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY"),
        base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL"),
    )
    model = os.getenv("OPENAI_COMPATIBLE_EMBEDDING_MODEL", "text-embedding-3-small")
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def _prepare_chunks(
    session_id: str,
    data: dict[str, Any],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    docs: list[str] = []
    metas: list[dict[str, Any]] = []
    ids: list[str] = []
    company = str(data.get("company_name") or "")
    stock = str(data.get("stock_code") or "")

    for field, label in SOURCE_FIELDS:
        raw = data.get(field)
        if not raw or not str(raw).strip():
            continue
        rag_chunks = chunk_for_rag(
            str(raw),
            source=field,
            source_label=label,
            company_name=company,
            stock_code=stock,
        )
        for chunk in rag_chunks:
            docs.append(chunk.text)
            metas.append({
                "session_id": session_id,
                "source": field,
                "source_label": label,
                "company_name": company,
                "stock_code": stock,
                "heading": chunk.heading,
                "heading_level": chunk.heading_level,
                "breadcrumb": chunk.breadcrumb,
                "chunk_index": chunk.chunk_index,
                "char_count": chunk.char_count,
            })
            ids.append(make_chunk_id(session_id, field, chunk))
    return ids, docs, metas


@dataclass
class RetrievedChunk:
    id: str
    document: str
    metadata: dict[str, Any]
    distance: float | None = None
    rerank_score: float | None = None


class ReportRAG:
    """分析报告检索：支持 Chroma / Elasticsearch 双路召回 + BGE 重排。"""

    def __init__(self) -> None:
        self.backend = _rag_backend()
        self._bm25_cache: dict[str, BM25Index] = {}
        self._chroma = None
        self._es = None

        if self.backend == "elasticsearch":
            from src.rag.es_store import ElasticsearchRAGStore, es_configured

            if not es_configured():
                raise RuntimeError(
                    "RAG_BACKEND=elasticsearch 但未配置 ES_URL / ES_API_KEY"
                )
            self._es = ElasticsearchRAGStore()
            logger.info("ReportRAG backend=elasticsearch index=%s", self._es.index)
        else:
            import chromadb
            from chromadb.config import Settings

            RAG_DIR.mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(
                path=str(RAG_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("ReportRAG backend=chroma")

    def _collection(self, user_id: str):
        assert self._chroma is not None
        return self._chroma.get_or_create_collection(
            name=f"user_{user_id.replace('-', '_')}",
            metadata={"hnsw:space": "cosine"},
        )

    def _invalidate_bm25(self, user_id: str) -> None:
        self._bm25_cache.pop(user_id, None)

    def _get_bm25_index(self, user_id: str) -> BM25Index | None:
        cached = self._bm25_cache.get(user_id)
        if cached is not None:
            return cached
        try:
            collection = self._collection(user_id)
            payload = collection.get(include=["documents", "metadatas"])
            ids = list(payload.get("ids") or [])
            docs = list(payload.get("documents") or [])
            metas = list(payload.get("metadatas") or [])
            if not ids:
                return None
            index = BM25Index(ids, docs, metas)
            self._bm25_cache[user_id] = index
            return index
        except Exception as exc:
            logger.warning("Build BM25 index failed: %s", exc)
            return None

    def index_analysis(
        self,
        user_id: str,
        session_id: str,
        data: dict[str, Any],
    ) -> int:
        """将一次完整分析写入检索库，返回新增 chunk 数。"""
        if not _rag_enabled() or not _embedding_configured():
            return 0

        ids, docs, metas = _prepare_chunks(session_id, data)
        if not docs:
            return 0

        try:
            embeddings = _embed_texts(docs)
            if self.backend == "elasticsearch":
                assert self._es is not None
                self._es.delete_session(user_id, session_id)
                count = self._es.bulk_upsert(
                    user_id=user_id,
                    ids=ids,
                    documents=docs,
                    metadatas=metas,
                    embeddings=embeddings,
                )
                logger.info(
                    "ES indexed %s chunks for user=%s session=%s",
                    count, user_id, session_id,
                )
                return count

            collection = self._collection(user_id)
            existing = collection.get(where={"session_id": session_id})
            if existing and existing.get("ids"):
                collection.delete(ids=existing["ids"])
            collection.add(
                ids=ids,
                documents=docs,
                embeddings=embeddings,
                metadatas=metas,
            )
            self._invalidate_bm25(user_id)
            logger.info("Chroma indexed %s chunks for session %s", len(docs), session_id)
            return len(docs)
        except Exception as exc:
            logger.warning("RAG index failed: %s", exc)
            return 0

    def _build_where(
        self,
        *,
        scope: RetrievalScope,
        session_id: str | None,
    ) -> dict[str, Any] | None:
        if scope == RetrievalScope.SESSION and session_id:
            return {"session_id": session_id}
        return None

    def _format_results(self, docs: list[str], metas: list[dict[str, Any]], scope: RetrievalScope) -> str:
        headers = {
            RetrievalScope.SESSION: "以下是与本轮追问语义相关的当前分析片段（RAG 检索）：",
            RetrievalScope.CROSS_SESSION: "以下是从您的历史分析库中检索到的相关片段（跨会话）：",
            RetrievalScope.COMPARE: "以下是对比问题相关的历史分析片段（可能来自不同标的）：",
        }
        lines = [headers.get(scope, headers[RetrievalScope.SESSION])]
        for i, (doc, meta) in enumerate(zip(docs, metas), 1):
            label = meta.get("source_label", meta.get("source", "片段"))
            company = meta.get("company_name") or "未知公司"
            stock = meta.get("stock_code") or ""
            stock_part = f" · {stock}" if stock else ""
            section = meta.get("breadcrumb") or meta.get("heading") or ""
            section_part = f" · {section}" if section else ""
            if scope == RetrievalScope.SESSION:
                title = f"片段 {i} · {label}{section_part} · {company}{stock_part}"
            else:
                sid = meta.get("session_id") or "未知会话"
                title = f"片段 {i} · {label}{section_part} · {company}{stock_part} · 会话 {sid[:8]}"
            lines.append(f"\n### {title}\n{doc}")
        return "\n".join(lines)

    def _dense_search_chroma(
        self,
        user_id: str,
        query: str,
        *,
        where: dict[str, Any] | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        query_emb = _embed_texts([query])[0]
        collection = self._collection(user_id)
        result = collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        chunks: list[RetrievedChunk] = []
        for idx, doc_id in enumerate(ids):
            chunks.append(RetrievedChunk(
                id=doc_id,
                document=docs[idx] if idx < len(docs) else "",
                metadata=metas[idx] if idx < len(metas) else {},
                distance=distances[idx] if idx < len(distances) else None,
            ))
        return chunks

    def _sparse_search_chroma(
        self,
        user_id: str,
        query: str,
        *,
        scope: RetrievalScope,
        session_id: str | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        index = self._get_bm25_index(user_id)
        if index is None or not index.available:
            return []
        hits = index.search(query, top_k=max(top_k * 3, top_k))
        chunks: list[RetrievedChunk] = []
        for hit in hits:
            if scope == RetrievalScope.SESSION and session_id:
                if hit.metadata.get("session_id") != session_id:
                    continue
            chunks.append(RetrievedChunk(
                id=hit.id,
                document=hit.document,
                metadata=hit.metadata,
                distance=None,
            ))
            if len(chunks) >= top_k:
                break
        return chunks

    def _dense_search_es(
        self,
        user_id: str,
        query: str,
        *,
        scope: RetrievalScope,
        session_id: str | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        assert self._es is not None
        query_emb = _embed_texts([query])[0]
        hits = self._es.dense_search(
            user_id,
            query_emb,
            session_id=session_id,
            scope_session_only=(scope == RetrievalScope.SESSION),
            top_k=top_k,
        )
        return [
            RetrievedChunk(
                id=h["id"],
                document=h["document"],
                metadata=h["metadata"],
                distance=h.get("distance"),
            )
            for h in hits
        ]

    def _sparse_search_es(
        self,
        user_id: str,
        query: str,
        *,
        scope: RetrievalScope,
        session_id: str | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        assert self._es is not None
        hits = self._es.sparse_search(
            user_id,
            query,
            session_id=session_id,
            scope_session_only=(scope == RetrievalScope.SESSION),
            top_k=top_k,
        )
        return [
            RetrievedChunk(
                id=h["id"],
                document=h["document"],
                metadata=h["metadata"],
                distance=None,
            )
            for h in hits
        ]

    def retrieve_chunks(
        self,
        user_id: str,
        query: str,
        *,
        scope: RetrievalScope = RetrievalScope.SESSION,
        session_id: str | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """双路召回（向量 + BM25）→ RRF 融合 → BGE 重排 → Top-K。"""
        if not _rag_enabled() or not _embedding_configured() or not query.strip():
            return []

        final_k = top_k or TOP_K_BY_SCOPE.get(scope, DEFAULT_TOP_K)
        candidate_k = _candidate_k(final_k)

        try:
            if self.backend == "elasticsearch":
                dense_chunks = self._dense_search_es(
                    user_id, query, scope=scope, session_id=session_id, top_k=candidate_k,
                )
                sparse_chunks = (
                    self._sparse_search_es(
                        user_id, query, scope=scope, session_id=session_id, top_k=candidate_k,
                    )
                    if _hybrid_enabled()
                    else []
                )
            else:
                where = self._build_where(scope=scope, session_id=session_id)
                dense_chunks = self._dense_search_chroma(
                    user_id, query, where=where, top_k=candidate_k,
                )
                sparse_chunks = (
                    self._sparse_search_chroma(
                        user_id, query, scope=scope, session_id=session_id, top_k=candidate_k,
                    )
                    if _hybrid_enabled()
                    else []
                )

            if not _hybrid_enabled():
                return dense_chunks[:final_k]

            by_id: dict[str, RetrievedChunk] = {}
            for chunk in dense_chunks + sparse_chunks:
                by_id.setdefault(chunk.id, chunk)

            if not by_id:
                return []

            fused_ids = rrf_fuse(
                [
                    [chunk.id for chunk in dense_chunks],
                    [chunk.id for chunk in sparse_chunks],
                ],
                limit=candidate_k,
            )
            if not fused_ids:
                fused_ids = [chunk.id for chunk in dense_chunks or sparse_chunks]

            candidates = [
                {
                    "id": doc_id,
                    "document": by_id[doc_id].document,
                    "metadata": by_id[doc_id].metadata,
                    "distance": by_id[doc_id].distance,
                }
                for doc_id in fused_ids
                if doc_id in by_id
            ]

            reranked = rerank_pairs(query, candidates, top_k=final_k)
            return [
                RetrievedChunk(
                    id=item["id"],
                    document=item.get("document") or "",
                    metadata=item.get("metadata") or {},
                    distance=item.get("distance"),
                    rerank_score=item.get("rerank_score"),
                )
                for item in reranked
            ]
        except Exception as exc:
            logger.warning("RAG retrieve_chunks failed: %s", exc)
            return []

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        scope: RetrievalScope = RetrievalScope.SESSION,
        session_id: str | None = None,
        top_k: int | None = None,
    ) -> str:
        """检索与问题最相关的报告片段，格式化为 Prompt 文本。"""
        if not _rag_enabled() or not _embedding_configured() or not query.strip():
            return "（未启用 RAG 检索或无可用向量库）"

        chunks = self.retrieve_chunks(
            user_id,
            query,
            scope=scope,
            session_id=session_id,
            top_k=top_k,
        )
        if not chunks:
            return "（未检索到相关历史片段）"

        docs = [chunk.document for chunk in chunks]
        metas = [chunk.metadata for chunk in chunks]
        return self._format_results(docs, metas, scope)


def is_empty_retrieval(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return True
    return any(marker in normalized for marker in EMPTY_RETRIEVAL_MARKERS)


_report_rag: ReportRAG | None = None


def get_report_rag() -> ReportRAG:
    global _report_rag
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except Exception:
        pass
    backend = _rag_backend()
    if _report_rag is None or getattr(_report_rag, "backend", None) != backend:
        _report_rag = ReportRAG()
    return _report_rag


def reset_report_rag() -> None:
    """测试或热切换后端时清空单例。"""
    global _report_rag
    _report_rag = None
