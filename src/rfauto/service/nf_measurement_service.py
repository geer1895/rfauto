"""近场测量 service：JSON 进出，CLI/MCP 壳共享（DP-18 C10a）。

数值只在确定性内核（铁律 7）：本模块只做参数校验、list→ndarray 转换与
异常到 JSON 信封的翻译，一切物理数字来自 core/nf_transform（平面波谱
加窗 FFT 近场→远场变换 + .ffs ASCII 逆工程 reader）。

信封契约（与 slotline_service 同族）：ok=False + error 字符串，绝不抛出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: 数值内核调用期可预期的异常族（参数不匹配/域拒绝/算术异常）——一律进信封
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError,
                ArithmeticError, OSError)


def nf_to_farfield(
    x_m: list[float],
    y_m: list[float],
    freq_hz: float,
    ex_re: list[list[float]],
    ex_im: list[list[float]],
    ey_re: list[list[float]],
    ey_im: list[list[float]],
    window: str = "kaiser",
    kaiser_beta: float = 6.0,
    theta_deg: list[float] | None = None,
    phi_deg: list[float] | None = None,
    z0_m: float = 0.0,
) -> dict[str, Any]:
    """平面近场栅格 → 远场方向图（dB 归一，JSON 可序列化）。

    复场以实/虚分列传入（JSON 无复数）；返回 pattern_db 为
    (n_theta, n_phi) 行主序嵌套列表，θ≥85°/谱支撑外为 null（如实 NaN）。
    """
    import numpy as np

    from rfauto.core.nf_transform import NearFieldGrid, planar_nf_to_farfield

    try:
        grid = NearFieldGrid(
            x_m=np.asarray(x_m, dtype=float),
            y_m=np.asarray(y_m, dtype=float),
            freq_hz=float(freq_hz),
            ex=np.asarray(ex_re, dtype=float) + 1j * np.asarray(ex_im,
                                                                dtype=float),
            ey=np.asarray(ey_re, dtype=float) + 1j * np.asarray(ey_im,
                                                                dtype=float),
            z0_m=float(z0_m),
        )
        th = None if theta_deg is None else np.asarray(theta_deg, dtype=float)
        ph = None if phi_deg is None else np.asarray(phi_deg, dtype=float)
        out = planar_nf_to_farfield(grid, window=window,
                                    kaiser_beta=float(kaiser_beta),
                                    theta_deg=th, phi_deg=ph)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}

    def _db_json(g: Any) -> list[list[float | None]]:
        return [[(round(float(v), 4) if v == v else None) for v in row]
                for row in g]

    def _amp_json(g: Any) -> list[list[float | None]]:
        return [[(round(float(abs(v)), 8) if v == v else None) for v in row]
                for row in g]

    return {
        "ok": True,
        "method": out["method"],
        "window": out["window"],
        "kaiser_beta": out["kaiser_beta"],
        "freq_hz": out["freq_hz"],
        "theta_deg": [float(t) for t in out["theta_deg"]],
        "phi_deg": [float(p) for p in out["phi_deg"]],
        "pattern_db": _db_json(out["pattern_db"]),
        "e_theta_amp": _amp_json(out["e_theta"]),
        "e_phi_amp": _amp_json(out["e_phi"]),
        "validity_max_deg": out["validity_max_deg"],
        "scan_span_m": list(out["scan_span_m"]),
        "note": out["note"],
    }


def ffs_info(path: str) -> dict[str, Any]:
    """.ffs 文件头视图（频率/三功率/网格规模/轴），不落全量复矩阵。"""
    from rfauto.core.nf_transform import read_ffs

    try:
        if not Path(path).is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}
        out = read_ffs(path, freq_index=0)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "reader_version": out["reader_version"],
        "path": str(path),
        "n_freq": out["n_freq"],
        "frequencies_hz": [float(f) for f in out["frequencies_hz"]],
        "power_first_block": out["power_radiated_accepted_stimulated"][0],
        "n_phi": int(out["phi_deg"].size),
        "n_theta": int(out["theta_deg"].size),
        "phi_deg_span": [float(out["phi_deg"][0]),
                         float(out["phi_deg"][-1])],
        "theta_deg_span": [float(out["theta_deg"][0]),
                           float(out["theta_deg"][-1])],
        "row_order": out["row_order"],
        "units_note": out["units_note"],
    }


def ffs_cut_view(path: str, freq_index: int = 0,
                 phi_deg: float | None = None,
                 theta_deg: float | None = None) -> dict[str, Any]:
    """.ffs 单频块切面视图（固定 phi 取 θ 扫描，或固定 θ 取 φ 扫描）。

    返回角度轴 + E_θ/E_φ 幅度与 dB（相对该切面峰值归一）；角度匹配 ±1e-6°。
    """
    import numpy as np

    from rfauto.core.nf_transform import farfield_pattern_db, read_ffs

    try:
        if not Path(path).is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}
        out = read_ffs(path, freq_index=int(freq_index))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    e_th = out["e_theta"][0]
    e_ph = out["e_phi"][0]
    phi_ax = out["phi_deg"]
    theta_ax = out["theta_deg"]
    if phi_deg is not None:
        j = int(np.argmin(np.abs(phi_ax - float(phi_deg))))
        if abs(phi_ax[j] - float(phi_deg)) > 1e-6:
            return {"ok": False,
                    "error": f"phi={phi_deg}° 不在采样轴上（最近 "
                             f"{float(phi_ax[j])}°）"}
        amp_th = np.abs(e_th[j, :])
        amp_ph = np.abs(e_ph[j, :])
        axis = theta_ax
        axis_name = "theta_deg"
        cut = f"phi={float(phi_ax[j])}deg"
    elif theta_deg is not None:
        i = int(np.argmin(np.abs(theta_ax - float(theta_deg))))
        if abs(theta_ax[i] - float(theta_deg)) > 1e-6:
            return {"ok": False,
                    "error": f"theta={theta_deg}° 不在采样轴上（最近 "
                             f"{float(theta_ax[i])}°）"}
        amp_th = np.abs(e_th[:, i])
        amp_ph = np.abs(e_ph[:, i])
        axis = phi_ax
        axis_name = "phi_deg"
        cut = f"theta={float(theta_ax[i])}deg"
    else:
        return {"ok": False,
                "error": "phi_deg/theta_deg 必须给一个（切面语义）"}
    amp_total = np.hypot(amp_th, amp_ph)
    db = farfield_pattern_db(amp_total)
    return {
        "ok": True,
        "reader_version": out["reader_version"],
        "freq_hz": float(out["frequencies_hz"][0]),
        "cut": cut,
        axis_name: [float(v) for v in axis],
        "e_theta_amp": [round(float(v), 8) for v in amp_th],
        "e_phi_amp": [round(float(v), 8) for v in amp_ph],
        "pattern_db": [None if v != v else round(float(v), 4)
                       for v in db],
        "units_note": out["units_note"],
    }
