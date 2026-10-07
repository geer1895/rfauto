"""scripts/check_numbers.py 数字门的钉子测试（#97）。

只钉轻量口径：CLI 实注册 walk=147（typer.main.get_command 实测裁决锚，
click 解析去重同名覆盖取一）、文档头部模式必须实际匹配（>0，防"门空转"
回归）、exe 缺失断言走优雅报错路径（登记⑪）。

不真跑 pytest collect（慢）——tests 计数保持脚本内"门日志优先/collect 回退"
行为，不在单测里触发。
"""

import importlib.util
import re
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py"
_SPEC = importlib.util.spec_from_file_location("check_numbers_gate", _SCRIPT)
check_numbers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_numbers)


def test_cli_registered_leaf_count_matches_round3_anchor():
    # round3 对拍锚：typer 实注册叶子=111（main 侧 108 + bench_app 3）。
    # 旧"正则数装饰器"口径只扫 main.py 得 108（R3-E-02①）。
    # df6_dp5cascade（2026-09-24）：+3（cascade budget/spur/plan）= 114。
    # 114→124（2026-09-25 df6 合流对账补锚，#231 消费者同步）：中间增量
    # dp15c3+1/dp4af+3/dp13u1+1 未回写本锚（实报 121），本轨 dp11vna
    # +2（vna en-report/replay）→ 123；口径=check_numbers.count_cli()
    # （click 解析去重，同名面板 shadow 明细见 TODO followUp）。
    # df6_dp14n7 +1（solvers qucsator-mline，2026-09-25 主代理接线）→ 124。
    # df6_dp1p2 +1（mmt solve，DP-1 MMT 段表求解薄壳，2026-09-24）→ 125。
    # df6_dp17wire +3（league-rebuild/league-report/explain-run）→ 130。
    # df6_dp18c10 +6（nfmeas/nfc/sar 子应用）→ 136。
    # df6_dp3anchors +3（anchors list/inspect/validate，2026-09-24）→ 139。
    # df6_dp8wire reports 改名解遮蔽（U1 report_app 原 name=report 与旧顶层
    # report 命令同名相撞）→ +1 可见 = 140（2026-09-25 收口对账）。
    # df7 shadow 裁定（2026-09-25）：注册面=解析面=140 零 shadow 已程序化
    # 证实（回归钉 test_cli 零 shadow 两钉；"10 面"系中间稿误计数，全 git
    # 历史仅 report/report 一对）。
    # df7_t2 +1（2026-09-25：si report，SI 通道报告薄壳零逻辑转发
    # si_channel_service）→ 141。
    # df7_f3lake +5（2026-09-25：lake index/query/pack/verify/restore，runs
    # 湖索引与分层压实薄壳零逻辑转发 lake_service）→ 146。
    # df7wire +1（2026-09-26：constraints check，R4 渲染前声明式几何约束
    # 一次求解薄壳零逻辑转发 render_constraint_service）→ 147。
    # me17a-shell1 +5（2026-09-26：runs stats/export-tracking + certify +
    # solid-import + port-gate，ME-17a 接线批第一组五件纯薄壳零逻辑转发
    # runs_stats/tracking_export/certify_design/solid_import_service/
    # port_gate_service）→ 152。
    # qw123 +2（2026-09-26：si mixed（QW-1 混合模薄壳）+ anchors stale
    # （QW-3 锚新鲜度薄壳）→ 154。
    # ge-fbp2 +3（2026-09-26：pdn analyze/select/gate，F-B P2 PI/PDN AC
    # 阻抗域三命令薄壳零逻辑转发 pdn_service）→ 157。
    # ge-fcp2 +3（2026-09-26：aging simulate/verdict/report，F-C P2 器件老化
    # 漂移三命令薄壳零逻辑转发 aging_service）→ 160。
    # ge-w4 +1（2026-09-26：lint，W4 design-lint 统一门面（聚合器不是新判据）
    # 薄壳零逻辑转发 design_lint_service.design_lint）→ 161。
    # ge-code2 +1（2026-09-26：anchors drift，QW-16 锚漂移预警薄壳零逻辑
    # 转发 anchors_service.anchor_drift_status）→ 162。
    # ge-code3 +4（2026-09-26：afs plan/sweep（M-3 AFS 自适应频扫薄壳，
    # sweep --synthetic 合成演示零真机）+ interop ts21-write/hfss-comments
    # （ME-10' 尾巴薄壳零逻辑转发 interop_service）→ 166。
    # remote-v0 +2（2026-09-28：remote probe/status，多机协同仿真资源探活/
    # 状态薄壳零逻辑转发 remote_service）→ 168。
    # me17b-wire +7（2026-09-28：ME-17b 接线批后半——repro-manifest/
    # repro-verify（零逻辑转发 reproducibility_service）+ chain lna/
    # loadpull（零逻辑转发 active_chain_service）+ even-odd（零逻辑转发
    # even_odd_service）+ lake sweep/export-parquet（QW-13/P-5，零逻辑
    # 转发 lake_service）→ 175。
    # t43-fab-absorb +9（2026-09-29：fab 子应用 go/pipeline/snapshot/draw/
    # audit/pack/rules/catalog/export，HFSS→可机加交付包薄壳零逻辑转发
    # fab_export_service，自 E:\协助调研\cad导出 原型吸收）→ 184。
    # AD-1 +1（2026-10-02：bench prompt-regression，系统提示词 A/B 回归门
    # 薄壳零逻辑转发 agent_bench.run_prompt_regression）→ 185。
    # PT-1/2/3 +3（2026-10-02：stats guardband/cpk/weibull，量产三件套薄壳
    # 域内惰性 import core/manufacturing_stats 直连）→ 188。
    # PT-6 +3（2026-10-02：firmware beam/varactor/dpd，固件工件三出口薄壳
    # 域内惰性 import core/firmware_export 直连）→ 191。
    # LC-2 +4（2026-10-02：pcell list/show/eval/render，PCell DSL 孤儿复活
    # 消费面——scattered 子应用惰性 import core/pcell_dsl 直连 + 渲染桥
    # 直产 Layout）→ 195。
    # AD-4 +1（2026-10-02：bench consistency，pass^k×成本一致性评测门
    # 薄壳零逻辑转发 agent_bench.evaluate_agentbench_consistency，k 缺省
    # 3 进月门）→ 196；ge8b 收口 XC-F preflight 两叶 → 198（E2-8 注释同步）。
    # X2 席 +2（2026-10-04：profile status/run，PR-8 剖析入口 CLI 面
    # 薄壳零逻辑转发 profile_service，宏图口径 `rfauto profile`）→ 200。
    # W1 孤儿接线批 +21（2026-10-05，规格包 VI-1：kicad gerber 1 +
    # layout 子应用 8 + tolerance-allocate 1 + vna measure/calibrate 2 +
    # diagnose detective 1 + hints list 1 + teaching show/index 2 +
    # few-shot build 1 + runs monitor/retrieve-similar 2 + zenodo
    # export/validate 2，全部零逻辑转发既有 service）→ 221。
    # W2 Phase 2 +6（2026-10-05：dag run/status 2 + campaign run 1 +
    # template-spec recommend 1 + simci-pin-baseline 1 + lake audit-stale 1，
    # 规格包 VI-4/VI-2/VI-3+SA §八）→ 227。
    # W3 Phase 3 +10（2026-10-05：lake lineage 1（XD-1）+ W3-D F-10 六服务
    # 壳 env_reliability 七叶+bench netlist-goldset 1（bench 分解 5→6）
    # → 237。
    # W5 Phase 5 +4（2026-10-05：goal set/status/advance/list，DS-3 goal 域）
    # → 241。
    # W6 +13（2026-10-06：SN-3/17/dev/diagnose deviation/kicad design-from-run
    # 等，合流实测口径）→ 254。
    assert check_numbers.count_cli() == 254


