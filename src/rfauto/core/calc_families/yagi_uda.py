"""G15 Yagi-Uda 定向阵 NBS 实测设计面（批 B Wave3 W3-G15G16，2026-10-13）。

两键：yagi_gain_nbs_tn688（增益-boom 长度阶梯：六档实测锚线性插值）/
yagi_geometry_nbs_tn688（标准档几何骨架：单元数/间距/已验证长度+米制
位置）。**经验数据面键**（NBS 建模测量阶梯，非闭式推导）——experimental
定性如实，插值档显式标注非实测点。

边界防撞（规格包 §0）
----------------------------------------------
仓内既有天线面不并入：dipole_emf_zin/folded_dipole_zin/small_loop_zin
（linear_antenna_zin.py，单元输入阻抗端）、array.schelkunoff_nulls 等
阵列综合键、reflector_antenna（反射面闭式）、antenna_q（电小天线 Q）、
helix_axial（螺旋天线 Kraus 口径）。本族只做 Yagi-Uda 定向阵的 NBS
实测设计面（增益阶梯+几何骨架）；有源折合偶极馈电阻抗走 folded_dipole_zin
语义。

法源（唯一锚源=原文公开 PDF，2026-10-13 免费抓取逐字提取）
----------------------------------------------
- P. P. Viezbicke, Yagi Antenna Design, NBS Technical Note 688, December
  1976（美国国家标准局技术笔记，美国政府作品 public domain；
  https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote688.pdf，
  36 页；§4 六档增益阶梯/例题 1（0.8λ@50.1MHz）/例题 2（4.2λ@827MHz）/
  Fig.13-19 图注逐字提取在案；教材转引=Balanis *Antenna Theory* §10.3.3
  Table 10.5/10.6 系本笔记 Table 1/Fig.9 数字化同源）。
  access_status=verified（原文免费可达）。
- 测量基准口径（docstring 写死）：400 MHz 模型测量、0.63 cm（1/4 in）
  铝管阵元、半波折合偶极有源元、增益相对同高度半波偶极（**dBd 口径**）、
  地面 3λ 高非导电支杆；dBi 换算恒等式 G_dBi = G_dBd + 2.15（半波偶极
  2.15 dBi 教科书常数，与 dipole_emf_zin 同仓互证）。
- 锚（#118）：规格包 §② B1-B8 文本级验证值（实现席 2026-10-13 复算例题
  恒等确认：λ(50.1MHz)=5.98388 m → 0.490λ=293.2 cm vs 原文 293、
  0.447λ=267.5 cm vs 原文 267（±0.003λ 截断容差内）；λ(827MHz)=36.25 cm
  → 0.308λ=11.17 cm vs 原文 11.2、4.2λ=152.25 cm vs 原文 152）；锚树
  tests/unit/test_b_wave3_yagi_slot.py。

不放键的面（登记续作，禁编造）：Table 1 全表数字化（36 页扫描表格 OCR
损坏，Balanis 转引表待有书补）、boom 修正图 Fig.10 全曲线（仅例题单点
D/λ=0.0085→+0.005λ 文本验证）、stacking 增益（Fig.11/12 曲线数字化）、
DL6WU 等民间经验式（无正式出处锚）、E/H 波束宽（仅 §3.6 两档文本值，
不进键面）。

守卫：boom_length_lambda ∈ [0.4, 4.2] λ（端点恰值=实测档 interpolated=
False；域外拒绝不外推——经验表外推无意义）；class_lambda 六档封闭枚举
（其他值显式拒绝）；f_ghz>0；element_d_lambda>0（合理域 0.001..0.05，
越域 warnings 注记不拒绝——TN688 Fig.9 域外不可靠如实声明）。数值 0.0
合法面判缺失一律 is not None（#364④）。
"""

from __future__ import annotations

from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

#: 六档 boom 长度锚（λ；TN688 §4 p.16 逐字）
_ANCHOR_BOOMS: tuple[float, ...] = (0.4, 0.8, 1.2, 2.2, 3.2, 4.2)

#: 六档增益锚（dBd；同上：「the 0.4, 0.8, 1.2, 2.2, 3.2 and 4.2λ long
#: Yagis that yield gains of 7.1, 9.2, 10.2, 12.3, 13.4 and 14.2 dB」）
_ANCHOR_GAINS_DBD: tuple[float, ...] = (7.1, 9.2, 10.2, 12.3, 13.4, 14.2)

#: dBd→dBi 恒等换算（半波偶极 2.15 dBi 教科书常数）
_DBD_TO_DBI = 2.15

