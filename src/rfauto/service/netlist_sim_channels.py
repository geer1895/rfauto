"""网表 goldset 回放的模拟器通道工厂（AI-6/F-10 W3-D：CLI/MCP 注入面，service 侧确定性构造）。

:func:`rfauto.service.netlist_goldset_service.replay_netlist_goldset` 的
``simulator`` 参数是注入点（``SimulatorChannel = Callable[[str, str],
Mapping[str, float]]``）——service 本体零通道假设（测试一律 mock，#139）。
本模块提供 **qucsatorRF 真通道**的确定性构造，供 CLI/MCP 薄壳注入：

1. :func:`rfauto.adapters.qucsator_adapter.resolve_qucsator_exe` 四源回退
   （显式参数 → env → solvers.yaml → 工作区/盘符/PATH）——**全部落空抛
   FileNotFoundError = fail-closed**（CLI/MCP 显式报缺，不静默降级）；
2. 临时目录写 .net（``analysis`` 说明以 qucs ``#`` 注释行附尾做 provenance
   ——qucs 网表的分析指令（.SP/.AC）由网表文本自身携带，通道不改写语义）；
3. ``qucsator_rf -i <net> -o <dat>`` 单次子进程（timeout 硬保护）；
4. :func:`rfauto.adapters.qucsator_adapter.read_qucs_dataset` 解析 dataset
   → :func:`dataset_metrics` 按下表文档化约定映射成 ``{metric: float}``。

**指标约定（v1，显式命名，同 #195 指标名方向后缀家法；全部由 dataset
拓扑确定性导出，零物理语义发明）**：

- ``n_freq``：频点数；
- ``freq_min_hz`` / ``freq_max_hz``：频轴端点（dataset 为空时缺键）；
- ``s<i>{j}_mag_min`` / ``s<i>{j}_mag_max``：S(i,j) 线性幅度极值；
- ``s<i>{j}_db_min`` / ``s<i>{j}_db_max``：dB 幅度极值（20·log10；幅度
  下探地板 ``_MAG_FLOOR`` 防 -inf 破坏 JSON 语义，同 service 容差判读的
  ``max(abs(value), 1e-300)`` 惯语）。

goldset 的 ``expected`` 指标名按本约定书写（如 ``s21_db_max``）；通道未
产出的指标由 replay 链如实判 FAIL（"通道未产出该指标"，不伪造）。
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rfauto.adapters.qucsator_adapter import (
    QucsatorError,
    read_qucs_dataset,
    resolve_qucsator_exe,
)
from rfauto.service.netlist_goldset_service import SimulatorChannel

__all__ = [
    "build_qucsator_channel",
    "build_simulator_channel",
    "dataset_metrics",
]

#: dB 换算幅度地板（防 log10(0) = -inf 破坏 JSON 语义；与容差判读同款惯语）
_MAG_FLOOR = 1e-300

#: qucsator 子进程硬超时（秒；网表级电路求解秒级量级，120s 为宽裕保护）
_SUBPROCESS_TIMEOUT_S = 120.0


def dataset_metrics(dataset: dict[str, Any]) -> dict[str, float]:
    """dataset（read_qucs_dataset 形态）→ 文档化指标约定映射（纯函数）。

    read_qucs_dataset 的 ``freq_hz``/``S`` 值是 **numpy 数组**（parse_qucs_dataset
    落盘形态）——缺省判断一律 ``is not None``（#117/#367 falsy 惯语对
    ndarray 触发 ambiguous truth value，真机冒烟实证），不写 ``or []``。
    """
    raw_freq = dataset.get("freq_hz")
    freqs = [float(f) for f in (raw_freq if raw_freq is not None else [])]
    out: dict[str, float] = {"n_freq": float(len(freqs))}
    if freqs:
        out["freq_min_hz"] = min(freqs)
        out["freq_max_hz"] = max(freqs)
    s_by_pair = dataset.get("S")
    if not isinstance(s_by_pair, dict):
        s_by_pair = {}
    for (i, j), vals in sorted(s_by_pair.items()):
        mags = [abs(complex(v)) for v in vals]
        if not mags:
            continue
        mag_min, mag_max = min(mags), max(mags)
        out[f"s{i}{j}_mag_min"] = mag_min
        out[f"s{i}{j}_mag_max"] = mag_max
        out[f"s{i}{j}_db_min"] = 20.0 * math.log10(max(mag_min, _MAG_FLOOR))
        out[f"s{i}{j}_db_max"] = 20.0 * math.log10(max(mag_max, _MAG_FLOOR))
    return out


def build_qucsator_channel(exe_path: str | Path | None = None, *,
                           timeout_s: float = _SUBPROCESS_TIMEOUT_S
                           ) -> SimulatorChannel:
    """构造 qucsatorRF 真通道（fail-closed：可执行缺席抛 FileNotFoundError）。

    Returns:
        Callable[[netlist_text, analysis], {metric: float}]（指标约定见模
        块 docstring）；子进程非零退出/无 dataset 抛 :class:`QucsatorError`
        ——replay 链将该任务如实判 ERROR（数据坏≠模型类不覆盖，分列）。
    """
    exe = resolve_qucsator_exe(exe_path)

    def channel(netlist_text: str, analysis: str) -> dict[str, float]:
        text = str(netlist_text)
        note = str(analysis or "").strip()
        if note:
            text = text.rstrip("\n") + f"\n# analysis: {note}\n"
        with tempfile.TemporaryDirectory(prefix="rfauto_netlist_goldset_") as td:
            net = Path(td) / "case.net"
            net.write_text(text, encoding="utf-8")
            dat = Path(td) / "case.dat"
            proc = subprocess.run(
                [str(exe), "-i", str(net), "-o", str(dat)],
                capture_output=True, text=True, timeout=float(timeout_s),
                check=False,
            )
            if proc.returncode != 0:
                raise QucsatorError(
                    f"qucsator 退出码 {proc.returncode}: "
                    f"{(proc.stderr or proc.stdout or '')[-500:]}")
            if not dat.is_file():
                raise QucsatorError(
                    "qucsator 未产出 dataset（分析指令缺失或网表非法）")
            dataset = read_qucs_dataset(dat)
        return dataset_metrics(dataset)

    return channel


def build_simulator_channel(engine: str, exe_path: str | Path | None = None
                            ) -> SimulatorChannel:
    """按 engine 名分派通道构造（v1 仅 ``qucsator``；未知名显式 ValueError）。"""
    if engine == "qucsator":
        return build_qucsator_channel(exe_path)
    raise ValueError(f"未知模拟器通道 engine={engine!r}（v1 可选：qucsator）")
