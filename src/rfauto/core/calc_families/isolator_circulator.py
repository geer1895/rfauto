"""隔离器/环行器理想 S 口径族两键（架构批 A8-B 席域 2，任务书候补"隔
离器/环行器理想 S 口径"；#222 triple-grep 证据 2026-10-11 实测：
isolator|circulator 注册键面零命中——core/circulator_synthesis.py 是铁氧
体结**尺寸综合内核**（Bosma 全闭式，函数未注册计算器，见边界节）。

两键：isolator_ideal_sparams（2 口非互易隔离器 dB 规格参数化理想 S：前
向插损 IL/反向隔离度 Iso/双口回损 RL → s21=c、s12=i、s11=s22=γ）/
circulator_ideal_sparams（3 口环行器 sense=cw|ccw 环行方向参数化理想 S：
环行项 c/隔离项 i/对角 γ + 每口无源性一致性守卫）。**两键均
reciprocal=False**（铁氧体非互易件，registry.py QM-1 §D-7 豁免位设计
用途的首批注册键；S≠Sᵀ 是设计本体，互易断言不适用）。

与既有面的边界（#222 triple-grep 证据，2026-10-11 实测）
--------------------------------------------------------
- core/circulator_synthesis.py=**铁氧体结尺寸综合内核**（Polder 张量→
  盘半径/耦合角/Wu-Rosenbaum 判据；其 ideal_junction_s_matrix=全局相位
  旋量 e^{jφ}P_sense、quasi_ideal_lossy_s_matrix=均匀衰减简化面——均
  **未注册**且无 RL/隔离结构）——本族=**器件级 dB 规格参数化注册键**
  （γ/c/i 三参数+passivity 一致性守卫+sense 翻转恒等式，零全局相位口
  径），语义"综合内核 vs 规格口径"不同不并入。
- magic_tee_s_matrix/waveguide_tee_s_matrix/hybrid_sum_difference
  （架构批 A5-A）=**互易**三/四口结（S=Sᵀ，功率分配/合成语义）——
  环行器=**非互易**铁氧体件（S≠Sᵀ 设计本体），物理语义相反不并入。
- attenuator_*=互易衰减器、cascade_budget=有源链级联——非铁氧体控制
  件，不并入。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_a8b_taper_isolator.py）
--------------------------------------------------------
- **理想隔离器**（Pozar《Microwave Engineering》§9.4 Ferrite Isolators
  理想口径）：S=[[0,0],[1,0]]（端口 1=输入/端口 2=输出；前向 1→2 全通、
  反向 2→1 全隔离；吸收体耗散反向波）。dB 规格参数化：s21=c=10^(−IL/20)
  （IL=前向插损 ≥0）、s12=i=10^(−Iso/20)（Iso=反向隔离度 ≥0，None=理想
  全隔离 → i=0）、s11=s22=γ=10^(−RL/20)（RL=双口回损 ≥0，None=理想匹
  配 → γ=0）。
- **理想环行器**（Pozar §9.4 / Bosma 无耗解极限）：sense=cw（1→2→3→1）
  时环行项 S21=S32=S13=c、隔离项 S12=S23=S31=i、对角 Sii=γ（与
  circulator_synthesis._permutation_matrix(SENSE_FORWARD) 同布局：
  matrix[row][col]、激励在列）；sense=ccw 环行/隔离项互换，恒等式
  S_ccw=S_cwᵀ（任意参数成立，构造级锚）。
- **无源性一致性守卫**（dB 规格三元组必须物理自洽，否则显式拒绝不凑
  绿）：隔离器 γ²+c²≤1 且 γ²+i²≤1；环行器 γ²+c²+i²≤1（每口激励功率
  预算；理想无耗+有限隔离组合天然违约——无耗三口结有限反向耦合必违
  酉性，守卫即该物理事实的显式化）。违约=拒绝，余量如实输出。
- 非互易度量：20lg|s12/s21| = IL−Iso（dB）；字段按实现实态取
  nonreciprocity_db=Iso−IL（典型 Iso>IL 为正，取的是该差的符号而非
  幅值），与等式左端互为反号；互易退化档 IL=Iso → S 对称（构造级
  自检字段）。

出处（Pozar《Microwave Engineering》4th ed. §9.4 Ferrite Isolators/
§9.6 Ferrite Circulators：理想隔离器 S=[[0,0],[1,0]] 与理想三口环行器
置换矩阵口径；dB 规格参数化与无源性一致性守卫为器件规格表通行工程口
径；sense 翻转恒等式与互易退化档为测试侧独立重解）。

守卫：il_db≥0、isolation_db≥0（或 None）、rl_db≥0（或 None）；sense 白
名单 {cw,ccw}；无源性一致性（见上）违约显式拒绝；数值 0.0 合法（判缺
失 is not None，#364④）；无 ``__all__``（公开 API 快照口径）。

接口：纯函数零 IO；math 本征；返回 JSON 可序列化结构（s_matrix 复数拆
[re,im] 嵌套，其余实数面/布尔）。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator
from .thermal import _finite

_SENSES = ("cw", "ccw")


def _db_to_mag(db: float) -> float:
    return 10.0 ** (-db / 20.0)


def _opt_db(value: float | None, name: str, tag: str) -> float | None:
    """可选 dB 参数（None=理想档哨兵；显式值须 ≥0；0.0 合法，#364④）。"""
    if value is None:
        return None
    out = _finite(value, f"{tag}.{name}")
    if out < 0.0:
        raise ValueError(
            f"{tag}: {name} 必须 ≥0（None=理想档哨兵），得到 {value!r}")
    return out


