"""C4 装配归一化链 + 离线判读单测（零 openEMS/零网络）。

钉住：
1. `engine_msl_line_z0`：合成均匀无耗 TL 三面探针（openEMS 探针文件格式）→ 复算 ZL 回收
   设定 Z0（行波与 Γ=0.5 驻波两态，负载无关性）；缺探针 → None；
2. `normalize_assembled_smatrix`：教科书带载前向构造（线基真 S、非激励端 PML 匹配）→
   CalcPort(ref=50) 伪波比值 → 链回收 = skrf renormalize_s(真 S, Z→50)（1e-10）、σmax 回到 1；
   数值/逐端口/"engine"（合成探针根目录）三种 line_z0 入口 + 缺探针端口恒等注记；
3. `solve_smatrix_openems(line_z0="engine")` 端到端（桩子进程写带载 CSV+合成探针）：
   归一后 .s4p、`<template>_raw.s4p` 留档、assembly_norm 契约、缓存携带 assembly_norm，
   line_z0=None 行为逐字节不变；
4. `judge_network`：fake 同源理想裁判网络 lange/cline → PASS；持续过耦合 → fc_at_band_edge；
   `center_plateau`；`resolve_root` 共享 root 守卫；
5. `judge_c4_assembly.rejudge_template`/`main` 离线复判端到端（tmp 根目录）。
"""
from __future__ import annotations

import json
import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from skrf.network import renormalize_s

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import judge_c4_assembly as jca
import smoke_c4_coupler_family as smoke
from rfauto.adapters import openems_rotation as rot

C0 = 299792458.0
Z_LINE = 45.0
F_BAND = np.linspace(2.3e9, 2.7e9, 41)
# 理想 3dB 90° 混合结（幺正、对称）——线基真 S
_H = -1 / math.sqrt(2) * np.array([[0, 1j, 1, 0], [1j, 0, 0, 1],
                                   [1, 0, 0, 1j], [0, 1, 1j, 0]], dtype=complex)


def _write_probe(path: Path, t: np.ndarray, v: np.ndarray, xyz: tuple[float, float, float],
                 kind: str) -> None:
    head = [f"% time-domain {kind} integration by openEMS synthetic",
            f"% start-coordinates: ({xyz[0]},{xyz[1]},{xyz[2]}) m -> [1,2,3]",
            f"% stop-coordinates: ({xyz[0]},{xyz[1]},{xyz[2]}) m -> [1,2,3]",
            f"% t/s\t{kind}"]
    body = [f"{ti:.6e}\t{vi:.9e}" for ti, vi in zip(t, v, strict=True)]
    path.write_text("\n".join(head + body) + "\n", encoding="utf-8")


def _write_tl_probes(fdtd: Path, port: int, z0: float, *, gamma_load: complex = 0.0,
                     eps_eff: float = 2.85, d_m: float = 1e-3, amp: float = 1.0) -> None:
    """合成均匀无耗 TL（前向波 + 在 y=0 以 Γ 反射的回波）三面 U/两面 I 探针文件。"""
    fdtd.mkdir(parents=True, exist_ok=True)
    v = C0 / math.sqrt(eps_eff)
    t = np.arange(0.0, 6e-9, 5e-12)
    y_u = np.array([-0.0446, -0.0446 + d_m, -0.0446 + 2 * d_m])
    y_i = y_u[:2] + d_m / 2
    f0, tau, t0 = 2.5e9, 0.5e-9, 2.5e-9

    def g(tt: np.ndarray) -> np.ndarray:
        return amp * np.exp(-((tt - t0) / tau) ** 2) * np.cos(2 * np.pi * f0 * (tt - t0))

    for s, y in zip("ABC", y_u, strict=True):
        vv = g(t - y / v) + gamma_load * g(t + y / v)
        _write_probe(fdtd / f"port_ut_{port}{s}", t, np.real(vv), (0.0, y, 5.08e-4), "voltage")
    for s, y in zip("AB", y_i, strict=True):
        ii = (g(t - y / v) - gamma_load * g(t + y / v)) / z0
        _write_probe(fdtd / f"port_it_{port}{s}", t, np.real(ii), (0.0, y, 5.08e-4), "current")


