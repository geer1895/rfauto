"""aurora36 W5-A 席锚树：doa 三键（MUSIC/ESPRIT/MVDR）+ combline_resonator 三键。

数值断言口径（#118 不自证——合成源回收与独立路线，不用自身推导互证）：
- DOA：①理想协方差双源 MUSIC 峰位回收=真值（<0.01°，黄金分割精化机器
  精度级）；②单源 MUSIC=ESPRIT=真值（ESPRIT TLS 无网格误差 <1e-8°）；
  ③快拍路径 seed 固定逐位可复现 + 单次实现角误差 <0.5°；④MVDR aᴴw=1
  构造恒等（残差 <1e-12，与协方差内容无关）；⑤MVDR 干扰零陷 <−60dB
  （20dB INR 理想协方差）；⑥R=I 退化常规波束形成 w=a/‖a‖² 逐位恒等；
  ⑦厄米化守卫（残差如实回显）+ 奇异/非正定协方差显式拒绝。
- combline/同轴腔：①双向 roundtrip ≤1e-12 相对（f₀↔l）；②f₀=1/(2π√LC)
  口径自洽回代；③C→0 极限=λ/4 短路线自谐振（l/(λg/4)→1，<1e-5）；④
  λ/2 空气腔 f₀=c₀/(2L√εr) 恒等回收（L=100mm→1.49896229GHz）；εr 定标
  精确 ÷√εr；⑤Z0=60/√εr·ln(b/a) 闭式锚 60·ln3；⑥Qu 串联合成单调性
  （Qu≤min(Qc,Qd)、tanδ→0→Qu=Qc、Qc∝√σ、Qc∝√f）；⑦Qc 双路（场积分
  闭式 vs β/(2α)）自洽 + 量级窗（Cu@1GHz/50Ω 口径 ≈5.6e2）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

C_MM_GHZ = 299.792458  # mm·GHz（registry 单源同值，测试侧独立常量）

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


def _cov_to_pairs(r: np.ndarray) -> list:
    """复矩阵 → [re,im] 对嵌套（JSON 输入口径）。"""
    return [[[float(v.real), float(v.imag)] for v in row] for row in r]


def _pairs_to_vec(pairs: list) -> np.ndarray:
    arr = np.array([complex(p[0], p[1]) for p in pairs])
    return arr


# ─── doa_music_spectrum：理想协方差回收 / 快拍复现 / 显式协方差 / 守卫 ───────


def test_music_ideal_covariance_dual_source_recovery():
    """理想协方差双源：MUSIC 峰位回收=真值（<0.01°），谱形状契约成立。"""
    from rfauto.core.calc_families.doa import synthesize_ula_covariance

    r = _run("doa_music_spectrum", {
        "n_elements": 8, "angles_deg": [-20.0, 30.0], "snr_db": 15.0,
        "grid_step_deg": 0.05})
    assert r["mode"] == "ideal" and r["peaks_found"] == 2
    assert r["n_snapshots"] is None
    assert r["estimated_angles_deg"] == pytest.approx([-20.0, 30.0], abs=0.01)
    assert r["abs_error_deg_max"] < 0.01
    # 谱契约：长度=180/步长，峰归一 0dB，全有限
    assert len(r["theta_grid_deg"]) == len(r["music_spectrum_db"]) == 3600
    assert max(r["music_spectrum_db"]) == pytest.approx(0.0, abs=1e-9)
    assert all(math.isfinite(v) for v in r["music_spectrum_db"])
    # 独立重构：同一协方差手工做 MUSIC → argmax 谱峰含真值邻域为全局最高
    r_h, _ = synthesize_ula_covariance(8, 0.5, [-20.0, 30.0], 15.0, None, 0)
    w, vecs = np.linalg.eigh(r_h)
    e_n = vecs[:, np.argsort(w)[::-1][2:]]  # 后 N−m 列（特征值降序）
    grid = np.arange(-89.9, 90.0, 0.1)
    spec = []
    for th in grid:
        a = np.exp(1j * 2.0 * math.pi * 0.5 * math.sin(math.radians(th))
                   * np.arange(8))
        spec.append(1.0 / float(np.sum(np.abs(e_n.conj().T @ a) ** 2)))
    spec = np.array(spec)
    for th in (-20.0, 30.0):
        neighborhood = np.abs(grid - th) <= 0.5
        # 两源峰都是天文量级、但相对高度随格点对真值的贴近度不同——
        # 判据=真值邻域含 ≥0.1×全局峰的锐峰（旁瓣地板在 1e-22 量级之下）
        assert float(spec[neighborhood].max()) >= 0.1 * float(spec.max()), (
            f"独立 MUSIC 谱在真值 {th}° 邻域非锐峰")


def test_music_single_source_matches_esprit_and_truth():
    """单源：MUSIC（网格法）=ESPRIT（无网格 TLS）=真值，三口互证。"""
    truth = 12.0
    rm = _run("doa_music_spectrum",
              {"n_elements": 8, "angles_deg": [truth], "snr_db": 15.0})
    re_ = _run("doa_esprit",
               {"n_elements": 8, "angles_deg": [truth], "snr_db": 15.0})
    assert rm["estimated_angles_deg"][0] == pytest.approx(truth, abs=0.01)
    assert re_["estimated_angles_deg"][0] == pytest.approx(truth, abs=1e-8)
    assert re_["abs_error_deg_max"] < 1e-8
    assert abs(rm["estimated_angles_deg"][0]
               - re_["estimated_angles_deg"][0]) < 0.01


def test_music_sample_path_seeded_reproducible():
    """快拍路径：seed=7/T=256 单次实现 <0.5°，且两次调用逐位可复现。"""
    params = {"n_elements": 8, "angles_deg": [-20.0, 30.0], "snr_db": 10.0,
              "n_snapshots": 256, "seed": 7}
    r1 = _run("doa_music_spectrum", params)
    r2 = _run("doa_music_spectrum", params)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    assert r1["mode"] == "sample"
    assert r1["abs_error_deg_max"] < 0.5
    # 换种子轨迹必须变（非退化随机源）
    r3 = _run("doa_music_spectrum", dict(params, seed=8))
    assert r1["estimated_angles_deg"] != r3["estimated_angles_deg"]


def test_music_explicit_covariance_path_matches_synthesis():
    """显式协方差路径与合成路径同 R 同解（[re,im] 嵌套 JSON 口径）。"""
    from rfauto.core.calc_families.doa import synthesize_ula_covariance

    r_h, _ = synthesize_ula_covariance(8, 0.5, [-20.0, 30.0], 15.0, None, 0)
    rs = _run("doa_music_spectrum", {
        "n_elements": 8, "angles_deg": [-20.0, 30.0], "snr_db": 15.0})
    rx = _run("doa_music_spectrum", {
        "n_elements": 8, "covariance": _cov_to_pairs(r_h), "n_sources": 2})
    assert rx["mode"] == "explicit_covariance"
    assert rx["estimated_angles_deg"] == rs["estimated_angles_deg"]
    _reject("doa_music_spectrum", {"n_elements": 8,
                                   "covariance": _cov_to_pairs(r_h)},
            needle="n_sources")


def test_music_domain_guards():
    """越界显式拒绝：阵元数/间距/角度/源数/快拍/网格步长/输入路径互斥。"""
    _reject("doa_music_spectrum", {"n_elements": 1, "angles_deg": [10.0]},
            needle="≥2")
    _reject("doa_music_spectrum",
            {"n_elements": 8, "spacing_lambda": 0.0, "angles_deg": [10.0]},
            needle="spacing_lambda")
    _reject("doa_music_spectrum",
            {"n_elements": 8, "spacing_lambda": 1.5, "angles_deg": [10.0]})
    _reject("doa_music_spectrum", {"n_elements": 8, "angles_deg": [90.0]})
    _reject("doa_music_spectrum", {"n_elements": 8, "angles_deg": [97.0]})
    _reject("doa_music_spectrum",
            {"n_elements": 8, "angles_deg": [10.0, 10.0000005]})
    _reject("doa_music_spectrum",
            {"n_elements": 4, "angles_deg": [10.0, 20.0, 30.0, 40.0]},
            needle="m=")
    _reject("doa_music_spectrum",
            {"n_elements": 8, "angles_deg": [-20.0, 30.0], "snr_db": 10.0,
             "n_snapshots": 4}, needle="快拍数")
    _reject("doa_music_spectrum",
            {"n_elements": 8, "angles_deg": [-20.0, 30.0], "seed": -1})
    _reject("doa_music_spectrum",
            {"n_elements": 8, "angles_deg": [-20.0, 30.0],
             "grid_step_deg": 0.01})
    _reject("doa_music_spectrum",
            {"n_elements": 8, "angles_deg": [-20.0, 30.0], "n_sources": 3})
    _reject("doa_music_spectrum", {"n_elements": 8})  # 两条协方差路径都不给
    _reject("doa_music_spectrum",
            {"n_elements": 8, "angles_deg": [10.0],
             "covariance": [[1, 0], [0, 1]]})  # 两条路径同时给


# ─── doa_esprit：TLS 闭式 / ψ 结构 / 守卫 ────────────────────────────────────


def test_esprit_ideal_dual_source_recovery_and_psi_structure():
    """理想协方差双源：TLS-ESPRIT 回收 <1e-6°；ψ=exp(j2π(d/λ)sinθ) 结构。"""
    angles = [-20.0, 30.0]
    r = _run("doa_esprit",
             {"n_elements": 8, "angles_deg": angles, "snr_db": 15.0})
    assert r["n_valid_roots"] == 2
    assert r["estimated_angles_deg"] == pytest.approx(angles, abs=1e-6)
    assert r["abs_error_deg_max"] < 1e-6
    # ψ 结构独立核对：理想协方差下 |ψ|→1，相角=2π(d/λ)sinθ（模 2π 取主值）
    for psi_pair, th in zip(r["psi_re_im"], angles, strict=True):
        psi = complex(psi_pair[0], psi_pair[1])
        assert abs(abs(psi) - 1.0) < 1e-9
        expect = 2.0 * math.pi * 0.5 * math.sin(math.radians(th))
        dev = math.remainder(float(np.angle(psi)) - expect, 2.0 * math.pi)
        assert dev == pytest.approx(0.0, abs=1e-9)


def test_esprit_sample_path_seeded_reproducible():
    """快拍路径 seed=3/T=512：单次实现 <0.5° 且逐位可复现。"""
    params = {"n_elements": 8, "angles_deg": [-20.0, 30.0], "snr_db": 10.0,
              "n_snapshots": 512, "seed": 3}
    r1 = _run("doa_esprit", params)
    r2 = _run("doa_esprit", params)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    assert r1["abs_error_deg_max"] < 0.5


def test_esprit_domain_guards():
    """ESPRIT 越界拒绝（与 MUSIC 同守卫族）+ 奇异协方差显式拒绝。"""
    _reject("doa_esprit", {"n_elements": 2, "angles_deg": [5.0, 10.0]},
            needle="m=")
    _reject("doa_esprit", {"n_elements": 1, "angles_deg": [5.0]})
    _reject("doa_esprit",
            {"n_elements": 8, "angles_deg": [10.0], "spacing_lambda": 0.0})
    # 秩亏奇异协方差 diag(1,0)（显式 [re,im] 嵌套）——显式拒绝不伪逆兜底
    _reject("doa_esprit",
            {"n_elements": 2, "covariance": [[1, 0], [0, 0]],
             "n_sources": 1}, needle="奇异")
    _reject("doa_music_spectrum",
            {"n_elements": 2, "covariance": [[1, 0], [0, 0]],
             "n_sources": 1}, needle="奇异")


# ─── doa_mvdr_weights：恒等式 / 零陷 / 白噪声退化 / 厄米化 / 守卫 ────────────


def _mvdr_ideal_r(n: int = 8, angles: tuple = (-25.0, 35.0),
                  snr_db: float = 20.0) -> np.ndarray:
    from rfauto.core.calc_families.doa import synthesize_ula_covariance

    r_h, _ = synthesize_ula_covariance(n, 0.5, list(angles), snr_db, None, 0)
    return r_h


def test_mvdr_look_direction_gain_identity():
    """aᴴw=1 构造恒等：期望方向增益恒 1（与协方差/方向内容无关）。"""
    r_h = _mvdr_ideal_r()
    r = _run("doa_mvdr_weights", {
        "covariance": _cov_to_pairs(r_h), "look_angle_deg": 10.0,
        "probe_angles_deg": [-25.0, 35.0, 10.0]})
    assert abs(r["look_gain_abs"] - 1.0) < 1e-12
    assert r["identity_residual"] < 1e-12
    assert r["look_gain_db"] == pytest.approx(0.0, abs=1e-9)
    # 探针 10° 处响应=1（期望方向），权重 JSON 往返后 aᴴw 复核
    w = np.array([complex(p[0], p[1]) for p in r["weights_re_im"]])
    a10 = np.exp(1j * 2.0 * math.pi * 0.5 * math.sin(math.radians(10.0))
                 * np.arange(8))
    assert abs(np.vdot(a10, w) - 1.0) < 1e-9


def test_mvdr_interferer_null_depth():
    """干扰源方向零陷：20dB INR 理想协方差下探针响应与栅格零陷 <−60dB。"""
    r_h = _mvdr_ideal_r()
    r = _run("doa_mvdr_weights", {
        "covariance": _cov_to_pairs(r_h), "look_angle_deg": 10.0,
        "probe_angles_deg": [-25.0, 35.0]})
    by_angle = {p["angle_deg"]: p["response_db"] for p in r["probe_responses"]}
    assert by_angle[-25.0] < -60.0
    assert by_angle[35.0] < -60.0
    assert r["null_depth_db"] < -60.0
    assert r["lambda_min_over_max"] > 0.0


def test_mvdr_white_covariance_conventional_beamformer_identity():
    """R=I 退化：w=a/‖a‖²（常规波束形成）逐位恒等。"""
    n = 4
    cov_i = [[[1.0, 0.0] if i == j else [0.0, 0.0]
              for j in range(n)] for i in range(n)]
    r = _run("doa_mvdr_weights",
             {"covariance": cov_i, "look_angle_deg": 25.0})
    a = np.exp(1j * 2.0 * math.pi * 0.5 * math.sin(math.radians(25.0))
               * np.arange(n))
    w_expect = a / float(np.vdot(a, a).real)
    w_got = np.array([complex(p[0], p[1]) for p in r["weights_re_im"]])
    assert float(np.max(np.abs(w_got - w_expect))) < 1e-12


def test_mvdr_hermitization_guard_and_steering_path():
    """非厄米输入先厄米化（残差如实回显）+ 显式 steering 与角构造同权重。"""
    # 非厄米 2×2：[[3+0j, 1+0j],[2+0j, 3+0j]] → R−Rᴴ 残差=1（实镜面反对称），
    # 厄米化后 R=[[3,1.5],[1.5,3]] 正定可解
    r = _run("doa_mvdr_weights", {
        "covariance": [[[3, 0], [1, 0]], [[2, 0], [3, 0]]],
        "look_angle_deg": 15.0})
    assert r["hermitization_residual"] == pytest.approx(1.0, abs=1e-12)
    assert abs(r["look_gain_abs"] - 1.0) < 1e-12
    # 显式 steering 路径与 look 角构造路径同解（同 spacing 口径）
    from rfauto.core.calc_families.doa import _steering_vector

    a15 = _steering_vector(2, 0.5, math.sin(math.radians(15.0)))
    r2 = _run("doa_mvdr_weights", {
        "covariance": [[[3, 0], [1, 0]], [[2, 0], [3, 0]]],
        "steering": [[float(a15[0].real), float(a15[0].imag)],
                     [float(a15[1].real), float(a15[1].imag)]]})
    assert r2["weights_re_im"] == r["weights_re_im"]
    assert r2["look_angle_deg"] is None


def test_mvdr_domain_guards():
    """MVDR 越界拒绝：奇异协方差/非正定/维数/方向互斥/探针角域。"""
    cov_i = [[[1.0, 0.0], [0.0, 0.0]], [[0.0, 0.0], [1.0, 0.0]]]
    _reject("doa_mvdr_weights", {"covariance": [[1, 0], [0, 0]]},
            needle="奇异")
    _reject("doa_mvdr_weights",
            {"covariance": [[1, 0], [1, 0]]}, needle="非正定")
    _reject("doa_mvdr_weights",
            {"covariance": [[-1, 0], [0, 1]]}, needle="正定")
    _reject("doa_mvdr_weights", {"covariance": [[1, 0]]})
    _reject("doa_mvdr_weights", {"covariance": cov_i})  # 方向一个都不给
    _reject("doa_mvdr_weights",
            {"covariance": cov_i, "look_angle_deg": 10.0,
             "steering": [[1, 0], [0, 0]]})  # 方向两个都给
    _reject("doa_mvdr_weights",
            {"covariance": cov_i, "look_angle_deg": 95.0})
    _reject("doa_mvdr_weights",
            {"covariance": cov_i, "look_angle_deg": 10.0,
             "spacing_lambda": 0.0})
    _reject("doa_mvdr_weights",
            {"covariance": cov_i, "look_angle_deg": 10.0,
             "probe_angles_deg": [91.0]})
    _reject("doa_mvdr_weights",
            {"covariance": cov_i,
             "steering": [[1, 0], [0, 0], [0, 0]]}, needle="长度")


# ─── combline_resonance：双向 roundtrip / C→0 极限 / εr 定标 / 守卫 ──────────


def test_combline_bidirectional_roundtrip_and_lc_identity():
    """给 f₀ 反解杆长 ↔ 给杆长回解 f₀（≤1e-12 相对）+ f₀=1/(2π√LC) 自洽。"""
    zr, cap_ff, er, f0 = 80.0, 1000.0, 1.0, 2.0
    rs = _run("combline_resonance",
              {"zr_ohm": zr, "cap_ff": cap_ff, "epsilon_r": er,
               "f0_ghz": f0})
    # 独立参考：θ₀=arctan(1/(ω₀C·Zr))，l=θ₀·c₀/(2π·f₀·√εeff)（测试侧重算）
    omega = 2.0 * math.pi * f0 * 1e9
    theta = math.atan(1.0 / (omega * cap_ff * 1e-15 * zr))
    l_ref = math.degrees(theta) / 360.0 * (C_MM_GHZ / (f0 * math.sqrt(er)))
    assert rs["theta_deg"] == pytest.approx(math.degrees(theta), abs=5e-9)
    assert 0.0 < rs["theta_deg"] < 90.0
    assert rs["length_mm"] == pytest.approx(l_ref, rel=1e-12)
    assert rs["length_mm"] == pytest.approx(18.674, abs=5e-3)  # 文献量级
    ra = _run("combline_resonance",
              {"zr_ohm": zr, "cap_ff": cap_ff, "epsilon_r": er,
               "length_mm": rs["length_mm"]})
    assert ra["f0_ghz"] == pytest.approx(f0, rel=1e-12)
    assert ra["route"] == "analyze_f0" and rs["route"] == "synthesize_length"
    # f₀=1/(2π√(L(ω₀)·C)) 口径自洽回代
    assert rs["f0_lc_selfcheck_ghz"] == pytest.approx(f0, rel=1e-12)
    assert rs["equiv_l_nh"] == pytest.approx(
        zr * math.tan(theta) / omega * 1e9, rel=1e-12)


def test_combline_capacitance_to_zero_quarter_wave_limit():
    """C→0 极限：f₀→c₀/(4·l·√εeff)（λ/4 短路线自谐振），l/(λg/4)→1。"""
    length = 18.673861049933
    r = _run("combline_resonance",
             {"zr_ohm": 80.0, "cap_ff": 1e-3, "epsilon_r": 1.0,
              "length_mm": length})
    f_quarter = C_MM_GHZ / (4.0 * length)
    assert r["f0_ghz"] == pytest.approx(f_quarter, rel=1e-5)
    assert abs(r["l_over_quarter_wave"] - 1.0) < 1e-5
    assert r["theta_deg"] == pytest.approx(90.0, abs=1e-3)
    # 对照：电容有限时频率低于 λ/4 极限（θ<90° ⇒ 谐振频率更低）——单调方向
    r2 = _run("combline_resonance",
              {"zr_ohm": 80.0, "cap_ff": 1000.0, "epsilon_r": 1.0,
               "length_mm": length})
    assert r2["f0_ghz"] < r["f0_ghz"]


def test_combline_epsilon_r_scaling_and_domain_guards():
    """εr 依赖：有限 C 域方向单调+根满足谐振条件残差；λ/4 极限域精确 √er 定标。"""
    zr, cap_ff, length = 80.0, 1000.0, 18.7
    r1 = _run("combline_resonance",
              {"zr_ohm": zr, "cap_ff": cap_ff, "epsilon_r": 1.0,
               "length_mm": length})
    r4 = _run("combline_resonance",
              {"zr_ohm": zr, "cap_ff": cap_ff, "epsilon_r": 4.0,
               "length_mm": length})
    # 方向：εeff↑ ⇒ 同杆长谐振频率下降（θ 域单调）
    assert r4["f0_ghz"] < r1["f0_ghz"]
    # 每个根独立回代谐振条件 ω₀·C·Zr·tanθ₀ = 1（测试侧重算）
    for r in (r1, r4):
        omega = 2.0 * math.pi * r["f0_ghz"] * 1e9
        resid = (omega * cap_ff * 1e-15 * zr
                 * math.tan(math.radians(r["theta_deg"])))
        assert resid == pytest.approx(1.0, rel=1e-9)
    # λ/4 极限域（C→0，θ→90°）：f₀ = c₀/(4·l·√εeff) → 比值精确 √εr
    q1 = _run("combline_resonance",
              {"zr_ohm": zr, "cap_ff": 1e-3, "epsilon_r": 1.0,
               "length_mm": length})
    q4 = _run("combline_resonance",
              {"zr_ohm": zr, "cap_ff": 1e-3, "epsilon_r": 4.0,
               "length_mm": length})
    assert q1["f0_ghz"] / q4["f0_ghz"] == pytest.approx(
        math.sqrt(4.0), rel=1e-5)
    for bad in ({"zr_ohm": 0.0, "cap_ff": 1000.0, "epsilon_r": 1.0,
                 "f0_ghz": 2.0},
                {"zr_ohm": 80.0, "cap_ff": 0.0, "epsilon_r": 1.0,
                 "f0_ghz": 2.0},
                {"zr_ohm": 80.0, "cap_ff": -1.0, "epsilon_r": 1.0,
                 "f0_ghz": 2.0},
                {"zr_ohm": 80.0, "cap_ff": 1000.0, "epsilon_r": 0.5,
                 "f0_ghz": 2.0},
                {"zr_ohm": 80.0, "cap_ff": 1000.0, "epsilon_r": 1.0},
                {"zr_ohm": 80.0, "cap_ff": 1000.0, "epsilon_r": 1.0,
                 "f0_ghz": 2.0, "length_mm": 18.7},
                {"zr_ohm": 80.0, "cap_ff": 1000.0, "epsilon_r": 1.0,
                 "f0_ghz": 0.0},
                {"zr_ohm": 80.0, "cap_ff": 1000.0, "epsilon_r": 1.0,
                 "length_mm": 0.0}):
        _reject("combline_resonance", bad)


# ─── coaxial_cavity_resonance：λ/2 恒等 / εr 定标 / Z0+TE11 / 守卫 ───────────


def test_coax_half_wave_air_identity_recovery():
    """λ/2 空气腔恒等回收：L=100mm → f₀=c₀/2L=1.49896229GHz，双向 roundtrip。"""
    r = _run("coaxial_cavity_resonance", {"mode": "half", "length_mm": 100.0})
    assert r["f0_ghz"] == pytest.approx(C_MM_GHZ / 200.0, rel=1e-12)
    rt = _run("coaxial_cavity_resonance",
              {"mode": "half", "f0_ghz": r["f0_ghz"]})
    assert rt["length_mm"] == pytest.approx(100.0, rel=1e-12)
    # λ/4 短路-开路腔：L=50mm 同频（同一 f₀ 两种腔长口径）
    rq = _run("coaxial_cavity_resonance", {"mode": "quarter",
                                           "length_mm": 50.0})
    assert rq["f0_ghz"] == pytest.approx(r["f0_ghz"], rel=1e-12)
    # εr=2.25 定标：f₀ 精确 ÷1.5
    re_ = _run("coaxial_cavity_resonance",
               {"mode": "half", "length_mm": 100.0, "epsilon_r": 2.25})
    assert re_["f0_ghz"] == pytest.approx(r["f0_ghz"] / 1.5, rel=1e-12)


def test_coax_z0_closed_form_and_te11_single_mode():
    """Z0=(60/√εr)ln(b/a) 闭式锚 + TE11 截止与单模域判定。"""
    r = _run("coaxial_cavity_resonance",
             {"mode": "half", "f0_ghz": 2.0, "a_mm": 1.0, "b_mm": 3.0})
    assert r["z0_ohm"] == pytest.approx(60.0 * math.log(3.0), rel=1e-9)
    te11_ref = C_MM_GHZ / (math.pi * (1.0 + 3.0))
    assert r["te11_cutoff_ghz"] == pytest.approx(te11_ref, rel=1e-9)
    assert r["te11_single_mode"] is True
    # f₀ 抬到 TE11 之上：单模假设失效如实标注（不拒绝，TEM 式仍成立）
    r_hi = _run("coaxial_cavity_resonance",
                {"mode": "half", "f0_ghz": 30.0, "a_mm": 1.0, "b_mm": 3.0})
    assert r_hi["te11_single_mode"] is False
    assert r_hi["note"]


def test_coax_domain_guards():
    """同轴腔越界显式拒绝（mode/f≤0/负腔长/a≥b/半径单给/εr<1）。"""
    for bad in ({"mode": "bogus", "f0_ghz": 2.0},
                {"mode": "half", "f0_ghz": 0.0},
                {"mode": "half", "length_mm": -1.0},
                {"mode": "half", "f0_ghz": 2.0, "a_mm": 3.0, "b_mm": 1.0},
                {"mode": "half", "f0_ghz": 2.0, "a_mm": 2.0, "b_mm": 2.0},
                {"mode": "half", "f0_ghz": 2.0, "a_mm": 1.0},
                {"mode": "half", "f0_ghz": 2.0, "epsilon_r": 0.9},
                {"mode": "half"}):
        _reject("coaxial_cavity_resonance", bad)


# ─── cavity_unloaded_q：串联合成单调性 / √σ·√f 定标 / 双路自洽 / 守卫 ─────────


def test_unloaded_q_series_synthesis_monotonicity():
    """1/Qu=1/Qc+1/Qd：Qu≤min、tanδ→0→Qu=Qc、有限 tanδ 严格降。"""
    base = {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
            "a_mm": 1.0, "b_mm": 2.301}
    q0 = _run("cavity_unloaded_q", base)
    assert q0["q_dielectric"] is None          # 无耗介质 Qd=∞ 如实返 null
    assert q0["q_unloaded"] == q0["q_conductor"]
    q1 = _run("cavity_unloaded_q", dict(base, tan_delta=1e-4))
    assert q1["q_dielectric"] == pytest.approx(1e4)
    qc, qd = q1["q_conductor"], q1["q_dielectric"]
    assert q1["q_unloaded"] == pytest.approx(qc * qd / (qc + qd), rel=1e-12)
    assert q1["q_unloaded"] < q1["q_conductor"]
    assert q1["q_unloaded"] <= min(qc, qd)
    # 逐点串联合成公式独立复核（1/(1/Qc+1/Qd)）
    assert q1["q_unloaded"] == pytest.approx(
        1.0 / (1.0 / qc + 1.0 / qd), rel=1e-12)


def test_unloaded_q_sqrt_sigma_and_sqrt_f_scaling():
    """Qc∝√σ（Al vs Cu）与 Qc∝√f（趋肤口径物理定标），≤1e-12 相对。"""
    cu = _run("cavity_unloaded_q",
              {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
               "a_mm": 1.0, "b_mm": 2.301})
    al = _run("cavity_unloaded_q",
              {"f_ghz": 1.0, "conductivity_s_per_m": 2.32e7,
               "a_mm": 1.0, "b_mm": 2.301})
    assert al["q_conductor"] / cu["q_conductor"] == pytest.approx(
        math.sqrt(2.32e7 / 5.8e7), rel=1e-12)
    cu2 = _run("cavity_unloaded_q",
               {"f_ghz": 2.0, "conductivity_s_per_m": 5.8e7,
                "a_mm": 1.0, "b_mm": 2.301})
    assert cu2["q_conductor"] / cu["q_conductor"] == pytest.approx(
        math.sqrt(2.0), rel=1e-12)


def test_unloaded_q_magnitude_window_and_xcheck():
    """量级窗（Cu@1GHz/50Ω 口径 ≈5.6e2）+ β/(2α) 独立路线自洽 + 窄缝极限。"""
    q = _run("cavity_unloaded_q",
             {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
              "a_mm": 1.0, "b_mm": 2.301})
    assert 100.0 <= q["q_conductor"] <= 2000.0
    assert q["q_xcheck_rel_dev"] <= 1e-12
    assert q["z0_ohm"] == pytest.approx(50.0, abs=0.1)
    # 几何极限：b→a⁺（缝隙消失）→ Qc→0；b 增大 → Qc 上升（单调方向）
    q_near = _run("cavity_unloaded_q",
                  {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                   "a_mm": 1.0, "b_mm": 1.001})
    assert q_near["q_conductor"] < q["q_conductor"]


def test_unloaded_q_domain_guards():
    """Q 键越界显式拒绝（f≤0/σ≤0/a≥b/负损耗角/μr≤0）。"""
    for bad in ({"f_ghz": 0.0, "conductivity_s_per_m": 5.8e7,
                 "a_mm": 1.0, "b_mm": 2.3},
                {"f_ghz": 1.0, "conductivity_s_per_m": 0.0,
                 "a_mm": 1.0, "b_mm": 2.3},
                {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                 "a_mm": 2.3, "b_mm": 2.3},
                {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                 "a_mm": 3.0, "b_mm": 2.3},
                {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                 "a_mm": 1.0, "b_mm": 2.3, "tan_delta": -1e-4},
                {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                 "a_mm": 1.0, "b_mm": 2.3, "mu_r": 0.0},
                {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                 "a_mm": 1.0, "b_mm": 2.3, "epsilon_r": 0.5}):
        _reject("cavity_unloaded_q", bad)


# ─── 注册面契约 ───────────────────────────────────────────────────────────────


def test_w5a_keys_registered_non_experimental():
    """六新键在册、非实验态、必需参数声明正确（#231 消费者钉之一）。"""
    expect = {
        "doa_music_spectrum": ("n_elements",),
        "doa_esprit": ("n_elements",),
        "doa_mvdr_weights": ("covariance",),
        "combline_resonance": ("zr_ohm", "cap_ff", "epsilon_r"),
        "coaxial_cavity_resonance": ("mode",),
        "cavity_unloaded_q": ("f_ghz", "conductivity_s_per_m", "a_mm",
                              "b_mm"),
    }
    for key, required in expect.items():
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.required == required, f"{key} required 面漂移"
        assert spec.experimental is False
