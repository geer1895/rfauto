r"""ADS 交换契约（§8.2）—— 端口顺序错乱是'不报错但优化方向全错'的隐蔽灾难。

两台软件不要求同机同进程同时打开；数据交换介质只有 Touchstone 文件 + 网表/数据集文件。
单位与参考阻抗严格随契约走，interchange.py 在导出与导入两侧都做契约校验。

端口顺序的形式化规则：
  1. 每个 token 必须匹配正则 ^(input|output_\d+)$；
  2. "input" 恰好出现一次；
  3. output_N 的序号 N 必须严格递增 —— 形如 [input, output_2, output_1] 即判非法。

设计依据：Touchstone 文件本身不含端口语义名，无法从 .sNp 直接判定语义顺序；
上述规则是唯一能在无 GUI、纯文本层面确定判定的形式化约束。
"""

from __future__ import annotations

import itertools
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

#: port_order 允许的 token 形式
PORT_TOKEN_RE = re.compile(r"^(input|output_\d+)$")
#: 提取 output_N 的序号
_OUTPUT_INDEX_RE = re.compile(r"^output_(\d+)$")


class TouchstoneContract(BaseModel):
    """Touchstone 文件交换契约。"""

    renormalization_ohm: float = Field(default=50.0, gt=0, description="参考阻抗 (Ω)")
    port_order: list[str] = Field(
        default=["input", "output_1", "output_2"],
        description="端口语义顺序（HFSS P1/P2/P3 ↔ 此映射）",
    )
    frequency_unit: Literal["GHz", "MHz", "kHz", "Hz"] = Field(default="GHz")
    parameter_format: Literal["db_angle", "ma_angle", "ri"] = Field(default="db_angle")
    deembed: bool = Field(default=False, description="是否去嵌")


class AdsContract(BaseModel):
    """ADS 侧契约。"""

    dataset_export: list[str] = Field(
        default_factory=lambda: ["system_gain_db", "input_vswr", "amplitude_balance_db"],
        description="需要导出的系统级指标",
    )
    netlist_template: str = Field(
        default="linkage/templates/ads/wilkinson_snp.net",
        description="版本化网表模板路径",
    )


class AdsExchangeContract(BaseModel):
    """完整的 ADS 交换契约——recipe 声明、pydantic 校验、export/导入两侧共同遵守。"""

    touchstone: TouchstoneContract = Field(default_factory=TouchstoneContract)
    ads: AdsContract = Field(default_factory=AdsContract)

    @classmethod
    def for_n_ports(cls, n_ports: int) -> AdsExchangeContract:
        """按端口数生成标准契约：1 个 input + (n-1) 个严格递增 output。

        port_order 形式化规则（下方 validator）天然接受该序列。n_ports=3 时
        与历史默认值 ["input", "output_1", "output_2"] 完全一致。
        """
        if n_ports < 1:
            raise ValueError(f"n_ports 必须 ≥ 1，实际 {n_ports}")
        port_order = ["input"] + [f"output_{i}" for i in range(1, n_ports)]
        return cls(touchstone=TouchstoneContract(port_order=port_order))

    @model_validator(mode="after")
    def validate_port_order(self) -> AdsExchangeContract:
        """端口顺序校验：非空 / 无重复 / token 形式 / input 唯一 / output_N 严格递增。

        第 3~5 条是 P3 新增的形式化规则：故意给错端口顺序时流程必须显式报错，
        而不是静默通过导致优化方向全错。
        """
        ports = self.touchstone.port_order
        if not ports:
            raise ValueError("port_order 不能为空")
        if len(ports) != len(set(ports)):
            raise ValueError(f"port_order 有重复: {ports}")

        bad = [t for t in ports if not PORT_TOKEN_RE.match(t)]
        if bad:
            raise ValueError(
                f"port_order 含非法 token {bad}；"
                r"必须匹配 ^(input|output_\d+)$（例如 input / output_1 / output_2）",
            )

        n_input = ports.count("input")
        if n_input != 1:
            raise ValueError(f"port_order 必须恰好包含一个 'input'，实际 {n_input} 个: {ports}")

        indices = [int(m.group(1)) for m in (_OUTPUT_INDEX_RE.match(t) for t in ports) if m]
        for a, b in itertools.pairwise(indices):
            if b <= a:
                raise ValueError(
                    f"port_order 的 output_N 序号必须严格递增，实际顺序: {ports}"
                )
        return self

    def validate_touchstone_ports(self, actual_ports: int) -> None:
        """校验 Touchstone 文件端口数与契约一致。"""
        expected = len(self.touchstone.port_order)
        if actual_ports != expected:
            from rfauto.core.errors import ContractViolationError
            raise ContractViolationError(
                f"Touchstone 端口数不匹配：契约 {expected} 端口 {self.touchstone.port_order}，"
                f"实际文件 {actual_ports} 端口",
                details={"expected": expected, "actual": actual_ports, "port_order": self.touchstone.port_order},
            )

    def validate_impedance(self, actual_z0: float) -> None:
        """校验参考阻抗（标量形式，兼容旧调用）。"""
        self.validate_port_impedances([actual_z0])

    def validate_port_impedances(self, actual_z: list) -> None:
        """逐端校验参考阻抗（多端口）。

        ADS .ds 回读的 PortZ[i] 是复数，理想情况下虚部为 0；此处只校验实部，
        容差 0.01 Ω 与标量版本一致。
        """
        expected = self.touchstone.renormalization_ohm
        bad = []
        for i, z in enumerate(actual_z):
            r = float(z.real) if isinstance(z, complex) else float(z)
            if abs(r - expected) > 0.01:
                bad.append((i + 1, r))
        if bad:
            from rfauto.core.errors import ContractViolationError
            raise ContractViolationError(
                f"参考阻抗不匹配：契约 {expected} Ω，实际 {bad}（端口号, 实测值）",
                details={"expected": expected, "actual": bad},
            )

    def check_against_ads_output(
        self, n_ports: int, port_names: list, port_z: list,
    ) -> None:
        """ADS 侧导入校验：.ds 回读的端口数 / 端口名 / 端口阻抗与契约对拍。

        这是 P3 验收项 2 的 ADS 侧落点：端口顺序/数量出错时显式 ContractViolationError，
        而不是让错误的系统指标进入优化循环。
        """
        self.validate_touchstone_ports(n_ports)
        self.validate_port_impedances(port_z)
        expected_names = [f"P{i}" for i in range(1, n_ports + 1)]
        if list(port_names) != expected_names:
            from rfauto.core.errors import ContractViolationError
            raise ContractViolationError(
                f"ADS 端口名与契约顺序不符：期望 {expected_names}，实际 {list(port_names)}",
                details={"expected": expected_names, "actual": list(port_names)},
            )
