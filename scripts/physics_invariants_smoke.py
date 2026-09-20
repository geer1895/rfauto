"""G15 Maxwell 尺度律 openEMS 真机冒烟（脚本，不入单测）。

对 1 个最轻模板（mline，2 端口均匀微带线）做真机尺度律元变：
**几何 ×k、频率 ÷k、材料不变 → S 参数不变**。

几何缩放口径（关键）：
- 参数级：线宽 w_mm ×k、线长 line_len_mm ×k、基板厚 h_mm ×k（横截面
  与纵向同时缩放 → 结构自相似，材料 er/tanδ 不变）；
- 频段：(f_lo, f_hi) ÷k；
- 网格：mesh_resolution_mm=0（官方自动 base=λ_sub/50）；频段 ÷k 使
  f_max ÷k → base 自动 ×k，与几何缩放同步（自相似离散）；
- **渲染脚本级**：openEMS 模板把板边硬编码为 BOARD=60e-3（域边界/端口
  面），另有固定 AIR_TOP=5e-3。真正"几何 ×k"必须把这两者也 ×k——本脚本
  在 solver.build_geometry() 之后、solve() 之前对生成的 simulation.py 做
  一次性常量替换（各断言恰好命中 1 处），否则端口馈线电长度不随 k 缩，
  尺度律在测量面上不成立。

判据：两次运行在对应频点（同 401 点、标称 = k × 缩放）逐点比较
max|ΔS11|、max|ΔS21|、max|ΔS| ≤ 网格误差量级阈值 MESH_ERROR_TOL。
产物：runs/invariants/scale_law_openems_smoke.json（真实输出，含耗时）。

openEMS 不可用 / 单次运行超时或失败 / |ΔS| 超阈：如实写入 json 的 status
与 notes，**不伪造绿**（任务硬约束 5）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(REPO / "src"))

from rfauto.adapters.em_solver_base import (  # noqa: E402
    EMSolverConfig,
    resolve_openems_exe,
)
from rfauto.adapters.openems_solver import OpenEMSSolver  # noqa: E402

TEMPLATE = "mline"
K = 2.0
# 标称设计点（TEMPLATE_NOMINAL['mline'] 与模板默认一致）
BASE_PARAMS = {"w_mm": 1.113, "line_len_mm": 40.0}
SUB_ER, SUB_H_MM, SUB_TAND = 3.66, 0.508, 0.0037
FREQ_NOMINAL = (2.25, 2.75)
# 网格：0 = 官方自动口径 base=λ_sub/50（render_script 内按 f_max 计算）。
# 频段 ÷k 时 λ_sub ×k → base/NEAR 自动 ×k，与几何缩放同步（自相似离散）。
# 实测：显式粗网格 base=2mm 会把 MSLPort 参考面打坏（|S11|≈0.94、非被动），
# 故采用官方自动网格（已验证锚点 |S11|≈−30dB）。
MESH_NOMINAL_MM = 0.0
RUN_TIMEOUT_S = 900  # 单次 15 分钟硬门（预声明）
# 网格误差量级阈值（|S| 绝对值）：自相似离散下两端口的数值色散/去嵌残差
# 量级上限，取 0.05（≈ −26dB）。
MESH_ERROR_TOL = 0.05

OUT_JSON = REPO / "runs" / "invariants" / "scale_law_openems_smoke.json"


def _scaled_inputs(k: float) -> tuple[dict[str, Any], dict[str, Any], tuple, float, float]:
    params = {key: value * k for key, value in BASE_PARAMS.items()}
    substrate = {"er": SUB_ER, "h_mm": SUB_H_MM * k, "tan_d": SUB_TAND}
    freq = (FREQ_NOMINAL[0] / k, FREQ_NOMINAL[1] / k)
    mesh_mm = MESH_NOMINAL_MM * k
    return params, substrate, freq, mesh_mm, 60e-3 * k


def _run_case(
    tag: str, k: float, board_scale_m: float, air_top_m: float
) -> dict[str, Any]:
    params, substrate, freq, mesh_mm, board_m = _scaled_inputs(k)
    work = REPO / "runs" / "invariants" / f"openems_{TEMPLATE}_{tag}"
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=freq,
        mesh_resolution_mm=mesh_mm,
        extra_params={"solve_timeout_s": RUN_TIMEOUT_S}))

    t0 = time.time()
    build_ok = solver.connect() and solver.build_geometry(
        {"template": TEMPLATE, "params": params, "substrate": substrate})

    # ── 脚本级几何缩放：BOARD / AIR_TOP 也必须 ×k ──────────────────────────
    script_path = work / "simulation.py"
    text = script_path.read_text(encoding="utf-8")
    n_board = text.count("BOARD = 60e-3")
    n_air = text.count("AIR_TOP = 0.005")
    assert n_board == 1, f"BOARD 常量定位失败（命中 {n_board} 次）"
    assert n_air == 1, f"AIR_TOP 常量定位失败（命中 {n_air} 次）"
    text = text.replace("BOARD = 60e-3", f"BOARD = {board_m!r}")
    text = text.replace("AIR_TOP = 0.005", f"AIR_TOP = {air_top_m!r}")
    script_path.write_text(text, encoding="utf-8")

    result = solver.solve()
    elapsed = time.time() - t0
    record: dict[str, Any] = {
        "tag": tag, "k": k, "build_ok": bool(build_ok),
        "success": bool(result.success), "message": result.message,
        "elapsed_s": round(elapsed, 2), "params": params,
        "substrate": substrate, "freq_range_ghz": list(freq),
        "mesh_resolution_mm": mesh_mm, "board_m": board_m,
        "work_dir": str(work.relative_to(REPO)),
    }
    if not result.success or result.s_params is None:
        record["status"] = "failed"
        return record
    s = np.asarray(result.s_params, dtype=complex)
    record["n_freq"] = int(s.shape[0])
    record["s11_max_abs"] = float(np.max(np.abs(s[:, 0, 0])))
    record["s21_mean_abs"] = float(np.mean(np.abs(s[:, 1, 0])))
    record["freq_first_last_ghz"] = [
        float(np.asarray(result.freq_ghz)[0]), float(np.asarray(result.freq_ghz)[-1])]
    return record


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "item": "g15-invariants",
        "kind": "openems_scale_law_smoke",
        "template": TEMPLATE,
        "k": K,
        "law": "geometry *k, freq /k, material unchanged -> S unchanged",
        "tolerance_abs_S": MESH_ERROR_TOL,
        "tolerance_note": (
            "官方自动网格 base=λ_sub/50（随 f_max 自动 ×k，与几何缩放同步=自相似"
            "离散）；阈值取数值色散+端口去嵌残差量级 0.05（|S| 绝对）"),
        "scale_note": (
            "BOARD=60e-3 与 AIR_TOP=5e-3 为模板硬编码常量，本脚本在渲染后"
            "一次性替换并断言各恰好 1 处，保证整结构（含域边界与端口馈线）"
            "自相似"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    exe = resolve_openems_exe()
    if not exe or not Path(exe).exists():
        payload["status"] = "unavailable"
        payload["notes"] = f"openEMS 不可用: {exe!r}"
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"openEMS unavailable: {exe!r} -> {OUT_JSON}")
        return 0

    payload["openems_exe"] = str(exe)
    try:
        nominal = _run_case("nominal_k1", 1.0, 60e-3, 5e-3)
        scaled = _run_case("scaled_k2", K, 60e-3 * K, 5e-3 * K)
    except Exception as exc:  # 冒烟如实记录失败，不伪造绿
        payload["status"] = "failed"
        payload["notes"] = f"运行异常: {type(exc).__name__}: {exc}"
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"smoke FAILED: {exc!r} -> {OUT_JSON}")
        return 0

    payload["nominal"] = nominal
    payload["scaled"] = scaled

    if nominal.get("status") == "failed" or scaled.get("status") == "failed":
        payload["status"] = "failed"
        payload["notes"] = (
            f"真机求解失败: nominal={nominal.get('message')!r} "
            f"scaled={scaled.get('message')!r}")
    else:
        # 对应频点比较：两段频段同为 401 点 linspace，标称频点 = k × 缩放频点
        work_n = REPO / nominal["work_dir"]
        work_s = REPO / scaled["work_dir"]
        raw_n = np.genfromtxt(work_n / "sparams.csv", delimiter=",",
                              names=True, dtype=complex)
        raw_s = np.genfromtxt(work_s / "sparams.csv", delimiter=",",
                              names=True, dtype=complex)
        s11_n = np.asarray(raw_n["re_S11"]) + 1j * np.asarray(raw_n["im_S11"])
        s21_n = np.asarray(raw_n["re_S21"]) + 1j * np.asarray(raw_n["im_S21"])
        s11_s = np.asarray(raw_s["re_S11"]) + 1j * np.asarray(raw_s["im_S11"])
        s21_s = np.asarray(raw_s["re_S21"]) + 1j * np.asarray(raw_s["im_S21"])
        n = min(len(s11_n), len(s11_s))
        d11 = float(np.max(np.abs(s11_n[:n] - s11_s[:n])))
        d21 = float(np.max(np.abs(s21_n[:n] - s21_s[:n])))
        dmax = max(d11, d21)
        payload["compare"] = {
            "n_points": n, "max_dS11": d11, "max_dS21": d21,
            "max_dS": dmax,
            "verdict": "PASS" if dmax <= MESH_ERROR_TOL else "FAIL",
        }
        payload["status"] = "ok" if dmax <= MESH_ERROR_TOL else "threshold_exceeded"
        payload["elapsed_total_s"] = round(
            nominal["elapsed_s"] + scaled["elapsed_s"], 2)
        print(f"max|dS11|={d11:.3e} max|dS21|={d21:.3e} "
              f"max|dS|={dmax:.3e} tol={MESH_ERROR_TOL} "
              f"-> {payload['compare']['verdict']}")
        print(f"elapsed nominal={nominal['elapsed_s']}s "
              f"scaled={scaled['elapsed_s']}s")

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"status={payload['status']} -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
