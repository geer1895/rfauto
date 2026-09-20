"""Icepak 热通道适配器（Icepak 电-热首案例，AEDT/pyaedt）。

定位：
- **AEDT 热通道**：Wilkinson 隔离电阻损耗 → Icepak 温度场 →（经
  core/electrothermal + core/thermal_iteration）材料温漂 → S 参数失谐；
- 首轮落地**最小传导首案例**（发热块 + 基板 1-D 传导锚 ≤2%）；后续补齐：**附着既有工程**（project_path）、**自然对流工况**
  （TemperatureAndFlow：空气域/重力/开口/环境温度 + HeatFlowRate 能量
  平衡判据）；HFSS→Icepak 场级损耗端到端由 map_em_losses 暴露 pyaedt
  官方 API（真机编排见 scripts/icepak_hfss_loss_e2e.py）。

通道纪律：
- **延迟 import**：`ansys.aedt.core` 只在 adapter 方法内引入（延迟 import 纪律，
  同 hfss_session）——未装 AEDT/pyaedt 的环境可安全 import 本模块；
- **损耗导入 API 名（检索确证）**：pyaedt
  `Icepak.assign_em_losses(assignment, design, setup, sweep, ...)`
  （底层 AEDT 命令 `oModule.AssignEMLoss`，本地
  pyaedt-main/src/ansys/aedt/core/icepak.py:1188 实证）；集总功率块
  走 `Icepak.assign_solid_block(object_name, power_assignment)`
  （同文件 :3703，底层 `oModule.AssignBlockBoundary`）；
- **1-D 传导锚（裁判=独立解析来源 #118）**：发热块满覆基板顶面 +
  基板底面 Dirichlet + 侧壁绝热（Icepak 默认壁）+ problem_type=
  TemperatureOnly 时，块中面温度解析精确等于
  `core/electrothermal.conduction_stack_rise_k`
  （Incropera 稳态傅里叶传导 + 均匀体热源中面平均）；真机验收门
  max|ΔT|/ΔT ≤ 2%。
- **版本钉扎与整轮重试**：AEDT 2025.1（与 hfss 脚本同池；
  license 探测 elec_solve_icepak=exists）；2025.1 gRPC 通道级
  不稳定（#191）由调用方（scripts/icepak_electrothermal_case.py）做
  整轮重试，本适配器不做单调用级重试。
- 非法输入显式 ValueError；失败一律 success=False + 明确 message
  （best-effort #105），不抛异常、不伪造结果。
"""

from __future__ import annotations

import logging
import math
import re
import time
from pathlib import Path
from typing import Any, ClassVar

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    EMSolverType,
    SolverCapabilities,
    get_global_registry,
)
from rfauto.core.electrothermal import (
    conduction_stack_rise_k,
    conduction_uniform_flux_rise_k,
)

logger = logging.getLogger(__name__)

#: 首案例模板名（发热块-基板传导栈）
TEMPLATE_CONDUCTION_STACK = "wilkinson_resistor_conduction"

#: AEDT 版本钉扎（本机 v251 = 2025.1，hfss 脚本同池，#191 口径）
DEFAULT_AEDT_VERSION = "2025.1"

#: 1-D 传导锚真机验收门（相对 ΔT）
ANCHOR_TOLERANCE = 0.02

#: 自然对流能量平衡验收门（壁面导出 + 开口对流 ≈ P_in，相对偏差）
ENERGY_BALANCE_TOLERANCE = 0.10

#: 自然对流默认重力方向：pyaedt edit_design_settings 口径 0..5 = −X..+Z，
#: 2 = −Z（安装 pyaedt 1.4.0 icepak.py:1106-1115 实装：>2 判正方向，
#: axis=Z）；早期草案"5=−Z"与实装相反，按代码实裁定（verdict 存档记录）。
DEFAULT_GRAVITY_DIR = 2

#: 模板默认参数（SI 内核 mm 几何；满覆锚工况：块=基板足印）：
#: P=0.5 W、A=20×20mm、h_sub=0.508mm/k=0.4（RO4350B 量级）、
#: h_blk=0.15mm/k=1.0 ⇒ ΔT=0.5/4e-4*(0.508e-3/0.4+0.15e-3/2) = 1.68125 K
STACK_DEFAULTS: dict[str, float] = {
    "board_len_mm": 20.0,
    "board_wid_mm": 20.0,
    "board_thk_mm": 0.508,
    "board_k_w_mk": 0.4,
    "blk_len_mm": 20.0,     # 满覆=1-D 锚工况；器件工况改小（如 2.0×1.25）
    "blk_wid_mm": 20.0,
    "blk_thk_mm": 0.15,
    "blk_k_w_mk": 1.0,
    "power_w": 0.5,
    "t_base_c": 25.0,
    "max_iterations": 100,
}

VALID_PROBLEM_TYPES = ("TemperatureOnly", "TemperatureAndFlow", "FlowOnly")

#: 环形谐振器基板工况默认参数（WP4.4a ① HFSS→Icepak 场级损耗端到端；
#: 几何与 scripts/icepak_hfss_loss_e2e.py 的 HFSS 源设计同名同坐标——
#: 基板中心在原点、环足印下的环带单独成体 rfauto_sub_ring，
#: EM 损耗映射按空间/同名双保险对齐）。power_w=0 → 无集总源（场级映射
#: 设计）；>0 → 环带体均匀体热源（同功率集总对照设计）。
RING_DEFAULTS: dict[str, float] = {
    "board_len_mm": 40.0,
    "board_wid_mm": 40.0,
    "board_thk_mm": 0.508,
    "board_k_w_mk": 0.4,
    "ring_r_in_mm": 11.0,
    "ring_r_out_mm": 12.2,
    "power_w": 0.0,
    "t_base_c": 25.0,
    "max_iterations": 100,
}

