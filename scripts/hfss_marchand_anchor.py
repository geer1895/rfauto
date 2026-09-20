"""HFSS 波端口提取 Marchand 两节耦合段/slotline β 锚点（对齐基准口径）。

背景：电路级综合
（core/slotline_transitions.synthesize_marchand_two_section，名义点 50Ω→280Ω
差分、(Z0e,Z0o)=(95.21,36.49)Ω、(w,s,ℓ)=(1.7616,0.1016,18.4670)mm@h=1.524）
缺全波锚点。HFSS 是对齐基准，本脚本三个锚点：

(a) 耦合段锚：HFSS 四端口边耦合微带段（w,s,ℓ 同源导入，端口面=全截面
    **2 模大截面波端口**，#254 口径；模 1/模 2=偶/奇模，模序按 Z0 幅值
    识别——偶模 Z0 恒大）→ 由 50Ω 归一 S 反推 Z0e/Z0o/εeff_e/εeff_o
    （模态分组→每模均匀线段 Z 参数反演，纯函数+合成回收单测）。
    门（写死）：max(|Z0e/Z0e_KJ−1|,|Z0o/Z0o_KJ−1|)·100 @f0
    ≤5% AGREE / 5–15% PARTIAL / >15% DISAGREE；KJ 参考=圆整几何
    （nominal_params 0.0001mm）回代 coupled_microstrip_even_odd_ohm。
(b) 巴伦锚：完整两节 Marchand 巴伦 3 端口（P1=不平衡 50Ω 集总口、
    P2/P3=平衡侧两 140Ω 单端集总口），HFSS S 过 MARCHAND2_GATES 四门
    （带内 max|S11|≤−10dB / min|S21|·|S31|≥−3.5dB / 不平衡≤1dB /
    |Δφ−180°|≤10°）逐门判读，并与电路级理想 S
    （marchand_two_section_sparams 同几何回代）逐量差值。
(c) slotline β 锚（离线，零求解）：slotline_lumped 名义几何（w_slot=1.0mm
    @h=1.524）β 对 core/slotline 闭式与既有 HFSS 仲裁
    （runs/slotline_port_b/result.json，HFSS-wide
    66.767 rad/m）差值复现。

拓扑（(b) 物理布局 ↔ 电路级 marchand_two_section_sparams 端口约束，逐端
映射已核对）：节 1 主线近端=P1、主线远端→结点（物理=主线贯通）、副线近端
短路（PEC 过孔棒）、副线远端→平衡 A（140Ω 馈线+集总口）；节 2 主线近端=
结点、主线远端开路（微带开路端）、副线近端→平衡 B、副线远端短路。节 1/2
副线分居主线 ±y 侧，x 向级联（各占 ℓ）。

产物：runs/hfss_marchand_anchor/（hfss_marchand_anchor_{a,b}.aedt、
hfss_marchand_anchor_{a,b}.sNp + 同名 stem params JSON（数据集工作目录
导入器可归属，dump_curve_params）、verdict_{a,b,c}.json、
verdict_summary.json、console.log）。执行（工作区根目录）：
    .venv/Scripts/python.exe scripts/hfss_marchand_anchor.py --anchor all
判读纯函数全部可离线单测（tests/unit/test_hfss_marchand_anchor.py 合成
回收），不 import pyaedt。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import shutil
import threading
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs" / "hfss_marchand_anchor"
C0 = 299792458.0

# ── 预声明门（写死，跑后不许改；#122）──────────────────────────────────
GATE_AGREE_MAX_PCT = 5.0          # (a) ≤5% AGREE
GATE_PARTIAL_MAX_PCT = 15.0       # (a) 5–15% PARTIAL / >15% DISAGREE
F0_GHZ = 2.5
BAND_GHZ = (2.25, 2.75)           # f0±10%（与 MARCHAND2_GATES 同带）
SWEEP_GHZ = (2.0, 3.0)
SWEEP_NPTS = 101
MAX_DELTA_S = 0.02
MAX_PASSES = 12
MAX_PASSES_B = 20                 # (b) 首跑 12 步触顶 ΔS 0.039 未收敛（缝 0.1/馈 0.3mm）
SOLVE_TIMEOUT_S = 2400

# 大截面域尺寸（#254：波端口/域截面远大于微带惯例；微带准 TEM 场 ~3h 衰减，
# 横向 12mm≈8h 场 <1e-10；端口截面一阶高次模截止 >5GHz 不污染 2 模解）
A_LAT_MARGIN_MM = 12.0            # (a) 耦合对两侧横向垫
A_AIR_TOP_MM = 10.0               # (a) 金属面上空气 ≈6.5h
B_PAD_MM = 12.0                   # (b) 四周垫 ≈λ0/8 @2.5GHz（辐射边界）
B_AIR_TOP_MM = 15.0               # (b) 顶垫 ≈λ0/8
B_FEED_LEN_MM = 4.0               # (b) 平衡臂 140Ω 馈线长（差分相位相消）
B_SUB_MARGIN_MM = 3.0             # (b) 基板边沿超过馈线口的余量
VIA_SIDE_MM = 0.25                # (b) 短路过孔棒边长（电学 ≈0.02nH 可忽略）


# ═══════════════════════ 纯函数（离线可测，不 import pyaedt）══════════════════════

def s_to_z(s: np.ndarray, z_ref: float) -> np.ndarray:
    """实参考阻抗 S→Z：Z=Zr(I+S)(I−S)⁻¹（批 (…,n,n)。对角失配引起奇异时抛）。"""
    s = np.asarray(s, dtype=complex)
    n = s.shape[-1]
    eye = np.eye(n, dtype=complex)
    return float(z_ref) * (eye + s) @ np.linalg.inv(eye - s)


def mode_line_from_s2(freq_hz: np.ndarray, s2: np.ndarray, ell_m: float,
                      z_ref: float = 50.0) -> dict:
    """均匀线段 2 端口 S（z_ref 归一）→ 模阻抗 Z0/传播常数 γ/εeff（Z 参数法）。

    原理：TL 的 Z 参数 Z11=Z0·coth(γℓ)、Z12=Z0·csch(γℓ) ⇒
    γℓ = arccosh(Z11/Z12)（主值复 arccosh）、Z0 = Z12·sinh(γℓ)。
    有效域：0 < Im(γℓ) < π（ℓ < λ'/2；ℓ=λ'/4 设计点带内安全），越域
    ValueError 不外推（低损判 Im(γℓ)；有损时 Re(γℓ)>0 一并返回）。
    """
    freq_hz = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    s2 = np.asarray(s2, dtype=complex)
    if s2.ndim == 2:
        s2 = s2[None, ...]
    if s2.shape[-1] != 2 or s2.shape[0] != freq_hz.shape[0]:
        raise ValueError(f"mode_line_from_s2: 形状不符 {s2.shape} vs {freq_hz.shape}")
    z = s_to_z(s2, z_ref)
    ratio = z[:, 0, 0] / z[:, 0, 1]
    gl = np.arccosh(ratio.astype(complex))
    # 主值分支：ratio 近实（无耗）时 Im 噪声 ∓ε 使 Im(γℓ) 翻符号——统一取 β>0
    # 根（cosh 偶函数，conj 保 Re≥0 即 α≥0 无源方向）
    gl = np.where(np.imag(gl) < 0.0, np.conj(gl), gl)
    im = np.imag(gl)
    if np.any(im <= 1e-9) or np.any(im >= math.pi - 1e-9):
        raise ValueError(
            f"mode_line_from_s2: γℓ 越出 (0,π) 有效域（Im 范围 "
            f"[{im.min():.6g}, {im.max():.6g}]；线长须 < λ'/2）")
    # 单频无法判折叠（arccos 混叠固有）；扫频下 βℓ 须随 f 单调增，折叠
    # （ℓ≥λ'/2）呈锯齿非单调——显式报错不外推
    if im.shape[0] > 2 and np.any(np.diff(im) <= 0.0):
        raise ValueError(
            "mode_line_from_s2: Im(γℓ) 随频非单调，疑似 βℓ 折叠（ℓ ≥ λ'/2）越出有效域")
    gamma = gl / float(ell_m)                      # (nf,) 复传播常数
    z0 = z[:, 0, 1] * np.sinh(gl)
    beta = np.imag(gamma)
    eps_eff = (beta * C0 / (2.0 * np.pi * freq_hz)) ** 2
    return {"z0_ohm": z0, "gamma_rad_m": gamma, "beta_rad_m": beta,
            "eps_eff": eps_eff}


def detect_modal_order(s4_mid: np.ndarray) -> str:
    """多模端口 4×4 S 的端口序识别（@单频点）。

    "grouped"     = (A模1, A模2, B模1, B模2)：跨端传输在 (0,2)/(1,3)，
                    同端跨模耦合在 (0,1)/(2,3)（对称结构 ≈0）；
    "interleaved" = (A模1, B模1, A模2, B模2)：传输在 (0,1)/(2,3)，
                    跨模在 (0,2)/(1,3)。
    判据：比较两组"应为零"的跨模项幅值和。
    """
    grouped_cross = abs(s4_mid[1, 0]) + abs(s4_mid[3, 2])
    interleaved_cross = abs(s4_mid[2, 0]) + abs(s4_mid[3, 1])
    return "grouped" if grouped_cross <= interleaved_cross else "interleaved"


def s4_to_grouped(s4: np.ndarray, order: str) -> np.ndarray:
    """任意模序统一到 grouped (A模1,A模2,B模1,B模2)。"""
    s4 = np.asarray(s4, dtype=complex)
    if order == "grouped":
        return s4
    if order == "interleaved":
        idx = np.array([0, 2, 1, 3])
        return s4[:, idx][:, :, idx]
    raise ValueError(f"未知模序 {order!r}")


def coupled_anchor_from_s4(freq_hz: np.ndarray, s4: np.ndarray, ell_m: float,
                           z_ref: float = 50.0) -> dict:
    """2 模大截面波端口 4×4 S → (Z0e,Z0o,εeff_e,εeff_o) 反演（模态分组路线）。

    **模阻抗基准（HFSS Driven Modal 双导体端口模式约定，真机实证）**：端口
    模式覆盖两条导带，其模阻抗是**共模 Z_c=Z0e/2**（两线并联）与**差模
    Z_d=2·Z0o**，而非单线偶/奇模阻抗；50Ω 归一 S 反演得到的即 Z_c/Z_d，
    换算 Z0e=2·Z_c、Z0o=Z_d/2。此基准下 Z_c<Z_d（C<0.6 时），故**偶模按
    εeff 较高识别**（偶模场更集中于基板，边耦合微带恒 εeff_e>εeff_o），
    不按 Z0 大小。首跑按"Z0 大=偶"误判致伪 DISAGREE（Z0e −22%/Z0o +29%，
    与 εeff 配对自相矛盾），换算后 ±1.5% 内——保留原始模阻抗作证据。
    端口序自动识别；跨模残余与互易性（S−Sᵀ）作对称性诊断（不为门）。
    """
    freq_hz = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    s4 = np.asarray(s4, dtype=complex)
    if s4.ndim == 2:
        s4 = s4[None, ...]
    i0 = int(np.argmin(np.abs(freq_hz - F0_GHZ * 1e9)))
    order = detect_modal_order(s4[i0])
    g = s4_to_grouped(s4, order)
    se = g[:, [0, 2], :][:, :, [0, 2]]
    so = g[:, [1, 3], :][:, :, [1, 3]]
    m1 = mode_line_from_s2(freq_hz, se, ell_m, z_ref)
    m2 = mode_line_from_s2(freq_hz, so, ell_m, z_ref)
    swap = bool(m2["eps_eff"][i0] > m1["eps_eff"][i0])   # 偶模=εeff 高者
    even, odd = (m2, m1) if swap else (m1, m2)
    # 对称结构跨模残余（grouped 后应为 0 的 8 项）
    zero_mask = np.zeros((4, 4), dtype=bool)
    for i, j in ((0, 1), (1, 0), (2, 3), (3, 2), (0, 3), (3, 0), (1, 2), (2, 1)):
        zero_mask[i, j] = True
    cross_resid = float(np.max(np.abs(g[i0][zero_mask])))
    recip = float(np.max(np.abs(s4[i0] - np.transpose(s4[i0], (1, 0)))))
    return {"order": order, "swap": swap, "cross_mode_resid": cross_resid,
            "reciprocity_max_abs": recip,
            "z_common_ohm": even["z0_ohm"], "z_diff_ohm": odd["z0_ohm"],
            "z0e_ohm": 2.0 * even["z0_ohm"], "z0o_ohm": 0.5 * odd["z0_ohm"],
            "ere_e": even["eps_eff"], "ere_o": odd["eps_eff"],
            "beta_e_rad_m": even["beta_rad_m"], "beta_o_rad_m": odd["beta_rad_m"],
            "alpha_e_np_m": np.real(even["gamma_rad_m"]),
            "alpha_o_np_m": np.real(odd["gamma_rad_m"]),
            "basis": "HFSS 2-conductor port modes: Z_common=Z0e/2, Z_diff=2*Z0o; "
                     "even identified by higher eps_eff",
            "i0": i0}


def coupled_anchor_from_s4_std(freq_hz: np.ndarray, s4: np.ndarray,
                               ell_m: float, z_ref: float = 50.0) -> dict:
    """标准 4 端口反演（单线 1 模波端口 ×4，镜面对称分解，备选路线）。

    端口序 (线1近=0, 线2近=1, 线1远=2, 线2远=3)。偶模激励 a=(1,1,0,0)/√2 ⇒
    偶模 2 端口（近,远）S_e = [[S00+S01, S02+S03],[S20+S21, S22+S23]]，
    奇模 a=(1,−1,0,0)/√2 ⇒ S_o 同式取差。先做镜面对称化
    0.5·(S+S_mirror)（镜面=同端异线互换 0↔1、2↔3），反对称残量作诊断。
    """
    freq_hz = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    s4 = np.asarray(s4, dtype=complex)
    if s4.ndim == 2:
        s4 = s4[None, ...]
    i0 = int(np.argmin(np.abs(freq_hz - F0_GHZ * 1e9)))
    mir = s4[:, [1, 0, 3, 2], :][:, :, [1, 0, 3, 2]]
    sym = 0.5 * (s4 + mir)
    asym_resid = float(np.max(np.abs(s4[i0] - mir[i0])))
    nf = sym.shape[0]
    se = np.empty((nf, 2, 2), dtype=complex)
    so = np.empty((nf, 2, 2), dtype=complex)
    for r, base in enumerate((0, 2)):
        # 行 r=近端响应(线1近=0)/远端响应(线1远=2)；列=近端入射(0+1)/远端入射(2+3)
        se[:, r, 0] = sym[:, base, 0] + sym[:, base, 1]
        se[:, r, 1] = sym[:, base, 2] + sym[:, base, 3]
        so[:, r, 0] = sym[:, base, 0] - sym[:, base, 1]
        so[:, r, 1] = sym[:, base, 2] - sym[:, base, 3]
    ev = mode_line_from_s2(freq_hz, se, ell_m, z_ref)
    od = mode_line_from_s2(freq_hz, so, ell_m, z_ref)
    swap = bool(np.real(od["z0_ohm"][i0]) > np.real(ev["z0_ohm"][i0]))
    even, odd = (od, ev) if swap else (ev, od)
    return {"z0e_ohm": even["z0_ohm"], "z0o_ohm": odd["z0_ohm"],
            "ere_e": even["eps_eff"], "ere_o": odd["eps_eff"],
            "beta_e_rad_m": even["beta_rad_m"], "beta_o_rad_m": odd["beta_rad_m"],
            "swap": swap, "asym_resid": asym_resid, "i0": i0}


def verdict_of(rel_pct: float) -> str:
    """(a) 预声明门：≤5% AGREE / 5–15% PARTIAL / >15% DISAGREE。"""
    if rel_pct <= GATE_AGREE_MAX_PCT:
        return "AGREE"
    if rel_pct <= GATE_PARTIAL_MAX_PCT:
        return "PARTIAL"
    return "DISAGREE"


def design_context() -> dict:
    """名义设计点单源读取（禁手抄）+ 圆整几何 KJ 回代参考 + 电路级自检。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
    from rfauto.core.slotline_transitions import marchand_two_section_nominal

    d = marchand_two_section_nominal()
    nom = d.nominal_params()
    ze_r, zo_r, ere_r, ero_r = coupled_microstrip_even_odd_ohm(
        nom["w_mm"], nom["s_mm"], d.f0_ghz, d.er, d.h_mm)
    return {
        "f0_ghz": float(d.f0_ghz), "er": float(d.er), "h_mm": float(d.h_mm),
        "tan_d": 0.0037, "z_unbal_ohm": float(d.z_unbal_ohm),
        "z_bal_diff_ohm": float(d.z_bal_diff_ohm),
        "z_bal_se_ohm": float(d.z_bal_se_ohm),
        "w_mm": float(nom["w_mm"]), "s_mm": float(nom["s_mm"]),
        "l_sect_mm": float(nom["l_sect_mm"]),
        "w_feed_mm": float(nom["w_feed_mm"]),
        "w_bal_mm": float(nom["w_bal_line_mm"]),
        "r_bal_se_ohm": float(nom["r_bal_se_ohm"]),
        "kj_ref": {"z0e_ohm": float(ze_r), "z0o_ohm": float(zo_r),
                   "ere_e": float(ere_r), "ere_o": float(ero_r),
                   "caliber": "coupled_microstrip_even_odd_ohm @圆整几何(w,s)"},
        "design_ideal": {"z0e_ohm": float(d.z0e_ohm), "z0o_ohm": float(d.z0o_ohm),
                         "coupling_db": float(d.coupling_db),
                         "realizable": bool(d.realizable)},
        "circuit_self_check": d.model_metrics,
    }


