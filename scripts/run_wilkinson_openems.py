"""wilkinson 模板真跑冒烟：build_geometry → solve → sparams.csv 解析。"""
import os
import sys

from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver

cfg = EMSolverConfig(
    solver_type="openems",
    exe_path=resolve_openems_exe(),
    working_dir=sys.argv[1] if len(sys.argv) > 1 else "runs/openems_wilk_smoke",
    freq_range_ghz=(2.0, 3.0),
    mesh_resolution_mm=1.0,
)
solver = OpenEMSSolver(cfg)
assert solver.connect(), "connect failed"
assert solver.build_geometry({
    "template": "wilkinson",
    "params": {"f0_ghz": 2.5, "series_w_mm": 1.87, "shunt_w_mm": 1.10, "arm_len_mm": 20.5},
}), "build_geometry failed"
print(open(os.path.join(cfg.working_dir, "simulation.py"), encoding="utf-8").read().splitlines()[0])
result = solver.solve()
print("success:", result.success)
print("message:", result.message)
if result.success:
    import numpy as np
    f, s = result.freq_ghz, result.s_params
    s11_db = 20 * np.log10(np.abs(s[:, 0, 0]) + 1e-12)
    print(f"n_freq={len(f)}, band S11 min={s11_db.min():.2f} dB @ {f[s11_db.argmin()]:.3f} GHz")
    print(f"S11 @2.5GHz = {s11_db[np.argmin(np.abs(f-2.5))]:.2f} dB")
