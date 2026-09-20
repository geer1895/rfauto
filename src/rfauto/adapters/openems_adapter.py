"""openEMS 适配器。

定位：趋势验证通道（比 fake 真实的量级校验），非 CI 全量回归主路径。
设计决策：
- 子进程模型：connect=定位 exe；build=生成脚本文件；solve=spawn+文件旁证
- CSV 输出解析（openEMS 不直接产 Touchstone）
- 模板覆盖 wilkinson+patch（非谐振先行+官方有贴片教程）
- Windows 安装 0.5 天 spike 前置为 gate
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
  from rfauto.adapters.em_solver_base import SolverCapabilities


@dataclass
class OpenEMSConfig:
  """openEMS 配置。"""
  exe_path: str | None = None
  solver: str = "FDTD"
  freq_range_ghz: tuple[float, float] = (1.0, 5.0)
  boundary: str = "PML_8"
  mesh_resolution: float = 0.5 # mm


@dataclass
class OpenEMSResult:
  """openEMS 仿真结果。"""
  success: bool
  s_params_file: str | None = None
  freq_ghz: np.ndarray | None = None
  s11_db: np.ndarray | None = None
  s21_db: np.ndarray | None = None
  message: str = ""

  def to_dict(self) -> dict[str, Any]:
    return {
      "success": self.success,
      "s_params_file": self.s_params_file,
      "n_freq_points": len(self.freq_ghz) if self.freq_ghz is not None else 0,
      "message": self.message,
    }


def find_openems_exe() -> str | None:
  """查找 openEMS 可执行文件。"""
  import shutil
  # 常见安装路径
  candidates = [
    "openEMS",
    "openEMS.exe",
    "E:/openEMS/install/bin/openEMS.exe",
    "C:/openEMS/openEMS.exe",
    "C:/Program Files/openEMS/openEMS.exe",
  ]
  for candidate in candidates:
    if shutil.which(candidate):
      return candidate
  for candidate in candidates:
    if Path(candidate).exists():
      return candidate
  return None


def parse_openems_csv(csv_path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  """解析 openEMS CSV 输出。

  Returns:
    (freq_ghz, s11_db, s21_db)
  """
  path = Path(csv_path)
  if not path.exists():
    raise FileNotFoundError(f"CSV 文件不存在: {path}")

  # 读取 CSV（openEMS 输出格式：freq, re(S11), im(S11), re(S21), im(S21)）
  data = np.loadtxt(str(path), delimiter=',', skiprows=1)

  freq_hz = data[:, 0]
  s11 = data[:, 1] + 1j * data[:, 2]
  s21 = data[:, 3] + 1j * data[:, 4]

  freq_ghz = freq_hz / 1e9
  s11_db = 20 * np.log10(np.abs(s11) + 1e-10)
  s21_db = 20 * np.log10(np.abs(s21) + 1e-10)

  return freq_ghz, s11_db, s21_db


class OpenEMSAdapter:
  """openEMS 适配器（兼容门面）。

  完整 build/solve/get_sparams 链委托给注册表中的 OpenEMSSolver
  （单一实现，避免两套逻辑漂移）；本类保留轻量状态/可用性接口。
  """

  def __init__(self, config: OpenEMSConfig | None = None):
    self._config = config or OpenEMSConfig()
    self._connected = False
    self._solver: Any | None = None

  def _make_solver(self) -> Any:
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
    from rfauto.adapters.openems_solver import OpenEMSSolver

    ec = EMSolverConfig(
      solver_type=EMSolverType.OPENEMS,
      exe_path=self._config.exe_path,
      freq_range_ghz=self._config.freq_range_ghz,
      mesh_resolution_mm=self._config.mesh_resolution,
    )
    return OpenEMSSolver(ec)

  def connect(self) -> bool:
    """连接到 openEMS。"""
    exe = self._config.exe_path or find_openems_exe()
    if exe is None:
      return False
    self._config.exe_path = exe
    self._solver = self._make_solver()
    if not self._solver.connect():
      return False
    self._connected = True
    return True

  def is_available(self) -> bool:
    """检查 openEMS 是否可用。"""
    exe = self._config.exe_path or find_openems_exe()
    if exe is None:
      return False
    return Path(exe).exists()

  def build_geometry(self, geometry: dict[str, Any]) -> bool:
    """构建几何（模板化: wilkinson|patch）。"""
    if not self._connected:
      self.connect()
    if self._solver is None:
      return False
    return self._solver.build_geometry(geometry)

  def solve(self) -> OpenEMSResult:
    """执行仿真并解析 CSV 输出。"""
    import numpy as np

    if self._solver is None:
      return OpenEMSResult(success=False, message="未连接")
    result = self._solver.solve()
    if not result.success:
      return OpenEMSResult(success=False, message=result.message)
    freq_ghz = result.freq_ghz
    s_db = 20 * np.log10(np.abs(result.s_params) + 1e-10)
    csv_path = self._solver._working_dir / "sparams.csv" if self._solver._working_dir else None
    return OpenEMSResult(
      success=True,
      s_params_file=str(csv_path) if csv_path else None,
      freq_ghz=freq_ghz,
      s11_db=s_db[:, 0, 0],
      s21_db=s_db[:, 1, 0],
      message=result.message,
    )

  def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
    """获取 S 参数 (freq_ghz, s_params)。"""
    if self._solver is None:
      self.connect()
    if self._solver is None:
      raise RuntimeError("openEMS 不可用")
    return self._solver.get_sparams()

  def close(self) -> None:
    """关闭。"""
    if self._solver is not None:
      self._solver.close()
    self._connected = False

  # ─── A5 能力声明 ─────────────────────────────────────────────────────────

  def capabilities(self) -> SolverCapabilities:
    """openEMS 通道能力声明（A5）。

    与注册表内 OpenEMSSolver 共用同一份声明（em_solver_base 内置表），
    避免两套逻辑漂移；available 位按当前可用性填充。
    """
    from rfauto.adapters.em_solver_base import EMSolverType, solver_capabilities_for

    caps = solver_capabilities_for(EMSolverType.OPENEMS)
    return caps.model_copy(update={"available": bool(self.is_available())})

  def get_status(self) -> dict[str, Any]:
    """获取适配器状态。"""
    return {
      "connected": self._connected,
      "available": self.is_available(),
      "exe_path": self._config.exe_path,
      "solver": self._config.solver,
    }
