"""HFSS g0 仲裁脚本自验门：预声明门与规范回收（零仿真）。

钉死三件事（scripts/hfss_mapes_g0_arbitration.py）：
1. 预声明门阈值写死且边界语义正确（≤5% AGREE / 5–15% PARTIAL / >15% DISAGREE）；
2. ``analyze`` 的 g0/τ 拟合在合成数据（oe = g0·e^{j2πfτ}·hfss，已知规范）下
   精确回收 |g0| 与 τ，门判定随之正确；
3. |S11,h| < S11_FLOOR 的深谷频点被剔除出统计（n_freq_used 减少）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "hfss_mapes_g0_arbitration.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("hfss_mapes_g0_arbitration", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_thresholds_are_predeclared_and_exact():
    mod = _load_script()
    assert mod.GATE_AGREE_MAX == 0.05
    assert mod.GATE_PARTIAL_MAX == 0.15
    assert mod.PRIMARY_CALIBER == "s_cal_sym_proj"
    assert mod.verdict_of(0.0) == "AGREE"
    assert mod.verdict_of(0.05) == "AGREE"
    assert mod.verdict_of(0.05 + 1e-9) == "PARTIAL"
    assert mod.verdict_of(0.15) == "PARTIAL"
    assert mod.verdict_of(0.15 + 1e-9) == "DISAGREE"


@pytest.fixture()
def synthetic_case(tmp_path, monkeypatch):
    """构造 hfss s2p + oe = g0·e^{j2πfτ}·hfss 的合成数据并替换 npz 路径。"""
    import skrf

    mod = _load_script()
    freq = np.linspace(1.0e9, 6.0e9, 41)
    g0, tau_s = 0.993, -6.0e-12
    s11_h = 0.55 * np.exp(1j * 2.0 * np.pi * freq * 3.0e-12)
    s21_h = 1.3e-5 * np.exp(-1j * 2.0 * np.pi * freq * 1.0e-11)
    gauge = g0 * np.exp(1j * 2.0 * np.pi * freq * tau_s)
    s = np.zeros((41, 2, 2), dtype=complex)
    s[:, 0, 0] = s11_h
    s[:, 1, 0] = s21_h
    net = skrf.Network(frequency=skrf.Frequency.from_f(freq, "hz"), s=s)
    s2p = tmp_path / "synthetic.s2p"
    net.write_touchstone(str(s2p))

    def _oe(g: np.ndarray) -> dict[str, np.ndarray]:
        s_oe = np.zeros((41, 150, 150), dtype=complex)
        s_oe[:, 0, 0] = s11_h * g
        s_oe[:, 1, 0] = s21_h * g
        return {"freq_hz": freq, "s_cal_sym_proj": s_oe, "s_cal_sym": s_oe * 0.99}

    np.savez_compressed(tmp_path / "z_all_s5.npz", **_oe(gauge))
    np.savez_compressed(tmp_path / "z_all.npz",
                        freq_hz=freq, s_all=_oe(gauge)["s_cal_sym"])
    monkeypatch.setattr(mod, "OE_S5_NPZ", tmp_path / "z_all_s5.npz")
    monkeypatch.setattr(mod, "OE_S4_NPZ", tmp_path / "z_all.npz")

    class _Layout:
        topology_key = "mapes:synthetic"
        n_ports = 150

    build_info = {"layout": _Layout(), "n_loads": 184, "n_bleeds": 36}
    return mod, s2p, build_info, g0, tau_s


def test_analyze_recovers_known_gauge_and_gate(synthetic_case):
    mod, s2p, build_info, g0, tau_s = synthetic_case
    res = mod.analyze(s2p, passes=6, delta_s=0.002, version="synthetic",
                      build_info=build_info, t_wall={"build_s": 0, "solve_s": 0})
    primary = res["calibers"][mod.PRIMARY_CALIBER]
    # 脚本 g0 定义 = S_hfss/S_oe = 应乘到 openEMS 装配列上的规范（与
    # core.mapes.gauge_factor 的 S·g 方向一致）；合成 oe = g·hfss → 回收 1/g、−τ。
    # |S11| 相对差 = |1−g0| ≈ 0.7% → AGREE
    assert abs(primary["g0_abs"] - 1.0 / g0) < 1e-9
    assert abs(primary["tau_ps"] + tau_s * 1e12) < 1e-6
    assert abs(primary["d_s11_median_rel"] - abs(1.0 - g0)) < 1e-9
    assert res["verdict"] == "AGREE"
    assert res["direction"] == ""
    # 三个口径都进结果（s_cal_sym 再乘 0.99 离 1 更远 → d 更大）
    assert set(res["calibers"]) == {"s_cal_sym_proj", "s_cal_sym", "s4_raw"}
    assert (res["calibers"]["s_cal_sym"]["d_s11_median_rel"]
            > res["calibers"][mod.PRIMARY_CALIBER]["d_s11_median_rel"])


def test_floor_excludes_deep_nulls(synthetic_case):
    mod, s2p, build_info, _g0, _tau_s = synthetic_case
    import skrf

    freq = np.linspace(1.0e9, 6.0e9, 41)
    s = np.zeros((41, 2, 2), dtype=complex)
    s11 = 0.55 * np.exp(1j * 2.0 * np.pi * freq * 3.0e-12)
    s11[7] = 0.01  # 单点深谷（|S11| < 0.05），oe 侧故意差 3 倍
    s[:, 0, 0] = s11
    s[:, 1, 0] = 1.3e-5
    net = skrf.Network(frequency=skrf.Frequency.from_f(freq, "hz"), s=s)
    s2p2 = s2p.parent / "with_null.s2p"
    net.write_touchstone(str(s2p2))
    with np.load(mod.OE_S5_NPZ) as d:
        s_oe = d["s_cal_sym_proj"].copy()
    s_oe[7, 0, 0] = 0.03
    np.savez_compressed(mod.OE_S5_NPZ, freq_hz=freq, s_cal_sym_proj=s_oe,
                        s_cal_sym=s_oe)
    res = mod.analyze(s2p2, passes=1, delta_s=0.0, version="synthetic",
                      build_info=build_info, t_wall={})
    primary = res["calibers"][mod.PRIMARY_CALIBER]
    assert primary["n_freq_used"] == 40