def circuit_sparams_grid(ctx: dict, freq_hz: np.ndarray) -> np.ndarray:
    """与 HFSS 同频轴的电路级理想 3 端口 S（同圆整几何回代 Z0e/Z0o）。"""
    from rfauto.core.slotline_transitions import marchand_two_section_sparams

    return marchand_two_section_sparams(
        np.asarray(freq_hz, dtype=float) / 1e9, ctx["f0_ghz"],
        ctx["kj_ref"]["z0e_ohm"], ctx["kj_ref"]["z0o_ohm"],
        ctx["z_unbal_ohm"], ctx["r_bal_se_ohm"])


def compare_balun(hfss_metrics: dict, circuit_metrics: dict) -> dict:
    """(b) HFSS 门逐门判读 + 与电路级理想 S 的差值（dB/线性幅度 %）。"""
    gates = {k: bool(v) for k, v in hfss_metrics["gates"].items()}
    keys = ("s11_db_f0", "s21_db_f0", "s31_db_f0", "s23_db_f0",
            "band_max_s11_db", "band_min_s21_db", "band_min_s31_db",
            "band_max_abs_imbalance_db", "band_max_phase_error_deg",
            "phase_diff_deg_f0")
    diff = {}
    for k in keys:
        hv, cv = hfss_metrics[k], circuit_metrics[k]
        diff[k] = {"hfss": float(hv), "circuit": float(cv),
                   "delta": float(hv - cv)}
    # 线性幅度口径百分比（dB 差值不取百分比，附线性 |S| 比值）
    for k in ("s11_db_f0", "s21_db_f0", "s31_db_f0"):
        lin_h, lin_c = 10.0 ** (hfss_metrics[k] / 20.0), 10.0 ** (circuit_metrics[k] / 20.0)
        diff[k]["pct_linear"] = float((lin_h / lin_c - 1.0) * 100.0)
    return {"gates": gates, "all_gates_pass": all(gates.values()),
            "metrics_diff": diff}


