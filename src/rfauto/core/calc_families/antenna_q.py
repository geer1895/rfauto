"""电小天线 Q 提取/带宽/Chu 界一键（架构批 W3-K 池件批，R2_core_tier5
§⑤-2/§③-11 提升核——池件 T1-A-04 分期承诺同笔清偿）。

提升核：消费 core/antenna_q.py 全套闭式（round17 §三 AP-12 落地物；
core docstring 的"分期承诺落注（T1-A-04）"自证"未注册 CALC 属登记级
边界如实……本注记即分期注记在位"——本键即其 CALC 注册面）。单源
零公式复制：Yaghjian-Best 阻抗导数式、FBW 换算、Chu/McLean 界判定
全在内核（Chu 界经 core/bounds.chu_q_bound 单源）。

公式（出处见 core/antenna_q.py 模块 docstring，不复制推导）
----------------------------------------------------------------
- Q(ω) = ω·|dZ/dω|/(2·Re Z)（Yaghjian & Best, "Impedance, Bandwidth,
  and Q of Antennas", IEEE TAP 53(4):1298-1324, 2005），X=0 谐振点取值
  （resonance_extract 线性内插过零）。
- FBW_hp = 2/Q（匹配半功率全宽）；FBW_S = (S−1)/(√S·Q)（VSWR≤S 全宽，
  串联 RLC 精确恒等）。
- Chu 界可达性 verdict：Q_min = 1/(ka)³+1/(ka)（McLean 1996 严格式，
  core/bounds.chu_q_bound 单源）；Q_meas < Q_min·(1−tol) →
  "unreachable"（低于无耗下界=物理不可能），否则 "reachable"。

适用域与边界
------------
- 单谐振口径：采样契约 Δf/f₀ ≪ 1/(2Q)（串联型中心差分精确、并联型
  O((2QΔf/f₀)²)/6）；多谐振/宽带口径如实退化（取 X=0 全局最小邻）。
- Re Z ≤ 0 频点 Q 无定义（内核 NaN 返回）——谐振点若落 R≤0，本键
  显式拒绝（NaN 不透传键面，JSON 信封安全）。
- 采样窗内无 X=0 过零 → 显式 ValueError（内核语义透传，不凑数）。
- ka 判定须给电尺寸 ka=c·ka/c0... 即 ka=k·a（波数×最大物理半径）；
  不给时只做 Q/带宽面（verdict 字段 None）。
- boundary：bounds（Chu/Harrington 界供给端，本键消费其单源）、
  linear_antenna_zin（偶极/小环阻抗解析面——本键吃任意实测/合成
  Z(f) 序列）、helix_axial（螺旋经验增益面）、antenna_regions（场区
  几何面）。

锚（#118 独立算术，tests/unit/test_w3k_pool_domains.py）：①串联 RLC
合成（R=50Ω、f0=1GHz、Q=40）→ q 机器精度回收 ω0L/R、FBW_hp=2/Q、
FBW_S(S=2)=1/(√2·Q)；②Γ(f) 数值宽度第三方法（二分找 |Γ|²=1/2 穿越与
换算式互证，两推导路径独立）；③FBW_hp=FBW_S|_{S=(1+√2)²} 自洽恒等
（(S−1)/√S=2）；④ka=π/2 → Q_min=8/π³+2/π=0.894632 手算锚（A-01 勘误
后口径）；⑤Q=0.1 合成 → unreachable、圆极化减半判据翻转锚。
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from .registry import register_calculator


def _finite_list(values: Any, name: str) -> list[float]:
    """序列档守卫：一维非空、全有限（bool 显式拒收）。"""
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ValueError(f"{name} 须为数值序列，实际 {type(values).__name__}")
    out: list[float] = []
    for k, v in enumerate(values):
        if isinstance(v, bool):
            raise ValueError(f"{name}[{k}] 必须为数值（不接受 bool）")
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"{name}[{k}] 必须为有限数，实际 {v!r}")
        out.append(f)
    if len(out) == 0:
        raise ValueError(f"{name} 须为非空序列")
    return out


@register_calculator(
    "antenna_q_yaghjian_best",
    "电小天线Q带宽Chu界判定：Yaghjian-Best 2005 阻抗导数式 "
    "Q=ω|dZ/dω|/(2R) 于 X=0 谐振点提取；匹配半功率 FBW=2/Q 与 VSWR≤S "
    "带宽 FBW_S=(S−1)/(√S·Q)；给 ka 时附 Chu/McLean 界 1/(ka)³+1/(ka) "
    "判定（低于无耗下界判 unreachable）；单谐振口径（Δf/f₀≪1/(2Q) "
    "采样契约），R≤0 谐振/无过零显式拒绝。单源 core/antenna_q（提升核"
    "注册面）",
    (("f_hz", "list[float] Hz 升序频率采样（≥3 点）"),
     ("z_re_ohm", "list[float] Ω 阻抗实部（与 f_hz 同长）"),
     ("z_im_ohm", "list[float] Ω 阻抗虚部（与 f_hz 同长）"),
     ("vswr", "float VSWR 档 S（>1，缺省 2）"),
     ("ka", "float k·a 电尺寸（>0 可选；给定时附 Chu 界 verdict）"),
     ("polarization", "str 线/圆极化档：linear/circular（缺省 linear，"
                      "圆极化 Chu 界减半）")),
    required=("f_hz", "z_re_ohm", "z_im_ohm"),
)
def antenna_q_yaghjian_best(
    f_hz: list[float],
    z_re_ohm: list[float],
    z_im_ohm: list[float],
    vswr: float = 2.0,
    ka: float | None = None,
    polarization: str = "linear",
) -> dict[str, Any]:
    from rfauto.core.antenna_q import (
        half_power_bandwidth,
        resonance_extract,
        vswr_bandwidth,
    )

    freq = _finite_list(f_hz, "f_hz")
    zre = _finite_list(z_re_ohm, "z_re_ohm")
    zim = _finite_list(z_im_ohm, "z_im_ohm")
    if not (len(freq) == len(zre) == len(zim)):
        raise ValueError(
            f"f_hz/z_re_ohm/z_im_ohm 长度须一致，得 {len(freq)}/"
            f"{len(zre)}/{len(zim)}")
    if len(freq) < 3:
        raise ValueError(f"至少 3 个频点（中心差分），得 {len(freq)}")
    if any(b - a <= 0.0 for a, b in itertools.pairwise(freq)):
        raise ValueError("f_hz 必须严格升序")
    if not isinstance(polarization, str) or polarization not in (
            "linear", "circular"):
        raise ValueError(
            f"polarization 必须是 ['circular', 'linear'] 之一，"
            f"收到 {polarization!r}")

    z = [complex(a, b) for a, b in zip(zre, zim, strict=True)]
    res = resonance_extract(freq, z)
    q = float(res["q"])
    if not math.isfinite(q):
        raise ValueError(
            "谐振点 Q 非有限（Re Z≤0 频点的导数式 Q 无定义）——检查"
            "采样数据或改用窄带采样窗")
    r0 = float(res["r0_ohm"])
    if r0 <= 0.0:
        raise ValueError(
            f"谐振点 Re Z={r0}≤0（Yaghjian-Best 口径要求 R>0），显式拒绝")

    s_val = float(vswr)
    if isinstance(vswr, bool) or not math.isfinite(s_val) or s_val <= 1.0:
        raise ValueError(f"vswr 必须 >1（S=1 为零带宽理想匹配），得 {vswr}")

    out: dict[str, Any] = {
        "n_points": len(freq),
        "f0_hz": res["f0_hz"],
        "r0_ohm": r0,
        "x0_ohm": float(res["x0_ohm"]),
        "q": q,
        "fbw_half_power": half_power_bandwidth(q),
        "vswr_s": s_val,
        "fbw_vswr": vswr_bandwidth(q, s_val),
        "ka": None,
        "polarization": polarization,
        "verdict_chu": None,
        "q_min_chu": None,
        "margin_ratio_chu": None,
        "method": res["method"],
        "note": (
            "单谐振口径（Δf/f₀≪1/(2Q) 采样契约；多谐振宽带如实退化）；"
            "FBW 为全宽口径（匹配半功率 |Γ|²=1/2 档 FBW=2/Q；文献常引"
            "1/Q 为单边半宽或松口径）；Chu 界 tol=0.05 相对余量（贴界"
            "浮点噪声不判违约）"),
        "source": (
            "Yaghjian & Best 2005 IEEE TAP 53(4):1298-1324（Q/带宽）；"
            "McLean 1996（Chu 界严格式，经 core/bounds 单源）"),
    }
    if ka is not None:
        if isinstance(ka, bool):
            raise ValueError("ka 必须为数值（不接受 bool）")
        from rfauto.core.antenna_q import q_reachability_verdict

        ka_val = float(ka)
        if not math.isfinite(ka_val) or ka_val <= 0.0:
            raise ValueError(f"ka 必须 >0，得 {ka_val}")
        verdict = q_reachability_verdict(ka_val, q,
                                         polarization=polarization)
        out.update({
            "ka": ka_val,
            "verdict_chu": verdict["verdict"],
            "q_min_chu": verdict["q_min_chu"],
            "margin_ratio_chu": verdict["margin_ratio"],
        })
    return out
