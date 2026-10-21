"""DGS 缺陷接地结构族（架构批 W2-S2 席域 C3，R2_core_tier4 §③ Top5 设计案）。

出处（文献族口径+第一性推导，详见下节物理口径）：
- dgs_dumbbell_lc_extract：哑铃 DGS 一阶 LC 等效（Lim/Ahn IEEE MTT
  2000-2002 文献族等效电路口径；本族两条提取条件从第一性推导不逐字
  转抄——文献原文页码级复读未做，如实登记 UNVERIFIED）。
- dgs_notch_response：一阶 LC 陷波/低通响应再生（同上等效电路构造
  恒等式，#118 锚树 tests/unit/test_w2s2_core_tier4.py）。

两键：dgs_dumbbell_lc_extract（哑铃形 DGS 一阶 LC 等效提取：EM 响应的
陷波频率 f0 与 3dB 截止 fc → 等效 L/C 反演闭式）/ dgs_notch_response
（LC → 缺陷地面陷波/低通响应再生：|S21| 逐频闭式）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``defected.?ground|\\bDGS\\b`` 在 src/tests/scripts 三面全零（R2 §② 方向 1
判据原文复跑零命中）——全仓唯一剩余 PCB 器件零命中域之一，本族首批键。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_w2s2_core_tier4.py）
--------------------------------------------------------
哑铃形 DGS（dumbbell DGS：地面两个矩形缺陷经窄连接槽缝串联）在微带线下
呈一阶低通带陷波响应，文献通行等效电路=**传输线并联支路上的串联回路**
（L=连接槽缝电感、C=哑铃矩形边缘电容；Lim/Ahn IEEE MTT 2000-2002 文献
族口径）。本族从第一性推导两条提取条件（不逐字转抄文献公式，#1c 禁凭
记忆写式；文献原文页码级复读未做，如实登记 UNVERIFIED——同
circulator_synthesis Wu-Rosenbaum 先例口径，锚树以构造恒等式自洽裁判）：

  并联支路阻抗  Z_g(jω) = jX(ω)，X(ω) = ωL − 1/(ωC)

  ① 陷波（全反射）条件：X(ω0) = 0 ⇔ ω0 = 1/√(LC)
  ② 3dB 截止条件：并联电抗 |X(ωc)| = Z0/2
     —— 由无损并联元件的传输式 |S21|² = 4X²/(Z0²+4X²) 令 =1/2 解出

  联立（X(ωc) = ωc·L − 1/(ωc·C) 代入 L=1/(ω0²C)）：

      C = 2(ω0² − ωc²)/(Z0·ω0²·ωc) = (2/(Z0·ωc))·(1 − (ωc/ω0)²)
      L = 1/(ω0²·C) = Z0·ωc/(2(ω0² − ωc²))

  自洽性：ω0 > ωc（陷波在截止之上）时 C>0、L>0 恒成立；f0 ≤ f3db 时
  支路呈感性无低通语义 → 显式拒绝。量级自检：2.4GHz 陷波/1.8GHz 截止
  /50Ω → C≈1.55pF、L≈2.84nH（文献哑铃 DGS 典型 pF/nH 量级一致）。

响应再生（同文件双路径，#118）：|S21(f)| = 2|X|/√(Z0²+4X²)，
X(f)=2πfL − 1/(2πfC)。低频极限 X→−∞ → |S21|→1（C 隔直直通）；f=f0 →
X=0 → 全陷波；f=fc → −3.0102999dB（构造恒等式）。f>f0 频段支路转感性
|S21| 回升——一阶模型不带辐射/表面波损耗面，陷波上方回升是模型真实
行为（如实注记，不冒充宽带低通）。dB 输出对理想全陷波（X 精确为 0）
取 −300dB 地板+below_floor 旗标（JSON 严格序列化禁 inf，信封契约）。

边界防撞（#222）
--------------------------------------------------------
- vendor_passives=器件级 RLC（磁珠/电容 ESR 模型）——本族=地面缺陷结构
  等效，非分立器件不并入；
- homogenization=等效介质参数化（体超材料）、amc_mushroom=表面型 EBG
  （Sievenpiper 各向异性表面阻抗）——DGS 为离散地面缺陷单元不并入；
- crlh=周期 LH/RH 单元阵列（色散/Bloch 面）——DGS 为单缺陷陷波器非
  周期阵列不并入；
- 慢波效应（DGS 加载线的等效相位延迟增大）=单键外的等效面，R2 §③ C3
  预声明"登记不建模"——慢波等效电长度=加载线逐缺陷级联的相位积分面，
  非本族一阶 LC 口径，如实留白不凑键。

几何→LC 的经验拟合式（哑铃边长/槽缝宽 → L/C 的文献拟合族）不做（#1c
禁凭记忆写经验常数；UNVERIFIED 余量待文献原文复读后另批）——本族只做
(f0, fc)→(L, C) 反演闭式与响应再生，几何面由调用方以 EM 提取 f0/fc
供给（真机仲裁链）。

数值锚（#118 独立来源；锚树 tests/unit/test_w2s2_core_tier4.py）
--------------------------------------------------------
- (2.4GHz, 1.8GHz, 50Ω) → C=1.5473pF、L=2.8421nH（独立算术复算逐位）；
- X(ωc) = −Z0/2 精确（3dB 条件回代恒等式）；|S21(fc)| = −3.0102999dB；
- X(ω0) ≈ 0（1e-14 机器尘）→ 陷波；ω0² = 1/(LC) 回代残差 ~1e-16；
- 低频 |S21|→1、无耗 |S21|≤1 全扫描、单调下降（f<fc 段）。

守卫：f0_ghz/f3db_ghz/z0_ohm>0 且 f0>f3db；l_nh/c_pf>0；freq_ghz 列表
非空且全>0；bool 入参显式拒收（_finite_nb，fec_codes._as_int 同族先例）。

接口：纯函数零 IO；math 为主；全部返回 JSON 可序列化结构（浮点/字符串/
bool/None；数值 0.0 合法，判缺失一律 is not None，禁 ``or 缺省``，
#364④）。无 ``__all__``（公开 API 快照口径，waveguide_iris 先例）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

#: dB 地板：理想全陷波（X 精确 0）的显示下限（JSON 严格序列化禁 inf）
_DB_FLOOR = -300.0


def _finite_nb(value: Any, name: str) -> float:
    """有限数收敛（bool 显式拒收版，全模块键面入参走此）——
    ``float(True)=1.0`` 静默污染面（W3-S1 审查 P3-2：原声明"自然拒收"
    失实），对齐 fec_codes._as_int 显式 bool 拒绝先例（df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染）")
    return _finite(value, name)


