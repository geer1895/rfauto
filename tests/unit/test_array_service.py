"""DP-4 P2 阵列服务层单测（service/array_service.py，J1/J3 全合成判据）。

裁判=独立闭式（runs/df6_dp4af/criteria.md 预声明）：
- J1a 快速档全链逐位：uniform N=4 d=0.5λ 侧射 |F| vs uniform_af_closed_form
  ≤1e-12（经 array_pattern 的单元×AF 复域乘法与切面装配）；
- J1b 4 元切比雪夫 −30dB：服务切面实测峰副瓣 −30.0±0.05dB（均匀 u 网格
  ≥4001 点）；
- Dmax 锚：isotropic dmax_fast=10lg N 精确、dmax_elem=0；半波振子
  Dmax_elem≈2.15dBi（数值积分网格 1°，实测分辨率 0.003dB）；rect 2×2=6.02dBi；
  Dmax_fast vs Dmax_grid 数值积分交叉互证；
- J3d 两档路由/阶段边界：显式 coupled → NotImplementedPhase（不发射真机）；
  auto+强耦 → invalid_fast_tier 标记 + NotImplementedPhase 状态块；Z_scan
  退化（Γ→1）如实 None；EEP 收集接口 NotImplementedPhase；
- JSON 全链可序列化；csv 单元（既有 nf2ff run 消费口径）与 meta Dmax。
全部确定性、无网络、无真机。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.array_synthesis import (
    chebyshev_weights,
    uniform_af_closed_form,
)
from rfauto.core.farfield import write_farfield_cut_csv
from rfauto.service.array_service import (
    NotImplementedPhase,
    array_pattern,
    array_scan_sweep,
    collect_eep_manifest,
    coupled_tier_solve,
    synthesize_array_weights,
)


def _uniform_request(**over):
    req = {
        "layout": "ula", "n_elements": 4, "spacing_lambda": 0.5,
        "amplitude_law": "uniform", "element": "isotropic", "scan_deg": 90.0,
    }
    req.update(over)
    return req


def _dense_u_theta_grid(n_points: int = 4001) -> list[float]:
    """均匀 u 采样的 θ 网格（z 轴 u=cosθ；SLL 测量的采样无关性）。"""
    return sorted(float(v) for v in
                  np.degrees(np.arccos(np.linspace(-1.0, 1.0, n_points))))


# ─── J1a：快速档全链 AF 闭式逐位 ─────────────────────────────────────────────

def test_j1a_uniform_af_matches_closed_form_via_service():
    res = array_pattern(_uniform_request(
        theta_grid={"start": 0.0, "stop": 180.0, "step": 0.5}))
    assert res["ok"], res.get("error")
    r = res["result"]
    assert r["tier"] == "fast" and not r["invalid_fast_tier"]
    cut = r["cuts"][0]
    theta = np.asarray(cut["theta_deg"], dtype=float)
    f_abs = np.asarray(cut["f_abs"], dtype=float)
    u = np.cos(np.radians(theta))
    ref = uniform_af_closed_form(2.0 * np.pi * 0.5 * u, 4)
    assert float(np.max(np.abs(f_abs - ref))) <= 1e-12
    # 峰值=1（归一 AF）、单元=1 → 峰在侧射 θ=90°
    assert float(f_abs.max()) == pytest.approx(1.0, abs=1e-12)
    peak_theta = theta[int(np.argmax(f_abs))]
    assert peak_theta == pytest.approx(90.0, abs=0.5)


def test_j1b_chebyshev_sll_meets_target_via_service():
    res = array_pattern(_uniform_request(
        amplitude_law="chebyshev", sidelobe_level_db=-30.0,
        theta_grid={"values": _dense_u_theta_grid(4001)}))
    assert res["ok"], res.get("error")
    r = res["result"]
    assert r["sll_db"] == pytest.approx(-30.0, abs=0.05)
    # 权重与 array_synthesis 直出一致（服务透传不加工）
    assert np.allclose(np.asarray(r["weights"]),
                       chebyshev_weights(4, -30.0), atol=1e-15)


# ─── Dmax 锚与交叉互证 ───────────────────────────────────────────────────────

def test_dmax_anchors_and_cross_check():
    # isotropic：dmax_elem=0 精确、dmax_fast=10lg N 精确
    res = array_pattern(_uniform_request())["result"]
    assert res["dmax_elem_dbi"] == 0.0
    assert res["dmax_fast_dbi"] == pytest.approx(10.0 * np.log10(4.0))
    assert res["dmax_grid_dbi"] == pytest.approx(res["dmax_fast_dbi"], abs=0.1)
    assert "近似" in res["dmax_fast_assumption"]
    assert "dmax_grid_dbi" in res["dmax_fast_assumption"]
    # 半波振子：D0≈2.15 dBi（文献 2.1534，数值积分 1° 网格实测偏差 0.0025dB）
    dip = array_pattern(_uniform_request(
        element="half_wave_dipole", dmax_grid_step_deg=1.0))["result"]
    assert dip["dmax_elem_dbi"] == pytest.approx(2.15, abs=0.05)
    # rect 2×2 isotropic 侧射：dmax_fast=10lg4（公式档）；dmax_grid 对照
    # 独立闭式——互相干积分 ∫|AF|²dΩ = 4π[N + Σ_{m≠n}sinc(k·d_mn)]：
    # 边缘对 k·d=π→0，对角对 k·d=π√2→sinc(√2)（未归一），
    # D = 16/(4+4·sinc(π√2)) = 5.109 = 7.084 dBi（2° 网格实测 7.08498）
    rect = array_pattern({
        "layout": "rect", "n_x": 2, "n_y": 2, "element": "isotropic",
        "scan_deg": 0.0, "dmax_grid_step_deg": 2.0,
    })["result"]
    assert rect["dmax_fast_dbi"] == pytest.approx(10.0 * np.log10(4.0))
    diag_term = float(np.sinc(np.sqrt(2.0)))  # np.sinc 归一化=sin(πx)/(πx)
    d_ref = 16.0 / (4.0 + 4.0 * diag_term)
    assert rect["dmax_grid_dbi"] == pytest.approx(10.0 * np.log10(d_ref), abs=0.01)
    # 锥削换算：|Σw|²/Σ|w|² 与 taper_gain_db 自洽（chebyshev<均匀）
    cheb = array_pattern(_uniform_request(
        amplitude_law="chebyshev", sidelobe_level_db=-30.0))["result"]
    assert cheb["taper_gain_db"] < res["taper_gain_db"]


def test_result_is_json_serializable_end_to_end():
    s = [[0.2, 0.02, 0.15, 0.03], [0.02, 0.2, 0.02, 0.15],
         [0.15, 0.02, 0.2, 0.02], [0.03, 0.15, 0.02, 0.2]]
    res = array_pattern(_uniform_request(
        s_matrix=s, slab={"eps_r": 2.2, "thickness_m": 1.575e-3},
        freq_hz=10e9))
    assert res["ok"]
    payload = json.dumps(res["result"], ensure_ascii=False)  # numpy 泄漏即炸
    r = json.loads(payload)
    assert len(r["gamma_act"]) == 4 and len(r["z_scan"]) == 4
    assert r["cuts"][0]["f"][0] == r["cuts"][0]["f"][0]


# ─── Γ_act / Z_scan（服务链）─────────────────────────────────────────────────

def test_gamma_and_zscan_with_degenerate_reflection():
    # 仅行 0 和=1（均匀激励 a≡1 下 Γ_0=1）；其余行和≠1；
    # 对角外最大 0.1（−20dB，弱耦不触门）
    s = [[0.7, 0.1, 0.1, 0.1], [0.1, 0.6, 0.0, 0.0],
         [0.1, 0.0, 0.5, 0.0], [0.1, 0.0, 0.0, 0.4]]
    res = array_pattern(_uniform_request(s_matrix=s))["result"]
    gamma = np.asarray([complex(*g) for g in res["gamma_act"]])
    assert abs(gamma[0] - 1.0) <= 1e-12  # 定义式：Σ_m S_0m·a_m/a_0，a≡1
    assert abs(gamma[1] - 0.7) <= 1e-12
    assert res["z_scan"][0] is None                      # Γ→1 如实 None
    assert res["z_scan_degenerate_indices"] == [0]
    assert res["z_scan"][1] is not None                  # 其余口正常
    assert res["gates"]["checks"]["coupling_db"]["pass"] is True


def test_s_matrix_as_complex_pair_format():
    s = [[["0.2", "0.0"], [0.0, 0.0]], [[0.0, 0.0], {"re": 0.2, "im": 0.0}]]
    res = array_pattern(_uniform_request(n_elements=2, s_matrix=s))["result"]
    gamma = np.asarray([complex(*g) for g in res["gamma_act"]])
    assert np.allclose(gamma, [0.2 + 0.0j, 0.2 + 0.0j], atol=1e-15)


# ─── J3d：两档路由与阶段边界 ────────────────────────────────────────────────

def test_j3d_explicit_coupled_tier_raises_not_implemented():
    """P2 阶段边界 → P3 更新（DP-4 P3 实现替换占位，2026-09-24）：
    array_pattern 显式 tier="coupled" 且**无注入**仍抛 NotImplementedPhase
    （注入式钩子语义保持——不显式给 coupled_solver 就不进互耦档）；
    collect_eep_manifest/coupled_tier_solve 已实现，非法调用走各自错误契约。"""
    with pytest.raises(NotImplementedPhase, match="P3"):
        array_pattern(_uniform_request(tier="coupled"))
    with pytest.raises(ValueError, match="run_dirs 长度须为 1"):
        collect_eep_manifest(["run_a", "run_b"], n_ports=4)
    res = coupled_tier_solve({})
    assert res["ok"] is False
    assert "template" in res["error"]


def test_j3d_gate_forced_upgrade_marks_invalid_fast_tier():
    strong = [[0.9, 0.5, 0.0, 0.0], [0.5, 0.9, 0.0, 0.0],
              [0.0, 0.0, 0.9, 0.0], [0.0, 0.0, 0.0, 0.9]]  # 近邻 −6dB
    res = array_pattern(_uniform_request(s_matrix=strong))["result"]
    assert res["tier"] == "coupled"
    assert res["invalid_fast_tier"] is True
    assert res["coupled_tier"]["status"] == "NotImplementedPhase"
    assert any("strong_coupling" in r for r in res["gates"]["reasons"])
    assert res["cuts"]            # 快档数字仍给出（带失效标记，供诊断）


def test_j3d_fast_tier_request_keeps_invalid_mark():
    res = array_pattern(_uniform_request(scan_deg=140.0, tier="fast"))["result"]
    assert res["tier"] == "fast"                    # 显式 fast（不路由）
    assert res["invalid_fast_tier"] is True         # 但门判超界（45°界）
    assert res["coupled_tier"]["status"] == "NotImplementedPhase"


# ─── 扫描扫掠 ────────────────────────────────────────────────────────────────

def test_scan_sweep_blind_spot_and_gate():
    res = array_scan_sweep({
        "layout": "rect", "n_x": 2, "n_y": 2, "element": "isotropic",
        "freq_hz": 10e9, "slab": {"eps_r": 2.2, "thickness_m": 1.575e-3},
        "scan_grid": {"start": 0.0, "stop": 80.0, "step": 1.0},
    })
    assert res["ok"], res.get("error")
    r = res["result"]
    # dx=dy=0.5λ → (m=−1,0) 阶在 θ≈74–80° 进入 0.02k0 匹配带（解析可预言）
    assert r["n_angles"] == 81
    assert r["n_blind"] == 6
    blind_rows = [row for row in r["rows"] if row["blind"] is True]
    assert all(row["nearest_order"] == [-1, 0] for row in blind_rows)
    assert all(74.0 <= row["scan_deg"] <= 80.0 for row in blind_rows)
    # θ>45° 全段判 coupled（平面阵扫描门）
    assert all(row["invalid_fast_tier"] for row in r["rows"]
               if row["scan_deg"] > 45.0)
    # x/y 轴阵：ula 盲点口径经服务层同样可走（dy 无周期处理）
    sweep_ula = array_scan_sweep({
        "layout": "ula", "axis": "x", "n_elements": 4,
        "freq_hz": 10e9, "slab": {"eps_r": 2.2, "thickness_m": 1.575e-3},
        "scan_grid": {"start": 30.0, "stop": 33.0, "step": 1.0},
    })
    assert sweep_ula["ok"]


def test_scan_sweep_cli_overrides_merge():
    res = array_scan_sweep({
        "n_elements": 4, "element": "isotropic",
        "scan_grid": {"start": 0.0, "stop": 180.0, "step": 90.0},
    })
    assert [row["scan_deg"] for row in res["result"]["rows"]] == [0.0, 90.0, 180.0]


# ─── csv 单元（既有 nf2ff run 消费口径）与 meta Dmax ─────────────────────────

def _write_dipole_cut_csv(path: Path) -> None:
    from rfauto.core.array_synthesis import half_wave_dipole_field
    theta = np.arange(0.0, 181.0, 1.0)
    e = np.asarray(half_wave_dipole_field(theta), dtype=float)
    rows = [{
        "phi_deg": 0.0, "theta_deg": float(t), "re_e_theta": float(v),
        "im_e_theta": 0.0, "re_e_phi": 0.0, "im_e_phi": 0.0,
        "e_norm": float(abs(v)), "p_rad": float(v * v),
    } for t, v in zip(theta, e, strict=True)]
    write_farfield_cut_csv(path, rows)


def test_csv_element_pattern_matches_closed_form(tmp_path):
    csv_path = tmp_path / "farfield_cut.csv"
    _write_dipole_cut_csv(csv_path)
    (tmp_path / "farfield_meta.json").write_text(
        json.dumps({"dmax_dbi": 2.15, "prad_w": 1.0, "p_acc_w": 1.0}),
        encoding="utf-8")
    # 与 csv 节点重合的 1° 网格 → 插值恰落节点，逐位一致钉有效
    grid = {"start": 0.0, "stop": 180.0, "step": 1.0}
    ref = array_pattern(_uniform_request(
        element="half_wave_dipole", theta_grid=grid))["result"]
    got = array_pattern(_uniform_request(
        element_pattern_csv=str(csv_path), theta_grid=grid))["result"]
    assert got["element"]["source"] == "csv"
    f_ref = np.asarray(ref["cuts"][0]["f_abs"])
    f_got = np.asarray(got["cuts"][0]["f_abs"])
    assert float(np.max(np.abs(f_got - f_ref))) <= 1e-12
    # 离节点重取样（稠密 u 网格）落在线性插值带内（1° 节距曲率误差 ~1e-4 量级，
    # 逐位钉只对节点网格声明——如实区分两类口径）
    dense = {"values": _dense_u_theta_grid(361)}
    got_dense = array_pattern(_uniform_request(
        element_pattern_csv=str(csv_path), theta_grid=dense))["result"]
    ref_dense = array_pattern(_uniform_request(
        element="half_wave_dipole", theta_grid=dense))["result"]
    band = float(np.max(np.abs(
        np.asarray(got_dense["cuts"][0]["f_abs"])
        - np.asarray(ref_dense["cuts"][0]["f_abs"]))))
    assert 0.0 < band <= 1e-3
    # Dmax_elem 来自 meta（PEC 镜像幂等修正后）
    assert got["dmax_elem_dbi"] == pytest.approx(2.15)
    assert got["dmax_fast_dbi"] == pytest.approx(2.15 + got["taper_gain_db"])


def test_csv_element_missing_meta_reports_honestly(tmp_path):
    csv_path = tmp_path / "farfield_cut.csv"
    _write_dipole_cut_csv(csv_path)
    res = array_pattern(_uniform_request(
        element_pattern_csv=str(csv_path)))["result"]
    assert res["dmax_elem_dbi"] is None
    assert res["dmax_fast_dbi"] is None
    assert "farfield_meta.json" in res["dmax_elem_note"]
    assert res["cuts"]      # 切面照常产出（切面不依赖 Dmax）


# ─── synthesize_array_weights ───────────────────────────────────────────────

def test_synthesize_weights_service():
    res = synthesize_array_weights({
        "n_elements": 4, "amplitude_law": "chebyshev",
        "sidelobe_level_db": -30.0, "spacing_lambda": 0.5})
    assert res["ok"]
    w = np.asarray(res["result"]["weights"])
    assert w.max() == 1.0 and np.allclose(w, w[::-1])   # max=1、对称
    assert res["result"]["gates"]["tier"] == "fast"
    bad = synthesize_array_weights({"amplitude_law": "chebyshev"})
    assert not bad["ok"] and "sidelobe_level_db" in bad["error"]
