"""N7 qucsatorRF solve 服务薄壳（DP-14 §14.2；JSON 进出，CLI/MCP 是薄壳）。

两入口：
- :func:`solve_mline`：mline 名义点电路级求解（渲染→真跑→产物落盘）；
- :func:`solve_mline_three_way`：在其上叠加 β 三方对照
  （qucsator vs openEMS 金锚 vs HJ 闭式，tol_rel=0.05 Meep 先例口径）。

诚实口径（#122）：qucsator 用 KJ 色散、HJ 为准静态——两者之差含**物理
口径差**，verdict 里 ``kj_vs_hj_note`` 单独成账，不与适配器 bug 混写；
openEMS 腿用 runs/benchmark/mline_mauto 金锚冻结值（零仿真只读引用），
请求网格与金锚三点无精确交叠时如实 ``openems_leg="unavailable"`` 不硬凑。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from rfauto.adapters.qucsator_adapter import (
    QucsatorError,
    compare_beta_triad,
    openems_golden_beta_mline,
    qucsator_available,
    qucsator_version,
)
from rfauto.core.synthesis import Stackup

#: KJ vs HJ 口径差声明（随 verdict 返回，防消费方误读成数值 bug）。
_KJ_VS_HJ_NOTE = (
    "qucsator MLIN 物理模型 = Hammerstad 准静态 + Kirschning-Jansen 频率色散；"
    "HJ 腿（core.synthesis.forward_z0，skrf MLine hammerstadjensen）为纯准静态、"
    "无色散项。hj-qucsator pair 的互差含色散物理口径差，是模型口径差而非适配器 "
    "bug；openEMS 腿为全波金锚，是仲裁基准。"
)


def _stackup_from_dict(st: dict[str, Any] | None) -> Stackup:
    st = dict(st or {})
    try:
        from rfauto.adapters.meep_adapter import default_stackup
        anchor = default_stackup()
    except Exception:  # pragma: no cover —— meep 侧缺省不可得时字面量兜底
        anchor = Stackup(name="rogers4350b", epsilon_r=3.66, thickness_mm=0.508,
                         loss_tangent=0.0037)
    return Stackup(
        name=str(st.get("name", anchor.name)),
        epsilon_r=float(st.get("epsilon_r", anchor.epsilon_r)),
        thickness_mm=float(st.get("thickness_mm", anchor.thickness_mm)),
        loss_tangent=float(st.get("loss_tangent", anchor.loss_tangent)),
        rho=float(st.get("rho", anchor.rho)),
    )


def solve_mline(
    *,
    w_mm: float | None = None,
    line_len_mm: float | None = None,
    stackup: dict[str, Any] | None = None,
    freqs_ghz: list[float] | None = None,
    n_freq: int = 41,
    work_dir: str | None = None,
    exe: str | None = None,
    timeout_s: int = 600,
    z0_ref: float = 50.0,
) -> dict[str, Any]:
    """mline 名义点 qucsatorRF 电路级求解（JSON 进出）。

    缺省几何 = openEMS mline 锚同源（w=1.113mm rogers4350b / L=40mm）；
    缺省频点 = freq_range_ghz(1,5) 均匀 n_freq 点，或显式 freqs_ghz。
    返回 dict：ok/status/version/freqs_ghz/s11/s21/beta/epsilon_eff/artifacts/
    message；失败 ok=False + errors（不抛异常不静默）。
    """
    if not qucsator_available(exe):
        return {"ok": False, "status": "unavailable",
                "errors": ["qucsatorRF 不可用（RFAUTO_QUCSATOR_BIN / "
                           "configs/solvers.yaml qucsator / tools 或 E 盘安装点）"]}
    wd = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="rfauto_qucsator_"))
    wd.mkdir(parents=True, exist_ok=True)
    params: dict[str, float] = {}
    if w_mm is not None:
        params["w_mm"] = float(w_mm)
    if line_len_mm is not None:
        params["line_len_mm"] = float(line_len_mm)
    geometry: dict[str, Any] = {"template": "mline", "params": params,
                                "stackup": dict(stackup or {}),
                                "n_freq": int(n_freq), "z0_ref": float(z0_ref)}
    if freqs_ghz is not None:
        geometry["freqs_ghz"] = [float(f) for f in freqs_ghz]
    from rfauto.adapters.em_solver_base import EMSolverConfig
    from rfauto.adapters.qucsator_adapter import QucsatorAdapter
    config = EMSolverConfig(solver_type="qucsator", exe_path=exe,
                            working_dir=str(wd))
    solver = QucsatorAdapter(config)
    try:
        if not solver.connect():
            return {"ok": False, "status": "unavailable",
                    "errors": ["qucsatorRF 可执行解析失败（connect=False）"]}
        if not solver.build_geometry(geometry):
            reason = getattr(solver, "_last_error", None) or "build_geometry 失败"
            return {"ok": False, "status": "not_supported" if "NOT_SUPPORTED" in reason
                    else "build_failed", "errors": [reason]}
        result = solver.solve()
    except QucsatorError as exc:
        return {"ok": False, "status": "error", "errors": [f"{type(exc).__name__}: {exc}"]}
    if not result.success:
        return {"ok": False, "status": "solve_failed", "errors": [result.message]}
    fd = result.field_data or {}
    return {
        "ok": True,
        "status": "ok",
        "engine": "qucsator_rf",
        "version": qucsator_version(exe),
        "work_dir": str(wd),
        "freqs_ghz": [float(f) for f in result.freq_ghz],
        "s11": [[float(v.real), float(v.imag)] for v in result.s_params[:, 0, 0]],
        "s21": [[float(v.real), float(v.imag)] for v in result.s_params[:, 1, 0]],
        "beta_rad_per_m": [float(b) for b in fd.get("beta_rad_per_m", [])],
        "epsilon_eff": [float(e) for e in fd.get("epsilon_eff", [])],
        "params": {"w_mm": float(params.get("w_mm", 1.113)),
                   "line_len_mm": float(params.get("line_len_mm", 40.0)),
                   "stackup": _stackup_from_dict(stackup).name,
                   "disp_model": "Kirschning", "quasi_static_model": "Hammerstad"},
        "artifacts": {
            "netlist": str(wd / "qucsator_mline.net"),
            "dataset": str(wd / "qucsator_dataset.dat"),
            "sparams_csv": str(wd / "qucsator_sparams.csv"),
            "port_beta_csv": str(wd / "qucsator_port_beta.csv"),
            "touchstone": str(wd / "qucsator_mline.s2p"),
        },
        "message": result.message,
    }


def solve_mline_three_way(
    *,
    w_mm: float | None = None,
    line_len_mm: float | None = None,
    stackup: dict[str, Any] | None = None,
    freqs_ghz: list[float] | None = None,
    work_dir: str | None = None,
    exe: str | None = None,
    timeout_s: int = 600,
    tol_rel: float = 0.05,
) -> dict[str, Any]:
    """mline 名义点三方 β 对照（qucsator vs openEMS 金锚 vs HJ 闭式）。

    判据（runs/df6_dp14n7/criteria.md §4a）：max 两两互差 ≤ tol_rel
    （缺省 0.05，Meep 先例口径）。openEMS 腿 = 金锚冻结值
    （2.25/2.5/2.75 GHz），请求网格须与之精确交叠，否则该腿如实记
    unavailable（不插值硬凑）。
    """
    solve = solve_mline(w_mm=w_mm, line_len_mm=line_len_mm, stackup=stackup,
                        freqs_ghz=freqs_ghz, work_dir=work_dir, exe=exe,
                        timeout_s=timeout_s)
    if not solve.get("ok"):
        return {**solve, "threeway": None, "kj_vs_hj_note": _KJ_VS_HJ_NOTE}
    freqs = [float(f) for f in solve["freqs_ghz"]]
    beta_qucs = [float(b) for b in solve["beta_rad_per_m"]]
    st = _stackup_from_dict(stackup)
    w = float(solve["params"]["w_mm"])
    try:
        from rfauto.adapters.meep_adapter import hj_beta_series
        beta_hj = [float(b) for b in hj_beta_series(w, freqs, st)]
    except Exception as exc:
        beta_hj = []
        solve["errors"] = [*solve.get("errors", []), f"HJ 腿失败: {exc}"]

    golden = openems_golden_beta_mline()
    gold_pts = sorted(golden)
    overlap = [f for f in freqs if any(abs(f - g) < 1e-9 for g in gold_pts)]
    openems_status = "frozen_golden" if overlap else "unavailable"
    legs: dict[str, list[float]] = {"hj": beta_hj, "qucsator": beta_qucs}
    if overlap:
        idx = [freqs.index(f) for f in overlap]
        legs["openems"] = [golden[float(f)] for f in overlap]
        legs["hj"] = [beta_hj[i] for i in idx]
        legs["qucsator"] = [beta_qucs[i] for i in idx]
    if overlap and beta_hj:
        report = compare_beta_triad(overlap, legs, tol_rel=tol_rel)
        verdict = report.to_dict()
        verdict["openems_leg"] = openems_status
        verdict["kj_vs_hj_rel"] = verdict["per_pair_max_rel"].get("hj-qucsator")
    else:
        verdict = {"passed": False, "openems_leg": openems_status,
                   "reason": "openEMS 金锚网格无精确交叠（金锚点 2.25/2.5/2.75 GHz）"
                             if not overlap else "HJ 腿失败"}
    return {
        **solve,
        "threeway": {
            "verdict": verdict,
            "legs_ghz": overlap or freqs,
            "beta": {k: [float(x) for x in v] for k, v in legs.items() if v},
            "kj_vs_hj_note": _KJ_VS_HJ_NOTE,
        },
    }