def _branch_reactance(f_hz: float, l_h: float, c_f: float) -> float:
    """并联支路电抗 X(ω)=ωL−1/(ωC)（Ω；串联回路面单源）。"""
    w = 2.0 * math.pi * f_hz
    return w * l_h - 1.0 / (w * c_f)


def _s21_from_x(x_ohm: float, z0_ohm: float) -> tuple[float, float]:
    """并联电抗 X → (|S21| 线性, dB)；X=0 精确全陷波走 dB 地板档。

    |S21| = 2|X|/√(Z0²+4X²)（无损并联元件传输式；X→±∞ 与 X=0 双极限
    均在量内）。dB=20lg(|S21|)；|S21|=0 时（JSON 禁 inf）取地板 −300dB
    并以返回第三元 below_floor 旗标如实标注。
    """
    s21 = 2.0 * abs(x_ohm) / math.sqrt(z0_ohm * z0_ohm + 4.0 * x_ohm ** 2)
    if s21 <= 0.0:
        return 0.0, _DB_FLOOR
    return s21, max(_DB_FLOOR, 20.0 * math.log10(s21))


@register_calculator(
    "dgs_dumbbell_lc_extract",
    "DGS 哑铃缺陷接地结构等效 LC 提取：陷波频率 f0 与 3dB 截止 fc → 并联"
    "串联回路等效 L/C 反演闭式——两条件 X(ω0)=0（陷波）与 |X(ωc)|=Z0/2"
    "（3dB：|S21|²=4X²/(Z0²+4X²)=1/2 解出）联立 C=2(ω0²−ωc²)/(Z0ω0²ωc)、"
    "L=Z0ωc/(2(ω0²−ωc²))（第一性推导，文献族 Lim/Ahn IEEE MTT 2000-2002"
    " 口径 UNVERIFIED 如实预声明）；ω0²=1/(LC) 与 X(ωc)=−Z0/2 回代残差随"
    "输出自检；f0≤f3db 显式拒绝（支路转感性无低通语义）",
    (("f0_ghz", "float GHz 陷波（全反射）频率（>f3db_ghz）"),
     ("f3db_ghz", "float GHz 3dB 截止频率（>0）"),
     ("z0_ohm", "float Ω 参考阻抗（>0，缺省 50）")),
    required=("f0_ghz", "f3db_ghz"),
)
def dgs_dumbbell_lc_extract(f0_ghz: float, f3db_ghz: float,
                            z0_ohm: float = 50.0) -> dict[str, Any]:
    tag = "dgs_dumbbell_lc_extract"
    f0 = _finite_nb(f0_ghz, f"{tag}.f0_ghz") * 1.0e9
    fc = _finite_nb(f3db_ghz, f"{tag}.f3db_ghz") * 1.0e9
    z0 = _finite_nb(z0_ohm, f"{tag}.z0_ohm")
    if f0 <= 0.0:
        raise ValueError(f"{tag}: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    if fc <= 0.0:
        raise ValueError(f"{tag}: f3db_ghz 必须 >0，得到 {f3db_ghz!r}")
    if z0 <= 0.0:
        raise ValueError(f"{tag}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    if f0 <= fc:
        raise ValueError(
            f"{tag}: f0_ghz={f0_ghz!r} 必须 >f3db_ghz={f3db_ghz!r}"
            "（陷波在截止之上；f0≤fc 时支路在截止处已呈感性、无低通语义"
            "——模型不一致显式拒绝）")
    w0 = 2.0 * math.pi * f0
    wc = 2.0 * math.pi * fc
    c_f = 2.0 * (w0 * w0 - wc * wc) / (z0 * w0 * w0 * wc)
    l_h = 1.0 / (w0 * w0 * c_f)
    # 构造级回代残差（解的两条条件恒等式）
    lc_residual = abs(1.0 / (l_h * c_f) - w0 * w0)
    xc = _branch_reactance(fc, l_h, c_f)
    x3db_residual = abs(abs(xc) - z0 / 2.0)
    s21_fc, s21_fc_db = _s21_from_x(xc, z0)
    return {
        "f0_ghz": round(f0 / 1.0e9, 12),
        "f3db_ghz": round(fc / 1.0e9, 12),
        "z0_ohm": z0,
        "l_nh": round(l_h * 1.0e9, 12),
        "c_pf": round(c_f * 1.0e12, 12),
        "x_at_f3db_ohm": round(xc, 12),
        "s21_at_f3db": round(s21_fc, 12),
        "s21_at_f3db_db": round(s21_fc_db, 9),
        "lc_residual_rad_s": round(lc_residual, 3),
        "x3db_residual_ohm": round(x3db_residual, 12),
        "note": (
            "哑铃 DGS 一阶等效=线并联串联回路（L=连接槽缝电感、C=哑铃矩"
            "形边缘电容）；低频段支路呈容性=并联电容低通面，f0 处串联谐"
            "振全陷波。f0≤f3db 显式拒绝。几何→LC 的文献经验拟合式不在口"
            "径（#1c 禁凭记忆写经验常数）——f0/fc 由调用方 EM 提取供给；"
            "文献公式原文页码级复读未做，UNVERIFIED 如实登记"),
        "source": (
            "第一性推导（陷波+3dB 两条件联立，见模块 docstring 物理口径"
            "节）；文献族口径 Lim/Ahn et al., IEEE Trans. MTT 2000-2002"
            "（哑铃 DGS 等效电路），UNVERIFIED 如实预声明"),
    }


@register_calculator(
    "dgs_notch_response",
    "DGS 等效 LC 陷波/低通响应再生：|S21(f)|=2|X|/√(Z0²+4X²)、"
    "X(f)=2πfL−1/(2πfC) 逐频闭式（无损并联元件传输式）——低频直通/"
    "f0 串联谐振全陷波/fc 处 −3.0103dB 构造恒等式；与 dgs_dumbbell_lc_"
    "extract 同文件双路径（extract→response roundtrip，#118）；理想全"
    "陷波 dB 取 −300 地板+below_floor 旗标（JSON 禁 inf）",
    (("l_nh", "float nH 等效电感（>0）"),
     ("c_pf", "float pF 等效电容（>0）"),
     ("freq_ghz", "float|list GHz 分析频率或频率列表（全>0）"),
     ("z0_ohm", "float Ω 参考阻抗（>0，缺省 50）")),
    required=("l_nh", "c_pf", "freq_ghz"),
)
def dgs_notch_response(l_nh: float, c_pf: float,
                       freq_ghz: float | list[float],
                       z0_ohm: float = 50.0) -> dict[str, Any]:
    tag = "dgs_notch_response"
    l_h = _finite_nb(l_nh, f"{tag}.l_nh") * 1.0e-9
    c_f = _finite_nb(c_pf, f"{tag}.c_pf") * 1.0e-12
    z0 = _finite_nb(z0_ohm, f"{tag}.z0_ohm")
    if l_h <= 0.0:
        raise ValueError(f"{tag}: l_nh 必须 >0，得到 {l_nh!r}")
    if c_f <= 0.0:
        raise ValueError(f"{tag}: c_pf 必须 >0，得到 {c_pf!r}")
    if z0 <= 0.0:
        raise ValueError(f"{tag}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    f_list = [freq_ghz] if isinstance(freq_ghz, (int, float)) else list(
        freq_ghz)
    if not f_list:
        raise ValueError(f"{tag}: freq_ghz 至少一个频点")
    points: list[dict[str, Any]] = []
    s21_max = 0.0
    for i, f_in in enumerate(f_list):
        f_ghz = _finite_nb(f_in, f"{tag}.freq_ghz[{i}]")
        if f_ghz <= 0.0:
            raise ValueError(
                f"{tag}: freq_ghz[{i}] 必须 >0，得到 {f_in!r}")
        x = _branch_reactance(f_ghz * 1.0e9, l_h, c_f)
        s21, s21_db = _s21_from_x(x, z0)
        s21_max = max(s21_max, s21)
        points.append({
            "freq_ghz": round(f_ghz, 12),
            "x_ohm": round(x, 12),
            "s21_mag": round(s21, 15),
            "s21_db": round(s21_db, 9),
            "below_floor": s21 <= 0.0,
        })
    return {
        "l_nh": round(l_h * 1.0e9, 12),
        "c_pf": round(c_f * 1.0e12, 12),
        "z0_ohm": z0,
        "f_resonance_ghz": round(1.0 / (2.0 * math.pi
                                        * math.sqrt(l_h * c_f)) / 1.0e9, 12),
        "points": points,
        "passive": bool(s21_max <= 1.0 + 1e-12),
        "note": (
            "无损并联串联回路面：低频 C 隔直直通→f0 串联谐振全陷波→"
            "f0 上方支路转感性 |S21| 回升（一阶模型真实行为，不带辐射/"
            "表面波损耗面，不冒充宽带低通）；dB 地板 −300+below_floor "
            "旗标对应理想全陷波（X 精确 0，JSON 禁 inf）；passive=全点"
            " |S21|≤1 无耗恒等自检"),
        "source": (
            "无损并联元件传输式 |S21|²=4X²/(Z0²+4X²)（第一性，模块 "
            "docstring 物理口径节）；与 dgs_dumbbell_lc_extract 同文件"
            "双路径消费闭环"),
    }
