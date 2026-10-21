"""合流预检（门口径 v2 ③，2026-10-05 用户令采纳）：席位返回前必跑。

把"漂移类失败"（计数锚/金快照/再生差异/信封契约/help 卫生）从 52 分钟
全量门**前移到席位并行消化**——W1/W2/W3 三批实证：这类失败占门失败
相当比例，且全部可以在席位返回前自证自愈。

时长口径：18 面时代预算 ~2 分钟；25 面（2026-10-19 架构批 W1-S4 扩面
后）串行实测 507s（2026-10-20 W8-S2 基线；大头=pytest 漂移面 399.5s
串行——架构批 扩面后已从历史 ~220s 涨至 400s 级 + pip-audit 网络审计
~80s，两者均先于本扩面存在；扩面六组 pytest 已按 3 并发车道压墙钟）。
2026-10-20 架构批 W8-S2 两项再压墙钟：
  ①漂移面 xdist -n 2 loadfile 并行（公开仓 CI test job 家法直搬：
    OPENBLAS_NUM_THREADS=1 import 前钉死（#258 xdist×BLAS 线程超订实测
    慢 85×）+ 门判据=日志汇总而非退出码的「零 failed 零 error 却 exit 1」
    xdist 异常态守卫（公开仓 run 37/38 实证家法），全量输出落
    runs/preflight_drift_last.log 再判读（#242 惯例）——此前"不采 xdist"
    的退出码假红顾虑即由该守卫消除）；
  ②pip-audit 加 env 指纹 + 24h TTL 缓存层（指纹=全部 dist name==version
    排序哈希，装/升/删任何包即失效重审；红不缓存、skip 不缓存；缓存只
    服务预检「快审」语义，权威口径仍是周期 audit_gate cron/CI 真审）。

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
      绿也不判红，环境类按 #122 三分法），网络面超时 300s 封顶；
      2026-10-20 W8-S2 加 env 指纹+24h TTL 缓存层——指纹一致且 TTL 内有
      绿报告即复用免网络审计，装/升/删任何包指纹漂移即失效重审）
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
  14. 锚 freshness 审计（架构批 R8 #6 常驻化，2026-10-11 A7-D：
      scripts/audit_anchor_freshness.py 对 knowledge/anchors.yaml 做只读
      时效审计——非 retired/awaiting_data 锚缺 last_verified 超棘轮
      （现值 35 冻结，只收不放）=红，新增锚必须带验证回填；时效超龄
      （experimental>30d/active>90d）=报告面永不红，时间推移不打红
      无关席位；注册表不可读=rc2 SKIP 诚实降级）
  15. 模板 meta 健康度审计（架构批 R8 面 3 常驻化，2026-10-11 A8-C：
      scripts/audit_template_meta.py 对 docs/templates/*/meta.yaml 只读
      5 维审计——schema 必备键/标量 sane、nominal 数值语义粗守卫、
      占位符残留、teaching schema（rfauto-teaching/v1）、仓内链接存在性
      （runs/=证据面报告不打红，其余前缀断链=红）；修复=meta.yaml 最小
      修（不动物理值），误报合法形态走脚本 EXEMPTIONS 带理由（只收不放，
      挂面时清单为空）；rc2=templates 根不可读 SKIP 诚实降级）
  16. runs 湖 registry 落后度审计（架构批 R8 #7 常驻化，2026-10-13
      R8-ENG1：scripts/registry_backfill.py --check 只读盘点 registry
      行数 vs 盘面 run 点数（meta 口径 #144 + 无 meta 真跑目录双层判真，
      helper/空壳豁免如实计数）——would_insert>0=落后 rc1 红（新落 run
      未入索引，回填一条命令自愈：``.venv/Scripts/python.exe
      scripts/registry_backfill.py``）；rc2=runs/ 树不可读 SKIP 诚实降级
      （CI/无湖环境）；幂等红线：回填重跑零增量行）
  17. MCP 描述单源门（Z-10 常驻化，架构批 W2-S10 E2：
      scripts/check_mcp_desc.py 五维硬门——工具描述非空/必填参数入
      docstring Args/schema 参数描述全覆盖/schema 描述与 docstring 逐字
      单源一致/幽灵参数；docstring Args=参数描述唯一真源，MCP-B 普查
      升级为门；零违例基线冻结 152 工具/514 参数，豁免走脚本 EXEMPTIONS
      带理由只收不放；rc2=fastmcp 缺席 SKIP 诚实降级）
  18. UI 前后端契约棘轮门（架构批 R1 #6/P8-10 常驻化，2026-10-18
      W2-S5：scripts/check_ui_contracts.py 双向对账——前端 JS（vendor/
      除外）的 /api/ 字面调用（引号字面量+拼接链+模板串三形态，查询串
      截断/参数段归一）⊆ server.py Route 表（悬空调用），反向路由表
      ⊆ 前端调用 ∪ 无消费豁免表（死路由）；DANGLING_ALLOWLIST 基线为空
      只收不放，UNCONSUMED_ALLOWLIST 条目只可删不可加；rc2=输入不可读
      SKIP 诚实降级）
  19. #231 注册表消费者四表一致（架构批 W1-S4 常驻化，2026-10-19，
      R3 面 3 缺口 1：test_calculators/test_physics_invariants/
      test_experimental_calculators/test_model_docs 四消费者与
      CALCULATOR_REGISTRY 键集逐位对账——C13 批全量门 4 红先例，新
      CALC 键不同步四表=定向绿/合流全量红）
  20. 模板 meta consistency（R3 缺口 2：test_template_meta_consistency
      +test_template_geometry_audit——#304 第五消费者，TEMPLATE_NOMINAL
      ↔docs/templates/*/meta.yaml↔几何审计三单源对账；w2g 批门红先例）
  21. json/源码文本棘轮面（R3 缺口 3：test_w2_c_json_coverage 新 CLI 叶
      --json 旗标棘轮（W3 门 +5 叶实红）+test_ui_r12_deepening 源码文本
      计数棘轮（T.api==0 防回潮钉等））
  22. width 单源（R3 缺口 4：test_width_single_source——50Ω 宽/名义值
      字面量 census 守卫，手抄字面量即红，走 synthesis.nominal_width_mm
      单源或 None 哨兵惰性求值）
  23. capability_cards+gallery 金快照（R3 缺口 5：
      test_capability_cards_export+test_gallery_export——导出面再生
      一致，"新面必红清单④"后两类金快照的常驻化）
  24. UI i18n 守卫（R3 缺口 6：test_ui_i18n 键集双向互证——视图引用
      ⊆LOCALES 且壳/页键有引用（悬空/死键双向即红）+test_ui_perf_loading
      静态壳加载性能钉）
  25. U+FFFD 替换字符内容抽查（R3 缺口 7，#89/#259 常驻化：扫
      src/scripts/tests/docs 文本扩展名白名单文件的 EF BF BD 字节序列
      ——零基线棘轮，出现即红；语义级中文讹变不可机检仍靠人工抽查纪律）

  面 19-24 六组 pytest 文件面互斥，按 3 并发车道执行（并发上限写死不
  探顶，#247 槽位纪律；文件级进程隔离=xdist loadfile 同款安全先例），
  结果按声明序判读——并发只省墙钟，不改变逐面三态语义。

席位任务书纪律（自本批起写入"返回前必跑"）：
  仓根执行 ``.venv/Scripts/python.exe scripts/merge_preflight.py``
  ——全绿才算交付；红=自己改完再返回（计数面漂移属预期红的除外——
  五钉共享计数面归主代理合流集中更新的项，席位如实报告预期红清单，
  预检输出会提示哪些是"合流集中项"）。

退出码：0=全绿；1=有红（逐项列出；合流集中项不计入本席返工，但需在
席位报告登记）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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

_AUDIT_CACHE_SCHEMA = "qm4/preflight_audit_cache/1"
_AUDIT_CACHE_TTL_S = 24 * 3600  # 快审缓存语义；权威口径=周期 audit_gate 真审


def _env_fingerprint() -> str:
    """当前环境依赖集指纹（全部 dist ``name==version`` 排序哈希）——审计缓存
    失效键：装/升/删任何包即漂移。枚举实测 ~1s 量级，相对网络审计 ~80s 可
    忽略；枚举异常返回一次性哨兵（永不命中缓存=诚实重审，#105 不静默放行）。
    """
    try:
        import importlib.metadata as im

        lines = sorted(
            f"{(d.metadata or {}).get('Name', '?')}=={d.version}"
            for d in im.distributions())
    except Exception:
        return f"error:{time.time()}"
    return hashlib.sha256("\n".join(lines).encode("utf-8", "replace")).hexdigest()


def _load_audit_cache(path: Path, fingerprint: str) -> dict | None:
    """读 pip-audit 快审缓存：schema 对、指纹一致、TTL 内且为绿报告才命中；
    任何不一致/异常=未命中（回退真审，不静默放行）。"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schema") != _AUDIT_CACHE_SCHEMA:
            return None
        if doc.get("fingerprint") != fingerprint:
            return None
        if doc.get("status") != "green":
            return None
        age = time.time() - float(doc.get("ts") or 0.0)
        if not 0 < age <= _AUDIT_CACHE_TTL_S:
            return None
        return doc
    except Exception:
        return None


