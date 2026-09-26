"""DP-4 P2：阵列两档方向图服务层（快速档编排；互耦档接口预留）。

职责（分层铁律：服务层 JSON 进出，CLI/MCP 薄壳；数值只在
确定性内核——全部物理数字来自 core/array_synthesis.py（零改动复用）与
core/array_scan.py 纯函数，本模块只做参数校验、布局/激励构建与结果装配）：

- array_pattern(request)：单扫描角方向图 → {tier, weights, excitations,
  cuts, SLL/HPBW/Dmax, Γ_act, Z_scan, blind_spot, gates}。两档路由：
  * 快速档 = 孤立单元方向图 × AF（复域逐点乘）+ Dmax_fast =
    Dmax_elem + 10·log10(|Σw|²/Σ|w|²)（大阵/侧射近似，assumption 字段标注
    假设域）；单元来源=闭式（isotropic/half_wave_dipole/patch）或既有 nf2ff
    run 的 farfield_cut.csv（复分量直接可吃）+ farfield_meta.json（Dmax_elem，
    PEC 镜像幂等修正）；
  * 互耦档 = EEP 集+全 S 矩阵真机编排——**本批仅留接口**：显式 tier="coupled"
    或 collect_eep_manifest → NotImplementedPhase（不发射真机）；auto 路由
    被 tier_gate 判升级时给快档数字 + invalid_fast_tier 标记 + coupled_tier
    状态块，耦合求解器可经 coupled_solver 钩子注入（P3）。
- array_scan_sweep(request)：θ 扫描网格逐点 {gate, Γ_act, blind_spot} 轻量
  汇总（盲点筛查主口径，不产出切面）。
- synthesize_array_weights(request)：只做加权综合（CLI array synthesize）。

请求 schema（全部键可选除注明；JSON 友好，复数用 [re, im] 对）：
    layout: "ula"（缺省）|"rect"
    n_elements / spacing_lambda / axis ("z"|"x"|"y")          # ula
    n_x / n_y / spacing_x_lambda / spacing_y_lambda           # rect
    amplitude_law: "uniform"|"chebyshev"|"taylor"|"binomial"|"custom"
    sidelobe_level_db / nbar / custom_weights / weights_x / weights_y
    scan_deg（ula z 轴 90=侧射、x/y 轴 0=侧射；rect=θ0） / scan_phi_deg
    element: "isotropic"|"half_wave_dipole"|"patch"；element_params（patch:
        len_mm/width_mm/freq_ghz[/h_mm/axis]）
    element_pattern_csv: farfield_cut.csv 路径（与 element 互斥，csv 优先）
    theta_grid: {"start","stop","step"} 或 {"values":[...]}（切面 θ 网格，
        缺省 patch 0..90°、其余 0..180°，步 1°）
    phi_cut_deg: float | [float]（缺省 0.0）
    dmax_grid_step_deg: 数值方向性积分步（缺省 2.0°）
    s_matrix: [[...]] NxN 复数（[re,im] 对）——给定时输出 Γ_act/Z_scan 并
        参与耦合门；z0_ohm（缺省 50）
    freq_hz / slab {eps_r, thickness_m} / dx_m / dy_m / surface_modes /
    blind_tol / gamma_threshold / max_order                   # 盲点筛查
    tier: "auto"（缺省）|"fast"|"coupled"；coupled_solver（P3 钩子，callable）
"""
from __future__ import annotations

import json
from collections.abc import Callable
from math import log10
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.array_scan import (
    active_reflection,
    blind_spot_screen,
    eep_superposition,
    scan_impedance,
    tier_gate,
)
from rfauto.core.array_synthesis import (
    array_factor,
    binomial_weights,
    broadside_hpbw_deg,
    chebyshev_weights,
    direction_cosine,
    half_wave_dipole_field,
    patch_element_field,
    peak_sidelobe_level_db,
    planar_array_factor,
    steering_direction_cosine,
    taylor_weights,
    uniform_weights,
)
from rfauto.core.farfield import (
    FARFIELD_3D_CPLX_NAME,
    FARFIELD_META_NAME,
    correct_pec_mirror,
    dmax_from_pattern,
    hpbw_deg,
    parse_farfield_3d_cplx_csv,
    parse_farfield_cut_csv,
    pattern_db,
)

__all__ = [
    "NotImplementedPhase",
    "array_pattern",
    "array_scan_sweep",
    "collect_eep_manifest",
    "synthesize_array_weights",
]

AXES = ("z", "x", "y")
_LAWS = ("uniform", "chebyshev", "taylor", "binomial", "custom")
_C_MM_GHZ = 299.792458  # 光速 mm·GHz（patch 闭式口径）
_DEG_TOL = 1e-12


class NotImplementedPhase(RuntimeError):
    """互耦档（EEP 全 S 矩阵真机编排）尚未到发射阶段——显式阶段边界。

    DP-4 P2 只交付快速档与接口契约；真机发射（EEP 模板/3D 复数 dump/
    rotation 透传/HFSS Floquet 锚）属 P3，另派执行。捕获本异常的调用方
    不应重试——这是阶段边界不是瞬态故障。
    """


# ─── JSON 装配小件 ───────────────────────────────────────────────────────────

def _cplx_pairs(arr) -> list[list[float]]:
    """复数组 → [[re, im], ...]（JSON 友好）。"""
    a = np.atleast_1d(np.asarray(arr, dtype=complex))
    return [[float(v.real), float(v.imag)] for v in a]


def _parse_cplx(value, label: str) -> complex:
    """[re,im] / {"re","im"} / 实数 / 原生 complex → complex。"""
    if isinstance(value, complex):
        return value
    if isinstance(value, dict) and "re" in value and "im" in value:
        return complex(float(value["re"]), float(value["im"]))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return complex(float(value[0]), float(value[1]))
    if isinstance(value, (int, float)):
        return complex(float(value), 0.0)
    raise ValueError(f"{label} 须为 [re,im] 对 / {{'re','im'}} / 实数，收到 {value!r}")


def _s_matrix_from_request(request: dict) -> np.ndarray | None:
    raw = request.get("s_matrix")
    if raw is None:
        return None
    rows = np.asarray(
        [[_parse_cplx(v, f"s_matrix[{i}][{j}]") for j, v in enumerate(row)]
         for i, row in enumerate(raw)], dtype=complex)
    if rows.ndim != 2 or rows.shape[0] != rows.shape[1]:
        raise ValueError(f"s_matrix 必须是方阵，收到 shape={rows.shape}")
    return rows


# ─── 加权综合 ────────────────────────────────────────────────────────────────

def _taper_for(law: str, n: int, request: dict, key: str = "custom_weights") -> np.ndarray:
    """幅度锥削分发（返回实幅度，max=1 归一，与 array_synthesis 约定一致）。"""
    if law == "uniform":
        return uniform_weights(n)
    if law == "binomial":
        return binomial_weights(n)
    if law == "chebyshev":
        sll = request.get("sidelobe_level_db")
        if sll is None:
            raise ValueError("chebyshev 锥削须给 sidelobe_level_db（负 dB）")
        return chebyshev_weights(n, float(sll))
    if law == "taylor":
        sll = request.get("sidelobe_level_db")
        if sll is None:
            raise ValueError("taylor 锥削须给 sidelobe_level_db（负 dB）")
        return taylor_weights(n, float(sll), nbar=int(request.get("nbar", 4)))
    if law == "custom":
        raw = request.get(key)
        if raw is None:
            raise ValueError(f"custom 锥削须给 {key}")
        w = np.asarray(raw, dtype=float)
        if w.ndim != 1 or w.size != n:
            raise ValueError(f"{key} 长度须为 {n}，收到 shape={w.shape}")
        if np.any(~np.isfinite(w)) or np.any(w < 0.0):
            raise ValueError(f"{key} 须为非负有限实数")
        peak = float(w.max())
        if peak <= 0.0:
            raise ValueError(f"{key} 全零")
        return w / peak
    raise ValueError(f"amplitude_law 须为 {_LAWS} 之一，收到 {law!r}")


