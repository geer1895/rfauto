"""核心抽象接口（§7.2 / §7.3）—— RFModelPlugin + SimulatorAdapter + JobHandle。

P0–P4 期间标注 EXPERIMENTAL，允许修改签名（ADR-0002）。
P5 第三实例完成后冻结，只增不改。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

# ─── JobHandle ────────────────────────────────────────────────────────────────

@dataclass
class JobHandle:
    """任务句柄——所有长时间运行的服务函数返回此对象。"""
    job_id: str
    run_id: str = ""


@dataclass
class SolveReport:
    """求解结果摘要。"""
    success: bool
    passes: int = 0
    delta_s_final: float = 0.0
    wall_time_s: float = 0.0
    message: str = ""


# ─── Adapter Capabilities ─────────────────────────────────────────────────────

class AdapterCapabilities(BaseModel):
    """适配器能力声明——可选方法调用前必须先查此表。"""
    supports_wave_port: bool = False
    supports_lumped_port: bool = True
    supports_field_export: bool = False
    supports_convergence_report: bool = True
    supports_touchstone_export: bool = True
    supports_headless_solve: bool = True
    supports_optimetrics: bool = False


class PortInfo(BaseModel):
    """端口信息。"""
    name: str
    kind: str = "lumped"  # "lumped" | "wave"
    impedance_ohm: float = 50.0
    renormalize: bool = True


class ConvergenceReport(BaseModel):
    """收敛报告。"""
    converged: bool
    passes: int
    delta_s_final: float
    max_delta_s: float = 0.0


# ─── SimulatorAdapter (§7.3) ─────────────────────────────────────────────────

class SimulatorAdapter(ABC):
    """仿真器适配器协议——核心八方法（P0–P4 EXPERIMENTAL）。

    硬性约束：
    - 核心包不引 EDA SDK：SDK import 仅在具体 adapter 实现内
    - 长任务返回 JobHandle，永不阻塞调用方
    - build 时强制命名规范校验
    """

    @abstractmethod
    def connect(self, settings: dict[str, Any]) -> None:
        """幂等连接：已连则复用。"""

    @abstractmethod
    def open_or_create_project(self, path: str | Path, design_name: str) -> None:
        """打开或创建项目。"""

    @abstractmethod
    def set_variables(self, vars: dict[str, str]) -> None:
        """设置设计变量——局部改动第一通道。"""

    @abstractmethod
    def build_and_setup(self, builder: Callable[[SimulatorAdapter], None], setup: Any) -> None:
        """执行构建器函数 + 设置求解器。"""

    @abstractmethod
    def solve(self, setup_name: str, timeout_s: int = 3600) -> SolveReport:
        """求解并返回报告（内含轮询）。"""

    @abstractmethod
    def get_sparams(self) -> Any:
        """统一返回 skrf.Network，屏蔽工具差异。"""

    @abstractmethod
    def export_touchstone(self, path: str | Path, contract: Any = None) -> Path:
        """按契约导出 Touchstone 文件。"""

    @abstractmethod
    def close(self, save: bool = True) -> None:
        """关闭会话。"""

    # ─── 可选方法层（调用前查 capabilities）────────────────────────────────────

    def capabilities(self) -> AdapterCapabilities:
        """返回适配器能力声明。"""
        return AdapterCapabilities()

    def list_ports(self) -> list[PortInfo]:
        """列出端口信息。"""
        raise NotImplementedError

    def get_convergence(self) -> ConvergenceReport | None:
        """获取收敛报告。"""
        return None

    def get_solver_log(self) -> Path | None:
        """获取求解器日志路径。"""
        return None

    def raw_escape(self, *args: Any, **kwargs: Any) -> Any:
        """oEditor 等原生逃逸口（使用须记录改动依据）。"""
        raise NotImplementedError("raw_escape 未实现，请检查 capabilities")

    def get_far_field(self, setup_name: str, freq_ghz: float = 2.4) -> dict[str, Any] | None:
        """获取远场数据（天线方向图）。

        Args:
            setup_name: 求解器 setup 名称
            freq_ghz: 频率 (GHz)

        Returns:
            dict with keys: theta, phi, gain_db, pattern_type
            None if not supported
        """
        return None

    def health_check(self) -> bool:
        """健康检查：连接是否存活。"""
        return True

    def ensure_connected(self) -> None:
        """自愈重连：连接掉线（license 回收等）后重建会话。

        实现应带退避；重试耗尽抛 ConnectFailedError。
        """
        raise NotImplementedError("ensure_connected 未实现")


# ─── RFModelPlugin (§7.2) ────────────────────────────────────────────────────

class RFModelPlugin(ABC):
    """模板插件协议——每个射频模型（功分器/耦合器/天线…）实现此接口。

    新模型 = 新目录，零改核心。
    第三个实例出现时才把共性抽进 base 脚手架。
    """

    name: ClassVar[str]
    params_model: ClassVar[type[BaseModel]]           # 参数 schema
    schema_version: ClassVar[int] = 1

    @classmethod
    def supports_recipe_version(cls, version: int) -> bool:
        """检查是否支持指定的配方版本。

        v1 永久支持（向后兼容）；v2 需要插件显式声明。
        """
        return version <= cls.schema_version                 # 插件参数 schema 版本
    # ── 端口/解析近似元数据（C4 新增，可选声明，缺省保持 3 端口 wilkinson 行为）──
    # n_ports 驱动交换契约 port_order 生成与 Touchstone 扩展名 (.sNp)；
    # fake_model_type 选择 FakeAdapter 的解析近似模型。
    n_ports: ClassVar[int] = 3
    fake_model_type: ClassVar[str] = "wilkinson"
    # 配方参数名 → 设计变量名 映射（2026-08-30 调谐闭环修复）：
    # 插件 build 写入的设计变量通常不带单位后缀（arm_len_mm → arm_len），
    # 优化器增量写参必须按此映射才作用于几何；缺省恒等映射。
    hfss_var_map: ClassVar[dict[str, str]] = {}

    @abstractmethod
    def build(self, ad: SimulatorAdapter, params: BaseModel) -> None:
        """声明式构建：创建 design → 设置变量 → 画几何（显式命名）→ 赋材料 → 端口/边界 → 默认 setup。

        硬性约束：
        - 尺寸只经 hfss['VarName']=value 写成变量再以表达式引用
        - 对象命名用 builder 常量表
        - 端口/边界绑定只允许命名对象或参数坐标推导的辅助面
        """

    def migrate(self, recipe: dict, from_ver: int) -> dict:
        """可选：旧版本配方 → 当前 schema 的迁移。"""
        return recipe

    def on_variable_change_repair(self, ad: SimulatorAdapter, params: BaseModel) -> None:
        """可选：改参后的修补钩子。"""

    def evaluate_extras(self, metrics: dict[str, float]) -> dict[str, float]:
        """可选：领域专属指标扩展。"""
        return metrics
