"""真模型 Runtime A/B 运行时批次（WP3.1 ①）：builtin vs pydantic_ai，证据落盘。

用法（工作区根目录；需 configs/chat_settings.yaml 配好 base_url/model/api_key，
且已装可选依赖组 pai = pydantic-ai-slim[openai]）：

    .venv\\Scripts\\python.exe scripts\\runtime_ab_live.py --repeats 3 --max-rounds 6

外网 + API key 路径（#139 禁入测试，只在运行时批次调用）。逻辑全在服务层
rfauto.service.runtime_ab.live_runtime_ab（JSON 进出），本脚本只是薄壳：跑批、
打印逐次进度、把报告写到 scripts/runtime_ab_live_out/evidence.json（含逐次
token/出站字节/工具序列/收尾/耗时、两轨均值、公平性、recommend_default 裁决；
不含 api_key）。裁决口径与回滚：runtime_ab.recommend_default 三条件；配置键
configs/chat_settings.yaml ``runtime:`` 缺省 builtin，随时可改回。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "scripts" / "runtime_ab_live_out" / "evidence.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="真模型 Runtime A/B（builtin vs pydantic_ai）")
    ap.add_argument("--repeats", type=int, default=3, help="每轨重复次数（交替跑）")
    ap.add_argument("--max-rounds", type=int, default=6, help="单轮工具循环预算")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="证据 JSON 输出路径")
    ap.add_argument("--rejudge", action="store_true",
                    help="不跑模型：读已有证据，用当前 recommend_default 重算裁决后回写（裁决可复算/可回滚）")
    args = ap.parse_args()

    os.chdir(ROOT)  # configs/ 与 runs/ 均按工作区相对路径读取
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from rfauto.service.runtime_ab import lib_available, live_runtime_ab, recommend_default

    out = Path(args.out)
    if args.rejudge:
        if not out.exists():
            print(f"证据文件不存在：{out}（先跑一次不带 --rejudge 的批次生成）",
                  file=sys.stderr)
            return 2
        report = json.loads(out.read_text(encoding="utf-8"))
        report["decision"] = recommend_default(report)
        report["decision"]["rejudged_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        if not lib_available():
            print("pydantic_ai 未安装：pip install -e .[pai] 后再跑", file=sys.stderr)
            return 2
        report = live_runtime_ab(repeats=args.repeats, max_rounds=args.max_rounds, log=print)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    b = report["runtimes"]["builtin"]
    p = report["runtimes"]["pydantic_ai"]
    print(f"\n[summary] model={report['model']} lib={report['lib_version']} "
          f"repeats={report['repeats']} max_rounds={report['max_rounds']} fair={report['fair']}")
    for name, r in (("builtin", b), ("pydantic_ai", p)):
        print(f"  {name:<12} prompt={r['prompt_tokens']:.1f} completion={r['completion_tokens']:.1f} "
              f"total={r['total_tokens']:.1f} cached={r['cached_tokens']:.1f} "
              f"llm_calls={r['llm_calls']:.1f} tool_calls={r['tool_calls']:.1f} "
              f"wire={r['wire_chars_total']:.1f}B wall={r['wall_s']:.1f}s "
              f"errors={r['errors']} finish={r['finish_reasons']}")
    d = report["decision"]
    print(f"[decision] default={d['default']} switch={d['switch']} metric={d['metric']} "
          f"saving={100 * d['saving']:+.1f}%")
    for reason in d["reasons"]:
        print("  -", reason)
    print("[evidence]", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
