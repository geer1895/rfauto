"""域词表巡检器（UX-B13/Z-8 survey domains 工具化）——独立入口。

本体=src/rfauto/service/domain_survey_service.py（确定性三词表双向对账
引擎，规则 3/4：分层不可破+服务层 JSON 进出——引擎放 service 层，本
脚本与 CLI 薄壳同为薄包装；pool_patrol 同范式）。cli 主 app 由本脚本
注入（service 层禁 import cli，W4-S20 分层修复）。

对账面（词表项 ↔ 实际注册面，孤儿词/缺词报出）：
  V1 计算器组词表  CALC_GROUP_ORDER ↔ CALC_GROUP_TABLE 值域
  V2 CLI 域词表    顶层组名（--help 暴露面）↔ cli/domains/ 源模块
  V3 MCP 工具组词表 knowledge/toolsets.yaml ↔ mcp_tools/ 注册面

用法：
  python scripts/survey_domains.py            # human 摘要（violation 在场逐条）
  python scripts/survey_domains.py --json     # JSON 信封（引擎原样）

退出码：0=零违例（基线冻结 2026-10-18）；1=有违例（修复或按 B4 原文
"发现空白≠立项只产报告"分流——报告面字段不判红，violations 才红）；
2=输入面不可读（error 信封，SKIP 诚实降级口径）。

挂点说明（任务口径"与 Z-10 二选一挂点"）：merge_preflight 面 17 已由
同批 E2（Z-10 check_mcp_desc）占用，本巡检器走独立可跑+单测钉基线，
不占预检时长预算。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rfauto.cli.main import app as _cli_app  # noqa: E402
from rfauto.service.domain_survey_service import domain_survey  # noqa: E402


def _human(data: dict) -> str:
    v1 = data["calc_groups"]
    v2 = data["cli_domains"]
    v3 = data["mcp_toolsets"]
    lines = [
        "域词表巡检（survey domains，三词表双向对账）",
        f"  V1 计算器组词表: ORDER {v1['order_count']} 组 ↔ TABLE 值域 "
        f"{v1['table_value_count']} 组（{v1['table_key_count']} 键；"
        f"注册键 {v1['registered_keys']}，未分组 "
        f"{len(v1['registered_keys_ungrouped'])}）",
        f"  V2 CLI 域词表: 顶层组 {v2['top_level_group_count']}"
        f"（空组 {len(v2['empty_groups'])}，重名 "
        f"{len(v2['duplicate_groups'])}）；domains 模块 "
        f"{v2['domain_module_count']}（孤儿 {len(v2['orphan_modules'])}）",
        f"  V3 MCP 工具组词表: toolsets {v3['toolset_count']} ↔ 注册工具 "
        f"{v3['registered_tool_count']}（hint 漂移 {len(v3['hint_drift'])}，"
        f"未覆盖工具 {len(v3['uncovered_tools'])}，死组模块 "
        f"{len(v3['dead_modules'])}）",
    ]
    violations = data.get("violations") or []
    if violations:
        lines.append(f"违例 {len(violations)} 条（红面；报告面字段不计入）:")
        lines.extend(f"  - {v}" for v in violations)
    else:
        lines.append("违例 0 条（零违例基线；报告面矩阵见 --json）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="域词表巡检器（survey domains）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 信封")
    args = ap.parse_args(argv)

    result = domain_survey(cli_app=_cli_app)
    if not result.get("ok"):
        print(json.dumps(result, ensure_ascii=False, indent=1))
        print("[SKIP] 域词表巡检：输入面不可读（error 信封）", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(_human(result))
    return 0 if not result.get("violation_count") else 1


if __name__ == "__main__":
    sys.exit(main())