# ═══════════════════════════════ HFSS 自动化 ═══════════════════════════════

def _mm(v: float) -> str:
    return f"{v:.9f}mm"


def _solve_with_watchdog(h, setup_name: str) -> tuple[float, bool]:
    """h.analyze 线程 + 超时 watchdog（#145 同口径；超时抛 RuntimeError）。"""
    box: dict = {"done": False, "err": None}

    def _go() -> None:
        try:
            h.analyze(setup="Setup")
            box["done"] = True
        except Exception as exc:
            box["err"] = repr(exc)

    t0 = time.time()
    th = threading.Thread(target=_go, daemon=True)
    th.start()
    th.join(timeout=SOLVE_TIMEOUT_S)
    solve_s = round(time.time() - t0, 1)
    if not box["done"]:
        raise RuntimeError(f"solve watchdog 超时（>{SOLVE_TIMEOUT_S}s）err={box['err']}")
    return solve_s, True


def _make_setup_and_sweep(h, max_passes: int = MAX_PASSES) -> str:
    setup = h.create_setup(name="Setup")
    setup.props["Frequency"] = f"{F0_GHZ!r}GHz"
    setup.props["MaxDeltaS"] = MAX_DELTA_S
    setup.props["MaximumPasses"] = int(max_passes)
    setup.update()
    h.create_linear_count_sweep(
        setup="Setup", unit="GHz", start_frequency=SWEEP_GHZ[0],
        stop_frequency=SWEEP_GHZ[1], num_of_freq_points=SWEEP_NPTS,
        name="Sweep", sweep_type="Interpolating", save_fields=False)
    return "Setup"


