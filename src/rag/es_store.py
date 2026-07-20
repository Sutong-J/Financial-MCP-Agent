"""Elasticsearch 存储：chunk 索引 + 向量 knn / BM25 双路检索。"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INDEX = "finance_rag_chunks"


def _es_url() -> str:
    return (os.getenv("ES_URL") or "").strip()


def _es_api_key() -> str:
    return (os.getenv("ES_API_KEY") or "").strip()


def _es_index() -> str:
    return (os.getenv("ES_INDEX") or DEFAULT_INDEX).strip()


def es_configured() -> bool:
    return bool(_es_url() and _es_api_key())


def create_es_client():
    from elasticsearch import Elasticsearch

    url = _es_url()
    api_key = _es_api_key()
    if not url or not api_key:
        raise RuntimeError("ES_URL / ES_API_KEY 未配置")
    return Elasticsearch(url, api_key=api_key)


class ElasticsearchRAGStore:
    """按 user/session 过滤的 ES chunk 存储。"""

    def __init__(self) -> None:
        self.client = create_es_client()
        self.index = _es_index()
        self._dims: int | None = None

    def ping(self) -> bool:
        return bool(self.client.ping())

    def ensure_index(self, dims: int) -> None:
        """创建索引（含 dense_vector + text）。维度变化时需重建索引。"""
        self._dims = dims
        if self.client.indices.exists(index=self.index):
            mapping = self.client.indices.get_mapping(index=self.index)
            props = (
                mapping.get(self.index, {})
                .get("mappings", {})
                .get("properties", {})
            )
            existing_dims = (
                props.get("content_embedding", {}).get("dims")
            )
            if existing_dims and int(existing_dims) != int(dims):
                raise RuntimeError(
                    f"ES index '{self.index}' embedding dims={existing_dims}, "
                    f"当前模型 dims={dims}。请换 ES_INDEX 或删除旧索引后重建。"
                )
            return

        # Elastic Cloud Serverless 不允许自定义 number_of_shards/replicas
        mappings = {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "user_id": {"type": "keyword"},
                "session_id": {"type": "keyword"},
                "source": {"type": "keyword"},
                "source_label": {"type": "keyword"},
                "company_name": {"type": "keyword"},
                "stock_code": {"type": "keyword"},
                "heading": {"type": "keyword"},
                "breadcrumb": {"type": "keyword"},
                "heading_level": {"type": "integer"},
                "chunk_index": {"type": "integer"},
                "char_count": {"type": "integer"},
                "content": {"type": "text"},
                "content_embedding": {
                    "type": "dense_vector",
                    "dims": dims,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        }
        self.client.indices.create(index=self.index, mappings=mappings)
        logger.info("Created ES index %s (dims=%s)", self.index, dims)

    def delete_session(self, user_id: str, session_id: str) -> None:
        if not self.client.indices.exists(index=self.index):
            return
        self.client.delete_by_query(
            index=self.index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"user_id": user_id}},
                        {"term": {"session_id": session_id}},
                    ]
                }
            },
            refresh=True,
            conflicts="proceed",
        )

    def bulk_upsert(
        self,
        *,
        user_id: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> int:
        if not ids:
            return 0
        dims = len(embeddings[0])
        self.ensure_index(dims)

        operations: list[dict[str, Any]] = []
        for doc_id, text, meta, emb in zip(ids, documents, metadatas, embeddings):
            operations.append({"index": {"_index": self.index, "_id": doc_id}})
            operations.append({
                "chunk_id": doc_id,
                "user_id": user_id,
                "session_id": meta.get("session_id") or "",
                "source": meta.get("source") or "",
                "source_label": meta.get("source_label") or "",
                "company_name": meta.get("company_name") or "",
                "stock_code": meta.get("stock_code") or "",
                "heading": meta.get("heading") or "",
                "breadcrumb": meta.get("breadcrumb") or "",
                "heading_level": int(meta.get("heading_level") or 0),
                "chunk_index": int(meta.get("chunk_index") or 0),
                "char_count": int(meta.get("char_count") or len(text)),
                "content": text,
                "content_embedding": emb,
            })

        result = self.client.bulk(operations=operations, refresh=True)
        if result.get("errors"):
            # 打印首个错误便于排查
            for item in result.get("items") or []:
                err = (item.get("index") or {}).get("error")
                if err:
                    logger.error("ES bulk error: %s", err)
                    break
            raise RuntimeError("ES bulk index reported errors")
        return len(ids)

    def _filters(
        self,
        user_id: str,
        *,
        session_id: str | None,
        scope_session_only: bool,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{"term": {"user_id": user_id}}]
        if scope_session_only and session_id:
            filters.append({"term": {"session_id": session_id}})
        return filters

    @staticmethod
    def _hit_to_meta(source: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": source.get("session_id") or "",
            "source": source.get("source") or "",
            "source_label": source.get("source_label") or "",
            "company_name": source.get("company_name") or "",
            "stock_code": source.get("stock_code") or "",
            "heading": source.get("heading") or "",
            "breadcrumb": source.get("breadcrumb") or "",
            "heading_level": source.get("heading_level") or 0,
            "chunk_index": source.get("chunk_index") or 0,
            "char_count": source.get("char_count") or 0,
        }

    def dense_search(
        self,
        user_id: str,
        query_vector: list[float],
        *,
        session_id: str | None,
        scope_session_only: bool,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not self.client.indices.exists(index=self.index):
            return []
        knn = {
            "field": "content_embedding",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": max(top_k * 4, 50),
            "filter": self._filters(
                user_id,
                session_id=session_id,
                scope_session_only=scope_session_only,
            ),
        }
        result = self.client.search(
            index=self.index,
            knn=knn,
            size=top_k,
            source_excludes=["content_embedding"],
        )
        hits: list[dict[str, Any]] = []
        for hit in result.get("hits", {}).get("hits", []):
            src = hit.get("_source") or {}
            score = hit.get("_score")
            distance = None if score is None else max(0.0, 1.0 - float(score))
            hits.append({
                "id": hit.get("_id") or src.get("chunk_id") or "",
                "document": src.get("content") or "",
                "metadata": self._hit_to_meta(src),
                "distance": distance,
            })
        return hits

    def sparse_search(
        self,
        user_id: str,
        query: str,
        *,
        session_id: str | None,
        scope_session_only: bool,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not self.client.indices.exists(index=self.index):
            return []
        result = self.client.search(
            index=self.index,
            size=top_k,
            query={
                "bool": {
                    "must": [
                        {
                            "match": {
                                "content": {
                                    "query": query,
                                    "operator": "or",
                                }
                            }
                        }
                    ],
                    "filter": self._filters(
                        user_id,
                        session_id=session_id,
                        scope_session_only=scope_session_only,
                    ),
                }
            },
            source_excludes=["content_embedding"],
        )
        hits: list[dict[str, Any]] = []
        for hit in result.get("hits", {}).get("hits", []):
            src = hit.get("_source") or {}
            hits.append({
                "id": hit.get("_id") or src.get("chunk_id") or "",
                "document": src.get("content") or "",
                "metadata": self._hit_to_meta(src),
                "distance": None,
            })
        return hits