def _loaded_ratios(s_true: np.ndarray, z_line: float, z_ref: float = 50.0) -> np.ndarray:
    """教科书带载前向构造：线基真 S（激励 j 的 a^Z=e_j、非激励端 PML 匹配 a^Z=0）
    → 物理 V/I → CalcPort(ref=z_ref) 伪波比值 r_ij=b_i^ref/a_j^ref（与 helper 互为独立机制）。"""
    _n, p, _ = s_true.shape
    r = np.empty_like(s_true)
    for j in range(p):
        a = np.zeros(p)
        a[j] = 1.0
        b = s_true[:, :, j]
        vv = math.sqrt(z_line) * (a + b)
        ii = (a - b) / math.sqrt(z_line)
        a_ref = (vv + z_ref * ii) / (2 * math.sqrt(z_ref))
        b_ref = (vv - z_ref * ii) / (2 * math.sqrt(z_ref))
        r[:, :, j] = b_ref / a_ref[:, j][:, None]
    return r


def _sigma_max(s: np.ndarray) -> float:
    return float(np.max(np.linalg.svd(s, compute_uv=False)))


# ---------------------------------------------------------------------------
# 1. 引擎 ZL 复算
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gamma", [0.0, 0.5, -0.3 + 0.2j])
def test_engine_msl_line_z0_recovers_z0_load_independent(tmp_path, gamma):
    _write_tl_probes(tmp_path, 1, Z_LINE, gamma_load=gamma)
    zl = rot.engine_msl_line_z0(tmp_path, 1, F_BAND)
    assert zl is not None and zl.shape == F_BAND.shape
    assert np.allclose(np.real(zl), Z_LINE, rtol=5e-3)
    assert np.max(np.abs(np.imag(zl))) < 0.5


def test_engine_msl_line_z0_missing_probe_returns_none(tmp_path):
    _write_tl_probes(tmp_path, 2, Z_LINE)
    (tmp_path / "port_it_2B").unlink()
    assert rot.engine_msl_line_z0(tmp_path, 2, F_BAND) is None
    assert rot.engine_msl_line_z0(tmp_path, 3, F_BAND) is None


def test_line_z0_from_rounds_median_and_missing_port(tmp_path):
    for k in range(1, 5):
        for p in range(1, 4):   # port4 全轮缺探针
            _write_tl_probes(tmp_path / f"p{k}" / "fdtd", p, Z_LINE + 0.1 * k)
    zl, info = rot.line_z0_from_rounds(tmp_path, 4, F_BAND)
    assert info["rounds_used"] == {"1": [1, 2, 3, 4], "2": [1, 2, 3, 4],
                                   "3": [1, 2, 3, 4], "4": []}
    # 跨轮中位：45.1/45.2/45.3/45.4 → 中位 45.25
    assert np.allclose(np.real(zl[:, :3]), Z_LINE + 0.25, rtol=5e-3)
    assert np.all(np.isnan(zl[:, 3]))


# ---------------------------------------------------------------------------
# 2. 装配归一化链
# ---------------------------------------------------------------------------

def _true_s(n: int) -> np.ndarray:
    return np.broadcast_to(_H, (n, 4, 4)).copy()


