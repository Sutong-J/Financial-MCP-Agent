"""BGE 系列重排：优先 FlagEmbedding，其次 sentence-transformers CrossEncoder。"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

_reranker = None
_reranker_backend: str | None = None
_reranker_failed = False


def _rerank_enabled() -> bool:
    return os.getenv("RAG_RERANK_ENABLED", "true").lower() not in {"0", "false", "no"}


def _rerank_model_name() -> str:
    return os.getenv("RAG_RERANK_MODEL", DEFAULT_RERANK_MODEL)


def _load_reranker():
    global _reranker, _reranker_backend, _reranker_failed
    if _reranker is not None or _reranker_failed:
        return _reranker

    model_name = _rerank_model_name()
    try:
        from FlagEmbedding import FlagReranker

        _reranker = FlagReranker(model_name, use_fp16=True)
        _reranker_backend = "flagembedding"
        logger.info("Loaded BGE reranker via FlagEmbedding: %s", model_name)
        return _reranker
    except Exception as exc:
        logger.info("FlagEmbedding reranker unavailable (%s), trying CrossEncoder...", exc)

    try:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(model_name)
        _reranker_backend = "cross_encoder"
        logger.info("Loaded BGE reranker via CrossEncoder: %s", model_name)
        return _reranker
    except Exception as exc:
        logger.warning("BGE reranker unavailable, skip rerank: %s", model_name, exc_info=False)
        logger.warning("Rerank load error detail: %s", exc)
        _reranker_failed = True
        return None


def rerank_pairs(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """
    对候选 chunk 重排。
    candidates 元素需含: id, document, metadata, 以及可选 distance/score。
    """
    if not candidates:
        return []
    if not _rerank_enabled() or top_k <= 0:
        return candidates[:top_k]

    model = _load_reranker()
    if model is None:
        return candidates[:top_k]

    pairs = [(query, item.get("document") or "") for item in candidates]
    try:
        if _reranker_backend == "flagembedding":
            scores = model.compute_score(pairs, normalize=True)
            if isinstance(scores, (int, float)):
                scores = [float(scores)]
            else:
                scores = [float(s) for s in scores]
        else:
            raw = model.predict(pairs)
            scores = [float(s) for s in raw]
    except Exception as exc:
        logger.warning("BGE rerank failed, fallback to fused order: %s", exc)
        return candidates[:top_k]

    ranked = sorted(
        zip(candidates, scores),
        key=lambda item: item[1],
        reverse=True,
    )
    results: list[dict[str, Any]] = []
    for item, score in ranked[:top_k]:
        enriched = dict(item)
        enriched["rerank_score"] = score
        results.append(enriched)
    return results