def test_cli_bench_subapp_breakdown():
    counts = check_numbers.cli_leaf_counts()
    # W3-D（2026-10-05）+1 netlist-goldset（F-10 六服务壳 qucsator 通道金集
    # 回放叶）→ 6
    assert counts["bench"] == 6  # goldset/agentbench/level2/prompt-regression/consistency + netlist-goldset
    # X2（PR-8 CLI 面）：profile 子应用 status/run 两叶（宏图 `rfauto profile`）
    assert counts["profile"] == 2
    assert sum(counts.values()) == check_numbers.count_cli()


@pytest.mark.parametrize(
    ("doc", "pattern", "label"),
    [
        (doc, pat, label)
        for doc, pats in check_numbers.DOC_PATTERNS.items()
        for pat, label in pats
    ],
)
def test_doc_header_patterns_actually_match(doc: str, pattern: str, label: str):
    # 回归钉：每个核对模式必须能在对应文档头部实际匹配到（>0），
    # 否则门静默空转——文档改版时必须同步改模式，让门红而不是放行。
    text = check_numbers.read_head(doc)
    assert text, f"{doc} 头部不可读"
    assert re.search(pattern, text), (
        f"{doc}: 模式 0 匹配——数字门空转回归 (label={label}, pattern={pattern!r})"
    )


