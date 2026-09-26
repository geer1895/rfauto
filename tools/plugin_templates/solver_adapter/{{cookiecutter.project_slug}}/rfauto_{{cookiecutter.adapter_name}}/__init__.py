"""{{ cookiecutter.adapter_name }} 适配器插件（rfauto 第三方求解器接入）。

由 rfauto 插件模板（tools/plugin_templates/solver_adapter）生成。
契约：EMSolverAdapter 六抽象方法（connect/is_available/build_geometry/
solve/get_sparams/close），导入即注册（模块级 register_ 函数）。

生成的适配器是**确定性合成通道**骨架：solve 产出确定性 S 参数（无真实
求解器也可跑通注册→dry-run 全链），替换真实求解器调用时保持方法签名
与注册面不变。
"""

from __future__ import annotations

import contextlib

import numpy as np

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    get_global_registry,
)

#: 求解器类型键：EMSolverType 枚举之外的自定义 EDA 用原始字符串
SOLVER_TYPE = "{{ cookiecutter.adapter_name }}"


class {{ cookiecutter.adapter_class }}(EMSolverAdapter):
    """{{ cookiecutter.adapter_name }} 求解器适配器（合成 dry-run 骨架）。

    #154 param_semantics（必填）：同名参数跨通道语义可能相反（series/
    shunt 实证）——每个模板的每个几何参数在本通道的物理角色必须显式
    声明，缺失会被 check_param_semantics 拦截。
    """

    #: dict[模板名][参数名] = 物理角色描述（按真实通道逐项补齐）
    param_semantics: dict[str, dict[str, str]] = {
        "*": {
            # "w_mm": "导体宽度（本通道：正几何量，越大阻抗越低）",
        },
    }

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        self._freq: np.ndarray | None = None
        self._sparams: np.ndarray | None = None

    def connect(self) -> bool:
        """连接求解器（骨架：恒可用，无外部进程）。"""
        self._connected = True
        return True

    def is_available(self) -> bool:
        return True

    def build_geometry(self, geometry: dict) -> bool:
        """声明式几何（骨架：仅登记，不画图）。"""
        if not self._connected:
            return False
        self._geometry = dict(geometry or {})
        return True

    def solve(self) -> EMSolverResult:
        """求解（骨架：确定性合成 S 参数，验证链路非物理）。

        真实接入点：在这里调用你的求解器 exe/API，把结果转成
        EMSolverResult（freq_ghz + s_params shape=(n_freq, n_ports,
        n_ports)）。合成谱 = 带内 -20dB S11 的 1 端口最小形态。
        """
        if not self._connected:
            return EMSolverResult(success=False)
        f0, f1 = self._config.freq_range_ghz
        freq = np.linspace(f0, f1, 201)
        s11 = np.full(freq.shape, 0.1 + 0.0j)  # 确定性，|S11|=0.1
        s = np.zeros((freq.size, 1, 1), dtype=complex)
        s[:, 0, 0] = s11
        self._freq = freq
        self._sparams = s
        return EMSolverResult(success=True, freq_ghz=freq, s_params=s)

    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        if self._freq is None or self._sparams is None:
            raise RuntimeError("solve() 尚未执行（先 solve 再取 S 参数）")
        return self._freq, self._sparams

    def close(self) -> None:
        self._connected = False


def register_{{ cookiecutter.adapter_name }}(registry=None):
    """注册到全局 EMSolverRegistry（导入即注册模式，同 openems/comsol/palace）。"""
    (registry if registry is not None else get_global_registry()).register(
        SOLVER_TYPE, {{ cookiecutter.adapter_class }}
    )


with contextlib.suppress(Exception):
    register_{{ cookiecutter.adapter_name }}()