def _convergence(h) -> dict:
    from rfauto.adapters.hfss_adapter import HfssAdapter

    out: dict = {}
    with contextlib.suppress(Exception):
        setup = h.get_setup("Setup")
        if setup is not None:
            passes, ds = HfssAdapter._extract_convergence(setup)
            out = {"passes": passes, "final_delta_s": float(ds)}
    return out


def _export_s(h, tag: str, n_terminals: int) -> Path:
    """导出 Touchstone；多模波端口的终端数=Σ模数，适配器按端口边界数命名会
    把 4×4 模态数据写成 .s2p（skrf 只按扩展名推 rank，#248 反向）——按实际
    终端数改名。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter

    adapter = HfssAdapter()
    adapter.session.hfss = h
    got = Path(adapter.export_touchstone(OUT / f"hfss_marchand_anchor_{tag}.snp"))
    want = got.with_suffix(f".s{n_terminals}p")
    if got != want:
        if want.exists():
            want.unlink()
        got.replace(want)
        print(f"[{tag}] touchstone 改名 {got.name} → {want.name}（模态终端 {n_terminals}）",
              flush=True)
    return want


def _read_touchstone(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import skrf

    net = skrf.Network(str(path))
    return net.frequency.f.astype(float), np.asarray(net.s, dtype=complex)


def _modal_zo_best_effort(h, port_names: tuple[str, ...]) -> dict:
    """Modal Solution Data 的 Zo/Gamma（best-effort，#105 不拖垮主路径）。"""
    meta: dict = {"quantities": {}, "errors": []}
    data: dict = {pn: {} for pn in port_names}
    sol_name = "Setup : LastAdaptive"
    with contextlib.suppress(Exception):
        cats = h.post.available_quantities_categories(
            report_category="Modal Solution Data", solution=sol_name)
        wanted = [c for c in (cats or []) if any(k in c for k in ("Zo", "Gamma"))]
        meta["wanted_categories"] = wanted
        for cat in wanted:
            with contextlib.suppress(Exception):
                qs = list(h.post.available_report_quantities(
                    report_category="Modal Solution Data", solution=sol_name,
                    quantities_category=cat) or [])
                meta["quantities"][cat] = qs
                if not qs:
                    continue
                sol = h.post.get_solution_data(
                    expressions=qs, setup_sweep_name=sol_name,
                    report_category="Modal Solution Data")
                if sol is None:
                    continue
                for q in qs:
                    with contextlib.suppress(Exception):
                        _x, re_ = sol.get_expression_data(q, formula="real")
                        _x, im_ = sol.get_expression_data(q, formula="imag")
                        val = [float(np.asarray(re_).ravel()[0]),
                               float(np.asarray(im_).ravel()[0])]
                        for pn in port_names:
                            if pn in q:
                                data[pn][q] = val
    return {"data": data, "meta": meta}


# ── 锚 (a)：边耦合微带段 + 2 模大截面波端口 ──────────────────────────────

def build_anchor_a(h, ctx: dict) -> dict:
    w, s, ell = ctx["w_mm"], ctx["s_mm"], ctx["l_sect_mm"]
    h.modeler.model_units = "mm"
    mat = "rfauto_marchand_ro4350b"
    with contextlib.suppress(Exception):
        h.materials.add_material(mat, properties={
            "permittivity": ctx["er"], "dielectric_loss_tangent": ctx["tan_d"]})
    y_pair_half = 0.5 * (2.0 * w + s)              # 耦合对整体半宽
    y1 = y_pair_half + A_LAT_MARGIN_MM             # 域/端口半宽
    top = A_AIR_TOP_MM
    h.modeler.create_box(origin=["0mm", _mm(-y1), "0mm"],
                         sizes=[_mm(ell), _mm(2 * y1), _mm(ctx["h_mm"])],
                         name="Sub", material=mat)
    h.modeler.create_rectangle(
        orientation="XY", origin=["0mm", _mm(-y1), "0mm"],
        sizes=[_mm(ell), _mm(2 * y1)], name="Ground")
    # 两线沿 x∈[0,ℓ]，缝隙居中：线 1 y∈[-(w+s/2), -s/2]、线 2 y∈[s/2, w+s/2]
    h.modeler.create_rectangle(
        orientation="XY", origin=["0mm", _mm(-(w + 0.5 * s)), _mm(ctx["h_mm"])],
        sizes=[_mm(ell), _mm(w)], name="Trace1")
    h.modeler.create_rectangle(
        orientation="XY", origin=["0mm", _mm(0.5 * s), _mm(ctx["h_mm"])],
        sizes=[_mm(ell), _mm(w)], name="Trace2")
    h.assign_perfecte_to_sheets(assignment=["Ground", "Trace1", "Trace2"],
                                name="PECAll")
    h.modeler.create_box(origin=["0mm", _mm(-y1), _mm(ctx["h_mm"])],
                         sizes=[_mm(ell), _mm(2 * y1), _mm(top)],
                         name="Air", material="air")
    # 辐射边界：Air 顶面 + 两侧 y 墙（x 两端=端口面不辐射；底面=地）
    air_faces = h.modeler.get_object_faces("Air")
    open_faces = []
    for f in air_faces:
        _cx, cy, cz = h.modeler.get_face_center(f)
        is_top = abs(cz - (ctx["h_mm"] + top)) < 1e-3
        is_side = abs(abs(cy) - y1) < 1e-3
        if is_top or is_side:
            open_faces.append(f)
    if not open_faces:
        raise RuntimeError("锚(a)辐射面过滤为空：检查面心单位/域尺寸")
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")
    # 全截面 2 模大截面波端口（模 1/2=偶/奇准 TEM 对；跨模由对称性解耦）
    ports = {}
    y_t1 = -(w + 0.5 * s) * 0.5                     # 线 1 中心（积分线路径）
    for pname, x_edge in (("PA", 0.0), ("PB", ell)):
        sheet = f"{pname}sheet"
        h.modeler.create_rectangle(
            orientation="YZ", origin=[_mm(x_edge), _mm(-y1), "0mm"],
            sizes=[_mm(2 * y1), _mm(ctx["h_mm"] + top)], name=sheet)
        face = h.modeler.get_object_faces(sheet)[0]
        # pyaedt 多模积分线格式 = [起点列表(每模一个), 终点列表(每模一个)]
        # （首跑传 [line,line] 被解析成 模1 起点=终点 → "length of port lines
        # must be greater than zero"）；两模同用线 1 下方地→导带竖直路径
        start = [_mm(x_edge), _mm(y_t1), "0mm"]
        end = [_mm(x_edge), _mm(y_t1), _mm(ctx["h_mm"])]
        try:
            h.wave_port(assignment=face, name=pname, impedance=50.0,
                        renormalize=True, modes=2,
                        integration_line=[[start, start], [end, end]])
            how = "explicit_line"
        except Exception:
            h.wave_port(assignment=face, name=pname, impedance=50.0,
                        renormalize=True, modes=2)
            how = "auto_line"
        ports[pname] = {"sheet": sheet, "modes": 2, "integration_line": how}
    return {"y1_mm": y1, "top_mm": top, "ports": ports,
            "traces": ["Trace1", "Trace2"], "coupled_len_mm": ell}


