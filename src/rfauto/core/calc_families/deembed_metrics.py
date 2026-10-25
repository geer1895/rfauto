"""THRU 去嵌+Z12 串联指标 CALC 注册面（aurora_k K8，2026-10-23，反馈 F6/P14）。

两键：
- ``z12_series_extract``——串联 2 端口（.s2p 语料）/并联 1 端口（.s1p 语料）
  的 C/R/Q 指标：**Z12 传输阻抗主口径**（R=Re(Z12)、X=Im(Z12)、
  C=−1/(ω·Im(Z12))、Q=|X|/R）+ **−1/Y21=ABCD B 副口径**（π 型端并联寄生
  免疫——THRU 去嵌后对 π 型 DUT 的 C/R 逐位回收）+ **简化式 2Z0(1/S21−1)
  强失配拒绝**（|S11|>阈值时 rejected=True+建议文案；反馈 P14 实测：
  |S11|≈0.95 强失配下把 R=1.4Ω 误算成 50Ω 量级——简化式仅对纯串联件
  +匹配系统精确，并联寄生+强失配组合放大误差）+ shunt 拓扑 Y11 的
  L/C/Q/SRF（Im(Y)/Re(Y) 口径）；
- ``deembed_thru_metrics``——THRU 去嵌+提取一站式：2x-thru 对称半拆
  （级联平方根闭式）双边去嵌（参考面从引线外端移回 pad 边缘，反馈 F6
  验收：IDC 波端口未去嵌 C=427.8fF（含 ~250fF 引线并联电容）→去嵌后
  回到集总值量级）后按同款指标面提取。

**薄注册纪律**（conductor_reg/polarization_reg 同款）：物理数学单源在
``rfauto.core.deembed``（deembed_thru/thru_half_network/z12_series_metrics，
2026-09-13 §10.20 ② 去嵌标准化模块的 K8 扩展面）——本模块只做
数组参数（JSON 可序列化）→ skrf.Network 的装配与结果 round 展示，
零公式复制（#116 死副本教训）。复数数组形态=逐频 [re, im] 对列表
（iss_oneport_cal_extract gamma 同款惯例）。

#222 triple-grep 证据（2026-10-23 本席开工实测）
--------------------------------------------------------
- ``z12_series_extract``/``deembed_thru_metrics`` src/tests/scripts 三面
  零命中（新键面）；
- Z12 传输阻抗提取：src 面零命中（transfer_impedance=电缆屏蔽 Zt 另一
  物理量；coupled_mode_z=耦合模阻抗；均不撞）；
- THRU 半拆/deembed：core/deembed.py 既有面=端口平移（单边全长）/
  OpenShort/探针尺度——**对称半拆（half）面零实现**，本批补口；
  measurement/afr_2xthru=IEEEP370 NZC 时域面（测量链预检+DC 外推语料），
  本族=频域精确代数（合成语料回收 1e-15），互补不并入；
- iss_on_wafer.py docstring 预声明"deembed=泛用 2 端口夹具去嵌不并入"
  指向 core/deembed 泛用件——本族注册键消费的就是该单源（同仓双源消费
  先例）。

与既有面边界
--------------------------------------------------------
- core/deembed.py 既有去嵌键消费面零（纯函数模块无注册键；本批为其
  K8 扩展函数补注册出口，公式单源零复制）；
- iss_standard_response thru 件=标准件**响应闭式**（定义→S）；本族=
  实测 S 的**去嵌应用+指标提取**（测量后半段）；
- 调用方拿裸网络判读走 core 函数（skrf.Network 面），本键=JSON 参数
  面（服务层/CLI/MCP 消费）。

数值锚（#118/#340 家法，tests/unit/test_k8_deembed_metrics.py）：
合成已知夹具（π 型 250fF 并联+2mm 有耗线）+已知 DUT（R=1.4Ω+C=173.5fF
+70fF pad）级联→去嵌→网络逐位回收（≤1e-9）+y21 口径 C/R 逐位回收
（≤1e-9）；强失配场景（|S11|≈0.96）简化式 R 误算（>2×）+rejected=True；
用户数值锚=去嵌后回到 173.5fF±5%（y21 口径 173.5000fF）。

守卫：频率列表非空逐点 >0；S 数组与频率同长、逐 [re,im] 成对有限；
|S|≤1+1e-9（无源）；topology 白名单；series 缺 s21 显式拒绝；
deembed 键 dut/thru 频栅格同长（core 层再校验互易/对称/欠采样守卫）。

出处：物理公式与去嵌算法出处见 rfauto.core.deembed 模块 docstring
（K8 节：对称半拆闭式代数+二阶差分分支连续；Z12/Y21 口径=Z 参数
定义+P14 用户实测）；本模块为薄注册包装，公式零复制。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core.deembed import (
    deembed_thru,
    z12_series_metrics,
)

from .registry import register_calculator

__all__ = [
    "deembed_thru_metrics",
    "z12_series_extract",
]

_SOURCE = (
    "出处见 rfauto.core.deembed 模块 docstring aurora_k K8 节（对称半拆="
    "级联平方根闭式代数；Z12 传输阻抗/−1/Y21 双口径+简化式强失配拒绝="
    "Z 参数定义+反馈 P14 用户实测 R=1.4Ω 误算 50Ω 场景）；本模块为薄注"
    "册包装，公式零复制")


def _freq_array(freq_ghz: Any) -> np.ndarray:
    """频率列表守卫：非空、逐点有限 >0（GHz）。"""
    if not isinstance(freq_ghz, (list, tuple)) or len(freq_ghz) == 0:
        raise ValueError(
            f"deembed: freq_ghz 须为非空列表，收到 {type(freq_ghz).__name__}")
    out = []
    for i, v in enumerate(freq_ghz):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(
                f"deembed: freq_ghz[{i}] 须为数值，收到 {v!r}")
        f = float(v)
        if not np.isfinite(f) or f <= 0.0:
            raise ValueError(
                f"deembed: freq_ghz[{i}] 须有限 >0，收到 {v!r}")
        out.append(f)
    return np.asarray(out, dtype=float)


def _complex_pairs(values: Any, name: str, n: int) -> np.ndarray:
    """逐频 [re, im] 对列表 → 复数 ndarray（长度/成对/有限/无源守卫）。"""
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"deembed: {name} 须为 [re,im] 对列表，收到 {name!r}")
    if len(values) != n:
        raise ValueError(
            f"deembed: {name} 长度 {len(values)} 与 freq_ghz {n} 不一致")
    out = []
    for i, pair in enumerate(values):
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2):
            raise ValueError(
                f"deembed: {name}[{i}] 须为 [re,im] 二元组，收到 {pair!r}")
        re_v, im_v = float(pair[0]), float(pair[1])
        if not (np.isfinite(re_v) and np.isfinite(im_v)):
            raise ValueError(f"deembed: {name}[{i}] 含非有限值 {pair!r}")
        out.append(complex(re_v, im_v))
    return np.asarray(out, dtype=complex)


def _s_matrix(s11: np.ndarray, s21: np.ndarray | None,
              s12: np.ndarray | None, s22: np.ndarray | None,
              n: int) -> np.ndarray:
    """装配 (n,2,2) S 矩阵；s12/s22 缺省=互易/对称假设（assumed 标记
    由调用方随结果透传）。无源性 |S|≤1+1e-9 守卫。"""
    if s21 is None:
        raise ValueError("deembed: series 拓扑必给 s21（传输项）")
    s12_use = s12 if s12 is not None else s21
    s22_use = s22 if s22 is not None else s11
    mat = np.zeros((n, 2, 2), dtype=complex)
    mat[:, 0, 0] = s11
    mat[:, 1, 0] = s21
    mat[:, 0, 1] = s12_use
    mat[:, 1, 1] = s22_use
    if float(np.max(np.abs(mat))) > 1.0 + 1e-9:
        raise ValueError(
            f"deembed: |S|>1（max={float(np.max(np.abs(mat))):.6f}）——"
            "无源性违例，非实测 2 端口数据")
    return mat


def _round_metrics(tree: Any) -> Any:
    """递归 round：float→12 位、None/str/list/dict 原样透传。"""
    if tree is None or isinstance(tree, (str, bool, int)):
        return tree
    if isinstance(tree, float):
        return round(tree, 12)
    if isinstance(tree, (list, tuple)):
        return [_round_metrics(v) for v in tree]
    if isinstance(tree, dict):
        return {k: _round_metrics(v) for k, v in tree.items()}
    return tree


@register_calculator(
    "z12_series_extract",
    "串联/并联器件Z12指标提取：串联 2 端口 C/R/Q（强失配下简化式 "
    "2Z0(1/S21−1) 把 R=1.4Ω 误算 50Ω——|S11|>阈值显式拒绝）R=Re(Z12)、"
    "C=−1/(ω·Im(Z12))、Q=|X|/R；副方法 −1/Y21（π 端并联寄生免疫，去嵌"
    "后逐位回收）；shunt 拓扑=1 端口 Y11 的 L/C/Q=|Im(Y)/Re(Y)|/SRF。锚："
    "合成 173.5fF+R=1.4Ω 逐位回收",
    (("freq_ghz", "array 频率列表 GHz（有限 >0，与 S 数组同长）"),
     ("s11", "array S11 逐频 [re,im] 对列表（shunt 拓扑=1 端口唯一输入）"),
     ("s21", "array S21 逐频 [re,im] 对列表（series 必给）"),
     ("s12", "array S12 逐频 [re,im] 对（缺省=互易假设 s12=s21）"),
     ("s22", "array S22 逐频 [re,im] 对（缺省=对称假设 s22=s11）"),
     ("topology", "str 'series'（2 端口串联，缺省）|'shunt'（1 端口并联）"),
     ("f_eval_ghz", "float 评估频率 GHz（带内；缺省=带内几何中心栅格点）"),
     ("z0_ohm", "float 系统阻抗 Ω（>0，缺省 50）"),
     ("simplified_reject_threshold", "float 简化式拒绝 |S11| 阈值"
      "（缺省 0.9；强失配实测场景）")),
    required=("freq_ghz", "s11"),
)
def z12_series_extract(
    freq_ghz: list,
    s11: list,
    s21: list | None = None,
    s12: list | None = None,
    s22: list | None = None,
    topology: str = "series",
    f_eval_ghz: float | None = None,
    z0_ohm: float = 50.0,
    simplified_reject_threshold: float = 0.9,
) -> dict[str, Any]:
    import skrf

    if topology not in ("series", "shunt"):
        raise ValueError(
            f"z12_series_extract: topology 须 ∈('series','shunt')，"
            f"得到 {topology!r}")
    z0 = float(z0_ohm)
    if not np.isfinite(z0) or z0 <= 0:
        raise ValueError(f"z12_series_extract: z0_ohm 须 >0，得到 {z0_ohm!r}")
    freq = _freq_array(freq_ghz)
    n = int(freq.size)
    if topology == "series":
        mat = _s_matrix(
            _complex_pairs(s11, "s11", n),
            None if s21 is None else _complex_pairs(s21, "s21", n),
            None if s12 is None else _complex_pairs(s12, "s12", n),
            None if s22 is None else _complex_pairs(s22, "s22", n), n)
        net = skrf.Network(
            frequency=skrf.Frequency.from_f(freq * 1e9, unit="hz"),
            s=mat, z0=z0)
    else:
        if s21 is not None:
            raise ValueError(
                "z12_series_extract: shunt 拓扑只收 s11（1 端口 .s1p 语料"
                "），给了 s21 请改 topology='series'")
        y1 = _complex_pairs(s11, "s11", n)
        net = skrf.Network(
            frequency=skrf.Frequency.from_f(freq * 1e9, unit="hz"),
            s=y1.reshape(n, 1, 1), z0=z0)
    result = z12_series_metrics(
        net,
        f_hz=None if f_eval_ghz is None else float(f_eval_ghz) * 1e9,
        topology=topology,
        simplified_reject_threshold=float(simplified_reject_threshold))
    out = _round_metrics(result)
    out["assumed"] = {
        "s12_reciprocal": s12 is None and topology == "series",
        "s22_symmetric": s22 is None and topology == "series",
    }
    out["z0_ohm"] = z0
    out["source"] = _SOURCE
    return out


@register_calculator(
    "deembed_thru_metrics",
    "THRU去嵌串联指标提取：参考面从引线外端移回 pad 边缘（IDC "
    "波端口未去嵌 C=427.8fF 含 ~250fF 引线并联电容，去嵌后回集总值）——"
    "2x-thru 对称半拆（级联平方根闭式+二阶差分分支连续）双边去嵌 dut=meas、"
    "thru=2x-thru（同栅格），half=True 对称半件/half=False 全长单边（side="
    "input）；去嵌后 Z12 主方法+−1/Y21 副方法 C/R/Q 提取。锚：合成夹具+DUT"
    "级联→去嵌→网络与 C/R 逐位回收 ≤1e-9",
    (("freq_ghz", "array 频率列表 GHz（dut/thru 同栅格，有限 >0）"),
     ("dut_s11", "array DUT 实测 S11 逐频 [re,im] 对"),
     ("dut_s21", "array DUT 实测 S21 逐频 [re,im] 对"),
     ("thru_s11", "array 2x-thru S11 逐频 [re,im] 对"),
     ("thru_s21", "array 2x-thru S21 逐频 [re,im] 对"),
     ("dut_s12", "array DUT S12 逐频 [re,im] 对（缺省=互易 s12=s21）"),
     ("dut_s22", "array DUT S22 逐频 [re,im] 对（缺省=对称 s22=s11）"),
     ("thru_s12", "array 2x-thru S12 逐频 [re,im] 对（缺省=互易）"),
     ("thru_s22", "array 2x-thru S22 逐频 [re,im] 对（缺省=对称——半拆"
      "守卫校验）"),
     ("half", "bool True=对称半拆双边（缺省，夹具镜像同件前提）/False="
      "全长单边"),
     ("side", "str half=False 时单边侧 'input'/'output'（缺省 output）"),
     ("f_eval_ghz", "float 评估频率 GHz（带内，缺省=带内几何中心）"),
     ("z0_ohm", "float 系统阻抗 Ω（>0，缺省 50）"),
     ("simplified_reject_threshold", "float 简化式拒绝 |S11| 阈值（缺省 0.9）")),
    required=("freq_ghz", "dut_s11", "dut_s21", "thru_s11", "thru_s21"),
)
def deembed_thru_metrics(
    freq_ghz: list,
    dut_s11: list,
    dut_s21: list,
    thru_s11: list,
    thru_s21: list,
    dut_s12: list | None = None,
    dut_s22: list | None = None,
    thru_s12: list | None = None,
    thru_s22: list | None = None,
    half: bool = True,
    side: str = "output",
    f_eval_ghz: float | None = None,
    z0_ohm: float = 50.0,
    simplified_reject_threshold: float = 0.9,
) -> dict[str, Any]:
    import skrf

    z0 = float(z0_ohm)
    if not np.isfinite(z0) or z0 <= 0:
        raise ValueError(f"deembed_thru_metrics: z0_ohm 须 >0，得到 {z0_ohm!r}")
    freq = _freq_array(freq_ghz)
    n = int(freq.size)
    skrf_freq = skrf.Frequency.from_f(freq * 1e9, unit="hz")
    dut = skrf.Network(
        frequency=skrf_freq,
        s=_s_matrix(
            _complex_pairs(dut_s11, "dut_s11", n),
            _complex_pairs(dut_s21, "dut_s21", n),
            None if dut_s12 is None else _complex_pairs(dut_s12, "dut_s12", n),
            None if dut_s22 is None else _complex_pairs(dut_s22, "dut_s22", n),
            n), z0=z0)
    thru = skrf.Network(
        frequency=skrf_freq,
        s=_s_matrix(
            _complex_pairs(thru_s11, "thru_s11", n),
            _complex_pairs(thru_s21, "thru_s21", n),
            None if thru_s12 is None else _complex_pairs(thru_s12, "thru_s12", n),
            None if thru_s22 is None else _complex_pairs(thru_s22, "thru_s22", n),
            n), z0=z0)
    deembedded = deembed_thru(dut, thru, half=bool(half), side=str(side))
    result = z12_series_metrics(
        deembedded,
        f_hz=None if f_eval_ghz is None else float(f_eval_ghz) * 1e9,
        topology="series",
        simplified_reject_threshold=float(simplified_reject_threshold),
        deembedded=True,
        reference_plane=(
            "thru-deembedded(half-split)" if half
            else f"thru-deembedded(full,{side})"))
    out = _round_metrics(result)
    out["deembed"] = {
        "mode": "half-split" if half else f"full-{side}",
        "n_points": n,
    }
    out["assumed"] = {
        "dut_s12_reciprocal": dut_s12 is None,
        "dut_s22_symmetric": dut_s22 is None,
        "thru_s12_reciprocal": thru_s12 is None,
        "thru_s22_symmetric": thru_s22 is None,
    }
    out["z0_ohm"] = z0
    out["source"] = _SOURCE
    return out
