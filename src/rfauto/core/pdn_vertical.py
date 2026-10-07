"""PK-2 垂直 PDN 叠层阻抗闭式内核（SB22-4b，2026-10-05 W4-D）。

2.5D/3D 堆叠 PDN 的层级串联模型：on-die → microbump 阵 → interposer
平面 → TGV 阵 → 封装基板平面 → BGA 阵 → PCB → VRM，各层 L/C 台阶产
分层反谐振峰（anti-resonance）。本模块提供：层等效模型（阵列折减电感
+ 平面平行板电容+腔模口径）、梯形级联阻抗谱、峰定位与逐峰归因、超标
峰的去耦建议（判读文本，不自动改设计——铁律 7）。

拓扑口径（预声明，与规格 §4b.2"每层 jωL∥(1/jωC) 台阶"简记的关系）
----------------------------------------------------------------
实现取**串 L/并 C 梯形网络**（Novak-Miller PDN 阶梯谱系）：每层一个
并联节点（平面对电容+挂点去耦）+ 一个串联支路（该层向下的垂直阵列
等效电感），最底层接到 vrm_model（core/pdn 复用）。取梯形而非"逐层
LC 并联台阶再串联"的原因（两条，均在 tests 钉）：

1. 退化恒等式（规格 §4b.3 判据 1）：只留一层（平面对 C+VRM 直挂、
   阵列电感=0）时梯形精确退化为 Z=C∥VRM——与 core/pdn.py 既有
   pdn_impedance_profile 同参逐位一致（1e-9）；逐层并联台阶再串联的
   读法给 (L∥C)+VRM，对任何参数都无法回收该恒等式。
2. 物理归属：垂直路径电感（bump/TGV/BGA 阵）本就位于相邻平面对之间
   （串联），平面对电容本就是并联节点——梯形是 2.5D PDN 文献的标准
   等效（Achkir 2017 IEEE TEMC 网格 PDN 阻抗闭式谱系；规格 §4b.1
   文献锚，量级带 [0.3,10] GHz 见规格 §4b.3 判据 4，1.6 GHz 量级锚
   出自 SB 报告三源检索）。

阵列折减（规格 §4b.2 条 1）：n_x×n_y 垂直阵列的等效电感按均匀分流
假设 L_eff=(1/N²)·ΣΣ Lmat_ij（Lmat 对角=rosa 单元自感、复用
core/package_interconnect.rosa_wire_self_inductance_h；非对角=精确
细丝互感闭式，与 package_interconnect.parallel_filament_mutual_exact_h
同式——向量化工作副本 _mutual_exact_vec，tests 对标量核抽样逐位钉+
Neumann 数值积分裁判交叉验证）。折减不是 1/N——含互感项
L_eff=L/N+(1−1/N)·<M>；规格首版"中心单元代表元"口径在 tests 作
交叉核对，全阵矩阵系向量化零成本增益（规格风险①的超集实现，边界
效应在全阵口径内显式进入）。适用域预声明：单元弱耦合（间距 ≥ 2 倍
直径）、均匀分流（边缘电流拥挤效应一阶忽略，规格风险①如实声明）。

平面电容：平行板 C=ε0·εr·A/d（边缘场忽略，偏差 O(d/√A) 如实）；
"腔修正"按规格口径=**validity 标注不修数**——lumped-C 口径仅在
f ≪ 第一腔模（plane_cavity_modes 同源筛查）成立，超域频点在输出里
逐层打 flag，不虚构修正项（铁律 7）。

峰归因（规格 §4b.3 判据 5）：第 k 层反谐振峰闭式估计
f_k=1/(2π√(C_k·L_k))（C_k=本层平面对电容、L_k=本层向下阵列电感；
层级尺度分离时逐峰一一归属），find_peaks 检出的实测峰配最近
log 频距的 f_k，标注层对自洽由 tests 独立重算对拍。

无源性与确定性：全链 L/C/R 无源 → Re(Z)≥0 全频（判据 3）；纯函数
零随机零全局状态，同输入逐位一致（判据 4 的前提）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import find_peaks

from rfauto.core.package_interconnect import rosa_wire_self_inductance_h
from rfauto.core.pdn import (
    MU0,
    VrmModel,
    _freq_array,
    _require_finite_nonneg,
    decap_impedance,
    plane_cavity_modes,
    vrm_model,
)

_EPS0 = 8.8541878128e-12  # F/m（CODATA 2018 真空介电常数；与 package_interconnect 同值口径）

#: 全阵互感矩阵元素数上限（N=n_x·n_y；O(N²) 对，防滥用）。
MAX_ARRAY_ELEMENTS = 4096


def _mutual_exact_vec(length_m: float, sep_m: np.ndarray) -> np.ndarray:
    """:func:`parallel_filament_mutual_exact_h` 同式向量化（间距>0 元素）。

    M=(μ0·l/2π)·[asinh(l/d)−√(1+(d/l)²)+d/l]。与标量核逐式同源；单源性
    由 tests 钉：抽样元素对本仓标量核（package_interconnect）逐位比对
    + 对 Neumann 数值积分裁判抽一对交叉验证。sep=0/负值不入本函数
    （对角自感由调用方回填）。
    """
    length = float(length_m)
    d = np.asarray(sep_m, dtype=float)
    x = length / d
    return MU0 * length / (2.0 * math.pi) * (
        np.arcsinh(x) - np.sqrt(1.0 + 1.0 / (x * x)) + 1.0 / x)


# ─── 层模型 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LayerSpec:
    """垂直 PDN 单层（一个并联节点+一个向下串联阵列）。

    Attributes:
        name: 层名（归因标注可读性；如 "on_die"/"interposer"/"pkg_substrate"）。
        c_plane_f: 本层平面对电容（F，正数；平行板口径见
            :func:`plane_pair_capacitance`，可直接给工程值）。
        l_array_h: 本层向下连到下一层的垂直阵列等效电感（H，非负；
            最底层到 VRM 的路径电感也记在此层）。0 = 本层与下层直挂
            （无垂直路径，退化恒等式用）。
        decaps: 挂在本层节点的去耦支路序列（每支路 (c_f, esr_ohm,
            esl_h[, mount_l_h]) 元组；口径与 core/pdn.decap_impedance
            一致）。缺省无。
        er: 平面对介质相对介电常数（provenance 记录；不重算 C——
            C 以 c_plane_f 为准单源）。
        f_cavity1_hz: 本层平面对第一腔模频率（Hz）——由
            :func:`plane_pair_capacitance` 同源产出后回填；缺省 inf=
            层几何未给、不虚构腔模界（lumped-C 超域 flag 不判）。
    """

    name: str
    c_plane_f: float
    l_array_h: float
    decaps: tuple[tuple[float, ...], ...] = ()
    er: float = 1.0
    f_cavity1_hz: float = math.inf


def plane_pair_capacitance(
    a_m: float, b_m: float, gap_m: float, er: float
) -> dict[str, Any]:
    """平面平行板电容 + 腔模口径标注（规格"平行板+腔修正"的诚实实现）。

    C=ε0·εr·a·b/d（边缘场忽略，偏差 O(d/√A) 量级如实声明，不引入
    未核修正系数）；第一腔模频率由 core/pdn.plane_cavity_modes 同源
    筛查（TM 闭式），lumped-C 口径仅在 f ≪ f_cavity1 成立——超域
    不修数，由调用方按 validity flag 如实处置（铁律 7）。

    Returns:
        {c_f, f_cavity1_hz, a_m, b_m, gap_m, er, scope_note}；建议把
        c_f 与 f_cavity1_hz 一起回填进 :class:`LayerSpec`（c_plane_f/
        f_cavity1_hz），使链级 cavity_flags 生效。
    """
    a = float(a_m)
    b = float(b_m)
    gap = float(gap_m)
    eps = float(er)
    if not math.isfinite(a) or a <= 0.0:
        raise ValueError(f"a_m 必须为正有限数，实际 {a_m!r}")
    if not math.isfinite(b) or b <= 0.0:
        raise ValueError(f"b_m 必须为正有限数，实际 {b_m!r}")
    if not math.isfinite(gap) or gap <= 0.0:
        raise ValueError(f"gap_m 必须为正有限数，实际 {gap_m!r}")
    if not math.isfinite(eps) or eps <= 0.0:
        raise ValueError(f"er 必须为正有限数，实际 {er!r}")
    c_f = _EPS0 * eps * a * b / gap
    modes = plane_cavity_modes(a, b, eps, 1, 0)
    f_cavity1_hz = modes[0].f_hz if modes else math.inf
    return {
        "c_f": c_f,
        "f_cavity1_hz": f_cavity1_hz,
        "a_m": a,
        "b_m": b,
        "gap_m": gap,
        "er": eps,
        "scope_note": "平行板精确（边缘场忽略 O(d/sqrt(A))）；lumped-C 口径"
        "限 f 远低于第一腔模（见 f_cavity1_hz），超域仅标注不修数",
    }


def array_equivalent_inductance(
    n_x: int,
    n_y: int,
    length_m: float,
    radius_m: float,
    pitch_x_m: float,
    pitch_y_m: float,
) -> dict[str, Any]:
    """垂直阵列（n_x×n_y 过孔/凸点/焊球）均匀分流等效电感（H）。

    L_eff=(1/N²)·ΣΣ Lmat_ij：对角=rosa 单元自感（l/r≥2 域，复用
    package_interconnect.rosa_wire_self_inductance_h），非对角=
    parallel_filament_mutual_exact_h 精确互感（矩形栅格欧氏间距）。
    M→0（间距拉大）时 L_eff→L/N；含互感项的折减慢于 1/N（tests 钉
    两端极限）。均匀分流假设（边缘电流拥挤一阶忽略）与单元弱耦合域
    （间距 ≥ 2 倍直径，低于显式拒绝）见模块 docstring 预声明。

    Returns:
        {l_eff_h, l_single_h, n_elements, reduction_factor,
        mutual_mean_h, method_note}
    """
    nx = int(n_x)
    ny = int(n_y)
    if nx < 1 or ny < 1:
        raise ValueError(f"n_x/n_y 必须 >=1，实际 ({n_x!r}, {n_y!r})")
    n = nx * ny
    if n > MAX_ARRAY_ELEMENTS:
        raise ValueError(
            f"阵列元素数 {n} 超上限 {MAX_ARRAY_ELEMENTS}（O(N^2) 互感对）")
    length = float(length_m)
    radius = float(radius_m)
    if not math.isfinite(length) or length <= 0.0:
        raise ValueError(f"length_m 必须为正有限数，实际 {length_m!r}")
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError(f"radius_m 必须为正有限数，实际 {radius_m!r}")
    px = float(pitch_x_m)
    py = float(pitch_y_m)
    for name, p in (("pitch_x_m", px), ("pitch_y_m", py)):
        if not math.isfinite(p) or p <= 0.0:
            raise ValueError(f"{name} 必须为正有限数，实际 {p!r}")
    min_sep = 2.0 * radius
    if min(px, py) < min_sep:
        raise ValueError(
            f"间距 {min(px, py):.3e} m 小于 2 倍半径 {min_sep:.3e} m："
            "细丝互感口径失效（阵列弱耦合域守卫）")
    l_single = rosa_wire_self_inductance_h(length, radius)

    xs = (np.arange(nx) - (nx - 1) / 2.0) * px
    ys = (np.arange(ny) - (ny - 1) / 2.0) * py
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    xg = gx.ravel()
    yg = gy.ravel()
    dx = xg[:, None] - xg[None, :]
    dy = yg[:, None] - yg[None, :]
    sep = np.sqrt(dx * dx + dy * dy)
    m_mat = np.full((n, n), np.nan)
    iu, ju = np.nonzero(sep > 0.0)
    m_mat[iu, ju] = _mutual_exact_vec(length, sep[iu, ju])
    np.fill_diagonal(m_mat, l_single)
    l_eff = float(m_mat.sum() / (n * n))
    off_diag = m_mat[~np.eye(n, dtype=bool)]
    return {
        "l_eff_h": l_eff,
        "l_single_h": l_single,
        "n_elements": n,
        "reduction_factor": l_eff / l_single,
        "mutual_mean_h": float(off_diag.mean()),
        "method_note": "全阵互感矩阵精确（均匀分流口径 L_eff=sum(Lmat)/N^2）；"
        "单元自感 rosa、互感 exact filament（复用 package_interconnect 原语）",
    }


# ─── 级联阻抗谱 ──────────────────────────────────────────────────────────────


def _branch_impedance_tuple(item: tuple[float, ...], freqs: np.ndarray) -> np.ndarray:
    """(c, esr, esl[, mount_l]) 元组 → 复阻抗（口径同 core/pdn._branch_impedance）。"""
    tup = tuple(float(x) for x in item)
    if len(tup) == 3:
        return decap_impedance(tup[0], tup[1], tup[2], 0.0, freqs)
    if len(tup) == 4:
        return decap_impedance(tup[0], tup[1], tup[2], tup[3], freqs)
    raise ValueError(
        f"去耦支路必须是 (c, esr, esl[, mount_l]) 三/四元组，实际长度 {len(tup)}")


def _parallel(z1: np.ndarray | complex, z2: np.ndarray | complex) -> np.ndarray:
    """两复阻抗并联（导纳求和口径；短路支配/双开路→inf 显式正确）。

    Z=0 → Y=∞（短路，并联结果取 0）；Z=∞ → Y=0（开路）；双开路 →
    Z=inf。复零除警告在函数内抑制（结果显式，非静默吞）。
    """
    a = np.asarray(z1, dtype=complex)
    b = np.asarray(z2, dtype=complex)
    with np.errstate(divide="ignore", invalid="ignore"):
        y1 = np.where(a == 0, np.inf + 0.0j, 1.0 / np.where(a == 0, 1.0, a))
        y2 = np.where(b == 0, np.inf + 0.0j, 1.0 / np.where(b == 0, 1.0, b))
        y = y1 + y2
        out = np.where(
            np.isinf(y), 0.0 + 0.0j,
            1.0 / np.where(np.isinf(y), 1.0, y))
    return out


def vertical_pdn_impedance(
    layers: Sequence[LayerSpec],
    vrm: VrmModel | None,
    f: float | Sequence[float] | np.ndarray,
) -> dict[str, Any]:
    """垂直叠层 PDN 输入阻抗谱（梯形级联：自顶层看入，纯 JSON 信封）。

    层序：layers[0]=最上层（负载侧，如 on-die），layers[-1]=最下层
    （如 PCB）。每层节点=平面对电容∥挂点去耦；串联支路=本层
    l_array_h 向下连到下一层；最底层之后接 vrm_model（None=理想源
    0Ω，docstring 预声明退化语义）。单层+l_array_h=0 时精确退化
    Z=C∥VRM（与 core/pdn.pdn_impedance_profile 同参逐位一致，判据 1）。

    Returns:
        {f_hz, z_complex, z_abs, z_real, n_layers, layer_details:
        [{name, c_plane_f, l_array_h, n_decaps, f_cavity1_hz, er}],
        cavity_flags: 逐频任一层 lumped-C 超域布尔数组, note}
    """
    if not layers:
        raise ValueError("layers 不能为空：垂直链至少一层（退化恒等式亦然）")
    freqs = _freq_array(f)
    omega = 2.0 * np.pi * freqs
    z_below = (
        vrm_model(freqs, vrm.r0, vrm.l0, vrm.r1, vrm.l1)
        if vrm is not None
        else np.zeros(freqs.shape, dtype=complex)
    )
    details: list[dict[str, Any]] = []
    cavity_over = np.zeros(freqs.shape, dtype=bool)
    for layer in reversed(layers):
        if not isinstance(layer, LayerSpec):
            raise TypeError(
                f"layers 元素须为 LayerSpec，实际 {type(layer).__name__}")
        c_val = float(layer.c_plane_f)
        if not math.isfinite(c_val) or c_val <= 0.0:
            raise ValueError(
                f"层 {layer.name!r} c_plane_f 必须为正有限数，实际 {c_val!r}")
        l_val = _require_finite_nonneg(
            f"层 {layer.name!r} l_array_h", layer.l_array_h)
        for dec in layer.decaps:
            if len(dec) not in (3, 4):
                raise ValueError(
                    f"层 {layer.name!r} 去耦支路长度非法：{len(dec)}")
            if float(dec[0]) <= 0.0:
                raise ValueError(f"层 {layer.name!r} 去耦电容必须为正数")
        f_c1 = float(layer.f_cavity1_hz)
        if not (math.isfinite(f_c1) and f_c1 > 0.0) and f_c1 != math.inf:
            raise ValueError(
                f"层 {layer.name!r} f_cavity1_hz 须为正有限数或 inf，"
                f"实际 {f_c1!r}")
        z_c = 1.0 / (1j * omega * c_val)
        z_node = z_c.copy()
        for dec in layer.decaps:
            z_node = _parallel(z_node, _branch_impedance_tuple(dec, freqs))
        z_series = 1j * omega * l_val + z_below
        z_below = _parallel(z_node, z_series)
        details.append(
            {"name": layer.name, "c_plane_f": c_val, "l_array_h": l_val,
             "n_decaps": len(layer.decaps), "f_cavity1_hz": f_c1,
             "er": float(layer.er)})
        if math.isfinite(f_c1):
            cavity_over |= freqs > f_c1
    details.reverse()
    return {
        "f_hz": freqs,
        "z_complex": z_below,
        "z_abs": np.abs(z_below),
        "z_real": np.real(z_below),
        "n_layers": len(layers),
        "layer_details": details,
        "cavity_flags": cavity_over,
        "note": "梯形级联（串 L 阵列/并 C 平面，模块 docstring 拓扑预声明）；"
        "层几何未给时 f_cavity1_hz=inf（不虚构腔模界），精确界走 "
        "plane_pair_capacitance",
    }


# ─── 峰定位与归因 ────────────────────────────────────────────────────────────


def _layer_pair_predictions(layers: Sequence[LayerSpec]) -> dict[str, float]:
    """逐层反谐振峰闭式估计 f_k=1/(2π√(C_k·L_k))（层对 C_k×L_k，判据 5 独立口径）。"""
    preds: dict[str, float] = {}
    for layer in layers:
        if layer.l_array_h > 0.0 and layer.c_plane_f > 0.0:
            preds[layer.name] = 1.0 / (
                2.0 * math.pi * math.sqrt(layer.c_plane_f * layer.l_array_h))
    return preds


def find_anti_resonance_peaks(
    f: float | Sequence[float] | np.ndarray,
    z_abs: np.ndarray | Sequence[float],
    layers: Sequence[LayerSpec],
    *,
    min_prominence_decade: float = 0.05,
) -> list[dict[str, Any]]:
    """log|Z| 峰定位 + 逐峰层对归因（最近 log 频距配 f_k，重复归属如实标）。

    Args:
        f: 频率（Hz，升序）。
        z_abs: |Z(f)|（Ω，与 f 同长，可含 inf）。
        layers: 与 :func:`vertical_pdn_impedance` 同层序（归因用 C_k/L_k）。
        min_prominence_decade: log10|Z| 峰 prominence 下限（decade，缺省 0.05
            ≈ 1.2 dB——过滤数值纹波）。

    Returns:
        [{f_peak_hz, z_peak_ohm, attributed_layer | None, f_pred_hz | None,
        attribution_note}]，按峰频升序。
    """
    freqs = _freq_array(f)
    za = np.asarray(z_abs, dtype=float)
    if za.shape != freqs.shape:
        raise ValueError(
            f"z_abs 形状 {za.shape} 与频率 {freqs.shape} 不一致")
    finite = np.isfinite(za) & (za > 0.0)
    log_z = np.full(za.shape, -np.inf)
    log_z[finite] = np.log10(za[finite])
    work = np.where(np.isfinite(log_z), log_z, log_z[finite].min() if finite.any() else 0.0)
    idx, _ = find_peaks(work, prominence=float(min_prominence_decade))
    preds = _layer_pair_predictions(layers)
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    for i in idx:
        f_peak = float(freqs[i])
        best_name: str | None = None
        best_pred: float | None = None
        best_dist = math.inf
        for name, f_pred in preds.items():
            if name in used:
                continue
            dist = abs(math.log10(f_peak) - math.log10(f_pred))
            if dist < best_dist:
                best_dist = dist
                best_name = name
                best_pred = f_pred
        if best_name is not None:
            used.add(best_name)
        out.append(
            {"f_peak_hz": f_peak,
             "z_peak_ohm": float(za[i]),
             "attributed_layer": best_name,
             "f_pred_hz": best_pred,
             "attribution_note": "最近 log 频距配层（f_k=1/(2pi*sqrt(C_k*L_k))）；"
             "配到的层不再复用（多峰同层如实落空）" if best_name is not None
             else "无可配层对预测（峰超出现有 C_k·L_k 覆盖域，如实标注）"})
    return out


# ─── 去耦建议（判读文本，不自动改设计）────────────────────────────────────────


def suggest_decaps_for_violations(
    layers: Sequence[LayerSpec],
    vrm: VrmModel | None,
    f: float | Sequence[float] | np.ndarray,
    z_target_ohm: float,
    candidates: Sequence[tuple[float, ...]],
    *,
    attach_layer: str | None = None,
) -> dict[str, Any]:
    """超标峰的去耦建议（贪心简化口径，纯判读输出不改设计——铁律 7）。

    流程：算 Z 谱 → 找 |Z|>z_target 峰 → 逐峰在归因层节点（或显式
    attach_layer）逐个试挂候选去耦支路，重算该峰频点 |Z|，按改善排序。

    Args:
        layers/vrm/f: 同 :func:`vertical_pdn_impedance`。
        z_target_ohm: 目标阻抗（Ω，正数；恒定口径，可先用
            core/pdn.target_impedance 由纹波/瞬态电流算出）。
        candidates: 候选去耦支路序列（(c, esr, esl[, mount_l]) 元组）。
        attach_layer: 显式挂点层名；None=逐峰用归因层（无归因峰落
            最上层）。

    Returns:
        {z_target_ohm, violations: [{f_peak_hz, z_peak_ohm, layer,
        suggestions: [{c_f, predicted_z_abs_ohm, improvement_ratio}]
        （升序，best 在前）}], note}
    """
    target = float(z_target_ohm)
    if not math.isfinite(target) or target <= 0.0:
        raise ValueError(f"z_target_ohm 必须为正有限数，实际 {z_target_ohm!r}")
    if not candidates:
        raise ValueError("candidates 不能为空（无候选不成建议）")
    freqs = _freq_array(f)
    base = vertical_pdn_impedance(layers, vrm, freqs)
    peaks = find_anti_resonance_peaks(freqs, base["z_abs"], layers)
    violations = [p for p in peaks if p["z_peak_ohm"] > target]
    out_v: list[dict[str, Any]] = []
    for peak in violations:
        layer_name = attach_layer or peak["attributed_layer"] or layers[0].name
        idx = next(
            (i for i, lay in enumerate(layers) if lay.name == layer_name), None)
        if idx is None:
            raise ValueError(f"挂点层名 {layer_name!r} 不在 layers 中")
        sugg: list[dict[str, Any]] = []
        for dec in candidates:
            patched = list(layers)
            lay = layers[idx]
            patched[idx] = LayerSpec(
                name=lay.name, c_plane_f=lay.c_plane_f,
                l_array_h=lay.l_array_h,
                decaps=(*tuple(lay.decaps), tuple(float(x) for x in dec)),
                er=lay.er)
            z_at = vertical_pdn_impedance(patched, vrm, peak["f_peak_hz"])
            z_abs_at = float(z_at["z_abs"][0])
            sugg.append(
                {"c_f": float(dec[0]),
                 "predicted_z_abs_ohm": z_abs_at,
                 "improvement_ratio": float(peak["z_peak_ohm"] / z_abs_at)
                 if z_abs_at > 0 else math.inf})
        sugg.sort(key=lambda s: s["predicted_z_abs_ohm"])
        out_v.append(
            {"f_peak_hz": peak["f_peak_hz"],
             "z_peak_ohm": peak["z_peak_ohm"],
             "layer": layer_name,
             "suggestions": sugg})
    return {
        "z_target_ohm": target,
        "violations": out_v,
        "note": "建议=判读文本不自动改设计（铁律 7）；单频点重算简化口径，"
        "未带宽带纹波复核——采纳前请对全带复跑 vertical_pdn_impedance",
    }


__all__ = [
    "MAX_ARRAY_ELEMENTS",
    "LayerSpec",
    "array_equivalent_inductance",
    "find_anti_resonance_peaks",
    "plane_pair_capacitance",
    "suggest_decaps_for_violations",
    "vertical_pdn_impedance",
]
