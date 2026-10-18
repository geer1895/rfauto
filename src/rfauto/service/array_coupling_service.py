"""EC-24 服务层：单元胞互耦→阵列级传播管线（JSON 进出，铁律 4）。

编排 core/array_coupling（参数化互耦模型/任意几何耦合矩阵/一阶嵌入方向
图）+ core/array_scan（active_reflection/scan_impedance/tier_gate——DP-4
面零改动复用）+ core/array_synthesis（闭式单元方向图）。三个入口：

- ``unit_cell_coupling_pipeline``：单元胞互耦参数（指数模型或表值）→
  N×N 耦合矩阵 → Γ_act/Z_scan → 嵌入方向图 + 与无耦对照 → 门旗
  （扫 d/扫描角单点语义；批量扫 d×角走 ``coupling_sweep``）；
- ``fit_coupling_model_from_s_matrix``：实测/装配 S 矩阵 + 位置 → 指数
  互耦模型参数（ CouplingFit 报告 JSON 化）；
- ``coupling_sweep``：间距档 × 扫描角档 → 阵列级指标表（max|Γ_act|/
  互耦 dB/栅瓣旗/快档放行门）——EC-24"扫 d/扫描角"面。

CLI/MCP 接线不在本批授权面（后续薄壳批次）；本模块只服务层 JSON 进出。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core.array_coupling import (
    coupled_array_pattern,
    coupling_matrix_from_positions,
    effective_excitations,
    exponential_coupling,
    fit_exponential_coupling,
    tabulated_coupling,
)
from rfauto.core.array_scan import active_reflection, scan_impedance
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "coupling_sweep",
    "fit_coupling_model_from_s_matrix",
    "unit_cell_coupling_pipeline",
]

_C_MM_GHZ = 299.792458


def _cplx_pairs(arr) -> list[list[float]]:
    out = []
    for v in np.asarray(arr, dtype=complex).ravel():
        if np.isfinite(v.real) and np.isfinite(v.imag):
            out.append([float(v.real), float(v.imag)])
        else:
            out.append([None, None])
    return out


def _parse_cplx(value, label: str) -> complex:
    seq = list(value)
    if len(seq) != 2:
        raise ValueError(f"{label} 须为 [re, im] 二元组，收到 {value!r}")
    return complex(float(seq[0]), float(seq[1]))


def _build_positions(n_x: int, n_y: int, spacing_x_mm: float,
                     spacing_y_mm: float) -> np.ndarray:
    """行主序元心位置（mm→m）——与 array_service._build_layout 同序契约
    （行主序=端口次序，EEP 轮转同约定）。"""
    xs = (np.arange(n_x) - (n_x - 1) / 2.0) * float(spacing_x_mm)
    ys = (np.arange(n_y) - (n_y - 1) / 2.0) * float(spacing_y_mm)
    xx, yy = np.meshgrid(xs, ys)          # 行=y 序（行主序契约）
    return np.stack([xx.ravel(), yy.ravel()], axis=1) * 1e-3


def _coupling_model_of_d(request: dict, freq_hz: float):
    """request["coupling"] → c(d) 闭包（exponential | tabulated）。"""
    spec = request.get("coupling") or {}
    kind = str(spec.get("kind", "exponential"))
    if kind == "exponential":
        c0 = float(spec.get("c0", 0.15))
        xi_mm = float(spec.get("decay_len_mm", 30.0))
        ee = float(spec.get("eps_eff_phase", 2.5))
        return lambda d: exponential_coupling(
            d, freq_hz=freq_hz, c0=c0, decay_len_m=xi_mm * 1e-3,
            eps_eff_phase=ee), {"kind": kind, "c0": c0,
                                "decay_len_mm": xi_mm, "eps_eff_phase": ee}
    if kind == "tabulated":
        ds = np.asarray(spec.get("d_mm") or [], dtype=float)
        ms = np.asarray(spec.get("mag") or [], dtype=float)
        ps = np.asarray(spec.get("phase_deg") or [], dtype=float)
        if ds.size < 2:
            raise ValueError("tabulated 互耦须 ≥2 个扫距样本（d_mm/mag/"
                             "phase_deg 等长升序）")

        def _interp(d):
            mag, ph = tabulated_coupling(
                d, d_samples_m=ds * 1e-3, mag_samples=ms,
                phase_deg_samples=ps)
            return mag * np.exp(1j * ph)

        return _interp, {"kind": kind, "d_mm": ds.tolist(),
                         "mag": ms.tolist(), "phase_deg": ps.tolist()}
    raise ValueError(
        f"coupling.kind 须为 exponential|tabulated，收到 {kind!r}")



def _apply_scan(amp: np.ndarray, positions_m: np.ndarray, f0_ghz: float,
                scan_deg: float, scan_phi_deg: float) -> np.ndarray:
    th0 = np.radians(float(scan_deg))
    ph0 = np.radians(float(scan_phi_deg))
    u0 = np.array([np.sin(th0) * np.cos(ph0), np.sin(th0) * np.sin(ph0),
                   np.cos(th0)])
    k0 = 2.0 * np.pi * float(f0_ghz) * 1e9 / _C_MM_GHZ
    rdot = positions_m @ u0
    return amp * np.exp(1j * k0 * rdot)


def _element_patterns(request: dict, th: np.ndarray,
                      ph: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """孤立单元方向图（闭式，快档同源）：patch（Balanis 腔）| iso。"""
    elem = request.get("element") or {"kind": "iso"}
    kind = str(elem.get("kind", "iso"))
    if kind == "iso":
        et = np.ones((th.size, ph.size))
        ep = np.zeros((th.size, ph.size))
        return et, ep
    if kind == "patch":
        from rfauto.core.array_synthesis import patch_element_field

        thg = th[:, None] * np.ones((1, ph.size))
        phg = ph[None, :] * np.ones((th.size, 1))
        axis = str(elem.get("axis", "y"))
        # 闭式单元域守卫（array_synthesis 地面上半空间）：地平线以下夹到
        # 0° 求值后置零——与 array_service._eep_fast_compare 同口径
        upper = thg <= 90.0 + 1e-9
        th_eval = np.where(upper, thg, 0.0)
        et = np.asarray(patch_element_field(
            th_eval, phg, len_mm=float(elem["len_mm"]),
            width_mm=float(elem["width_mm"]), freq_ghz=float(
                elem.get("freq_ghz", request.get("f0_ghz"))),
            axis=axis, component="theta"), dtype=float)
        ep = np.asarray(patch_element_field(
            th_eval, phg, len_mm=float(elem["len_mm"]),
            width_mm=float(elem["width_mm"]), freq_ghz=float(
                elem.get("freq_ghz", request.get("f0_ghz"))),
            axis=axis, component="phi"), dtype=float)
        return np.where(upper, et, 0.0), np.where(upper, ep, 0.0)
    raise ValueError(f"element.kind 须为 iso|patch，收到 {kind!r}")


def _pattern_metrics(f: np.ndarray, th: np.ndarray,
                     ph: np.ndarray) -> dict[str, Any]:
    pdb = 20.0 * np.log10(np.maximum(np.abs(f), 1e-300))
    flat = int(np.argmax(np.abs(f)))
    n_ph = ph.size
    peak_db = float(pdb.flat[flat])
    return {
        "peak_db": peak_db,
        "peak_theta_deg": float(th[flat // n_ph]),
        "peak_phi_deg": float(ph[flat % n_ph]),
    }


def _deviation_report(f_c, f_u, th, ph, floor_db: float = -40.0,
                      hemisphere_upper: bool = True) -> dict[str, Any]:
    """嵌入 vs 无耦方向图偏差报告（J4b 同口径：统计域=上半球+峰值下地板；
    报告非硬阈，#122 如实）。"""
    fc_db = 20.0 * np.log10(np.maximum(np.abs(f_c), 1e-300))
    fu_db = 20.0 * np.log10(np.maximum(np.abs(f_u), 1e-300))
    thg = th[:, None] * np.ones((1, ph.size))
    mask = np.isfinite(fc_db) & np.isfinite(fu_db)
    if hemisphere_upper:
        mask &= thg <= 90.0 + 1e-9
    peak = float(fc_db.max())
    mask &= fc_db > peak + float(floor_db)
    n_pts = int(np.count_nonzero(mask))
    if n_pts < 1:
        return {"n_points": 0, "floor_db": float(floor_db),
                "note": "统计域为空"}
    dev = (fc_db - fu_db)[mask]
    return {
        "n_points": n_pts,
        "floor_db": float(floor_db),
        "dev_db_median": float(np.median(dev)),
        "dev_db_p95": float(np.percentile(dev, 95)),
        "dev_db_max_abs": float(np.abs(dev).max()),
        "criteria": "报告门（互耦方向图偏离 1-3dB 级预期；如实报告不设硬阈，"
                    "J4b 判据书归档同口径）",
    }