#: 档位单元数（Fig.13-19 图注/pattern 页标题逐字：B7）
_ANCHOR_N_ELEMENTS = {
    0.4: 3,
    0.8: 5,
    1.2: 6,
    2.2: 12,
    3.2: 17,
    4.2: 15,
}

#: 反射器间距（λ；Fig.1 实测最优口径——偶极+反射器 0.2λ 间距实测增益峰
#: 2.6 dBd，§3.1 逐字）
_REFLECTOR_SPACING_LAMBDA = 0.2

#: 已文本验证的档位指向元间距（λ）：0.8λ 档工作例（Fig.8 口径 S=0.2λ）、
#: 4.2λ 档例题 2 GIVEN 块（0.308λ）；其余四档不在文本验证面——null 如实
_DIRECTOR_SPACING_LAMBDA = {
    0.8: 0.2,
    4.2: 0.308,
}

#: 仅 0.8λ 档例题验证的未补偿长度（λ；例题 1 Step2 d/λ=0.0042 路线：
#: LR=0.485、D=0.442）与 boom 修正单点（D/λ=0.0085 → +0.005λ；Fig.10
#: 全曲线未数字化不外推）→ 修正后 LR=0.490（=293 cm@50.1MHz）、
#: L=0.447（=267 cm）
_verified_lengths_08 = {
    "reflector_length_lambda": 0.485,
    "director_length_lambda": 0.442,
    "boom_correction_lambda": 0.005,
    "reflector_length_corrected_lambda": 0.490,
    "director_length_corrected_lambda": 0.447,
}

#: element_d_lambda 合理域（TN688 Fig.9 域外不可靠；越域注记不拒绝）
_D_LAMBDA_LO, _D_LAMBDA_HI = 0.001, 0.05

#: TN688 基准单元直径比（0.25 in @400 MHz → d/λ=0.0085）
_BASELINE_D_LAMBDA = 0.0085

_SOURCES = {
    "gain": (
        "Viezbicke, Yagi Antenna Design, NBS Technical Note 688 (Dec 1976),"
        " §4 p.16 六档增益阶梯逐字（美国政府作品 public domain，"
        "https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote688.pdf"
        "）；dBd 口径=相对同高度半波偶极，dBi=G_dBd+2.15 恒等式；教材转引 "
        "Balanis Antenna Theory §10.3.3（Table 10.5 同源）。NBS 400MHz "
        "建模测量经验面——非闭式推导，档间线性插值如实标注非实测点"),
    "geometry": (
        "Viezbicke, NBS Technical Note 688 (Dec 1976)：单元数=Fig.13-19 "
        "图注逐字（B7）；反射器间距 0.2λ=§3.1/Fig.1 实测最优（峰 2.6 dBd）；"
        "0.8λ 档长度 0.485/0.442+boom 修正单点 +0.005λ=例题 1（p.17）逐字；"
        "4.2λ 档间距 0.308λ=例题 2（p.19）GIVEN 块逐字；原文 "
        "https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote688.pdf"),
}


def _gain_dbd_at_anchor(index: int) -> float:
    """档位实测增益（dBd，六档表内直读；键 1/键 2 同源单一实现点）。"""
    return _ANCHOR_GAINS_DBD[index]


def _gain_row(boom_length_lambda: float) -> tuple[float, bool, float]:
    """阶梯插值单一实现点：→(gain_dbd, interpolated, class_lambda)。

    六档间对 boom 长度线性插值（经验面无解析曲率依据——对数曲率等均属
    编造，如实线性+标注）；端点恰值=实测档 interpolated=False；域外拒绝。
    """
    boom = boom_length_lambda
    if not _ANCHOR_BOOMS[0] <= boom <= _ANCHOR_BOOMS[-1]:
        raise ValueError(
            "yagi_gain_nbs_tn688: boom_length_lambda 必须 ∈ [0.4, 4.2] λ"
            f"（TN688 六档实测域，域外不外推——经验表外推无意义），得到 "
            f"{boom_length_lambda!r}")
    for i, anchor in enumerate(_ANCHOR_BOOMS):
        if boom == anchor:
            return _gain_dbd_at_anchor(i), False, anchor
    for i in range(len(_ANCHOR_BOOMS) - 1):
        lo, hi = _ANCHOR_BOOMS[i], _ANCHOR_BOOMS[i + 1]
        if lo < boom < hi:
            frac = (boom - lo) / (hi - lo)
            g = (_gain_dbd_at_anchor(i) * (1.0 - frac)
                 + _gain_dbd_at_anchor(i + 1) * frac)
            # class=最近标准档（恰中点取低档：min 首见语义）
            cls = min(_ANCHOR_BOOMS, key=lambda c: (abs(boom - c), c))
            return g, True, cls
    raise AssertionError("unreachable: 域检查与档间搜索覆盖不全")