#: 数值 token 提取（"61.3cel"/" 60 cel"/"-12.5C" → 数值部分）
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def normalize_ring_params(params: dict[str, Any] | None) -> dict[str, float]:
    """环形基板工况参数规范化（power_w 允许 0=无集总源，其余正数）。"""
    spec = dict(RING_DEFAULTS)
    for key, value in (params or {}).items():
        if key not in spec:
            raise ValueError(f"未知环形工况参数 {key!r}（允许: {sorted(spec)}）")
        spec[key] = value
    try:
        max_iter = int(spec["max_iterations"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"max_iterations 必须是正整数，得到 {spec['max_iterations']!r}") from exc
    if max_iter < 1:
        raise ValueError(f"max_iterations 必须 >=1，得到 {max_iter}")
    spec["max_iterations"] = max_iter
    for key, value in spec.items():
        if key == "max_iterations":
            continue
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"环形工况参数 {key} 必须是实数，得到 {value!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"环形工况参数 {key} 必须有限，得到 {value!r}")
        if key == "power_w":
            if value < 0.0:
                raise ValueError(f"power_w 必须 >=0，得到 {value!r}")
        elif value <= 0.0:
            raise ValueError(f"环形工况参数 {key} 必须为正数，得到 {value!r}")
        spec[key] = value
    if spec["ring_r_in_mm"] >= spec["ring_r_out_mm"]:
        raise ValueError("ring_r_in_mm 必须 < ring_r_out_mm")
    half = min(spec["board_len_mm"], spec["board_wid_mm"]) / 2.0
    if spec["ring_r_out_mm"] >= half:
        raise ValueError("环外径必须小于基板半宽（环带须落在基板内）")
    return spec


def normalize_stack_params(params: dict[str, Any] | None) -> dict[str, float]:
    """模板参数规范化：补默认、转 float、正数/整数校验（不静默兜底）。"""
    spec = dict(STACK_DEFAULTS)
    for key, value in (params or {}).items():
        if key not in spec:
            raise ValueError(f"未知模板参数 {key!r}（允许: {sorted(spec)}）")
        spec[key] = value
    try:
        max_iter = int(spec["max_iterations"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"max_iterations 必须是正整数，得到 {spec['max_iterations']!r}") from exc
    if max_iter < 1:
        raise ValueError(f"max_iterations 必须 >=1，得到 {max_iter}")
    spec["max_iterations"] = max_iter
    for key, value in spec.items():
        if key == "max_iterations":
            continue
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"模板参数 {key} 必须是实数，得到 {value!r}") from exc
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"模板参数 {key} 必须为正数，得到 {value!r}")
        spec[key] = value
    return spec


def anchor_closed_form_c(spec: dict[str, float]) -> dict[str, float]:
    """按（规范化后）模板参数给 1-D 传导锚闭式温度（core 单一实现）。"""
    return conduction_stack_rise_k(
        power_w=spec["power_w"],
        area_m2=(spec["blk_len_mm"] * 1e-3) * (spec["blk_wid_mm"] * 1e-3),
        h_sub_m=spec["board_thk_mm"] * 1e-3,
        k_sub_w_mk=spec["board_k_w_mk"],
        h_blk_m=spec["blk_thk_mm"] * 1e-3,
        k_blk_w_mk=spec["blk_k_w_mk"],
        t_base_c=spec["t_base_c"],
    )


def pyaedt_installed() -> bool:
    """ansys.aedt.core 可 import 即认为 SDK 面 OK（license 由真机 connect 决定）。"""
    try:
        import ansys.aedt.core  # noqa: F401
    except Exception:
        return False
    return True


