"""端口 renormalize 数学钉子（定案 (a)，零 openEMS 依赖、零网络）。

机理与全链：openEMS 端口面贴 PML，非激励
端的线由 PML 按线自身 Z0 匹配端接 → 单激励 uf 比值是**带载比值**（非激励端在
50Ω 基下被 Γ=(Z−50)/(Z+50) 端接、a≠0），与 50Ω 双端接裁判（fake Pozar
ABCD@50 / skrf renormalize([50,50])）本非同一量。落实（a）：
loaded_ratios_to_line_basis（按列反演 ≡ CalcPort ref=Z_k）→ 线基去嵌
（e^{+γl}，β 引擎/α HJ）→ skrf renormalize_s(traveling) → 50Ω。

本文件钉：
1. skrf renormalize_s 方向语义锚（匹配线 S=0(Z 基)↔(Z−50)/(Z+50)(50 基)）；
2. 理想阶跃真波基闭式 [[Γ,t],[t,−Γ]]：线基镜像/互易性质（G4/G5 物理语义）；
3. 带载比值按列反演回收 S_true（教科书带载公式为独立前向构造，实/复 Z，1e-10）；
4. 全链输出 vs fake `_wstep_sparams`（Pozar ABCD@50 独立机制，1e-10）+ 整矩
   阵 renormalize 反例（误差=|Γ_step|，钉死带载陷阱）+ 50Ω 线恒等；
5. wstep 去嵌长度/γ 闭式 + 冒烟脚本胶水 + 渲染 ZL 落盘（via/msl_cpw 不变）。
"""
from __future__ import annotations

import csv
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from skrf.network import renormalize_s

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.fake_adapter import _wstep_sparams
from rfauto.adapters.openems_templates import (
    TEMPLATE_NOMINAL,
    loaded_ratios_to_line_basis,
    render_script,
    renorm_engine_s_to_ref,
    tl_gamma_per_m,
    wstep_deembed_lens_m,
)
from rfauto.core.synthesis import Stackup, forward_z0

W1, W2, L = 1.1134, 1.897, 40.0
F_MID = 2.5
_STACK = Stackup.from_materials_yaml("rogers4350b_h0.508")
Z1, EPS1 = forward_z0(W1, F_MID, _STACK)
Z2, EPS2 = forward_z0(W2, F_MID, _STACK)
TAN_D = 0.0037
C0 = 299792458.0
L_END = 0.02                          # 线端面（fake seg_len=L/2）
L_DEEMBED = 0.026666666666666664      # 测量面→线端 = 2·(60−20)/3 mm
L_MEAS = L_END + L_DEEMBED            # 测量面距阶跃 46.67mm


def _gamma(f_hz: np.ndarray, eps_eff: float, tan_d: float = TAN_D) -> np.ndarray:
    """段复传播常数（HJ 闭式，=fake 同式：α=πf√ε·tanδ/c，β=2πf√ε/c）。"""
    return tl_gamma_per_m(f_hz, eps_eff, tan_d)


def _s_true(f_hz: np.ndarray, za: complex, zb: complex,
            l1_m: float, l2_m: float, tan_d: float = TAN_D) -> np.ndarray:
    """[Za 线 l1 | 阶跃 | Zb 线 l2] 的真波基 S（闭式：Γ/t × 传播因子）。

    traveling 波定义下阶跃闭式 Γ=(Zb−Za)/(Zb+Za)、t=2√Za√Zb/(Za+Zb) 对复 Z
    同样成立（V/I 连续 + a=(u+Zi)/(2√Z)）。有耗时 |S11|=|Γ|e^{−2α1l1}、
    |S22|=|Γ|e^{−2α2l2}，α1≠α2 → 幅度镜像残差 ~1e-4（物理，非算法）。
    """
    g = (zb - za) / (zb + za)
    t = 2 * np.sqrt(za) * np.sqrt(zb) / (za + zb)
    g1, g2 = _gamma(f_hz, EPS1, tan_d), _gamma(f_hz, EPS2, tan_d)
    s = np.empty((len(f_hz), 2, 2), dtype=complex)
    s[:, 0, 0] = g * np.exp(-2 * g1 * l1_m)
    s[:, 1, 1] = -g * np.exp(-2 * g2 * l2_m)
    s[:, 1, 0] = t * np.exp(-(g1 * l1_m + g2 * l2_m))
    s[:, 0, 1] = s[:, 1, 0]
    return s