def _matrix_to_json(matrix: list[list[complex]]) -> list[list[dict]]:
    return [[{"re": float(v.real), "im": float(v.imag)} for v in row]
            for row in matrix]


@register_calculator(
    "isolator_ideal_sparams",
    "隔离器理想 2 口 S 口径：非互易铁氧体件（reciprocal=False 豁免位）"
    "dB 规格参数化——前向 s21=10^(−IL/20)、反向 s12=10^(−Iso/20)（None="
    "理想全隔离）、s11=s22=10^(−RL/20)（None=理想匹配）；无源性一致性守"
    "卫（γ²+c²≤1 双口）违约显式拒绝；理想极限档回 canonical [[0,0],[1,0]]",
    (("il_db", "float dB 前向插损 IL（≥0，缺省 0=理想无耗）"),
     ("isolation_db", "float dB 反向隔离度 Iso（≥0 或 None=∞ 理想隔离）"),
     ("rl_db", "float dB 双口回损 RL（≥0 或 None=理想匹配）")),
    required=(),
    reciprocal=False,
)
def isolator_ideal_sparams(il_db: float = 0.0,
                           isolation_db: float | None = None,
                           rl_db: float | None = None) -> dict[str, Any]:
    tag = "isolator_ideal_sparams"
    il = _finite(il_db, f"{tag}.il_db")
    if il < 0.0:
        raise ValueError(f"{tag}: il_db 必须 ≥0，得到 {il_db!r}")
    iso = _opt_db(isolation_db, "isolation_db", tag)
    rl = _opt_db(rl_db, "rl_db", tag)
    gamma = _db_to_mag(rl) if rl is not None else 0.0
    c_fwd = _db_to_mag(il)
    i_rev = _db_to_mag(iso) if iso is not None else 0.0
    margin_p1 = 1.0 - gamma * gamma - c_fwd * c_fwd
    margin_p2 = 1.0 - gamma * gamma - i_rev * i_rev
    if margin_p1 < 0.0 or margin_p2 < 0.0:
        raise ValueError(
            f"{tag}: dB 规格三元组违反无源性（γ²+c² 或 γ²+i² >1："
            f"margin1={margin_p1!r}, margin2={margin_p2!r}）——非物理规"
            "格显式拒绝（理想无耗+有限隔离/匹配组合必违约）")
    s_matrix = [
        [complex(gamma, 0.0), complex(i_rev, 0.0)],
        [complex(c_fwd, 0.0), complex(gamma, 0.0)],
    ]
    nonrecip_db = (round(iso - il, 9)
                   if iso is not None else None)
    return {
        "device": "isolator",
        "s_matrix": _matrix_to_json(s_matrix),
        "il_db": il,
        "isolation_db": iso,
        "rl_db": rl,
        "forward_mag": round(c_fwd, 12),
        "reverse_mag": round(i_rev, 12),
        "reflection_mag": round(gamma, 12),
        "nonreciprocity_db": nonrecip_db,
        "reciprocal_degenerate": (iso is not None
                                  and abs(iso - il) <= 1e-12),
        "port1_power_margin": round(margin_p1, 15),
        "port2_power_margin": round(margin_p2, 15),
        "ideal_limit": bool(il == 0.0 and iso is None and rl is None),
        "note": (
            "端口约定：1=输入、2=输出；s21=前向（1→2）、s12=反向隔离"
            "（2→1，反向波被铁氧体+吸收体耗散）；非互易设计本体 S≠Sᵀ"
            "（reciprocal=False 豁免位，互易断言不适用——S12=S21 仅在 "
            "IL=Iso 退化档成立）；无耗+有限隔离/回损组合违反无源性（耗散"
            "必须去某处）——守卫拒绝，如实不凑绿；理想极限档（全缺省）"
            "=canonical [[0,0],[1,0]]；频域无依赖（集总理想口径），色散/"
            "带宽特性不在口径"),
        "source": (
            "Pozar《Microwave Engineering》4th ed. §9.4 Ferrite "
            "Isolators（理想隔离器 S=[[0,0],[1,0]] 口径）；dB 规格参数化"
            "+无源性一致性守卫=器件规格表通行工程口径"),
    }