def test_readme_number_anchor_bindings_present():
    """防回退钉：README 数字锚块的七字段绑定必须在 DOC_PATTERNS 中
    （tests_min 之外：mcp 双数/cli_leaf/templates/calc_registry/
    template_meta/expected_templates/anchors——任一移除即门盲区）。"""
    labels = {label for _, label in check_numbers.DOC_PATTERNS["README.md"]}
    assert {"tests_min", "mcp", "cli_leaf", "templates", "calc_registry",
            "template_meta", "expected_templates", "anchors"} <= labels
    assert labels == {label for _, label
                      in check_numbers.DOC_PATTERNS["README.zh-CN.md"]}


def test_mcp_entry_missing_reports_gracefully(tmp_path: Path):
    # exe 缺失时返回明确缺失信息而非抛异常（不算崩溃）。
    msg = check_numbers.mcp_entry_missing_message(tmp_path / "nope" / "rfauto-mcp.exe")
    assert msg is not None
    assert "missing" in msg
    assert "rfauto-mcp.exe" in msg


def test_mcp_entry_present_in_dev_venv():
    # 开发 venv（editable 重装后）应当存在；缺失时脚本门会红，这里只断言
    # "存在→None / 缺失→字符串"的判定不抛异常，不把安装态钉死进单测。
    result = check_numbers.mcp_entry_missing_message()
    assert result is None or "missing" in result


# ── 绑锚计数（df7 锚消费接线第二批：count_anchors + 双向核对）───────────────

def test_anchors_count_matches_core_single_source():
    # #231 注册表消费者纪律：knowledge/anchors.yaml raw 条数与
    # core/anchors.py EXPECTED_ANCHOR_COUNT 双向一致（DP-3 P1 批=6；
    # HFSS 窗 B→A 批 wf:anchor-register 2026-09-29 +6=12：constant 2+
    # pointer 4 双值指针；补批 wf:anchor-register-p1x4 2026-09-29
    # +1=13：patch_array_1x4.f_res constant active；指针补批
    # wf:anchor-pointer-register 2026-09-29 +1=14：patch_array.f_res
    # 族级 pointer experimental，席 8 2x2 重跑 DISAGREE 双值；
    # P-KJ-EVEN P3 批 wf:goal-t5 2026-09-30 +1=15：coupled_microstrip.
    # kj_even_domain.lit-v1——KJ even 闭式适用域盒 constant active，
    # 域盒 u/g/er=[0.1,10]²×[1,18]+域内基准 0.66%+两条域缘注记；
    # Goal 批 T14 wf:goal-t14 2026-09-30 +2=17：mmt.inductive_post_b.
    # hfss-v1 / mmt.resonant_window_fres.hfss-v1——ME-5 MMT 销钉/谐振窗
    # HFSS 仲裁锚（sim_host 远程，两案 AGREE_HFSS 偏差常量
    # 9.224%/16.600% active，criteria runs/mmt_anchor_20260930）；
    # ge6 Wave1 锚注册批 wf:ge6-anchor 2026-10-01 +2=19：
    # ring.design_dk.openems-hfss-v1（FA3 双引擎 DISAGREE 双值指针
    # {oe 3.5333, hfss 3.3425}，预备稿兑现）+ mmwave.design_dk.ro3003-
    # oe-v1（OE 单引擎封档 er_design=3.1434，C10d 离线复判 PASS
    # runs/ge6_anchor/verdict.json，constant 待 78GHz HFSS 仲裁腿）；
    # ge6 A22 批 wf:ge6-a22 2026-10-01 +1=20：ms_cross.wg_resonance.
    # openems-hfss-v1（ge6 席 2 HFSS 仲裁分支 A 收敛判读——同几何谷位
    # 互差 0.180GHz ≤ 预声明 0.30GHz 门，双值指针 {oe 11.675,
    # hfss 11.4951}，runs/ge6_hfsswin/seat2_mscross）。
    from rfauto.core.anchors import EXPECTED_ANCHOR_COUNT

    assert check_numbers.count_anchors() == EXPECTED_ANCHOR_COUNT
    assert EXPECTED_ANCHOR_COUNT == 60  # W6-F cpw.z0_ohm.closedform-v1 +1（核验裁决 A=CPWG/50Ω 胜出）  # W4-E 锚二批+UX-B1 档① +10（cps z0+eps/suspended_stripline z0+eps/cheb_g 五模板/xcheb_bpf4/msl_cpw.s11_f0）  # ge8e X5 批 +13（atten_pi/atten_t/ratrace/stripline/slotline/siw/monopole/coil_nfc/pyramid_horn 九族 analytic 锚）  # ge8b WB 席B9 +2（isl_shielded/vivaldi_tsa closedform）  # ge8 K-4 锚演进 +1  # ge8 TA 批三 +4  # ge8 TA 批二 +4  # ge8 TA 批 +2（schiffman/qwt_multisection 内核恒等锚 experimental）  # ge8b WA 席1 +3（TA-7/8/9 fdref×2+closedform×1）


