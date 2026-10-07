"""HFSS Driven Modal 双导体（耦合线对）端口模阻抗基准换算（#307 单源）。

背景（#307，2026-09-18 rm-hfss-anchor 实证； 踩坑速查 HFSS hairpin
锚点六坑①族）：HFSS Driven Modal 双导体端口的**模阻抗输出基准**是
共模 Zc = Z0e/2、差模 Zd = 2·Z0o（终端分组随模而变：偶模等电位端子合并
→ Zvi=Z0e/2、奇模分立 → Zvi=Z0o；Zvi=√(Zpi·Zpv) 恒等式可实测自校，
#356⑤），**不是单线偶/奇模阻抗**——50Ω 归一 S 反演得到的也是共模/差模
阻抗。换算链：

    Z0e = 2·Zc        Z0o = Zd/2

模序识别必须**按 εeff 较高识别偶模**——按 Z0 大小识别在该基准下反转
（本基准下共模读数 < 差模读数，如 hairpin g0.5 实测 Zc≈29.3 < Zd≈96.7），
#307 首判即此翻车（DISAGREE −22%/+29%），Modal Solution Data Zo 独立确认。

出处链（回归钉证据，runs 归档零改写只读）：
- 换算式与识别规则：战役任务书 §路线 C（"换算 Z0e=2·Zc、
  Z0o=Zd/2；模序按 εeff 较高识别偶模"）；
- 数值证据：runs/hairpin_hfss_anchor/hairpin_anchor.json
  verdict.points.<gap>.line_default_zpi（per_port 每模 Zo 读数 + 换算后
  z0e_ohm/z0o_ohm）与 runs/hairpin_hfss_anchor/criteria.md §表
  （g0500: Z0e_HFSS=58.29/Z0o_HFSS=48.02；g2200: 54.31/52.70）；
- 审查条目：runs/review_ge8e/r4_adapters/REPORT.md R4-4（换算链此前只在
  runs 任务书 文档与战役脚本中，无 core/service 可复用实现）。

多端口读数口径：同一模在两端口的读数先跨端口取算术均值再换算
（hairpin anchor 管线实测口径：g0.5 的 z0e_ohm=58.29372163361394
=2·mean(29.29097559664919, 29.002746036964748)，逐位回收，见回归钉）。
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass

#: 模阻抗基准换算系数（#307）：Z0e=2·Zc、Z0o=Zd/2
EVEN_FACTOR = 2.0
ODD_FACTOR = 0.5


@dataclass(frozen=True)
class DualConductorModeImpedances:
    """换算结果（含回读量与识别依据，schema 自描述）。"""

    z0e_ohm: float
    z0o_ohm: float
    #: 识别出的偶/奇模键（调用方 per_mode 映射的键）
    even_mode_key: Hashable
    odd_mode_key: Hashable
    #: 回读量：共模/差模读数（跨端口均值）
    common_mode_zo_ohm: float   # Zc = Z0e/2 基准读数
    diff_mode_zo_ohm: float     # Zd = 2·Z0o 基准读数
    #: 识别依据（εeff 较高者=偶模，#307）
    eps_eff_even: float
    eps_eff_odd: float
    k_z: float  # (Z0e−Z0o)/(Z0e+Z0o)，与 KJ 闭式同口径（便利量）


def _mean(v: float | Sequence[float]) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    vals = [float(x) for x in v]
    if not vals:
        raise ValueError("空序列无均值（per-port 读数至少 1 个）")
    return sum(vals) / len(vals)


def dual_conductor_mode_impedances(
    zo_by_mode: Mapping[Hashable, float | Sequence[float]],
    eps_eff_by_mode: Mapping[Hashable, float | Sequence[float]],
) -> DualConductorModeImpedances:
    """双导体模端口模阻抗读数 → (Z0e, Z0o)（#307 换算链单源）。

    Args:
        zo_by_mode: 模键 → 模阻抗读数（Ω，单端口标量或多端口序列——序列
            先跨端口取算术均值）；至少两个模。
        eps_eff_by_mode: 模键 → 有效介电常数（同键面；序列同法取均值）。
            **模序识别依据：εeff 较高者=偶模**（#307：按 Z0 大小识别在本
            基准下反转向，禁止）。

    Returns:
        DualConductorModeImpedances（含 k_z 便利量）。

    Raises:
        ValueError: 模数 <2 / 键面不一致 / εeff 并列（识别歧义）/ 非正阻抗。
    """
    if len(zo_by_mode) < 2:
        raise ValueError(
            f"双导体端口至少 2 个模，得 {len(zo_by_mode)}（键={list(zo_by_mode)}）")
    if set(zo_by_mode) != set(eps_eff_by_mode):
        raise ValueError(
            f"zo/eps_eff 键面不一致：{sorted(map(str, zo_by_mode))} vs "
            f"{sorted(map(str, eps_eff_by_mode))}")
    zo = {k: _mean(v) for k, v in zo_by_mode.items()}
    eps = {k: _mean(v) for k, v in eps_eff_by_mode.items()}
    for k, z in zo.items():
        if not (z > 0.0):
            raise ValueError(f"模 {k!r} 的 Zo 读数须为正，得 {z!r}")
    # 模序识别：εeff 较高者=偶模（#307 唯一合法口径）；并列=歧义显式拒
    e_key, o_key = sorted(eps, key=lambda k: eps[k], reverse=True)[:2]
    if eps[e_key] == eps[o_key]:
        raise ValueError(
            f"两模 εeff 并列（{eps[e_key]!r}）——偶/奇识别歧义，显式拒绝"
            "（#307 口径禁止按 Z0 大小识别）")
    zc, zd = zo[e_key], zo[o_key]           # 共模/差模读数（跨端口均值）
    z0e = EVEN_FACTOR * zc
    z0o = ODD_FACTOR * zd
    k_z = (z0e - z0o) / (z0e + z0o)
    return DualConductorModeImpedances(
        z0e_ohm=z0e, z0o_ohm=z0o,
        even_mode_key=e_key, odd_mode_key=o_key,
        common_mode_zo_ohm=zc, diff_mode_zo_ohm=zd,
        eps_eff_even=eps[e_key], eps_eff_odd=eps[o_key], k_z=k_z)