def unit_cell_coupling_pipeline(request: dict) -> dict[str, Any]:
    """EC-24 主入口：单元胞互耦参数 → 阵列级（耦合矩阵/Γ_act/嵌入方向图）。

    请求 schema（JSON 友好，全部可选键有缺省）::

        n_x/n_y                阵格（缺省 2×2）
        spacing_x_mm/spacing_y_mm  元间距（缺省 25.0；可被 spacing_mm 覆盖）
        f0_ghz                 工作频率（必填）
        coupling.kind          exponential（c0/decay_len_mm/eps_eff_phase）
                               | tabulated（d_mm[]/mag[]/phase_deg[]）
        element.kind           iso | patch（len_mm/width_mm[/axis]）
        amplitude_law          uniform | cosine（缺省 uniform）
        custom_weights         (N,) 实权（优先于 amplitude_law）
        scan_deg/scan_phi_deg  扫描角（缺省 0）
        s11_diag_re/s11_diag_im  孤立元反射（缺省 −10dB 实数 −0.1）
        theta_deg/phi_deg      角网格（缺省 0:5:180 / 0:5:359）
        include_pattern        True 时带全方向图网格（缺省只带摘要）
        include_s_matrix       True 时带耦合矩阵（缺省带，小阵面）
    """
    try:
        f0_ghz = float(request["f0_ghz"])
        if not (np.isfinite(f0_ghz) and f0_ghz > 0.0):
            raise ValueError(f"f0_ghz 须为正有限，收到 {request['f0_ghz']!r}")
        n_x = int(request.get("n_x", 2))
        n_y = int(request.get("n_y", 2))
        if n_x < 1 or n_y < 1 or n_x * n_y < 2:
            raise ValueError("n_x/n_y 须 ≥1 且 N=n_x·n_y ≥2")
        spacing_mm = request.get("spacing_mm")
        sx = float(request.get("spacing_x_mm",
                               spacing_mm if spacing_mm is not None else 25.0))
        sy = float(request.get("spacing_y_mm",
                               spacing_mm if spacing_mm is not None else sx))
        if sx <= 0.0 or sy <= 0.0:
            raise ValueError(f"间距须为正，收到 {sx!r}/{sy!r}")
        n = n_x * n_y
        positions = _build_positions(n_x, n_y, sx, sy)
        # 衬 z=0 列（core 面接受 (N,2)|(N,3)；扫描相位记账须 (N,3)）
        positions = np.concatenate([positions,
                                    np.zeros((n, 1))], axis=1)
        freq_hz = f0_ghz * 1e9

        model_of_d, model_spec = _coupling_model_of_d(request, freq_hz)
        s11 = complex(float(request.get("s11_diag_re", -0.1)),
                      float(request.get("s11_diag_im", 0.0)))
        s_mat = coupling_matrix_from_positions(positions, model_of_d,
                                               s11_diag=s11)

        weights = request.get("custom_weights")
        if weights is not None:
            w = np.asarray(weights, dtype=float)
            if w.shape != (n,):
                raise ValueError(
                    f"custom_weights 须为 ({n},)，收到 {w.shape}")
            amp = w.astype(complex)
        else:
            law = str(request.get("amplitude_law", "uniform"))
            if law == "uniform":
                amp = np.ones(n, dtype=complex)
            elif law == "cosine":
                wy = np.cos(np.linspace(
                    -np.pi / 2 * (n_y - 1) / max(n_y, 2),
                    np.pi / 2 * (n_y - 1) / max(n_y, 2), n_y))
                amp = np.tile(wy, n_x).astype(complex)
            else:
                raise ValueError(
                    f"amplitude_law 须为 uniform|cosine，收到 {law!r}")
        scan_deg = float(request.get("scan_deg", 0.0))
        scan_phi_deg = float(request.get("scan_phi_deg", 0.0))
        a = _apply_scan(amp, positions, f0_ghz, scan_deg, scan_phi_deg)

        # 阵列级传播量（core.array_scan 零改动复用：行=观测口 列=激励口）
        gamma = active_reflection(s_mat, a)
        z_scan = scan_impedance(gamma, 50.0)
        a_eff = effective_excitations(a, s_mat)
        coupling_db = 20.0 * np.log10(max(
            float(np.max(np.abs(s_mat - np.diag(np.diag(s_mat))))), 1e-300))

        th = np.asarray(request.get("theta_deg",
                                    np.arange(0.0, 180.0, 5.0)), dtype=float)
        ph = np.asarray(request.get("phi_deg",
                                    np.arange(0.0, 360.0, 5.0)) % 360.0,
                        dtype=float)
        et, ep = _element_patterns(request, th, ph)
        f_t, _f_p = coupled_array_pattern(
            positions, a, elem_pattern_theta=et, elem_pattern_phi=ep,
            theta_deg=th, phi_deg=ph, freq_hz=freq_hz, s_matrix=s_mat)
        f_t0, _f_p0 = coupled_array_pattern(
            positions, a, elem_pattern_theta=et, elem_pattern_phi=ep,
            theta_deg=th, phi_deg=ph, freq_hz=freq_hz, s_matrix=None)
        # 无耦对照的 AF 面用同单元同激励（零耦极限恒等在 core 已钉）

        # 快档放行门（tier_gate 零改动复用；spacing=min(dx,dy)/λ 口径）
        from rfauto.core.array_scan import tier_gate

        gate = tier_gate(
            min(sx, sy) / (_C_MM_GHZ / f0_ghz), abs(scan_deg),
            u0=float(np.sin(np.radians(scan_deg))
                     * np.cos(np.radians(scan_phi_deg))),
            coupling_db=float(coupling_db))

        result: dict[str, Any] = {
            "tier": "coupled_model",
            "n_x": n_x, "n_y": n_y, "n": n,
            "f0_ghz": f0_ghz,
            "spacing_x_mm": sx, "spacing_y_mm": sy,
            "spacing_lambda": min(sx, sy) / (_C_MM_GHZ / f0_ghz),
            "positions_mm": [[float(row[0] * 1e3), float(row[1] * 1e3)]
                             for row in positions],
            "coupling_model": model_spec,
            "s_matrix": _cplx_pairs(s_mat),
            "excitations": _cplx_pairs(a),
            "effective_excitations": _cplx_pairs(a_eff),
            "gamma_act": _cplx_pairs(gamma),
            "z_scan": [[float(v.real), float(v.imag)]
                       if np.isfinite(v.real) and np.isfinite(v.imag)
                       else [None, None] for v in np.atleast_1d(z_scan)],
            "coupling_max_db": float(coupling_db),
            "pattern_coupled": _pattern_metrics(f_t, th, ph),
            "pattern_uncoupled": _pattern_metrics(f_t0, th, ph),
            "deviation_report": _deviation_report(f_t, f_t0, th, ph),
            "tier_gate": gate,
            "notes": [
                "一阶多重散射嵌入模型：a_eff=(I+S)·a，F=E_iso·Σ a_eff,m·"
                "exp(j·k0·r̂·r_m)（core.array_coupled；S→0 精确退化快档）",
                "Γ_act/Z_scan 数值面=core.array_scan 零改动复用（行=观测口 "
                "列=激励口，#208 同约定）",
            ],
        }
        if bool(request.get("include_pattern")):
            result["pattern_grid"] = {
                "theta_deg": th.tolist(), "phi_deg": ph.tolist(),
                "f_coupled_db": [[None if not np.isfinite(v) else float(v)
                                  for v in row]
                                 for row in 20.0 * np.log10(
                                     np.maximum(np.abs(f_t), 1e-300))],
            }
        return ok_envelope(result=result)
    except (ValueError, TypeError, KeyError) as exc:
        return error_envelope([str(exc)])


