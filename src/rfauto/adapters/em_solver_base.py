"""模块化 EM 求解器架构（可替换设计）。

设计原则：
- 抽象基类 EMSolverAdapter 定义统一接口
- 每个求解器是独立模块，可热插拔
- 配置驱动：通过 configs/solvers.yaml 选择求解器
- 支持 openEMS / MEEP / Elmer / 未来扩展

接口（与 SimulatorAdapter 对齐但独立）：
- connect() → 连接求解器
- build_geometry(params) → 构建几何
- solve() → 执行求解
- get_sparams() → 获取 S 参数
- close() → 清理资源
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.core.interfaces import AdapterCapabilities

logger = logging.getLogger(__name__)


class EMSolverType(str, Enum):
    """EM 求解器类型。

    内置枚举覆盖框架自带适配器；configs/solvers.yaml 中出现的自定义类型
    （CST/COMSOL 等商用 EDA，经方向 6h 管理页添加）以原始字符串保存在
    EMSolverConfig.solver_type 中，待对应 adapter 实现并注册后生效。
    """
    OPENEMS = "openems"
    MEEP = "meep"
    ELMER = "elmer"
    PALACE = "palace"
    HFSS = "hfss"  # 商业求解器（对照用）
    COMSOL = "comsol"  # 商业 FEM（RF Module，MPh 桥；WP4.4c 第三方仲裁）
    NGSOLVE = "ngsolve"  # 开源 FEM（A9 零 license 频域通道；§10.19）
    ICEPAK = "icepak"  # AEDT 热通道（WP4.4a 电-热首案例；license 探测 ✅ 2026-09-12）
    Q3D = "q3d"  # AEDT 寄生提取通道（WP4.4b PCB 无源/互连 RLC；license 探测 ✅ 2026-09-12）
    FAKE = "fake"   # 解析近似（测试用）
    VNA = "vna"  # 实物 VNA 测量通道（DP-11：测量=一台"真机求解器"，与 fake 同接口）
    QUCSATOR = "qucsator"  # 电路级仿真器 qucsator_rf（qucs-S，GPL；DP-14 N7）
    MMT = "mmt"  # 自研 RWG/SIW 解析模基 MMT（GSM）求解器（DP-1：秒级模匹配，零外部进程零 license）


# ─── A5 求解器能力协议（SolverCapabilities）────────────────────────────────────
#
# 加性扩展 core.interfaces.AdapterCapabilities（不修改 core——该文件不在本项
# 文件面内）：继承其端口/导出/求解布尔位，叠加 A5 要求的维度/材料模型/并行/
# SAR/nf2ff 轴。**声明必须与适配器代码实际行为一致，不得虚报**——未实现的
# 能力一律 False/空元组；CAPABILITY_METHOD_REQUIREMENTS 给「声明 vs 实现」
# 一致性抽检提供方法映射（声明为真则必须有对应实现方法）。

#: 材料模型词表：material_models 声明值必须是此集合的子集
MATERIAL_MODELS: frozenset[str] = frozenset({
    "pec",                  # 理想导体（金属/边界）
    "lossless_dielectric",  # 无耗介质
    "lossy_dielectric",     # 有耗介质（tanδ / kappa）
    "lumped_element",       # 集总元件（电阻/负载）
})

#: 能力位 → 必须有其一实现方法（hasattr 抽检用；空元组=无方法可映射）
CAPABILITY_METHOD_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "supports_field_export": (
        "get_far_field", "get_field_data", "temperature_field",
        "evaluate_volume_series", "extract_temperature",
    ),
    "supports_convergence_report": ("get_convergence", "convergence_report"),
    "supports_touchstone_export": ("export_touchstone", "_export_touchstone"),
    "supports_optimetrics": ("run_optimetrics", "optimetrics", "add_optimetrics"),
    "supports_nf2ff": ("get_nf2ff", "nf2ff", "far_field_transform"),
    "supports_sar": ("get_sar", "sar"),
}


class SolverCapabilities(AdapterCapabilities):
    """EMSolverAdapter 通道能力声明（§10.1 A5）。

    字段语义（继承 core.interfaces.AdapterCapabilities，服务层可统一消费）：

    继承位
        supports_wave_port / supports_lumped_port —— 端口类型轴；
        supports_field_export —— 有场数据提取/导出实现（本协议定义为「存在
            可用的场提取方法」：COMSOL 温度/体积场为真；非远场方向图，远场
            单独由 supports_nf2ff 声明）；
        supports_convergence_report —— 有自适应收敛报告（直接法/FDTD 无此概念）；
        supports_touchstone_export —— 求解管线可产出/消费 Touchstone；
        supports_headless_solve —— 可无头求解；
        supports_optimetrics —— 有通用 Optimetrics 类优化驱动。

    A5 扩展位
        solver_type —— 求解器类型字符串；
        dimension —— 求解维度（"2d" / "3d"）；
        material_models —— MATERIAL_MODELS 子集，本通道真实建模的材料模型；
        parallel_backends —— 真实启用的并行后端（"shared_memory"/"mpi"/"gpu"）；
            适配器未透传并行开关时保持空元组（不虚报引擎理论并行能力）；
        supports_sar —— 比吸收率专用后处理；
        supports_nf2ff —— 近场→远场变换（天线方向图）；
        supports_lumped_elements —— 集总元件（电阻/负载）建模；
        supported_templates —— 本通道模板名（无模板机制的通道为空元组）；
        requires_license —— 求解是否占用商业 license 席位；
        availability_gate —— 可用性前置（"exe_path"/"mph+comsol_root"/...）；
        available —— 运行时可用性快照（capabilities() 调用时按 is_available()
            填充，非静态声明）。
    """
    solver_type: str = ""
    dimension: str = "3d"
    material_models: tuple[str, ...] = ()
    parallel_backends: tuple[str, ...] = ()
    supports_sar: bool = False
    supports_nf2ff: bool = False
    supports_lumped_elements: bool = False
    supported_templates: tuple[str, ...] = ()
    requires_license: bool = False
    availability_gate: str = ""
    available: bool = False


def _openems_template_names() -> tuple[str, ...]:
    """openEMS 模板名（从 TEMPLATE_META 实测，防手写清单漂移）。"""
    try:
        from rfauto.adapters.openems_templates import TEMPLATE_META
    except Exception:  # best-effort：拿不到就声明为空，不臆造
        return ()
    return tuple(TEMPLATE_META)


#: openEMS 能力声明：其适配器模块 openems_solver.py 不在本项文件面内，故声明
#: 集中在此（单一事实来源）。事实依据（2026-09-12 逐行核对；2026-09-13 WP4.1
#: 更新 nf2ff/SAR 两位）：
#:   - 端口：模板只用 MSLPort / LumpedPort（无 RectWG 波导端口）→ wave=False；
#:   - 材料：AddMaterial(epsilon, kappa=TAND...) + PEC → 有耗介质 + 理想导体；
#:   - Touchstone：solve 的 _parse_output 以 *.sNp（skrf）为主路；
#:   - nf2ff（WP4.1）：OpenEMSSolver.get_nf2ff + 模板 far_field 注入
#:     （CreateNF2FFBox 官方教程口径）→ True；
#:   - SAR（WP4.1/D4，绑定已随包）：OpenEMSSolver.get_sar + 模板 sar 注入
#:     （DumpType 29 + SAR_Calculation IEEE_62704）→ True；
#:   - 收敛报告/optimetrics/通用场导出：无对应实现 → False；
#:   - 并行：subprocess 单进程、不传 MPI/线程开关 → 空元组。
_OPENEMS_CAPABILITIES = SolverCapabilities(
    solver_type="openems",
    supports_wave_port=False,
    supports_lumped_port=True,
    supports_field_export=False,
    supports_convergence_report=False,
    supports_touchstone_export=True,
    supports_headless_solve=True,
    supports_optimetrics=False,
    dimension="3d",
    material_models=("pec", "lossy_dielectric", "lossless_dielectric"),
    parallel_backends=(),
    supports_sar=True,
    supports_nf2ff=True,
    supports_lumped_elements=True,
    supported_templates=_openems_template_names(),
    requires_license=False,
    availability_gate="exe_path",
)

#: 内置能力表：仅需覆盖无法在自身模块声明的通道（openEMS）。COMSOL/Palace 在
#: 各自适配器模块以类属性 CAPABILITIES 声明（就近维护，避免两处漂移）。
_SOLVER_CAPABILITY_SPECS: dict[EMSolverType, SolverCapabilities] = {
    EMSolverType.OPENEMS: _OPENEMS_CAPABILITIES,
}


def _undeclared_capabilities(solver_type: Any) -> SolverCapabilities:
    """未声明通道的保守默认：所有能力位 False/空（宁可拒绝也不虚报）。"""
    name = str(getattr(solver_type, "value", solver_type))
    return SolverCapabilities(
        solver_type=name,
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=False,
        supports_optimetrics=False,
        dimension="3d",
        material_models=(),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=(),
        requires_license=False,
        availability_gate="undeclared",
    )


@dataclass
class EMSolverConfig:
    """EM 求解器配置。"""
    solver_type: EMSolverType | str
    exe_path: str | None = None
    working_dir: str | None = None
    freq_range_ghz: tuple[float, float] = (1.0, 5.0)
    # openEMS 新语义（2026-09-04 官方方法学）：网格 base 覆盖（mm）；
    # 0 = 自动 λ_sub/50（官方口径）。0.5 ≈ λ_sub/100 已收敛档（E4-fine 实证）
    mesh_resolution_mm: float = 0.5
    boundary_condition: str = "PML_8"
    max_iterations: int = 1000
    convergence_threshold: float = 1e-4
    extra_params: dict[str, Any] = None

    def __post_init__(self):
        if self.extra_params is None:
            self.extra_params = {}


@dataclass
class EMSolverResult:
    """EM 求解器结果。"""
    success: bool
    freq_ghz: np.ndarray | None = None
    s_params: np.ndarray | None = None  # shape (n_freq, n_ports, n_ports)
    field_data: dict[str, Any] | None = None
    #: WP4.1/D4：nf2ff 远场产物（farfield_meta.json 内容 + 切面摘要）；
    #: 无远场注入或解析失败 → None（best-effort，不阻塞 S 参数主路）
    far_field: dict[str, Any] | None = None
    #: WP4.1/D4：SAR 产物（sar.csv 内容）；未注入 sar → None
    sar: dict[str, Any] | None = None
    convergence_iterations: int = 0
    wall_time_s: float = 0.0
    message: str = ""
    #: DP-11（测量通道加性可选字段，其余适配器恒 None——to_dict 不输出，
    #: 既有 JSON 面逐字节不变）：已测掩码 (n_ports, n_ports) bool，
    #: 语义同 health_service._parse_sparams_csv_masked（#314：补齐元素必须
    #: 标 False，全矩阵实测标全 True）。
    measured_mask: np.ndarray | None = None
    #: DP-11 测量 meta：{idn, calibrated, calkit_id, timestamp, temperature_c,
    #: driver, suspect: [...]}——缺失项记 suspect 不阻塞（G4 决议）。
    measurement_meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "n_freq_points": len(self.freq_ghz) if self.freq_ghz is not None else 0,
            "n_ports": self.s_params.shape[1] if self.s_params is not None else 0,
            "convergence_iterations": self.convergence_iterations,
            "wall_time_s": self.wall_time_s,
            "message": self.message,
        }


class EMSolverAdapter(ABC):
    """EM 求解器抽象基类。

    所有求解器必须实现此接口。
    """

    def __init__(self, config: EMSolverConfig):
        self._config = config
        self._connected = False

    @property
    def solver_type(self) -> EMSolverType:
        return self._config.solver_type

    @abstractmethod
    def connect(self) -> bool:
        """连接到求解器。"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查求解器是否可用。"""
        ...

    @abstractmethod
    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """构建几何模型。

        Args:
            geometry: 几何描述（层叠/走线/端口等）

        Returns:
            是否成功
        """
        ...

    @abstractmethod
    def solve(self) -> EMSolverResult:
        """执行求解。"""
        ...

    @abstractmethod
    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        """获取 S 参数。

        Returns:
            (freq_ghz, s_params) 其中 s_params shape = (n_freq, n_ports, n_ports)
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """关闭求解器，释放资源。"""
        ...

    def visualizations(self) -> list[dict[str, Any]]:
        """声明此求解器可提供的可视化产物（方向 6g 产物视图协议）。

        Returns: [{kind: str, spec: dict}]
            kind: "model3d" | "circuit" | "sparams" | "field" | "mesh" | ...
            spec: kind-specific metadata (file path, rendering hints, etc.)
        子类重写此方法声明自己的可视化能力；不认识的 kind 降级为文件下载。
        """
        return []

    def supported_output_formats(self) -> list[str]:
        """声明此求解器支持的输出格式。"""
        return ["touchstone", "csv"]


    def get_status(self) -> dict[str, Any]:
        """获取求解器状态。"""
        return {
            "solver_type": self.solver_type.value,
            "connected": self._connected,
            "available": self.is_available(),
            "config": {
                "freq_range_ghz": self._config.freq_range_ghz,
                "mesh_resolution_mm": self._config.mesh_resolution_mm,
            },
        }


    # ─── A5 能力声明 ─────────────────────────────────────────────────────────

    #: 子类可选：本通道静态能力声明（就近声明，见 ComsolAdapter/PalaceSolver）。
    #: None 时回落到内置能力表（openEMS）/保守默认（未声明通道）。
    CAPABILITIES: ClassVar[SolverCapabilities | None] = None

    def capabilities(self) -> SolverCapabilities:
        """返回本通道能力声明（§10.1 A5）。

        available 位按当前 is_available() 填充；其余位是静态声明。
        未声明通道返回保守默认（全 False/空），不虚报能力。
        """
        caps = self._declared_capabilities()
        return caps.model_copy(update={"available": bool(self.is_available())})

    def _declared_capabilities(self) -> SolverCapabilities:
        declared = getattr(type(self), "CAPABILITIES", None)
        if declared is not None:
            return declared
        spec = _SOLVER_CAPABILITY_SPECS.get(self.solver_type)
        if spec is not None:
            return spec
        return _undeclared_capabilities(self.solver_type)


class EMSolverRegistry:
    """EM 求解器注册表。

    用法：
        registry = EMSolverRegistry()
        registry.register(EMSolverType.OPENEMS, OpenEMSSolver)
        solver = registry.create(EMSolverType.OPENEMS, config)
    """

    def __init__(self):
        self._solvers: dict[EMSolverType, type[EMSolverAdapter]] = {}

    def register(self, solver_type: EMSolverType, solver_cls: type[EMSolverAdapter]) -> None:
        """注册求解器。"""
        self._solvers[solver_type] = solver_cls

    def create(self, solver_type: EMSolverType, config: EMSolverConfig) -> EMSolverAdapter:
        """创建求解器实例。

        未注册类型显式报错（含自定义 EDA 字符串类型——不再因 .value 缺失
        退化成 AttributeError）。
        """
        if solver_type not in self._solvers:
            name = getattr(solver_type, "value", solver_type)
            raise ValueError(f"未注册的求解器: {name}")
        return self._solvers[solver_type](config)

    def list_available(self) -> list[EMSolverType]:
        """列出已注册的求解器类型。"""
        return list(self._solvers.keys())

    def is_registered(self, solver_type: EMSolverType) -> bool:
        """检查求解器是否已注册。"""
        return solver_type in self._solvers

    def lookup(self, solver_type: EMSolverType | str) -> type[EMSolverAdapter] | None:
        """按类型返回已注册适配器类；未注册返回 None（不抛错）。"""
        return self._solvers.get(solver_type)


# 全局注册表
_global_registry = EMSolverRegistry()


# ─── 第三方适配器 entry-point 发现（DP-17 O1；仿 models.registry 双检锁） ────
# 内置注册路径（register_openems/register_comsol/… 各模块导入即注册）逐字节
# 不变：发现口是纯增量，不接进既有 create/list/注册函数。接线点由主代理在
# pyproject.toml 增补 [project.entry-points."rfauto.adapters"] 段时一并裁定
# （建议：configs/solvers.yaml 装载或 pipeline 选型入口先调
# ensure_adapter_plugins_loaded()——勿接进 get_global_registry，第三方模块
# import 期 register 会重入本模块造成非重入锁死锁）。

_adapter_plugins_loaded = False
_adapter_load_lock = threading.Lock()


def _discover_adapter_entry_points() -> None:
    """从 `[project.entry-points."rfauto.adapters"]` 发现第三方适配器插件。

    entry-point 值支持两种形式：
    - `"package.module"`（模块形式）：import 副作用完成注册（模块尾
      `register_<name>()`，同内置适配器惯例）；
    - `"package.module:AdapterClass"`（类形式）：load() 即 import 模块，
      同样依赖模块级注册；类对象本身不再二次注册（类型键归模块声明）。

    单个插件加载失败只 warning 不传染（与 models.registry 同口径）。
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover —— py3.10+ 恒可用
        return

    try:
        ep_group = entry_points(group="rfauto.adapters")
    except Exception:
        logger.warning("rfauto.adapters entry-point 组枚举失败", exc_info=True)
        return

    for ep in ep_group:
        try:
            ep.load()
            logger.debug("adapters entry-point loaded: %s", ep.name)
        except Exception:
            logger.warning("adapters entry-point 加载失败: %s",
                           ep.name, exc_info=True)


