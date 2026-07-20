"""双路召回：向量（dense）+ BM25（sparse），RRF 融合。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9\.\%]+")


def tokenize(text: str) -> list[str]:
    """中英混合简易分词：单字中文 + 连续英文/数字/%。"""
    if not text:
        return []
    try:
        import jieba

        return [tok.strip().lower() for tok in jieba.lcut(text) if tok.strip()]
    except Exception:
        return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


@dataclass
class SparseHit:
    id: str
    score: float
    document: str
    metadata: dict[str, Any]


class BM25Index:
    """基于 rank_bm25 的稀疏检索索引。"""

    def __init__(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]):
        self.ids = ids
        self.documents = documents
        self.metadatas = metadatas
        self._tokenized = [tokenize(doc) for doc in documents]
        self._bm25 = None
        if ids:
            try:
                from rank_bm25 import BM25Okapi

                self._bm25 = BM25Okapi(self._tokenized)
            except Exception as exc:
                logger.warning("BM25 unavailable, sparse path disabled: %s", exc)

    @property
    def available(self) -> bool:
        return self._bm25 is not None and bool(self.ids)

    def search(self, query: str, top_k: int = 20) -> list[SparseHit]:
        if not self.available or not query.strip() or top_k <= 0:
            return []
        query_tokens = tokenize(query)
        scores = list(self._bm25.get_scores(query_tokens))
        # 小语料时 IDF 可能全为 0，退化为词项命中计数
        if not any(score > 0 for score in scores):
            scores = [
                float(sum(1 for tok in query_tokens if tok in doc_tokens))
                for doc_tokens in self._tokenized
            ]
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        hits: list[SparseHit] = []
        for idx, score in ranked[:top_k]:
            if score <= 0:
                continue
            hits.append(SparseHit(
                id=self.ids[idx],
                score=float(score),
                document=self.documents[idx],
                metadata=self.metadatas[idx] if idx < len(self.metadatas) else {},
            ))
        return hits


def rrf_fuse(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
    limit: int | None = None,
) -> list[str]:
    """Reciprocal Rank Fusion，返回融合后的 id 列表。"""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ids = [doc_id for doc_id, _ in ordered]
    if limit is not None:
        return ids[:limit]
    return ids


def filter_by_session(
    ids: Iterable[str],
    metadatas: dict[str, dict[str, Any]],
    session_id: str | None,
) -> list[str]:
    if not session_id:
        return list(ids)
    return [
        doc_id for doc_id in ids
        if (metadatas.get(doc_id) or {}).get("session_id") == session_id
    ]
