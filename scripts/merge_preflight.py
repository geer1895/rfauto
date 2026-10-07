"""合流预检（门口径 v2 ③，2026-10-05 用户令采纳）：席位返回前必跑，~2 分钟。

把"漂移类失败"（计数锚/金快照/再生差异/信封契约/help 卫生）从 52 分钟
全量门**前移到席位并行消化**——W1/W2/W3 三批实证：这类失败占门失败
相当比例，且全部可以在席位返回前自证自愈。

检查面（=三批门实红谱系）：
  1. check_numbers 全链一致（tests/CLI/MCP/CALC 数字锚）
  2. public_api 金快照 --check
  3. docs_site 再生差异（test_docs_site）
  4. kernel_cards 再生差异（test_kernel_cards）
  5. 注册序金快照（test_cli_registration_order）
  6. 信封契约（test_envelope_contract）
  7. help 卫生（test_cli_help_text_hygiene）
  8. count_cli vs 台账互证（test_check_numbers+test_cli 叶计数）
  9. MCP 计数/名单/一致性（test_mcp_server+test_mcp_tool_consistency）

席位任务书纪律（自本批起写入"返回前必跑"）：
  仓根执行 ``.venv/Scripts/python.exe scripts/merge_preflight.py``
  ——全绿才算交付；红=自己改完再返回（计数面漂移属预期红的除外——
  五钉共享计数面归主代理合流集中更新的项，席位如实报告预期红清单，
  预检输出会提示哪些是"合流集中项"）。

退出码：0=全绿；1=有红（逐项列出；合流集中项不计入本席返工，但需在
席位报告登记）。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 预检 pytest 集（漂移谱系面；全量门之外的自证最小集）
PYTEST_TARGETS = [
    "tests/unit/test_docs_site.py",
    "tests/unit/test_kernel_cards.py",
    "tests/unit/test_cli_registration_order.py",
    "tests/unit/test_envelope_contract.py",
    "tests/unit/test_cli_help_text_hygiene.py",
    "tests/unit/test_check_numbers.py",
    "tests/unit/test_cli.py::TestCommandRegistryCount",
    "tests/unit/test_mcp_server.py",
    "tests/unit/test_mcp_tool_consistency.py",
    "tests/unit/test_public_api.py",
]


def main(argv: list[str] | None = None) -> int:
    t0 = time.monotonic()
    failures: list[str] = []
    print("== merge_preflight（合流预检；红=席位返回前自证自愈）==", flush=True)

    # 1) check_numbers 全链
    r = subprocess.run([PY, "scripts/check_numbers.py"], cwd=str(REPO_ROOT),
                       capture_output=True, text=True, timeout=180)
    ok = "All numbers consistent" in (r.stdout + r.stderr)
    print(f"[{'PASS' if ok else 'FAIL'}] check_numbers 全链一致")
    if not ok:
        failures.append("check_numbers")
        print((r.stdout + r.stderr)[-1200:])

    # 2) public_api 金快照
    r = subprocess.run(
        [PY, "scripts/check_public_api.py", "--check", "tests/gold/public_api.json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180)
    ok = r.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] public_api 金快照")
    if not ok:
        failures.append("public_api")
        print(r.stdout[-800:])

    # 3-9) pytest 漂移面
    r = subprocess.run(
        [PY, "-m", "pytest", *PYTEST_TARGETS, "-q", "--tb=line",
         "-p", "no:cacheprovider"],
        cwd=str(REPO_ROOT), timeout=600)
    ok = r.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] pytest 漂移面 "
          f"（{len(PYTEST_TARGETS)} 文件）")
    if not ok:
        failures.append("pytest-drift面（细看上方 FAILED 行；计数断言类="
                        "五钉共享面归主代理合流集中项，登记即可）")

    wall = time.monotonic() - t0
    print(f"== preflight {'PASS' if not failures else 'FAIL'} "
          f"({wall:.0f}s)；红项: {failures or '无'} ==")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