def synthesize_array_weights(request: dict) -> dict[str, Any]:
    """只做加权综合（确定性闭式；CLI array synthesize 薄壳的实体）。"""
    try:
        law = str(request.get("amplitude_law", "uniform"))
        layout = str(request.get("layout", "ula"))
        if layout == "ula":
            n = int(request.get("n_elements", 4))
            spacing = float(request.get("spacing_lambda", 0.5))
            w = _taper_for(law, n, request)
            scan = float(request.get("scan_deg", 90.0))
            axis = str(request.get("axis", "z"))
            u0 = steering_direction_cosine(scan, float(request.get("scan_phi_deg", 0.0)), axis)
            gate = tier_gate(spacing, _scan_from_broadside(scan, axis), u0=u0)
            result = {
                "layout": layout, "law": law, "n_elements": n,
                "spacing_lambda": spacing,
                "weights": [float(v) for v in w],
                "aperture_lambda": (n - 1) * spacing,
                "broadside_hpbw_deg": (broadside_hpbw_deg(n, spacing)
                                       if n >= 2 else None),
                "gates": gate,
            }
        elif layout == "rect":
            nx = int(request.get("n_x", 2))
            ny = int(request.get("n_y", 2))
            dx = float(request.get("spacing_x_lambda", 0.5))
            dy = float(request.get("spacing_y_lambda", 0.5))
            wx = _taper_for(law, nx, request, key="weights_x")
            wy = _taper_for(law, ny, request, key="weights_y")
            result = {
                "layout": layout, "law": law, "n_x": nx, "n_y": ny,
                "spacing_x_lambda": dx, "spacing_y_lambda": dy,
                "weights_x": [float(v) for v in wx],
                "weights_y": [float(v) for v in wy],
                "gates": _rect_gate(dx, dy, float(request.get("scan_deg", 0.0)),
                                    float(request.get("scan_phi_deg", 0.0)),
                                    None),
            }
        else:
            raise ValueError(f"layout 须为 ula/rect，收到 {layout!r}")
        return {"ok": True, "result": result}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


# ─── 布局 / 激励 ─────────────────────────────────────────────────────────────

def _scan_from_broadside(scan_deg: float, axis: str | None) -> float:
    """扫描角偏离侧射的角度（ula z 轴侧射=90°，x/y 轴与平面阵侧射=0°）。"""
    broadside = 90.0 if axis == "z" else 0.0
    return abs(float(scan_deg) - broadside)


def _build_layout(request: dict) -> dict[str, Any]:
    """布局 → {kind, n, weights(复指标), positions_lambda(N,3), AF 参数}。"""
    layout = str(request.get("layout", "ula"))
    law = str(request.get("amplitude_law", "uniform"))
    if layout == "ula":
        axis = str(request.get("axis", "z"))
        if axis not in AXES:
            raise ValueError(f"axis 必须是 {AXES} 之一，收到 {axis!r}")
        n = int(request.get("n_elements", 4))
        if n < 1:
            raise ValueError(f"n_elements 至少为 1，收到 {n!r}")
        spacing = float(request.get("spacing_lambda", 0.5))
        if not np.isfinite(spacing) or spacing <= 0.0:
            raise ValueError(f"spacing_lambda 必须为正的有限值，收到 {spacing!r}")
        w = _taper_for(law, n, request)
        idx = np.arange(n, dtype=float)
        axis_vec = {"z": (0.0, 0.0, 1.0), "x": (1.0, 0.0, 0.0),
                    "y": (0.0, 1.0, 0.0)}[axis]
        pos = idx[:, None] * np.asarray(axis_vec)[None, :] * spacing
        return {
            "kind": "ula", "n": n, "axis": axis, "spacing_lambda": spacing,
            "weights": w, "positions_lambda": pos,
        }
    if layout == "rect":
        nx = int(request.get("n_x", 2))
        ny = int(request.get("n_y", 2))
        if nx < 1 or ny < 1:
            raise ValueError(f"n_x/n_y 至少为 1，收到 {nx}x{ny}")
        dx = float(request.get("spacing_x_lambda", 0.5))
        dy = float(request.get("spacing_y_lambda", 0.5))
        for label, v in (("spacing_x_lambda", dx), ("spacing_y_lambda", dy)):
            if not np.isfinite(v) or v <= 0.0:
                raise ValueError(f"{label} 必须为正的有限值，收到 {v!r}")
        wx = _taper_for(law, nx, request, key="weights_x")
        wy = _taper_for(law, ny, request, key="weights_y")
        w2 = (wx[:, None] * wy[None, :]).ravel()  # 行主序：m 外层、n 内层
        mx, my = np.meshgrid(np.arange(nx, dtype=float),
                             np.arange(ny, dtype=float), indexing="ij")
        pos = np.stack([mx.ravel() * dx, my.ravel() * dy,
                        np.zeros(nx * ny)], axis=1)
        return {
            "kind": "rect", "n": nx * ny, "n_x": nx, "n_y": ny,
            "spacing_x_lambda": dx, "spacing_y_lambda": dy,
            "weights_x": wx, "weights_y": wy, "weights": w2,
            "positions_lambda": pos,
        }
    raise ValueError(f"layout 须为 ula/rect，收到 {layout!r}")


def _excitations(request: dict, lay: dict[str, Any]) -> dict[str, Any]:
    """扫描相位记账：a_n = w_n·exp(−jψ_n)（与 array_factor 相位约定一致）。"""
    default_scan = (90.0 if (lay["kind"] == "ula" and lay.get("axis") == "z")
                    else 0.0)
    scan = float(request.get("scan_deg", default_scan))
    scan_phi = float(request.get("scan_phi_deg", 0.0))
    w = lay["weights"]
    if lay["kind"] == "ula":
        axis = lay["axis"]
        u0 = float(steering_direction_cosine(scan, scan_phi, axis))
        psi = 2.0 * np.pi * lay["spacing_lambda"] * u0 * np.arange(lay["n"])
        a = w * np.exp(-1j * psi)
        return {"scan_deg": scan, "scan_phi_deg": scan_phi, "u0": u0,
                "excitations": a}
    th0 = np.radians(scan)
    ph0 = np.radians(scan_phi)
    ux0 = float(np.sin(th0) * np.cos(ph0))
    uy0 = float(np.sin(th0) * np.sin(ph0))
    psi = (2.0 * np.pi * lay["spacing_x_lambda"] * ux0
           * np.arange(lay["n_x"], dtype=float)[:, None]
           + 2.0 * np.pi * lay["spacing_y_lambda"] * uy0
           * np.arange(lay["n_y"], dtype=float)[None, :])
    a = w * np.exp(-1j * psi.ravel())
    return {"scan_deg": scan, "scan_phi_deg": scan_phi, "u0": ux0,
            "scan_u_y": uy0, "excitations": a}


def _af_on_angles(lay: dict[str, Any], ex: dict[str, Any],
                  theta_deg, phi_deg) -> np.ndarray:
    """阵列因子（复，归一到侧射峰 1）在任意 (θ,φ) 网格上。"""
    theta = np.asarray(theta_deg, dtype=float)
    phi = np.asarray(phi_deg, dtype=float)
    if lay["kind"] == "ula":
        u = direction_cosine(theta, phi, lay["axis"])
        return array_factor(u, lay["weights"],
                            spacing_lambda=lay["spacing_lambda"],
                            scan_direction_cosine=ex["u0"], normalize=True)
    theta, phi = np.broadcast_arrays(theta, phi)
    return planar_array_factor(
        theta, phi, lay["weights_x"], lay["weights_y"],
        spacing_x_lambda=lay["spacing_x_lambda"],
        spacing_y_lambda=lay["spacing_y_lambda"],
        scan_u_x=ex["u0"], scan_u_y=ex["scan_u_y"], normalize=True)