class IcepakAdapter(EMSolverAdapter):
    """Icepak 热通道适配器（本项：发热块-基板传导首案例）。

    用法::

        cfg = EMSolverConfig(solver_type=EMSolverType.ICEPAK,
                             working_dir="runs/wp44a_icepak")
        solver = IcepakAdapter(cfg)
        solver.build_geometry({"power_w": 0.5})   # 满覆=1-D 锚工况
        result = solver.solve()                    # 真机稳态热
        result.field_data["anchor"]               # 闭式对照 + 门判
    """

    #: A5 能力声明（如实，逐条对代码）：热通道不产 S 参数（端口面全
    #: False）；温度场/监控点温度导出 True；自然对流（TemperatureAndFlow）
    #: 经 build_convection_case 支持——能量平衡判据而非流场精细校准；
    #: 材料模型：传导栈基板=无耗介质板（RO4350B 量级）热行为，取 EM 词表
    #: 最贴近条目 lossless_dielectric（金属块不按 PEC/集总建模，不虚报）；
    #: headless：non_graphical gRPC → True；license：AEDT 池 → True。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="icepak",
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=True,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="3d",
        material_models=("lossless_dielectric",),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=(TEMPLATE_CONDUCTION_STACK,),
        requires_license=True,
        availability_gate="pyaedt",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        extra = config.extra_params or {}
        self._desktop_version: str = str(extra.get("desktop_version",
                                                   DEFAULT_AEDT_VERSION))
        self._problem_type: str = str(extra.get("problem_type", "TemperatureOnly"))
        if self._problem_type not in VALID_PROBLEM_TYPES:
            raise ValueError(
                f"problem_type 必须是 {VALID_PROBLEM_TYPES}，收到 {self._problem_type!r}")
        self._save_project: bool = bool(extra.get("save_project", True))
        # 附着既有工程模式（WP4.4a ①HFSS→Icepak 场级损耗端到端）：给了
        # project_path 就 new_desktop=False 挂既有 AEDT 工程（同桌面第二
        # 设计的挂法），不新建 wp44a_electrothermal.aedt；默认路径不变
        # （现首案例回归靠既有 fake 测试钉住）。
        project_path = extra.get("project_path")
        if project_path is not None and not str(project_path).strip():
            raise ValueError("project_path 不能是空字符串（不附着=不传）")
        self._project_path: str | None = (
            None if project_path is None else str(project_path))
        self._design_name: str = str(extra.get("design_name", "rfauto_et"))
        self._ipk: Any = None
        self._spec: dict[str, float] | None = None
        self._monitor_name: str | None = None
        self._monitor_point: str = "block_centroid"
        self._setup_name: str | None = None
        self._built: bool = False
        self._mode: str = "stack"  # "stack"=传导栈锚 | "convection"=自然对流
        #: 出热判据数据源=边界名（field summary 按边界取 HeatFlowRate 总量；
        #: 面 id 监控在 Region 重生成时会被 AEDT 删除——2025.1 真机实证）
        self._wall_boundary: str | None = None
        self._opening_boundary: str | None = None
        self._region_extent_mm: dict[str, float] | None = None
        #: 多设计往返（E2E：field↔lumped）时的逐设计建模状态快照
        self._design_state: dict[str, dict[str, Any]] = {}
        self._last_message = ""
        self._last_field: dict[str, Any] | None = None

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """pyaedt SDK 可 import 即 True；license/桌面级检查在 connect 真做。"""
        return pyaedt_installed()

    def connect(self) -> bool:
        """启动/连接 AEDT Desktop 并创建 Icepak 设计（non_graphical gRPC）。

        失败返回 False（best-effort #105），不抛异常。
        """
        if self._ipk is not None:
            return True
        if not pyaedt_installed():
            self._last_message = "pyaedt 不可用：无法 import ansys.aedt.core"
            logger.warning(self._last_message)
            return False
        workdir = self._resolve_working_dir()
        try:
            from ansys.aedt.core import Icepak

            # 附着既有工程模式：new_desktop=False 挂同桌面既有工程
            # （E2E 双设计同桌面：首个 Hfss 对象 new_desktop=True 起桌面，
            # 第二个 Icepak 对象按路径附着——pyaedt Icepak 构造器对不存在的
            # 设计名会新建，锁/陈旧面由调用方先清工程产物）
            project = (self._project_path if self._project_path is not None
                       else str(Path(workdir) / "wp44a_electrothermal.aedt"))
            new_desktop = self._project_path is None
            self._ipk = Icepak(
                project=project,
                design=self._design_name,
                version=self._desktop_version,
                non_graphical=True,
                new_desktop=new_desktop,
            )
            self._ipk.problem_type = self._problem_type
            self._design_state = {}
            self._restore_state(None)
            self._connected = True
            return True
        except Exception as exc:
            self._last_message = f"连接 AEDT/Icepak 失败: {exc}"
            logger.warning(self._last_message)
            self._ipk = None
            self._connected = False
            return False

    def _resolve_working_dir(self) -> Path:
        raw = self._config.working_dir or "runs/wp44a_icepak"
        workdir = Path(raw)
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def _snapshot_state(self) -> dict[str, Any]:
        """当前设计的建模状态（切设计时存档/换设计时恢复）。"""
        return {
            "built": self._built,
            "spec": self._spec,
            "mode": self._mode,
            "monitor_name": self._monitor_name,
            "monitor_point": self._monitor_point,
            "setup_name": self._setup_name,
            "wall_boundary": self._wall_boundary,
            "opening_boundary": self._opening_boundary,
            "region_extent_mm": self._region_extent_mm,
        }

    def _restore_state(self, state: dict[str, Any] | None) -> None:
        if not state:
            self._built = False
            self._spec = None
            self._mode = "stack"
            self._monitor_name = None
            self._monitor_point = "block_centroid"
            self._setup_name = None
            self._wall_boundary = None
            self._opening_boundary = None
            self._region_extent_mm = None
            return
        self._built = state["built"]
        self._spec = state["spec"]
        self._mode = state["mode"]
        self._monitor_name = state["monitor_name"]
        self._monitor_point = state["monitor_point"]
        self._setup_name = state["setup_name"]
        self._wall_boundary = state["wall_boundary"]
        self._opening_boundary = state["opening_boundary"]
        self._region_extent_mm = state["region_extent_mm"]

    def _swap_design_state(self, previous: str | None, target: str | None) -> None:
        """把 previous 设计的建模状态存档，再载入 target 设计状态（无则全新）。

        注意 previous 必须在 insert/set_active_design **切换之前**取——
        切换后 design_name 已是新设计，把旧状态存到新键下会让新设计继承
        旧 setup_name（2025.1 真机实证：solve 跳过 create_setup → analyze
        对不存在 setup 静默 no-op "solved in 0.0s" → 监控读取空）。
        """
        if previous and previous != target:
            self._design_state[previous] = self._snapshot_state()
        self._restore_state(self._design_state.get(target) if target else None)

    def use_design(self, design_name: str,
                   problem_type: str | None = None) -> bool:
        """在当前工程内插入并切换到新设计（首案例 A 锚/B 器件两工况）。

        insert_design 会激活新设计；problem_type 按设计级设置需重新钉扎
        （可传 ``problem_type`` 覆盖本设计的问题类型，如同一 adapter 先建
        TemperatureAndFlow 对流设计、再插 TemperatureOnly 纯传导对照设计）。
        建模状态按设计名快照/恢复。失败返回 False（best-effort #105）。
        """
        if self._ipk is None:
            self._last_message = "未连接：先 connect()"
            return False
        if problem_type is not None:
            if problem_type not in VALID_PROBLEM_TYPES:
                self._last_message = (
                    f"problem_type 必须是 {VALID_PROBLEM_TYPES}，"
                    f"收到 {problem_type!r}")
                return False
            self._problem_type = problem_type
        try:
            previous = getattr(self._ipk, "design_name", None)
            self._ipk.insert_design(design_name)
            self._ipk.problem_type = self._problem_type
            self._swap_design_state(previous, design_name)
            return True
        except Exception as exc:
            self._last_message = f"insert_design({design_name!r}) 失败: {exc}"
            logger.warning(self._last_message)
            return False

    def set_active_design(self, design_name: str) -> bool:
        """切换到工程内既有设计（E2E field↔lumped 往返，不新建设计）。

        建模状态按设计名快照/恢复。失败返回 False（best-effort #105）。
        """
        if self._ipk is None:
            self._last_message = "未连接：先 connect()"
            return False
        try:
            previous = getattr(self._ipk, "design_name", None)
            self._ipk.set_active_design(design_name)
            self._swap_design_state(previous, design_name)
            return True
        except Exception as exc:
            self._last_message = f"set_active_design({design_name!r}) 失败: {exc}"
            logger.warning(self._last_message)
            return False

    def delete_boundary(self, name: str) -> bool:
        """按名删除既有边界（E2E 重映射前清旧 EMLoss；best-effort #105）。"""
        if self._ipk is None:
            self._last_message = "未连接：先 connect()"
            return False
        try:
            for boundary in list(self._ipk.boundaries):
                if getattr(boundary, "name", None) == name:
                    return bool(boundary.delete())
        except Exception as exc:
            logger.warning("delete_boundary(%s) 失败: %s", name, exc)
        return False

    # ── 几何 / 边界 / 监控 ──────────────────────────────────────────────────

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """构建发热块-基板传导栈（显式单位字符串，#218 同法）。

        参数经 normalize_stack_params 校验；另有布尔/字符串键
        ``monitor_point``：``"block_centroid"``（默认，块内中面监控点，
        温漂链用）或 ``"substrate_midplane"``（锚工况——基板中面线性区
        监控点，通量均匀、剖面线性，网格离散不敏感）。
        调用顺序：connect → 本方法 → solve。发热块置于基板顶面正中
        （满覆锚工况=同足印），基板底面 Dirichlet（stationary wall
        with temperature），块体 assign_solid_block 总功率。
        """
        if self._ipk is None:
            self._last_message = "未连接：先 connect()"
            return False
        geometry = dict(geometry or {})
        monitor_point = str(geometry.pop("monitor_point", "block_centroid"))
        if monitor_point not in ("block_centroid", "substrate_midplane"):
            self._last_message = (
                f"monitor_point 必须是 block_centroid|substrate_midplane，"
                f"收到 {monitor_point!r}")
            return False
        try:
            spec = normalize_stack_params(geometry)
        except ValueError as exc:
            self._last_message = str(exc)
            return False
        if not self._build_stack(spec, monitor_point):
            return False
        self._spec = spec
        self._monitor_point = monitor_point
        self._mode = "stack"
        self._opening_boundary = None
        self._region_extent_mm = None
        self._built = True
        return True

    def _build_stack(self, spec: dict[str, float], monitor_point: str) -> bool:
        """传导栈本体：基板 + 发热块 + 底面 Dirichlet + 块功率 + 温度监控点。

        build_geometry / build_convection_case 共用；成功置 _monitor_name。
        """
        mm = lambda v: f"{v}mm"  # noqa: E731 —— 几何一律显式单位（#218）
        self._monitor_name = None  # 多设计复用同一 adapter：不沿用上一设计的监控名
        try:
            modeler = self._ipk.modeler
            blk_l, blk_w = spec["blk_len_mm"], spec["blk_wid_mm"]
            board_l, board_w = spec["board_len_mm"], spec["board_wid_mm"]
            if blk_l > board_l + 1e-9 or blk_w > board_w + 1e-9:
                self._last_message = "发热块足印不得大于基板足印"
                return False
            modeler.create_box(
                origin=["0mm", "0mm", "0mm"],
                sizes=[mm(board_l), mm(board_w), mm(spec["board_thk_mm"])],
                name="rfauto_sub",
                material=self._make_material("rfauto_sub_mat", spec["board_k_w_mk"]),
            )
            modeler.create_box(
                origin=[mm((board_l - blk_l) / 2.0), mm((board_w - blk_w) / 2.0),
                        mm(spec["board_thk_mm"])],
                sizes=[mm(blk_l), mm(blk_w), mm(spec["blk_thk_mm"])],
                name="rfauto_blk",
                material=self._make_material("rfauto_blk_mat", spec["blk_k_w_mk"]),
            )
            # 基板底面 Dirichlet：z≈0 的面（get_face_center 判读，同 hfss 脚本）
            bottom_face = self._bottom_face_id("rfauto_sub")
            if bottom_face is None:
                self._last_message = "未找到基板底面（z≈0 面）"
                return False
            wall = self._ipk.assign_stationary_wall_with_temperature(
                bottom_face, temperature=f"{spec['t_base_c']}cel", thickness="0mm")
            if wall is None:
                self._last_message = "assign_stationary_wall_with_temperature 失败"
                return False
            self._wall_boundary = _boundary_name(wall)
            # 发热块总功率（损耗导入的集总口径；场级 EM 损耗映射见
            # map_em_losses——pyaedt assign_em_losses / AssignEMLoss）
            block = self._ipk.assign_solid_block(
                "rfauto_blk", f"{spec['power_w']}W")
            if block is None:
                self._last_message = "assign_solid_block 失败"
                return False
            if monitor_point == "substrate_midplane":
                # 锚工况：基板中面监控点（线性剖面区，网格离散不敏感；
                # 首跑块内中面监控 2.79% 网格敏感超 2% 门的对策）
                monitor = self._ipk.assign_point_monitor(
                    [mm(board_l / 2.0), mm(board_w / 2.0),
                     mm(spec["board_thk_mm"] / 2.0)],
                    monitor_type="Temperature",
                    monitor_name="rfauto_T_sub")
            else:
                monitor = self._ipk.assign_point_monitor_in_object(
                    "rfauto_blk", monitor_type="Temperature",
                    monitor_name="rfauto_T_blk")
            if not monitor:
                self._last_message = "温度监控点创建失败"
                return False
            if isinstance(monitor, str) and monitor:
                self._monitor_name = monitor
        except Exception as exc:
            self._last_message = f"构建几何失败: {exc}"
            logger.warning(self._last_message)
            return False
        # pyaedt 成功时返回监控点名，异常时返回 False——bool 兜底回默认名
        if not isinstance(self._monitor_name, str) or not self._monitor_name:
            self._monitor_name = ("rfauto_T_sub" if monitor_point == "substrate_midplane"
                                  else "rfauto_T_blk")
        return True

    def build_convection_case(self, geometry: dict[str, Any]) -> bool:
        """自然对流工况（WP4.4a ②）：传导栈入空气域 + 重力 + 开口 + 环境温度。

        需 problem_type="TemperatureAndFlow"（构造时给；``with_openings``
        =False 的同域纯传导对照设计除外）。在 build_geometry 的传导栈之上
        （底面 Dirichlet 保留=壁面导出路径）：
        - 空气域：AEDT Icepak 自动生成的 Region 改六向 Absolute Offset
          填充（``region_pad_mm``，默认 10mm；无自动 Region 时
          ``modeler.create_region``）；
        - ``edit_design_settings(gravity_dir, ambient_temperature)``：重力
          默认 −Z（DEFAULT_GRAVITY_DIR=2，见常量注释）、环境温度=t_base_c；
        - ``assign_openings(空气域六面)``：开放边界（自然对流进出口）；
        - HeatFlowRate 判据=边界 field summary（壁面 Adjacent 固侧 + 开口
          Default），solve() 汇总 ``energy_balance``。
        额外键：``gravity_dir``（0..5 整数）、``region_pad_mm``（正数）、
        ``with_openings``（默认 True；False=同域不开口——纯传导对照设计，
        与对流设计同几何同网格族、只差流动物理，2025.1 真机实证：无域
        对照网格对小块更细、温度差被网格噪声淹没 242.5 vs 219.7）、
        ``monitor_point``（同 build_geometry）。
        """
        if self._ipk is None:
            self._last_message = "未连接：先 connect()"
            return False
        geometry = dict(geometry or {})
        with_openings = geometry.pop("with_openings", True)
        if not isinstance(with_openings, bool):
            self._last_message = f"with_openings 必须是布尔，收到 {with_openings!r}"
            return False
        if with_openings and self._problem_type != "TemperatureAndFlow":
            self._last_message = (
                f"自然对流工况需 problem_type=TemperatureAndFlow，"
                f"当前 {self._problem_type!r}")
            return False
        geometry = dict(geometry or {})
        monitor_point = str(geometry.pop("monitor_point", "block_centroid"))
        if monitor_point not in ("block_centroid", "substrate_midplane"):
            self._last_message = (
                f"monitor_point 必须是 block_centroid|substrate_midplane，"
                f"收到 {monitor_point!r}")
            return False
        gravity_raw = geometry.pop("gravity_dir", DEFAULT_GRAVITY_DIR)
        if (isinstance(gravity_raw, bool) or not isinstance(gravity_raw, int)
                or not 0 <= gravity_raw <= 5):
            self._last_message = f"gravity_dir 必须是 0..5 整数，收到 {gravity_raw!r}"
            return False
        pad_raw = geometry.pop("region_pad_mm", 10.0)
        try:
            pad_mm = float(pad_raw)
        except (TypeError, ValueError):
            self._last_message = f"region_pad_mm 必须是正实数，收到 {pad_raw!r}"
            return False
        if not math.isfinite(pad_mm) or pad_mm <= 0.0:
            self._last_message = f"region_pad_mm 必须是正实数，收到 {pad_raw!r}"
            return False
        try:
            spec = normalize_stack_params(geometry)
        except ValueError as exc:
            self._last_message = str(exc)
            return False
        if not self._build_stack(spec, monitor_point):
            return False
        try:
            modeler = self._ipk.modeler
            # 空气域：AEDT Icepak 建首个实体时**自动生成 Region**（2025.1 真机
            # 实证：create_region 报 "Region object already exists"）——优先
            # 经 mesh.global_mesh_region.global_region 改既有 Region 的六向
            # 填充为 Absolute Offset（pyaedt mesh_icepak.py:301-313 setter），
            # 无自动 Region 时才 create_region；顺序 +X,-X,+Y,-Y,+Z,-Z
            region_name = self._configure_air_region(pad_mm)
            if region_name is None:
                return False
            if not self._ipk.edit_design_settings(
                    gravity_dir=gravity_raw,
                    ambient_temperature=spec["t_base_c"]):
                self._last_message = "edit_design_settings（重力/环境温度）失败"
                return False
            # 填充改完后再取面（Region 面随填充重生成）
            air_faces = [int(f) for f in modeler.get_object_faces(region_name)]
            if not air_faces:
                self._last_message = "空气域无面可开口"
                return False
            self._region_extent_mm = self._faces_extent_mm(air_faces)
            if with_openings:
                opening = self._ipk.assign_openings(air_faces)
                if opening is None:
                    self._last_message = "assign_openings 失败"
                    return False
                # 出热判据数据源=边界名（solve 后 field summary 按边界取
                # HeatFlowRate 总量）：面 id 监控在 Region 重生成时被 AEDT 删
                # （"lost its assignment"，2025.1 实证 6 丢 2）、对象级面监控
                # 对 3D Region 报 AssignFaceMonitor 失败——两坑均已真机踩实
                self._opening_boundary = _boundary_name(opening)
                if not self._wall_boundary or not self._opening_boundary:
                    self._last_message = "边界名缺失：无法建立出热判据"
                    return False
            elif self._problem_type == "TemperatureAndFlow":
                self._last_message = (
                    "同域不开口对照设计需 problem_type=TemperatureOnly"
                    "（TemperatureAndFlow 下无开口=绝热闭腔，无热出口）")
                return False
        except Exception as exc:
            self._last_message = f"构建自然对流工况失败: {exc}"
            logger.warning(self._last_message)
            return False
        self._spec = spec
        self._monitor_point = monitor_point
        self._mode = "convection"
        self._built = True
        return True

    def _faces_extent_mm(self, faces: list[int]) -> dict[str, float] | None:
        """按面心估计对象包围盒（mm，诊断用：核对空气域填充是否生效）。"""
        try:
            modeler = self._ipk.modeler
            xs: list[float] = []
            ys: list[float] = []
            zs: list[float] = []
            for f in faces:
                cx, cy, cz = modeler.get_face_center(f)
                xs.append(_mm_float(cx))
                ys.append(_mm_float(cy))
                zs.append(_mm_float(cz))
            if not xs:
                return None
            return {"x_min": min(xs), "x_max": max(xs), "y_min": min(ys),
                    "y_max": max(ys), "z_min": min(zs), "z_max": max(zs)}
        except Exception as exc:  # 诊断信息 best-effort（#105）
            logger.info("空气域包围盒读取失败（忽略）: %s", exc)
            return None

    def _configure_air_region(self, pad_mm: float) -> str | None:
        """六向 Absolute Offset 空气域：改既有自动 Region 或新建；返回域名。"""
        modeler = self._ipk.modeler
        region = None
        region_obj = None
        try:
            region = self._ipk.mesh.global_mesh_region.global_region
            region_obj = region.object
        except Exception as exc:  # 无自动 Region / 旧版 pyaedt 无该属性
            logger.info("global_region 不可用（%s），改走 create_region", exc)
        pads = [f"{pad_mm}mm"] * 6
        if region is not None and region_obj is not None:
            region.padding_types = ["Absolute Offset"] * 6
            region.padding_values = pads
            return str(getattr(region_obj, "name", "Region") or "Region")
        created = modeler.create_region(pads, pad_type="Absolute Offset",
                                        name="Region")
        if not created:
            self._last_message = "create_region 失败"
            return None
        return str(getattr(created, "name", "Region") or "Region")

    def build_ring_substrate_case(self, geometry: dict[str, Any]) -> bool:
        """环形谐振器基板热工况（WP4.4a ① 场级损耗映射的接收几何）。

        坐标/命名与 HFSS 源设计逐一对齐（映射按空间+同名双保险）：
        - ``rfauto_sub``：基板外体（中心在原点，含环带孔）；
        - ``rfauto_sub_ring``：环足印下的环带体（同材料，全基板厚度）；
        - 底面 Dirichlet（t_base_c）+ 底面 HeatFlowRate 面监控
          （映射总功率的守恒判据数据源，TemperatureOnly 下唯一出热口）；
        - 环带中面温度监控点 ``rfauto_T_ring``（(r_mean, 0, h/2)）；
        - ``power_w``>0 时环带体加 assign_solid_block 集总体热源（同功率
          集总对照设计）；=0 为场级映射接收设计（损耗由 map_em_losses 注入）。
        """
        if self._ipk is None:
            self._last_message = "未连接：先 connect()"
            return False
        self._monitor_name = None
        try:
            spec = normalize_ring_params(geometry)
        except ValueError as exc:
            self._last_message = str(exc)
            return False
        mm = lambda v: f"{v}mm"  # noqa: E731
        try:
            modeler = self._ipk.modeler
            bl, bw = spec["board_len_mm"], spec["board_wid_mm"]
            k_sub = spec["board_k_w_mk"]
            modeler.create_box(
                origin=[mm(-bl / 2.0), mm(-bw / 2.0), "0mm"],
                sizes=[mm(bl), mm(bw), mm(spec["board_thk_mm"])],
                name="rfauto_sub",
                material=self._make_material("rfauto_sub_mat", k_sub),
            )
            # 环带体（CylinderCS 原语：orientation="Z"、原点在环心 z=0）
            modeler.create_cylinder(
                orientation="Z",
                origin=["0mm", "0mm", "0mm"],
                radius=mm(spec["ring_r_out_mm"]),
                height=mm(spec["board_thk_mm"]),
                name="rfauto_sub_ring",
                material=self._make_material("rfauto_sub_mat", k_sub),
            )
            modeler.subtract("rfauto_sub", ["rfauto_sub_ring"],
                             keep_originals=True)
            bottom_face = self._bottom_face_id("rfauto_sub")
            if bottom_face is None:
                self._last_message = "未找到基板底面（z≈0 面）"
                return False
            wall = self._ipk.assign_stationary_wall_with_temperature(
                bottom_face, temperature=f"{spec['t_base_c']}cel",
                thickness="0mm")
            if wall is None:
                self._last_message = "assign_stationary_wall_with_temperature 失败"
                return False
            self._wall_boundary = _boundary_name(wall)
            self._opening_boundary = None
            self._region_extent_mm = None
            if not self._wall_boundary:
                self._last_message = "壁面边界名缺失：无法建立出热判据"
                return False
            r_mean = (spec["ring_r_in_mm"] + spec["ring_r_out_mm"]) / 2.0
            monitor = self._ipk.assign_point_monitor(
                [mm(r_mean), "0mm", mm(spec["board_thk_mm"] / 2.0)],
                monitor_type="Temperature", monitor_name="rfauto_T_ring")
            if not monitor:
                self._last_message = "温度监控点创建失败"
                return False
            if isinstance(monitor, str) and monitor:
                self._monitor_name = monitor
            if spec["power_w"] > 0.0:
                block = self._ipk.assign_solid_block(
                    "rfauto_sub_ring", f"{spec['power_w']}W")
                if block is None:
                    self._last_message = "assign_solid_block 失败"
                    return False
            # 环带区网格加密（映射保真度）：HFSS 损耗场插值到 Icepak 网格，
            # 默认网格对 1mm 级环带欠分辨会把映射总功率抹低（2025.1 真机
            # 实测映射只有源口径的 65%）。手动设置显式单元尺寸（level 预设
            # 不够细）；失败不阻塞（best-effort #105，保真度由守恒判据把关）
            try:
                self._ipk.modeler.model_units = "mm"
                # 注意：网格区域只能给环带体——全基板 0.5/0.25mm 显式网格
                # 实测把求解搞坏（T=1367C、壁面出热 0.00009W，2025.1 真机）
                mr = self._ipk.mesh.assign_mesh_region(
                    assignment=["rfauto_sub_ring"], level=5)
                if mr:
                    mr.manual_settings = True
                    mr.settings["MaxElementSizeX"] = 0.5
                    mr.settings["MaxElementSizeY"] = 0.5
                    mr.settings["MaxElementSizeZ"] = 0.25
                    mr.update()
            except Exception as exc:
                logger.warning("assign_mesh_region 失败（忽略）: %s", exc)
        except Exception as exc:
            import traceback

            self._last_message = (
                f"构建环形基板工况失败: {exc!r} | tb="
                f"{' <- '.join(traceback.format_exc().strip().splitlines()[-4:])}")
            logger.warning(self._last_message)
            return False
        if not isinstance(self._monitor_name, str) or not self._monitor_name:
            self._monitor_name = "rfauto_T_ring"
        self._spec = spec
        self._monitor_point = "ring_midplane"
        self._mode = "ring"
        self._built = True
        return True

    def read_heat_flow_rates(self) -> dict[str, Any] | None:
        """按边界名取 HeatFlowRate 总量（W）：壁面导出 + 开口对流；未建→None。

        走 pyaedt ``post.evaluate_boundary_quantity``（field summary，
        ExportFieldsSummary 按边界积分）返回 {"Total": v, "Unit": "W"}；
        取绝对值（面法向符号约定不参与能量平衡判据）。任一边界读不到
        数值即返回 None（不臆造）。环形工况只有壁面（openings_w=0）。
        """
        if self._ipk is None or self._mode not in ("convection", "ring") \
                or not self._setup_name or not self._wall_boundary:
            return None
        setup_full = f"{self._setup_name} : SteadyState"

        def _total(boundary: str, side: str) -> float | None:
            report = self._ipk.post.evaluate_boundary_quantity(
                boundary=boundary, quantity="HeatFlowRate", side=side,
                setup_name=setup_full)
            return _total_from_summary(report)

        try:
            # 壁面取 solid 侧（side="Adjacent"）：Dirichlet 面是固/气内部面，
            # Default=空气侧（2025.1 真机实测 0.0004W vs Adjacent 0.4992W——
            # 能量守恒真值在固侧出热）
            wall = _total(self._wall_boundary, "Adjacent")
            if wall is None:
                return None
            openings_w = 0.0
            if self._opening_boundary:
                value = _total(self._opening_boundary, "Default")
                if value is None:
                    return None
                openings_w = abs(value)
        except Exception as exc:
            logger.warning("HeatFlowRate 边界读取失败: %s", exc)
            return None
        return {
            "wall_w": abs(wall),
            "openings_w": openings_w,
            "total_w": abs(wall) + openings_w,
            "wall_boundary": self._wall_boundary,
            "opening_boundary": self._opening_boundary,
            "wall_side": "Adjacent",
        }

    def _desktop_msgs(self) -> str:
        """抓 AEDT 消息窗最近几条（诊断用，best-effort #105，失败返回空）。"""
        try:
            msgs = [str(m).strip() for m in
                    self._ipk.odesktop.GetMessages("", "", 0)[-4:]]
            return "last_msgs=" + " ~~ ".join(msgs) if msgs else ""
        except Exception:
            return ""

    def _make_material(self, name: str, k_w_mk: float) -> str:
        """确保热材料存在并返回名字（幂等；已有同名则改热导率）。"""
        materials = self._ipk.materials
        if name not in materials.material_keys:
            materials.add_material(name, properties={"thermal_conductivity": k_w_mk})
        else:
            materials.material_keys[name].thermal_conductivity = k_w_mk
        return name

    def _bottom_face_id(self, obj_name: str) -> int | None:
        """取物体 z≈min-z 的面 id（基板底面）。

        get_face_center 失败时 pyaedt 返回 False（gRPC 面心读取偶发失败），
        跳过非法返回值而不是让 'bool' object is not subscriptable 掩盖真因。
        """
        modeler = self._ipk.modeler
        faces = modeler.get_object_faces(obj_name)
        centers = [modeler.get_face_center(f) for f in faces]
        valid = [(f, c) for f, c in zip(faces, centers, strict=True)
                 if isinstance(c, (list, tuple)) and len(c) >= 3]
        if not valid:
            return None
        z_values = [float(c[2].replace("mm", "")) if isinstance(c[2], str)
                    else float(c[2]) for _, c in valid]
        z_min = min(z_values)
        for (face_id, _), z in zip(valid, z_values, strict=True):
            if abs(z - z_min) < 1e-6:
                return int(face_id)
        return None

    # ── 求解 / 提取 ─────────────────────────────────────────────────────────

    def solve(self, timeout_s: float | None = None) -> EMSolverResult:
        """稳态热求解 → 监控点温度 → 1-D 传导锚对照（门 ≤2%）。

        失败一律 success=False + 明确 message（best-effort #105）。
        """
        started = time.perf_counter()
        if self._ipk is None or not self._built or self._spec is None:
            return EMSolverResult(success=False,
                                  message="未连接或未建模：先 connect()+build_geometry()")
        try:
            if self._setup_name is None:
                setup = self._ipk.create_setup("rfauto_et_setup")
                setup.props["Convergence Criteria - Max Iterations"] = \
                    int(self._spec["max_iterations"])
                if self._mode == "convection":
                    # 重力开关在 **setup 级**且默认 False（2025.1 真机实证：
                    # 不开则浮升力为零、流动场零解，温度场与纯传导逐位相同、
                    # 开口出热恒 0——自然对流必须显式开）
                    setup.props["Include Gravity"] = True
                self._setup_name = "rfauto_et_setup"
            # 同一设计重解（E2E 第二轮重映射后）复用既有 setup，不重复创建
            analyze_ok = bool(self._ipk.analyze(self._setup_name))
            if not analyze_ok:
                # analyze 失败还去 evaluate 只会在空 variations 上 IndexError
                # 掩盖真因——快速失败并抓 AEDT 消息窗（#105 best-effort）
                return EMSolverResult(
                    success=False,
                    wall_time_s=time.perf_counter() - started,
                    message=f"Icepak 求解失败（analyze=False）{self._desktop_msgs()}")
            report = self._ipk.post.evaluate_monitor_quantity(
                monitor=self._monitor_name, quantity="Temperature",
                setup_name=f"{self._setup_name} : SteadyState")
        except Exception as exc:
            return EMSolverResult(
                success=False,
                wall_time_s=time.perf_counter() - started,
                message=f"Icepak 求解失败: {exc!r} {self._desktop_msgs()}")
        wall = time.perf_counter() - started

        t_hot = _temperature_from_summary(report)
        if t_hot is None:
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"温度提取失败：{report!r}")
        rise = t_hot - self._spec["t_base_c"]
        if self._mode == "ring":
            # 环形工况无 1-D 传导闭式锚（损耗分布非 1-D）：闭式对照如实 None
            anchor = {"t_monitor_c": None, "rise_k": None}
            ref_rise = None
            rel_dev = None
        elif self._monitor_point == "substrate_midplane":
            # 锚工况：基板中面线性区（均匀通量，Fourier 线性闭式）
            anchor = conduction_uniform_flux_rise_k(
                power_w=self._spec["power_w"],
                area_m2=(self._spec["board_len_mm"] * 1e-3)
                * (self._spec["board_wid_mm"] * 1e-3),
                depth_m=self._spec["board_thk_mm"] * 0.5e-3,
                k_w_mk=self._spec["board_k_w_mk"],
                t_base_c=self._spec["t_base_c"])
            ref_rise = anchor["rise_k"]
            rel_dev = abs(rise - ref_rise) / abs(ref_rise) if ref_rise else 0.0
        else:
            anchor = anchor_closed_form_c(self._spec)
            ref_rise = anchor["rise_k"]
            rel_dev = abs(rise - ref_rise) / abs(ref_rise) if ref_rise else 0.0
        anchor_out = {
            "monitor_point": self._monitor_point,
            "t_sim_c": t_hot,
            "t_closed_form_c": anchor["t_monitor_c"],
            "rise_sim_k": rise,
            "rise_closed_form_k": ref_rise,
            "relative_deviation": rel_dev,
            "pass_2pct": (None if ref_rise is None
                          else rel_dev <= ANCHOR_TOLERANCE),
        }
        if self._mode not in ("convection", "ring"):
            message = (f"Icepak 真跑成功：T={t_hot:.4f}C，闭式锚"
                       f"={anchor['t_monitor_c']:.4f}C，相对偏差={rel_dev * 100:.3g}%")
            field_data: dict[str, Any] = {
                "t_blk_c": t_hot,
                "monitor_point": self._monitor_point,
                "anchor": anchor_out,
                "spec": dict(self._spec),
            }
            self._last_field = field_data
            return EMSolverResult(success=True, wall_time_s=wall,
                                  field_data=field_data, message=message)
        # 自然对流 / 环形基板（场级映射）模式：传导闭式不再作验收门
        # （对流多一条并联散热路径 / 环带损耗分布非 1-D），温度对闭式的
        # 偏差仅记录不判门；验收数据 = HeatFlowRate 监控（守恒判据由
        # 脚本对 HFSS |S|² 口径耗散功率做 ≤5% 判，能量平衡门仅对流模式）。
        heat = self.read_heat_flow_rates()
        if heat is None:
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message="判据数据失败：HeatFlowRate 监控读取不到数值")
        p_in = self._spec["power_w"]
        anchor_out["mode"] = self._mode
        if self._mode == "convection":
            balance_rel = abs(heat["total_w"] - p_in) / p_in
            cooler_than_conduction = rise < ref_rise
            energy_ok = balance_rel <= ENERGY_BALANCE_TOLERANCE
            anchor_out["energy_balance"] = {
                "p_in_w": p_in,
                "wall_w": heat["wall_w"],
                "openings_w": heat["openings_w"],
                "total_out_w": heat["total_w"],
                "relative_imbalance": balance_rel,
                "tolerance": ENERGY_BALANCE_TOLERANCE,
                "pass": energy_ok,
            }
            anchor_out["physically_healthy"] = cooler_than_conduction
            anchor_out["pass_2pct"] = bool(energy_ok and cooler_than_conduction)
            message = (f"Icepak 自然对流真跑：T={t_hot:.4f}C，能量平衡"
                       f"偏差={balance_rel * 100:.2g}%（门"
                       f"{ENERGY_BALANCE_TOLERANCE * 100:.0g}%），"
                       f"低于纯传导对照={cooler_than_conduction}")
        else:
            anchor_out["pass_2pct"] = None  # 环形工况无 1-D 闭式锚（如实 None）
            message = (f"Icepak 环形基板真跑：T={t_hot:.4f}C，"
                       f"底面出热={heat['wall_w']:.6g}W")
        field_data = {
            "t_blk_c": t_hot,
            "monitor_point": self._monitor_point,
            "mode": self._mode,
            "anchor": anchor_out,
            "heat_flow": heat,
            "region_extent_mm": self._region_extent_mm,
            "spec": dict(self._spec),
        }
        self._last_field = field_data
        return EMSolverResult(success=True, wall_time_s=wall,
                              field_data=field_data, message=message)

    def get_sparams(self) -> tuple[Any, Any]:
        """热通道不产出 S 参数（显式报错，不返回伪数据）。"""
        raise NotImplementedError("IcepakAdapter 是热通道，不产出 S 参数")

    def temperature_field(self) -> dict[str, Any] | None:
        """最近一次求解的温度场数据（solve().field_data：监控点温度+锚对照）；
        未求解返回 None（不臆造，同 Elmer 通道口径）。"""
        return self._last_field

    def close(self) -> None:
        """保存（可选）并释放桌面（best-effort，不抛异常）。

        pyaedt 1.4.0 Design.release_desktop 签名为
        (close_projects=True, close_desktop=True)（真机实证 2025.1 gRPC：
        无 close_on_exit 形参，传错会 AEDT ERROR 后由 Desktop 默认释放）。
        """
        if self._ipk is None:
            return
        try:
            if self._save_project:
                self._ipk.save_project()
            self._ipk.release_desktop(close_projects=False, close_desktop=True)
        except Exception as exc:
            logger.warning("关闭 AEDT 失败（忽略）: %s", exc)
        finally:
            self._ipk = None
            self._design_state = {}
            self._connected = False

    # ── EM 损耗映射（方案注记的 API 名，端到端真跑为后续项）────────────────

    def map_em_losses(self, payload: dict[str, Any]) -> dict[str, Any]:
        """HFSS/Q3D → Icepak 损耗映射（pyaedt `assign_em_losses` 薄封装）。

        payload: {"assignment": obj|list, "design": str, "setup": str,
                  "sweep": str, "map_frequency": str|float|None,
                  "source_project_name": str|None, "loss_multiplier": float}
        需要同工程内已解的源设计；失败返回 {"ok": False, "error": ...}。
        """
        if self._ipk is None:
            return {"ok": False, "error": "未连接：先 connect()"}
        try:
            boundary = self._ipk.assign_em_losses(
                payload["assignment"], payload["design"], payload["setup"],
                payload["sweep"],
                map_frequency=payload.get("map_frequency"),
                source_project_name=payload.get("source_project_name"),
                loss_multiplier=payload.get("loss_multiplier", 1.0),
            )
        except Exception as exc:
            return {"ok": False, "error": f"assign_em_losses 失败: {exc}"}
        if boundary is None:
            return {"ok": False, "error": "assign_em_losses 返回 None（见 AEDT 消息窗口）"}
        return {"ok": True, "boundary_name": getattr(boundary, "name", None)}