def analyze_anchor_a(freq_hz: np.ndarray, s4: np.ndarray, ctx: dict,
                     build_info: dict, solve_info: dict) -> dict:
    ell_m = ctx["l_sect_mm"] * 1e-3
    res = coupled_anchor_from_s4(freq_hz, s4, ell_m)
    i0 = res["i0"]
    z0e = float(np.real(res["z0e_ohm"][i0]))
    z0o = float(np.real(res["z0o_ohm"][i0]))
    ere_e = float(res["ere_e"][i0])
    ere_o = float(res["ere_o"][i0])
    kj = ctx["kj_ref"]
    rel_e = (z0e / kj["z0e_ohm"] - 1.0) * 100.0
    rel_o = (z0o / kj["z0o_ohm"] - 1.0) * 100.0
    rel_ee = (ere_e / kj["ere_e"] - 1.0) * 100.0
    rel_eo = (ere_o / kj["ere_o"] - 1.0) * 100.0
    rel_pct = max(abs(rel_e), abs(rel_o))
    return {
        "anchor": "a",
        "title": "耦合段锚：2 模大截面波端口 S 反演 vs KJ 综合（名义点）",
        "gate": {"agree_max_pct": GATE_AGREE_MAX_PCT,
                 "partial_max_pct": GATE_PARTIAL_MAX_PCT,
                 "metric": "max(|Z0e/Z0e_KJ−1|,|Z0o/Z0o_KJ−1|)·100 @f0；"
                           "KJ=圆整几何回代（单一事实源）",
                 "rel_pct_max": rel_pct},
        "hfss": {"z0e_ohm_f0": z0e, "z0o_ohm_f0": z0o,
                 "ere_e_f0": ere_e, "ere_o_f0": ere_o,
                 "beta_e_rad_m_f0": float(res["beta_e_rad_m"][i0]),
                 "beta_o_rad_m_f0": float(res["beta_o_rad_m"][i0]),
                 "z0e_band_mean_ohm": float(np.mean(np.real(res["z0e_ohm"]))),
                 "z0o_band_mean_ohm": float(np.mean(np.real(res["z0o_ohm"]))),
                 "raw_mode_z_common_ohm_f0": float(np.real(res["z_common_ohm"][i0])),
                 "raw_mode_z_diff_ohm_f0": float(np.real(res["z_diff_ohm"][i0])),
                 "basis": res["basis"],
                 "mode_order": res["order"], "even_is_mode2": res["swap"],
                 "cross_mode_resid": res["cross_mode_resid"],
                 "reciprocity_max_abs_s_minus_sT": res["reciprocity_max_abs"]},
        "ref": {**kj, "design_ideal": ctx["design_ideal"],
                "kj_z_common_ohm": 0.5 * kj["z0e_ohm"],
                "kj_z_diff_ohm": 2.0 * kj["z0o_ohm"]},
        "rel_pct": {"z0e": rel_e, "z0o": rel_o, "ere_e": rel_ee,
                    "ere_o": rel_eo},
        "verdict": verdict_of(rel_pct),
        "build": build_info, "solve": solve_info,
        "declared_differences": [
            "端口面=全截面 2 模大截面波端口（横向 ±12mm/顶 10mm，一阶高次模"
            "截止 >5GHz），模 1/2=偶/奇准 TEM 对，偶模按 εeff 较高识别",
            "HFSS 双导体端口模阻抗基准=共模 Z0e/2 与差模 2·Z0o（真机实证，"
            "首跑按单线基准误判 DISAGREE 已纠正，原始模阻抗保留 raw_mode_*）",
            "S 为 50Ω 归一（renormalize=True）；反演纯函数含合成回收单测",
            "几何圆整 0.0001mm（nominal_params 口径）；介质 tanδ=0.0037 计入",
            "电路级 KJ 参考为二维准静态闭式，不含色散/端效应（均匀段无端头）",
        ],
    }


# ── 锚 (b)：完整两节 Marchand 巴伦 3 端口 ────────────────────────────────