# ─── 单元方向图来源 ──────────────────────────────────────────────────────────

def _element_provider(request: dict) -> tuple[Callable[..., tuple[np.ndarray, np.ndarray]], dict[str, Any]]:
    """单元方向图来源 → (e_theta,e_phi 复) 采样函数 + 描述 dict。

    闭式（isotropic/half_wave_dipole/patch，实值转复）或 farfield_cut.csv
    （复分量，最近 φ 平面 + θ 线性内插，端点外截断夹持——如实记录范围）。
    """
    csv_path = request.get("element_pattern_csv")
    if csv_path is not None:
        path = Path(str(csv_path))
        if not path.is_file():
            raise ValueError(f"element_pattern_csv 不存在: {path}")
        cuts = parse_farfield_cut_csv(path)
        phis = np.asarray([c["phi_deg"] for c in cuts], dtype=float)

        def csv_field(theta_deg, phi_deg):
            th = np.asarray(theta_deg, dtype=float)
            ph = np.asarray(phi_deg, dtype=float)
            th, ph = np.broadcast_arrays(th, ph)
            et = np.empty(th.shape, dtype=complex)
            ep = np.empty(th.shape, dtype=complex)
            # 逐点取最近 φ 平面（切面用途 φ 恒定 → 单平面 fast path 亦走此处）
            for idx, (tv, pv) in enumerate(zip(th.ravel(), ph.ravel(), strict=True)):
                k = int(np.argmin(np.abs(phis - pv)))
                cut = cuts[k]
                order = np.argsort(cut["theta_deg"])
                t_axis = cut["theta_deg"][order]
                et_ax = cut["e_theta"][order]
                ep_ax = cut["e_phi"][order]
                et.ravel()[idx] = (np.interp(tv, t_axis, et_ax.real)
                                   + 1j * np.interp(tv, t_axis, et_ax.imag))
                ep.ravel()[idx] = (np.interp(tv, t_axis, ep_ax.real)
                                   + 1j * np.interp(tv, t_axis, ep_ax.imag))
            return et, ep

        info = {"source": "csv", "path": str(path), "phi_planes_deg":
                [float(v) for v in phis]}
        return csv_field, info

    kind = str(request.get("element", "isotropic"))
    if kind == "isotropic":
        def iso_field(theta_deg, phi_deg):
            th, _ph = np.broadcast_arrays(np.asarray(theta_deg, float),
                                          np.asarray(phi_deg, float))
            return np.ones(th.shape, dtype=complex), np.zeros(th.shape, dtype=complex)
        return iso_field, {"source": "closed_form", "kind": "isotropic"}
    if kind == "half_wave_dipole":
        def dipole_field(theta_deg, phi_deg):
            # z 向振子方位对称：θ 广播到 (θ,φ) 全形，φ 依赖显式为零
            th, _ph = np.broadcast_arrays(np.asarray(theta_deg, dtype=float),
                                          np.asarray(phi_deg, dtype=float))
            e = np.asarray(half_wave_dipole_field(th), dtype=float)
            return e.astype(complex), np.zeros(e.shape, dtype=complex)
        return dipole_field, {"source": "closed_form", "kind": "half_wave_dipole"}
    if kind == "patch":
        params = request.get("element_params") or {}
        try:
            kw = dict(len_mm=float(params["len_mm"]),
                      width_mm=float(params["width_mm"]),
                      freq_ghz=float(params["freq_ghz"]),
                      h_mm=float(params.get("h_mm", 0.508)),
                      axis=str(params.get("axis", "x")))
        except KeyError as exc:
            raise ValueError(
                f"patch element_params 缺必填键 {exc}（len_mm/width_mm/freq_ghz）"
            ) from exc

        def patch_field(theta_deg, phi_deg):
            et = np.asarray(patch_element_field(theta_deg, phi_deg,
                                                component="theta", **kw))
            ep = np.asarray(patch_element_field(theta_deg, phi_deg,
                                                component="phi", **kw))
            return et.astype(complex), ep.astype(complex)

        return patch_field, {"source": "closed_form", "kind": "patch", **kw}
    raise ValueError(
        f"element 须为 isotropic/half_wave_dipole/patch，或给 element_pattern_csv；"
        f"收到 {kind!r}")


def _default_theta_grid(request: dict, elem_info: dict[str, Any]) -> np.ndarray:
    tg = request.get("theta_grid")
    if tg is not None:
        if "values" in tg:
            vals = np.asarray(tg["values"], dtype=float)
            if vals.size < 3:
                raise ValueError("theta_grid.values 至少 3 点")
            return np.sort(vals)
        step = float(tg.get("step", 1.0))
        start = float(tg.get("start", 0.0))
        stop = float(tg.get("stop", 180.0))
        vals = np.arange(start, stop + step * 0.5, step)
        if vals.size < 3:
            raise ValueError("theta_grid 至少 3 点")
        return vals
    stop = 90.0 if elem_info.get("kind") == "patch" else 180.0
    return np.arange(0.0, stop + 0.5, 1.0)


def _integration_grid(elem_info: dict[str, Any], step_deg: float
                      ) -> tuple[np.ndarray, np.ndarray]:
    """方向性数值积分网格（θ 上限按单元口径：patch 半球、其余全球）。"""
    th_stop = 90.0 if elem_info.get("kind") == "patch" else 180.0
    th = np.arange(0.0, th_stop + step_deg * 0.5, step_deg)
    ph = np.arange(0.0, 360.0, step_deg)
    return th, ph


def _hemisphere_for(elem_info: dict[str, Any]) -> str:
    return "upper" if elem_info.get("kind") == "patch" else "full"


def _dmax_elem_dbi(elem_info: dict[str, Any],
                   elem_fn: Callable, grid_step: float) -> tuple[float | None, str | None]:
    """单元方向性 Dmax_elem（dBi）。

    isotropic=0 精确；闭式单元=数值球面/半球积分（dmax_from_pattern）；
    csv 单元=伴生 farfield_meta.json（correct_pec_mirror 幂等修正后 dmax_dbi），
    缺 meta → (None, 原因) 如实不虚构。
    """
    if elem_info["source"] == "closed_form":
        if elem_info.get("kind") == "isotropic":
            return 0.0, None
        th, ph = _integration_grid(elem_info, grid_step)
        et, ep = elem_fn(th[:, None], ph[None, :])
        p = np.abs(et) ** 2 + np.abs(ep) ** 2
        d = dmax_from_pattern(p, np.radians(th), np.radians(ph),
                              hemisphere=_hemisphere_for(elem_info))
        return 10.0 * log10(max(d, 1e-300)), None
    # csv：meta 定位（csv 同目录或 fdtd/ 子目录）
    base = Path(elem_info["path"]).parent
    for cand in (base / FARFIELD_META_NAME, base / "fdtd" / FARFIELD_META_NAME):
        if cand.is_file():
            meta = json.loads(cand.read_text(encoding="utf-8"))
            meta = correct_pec_mirror(meta)
            v = meta.get("dmax_dbi")
            if v is None:
                return None, f"meta {cand} 无 dmax_dbi 字段"
            return float(v), None
    return None, f"未找到伴生 {FARFIELD_META_NAME}（{base} 及 fdtd/）"


# ─── 门 ──────────────────────────────────────────────────────────────────────

def _max_coupling_db(s_matrix: np.ndarray | None) -> float | None:
    """max_{n≠m}|S_nm| 的 dB（无 S/全零 → None/−300，未知不等于弱耦）。"""
    if s_matrix is None:
        return None
    off = np.abs(s_matrix - np.diag(np.diag(s_matrix)))
    peak = float(off.max())
    if peak <= 0.0:
        return -300.0
    return 20.0 * log10(peak)