@register_calculator(
    "circulator_ideal_sparams",
    "环行器理想 3 口 S 口径：非互易铁氧体件（reciprocal=False 豁免位）"
    "sense=cw|ccw 环行方向参数化——环行项 10^(−IL/20)、隔离项 10^(−Iso/20)"
    "（None=理想）、对角 10^(−RL/20)（None=理想匹配）；每口无源性一致性"
    "守卫（γ²+c²+i²≤1）违约显式拒绝；sense 翻转恒等式 S_ccw=S_cwᵀ；理想"
    "极限档回置换矩阵（与 circulator_synthesis SENSE_FORWARD 同布局）",
    (("sense", "str 环行方向 cw（1→2→3→1）|ccw（1→3→2→1），缺省 cw"),
     ("il_db", "float dB 环行方向插损 IL（≥0，缺省 0=理想无耗）"),
     ("isolation_db", "float dB 反向隔离度 Iso（≥0 或 None=∞ 理想隔离）"),
     ("rl_db", "float dB 各口回损 RL（≥0 或 None=理想匹配）")),
    required=(),
    reciprocal=False,
)
def circulator_ideal_sparams(sense: str = "cw", il_db: float = 0.0,
                             isolation_db: float | None = None,
                             rl_db: float | None = None) -> dict[str, Any]:
    tag = "circulator_ideal_sparams"
    if sense not in _SENSES:
        raise ValueError(
            f"{tag}: sense 须 ∈{{'cw','ccw'}}（cw=1→2→3→1），得到 {sense!r}")
    il = _finite(il_db, f"{tag}.il_db")
    if il < 0.0:
        raise ValueError(f"{tag}: il_db 必须 ≥0，得到 {il_db!r}")
    iso = _opt_db(isolation_db, "isolation_db", tag)
    rl = _opt_db(rl_db, "rl_db", tag)
    gamma = _db_to_mag(rl) if rl is not None else 0.0
    c_circ = _db_to_mag(il)
    i_iso = _db_to_mag(iso) if iso is not None else 0.0
    margin = 1.0 - gamma * gamma - c_circ * c_circ - i_iso * i_iso
    if margin < 0.0:
        raise ValueError(
            f"{tag}: dB 规格三元组违反每口无源性（γ²+c²+i²="
            f"{gamma * gamma + c_circ * c_circ + i_iso * i_iso!r} >1）——"
            "非物理规格显式拒绝（理想无耗+有限隔离组合必违约酉性）")
    # cw（1→2→3→1）：环行项 S21,S32,S13=c；隔离项 S12,S23,S31=i（1-indexed）
    if sense == "cw":
        c_pairs = ((1, 0), (2, 1), (0, 2))
        i_pairs = ((0, 1), (1, 2), (2, 0))
    else:
        c_pairs = ((0, 1), (1, 2), (2, 0))
        i_pairs = ((1, 0), (2, 1), (0, 2))
    s_matrix = [[complex(gamma if i == j else 0.0, 0.0) for j in range(3)]
                for i in range(3)]
    for r, col in c_pairs:
        s_matrix[r][col] = complex(c_circ, 0.0)
    for r, col in i_pairs:
        s_matrix[r][col] = complex(i_iso, 0.0)
    total_energy = sum(abs(v) ** 2 for row in s_matrix for v in row)
    return {
        "device": "circulator",
        "sense": sense,
        "circulation_path": ("1→2→3→1" if sense == "cw" else "1→3→2→1"),
        "s_matrix": _matrix_to_json(s_matrix),
        "il_db": il,
        "isolation_db": iso,
        "rl_db": rl,
        "circulation_mag": round(c_circ, 12),
        "isolation_mag": round(i_iso, 12),
        "reflection_mag": round(gamma, 12),
        "nonreciprocity_db": (round(iso - il, 9)
                              if iso is not None else None),
        "reciprocal_degenerate": (iso is not None
                                  and abs(iso - il) <= 1e-12),
        "port_power_margin": round(margin, 15),
        "total_energy": round(total_energy, 15),
        "ideal_limit": bool(il == 0.0 and iso is None and rl is None),
        "note": (
            "矩阵布局=matrix[row][col]、激励在列（与 circulator_synthesis"
            "._permutation_matrix(SENSE_FORWARD) 同布局）；cw 档环行项 "
            "S21/S32/S13、隔离项 S12/S23/S31；sense 翻转恒等式 S_ccw=S_cw"
            "ᵀ（任意参数成立，构造级）；非互易设计本体 S≠Sᵀ（reciprocal="
            "False 豁免位，互易断言不适用——S 对称仅在 IL=Iso 退化档成"
            "立）；无耗+有限隔离组合违反酉性（总能量 Σ|S|²=3(γ²+c²+i²)"
            ">3 即违约）——守卫拒绝，如实不凑绿；理想极限档=置换矩阵"
            "（总能量 3）；频域无依赖（集总理想口径）"),
        "source": (
            "Pozar《Microwave Engineering》4th ed. §9.4/§9.6 Ferrite "
            "Circulators（理想三口环行器置换矩阵口径，Bosma 无耗解极限）"
            "；dB 规格参数化+每口无源性守卫=器件规格表通行工程口径"),
    }
