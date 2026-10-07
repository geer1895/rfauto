"""SV-3：Palace Floquet/周期结构配置接线（v0.18.1 官方 schema 实录面）。

规格（round14 §六 SV-3）："Palace Floquet/2D 能力接线——v0.17 Floquet=
免 license 周期结构第二裁判（HFSS Floquet 锚互补）+2D 档提速。验收：
ms_patch 单胞 Γ vs HFSS Floquet FSV≥VG."

**架构位置**（任务书禁改"既有 adapter（除注册表追加）"）：本模块不修改
``palace_solver.py``——PalaceSolver.build_geometry 的 ``boundaries``
子键为官方透传通道（见其 docstring），本模块产出**可直接并入该通道的
官方 schema 配置段**（Boundaries.Periodic / Boundaries.FloquetPort）与
完整五分节配置 dict；既有求解路径零改动。

** grounding（2026-10-03 实录）**：官方 config-schema.json（GitHub
awslabs/palace tag ``v0.18.1``，``scripts/schema/config-schema.json``）
逐键摘录：
- ``Boundaries.Periodic``（object）＝
  ``BoundaryPairs``（必填，数组；每项 ``DonorAttributes`` +
  ``ReceiverAttributes``，可选 ``Translation``（3 向量）**或**
  ``AffineTransformation``（16 元 4×4 行主序）——二者互斥）＋
  ``FloquetWaveVector``（3 元数组，缺省 [0,0,0]，**单位=每网格长度
  单位的弧度**）＋ ``FloquetReferenceFrequency``（GHz，缺省 0.0）；
- ``Boundaries.FloquetPort``（数组）＝ ``Index``(>0)/``Attributes``/
  ``Excitation``(bool 或 ``ExcitationIndex``≥0)/
  ``IncidentPolarization``(TE|TM|RHC|LHC，缺省 TE)/``MaxOrder``(≥0，
  衍射阶)；官方注记 FloquetPort 需要 **两个横向 BoundaryPairs** 的
  Periodic 边界——本模块校验器按此给出 warning 级一致性检查；
- 官方 schema **无** "Lattice"/独立 2D 配置节（2D 仅以 BoundaryMode
  问题类型存在）——2D 档不在本模块虚设接口。

真机验收（ms_patch 单胞 vs HFSS Floquet FSV）走 env 显式意图门
（Palace WSL 通道真跑，超 unit 门）；本模块全部面=配置数学（离线可测）。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

POLARIZATIONS: tuple[str, ...] = ("TE", "TM", "RHC", "LHC")

#: FloquetPort 官方要求：两个横向 BoundaryPairs（transverse pairs）
FLOQUET_PORT_MIN_PAIRS = 2


def build_boundary_pair(
    donor_attributes: Sequence[int],
    receiver_attributes: Sequence[int],
    *,
    translation: Sequence[float] | None = None,
    affine: Sequence[float] | None = None,
) -> dict[str, Any]:
    """单个 BoundaryPair（Donor/Receiver 属性组 + Translation|Affine 二选一）。"""
    d = _attr_list(donor_attributes, "donor_attributes")
    r = _attr_list(receiver_attributes, "receiver_attributes")
    if not d or not r:
        raise ValueError("Donor/Receiver 属性组均不得为空")
    if set(d) & set(r):
        logger.warning("Donor 与 Receiver 属性组相交 %s——周期对通常应互斥",
                       sorted(set(d) & set(r)))
    out: dict[str, Any] = {
        "DonorAttributes": d,
        "ReceiverAttributes": r,
    }
    if translation is not None and affine is not None:
        raise ValueError("Translation 与 AffineTransformation 互斥"
                         "（官方 BoundaryPair schema）")
    if translation is not None:
        out["Translation"] = _vec3(translation, "translation")
    elif affine is not None:
        arr = [float(v) for v in affine]
        if len(arr) != 16:
            raise ValueError(
                f"AffineTransformation 须为 16 元 4×4 行主序，实得 {len(arr)} 元")
        out["AffineTransformation"] = arr
    return out


def build_periodic_section(
    boundary_pairs: Sequence[dict[str, Any]],
    *,
    wave_vector: Sequence[float] = (0.0, 0.0, 0.0),
    reference_frequency_ghz: float = 0.0,
) -> dict[str, Any]:
    """官方 ``Boundaries.Periodic`` 段（FloquetBloch 相位 + 周期对）。"""
    if not boundary_pairs:
        raise ValueError("BoundaryPairs 不得为空（周期段至少 1 对）")
    pairs = [dict(p) for p in boundary_pairs]
    for p in pairs:
        if "DonorAttributes" not in p or "ReceiverAttributes" not in p:
            raise ValueError(
                f"BoundaryPair 缺 Donor/ReceiverAttributes: {sorted(p)}")
    ref = float(reference_frequency_ghz)
    if not math.isfinite(ref) or ref < 0.0:
        raise ValueError(
            f"FloquetReferenceFrequency 须 ≥0（GHz），实得 {ref}")
    return {
        "BoundaryPairs": pairs,
        "FloquetWaveVector": _vec3(wave_vector, "wave_vector"),
        "FloquetReferenceFrequency": ref,
    }


def build_floquet_port(
    index: int,
    attributes: Sequence[int],
    *,
    polarization: str = "TE",
    max_order: int = 0,
    excitation: bool = False,
    excitation_index: int | None = None,
) -> dict[str, Any]:
    """官方 ``Boundaries.FloquetPort`` 数组元素（口径入射端口）。"""
    i = int(index)
    if i < 1:
        raise ValueError(f"FloquetPort.Index 必须 >0，实得 {index}")
    pol = str(polarization).upper()
    if pol not in POLARIZATIONS:
        raise ValueError(
            f"IncidentPolarization 须为 {'|'.join(POLARIZATIONS)}，"
            f"实得 {polarization!r}")
    order = int(max_order)
    if order < 0:
        raise ValueError(f"MaxOrder 必须 ≥0（衍射阶），实得 {max_order}")
    out: dict[str, Any] = {
        "Index": i,
        "Attributes": _attr_list(attributes, "attributes"),
        "IncidentPolarization": pol,
        "MaxOrder": order,
    }
    if not out["Attributes"]:
        raise ValueError("FloquetPort.Attributes 不得为空")
    if excitation_index is not None:
        ei = int(excitation_index)
        if ei < 0:
            raise ValueError(
                f"ExcitationIndex 必须 ≥0，实得 {excitation_index}")
        out["ExcitationIndex"] = ei
    elif excitation:
        out["Excitation"] = True
    return out


def check_floquet_consistency(
    periodic: dict[str, Any],
    floquet_ports: Sequence[dict[str, Any]],
) -> list[str]:
    """官方一致性检查（非致命项 warning，致命项 raise 前先返回清单）。

    规则（官方 schema 注记）：FloquetPort 需要 **两个横向 BoundaryPairs**
    的 Periodic 边界——本函数按"pairs ≥2"给校验意见；端口 Index 重复
    属致命项（返回清单非空表示存在需人工处理项）。
    """
    issues: list[str] = []
    n_pairs = len(periodic.get("BoundaryPairs") or [])
    if floquet_ports and n_pairs < FLOQUET_PORT_MIN_PAIRS:
        issues.append(
            f"官方注记 FloquetPort 需要两个横向 BoundaryPairs，实得 {n_pairs} 对")
    indices = [int(p.get("Index", 0)) for p in floquet_ports]
    dup = {i for i in indices if indices.count(i) > 1}
    if dup:
        issues.append(f"FloquetPort.Index 重复: {sorted(dup)}（致命——官方 "
                      "Index 为端口唯一标识）")
    return issues


def assemble_floquet_config(
    *,
    mesh_file: str,
    l0_m: float,
    materials: list[dict[str, Any]],
    boundary_pairs: Sequence[dict[str, Any]],
    wave_vector: Sequence[float] = (0.0, 0.0, 0.0),
    reference_frequency_ghz: float = 0.0,
    floquet_ports: Sequence[dict[str, Any]] | None = None,
    freq_range_ghz: tuple[float, float, int] = (1.0, 10.0, 101),
    solver_order: int = 2,
) -> dict[str, Any]:
    """装配完整五分节 Palace 配置（Problem/Model/Domains/Boundaries/Solver）。

    产物可直接写盘 ``palace_config.json``；其 Boundaries.Periodic 子键
    亦可通过既有 PalaceSolver.build_geometry 的 ``boundaries`` 透传通道
    并入（不修改既有 adapter）。Driven 问题 + 官方五分节结构（同
    palace_solver 生成器口径）。
    """
    if not mesh_file:
        raise ValueError("mesh_file 必填（官方 Model.Mesh）")
    l0 = float(l0_m)
    if not math.isfinite(l0) or l0 <= 0.0:
        raise ValueError(f"Model.L0 须 >0（相对米），实得 {l0_m}")
    if not materials:
        raise ValueError("materials 必填（官方 Domains.Materials，逐项须含 "
                         "Attributes 域标签绑定）")
    for m in materials:
        if not isinstance(m, dict) or "Attributes" not in m:
            raise ValueError(
                f"材料缺 Attributes 域标签绑定（官方口径）: {m!r}")
    f0, f1, n = (float(freq_range_ghz[0]), float(freq_range_ghz[1]),
                 int(freq_range_ghz[2]))
    if n < 2 or not 0.0 < f0 < f1:
        raise ValueError(f"扫频栅格非法: {freq_range_ghz!r}")
    order = int(solver_order)
    if order < 1:
        raise ValueError(f"Solver.Order 必须 ≥1，实得 {solver_order}")

    periodic = build_periodic_section(
        boundary_pairs, wave_vector=wave_vector,
        reference_frequency_ghz=reference_frequency_ghz)
    ports = [dict(p) for p in (floquet_ports or [])]
    issues = check_floquet_consistency(periodic, ports)
    for issue in issues:
        if "Index 重复" in issue:
            raise ValueError(issue)
        logger.warning("Floquet 一致性: %s", issue)
    boundaries: dict[str, Any] = {"Periodic": periodic}
    if ports:
        boundaries["FloquetPort"] = ports
    return {
        "Problem": {"Type": "Driven", "Output": "postpro"},
        "Model": {"Mesh": str(mesh_file), "L0": l0},
        "Domains": {"Materials": [dict(m) for m in materials]},
        "Boundaries": boundaries,
        "Solver": {
            "Order": order,
            # 官方推荐扫频接口 Solver.Driven.Samples（v0.18.1 实录，同
            # palace_solver.py 生成器口径；顶层 MinFreq/MaxFreq 已废弃）
            "Driven": {"Samples": [{
                "Type": "Linear",
                "MinFreq": f0,
                "MaxFreq": f1,
                "NSample": n,
            }]},
        },
    }


def wavevector_axis(
    axis: int, k_max: float, n: int,
) -> list[tuple[float, float, float]]:
    """Γ→k_max 单轴扫 k 轨迹（Γ 点含首尾；带图/Γ-X 扫描常用面）。"""
    if axis not in (0, 1, 2):
        raise ValueError(f"axis 须为 0|1|2，实得 {axis}")
    if n < 2:
        raise ValueError(f"n 必须 ≥2（含 Γ 与端点），实得 {n}")
    if not math.isfinite(float(k_max)) or float(k_max) <= 0.0:
        raise ValueError(f"k_max 必须 >0 有限，实得 {k_max}")
    return [
        tuple(
            float(k_max) * i / (n - 1) if a == axis else 0.0
            for a in range(3))
        for i in range(n)
    ]


def _attr_list(values: Sequence[int], name: str) -> list[int]:
    out = [int(v) for v in values]
    if any(v < 1 for v in out):
        raise ValueError(f"{name} 须为正整数网格属性标签，实得 {values!r}")
    return out


def _vec3(values: Sequence[float], name: str) -> list[float]:
    arr = [float(v) for v in values]
    if len(arr) != 3 or not all(math.isfinite(v) for v in arr):
        raise ValueError(f"{name} 须为 3 元有限向量，实得 {values!r}")
    return arr