def build_anchor_b(hh, ctx: dict) -> dict:
    from ansys.aedt.core.generic.constants import Gravity

    w, s, ell = ctx["w_mm"], ctx["s_mm"], ctx["l_sect_mm"]
    wb = ctx["w_bal_mm"]
    lf = B_FEED_LEN_MM
    h_min = ctx["h_mm"]
    hh.modeler.model_units = "mm"
    mat = "rfauto_marchand_ro4350b"
    with contextlib.suppress(Exception):
        hh.materials.add_material(mat, properties={
            "permittivity": ctx["er"], "dielectric_loss_tangent": ctx["tan_d"]})
    y_out = 2.0 * w + s                            # 副线外缘
    y0 = y_out + lf + B_SUB_MARGIN_MM              # 基板半宽
    x_tot = 2.0 * ell
    pad = B_PAD_MM
    hh.modeler.create_box(origin=[_mm(-pad), _mm(-y0), "0mm"],
                          sizes=[_mm(x_tot + 2 * pad), _mm(2 * y0), _mm(h_min)],
                          name="Sub", material=mat)
    hh.modeler.create_rectangle(
        orientation="XY", origin=[_mm(-pad), _mm(-y0), "0mm"],
        sizes=[_mm(x_tot + 2 * pad), _mm(2 * y0)], name="Ground")
    # 主线贯通 x∈[0,2ℓ]（节1远端↔节2近端=结点；节2远端=微带开路端）
    hh.modeler.create_rectangle(
        orientation="XY", origin=["0mm", "0mm", _mm(h_min)],
        sizes=[_mm(x_tot), _mm(w)], name="MainLine")
    # 节 1 副线（+y 侧）x∈[0,ℓ] + 平衡 A 馈线（+y 向 lf）。**馈线与副线面积
    # 重叠 w/2**：首跑馈线只沿边接触副线，pyaedt 报 "Union executed" 但 HFSS
    # 对仅共边的共面薄片不真正合并——FeedA/FeedB 仍为独立对象且不在 PEC
    # 表 → 馈线不导电 → 副线成短路-开路 λ/4 谐振器（|S11|≈−0.2dB 全反射）。
    ovl = 0.5 * w
    hh.modeler.create_rectangle(
        orientation="XY", origin=["0mm", _mm(w + s), _mm(h_min)],
        sizes=[_mm(ell), _mm(w)], name="SecLine1")
    hh.modeler.create_rectangle(
        orientation="XY", origin=[_mm(ell - wb), _mm(y_out - ovl), _mm(h_min)],
        sizes=[_mm(wb), _mm(lf + ovl)], name="FeedA")
    # 节 2 副线（−y 侧）x∈[ℓ,2ℓ]：主线占 y∈[0,w]，−y 侧副线须占 y∈[−(w+s), −s]
    # （间隙 s 贴主线底边）。run3 误写 y∈[−(2w+s), −(w+s)]（关于 y=0 而非主线
    # 中心镜像）→ 节 2 间隙 w+s=1.86mm 几乎不耦合（A/B 臂 −1/−12.7dB 伪失衡）。
    y_out2 = w + s                                 # 节 2 副线外缘 |y|
    hh.modeler.create_rectangle(
        orientation="XY", origin=[_mm(ell), _mm(-y_out2), _mm(h_min)],
        sizes=[_mm(ell), _mm(w)], name="SecLine2")
    hh.modeler.create_rectangle(
        orientation="XY", origin=[_mm(ell), _mm(-y_out2 - lf), _mm(h_min)],
        sizes=[_mm(wb), _mm(lf + ovl)], name="FeedB")
    hh.modeler.unite(["SecLine1", "FeedA"], keep_originals=False)
    hh.modeler.unite(["SecLine2", "FeedB"], keep_originals=False)
    # 合并后校验：仍存在的馈线对象一律并入 PEC 表（#212 连通性审计口径）
    existing = set(hh.modeler.object_names)
    conductors = [n for n in ("Ground", "MainLine", "SecLine1", "SecLine2",
                              "FeedA", "FeedB") if n in existing]
    unite_ok = ("FeedA" not in existing) and ("FeedB" not in existing)
    hh.assign_perfecte_to_sheets(assignment=conductors, name="PECAll")
    # 耦合间隙自审（#212）：两节副线到主线的缝必须都 = s
    bb_m = [float(v) for v in hh.modeler["MainLine"].bounding_box]
    bb_1 = [float(v) for v in hh.modeler["SecLine1"].bounding_box]
    bb_2 = [float(v) for v in hh.modeler["SecLine2"].bounding_box]
    gap1 = bb_1[1] - bb_m[4]
    gap2 = bb_m[1] - bb_2[4]
    if abs(gap1 - s) > 1e-3 or abs(gap2 - s) > 1e-3:
        raise RuntimeError(f"耦合间隙自审失败：gap1={gap1:.4f} gap2={gap2:.4f} 期望 s={s}")
    # 理想短路：PEC 过孔棒（节1副线近端 x=0、节2副线远端 x=2ℓ），从基板挖去
    # 消除实体重叠歧义
    via_names = []
    for name, x0 in (("Via1", 0.0), ("Via2", x_tot - VIA_SIDE_MM)):
        y_c = 1.5 * w + s if name == "Via1" else -(0.5 * w + s)
        hh.modeler.create_box(
            origin=[_mm(x0), _mm(y_c - 0.5 * VIA_SIDE_MM), "0mm"],
            sizes=[_mm(VIA_SIDE_MM), _mm(VIA_SIDE_MM), _mm(h_min)],
            name=name, material="pec")
        via_names.append(name)
    hh.modeler.subtract("Sub", via_names, keep_originals=True)
    # 空气域（顶垫）+ 辐射边界（顶+四侧墙；底面=地）
    top = B_AIR_TOP_MM
    hh.modeler.create_box(origin=[_mm(-pad), _mm(-y0), _mm(h_min)],
                          sizes=[_mm(x_tot + 2 * pad), _mm(2 * y0), _mm(top)],
                          name="Air", material="air")
    air_faces = hh.modeler.get_object_faces("Air")
    mid_x, half_x = 0.5 * x_tot, 0.5 * (x_tot + 2 * pad)
    open_faces = []
    for f in air_faces:
        cx, cy, cz = hh.modeler.get_face_center(f)
        is_top = abs(cz - (h_min + top)) < 1e-3
        is_side = (abs(abs(cx - mid_x) - half_x) < 1e-3
                   or abs(abs(cy) - y0) < 1e-3)
        if is_top or is_side:
            open_faces.append(f)
    if not open_faces:
        raise RuntimeError("锚(b)辐射面过滤为空：检查面心单位/域尺寸")
    hh.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")
    # P1 不平衡 50Ω（主线 x=0 端，竖片 z 0→h）；P2/P3 平衡 140Ω（馈线端）。
    # **HFSS 矩形 Width/Height 按法向轴循环映射**（轴 X→(Y,Z)、轴 Y→(Z,X)、
    # 轴 Z→(X,Y)），pyaedt sizes 直通不重排：XZ 薄片须写 sizes=[h(→Z), w(→X)]
    # （run2 写 [w,h] 得 0.3mm 高薄片悬在地面附近未触馈线，bbox 探测实证）。
    hh.modeler.create_rectangle(
        orientation="YZ", origin=["0mm", "0mm", "0mm"],
        sizes=[_mm(w), _mm(h_min)], name="P1sheet")
    hh.lumped_port(assignment="P1sheet", integration_line=Gravity.ZPos,
                   impedance=ctx["z_unbal_ohm"], name="P1", renormalize=True)
    hh.modeler.create_rectangle(
        orientation="XZ", origin=[_mm(ell - wb), _mm(y_out + lf), "0mm"],
        sizes=[_mm(h_min), _mm(wb)], name="P2sheet")
    hh.lumped_port(assignment="P2sheet", integration_line=Gravity.ZPos,
                   impedance=ctx["r_bal_se_ohm"], name="P2", renormalize=True)
    hh.modeler.create_rectangle(
        orientation="XZ", origin=[_mm(ell), _mm(-y_out2 - lf), "0mm"],
        sizes=[_mm(h_min), _mm(wb)], name="P3sheet")
    hh.lumped_port(assignment="P3sheet", integration_line=Gravity.ZPos,
                   impedance=ctx["r_bal_se_ohm"], name="P3", renormalize=True)
    # 构建期几何自审（#212）：端口薄片须 z∈[0,h] 且 x/y 跨度=导带宽，否则报错
    audit = {}
    expect = {"P1sheet": (0.0, 0.0, 0.0, w), "P2sheet": (ell - wb, ell, y_out + lf, y_out + lf),
              "P3sheet": (ell, ell + wb, -y_out2 - lf, -y_out2 - lf)}
    for name, (x0, x1, ya, yb) in expect.items():
        bb = [float(v) for v in hh.modeler[name].bounding_box]
        audit[name] = bb
        ok_z = abs(bb[2]) < 1e-3 and abs(bb[5] - h_min) < 1e-3
        ok_x = abs(bb[0] - x0) < 1e-3 and abs(bb[3] - x1) < 1e-3
        ok_y = abs(bb[1] - ya) < 1e-3 and abs(bb[4] - yb) < 1e-3
        if not (ok_z and ok_x and ok_y):
            raise RuntimeError(f"端口薄片几何自审失败 {name}: bbox={bb} 期望 x[{x0},{x1}] "
                               f"y[{ya},{yb}] z[0,{h_min}]")
    return {"y0_mm": y0, "x_tot_mm": x_tot, "pad_mm": pad, "top_mm": top,
            "feed_len_mm": lf, "via_side_mm": VIA_SIDE_MM,
            "n_ports": 3, "unite_ok": unite_ok, "pec_objects": conductors,
            "port_sheet_bbox_mm": audit,
            "port_map": {"P1": "不平衡 50Ω @主线 x=0",
                         "P2": f"平衡 A {ctx['r_bal_se_ohm']}Ω @节1副线远端馈线",
                         "P3": f"平衡 B {ctx['r_bal_se_ohm']}Ω @节2副线近端馈线"}}