def _rect_gate(dx: float, dy: float, scan_deg: float, scan_phi_deg: float,
               coupling_db: float | None) -> dict[str, Any]:
    """平面阵两轴门合并（逐轴栅瓣判据；间距门取 min(dx,dy)，θ 门取 |θ0|）。"""
    th0 = float(scan_deg)
    ph0 = np.radians(scan_phi_deg)
    ux0 = float(np.sin(np.radians(th0)) * np.cos(ph0))
    uy0 = float(np.sin(np.radians(th0)) * np.sin(ph0))
    gx = tier_gate(dx, abs(th0), u0=ux0, coupling_db=coupling_db)
    gy = tier_gate(dy, abs(th0), u0=uy0, coupling_db=coupling_db)
    allowed = gx["allowed"] and gy["allowed"]
    return {
        "tier": "fast" if allowed else "coupled",
        "allowed": allowed,
        "invalid_fast_tier": not allowed,
        "reasons": [f"axis_x: {r}" for r in gx["reasons"]]
                   + [f"axis_y: {r}" for r in gy["reasons"]],
        "checks": {"x": gx["checks"], "y": gy["checks"]},
    }


def _gate_for(request: dict, lay: dict[str, Any], ex: dict[str, Any],
              coupling_db: float | None) -> dict[str, Any]:
    if lay["kind"] == "ula":
        return tier_gate(lay["spacing_lambda"],
                         _scan_from_broadside(ex["scan_deg"], lay["axis"]),
                         u0=ex["u0"], coupling_db=coupling_db)
    return _rect_gate(lay["spacing_x_lambda"], lay["spacing_y_lambda"],
                      ex["scan_deg"], ex["scan_phi_deg"], coupling_db)


# ─── 盲点 ────────────────────────────────────────────────────────────────────

def _blind_spot_for(request: dict, lay: dict[str, Any], ex: dict[str, Any],
                    gamma_act: np.ndarray | None) -> dict[str, Any] | None:
    """单扫描角盲点筛查；前置不足（无频率/无基片/无 β）→ None + 说明。

    gamma_act：复激励下的逐元 Γ_act（1D 复数组，None=无 S 数据），以
    (1, N) 二维传给 blind_spot_screen 取逐点最大。口径注记：盲点筛查的
    栅格周期必须在接地板 k∥ 平面内——rect 阵天然满足；ula 仅 x/y 轴阵
    适用（正交向无周期性，以 1e6·λ 的大间距使该向栅格阶坍缩、等效一维）；
    z 轴阵栅格垂直于板面，Floquet k∥ 口径不适用，如实跳过（P3 全波/Floquet
    仲裁，不虚构筛查结论）。
    """
    slab = request.get("slab")
    has_beta = request.get("beta_sw_rad_per_m") is not None
    if slab is None and not has_beta:
        return None
    freq_hz = request.get("freq_hz")
    if freq_hz is None and request.get("element") == "patch":
        params = request.get("element_params") or {}
        freq_hz = params.get("freq_ghz")
        if freq_hz is not None:
            freq_hz = float(freq_hz) * 1e9
    if freq_hz is None:
        return {"skipped": True, "reason": "缺 freq_hz（或 patch freq_ghz），k0 不可得"}
    freq_hz = float(freq_hz)
    lam = _C_MM_GHZ / (freq_hz / 1e9) / 1000.0  # λ0（m）

    _NO_PERIODICITY = lam * 1e6  # 正交向无栅格：阶坍缩至 k∥≈0，等效一维筛查
    if lay["kind"] == "ula":
        axis = lay["axis"]
        if axis == "z":
            return {"skipped": True,
                    "reason": "z 轴阵栅格垂直于接地板 k∥ 平面，Floquet 盲点口径"
                              "不适用（P3 以 HFSS Floquet/全波仲裁，不虚构筛查）"}
        dx_m = float(request.get("dx_m") or (lay["spacing_lambda"] * lam))
        dy_m = float(request.get("dy_m") or _NO_PERIODICITY)
    else:
        dx_m = float(request.get("dx_m") or (lay["spacing_x_lambda"] * lam))
        dy_m = float(request.get("dy_m") or (lay["spacing_y_lambda"] * lam))
    kw: dict[str, Any] = {
        "freq_hz": freq_hz, "dx_m": dx_m, "dy_m": dy_m,
        "tol": float(request.get("blind_tol", 0.02)),
        "gamma_threshold": float(request.get("gamma_threshold", 0.8)),
        "max_order": int(request.get("max_order", 2)),
    }
    if has_beta:
        kw["beta_sw_rad_per_m"] = request["beta_sw_rad_per_m"]
    else:
        kw["slab_eps_r"] = float(slab["eps_r"])
        kw["slab_thickness_m"] = float(slab["thickness_m"])
        kw["surface_modes"] = tuple(request.get("surface_modes", ("TM0", "TE1")))
    if gamma_act is not None:
        kw["gamma_act"] = np.abs(np.asarray(gamma_act, dtype=complex))[None, :]
    return blind_spot_screen(ex["scan_deg"], ex["scan_phi_deg"], **kw)


# ─── 主入口：单扫描角方向图 ───────────────────────────────────────────────────