def _engine_ratios(s50: np.ndarray, za: complex, zb: complex) -> np.ndarray:
    """引擎单激励带载比值（教科书公式，独立前向构造）。

    非激励端在 50Ω 基下被 Γ_k=(Z_k−50)/(Z_k+50) 端接：
    r11 = S11 + S12·S21·Γ2/(1−S22·Γ2)，r21 = S21/(1−S22·Γ2)，镜像列同型。
    """
    g1 = (za - 50.0) / (za + 50.0)
    g2 = (zb - 50.0) / (zb + 50.0)
    s11, s12 = s50[:, 0, 0], s50[:, 0, 1]
    s21, s22 = s50[:, 1, 0], s50[:, 1, 1]
    r = np.empty_like(s50)
    r[:, 0, 0] = s11 + s12 * s21 * g2 / (1 - s22 * g2)
    r[:, 1, 0] = s21 / (1 - s22 * g2)
    r[:, 1, 1] = s22 + s21 * s12 * g1 / (1 - s11 * g1)
    r[:, 0, 1] = s12 / (1 - s11 * g1)
    return r


def _synth_engine(f_hz: np.ndarray, za: complex, zb: complex,
                  l_m: float, tan_d: float = TAN_D) -> tuple[np.ndarray, np.ndarray]:
    """合成引擎：S_true@测量面 → 50Ω 基 → 带载比值。返回 (s_true, r)。"""
    s_true = _s_true(f_hz, za, zb, l_m, l_m, tan_d)
    s50 = renormalize_s(s_true, [za, zb], [50.0, 50.0], s_def="traveling")
    return s_true, _engine_ratios(s50, za, zb)


# ─── 1. skrf 方向语义锚 ───────────────────────────────────────────────────────

def test_renormalize_direction_anchor_matched_line():
    """匹配线 S=0（Z 基）↔ (Z−50)/(Z+50)（50 基）=CalcPort 对匹配非 50 线的实录。"""
    one = renormalize_s(np.zeros((1, 1, 1)), [Z2], [50.0], s_def="traveling")
    assert one[0, 0, 0] == pytest.approx((Z2 - 50.0) / (Z2 + 50.0), abs=1e-12)
    back = renormalize_s(one, [50.0], [Z2], s_def="traveling")
    assert abs(back[0, 0, 0]) == pytest.approx(0.0, abs=1e-12)


# ─── 2. 理想阶跃真波基闭式（G4/G5 物理语义）───────────────────────────────────

def test_step_line_basis_mirror_and_reciprocity():
    """线基内 |S11|=|S22|（无耗精确）、S21=S12（有耗亦精确）——G4/G5 判据语义。"""
    f = np.linspace(1.5e9, 3.5e9, 201)
    s0 = _s_true(f, Z1, Z2, L_MEAS, L_MEAS, tan_d=0.0)
    assert np.max(np.abs(np.abs(s0[:, 0, 0]) - np.abs(s0[:, 1, 1]))) <= 1e-12
    assert np.max(np.abs(s0[:, 1, 0] - s0[:, 0, 1])) <= 1e-12
    s = _s_true(f, Z1, Z2, L_MEAS, L_MEAS)              # 有耗：互易精确、镜像 ~1e-4
    assert np.max(np.abs(s[:, 1, 0] - s[:, 0, 1])) <= 1e-12
    assert 1e-6 < np.max(np.abs(np.abs(s[:, 0, 0]) - np.abs(s[:, 1, 1]))) < 5e-4
    sj = _s_true(np.array([2.5e9]), Z1, Z2, 0.0, 0.0)
    assert abs(sj[0, 0, 0]) == pytest.approx(abs((Z2 - Z1) / (Z2 + Z1)), rel=1e-9)
    assert abs(sj[0, 1, 0]) == pytest.approx(2 * math.sqrt(Z1 * Z2) / (Z1 + Z2), rel=1e-9)
    # 引擎 raw 口径象（无耗）：带载 |r11| 恒=|Γ_step|（engine_termination_model 同象；
    # Z1=49.99999≠50 精确值留 1e-7 级基残差）
    _, r0 = _synth_engine(f, Z1, Z2, L_MEAS, tan_d=0.0)
    assert np.max(np.abs(np.abs(r0[:, 0, 0]) - abs((Z2 - Z1) / (Z2 + Z1)))) <= 1e-6
    # raw 口径本不镜像/不互易（pt3 FAIL 的确定性再现）
    _, r = _synth_engine(f, Z1, Z2, L_MEAS)
    assert np.max(np.abs(np.abs(r[:, 0, 0]) - np.abs(r[:, 1, 1]))) > 0.1
    assert np.max(np.abs(np.abs(r[:, 1, 0]) - np.abs(r[:, 0, 1]))) > 0.03


