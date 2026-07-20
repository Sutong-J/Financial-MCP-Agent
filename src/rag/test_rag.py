from src.rag.chunker import (
    chunk_for_rag,
    chunk_text,
    make_chunk_id,
)
from src.rag.hybrid import BM25Index, rrf_fuse, tokenize
from src.rag.query_router import RetrievalScope, classify_retrieval_scope, scope_label
from src.rag.rerank import rerank_pairs
from src.rag.service import ReportRAG, is_empty_retrieval


SAMPLE_REPORT = """# 贵州茅台(sh.600519) 综合分析报告

## 执行摘要
贵州茅台 ROE 长期维持在 30% 以上，毛利率 91.2%。

## 基本面分析
### 1）盈利能力
ROE 为 31.2%，毛利率 91.2%，净利率 52.3%。

### 2）成长性
营收同比增长 15.8%，净利润同比增长 18.5%。

## 投资建议
综合评级：增持。
"""


def test_chunk_for_rag_splits_by_h2():
    chunks = chunk_for_rag(SAMPLE_REPORT, source="final_report", source_label="综合报告")
    breadcrumbs = {chunk.breadcrumb for chunk in chunks}
    assert "执行摘要" in breadcrumbs
    assert "基本面分析 > 盈利能力" in breadcrumbs
    assert "投资建议" in breadcrumbs


def test_chunk_for_rag_short_text_single_chunk():
    text = "贵州茅台新闻舆情：近期渠道改革受到关注，整体舆情偏正面。"
    chunks = chunk_for_rag(text, source="news_analysis", source_label="新闻")
    assert len(chunks) == 1
    assert chunks[0].heading_slug == "_root_"


def test_chunk_for_rag_preserves_numbers_across_splits():
    long_body = "ROE 为 31.2%，毛利率 91.2%。" + ("公司盈利稳定。" * 120)
    text = f"## 基本面分析\n\n### 1）盈利能力\n\n{long_body}"
    chunks = chunk_for_rag(text, source="fundamental_analysis", source_label="基本面", max_chunk_size=300)
    assert len(chunks) > 1
    combined = "\n".join(chunk.text for chunk in chunks)
    assert "31.2%" in combined
    assert "91.2%" in combined
    for chunk in chunks:
        assert "31.2" not in chunk.text or "31.2%" in chunk.text


def test_chunk_for_rag_adds_prefix():
    chunks = chunk_for_rag(
        "## 估值分析\n\n市盈率 28.5 倍。",
        source="value_analysis",
        source_label="估值",
        company_name="贵州茅台",
        stock_code="sh.600519",
    )
    assert chunks[0].text.startswith("[来源: 估值")
    assert "贵州茅台" in chunks[0].text


def test_make_chunk_id_uses_heading_slug():
    chunks = chunk_for_rag("## 执行摘要\n\n内容", source="final_report", source_label="综合报告")
    chunk_id = make_chunk_id("sess-1", "final_report", chunks[0])
    assert chunk_id == "sess-1:final_report:执行摘要:0"


def test_chunk_text_splits_long_paragraphs():
    text = "段落一。\n\n" + ("长内容。" * 200)
    chunks = chunk_text(text, chunk_size=200, overlap=20)
    assert len(chunks) > 1


def test_chunk_text_empty():
    assert chunk_text("") == []


def test_classify_retrieval_scope_session_default():
    assert classify_retrieval_scope("ROE 为什么高？") == RetrievalScope.SESSION


def test_classify_retrieval_scope_cross_session():
    assert classify_retrieval_scope("上次分析茅台的结论是什么？") == RetrievalScope.CROSS_SESSION


def test_classify_retrieval_scope_compare():
    assert classify_retrieval_scope("和五粮液比哪个估值更合理？") == RetrievalScope.COMPARE


def test_scope_label():
    assert "跨会话" in scope_label(RetrievalScope.CROSS_SESSION)


def test_is_empty_retrieval():
    assert is_empty_retrieval("（未检索到相关历史片段）")
    assert not is_empty_retrieval("以下是与本轮追问语义相关的当前分析片段")


def test_format_results_cross_session():
    rag = ReportRAG.__new__(ReportRAG)
    text = rag._format_results(
        ["估值偏高"],
        [{
            "source_label": "估值",
            "breadcrumb": "估值分析",
            "company_name": "五粮液",
            "stock_code": "000858",
            "session_id": "abc12345-6789",
        }],
        RetrievalScope.CROSS_SESSION,
    )
    assert "跨会话" in text
    assert "五粮液" in text
    assert "估值分析" in text
    assert "abc12345" in text


def test_rrf_fuse_prefers_shared_hits():
    fused = rrf_fuse([
        ["a", "b", "c"],
        ["c", "d", "a"],
    ], limit=3)
    assert fused[0] in {"a", "c"}
    assert set(fused) <= {"a", "b", "c", "d"}


def test_bm25_prefers_exact_term():
    ids = ["roe", "tech", "news"]
    docs = [
        "贵州茅台 ROE 长期维持在 30% 以上，毛利率很高。",
        "股价支撑位在 1600 元附近，均线多头。",
        "渠道改革消息面偏正面。",
    ]
    metas = [{"session_id": "s1"} for _ in ids]
    index = BM25Index(ids, docs, metas)
    if not index.available:
        return
    hits = index.search("ROE 为什么高", top_k=2)
    assert hits
    assert hits[0].id == "roe"


def test_tokenize_keeps_ticker_and_chinese():
    tokens = tokenize("分析 sh.600519 的 ROE")
    assert any("600519" in tok or tok == "sh.600519" for tok in tokens) or "600519" in "".join(tokens)
    assert any("分析" in tok or tok == "分" for tok in tokens)


def test_rerank_fallback_without_model(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_ENABLED", "false")
    candidates = [
        {"id": "a", "document": "ROE 很高", "metadata": {}},
        {"id": "b", "document": "支撑位", "metadata": {}},
    ]
    ranked = rerank_pairs("ROE", candidates, top_k=1)
    assert len(ranked) == 1
    assert ranked[0]["id"] == "a"