def fit_coupling_model_from_s_matrix(request: dict) -> dict[str, Any]:
    """实测/装配 S 矩阵 + 元位置 → 指数互耦模型参数（拟合报告 JSON）。

    请求::

        s_matrix        (N,N) 复 [re,im] 行主序展平或嵌套（嵌套=逐元
                        [re,im] 的 (N,N,2) 列表，两形态等价受理）
        positions_mm    (N,2)|(N,3) 元心位置
        f0_ghz          拟合频率
    """
    try:
        raw = request["s_matrix"]
        arr = np.asarray(raw, dtype=float)
        if arr.ndim == 3:
            # 嵌套形态（docstring 第二承诺，W6-S26 P1-1 补受理）：行主序
            # 语义与展平等价，受理后走同一拟合链
            if arr.shape[0] != arr.shape[1] or arr.shape[2] != 2:
                raise ValueError(
                    "s_matrix 嵌套形态须为 (N,N,2) 逐元 [re,im]，收到 "
                    f"shape {arr.shape}")
            flat = [complex(x, y) for x, y in arr.reshape(-1, 2)]
        else:
            flat = [complex(x, y) for x, y in raw]
        n = round(len(flat) ** 0.5)
        if n * n != len(flat):
            raise ValueError("s_matrix 须为完全平方长度的 [re,im] 展平")
        s = np.array(flat, dtype=complex).reshape(n, n)
        pos = np.asarray(request["positions_mm"], dtype=float) * 1e-3
        if pos.shape[0] != n:
            raise ValueError(
                f"positions_mm 首维须 =N={n}，收到 {pos.shape}")
        f0_ghz = float(request["f0_ghz"])
        fit = fit_exponential_coupling(s, pos, freq_hz=f0_ghz * 1e9)
        return ok_envelope(result={
            "c0": fit.c0,
            "decay_len_mm": (None if not np.isfinite(fit.decay_len_m)
                             else float(fit.decay_len_m * 1e3)),
            "k_eff_rad_per_m": fit.k_eff_rad_per_m,
            "eps_eff_implied": fit.eps_eff_implied,
            "mag_resid_max_abs": fit.mag_resid_max_abs,
            "phase_resid_max_rad": fit.phase_resid_max_rad,
            "n_pairs": fit.n_pairs,
            "distances_mm": [d * 1e3 for d in fit.distances_m],
            "degenerate": fit.degenerate,
            "notes": [
                "幅度拟合 ln|c|-d 线性 LS；相位=相干度网格搜（缠绕免 unwrap）",
                "degenerate=true 时幅度拟合零自由度（零残差属构造性非验证）",
            ],
        })
    except (ValueError, TypeError, KeyError) as exc:
        return error_envelope([str(exc)])