# ─── 3. 带载比值按列反演 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("zl", [(Z1, Z2), (49.6 + 0.21j, 34.7 - 0.15j)])
def test_loaded_ratios_inversion_recovers_s_true(zl):
    """引擎带载比值（教科书前向）→ 按列反演 = S_true（实/复 Z 均精确）。"""
    f = np.linspace(1.5e9, 3.5e9, 101)
    s_true, r = _synth_engine(f, zl[0], zl[1], L_MEAS)
    rec = loaded_ratios_to_line_basis(r, list(zl), 50.0)
    assert np.max(np.abs(rec - s_true)) <= 1e-10


def test_loaded_ratios_inversion_accepts_per_frequency_z():
    """z_line 可逐频 (N,) 数组（引擎自算 ZL(f) 基）。"""
    f = np.linspace(1.5e9, 3.5e9, 41)
    s_true, r = _synth_engine(f, Z1, Z2, L_MEAS)
    zl = np.column_stack([np.full(len(f), Z1), np.full(len(f), Z2)])
    rec = loaded_ratios_to_line_basis(r, zl, 50.0)
    assert np.max(np.abs(rec - s_true)) <= 1e-10
    with pytest.raises(ValueError):
        loaded_ratios_to_line_basis(r[:, 0, :], [Z1, Z2], 50.0)


def test_whole_matrix_renormalize_is_wrong_on_loaded_ratios():
    """反例钉子：对装配带载比值整块 renormalize_s ≠ S_true（误差≈|Γ_step|）。

    防回归：定案 (a) 的正确路径是按列反演（loaded_ratios_to_line_basis），
    不是把 [50,50] 基带载矩阵当 S^50 直接换基。
    """
    f = np.linspace(1.5e9, 3.5e9, 41)
    s_true, r = _synth_engine(f, Z1, Z2, L_MEAS)
    naive = renormalize_s(r, [50.0, 50.0], [Z1, Z2], s_def="traveling")
    assert np.max(np.abs(naive - s_true)) > 0.9 * abs((Z2 - Z1) / (Z2 + Z1))
    assert np.max(np.abs(loaded_ratios_to_line_basis(r, [Z1, Z2], 50.0) - s_true)) <= 1e-10


def test_50ohm_lines_identity():
    """端口线全 50Ω（Γ=0）→ 反演恒等：50Ω 模板接此 helper 天然无变化。"""
    rng = np.random.default_rng(7)
    s = (rng.normal(size=(21, 2, 2)) + 1j * rng.normal(size=(21, 2, 2))) * 0.3
    assert np.max(np.abs(loaded_ratios_to_line_basis(s, [50.0, 50.0], 50.0) - s)) <= 1e-12
    out = renorm_engine_s_to_ref(s, [50.0, 50.0], 50.0)
    assert np.max(np.abs(out - s)) <= 1e-12


def test_renorm_roundtrip_line_to_50_to_line():
    """helper 输出（50Ω 基）逆 renormalize 回线基 = S_true（基变换可逆钉）。"""
    f = np.linspace(1.5e9, 3.5e9, 41)
    s_true, r = _synth_engine(f, Z1, Z2, L_END)
    s50 = renorm_engine_s_to_ref(r, [Z1, Z2], 50.0)
    back = renormalize_s(s50, [50.0, 50.0], [Z1, Z2], s_def="traveling")
    assert np.max(np.abs(back - s_true)) <= 1e-10
    with pytest.raises(ValueError):
        renorm_engine_s_to_ref(r, [Z1, Z2], 50.0, deembed_lens_m=[L_DEEMBED, L_DEEMBED])