def array_pattern(request: dict, coupled_solver: Callable[[dict], dict] | None = None) -> dict[str, Any]:
    """阵列方向图两档路由（schema 见模块 docstring；返回 {"ok": ...}）。

    NotImplementedPhase：显式 tier="coupled" 且 coupled_solver=None 时抛出
    （阶段边界，不重试）；auto 路由被判升级时不抛——返回快档数字 +
    invalid_fast_tier=True + coupled_tier 状态块。
    """
    try:
        lay = _build_layout(request)
        ex = _excitations(request, lay)
        s_matrix = _s_matrix_from_request(request)
        z0 = float(request.get("z0_ohm", 50.0))
        coupling_db = _max_coupling_db(s_matrix)
        gate = _gate_for(request, lay, ex, coupling_db)

        tier_req = str(request.get("tier", "auto"))
        if tier_req not in ("auto", "fast", "coupled"):
            raise ValueError(f"tier 须为 auto/fast/coupled，收到 {tier_req!r}")
        if tier_req == "coupled":
            if coupled_solver is None:
                raise NotImplementedPhase(
                    "DP-4 互耦档（EEP+全 S 矩阵真机编排）属 P3：本批仅预定义"
                    "接口，不发射真机（详见 runs/df6_dp4af/criteria.md P3 交接）")
            return {"ok": True, "result": coupled_solver(request)}

        # ── 快速档（秒级）：单元方向图 × AF 复域逐点乘 ──
        elem_fn, elem_info = _element_provider(request)
        grid_step = float(request.get("dmax_grid_step_deg", 2.0))
        dmax_elem, dmax_elem_note = _dmax_elem_dbi(elem_info, elem_fn, grid_step)

        phi_cuts_raw = request.get("phi_cut_deg", 0.0)
        phi_cuts = ([float(v) for v in phi_cuts_raw]
                    if isinstance(phi_cuts_raw, (list, tuple))
                    else [float(phi_cuts_raw)])
        th_cut = _default_theta_grid(request, elem_info)
        cuts_out = []
        for phi_cut in phi_cuts:
            et, ep = elem_fn(th_cut, np.full_like(th_cut, phi_cut))
            af = _af_on_angles(lay, ex, th_cut, np.full_like(th_cut, phi_cut))
            f = (et + ep) * af
            f_abs = np.abs(f)
            u_cut = (direction_cosine(th_cut, phi_cut, lay["axis"])
                     if lay["kind"] == "ula"
                     else direction_cosine(th_cut, phi_cut, "x"))
            main_u = float(ex["u0"])
            pdb = pattern_db(f_abs)
            cuts_out.append({
                "phi_deg": phi_cut,
                "theta_deg": [float(v) for v in th_cut],
                "f": _cplx_pairs(f),
                "f_abs": [float(v) for v in f_abs],
                "f_db": [None if not np.isfinite(v) else float(v) for v in pdb],
                "af_abs": [float(v) for v in np.abs(af)],
                "element_abs": [float(v) for v in np.abs(et + ep)],
                "sll_db": (float(peak_sidelobe_level_db(
                    f_abs, u_cut, main_lobe_direction_cosine=main_u))
                    if f_abs.max() > 0.0 else None),
                "hpbw_deg": hpbw_deg(th_cut, pdb),
            })

        # Dmax：公式档（假设域标注）+ 数值积分档（交叉核验）
        w = lay["weights"]
        taper_gain_db = 10.0 * log10(max(float(np.abs(w.sum()) ** 2)
                                         / max(float(np.sum(np.abs(w) ** 2)), 1e-300),
                                         1e-300))
        dmax_fast = (float(dmax_elem) + taper_gain_db
                     if dmax_elem is not None else None)
        dmax_grid = None
        th_g, ph_g = _integration_grid(elem_info, grid_step)
        et_g, ep_g = elem_fn(th_g[:, None], ph_g[None, :])
        af_g = _af_on_angles(lay, ex, th_g[:, None], ph_g[None, :])
        p_arr = np.abs(et_g + ep_g) ** 2 * np.abs(af_g) ** 2
        d_lin = dmax_from_pattern(p_arr, np.radians(th_g), np.radians(ph_g),
                                  hemisphere=_hemisphere_for(elem_info))
        dmax_grid = 10.0 * log10(max(d_lin, 1e-300))

        gamma_out: list[list[float]] | None = None
        z_out: list[list[float] | None] | None = None
        z_degenerate: list[int] = []
        if s_matrix is not None:
            gamma = active_reflection(s_matrix, ex["excitations"])
            zvals = scan_impedance(gamma, z0)
            gamma_out = _cplx_pairs(gamma)
            z_out = []
            for i, zv in enumerate(np.atleast_1d(zvals)):
                if not np.isfinite(zv.real) or not np.isfinite(zv.imag):
                    z_out.append(None)
                    z_degenerate.append(i)
                else:
                    z_out.append([float(zv.real), float(zv.imag)])
        blind = _blind_spot_for(request, lay, ex,
                                np.asarray(gamma_out, dtype=complex)
                                if gamma_out is not None else None)

        coupled_tier = None
        if gate["invalid_fast_tier"]:
            coupled_tier = {
                "status": "NotImplementedPhase",
                "message": ("tier_gate 判快速档假设域外/强耦——互耦档真机编排属 "
                            "P3（本批不发射）；上方快档数字带 invalid 标记，"
                            "仅供诊断不采信"),
                "reasons": gate["reasons"],
            }

        result = {
            "tier": gate["tier"] if tier_req == "auto" else "fast",
            "invalid_fast_tier": gate["invalid_fast_tier"],
            "gates": gate,
            "layout": lay["kind"],
            "n_elements": lay["n"],
            "axis": lay.get("axis"),
            "spacing_lambda": lay.get("spacing_lambda"),
            "positions_lambda": lay["positions_lambda"].tolist(),
            "scan_deg": ex["scan_deg"],
            "scan_phi_deg": ex["scan_phi_deg"],
            "scan_u0": ex.get("u0"),
            "amplitude_law": str(request.get("amplitude_law", "uniform")),
            "weights": [float(v) for v in w],
            "excitations": _cplx_pairs(ex["excitations"]),
            "element": elem_info,
            "cuts": cuts_out,
            "sll_db": cuts_out[0]["sll_db"],
            "hpbw_deg": cuts_out[0]["hpbw_deg"],
            "dmax_elem_dbi": dmax_elem,
            "dmax_elem_note": dmax_elem_note,
            "dmax_fast_dbi": dmax_fast,
            "dmax_fast_assumption": (
                "大阵/侧射近似 Dmax_elem+10lg(|Σw|²/Σ|w|²)：仅在 tier_gate 放行域内"
                "有效；扫描下的真实方向性以 dmax_grid_dbi 数值积分为准"),
            "taper_gain_db": taper_gain_db,
            "dmax_grid_dbi": dmax_grid,
            "gamma_act": gamma_out,
            "z_scan": z_out,
            "z_scan_degenerate_indices": z_degenerate,
            "z0_ohm": z0,
            "blind_spot": blind,
            "coupled_tier": coupled_tier,
            "coupled_solver_hooked": coupled_solver is not None,
        }
        return {"ok": True, "result": result}
    except (ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}


# ─── 扫描扫掠（盲点/Γ_act 主口径）────────────────────────────────────────────

def array_scan_sweep(request: dict) -> dict[str, Any]:
    """θ 扫描网格逐点 {gate, Γ_act, blind_spot}（不产出切面，轻量）。"""
    try:
        lay = _build_layout(request)
        s_matrix = _s_matrix_from_request(request)
        coupling_db = _max_coupling_db(s_matrix)
        grid = request.get("scan_grid") or {}
        if "values" in grid:
            angles = np.asarray(grid["values"], dtype=float)
        else:
            step = float(grid.get("step", 2.0))
            angles = np.arange(float(grid.get("start", 0.0)),
                               float(grid.get("stop", 90.0)) + step * 0.5, step)
        if angles.size < 1:
            raise ValueError("scan_grid 至少 1 点")
        rows = []
        for ang in angles:
            req1 = dict(request)
            req1["scan_deg"] = float(ang)
            ex = _excitations(req1, lay)
            gate = _gate_for(req1, lay, ex, coupling_db)
            row: dict[str, Any] = {
                "scan_deg": float(ang),
                "scan_from_broadside_deg": _scan_from_broadside(
                    float(ang), lay.get("axis")),
                "tier": gate["tier"],
                "invalid_fast_tier": gate["invalid_fast_tier"],
                "reasons": gate["reasons"],
            }
            gamma = None
            if s_matrix is not None:
                gamma = active_reflection(s_matrix, ex["excitations"])
                row["gamma_act_max"] = float(np.abs(gamma).max())
            bs = _blind_spot_for(req1, lay, ex, gamma)
            if bs is not None:
                row["blind"] = bool(bs["blind"][0]) if not bs.get("skipped") else None
                row["blind_by"] = (bs["blind_by"][0]
                                   if not bs.get("skipped") else bs.get("reason"))
                row["min_dist_over_k0"] = (bs["min_dist_over_k0"][0]
                                           if not bs.get("skipped") else None)
                row["nearest_order"] = ([bs["nearest_order_m"][0],
                                         bs["nearest_order_n"][0]]
                                        if not bs.get("skipped") else None)
            rows.append(row)
        n_blind = sum(1 for r in rows if r.get("blind") is True)
        return {"ok": True, "result": {
            "layout": lay["kind"], "n_elements": lay["n"],
            "n_angles": int(angles.size), "n_blind": n_blind,
            "coupling_db": coupling_db,
            "has_slab_screen": (request.get("slab") is not None
                                or request.get("beta_sw_rad_per_m") is not None),
            "rows": rows,
        }}
    except (ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}


# ─── P3 互耦档（EEP 全 S 矩阵 + 叠加；DP-4 P3 实现替换 P2 占位）───────────────
#
# 编排链（铁律 7：数值只在确定性内核）：
#   solve_smatrix_openems（#208 进程隔离 N 次单激励，far_field=True 透传）
#     → collect_eep_manifest（#320 显式引用归属，缺件如实 skipped 不猜）
#     → 逐轮 farfield3d_cplx.csv 载入（core.farfield 契约）→ eep_superposition
#     → Γ_act/Z_scan（core.array_scan）→ σmax 装配门（J4a，numpy SVD 实测）。
# EEP 轮口径（openems_templates §DP-4 P3 段）：每元独立 LumpedPort 底探针，
# f_res=F0 固定（轮间同频方可叠加）；端口次序=行主序（x 外层 y 内层），
# 与 EEP_TIER_GRIDS 布局的激励行主序一致。