@register_calculator(
    "yagi_gain_nbs_tn688",
    "Yagi 增益阶梯（NBS TN688）：boom 总长 λ∈[0.4,4.2] → 增益 dBd/dBi"
    "（六档实测锚 7.1/9.2/10.2/12.3/13.4/14.2 dBd 线性插值，插值档如实"
    "标注非实测点；dBd 相对半波偶极，dBi=+2.15 恒等）；附最近标准档类与"
    "NBS 400MHz 建模测量口径注记——经验面非闭式",
    (("boom_length_lambda", "float λ boom 总长（0.4≤L≤4.2，端点恰值=实测"
      "档；域外拒绝不外推）"),
     ("output", "str 输出选择（\"dbd\"/\"dbi\"/\"both\"，缺省 \"both\""
      "双输出；单选时另一口径返 null）")),
    required=("boom_length_lambda",),
)
def yagi_gain_nbs_tn688(
    boom_length_lambda: float,
    output: str = "both",
) -> dict[str, Any]:
    """增益阶梯：boom 长度 → dBd/dBi（六档实测锚，档间线性插值）。"""
    L = _finite(boom_length_lambda, "boom_length_lambda")
    if output not in ("dbd", "dbi", "both"):
        raise ValueError(
            "yagi_gain_nbs_tn688: output 必须 ∈ {\"dbd\", \"dbi\", "
            f"\"both\"}}，得到 {output!r}")

    gain_dbd, interpolated, cls = _gain_row(L)
    gain_dbi = gain_dbd + _DBD_TO_DBI
    return {
        "gain_dbd": gain_dbd if output in ("dbd", "both") else None,
        "gain_dbi": gain_dbi if output in ("dbi", "both") else None,
        "class_lambda": cls,
        "interpolated": interpolated,
        "gain_output": output,
        "note": (
            "NBS TN688 400MHz 建模测量口径：0.63cm（1/4in）铝管阵元、半波"
            "折合偶极有源元、增益相对同高度半波偶极（dBd）、地面 3λ 高非"
            "导电支杆；六档实测锚 0.4/0.8/1.2/2.2/3.2/4.2λ → "
            "7.1/9.2/10.2/12.3/13.4/14.2 dBd（§4 逐字）；"
            + ("当前值落在六档之间=线性插值档，**非实测点**（经验面无解析"
               "曲率依据，对 boom 长度线性如实声明）" if interpolated else
               "当前值=实测档（interpolated=False）")
            + "；NBS 实测经验面非闭式推导"),
        "source": _SOURCES["gain"],
    }