# ─── 4. 全链 vs fake 裁判（独立机制）──────────────────────────────────────────

def test_full_chain_matches_fake_referee_at_line_end_planes():
    """带载比值@46.67mm 面 → 反演+去嵌 26.67mm+renormalize 50 = fake(20mm)。"""
    f = np.linspace(1.5e9, 3.5e9, 201)
    _, r = _synth_engine(f, Z1, Z2, L_MEAS)
    gam = [_gamma(f, EPS1), _gamma(f, EPS2)]
    out = renorm_engine_s_to_ref(r, [Z1, Z2], 50.0, [L_DEEMBED, L_DEEMBED], gam)
    fake = _wstep_sparams(f / 1e9, eps_eff1=EPS1, eps_eff2=EPS2, z1=Z1, z2=Z2,
                          seg_len_mm=L / 2, tan_d=TAN_D)
    assert np.max(np.abs(out - fake)) <= 1e-10
    # 不去嵌 = 46.67mm 面的 50Ω S（与 fake 面不同 → 幅度可分辨），钉去嵌确有作用
    out_nd = renorm_engine_s_to_ref(r, [Z1, Z2], 50.0)
    assert np.max(np.abs(np.abs(out_nd[:, 1, 1]) - np.abs(fake[:, 1, 1]))) > 0.05


def test_full_chain_line_basis_output_is_mirror_reciprocal():
    """z_out=线基输出：合成引擎数据经全链后互易 ≤1e-10、镜像无耗精确/有耗 ~1e-4。"""
    f = np.linspace(1.5e9, 3.5e9, 101)
    for tan_d, mirror_tol in ((0.0, 1e-10), (TAN_D, 5e-4)):
        _, r = _synth_engine(f, Z1, Z2, L_MEAS, tan_d=tan_d)
        gam = [_gamma(f, EPS1, tan_d), _gamma(f, EPS2, tan_d)]
        s_line = renorm_engine_s_to_ref(r, [Z1, Z2], 50.0, [L_DEEMBED, L_DEEMBED],
                                        gam, z_out_ohm=[Z1, Z2])
        a = np.abs(s_line)
        assert np.max(np.abs(a[:, 0, 0] - a[:, 1, 1])) <= mirror_tol
        assert np.max(np.abs(s_line[:, 1, 0] - s_line[:, 0, 1])) <= 1e-10
        assert np.max(np.abs(s_line - _s_true(f, Z1, Z2, L_END, L_END, tan_d))) <= 1e-10


# ─── 5. wstep 专用闭式与胶水 ──────────────────────────────────────────────────

def test_wstep_deembed_lens_matches_template_geometry():
    """去嵌长度=2·(BOARD−L/2)/3（与 _wstep_lines MeasPlaneShift 同式单源）。"""
    l1, l2 = wstep_deembed_lens_m({"line_len_mm": 40.0})
    assert l1 == pytest.approx(L_DEEMBED) and l2 == pytest.approx(L_DEEMBED)
    l1b, _ = wstep_deembed_lens_m({"line_len_mm": 30.0})
    assert l1b == pytest.approx(0.03)


