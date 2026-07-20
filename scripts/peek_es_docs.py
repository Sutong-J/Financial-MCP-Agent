"""查看 ES 中已索引的 RAG chunk（不打印密钥）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.rag.es_store import ElasticsearchRAGStore, es_configured


def main() -> None:
    parser = argparse.ArgumentParser(description="Peek Elasticsearch RAG documents")
    parser.add_argument("--user-id", default=None, help="按 user_id 过滤")
    parser.add_argument("--session-id", default=None, help="按 session_id 过滤")
    parser.add_argument("--size", type=int, default=10, help="最多显示几条")
    parser.add_argument("--full", action="store_true", help="打印完整 content")
    parser.add_argument("--with-vector", action="store_true", help="附带向量前 8 维预览")
    args = parser.parse_args()

    if not es_configured():
        raise SystemExit("未配置 ES_URL / ES_API_KEY")

    store = ElasticsearchRAGStore()
    if not store.client.indices.exists(index=store.index):
        raise SystemExit(f"索引不存在: {store.index}")

    count = store.client.count(index=store.index)["count"]
    print(f"index = {store.index}")
    print(f"total_docs = {count}")

    filters = []
    if args.user_id:
        filters.append({"term": {"user_id": args.user_id}})
    if args.session_id:
        filters.append({"term": {"session_id": args.session_id}})

    query = {"match_all": {}} if not filters else {"bool": {"filter": filters}}
    result = store.client.search(
        index=store.index,
        size=args.size,
        query=query,
        source_excludes=[] if args.with_vector else ["content_embedding"],
        sort=[{"session_id": "asc"}, {"source": "asc"}, {"chunk_index": "asc"}],
    )

    hits = result.get("hits", {}).get("hits", [])
    print(f"showing = {len(hits)}\n")
    for i, hit in enumerate(hits, 1):
        src = hit.get("_source") or {}
        content = src.get("content") or ""
        preview = content if args.full else content[:180].replace("\n", " ")
        print(f"[{i}] _id={hit.get('_id')}")
        print(f"    user_id={src.get('user_id')}  session_id={src.get('session_id')}")
        print(f"    source={src.get('source')}  company={src.get('company_name')} {src.get('stock_code')}")
        print(f"    breadcrumb={src.get('breadcrumb')}")
        print(f"    content={preview}{'...' if not args.full and len(content) > 180 else ''}")
        if args.with_vector:
            emb = src.get("content_embedding") or []
            print(f"    embedding_dims={len(emb)}  head={emb[:8]}")
        print()


if __name__ == "__main__":
    main()
