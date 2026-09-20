"""Elmer 开源多物理求解器适配器（开源免 license 热/结构回退）。

定位：
- **开源免 license 的热/结构回退通道**，兼作第三方**交叉验证器**（与 COMSOL ht /
  Icepak 对拍）；
- 本项只落地**最小热传导案例：1-D 均匀热源平板**，验收口径 =
  「闭式温度分布 ≤1%」（D3-2 开源兜底案例），不虚报结构/HFSS 级能力。

VectorHelmholtz 择一结论（收口冻结，结论记于此不再反复）：**开源 FEM 高频 EM 通道 = A9 NGSolve；Elmer 定位 =
D3-2 开源热兜底 + 对 COMSOL ht/Icepak 的交叉验证器；Elmer
VectorHelmholtz/结构求解不实现**。理由：
1. 立项口径本就写明「与 NGSolve 比较后择一
   作开源 FEM 通道，避免两套」（能力口径当时标假设待证）；
2. NGSolve 已真机确证（PEC 立方腔 vs 闭式 0.31%、适配器真机 1e-7 量级）
   且已导入即注册（ngsolve_adapter）；Elmer 高频链
   至今未检索实证（假设未消），且其高频波端口/S 参数提取需自定义
   边界 + 后处理、无现成去嵌；
3. 热通道与 EM 通道能力面正交：Elmer 补位的是「免 license 热/结构」，
   与 NGSolve 补位的「免 license 频域 EM」不重叠，择二反而各司其职、
   不构成能力重复建设。

通道纪律：
- **不 import Elmer**：一律子进程调用 ElmerGrid.exe（Gmsh→Elmer 网格）与
  ElmerSolver.exe（SIF 求解），与项目「KiCad 子进程 / openEMS 子进程」同模式；
- **网格/SIF 全部文本生成**（build_gmsh_quad_strip / build_slab_sif），
  确定性可离线单测；
- 本文件每处 SIF 关键字均**对本机 Elmer 26.1 真机实证**，关键实证：
  * Heat Source 在 26.1 的 SOLVER.KEYWORDS 中存在但 HeatSolver **不消费**
    （实测 q=1e6 仍得 T≡300），必须用 **Volumetric Heat Source**（真机实证
    T(L)=T0+qL²/2k，闭式吻合）；
  * Solver 编号必须**连续**（缺号 → ERROR:: LoadInputFile: Entry missing）；
  * 结果读取走 SaveData/SaveLine 的 ASCII line.dat（列序见 _SAVE_LINE_COLUMNS），
    不解析二进制/附加段 VTU。

闭式（裁判=独立解析来源，非自证）：
    平板 x∈[0,L]，左端 Dirichlet T(0)=T0，其余面绝热（零热流），均匀体热源 q：
        k·T''(x) + q = 0,  T(0)=T0,  T'(L)=0
      ⇒ T(x) = T0 + q/(2k)·(2Lx − x²)
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    EMSolverType,
    SolverCapabilities,
    get_global_registry,
)

logger = logging.getLogger(__name__)

# ── Elmer 安装定位（与 scripts/multiphysics_probe.py 同口径）─────────────────
ELMER_HOME_ENV = "ELMER_HOME"              # 官方安装器设置的安装根
RFAUTO_ELMER_BIN_ENV = "RFAUTO_ELMER_BIN"  # 可移植化：直接指向 bin 目录
DEFAULT_ELMER_HOME = r"E:\Elmer\Elmer 26.1-Release"
ELMER_SOLVER_REL = Path("bin") / "ElmerSolver.exe"
ELMER_GRID_REL = Path("bin") / "ElmerGrid.exe"

# ── 模板：1-D 均匀热源平板 ────────────────────────────────────────────────────
TEMPLATE_HEAT_SLAB_1D = "heat_slab_1d"

#: 平板模板默认参数（SI 内核 + mm 几何；q=1000 W/m³、k=1 W/(m·K)、L=0.1m
#: ⇒ ΔT_max = qL²/2k = 5 K，闭式值整齐便于断言）
SLAB_DEFAULTS: dict[str, float] = {
    "thickness_mm": 100.0,   # x 向厚度 L
    "width_mm": 50.0,        # y 向宽度（1 层即降为 1-D 传导）
    "n_x": 40,               # x 向网格分段（SaveLine 节点数 = n_x+1）
    "n_y": 2,                # y 向分段（偶数，保证中线落在网格节点上）
    "heat_conductivity_w_mk": 1.0,
    "heat_source_w_m3": 1000.0,
    "t0_k": 300.0,
    "steady_tol": 1.0e-10,
}

#: SaveLine 输出列（1-based，见 line.dat.names；真机 26.1 实录）
_SAVE_LINE_COLUMNS = (
    "call_count", "boundary_condition", "node_index",
    "x", "y", "z", "temperature",
)
_SAVE_LINE_NCOLS = len(_SAVE_LINE_COLUMNS)
_SAVE_LINE_TEMP_COL = _SAVE_LINE_COLUMNS.index("temperature")
_SAVE_LINE_X_COL = _SAVE_LINE_COLUMNS.index("x")

_GMSH_EDGE_LEFT = 2    # physical tag：x=0 面（Dirichlet）
_GMSH_EDGE_RIGHT = 3   # x=L 面（绝热，零热流）
_GMSH_EDGE_TOP = 4     # y=W 面（绝热）
_GMSH_EDGE_BOTTOM = 5  # y=0 面（绝热）

#: 本通道产出主结果文件名
RESULT_LINE_FILE = "line.dat"
SIF_FILE = "case.sif"
GMSH_FILE = "plate.msh"
MESH_DIR = "mesh"


# ── 纯函数：参数规范化 / 闭式 / 网格与 SIF 文本 / 结果解析 ─────────────────────

def normalize_slab_params(params: dict[str, Any] | None) -> dict[str, float]:
    """平板模板参数规范化：补默认、转 float、正数校验。

    n_x / n_y 必须为正整数（网格分段数），其余为严格正实数。
    """
    spec = dict(SLAB_DEFAULTS)
    for key, value in (params or {}).items():
        if key in SLAB_DEFAULTS:
            spec[key] = value
    for key in ("n_x", "n_y"):
        raw = float(spec[key])
        if not np.isfinite(raw) or raw < 1 or raw != int(raw):
            raise ValueError(f"slab 参数 {key} 必须为正整数，得到 {spec[key]}")
        spec[key] = int(raw)
    for key, value in spec.items():
        if key in ("n_x", "n_y"):
            continue
        value = float(value)
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"slab 参数 {key} 必须为正数，得到 {value}")
        spec[key] = value
    return spec


def slab_temperature_closed_form(
    x_m: np.ndarray | float,
    length_m: float,
    heat_source_w_m3: float,
    heat_conductivity_w_mk: float,
    t0_k: float,
) -> np.ndarray:
    """1-D 均匀热源平板闭式温度分布（裁判=独立解析解）。

    T(x) = T0 + q/(2k)·(2Lx − x²)，左端 Dirichlet、右端绝热、体热源均匀。
    """
    x = np.asarray(x_m, dtype=float)
    return t0_k + heat_source_w_m3 / (2.0 * heat_conductivity_w_mk) * (
        2.0 * length_m * x - x * x
    )


def build_gmsh_quad_strip(
    length_m: float,
    width_m: float,
    n_x: int,
    n_y: int,
) -> str:
    """生成 Gmsh v2.2 ASCII 结构化四边形网格（x∈[0,L] × y∈[0,W]）。

    physical tag 约定：域=1，左/右/上/下边=2/3/4/5（SIF 的 Target 编号据此）。
    节点序 (i,j) → index = j*(n_x+1)+i+1，四边形按逆时针连接。
    """
    if n_x < 1 or n_y < 1:
        raise ValueError("n_x/n_y 必须 ≥ 1")
    nx, ny = int(n_x) + 1, int(n_y) + 1

    def nid(i: int, j: int) -> int:
        return j * nx + i + 1

    nodes = "".join(
        f"{nid(i, j)} {length_m * i / n_x:.10g} {width_m * j / n_y:.10g} 0\n"
        for j in range(ny) for i in range(nx)
    )
    els: list[str] = []
    eid = 1
    for j in range(n_y):
        for i in range(n_x):
            els.append(
                f"{eid} 3 2 1 1 {nid(i, j)} {nid(i + 1, j)} "
                f"{nid(i + 1, j + 1)} {nid(i, j + 1)}"
            )
            eid += 1
    for j in range(n_y):  # 左边 x=0 → physical 2
        els.append(f"{eid} 1 2 {_GMSH_EDGE_LEFT} {_GMSH_EDGE_LEFT} "
                   f"{nid(0, j)} {nid(0, j + 1)}")
        eid += 1
    for j in range(n_y):  # 右边 x=L → physical 3
        els.append(f"{eid} 1 2 {_GMSH_EDGE_RIGHT} {_GMSH_EDGE_RIGHT} "
                   f"{nid(n_x, j)} {nid(n_x, j + 1)}")
        eid += 1
    for i in range(n_x):  # 上边 y=W → physical 4
        els.append(f"{eid} 1 2 {_GMSH_EDGE_TOP} {_GMSH_EDGE_TOP} "
                   f"{nid(i, n_y)} {nid(i + 1, n_y)}")
        eid += 1
    for i in range(n_x):  # 下边 y=0 → physical 5
        els.append(f"{eid} 1 2 {_GMSH_EDGE_BOTTOM} {_GMSH_EDGE_BOTTOM} "
                   f"{nid(i, 0)} {nid(i + 1, 0)}")
        eid += 1

    return (
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n"
        f"$Nodes\n{nx * ny}\n{nodes}$EndNodes\n"
        f"$Elements\n{eid - 1}\n" + "\n".join(els) + "\n$EndElements\n"
    )


def _fmt(value: float) -> str:
    return f"{float(value):.10g}"


def build_slab_sif(
    length_m: float,
    width_m: float,
    heat_source_w_m3: float,
    heat_conductivity_w_mk: float,
    t0_k: float,
    steady_tol: float = SLAB_DEFAULTS["steady_tol"],
) -> str:
    """生成 1-D 均匀热源平板 SIF（关键字均经本机 Elmer 26.1 真机实证）。

    关键实证（见模块 docstring）：体热源必须用 Volumetric Heat Source；
    Solver 编号连续；结果由 SaveData/SaveLine 沿中线输出 ASCII。
    """
    y_mid = 0.5 * width_m
    return f"""Header
  Mesh DB "." "mesh"
