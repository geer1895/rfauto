"""wstep 阶跃基元真机锚 pt3（定案 (a) 版）：双激励进程隔离 + 端接口径统一后按 50Ω 裁判重判。

背景：
- pt3_s22（#208 进程隔离版）：两次激励进程隔离，
  G1-G3 连续复现，新门 G4 幅度镜像 0.208 / G5 互易 0.072 失守 ⇒ FAIL；根因已
  闭式定位——openEMS 端口面贴 PML，非激励端的线由 PML 按线自身 Z0 端接，
  CalcPort(ref_impedance=50) 只是 50Ω 伪波分解，与 fake/skrf "50Ω 双端接"
  裁判本非同一 S 定义（engine_termination_model 逐点 0.033/0.029 为证）。
- 定案 (a)（本脚本落实）：裁判 50Ω 口径不动；引擎
  S 经 rfauto.adapters.openems_templates.renorm_engine_s_to_ref 后处理——
  ① 单激励 uf **带载比值**按列反演到各端口线自身 Z0 真波基
     （loaded_ratios_to_line_basis ≡ CalcPort(ref_impedance=Z_k) 代数恒等；
     非激励端在 50Ω 基下被 Γ=(Z−50)/(Z+50) 端接、a≠0，整矩阵 renormalize 是错的）；
  ② 线基内去嵌"测量面→线端"（wstep_deembed_lens_m 单源 2·(BOARD−L/2)/3=
     26.67mm；β 取引擎 port_beta.csv 金标准、α 取 HJ 一阶介质损耗=fake 同式）；
  ③ skrf renormalize 到 50Ω 参考 —— 与 fake `_wstep_sparams`（Pozar ABCD@50，
     seg_len=L/2）同定义同参考面（test_port_renormalize.py 合成钉 1e-12）。
  基两版：HJ 闭式 Z（forward_z0，裁判同源=G6 判据基）与引擎自算 ZL 中值
  （模板 β 块落盘的 sqrt(Et·dEt/(Ht·dHt))，引擎自洽基=G4/G5 判据基；
  HJ-vs-引擎 Z 偏差如实记录）。

流程：p1_exc = 模板原样（port1 excite=1）；p2_exc = 脚本级改写（excite 互换 +
footer 参考 `_port1.uf_inc`→`_port2.uf_inc`，幂等）；两 CSV 装配带载比值全矩阵
[r11,r12;r21,r22]（第 j 列=激励 j）→ 后处理 → 裁判。真机复跑默认**关闭全局
缓存**（extra_params cache=False；同脚本全文哈希会命中 pt3 缓存秒回且不落 CSV，
见 openems_solver._cache_key）。

门（PASS 需全过；#122 不凑绿）：
G1 分段 β 金标准 |Δεeff|≤2%（pt2/pt3 同门）；
G2 |S11| 单侧 ≤+3dB —— **处理后**（50Ω@线端）引擎 vs skrf 理想级联（同定义同面；
   pt2 "gap −4.9dB" 系口径差伪象，本版为真准确度门）；
G3 |S21| 额外损耗 ≤0.05（处理后 vs 理想）；
G4 幅度镜像 max_f ||S11|−|S22|| ≤0.01 —— **线基**（低耗互易二端口幺正性要求两侧
   反射幅度一致，在真波基内成立；50Ω 伪波基内因两端口线 Z0 不同本不镜像）；
   判据基=引擎 ZL 中值（自洽基；无 ZL 列时回退 HJ），HJ 基并列报告；
G5 互易 max_f ||S21|−|S12|| ≤0.01 —— 线基，同 G4 基；
G6 定案主门：处理后引擎（HJ 基，50Ω@线端）vs fake 裁判逐点 |Δ|S11||、|Δ|S22||
   ≤0.05（残差=HJ vs 引擎 Z0/β + 阶梯寄生 + 网格；G1 ±2% β 与 ~1% Z0 的闭式
   传播量级 0.01-0.03，0.05 留 2× 余量；d21 报告项）。
报告项：raw 口径（pt3 同法）的 d11/d22/镜像/互易与 engine_termination_model
对照——新旧口径逐点偏差并列留档。

产物 runs/wstep_smoke/<pt>/{p1_exc,p2_exc}/ + _smoke_result.json（默认 pt=
pt3_s22_renorm，pt3_s22 产物只增不删）。--analyze-only 复用既有 CSV 只重判。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.fake_adapter import _wstep_sparams
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import (
    renorm_engine_s_to_ref,
    tl_gamma_per_m,
    wstep_deembed_lens_m,
)
from rfauto.core.synthesis import Stackup, forward_z0

W1, W2, L = 1.1134, 1.897, 40.0
H_SUB, ER, F_MID = 0.508, 3.66, 2.5
MESH = 0.4  # 收敛档（pt2 同口径）
FREQ_RANGE = (1.5, 3.5)
BOARD_MM = 60.0  # 模板渲染 footer BOARD=60e-3（端口面=板边）
MIRROR_TOL = 0.01  # G4/G5：followUp④ 口径（线基重判）
JUDGE_TOL = 0.05   # G6：定案 (a) 同定义后引擎 vs fake 逐点幅度偏差
BAND_REL = 0.04    # β/ZL 中值窗 ±4%·F_MID（pt2 同法）

_PORT_HEAD = re.compile(r"^_port(\d) = MSLPort\(")


def swap_excitation(script: str, excite_port: int) -> str:
    """脚本级改写：两端口模板的 excite 切到 excite_port（另一端置 0）。

    只改顶层 `_portN = MSLPort(...)` 块内的 `excite=X`（按 port_nr 锚定）；
    footer 内缩进的 `_port3e` 副本不受影响。幂等（重复调用结果不变）。
    """
    out: list[str] = []
    cur: int | None = None
    for line in script.splitlines(keepends=True):
        m = _PORT_HEAD.match(line)
        if m:
            cur = int(m.group(1))
        if cur is not None:
            line = re.sub(r"excite=[01]",
                          f"excite={1 if cur == excite_port else 0}", line)
            if "priority=10)" in line:
                cur = None
        out.append(line)
    return "".join(out)


def swap_reference_port(script: str, excite_port: int) -> str:
    """footer 参考入射波切到激励端口：`_port1.uf_inc` → `_port{k}.uf_inc`。

    非激励端口的 uf_inc≈0，保留 port1 参考会得 0/0；切换后 CSV "S11" 列
    ≡ S_1k、"S21" 列 ≡ S_2k（k=2 时即 S12 / S22）。幂等。
    """
    return script.replace("_port1.uf_inc", f"_port{excite_port}.uf_inc")


def rewrite_for_port2(script: str) -> str:
    """p2_exc 完整改写 = excite 互换 + 参考端口切换（幂等）。"""
    return swap_reference_port(swap_excitation(script, 2), 2)


def read_sparams_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """读 5 列 sparams.csv → (f_hz, col_S11, col_S21)（复数）。"""
    data = np.loadtxt(str(path), delimiter=",", skiprows=1)
    return (data[:, 0], data[:, 1] + 1j * data[:, 2],
            data[:, 3] + 1j * data[:, 4])


def read_port_beta_csv(path: Path) -> dict[str, np.ndarray]:
    """读 port_beta.csv（header 驱动）：f_hz/beta1/beta2 + 可选 zl1/zl2（复数）。

    ZL 列（re/im_zl{1,2}_ohm）由 wstep 模板 β 块落盘（W2⑤ (a)，ReadUIData
    重读恢复的引擎自算线阻抗）；旧 run（pt3_s22）无该列 → 不含 zl 键。
    """
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = {
        "f_hz": np.array([float(r["freq_hz"]) for r in rows]),
        "beta1": np.array([float(r["beta1_rad_per_m"]) for r in rows]),
        "beta2": np.array([float(r["beta2_rad_per_m"]) for r in rows]),
    }
    if rows and "re_zl1_ohm" in rows[0]:
        for k in ("1", "2"):
            out[f"zl{k}"] = np.array(
                [float(r[f"re_zl{k}_ohm"]) + 1j * float(r[f"im_zl{k}_ohm"])
                 for r in rows])
    return out


def assemble_s_raw(s11: np.ndarray, s12: np.ndarray, s21: np.ndarray,
                   s22: np.ndarray) -> np.ndarray:
    """双激励两 CSV 装配带载比值全矩阵 (N,2,2)：第 j 列=激励 j（[r11,r12;r21,r22]）。"""
    s = np.empty((len(s11), 2, 2), dtype=complex)
    s[:, 0, 0], s[:, 0, 1], s[:, 1, 0], s[:, 1, 1] = s11, s12, s21, s22
    return s


def band_median(f_hz: np.ndarray, y: np.ndarray, f_mid_hz: float,
                rel: float = BAND_REL) -> float:
    """带中 ±rel 窗内中值（β/ZL 抗边带噪声，pt2 G1 同法）。"""
    sel = (f_hz >= (1 - rel) * f_mid_hz) & (f_hz <= (1 + rel) * f_mid_hz)
    return float(np.median(np.asarray(y, dtype=float)[sel]))


def process_engine(f_hz: np.ndarray, s_raw: np.ndarray, *, z_line: list[float],
                   beta1: np.ndarray, beta2: np.ndarray, eps_hj1: float,
                   eps_hj2: float, tan_d: float, line_len_mm: float,
                   board_mm: float = BOARD_MM) -> dict[str, object]:
    """定案 (a) 后处理胶水（wstep 专用，纯 numpy/skrf，离线可测）。

    返回 s_line（线基、去嵌到线端，G4/G5 判据面）、s_50（50Ω@线端，G2/G3/G6
    判据面）、lens_m。γ_k = α_HJ(εeff_k, tanδ) + j·β_engine_k（β 引擎金标准、
    α HJ 一阶损耗=fake 同式；α·l≈4e-3 Np 量级）。
    """
    lens = wstep_deembed_lens_m({"line_len_mm": line_len_mm}, board_mm=board_mm)
    gam = [np.real(tl_gamma_per_m(f_hz, eps_hj1, tan_d)) + 1j * np.asarray(beta1, float),
           np.real(tl_gamma_per_m(f_hz, eps_hj2, tan_d)) + 1j * np.asarray(beta2, float)]
    s_line = renorm_engine_s_to_ref(s_raw, z_line, 50.0, list(lens), gam,
                                    z_out_ohm=z_line)
    s_50 = renorm_engine_s_to_ref(s_raw, z_line, 50.0, list(lens), gam)
    return {"s_line": s_line, "s_50": s_50, "lens_m": lens}


def consistency_report(s_line: np.ndarray) -> dict[str, float]:
    """线基自洽量：幅度镜像 / 幅度互易 / 复数互易（G4/G5 数学，纯 numpy）。"""
    a = np.abs(s_line)
    return {
        "mirror_mag": float(np.max(np.abs(a[:, 0, 0] - a[:, 1, 1]))),
        "recip_mag": float(np.max(np.abs(a[:, 1, 0] - a[:, 0, 1]))),
        "recip_cplx": float(np.max(np.abs(s_line[:, 1, 0] - s_line[:, 0, 1]))),
        "s11_mag_min": float(a[:, 0, 0].min()), "s11_mag_max": float(a[:, 0, 0].max()),
        "s22_mag_min": float(a[:, 1, 1].min()), "s22_mag_max": float(a[:, 1, 1].max()),
    }


def judge_report(s_50: np.ndarray, s_fake: np.ndarray) -> dict[str, float]:
    """同定义（50Ω@线端）引擎 vs fake 逐点偏差（G6 数学，纯 numpy）。"""
    a, b = np.abs(s_50), np.abs(s_fake)
    return {
        "d11_mag": float(np.max(np.abs(a[:, 0, 0] - b[:, 0, 0]))),
        "d22_mag": float(np.max(np.abs(a[:, 1, 1] - b[:, 1, 1]))),
        "d21_mag": float(np.max(np.abs(a[:, 1, 0] - b[:, 1, 0]))),
        "d11_cplx": float(np.max(np.abs(s_50[:, 0, 0] - s_fake[:, 0, 0]))),
        "d22_cplx": float(np.max(np.abs(s_50[:, 1, 1] - s_fake[:, 1, 1]))),
        "s11_max_db": float(20 * np.log10(a[:, 0, 0].max() + 1e-12)),
        "s22_max_db": float(20 * np.log10(a[:, 1, 1].max() + 1e-12)),
        "s21_mag_mean": float(a[:, 1, 0].mean()),
    }


def per_port_report(s11_e: np.ndarray, s22_e: np.ndarray, s21_e: np.ndarray,
                    s12_e: np.ndarray, s_fake: np.ndarray) -> dict[str, float]:
    """按端口比对数学（纯 numpy，离线可测）——raw 口径（pt3 同法，留档对照）。

    返回：匹配/互换分配的幅度最大偏差、引擎与 fake 的幅度/复数镜像量、
    跨 run 互易残差。
    """
    a11, a22 = np.abs(s11_e), np.abs(s22_e)
    f11, f22 = np.abs(s_fake[:, 0, 0]), np.abs(s_fake[:, 1, 1])
    return {
        "d11_matched": float(np.max(np.abs(a11 - f11))),
        "d22_matched": float(np.max(np.abs(a22 - f22))),
        "d11_swapped": float(np.max(np.abs(a11 - f22))),
        "d22_swapped": float(np.max(np.abs(a22 - f11))),
        "mirror_mag_engine": float(np.max(np.abs(a11 - a22))),
        "mirror_mag_fake": float(np.max(np.abs(f11 - f22))),
        "mirror_cplx_engine": float(np.max(np.abs(s11_e - s22_e))),
        "mirror_cplx_fake": float(np.max(np.abs(s_fake[:, 0, 0] - s_fake[:, 1, 1]))),
        "recip_mag_engine": float(np.max(np.abs(np.abs(s21_e) - np.abs(s12_e)))),
        "d21_matched": float(np.max(np.abs(np.abs(s21_e) - np.abs(s_fake[:, 1, 0])))),
    }


def engine_termination_model(f_hz: np.ndarray, z1: float, z2: float, eps2: float,
                             l2_m: float, z_ref: float = 50.0) -> tuple[np.ndarray, np.ndarray]:
    """引擎单激励 raw 口径的闭式对照（无耗，确定性）——解释 raw |S11|≠|S22| 的端接差异。

    openEMS 端口面贴 PML：非激励端的线由 PML 以**自身特征阻抗**匹配端接（不是
    z_ref），而 CalcPort(ref_impedance=z_ref) 只是伪波分解；fake/skrf 裁判则把
    两端都端接 z_ref。于是：
    - S11_model（port1 激励）：port1 看入 = Z1=z_ref 匹配线 → 阶跃 → Z2 线被 PML
      按 Z2 端接 ⇒ |Γ| = |(Z2−Z1)/(Z2+Z1)| 恒定（W1 线只转相位）；
    - S22_model（port2 激励）：port2 测量面（距阶跃 l2）看入 = Z2 线负载为阶跃到
      Z1=z_ref 匹配线（=z_ref）⇒ Z_in = Z2·(z_ref + jZ2 tanβl)/(Z2 + j z_ref tanβl)，
      Γ = (Z_in−z_ref)/(Z_in+z_ref)（λ/4 处极值 |Γ|=|Z2²/z_ref−z_ref|/(Z2²/z_ref+z_ref)）。
    定案 (a) 后此模型仅作 raw 口径留档；判据面转到 process_engine 输出。
    """
    f = np.asarray(f_hz, dtype=float)
    g_step = (z2 - z1) / (z2 + z1)
    s11 = np.full_like(f, abs(g_step), dtype=float)
    beta = 2.0 * np.pi * f * np.sqrt(eps2) / 299792458.0
    t = np.tan(beta * l2_m)
    z_in = z2 * (z_ref + 1j * z2 * t) / (z2 + 1j * z_ref * t)
    s22 = np.abs((z_in - z_ref) / (z_in + z_ref))
    return s11, s22


def _solve(work: Path, rewrite=None, use_cache: bool = False) -> tuple[OpenEMSSolver, float]:
    extra: dict[str, object] = {"solve_timeout_s": 36000}
    if not use_cache:
        extra["cache"] = False  # 真机复跑：脚本全文哈希会命中 pt3 缓存秒回且不落 CSV
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=FREQ_RANGE,
        mesh_resolution_mm=MESH, extra_params=extra))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": "wstep",
                                  "params": {"w1_mm": W1, "w2_mm": W2,
                                             "line_len_mm": L}})
    script_path = work / "simulation.py"
    if rewrite is not None:
        script_path.write_text(rewrite(script_path.read_text(encoding="utf-8")),
                               encoding="utf-8")
    t0 = time.time()
    result = solver.solve()
    dt = time.time() - t0
    print(f"[{work.name}] solve_s={dt:.0f} success={result.success} "
          f"msg={result.message[:200]}", flush=True)
    assert result.success, f"openEMS 真跑失败: {result.message}"
    return solver, dt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pt", default="pt3_s22_renorm")
    parser.add_argument("--analyze-only", action="store_true",
                        help="不求解，复用 <pt>/{p1_exc,p2_exc} 既有 CSV 只重判")
    parser.add_argument("--use-cache", action="store_true",
                        help="允许 openems_cache 全局缓存命中（默认关闭=真机复跑）")
    args = parser.parse_args(argv)

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    z1, eps_hj1 = forward_z0(W1, F_MID, stackup)
    z2, eps_hj2 = forward_z0(W2, F_MID, stackup)
    tan_d = float(stackup.loss_tangent or 0.0037)

    root = Path(f"runs/wstep_smoke/{args.pt}")
    if args.analyze_only:
        t_p1 = t_p2 = 0.0
    else:
        _, t_p1 = _solve(root / "p1_exc", use_cache=args.use_cache)
        _, t_p2 = _solve(root / "p2_exc", rewrite=rewrite_for_port2,
                         use_cache=args.use_cache)

    f_hz, r11, r21 = read_sparams_csv(root / "p1_exc" / "sparams.csv")
    f2_hz, r12, r22 = read_sparams_csv(root / "p2_exc" / "sparams.csv")
    assert np.allclose(f_hz, f2_hz), "两次激励频率轴不一致"
    f_ghz = f_hz / 1e9
    s_raw = assemble_s_raw(r11, r12, r21, r22)
    pb = read_port_beta_csv(root / "p1_exc" / "port_beta.csv")
    assert np.allclose(pb["f_hz"], f_hz), "port_beta 频率轴不一致"

    # ── 裁判：fake（2d68012，HJ 同源）+ pt2 skrf 级联理想（连续性）──
    s_fake = _wstep_sparams(f_ghz, eps_eff1=eps_hj1, eps_eff2=eps_hj2,
                            z1=z1, z2=z2, seg_len_mm=L / 2, tan_d=tan_d)
    import skrf

    freq = skrf.Frequency.from_f(f_hz, unit="Hz")
    m1 = skrf.media.MLine(frequency=freq, w=W1 * 1e-3, h=H_SUB * 1e-3, ep_r=ER)
    m2 = skrf.media.MLine(frequency=freq, w=W2 * 1e-3, h=H_SUB * 1e-3, ep_r=ER)
    ideal = m1.line(L / 2, unit="mm") ** m2.line(L / 2, unit="mm")
    ideal.renormalize([50.0, 50.0])

    # G1 分段 β 金标准（pt2 同法：带中 ±4% 中值）
    f_mid_hz = F_MID * 1e9
    eps = {}
    for name, beta in (("eps_eff1", pb["beta1"]), ("eps_eff2", pb["beta2"])):
        b_med = band_median(f_hz, beta, f_mid_hz)
        eps[name] = (b_med * 299792458.0 / (2 * np.pi * f_mid_hz)) ** 2
    d1 = (eps["eps_eff1"] / eps_hj1 - 1) * 100
    d2 = (eps["eps_eff2"] / eps_hj2 - 1) * 100

    # ── 定案 (a) 后处理：HJ 基（裁判同源）+ 引擎 ZL 中值基（自洽）──
    common = dict(beta1=pb["beta1"], beta2=pb["beta2"], eps_hj1=eps_hj1,
                  eps_hj2=eps_hj2, tan_d=tan_d, line_len_mm=L)
    proc_hj = process_engine(f_hz, s_raw, z_line=[z1, z2], **common)
    cons_hj = consistency_report(proc_hj["s_line"])
    judge_hj = judge_report(proc_hj["s_50"], s_fake)
    zl_info: dict[str, object] = {"available": False}
    proc_zl = cons_zl = judge_zl = None
    if "zl1" in pb:
        zl_med = [band_median(f_hz, np.real(pb["zl1"]), f_mid_hz),
                  band_median(f_hz, np.real(pb["zl2"]), f_mid_hz)]
        zl_info = {
            "available": True, "zl_median_ohm": zl_med,
            "zl_vs_hj_pct": [(zl_med[0] / z1 - 1) * 100, (zl_med[1] / z2 - 1) * 100],
            "zl_imag_median_ohm": [band_median(f_hz, np.imag(pb["zl1"]), f_mid_hz),
                                   band_median(f_hz, np.imag(pb["zl2"]), f_mid_hz)],
        }
        proc_zl = process_engine(f_hz, s_raw, z_line=zl_med, **common)
        cons_zl = consistency_report(proc_zl["s_line"])
        judge_zl = judge_report(proc_zl["s_50"], s_fake)
    # G4/G5 判据基：引擎 ZL（自洽）优先，无则 HJ
    cons_gate = cons_zl if cons_zl is not None else cons_hj
    gate_basis = "engine_zl_median" if cons_zl is not None else "hj"

    # G2/G3（处理后 HJ 基 50Ω@线端 vs 理想，同定义同面）
    s50 = proc_hj["s_50"]
    m11_eng = 20 * np.log10(np.abs(s50[:, 0, 0]) + 1e-12)
    m11_ideal = 20 * np.log10(np.abs(ideal.s[:, 0, 0]) + 1e-12)
    s11_gap = float(np.max(m11_eng) - np.max(m11_ideal))
    mag_eng = float(np.mean(np.abs(s50[:, 1, 0])))
    mag_ideal = float(np.mean(np.abs(ideal.s[:, 0, 1])))

    # raw 口径留档（pt3 同法）：per_port_report + engine_termination_model + raw gap
    rep_raw = per_port_report(r11, r22, r21, r12, s_fake)
    m11_raw = 20 * np.log10(np.abs(r11) + 1e-12)
    s11_gap_raw = float(np.max(m11_raw) - np.max(m11_ideal))
    l2_m = (BOARD_MM - (BOARD_MM - L / 2) / 3) * 1e-3   # 测量面距阶跃（raw 模型）
    s11_m, s22_m = engine_termination_model(f_hz, z1, z2, eps_hj2, l2_m)
    term = {
        "l2_measplane_to_step_mm": l2_m * 1e3,
        "gamma_step_db": float(20 * np.log10(abs((z2 - z1) / (z2 + z1)))),
        "transformer_max_db": float(20 * np.log10(abs(z2 * z2 / 50.0 - 50.0) / (z2 * z2 / 50.0 + 50.0))),
        "d11_engine_vs_model": float(np.max(np.abs(np.abs(r11) - s11_m))),
        "d22_engine_vs_model": float(np.max(np.abs(np.abs(r22) - s22_m))),
    }

    gates = {
        "G1_beta_seg1_pct": {"value": d1, "limit": 2.0, "ok": abs(d1) <= 2.0},
        "G1_beta_seg2_pct": {"value": d2, "limit": 2.0, "ok": abs(d2) <= 2.0},
        "G2_s11_gap_db": {"value": s11_gap, "limit": 3.0, "ok": s11_gap <= 3.0,
                          "basis": "processed_hj_50ohm_at_line_end"},
        "G3_s21_mag_mean": {"value": mag_eng, "floor": mag_ideal - 0.05,
                            "ok": mag_eng >= mag_ideal - 0.05,
                            "basis": "processed_hj_50ohm_at_line_end"},
        "G4_mirror_mag_line": {"value": cons_gate["mirror_mag"], "limit": MIRROR_TOL,
                               "ok": cons_gate["mirror_mag"] <= MIRROR_TOL,
                               "basis": gate_basis},
        "G5_recip_mag_line": {"value": cons_gate["recip_mag"], "limit": MIRROR_TOL,
                              "ok": cons_gate["recip_mag"] <= MIRROR_TOL,
                              "basis": gate_basis},
        "G6_d11_vs_fake": {"value": judge_hj["d11_mag"], "limit": JUDGE_TOL,
                           "ok": judge_hj["d11_mag"] <= JUDGE_TOL, "basis": "hj"},
        "G6_d22_vs_fake": {"value": judge_hj["d22_mag"], "limit": JUDGE_TOL,
                           "ok": judge_hj["d22_mag"] <= JUDGE_TOL, "basis": "hj"},
    }
    ok = all(g["ok"] for g in gates.values())
    verdict = "PASS" if ok else "FAIL"

    r5 = lambda d: {k: (round(v, 5) if isinstance(v, float) else v) for k, v in d.items()}  # noqa: E731
    print(f"eps_hj: seg1={eps_hj1:.4f} seg2={eps_hj2:.4f} | engine(beta): "
          f"seg1={eps['eps_eff1']:.4f} ({d1:+.2f}%) seg2={eps['eps_eff2']:.4f} ({d2:+.2f}%)")
    print(f"z_hj=[{z1:.3f},{z2:.3f}] zl_engine={zl_info}")
    print(f"[processed hj] |S11|max eng={judge_hj['s11_max_db']:.2f}dB fake="
          f"{20 * np.log10(np.abs(s_fake[:, 0, 0]).max()):.2f}dB ideal={np.max(m11_ideal):.2f}dB "
          f"gap={s11_gap:+.2f}dB (raw gap {s11_gap_raw:+.2f}) | |S22|max eng="
          f"{judge_hj['s22_max_db']:.2f} fake={20 * np.log10(np.abs(s_fake[:, 1, 1]).max()):.2f}")
    print(f"s21_mag_mean eng={mag_eng:.4f} fake={np.abs(s_fake[:, 1, 0]).mean():.4f} "
          f"ideal={mag_ideal:.4f}")
    print("consistency line-basis hj :", json.dumps(r5(cons_hj)))
    if cons_zl is not None:
        print("consistency line-basis zl :", json.dumps(r5(cons_zl)))
    print("judge hj (50Ω@line-end vs fake):", json.dumps(r5(judge_hj)))
    if judge_zl is not None:
        print("judge zl (50Ω@line-end vs fake):", json.dumps(r5(judge_zl)))
    print("raw legacy per-port:", json.dumps(r5(rep_raw)))
    print("raw engine-termination model:", json.dumps(r5(term)))
    print(f"WSTEP_S22_PROBE_{verdict}（G1 β±2% / G2 |S11|≤+3dB / G3 |S21| 损耗≤0.05 / "
          f"G4 线基镜像≤{MIRROR_TOL} / G5 线基互易≤{MIRROR_TOL} / G6 vs fake≤{JUDGE_TOL}；"
          f"G4/G5 基={gate_basis}）", flush=True)

    result = {
        "item": "openems-real-smoke-bundle/①wstep_s22 (W2⑤ 定案 (a) 重判)",
        "verdict": verdict, "pt": args.pt, "mesh_mm": MESH,
        "freq_range_ghz": list(FREQ_RANGE), "analyze_only": bool(args.analyze_only),
        "params": {"w1_mm": W1, "w2_mm": W2, "line_len_mm": L,
                   "z1_hj_ohm": z1, "z2_hj_ohm": z2,
                   "eps_hj1": eps_hj1, "eps_hj2": eps_hj2, "tan_d": tan_d},
        "solve_s": {"p1_exc": round(t_p1, 1), "p2_exc": round(t_p2, 1),
                    "cache": bool(args.use_cache)},
        "decision": {
            "choice": "(a) 引擎侧后处理统一到 50Ω 参考，裁判定义不动",
            "helper": "rfauto.adapters.openems_templates.renorm_engine_s_to_ref",
            "chain": ["loaded_ratios_to_line_basis（按列反演≡CalcPort ref=Z_k）",
                      "线基去嵌 测量面→线端 e^{+γl}（β 引擎/α HJ）",
                      "skrf renormalize_s traveling → 50Ω"],
            "deembed_lens_mm": [v * 1e3 for v in proc_hj["lens_m"]],
            "engine_zl": zl_info,
        },
        "engine": {"eps_eff1": eps["eps_eff1"], "eps_eff2": eps["eps_eff2"],
                   "raw_s11_max_db": float(np.max(m11_raw)),
                   "raw_s22_max_db": float(20 * np.log10(np.abs(r22).max() + 1e-12)),
                   "raw_s21_mag_mean": float(np.mean(np.abs(r21)))},
        "processed": {
            "hj": {"consistency_line": cons_hj, "judge_vs_fake": judge_hj},
            "engine_zl": ({"consistency_line": cons_zl, "judge_vs_fake": judge_zl}
                          if cons_zl is not None else None),
        },
        "judge": {"fake": "fake_adapter._wstep_sparams@2d68012（M1@M2 + Pozar T4.2，HJ 同源）",
                  "ideal_s11_max_db": float(np.max(m11_ideal)),
                  "fake_s11_max_db": float(20 * np.log10(np.abs(s_fake[:, 0, 0]).max())),
                  "fake_s22_max_db": float(20 * np.log10(np.abs(s_fake[:, 1, 1]).max())),
                  "fake_s21_mag_mean": float(np.abs(s_fake[:, 1, 0]).mean()),
                  "ideal_s21_mag_mean": mag_ideal},
        "raw_legacy": {"per_port": rep_raw, "engine_termination_model": term,
                       "s11_gap_db_raw": s11_gap_raw,
                       "pt3_s22_reference": {"G4_mirror": 0.208, "G5_recip": 0.072,
                                             "d11_matched": 0.171, "d22_matched": 0.305,
                                             "solve_s": [428, 425], "verdict": "FAIL"}},
        "gates": gates,
        "pt2_reference": {"solve_s": 156, "beta_pct": [0.87, 1.31],
                          "s11_gap_db": -4.9, "verdict": "WSTEP_PROBE_PASS",
                          "note": "gap −4.9dB 系 raw 端接口径差伪象（定案 (a) 重解读）"},
        "notes": [
            "定案 (a)：引擎单激励 uf 比值是带载比值（非激励端 50Ω 基下被 Γ=(Z−50)/(Z+50) "
            "端接），按列反演到线自身 Z0 基后 PML 端接=匹配，去嵌到线端再 renormalize 50Ω "
            "即与 fake（Pozar ABCD@50，seg=L/2）同定义同面；整矩阵 renormalize 是错的（合成"
            "误差=|Γ_step|）",
            "G4/G5 判据面=线基（真波基内幺正性 ⇒ |S11|=|S22|、S21=S12）；基取引擎自算 ZL "
            "中值（自洽，HJ-vs-引擎 Z 偏差另记），无 ZL 列时回退 HJ",
            "G6 残差=HJ vs 引擎 Z0/β + 阶梯寄生 + 网格（锚判据本来要测的量）",
            "复数域仅作参考：uf_ref/uf_inc 相位含端口分解伪象（#161）",
        ],
    }
    # 产物只增不删：--analyze-only 是对既有 run 的重判，不覆盖其原始 _smoke_result.json
    out_name = ("_smoke_result_reanalysis.json" if args.analyze_only
                else "_smoke_result.json")
    (root / out_name).write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
