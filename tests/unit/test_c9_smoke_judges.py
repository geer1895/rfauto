"""C9 冒烟判读器（scripts/smoke_cps_anchor.py / smoke_suspended_stripline_anchor.py）
纯函数单测：预声明门、合成理想线正/反例、pt1 归档回放（若 runs/ 产物在树则复算）。

确定性、无真机：合成 S 参数按理想无耗线 S21=e^{−jβL}、S11=Γ(ZL,50) 构造，
锚=core/quasistatic_fd.py 裁判现算（与判读器同源）。pt1 归档数字（2026-09-17
收尾批）作为审计结论的回归锚：端口 β 2.0172 ≡ S21 斜率 2.0193（0.1%）。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import smoke_cps_anchor as jc
import smoke_suspended_stripline_anchor as js

C0 = 299792458.0
F = np.linspace(2.25e9, 2.75e9, 401)


def _read_rows(path: Path) -> list[list[str]]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.reader(fh))[1:]


def _line(eps_eff: float, zl: float, length_m: float, z_ref: float = 50.0):
    """理想无耗线：S21=e^{−jβL}（幅 0.999）、S11=Γ(ZL,z_ref) 实常数。"""
    beta = np.sqrt(eps_eff) * 2 * np.pi * F / C0
    s21 = 0.999 * np.exp(-1j * beta * length_m)
    s11 = np.full(F.shape, (zl - z_ref) / (zl + z_ref), dtype=complex)
    return s11, s21, beta


@pytest.fixture(scope="module")
def ssl_anchor():
    return js.fd_anchor(0.731, 1.016, 0.508, 3.66)


@pytest.fixture(scope="module")
def cps_anchor():
    return jc.fd_anchor(2.95, 0.5, 0.508, 3.66)


# ─── 预声明门（写死，#122）─────────────────────────────────────────────────

def test_gates_predeclared():
    assert js.GATES == {"beta_consistency_pct": 2.5, "s11_max_db": -10.0,
                        "eps_pass_pct": 3.0, "eps_partial_pct": 5.0,
                        "zl_pass_pct": 5.0}
    assert jc.GATES == {"s11_max_db": -15.0, "eps_pass_pct": 3.0,
                        "eps_partial_pct": 7.0, "closed_vs_fd_info_pct": 1.2}
    assert js.nominal_plane_dist_m() == pytest.approx(4 * 60e-3 / 3 + 40e-3 / 3)


# ─── 悬置带线判读 ─────────────────────────────────────────────────────────────

def test_ssl_anchor_is_fd_referee(ssl_anchor):
    assert ssl_anchor["eps_eff"] == pytest.approx(2.092, abs=0.01)
    assert ssl_anchor["z0_ohm"] == pytest.approx(56.1, abs=0.5)
    assert abs(ssl_anchor["z0_air_vs_cohn_pct"]) < 0.5


def test_ssl_ideal_line_at_fd_truth_passes(ssl_anchor):
    eps, zl = ssl_anchor["eps_eff"], ssl_anchor["z0_ohm"]
    d = js.nominal_plane_dist_m()
    s11, s21, beta = _line(eps, zl, d)
    v = js.judge_suspended_stripline(F, s11, s21, beta, d, ssl_anchor)
    assert v["verdict"] == "PASS", v
    assert v["numbers"]["eps_beta"] == pytest.approx(eps, abs=1e-4)
    assert v["numbers"]["eps_s21_slope"] == pytest.approx(eps, abs=5e-4)
    assert v["numbers"]["zl_ohm"] == pytest.approx(zl, abs=0.01)
    assert v["numbers"]["zl_source"] == "s11_inversion"
    # ZL 优先读 port_beta 列
    v2 = js.judge_suspended_stripline(F, s11, s21, beta, d, ssl_anchor,
                                      zl_ohm=np.full(F.shape, zl))
    assert v2["numbers"]["zl_source"] == "port_beta_csv" and v2["verdict"] == "PASS"


def test_ssl_verdict_ladder(ssl_anchor):
    eps, zl = ssl_anchor["eps_eff"], ssl_anchor["z0_ohm"]
    d = js.nominal_plane_dist_m()
    # 粗网格 pt1 形态：β −3.6%（PARTIAL 档）+ ZL −10.6%（G3 FAIL）→ PARTIAL
    s11, s21, beta = _line(eps * 0.964, 50.2, d)
    v = js.judge_suspended_stripline(F, s11, s21, beta, d, ssl_anchor)
    assert v["verdict"] == "PARTIAL"
    assert not v["gates"]["G3_zl_vs_fd"]["pass"]
    # β −8% → FAIL
    s11, s21, beta = _line(eps * 0.92, zl, d)
    assert js.judge_suspended_stripline(F, s11, s21, beta, d, ssl_anchor)["verdict"] == "FAIL"
    # 端口 β 与 S21 斜率不自洽（β 高 6%）→ 门失语 UNDECIDABLE
    s11, s21, beta = _line(eps, zl, d)
    v = js.judge_suspended_stripline(F, s11, s21, beta * 1.03, d, ssl_anchor)
    assert v["verdict"] == "UNDECIDABLE" and not v["gates"]["G0_beta_consistency"]["pass"]
    # |S11| −8dB → FAIL（G1）
    s11, s21, beta = _line(eps, 25.0, d)
    assert js.judge_suspended_stripline(F, s11, s21, beta, d, ssl_anchor)["verdict"] == "FAIL"


def test_zl_from_s11_inversion_roundtrip():
    for zl in (40.0, 50.2, 56.1, 80.0):
        g = (zl - 50) / (zl + 50)
        assert js.zl_from_s11(complex(g, 0.0)) == pytest.approx(zl, rel=1e-12)


ARCHIVE = REPO / "runs" / "suspended_stripline_smoke" / "pt1"


@pytest.mark.skipif(not (ARCHIVE / "sparams.csv").exists(),
                    reason="pt1 归档不在树（runs/ 不入库）")
def test_ssl_pt1_archive_replay_documents_audit(ssl_anchor):
    """pt1（粗网格 BASE 1.14/z 8 格）回放：端口 β 与 S21 斜率自洽 ≤0.2%（β 口径
    合法）、G2 −3.6% PARTIAL、G3 ZL ≈50 vs 56.1 −11% FAIL → PARTIAL。"""
    rows = _read_rows(ARCHIVE / "sparams.csv")
    f = np.array([float(r[0]) for r in rows])
    s11 = np.array([float(r[1]) + 1j * float(r[2]) for r in rows])
    s21 = np.array([float(r[3]) + 1j * float(r[4]) for r in rows])
    beta, zl, plane = js._read_port_beta(ARCHIVE)
    assert zl is None and plane == pytest.approx(js.nominal_plane_dist_m())
    v = js.judge_suspended_stripline(f, s11, s21, beta, plane, ssl_anchor)
    n = v["numbers"]
    assert n["eps_beta"] == pytest.approx(2.0172, abs=2e-3)
    assert n["eps_s21_slope"] == pytest.approx(2.0193, abs=2e-3)
    assert v["gates"]["G0_beta_consistency"]["value_pct"] < 0.2
    assert n["zl_ohm"] == pytest.approx(50.0, abs=0.4)      # |Γ|≈2e-3 → ±0.2Ω
    assert n["s11_max_db"] == pytest.approx(-56.4, abs=0.3)   # 带内（全频 −52.9）
    assert v["gates"]["G2_eps_vs_fd"]["partial"] and not v["gates"]["G2_eps_vs_fd"]["pass"]
    assert not v["gates"]["G3_zl_vs_fd"]["pass"]
    assert v["verdict"] == "PARTIAL"


# ─── CPS 判读 ────────────────────────────────────────────────────────────────

def test_cps_anchor_closed_form_calibrated_within_info(cps_anchor):
    assert cps_anchor["eps_eff"] == pytest.approx(1.667, abs=0.006)
    assert abs(cps_anchor["closed_vs_fd_pct"]) <= jc.GATES["closed_vs_fd_info_pct"]
    assert cps_anchor["z0_closed_ohm"] == pytest.approx(116.17, abs=0.05)


def test_cps_ideal_line_ladder(cps_anchor):
    eps = cps_anchor["eps_eff"]
    L = 40e-3
    s11, s21, _ = _line(eps, 116.17, L, z_ref=116.17)
    v = jc.judge_cps(F, s11, s21, L, cps_anchor, base_cell_m=1.14e-3)
    assert v["verdict"] == "PASS"
    assert v["numbers"]["eps_engine_s21_slope"] == pytest.approx(eps, rel=1e-4)
    lo, hi = v["numbers"]["eps_engine_len_pm_1cell"]
    assert lo < eps < hi and hi / lo - 1 == pytest.approx(0.117, abs=0.01)  # ±5.7%
    # 端口元落格 +1 格（相位按 L+1.14mm 走，判读按 L）→ +5.8% → PARTIAL 档
    s11, s21, _ = _line(eps, 116.17, L + 1.14e-3, z_ref=116.17)
    assert jc.judge_cps(F, s11, s21, L, cps_anchor)["verdict"] == "PARTIAL"
    # pt1 形态 +13.4% → FAIL
    s11, s21, _ = _line(eps * 1.134, 116.17, L, z_ref=116.17)
    assert jc.judge_cps(F, s11, s21, L, cps_anchor)["verdict"] == "FAIL"
    # 失配 −12dB → FAIL（G1）
    s11, s21, _ = _line(eps, 116.17 * 1.67, L, z_ref=116.17)
    v = jc.judge_cps(F, s11, s21, L, cps_anchor)
    assert not v["gates"]["G1_s11_max_db"]["pass"] and v["verdict"] == "FAIL"


def test_cps_line_len_source_port_beta_csv(cps_anchor):
    """判读器用模板落盘的实测差分线长替代标称 L
    （line_len_source=port_beta_csv → numbers 记录来源；端口元落格 +1 格时
    实测线长吸收该偏移，不再落 PARTIAL 档——标称口径下同数据 = PARTIAL）。"""
    eps = cps_anchor["eps_eff"]
    L = 40e-3
    s11, s21, _ = _line(eps, cps_anchor["z0_closed_ohm"], L + 1.14e-3,
                        z_ref=cps_anchor["z0_closed_ohm"])
    # 标称线长口径：相位多走 1 格 → εeff 高 5.9% → PARTIAL（口径地板实证）
    v_nom = jc.judge_cps(F, s11, s21, L, cps_anchor)
    assert v_nom["numbers"]["line_len_source"] == "nominal"
    assert v_nom["verdict"] == "PARTIAL"
    # 实测线长口径（落盘 plane_dist_m = L+1.14mm）：同数据 → PASS
    v_meas = jc.judge_cps(F, s11, s21, L + 1.14e-3, cps_anchor,
                          line_len_source="port_beta_csv")
    assert v_meas["numbers"]["line_len_source"] == "port_beta_csv"
    assert v_meas["verdict"] == "PASS"
    assert v_meas["numbers"]["eps_engine_s21_slope"] == pytest.approx(eps, rel=1e-4)


CPS_ARCHIVE = REPO / "runs" / "cps_smoke" / "pt1"


@pytest.mark.skipif(not (CPS_ARCHIVE / "sparams.csv").exists(),
                    reason="pt1 归档不在树（runs/ 不入库）")
def test_cps_pt1_archive_replay(cps_anchor):
    rows = _read_rows(CPS_ARCHIVE / "sparams.csv")
    f = np.array([float(r[0]) for r in rows])
    s11 = np.array([float(r[1]) + 1j * float(r[2]) for r in rows])
    s21 = np.array([float(r[3]) + 1j * float(r[4]) for r in rows])
    v = jc.judge_cps(f, s11, s21, 40e-3, cps_anchor, base_cell_m=1.1404546e-3)
    assert v["numbers"]["eps_engine_s21_slope"] == pytest.approx(1.8909, abs=2e-3)
    assert v["gates"]["G1_s11_max_db"]["pass"]
    assert v["verdict"] == "FAIL"
