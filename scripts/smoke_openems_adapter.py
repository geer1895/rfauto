"""openEMS 适配器冒烟验证（编译构建完成后运行）。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from rfauto.adapters import openems_solver  # noqa: F401  触发自动注册
from rfauto.adapters.em_solver_base import (
    create_solver_from_config,
    load_solvers_config,
)

configs = load_solvers_config()
print("solvers.yaml 条目:", list(configs))

solver = create_solver_from_config("openems")
print("is_available:", solver.is_available())
print("connect:", solver.connect())
print("status:", solver.get_status())

ok = solver.build_geometry({
    "template": "wilkinson",
    "params": {"f0_ghz": 2.4, "series_w_mm": 0.33, "shunt_w_mm": 1.10, "arm_len_mm": 20.5},
})
script = solver._working_dir / "simulation.py"
print("build_geometry:", ok)
print("script generated:", script.exists(), script.stat().st_size, "bytes")

# 求解需要 openEMS Python 绑定（未编译），此处仅验证优雅失败
result = solver.solve()
print("solve (预期失败, 无绑定):", result.success, "-", result.message[:60])
solver.close()
print("SMOKE_OK")