def _store_audit_cache(path: Path, fingerprint: str) -> None:
    """真审绿后写缓存（报告名=runs/audit_gate 最新 audit_deps_report JSON）；
    观测路径 best-effort（#105），失败不阻塞门判读。"""
    try:
        reports = sorted(path.parent.glob("audit_deps_report_*.json"),
                         key=lambda p: p.stat().st_mtime)
        doc = {"schema": _AUDIT_CACHE_SCHEMA, "ts": time.time(),
               "fingerprint": fingerprint, "status": "green",
               "report": reports[-1].name if reports else None}
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception:
        pass  # 观测路径 best-effort：写不进缓存也不得阻塞门判读（#105）


def main(argv: list[str] | None = None) -> int:
    t0 = time.monotonic()
    failures: list[str] = []
    print("== merge_preflight（合流预检；红=席位返回前自证自愈）==", flush=True)

    # 1) check_numbers 全链（含 pytest --collect-only 兜底口径：2 核 CI runner
    # 上 2.5 万级测试收集实测 >180s（公开仓 run 38839481077 TimeoutExpired
    # 实证），上限 900s 对齐 ci.yml preflight 预算注释）
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

    # 3-9) pytest 漂移面（2026-10-20 W8-S2 xdist 化：-n 2 loadfile 按文件
    #      分组分发不破坏文件内顺序；OPENBLAS_NUM_THREADS=1 import 前钉死
    #      （#258 xdist×BLAS 线程超订实测慢 85×）。门判据=日志汇总而非退出
    #      码：pytest-xdist「零 failed 零 error 却 exit 1」异常态（公开仓
    #      run 37/38 实证家法）响亮标注后放行，真实失败照常红；全量输出落
    #      runs/ 日志再判读（#242 惯例：stdout 直消费有 256KB cap）。
    drift_env = os.environ.copy()
    drift_env["OPENBLAS_NUM_THREADS"] = "1"
    drift_log = REPO_ROOT / "runs" / "preflight_drift_last.log"
    try:
        r = subprocess.run(
            [PY, "-m", "pytest", *PYTEST_TARGETS, "-q", "--tb=line",
             "-p", "no:cacheprovider", "-n", "2", "--dist=loadfile"],
            cwd=str(REPO_ROOT), env=drift_env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=600)
        drift_out = (r.stdout or "") + (r.stderr or "")
        drift_rc = r.returncode
    except subprocess.TimeoutExpired:
        drift_out = "pytest 漂移面 600s 超时（面内卡死/runner 异常）"
        drift_rc = 124
    with contextlib.suppress(OSError):
        drift_log.write_text(drift_out, encoding="utf-8")  # 留档 best-effort（#105）
    ok = drift_rc == 0
    if not ok:
        # 退出码异常态守卫：汇总零 failed 零 error（含无 ERRORS 节）且非超时
        # → xdist 已知异常态，按日志汇总放行；真实失败照常红。
        n_failed = sum(int(x) for x in re.findall(r"(\d+) failed", drift_out))
        n_error = sum(int(x) for x in re.findall(r"(\d+) error", drift_out))
        if drift_rc != 124 and n_failed == 0 and n_error == 0 \
                and "= ERRORS =" not in drift_out:
            ok = True
            print(f"  [WARN] rc={drift_rc} 但汇总零 failed 零 error——xdist "
                  "退出码异常态（公开仓 run 37/38 家法），按日志汇总放行；"
                  f"全量输出: {drift_log}")
    print(f"[{'PASS' if ok else 'FAIL'}] pytest 漂移面 "
          f"（{len(PYTEST_TARGETS)} 文件，xdist -n 2 loadfile）")
    if not ok:
        failures.append("pytest-drift面（细看 " + str(drift_log) +
                        " 的 FAILED 行；计数断言类=五钉共享面归主代理合流"
                        "集中项，登记即可）")
        print(drift_out[-1200:])

    # 10) pip-audit 依赖漏洞快审（QM-4 周期化；audit_gate 落日志+rc 透传）。
    #     2026-10-20 W8-S2 缓存层：env 指纹一致且 24h 内有绿报告 → 复用免
    #     网络审计（env 模式实测 ~80s=预检大头之二）；装/升/删任何包指纹
    #     漂移即失效重审；红/跳过均不写缓存（诚实语义：只有真审绿可缓存，
    #     权威口径仍是周期 audit_gate cron/CI 真审）。
    audit_cache = REPO_ROOT / "runs" / "audit_gate" / "preflight_audit_cache.json"
    cached = _load_audit_cache(audit_cache, _env_fingerprint())
    if cached is not None:
        age_h = (time.time() - float(cached.get("ts") or 0.0)) / 3600.0
        print(f"[PASS] pip-audit 依赖漏洞快审（缓存复用：{age_h:.1f}h 前绿"
              f"报告，env 指纹一致；来源报告 "
              f"{cached.get('report') or '?'}；快审语义，权威=周期 audit_gate）")
    else:
        try:
            r = subprocess.run([PY, str(REPO_ROOT / "scripts" / "audit_gate.py")],
                               cwd=str(REPO_ROOT), capture_output=True, text=True,
                               timeout=300)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = 2
        if rc == 0:
            print("[PASS] pip-audit 依赖漏洞快审（audit_gate 绿）")
            _store_audit_cache(audit_cache, _env_fingerprint())
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
            with contextlib.suppress(OSError):  # 真审红=缓存不可留（防过期绿被误读）
                audit_cache.unlink(missing_ok=True)

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

    # 14) 锚 freshness 审计（架构批 R8 #6 常驻化，2026-10-11 A7-D）
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

    # 15) 模板 meta 健康度审计（架构批 R8 面 3 常驻化，2026-10-11 A8-C）
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

    # 16) runs 湖 registry 落后度审计（架构批 R8 #7 常驻化，2026-10-13
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

    # 17) MCP 描述单源门（Z-10 常驻化，架构批 W2-S10 E2）
    r = subprocess.run(
        [PY, str(REPO_ROOT / "scripts" / "check_mcp_desc.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        print("[PASS] MCP 描述单源门（docstring Args=参数描述唯一真源，"
              "五维零违例）")
    elif r.returncode == 2:
        print("[SKIP] MCP 描述单源门（fastmcp 缺席/注册面不可用——诚实"
              "降级，环境类非门红）")
    else:
        print("[FAIL] MCP 描述单源门（新工具/新参数描述违例逐条见上；"
              "修复=补 docstring Args 条目使与 schema 一致——Args 是唯一"
              "真源，fastmcp 自动渲染进 schema description；豁免走 "
              "check_mcp_desc.EXEMPTIONS 带理由）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("MCP 描述单源门（Z-10：五维描述违例）")

    # 18) UI 前后端契约棘轮门（架构批 R1 #6/P8-10 常驻化，2026-10-18 W2-S5）
    r = subprocess.run(
        [PY, str(REPO_ROOT / "scripts" / "check_ui_contracts.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        print("[PASS] UI 前后端契约门（前端调用↔server 路由双向对账零违例）")
    elif r.returncode == 2:
        print("[SKIP] UI 契约门（静态面不可读/路由表解析为空——诚实降级，"
              "环境类非门红）")
    else:
        print("[FAIL] UI 前后端契约门（悬空调用/无消费端点逐条见上；修复="
              "改调用路径对齐 Route 表，或按脚本头注纪律登记豁免——"
              "DANGLING 表基线为空、UNCONSUMED 表只可删不可加）")
        print((r.stdout + r.stderr)[-800:])
        failures.append("UI 前后端契约门（R1 #6：悬空调用/死路由）")

    # 19-24) 扩面消费者 pytest 面（架构批 W1-S4 常驻化，2026-10-19；R3
    #        面 3 缺口 1-6）。六组文件面互斥，3 并发车道执行（上限写死
    #        不探顶，#247 槽位纪律；文件级进程隔离=xdist loadfile 同款
    #        安全先例）；结果按声明序判读——并发只省墙钟，不改逐面三态。
    #        OPENBLAS_NUM_THREADS=1 子进程 env 构造期钉死（#258）。
    ext_faces: list[tuple[str, list[str], str]] = [
        ("#231 注册表消费者四表一致（CALC 键集×4 表逐位对账）",
         ["tests/unit/test_calculators.py",
          "tests/unit/test_physics_invariants.py",
          "tests/unit/test_experimental_calculators.py",
          "tests/unit/test_model_docs.py"],
         "新 CALC 键必须同步四表（test_calculators EXPECTED+"
         "test_physics_invariants 输入表+test_experimental_calculators+"
         "test_model_docs）——#231 家法，定向绿/合流全量红即此"),
        ("模板 meta consistency（TEMPLATE_NOMINAL↔meta.yaml↔几何审计）",
         ["tests/unit/test_template_meta_consistency.py",
          "tests/unit/test_template_geometry_audit.py"],
         "新模板注册必同步 core 侧 TEMPLATE_META 与 docs/templates/*/"
         "meta.yaml（nominal_params/teaching 块）——#304 第五消费者"),
        ("json/源码文本棘轮面（CLI --json 全覆盖+T.api 防回潮）",
         ["tests/unit/test_w2_c_json_coverage.py",
          "tests/unit/test_ui_r12_deepening.py"],
         "新 CLI 叶必须带 --json 旗标（棘轮只收不放，W3 门 +5 叶先例）；"
         "UI 源码文本计数回潮按 test_ui_r12 头注迁移终态修（新增请求走 "
         "pages/api.js 单源）"),
        ("width 单源（50Ω 字面量 census 守卫）",
         ["tests/unit/test_width_single_source.py"],
         "50Ω 宽/名义值禁手抄字面量——走 synthesis.nominal_width_mm "
         "单源或 None 哨兵惰性求值（合流清单⑤）"),
        ("capability_cards+gallery 金快照（导出面再生一致）",
         ["tests/unit/test_capability_cards_export.py",
          "tests/unit/test_gallery_export.py"],
         "卡/画廊导出面漂移——仓根重跑对应导出器并同笔提交产物，勿手改"
         "（合流清单④后两类常驻化）"),
        ("UI i18n 守卫（键集双向互证+静态壳性能钉）",
         ["tests/unit/test_ui_i18n.py", "tests/unit/test_ui_perf_loading.py"],
         "新增 UI 文案必须 zh/en 双语入 LOCALES 且视图有引用（悬空引用/"
         "死键双向即红）；壳预取/懒加载钉按 test_ui_perf_loading 头注"),
    ]
    ext_env = os.environ.copy()
    ext_env["OPENBLAS_NUM_THREADS"] = "1"

    def _run_ext_face(targets: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PY, "-m", "pytest", *targets, "-q", "--tb=line",
             "-p", "no:cacheprovider"],
            cwd=str(REPO_ROOT), env=ext_env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=300)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(_run_ext_face, targets)
                for _, targets, _ in ext_faces]
        for (label, _targets, hint), fut in zip(ext_faces, futs,
                                                strict=True):
            try:
                r = fut.result()
            except subprocess.TimeoutExpired:
                print(f"[FAIL] {label}（300s 超时——面内测试卡死/runner 异常，"
                      "按提示单独复跑定位）")
                print(hint)
                failures.append(f"{label}（超时）")
                continue
            except Exception as exc:  # 车道执行层故障如实记红不吞（#229）
                print(f"[FAIL] {label}（执行层异常 {type(exc).__name__}: "
                      f"{exc}）")
                failures.append(f"{label}（执行层异常）")
                continue
            if r.returncode == 0:
                print(f"[PASS] {label}")
            else:
                print(f"[FAIL] {label}")
                print(hint)
                print(((r.stdout or "") + (r.stderr or ""))[-800:])
                failures.append(label)

    # 25) U+FFFD 替换字符内容抽查（#89/#259 常驻化，架构批 W1-S4）
    _UFFFD_EXTS = {".py", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg",
                   ".ini", ".json", ".js", ".css", ".html"}
    ufffd_hits: list[str] = []
    for _root in ("src", "scripts", "tests", "docs"):
        for _p in (REPO_ROOT / _root).rglob("*"):
            if _p.suffix.lower() not in _UFFFD_EXTS or not _p.is_file():
                continue
            try:
                _n = _p.read_bytes().count(b"\xef\xbf\xbd")
            except OSError:
                continue
            if _n:
                ufffd_hits.append(f"{_p.relative_to(REPO_ROOT)} x{_n}")
    if ufffd_hits:
        print("[FAIL] U+FFFD 内容抽查（替换字符混入文本面——#89 PowerShell "
              "编码事故/#259 Edit 长中文段；逐条如下）")
        for _h in ufffd_hits[:20]:
            print("  " + _h)
        failures.append("U+FFFD 内容抽查（#89/#259：替换字符混入文本面）")
    else:
        print("[PASS] U+FFFD 内容抽查（src/scripts/tests/docs 文本面零替换"
              "字符；语义级中文讹变仍靠改完人工抽查）")

    wall = time.monotonic() - t0
    print(f"== preflight {'PASS' if not failures else 'FAIL'} "
          f"({wall:.0f}s)；红项: {failures or '无'} ==")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
