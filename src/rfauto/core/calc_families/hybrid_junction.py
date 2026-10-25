"""混合结/魔 T/波导三口结族（aurora72 A5-A 席域 2，R7 候补 G8 大件首拆席）。

出处（教科书经典口径二级转引，详见下节物理口径）：
- magic_tee_s_matrix：理想魔 T 四约束口径（Pozar, Microwave
  Engineering §7.5 混合结；幺正+E/H 臂隔离+3dB 均分+相位四约束
  独立复核）。
- waveguide_tee_s_matrix：H 面/E 面理想对称无耗三口结功率波口径
  第一性推导（幺正+互易+镜像对称+对偶四约束钉死）。
- hybrid_sum_difference：魔 T 和差合成行为（能量守恒恒等+正交 3dB
  拆分；同 Pozar §7.5 口径）。

三键：magic_tee_s_matrix（魔 T 理想 4 口 S 矩阵：匹配+E/H 臂隔离+3dB 均分+
和差相位行为，激励口逐端口输出） / waveguide_tee_s_matrix（H 面/E 面理想对称
无耗三口结 S 矩阵：并联星形结/串联环形结功率波闭式，幺正+互易+镜像对称+对偶
四约束钉死） / hybrid_sum_difference（魔 T 和差合成行为：双侧臂输入→和口/差
口功率，能量守恒恒等+正交 3dB 拆分）。

与既有耦合/功分面的边界（语义防撞，R7 G8 + 本次 triple-grep 证据）
--------------------------------------------------------
- 全仓 grep（magic.tee|魔T|hybrid_ring|rat_race|e_plane_tee|waveguide_tee）
  注册键面零命中；ratrace 仅 core/anchor_benchmark **模板锚判读**（七门
  判读模板跑分，非设计键）、butler_matrix 内部固定理想 **90°** 混合环块
  （未注册键，90° 正交口径与本族 **180°** 混合结不同）、even_odd_split=
  功分器奇偶模分析面——均不并入。
- unequal_split_wilkinson/bethe_hole_coupler=电阻功分/孔耦合**综合**键
  （出几何尺寸）；本族只做**结器件理想 S 矩阵口径**（不出波导尺寸综合
  ——E/H 臂口径尺寸设计属波导模板域，如实注记不做）。
- anchors.py:136 电阻衰减器/ratrace"席位"=模板真机锚判读语境，非本族。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 魔 T（匹配 E/H 混合结，Pozar Microwave Engineering §7.5 混合结口径）：
  端口 1=H 臂和口（sum）、4=E 臂差口（difference）、2/3=侧臂（互隔离）：

      S = (1/√2)·[[0, 1, 1, 0],
                  [1, 0, 0, 1],
                  [1, 0, 0, -1],
                  [0, 1, -1, 0]]

  四约束钉死：①幺正（无耗）②S14=S41=0（E/H 臂隔离）③匹配 S_ii=0
  ④和差相位行为（激励 1→2/3 同相各 1/√2；激励 4→2/3 反相各 1/√2）。
  符号约定（哪路取负）随端口参考方向选择可整体置换/取共轭，物理不变
  ——本实现写死上式口径（测试侧以幺正+隔离+3dB+相位四约束独立复核）。
  和差合成：b_sum=(a2+a3)/√2、b_diff=(a2−a3)/√2；能量守恒
  |b_sum|²+|b_diff|²=|a2|²+|a3|² 恒等（幺正推论）；等幅同相→差口零
  （隔离 null）、反相→和口零、正交→恰各半（−3.0103dB 恒等）。
- H 面/E 面三口结（理想对称无耗互易，功率波口径第一性推导）：
  并联星形结（H 面，共电压节点，KCL 推导）：S_ii=−1/3、S_ij=+2/3；
  串联环形结（E 面，KVL 对偶）：S_ii=+1/3、S_ij=−2/3。
  四约束钉死：①幺正（列范数 1/正交）②互易 S=Sᵀ ③镜像对称（2↔3 等价）
  ④对偶 S_E=−S_H。无耗互易三口**全匹配不可能**（S11=±1/3 是拓扑必然
  ——匹配三端口需非互易，环行器另域）；侧臂均分 20lg(2/3)=−3.5218dB、
  支臂反射 |S11|=1/3（回损 9.5424dB）。印刷矩阵各文献符号约定不一
  （端口参考方向选择所致，部分 ±1/2 表违反幺正），本实现按四约束口径
  落定（测试侧以 KCL/KVL 线性方程组独立重解=异路线互证 #118）。

验证（in-output xcheck + 测试侧独立重算，#118 不自证）
------------------------------------------------------
- 魔 T：SS†=I 残差字段 ≤1e-12（测试侧 numpy 独立复算）；|S21|=1/√2 常数；
  S14=0；激励 1/4 的 2/3 相位差 0°/180° 恒等；和差键与 4 口矩阵乘
  b=S·a（匹配负载口径）逐位互证（跨键）。
- 三口结：幺正残差字段；S_E=−S_H 对偶残差 ≤1e-15；|S11|=1/3、
  20lg(2/3)=−3.5218dB 常数；测试侧 KCL/KVL 方程组重解 ≤1e-12。
- 和差键：能量守恒残差字段 ≤1e-12；等幅同相/反相双 null；正交 −3.0103dB
  恒等；全 4 口矩阵乘独立路线逐位互证。

守卫：excite_port∈{1,2,3,4}；tee_type∈{h_plane,e_plane}；p2_dbm/p3_dbm
∈[−300,300] 有限（幅值下溢防呆）；phase_deg 有限；越界一律显式拒绝。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

# 理想魔 T S 矩阵（(1/√2)·整数符号阵；口径见模块 docstring 四约束）
_MAGIC_TEE_INT = (
    (0, 1, 1, 0),
    (1, 0, 0, 1),
    (1, 0, 0, -1),
    (0, 1, -1, 0),
)
_INV_SQRT2 = 1.0 / math.sqrt(2.0)
_MAGIC_TEE_S = tuple(
    tuple(_INV_SQRT2 * float(v) for v in row) for row in _MAGIC_TEE_INT)

# H 面（并联星形结）/E 面（串联环形结）理想对称无耗三口结闭式
_TEE_OFF = 2.0 / 3.0
_TEE_S = {
    "h_plane": (-1.0 / 3.0, _TEE_OFF),   # (S_ii, S_ij)
    "e_plane": (1.0 / 3.0, -_TEE_OFF),
}

_DBM_MIN = -300.0
_DBM_MAX = 300.0
# 隔离 null 份额口径：frac<1e-24 → dBm 如实 None（浮点理想零噪声电平不冒充
# 伪精确 dBm 值，与 note 口径一致）
_NULL_FRAC_TOL = 1e-24

_SOURCES = {
    "magic_tee": "理想魔 T 四约束口径（Pozar §7.5 混合结）：幺正+E/H 臂隔离+"
                 "全匹配+和差相位行为；符号约定写死见模块 docstring",
    "tee": "对称无耗互易三口结功率波闭式（并联星形/串联环形 KCL/KVL 第一性"
           "推导）；幺正+互易+镜像对称+E/H 对偶四约束钉死；S_E=−S_H",
    "sum_diff": "和差合成 b±=(a2±a3)/√2（魔 T 侧臂口径）；能量守恒=幺正推论；"
                "正交激励恰各半 −3.0103dB 恒等",
}


def _matrix_to_json(m: tuple[tuple[complex, ...], ...]) -> list[list[list[float]]]:
    """复矩阵 → [re, im] 嵌套列表（JSON 进出契约，coupling_matrix 同构）。"""
    return [[[round(c.real, 15), round(c.imag, 15)] for c in row]
            for row in m]


def _unitarity_residual(m: tuple[tuple[complex, ...], ...]) -> float:
    """max|(SS†−I)_ij|（纯 Python 独立路线，测试侧 numpy 复算互证）。"""
    n = len(m)
    worst = 0.0
    for i in range(n):
        for j in range(n):
            acc = 0.0 + 0.0j
            for k in range(n):
                acc += m[i][k] * m[j][k].conjugate()
            target = 1.0 if i == j else 0.0
            worst = max(worst, abs(acc - target))
    return worst


# ─── 键 1：魔 T 理想 S 矩阵（激励口逐端口行为）──────────────────────────────

@register_calculator(
    "magic_tee_s_matrix",
    "魔 T 理想 S 矩阵口径：匹配 E/H 混合结 4 口——端口 1=H 臂和口/4=E 臂差"
    "口/2·3=侧臂互隔离；S 矩阵 + 幺正残差 + E/H 臂隔离 S14=0 + 3dB 均分 "
    "|S21|²=0.5 + 激励口逐端口输出功率与相位行为（激励 1→侧臂同相 0°、激励 "
    "4→侧臂反相 180°、激励 2→和/差口各半）。锚：SS†=I 测试侧 numpy 独立复算；"
    "3.0103dB/隔离/相位三常数恒等；与 hybrid_sum_difference 跨键矩阵乘互证。"
    "注意：理想口径出 S 矩阵与功率分配，不出波导尺寸综合",
    (("excite_port", "int 激励端口 ∈{1,2,3,4}（缺省 1=H 臂和口）"),),
    required=(),
)
def magic_tee_s_matrix(excite_port: int = 1) -> dict[str, Any]:
    # bool 显式拒收；整值 float（JSON 通道 2.0）按 _as_int 家族宽口径收敛
    # （_finite 拒 nan/inf + round 差 ≤1e-9），非整值/非数值类型仍显式拒绝
    if isinstance(excite_port, bool):
        raise ValueError(
            f"magic_tee_s_matrix: excite_port 须为整数端口序号，得到布尔值 "
            f"{excite_port!r}")
    if isinstance(excite_port, float):
        out = _finite(excite_port, "excite_port")
        iout = round(out)
        if abs(out - iout) > 1e-9:
            raise ValueError(
                f"magic_tee_s_matrix: excite_port 须为整数端口序号，得到 "
                f"{excite_port!r}")
        excite_port = iout
    if not isinstance(excite_port, int):
        raise ValueError(
            f"magic_tee_s_matrix: excite_port 须为整数端口序号，得到 "
            f"{excite_port!r}")
    if excite_port not in (1, 2, 3, 4):
        raise ValueError(
            f"magic_tee_s_matrix: excite_port 须 ∈{{1,2,3,4}}（1=H 臂和口、"
            f"4=E 臂差口、2/3=侧臂），得到 {excite_port!r}")
    m = tuple(tuple(complex(v) for v in row) for row in _MAGIC_TEE_S)
    resid = _unitarity_residual(m)
    col = [m[r][excite_port - 1] for r in range(4)]
    powers = [abs(b) ** 2 for b in col]
    phase_pair = (2, 3) if excite_port in (1, 4) else (1, 4)
    rel = col[phase_pair[0] - 1] * col[phase_pair[1] - 1].conjugate()
    # 相位归一到 [0,360)（反相=180° 口径，负角语义写死不出现）
    phase_diff_deg = (math.degrees(cmath.phase(rel)) % 360.0
                      if abs(rel) > 0.0 else None)
    return {
        "ports": {"1": "h_arm_sum", "4": "e_arm_diff",
                  "2": "side_a", "3": "side_b"},
        "s_matrix": _matrix_to_json(m),
        "unitarity_residual": round(resid, 18),
        "isolation_s14_linear": round(abs(m[0][3]) ** 2, 18),
        "split_power_frac": 0.5,
        "split_power_db": round(-10.0 * math.log10(2.0), 12),
        "excite_port": excite_port,
        "output_powers_frac": [round(p, 18) for p in powers],
        "phase_pair": list(phase_pair),
        "phase_diff_deg": (
            None if phase_diff_deg is None else round(phase_diff_deg, 12)),
        "note": (
            "理想口径（匹配+隔离+3dB）；符号约定随端口参考方向选择，本实现"
            "写死模块 docstring 矩阵（物理=四约束，可整体置换/共轭）；和差"
            "行为数值面走 hybrid_sum_difference（跨键互证）"),
        "source": _SOURCES["magic_tee"],
    }


# ─── 键 2：H 面/E 面三口结 S 矩阵 ────────────────────────────────────────────

@register_calculator(
    "waveguide_tee_s_matrix",
    "H 面/E 面波导三口结理想 S 矩阵：对称无耗互易星形结功率波闭式——H 面"
    "（并联）S_ii=−1/3、S_ij=+2/3；E 面（串联对偶）S_ii=+1/3、S_ij=−2/3；"
    "幺正+互易+镜像对称+E/H 对偶（S_E=−S_H）四约束钉死。侧臂均分 20lg(2/3)"
    "=−3.5218dB、支臂反射 1/3（回损 9.5424dB）=无耗互易三口不可全匹配的拓扑"
    "必然（匹配需非互易=环行器另域）。锚：KCL/KVL 方程组测试侧独立重解；"
    "对偶残差 ≤1e-15；−3.5218dB/9.5424dB 常数。理想口径不出尺寸综合",
    (("tee_type", "str 三口结类型 ∈{h_plane,e_plane}（缺省 h_plane 并联星形"
      "结）"),),
    required=(),
)
def waveguide_tee_s_matrix(tee_type: str = "h_plane") -> dict[str, Any]:
    if tee_type not in _TEE_S:
        raise ValueError(
            f"waveguide_tee_s_matrix: tee_type 须 ∈{{h_plane,e_plane}}"
            f"（h_plane=并联星形结、e_plane=串联环形结对偶），得到 "
            f"{tee_type!r}")
    s_ii, s_ij = _TEE_S[tee_type]
    m = tuple(
        tuple(s_ii if i == j else s_ij for j in range(3))
        for i in range(3))
    m = tuple(tuple(complex(v) for v in row) for row in m)
    resid = _unitarity_residual(m)
    dual_type = "e_plane" if tee_type == "h_plane" else "h_plane"
    d_ii, d_ij = _TEE_S[dual_type]
    dual_resid = max(
        abs(m[i][j] - complex(-d_ii if i == j else -d_ij))
        for i in range(3) for j in range(3))
    return {
        "tee_type": tee_type,
        "ports": {"1": "branch_arm", "2": "collinear_a", "3": "collinear_b"},
        "s_matrix": _matrix_to_json(m),
        "unitarity_residual": round(resid, 18),
        "s11_mag": round(abs(m[0][0]), 15),
        "s11_return_loss_db": round(-20.0 * math.log10(abs(m[0][0])), 12),
        "side_split_db": round(20.0 * math.log10(_TEE_OFF), 12),
        "side_to_side_linear": round(abs(m[1][2]), 15),
        "dual_tee_type": dual_type,
        "duality_residual": round(dual_resid, 18),
        "note": (
            "理想对称无耗互易三口结口径：印刷矩阵各文献符号约定不一（端口"
            "参考方向选择所致），本实现以幺正+互易+镜像对称+对偶四约束钉死"
            "（KCL/KVL 独立重解见锚树）；'3dB 均分'直觉属失配理想化——无耗"
            "互易三口拓扑必然带 1/3 反射，匹配三端口需非互易（环行器）；"
            "尺寸综合属波导模板域不在本键"),
        "source": _SOURCES["tee"],
    }


# ─── 键 3：魔 T 和差合成行为 ─────────────────────────────────────────────────

@register_calculator(
    "hybrid_sum_difference",
    "魔 T/180° 混合结和差合成：双侧臂复数输入（dBm+相对相位）→ 和口 "
    "b_sum=(a2+a3)/√2 与差口 b_diff=(a2−a3)/√2 功率（dBm，null 如实 None）+"
    "占总功率份额；能量守恒 |b_sum|²+|b_diff|²=|a2|²+|a3|² 恒等（残差字段）"
    "；等幅同相→差口 null（隔离）、反相→和口 null、正交→恰各半 −3.0103dB。"
    "锚：与 magic_tee_s_matrix 全矩阵乘 b=S·a 匹配负载口径跨键逐位互证；"
    "正交 3.0103dB 恒等",
    (("p2_dbm", "float dBm 侧臂 2 输入功率（∈[−300,300]）"),
     ("p3_dbm", "float dBm 侧臂 3 输入功率（∈[−300,300]）"),
     ("phase_deg", "float deg 侧臂 3 相对侧臂 2 的相位（缺省 0=同相）")),
    required=("p2_dbm", "p3_dbm"),
)
def hybrid_sum_difference(p2_dbm: float, p3_dbm: float,
                          phase_deg: float = 0.0) -> dict[str, Any]:
    p2 = _finite(p2_dbm, "p2_dbm")
    p3 = _finite(p3_dbm, "p3_dbm")
    phase = _finite(phase_deg, "phase_deg")
    for name, val in (("p2_dbm", p2), ("p3_dbm", p3)):
        if not _DBM_MIN <= val <= _DBM_MAX:
            raise ValueError(
                f"hybrid_sum_difference: {name} 须 ∈[{_DBM_MIN},{_DBM_MAX}]"
                f"（幅值下溢/上溢防呆），得到 {val!r}")
    a2 = cmath.sqrt(10.0 ** (p2 / 10.0))          # √mW 幅度口径
    a3 = cmath.sqrt(10.0 ** (p3 / 10.0)) * cmath.exp(
        1j * math.radians(phase))
    b_sum = (a2 + a3) / math.sqrt(2.0)
    b_diff = (a2 - a3) / math.sqrt(2.0)
    p_sum_mw = abs(b_sum) ** 2
    p_diff_mw = abs(b_diff) ** 2
    p_total_mw = 10.0 ** (p2 / 10.0) + 10.0 ** (p3 / 10.0)
    conserv_resid = abs((p_sum_mw + p_diff_mw) - p_total_mw)
    frac_sum = p_sum_mw / p_total_mw
    frac_diff = p_diff_mw / p_total_mw
    # null 口径：份额 <1e-24 → dBm 如实 None（理想零在浮点下是 ~1e-31 噪声
    # 电平，不冒充 −300dBm 类伪精确值）；balanced 判据带 1e-12 容差
    # （正交等幅拆分的浮点噪声边缘，防 0.5±1e-16 翻 dominant）

    def _dbm(p_mw: float, frac: float) -> float | None:
        if p_mw <= 0.0 or frac < _NULL_FRAC_TOL:
            return None
        return round(10.0 * math.log10(p_mw), 12)

    if abs(frac_sum - 0.5) <= 1e-12:
        dominant = "balanced"
    elif frac_sum > frac_diff:
        dominant = "sum"
    else:
        dominant = "diff"
    isolation_null = frac_sum < _NULL_FRAC_TOL or frac_diff < _NULL_FRAC_TOL
    return {
        "p2_dbm": p2,
        "p3_dbm": p3,
        "phase_deg": phase,
        "total_in_dbm": round(10.0 * math.log10(p_total_mw), 12),
        "p_sum_dbm": _dbm(p_sum_mw, frac_sum),
        "p_diff_dbm": _dbm(p_diff_mw, frac_diff),
        "frac_sum": round(frac_sum, 15),
        "frac_diff": round(frac_diff, 15),
        "conservation_residual": round(conserv_resid, 18),
        "dominant_port": dominant,
        "isolation_null": bool(isolation_null),
        "note": (
            "幅度口径 a=√P_mW（功率波归一）；null 口径 |b|²<1e-24·P_tot 记"
            "隔离 null（等幅同相/反相的理想零在浮点下如实给 None dBm）；"
            "中间相位分布连续内插不夹持；只覆盖理想匹配魔 T 口径（实测器件"
            "隔离度/幅度平衡按实测 S 另行判读）"),
        "source": _SOURCES["sum_diff"],
    }