def test_normalize_recovers_true_s_from_loaded_ratios():
    f_ghz = F_BAND / 1e9
    s_true = _true_s(len(f_ghz))
    r = _loaded_ratios(s_true, Z_LINE)
    assert _sigma_max(r) > 1.02          # 带载比值非无源外观（refix 症状同族）
    s_norm, info = rot.normalize_assembled_smatrix(r, f_ghz, Z_LINE, n_ports=4)
    zl = np.full((len(f_ghz), 4), Z_LINE)
    expect = renormalize_s(s_true, zl, np.full_like(zl, 50.0), s_def="traveling")
    assert np.allclose(s_norm, expect, atol=1e-10)
    assert info["sigma_max_norm"] == pytest.approx(1.0, abs=1e-9)
    assert info["sigma_max_raw"] == pytest.approx(_sigma_max(r))
    assert info["line_z0_ohm"] == [Z_LINE] * 4
    assert info["line_z0_dev_pct"] == pytest.approx([-10.0] * 4)
    assert info["mode"] == "45.0" and info["notes"] == []
    # z_line=50 恒等
    s_id, _ = rot.normalize_assembled_smatrix(r, f_ghz, 50.0, n_ports=4)
    assert np.allclose(s_id, r, atol=1e-12)
    # 标量扫描（独立交叉验证）在真 Z 处取 σmax 最小=1
    sc = jca.scalar_scan(r)
    assert sc["z_best_ohm"] == Z_LINE and sc["sigma_max_best"] == pytest.approx(1.0, abs=1e-9)


def test_normalize_engine_mode_from_synthetic_probes(tmp_path):
    f_ghz = F_BAND / 1e9
    s_true = _true_s(len(f_ghz))
    r = _loaded_ratios(s_true, Z_LINE)
    for k in range(1, 5):
        for p in range(1, 5):
            _write_tl_probes(tmp_path / f"p{k}" / "fdtd", p, Z_LINE, gamma_load=0.2 * (p - 1))
    s_norm, info = rot.normalize_assembled_smatrix(r, f_ghz, "engine", n_ports=4,
                                                   root=tmp_path)
    zl = np.full((len(f_ghz), 4), Z_LINE)
    expect = renormalize_s(s_true, zl, np.full_like(zl, 50.0), s_def="traveling")
    assert np.allclose(s_norm, expect, atol=2e-2)
    assert info["sigma_max_norm"] <= 1.005
    assert np.allclose(info["line_z0_ohm"], Z_LINE, rtol=5e-3)
    assert info["rounds_used"]["1"] == [1, 2, 3, 4]


def test_normalize_engine_mode_missing_port_falls_back_to_z_ref(tmp_path):
    f_ghz = F_BAND / 1e9
    r = _loaded_ratios(_true_s(len(f_ghz)), Z_LINE)
    for k in range(1, 5):
        for p in range(1, 4):
            _write_tl_probes(tmp_path / f"p{k}" / "fdtd", p, Z_LINE)
    _, info = rot.normalize_assembled_smatrix(r, f_ghz, "engine", n_ports=4, root=tmp_path)
    assert info["line_z0_ohm"][3] == 50.0
    assert any("port4" in n for n in info["notes"])


def test_normalize_rejects_bad_mode():
    r = _loaded_ratios(_true_s(3), Z_LINE)
    with pytest.raises(ValueError):
        rot.normalize_assembled_smatrix(r, F_BAND[:3] / 1e9, "hj", n_ports=4)
    with pytest.raises(ValueError):
        rot.normalize_assembled_smatrix(r, F_BAND[:3] / 1e9, "engine", n_ports=4)


# ---------------------------------------------------------------------------
# 3. solve_smatrix_openems(line_z0="engine") 端到端（桩子进程）
# ---------------------------------------------------------------------------

E2E_F_HZ = (2.4e9, 2.5e9, 2.6e9)


@pytest.fixture()
def fake_render(monkeypatch):
    def _render(template, params, freq_range_ghz, mesh_resolution_mm=0.0, excite_port=1):
        return f"SCRIPT-{template}-{excite_port}"

    monkeypatch.setattr("rfauto.adapters.openems_templates.render_script", _render)


