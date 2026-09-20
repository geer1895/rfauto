"""ADS circuit recipe model and utilities.

AdsCircuitRecipe 是 ADS 侧系统指标 / 拓扑 / 元件的抽象——
没有这个抽象, ADS 侧要么拓扑写死背叛 G1, 要么临时发明第二套插件机制。

职责:
- 定义 ADS 电路拓扑（netlist_template 版本化）+ 可调元件 + 系统指标清单;
- render_netlist: 委托 B 档 ads_netlist.generate_netlist（SnP 语法, ADR-0009）;
- parse_results: 委托 ads_netlist.parse_dataset（ADS python 子进程读 .ds）,
  再把 S 参数网络折算成系统指标（skrf）。

系统指标命名（与契约 dataset_export 对齐）:
- system_gain_db      : 20*log10(|S21|) 带内均值 (dB)
- input_vswr          : 端口1 驻波 (1+|S11|)/(1-|S11|) 带内均值
- amplitude_balance_db: |S21_db - S31_db| 带内均值 (两输出幅度差, dB)
- output_phase_balance: phase(S21)-phase(S31) 带内均值 (deg)
- S11_db / S21_db / S31_db / S22_db / S23_db / S32_db: 对应 S 参数 dB 带内均值
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from rfauto.adapters import ads_netlist
from rfauto.core.contracts import AdsExchangeContract

logger = logging.getLogger(__name__)


class CircuitComponent(BaseModel):
    """ADS 电路中的一个元件。

    type 目前核心是 "SNP"（外部 Touchstone 数据源）; 其余元件(匹配网络/传输线)
    由对应 .net 模板内联定义, 此模型作为"可调元件"的声明抽象。
    """
    name: str
    type: str = "SNP"
    value: str | None = None
    tunable: bool = False


class AdsCircuitRecipe(BaseModel):
    """ADS 电路配方: 拓扑 + 可调元件 + 系统指标定义。

    - topology: 电路拓扑标识（对应模板与元件集合）;
    - components: 可调元件声明（供后续 ADR-0003 参数路由用）;
    - system_metrics: 需要从 ADS 仿真结果折算的系统指标清单;
    - netlist_template: 版本化 .net 模板路径（随 repo 入库）;
    - contract: ADS 交换契约（可选, 渲染时强制端口数一致）。
    """
    topology: str = "wilkinson_snp"
    components: list[CircuitComponent] = Field(default_factory=list)
    system_metrics: list[str] = Field(
        default_factory=lambda: ["system_gain_db", "input_vswr", "amplitude_balance_db"]
    )
    netlist_template: str | None = None
    contract: AdsExchangeContract | None = None


def render_netlist(
    recipe: AdsCircuitRecipe,
    s_params_path: str | Path,
    output_path: str | Path,
    contract: AdsExchangeContract | None = None,
) -> Path:
    """渲染完整 ADS 网表并写盘（委托 B 档 generate_netlist）。

    template 取 recipe.netlist_template; 若未指定, 退回拓扑默认模板路径。
    """
    contract = contract or recipe.contract
    tpl = recipe.netlist_template or _default_template(recipe.topology)
    return ads_netlist.generate_netlist(
        template_path=tpl,
        s_params_path=s_params_path,
        output_path=output_path,
        contract=contract,
    )


_TPL_DIR = Path(__file__).resolve().parent / "templates" / "ads"

def _default_template(topology: str) -> str:
    """拓扑 -> 默认 .net 模板路径（本模块同级 templates/ads）。"""
    known = {
        "wilkinson_snp": _TPL_DIR / "wilkinson_snp.net",
    }
    if topology in known:
        return str(known[topology])
    raise ValueError(f"未知拓扑 {topology!r}, 无默认模板; 请在 recipe.netlist_template 指定")


def parse_results(
    dataset_path: str | Path,
    ads_dir: str | Path | None = None,
    system_metrics: list[str] | None = None,
    contract: AdsExchangeContract | None = None,
) -> dict[str, Any]:
    """解析 ADS 结果 .ds -> 系统指标 dict。

    返回: {"metrics": {metric: value}, "n_ports", "frequency_hz": [...]}
    同时做契约对拍（端口数/端口名/端口阻抗）。
    """
    payload = ads_netlist.parse_dataset(dataset_path, ads_dir=ads_dir)
    if contract is not None:
        contract.check_against_ads_output(
            n_ports=len(payload["port_names"]),
            port_names=payload["port_names"],
            port_z=[complex(re, im) for re, im in payload["port_z"]],
        )
    network = _payload_to_network(payload)
    metric_names = system_metrics or ["system_gain_db", "input_vswr", "amplitude_balance_db"]
    metrics = compute_system_metrics(network, metric_names)
    return {
        "metrics": metrics,
        "n_ports": len(payload["port_names"]),
        "frequency_hz": payload["frequency_hz"],
    }


def _payload_to_network(payload: dict[str, Any]):
    """把 parse_dataset 的 dict 组装成 skrf Network。"""
    import skrf
    freq = np.asarray(payload["frequency_hz"], dtype=float)
    n_ports = len(payload["port_names"])
    s = np.zeros((len(freq), n_ports, n_ports), dtype=complex)
    for key, vals in payload["s"].items():
        i, j = (int(x) for x in key.split("_"))
        s[:, i - 1, j - 1] = [complex(re, im) for re, im in vals]
    z0 = [complex(re, im).real for re, im in payload["port_z"]] or [50.0] * n_ports
    f = skrf.Frequency.from_f(freq, unit="Hz")
    return skrf.Network(frequency=f, s=s, z0=z0, name="ads")


def compute_system_metrics(
    network: Any,
    metric_names: list[str],
) -> dict[str, float]:
    """从 S 参数网络计算系统指标（带内均值）。

    端口约定: 1=输入, 2/3=输出（与契约 port_order=[input,output_1,output_2] 对应）。
    """
    s = np.asarray(network.s)  # (npts, n, n) 复数
    n_ports = s.shape[1]
    out: dict[str, float] = {}

    def db(v):
        return 20.0 * np.log10(np.abs(v) + 1e-30)

    def mean_db(i, j):
        return float(np.mean(db(s[:, i - 1, j - 1])))

    for name in metric_names:
        if name == "system_gain_db":
            out[name] = mean_db(2, 1)
        elif name == "input_vswr":
            s11 = np.abs(s[:, 0, 0])
            out[name] = float(np.mean((1 + s11) / (1 - s11 + 1e-30)))
        elif name == "amplitude_balance_db":
            if n_ports >= 3:
                out[name] = abs(mean_db(2, 1) - mean_db(3, 1))
            else:
                out[name] = float("nan")
        elif name == "output_phase_balance":
            if n_ports >= 3:
                d = np.angle(s[:, 1, 0]) - np.angle(s[:, 2, 0])
                out[name] = float(np.mean(np.degrees(d)))
            else:
                out[name] = float("nan")
        elif name in ("S11_db", "S21_db", "S31_db", "S22_db", "S23_db", "S32_db"):
            i, j = int(name[1]), int(name[2])
            out[name] = mean_db(i, j) if i <= n_ports and j <= n_ports else float("nan")
        else:
            raise ValueError(f"未知系统指标: {name!r}")
    return out