def coupling_sweep(request: dict) -> dict[str, Any]:
    """扫间距 × 扫描角 → 阵列级指标表（EC-24"扫 d/扫描角"面）。

    请求在 pipeline schema 基础上增加::

        spacings_mm       [float] 间距档列表（≥1，各档为各向同性间距）
        scan_deg_list     [float] 扫描角档列表（≥1）
    """
    try:
        spacings = [float(v) for v in (request.get("spacings_mm") or [])]
        scans = [float(v) for v in (request.get("scan_deg_list") or [])]
        if not spacings or not scans:
            raise ValueError("spacings_mm/scan_deg_list 均须 ≥1 档")
        rows: list[dict[str, Any]] = []
        for sp in spacings:
            for sc in scans:
                req = dict(request)
                req["spacing_mm"] = float(sp)
                req["scan_deg"] = float(sc)
                req["include_pattern"] = False
                out = unit_cell_coupling_pipeline(req)
                if not out.get("ok"):
                    return out
                r = out["result"]
                gamma_pairs = r["gamma_act"]
                # 非有限 gamma（序列化口径 [None,None]，模型域外）显式置
                # None+行内注记，不依赖 TypeError 兜底（W6-S26 P2-1；与
                # pipeline 的 [None,None] 输出口径一致）
                nonfinite = any(p[0] is None or p[1] is None
                                for p in gamma_pairs)
                row: dict[str, Any] = {
                    "spacing_mm": float(sp),
                    "scan_deg": float(sc),
                    "gamma_act_max_abs": (
                        None if nonfinite else float(np.max(np.abs(
                            [complex(p[0], p[1]) for p in gamma_pairs])))),
                    "coupling_max_db": r["coupling_max_db"],
                    "tier": r["tier_gate"]["tier"],
                    "invalid_fast_tier": bool(
                        r["tier_gate"]["invalid_fast_tier"]),
                    "grating_lobes": r["tier_gate"]["checks"][
                        "grating_lobe_free"]["lobes"],
                }
                if nonfinite:
                    row["gamma_note"] = (
                        "gamma_act 含非有限元（序列化为 [None,None]，模型"
                        "域外）——max|Γ_act| 如实置 None 不猜测")
                rows.append(row)
        return ok_envelope(result={
            "rows": rows,
            "n_rows": len(rows),
            "f0_ghz": float(request["f0_ghz"]),
            "criteria": "扫描表（报告面：Γ_act/互耦/栅瓣旗逐档可分辨；"
                        "EC-24 扫 d/扫描角传播口径）",
        })
    except (ValueError, TypeError, KeyError) as exc:
        return error_envelope([str(exc)])