def _temperature_from_summary(report: Any) -> float | None:
    """从 evaluate_monitor_quantity 返回体提取监控点温度 [°C]。

    点监控返回 {"Max"/"Mean"/"Min": value, "Unit": "cel"}；value 可能是
    float 或带单位字符串（如 "61.3cel"），提取首个数值 token（单位默认
    cel，不换算）。
    """
    if not isinstance(report, dict):
        return None
    for key in ("Mean", "Max", "Value"):
        raw = report.get(key)
        if raw is None:
            continue
        match = _NUMBER_RE.search(str(raw))
        if match is not None:
            try:
                return float(match.group(0))
            except ValueError:  # pragma: no cover - 正则保证可 float
                continue
    return None


def _total_from_summary(report: Any) -> float | None:
    """从 evaluate_*_quantity 返回体提取积分量总量 [W]。

    面/体/边界积分量返回 {"Total": value, "Unit": "W"}；value 可能是 float
    或带单位字符串，提取首个数值 token；读不到返回 None（不臆造）。
    """
    if not isinstance(report, dict):
        return None
    raw = report.get("Total")
    if raw is None:
        return None
    match = _NUMBER_RE.search(str(raw))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:  # pragma: no cover - 正则保证可 float
        return None


def _boundary_name(boundary: Any) -> str | None:
    """pyaedt BoundaryObject → 名字（无名/非对象 → None，不臆造）。"""
    name = getattr(boundary, "name", None)
    return str(name) if isinstance(name, str) and name else None


def _mm_float(raw: Any) -> float:
    """pyaedt 面心坐标（float 或 "12.0mm" 串）→ float [mm]。"""
    if isinstance(raw, str):
        return float(raw.replace("mm", "").strip())
    return float(raw)


# ── 注册（把 Icepak 通道接入全局注册表）──────────────────────────────────────

def register_icepak_adapter(registry: Any | None = None) -> None:
    """向求解器注册表注册 Icepak 通道（调用方显式调用，同 Elmer 通道）。"""
    reg = registry or get_global_registry()
    reg.register(EMSolverType.ICEPAK, IcepakAdapter)
