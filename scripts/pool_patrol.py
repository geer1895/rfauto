"""池登记项新鲜度巡检器（Z-11 工具化）——独立入口。

本体=src/rfauto/service/pool_patrol_service.py（确定性双判据引擎，规则 3/4：
分层不可破+服务层 JSON 进出——引擎放 service 层，本脚本与 CLI 薄壳同为
薄包装；scripts/ 不进 wheel 安装面，引擎放 scripts 会使 CLI 在安装态断链）。

用法：
  python scripts/pool_patrol.py                     # 全池巡检（human 表）
  python scripts/pool_patrol.py --json              # JSON 信封
  python scripts/pool_patrol.py --ids Z-16,SB22-MS-3 --json
  python scripts/pool_patrol.py --since 2026-10-04  # 新鲜度窗
  python scripts/pool_patrol.py --gold              # 金标校准（默认账本）

退出码：0=正常（校准模式另要求 rate=1.0）；2=输入错误（error 信封）；
1=校准模式不一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rfauto.service.pool_patrol_service import pool_patrol  # noqa: E402

DEFAULT_POOL_DOC = "docs/plan_expansion_pool_20260924.md"


def _human(result: dict) -> str:
    lines: list[str] = []
    counts = result.get("counts", {})
    lines.append(
        f"池新鲜度巡检（{result.get('pool_doc', '?')}）"
        f" 总 {result.get('total_items', 0)} 项："
        f"闭合 {counts.get('closed', 0)} / 开放 {counts.get('open', 0)} / "
        f"部分 {counts.get('partial', 0)} / 漂移 {counts.get('stale', 0)} / "
        f"不明 {counts.get('ambiguous', 0)} / 并档 {counts.get('merged_alias', 0)}"
    )
    if result.get("since"):
        lines.append(f"  新鲜度窗 --since {result['since']}")
    lines.append("")
    lines.append(f"{'ID':<18}{'状态':<14}{'判据':<34}行")
    for it in result.get("items", []):
        lines.append(
            f"{it['id']:<18}{it['status']:<14}{it['reason'][:32]:<34}"
            f"R{it['round']}:{it['line_no']}"
        )
    fp = result.get("false_positive_watch", [])
    fn = result.get("false_negative_watch", [])
    if fp:
        lines.append(f"\n假阳清单（被否决的 tag 命中，人工复核面）{len(fp)} 项：")
        for w in fp[:10]:
            lines.append(f"  {w['id']} [{w['kind']}] {len(w['hits'])} 笔")
    if fn:
        lines.append(f"\n假阴清单（单判据件）{len(fn)} 项：")
        for w in fn[:10]:
            lines.append(f"  {w['id']} {w['reason']}")
    if "calibration" in result:
        cal = result["calibration"]
        lines.append(
            f"\n金标校准：{cal['agree']}/{cal['rated']} 一致"
            f"（rate={cal['rate']}）门={result.get('calibration_gate')}"
        )
        for m in cal.get("mismatches", []):
            lines.append(f"  MISMATCH {m['id']}: 期望 {m['expected']} 实测 {m['actual']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="池登记项新鲜度巡检（Z-11）")
    parser.add_argument("pool_doc", nargs="?", default=DEFAULT_POOL_DOC,
                        help="池登记文档路径（缺省=docs/plan_expansion_pool_20260924.md）")
    parser.add_argument("--repo", default=".", help="仓库根（缺省=脚本上级目录）")
    parser.add_argument("--since", default=None, help="git log --since 新鲜度窗")
    parser.add_argument("--ids", default="", help="逗号分隔 ID 子集（SB22-MS-1 形态可）")
    parser.add_argument("--gold", action="store_true",
                        help="跑金标校准（runs/pool_reaudit/reaudit_ledger_20261007.json 口径）")
    parser.add_argument("--json", action="store_true", help="JSON 信封输出")
    args = parser.parse_args(argv)

    config: dict = {
        "pool_doc": args.pool_doc,
        "repo_root": str(Path(args.repo).resolve()),
        "since": args.since,
    }
    if args.ids.strip():
        config["ids"] = [x.strip() for x in args.ids.split(",") if x.strip()]
    if args.gold:
        config["gold"] = True

    result = pool_patrol(config)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_human(result))
    if not result.get("ok", False):
        return 2
    if result.get("calibration_gate") == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