End

Simulation
  Max Output Level = 5
  Coordinate System = Cartesian
  Simulation Type = Steady state
  Steady State Max Iterations = 1
  Output Intervals = 1
  Post File = "case.vtu"
End

Material 1
  Heat Conductivity = {_fmt(heat_conductivity_w_mk)}
End

Body Force 1
  Volumetric Heat Source = {_fmt(heat_source_w_m3)}
End

Body 1
  Target Bodies(1) = 1
  Equation = 1
  Material = 1
  Body Force = 1
End

Equation 1
  Active Solvers(1) = 1
End

Solver 1
  Equation = Heat Equation
  Procedure = "HeatSolve" "HeatSolver"
  Variable = Temperature
  Linear System Solver = Direct
  Steady State Convergence Tolerance = {_fmt(steady_tol)}
End

Solver 2
  Exec Solver = After Simulation
  Equation = "SaveLine"
  Procedure = "SaveData" "SaveLine"
  Filename = "{RESULT_LINE_FILE}"
  Polyline Coordinates(2,3) = Real 0.0 {_fmt(y_mid)} 0.0  {_fmt(length_m)} {_fmt(y_mid)} 0.0
End

Boundary Condition 1
  Target Boundaries(1) = {_GMSH_EDGE_LEFT}
  Temperature = {_fmt(t0_k)}
