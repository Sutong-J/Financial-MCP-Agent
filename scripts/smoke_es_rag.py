"""ES 双路召回冒烟测试：索引 + 检索。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)
os.environ["RAG_BACKEND"] = "elasticsearch"
os.environ.setdefault("RAG_RERANK_ENABLED", "false")

from src.rag.query_router import RetrievalScope
from src.rag.service import get_report_rag, reset_report_rag


def main() -> None:
    reset_report_rag()
    rag = get_report_rag()
    print("backend =", rag.backend)

    data = {
        "company_name": "贵州茅台",
        "stock_code": "sh.600519",
        "fundamental_analysis": "贵州茅台基本面：ROE 长期维持 30% 以上，毛利率约 91%。",
        "technical_analysis": "技术面：支撑位在 1600 元附近。",
        "value_analysis": "估值：市盈率约 28 倍。",
        "news_analysis": "新闻：渠道改革舆情偏正面。",
        "final_report": "综合结论：基本面优秀，ROE 优势明显。",
    }
    n = rag.index_analysis("eval-user-es", "sess-es-001", data)
    print("indexed =", n)
    chunks = rag.retrieve_chunks(
        "eval-user-es",
        "ROE 为什么高？",
        scope=RetrievalScope.SESSION,
        session_id="sess-es-001",
        top_k=4,
    )
    print("hits =", len(chunks))
    for chunk in chunks:
        preview = chunk.document[:60].replace("\n", " ")
        print("-", chunk.id, preview)
    if n <= 0 or not chunks:
        raise SystemExit("ES smoke failed")
    print("ES dual-path smoke OK")


if __name__ == "__main__":
    main()
