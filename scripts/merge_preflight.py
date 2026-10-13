"""合流预检（门口径 v2 ③）：席位返回前必跑，~2 分钟。

把"漂移类失败"（计数锚/金快照/再生差异/信封契约/help 卫生）从全量门
**前移到席位并行消化**——这类失败占门失败相当比例，且全部可以在席位
返回前自证自愈。

检查面（与上游仓 16 面形态的移植判定，2026-10-13 CI-PREP 席逐面核）：
  1. check_numbers 全链一致（tests/CLI/MCP/CALC 数字锚）
  2. public_api 金快照 --check
  3. docs_site 再生差异（test_docs_site）
  4. kernel_cards 再生差异（test_kernel_cards）
  5. 注册序金快照（test_cli_registration_order）
  6. 信封契约（test_envelope_contract）
  7. help 卫生（test_cli_help_text_hygiene）
  8. count_cli vs 台账互证（test_check_numbers+test_cli 叶计数）
  9. MCP 计数/名单/一致性（test_mcp_server+test_mcp_tool_consistency）
  10. pip-audit 依赖漏洞快审——**不移植**：本仓 CI 已有专 supply-chain
      job（pip-audit 钉版 + SBOM + 带哈希 requirements，逐 push/PR 跑），
      覆盖更强；上游 audit_gate 的 runs/ 留痕语义依赖内部工作区。
  11. sleep-AST 常驻守卫（scripts/audit_test_sleeps.py，tests 树 AST 扫
      time.sleep(N>10)——纯 stdlib 只读，零仓外语境；违例 rc=1 红，
      新增长睡只有 --allow 豁免一条路且须带理由注记）
  12. CLI 参数级 help 字符卫生——**脚本已同步、暂不挂门**：本仓 cli 树
      尚含 21 处参数 help 裸 ``[`` 残留（上游 2026-10-11 清偿批未随仓
      同步，两代际 cli 文件差异大不宜整文件搬）——挂门必红；待下轮
      cli 代际同步清偿后接线（脚本 check_cli_help_bracket.py 就位，
      树面判定地面=tests/unit/test_cli_help_text_hygiene.py 命令级已钉）。
  13. 几何 API 字面算术审计（scripts/audit_literal_arithmetic_geometry.py，
      adapters/scripts 树 AST 扫几何 API 字面算术按 SI 米求值=违规；
      #218 家族；豁免走脚本 ALLOWLIST 带理由注记，违例 rc=1 红）
  14. 锚 freshness 审计——**脚本已同步、暂不挂门**：本仓
      knowledge/anchors.yaml 属前代际（缺验证锚 37 > 棘轮 35，2026-10-13
      实测；上游 HEAD 同日 35=35 绿）——挂门必红且"棘轮只收不放"不允许
      为代际差上调；待 anchors.yaml 代际同步后按同值复核接线
      （脚本 audit_anchor_freshness.py 就位）。
  15. 模板 meta 健康度审计（scripts/audit_template_meta.py，docs/templates/
      */meta.yaml 只读 5 维审计——schema/nominal/占位符/teaching/仓内
      链接；runs/ 前缀=证据面报告不打红，其余断链=红；豁免走脚本
      EXEMPTIONS 带理由；templates 根不可读=rc2 SKIP 诚实降级）
  16. runs 湖 registry 落后度审计——**不移植**：runs 湖=上游工作区语境
      （新落 run 未入索引的落后度语义无对象），本仓 runs/ 仅样例证据面。

席位/贡献者纪律：仓根执行 ``python scripts/merge_preflight.py``——
全绿才算交付；红=自己改完再返回（计数面漂移属预期红的除外——共享
计数面归合流集中更新的项，如实报告预期红清单）。

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
    # timeout=900：无 gate 日志的仓（CI/冷检出）走 pytest --collect-only
    # 兜底，2 万+用例冷收集在 2 核 runner 上可达 3-5min——180s 实测必超
    # （TimeoutExpired 未捕获=裸 traceback 退出，CI 实证）。
    try:
        r = subprocess.run([PY, "scripts/check_numbers.py"], cwd=str(REPO_ROOT),
                           capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        print("[FAIL] check_numbers 全链一致（>900s 超时；collect fallback "
              "过慢——检查 runner 负载或固化 gate 日志口径）")
        failures.append("check_numbers")
        r = None
    ok = r is not None and "All numbers consistent" in (r.stdout + r.stderr)
    if r is not None:
        print(f"[{'PASS' if ok else 'FAIL'}] check_numbers 全链一致")
    if r is not None and not ok:
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
    try:
        r = subprocess.run(
            [PY, "-m", "pytest", *PYTEST_TARGETS, "-q", "--tb=line",
             "-p", "no:cacheprovider"],
            cwd=str(REPO_ROOT), timeout=600)
    except subprocess.TimeoutExpired:
        print("[FAIL] pytest 漂移面（>600s 超时）")
        failures.append("pytest-drift面（超时）")
        r = None
    ok = r is not None and r.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] pytest 漂移面 "
          f"（{len(PYTEST_TARGETS)} 文件）")
    if not ok:
        failures.append("pytest-drift面（细看上方 FAILED 行；计数断言类="
                        "共享计数面归合流集中项，登记即可）")

    # 10) pip-audit 快审——不挂（本仓 supply-chain job 承担，见 docstring）

    # 11) sleep-AST 常驻守卫
    r = subprocess.run([PY, str(REPO_ROOT / "scripts" / "audit_test_sleeps.py")],
                       cwd=str(REPO_ROOT), capture_output=True, text=True,
                       timeout=120)
    if r.returncode == 0:
        print("[PASS] sleep-AST 常驻守卫（tests 树零 sleep(N>10)）")
    else:
        print("[FAIL] sleep-AST 常驻守卫（长睡测试回归；逐条见上）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("sleep-AST（sleep(N>10) 常驻慢测试）")

    # 12) CLI 参数级 help 字符卫生——暂不挂（cli 树 21 处清偿未随仓同步，
    #     挂门必红；脚本已就位，见 docstring）

    # 13) 几何 API 字面算术审计
    r = subprocess.run(
        [PY, str(REPO_ROOT / "scripts" / "audit_literal_arithmetic_geometry.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        print("[PASS] 几何字面算术审计（adapters/scripts 零未豁免 LITERAL_ARITH）")
    else:
        print("[FAIL] 几何字面算术审计（几何 API 字面算术=SI 米陷阱 #218 家族；"
              "违规逐条见上，修复=预计算浮点+显式单位或 hfss_builder_utils."
              "Quantity，豁免走脚本 ALLOWLIST 带理由）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("几何字面算术（#218 家族 SI 米陷阱）")

    # 14) 锚 freshness 审计——暂不挂（anchors.yaml 前代际 37>棘轮 35，
    #     待代际同步后接线；脚本已就位，见 docstring）

    # 15) 模板 meta 健康度审计（只读 5 维；rc2=templates 根不可读 SKIP）
    r = subprocess.run(
        [PY, str(REPO_ROOT / "scripts" / "audit_template_meta.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        print("[PASS] 模板 meta 健康度审计（schema/nominal/占位符/teaching/"
              "链接 5 维零违例）")
    elif r.returncode == 2:
        print("[SKIP] 模板 meta 审计（docs/templates 不可读/空集——诚实降级，"
              "环境类非门红）")
    else:
        print("[FAIL] 模板 meta 健康度审计（违例逐条见上；修复=meta.yaml "
              "最小修不动物理值，断链改指实存文件，占位符清偿；误报合法"
              "形态走 audit_template_meta.EXEMPTIONS 带理由注记）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("模板 meta 健康度（5 维审计违例）")

    # 16) runs 湖 registry 落后度——不挂（内部工作区语境，见 docstring）

    wall = time.monotonic() - t0
    print(f"== preflight {'PASS' if not failures else 'FAIL'} "
          f"({wall:.0f}s)；红项: {failures or '无'} ==")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