End

Boundary Condition 2
  Target Boundaries(3) = {_GMSH_EDGE_RIGHT} {_GMSH_EDGE_TOP} {_GMSH_EDGE_BOTTOM}
  Heat Flux = 0.0
End
"""


def parse_save_line(text: str) -> tuple[np.ndarray, np.ndarray]:
    """解析 Elmer SaveLine ASCII 输出 → (x_m, temperature_k)，按 x 升序。

    文件可能含多个步块（每块以 call_count 递增开头）；只取**最后一块**。
    列序见 _SAVE_LINE_COLUMNS；空/坏行显式报错而非静默跳过。
    """
    blocks: list[list[tuple[float, float]]] = []
    current_call: float | None = None
    current: list[tuple[float, float]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < _SAVE_LINE_NCOLS:
            raise ValueError(
                f"line.dat 第 {lineno} 行列数 {len(tokens)} < {_SAVE_LINE_NCOLS}: {line!r}"
            )
        try:
            values = [float(tok) for tok in tokens]
        except ValueError as exc:
            raise ValueError(f"line.dat 第 {lineno} 行非数值: {line!r}") from exc
        call = values[0]
        if current_call is None or call != current_call:
            if current:
                blocks.append(current)
            current = []
            current_call = call
        current.append((values[_SAVE_LINE_X_COL], values[_SAVE_LINE_TEMP_COL]))
    if current:
        blocks.append(current)
    if not blocks:
        raise ValueError("line.dat 无可解析的数据行")
    last = sorted(blocks[-1], key=lambda pair: pair[0])
    x = np.asarray([pair[0] for pair in last], dtype=float)
    t = np.asarray([pair[1] for pair in last], dtype=float)
    return x, t


def compare_temperature_profiles(
    x_num: np.ndarray,
    t_num: np.ndarray,
    x_ref: np.ndarray,
    t_ref: np.ndarray,
) -> dict[str, float]:
    """数值温度分布 vs 裁判解析分布：最大绝对/归一化相对偏差。

    相对偏差归一化到**参考分布的温度升幅**（max T_ref − min T_ref），
    而非绝对温度（含 300 K 时绝对相对量会失真）；温度升幅为 0 时退化为
    绝对偏差（不再有意义地归一化，如实返回）。
    """
    x_num = np.asarray(x_num, dtype=float)
    t_num = np.asarray(t_num, dtype=float)
    x_ref = np.asarray(x_ref, dtype=float)
    t_ref = np.asarray(t_ref, dtype=float)
    if x_num.size == 0 or x_ref.size < 2:
        raise ValueError("剖面至少需要 1 个数值点与 2 个参考点")
    order = np.argsort(x_ref)
    ref_at_num = np.interp(x_num, x_ref[order], t_ref[order])
    abs_err = np.abs(t_num - ref_at_num)
    max_abs = float(np.max(abs_err))
    rise = float(np.max(t_ref) - np.min(t_ref))
    max_rel = max_abs / rise if rise > 0 else max_abs
    return {
        "max_abs_deviation_k": max_abs,
        "reference_rise_k": rise,
        "max_relative_deviation": float(max_rel),
        "n_points": int(x_num.size),
    }


# ── 子进程执行（测试可注入 runner，离线确定性）────────────────────────────────

def run_command(
    cmd: list[str],
    timeout_s: float,
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    """执行子进程；返回 {rc, stdout, stderr, timed_out, elapsed_s}。

    best-effort（#105）：任何执行异常都收敛为结构化失败字典，不向上抛。
    """
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "rc": -1,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout_s}s",
            "timed_out": True,
            "elapsed_s": time.perf_counter() - started,
        }
    except Exception as exc:  # best-effort：执行异常不炸主路径
        return {
            "rc": -1, "stdout": "", "stderr": str(exc),
            "timed_out": False, "elapsed_s": time.perf_counter() - started,
        }
    return {
        "rc": int(proc.returncode),
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "timed_out": False,
        "elapsed_s": time.perf_counter() - started,
    }


def resolve_elmer_bin(exe_path: str | None = None) -> Path | None:
    """解析 ElmerSolver 路径（显式 exe_path > RFAUTO_ELMER_BIN > ELMER_HOME
    > 本机默认安装根 > PATH）。全部落空返回 None（best-effort，不抛）。"""
    candidates: list[Path] = []
    if exe_path:
        candidates.append(Path(exe_path))
    bin_env = os.environ.get(RFAUTO_ELMER_BIN_ENV, "").strip()
    if bin_env:
        candidates.append(Path(bin_env) / "ElmerSolver.exe")
    home_env = os.environ.get(ELMER_HOME_ENV, "").strip()
    if home_env:
        candidates.append(Path(home_env) / ELMER_SOLVER_REL)
    candidates.append(Path(DEFAULT_ELMER_HOME) / ELMER_SOLVER_REL)
    for cand in candidates:
        if cand.exists():
            return cand
    which = shutil.which("ElmerSolver") or shutil.which("ElmerSolver.exe")
    return Path(which) if which else None


# ── 适配器 ────────────────────────────────────────────────────────────────────

class ElmerAdapter(EMSolverAdapter):
    """Elmer 开源多物理适配器（本项：1-D 均匀热源平板热传导）。

    用法：
        cfg = EMSolverConfig(solver_type=EMSolverType.ELMER,
                             exe_path=..., working_dir="runs/elmer_case")
        solver = ElmerAdapter(cfg); solver.connect()
        solver.build_geometry({"thickness_mm": 100.0, ...})
        result = solver.solve()
        report = solver.deviation_report()   # vs 解析解
    """

    #: A5 能力声明（如实，逐条对代码；不虚报结构/EM 能力）：
    #:   - 端口：本项只做热传导，无波/集总端口 → False；
    #:   - 场导出：temperature_field() 提供温度剖面 → True；
    #:   - 收敛报告/optimetrics/nf2ff/SAR/集总元件：无实现 → False；
    #:   - Touchstone：热通道不产 S 参数 → False；
    #:   - dimension="2d"：本项生成 2-D 条带网格（y 向 1 层即 1-D 传导），
    #:     不虚报 3-D；
    #:   - material_models=()：MATERIAL_MODELS 是 EM 材料词表，热通道不适用，
    #:     留空而非套用 EM 术语；
    #:   - 模板：heat_slab_1d；license：GPL 开源 → False。
    #:
    #: VectorHelmholtz 择一收口（详见模块 docstring）：EM 求解位全部 False
    #: 是**择一结论**（开源 FEM EM 通道=A9 NGSolve），不是待实现占位。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="elmer",
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=True,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="2d",
        material_models=(),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=(TEMPLATE_HEAT_SLAB_1D,),
        requires_license=False,
        availability_gate="exe_path",
    )

    def __init__(self, config: EMSolverConfig,
                 runner: Callable[..., dict[str, Any]] | None = None):
        super().__init__(config)
        self._exe_path: Path | None = None
        self._grid_exe: Path | None = None
        self._working_dir: Path | None = None
        self._params: dict[str, Any] = {}
        self._built = False
        self._runner = runner or run_command
        self._profile: dict[str, np.ndarray] | None = None
        self._deviation: dict[str, float] | None = None
        self._last_message = ""

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        solver = resolve_elmer_bin(self._config.exe_path)
        if solver is None:
            self._last_message = (
                "Elmer 不可用：未找到 ElmerSolver.exe（检查 exe_path / "
                f"{RFAUTO_ELMER_BIN_ENV} / {ELMER_HOME_ENV} / 默认安装根）"
            )
            logger.warning(self._last_message)
            return False
        self._exe_path = solver
        grid = solver.parent / "ElmerGrid.exe"
        self._grid_exe = grid if grid.exists() else None
        if self._config.working_dir:
            self._working_dir = Path(self._config.working_dir)

        # 检查版本（best-effort：拿不到版本不阻塞连接，只记录）
        info = self._runner([str(solver), "--version"], 30.0, cwd=self._working_dir)
        if info.get("timed_out"):
            logger.warning("ElmerSolver --version 超时；继续（best-effort）")
        self._connected = True
        self._last_message = f"ElmerSolver = {solver}"
        return True

    def is_available(self) -> bool:
        return resolve_elmer_bin(self._config.exe_path) is not None

    def close(self) -> None:
        self._connected = False

    @property
    def last_message(self) -> str:
        """最近一次 connect/build/solve 的状态说明（诊断用，可空串）。"""
        return self._last_message

    # ── 建模 / 求解 ─────────────────────────────────────────────────────────

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """生成 Gmsh 网格文本 + SIF，并（若 ElmerGrid 可用）转 Elmer 网格。

        best-effort：Elmer 不可用或转换失败均返回 False + 明确 message，不抛。
        """
        if not self._connected or self._exe_path is None:
            self._last_message = "build_geometry 失败：未连接（先 connect()）"
            return False
        if self._working_dir is None:
            self._working_dir = Path(tempfile.mkdtemp(prefix="rfauto_elmer_"))
        workdir = self._working_dir
        try:
            workdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._last_message = f"build_geometry 失败：无法创建 {workdir}: {exc}"
            return False

        try:
            spec = normalize_slab_params(geometry)
        except ValueError as exc:
            self._last_message = f"build_geometry 参数非法：{exc}"
            return False
        self._params = spec

        length_m = spec["thickness_mm"] / 1000.0
        width_m = spec["width_mm"] / 1000.0
        gmsh_path = workdir / GMSH_FILE
        gmsh_path.write_text(
            build_gmsh_quad_strip(length_m, width_m, int(spec["n_x"]), int(spec["n_y"])),
            encoding="utf-8",
        )
        (workdir / SIF_FILE).write_text(
            build_slab_sif(
                length_m=length_m,
                width_m=width_m,
                heat_source_w_m3=spec["heat_source_w_m3"],
                heat_conductivity_w_mk=spec["heat_conductivity_w_mk"],
                t0_k=spec["t0_k"],
                steady_tol=spec["steady_tol"],
            ),
            encoding="utf-8",
        )

        if self._grid_exe is None:
            self._last_message = (
                "build_geometry 失败：未找到 ElmerGrid.exe——Gmsh→Elmer 网格转换"
                "是求解前置（Elmer 安装不完整）"
            )
            logger.error(self._last_message)
            return False

        mesh_dir = workdir / MESH_DIR
        extra = self._config.extra_params or {}
        info = self._runner(
            [str(self._grid_exe), "14", "2", str(gmsh_path), "-out", str(mesh_dir)],
            float(extra.get("grid_timeout_s", 120.0)),
            cwd=workdir,
        )
        header = mesh_dir / "mesh.header"
        if info.get("rc") != 0 or not header.exists():
            self._last_message = (
                f"build_geometry 失败：ElmerGrid rc={info.get('rc')}，"
                f"mesh.header 存在={header.exists()}；stderr={info.get('stderr', '')[:400]}"
            )
            logger.error(self._last_message)
            return False
        self._built = True
        self._last_message = f"网格已转换：{mesh_dir}"
        return True

    def solve(self, timeout_s: float | None = None) -> EMSolverResult:
        """子进程执行 ElmerSolver → 解析 line.dat → 与闭式对照。

        失败（未连接/未建模/不可用/rc≠0/结果缺失）一律返回 success=False
        并带明确 message（best-effort，#105），不抛异常、不伪造结果。
        """
        started = time.perf_counter()
        if not self._connected or self._exe_path is None:
            return EMSolverResult(success=False,
                                  message="未连接：先 connect()（Elmer 不可用或未初始化）")
        if not self._built or self._working_dir is None:
            return EMSolverResult(
                success=False, message="未建模：先 build_geometry() 生成网格与 SIF")

        workdir = self._working_dir
        extra = self._config.extra_params or {}
        tmo = float(timeout_s if timeout_s is not None
                    else extra.get("solve_timeout_s", 600.0))
        info = self._runner([str(self._exe_path), SIF_FILE], tmo, cwd=workdir)
        wall = time.perf_counter() - started

        line_path = workdir / RESULT_LINE_FILE
        if info.get("timed_out"):
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"ElmerSolver 超时（>{tmo}s）")
        if info.get("rc") != 0:
            return EMSolverResult(
                success=False, wall_time_s=wall,
                message=f"ElmerSolver rc={info.get('rc')}；"
                        f"stderr={(info.get('stderr') or '')[:400]}")
        if not line_path.exists():
            return EMSolverResult(
                success=False, wall_time_s=wall,
                message=f"ElmerSolver 完成但缺少结果文件 {RESULT_LINE_FILE}")
        try:
            x_num, t_num = parse_save_line(line_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"结果解析失败：{exc}")

        self._profile = {"x_m": x_num, "temperature_k": t_num}
        self._deviation = self._closed_form_deviation(x_num, t_num)
        report = dict(self._deviation)
        report["pass_1pct"] = report["max_relative_deviation"] <= 0.01
        self._last_message = (
            f"Elmer 真跑成功：{x_num.size} 点，ΔT_max={report['reference_rise_k']:.6g} K，"
            f"max|ΔT|={report['max_abs_deviation_k']:.6g} K，"
            f"相对偏差={report['max_relative_deviation'] * 100:.4g}%"
        )
        return EMSolverResult(
            success=True,
            wall_time_s=wall,
            field_data={
                "x_m": x_num,
                "temperature_k": t_num,
                "deviation_vs_closed_form": report,
            },
            message=self._last_message,
        )

    # ── 结果 / 交叉验证 ─────────────────────────────────────────────────────

    def _closed_form_deviation(self, x_num: np.ndarray,
                               t_num: np.ndarray) -> dict[str, float]:
        spec = self._params
        t_ref = slab_temperature_closed_form(
            x_num,
            length_m=spec["thickness_mm"] / 1000.0,
            heat_source_w_m3=spec["heat_source_w_m3"],
            heat_conductivity_w_mk=spec["heat_conductivity_w_mk"],
            t0_k=spec["t0_k"],
        )
        return compare_temperature_profiles(x_num, t_num, x_num, t_ref)

    def temperature_field(self) -> dict[str, np.ndarray] | None:
        """温度剖面（x_m / temperature_k）；未求解返回 None（不臆造）。"""
        return self._profile

    def deviation_report(self) -> dict[str, float] | None:
        """最近一次求解 vs 解析解的最大绝对/相对偏差；未求解返回 None。"""
        return self._deviation

    def closed_form_profile(self) -> dict[str, np.ndarray] | None:
        """在数值解同一 x 网格上的解析解剖面（供外部作图/对拍）。"""
        if self._profile is None:
            return None
        spec = self._params
        x = self._profile["x_m"]
        return {
            "x_m": x,
            "temperature_k": slab_temperature_closed_form(
                x,
                length_m=spec["thickness_mm"] / 1000.0,
                heat_source_w_m3=spec["heat_source_w_m3"],
                heat_conductivity_w_mk=spec["heat_conductivity_w_mk"],
                t0_k=spec["t0_k"],
            ),
        }

    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        """热通道不产出 S 参数（显式报错，不返回伪数据）。"""
        raise NotImplementedError("ElmerAdapter 是热传导通道，不产出 S 参数")

    def visualizations(self) -> list[dict[str, Any]]:
        if self._working_dir is None or not self._built:
            return []
        workdir = self._working_dir
        return [
            {"kind": "model3d",
             "spec": {"mesh_dir": str(workdir / MESH_DIR), "format": "elmer-mesh"}},
            {"kind": "field",
             "spec": {"path": str(workdir / RESULT_LINE_FILE),
                      "variable": "temperature", "format": "elmer-saveline"}},
        ]


# ── 注册（把 Elmer 通道接入全局注册表）────────────────────────────────────────

def register_elmer_adapter(registry: Any | None = None) -> None:
    """向求解器注册表注册 Elmer 通道。

    模块尾部已做导入即注册（与 comsol/meep/ngsolve 同模式）；registry
    形参保留供测试注入局部注册表（test_elmer_adapter.py）。
    """
    reg = registry or get_global_registry()
    reg.register(EMSolverType.ELMER, ElmerAdapter)


# 导入即注册（与 comsol_adapter/palace_solver 同模式；永不阻塞导入，#105）
with contextlib.suppress(Exception):
    register_elmer_adapter()
