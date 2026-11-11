"""悬置带线 G3 FD 静流第三方裁判（core/suspended_stripline_fd_judge.py +
service/suspended_stripline_judge_service.py）单测（Q-X20 / aurora_q）。

裁判先过已知基准才有资格裁判闭式（#300/#118）：Cohn 空气带状线 Z0 锚、
h→b/εr=1 两支构造恒等、与已验证裁判 quasistatic_fd 独立网格族交叉对拍；
预声明收敛锚（六级阶梯三点 Richardson，残差 <0.1%）与 z 空气隙假说分类
阈值边界钉死；负例=阶梯不收敛如实 INCOMPLETE（不凑绿，#122）。

数字锚来源：runs/aurora_q/qx20_fd_judge/judge_result.json（本席实测）；
w2f 角点 eps_fd 抄自 runs/w2f_rescale_batch/ssl_er_scan.json（runs/ 湖
gitignored——测试以常量随行登记出处，不运行时读湖）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import suspended_stripline_fd_judge as fdj
from rfauto.core.calculators import _suspended_stripline_ri
from rfauto.service.suspended_stripline_judge_service import (
    attribution_one_liner,
    suspended_stripline_closed_form_bias,
    suspended_stripline_g3_fd_judge,
)

# G3 点本席实测数字带（judge_result.json；带宽 ±0.2% 容数值环境漂移）
FD_EPS_BAND = (1.5830, 1.5880)
FD_Z0_BAND = (50.30, 50.65)
E1_SHIFT_BAND = (-0.0223, -0.0123)     # 实测 −0.01735
E2_SHIFT_BAND = (-0.0196, -0.0096)     # 实测 −0.01463
E3_SHIFT_BAND = (-0.0094, -0.0000)     # 实测 −0.00436（含 0 上界：x 轴偏移可过 0）


@pytest.fixture(scope="module")
def ladder():
    return fdj.judge_ladder()


@pytest.fixture(scope="module")
def service_result():
    return suspended_stripline_g3_fd_judge()


# ── 裁判资格锚（#300：先过已知基准）──────────────────────────────────────────

def test_exact_limit_anchors_full_fill_and_air_identity():
    """h→b 全填充 εeff=εr 与 εr=1 恒等 εeff=1——构造恒等逐位（钉组装面）。"""
    lim = fdj.exact_limit_anchors()
    assert lim["full_fill_eps_eff"] == pytest.approx(11.9, abs=1e-12)
    assert lim["full_fill_err"] == 0.0
    assert lim["air_identity_eps_eff"] == pytest.approx(1.0, abs=1e-12)
    assert lim["air_identity_err"] == 0.0


def test_thin_substrate_physical_monotone():
    """薄基板物理单调锚：εeff(h=b/100) > 1 且 < εeff(h=b/10)（h→0 极限的
    FD 可达版；非精确恒等——h=0 网格零宽段退化不可入网格，如实声明）。"""
    lim = fdj.exact_limit_anchors()
    assert 1.0 < lim["thin_eps_eff"] < 1.3
    assert lim["thin_minus_air"] > 0.0
    assert lim["thin_lt_thicker"] is True


def test_cohn_air_stripline_anchor_within_frozen_tolerance():
    """空气带状线 Z0 vs Cohn 闭式：外推 rel ≤0.5%（冻结合格线，已验证裁判
    −0.5% 先例同量级）且末两档互差 <0.5%（收敛在位）。"""
    a = fdj.cohn_air_anchor()
    assert a["converged"] is True
    assert abs(a["rel"]) <= 5e-3
    # 随档单调向上收敛（能量法下界性质，先例"收敛向上"同谱）
    rels = a["level_rel"]
    assert all(rels[i] < rels[i + 1] for i in range(len(rels) - 1))


def test_grid_lines_exact_anchors_fail_loud():
    """网格线未精确落在带平面 → RuntimeError fail-loud（构造守卫）。"""
    xs = fdj.judge_x_lines(0.0125, 0.52, 0.50)
    zs_bad = np.linspace(0.0, 0.5, 10)                # 0.25 不在网格线上
    with pytest.raises(RuntimeError, match="带缘"):
        fdj.ssl_capacitance_eps0(xs, zs_bad, 0.52, 0.50, 0.05, 11.9)


# ── 收敛阶梯（预声明门）──────────────────────────────────────────────────────

def test_ladder_converged_status_and_gates(ladder):
    """六级阶梯预声明门全过 → CONVERGED（收敛锚主钉）。"""
    assert ladder.status == "CONVERGED"
    assert all(ladder.gates.values()), ladder.gates


def test_ladder_residuals_below_predeclared_1e3(ladder):
    """四项残差（εeff/C_air × finest/互差）逐项 <0.1%（数字钉，非布尔转述）。"""
    assert ladder.residual_eps_fine < 1e-3
    assert ladder.residual_eps_agree < 1e-3
    assert ladder.residual_cair_fine < 1e-3
    assert ladder.residual_cair_agree < 1e-3


def test_ladder_observed_order_in_window(ladder):
    """观察阶 p ∈ [0.5,4]（零厚边缘奇异一阶族——p≈1 物理合理窗）。"""
    assert 0.5 <= ladder.p_eps <= 4.0
    assert 0.5 <= ladder.p_cair <= 4.0


def test_ladder_fd_values_in_pinned_band(ladder):
    """FD 收敛 εeff/Z0 落本席实测数字带（回归钉；G3 点真值 1.58537/50.482）。"""
    assert FD_EPS_BAND[0] <= ladder.eps_eff <= FD_EPS_BAND[1]
    assert FD_Z0_BAND[0] <= ladder.z0_ohm <= FD_Z0_BAND[1]
    # 1 ≤ εeff ≤ εr 物理括号
    assert 1.0 < ladder.eps_eff < 11.9


def test_ladder_eps_stable_across_depth(ladder):
    """渐近稳定性：5 档与 6 档三点外推互差 <1e-4（shake-down 实测 1.2e-6）。"""
    lad5 = fdj.judge_ladder(levels=5)
    assert lad5.status == "CONVERGED"
    assert abs(lad5.eps_eff - ladder.eps_eff) < 1e-4


def test_referee_cross_check_independent_grid_family(ladder):
    """与已验证裁判 quasistatic_fd（均匀+边缘加密三点档，独立网格族）交叉
    对拍 ≤2e-3——钉住网格族特异性伪象（实测 −1.3e-4）。"""
    xf = fdj.referee_cross_check(eps_self=ladder.eps_eff)
    assert xf["rel_vs_self"] is not None
    assert abs(xf["rel_vs_self"]) <= 2e-3


def test_run_mesh_profile_matches_qx9_artifact():
    """run z 网格画像 = qx9_anchor ssl_open 真跑实测（audit n_lines.z=9；
    空气隙 2 格 112.5µm + 基板半层 2 格 12.5µm——假说检验的网格前提钉死）。"""
    z = fdj.RUN_Z_LINES_MM
    assert len(z) == 9
    assert z == pytest.approx([0.0, 0.1125, 0.225, 0.2375, 0.25, 0.2625,
                               0.275, 0.3875, 0.5], abs=1e-12)
    # 空气隙格宽 112.5µm（下半 0→0.1125→0.225 / 上半 0.275→0.3875→0.5）
    assert z[1] - z[0] == pytest.approx(0.1125, abs=1e-12)
    assert z[8] - z[7] == pytest.approx(0.1125, abs=1e-12)
    # 基板半层格宽 12.5µm（0.225→0.2375→0.25 与镜像）
    assert z[4] - z[3] == pytest.approx(0.0125, abs=1e-12)
    assert z[6] - z[5] == pytest.approx(0.0125, abs=1e-12)
    # x 近场均匀段格宽 = audit min_gap 17.333µm（round(0.26/NEAR) 段宽互证）
    xs = fdj.run_x_lines()
    dx = xs[1] - xs[0]
    assert dx == pytest.approx(0.26 / 15, abs=1e-12)     # =17.333µm
    assert abs(dx * 1e3 - 17.333333333333332) < 1e-9     # µm 口径互证


# ── run 网格离散化假说（E1/E2/E3 + 分类）─────────────────────────────────────

def test_emulation_shifts_pinned_bands(service_result):
    """E1/E2/E3 偏移落实测数字带且方向为负（粗网格静流 εeff 低——回归钉）。"""
    em = {c["tag"]: c for c in service_result["emulation"]["cases"]}
    assert E1_SHIFT_BAND[0] <= em["E1"]["shift_rel"] <= E1_SHIFT_BAND[1]
    assert E2_SHIFT_BAND[0] <= em["E2"]["shift_rel"] <= E2_SHIFT_BAND[1]
    assert E3_SHIFT_BAND[0] <= em["E3"]["shift_rel"] <= E3_SHIFT_BAND[1]
    # 单调：全 run 网格偏移 ≥ z 轴单独偏移 ≥ 0（误差可加性的方向一致性）
    assert em["E1"]["shift_rel"] < em["E2"]["shift_rel"] < 0.0


def test_z_hypothesis_classification_boundaries():
    """分类阈值边界钉（预声明份额 0.60/0.25，纯函数）。"""
    f = fdj.classify_z_airgap_hypothesis
    assert f(-0.024, -0.0145)["verdict"] == "CONFIRMED"       # share 0.604
    assert f(-0.024, -0.0144)["verdict"] == "CONFIRMED"       # share 0.600 恰
    assert f(-0.024, -0.0143)["verdict"] == "PARTIAL"         # share 0.596
    assert f(-0.024, -0.0060)["verdict"] == "PARTIAL"         # share 0.250 恰
    assert f(-0.024, -0.0059)["verdict"] == "REFUTED"         # share 0.246
    assert f(-0.024, +0.001)["verdict"] == "REFUTED"          # 反号
    assert f(0.005, -0.01)["verdict"] == "NO_RESIDUAL"        # 无残余可归因
    g = f(-0.024, -0.0145, -0.020)
    assert g["e1_share"] == pytest.approx(-0.020 / -0.024)


def test_g3_z_hypothesis_lands_partial_band(service_result):
    """G3 实判：z 空气隙假说落 PARTIAL 带（share∈[0.25,0.60)）——本席主结论
    回归钉（shake-down 实测 share=0.588，距 CONFIRMED 线 1.2pp）。"""
    hyp = service_result["attribution"]["z_airgap_hypothesis"]
    assert hyp["verdict"] == "PARTIAL"
    assert 0.25 <= hyp["share"] < 0.60


def test_static_mesh_share_and_unattributed(service_result):
    """静态网格仿真占比与静态外余项：E1 占比 ∈(0.5,0.9)（实测 0.697），
    余项符号为负且 |余项| < |残余| 的一半。"""
    att = service_result["attribution"]
    assert 0.5 < att["static_mesh_share"] < 0.9
    assert att["unattributed_rel"] < 0.0
    assert abs(att["unattributed_rel"]) < 0.5 * abs(
        att["engine_residual_vs_fd_rel"])


# ── 负例（不凑绿，#122）──────────────────────────────────────────────────────

def test_negative_incomplete_on_nonmonotone_ladder(monkeypatch):
    """阶梯不收敛（人造振荡解）→ INCOMPLETE + εeff 回落 finest 档（不凑）。"""

    def oscillating(xs, zs, w, b, h, er):
        if er > 1.0:
            oscillating.i += 1
            vals = [1.590, 1.570, 1.585, 1.575, 1.588, 1.577]
            return vals[(oscillating.i - 1) % 6], 5.9
        return 1.0, 5.9
    oscillating.i = 0

    monkeypatch.setattr(fdj, "_ssl_eps_eff_and_cair", oscillating)
    lad = fdj.judge_ladder()
    assert lad.status == "INCOMPLETE"
    assert not all(lad.gates.values())
    assert lad.gates["monotone_eps_last3"] is False
    # εeff 回落 finest 档原始值（外推值被门拒绝，不凑外推数）
    assert lad.eps_eff == pytest.approx(1.577, abs=1e-12)


def test_negative_ladder_residual_gate_rejects_coarse_depth(monkeypatch):
    """4 档浅阶梯（C_air finest 残差 1.66e-3>1e-3，shake-down 实测数字回放）
    被门拒——预声明 0.1% 红线不因档数少而放行（行为钉）。"""

    def shallow(xs, zs, w, b, h, er):
        if er > 1.0:
            shallow.i += 1
            eps4 = [1.5784889, 1.5821723, 1.5838251, 1.5846501]
            cair4 = [6.0002945, 5.9637158, 5.9454401, 5.9360682]
            return eps4[shallow.i - 1], cair4[shallow.i - 1]
        return 1.0, 5.9360682
    shallow.i = 0

    monkeypatch.setattr(fdj, "_ssl_eps_eff_and_cair", shallow)
    lad = fdj.judge_ladder(levels=4)
    assert lad.status == "INCOMPLETE"
    assert lad.gates["residual_cair_fine"] is False
    assert lad.gates["residual_eps_fine"] is True   # εeff 门过、C_air 门拒


# ── 服务面（规则 4：JSON 进出）───────────────────────────────────────────────

def test_service_json_roundtrip_and_status(service_result):
    """服务输出 JSON 安全（json.dumps 通过）+ 主状态 CONVERGED + 关键块齐。"""
    payload = json.dumps(service_result, ensure_ascii=False)
    assert len(payload) > 1000
    r = json.loads(payload)
    assert r["status"] == "CONVERGED"
    for key in ("point", "fd", "anchors", "emulation", "three_way",
                "bias_rel", "attribution"):
        assert key in r
    assert r["point"]["u_outside_fit_domain"] is True   # u=1.04 在拟合域外


def test_service_three_way_closed_form_matches_facade(service_result):
    """闭式腿=facade `_suspended_stripline_ri` 现场重算逐位一致（不被硬编码）。"""
    tw = service_result["three_way"]
    eps_cf, z0_cf = _suspended_stripline_ri(0.52, 0.50, 0.05, 11.9)
    assert tw["closed_form"]["eps_eff"] == eps_cf
    assert tw["closed_form"]["z0_ohm"] == z0_cf
    assert tw["fd_converged"]["eps_eff"] == service_result["fd"]["eps_eff"]
    assert tw["openems"]["eps_eff_clean"] < tw["fd_converged"]["eps_eff"] \
        < tw["closed_form"]["eps_eff"]                   # 三方排序钉


def test_service_bias_numbers_pinned(service_result):
    """偏差分解数字钉：闭式 +1.14%（w2f 邻域带顶）、openEMS −2.49%、
    HFSS 隐含 +0.29%、FD Z0 vs openEMS ZL +0.03%（±0.15pp 带宽）。"""
    b = service_result["bias_rel"]
    assert b["closed_form_vs_fd"] == pytest.approx(0.011383, abs=1.5e-3)
    assert b["openems_clean_vs_fd"] == pytest.approx(-0.024875, abs=1.5e-3)
    assert b["hfss_implied_vs_fd"] == pytest.approx(0.002919, abs=5e-4)
    assert abs(b["fd_z0_vs_openems_zl"]) < 1.5e-3
    assert b["closed_form_vs_openems_clean"] == pytest.approx(
        0.037183, abs=1.5e-3)


def test_closed_form_bias_corners_systematically_high():
    """w2f 邻域 8 角点（ssl_er_scan.json 实测 eps_fd，常量随行登记出处）：
    闭式全部正向偏高（系统性）且 ≤2%——'+0.4~+1.3% 系统性高' 方向钉。"""
    corners = [
        {"u": 0.719, "s": 0.0625, "epsilon_r": 10.2, "eps_fd": 1.46421},
        {"u": 0.719, "s": 0.0625, "epsilon_r": 12.9, "eps_fd": 1.54471},
        {"u": 0.719, "s": 0.1875, "epsilon_r": 10.2, "eps_fd": 2.03199},
        {"u": 0.719, "s": 0.1875, "epsilon_r": 12.9, "eps_fd": 2.19681},
        {"u": 1.0, "s": 0.0625, "epsilon_r": 10.2, "eps_fd": 1.38483},
        {"u": 1.0, "s": 0.0625, "epsilon_r": 12.9, "eps_fd": 1.44986},
        {"u": 1.0, "s": 0.1875, "epsilon_r": 10.2, "eps_fd": 1.86954},
        {"u": 1.0, "s": 0.1875, "epsilon_r": 12.9, "eps_fd": 2.00322},
    ]
    rows = suspended_stripline_closed_form_bias(corners)
    assert len(rows) == 8
    biases = [r["bias_rel"] for r in rows]
    assert all(b > 0.0 for b in biases)               # 系统性偏高（方向）
    assert max(biases) <= 0.02                        # 量级 ≤2%
    assert 0.0 <= sum(biases) / len(biases) <= 0.02   # 均值量级在案


def test_attribution_one_liner_mentions_partial(service_result):
    """人读一句话定论含 PARTIAL 判语与三个关键百分数（报告面拼装）。"""
    line = attribution_one_liner(service_result)
    assert "PARTIAL" in line
    assert "+1.14%" in line
    assert "-2.49%" in line


def test_service_incomplete_path_honest(monkeypatch):
    """FD 阶梯 INCOMPLETE 时服务 status 如实降级 INCOMPLETE（不凑 CONVERGED）。"""

    def flat(xs, zs, w, b, h, er):
        return 1.5, 6.0   # 零差阶梯 → 残差门拒

    monkeypatch.setattr(fdj, "_ssl_eps_eff_and_cair", flat)
    r = suspended_stripline_g3_fd_judge()
    assert r["status"] == "INCOMPLETE"
    assert r["fd"]["status"] == "INCOMPLETE"