@register_calculator(
    "yagi_geometry_nbs_tn688",
    "Yagi 档位几何（NBS TN688）：六档（0.4/0.8/1.2/2.2/3.2/4.2λ）封闭"
    "枚举 → 单元数（3/5/6/12/17/15）/反射器间距 0.2λ/已文本验证的指向元"
    "间距（0.8λ 档 0.2λ、4.2λ 档 0.308λ，其余 null 如实注记禁编造）+"
    "0.8λ 档例题长度（未补偿 0.485/0.442+修正单点 0.490/0.447）+f_ghz "
    "米制缩放位置（有源元原点/反射器 −0.2λ/指向元等距）",
    (("class_lambda", "float λ 标准档（0.4/0.8/1.2/2.2/3.2/4.2 六档封闭"
      "枚举，其他值显式拒绝）"),
     ("f_ghz", "float GHz 工作频率（>0，几何米制缩放用）"),
     ("element_d_lambda", "float d/λ 阵元直径比（>0，缺省 0.0085=TN688 "
      "基准 0.25in@400MHz；合理域 0.001..0.05 越域注记不拒绝）")),
    required=("class_lambda", "f_ghz"),
)
def yagi_geometry_nbs_tn688(
    class_lambda: float,
    f_ghz: float,
    element_d_lambda: float = _BASELINE_D_LAMBDA,
) -> dict[str, Any]:
    """标准档几何骨架（仅文本验证子集；未验证档 null+注记禁编造）。"""
    cls = _finite(class_lambda, "class_lambda")
    f = _finite(f_ghz, "f_ghz")
    d_lam = _finite(element_d_lambda, "element_d_lambda")
    if f <= 0.0:
        raise ValueError(
            f"yagi_geometry_nbs_tn688: f_ghz 必须 >0，得到 {f_ghz!r}")
    if d_lam <= 0.0:
        raise ValueError(
            f"yagi_geometry_nbs_tn688: element_d_lambda 必须 >0，得到 "
            f"{element_d_lambda!r}")
    if cls not in _ANCHOR_N_ELEMENTS:
        raise ValueError(
            f"yagi_geometry_nbs_tn688: class_lambda 须为六档封闭枚举 "
            f"{list(_ANCHOR_N_ELEMENTS)}（其他档位无文本验证锚，显式拒绝"
            f"不插值不编造），得到 {class_lambda!r}")

    warnings: list[str] = []
    if not _D_LAMBDA_LO <= d_lam <= _D_LAMBDA_HI:
        warnings.append(
            f"element_d_lambda={d_lam!r} 出 TN688 合理域 "
            f"[{_D_LAMBDA_LO}, {_D_LAMBDA_HI}]（Fig.9 域外设计曲线不可靠，"
            "数值照给如实标注")

    idx = _ANCHOR_BOOMS.index(cls)
    gain_dbd = _gain_dbd_at_anchor(idx)
    n_elements = _ANCHOR_N_ELEMENTS[cls]
    dir_spacing = _DIRECTOR_SPACING_LAMBDA.get(cls)

    lam_m = C_MM_GHZ / f / 1000.0  # m（C_MM_GHZ=mm·GHz → /1000）
    reflector_m = -_REFLECTOR_SPACING_LAMBDA * lam_m
    if dir_spacing is not None:
        n_directors = n_elements - 2
        positions: dict[str, Any] = {
            "reflector_m": reflector_m,
            "driven_m": 0.0,
            "directors_m": [dir_spacing * lam_m * (i + 1)
                            for i in range(n_directors)],
            "lambda_m": lam_m,
        }
    else:
        positions = None

    if cls == 0.8:
        lengths = dict(_verified_lengths_08)
        if d_lam == _BASELINE_D_LAMBDA:
            boom_corr: float | None = lengths["boom_correction_lambda"]
            refl_corr: float | None = (
                lengths["reflector_length_corrected_lambda"])
            dir_corr: float | None = (
                lengths["director_length_corrected_lambda"])
        else:
            boom_corr = refl_corr = dir_corr = None
            warnings.append(
                f"element_d_lambda={d_lam!r} ≠ TN688 基准 "
                f"{_BASELINE_D_LAMBDA}（0.25in@400MHz）：boom 修正仅 "
                "0.0085→+0.005λ 例题单点文本验证（Fig.10 全曲线未数字化），"
                "修正值返 null 不外推")
    else:
        lengths = {
            "reflector_length_lambda": None,
            "director_length_lambda": None,
        }
        boom_corr = refl_corr = dir_corr = None

    return {
        "class_lambda": cls,
        "n_elements": n_elements,
        "reflector_spacing_lambda": _REFLECTOR_SPACING_LAMBDA,
        "director_spacing_lambda": dir_spacing,
        "gain_dbd": gain_dbd,
        "gain_dbi": gain_dbd + _DBD_TO_DBI,
        "reflector_length_lambda": lengths["reflector_length_lambda"],
        "director_length_lambda": lengths["director_length_lambda"],
        "boom_correction_lambda": boom_corr,
        "reflector_length_corrected_lambda": refl_corr,
        "director_length_corrected_lambda": dir_corr,
        "element_positions_m": positions,
        "lambda_m": lam_m,
        "note": (
            "NBS TN688 实测经验面（400MHz 建模测量，dBd 口径）；单元数="
            "Fig.13-19 图注逐字；反射器间距 0.2λ=§3.1/Fig.1 实测最优口径"
            "（偶极+反射器 0.2λ 间距实测增益峰 2.6 dBd）；指向元间距仅 "
            "0.8λ 档（0.2λ 工作例）与 4.2λ 档（0.308λ 例题 2：λ=36.25cm、"
            "总长 4.2λ=152cm、未补偿 D1=0.414λ）文本验证，其余四档无验证"
            "锚返 null 禁编造；长度/修正仅 0.8λ 档例题 1 文本验证（未补偿 "
            "LR=0.485/D=0.442；boom 修正单点 D/λ=0.0085→+0.005λ → "
            "0.490λ=293cm/0.447λ=267cm@50.1MHz，例题印值 264.5cm 系未修正"
            "第二指向元 L2 原文逐字）；波束宽（B8：0.4λ 档 57°/72°、0.8λ "
            "档 48°/56°、F/B 15dB）不在键面；NBS 实测经验面非闭式推导，"
            "与全波解偏差 1-2dB 属预期（helix_axial 同口径诚实边界）"),
        "warnings": warnings,
        "source": _SOURCES["geometry"],
    }
