"""F-H.4 低温材料面内核+service 单测（研究扩充 round4 F-H 件 4）。

裁判口径（#118/#122 先行）：解析锚点由测试侧独立常量与独立代数路径离线
推导——Cu Rs 双路径 √(πfμ₀ρ) vs √(ωμ₀ρ/2)；RRR 恒等式 ρ(T_ref)/ρ(0)=RRR
（模型构造性恒等）；ASE 分界定义恒等式 δ(f_c)==l（f_c 本身由该式反解）；
London 锚 t=(1/2)^(1/4)·Tc → λ=λ₀·√2（1−t⁴=1/2 的代数精确点）；动能电感
双路径 μ₀λ²/t vs (λ/t)·(λμ₀)。IEEE-754 重排 1-ulp 级差——逐位断言只放在
FP 精确保证的恒等式上（T=0 剩余项、f=0 → 0、t=0 → λ₀、κ_k=0 → f₀、
κ_k=0 分支直返），一般情形 rel=1e-12（文件头如实登记，不冒充逐位）。

判据覆盖（spec）：London 温度律端点回收（T→0 λ→λ₀；T→Tc 发散守卫显式
报错）+ Cu RRR 缩放近似带（模型内 Rs(293)/Rs(4K) ∈ [1, √RRR]）+ 表值
来源登记（Nb 带内点值钉 + 介电表 band/provenance/schema 政策钉）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import cryo_materials as cryo
from rfauto.service import cryo_materials_service as svc

# ─── 测试侧独立常量（手算/离线推导，非被测实现产物）─────────────────────────
MU0 = 1.25663706212e-6
RHO293 = 1.68e-8
RRR = 100.0
VF, NE, ME, QE = 1.57e6, 8.47e28, 9.1093837015e-31, 1.602176634e-19
RHO_4K_100 = 3.9505802047781576e-10  # 1.68e-8/100 + (1.68e-8−1.68e-8/100)·4/293
RS_10G_293 = 0.025753396205437745  # √(π·1e10·μ₀·1.68e-8) 手算锚
RS_1G_293 = 0.008143938949392089  # √(π·1e9·μ₀·ρ)
RS_10G_4K = 0.003949210746321881  # √(π·1e10·μ₀·ρ4K)
L_293 = 3.9153912731299136e-08  # VF·ME/(NE·QE²·ρ)
L_4K = 1.6650357663672926e-06
FC_293 = 2775870539788.813  # ρ/(πμ₀l²)
FC_4K = 36095578.98407184
LAMBDA_NB = 39e-9
TC_NB = 9.3
LS_ANCHOR = 1.91134497148452e-13  # μ₀·(39e-9)²/10e-9
XS_6G_ANCHOR = 0.007205600785069872  # 2π·6e9·Ls
Q_ANCHOR = 99800.3992015968  # 1/(1e-5+1e-3/5e4)
F0_K01_R2 = 0.9534625892455922  # f0/√(0.9+0.1·2)


def _rho_ref(t_k: float, rrr_v: float) -> float:
    """测试侧独立 ρ(T) 实现（同公式异构：先写锚点式再约化）。"""
    res = RHO293 / rrr_v
    return res + (RHO293 - res) * (t_k / 293.0)


# ─── 1. 常数与铜电阻率：锚点 + RRR 恒等式 ────────────────────────────────────


def test_mu0_codata_pin():
    # CODATA 2018 推荐值逐位钉（2019 SI 后 μ₀ 非精确定义）
    assert cryo.MU0_SI == 1.25663706212e-6


def test_copper_resistivity_anchors():
    # T=0 → 剩余项逐位（a + 0.0·(x−a) = a，IEEE 精确）
    assert cryo.copper_resistivity(0.0, RRR) == RHO293 / RRR
    # T_ref 锚点 + 测试侧独立实现对照
    assert cryo.copper_resistivity(293.0, RRR) == pytest.approx(RHO293, rel=1e-15)
    assert cryo.copper_resistivity(4.0, RRR) == pytest.approx(RHO_4K_100, rel=1e-12)
    assert cryo.copper_resistivity(4.0, RRR) == pytest.approx(_rho_ref(4.0, RRR), rel=1e-12)
    # RRR=1 → 恒 ρ_ref（声子权重为 0）
    assert cryo.copper_resistivity(77.0, 1.0) == pytest.approx(RHO293, rel=1e-15)


def test_copper_rrr_definition_identity():
    # RRR 定义恒等式 ρ(T_ref)/ρ(0) = RRR（模型构造性精确）
    ratio = cryo.copper_resistivity(293.0, RRR) / cryo.copper_resistivity(0.0, RRR)
    assert ratio == pytest.approx(RRR, rel=1e-15)
    # T 单调增；RRR 增 → 低温柔项下降（同温对照 4K）
    assert cryo.copper_resistivity(4.0, RRR) < cryo.copper_resistivity(77.0, RRR)
    assert cryo.copper_resistivity(77.0, RRR) < cryo.copper_resistivity(293.0, RRR)
    assert cryo.copper_resistivity(4.0, 200.0) < cryo.copper_resistivity(4.0, 50.0)


def test_copper_4k_band_derived():
    # 预声明推导带：ρ(4K)/ρ(293) ∈ [1/RRR, (1+(RRR−1)·4/293)/RRR]
    # （线性声子模型内上界；实测可低于下界——BG T⁵ 滚降未建模，UNVERIFIED①）
    # 上界与模型同式异构（闭式展开 vs 逐步项和）——rel=1e-12 容纳 1-ulp 级差
    ratio = cryo.copper_resistivity(4.0, RRR) / RHO293
    upper = (1.0 + (RRR - 1.0) * 4.0 / 293.0) / RRR
    assert ratio > 1.0 / RRR
    assert ratio == pytest.approx(upper, rel=1e-12)
    with pytest.raises(ValueError):
        cryo.copper_resistivity(4.0, 0.5)  # RRR<1 拦
    with pytest.raises(ValueError):
        cryo.copper_resistivity(-1.0, RRR)
    with pytest.raises(ValueError):
        cryo.copper_resistivity(True, RRR)  # bool 拒收（df7+⑯）


# ─── 2. Rs 正常趋肤 + RRR 缩放近似带 ────────────────────────────────────────


def test_normal_skin_rs_dual_path():
    # 路径 A：√(πfμ₀ρ)；路径 B：√(ωμ₀ρ/2)，ω=2πf——独立重排
    rs_a = cryo.normal_skin_rs_ohm(RHO293, 10e9)
    rs_b = math.sqrt(2.0 * math.pi * 10e9 * MU0 * RHO293 / 2.0)
    assert rs_a == pytest.approx(RS_10G_293, rel=1e-12)
    assert rs_a == pytest.approx(rs_b, rel=1e-12)
    assert cryo.normal_skin_rs_ohm(RHO293, 1e9) == pytest.approx(RS_1G_293, rel=1e-12)
    # √f 标度恒等式：10×f → √10×Rs
    assert cryo.normal_skin_rs_ohm(RHO293, 10e9) == pytest.approx(
        cryo.normal_skin_rs_ohm(RHO293, 1e9) * math.sqrt(10.0), rel=1e-15
    )
    assert cryo.normal_skin_rs_ohm(RHO293, 0.0) == 0.0  # 直流逐位


def test_rs_rrr_scaling_band():
    # RRR 缩放恒等式（近似带口径）：模型内 Rs(293)/Rs(4K) ∈ [1, √RRR]
    # ——下界=声子项贡献使低温 Rs 不低于纯剩余项 √ 缩放
    rs_293 = cryo.normal_skin_rs_ohm(RHO293, 10e9)
    rs_4k = cryo.normal_skin_rs_ohm(cryo.copper_resistivity(4.0, RRR), 10e9)
    assert rs_293 / rs_4k == pytest.approx(math.sqrt(RHO293 / RHO_4K_100), rel=1e-12)
    assert 1.0 <= rs_293 / rs_4k <= math.sqrt(RRR)
    assert rs_4k == pytest.approx(RS_10G_4K, rel=1e-12)
    # 低温收益方向恒等式： cryo Rs < RT Rs
    assert rs_4k < rs_293


def test_mean_free_path_anchors():
    # 293K 手算锚 ~39.2 nm（文献量级核）+ 4K RRR100 锚
    l293 = cryo.carrier_mean_free_path_m(RHO293)
    assert l293 == pytest.approx(L_293, rel=1e-12)
    assert l293 == pytest.approx(VF * ME / (NE * QE**2 * RHO293), rel=1e-12)
    assert 3.8e-8 <= l293 <= 4.0e-8  # 物理量级核（Cu RT ~39 nm）
    assert cryo.carrier_mean_free_path_m(RHO_4K_100) == pytest.approx(L_4K, rel=1e-12)
    # ρ↓ → l↑ 单调（Drude 反比恒等式）
    assert cryo.carrier_mean_free_path_m(RHO293 / 10.0) == pytest.approx(10.0 * l293, rel=1e-12)


def test_ase_crossover_defining_identity():
    # 定义恒等式 δ(f_c) == l（f_c 由该式反解——裁判闭合）
    for rho in (RHO293, RHO_4K_100, 1e-9):
        f_c = cryo.ase_crossover_freq_hz(rho)
        assert cryo.skin_depth_m(rho, f_c) == pytest.approx(cryo.carrier_mean_free_path_m(rho), rel=1e-12)
    assert cryo.ase_crossover_freq_hz(RHO293) == pytest.approx(FC_293, rel=1e-12)
    assert cryo.ase_crossover_freq_hz(RHO_4K_100) == pytest.approx(FC_4K, rel=1e-12)


def test_skin_regime_classifier():
    # 293K：f_c≈2.8 THz → 10 GHz 正常趋肤；4K RRR100：f_c≈36 MHz → 反常
    assert cryo.skin_regime(RHO293, 10e9) == "normal"
    assert cryo.skin_regime(RHO_4K_100, 10e9) == "anomalous"
    # 分界邻域方向：f_c 下方 normal、上方 anomalous（δ=l 处翻转）
    f_c = cryo.ase_crossover_freq_hz(RHO_4K_100)
    assert cryo.skin_regime(RHO_4K_100, f_c * (1.0 - 1e-9)) == "normal"
    assert cryo.skin_regime(RHO_4K_100, f_c * (1.0 + 1e-9)) == "anomalous"
    # RRR 低 → f_c 高（剩余项主导时 l 短——"RRR≲15 无 GHz ASE"方向核）
    assert cryo.ase_crossover_freq_hz(cryo.copper_resistivity(4.0, 10.0)) > cryo.ase_crossover_freq_hz(RHO_4K_100)


def test_copper_surface_face_dataclass():
    face = cryo.copper_surface_face(4.0, RRR, 10e9)
    d = face.to_dict()
    assert d == json.loads(json.dumps(d))  # JSON 可序列化往返
    assert d["rho_ohm_m"] == pytest.approx(RHO_4K_100, rel=1e-12)
    assert d["rs_ohm_per_sq"] == pytest.approx(RS_10G_4K, rel=1e-12)
    assert d["regime"] == "anomalous"
    assert d["f_crossover_hz"] == pytest.approx(FC_4K, rel=1e-12)
    # 与逐函数一致性
    assert face.rs_ohm_per_sq == pytest.approx(
        cryo.normal_skin_rs_ohm(face.rho_ohm_m, 10e9), rel=1e-15
    )


# ─── 3. 超导 London 面：端点回收 + 解析锚 ────────────────────────────────────


def test_london_endpoints_and_divergence_guard():
    # T=0 → λ₀ 逐位（√1=1 精确）；发散守卫 T≥Tc 显式报错
    assert cryo.london_penetration_depth_m(LAMBDA_NB, 0.0, TC_NB) == LAMBDA_NB
    for t_bad in (TC_NB, 1.5 * TC_NB):
        with pytest.raises(ValueError, match="发散"):
            cryo.london_penetration_depth_m(LAMBDA_NB, t_bad, TC_NB)
    # 单调增（(0,1) 域内 t↑ → λ↑）
    lam_prev = 0.0
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        lam = cryo.london_penetration_depth_m(LAMBDA_NB, t * TC_NB, TC_NB)
        assert lam > lam_prev
        lam_prev = lam
    with pytest.raises(ValueError):
        cryo.london_penetration_depth_m(LAMBDA_NB, -1.0, TC_NB)
    with pytest.raises(ValueError):
        cryo.london_penetration_depth_m(LAMBDA_NB, True, TC_NB)  # bool 拒收


def test_london_analytic_sqrt2_anchor():
    # 代数精确点：t=(1/2)^(1/4)·Tc → 1−t⁴=1/2 → λ=λ₀√2
    lam = cryo.london_penetration_depth_m(LAMBDA_NB, 0.5**0.25 * TC_NB, TC_NB)
    assert lam / LAMBDA_NB == pytest.approx(math.sqrt(2.0), rel=1e-12)
    assert lam == pytest.approx(5.51543289325507e-08, rel=1e-12)


def test_sheet_kinetic_inductance_and_reactance():
    # 薄膜动能电感锚（Nb λ=39nm、膜厚 10nm → ~0.191 nH/□）双路径
    ls = cryo.sheet_kinetic_inductance_h_per_sq(LAMBDA_NB, 10e-9)
    assert ls == pytest.approx(LS_ANCHOR, rel=1e-12)
    assert ls == pytest.approx((LAMBDA_NB / 10e-9) * (LAMBDA_NB * MU0), rel=1e-12)
    # 表面电抗：X=ω·Ls；f 线性标度恒等式；f=0 → 0
    xs = cryo.sheet_surface_reactance_ohm_per_sq(6e9, LAMBDA_NB, 10e-9)
    assert xs == pytest.approx(XS_6G_ANCHOR, rel=1e-12)
    assert xs == pytest.approx(2.0 * math.pi * 6e9 * ls, rel=1e-15)
    assert cryo.sheet_surface_reactance_ohm_per_sq(12e9, LAMBDA_NB, 10e-9) == pytest.approx(
        2.0 * xs, rel=1e-12
    )
    assert cryo.sheet_surface_reactance_ohm_per_sq(0.0, LAMBDA_NB, 10e-9) == 0.0
    with pytest.raises(ValueError):
        cryo.sheet_kinetic_inductance_h_per_sq(LAMBDA_NB, 0.0)


def test_superconductor_f0_endpoints_and_anchor():
    # κ_k=0 → f₀ 逐位（无动能电感通道，任意 T）
    assert cryo.superconductor_f0_hz(1e9, 0.0, LAMBDA_NB, 4.0, TC_NB) == 1e9
    # T=0 → f₀（r=1，rel 1e-15）
    assert cryo.superconductor_f0_hz(1e9, 0.5, LAMBDA_NB, 0.0, TC_NB) == pytest.approx(1e9, rel=1e-15)
    # 解析锚：t=(1/2)^(1/4)Tc → r≈2 → f₀/√(1+κ)，κ=0.1 → 0.95346
    f_t = cryo.superconductor_f0_hz(1e9, 0.1, LAMBDA_NB, 0.5**0.25 * TC_NB, TC_NB)
    assert f_t == pytest.approx(1e9 * F0_K01_R2, rel=1e-12)
    # T↑ → f↓（动能电感增大）；London 发散守卫透传
    assert f_t < cryo.superconductor_f0_hz(1e9, 0.1, LAMBDA_NB, 0.2 * TC_NB, TC_NB)
    with pytest.raises(ValueError):
        cryo.superconductor_f0_hz(1e9, 0.1, LAMBDA_NB, TC_NB, TC_NB)
    with pytest.raises(ValueError):
        cryo.superconductor_f0_hz(1e9, 1.5, LAMBDA_NB, 4.0, TC_NB)  # κ>1 拦
    with pytest.raises(ValueError):
        cryo.superconductor_f0_hz(1e9, True, LAMBDA_NB, 4.0, TC_NB)  # bool 拒收


# ─── 4. Q(T) 面：损耗通道相加 + 分解恒等式 ───────────────────────────────────


def test_resonator_q_forms():
    q = cryo.resonator_unloaded_q(1e-5, 1e-3, 5e4)
    assert q == pytest.approx(Q_ANCHOR, rel=1e-12)
    # 纯介质通道：Q=1/tanδ
    assert cryo.resonator_unloaded_q(1e-5) == pytest.approx(1e5, rel=1e-15)
    # 纯导体通道：tanδ=0 → Q=G/Rs
    assert cryo.resonator_unloaded_q(0.0, 1e-3, 5e4) == pytest.approx(5e7, rel=1e-15)
    with pytest.raises(ValueError, match="无定义"):
        cryo.resonator_unloaded_q(0.0)  # 双通道全缺
    with pytest.raises(ValueError, match=r"成对|同时"):
        cryo.resonator_unloaded_q(1e-5, rs_ohm_per_sq=1e-3)  # Rs/G 须成对
    with pytest.raises(ValueError):
        cryo.resonator_unloaded_q(True)  # bool 拒收


def test_resonator_q_breakdown_identity():
    # 恒等式：Q = 1/(1/Q_d + 1/Q_c)（分解→合成的双路径）
    br = cryo.resonator_q_breakdown(1e-5, 1e-3, 5e4)
    assert br.q_dielectric == pytest.approx(1e5, rel=1e-15)
    assert br.q_conductor == pytest.approx(5e7, rel=1e-15)
    assert br.q_unloaded == pytest.approx(
        1.0 / (1.0 / br.q_dielectric + 1.0 / br.q_conductor), rel=1e-15
    )
    assert br.q_unloaded == pytest.approx(Q_ANCHOR, rel=1e-12)
    d = br.to_dict()
    assert d == json.loads(json.dumps(d))
    # 通道缺失 → None 语义（#364④：缺失用 None 非 0）
    br_d = cryo.resonator_q_breakdown(1e-5)
    assert br_d.q_dielectric == pytest.approx(1e5, rel=1e-15)
    assert br_d.q_conductor is None
    with pytest.raises(ValueError):
        cryo.resonator_q_breakdown(0.0)  # 无耗散通道


def test_dielectric_band_feeds_q():
    # 表值消费钉：蓝宝石 4K tanδ 带 → 介质限 Q 包络 [1e7, 1e9]
    band = cryo.CRYO_DIELECTRICS["sapphire_al2o3"]["tan_delta_band_4k_10ghz"]
    q_lo = cryo.resonator_unloaded_q(band[1])  # tanδ 带上界 → Q 下界
    q_hi = cryo.resonator_unloaded_q(band[0])
    assert q_lo == pytest.approx(1.0 / band[1], rel=1e-15)
    assert q_hi == pytest.approx(1.0 / band[0], rel=1e-15)
    assert 1e7 <= q_lo <= q_hi <= 1e9


# ─── 5. 表值来源登记（spec 判据：表值来源 registered）────────────────────────


def test_nb_typical_constants_registered():
    nb = cryo.NB_TYPICAL
    assert nb["tc_band_k"][0] <= nb["tc_k"] <= nb["tc_band_k"][1]
    assert nb["lambda_l0_band_nm"][0] <= nb["lambda_l0_nm"] <= nb["lambda_l0_band_nm"][1]
    assert nb["status"] == "typical"
    assert nb["single_source"] is True  # 单源如实
    assert isinstance(nb["provenance"], str) and len(nb["provenance"]) > 20
    # 点值喂内核：λ₀=39nm、Tc=9.3K 进 London 律得解析锚
    lam = cryo.london_penetration_depth_m(nb["lambda_l0_nm"] * 1e-9, 0.5**0.25 * nb["tc_k"], nb["tc_k"])
    assert lam == pytest.approx(nb["lambda_l0_nm"] * 1e-9 * math.sqrt(2.0), rel=1e-12)


def test_cryo_dielectrics_schema():
    assert set(cryo.CRYO_DIELECTRICS) == {"sapphire_al2o3", "alumina_99p6", "ptfe"}
    for mat, entry in cryo.CRYO_DIELECTRICS.items():
        er_lo, er_hi = entry["er_band"]
        assert 0.0 < er_lo < er_hi, mat
        for key in ("tan_delta_band_300k_10ghz", "tan_delta_band_4k_10ghz"):
            td_lo, td_hi = entry[key]
            assert 0.0 < td_lo < td_hi, f"{mat}.{key}"
        assert entry["status"] == "typical_band"
        assert entry["single_source"] is True  # 单源如实标注
        assert isinstance(entry["provenance"], str) and len(entry["provenance"]) > 20
    # 物理序恒等式：低温 tanδ 带上界 ≤ 300K 带下界（介质损耗随温降单调降的带间关系）
    for entry in cryo.CRYO_DIELECTRICS.values():
        assert entry["tan_delta_band_4k_10ghz"][1] <= entry["tan_delta_band_300k_10ghz"][0]


# ─── 6. service 信封：ok 路径 JSON 往返 + ok=False 收敛不抛 ──────────────────


def _full_payload() -> dict:
    return {
        "t_k": 4.0,
        "rrr": 100.0,
        "f_hz": 10e9,
        "superconductor": {
            "lambda_l0_m": LAMBDA_NB,
            "tc_k": TC_NB,
            "film_thickness_m": 10e-9,
            "f0_at_zero_k_hz": 6e9,
            "kappa_kinetic": 0.1,
        },
        "q_section": {"tan_delta_eff": 1e-6, "rs_ohm_per_sq": RS_10G_4K, "geometry_factor_ohm": 5e4},
    }


def test_service_cryo_ok_path():
    out = svc.cryo_surface_estimate(_full_payload())
    assert out["ok"] is True
    assert json.dumps(out)  # 全量 JSON 可序列化
    assert out["copper"]["regime"] == "anomalous"
    assert out["copper"]["rs_ohm_per_sq"] == pytest.approx(RS_10G_4K, rel=1e-12)
    sc = out["superconductor"]
    # λ(T=4K)/λ₀ 独立路径：1/√(1−t⁴)，t=4/9.3
    assert sc["lambda_ratio"] == pytest.approx(
        1.0 / math.sqrt(1.0 - (4.0 / TC_NB) ** 4), rel=1e-12
    )
    assert sc["lambda_ratio"] > 1.0
    assert sc["f0_hz"] < 6e9  # 动能电感使 f0 下移
    assert out["q"]["q_unloaded"] == pytest.approx(
        1.0 / (1e-6 + RS_10G_4K / 5e4), rel=1e-12
    )


def test_service_cryo_error_envelopes():
    for bad in (
        "not-a-dict",
        {},
        {"t_k": 4.0},  # 缺 rrr/f_hz
        {"t_k": True, "rrr": 100.0, "f_hz": 1e9},  # bool 拒收
        {"t_k": 4.0, "rrr": 0.5, "f_hz": 1e9},  # RRR<1
        dict(_full_payload(), superconductor={"lambda_l0_m": LAMBDA_NB, "tc_k": TC_NB}),  # 缺膜厚
        dict(_full_payload(), superconductor=dict(_full_payload()["superconductor"], kappa_kinetic=0.1, f0_at_zero_k_hz=None)),  # f0/κ 不成对
        dict(_full_payload(), q_section={"tan_delta_eff": 1e-6, "rs_ohm_per_sq": 1e-3}),  # Rs 无 G
    ):
        out = svc.cryo_surface_estimate(bad)
        assert out["ok"] is False, bad
        assert out["errors"], bad
    # T≥Tc → London 守卫在信封内收敛
    out = svc.cryo_surface_estimate(
        dict(_full_payload(), superconductor=dict(_full_payload()["superconductor"], tc_k=4.0))
    )
    assert out["ok"] is False
    assert any("发散" in e for e in out["errors"])
