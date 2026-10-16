"""G16 矩形波导缝隙阵 Stevenson 族（批 B Wave3 W3-G15G16，2026-10-13）。

两键：slot_stevenson_conductance（宽壁纵向偏置缝谐振电导 g(x) 正反解）/
slot_array_synthesis_resonant（谐振（驻波）阵导电率阶梯 → 逐缝偏置/
交替换边/短路位）。

边界防撞（R7 §③ 三重搜索证据沿用规格包）
----------------------------------------------
rw_tables=EIA 商品矩形波导表；rwg_mmt=矩形波导模基 GSM 数值匹配；
waveguide_iris/wg_iris_*=膜片/窗匹配；circular_cavity_mode_*=圆柱腔；
siw_*=基片集成波导传输线——均不并入。本族只做**矩形波导宽壁纵向缝辐射
元 + 谐振（驻波）阵综合**（Stevenson 一阶口径）。行波（非谐振）阵的
Elliott 迭代综合、有限壁厚/缝宽修正（Stegen/Oliner 实测曲线）、窄壁斜缝
B(θ) 表不在键面（锚为实测曲线数字化，#118 不可自证，登记续作）。阵列
幅度综合走 array.* 既有键（本族键 2 只收外部权重向量，不重复注册）。

物理口径（docstring 写死，#1c/#300/#118 出处纪律）
----------------------------------------------
- TE10 导波波长（教科书式，Pozar *Microwave Engineering* §3.3）：
  λg = λ0/sqrt(1−(λ0/2a)²)，λ0 = c0/f；fc(TE10) = c0/2a；单模域
  fc < f < 2fc（域外显式拒绝；f=fc 恰值拒绝，λg 发散）。
- 谐振缝长（理想口径）：l_res ≈ λ0/2（kl≈π 假设显式化；实测缝因壁厚/
  缝宽缩短至 ~0.47-0.49λ0，Stegen/Mondal 实测——本键输出理想口径并附注）。
- **宽壁纵向偏置缝并联相对电导（Stevenson 式，含 (a/b) 与 cos² 两因子）**::

      g(x) = G/G0 = 2.09·(a/b)·(λg/λ0)·cos²(π·λ0/(2·λg))·sin²(π·x/a)

  x=缝中心对宽壁中线的偏置（公式对 x 偶函数，负偏置取 |x|，相位符号由
  相邻缝交替换边承担）；G0=波导等效传输线（并联电路）特性电导（归一化
  基准）。**反解**（与 PIER C 56 (2015) 式 (4) 同形态）：
  x = (a/π)·arcsin(sqrt(g/g_max))，其中
  g_max(f) = 2.09·(a/b)·(λg/λ0)·cos²(πλ0/(2λg))。g > g_max 显式拒绝
  （f=10GHz/WR90 时 g_max=0.877747<1，g=1 单缝匹配不可达——公式行为
  非缺陷）；g_max(f)=1 边界频率 **f=9.753118 GHz**（WR90 单缝匹配阵
  频率上限：低于此值 g=1 可达，如 g=1@9.375GHz → x=8.1437mm；
  高于此值单缝匹配不可达，驻波阵 Σgn=g_total 分摊到 N 缝不受限）。
- 谐振（驻波）阵综合：各缝同相功率叠加口径 gn = g_total·wn²/Σw²
  （Σgn=g_total；g_total=1 即单馈匹配），缝间距 λg/2（相邻缝交替换边
  保证同相），末缝后 λg/4 短路（λg/4 变换到缝处呈开路）。

出处（式形态=RESOLVED 裁决，规格包式 S1 已勘误）
----------------------------------------------
- 法源：Stevenson 1948, J. Appl. Phys. 19, 24-38, DOI 10.1063/1.1697868
  （原文 closed，Unpaywall 2026-10-13 实测不可达；**式号不可考——禁编造
  原文字号/式号**；式形态经四路独立二手源逐字互证 + WR90 数值逐位复算，
  四路出处/锚勘误表/置信度声明见
  内部规格档（Stevenson 阵综合）
  §2/§4/§6；裁决式含 (a/b) 与 cos²(πλ0/2λg) 两因子，规格包式 S1 已证伪；
  access_status=verified_secondary_4source）。
- λg/fc 教科书式：Pozar *Microwave Engineering* §3.3（任意波导教本同式）。
- 锚（#118 双路径）：RESOLVED §4 勘误表 A1-A7 替代锚 + 新增 N1-N4（实现席
  2026-10-13 全部独立复算逐位确认）+ S1 源（arXiv:2608.21231）Table II
  跨源钉 g(2.3814mm)@9.375GHz=0.127649（原文 0.12765）+ 测试面 sin² 半角
  恒等式第二路线（锚树 tests/unit/test_b_wave3_yagi_slot.py）。

理想化偏差方向注记（不修正项）：有限壁厚使 Stevenson 式**高估**电导——
S1 源 WR90（t=1.27mm）13 点全波标定 Stevenson/实测 = 1/0.9484±0.0020
（恒定高估 5.16%，六点散布 0.21%），方向与 Oliner 变分有限壁厚处理一致；
有限壁厚修正不在键面。

守卫：f/a/b 有限正值；b<a（TE10 主模性，b≥a 显式拒绝）；fc<f<2fc；
route 参数 offset_x_mm/g 二选一（同给/全缺显式拒绝，#364④ is not None
口径）；0 ≤ x ≤ a/2（x=0 恰值接受输出 g=0 缝退化无扰动；x=a/2 恰值接受
输出 g_max——工程上缝缘不贴壁实际偏置上限远小于 a/2，本键为理想闭式
口径）；0 ≤ g ≤ g_max（g>g_max 显式拒绝）；n_slots 正整数 2..128；
weights 与 n_slots 等长、逐项非负有限、全零拒绝；g_total>0；单缝
gn ≤ g_max（超限显式拒绝并提示降 g_total/收窄幅度锥度）。数值 0.0 合法
面判缺失一律 is not None（#364④）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

#: n_slots 上限（防组合面；规格包 §① 键 2 口径）
_N_SLOTS_MAX = 128

#: 常数 2.09（Stevenson 功率平衡口径前因子；四路二手源逐字一致）
_STEVENSON_CONST = 2.09

#: WR-90 内尺寸（mm；锚环境/示例口径，RESOLVED §4 复算环境）
_WR90_A_MM = 22.86
_WR90_B_MM = 10.16

_SOURCES = {
    "stevenson": (
        "Stevenson 1948, J. Appl. Phys. 19, 24-38, DOI 10.1063/1.1697868"
        "（原文 closed，式号不可考——禁编造原文字号；式形态=四路独立二手源"
        "逐字互证+WR90 数值逐位复算的 RESOLVED 裁决式，含 (a/b) 与 "
        "cos²(πλ0/2λg) 两因子，规格包式 S1 已勘误；四路出处与锚勘误表见 "
        "内部规格档 §2/§4/§6）；λg/fc 教科书式 "
        "Pozar Microwave Engineering §3.3"),
    "array": (
        "驻波阵综合口径（Σgn=g_total·wn²/Σw²+λg/2 同相间距+交替换边+末缝"
        "后 λg/4 短路；单缝导电率=Stevenson 式）；同内部规格档 §2/§5"
        "（S3 源 PIER C 56 (2015) 式 (4)(5) 同口径）；Stevenson 1948 DOI "
        "10.1063/1.1697868（原文 closed，式号不可考）"),
}


def _lambda0_mm(f_ghz: float) -> float:
    """自由空间波长 λ0 = c0/f（mm·GHz 单源 C_MM_GHZ）。"""
    return C_MM_GHZ / f_ghz


def _lambda_g_mm(f_ghz: float, a_mm: float) -> float:
    """TE10 导波波长 λg = λ0/sqrt(1−(λ0/2a)²)（教科书式）。"""
    l0 = _lambda0_mm(f_ghz)
    return l0 / math.sqrt(1.0 - (l0 / (2.0 * a_mm)) ** 2)


def _slot_g_max(f_ghz: float, a_mm: float, b_mm: float) -> float:
    """g_max(f) = 2.09·(a/b)·(λg/λ0)·cos²(πλ0/(2λg))（单一实现点）。

    测试面以 sin² 半角恒等式/λg 独立重算做第二路线互证。
    """
    l0 = _lambda0_mm(f_ghz)
    lg = _lambda_g_mm(f_ghz, a_mm)
    cos2 = math.cos(math.pi * l0 / (2.0 * lg)) ** 2
    return _STEVENSON_CONST * (a_mm / b_mm) * (lg / l0) * cos2


def _offset_from_g(g_val: float, f_ghz: float, a_mm: float, b_mm: float,
                   g_max: float) -> float:
    """反解 x = (a/π)·arcsin(sqrt(g/g_max))（S3 源式 (4) 同形态）。"""
    return (a_mm / math.pi) * math.asin(math.sqrt(g_val / g_max))


def _validate_guide(f_ghz: float, a_mm: float, b_mm: float) -> float:
    """共用域守卫：有限正值 + b<a + TE10 单模域 fc<f<2fc；返回 fc(GHz)。"""
    if a_mm <= 0.0:
        raise ValueError(
            f"slot_array: a_mm 必须 >0（宽壁内尺寸），得到 {a_mm!r}")
    if b_mm <= 0.0:
        raise ValueError(
            f"slot_array: b_mm 必须 >0（窄壁内尺寸），得到 {b_mm!r}")
    if b_mm >= a_mm:
        raise ValueError(
            f"slot_array: 要求 b<a（矩形波导 TE10 主模性），得到 "
            f"a_mm={a_mm!r}, b_mm={b_mm!r}")
    fc = C_MM_GHZ / (2.0 * a_mm)
    if not fc < f_ghz < 2.0 * fc:
        raise ValueError(
            f"slot_array: f_ghz={f_ghz!r} 出 TE10 单模域 "
            f"({fc:.9g}, {2.0 * fc:.9g}) GHz（fc=c0/2a；f=fc 恰值 λg 发散"
            f"拒绝，f≥2fc 高阶模域拒绝）")
    return fc


@register_calculator(
    "slot_stevenson_conductance",
    "波导缝隙 Stevenson 电导（正反解）：宽壁纵向偏置缝谐振相对电导 "
    "g(x)=2.09(a/b)(λg/λ0)cos²(πλ0/2λg)sin²(πx/a)——offset→g 正解或 "
    "g→offset 反解（route 自动分派，二选一）；随行 g_max(f) 元数据与 "
    "g_max=1 边界频率（WR90=9.753118GHz，低于此值单缝匹配 g=1 可达）；"
    "g>g_max 显式拒绝（公式封顶非缺陷）；谐振缝长=λ0/2 理想口径",
    (("f_ghz", "float GHz 工作频率（TE10 单模域 fc<f<2fc）"),
     ("a_mm", "float mm 波导宽壁内尺寸（>0；WR-90=22.86）"),
     ("b_mm", "float mm 波导窄壁内尺寸（>0 且 <a；WR-90=10.16）"),
     ("offset_x_mm", "float mm 缝中心偏置（0≤x≤a/2；与 g 二选一）"),
     ("g", "float 目标相对电导 G/G0（0≤g≤g_max；与 offset_x_mm 二选一）")),
    required=("f_ghz", "a_mm", "b_mm"),
)
def slot_stevenson_conductance(
    f_ghz: float,
    a_mm: float,
    b_mm: float,
    offset_x_mm: float | None = None,
    g: float | None = None,
) -> dict[str, Any]:
    """正反解：偏置↔谐振相对电导（route 按所给参数分派）。"""
    f = _finite(f_ghz, "f_ghz")
    a = _finite(a_mm, "a_mm")
    b = _finite(b_mm, "b_mm")
    if f <= 0.0:
        raise ValueError(
            f"slot_stevenson_conductance: f_ghz 必须 >0，得到 {f_ghz!r}")
    fc = _validate_guide(f, a, b)

    has_x = offset_x_mm is not None
    has_g = g is not None
    if has_x and has_g:
        raise ValueError(
            "slot_stevenson_conductance: offset_x_mm 与 g 二选一（同给显式"
            "拒绝，route 不可分派）")
    if not has_x and not has_g:
        raise ValueError(
            "slot_stevenson_conductance: offset_x_mm 与 g 须给其一（全缺"
            "显式拒绝）")

    g_max = _slot_g_max(f, a, b)
    if has_x:
        x = _finite(offset_x_mm, "offset_x_mm")
        if not 0.0 <= x <= a / 2.0:
            raise ValueError(
                "slot_stevenson_conductance: offset_x_mm 必须 ∈ [0, a/2]="
                f"[0, {a / 2.0:.9g}]（x=0 恰值=中缝无扰动 g=0；x=a/2 恰值"
                f"=贴壁缝 g_max；负偏置取 |x| 由相邻缝交替换边承担，本键不"
                f"收负值），得到 {offset_x_mm!r}")
        g_val = g_max * math.sin(math.pi * x / a) ** 2
        route = "offset_to_g"
    else:
        g_val = _finite(g, "g")
        if not 0.0 <= g_val <= g_max:
            raise ValueError(
                "slot_stevenson_conductance: g 必须 ∈ [0, g_max]="
                f"[0, {g_max:.9g}]（f={f:.9g} GHz 电导封顶 g_max={g_max:.6f}"
                "——超限即物理不可达显式拒绝：f 高于 g_max(f)=1 边界频率"
                "（WR90=9.753118 GHz）时 g=1 单缝匹配不可达，属公式行为非"
                f"缺陷），得到 {g!r}")
        x = _offset_from_g(g_val, f, a, b, g_max)
        route = "g_to_offset"

    l0 = _lambda0_mm(f)
    return {
        "route": route,
        "conductance": g_val,
        "offset_x_mm": x,
        "offset_frac": x / a,
        "g_max": g_max,
        "lambda_0_mm": l0,
        "lambda_g_mm": _lambda_g_mm(f, a),
        "fc_ghz": fc,
        "resonant_length_mm": l0 / 2.0,
        "note": (
            "Stevenson 一阶口径理想化：零壁厚、零缝宽、无限大宽壁、谐振缝长"
            "（kl≈π）；有限壁厚使本式高估电导（WR90 t=1.27mm 全波标定恒定"
            "高估 5.16%，方向与 Oliner 变分处理一致，不设修正项）；谐振缝长"
            "=λ0/2 理想口径（实测缝因壁厚/缝宽缩短至 ~0.47-0.49λ0）；"
            "offset_frac=x/a；g_max 随频率降（WR90 g_max(f)=1 边界 "
            "9.753118 GHz，参考点 8/9/9.375/10/11/12 GHz → "
            "3.172828/1.548308/1.235286/0.877747/0.543655/0.357935）"),
        "source": _SOURCES["stevenson"],
    }


@register_calculator(
    "slot_array_synthesis_resonant",
    "谐振缝隙阵综合（Stevenson 驻波阵口径）：权重向量 wn（外部幅度综合"
    "产物，如 Taylor）→ 逐缝相对电导 gn=g_total·wn²/Σw²（Σgn=g_total，"
    "缺省 1=单馈匹配）+ 反解偏置+相邻缝交替换边符号序列+λg/2 等间距轴向"
    "位置+末缝后 λg/4 短路位；单缝 gn≤g_max(f) 守卫（f 高于 9.753GHz "
    "WR90 时 g_max<1，g_total=1 单馈匹配须按 N≥ceil(1/g_max) 分摊）",
    (("f_ghz", "float GHz 工作频率（TE10 单模域 fc<f<2fc）"),
     ("a_mm", "float mm 波导宽壁内尺寸（>0；WR-90=22.86）"),
     ("b_mm", "float mm 波导窄壁内尺寸（>0 且 <a；WR-90=10.16）"),
     ("n_slots", "int 缝数（2..128）"),
     ("weights", "list[float] 逐缝幅度权重（≥0 有限，长度=n_slots，"
      "全零拒绝；可为 array.villeneuve_weights 等外部综合产物）"),
     ("g_total", "float Σgn 目标（>0，缺省 1.0=单馈匹配口径）")),
    required=("f_ghz", "a_mm", "b_mm", "n_slots", "weights"),
)
def slot_array_synthesis_resonant(
    f_ghz: float,
    a_mm: float,
    b_mm: float,
    n_slots: int,
    weights: list[float],
    g_total: float = 1.0,
) -> dict[str, Any]:
    """谐振阵综合：导电率阶梯 → 偏置/换边/位置/短路位（驻波阵口径）。"""
    f = _finite(f_ghz, "f_ghz")
    a = _finite(a_mm, "a_mm")
    b = _finite(b_mm, "b_mm")
    if f <= 0.0:
        raise ValueError(
            f"slot_array_synthesis_resonant: f_ghz 必须 >0，得到 {f_ghz!r}")
    fc = _validate_guide(f, a, b)
    gt = _finite(g_total, "g_total")
    if gt <= 0.0:
        raise ValueError(
            f"slot_array_synthesis_resonant: g_total 必须 >0，得到 "
            f"{g_total!r}")
    if isinstance(n_slots, bool):
        raise ValueError(
            f"slot_array_synthesis_resonant: n_slots 须为整数，得到 bool "
            f"{n_slots!r}")
    n_f = _finite(n_slots, "n_slots")
    if n_f != int(n_f):
        raise ValueError(
            f"slot_array_synthesis_resonant: n_slots 须为整数，得到 "
            f"{n_slots!r}")
    n = int(n_f)
    if not 2 <= n <= _N_SLOTS_MAX:
        raise ValueError(
            f"slot_array_synthesis_resonant: n_slots 必须 ∈ [2, "
            f"{_N_SLOTS_MAX}]（下限=驻波阵至少两缝；上限防组合面），得到 "
            f"{n_slots!r}")
    if not isinstance(weights, (list, tuple)):
        raise ValueError(
            f"slot_array_synthesis_resonant: weights 须为 list[float]，"
            f"得到 {type(weights).__name__}")
    if len(weights) != n:
        raise ValueError(
            f"slot_array_synthesis_resonant: weights 长度 {len(weights)} "
            f"≠ n_slots={n}（显式校验）")
    w = [_finite(v, f"weights[{i}]") for i, v in enumerate(weights)]
    if any(v < 0.0 for v in w):
        raise ValueError(
            f"slot_array_synthesis_resonant: weights 逐项须 ≥0，得到 "
            f"{weights!r}")
    w_sum_sq = math.fsum(v * v for v in w)
    if w_sum_sq <= 0.0:
        raise ValueError(
            "slot_array_synthesis_resonant: weights 全零显式拒绝（导电率"
            "阶梯无定义）")

    g_max = _slot_g_max(f, a, b)
    g_n = [gt * (v * v) / w_sum_sq for v in w]
    g_peak = max(g_n)
    if g_peak > g_max:
        raise ValueError(
            "slot_array_synthesis_resonant: 单缝电导超封顶——"
            f"max(gn)={g_peak:.9g} > g_max(f)={g_max:.9g}（窄缝强激励设计"
            "不可实现，属守卫非建议）：降低 g_total 或收窄幅度锥度；"
            "f 高于 9.753 GHz（WR90）时 g_max<1，Σgn=1 的单馈匹配须按 "
            "N≥ceil(1/g_max) 分摊")

    lg = _lambda_g_mm(f, a)
    offsets_mag = [
        _offset_from_g(v, f, a, b, g_max) if v > 0.0 else 0.0 for v in g_n]
    signs = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    offsets = [s * m for s, m in zip(signs, offsets_mag, strict=True)]
    positions = [i * lg / 2.0 for i in range(n)]

    return {
        "n_slots": n,
        "conductances": g_n,
        "offset_x_mm": offsets,
        "offset_signs": signs,
        "positions_mm": positions,
        "slot_spacing_mm": lg / 2.0,
        "short_position_mm": positions[-1] + lg / 4.0,
        "sum_conductance": math.fsum(g_n),
        "g_total": gt,
        "g_max": g_max,
        "lambda_0_mm": _lambda0_mm(f),
        "lambda_g_mm": lg,
        "fc_ghz": fc,
        "resonant_length_mm": _lambda0_mm(f) / 2.0,
        "note": (
            "驻波阵口径：gn=g_total·wn²/Σw²（Σgn=g_total，各缝同相功率"
            "叠加；g_total 缺省 1=单馈匹配）；缝间距 λg/2 同相+相邻缝交替"
            "换边（offset_signs 符号序列，offset 幅值=|x| 对 x 偶函数）；"
            "末缝后 λg/4 短路（变换到末缝呈开路）；offset 符号约定首缝 "
            "+x；λg>λ0 栅瓣注记：间距 λg/2 的驻波阵 E 面无栅瓣但 H 面"
            "口径按 λ0/2 阵元间距计；零权重缝 offset=0（不辐射占位）如实"
            "输出"),
        "source": _SOURCES["array"],
    }