def test_tl_gamma_matches_fake_loss_formulas():
    """tl_gamma_per_m 的 α/β 与 fake `_wstep_sparams` 逐式一致（同源口径）。"""
    f_hz = np.linspace(1.5e9, 3.5e9, 33)
    g = tl_gamma_per_m(f_hz, EPS2, TAN_D)
    assert np.allclose(np.imag(g), 2.0 * np.pi * f_hz * math.sqrt(EPS2) / C0, rtol=1e-12)
    assert np.allclose(np.real(g), np.pi * f_hz * math.sqrt(EPS2) * TAN_D / C0, rtol=1e-12)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_smoke_script_glue_end_to_end_synthetic():
    """冒烟脚本胶水（assemble/process_engine/consistency/judge）合成端到端。"""
    ws = _load("smoke_wstep_anchor_s22")
    f = np.linspace(1.5e9, 3.5e9, 81)
    _, r = _synth_engine(f, Z1, Z2, L_MEAS)
    s_raw = ws.assemble_s_raw(r[:, 0, 0], r[:, 0, 1], r[:, 1, 0], r[:, 1, 1])
    assert np.max(np.abs(s_raw - r)) == 0.0
    proc = ws.process_engine(
        f, s_raw, z_line=[Z1, Z2], beta1=np.imag(_gamma(f, EPS1)),
        beta2=np.imag(_gamma(f, EPS2)), eps_hj1=EPS1, eps_hj2=EPS2,
        tan_d=TAN_D, line_len_mm=L)
    assert proc["lens_m"] == (pytest.approx(L_DEEMBED), pytest.approx(L_DEEMBED))
    cons = ws.consistency_report(proc["s_line"])
    assert cons["mirror_mag"] <= 5e-4 and cons["recip_mag"] <= 1e-9   # 有耗镜像 ~1e-4
    fake = _wstep_sparams(f / 1e9, eps_eff1=EPS1, eps_eff2=EPS2, z1=Z1, z2=Z2,
                          seg_len_mm=L / 2, tan_d=TAN_D)
    jd = ws.judge_report(proc["s_50"], fake)
    assert jd["d11_mag"] <= 1e-9 and jd["d22_mag"] <= 1e-9 and jd["d21_mag"] <= 1e-9
    assert jd["s21_mag_mean"] == pytest.approx(float(np.abs(fake[:, 1, 0]).mean()), abs=1e-9)
    assert ws.band_median(f, np.arange(len(f), dtype=float), 2.5e9) == pytest.approx(40.0)


def test_read_port_beta_csv_with_and_without_zl(tmp_path):
    """port_beta.csv 解析：header 驱动，ZL 列可缺（pt3 旧 run 兼容）。"""
    ws = _load("smoke_wstep_anchor_s22")
    p_old = tmp_path / "beta_old.csv"
    with open(p_old, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz", "beta1_rad_per_m", "beta2_rad_per_m"])
        w.writerow([1.5e9, 88.0, 92.0])
        w.writerow([2.5e9, 90.0, 94.0])
    d = ws.read_port_beta_csv(p_old)
    assert "zl1" not in d and d["beta2"][1] == pytest.approx(94.0)
    p_new = tmp_path / "beta_new.csv"
    with open(p_new, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz", "beta1_rad_per_m", "beta2_rad_per_m",
                    "re_zl1_ohm", "im_zl1_ohm", "re_zl2_ohm", "im_zl2_ohm"])
        w.writerow([2.5e9, 90.0, 94.0, 49.9, 0.2, 35.1, -0.1])
    d2 = ws.read_port_beta_csv(p_new)
    assert d2["zl1"][0] == pytest.approx(49.9 + 0.2j)
    assert d2["zl2"][0] == pytest.approx(35.1 - 0.1j)


def test_wstep_render_exports_engine_zl_via_msl_cpw_unchanged():
    """wstep β 块落盘引擎 ZL（定案 (a)）；via/msl_cpw 分支文本不受影响。"""
    w = render_script("wstep", {"w1_mm": W1, "w2_mm": W2, "line_len_mm": L},
                      (2.25, 2.75))
    assert "_port1.ReadUIData(SIM_PATH, f)" in w and "_port2.ReadUIData(SIM_PATH, f)" in w
    assert "re_zl1_ohm" in w and "im_zl2_ohm" in w and "beta2_rad_per_m" in w
    # ZL 重读在 CalcPort 之后（uf_inc/uf_ref 已固化，S 列口径不变）
    assert w.index("_port1.CalcPort(SIM_PATH, f, ref_impedance=50)") < w.index("_port1.ReadUIData")
    compile(w, "sim_wstep_zl", "exec")
    v = render_script("via", TEMPLATE_NOMINAL["via"], (2.25, 2.75))
    assert "ReadUIData" not in v and "beta2_rad_per_m" in v
    m = render_script("msl_cpw", TEMPLATE_NOMINAL["msl_cpw"], (2.25, 2.75))
    assert "ReadUIData" not in m and "beta2_rad_per_m" in m