def ensure_adapter_plugins_loaded() -> None:
    """确保第三方适配器 entry-point 已发现（双检锁；幂等）。

    并发口径同 models.registry C3 修复：标志位在 import 完成后才置位，
    避免并发线程看到"已加载"却拿到空注册表。
    """
    global _adapter_plugins_loaded
    if _adapter_plugins_loaded:
        return
    with _adapter_load_lock:
        if _adapter_plugins_loaded:
            return
        _discover_adapter_entry_points()
        _adapter_plugins_loaded = True


def get_global_registry() -> EMSolverRegistry:
    """获取全局求解器注册表。"""
    return _global_registry


def solver_capabilities_for(solver_type: EMSolverType | str) -> SolverCapabilities:
    """按求解器类型反查静态能力声明（A5；available 位保持 False）。

    查找顺序：内置能力表（openEMS）→ 注册表内适配器的 CAPABILITIES 类属性
    （COMSOL/Palace）→ 显式报错 KeyError（未知/非法类型不静默返回空声明，
    否则按能力选择求解器的调用方会误判）。
    """
    key: Any = solver_type
    if not isinstance(key, EMSolverType):
        try:
            key = EMSolverType(str(solver_type))
        except ValueError:
            key = solver_type  # 自定义 EDA 字符串，保留原值供注册表反查
    spec = _SOLVER_CAPABILITY_SPECS.get(key)
    if spec is None:
        cls = get_global_registry().lookup(key)
        spec = getattr(cls, "CAPABILITIES", None) if cls is not None else None
    if spec is None:
        name = getattr(solver_type, "value", solver_type)
        raise KeyError(f"未声明的求解器能力: {name}")
    return spec.model_copy()