#: EEP 模板 → 阵面栅格 (n_x, n_y)（激励/位置记账行主序契约，与
#: openems_templates._eep_layout 端口次序一致，test_eep_templates 互检）
EEP_TIER_GRIDS: dict[str, tuple[int, int]] = {
    "patch_eep_2x2": (2, 2),
    "patch_eep_1x4": (4, 1),
}

#: J4a 装配无源门（runs/df6_dp4p3/criteria.md 预声明）：带内 max σmax ≤ 1.005。
#: EEP 模板为 LumpedPort 端口（参考=50Ω 集总元自身），raw 装配即 50Ω 基——
#: #250 MSL 线基反演不适用（无三面探针）。
EEP_SIGMA_MAX_LIMIT = 1.005

#: J4b 报告门动态地板：只统计 |F_coupled| 峰值下 40dB 以内的点（副瓣级
#: 比较不进噪声底）。
_EEP_COMPARE_FLOOR_DB = -40.0


def _sha256_file(path: Path) -> str | None:
    """文件 sha256（best-effort，#105：观测性不得阻塞主路径）。"""
    import hashlib

    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _csv_row_count(path: Path) -> int | None:
    """数据行数（含表头减一；best-effort，供 manifest 落痕）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return max(sum(1 for _ in fh) - 1, 0)
    except OSError:
        return None


def _read_eep_meta(path: Path) -> dict[str, Any] | None:
    """读轮级 farfield_meta.json 的 J4d 判读子集（best-effort）。"""
    try:
        import json

        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    keys = ("ok", "template", "eep", "excite_port", "f_res_ghz", "f_res_mode",
            "grid_theta_deg", "grid_phi_deg")
    return {k: meta.get(k) for k in keys if k in meta}


def collect_eep_manifest(run_dirs: list[str], n_ports: int, *,
                         curve_refs: dict[int, str] | None = None) -> dict[str, Any]:
    """互耦档 EEP 收集清单（DP-4 P3 实现，替换 P2 占位；签名=P2 契约 57dac66）。

    N 次单激励 run（openEMS 逐端口子进程，#208 进程隔离）→ EEP 集
    （farfield3d_cplx.csv）+ 全 S 矩阵轮列（sparams.csv 掩码载体优先，#314）
    的归属清单。两种布局：
    - run_dirs=[work_root]（rotation 布局）：逐端口基目录 = root/p{k}，
      缺省引用 `p{k}/farfield3d_cplx.csv`（#320 示例同构，相对 run 根）；
    - run_dirs=[d1..dN]（逐端口布局）：基目录 = d{k}，缺省引用相对端口目录。
    curve_refs（端口号 → 相对基目录路径）显式引用优先——禁止按文件序/字典序
    猜归属；缺文件端口如实列入 skipped（不猜不补，#316 方向）。
    """
    n = int(n_ports)
    if n < 1:
        raise ValueError(f"n_ports 至少为 1，收到 {n_ports!r}")
    if not run_dirs:
        raise ValueError("run_dirs 为空")
    bases = [Path(str(d)) for d in run_dirs]
    if len(bases) == 1:
        root = bases[0]
        if not root.is_dir():
            return {"ok": False, "error": f"run 根不存在: {root}"}
        layout = "work_root"
        port_bases = [root / f"p{k}" for k in range(1, n + 1)]
        default_ref = lambda k: f"p{k}/{FARFIELD_3D_CPLX_NAME}"  # noqa: E731
        default_meta = lambda k: f"p{k}/{FARFIELD_META_NAME}"    # noqa: E731
        default_round = lambda k: f"p{k}/sparams.csv"            # noqa: E731
    elif len(bases) == n:
        layout = "per_port"
        root = bases[0]
        port_bases = bases
        default_ref = lambda k: FARFIELD_3D_CPLX_NAME            # noqa: E731
        default_meta = lambda k: FARFIELD_META_NAME              # noqa: E731
        default_round = lambda k: "sparams.csv"                  # noqa: E731
    else:
        raise ValueError(
            f"run_dirs 长度须为 1（work_root 布局）或 n_ports={n}（逐端口布局），"
            f"收到 {len(bases)}")

    refs = dict(curve_refs or {})
    ports: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    rounds: dict[str, dict[str, Any]] = {}
    for k in range(1, n + 1):
        # 引用解析基：work_root 布局=run 根（缺省 ref 含 p{k}/ 前缀，#320
        # 示例同构）；逐端口布局=该端口目录。二者都不得二次拼接端口目录。
        ref_base = bases[0] if layout == "work_root" else port_bases[k - 1]
        ref = str(refs.get(k, default_ref(k)))
        path = ref_base / ref
        entry: dict[str, Any] = {"port": k, "curve_ref": ref,
                                 "path": str(path), "exists": path.is_file()}
        if entry["exists"]:
            entry["sha256"] = _sha256_file(path)
            entry["rows"] = _csv_row_count(path)
            meta_p = ref_base / str(refs.get(-k, default_meta(k)))
            meta = _read_eep_meta(meta_p)
            if meta is not None:
                entry["meta_ref"] = str(meta_p)
                entry["meta"] = meta
        else:
            skipped.append({"port": k, "kind": "eep_curve",
                            "curve_ref": ref, "reason": "curve_ref 不存在"})
        sref = default_round(k)
        spath = ref_base / sref
        rounds[str(k)] = {"ref": sref, "path": str(spath),
                          "exists": spath.is_file()}
        ports[str(k)] = entry

    s_matrix: dict[str, Any] = {"source": "rounds", "ref": "rounds/sparams.csv"}
    if layout == "work_root":
        s4p_hits = sorted(
            p for p in root.glob(f"*.s{n}.p")
            if not p.name.endswith(f"_raw.s{n}.p"))
        if s4p_hits:
            s_matrix = {"source": "s4p", "ref": s4p_hits[0].name,
                        "path": str(s4p_hits[0])}
    return {
        "ok": True, "layout": layout, "n_ports": n,
        "run_root": str(root), "run_dirs": [str(b) for b in bases],
        "ports": ports, "rounds": rounds, "s_matrix": s_matrix,
        "skipped": skipped, "n_skipped": len(skipped),
        "curve_refs_policy": ("显式引用优先（#320）；缺省 p{k}/farfield3d_cplx.csv"
                              if layout == "work_root" else
                              "显式引用优先（#320）；缺省 farfield3d_cplx.csv"),
    }


def _load_smatrix_from_rounds(work_root: str | Path,
                              n_ports: int) -> tuple[Any, Any]:
    """轮列 sparams.csv → (freq_ghz, (nf,N,N) 复 S)（#314 掩码载体优先口径）。

    任一轮缺失/不可解析/频率轴不一致 → ValueError（装配中止，不猜不补）。
    """
    from rfauto.adapters.openems_rotation import load_round_column

    root = Path(str(work_root))
    freq: Any = None
    s_mat: Any = None
    for k in range(1, n_ports + 1):
        got = load_round_column(root / f"p{k}" / "sparams.csv", n_ports)
        if got is None:
            raise ValueError(
                f"p{k}/sparams.csv 缺失或不可解析（装配中止，#314 载体优先，不猜）")
        fg, col = got
        if freq is None:
            freq = fg
            s_mat = np.zeros((len(fg), n_ports, n_ports), dtype=complex)
        elif not np.allclose(fg, freq):
            raise ValueError(f"p{k} 频率轴与 p1 不一致（装配中止）")
        for i in range(n_ports):
            s_mat[:, i, k - 1] = col[i]
    return freq, s_mat


def _eep_tier_request(request: dict, template: str,
                      f0_ghz: float) -> tuple[dict, dict, dict, dict]:
    """模板+参数 → (rect 布局请求, 布局, 激励, 合并几何参数)（行主序=端口次序契约）。"""
    from rfauto.adapters.openems_templates import EEP_NOMINAL

    nx, ny = EEP_TIER_GRIDS[template]
    p = dict(EEP_NOMINAL[template])
    for key, val in (request.get("params") or {}).items():
        if key in p:
            p[key] = float(val)
    lam0_m = _C_MM_GHZ / f0_ghz / 1000.0
    sx_l = float(p["spacing_x_mm"]) * 1e-3 / lam0_m
    sy_l = float(p.get("spacing_y_mm", p["spacing_x_mm"])) * 1e-3 / lam0_m
    req: dict[str, Any] = {
        "layout": "rect", "n_x": nx, "n_y": ny,
        "spacing_x_lambda": sx_l, "spacing_y_lambda": sy_l,
        "amplitude_law": str(request.get("amplitude_law", "uniform")),
        "scan_deg": float(request.get("scan_deg", 0.0)),
        "scan_phi_deg": float(request.get("scan_phi_deg", 0.0)),
    }
    for key in ("sidelobe_level_db", "nbar", "custom_weights", "weights_x",
                "weights_y"):
        if request.get(key) is not None:
            req[key] = request[key]
    lay = _build_layout(req)
    ex = _excitations(req, lay)
    return req, lay, ex, p


def _eep_fast_compare(template: str, request: dict, lay: dict[str, Any],
                      ex: dict[str, Any], params: dict[str, Any],
                      theta_deg: Any, phi_deg: Any, f_coupled: Any,
                      f0_ghz: float) -> dict[str, Any]:
    """J4b 全阵 vs 快档带内报告（报告非硬阈，#122：如实 PASS/FAIL 不凑绿）。

    快档 = 闭式单元（Balanis Ch.14 腔模型，L 沿 y）× 平面阵 AF（同一激励）；
    统计域 = 上半球（θ≤90°）且 |F_coupled| 高于峰值 40dB（副瓣级比较不进
    噪声底）。
    """
    from rfauto.core.array_synthesis import patch_element_field

    th = np.asarray(theta_deg, dtype=float)[:, None]
    ph = np.asarray(phi_deg, dtype=float)[None, :]
    upper = th <= 90.0 + 1e-9
    # 闭式单元只定义在上半球（地面下无场，array_synthesis 域守卫）——
    # 地平线下取 0（与地面镜像物理一致），统计域本就只取上半球
    th_eval = np.where(upper, th, 0.0)
    et = np.asarray(patch_element_field(
        th_eval, ph, len_mm=float(params["elem_len_mm"]),
        width_mm=float(params["elem_w_mm"]), freq_ghz=f0_ghz,
        axis="y", component="theta"), dtype=float)
    epf = np.asarray(patch_element_field(
        th_eval, ph, len_mm=float(params["elem_len_mm"]),
        width_mm=float(params["elem_w_mm"]), freq_ghz=f0_ghz,
        axis="y", component="phi"), dtype=float)
    et = np.where(upper, et, 0.0)
    epf = np.where(upper, epf, 0.0)
    af = planar_array_factor(
        th, ph, lay["weights_x"], lay["weights_y"],
        spacing_x_lambda=lay["spacing_x_lambda"],
        spacing_y_lambda=lay["spacing_y_lambda"],
        scan_u_x=float(ex["u0"]), scan_u_y=float(ex["scan_u_y"]),
        normalize=True)
    f_fast = (et + epf) * af
    fc_db = pattern_db(np.abs(f_coupled))
    ff_db = pattern_db(np.abs(f_fast))
    upper = th <= 90.0 + 1e-9
    mask = upper & np.isfinite(fc_db) & (fc_db > _EEP_COMPARE_FLOOR_DB)
    n_pts = int(np.count_nonzero(mask))
    if n_pts < 1:
        return {"n_points": 0, "gate": None,
                "note": "统计域为空（全阵方向图低于地板），无可比点"}
    dev = (fc_db - ff_db)[mask]
    ic = int(np.argmax(np.abs(f_coupled)))
    ifast = int(np.argmax(np.abs(f_fast)))
    th_f = np.asarray(theta_deg, dtype=float)
    ph_f = np.asarray(phi_deg, dtype=float)
    n_ph = ph_f.size   # 行主序 (n_theta, n_phi)：it=flat//n_ph、ip=flat%n_ph
    return {
        "n_points": n_pts,
        "floor_db": _EEP_COMPARE_FLOOR_DB,
        "dev_db_median": float(np.median(dev)),
        "dev_db_p95": float(np.percentile(dev, 95)),
        "dev_db_max": float(dev.max()),
        "peak_coupled_theta_deg": float(th_f[ic // n_ph]),
        "peak_coupled_phi_deg": float(ph_f[ic % n_ph]),
        "peak_fast_theta_deg": float(th_f[ifast // n_ph]),
        "peak_fast_phi_deg": float(ph_f[ifast % n_ph]),
        "gate": None,
        "criteria": "J4b 报告门（副瓣级 1–3dB 预期，如实报告不设硬阈；"
                    "runs/df6_dp4p3/criteria.md）",
    }


def coupled_tier_solve(request: dict) -> dict[str, Any]:
    """互耦档求解入口（DP-4 P3 实现；经 array_pattern(request, coupled_solver=·)
    注入，或显式 tier="coupled" 路由直达）。

    请求 schema（JSON 友好）：
        template（必填）：patch_eep_2x2 | patch_eep_1x4
        work_root（必填）：EEP 轮转 run 根（launch=True 时为产出目录，
            launch=False 时须已含 p1..pN 轮产物——真机复判/合成 fixture）
        launch（缺省 True）：True=调 solve_smatrix_openems 真跑（N 次单激励
            子进程 #208，逐轮断点缓存 resume）；False=只对既有产物判读
        params / freq_range_ghz / mesh_resolution_mm / timeout_s / exe_path /
            cache / resume / line_z0：透传 solve_smatrix_openems
            （far_field 缺省 True；line_z0 缺省 None——LumpedPort 端口
            50Ω 基即真波基，#250 MSL 线基反演不适用，见 EEP_SIGMA_MAX_LIMIT 注）
        curve_refs / allow_partial：透传 collect_eep_manifest（#320）
        scan_deg / scan_phi_deg / amplitude_law / sidelobe_level_db / nbar /
            weights_x / weights_y / z0_ohm / f0_ghz：激励与判读频率
        include_s_matrix（缺省 False）：True 时带全频段 s_params（[re,im]）

    返回 {"ok", "result"| "error"}；J4a σmax 门与 J4b 报告门见
    runs/df6_dp4p3/criteria.md。
    """
    try:
        template = str(request.get("template", ""))
        if template not in EEP_TIER_GRIDS:
            raise ValueError(
                f"template 须为 {sorted(EEP_TIER_GRIDS)} 之一，收到 {template!r}")
        from rfauto.adapters.openems_templates import eep_n_ports

        n_ports = int(eep_n_ports(template))
        work_root = request.get("work_root")
        if not work_root:
            raise ValueError("coupled_tier_solve 须给 work_root（EEP 轮转 run 根）")
        launch = bool(request.get("launch", True))
        solver_info: dict[str, Any] | None = None
        freq_ghz: Any = None
        s_mat: Any = None
        if launch:
            from rfauto.adapters.openems_rotation import solve_smatrix_openems

            fr = request.get("freq_range_ghz")
            if fr is None:
                raise ValueError("launch=True 须给 freq_range_ghz")
            res = solve_smatrix_openems(
                str(work_root), template=template,
                params=dict(request.get("params") or {}),
                freq_range_ghz=(float(fr[0]), float(fr[1])),
                mesh_resolution_mm=float(request.get("mesh_resolution_mm", 0.0)),
                n_ports=n_ports,
                timeout_s=int(request.get("timeout_s", 36000)),
                exe_path=request.get("exe_path"),
                cache=bool(request.get("cache", True)),
                resume=bool(request.get("resume", True)),
                line_z0=request.get("line_z0"),
                far_field=bool(request.get("far_field", True)))
            if not res.get("ok"):
                return {"ok": False,
                        "error": ("solve_smatrix_openems 失败："
                                  + "；".join(res.get("errors") or [])),
                        "solver": {"n_runs": res.get("n_runs"),
                                   "resumed_rounds": res.get("resumed_rounds")}}
            freq_ghz = np.asarray(res["freq_ghz"], dtype=float)
            s_mat = np.asarray(res["s_params"], dtype=complex)
            solver_info = {
                "message": res.get("message"),
                "elapsed_s": res.get("elapsed_s"),
                "resumed_rounds": res.get("resumed_rounds"),
                "assembly_norm": res.get("assembly_norm"),
                "s4p_path": res.get("s4p_path"),
                "far_field": bool(res.get("far_field", False)),
            }

        manifest = collect_eep_manifest([str(work_root)], n_ports,
                                        curve_refs=request.get("curve_refs"))
        if not manifest.get("ok"):
            return {"ok": False, "error": str(manifest.get("error"))}

        missing = [s["port"] for s in manifest["skipped"]
                   if s.get("kind") == "eep_curve"]
        if missing and not request.get("allow_partial"):
            return {"ok": False, "error": (
                f"EEP 曲线缺失端口 {missing}（#320 如实不猜；确需部分判读传 "
                "allow_partial=true，此时 Γ_act/Z_scan 可产出、方向图缺 EEP 不可叠 "
                "加）"), "manifest": manifest}

        if freq_ghz is None or s_mat is None:
            freq_ghz, s_mat = _load_smatrix_from_rounds(work_root, n_ports)
        freq_ghz = np.asarray(freq_ghz, dtype=float)
        s_mat = np.asarray(s_mat, dtype=complex)

        f0_ghz = float(request.get("f0_ghz", float(np.median(freq_ghz))))
        i0 = int(np.argmin(np.abs(freq_ghz - f0_ghz)))
        req, lay, ex, merged_params = _eep_tier_request(request, template,
                                                        f0_ghz)
        a = np.asarray(ex["excitations"], dtype=complex)
        z0 = float(request.get("z0_ohm", 50.0))

        # EEP 载入（全部端口同一角网格——轮间不同网格即显式报错，J4d）
        eeps: list[Any] = []
        grid_ref: tuple[Any, Any] | None = None
        for k in range(1, n_ports + 1):
            if int(k) in missing:
                eeps.append(None)
                continue
            path = Path(manifest["ports"][str(k)]["path"])
            th_k, ph_k, et_k, ep_k = parse_farfield_3d_cplx_csv(str(path))
            grid = (th_k, ph_k)
            if grid_ref is None:
                grid_ref = grid
            elif not (np.array_equal(grid_ref[0], th_k)
                      and np.array_equal(grid_ref[1], ph_k)):
                raise ValueError(
                    f"p{k} 远场角网格与 p1 不一致（轮间不同网格不可叠加，J4d）")
            eeps.append(et_k + ep_k)
        theta_deg, phi_deg = (grid_ref if grid_ref is not None
                              else (np.zeros(1), np.zeros(1)))
        have_all = not missing
        f_coupled: Any = None
        pattern_out: dict[str, Any] | None = None
        if have_all:
            eep_stack = np.stack(eeps, axis=0)   # (N, n_th, n_ph) 复
            f_coupled = eep_superposition(eep_stack, a)
            pdb = pattern_db(np.abs(f_coupled))
            flat = int(np.argmax(np.abs(f_coupled)))
            pattern_out = {
                "theta_deg": [float(v) for v in theta_deg],
                "phi_deg": [float(v) for v in phi_deg],
                "f_db": [[None if not np.isfinite(v) else float(v)
                          for v in row] for row in pdb],
                "peak_theta_deg": float(theta_deg[flat // phi_deg.size]),
                "peak_phi_deg": float(phi_deg[flat % phi_deg.size]),
                "superposition": "F(û)=ΣₙaₙEEPₙ(û)（core.array_scan."
                                 "eep_superposition；EEP 含全局原点位置相位）",
            }

        # Γ_act / Z_scan / σmax（数值全走 core.array_scan + numpy SVD）
        gamma_all = np.stack([active_reflection(s_mat[f], a)
                              for f in range(s_mat.shape[0])], axis=0)
        g0 = gamma_all[i0]
        z_vals = scan_impedance(g0, z0)
        z_out: list[list[float] | None] = []
        z_deg: list[int] = []
        for idx, zv in enumerate(np.atleast_1d(z_vals)):
            if not np.isfinite(zv.real) or not np.isfinite(zv.imag):
                z_out.append(None)
                z_deg.append(idx)
            else:
                z_out.append([float(zv.real), float(zv.imag)])
        sv_max = np.linalg.svd(s_mat, compute_uv=False)[:, 0]
        sig_max = float(sv_max.max())
        sigma_gate = {
            "limit": EEP_SIGMA_MAX_LIMIT,
            "max": sig_max,
            "median": float(np.median(sv_max)),
            "pass": bool(sig_max <= EEP_SIGMA_MAX_LIMIT),
            "basis": "LumpedPort 50Ω 基 raw 装配（line_z0=None；#250 MSL 线基"
                     "反演不适用——无三面探针，见 runs/df6_dp4p3/criteria.md J4a）",
            "criteria": "J4a runs/df6_dp4p3/criteria.md",
        }
        fast_cmp = (None if not have_all else _eep_fast_compare(
            template, request, lay, ex, merged_params, theta_deg, phi_deg,
            f_coupled, f0_ghz))

        positions_mm = (np.asarray(lay["positions_lambda"], dtype=float)
                        * (_C_MM_GHZ / f0_ghz))
        result: dict[str, Any] = {
            "tier": "coupled",
            "template": template,
            "n_ports": n_ports,
            "work_root": str(work_root),
            "launch": launch,
            "solver": solver_info,
            "manifest": manifest,
            "freq_ghz": [float(v) for v in freq_ghz],
            "f0_ghz": float(freq_ghz[i0]),
            "f0_index": i0,
            "layout": {"n_x": req["n_x"], "n_y": req["n_y"],
                       "spacing_x_lambda": req["spacing_x_lambda"],
                       "spacing_y_lambda": req["spacing_y_lambda"],
                       "positions_mm": [[float(px), float(py)]
                                        for px, py, _ in positions_mm]},
            "scan_deg": ex["scan_deg"],
            "scan_phi_deg": ex["scan_phi_deg"],
            "weights": [float(v) for v in lay["weights"]],
            "excitations": _cplx_pairs(a),
            "s_matrix_f0": _cplx_pairs(s_mat[i0].ravel()),  # 行主序展平 (N,N)
            "gamma_act_f0": _cplx_pairs(g0),
            "gamma_act_max_band": _cplx_pairs(
                gamma_all[int(np.argmax(np.abs(gamma_all).max(axis=1)))]),
            "z_scan_f0": z_out,
            "z_scan_degenerate_indices": z_deg,
            "z0_ohm": z0,
            "sigma_max_curve": [float(v) for v in sv_max],
            "sigma_max_gate": sigma_gate,
            "pattern": pattern_out,
            "fast_tier_compare": fast_cmp,
            "notes": [
                "Γ_act,n=Σ_m S_nm(a_m/a_n)（core.array_scan.active_reflection，"
                "行=观测口 列=激励口，#208 逐列装配同约定）",
                "EEPₙ 轮间可比前提=全同端口几何+同激励幅值（openems_templates "
                "§DP-4 P3 理论核验 2）；非均匀元尺寸阵不外推",
            ],
        }
        if missing:
            result["partial"] = {"missing_ports": missing,
                                 "pattern": None,
                                 "note": "EEP 缺失端口如实不猜（#320）"}
        if bool(request.get("include_s_matrix")):
            result["s_params"] = [
                _cplx_pairs(s_mat[f].ravel()) for f in range(s_mat.shape[0])]
        return {"ok": True, "result": result}
    except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}