def analyze_anchor_b(freq_hz: np.ndarray, s3: np.ndarray, ctx: dict,
                     build_info: dict, solve_info: dict) -> dict:
    from rfauto.core.slotline_transitions import marchand_two_section_metrics

    hfss_m = marchand_two_section_metrics(freq_hz, s3, BAND_GHZ)
    s_c = circuit_sparams_grid(ctx, freq_hz)
    circuit_m = marchand_two_section_metrics(freq_hz, s_c, BAND_GHZ)
    cmp = compare_balun(hfss_m, circuit_m)
    return {
        "anchor": "b",
        "title": "巴伦锚：完整两节 Marchand 3 端口 HFSS S vs 电路级理想 S",
        "gates_circuit_self_check": {
            "all_pass": bool(circuit_m["all_gates_pass"]),
            "metrics": {k: circuit_m[k] for k in (
                "band_max_s11_db", "band_min_s21_db", "band_min_s31_db",
                "band_max_abs_imbalance_db", "band_max_phase_error_deg")}},
        "hfss_metrics": {k: hfss_m[k] for k in (
            "s11_db_f0", "s21_db_f0", "s31_db_f0", "s23_db_f0",
            "phase_diff_deg_f0", "band_max_s11_db", "band_min_s21_db",
            "band_min_s31_db", "band_max_abs_imbalance_db",
            "band_max_phase_error_deg", "band_max_s23_db")},
        "gates": cmp["gates"],
        "all_gates_pass": cmp["all_gates_pass"],
        "verdict": "PASS" if cmp["all_gates_pass"] else "FAIL",
        "verdict_qualifier": (None if solve_info.get("converged")
                              else "UNCONVERGED（自适应未达 ΔS 门，判读仅供方向参考）"),
        "vs_circuit": cmp["metrics_diff"],
        "build": build_info, "solve": solve_info,
        "declared_differences": [
            "理想短路→PEC 过孔棒 0.25mm（≈0.02nH）；理想开路→微带开路端"
            "fringe（Δl≈0.6mm 量级，节长 3% 内）",
            f"平衡馈线 {B_FEED_LEN_MM}mm 140Ω 线附加相位（Δφ 差分相消；幅度门"
            "不含馈线损差异）",
            "结区/耦合段端效应/偶奇模相速差未建模于电路级（理想 TEM 耦合线）",
            "辐射边界顶/侧垫 ≈λ0/8 @2.5GHz（弱辐射接地结构）",
        ],
    }


# ── 锚 (c)：slotline β（离线，对拍既有 HFSS 仲裁）────────────────────────

def analyze_anchor_c() -> dict:
    from rfauto.core.slotline import slotline_closed_form

    src = REPO / "runs" / "slotline_port_b" / "result.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    w_mm = float(data["design"]["w_mm"])
    h_mm = float(data["design"]["h_mm"])
    er = float(data["design"]["er"])
    f0 = float(data["design"]["f0_ghz"])
    cf = slotline_closed_form(w_mm, h_mm, er, f0)
    lam0_m = C0 / (f0 * 1e9)
    beta_cf = 2.0 * math.pi / (cf.lambda_ratio * lam0_m)
    hfss_beta = float(data["hfss_reference"]["beta_gamma_rad_m_f0"])
    routeb_beta = float(data["variants"]["r_closed"]["beta_probe_rad_m_f0"])
    rec_hfss = float(data["hfss_reference"].get("beta_gamma_rad_m_f0", float("nan")))
    rec_vs_hfss = float(data["variants"]["r_closed"]["beta_vs_hfss_pct"])
    rec_vs_cf = float(data["variants"]["r_closed"]["beta_vs_cf_pct"])
    vs_hfss = (routeb_beta / hfss_beta - 1.0) * 100.0
    vs_cf = (routeb_beta / beta_cf - 1.0) * 100.0
    hfss_vs_cf = (hfss_beta / beta_cf - 1.0) * 100.0
    reproduced = (abs(vs_hfss - rec_vs_hfss) <= 0.05
                  and abs(vs_cf - rec_vs_cf) <= 0.05
                  and math.isfinite(rec_hfss))
    return {
        "anchor": "c",
        "title": "slotline β 锚（离线）：名义几何三方 β 差值复现",
        "geometry": {"w_slot_mm": w_mm, "h_mm": h_mm, "er": er, "f0_ghz": f0,
                     "template": "slotline_lumped 名义（meta.yaml nominal）"},
        "beta_rad_m": {"closed_form": beta_cf, "hfss_wide_gamma": hfss_beta,
                       "openems_route_b": routeb_beta,
                       "z0_closed_ohm": float(cf.z0_ohm),
                       "eps_eff_closed": float(cf.eps_eff)},
        "deltas_pct": {"hfss_vs_closed": hfss_vs_cf,
                       "routeb_vs_hfss": vs_hfss,
                       "routeb_vs_closed": vs_cf},
        "recorded_pct": {"routeb_vs_hfss": rec_vs_hfss,
                         "routeb_vs_closed": rec_vs_cf},
        "reproduced": reproduced,
        "verdict": "AGREE" if reproduced else "PARTIAL",
        "gate": {"metric": "重算差值与既有仲裁记录一致（≤0.05pp）且三方数字 "
                           "齐全 → AGREE；否则 PARTIAL（数据漂移如实）",
                 "source": str(src)},
        "declared_differences": [
            "零新求解：消费 runs/slotline_port_b/result.json（HFSS-wide "
            "β=Gamma 口径）+ core/slotline 闭式重算",
        ],
    }


# ═══════════════════════════════ 编排 ═══════════════════════════════

def _stale_project_clean(tag: str) -> None:
    for stale in OUT.glob(f"hfss_marchand_anchor_{tag}.aedt*"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)


def dump_curve_params(tag: str, snp: Path, ctx: dict) -> Path:
    """曲线同名 stem params JSON 落盘（import_workdir_runs 键路径契约 params）。

    runs/hfss_marchand_anchor/ 是**多曲线工作目录**（a/b 及历史 runN 变体
    共存于根级）——读取端按"同名 stem"归属（dataset_service.
    _resolve_workdir_params），另嵌 "curve" 显式引用双保险。字段=该锚实跑
    几何/材料/端口阻抗（design_context 单源圆整值，#320 不手抄）+ 锚标签。
    """
    from rfauto.service.dataset_service import write_workdir_params_json

    params = {k: ctx[k] for k in (
        "f0_ghz", "er", "tan_d", "h_mm", "w_mm", "s_mm", "l_sect_mm",
        "w_feed_mm", "w_bal_mm", "r_bal_se_ohm", "z_unbal_ohm",
        "z_bal_diff_ohm", "z_bal_se_ohm")}
    params["anchor"] = tag
    return write_workdir_params_json(OUT, params, curve=snp)


