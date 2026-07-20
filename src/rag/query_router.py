from __future__ import annotations

import re
from enum import Enum


class RetrievalScope(str, Enum):
    SESSION = "session"
    CROSS_SESSION = "cross_session"
    COMPARE = "compare"


_CROSS_SESSION_PATTERN = re.compile(
    r"上次|之前|以前|历史|我分析过|分析过|还记得|那次|上周|昨天|前几天|早些时候|earlier|previous",
    re.IGNORECASE,
)
_COMPARE_PATTERN = re.compile(
    r"对比|比较|相比|哪个更|哪一个更|vs\.?|VS|和.+比|跟.+比|与.+比",
    re.IGNORECASE,
)


def classify_retrieval_scope(user_query: str) -> RetrievalScope:
    """根据追问内容选择 RAG 检索范围。"""
    query = (user_query or "").strip()
    if not query:
        return RetrievalScope.SESSION

    if _COMPARE_PATTERN.search(query):
        return RetrievalScope.COMPARE
    if _CROSS_SESSION_PATTERN.search(query):
        return RetrievalScope.CROSS_SESSION
    return RetrievalScope.SESSION


def scope_label(scope: RetrievalScope) -> str:
    labels = {
        RetrievalScope.SESSION: "当前会话检索（仅本次分析）",
        RetrievalScope.CROSS_SESSION: "跨会话检索（全部历史分析）",
        RetrievalScope.COMPARE: "对比检索（跨标的历史分析）",
    }
    return labels.get(scope, "当前会话检索")
