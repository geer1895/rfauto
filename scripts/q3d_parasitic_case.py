"""WP4.4b Q3D 寄生提取真机首案例驱动（RO4350B 50Ω 直条微带 RLC）。

真机纪律（COMMON）：
- AEDT 2025.1（本机 v251，hfss/icepak 同池；license 探测
  q3d_desktop=exists + Q3D.dll/Q3DCOMENGINE.exe 齐，
  runs/multiphysics_probe/capability_matrix.json）；
- non_graphical gRPC；2025.1 gRPC 通道级不稳定（#191）→ **调用方
  整轮重试**（同 scripts/icepak_electrothermal_case.py 口径），
  重试前只杀 ansysedt 进程（不用 taskkill /T，#157）；
- 启动/求解可能耗时数分钟——建议 Start-Process 分离进程 + 日志文件
  轮询（#157）；
- 产物：runs/wp44b_q3d/case_result.json（steps/extracted/anchor/verdict）。

用法::

    .venv/Scripts/python.exe scripts/q3d_parasitic_case.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

WORKDIR = Path("runs/wp44b_q3d")
RESULT_JSON = WORKDIR / "case_result.json"
MAX_ATTEMPTS = 3


def _kill_desktops() -> None:
    """杀遗留 ansysedt（仅整轮重试时调用；#157 先查后杀，不 /T 连坐）。"""
    probe = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process ansysedt -ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True)
    count = (probe.stdout or "").strip()
    print(f"[retry] 检测到 {count or 0} 个 ansysedt 进程，清理后重试",
          flush=True)
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process ansysedt -ErrorAction SilentlyContinue | "
                    "Stop-Process -Force"], capture_output=True)
    time.sleep(5)


def _clean_project_artifacts() -> None:
    """清理上轮遗留工程/锁（失败轮可能留下损坏 .aedt）。"""
    for name in ("wp44b_parasitic.aedt",
                 "wp44b_parasitic.aedt.lock",
                 "matrix_acrl.txt", "matrix_c.txt"):
        path = WORKDIR / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)


def _run_attempt() -> dict:
    from rfauto.adapters.em_solver_base import (
        EMSolverConfig,
        EMSolverType,
    )
    from rfauto.adapters.q3d_adapter import Q3dAdapter

    steps: dict[str, object] = {}
    cfg = EMSolverConfig(solver_type=EMSolverType.Q3D,
                         working_dir=str(WORKDIR))
    solver = Q3dAdapter(cfg)
    started = time.perf_counter()
    try:
        steps["pyaedt_available"] = solver.is_available()
        steps["connect"] = solver.connect()
        if not steps["connect"]:
            steps["error"] = solver._last_message
            return steps
        steps["build_geometry"] = solver.build_geometry({})
        if not steps["build_geometry"]:
            steps["error"] = solver._last_message
            return steps
        result = solver.solve()
        steps["solve_message"] = result.message
        steps["solve_wall_s"] = round(result.wall_time_s, 1)
        steps["field_data"] = result.field_data
        verdict = (result.field_data or {}).get("verdict") or {}
        steps["ok"] = bool(result.success and verdict.get("pass_5pct"))
        if not result.success:
            steps["error"] = result.message
        return steps
    finally:
        solver.close()
        steps["total_wall_s"] = round(time.perf_counter() - started, 1)


def main() -> int:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    last: dict | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"=== attempt {attempt}/{MAX_ATTEMPTS} ===", flush=True)
        _clean_project_artifacts()
        try:
            last = _run_attempt()
        except Exception as exc:  # 真机面兜底落盘（#105）
            last = {"ok": False, "error": f"unhandled: {exc}"}
        if last.get("ok"):
            break
        print(f"attempt {attempt} FAIL: {last.get('error')}", flush=True)
        if attempt < MAX_ATTEMPTS:
            _kill_desktops()
    last = last or {"ok": False, "error": "no attempt recorded"}
    RESULT_JSON.write_text(
        json.dumps(last, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {RESULT_JSON}", flush=True)
    return 0 if last.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
