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
  10. pip-audit 依赖漏洞快审（QM-4 周期化，2026-10-08 快赢席 W2 挂入：
      经 scripts/audit_gate.py 调 audit_deps env 模式，门日志+报告 JSON
      落 runs/audit_gate/；rc 语义 0=绿 / 1,4=红（未豁免漏洞/门不可留痕）
      / 2,3,超时=SKIP（审计跑不起来/pip-audit 缺席/未完成——如实降级不判
      绿也不判红，环境类按 #122 三分法），网络面超时 300s 封顶）
  11. sleep-AST 常驻守卫（门口径 v2 ④ followUp 清偿，2026-10-11 W2-D：
      scripts/audit_test_sleeps.py 对 tests 树 AST 扫 time.sleep(N>10)
      常驻慢测试；违例 rc=1 红非 SKIP——新增长睡只有 --allow 豁免一条路
      且须带理由注记；配对面=wf_gate_full_v2 durations 分层报告）
  12. CLI 参数级 help 字符卫生（D-06 参数级清偿常驻化，2026-10-11 W5-C：
      scripts/check_cli_help_bracket.py 源码 AST 扫 cli 树 help= 字面裸 `[`
      ——rich markup 吞词元/炸 --help；参数级 21 处残留清偿后零基线棘轮；
      树面判定地面=tests/unit/test_cli_help_text_hygiene.py::
      TestParamHelpTextHygiene，双机制同口径）
  13. 几何 API 字面算术审计（#218 家族常驻化，2026-10-11 W5-C：
      scripts/audit_literal_arithmetic_geometry.py 对 adapters/scripts 树
      AST 扫 create_* 几何 API 的 origin/sizes/radius/height 实参，字面
      算术按 SI 米求值=违规；豁免走脚本 ALLOWLIST（带理由+背书注记），
      违例 rc=1 红）
  14. 锚 freshness 审计（aurora72 R8 #6 常驻化，2026-10-11 A7-D：
      scripts/audit_anchor_freshness.py 对 knowledge/anchors.yaml 做只读
      时效审计——非 retired/awaiting_data 锚缺 last_verified 超棘轮
      （现值 35 冻结，只收不放）=红，新增锚必须带验证回填；时效超龄
      （experimental>30d/active>90d）=报告面永不红，时间推移不打红
      无关席位；注册表不可读=rc2 SKIP 诚实降级）
  15. 模板 meta 健康度审计（aurora72 R8 面 3 常驻化，2026-10-11 A8-C：
      scripts/audit_template_meta.py 对 docs/templates/*/meta.yaml 只读
      5 维审计——schema 必备键/标量 sane、nominal 数值语义粗守卫、
      占位符残留、teaching schema（rfauto-teaching/v1）、仓内链接存在性
      （runs/=证据面报告不打红，其余前缀断链=红）；修复=meta.yaml 最小
      修（不动物理值），误报合法形态走脚本 EXEMPTIONS 带理由（只收不放，
      挂面时清单为空）；rc2=templates 根不可读 SKIP 诚实降级）
  16. runs 湖 registry 落后度审计（aurora72 R8 #7 常驻化，2026-10-13
      R8-ENG1：scripts/registry_backfill.py --check 只读盘点 registry
      行数 vs 盘面 run 点数（meta 口径 #144 + 无 meta 真跑目录双层判真，
      helper/空壳豁免如实计数）——would_insert>0=落后 rc1 红（新落 run
      未入索引，回填一条命令自愈：``.venv/Scripts/python.exe
      scripts/registry_backfill.py``）；rc2=runs/ 树不可读 SKIP 诚实降级
      （CI/无湖环境）；幂等红线：回填重跑零增量行）

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

    # 1) check_numbers 全链（含 pytest --collect-only 兜底口径：2 核 CI runner
    # 上 2.5 万级测试收集实测 >180s（run 38839481077 TimeoutExpired 实证），
    # 上限 900s 对齐 ci.yml preflight 预算注释）
    r = subprocess.run([PY, "scripts/check_numbers.py"], cwd=str(REPO_ROOT),
                       capture_output=True, text=True, timeout=900)
    ok = "All numbers consistent" in (r.stdout + r.stderr)
    print(f"[{'PASS' if ok else 'FAIL'}] check_numbers 全链一致")
    if not ok:
        failures.append("check_numbers")
        print((r.stdout + r.stderr)[-1200:])

    # 2) public_api 金快照（同上 import+collect 面，2 核 runner 同余量）
    r = subprocess.run(
        [PY, "scripts/check_public_api.py", "--check", "tests/gold/public_api.json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
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

    # 10) pip-audit 依赖漏洞快审（QM-4 周期化；audit_gate 落日志+rc 透传）
    try:
        r = subprocess.run([PY, str(REPO_ROOT / "scripts" / "audit_gate.py")],
                           cwd=str(REPO_ROOT), capture_output=True, text=True,
                           timeout=300)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        rc = 2
    if rc == 0:
        print("[PASS] pip-audit 依赖漏洞快审（audit_gate 绿）")
    elif rc in (2, 3):
        print(f"[SKIP] pip-audit 快审（rc={rc}="
              + ("网络/审计本体不可用" if rc == 2 else "pip-audit 未安装")
              + "——如实降级，环境类非门红；红=真漏洞另报）")
    else:
        print(f"[FAIL] pip-audit 依赖漏洞快审（rc={rc}；报告+日志见 "
              "runs/audit_gate/ 最新文件——豁免走 audit_deps.EXEMPT 表"
              "带理由+复审日期，不降级 continue-on-error）")
        tail = ""
        if rc != 2:
            tail = (r.stdout + r.stderr)[-800:]
        print(tail)
        failures.append("pip-audit（未豁免漏洞/门不可留痕）")

    # 11) sleep-AST 常驻守卫（门口径 v2 ④ followUp 清偿，2026-10-11 W2-D）
    r = subprocess.run([PY, str(REPO_ROOT / "scripts" / "audit_test_sleeps.py")],
                       cwd=str(REPO_ROOT), capture_output=True, text=True,
                       timeout=120)
    if r.returncode == 0:
        print("[PASS] sleep-AST 常驻守卫（tests 树零 sleep(N>10)）")
    else:
        print("[FAIL] sleep-AST 常驻守卫（长睡测试回归；逐条见上）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("sleep-AST（sleep(N>10) 常驻慢测试）")

    # 12) CLI 参数级 help 字符卫生（D-06 参数级清偿常驻化，2026-10-11 W5-C）
    r = subprocess.run([PY, str(REPO_ROOT / "scripts" / "check_cli_help_bracket.py")],
                       cwd=str(REPO_ROOT), capture_output=True, text=True,
                       timeout=60)
    if r.returncode == 0:
        print("[PASS] CLI 参数级 help 字符卫生（cli 树 help= 零裸 [）")
    else:
        print("[FAIL] CLI 参数级 help 字符卫生（参数 help 裸 [ 回归；"
              "file:line 逐条见上）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("CLI 参数级 help 字符卫生（D-06，裸 [ 炸 rich 渲染）")

    # 13) 几何 API 字面算术审计（#218 家族常驻化，2026-10-11 W5-C）
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

    # 14) 锚 freshness 审计（aurora72 R8 #6 常驻化，2026-10-11 A7-D）
    r = subprocess.run(
        [PY, str(REPO_ROOT / "scripts" / "audit_anchor_freshness.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        print("[PASS] 锚 freshness 审计（缺验证锚 ≤ 棘轮；超龄=报告面）")
    elif r.returncode == 2:
        print("[SKIP] 锚 freshness 审计（注册表不可读/空集——诚实降级，"
              "环境类非门红）")
    else:
        print("[FAIL] 锚 freshness 审计（缺验证锚超棘轮——新锚必须带 "
              "last_verified 回填；棘轮只收不放，上调须战役台账给理由，"
              "口径见 scripts/audit_anchor_freshness.py 头注）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("锚 freshness（R8 #6：缺验证锚超棘轮）")

    # 15) 模板 meta 健康度审计（aurora72 R8 面 3 常驻化，2026-10-11 A8-C）
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
        failures.append("模板 meta 健康度（R8 面 3：5 维审计违例）")

    # 16) runs 湖 registry 落后度审计（aurora72 R8 #7 常驻化，2026-10-13
    # R8-ENG1）——只读 --check，落后 rc1 / runs 树不可读 rc2 SKIP
    r = subprocess.run(
        [PY, str(REPO_ROOT / "scripts" / "registry_backfill.py"), "--check"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        print("[PASS] runs 湖 registry 落后度（registry 覆盖全部盘面 run 点，"
              "幂等零缺口）")
    elif r.returncode == 2:
        print("[SKIP] runs 湖 registry 落后度（runs/ 树不可读/无湖——诚实"
              "降级，环境类非门红）")
    else:
        print("[FAIL] runs 湖 registry 落后度（盘面有 run 点未入索引——"
              "would_insert 明细见上；回填自愈="
              ".venv/Scripts/python.exe scripts/registry_backfill.py，"
              "幂等可重跑）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("runs 湖 registry 落后度（R8 #7：新 run 未入索引）")

    wall = time.monotonic() - t0
    print(f"== preflight {'PASS' if not failures else 'FAIL'} "
          f"({wall:.0f}s)；红项: {failures or '无'} ==")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
