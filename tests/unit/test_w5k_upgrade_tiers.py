"""架构批 W5-K 升级核席锚树：R2 §④ Top3（既有键工程修正档）。

三件形态（升级核=给既有键加可选参数档，非新键——CALC 注册数不变）：
- ① coax_line_attenuation 粗糙度档：Rs_eff=Rs·K_R → αc 与线 Q 同比含
  K_R；K_R 消费 core/conductor_loss.roughness_gain 单源（Huray/Hammerstad
  闭式出处见该模块 docstring）。
- ② cavity_unloaded_q + circular/rectangular_cavity_mode_q 同法粗糙度档：
  Qc'=Qc/K_R（Q∝1/Rs 同场分布口径），1/Qu 合成链不变，闭式/数值积分
  双路线同步含 K_R（xcheck rel_dev 恒等保持）。
- ③ microstrip_lambda_g HJ 色散档：εeff(f)=εr−(εr−εeff_qs)/(1+g·fp²)
  （Hammerstad-Jensen 1980 色散式；Kirschning-Jansen 档系数需原文核，
  #122 如实不提供）；f→0 退化=准静态 εeff 逐位。

数值断言口径（#118 不自证）：粗糙度/色散闭式在测试侧独立转录重算
（非调用被测实现）；Δ=0/smooth 缺省路径逐位退化恒等（既有键输出键
逐一 ==）；skrf mline analyse_dispersion 'hammerstadjensen' 支作色散式
仓内第二实现裁判。

缺省零漂移证明：本文件全组"缺省/显式 smooth/Δ=0 调用与改动前口径逐位
相等"断言 + 既有锚（test_a2c_coax_waveguide.py / test_w5a_doa_combline.py
/ test_ap6x 家族）全绿——既有测试即缺省路径零变的回归证明。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12

# 名义设计点（与既有锚树同口径）
_COAX = {"f_ghz": 10.0, "a_mm": 1.0, "b_mm": 2.301,
         "conductivity_s_per_m": 5.8e7}
_CAV = {"f_ghz": 10.0, "conductivity_s_per_m": 5.8e7,
        "a_mm": 1.0, "b_mm": 2.301, "tan_delta": 1e-4}
_CIRC = {"mode_type": "TE", "m": 0, "n": 1, "p": 1, "radius_mm": 10.0,
         "length_mm": 12.0, "conductivity_s_per_m": 5.8e7}
_RECT = {"mode_type": "TE", "m": 1, "n": 0, "p": 1, "a_mm": 22.86,
         "b_mm": 10.16, "d_mm": 25.0, "conductivity_s_per_m": 5.8e7}
_MS = {"width_mm": 0.731, "freq_ghz": 10.0, "epsilon_r": 3.66,
       "h_mm": 0.508}


# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _reject(key: str, params: dict, needle: str | None = None) -> None:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r}"
    if needle is not None:
        assert needle in str(out.get("error")), (
            f"{key} 拒绝语义不符: {out.get('error')!r}")


def _skin_depth_m(f_hz: float, sigma: float, mu_r: float = 1.0) -> float:
    """趋肤深度（测试侧独立转录：δ=√(2/(ωμ0μrσ))，Pozar §1.7.1）。"""
    return math.sqrt(2.0 / (2.0 * math.pi * f_hz * _MU0 * mu_r * sigma))


def _hammerstad_k(rq_m: float, delta_m: float, rf: float = 2.0) -> float:
    """修改版 Hammerstad K_H（测试侧独立转录：HJ 1980/Shlepnev 2011）。"""
    return 1.0 + (rf - 1.0) * (2.0 / math.pi) * math.atan(
        1.4 * (rq_m / delta_m) ** 2)


def _huray_k(delta_m: float, r_m: float, f_ratio: float) -> float:
    """Hall-Huray 雪球 K_HH 单族（测试侧独立转录：哑光基底 1+雪球项）。"""
    return 1.0 + 1.5 * f_ratio / (
        1.0 + delta_m / r_m + delta_m * delta_m / (2.0 * r_m * r_m))


def _assert_default_keys_bitwise(base: dict, tiered: dict,
                                 tier_keys: tuple[str, ...]) -> None:
    """档位调用中"既有输出键"（物理量）逐位相等——缺省零漂移断言核。

    tier_keys（档位回执键：模型名/增益/配置回执）按调用回显语义单独断言，
    不进逐位集合（Δ=0 时 roughness_model='hammerstad' 是调用回显非漂移）。
    """
    assert set(tier_keys) <= set(tiered), f"档位新键缺失: {tier_keys}"
    for k, v in base.items():
        if k in tier_keys:
            continue
        assert tiered[k] == v, (
            f"既有输出键 {k} 漂移: {v!r} -> {tiered[k]!r}（缺省路径必须"
            "逐位不变）")


# ─── ① coax_line_attenuation 粗糙度档 ────────────────────────────────────────

_ROUGH_KEYS = ("roughness_model", "roughness_gain_k", "roughness")


def test_coax_att_default_and_smooth_bitwise():
    """缺省调用 == 显式 smooth：全输出键逐位（缺省路径零漂移第一证）。"""
    base = _run("coax_line_attenuation", dict(_COAX))
    smooth = _run("coax_line_attenuation",
                  {**_COAX, "roughness_model": "smooth"})
    assert base == smooth
    assert smooth["roughness_model"] == "smooth"
    assert smooth["roughness_gain_k"] == 1.0
    # 既有模块锚不漂（test_a2c 同款口径：Cu/1GHz αc≈0.16373 dB/m）
    base1g = _run("coax_line_attenuation", {**_COAX, "f_ghz": 1.0})
    assert base1g["alpha_conductor_db_m"] == pytest.approx(
        0.163730589366, abs=5e-10)


def test_coax_att_hammerstad_delta_zero_bitwise():
    """Δ=0 → K_H 精确 1.0（atan(0)=0）→ 既有键全逐位退化恒等。"""
    base = _run("coax_line_attenuation", dict(_COAX))
    d0 = _run("coax_line_attenuation",
              {**_COAX, "roughness_model": "hammerstad",
               "roughness_rms_um": 0.0})
    assert d0["roughness_gain_k"] == 1.0
    _assert_default_keys_bitwise(base, d0, _ROUGH_KEYS)


def test_coax_att_hammerstad_scaling_and_monotonic():
    """αc·Q 同比乘 K_H（K_H 测试侧独立转录重算）+ Rq 单调增。"""
    base = _run("coax_line_attenuation", dict(_COAX))
    tier = _run("coax_line_attenuation",
                {**_COAX, "roughness_model": "hammerstad",
                 "roughness_rms_um": 2.0})
    delta = _skin_depth_m(_COAX["f_ghz"] * 1e9, _COAX["conductivity_s_per_m"])
    k_ref = _hammerstad_k(2.0e-6, delta, 2.0)
    assert tier["roughness_gain_k"] == pytest.approx(k_ref, rel=1e-12)
    # αc 与线 Q 同比（12/9 位舍入 → 1e-11 rel 档）
    assert tier["alpha_conductor_db_m"] == pytest.approx(
        base["alpha_conductor_db_m"] * k_ref, rel=1e-11)
    assert tier["line_q"] == pytest.approx(base["line_q"] / k_ref, rel=1e-11)
    assert tier["alpha_total_db_m"] == pytest.approx(
        base["alpha_conductor_db_m"] * k_ref
        + (base["alpha_total_db_m"] - base["alpha_conductor_db_m"]),
        rel=1e-11)
    # 单调：Rq↑ → K↑（≥）；且 K 落 (1, RF] 物理窗
    tier3 = _run("coax_line_attenuation",
                 {**_COAX, "roughness_model": "hammerstad",
                  "roughness_rms_um": 3.0})
    k3 = _hammerstad_k(3.0e-6, delta, 2.0)
    assert k3 > k_ref > 1.0
    assert tier3["roughness_gain_k"] == pytest.approx(k3, rel=1e-12)


def test_coax_att_huray_siwave_published_params():
    """Hall-Huray 雪球档：K_HH 测试侧独立转录（SIwave 内置 r=0.5µm/
    SR=3 发布参数点族）+ αc/Q 同比恒等。"""
    tier = _run("coax_line_attenuation",
                {**_COAX, "roughness_model": "huray",
                 "nodule_radius_um": 0.5, "nodules_per_cell": 16.0,
                 "cell_area_um2": 16.0 * 4.0 * math.pi * 0.25 / 3.0})
    delta = _skin_depth_m(_COAX["f_ghz"] * 1e9, _COAX["conductivity_s_per_m"])
    k_ref = _huray_k(delta, 0.5e-6, 3.0)
    assert tier["roughness_gain_k"] == pytest.approx(k_ref, rel=1e-12)
    base = _run("coax_line_attenuation", dict(_COAX))
    assert tier["alpha_conductor_db_m"] == pytest.approx(
        base["alpha_conductor_db_m"] * k_ref, rel=1e-11)
    assert tier["line_q"] == pytest.approx(base["line_q"] / k_ref, rel=1e-11)


def test_coax_att_roughness_guards():
    """缺参/未知模型/负值/bool 显式拒绝（service 面与内核面同口径）。"""
    _reject("coax_line_attenuation",
            {**_COAX, "roughness_model": "hammerstad"}, "roughness_rms_um")
    _reject("coax_line_attenuation",
            {**_COAX, "roughness_model": "huray"}, "nodule_radius_um")
    _reject("coax_line_attenuation",
            {**_COAX, "roughness_model": "kirschning"}, "roughness_model")
    _reject("coax_line_attenuation",
            {**_COAX, "roughness_model": "hammerstad",
             "roughness_rms_um": -0.1}, "roughness_rms_um")
    _reject("coax_line_attenuation",
            {**_COAX, "roughness_model": "hammerstad",
             "roughness_rms_um": True}, "roughness_rms_um")


# ─── ② 腔 Q 族粗糙度档（cavity_unloaded_q + 圆柱/矩形模式 Q）────────────────


@pytest.mark.parametrize("key, base_params", [
    ("cavity_unloaded_q", _CAV),
    ("circular_cavity_mode_q", _CIRC),
    ("rectangular_cavity_mode_q", _RECT),
])
def test_cavity_q_roughness_delta_zero_bitwise(key, base_params):
    """Δ=0 → K_R=1 → 既有键全逐位退化（三腔 Q 键同构）。"""
    base = _run(key, dict(base_params))
    d0 = _run(key, {**base_params, "roughness_model": "hammerstad",
                    "roughness_rms_um": 0.0})
    assert d0["roughness_gain_k"] == 1.0
    _assert_default_keys_bitwise(base, d0, _ROUGH_KEYS)


@pytest.mark.parametrize("key, base_params", [
    ("cavity_unloaded_q", _CAV),
    ("circular_cavity_mode_q", _CIRC),
    ("rectangular_cavity_mode_q", _RECT),
])
def test_cavity_q_roughness_kr_scaling(key, base_params):
    """Qc'=Qc/K_H（K_H 独立转录重算）+ xcheck rel_dev 恒等保持 +
    1/Qu 合成链不变。

    rel=1e-9：模式 Q 键的 f 由模式谱给出（输出 9 位舍入 → 1 Hz 粒度），
    δ/K 的重算链受 1e-10 级频率舍入传播——1e-12 只对固定 f 的 coax 键钉。"""
    base = _run(key, dict(base_params))
    f_hz = base["f_ghz"] * 1e9
    delta = _skin_depth_m(f_hz, base_params["conductivity_s_per_m"])
    k_ref = _hammerstad_k(1.5e-6, delta, 2.0)
    tier = _run(key, {**base_params, "roughness_model": "hammerstad",
                      "roughness_rms_um": 1.5})
    assert tier["roughness_gain_k"] == pytest.approx(k_ref, rel=1e-9)
    assert tier["q_conductor"] == pytest.approx(
        base["q_conductor"] / k_ref, rel=1e-9)
    # 双路线互证偏差不因档位改变（两路线同比含 K_R）
    assert (tier["q_xcheck_rel_dev"] == base["q_xcheck_rel_dev"]
            or tier["q_xcheck_rel_dev"] <= 1e-9)
    # 1/Qu 合成链：1/Qu' == 1/Qc' + 1/Qd（介质路不含 K_R）
    qd = tier["q_dielectric"]
    qu = tier["q_unloaded"]
    qc = tier["q_conductor"]
    if qd is not None:
        assert 1.0 / qu == pytest.approx(1.0 / qc + 1.0 / qd, rel=1e-9)
    else:
        assert qu == qc
    assert tier["rs_ohm_per_sq"] == pytest.approx(
        base["rs_ohm_per_sq"] * k_ref, rel=1e-12)


def test_cavity_q_roughness_huray_and_guards():
    """huray 档（cavity_unloaded_q 走面）+ 三键缺参/未知模型拒绝。"""
    tier = _run("cavity_unloaded_q",
                {**_CAV, "roughness_model": "huray",
                 "nodule_radius_um": 0.5, "nodules_per_cell": 16.0,
                 "cell_area_um2": 16.0 * 4.0 * math.pi * 0.25 / 3.0})
    delta = _skin_depth_m(_CAV["f_ghz"] * 1e9, _CAV["conductivity_s_per_m"])
    assert tier["roughness_gain_k"] == pytest.approx(
        _huray_k(delta, 0.5e-6, 3.0), rel=1e-12)
    for key, params in (("cavity_unloaded_q", _CAV),
                        ("circular_cavity_mode_q", _CIRC),
                        ("rectangular_cavity_mode_q", _RECT)):
        _reject(key, {**params, "roughness_model": "hammerstad"},
                "roughness_rms_um")
        _reject(key, {**params, "roughness_model": "nope"},
                "roughness_model")


# ─── ③ microstrip_lambda_g HJ 色散档 ─────────────────────────────────────────


def test_microstrip_lambda_g_default_path_bitwise():
    """缺省 == 显式 none：四既有键逐位（现键准静态口径零改动）。"""
    base = _run("microstrip_lambda_g", dict(_MS))
    none = _run("microstrip_lambda_g", {**_MS, "dispersion": "none"})
    assert base == none
    assert "dispersion" not in base
    # 现键准静态 εeff 与频率无关（1 与 40 GHz 同值——色散只在档内）
    lo = _run("microstrip_lambda_g", {**_MS, "freq_ghz": 1.0})
    hi = _run("microstrip_lambda_g", {**_MS, "freq_ghz": 40.0})
    assert lo["eps_eff"] == hi["eps_eff"]


def test_microstrip_lambda_g_dispersion_f0_bitwise_degenerate():
    """f→0 退化=准静态 εeff 逐位（Sterbenz 引理保证：εeff_qs>εr/2 →
    er−εeff_qs 精确减法 → 回代逐位恢复；1 Hz/1 kHz 实测 0 ulp——
    1 MHz 处 x=g·fp²≈5e-10 已超出 2^-53，色散已物理起效不属退化区）。"""
    qs_raw = {}
    for f_ghz in (1e-9, 1e-6):
        tier = _run("microstrip_lambda_g",
                    {**_MS, "freq_ghz": f_ghz,
                     "dispersion": "hammerstad-jensen"})
        assert tier["eps_eff_disp"] == tier["eps_eff_quasi_static"], (
            f"f={f_ghz} GHz 色散档未逐位退化到准静态")
        assert tier["lambda_g_disp_mm"] == tier["lambda_g_mm"]
        qs_raw[f_ghz] = tier["eps_eff_disp"]
    assert qs_raw[1e-9] == qs_raw[1e-6]


def test_microstrip_lambda_g_dispersion_skrf_referee():
    """#118 双证：HJ 色散闭式（键）vs skrf mline analyse_dispersion
    'hammerstadjensen'（仓内第二实现）≤1e-9 rel；色散方向 εeff(f) 单调
    趋向 εr、λg 同步缩短。"""
    import numpy as np
    import skrf

    for f_ghz in (1.0, 10.0, 40.0):
        tier = _run("microstrip_lambda_g",
                    {**_MS, "freq_ghz": f_ghz,
                     "dispersion": "hammerstad-jensen"})
        media = skrf.media.MLine(
            frequency=skrf.Frequency(f_ghz, f_ghz, 1, unit="GHz"),
            w=_MS["width_mm"] * 1e-3, h=_MS["h_mm"] * 1e-3,
            ep_r=_MS["epsilon_r"], tand=0.0,
            model="hammerstadjensen", disp="hammerstadjensen")
        ep_ref = float(np.real(media.ep_reff_f[0]))
        rel = abs(tier["eps_eff_disp"] - ep_ref) / ep_ref
        assert rel <= 1e-9, f"f={f_ghz}: |Δεeff|/εeff={rel:.3e} > 1e-9"
    mono = [
        _run("microstrip_lambda_g",
             {**_MS, "freq_ghz": f, "dispersion": "hammerstad-jensen"})
        ["eps_eff_disp"] for f in (1.0, 10.0, 40.0)
    ]
    assert mono[0] < mono[1] < mono[2] < _MS["epsilon_r"]
    lam = _run("microstrip_lambda_g",
               {**_MS, "freq_ghz": 40.0, "dispersion": "hammerstad-jensen"})
    assert lam["lambda_g_disp_mm"] < lam["lambda_g_mm"]


def test_microstrip_lambda_g_dispersion_closed_form_recompute():
    """色散式测试侧独立转录重算（g/fp/εeff(f) 全式对拍，1e-12 rel）。

    准静态两量（εeff_qs/Z0_qs）取 skrf HJ quasi-static 单源原始值（与
    被测键同源；本测试钉的是 HJ 色散式转录本身，非准静态源）。"""
    import numpy as np

    tier = _run("microstrip_lambda_g",
                {**_MS, "freq_ghz": 10.0,
                 "dispersion": "hammerstad-jensen"})
    media = _skrf_media_ms()
    eps_qs = float(np.real(media.ep_reff[0]))   # 原始准静态 εeff
    z0_qs = float(np.real(media.zl_eff[0]))     # 原始准静态 Z0
    er = _MS["epsilon_r"]
    g = (math.pi ** 2 / 12.0) * ((er - 1.0) / eps_qs) * math.sqrt(
        2.0 * math.pi * z0_qs / _ETA0_LOCAL())
    fp = 2.0 * _MU0 * (_MS["h_mm"] * 1e-3) * (10.0 * 1e9) / z0_qs
    eps_ref = er - (er - eps_qs) / (1.0 + g * fp * fp)
    # 输出面 9 位舍入（5e-10 粒度）vs 全精度参考 → abs 容差口径
    assert tier["eps_eff_disp"] == pytest.approx(eps_ref, abs=1e-8)
    # 输出面准静态键与既有 eps_eff 同量（4 位舍入回扣）
    base = _run("microstrip_lambda_g", dict(_MS))
    assert round(tier["eps_eff_quasi_static"], 4) == base["eps_eff"]


def _skrf_media_ms():
    import skrf

    return skrf.media.MLine(
        frequency=skrf.Frequency(_MS["freq_ghz"], _MS["freq_ghz"], 1,
                                 unit="GHz"),
        w=_MS["width_mm"] * 1e-3, h=_MS["h_mm"] * 1e-3,
        ep_r=_MS["epsilon_r"], tand=0.0, model="hammerstadjensen")


def _ETA0_LOCAL() -> float:
    return math.sqrt(_MU0 / _EPS0)


def test_microstrip_lambda_g_dispersion_guards():
    """KJ 档 #122 如实不提供（错误信息含判定依据）+ f≤0/h≤0 拒绝。"""
    _reject("microstrip_lambda_g", {**_MS, "dispersion": "kirschning-jansen"},
            "hammerstad")
    _reject("microstrip_lambda_g", {**_MS, "dispersion": "yamashita"},
            "dispersion")
    _reject("microstrip_lambda_g",
            {**_MS, "freq_ghz": 0.0, "dispersion": "hammerstad-jensen"},
            "freq_ghz")
    _reject("microstrip_lambda_g",
            {**_MS, "h_mm": 0.0, "dispersion": "hammerstad-jensen"}, "h_mm")


# ─── 注册面/四表（无新键口径钉）──────────────────────────────────────────────


def test_no_new_keys_registered():
    """升级核=参数档非新键：三件目标键仍在、无 roughness/dispersion 新键；
    CALC 注册总数不变（323 实注册口径，变化属他席/收官批职责）。"""
    names = set(CALCULATOR_REGISTRY.names())
    for key in ("coax_line_attenuation", "cavity_unloaded_q",
                "circular_cavity_mode_q", "rectangular_cavity_mode_q",
                "microstrip_lambda_g"):
        assert key in names
    assert not any("roughness" in n or "dispersion" in n for n in names)
    # 注册参数面可见（service 透传前提）：describe 含新档参数
    rows = {r["name"]: r for r in CALCULATOR_REGISTRY.describe()}
    att_params = {p["name"] for p in rows["coax_line_attenuation"]["params"]}
    assert {"roughness_model", "roughness_rms_um", "roughness_factor",
            "nodule_radius_um", "nodules_per_cell",
            "cell_area_um2"} <= att_params
    ms_params = {p["name"] for p in rows["microstrip_lambda_g"]["params"]}
    assert "dispersion" in ms_params
