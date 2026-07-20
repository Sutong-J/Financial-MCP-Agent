"""
RAG 检索评测 - 扫描 Top-K、计算 recall@K 与 Token 预算

整体流程：
  1. 准备 fixtures（harness/eval/fixtures/*.json）并 seed 到 Chroma
  2. 标注 rag_benchmark_cases.json 中的 expected_chunk_ids
  3. 运行本脚本扫描 K，输出 recall@K 与平均字符/Token
  4. 根据报告选定各 scope 的最优 K

用法：
  python -m harness.eval.run_rag_eval --dry-run
  python -m harness.eval.run_rag_eval --seed-fixtures
  python -m harness.eval.run_rag_eval --preview-chunks
  python -m harness.eval.run_rag_eval --list-chunks
  python -m harness.eval.run_rag_eval
  python -m harness.eval.run_rag_eval --k-values 1,2,4,6,8,10 --scope session
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

# 评测默认跟随 .env 的 RAG_BACKEND（elasticsearch / chroma）

BENCHMARK_PATH = Path(__file__).resolve().parent / "rag_benchmark_cases.json"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_K_VALUES = [1, 2, 4, 6, 8, 10]
SOURCE_FIELDS = (
    ("final_report", "综合报告"),
    ("fundamental_analysis", "基本面"),
    ("technical_analysis", "技术面"),
    ("value_analysis", "估值"),
    ("news_analysis", "新闻"),
)


def load_benchmark_cases() -> list[dict[str, Any]]:
    with open(BENCHMARK_PATH, encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("rag_benchmark_cases.json 必须是非空数组")
    return cases


def validate_case(case: dict[str, Any]) -> None:
    required = ("id", "scope", "user_id", "query", "expected_chunk_ids")
    missing = [field for field in required if field not in case]
    if missing:
        raise ValueError(f"用例 {case.get('id', '<unknown>')} 缺少字段: {', '.join(missing)}")
    if not case["query"].strip():
        raise ValueError(f"用例 {case['id']} 的 query 不能为空")
    if not case["expected_chunk_ids"]:
        raise ValueError(f"用例 {case['id']} 的 expected_chunk_ids 不能为空")


def estimate_tokens(text: str) -> int:
    """粗略估算 Token：中文约 1.5 字/token，英文约 4 字符/token。"""
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii = len(text) - ascii_chars
    return max(1, int(non_ascii / 1.5 + ascii_chars / 4))


def load_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for path in sorted(FIXTURES_DIR.glob("rag_*_session.json")):
        with open(path, encoding="utf-8") as file:
            item = json.load(file)
        fixtures.append(item)
    if not fixtures:
        raise ValueError(f"未在 {FIXTURES_DIR} 找到 fixture 文件")
    return fixtures


def build_chunk_map(session_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """模拟 index_analysis 的切分逻辑，输出 chunk id 与文本对应关系（无需 Chroma）。"""
    from src.rag.chunker import chunk_for_rag, make_chunk_id

    rows: list[dict[str, Any]] = []
    company = str(data.get("company_name") or "")
    stock = str(data.get("stock_code") or "")
    for field, label in SOURCE_FIELDS:
        raw = data.get(field)
        if not raw or not str(raw).strip():
            continue
        chunks = chunk_for_rag(
            str(raw),
            source=field,
            source_label=label,
            company_name=company,
            stock_code=stock,
        )
        for chunk in chunks:
            rows.append({
                "id": make_chunk_id(session_id, field, chunk),
                "field": field,
                "label": label,
                "index": chunk.chunk_index,
                "heading": chunk.heading,
                "breadcrumb": chunk.breadcrumb,
                "chunk_count_in_field": len(chunks),
                "char_count": len(chunk.text),
                "preview": chunk.text[:160],
                "text": chunk.text,
            })
    return rows


def preview_fixtures(session_id: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fixture in load_fixtures():
        if session_id and fixture["session_id"] != session_id:
            continue
        rows.extend(build_chunk_map(fixture["session_id"], fixture["data"]))
    return rows


def preview_from_data_file(path: Path, session_id: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as file:
        payload = json.load(file)
    if "data" in payload and isinstance(payload["data"], dict):
        data = payload["data"]
    elif isinstance(payload, dict):
        data = payload
    else:
        raise ValueError(f"{path} 格式无效，需要 analysis data 对象或含 data 字段的 JSON")
    return build_chunk_map(session_id, data)


def print_chunk_map(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("没有 chunk。请检查 session_id 或数据文件。")
        return

    current_field = None
    for row in rows:
        if row["field"] != current_field:
            current_field = row["field"]
            print(f"\n## {row['label']} ({row['field']}) — 共 {row['chunk_count_in_field']} 块")
        print(f"\nID: {row['id']}")
        print(f"  序号: {row['index']} / 字符数: {row['char_count']}")
        print(f"  内容: {row['preview']}{'...' if row['char_count'] > 160 else ''}")


def seed_fixtures() -> dict[str, Any]:
    from src.rag import get_report_rag

    rag = get_report_rag()
    summary: dict[str, Any] = {"sessions": [], "total_chunks": 0}

    for fixture in load_fixtures():
        user_id = fixture["user_id"]
        session_id = fixture["session_id"]
        data = fixture["data"]
        count = rag.index_analysis(user_id, session_id, data)
        summary["sessions"].append({
            "session_id": session_id,
            "company_name": data.get("company_name"),
            "chunks_indexed": count,
        })
        summary["total_chunks"] += count

    return summary


def list_chunks(user_id: str = "eval-user-rag") -> list[dict[str, Any]]:
    from src.rag import get_report_rag

    rag = get_report_rag()
    collection = rag._collection(user_id)
    result = collection.get(include=["documents", "metadatas"])
    rows: list[dict[str, Any]] = []
    for idx, chunk_id in enumerate(result.get("ids") or []):
        doc = (result.get("documents") or [""])[idx]
        meta = (result.get("metadatas") or [{}])[idx]
        rows.append({
            "id": chunk_id,
            "source": meta.get("source"),
            "company_name": meta.get("company_name"),
            "session_id": meta.get("session_id"),
            "preview": (doc or "")[:120],
        })
    return rows


def recall_hit(retrieved_ids: list[str], expected_ids: list[str]) -> bool:
    """任一 expected id 出现在 top-k 结果中即算命中。"""
    expected = set(expected_ids)
    return any(chunk_id in expected for chunk_id in retrieved_ids)


def evaluate_case_at_k(
    case: dict[str, Any],
    k: int,
) -> dict[str, Any]:
    from src.rag import get_report_rag
    from src.rag.query_router import RetrievalScope

    scope = RetrievalScope(case["scope"])
    rag = get_report_rag()
    chunks = rag.retrieve_chunks(
        case["user_id"],
        case["query"],
        scope=scope,
        session_id=case.get("session_id"),
        top_k=k,
    )
    retrieved_ids = [chunk.id for chunk in chunks]
    retrieved_text = "\n\n".join(chunk.document for chunk in chunks)
    hit = recall_hit(retrieved_ids, case["expected_chunk_ids"])

    return {
        "case_id": case["id"],
        "scope": case["scope"],
        "k": k,
        "hit": hit,
        "retrieved_ids": retrieved_ids,
        "expected_chunk_ids": case["expected_chunk_ids"],
        "char_count": len(retrieved_text),
        "estimated_tokens": estimate_tokens(retrieved_text),
    }


def aggregate_recall(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"recall": 0.0, "hits": 0, "total": 0}

    hits = sum(1 for row in results if row["hit"])
    total = len(results)
    avg_chars = sum(row["char_count"] for row in results) / total
    avg_tokens = sum(row["estimated_tokens"] for row in results) / total
    return {
        "recall": hits / total,
        "hits": hits,
        "total": total,
        "avg_char_count": round(avg_chars, 1),
        "avg_estimated_tokens": round(avg_tokens, 1),
    }


def run_rag_eval(
    *,
    k_values: list[int] | None = None,
    scope: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    cases = load_benchmark_cases()
    for case in cases:
        validate_case(case)

    if scope:
        cases = [case for case in cases if case["scope"] == scope]
    if case_id:
        cases = [case for case in cases if case["id"] == case_id]
    if not cases:
        raise ValueError("过滤后没有可运行的 RAG 评测用例")

    ks = k_values or DEFAULT_K_VALUES
    by_k: dict[str, Any] = {}
    case_details: list[dict[str, Any]] = []

    for k in ks:
        k_results = [evaluate_case_at_k(case, k) for case in cases]
        case_details.extend(k_results)
        by_k[str(k)] = {
            "overall": aggregate_recall(k_results),
            "by_scope": {},
        }
        for scope_name in sorted({case["scope"] for case in cases}):
            scoped = [row for row in k_results if row["scope"] == scope_name]
            by_k[str(k)]["by_scope"][scope_name] = aggregate_recall(scoped)

    best_by_scope: dict[str, dict[str, Any]] = {}
    for scope_name in sorted({case["scope"] for case in cases}):
        best_k = None
        best_recall = -1.0
        best_tokens = None
        for k in ks:
            scoped = aggregate_recall([
                row for row in case_details
                if row["k"] == k and row["scope"] == scope_name
            ])
            if scoped["recall"] > best_recall:
                best_k = k
                best_recall = scoped["recall"]
                best_tokens = scoped["avg_estimated_tokens"]
        best_by_scope[scope_name] = {
            "recommended_k": best_k,
            "recall": best_recall,
            "avg_estimated_tokens": best_tokens,
        }

    return {
        "eval_id": f"rag_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "case_count": len(cases),
        "k_values": ks,
        "by_k": by_k,
        "recommended_k_by_scope": best_by_scope,
        "case_details": case_details,
    }


def save_report(report: dict[str, Any]) -> Path:
    output_dir = PROJECT_ROOT / "logs" / report["eval_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "rag_eval_report.json"
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    return report_path


def print_summary(report: dict[str, Any]) -> None:
    print(f"\nRAG Eval: {report['eval_id']}")
    print(f"Cases: {report['case_count']} | K values: {report['k_values']}\n")

    print("recall@K by scope:")
    for k in report["k_values"]:
        entry = report["by_k"][str(k)]
        overall = entry["overall"]
        print(
            f"  K={k:<2}  overall recall={overall['recall']:.2%} "
            f"({overall['hits']}/{overall['total']})  "
            f"avg_tokens≈{overall['avg_estimated_tokens']}"
        )
        for scope_name, scoped in entry["by_scope"].items():
            print(
                f"         {scope_name:<14} recall={scoped['recall']:.2%} "
                f"avg_tokens≈{scoped['avg_estimated_tokens']}"
            )

    print("\nRecommended K by scope:")
    for scope_name, item in report["recommended_k_by_scope"].items():
        print(
            f"  {scope_name:<14} K={item['recommended_k']}  "
            f"recall={item['recall']:.2%}  avg_tokens≈{item['avg_estimated_tokens']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Financial MCP Agent RAG eval")
    parser.add_argument("--dry-run", action="store_true", help="只校验 rag_benchmark_cases.json")
    parser.add_argument("--seed-fixtures", action="store_true", help="将 fixtures 索引到 Chroma")
    parser.add_argument(
        "--preview-chunks",
        action="store_true",
        help="预览切分结果与 chunk id（无需 Chroma，推荐先跑这个）",
    )
    parser.add_argument("--list-chunks", action="store_true", help="从 Chroma 列出已索引的 chunk id")
    parser.add_argument("--user-id", default="eval-user-rag", help="list-chunks 使用的用户 id")
    parser.add_argument("--session-id", help="只预览/列出指定 session")
    parser.add_argument(
        "--data-file",
        type=Path,
        help="预览任意 analysis JSON（需配合 --session-id）",
    )
    parser.add_argument("--k-values", default=",".join(str(k) for k in DEFAULT_K_VALUES))
    parser.add_argument("--scope", choices=["session", "cross_session", "compare"])
    parser.add_argument("--case-id")
    args = parser.parse_args()

    if args.dry_run:
        cases = load_benchmark_cases()
        for case in cases:
            validate_case(case)
        print(f"OK: {len(cases)} RAG benchmark cases validated")
        return

    if args.seed_fixtures:
        summary = seed_fixtures()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("\n下一步：运行 --preview-chunks 或 --list-chunks 核对 id")
        return

    if args.preview_chunks:
        if args.data_file:
            if not args.session_id:
                raise SystemExit("--data-file 需要同时提供 --session-id")
            rows = preview_from_data_file(args.data_file, args.session_id)
        else:
            rows = preview_fixtures(session_id=args.session_id)
        print_chunk_map(rows)
        print(f"\n共 {len(rows)} 个 chunk。将上面的 ID 填入 rag_benchmark_cases.json 的 expected_chunk_ids。")
        return

    if args.list_chunks:
        rows = list_chunks(user_id=args.user_id)
        if args.session_id:
            rows = [row for row in rows if row.get("session_id") == args.session_id]
        if not rows:
            print("未找到 chunk。请先 --seed-fixtures，或检查 --user-id / --session-id")
            return
        for row in rows:
            print(f"{row['id']}  [{row.get('source')}]  {row.get('company_name')}")
            print(f"  {row['preview']}")
        return

    k_values = [int(value.strip()) for value in args.k_values.split(",") if value.strip()]
    report = run_rag_eval(k_values=k_values, scope=args.scope, case_id=args.case_id)
    report_path = save_report(report)
    print_summary(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