def _make_fake_run(calls: list[int], z_line: float = Z_LINE):
    r = _loaded_ratios(_true_s(len(E2E_F_HZ)), z_line)

    def fake_run(cmd, capture_output, text, timeout, cwd):
        work_k = Path(cwd)
        k = int(work_k.name[1:])
        calls.append(k)
        header = "freq_hz" + "".join(f",re_S{c + 1}1,im_S{c + 1}1" for c in range(4))
        rows = [header]
        for m, f in enumerate(E2E_F_HZ):
            vals = [repr(f)]
            for c in range(4):
                vals += [repr(float(r[m, c, k - 1].real)), repr(float(r[m, c, k - 1].imag))]
            rows.append(",".join(vals))
        (work_k / "sparams.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        for p in range(1, 5):
            _write_tl_probes(work_k / "fdtd", p, z_line, gamma_load=0.1 * (k - 1))
        return types.SimpleNamespace(returncode=0, stderr="")

    return fake_run


def test_solve_smatrix_line_z0_engine_end_to_end(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    monkeypatch.setattr("rfauto.adapters.openems_rotation.subprocess.run",
                        _make_fake_run(calls))
    res = rot.solve_smatrix_openems(tmp_path, template="lange", params={},
                                    freq_range_ghz=(2.4, 2.6), n_ports=4,
                                    line_z0="engine")
    assert res["ok"] and calls == [1, 2, 3, 4]
    an = res["assembly_norm"]
    assert an["mode"] == "engine" and an["sigma_max_raw"] > 1.02
    assert an["sigma_max_norm"] <= 1.005
    assert np.allclose(an["line_z0_ohm"], Z_LINE, rtol=5e-3)
    assert np.allclose(an["line_z0_dev_pct"], -10.0, atol=0.6)
    zl = np.full((3, 4), Z_LINE)
    expect = renormalize_s(_true_s(3), zl, np.full_like(zl, 50.0), s_def="traveling")
    assert np.allclose(res["s_params"], expect, atol=2e-2)
    assert np.allclose(res["s_params_raw"], _loaded_ratios(_true_s(3), Z_LINE), atol=1e-12)
    assert Path(an["raw_s4p_path"]).name == "lange_raw.s4p"
    assert Path(an["raw_s4p_path"]).exists() and Path(res["s4p_path"]).exists()
    assert "装配归一 line_z0=engine" in res["message"]
    # 缓存复用携带 assembly_norm；raw 口径（line_z0=None）另键、行为不变
    cached = rot.solve_smatrix_openems(tmp_path, template="lange", params={},
                                       freq_range_ghz=(2.4, 2.6), n_ports=4,
                                       line_z0="engine")
    assert "缓存复用" in cached["message"] and len(calls) == 4
    assert cached["assembly_norm"]["line_z0_ohm"] == pytest.approx(an["line_z0_ohm"])
    raw = rot.solve_smatrix_openems(tmp_path, template="lange", params={},
                                    freq_range_ghz=(2.4, 2.6), n_ports=4)
    assert raw["assembly_norm"] is None and len(calls) == 4   # 断点复用，零重跑
    assert np.allclose(raw["s_params"], res["s_params_raw"], atol=1e-12)


# ---------------------------------------------------------------------------
# 4. 判读器纯函数
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template", ["lange", "cline_coupler"])
def test_judge_network_ideal_circuit_judge_passes(template):
    f_ghz = np.linspace(2.0, 3.0, 401)
    f0 = float(smoke.TEMPLATE_META[template]["f0_ghz"])
    params = {k: float(v) for k, v in smoke.TEMPLATE_NOMINAL[template].items()}
    circ = smoke.circuit_judge(template, f_ghz, params, f0)
    eps_hj = smoke.feed_eps_hj(params, f0)
    j = smoke.judge_network(template, f_ghz, circ, params, f0, d_beta=0.0, eps_hj=eps_hj)
    assert j["verdict"] == "PASS"
    assert j["fc_at_band_edge"] is False and j["fc_note"] is None
    lo, hi = j["fc_plateau_ghz"]
    assert 2.0 <= lo <= f0 <= hi <= 3.0
    assert j["em_vs_circuit"]["max_abs_ds31_db_band"] == pytest.approx(0.0, abs=1e-9)
    assert j["gates"]["G5_beta_feed_pct_recorded"]["ok"] is True
    json.dumps(j, default=str)


def test_judge_network_persistent_overcoupling_flags_band_edge():
    f_ghz = np.linspace(2.0, 3.0, 101)
    s = np.zeros((101, 4, 4), dtype=complex)
    s[:, 1, 0] = s[:, 0, 1] = 0.5            # S21 −6dB
    s[:, 2, 0] = s[:, 0, 2] = 0.8            # S31 −1.9dB：不平衡带内恒定
    s[:, 3, 1] = s[:, 1, 3] = 0.8
    s[:, 3, 2] = s[:, 2, 3] = 0.5
    params = {k: float(v) for k, v in smoke.TEMPLATE_NOMINAL["lange"].items()}
    j = smoke.judge_network("lange", f_ghz, s, params, 2.5, d_beta=float("nan"),
                            eps_hj=2.85)
    assert j["verdict"] == "FAIL"
    assert j["fc_at_band_edge"] is True and "带沿" in j["fc_note"]
    assert j["fc_plateau_ghz"] == [2.0, 3.0]
    assert j["gates"]["G5_beta_feed_pct_recorded"]["ok"] is True   # nan=未记录不翻转


def test_resolve_root_guard():
    assert smoke.resolve_root(None, "lange") == Path("runs/smoke_c4/lange")
    assert smoke.resolve_root("runs/x", "lange") == Path("runs/x/lange")
    assert smoke.resolve_root("runs/x/lange", "lange") == Path("runs/x/lange")


# ---------------------------------------------------------------------------
# 5. 离线复判脚本端到端
# ---------------------------------------------------------------------------

def _write_ideal_lange_s4p(root: Path) -> np.ndarray:
    import skrf

    f_ghz = np.linspace(2.0, 3.0, 401)
    params = {k: float(v) for k, v in smoke.TEMPLATE_NOMINAL["lange"].items()}
    circ = smoke.circuit_judge("lange", f_ghz, params, 2.5)
    freq = skrf.Frequency(2.0, 3.0, 401, unit="GHz")
    skrf.Network(frequency=freq, s=circ, z0=50.0).write_touchstone(str(root / "lange.s4p"))
    return f_ghz


def test_rejudge_template_and_main_offline(tmp_path):
    _write_ideal_lange_s4p(tmp_path)
    for k in range(1, 5):
        for p in range(1, 5):
            _write_tl_probes(tmp_path / f"p{k}" / "fdtd", p, 50.0)
    r = jca.rejudge_template("lange", tmp_path, tmp_path, beta_pct=0.5,
                             beta_source="test", solve_s=1.0)
    assert r["verdict"] == "PASS" and r["verdict_after_norm"] == "PASS"
    assert abs(r["scalar_scan"]["z_best_ohm"] - 50.0) <= 0.25
    assert np.allclose(r["assembly_norm"]["line_z0_ohm"], 50.0, rtol=5e-3)
    assert r["raw"]["beta_feed_pct"] == 0.5
    json.dumps(r, default=str)

    rc = jca.main(["--root", str(tmp_path), "--templates", "lange",
                   "--beta-pct", "lange=0.5", "--solve-s", "lange=1.0"])
    assert rc == 0
    out = json.loads((tmp_path / "lange_judge.json").read_text(encoding="utf-8"))
    assert out["verdict"] == "PASS" and out["solve_s"] == 1.0
    md = (tmp_path / "assembly_diag.md").read_text(encoding="utf-8")
    assert "σmax 归一化前后对照" in md and "\ufffd" not in md