def test_anchors_consistency_check_returns_none_when_aligned():
    assert check_numbers.check_anchors_vs_core() is None


def test_anchors_consistency_detects_mismatch(monkeypatch: pytest.MonkeyPatch):
    # 单源漂移（增删锚未同步 core，或反向）必须被判红（返回失败描述）。
    import rfauto.core.anchors as anchors_mod

    monkeypatch.setattr(anchors_mod, "EXPECTED_ANCHOR_COUNT", 5)
    msg = check_numbers.check_anchors_vs_core()
    assert msg is not None
    assert "EXPECTED_ANCHOR_COUNT" in msg and "5" in msg


# ── MCP resources 门控（R5-02/R7-2 修复批 review_ge8e F1）────────────────────

def test_mcp_resources_dual_source_consistent():
    # R5-02 回归钉：resources 数有实测门控且双口径一致。旧版 DOC_PATTERNS
    # 把该数硬编码字面量 "3"，README 漂移 3→4（QW-6 terminology 第 4 件
    # d4466b72）时门恒绿=结构性失明。现值 4（2026-10-04 实测；
    # 增删 resource 时随本锚注释递增，同 CLI/ANCHORS 锚演进惯例）。
    # W5-D（2026-10-05）+1 rfauto://toolsets/definition（EC-6 toolsets 单源）
    # → 5。
    n, src = check_numbers.count_mcp_resources()
    n_rx = check_numbers.count_mcp_resources_regex()
    assert n == n_rx == 5
    assert src.startswith("list_resources()")  # 注册面主口径可达（非回退态）


def test_readme_mcp_pattern_captures_both_numbers():
    # R5-02 结构钉：README 模式必须同时捕获 tools+resources 两个数字
    # （任一为字面量即本红）。采样行=EN README 数字块现行版式
    # （2026-10-07 英文化勘误：旧中文采样随 EN 模式一并更新）。
    pat = next(p for p, label in check_numbers.DOC_PATTERNS["README.md"]
               if label == "mcp")
    m = re.search(pat, "(123 MCP tools + 4 resources)")
    assert m is not None and m.groups() == ("123", "4")


def test_check_doc_flags_wrong_resources_number():
    # R5-02 负向钉：resources 数字写错必须判红（旧版恒绿的反面证明）。
    mc = check_numbers.count_mcp()
    rc, _ = check_numbers.count_mcp_resources()
    failures: list[str] = []
    check_numbers.check_doc(
        "README.md", check_numbers.DOC_PATTERNS["README.md"],
        {"mcp": (mc, rc + 1), "tests": (check_numbers.count_tests()[0],),
         "calc_registry": (check_numbers.count_calculators(),),
         "cli_leaf": (check_numbers.count_cli(),)},
        failures)
    assert any("mcp=" in f for f in failures), failures


def test_full_gate_glob_patterns_discriminate_targeted_logs():
    # R5-03 回归钉：baseline glob 收窄为日期形态后，定向门
    # （gate_baseline_fix-*.log 家族）不再命中任何 glob；真全量基线
    # （gate_baseline_2026*.log 与 wf_gate_full-baseline-* 族）仍命中。
    import fnmatch

    full_pat, baseline_pat = check_numbers.FULL_GATE_LOG_GLOBS
    assert fnmatch.fnmatch("gate_baseline_fix-ipc2581.log", baseline_pat) is False
    assert fnmatch.fnmatch("gate_baseline_fix-ipc2581.log", full_pat) is False
    assert fnmatch.fnmatch("gate_baseline_20260917.log", baseline_pat) is True
    assert fnmatch.fnmatch("wf_gate_full-baseline-20260921df2.log", full_pat) is True
    assert fnmatch.fnmatch("wf_gate_full_ge8d_final2.log", full_pat) is True


def test_count_tests_never_selects_targeted_logs():
    # R5-03 活体钉：修复后 runs/ 实测选择结果不变——来源必为 wf_gate_full
    # 真全量门，定向指纹（fix- 等任务后缀）永不入选。
    tc, src = check_numbers.count_tests()
    assert tc > 1000, f"tests 计数异常: {src}"
    assert "fix-" not in src, f"定向门日志入选全量门口径: {src}"
    # 公开仓口径：tests 计数=pytest --collect-only（无 runs/ 门日志载体）
    assert src == "pytest --collect-only"
