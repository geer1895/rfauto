"""CLI/MCP 注册序金快照守卫（AU-1 批3 快照转正，ge6 followUp 批3）.

钉住三面注册序（防后续拆分/新增**静默漂移**——AU-1 批3 机械拆分曾把
mcp_server 拆成 facade+mcp_tools/ 包，typer→click 树与工具注册序是当时
before/after 快照的对账面；本守卫把该对账转正常驻门）：

- CLI：typer app 经 ``typer.main.get_command`` 落成 click 树——顶层
  命令/组的注册序 + 全树叶命令的**深度优先注册序**（click 的
  ``commands`` 是插入序 dict，顺序即注册序；AD-1 2026-10-02 bench
  prompt-regression +1 重钉；PT-1/2/3 2026-10-02 stats
  guardband/cpk/weibull +3 重钉；PT-6 2026-10-02 firmware
  beam/varactor/dpd +3 重钉；LC-2 2026-10-02 pcell
  list/show/eval/render +4 重钉；AD-4 2026-10-02 bench
  consistency +1 重钉；X2 2026-10-04 profile status/run +2 重钉）；
- MCP：``mcp.list_tools()`` 的 132 工具名注册序 + ``list_resources()``
  （x3-wiring 2026-10-04 W7 台账①态接线批 +9 重钉）。

金快照在 ``tests/gold/cli_registration_order.json`` 与
``tests/gold/mcp_registration_order.json``；顺序漂移（拆分子包时注册序
重排/装饰器顺序调整/新增命令插队）即红。**新增命令是显式评审动作**：
重钉命令见下方 regen 说明。

金快照重生成（新命令/组合入并有意重排后跑一次，随代码同 commit）::

    .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GOLD_DIR = _REPO / "tests" / "gold"
_GOLD_CLI = _GOLD_DIR / "cli_registration_order.json"
_GOLD_MCP = _GOLD_DIR / "mcp_registration_order.json"

src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def _cli_tree_snapshot() -> dict:
    """click 树顺序快照（runs/au1_cli_split/snapshot.py 同款走法）。

    返回 {"top_level": [名...按注册序], "leaf_paths": ["rfauto ...",
    ...深度优先序], "n_leaves": int, "n_top": int}。
    """
    from typer.main import get_command

    from rfauto.cli import main as cli_main

    top: list[str] = []
    leaves: list[str] = []

    def walk(cmd, path: str) -> int:
        n_leaves = 0
        if hasattr(cmd, "commands"):
            for name, sub in cmd.commands.items():
                child_path = f"{path} {name}"
                if len(path.split()) == 1:
                    top.append(name)          # 顶层注册序
                n_leaves += walk(sub, child_path)
        else:
            leaves.append(path)
            n_leaves = 1
        return n_leaves

    root = get_command(cli_main.app)
    n_leaves = walk(root, "rfauto")
    return {"top_level": top, "leaf_paths": leaves, "n_leaves": n_leaves,
            "n_top": len(top)}


def _mcp_snapshot() -> dict:
    """MCP 工具/资源注册序快照（list_tools 返回序=注册序）。"""
    pytest.importorskip("fastmcp")
    import asyncio

    from rfauto import mcp_server

    tools = asyncio.run(mcp_server.mcp.list_tools())
    resources = asyncio.run(mcp_server.mcp.list_resources())
    return {"tool_names_order": [t.name for t in tools],
            # 资源身份取 uri（str(Resource) 的 repr 含对象地址——跨进程
            # 不稳定，金快照会假红）
            "resources": sorted(str(getattr(r, "uri", r)) for r in resources)}


def test_cli_top_level_registration_order():
    """89 顶层命令/组注册序逐位=金快照（新增/重排=显式评审+重钉）。"""
    gold = json.loads(_GOLD_CLI.read_text(encoding="utf-8"))
    snap = _cli_tree_snapshot()
    assert snap["n_top"] == len(gold["top_level"]), (
        f"顶层命令数漂移: {snap['n_top']} != {len(gold['top_level'])}")
    assert snap["top_level"] == gold["top_level"], (
        "CLI 顶层注册序漂移（拆分/新增/重排须显式评审+重钉金快照）")


def test_cli_leaf_paths_registration_order():
    """叶命令深度优先注册序逐位=金快照（E2-8：失败消息改动态 len 防再陈旧）。"""
    gold = json.loads(_GOLD_CLI.read_text(encoding="utf-8"))
    snap = _cli_tree_snapshot()
    assert snap["n_leaves"] == 254, (
        f"叶命令数漂移: {snap['n_leaves']} != 254（check_numbers CLI 口径；"
        "W6 2026-10-06 SN-3/17/dev/diagnose deviation/kicad design-from-run"
        " 等 +13 重钉）")
    assert snap["leaf_paths"] == gold["leaf_paths"], (
        "CLI 叶命令注册序漂移（同族段内次序是 AU-1B4 钉的镜像面）")


def test_mcp_tool_and_resource_order():
    """132 个 MCP 工具注册序 + 资源清单=金快照（批3 拆分对账面转正）。"""
    gold = json.loads(_GOLD_MCP.read_text(encoding="utf-8"))
    snap = _mcp_snapshot()
    assert len(snap["tool_names_order"]) == 149, (
        f"MCP 工具数漂移: {len(snap['tool_names_order'])} != 149"
        "（check_numbers MCP 口径；W6 2026-10-06 start_tune/run_sweep/"
        "preflight_run +3 重钉）")
    assert snap["tool_names_order"] == gold["tool_names_order"], (
        "MCP 工具注册序漂移")
    assert snap["resources"] == gold["resources"], "MCP 资源清单漂移"


def _write_gold() -> None:
    _GOLD_DIR.mkdir(parents=True, exist_ok=True)
    cli = _cli_tree_snapshot()
    _GOLD_CLI.write_text(
        json.dumps(cli, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    mcp = _mcp_snapshot()
    _GOLD_MCP.write_text(
        json.dumps(mcp, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print(f"gold written: {_GOLD_CLI.name} (top={cli['n_top']}, "
          f"leaves={cli['n_leaves']}), {_GOLD_MCP.name} "
          f"(tools={len(mcp['tool_names_order'])})")


if __name__ == "__main__":
    if "--write-gold" in sys.argv:
        _write_gold()
    else:
        print(__doc__)
        print("用法: python tests/unit/test_cli_registration_order.py "
              "--write-gold")