_DEFAULT_SOLVERS_YAML = "configs/solvers.yaml"


def load_solvers_config(path: str | Path | None = None) -> dict[str, EMSolverConfig]:
    """从 configs/solvers.yaml 加载各求解器的 EMSolverConfig。

    文件不存在时返回空 dict（不抛错——fake/无 openEMS 环境不受影响）。
    exe_path 支持 ${VAR} 环境变量展开。
    """
    import os

    import yaml

    cfg_path = Path(path or os.environ.get("RFAUTO_SOLVERS_YAML", _DEFAULT_SOLVERS_YAML))
    if not cfg_path.exists():
        return {}

    with open(cfg_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    configs: dict[str, EMSolverConfig] = {}
    for name, entry in (data.get("solvers") or {}).items():
        entry = dict(entry or {})
        exe = entry.get("exe_path")
        if exe:
            exe = os.path.expandvars(exe)
        freq = entry.get("freq_range_ghz") or [1.0, 5.0]
        raw_type = entry.get("solver_type", name)
        try:
            solver_type: EMSolverType | str = EMSolverType(raw_type)
        except ValueError:
            # 自定义 EDA 类型（6h 管理页添加，adapter 待实现）：保留原始字符串，
            # 注册对应 adapter 前 create_solver_from_config 会给出明确报错
            solver_type = str(raw_type)
        configs[name] = EMSolverConfig(
            solver_type=solver_type,
            exe_path=exe,
            working_dir=entry.get("working_dir"),
            freq_range_ghz=(float(freq[0]), float(freq[1])),
            mesh_resolution_mm=float(entry.get("mesh_resolution_mm", 0.5)),
            boundary_condition=entry.get("boundary_condition", "PML_8"),
            extra_params=dict(entry.get("extra_params") or {}),
        )
    return configs


def resolve_openems_exe() -> str:
    """解析 openEMS exe：solvers.yaml（${VAR} 展开）优先，回退
    RFAUTO_OPENEMS_BIN，最后旧机字面量兜底（#179：service 层硬编码
    旧路径会绕开可移植化链路，统一走这里）。"""
    import os

    cfg = load_solvers_config().get("openems")
    if cfg and cfg.exe_path:
        return cfg.exe_path
    bin_dir = os.environ.get("RFAUTO_OPENEMS_BIN")
    if bin_dir:
        return os.path.join(bin_dir, "openEMS.exe")
    return r"E:\openEMS\install\bin\openEMS.exe"


def create_solver_from_config(
    name: str,
    registry: EMSolverRegistry | None = None,
    path: str | Path | None = None,
) -> EMSolverAdapter:
    """按 configs/solvers.yaml 中的条目名创建求解器实例。

    Raises:
        KeyError: 配置中无此求解器条目。
        ValueError: 求解器类型未注册。
    """
    reg = registry or _global_registry
    configs = load_solvers_config(path)
    if name not in configs:
        raise KeyError(f"configs/solvers.yaml 中无此求解器条目: {name}")
    return reg.create(configs[name].solver_type, configs[name])