def run_anchor_hfss(tag: str) -> dict:
    ctx = design_context()
    project = OUT / f"hfss_marchand_anchor_{tag}.aedt"
    _stale_project_clean(tag)
    from ansys.aedt.core import Hfss

    t0 = time.time()
    hh = Hfss(project=str(project), design=f"marchand_anchor_{tag}",
              version="2025.1", non_graphical=True, new_desktop=True)
    try:
        build_info = build_anchor_a(hh, ctx) if tag == "a" else build_anchor_b(hh, ctx)
        t_build = round(time.time() - t0, 1)
        print(f"[{tag}] build done {t_build}s info={build_info.get('unite_ok', 'n/a')}",
              flush=True)
        max_passes = MAX_PASSES if tag == "a" else MAX_PASSES_B
        setup_name = _make_setup_and_sweep(hh, max_passes)
        solve_s, _ = _solve_with_watchdog(hh, setup_name)
        conv = _convergence(hh)
        solve_info = {"build_s": t_build, "solve_s": solve_s, **conv,
                      "max_delta_s": MAX_DELTA_S, "max_passes": max_passes,
                      "converged": bool(conv.get("final_delta_s", 1.0) <= MAX_DELTA_S)}
        print(f"[{tag}] solve done {solve_s}s conv={conv}", flush=True)
        # 求解元数据先落盘（后续导出/判读崩溃仍可 --reanalyze 抢救）
        (OUT / f"solve_{tag}.json").write_text(
            json.dumps({"solve": solve_info, "build": build_info},
                       ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        with contextlib.suppress(Exception):
            hh.save_project()
        snp = _export_s(hh, tag, 4 if tag == "a" else 3)
        dump_curve_params(tag, snp, ctx)
        freq_hz, smat = _read_touchstone(snp)
        modal = (_modal_zo_best_effort(hh, ("PA", "PB")) if tag == "a" else {})
        if tag == "a":
            res = analyze_anchor_a(freq_hz, smat, ctx, build_info, solve_info)
            res["modal_zo_best_effort"] = modal
        else:
            res = analyze_anchor_b(freq_hz, smat, ctx, build_info, solve_info)
        res["touchstone"] = str(snp)
        (OUT / f"verdict_{tag}.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        print(f"ANCHOR_{tag.upper()}_VERDICT_{res['verdict']}", flush=True)
        return res
    finally:
        with contextlib.suppress(Exception):
            hh.release_desktop(close_projects=True, close_desktop=True)


def dump_modal_zo(tag: str) -> dict:
    """重开已解项目（零求解）读 Modal Solution Data Zo/Gamma → modal_zo_{tag}.json。

    独立第二来源（#118）：核对 S 反演的模阻抗基准（共模 Z0e/2、差模 2·Z0o）
    与 εeff（Gamma→β）。best-effort，不影响 verdict。
    """
    from ansys.aedt.core import Hfss

    project = OUT / f"hfss_marchand_anchor_{tag}.aedt"
    if not project.exists():
        raise FileNotFoundError(f"dump_modal_zo: 缺 {project}")
    hh = Hfss(project=str(project), design=f"marchand_anchor_{tag}",
              version="2025.1", non_graphical=True, new_desktop=True)
    try:
        ports = ("PA", "PB") if tag == "a" else ("P1", "P2", "P3")
        out = _modal_zo_best_effort(hh, ports)
        (OUT / f"modal_zo_{tag}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"MODAL_ZO_{tag.upper()}_DUMPED n_quantities="
              f"{sum(len(v) for v in out['meta'].get('quantities', {}).values())}",
              flush=True)
        return out
    finally:
        with contextlib.suppress(Exception):
            hh.release_desktop(close_projects=True, close_desktop=True)


def reanalyze(tag: str) -> dict:
    """从既有 Touchstone + solve_{tag}.json 侧文件离线重判（抢救/复判口径）。"""
    ctx = design_context()
    n_t = 4 if tag == "a" else 3
    snp = OUT / f"hfss_marchand_anchor_{tag}.s{n_t}p"
    if not snp.exists():
        raise FileNotFoundError(f"reanalyze: 缺 {snp}")
    dump_curve_params(tag, snp, ctx)
    side = OUT / f"solve_{tag}.json"
    meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    freq_hz, smat = _read_touchstone(snp)
    solve_info = {**meta.get("solve", {}), "reanalyzed": True}
    build_info = meta.get("build", {})
    if tag == "a":
        res = analyze_anchor_a(freq_hz, smat, ctx, build_info, solve_info)
    else:
        res = analyze_anchor_b(freq_hz, smat, ctx, build_info, solve_info)
    res["touchstone"] = str(snp)
    (OUT / f"verdict_{tag}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"ANCHOR_{tag.upper()}_VERDICT_{res['verdict']}", flush=True)
    return res


def write_summary() -> dict:
    anchors: dict = {}
    rank = {"AGREE": 0, "PASS": 0, "PARTIAL": 1, "FAIL": 2, "DISAGREE": 2}
    for k in ("a", "b", "c"):
        p = OUT / f"verdict_{k}.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            anchors[k] = {"verdict": d["verdict"], "title": d["title"],
                          "gate_metric": d.get("gate", {}).get("metric", "")}
            if k == "a":
                anchors[k]["headline"] = {
                    "rel_pct": d["rel_pct"], "z0e_ohm": d["hfss"]["z0e_ohm_f0"],
                    "z0o_ohm": d["hfss"]["z0o_ohm_f0"], "kj_z0e": d["ref"]["z0e_ohm"],
                    "kj_z0o": d["ref"]["z0o_ohm"]}
            elif k == "b":
                hm = d["hfss_metrics"]
                anchors[k]["headline"] = {
                    "gates": d["gates"], "qualifier": d.get("verdict_qualifier"),
                    "band_max_s11_db": hm["band_max_s11_db"],
                    "band_min_s21_db": hm["band_min_s21_db"],
                    "band_min_s31_db": hm["band_min_s31_db"],
                    "band_max_abs_imbalance_db": hm["band_max_abs_imbalance_db"],
                    "band_max_phase_error_deg": hm["band_max_phase_error_deg"],
                    "distance_to_gate_db": {
                        "s21": hm["band_min_s21_db"] - (-3.5),
                        "s31": hm["band_min_s31_db"] - (-3.5),
                        "s11": (-10.0) - hm["band_max_s11_db"]}}
            elif k == "c":
                anchors[k]["headline"] = d["deltas_pct"]
    overall = "AGREE"
    if anchors:
        worst = max(rank.get(v["verdict"], 2) for v in anchors.values())
        overall = {0: "AGREE", 1: "PARTIAL", 2: "DISAGREE"}[worst]
    if len(anchors) < 3 and anchors:
        overall = ("PARTIAL" if rank.get(overall, 2) < 1 else overall)
    summary = {
        "item_id": "hfss_marchand_anchor",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "anchors": anchors,
        "overall": overall,
        "note": "HFSS=对齐基准；门写死于脚本常量（#122）",
    }
    (OUT / "verdict_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--anchor", choices=["a", "b", "c", "all"], default="all")
    ap.add_argument("--reanalyze", action="store_true",
                    help="不求解：从既有 Touchstone 离线重判（a/b）")
    ap.add_argument("--modal-zo", action="store_true",
                    help="不求解：重开已解项目读 Modal Solution Data Zo/Gamma")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.modal_zo:
        dump_modal_zo(args.anchor if args.anchor != "all" else "a")
        return 0
    which = ["c", "a", "b"] if args.anchor == "all" else [args.anchor]
    failed: list[str] = []
    for k in which:
        try:
            if k == "c":
                res = analyze_anchor_c()
                (OUT / "verdict_c.json").write_text(
                    json.dumps(res, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
                print(f"ANCHOR_C_VERDICT_{res['verdict']}", flush=True)
            elif args.reanalyze:
                reanalyze(k)
            else:
                run_anchor_hfss(k)
        except Exception as exc:
            print(f"ANCHOR_{k.upper()}_FAILED: {exc!r}", flush=True)
            failed.append(k)
    summary = write_summary()
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"RM_HFSS_ANCHOR_DONE failed={failed}", flush=True)
    return 1 if len(failed) == len(which) else 0


if __name__ == "__main__":
    raise SystemExit(main())
