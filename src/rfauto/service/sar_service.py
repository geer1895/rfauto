"""SAR 后处理 service：JSON 进出，CLI/MCP 壳共享（DP-18 C10c）。

数值只在确定性内核（铁律 7）：一切物理数字来自 core/sar（点值
σ|E|²/(2ρ) + IEC/IEEE 62704-1 固定质量立方 1g/10g 平均 + 峰值定位 +
分布），本模块只做 list→ndarray、phantom 规格构建与异常到 JSON 信封的
翻译。Virtual Family 需 IT'IS 许可——资产边界不支持（拒绝路径随信封
ok=False 返回）。

信封契约（与 slotline_service 同族）：ok=False + error 字符串，绝不抛出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: 数值内核调用期可预期的异常族——一律进信封
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError,
                ArithmeticError, OSError)


def _normalize_phantom_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """layer dict（z_lo/z_hi/sigma/rho/name）→ build_phantom 元组口径。"""
    norm: dict[str, Any] = dict(spec)
    if str(spec.get("kind", "")).lower() == "layered" and "layers" in spec:
        tuples = []
        for t in spec["layers"]:
            if isinstance(t, dict):
                tuples.append((float(t["z_lo"]), float(t["z_hi"]),
                               float(t["sigma"]), float(t["rho"]),
                               str(t.get("name", ""))))
            else:
                tuples.append(tuple(t))
        norm["layers"] = tuples
    return norm


def sar_report_from_grid(
    e_re: list[list[list[float]]],
    e_im: list[list[list[float]]],
    sigma: list[list[list[float]]] | float,
    rho: list[list[list[float]]] | float,
    voxel_m: list[float] | float,
    mass_g_list: list[float] | None = None,
    phantom_spec: dict[str, Any] | None = None,
    z_axis_m: list[float] | None = None,
) -> dict[str, Any]:
    """SAR 合规报告（E 相量网格 → 点值 + 1g/10g 立方平均 + 峰值 + 分布）。

    E 以实/虚分列传入（峰值相量 V/m；RMS 输入请调用方先 ×√2）。
    σ/ρ 给标量（均匀）或全网格；或给 phantom_spec（uniform/layered）+
    z_axis_m（分层必需）。mass_g_list 缺省 [1, 10]。
    """
    import numpy as np

    from rfauto.core.sar import build_phantom, phantom_props_grid, sar_pointwise, sar_report

    try:
        e = (np.asarray(e_re, dtype=float)
             + 1j * np.asarray(e_im, dtype=float))
        if e.ndim != 3:
            raise ValueError(f"E 网格须 3D，收到 shape={e.shape}")
        shape = e.shape
        if phantom_spec is not None:
            ph = build_phantom(_normalize_phantom_spec(phantom_spec))
            z_ax = (None if z_axis_m is None
                    else np.asarray(z_axis_m, dtype=float))
            sig, r = phantom_props_grid(ph, shape, z_ax)
        else:
            sig = (np.full(shape, float(sigma))
                   if np.isscalar(sigma) or isinstance(sigma, (int, float))
                   else np.asarray(sigma, dtype=float))
            r = (np.full(shape, float(rho))
                 if np.isscalar(rho) or isinstance(rho, (int, float))
                 else np.asarray(rho, dtype=float))
        sar = sar_pointwise(sig, e, r)
        voxel = (float(voxel_m) if np.isscalar(voxel_m)
                 or isinstance(voxel_m, (int, float))
                 else tuple(float(v) for v in voxel_m))
        masses = tuple(float(g) * 1e-3 for g in (mass_g_list or [1.0, 10.0]))
        out = sar_report(sar, r, voxel, mass_kg_list=masses)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **out}


def sar_analytic_plane_wave(
    freq_hz: float, e0_v_per_m: float, sigma_s_per_m: float,
    epsilon_r: float, rho_kg_m3: float, depth_m: list[float],
    mass_g: float = 1.0,
) -> dict[str, Any]:
    """有耗半空间平面波 SAR 闭式对照面（判据锚，独立于场合成）。

    α = ω√(με/2)·[√(1+tan²δ)−1]^{1/2}，SAR(z)=σ|E₀|²e^{−2αz}/(2ρ)；
    另给 depth 处 mass_g 立方平均的解析预期（均匀场档 → 等于点值）。
    """
    import math

    import numpy as np

    from rfauto.core.sar import cube_side_m, sar_pointwise

    try:
        w = 2.0 * math.pi * float(freq_hz)
        eps0 = 8.854187817e-12
        mu0 = 4.0e-7 * math.pi
        eps = eps0 * float(epsilon_r)
        td = float(sigma_s_per_m) / (w * eps)
        alpha = w * math.sqrt(mu0 * eps / 2.0) \
            * math.sqrt(math.sqrt(1.0 + td * td) - 1.0)
        z = np.asarray(depth_m, dtype=float)
        e_amp = float(e0_v_per_m) * np.exp(-alpha * z)
        sar = sar_pointwise(float(sigma_s_per_m), e_amp.astype(complex),
                            float(rho_kg_m3))
        side = cube_side_m(float(mass_g) * 1e-3, float(rho_kg_m3))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "alpha_np_per_m": float(alpha),
        "tan_delta": float(td),
        "depth_m": [float(v) for v in z],
        "sar_w_per_kg": [float(v) for v in sar],
        "cube_side_m": float(side),
        "note": "均匀媒质内固定质量立方平均==点值（解析恒等）；体表出体"
                "场景见 core/sar coverage 注记",
    }


def sar_phantom_spec(kind: str, sigma: float | None = None,
                     rho: float | None = None,
                     layers: list[dict[str, float | str]] | None = None,
                     ) -> dict[str, Any]:
    """phantom 规格校验器（uniform/layered；Virtual Family 显式拒绝）。"""
    from rfauto.core.sar import build_phantom

    spec: dict[str, Any] = {"kind": str(kind)}
    if sigma is not None:
        spec["sigma"] = float(sigma)
    if rho is not None:
        spec["rho"] = float(rho)
    if layers is not None:
        spec["layers"] = layers
    try:
        ph = build_phantom(_normalize_phantom_spec(spec))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    if hasattr(ph, "layers"):
        return {"ok": True, "kind": "layered",
                "layers": [list(t) for t in ph.layers]}
    return {"ok": True, "kind": "uniform", "sigma": ph.sigma, "rho": ph.rho}


def sar_load_field_npz(path: str) -> dict[str, Any]:
    """读取 npz 场网格（键 e_re/e_im/sigma/rho/voxel_m）→ sar_report。

    产物契约：.npz 由调用方/求解器 dump 路径落盘（本函数只读）；缺键
    显式报错（不静默兜底）。
    """
    import numpy as np

    from rfauto.core.sar import sar_pointwise, sar_report

    try:
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}
        data = np.load(p)
        missing = [k for k in ("e_re", "e_im", "rho") if k not in data]
        if missing:
            return {"ok": False, "error": f"npz 缺键: {missing}"}
        e = data["e_re"] + 1j * data["e_im"]
        rho = data["rho"]
        sigma = (data["sigma"] if "sigma" in data
                 else np.full(e.shape, 1.0))
        voxel = (tuple(float(v) for v in data["voxel_m"])
                 if "voxel_m" in data else 1e-3)
        sar = sar_pointwise(sigma, e, rho)
        out = sar_report(sar, rho, voxel)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(path), **out}
