#!/usr/bin/env python3
"""PR-13a README 数字自动同步（round16 规格 PR-13a；#97 治本"147 vs 184 漂移"）。

从 scripts/check_numbers.py 同源计数生成 README 数字条（AUTO-NUMBERS 标记块，
装载法与 build_docs_pages.py 同款 importlib 按路径 exec），并对 README 头部
check_numbers 门钉的两处内联数字（MCP 工具数 / CALCULATOR_REGISTRY 含实验键）
做同值重写。缺省 dry-run 报告 unified diff，--write 落盘。

覆盖面（round16 规格 PR-13a 五数字+R5-02 扩 resources 第六位；tests 徽章
**不在内**——它与全量门日志绑定，口径见 check_numbers.count_tests，
收口时人工随门回填）：
- MCP 工具数（内联行 + 数字条）      ← check_numbers DOC_PATTERNS 门钉行
- MCP resources 数（内联行 + 数字条）← 同上（R5-02：resources 入门控）
- CALCULATOR_REGISTRY 主键/实验键    ← 同上（内联行 + 数字条）
- CLI 叶子命令数（数字条）
- 器件模板 TEMPLATE_META（数字条）
- 标定锚注册表条数（数字条，精确值）

一致性由 tests/unit/test_sync_readme_numbers.py 保鲜钉守护（XA-8 kernel_cards
同款：重渲染 == 已提交字节，漂移=红+修复动作提示）。

用法（venv 内，仓根执行）：
    python scripts/sync_readme_numbers.py            # dry-run：漂移打 diff（rc=1）
    python scripts/sync_readme_numbers.py --write    # 落盘 README.md（rc=0）
退出码：0=已同步（或已写入）；1=存在漂移（仅 dry-run）；2=载体缺失等硬错误。
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"

# 数字条标记块（XA-8 kernel_cards AUTO 段同款思路；整块由生成器接管，勿手改）
AUTO_START = (
    "<!-- AUTO-NUMBERS:START（scripts/sync_readme_numbers.py 生成，勿手改） -->"
)
AUTO_END = "<!-- AUTO-NUMBERS:END -->"
STRIP_HEADING_ANCHOR = "## Quick start"  # 公开仓 README.md 为英文版式

# 内联载体行模式（与 check_numbers.DOC_PATTERNS["README.md"] 同源对齐：
#  （N 个工具 + M 个 resources）/ CALCULATOR_REGISTRY N，含实验键 K——
#  数字条用全角括号变体「（含实验键 K）」，两模式互不相交，各钉各的载体；
#  resources 亦为捕获变量（R5-02：旧版 "3" 字面量致 README 漂移 3→4 门恒绿）。
CARRIER_MCP = r"（\d+ 个工具 \+ \d+ 个 resources）"
CARRIER_CALC = r"CALCULATOR_REGISTRY (\d+)，含实验键 (\d+)"


def load_check_numbers() -> Any:
    """按文件路径装载 scripts/check_numbers.py（build_docs_pages 同款）。"""
    path = Path(__file__).resolve().parent / "check_numbers.py"
    spec = importlib.util.spec_from_file_location("_pr13a_check_numbers", path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pr13a_check_numbers"] = mod
    spec.loader.exec_module(mod)
    return mod


def collect_counts(cn: Any) -> dict[str, int]:
    """六数字同源计数（键集=覆盖面契约，保鲜钉按键断言）。"""
    return {
        "mcp": int(cn.count_mcp()),
        "resources": int(cn.count_mcp_resources()[0]),
        "cli": int(cn.count_cli()),
        "calc": int(cn.count_calculators()),
        "calc_all": int(cn.count_calculators_all()),
        "templates": int(cn.count_template_meta()),
        "anchors": int(cn.count_anchors()),
    }


def render_strip(counts: dict[str, int]) -> str:
    """数字条单行正文（数字恒在标签词之后，避开 check_numbers 退役数字
    子串标记的碰撞面，如「35 CLI」「12 个工具」——见 check_numbers stale 扫描）。"""
    return (
        f"MCP 工具 {counts['mcp']}（+{counts['resources']} resources）｜ "
        f"CLI 命令 {counts['cli']}（叶子）｜ "
        f"CALCULATOR_REGISTRY {counts['calc']}"
        f"（含实验键 {counts['calc_all']}）｜ "
        f"器件模板 {counts['templates']} ｜ "
        f"标定锚 {counts['anchors']}"
    )


def render_block(counts: dict[str, int]) -> str:
    """完整标记块（含溯源横幅；替换/插入时整块接管标记间内容）。"""
    return (
        f"{AUTO_START}\n"
        "<!-- PR-13a：由 scripts/sync_readme_numbers.py 从 check_numbers 同源"
        "计数生成；漂移修复=仓根重跑 "
        "`python scripts/sync_readme_numbers.py --write` 并同笔提交（#97） -->\n\n"
        f"**规模数字**：{render_strip(counts)}\n"
        f"{AUTO_END}"
    )


def sync_text(text: str, counts: dict[str, int]) -> str:
    """纯函数同步：返回应用五数字后的完整 README 文本。

    - 内联两载体逐位重写（缺失/多命中即 ValueError——fail-closed，门不空转）；
    - 标记块存在则整块替换，缺失则在「## Quick start」标题前插入；
      标题缺失同样 ValueError（插入点漂移必须显式暴露，不许静默放弃）。
    幂等：sync_text(sync_text(t,c),c) == sync_text(t,c)（构造性保证，测试钉）。
    """
    problems: list[str] = []

    new_text, n_mcp = re.subn(
        CARRIER_MCP, f"（{counts['mcp']} 个工具 + {counts['resources']} 个 resources）",
        text)
    if n_mcp != 1:
        problems.append(
            f"MCP 载体行命中 {n_mcp} 次（须恰 1）：{CARRIER_MCP}——README 格式"
            "漂移，恢复「（N 个工具 + M 个 resources）」行后重跑")

    new_text, n_calc = re.subn(
        CARRIER_CALC,
        f"CALCULATOR_REGISTRY {counts['calc']}，含实验键 {counts['calc_all']}",
        new_text,
    )
    if n_calc != 1:
        problems.append(
            f"CALC 载体行命中 {n_calc} 次（须恰 1）：{CARRIER_CALC}——README 格式"
            "漂移，恢复「CALCULATOR_REGISTRY N，含实验键 M」行后重跑")

    block = render_block(counts)
    block_pat = re.compile(
        re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END), re.S)
    if block_pat.search(new_text):
        new_text = block_pat.sub(lambda _m: block, new_text, count=1)
    elif STRIP_HEADING_ANCHOR in new_text:
        new_text = new_text.replace(
            STRIP_HEADING_ANCHOR, block + "\n\n" + STRIP_HEADING_ANCHOR, 1)
    else:
        problems.append(
            f"数字条标记块缺失且插入点「{STRIP_HEADING_ANCHOR}」不存在——"
            "README 结构漂移，人工核对后重跑")

    if problems:
        raise ValueError("README 数字载体缺失（fail-closed）：" + "；".join(problems))
    return new_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PR-13a README 数字自动同步（五数字，dry-run 缺省）")
    parser.add_argument("--write", action="store_true",
                        help="把同步结果落盘 README.md（缺省只报告 diff）")
    parser.add_argument("--readme", default=str(README_PATH),
                        help="README 路径（缺省仓根 README.md；测试用）")
    args = parser.parse_args(argv)

    counts = collect_counts(load_check_numbers())
    print(
        f"Actual: MCP={counts['mcp']}, CLI={counts['cli']}, "
        f"CALCULATOR_REGISTRY={counts['calc']} (含实验键 {counts['calc_all']}), "
        f"TEMPLATE_META={counts['templates']}, ANCHORS={counts['anchors']} "
        f"（tests 徽章不自动写——绑定全量门日志口径）"
    )

    readme = Path(args.readme)
    text = readme.read_text(encoding="utf-8")
    try:
        new_text = sync_text(text, counts)
    except ValueError as exc:
        print(f"HARD FAIL: {exc}", file=sys.stderr)
        return 2

    if new_text == text:
        print(f"Already in sync: {readme}")
        return 0

    diff = "\n".join(difflib.unified_diff(
        text.splitlines(), new_text.splitlines(),
        fromfile=f"{readme} (current)", tofile=f"{readme} (synced)",
        lineterm=""))
    print(diff)
    if args.write:
        readme.write_text(new_text, encoding="utf-8")
        print(f"written: {readme}")
        return 0
    print("dry-run：存在漂移（rc=1）——--write 落盘，或仓根重跑本脚本 --write")
    return 1


if __name__ == "__main__":
    sys.exit(main())
