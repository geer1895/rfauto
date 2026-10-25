"""aurora_g W9-S2 席锚树：内核新域批 3 五键（GNSS 定位几何三键+雷达杂波
扩展两键：Weibull 幅度分布+CA-CFAR 滑窗检测链）。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算——测试
内表达式路径独立于键内实现（原始构造/常数内联，不消费模块中间量）；
#122 三态/UNVERIFIED 如实不凑绿）：

- GNSS 几何矩阵（gdop_dop）：①头号锚=4 星正四面体理想星座（天顶+三颗
  sin el=−1/3 环带，Σu uᵀ=(4/3)I、Σu=0 ⇒ Q=diag(3/4,3/4,3/4,1/4)）闭式
  全族逐位：GDOP=√(5/2)、PDOP=3/2、HDOP=√(3/2)、VDOP=√3/2、TDOP=1/2
  （Kihara-Okada 1984 最优几何经典结果，rel 1e-15）；②共面退化（全零
  仰角）奇异守卫显式拒绝+卫星数 <4 拒绝+零矢量拒绝；③加星单调性=
  Sherman-Morrison（HᵀH 加 PSD 秩一 ⇒ Q Loewner 非增 ⇒ tr 不增）数值钉
  （第 5 星入阵 GDOP 不增）+tr(Q)/对角恒等。
- 方位/仰角档（dop_from_satellite_geometry）：①天顶+地平三脚架（az=
  90/210/330°、el=0°）闭式全族：GDOP=√3、HDOP=VDOP=2/√3、TDOP=1/√3
  （rel 1e-12）；②与 gdop_dop 位置矢量档同一几何双路径对照（azel 三角
  构造 vs 精确坐标，rel 1e-12——trig 舍入 1e-17 级位不逐位）；③az/el
  数目不齐/el 域越界显式拒绝。
- UERE 换算（uere_to_position_error）：①GDOP×UERE 逐位恒等（恒等式即
  键面）；②RSS 分解 GDOP²=HDOP²+VDOP²+TDOP² 残差≈0（四面体闭式值喂入，
  交叉键双源：DOP 取自 gdop_dop 输出）；③σ_time=TDOP·UERE/c 独立算术
  （0.5m UERE、TDOP=1/2 → 1.6678204759907602 ns 数值锤）。
- Weibull 杂波（weibull_clutter_model）：①k=1 退化=指数分布逐位
  （pdf(x)=(1/λ)e^{−x/λ} 独立算术+mean=λ/var=λ² Γ 闭式）；②k=2 退化=
  Rayleigh（σ=λ/√2：cdf(x)=1−exp(−x²/(2σ²)) 独立算术逐点对照）；③纯杂
  波门限 P(X>x_th)=pfa 回代恒等（rel 1e-12）+重尾单调（k↓ ⇒ 门限↑）；
  ④k<1 且 x=0 PDF 发散显式拒绝（不出 inf 保 JSON 信封）。
- CA-CFAR 检测链（cell_averaging_cfar）：①α 恒等式双路径（α·mean vs
  β·Σ 相对残差 <1e-12）+Pfa 回代 (1+β)^{−N} 恒等；②保护带几何=剔除
  中心 2G 逐位（同参考元去保护档输出一致）+与 radar_eq.ca_cfar_threshold
  同式双源（β/α rel 1e-12——彼键 round(·,12) 出账不逐位）；③SW1 Pd 与
  已知噪声极限 Pd_∞ 对照（CFAR 代价 Pd_cf<Pd_known 同 S 逐点）+通胀因子
  >1（有限窗门限高于已知噪声）；④窗长/保护带越界/pfa 域外显式拒绝。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.gnss_geometry import (
    dop_from_satellite_geometry,
    gdop_dop,
    uere_to_position_error,
)
from rfauto.core.calc_families.radar_clutter import (
    cell_averaging_cfar,
    weibull_clutter_model,
)
from rfauto.core.calc_families.radar_eq import ca_cfar_threshold

_C_M_S = 299792458.0  # 原始 SI 定义值（不消费模块常量——#118）


def _tetrahedron_enu() -> list[list[float]]:
    """4 星正四面体理想星座（ENU，单位半径）：天顶+三颗 sin el=−1/3 环带。"""
    r = 2.0 * math.sqrt(2.0) / 3.0
    z = -1.0 / 3.0
    return [
        [0.0, 0.0, 1.0],
        [r, 0.0, z],
        [-r / 2.0, r * math.sqrt(3.0) / 2.0, z],
        [-r / 2.0, -r * math.sqrt(3.0) / 2.0, z],
    ]


# ─── gdop_dop（GNSS 键 1）────────────────────────────────────────────────────

def test_gdop_dop_tetrahedron_exact_family():
    """头号锚：正四面体理想星座 Q=diag(3/4,3/4,3/4,1/4) DOP 闭式全族。"""
    res = gdop_dop(_tetrahedron_enu())
    assert res["n_sat"] == 4
    assert res["gdop"] == pytest.approx(math.sqrt(2.5), rel=1e-15)
    assert res["pdop"] == pytest.approx(1.5, rel=1e-15)
    assert res["hdop"] == pytest.approx(math.sqrt(1.5), rel=1e-15)
    assert res["vdop"] == pytest.approx(math.sqrt(3.0) / 2.0, rel=1e-15)
    assert res["tdop"] == pytest.approx(0.5, rel=1e-15)
    # tr(Q) 恒等：gdop²=q 对角和
    assert res["gdop"] ** 2 == pytest.approx(sum(res["q_diagonal"]),
                                             rel=1e-15)
    # Q 对角闭式值（3×3/4+1/4）
    assert res["q_diagonal"][:3] == pytest.approx([0.75] * 3, rel=1e-15)
    assert res["q_diagonal"][3] == pytest.approx(0.25, rel=1e-15)


def test_gdop_dop_degenerate_guards():
    """共面退化/少星/零矢量/非有限坐标显式拒绝（奇异守卫纪律）。"""
    coplanar = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0],
                [0.0, -1.0, 0.0]]
    with pytest.raises(ValueError, match="奇异"):
        gdop_dop(coplanar)
    with pytest.raises(ValueError, match="4 颗"):
        gdop_dop([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    with pytest.raises(ValueError, match="零矢量"):
        gdop_dop([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                  [0.0, 0.0, 0.0]])
    with pytest.raises(ValueError):
        gdop_dop([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                  [float("nan"), 0.0, 1.0]])


def test_gdop_dop_add_satellite_monotone():
    """加星单调性（Sherman-Morrison：HᵀH 加 PSD 秩一 ⇒ tr(Q) 不增）。"""
    base = gdop_dop(_tetrahedron_enu())
    fifth = gdop_dop([*_tetrahedron_enu(), [0.0, 1.0, 0.0]])
    assert fifth["gdop"] <= base["gdop"]
    # 开工日独立算术：第 5 星（北向地平）入阵 GDOP≈1.4790（数值锤）
    assert fifth["gdop"] == pytest.approx(1.479019945774904, rel=1e-12)


# ─── dop_from_satellite_geometry（GNSS 键 2）─────────────────────────────────

def test_dop_az_el_zenith_horizon_tripod_exact():
    """天顶+地平三脚架（az=90/210/330, el=0）闭式族：GDOP=√3 档。"""
    res = dop_from_satellite_geometry([90.0, 210.0, 330.0, 0.0],
                                      [0.0, 0.0, 0.0, 90.0])
    s3 = math.sqrt(3.0)
    assert res["gdop"] == pytest.approx(s3, rel=1e-12)
    assert res["hdop"] == pytest.approx(2.0 / s3, rel=1e-12)
    assert res["vdop"] == pytest.approx(2.0 / s3, rel=1e-12)
    assert res["tdop"] == pytest.approx(1.0 / s3, rel=1e-12)


def test_dop_az_el_matches_position_path():
    """同一几何双路径对照（azel 三角构造 vs 精确坐标，rel 1e-12）。"""
    el_neg = math.degrees(math.asin(-1.0 / 3.0))
    via_az = dop_from_satellite_geometry([90.0, 210.0, 330.0, 0.0],
                                         [el_neg, el_neg, el_neg, 90.0])
    via_pos = gdop_dop(_tetrahedron_enu())
    for k in ("gdop", "pdop", "hdop", "vdop", "tdop"):
        assert via_az[k] == pytest.approx(via_pos[k], rel=1e-12)


def test_dop_az_el_domain_guards():
    """az/el 数目不齐与仰角域越界显式拒绝。"""
    with pytest.raises(ValueError, match="数目须一致"):
        dop_from_satellite_geometry([0.0, 90.0], [0.0])
    with pytest.raises(ValueError, match="el_deg"):
        dop_from_satellite_geometry([0.0] * 4, [10.0, 20.0, 30.0, 95.0])


# ─── uere_to_position_error（GNSS 键 3）──────────────────────────────────────

def test_uere_identity_and_rss_decomposition():
    """GDOP×UERE 逐位恒等 + RSS 分解残差≈0（DOP 取自 gdop_dop 交叉键）。"""
    g = gdop_dop(_tetrahedron_enu())
    uere = 1.7
    res = uere_to_position_error(uere, g["gdop"], hdop=g["hdop"],
                                 vdop=g["vdop"], tdop=g["tdop"])
    assert res["sigma_3d_m"] == pytest.approx(math.sqrt(2.5) * uere,
                                              rel=1e-15)
    # RSS 分解：gdop² = hdop²+vdop²+tdop²（四面体闭式 2.5）
    assert (res["hdop"] ** 2 + res["vdop"] ** 2 + res["tdop"] ** 2
            ) == pytest.approx(2.5, rel=1e-12)
    assert abs(res["rss_residual"]) < 1e-12
    # σ_3d²=σ_h²+σ_v²+σ_t²（距离单位）
    assert res["sigma_3d_m"] ** 2 == pytest.approx(
        res["sigma_horiz_m"] ** 2 + res["sigma_vert_m"] ** 2
        + (res["tdop"] * uere) ** 2, rel=1e-12)


def test_uere_time_error_value_hammer():
    """σ_time=TDOP·UERE/c 独立算术数值锤（TDOP=1/2、UERE=1m）。"""
    res = uere_to_position_error(1.0, math.sqrt(2.5), tdop=0.5)
    assert res["sigma_time_s"] == pytest.approx(0.5 / _C_M_S, rel=1e-15)
    assert res["sigma_time_ns"] == pytest.approx(
        1.6678204759907602, rel=1e-12)


def test_uere_domain_guards():
    """非正 UERE/GDOP 显式拒绝。"""
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            uere_to_position_error(bad, 2.0)
        with pytest.raises(ValueError):
            uere_to_position_error(1.0, bad)


# ─── weibull_clutter_model（雷达扩展键 1）────────────────────────────────────

def test_weibull_k1_exponential_identity():
    """k=1 退化=指数分布：pdf/mean/var/median 独立算术逐位带。"""
    lam = 2.0
    res = weibull_clutter_model(1.0, lam, x_list=[0.0, 0.5, 1.0, 2.0])
    for x, pdf in zip(res["x_list"], res["pdf"], strict=True):
        assert pdf == pytest.approx((1.0 / lam) * math.exp(-x / lam),
                                    rel=1e-15)
    assert res["mean"] == pytest.approx(lam, rel=1e-15)
    assert res["variance"] == pytest.approx(lam * lam, rel=1e-15)
    assert res["median"] == pytest.approx(lam * math.log(2.0), rel=1e-15)


def test_weibull_k2_rayleigh_identity():
    """k=2 退化=Rayleigh（σ=λ/√2）：cdf 独立算术逐点对照+矩恒等。"""
    lam = 2.0
    sigma = lam / math.sqrt(2.0)
    res = weibull_clutter_model(2.0, lam, x_list=[0.5, 1.0, 3.0])
    for x, cdf in zip(res["x_list"], res["cdf"], strict=True):
        assert cdf == pytest.approx(
            1.0 - math.exp(-x * x / (2.0 * sigma * sigma)), rel=1e-15)
    # Γ 闭式矩：mean=λ·Γ(3/2)=λ√π/2、var=λ²(Γ(2)−Γ(3/2)²)
    assert res["mean"] == pytest.approx(lam * math.sqrt(math.pi) / 2.0,
                                        rel=1e-15)
    g15 = math.gamma(1.5)
    assert res["variance"] == pytest.approx(
        lam * lam * (1.0 - g15 * g15), rel=1e-15)


def test_weibull_k_gt1_zero_pdf_is_zero():
    """k>1 时 f(0)=0（W16 审计 P2 W-1 回归钉：原实现对 k>1 也写 k/λ
    ——Rayleigh f(0)=0 非 2/λ；k=1 指数分布 f(0)=1/λ 不受影响）。"""
    res = weibull_clutter_model(2.0, 2.0, x_list=[0.0])
    assert res["pdf"] == [0.0]
    assert weibull_clutter_model(1.0, 2.0, x_list=[0.0])["pdf"] == \
        pytest.approx([0.5], rel=1e-15)
    assert weibull_clutter_model(3.0, 2.0, x_list=[0.0])["pdf"] == [0.0]


def test_weibull_pfa_threshold_roundtrip_and_monotone():
    """纯杂波门限 P(X>x_th)=pfa 回代恒等 + 形状重尾单调（k↓ ⇒ 门限↑）。"""
    k, lam, pfa = 1.5, 3.0, 1e-3
    res = weibull_clutter_model(k, lam, pfa=pfa)
    assert res["pfa_roundtrip"] == pytest.approx(pfa, rel=1e-12)
    # 门限独立算术
    assert res["pfa_threshold"] == pytest.approx(
        lam * (-math.log(pfa)) ** (1.0 / k), rel=1e-15)
    # 重尾单调：k=0.7（重尾）门限高于 k=2.5（轻尾）
    heavy = weibull_clutter_model(0.7, lam, pfa=pfa)
    light = weibull_clutter_model(2.5, lam, pfa=pfa)
    assert heavy["pfa_threshold"] > light["pfa_threshold"]


def test_weibull_domain_guards():
    """k/λ/pfa 域外与 k<1 且 x=0 发散点显式拒绝（不出 inf）。"""
    with pytest.raises(ValueError):
        weibull_clutter_model(0.0, 2.0)
    with pytest.raises(ValueError):
        weibull_clutter_model(1.0, -2.0)
    with pytest.raises(ValueError):
        weibull_clutter_model(1.0, 2.0, pfa=1.0)
    with pytest.raises(ValueError, match="发散"):
        weibull_clutter_model(0.5, 2.0, x_list=[0.0])


# ─── cell_averaging_cfar（雷达扩展键 2）──────────────────────────────────────

def _window_with_guards(n_lead: int, n_guard: int, n_lag: int,
                        base: float = 1.0) -> list[float]:
    """检测窗构造：前参考|前保护|后保护|后参考（保护单元抬值可辨）。"""
    return ([base + 0.01 * i for i in range(n_lead)]
            + [9.0] * n_guard + [9.0] * n_guard
            + [base + 0.01 * i for i in range(n_lag)])


def test_ca_cfar_alpha_identity_and_pfa_roundtrip():
    """α 恒等式双路径（α·mean vs β·Σ）+Pfa 回代 (1+β)^{−N} 恒等。"""
    win = _window_with_guards(8, 0, 8)
    res = cell_averaging_cfar(win, pfa=1e-4, n_guard=0)
    n = res["n_ref_cells"]
    assert n == 16
    # 独立算术：β=Pfa^(−1/N)−1、α=N·β
    beta = (1e-4) ** (-1.0 / 16) - 1.0
    assert res["beta"] == pytest.approx(beta, rel=1e-15)
    assert res["alpha"] == pytest.approx(16.0 * beta, rel=1e-15)
    # 双路径门限相对残差 <1e-12（浮点恒等面）
    assert abs(res["identity_residual"]) <= 1e-12 * res["threshold"]
    # Pfa 回代恒等
    assert res["pfa_roundtrip"] == pytest.approx(1e-4, rel=1e-12)


def test_ca_cfar_guard_geometry_and_cross_module_anchor():
    """保护带=剔除中心 2G 逐位 + 与 radar_eq.ca_cfar_threshold 同式双源。"""
    refs = [1.0 + 0.01 * i for i in range(12)]
    no_guard = cell_averaging_cfar(refs, pfa=1e-4, n_guard=0)
    padded = cell_averaging_cfar([*refs[:6], 50.0, 50.0, *refs[6:]],
                                 pfa=1e-4, n_guard=1)
    # 剔除保护后参考集逐位同 → 噪声估计/门限逐位一致
    assert padded["n_ref_cells"] == 12
    assert padded["reference_cells"] == no_guard["reference_cells"]
    assert padded["threshold"] == no_guard["threshold"]
    # 同式双源（radar_eq 出账 round(·,12) → rel 1e-12 非逐位）
    ref = ca_cfar_threshold(1e-4, 12)
    assert padded["beta"] == pytest.approx(ref["beta"], rel=1e-12)
    assert padded["alpha"] == pytest.approx(ref["alpha"], rel=1e-12)
    # 决策链：CUT=门限上方/下方
    above = cell_averaging_cfar(refs, pfa=1e-4, n_guard=0,
                                cut_power=no_guard["threshold"] * 10.0)
    below = cell_averaging_cfar(refs, pfa=1e-4, n_guard=0,
                                cut_power=no_guard["threshold"] * 0.5)
    assert above["detect"] is True
    assert above["margin_db"] == pytest.approx(10.0, rel=1e-12)
    assert below["detect"] is False and below["margin_db"] < 0.0


def test_ca_cfar_pd_faces_and_inflation():
    """SW1 Pd 与已知噪声极限对照（CFAR 代价）+通胀因子>1+独立算术锤。"""
    refs = [1.0] * 16
    res = cell_averaging_cfar(refs, pfa=1e-4, n_guard=0, snr_db=10.0)
    beta = (1e-4) ** (-1.0 / 16) - 1.0
    s = 10.0  # 10 dB 线性=10
    # SW1 Pd 独立算术（Richards ch.6 闭式）
    assert res["pd_swerling1"] == pytest.approx(
        (1.0 + beta / (1.0 + s)) ** (-16), rel=1e-15)
    # 已知噪声极限（N→∞）
    assert res["pd_known_noise_limit"] == pytest.approx(
        math.exp(-math.log(1e4) / (1.0 + s)), rel=1e-15)
    # CFAR 代价方向：同 SNR 下有限窗 Pd 低于已知噪声档
    assert res["pd_swerling1"] < res["pd_known_noise_limit"]
    # 通胀因子：门限/已知噪声门限 >1 且独立算术
    assert res["cfar_inflation_vs_known"] == pytest.approx(
        (16.0 * beta) / math.log(1e4), rel=1e-12)
    assert res["cfar_inflation_vs_known"] > 1.0


def test_ca_cfar_domain_guards():
    """窗空/保护带越界/pfa 域外/n_guard 非整显式拒绝。"""
    with pytest.raises(ValueError):
        cell_averaging_cfar([], pfa=1e-4, n_guard=0)
    with pytest.raises(ValueError, match="参考单元"):
        cell_averaging_cfar([1.0, 5.0, 5.0, 1.0], pfa=1e-4, n_guard=2)
    with pytest.raises(ValueError):
        cell_averaging_cfar([1.0, 1.0], pfa=1.5, n_guard=0)
    with pytest.raises(ValueError):
        cell_averaging_cfar([1.0, 1.0], pfa=1e-4, n_guard=1.5)
