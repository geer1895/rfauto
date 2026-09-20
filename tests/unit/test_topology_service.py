"""E10 TopologyProposer 生成式综合首案例单测（方案 §3 E10 / §4 WP4.6）。

钉死面（service/topology_service.py）：
- typed 提议 schema：结构族/阶数/耦合形式，**数值字段一律拒绝**（铁律 7）；
- 提议器注册表（基类+注册表，同 AgentRuntime 模式）：rule_based / llm；
- synthesis 初值：全数字由确定性综合链产出（coupled_bpf ↔ WP2.3 NOMINAL）；
- 小战役精算：电路裁判（coupled_bpf_circuit_sparams）+ C13 理想目标曲线 +
  初值入队 TPE + 确定性坐标精化；约束语义（RL 恒不劣于初值、阻带守卫）；
- LLM 通道零内置网络：llm_call 必须注入（#139），输出走同一严格 schema。

全部离线秒级（无真机求解）；optuna 内存 study 不落 runs/。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from rfauto.service.topology_service import (
    DEFAULT_GAP_FLOOR_MM,
    FilterSpec,
    LLMTopologyProposer,
    RuleBasedTopologyProposer,
    TopologyCampaignError,
    TopologyProposalError,
    TopologyProposerRegistry,
    design_initial_values,
    list_families,
    parse_topology_proposal,
    run_fine_campaign,
    stage_design_to_sandbox,
)

SPEC = FilterSpec(f0_ghz=2.5, fbw=0.05, rl_db=20.0)


# ─── 注册表与规则提议器 ──────────────────────────────────────────────────────

def test_registry_has_rule_and_llm():
    assert set(TopologyProposerRegistry.available()) >= {"rule_based", "llm"}
    with pytest.raises(KeyError):
        TopologyProposerRegistry.create("no_such_proposer")


def test_rule_proposer_deterministic_default():
    p1 = RuleBasedTopologyProposer().propose(SPEC)
    p2 = TopologyProposerRegistry.create("rule_based").propose(SPEC)
    assert p1 == p2
    assert p1.family == "coupled_bpf"          # 首案例默认族
    assert p1.order == 3                        # 无阻带要求 → N=3 基准
    assert p1.coupling_form == "chebyshev_parallel"
    assert p1.source == "rule"


def test_rule_proposer_order_from_rejection_closed_form():
    """选阶闭式独立复算（Pozar eq.8.13）：Rs=30dB@2×带边、RL=20dB、fbw=0.05。"""
    spec = FilterSpec(f0_ghz=2.5, fbw=0.05, rl_db=20.0,
                      stop_rejection_db=30.0, stop_fbw_mult=2.0)
    prop = RuleBasedTopologyProposer().propose(spec)
    # 独立复算：ratio=√((10^3−1)/(10^2−1))，Ωs=(1.05−1/1.05)/0.05
    import math
    ratio = math.sqrt((10.0 ** 3.0 - 1.0) / (10.0 ** 2.0 - 1.0))
    omega_s = (1.05 - 1.0 / 1.05) / 0.05
    n_expect = min(12, max(1, math.ceil(math.acosh(ratio)
                                       / math.acosh(omega_s) - 1e-12)))
    assert prop.order == n_expect
    # family_hint 生效（hairpin 注册可见）
    spec_hp = FilterSpec(f0_ghz=2.5, fbw=0.05, rl_db=20.0,
                         family_hint="hairpin")
    assert RuleBasedTopologyProposer().propose(spec_hp).family == "hairpin"
    assert "hairpin" in list_families()


def test_filter_spec_validation():
    with pytest.raises(TopologyProposalError):
        FilterSpec(f0_ghz=0.0, fbw=0.05, rl_db=20.0)
    with pytest.raises(TopologyProposalError):
        FilterSpec(f0_ghz=2.5, fbw=1.5, rl_db=20.0)
    with pytest.raises(TopologyProposalError):
        FilterSpec(f0_ghz=2.5, fbw=0.05, rl_db=-1.0)
    with pytest.raises(TopologyProposalError):
        FilterSpec(f0_ghz=2.5, fbw=0.05, rl_db=20.0, family_hint="bogus")
    with pytest.raises(TopologyProposalError):
        FilterSpec(f0_ghz=2.5, fbw=0.05, rl_db=20.0, order_hint=99)


# ─── typed schema：数值字段禁令（铁律 7 零冲突的机器钉子）────────────────────

@pytest.mark.parametrize("payload", [
    {"family": "coupled_bpf", "order": 3, "coupling_form":
     "chebyshev_parallel", "f0_ghz": 2.5},                # 走私频率
    {"family": "coupled_bpf", "order": 3, "widths_mm": [0.9, 1.1, 1.1, 0.9]},
    {"family": "coupled_bpf", "order": 3.0},                # float 阶数
    {"family": "coupled_bpf", "order": True},               # bool 阶数
    {"family": "coupled_bpf", "order": "3"},                # str 阶数
    {"family": "waveguide_cavity", "order": 3},             # 未注册族
    {"family": "coupled_bpf", "order": 3, "coupling_form": "cross_coupled"},
    {"family": "coupled_bpf", "order": 0},
    {"family": "coupled_bpf", "order": 13},
    "not a dict",
    {"family": "coupled_bpf", "order": 3, "source": "agent"},  # source 白名单
])
def test_proposal_schema_rejects(payload):
    with pytest.raises(TopologyProposalError):
        parse_topology_proposal(payload)


def test_proposal_schema_accepts_typed_only():
    prop = parse_topology_proposal({"family": "coupled_bpf", "order": 4,
                                    "coupling_form": "chebyshev_parallel",
                                    "rationale": "用户要更高矩形度"})
    assert (prop.family, prop.order, prop.source) == ("coupled_bpf", 4, "rule")
    assert prop.rationale == "用户要更高矩形度"
    assert prop.to_dict() == {"family": "coupled_bpf", "order": 4,
                              "coupling_form": "chebyshev_parallel",
                              "rationale": "用户要更高矩形度",
                              "source": "rule"}


# ─── LLM 提议器：零内置通道（#139）+ 同一严格 schema ─────────────────────────

def test_llm_proposer_requires_injected_channel():
    with pytest.raises(TopologyProposalError):
        LLMTopologyProposer(None)               # 无通道显式报错，不真连


def test_llm_proposer_valid_payload_through_strict_schema():
    seen = []

    def fake_llm(prompt: str) -> str:
        seen.append(prompt)
        return '```json\n{"family": "coupled_bpf", "order": 5, ' \
               '"coupling_form": "chebyshev_parallel", ' \
               '"rationale": "窄带高阶"}\n```'

    prop = LLMTopologyProposer(fake_llm).propose(SPEC)
    assert prop.source == "llm" and prop.order == 5
    assert len(seen) == 1
    # prompt 含用户规格（输入侧数字合法），并声明禁数值输出契约
    assert "2.5" in seen[0] and "禁止输出任何其他数值字段" in seen[0]


@pytest.mark.parametrize("reply", [
    '{"family": "coupled_bpf", "order": 3, "f0_ghz": 2.5}',   # 走私频率
    '{"family": "coupled_bpf", "order": 3.5}',                # 非法阶数
    '{"family": "coupled_bpf", "order": 3, "fbw": 0.05}',     # 走私带宽
    '抱歉，我建议三阶平行耦合滤波器。',                          # 无 JSON
    '{"family": "coupled_bpf", "order": 3',                   # 坏 JSON
])
def test_llm_proposer_smuggled_numbers_rejected_no_silent_fallback(reply):
    with pytest.raises(TopologyProposalError):
        LLMTopologyProposer(lambda _p: reply).propose(SPEC)


# ─── synthesis 初值：数字全部出自确定性综合链 ────────────────────────────────

def test_design_initial_values_match_wp23_nominal():
    prop = parse_topology_proposal({"family": "coupled_bpf", "order": 3})
    out = design_initial_values(prop, SPEC)
    assert out["campaign_capable"] is True
    tp = out["template_params"]
    nom = ot.COUPLED_BPF_NOMINAL             # WP2.3 锚（4 位舍入口径）
    assert tp["order"] == nom["order"]
    assert round(tp["res_len_mm"], 4) == nom["res_len_mm"]
    assert round(tp["feed_len_mm"], 4) == nom["feed_len_mm"]
    assert [round(v, 4) for v in tp["widths_mm"]] == nom["widths_mm"]
    assert [round(v, 4) for v in tp["gaps_mm"]] == nom["gaps_mm"]
    assert len(out["design"]["coupling_matrix"]) == 5   # N+2 C13 矩阵


def test_design_accepts_dict_payload_and_spec():
    out = design_initial_values({"family": "coupled_bpf", "order": 2},
                                {"f0_ghz": 2.5, "fbw": 0.08, "rl_db": 15.0})
    assert out["order"] == 2
    assert len(out["design"]["sections"]) == 3


def test_hairpin_design_but_not_campaign_capable():
    prop = parse_topology_proposal({"family": "hairpin", "order": 3})
    out = design_initial_values(prop, SPEC)
    assert out["campaign_capable"] is False
    assert out["template_params"] is None
    assert len(out["design"]["k_list"]) == 2 and out["design"]["qe"] > 0
    with pytest.raises(TopologyCampaignError):
        run_fine_campaign(prop, SPEC)


# ─── 小战役精算：约束精化语义 + 确定性 ──────────────────────────────────────

def test_campaign_constrained_improvement_and_deterministic():
    prop = RuleBasedTopologyProposer().propose(SPEC)
    rec = run_fine_campaign(prop, SPEC, n_trials=40, seed=20260914)
    rec2 = run_fine_campaign(prop, SPEC, n_trials=40, seed=20260914)
    assert rec == rec2                        # 同种子确定性复现
    assert json.dumps(rec, ensure_ascii=False, allow_nan=False)  # JSON 进出
    init, best = rec["initial"], rec["best"]
    # 约束精化语义：RL 恒不劣于初值（代价结构可证），阻带守卫=初值水平
    assert best["rl_min_db"] >= init["rl_min_db"] - 1e-9
    assert best["stop_max_db"] <= init["stop_max_db"] + 1e-9
    assert best["min_gap_mm"] >= rec["gap_floor_mm"] - 1e-9
    assert rec["stage"] == "polish"
    # 首案例关键数字（2026-09-14 实测）：初值 12.93dB → 精化 13.79dB
    assert init["rl_min_db"] == pytest.approx(12.932, abs=0.01)
    assert best["rl_min_db"] == pytest.approx(13.792, abs=0.01)
    assert rec["improvement"]["rl_delta_db"] == pytest.approx(0.859, abs=0.02)
    # C13 理想目标锚与守卫入 record
    assert rec["targets"]["rl_ideal_db"] == pytest.approx(19.047, abs=0.01)
    assert rec["targets"]["stop_ideal_db"] == pytest.approx(-8.309, abs=0.01)
    # 精化配方参数可直接对回 COUPLED_BPF_NOMINAL 键位
    assert set(rec["recipe_params"]) == set(ot.COUPLED_BPF_NOMINAL)
    assert len(rec["recipe_params"]["gaps_mm"]) == 4


def test_campaign_validation_errors():
    prop = RuleBasedTopologyProposer().propose(SPEC)
    with pytest.raises(TopologyCampaignError):
        run_fine_campaign(prop, SPEC, n_trials=0)
    with pytest.raises(TopologyCampaignError):
        run_fine_campaign(prop, SPEC, n_trials=1)   # 预算 < 入队点数
    assert DEFAULT_GAP_FLOOR_MM == 0.10


def test_campaign_absolute_recipe_params_differ_from_initial_when_improved():
    prop = RuleBasedTopologyProposer().propose(SPEC)
    rec = run_fine_campaign(prop, SPEC, n_trials=40)
    base = design_initial_values(prop, SPEC)["template_params"]
    if rec["stage"] == "polish":
        assert rec["recipe_params"] != base      # 精化确实动了几何


# ─── 沙箱落草稿（写面隔离，只写沙箱、不做 promote）───────────────────────────

def test_stage_design_to_sandbox_writes_draft_only(tmp_path):
    from rfauto.service.agent_sandbox import RecipeSandbox

    params = {"order": 3, "w_feed_mm": 1.1117,
              "widths_mm": [0.8952, 1.0956, 1.0956, 0.8952],
              "gaps_mm": [0.1286, 0.7794, 0.7794, 0.1286],
              "res_len_mm": 35.5107, "feed_len_mm": 24.4893}
    out = stage_design_to_sandbox(params, "e10_case", root=tmp_path)
    assert out["ok"]
    draft = Path(out["draft"])
    assert draft.parent == tmp_path.resolve()
    text = draft.read_text(encoding="utf-8")
    assert "coupled_bpf" in text and "res_len_mm" in text
    # 沙箱内草稿，工作区配方面零写入
    assert RecipeSandbox(root=tmp_path).list_drafts()["ok"]
