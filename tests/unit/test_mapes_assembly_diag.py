"""A8 MAPES stage-5 装配重推导内核定向单测（确定性、离线、零真机）。

覆盖 W3③ 文件面新增内核（core/mapes.py stage-5 节）：
1. ``assemble_s_from_ui``：无偏合成 (uf, if) 下 wave/current 两口径都精确复原
   S_true（≤1e-12）；形状/口径非法显式报错；
2. 探针偏差注入回收：逐端口行因子 r（端接口 i 探针偏差）× 列因子 c（激励口
   SREF 偏差）注入后，wave 口径互易破缺可见；current 口径 +
   ``fit_reciprocity_gain`` + ``apply_port_gain`` 得到**精确对称**结果，且
   等于合同变换 D·S·D·C（D=diag(r)，C 全局常数）——互易只能辨识 r/c 势场，
   不能分离 r 与 c、也不能辨识全局尺度（模块 docstring 如实声明的口径边界）；
3. ``gauge_factor``：|g|=g0、相位斜率 2πτ；
4. ``passive_project_z``：非无源对称 Z 投影后互易保持（≤1e-13）、min_eig ≥
   floor、钳位量级如实回报；已无源输入零改动；
5. ``z_all_gate``：门常量写死值；RLC 网格 S 全过、注入负阻/非对称后逐门失守；
6. ``reciprocity_pair_residual``：坏对定位索引与残差一致。

7. ``scripts/mapes_s2_zall.reassemble_z_all``：合成偏差下四阶段编排（S1 current →
   S2 gain-cal → S3 sym → S4 passive-proj）门指标形态：S3 互易精确、S4 三门全过、
   投影量级回报；``gauge``/``project`` 开关生效；``read_rounds_ui`` 缺档显式报错。

阈值依据：合成路径为纯线性代数，随机复矩阵实测 1e-14 量级，断言 1e-10；
D·S·D 合同关系在无旋度模型下精确成立，断言相对 1e-8。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import (
    PASSIVE_FLOOR_OHM,
    ZALL_GATE_MIN_EIG_RE,
    ZALL_GATE_RECIPROCITY_MAX,
    ZALL_GATE_SIGMA_MAX,
    apply_port_gain,
    assemble_s_from_ui,
    fake_mesh,
    fit_reciprocity_gain,
    gauge_factor,
    passive_project_z,
    reciprocity_pair_residual,
    s_to_z,
    z_all_gate,
    z_to_s,
)

Z0 = 50.0
FREQ_HZ = np.array([1.0e9, 3.5e9, 6.0e9])
Q = 9
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "mapes_s2_zall.py"


def _stage2_module():
    spec = importlib.util.spec_from_file_location("mapes_s2_zall", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _true_s() -> np.ndarray:
    mesh = fake_mesh(Q, n_cols=3)
    z = np.stack([mesh.z_all(f) for f in FREQ_HZ])
    return z_to_s(z, reference_impedance=Z0)


def _synth_ui(s: np.ndarray, *, r=None, c=None):
    """由 S_true 合成激励轮转原始 (uf, if)：轮 k 入射 a=e_k，U=a+b，I=(a−b)/Z0。

    ``r``（q,）端接口 i 探针行因子：I^m_p = I_p·r_p（仅对非激励口生效——激励口
    的探针偏差全部折进列因子 c）；``c``（q,）激励口列因子：轮 k 的 (U_k, I_k)
    同乘 c_k（SREF 偏差）。
    """
    nf, q, _ = s.shape
    uf = np.zeros((q, q, nf), dtype=complex)
    if_ = np.zeros((q, q, nf), dtype=complex)
    for k in range(q):
        a = np.zeros(q, dtype=complex)
        a[k] = 1.0
        b = s[:, :, k]                      # (nf, q)
        u = a[None, :] + b
        i = (a[None, :] - b) / Z0
        if r is not None:
            rr = np.asarray(r, dtype=complex).copy()
            rr[k] = 1.0
            i = i * rr[None, :]
        if c is not None:
            u[:, k] *= c[k]
            i[:, k] *= c[k]
        uf[k] = u.T
        if_[k] = i.T
    return uf, if_


# ─── 1. 无偏合成：两口径精确复原 ────────────────────────────────────────────

@pytest.mark.parametrize("numerator", ["wave", "current"])
def test_assemble_unbiased_recovers_s_true(numerator: str) -> None:
    s = _true_s()
    uf, if_ = _synth_ui(s)
    got = assemble_s_from_ui(uf, if_, reference_impedance=Z0, numerator=numerator)
    assert got.shape == s.shape
    assert np.max(np.abs(got - s)) < 1.0e-10


def test_assemble_rejects_bad_inputs() -> None:
    s = _true_s()
    uf, if_ = _synth_ui(s)
    with pytest.raises(ConfigError):
        assemble_s_from_ui(uf, if_, numerator="voltage")
    with pytest.raises(ConfigError):
        assemble_s_from_ui(uf[:, :4], if_[:, :4])
    with pytest.raises(ConfigError):
        assemble_s_from_ui(uf, if_, reference_impedance=0.0)


# ─── 2. 偏差注入回收：势场辨识边界如实 ──────────────────────────────────────

def _bias_factors() -> tuple[np.ndarray, np.ndarray]:
    idx = np.arange(Q)
    r = (1.0 + 0.012 * np.cos(idx)) * np.exp(1j * 0.02 * np.sin(1.7 * idx))
    c = (1.0 - 0.008 * np.sin(0.9 * idx)) * np.exp(-1j * 0.015 * np.cos(2.3 * idx))
    return r, c


def test_wave_numerator_shows_injected_reciprocity_break() -> None:
    s = _true_s()
    r, c = _bias_factors()
    uf, if_ = _synth_ui(s, r=r, c=c)
    got = assemble_s_from_ui(uf, if_, numerator="wave")
    rec = np.max(np.abs(got - np.swapaxes(got, -1, -2)))
    assert rec > 1.0e-3  # 注入 1-2% 探针偏差 → 互易破缺可见（真数据 3.4e-2 同级）


def test_current_plus_gain_fit_recovers_congruence_exactly() -> None:
    s = _true_s()
    r, c = _bias_factors()
    uf, if_ = _synth_ui(s, r=r, c=c)
    s1 = assemble_s_from_ui(uf, if_, numerator="current")
    x, info = fit_reciprocity_gain(s1)
    assert x.shape == (len(FREQ_HZ), Q)
    assert info["fit_resid_wrms_max"] < 1.0e-8  # 无旋度模型 → 势场精确
    assert np.max(np.abs(x.sum(axis=1))) < 1.0e-8  # 规范 Σx=0
    s2 = apply_port_gain(s1, x)
    rec = np.max(np.abs(s2 - np.swapaxes(s2, -1, -2)))
    assert rec < 1.0e-9
    # 非对角元 = D·S·D·C（D=diag(r)，C 逐频全局复常数）
    off = ~np.eye(Q, dtype=bool)
    dsd = r[None, :, None] * s * r[None, None, :]
    ratio = (s2 / dsd)[:, off]
    for f in range(len(FREQ_HZ)):
        rf = ratio[f]
        assert np.max(np.abs(rf / rf.mean() - 1.0)) < 1.0e-8
    # 互易不能分离 r 与 c：若 |r|≠1，结果非无源可见（口径边界）
    gate = z_all_gate(s2)
    assert gate["pass_reciprocity"]


def test_uniform_row_bias_is_a_pure_global_gauge() -> None:
    """r 全端口相同 → 合同变换退化为全局尺度 r²，可由 gauge_factor 精确抵消。"""
    s = _true_s()
    r = np.full(Q, 1.01 * np.exp(1j * 0.01))
    _, c = _bias_factors()
    uf, if_ = _synth_ui(s, r=r, c=c)
    s1 = assemble_s_from_ui(uf, if_, numerator="current")
    x, _ = fit_reciprocity_gain(s1)
    s2 = apply_port_gain(s1, x)
    off = ~np.eye(Q, dtype=bool)
    for f in range(len(FREQ_HZ)):
        g = (s2[f] / s[f])[off]
        assert np.max(np.abs(g / g.mean() - 1.0)) < 1.0e-8
        s_fixed = s2[f] / g.mean()
        assert np.max(np.abs(s_fixed[off] - s[f][off])) < 1.0e-9


# ─── 3. gauge_factor ─────────────────────────────────────────────────────────

def test_gauge_factor_magnitude_and_phase_slope() -> None:
    g = gauge_factor(FREQ_HZ, 0.98, 1.3e-12)
    assert np.allclose(np.abs(g), 0.98)
    slope = np.diff(np.unwrap(np.angle(g))) / np.diff(FREQ_HZ)
    assert np.allclose(slope, 2.0 * np.pi * 1.3e-12)
    with pytest.raises(ConfigError):
        gauge_factor(FREQ_HZ, 0.0, 0.0)
    with pytest.raises(ConfigError):
        gauge_factor(FREQ_HZ, 1.0, np.nan)


# ─── 4. passive_project_z ────────────────────────────────────────────────────

def test_passive_project_preserves_reciprocity_and_reports_clip() -> None:
    s = _true_s()
    z = s_to_z(s, reference_impedance=Z0)
    lam0, vec0 = np.linalg.eigh(z[1].real)
    v = vec0[:, 0]
    z_bad = z.copy()
    z_bad[1] -= (lam0[0] + 0.7) * np.outer(v, v)  # 沿最小特征向量压到 −0.7Ω（对称保持）
    lam_before = np.linalg.eigvalsh(z_bad[1].real).min()
    assert lam_before == pytest.approx(-0.7, abs=1e-9)
    z_p, info = passive_project_z(z_bad)
    assert np.max(np.abs(z_p - np.swapaxes(z_p, -1, -2))) < 1.0e-13
    for f in range(len(FREQ_HZ)):
        assert np.linalg.eigvalsh(z_p[f].real).min() >= PASSIVE_FLOOR_OHM - 1.0e-12
    assert info["max_eig_clip_ohm"] == pytest.approx(PASSIVE_FLOOR_OHM - lam_before, rel=1e-6)
    assert info["max_abs_delta_ohm"] > 0.0
    # 已无源：零改动
    z_same, info0 = passive_project_z(z)
    assert np.max(np.abs(z_same - z)) < 1.0e-12
    assert info0["max_eig_clip_ohm"] == 0.0


def test_passive_project_rejects_bad_floor() -> None:
    z = s_to_z(_true_s())
    with pytest.raises(ConfigError):
        passive_project_z(z, floor=-1.0)
    with pytest.raises(ConfigError):
        passive_project_z(np.ones((3, 4)))


# ─── 5. z_all_gate：常量与判定 ───────────────────────────────────────────────

def test_gate_constants_are_pre_declared() -> None:
    assert ZALL_GATE_RECIPROCITY_MAX == 1.0e-3
    assert ZALL_GATE_MIN_EIG_RE == -1.0e-6
    assert ZALL_GATE_SIGMA_MAX == 1.001
    assert PASSIVE_FLOOR_OHM == 1.0e-6


def test_gate_passes_rlc_and_fails_on_injected_violations() -> None:
    s = _true_s()
    g = z_all_gate(s)
    assert g["pass"] and g["pass_reciprocity"] and g["pass_passivity"] and g["pass_sigma_max"]
    assert g["n_freq"] == len(FREQ_HZ)
    assert g["n_freq_reciprocity_pass"] == len(FREQ_HZ)
    # 非对称注入 → 互易门失守，其他门不受影响的量级
    s_asym = s.copy()
    s_asym[:, 0, 1] += 5.0e-3
    g1 = z_all_gate(s_asym)
    assert not g1["pass_reciprocity"] and not g1["pass"]
    # 全局放大到 σmax≈1.02 → σmax/无源门双失守，互易门仍过
    smax_true = float(np.linalg.norm(s, ord=2, axis=(-2, -1)).max())
    g2 = z_all_gate(s * (1.02 / smax_true))
    assert g2["pass_reciprocity"]
    assert not g2["pass_sigma_max"] and not g2["pass_passivity"] and not g2["pass"]
    assert g2["sigma_max"] > 1.001


# ─── 6. 坏对定位 ─────────────────────────────────────────────────────────────

def test_reciprocity_pair_residual_localizes_injected_pair() -> None:
    s = _true_s()
    s[:, 2, 5] += 2.0e-2
    tab = reciprocity_pair_residual(s)
    k = int(np.argmax(tab["residual_max"]))
    assert (int(tab["pair_i"][k]), int(tab["pair_k"][k])) == (2, 5)
    assert tab["residual_max"][k] == pytest.approx(2.0e-2, rel=1e-9)
    assert tab["coupling_max"][k] >= np.abs(s[:, 2, 5]).max() - 1e-15


# ─── 7. scripts/mapes_s2_zall：reassemble 管线编排 ──────────────────────────

def test_script_reassemble_pipeline_stages_and_projection() -> None:
    mod = _stage2_module()
    s = _true_s()
    r, c = _bias_factors()
    uf, if_ = _synth_ui(s, r=r, c=c)
    res = mod.reassemble_z_all(uf, if_, FREQ_HZ)
    stages = res["stages"]
    assert set(stages) == {"S1_current", "S2_gain_cal", "S3_sym", "S4_passive_proj"}
    assert stages["S1_current"]["gate"]["reciprocity_max"] > 1.0e-3
    assert stages["S3_sym"]["gate"]["reciprocity_max"] < 1.0e-12
    assert stages["S4_passive_proj"]["gate"]["pass"]
    assert stages["S4_passive_proj"]["gate"]["min_eig_re_min"] >= 1.0e-6 - 1e-12
    assert stages["S4_passive_proj"]["gate"]["sigma_max"] <= 1.001
    assert res["projection_info"]["max_eig_clip_ohm"] >= 0.0
    z = res["z_cal_sym"]
    assert np.max(np.abs(z - np.swapaxes(z, -1, -2))) < 1.0e-10
    assert np.allclose(z_to_s(z, reference_impedance=Z0), res["s_cal_sym"])
    # gauge/project 开关
    res2 = mod.reassemble_z_all(uf, if_, FREQ_HZ, gauge=(0.99, 0.5), project=False)
    assert "z_cal_sym_proj" not in res2
    assert res2["gauge"] == (0.99, 0.5)
    assert "S4_passive_proj" not in res2["stages"]
    # wave 口径分支
    res3 = mod.reassemble_z_all(uf, if_, FREQ_HZ, numerator="wave")
    assert "S1_wave" in res3["stages"]
    with pytest.raises(ConfigError):
        mod.reassemble_z_all(uf, if_, FREQ_HZ, numerator="voltage")


def test_script_read_rounds_ui_rejects_missing_dump(tmp_path: Path) -> None:
    mod = _stage2_module()
    fdtd = tmp_path / "p1" / "fdtd"
    fdtd.mkdir(parents=True)
    (fdtd / "port_ut_1").write_text("0 0\n1 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        mod.read_rounds_ui(tmp_path, 2, FREQ_HZ)
