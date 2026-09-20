r"""F2 RAG 词法检索 demo（确定性、零网络）：索引仓库 docs/ + runs/ 并检索。

用法（仓库根）：
    .venv\Scripts\python.exe scripts\rag_demo.py --query "端口" --query "s11_db" --top-k 3
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rfauto.service.rag_service import build_index

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="F2 RAG 确定性词法检索 demo（无网络/无 embedding）")
    parser.add_argument("--root", default=str(ROOT), help="仓库根目录")
    parser.add_argument("--query", action="append", default=None,
                        help="检索词，可重复给出")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--runs-limit", type=int, default=200,
                        help="最多索引多少个 run 目录")
    parser.add_argument("--skip-runs", action="store_true",
                        help="只索引 docs/（不读 runs/）")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    queries = args.query or ["wilkinson ports", "s11_db", "端口"]
    started = time.perf_counter()
    index = build_index(
        docs_dir=root / "docs",
        runs_dir=None if args.skip_runs else root / "runs",
        base_dir=root,
        runs_limit=args.runs_limit,
    )
    elapsed = time.perf_counter() - started
    out = {
        "stats": index.stats(),
        "index_seconds": round(elapsed, 3),
        "queries": [],
    }
    for text in queries:
        result = index.query(text, top_k=args.top_k)
        out["queries"].append({
            "query": text,
            "n_hits": result["n_hits"],
            "hits": [
                {
                    "score": round(hit["score"], 6),
                    "citation": hit["citation"],
                    "snippet": hit["snippet"],
                }
                for hit in result["hits"]
            ],
        })
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
