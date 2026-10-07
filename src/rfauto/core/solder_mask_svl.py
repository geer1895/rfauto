"""F-J.3 阻焊层（solder mask）三层介质填充因子闭式（Svacina 框架）。

权威口径：J. Svacina, "Analysis of multilayer microstrip lines by a
conformal mapping method", IEEE Trans. Microwave Theory Tech., 40(4):
769-772, Apr. 1992（IEEE 付费墙，本仓未购）——**框架**经二手可达来源
核对：εeff = 1 + Σᵢ qᵢ·(εr,ᵢ − 1)，qᵢ 为第 i 层填充因子（该层映射场能
占比），qᵢ 只依赖几何、与各层 εr 取值无关（Svacina 共形映射核心性质；
二手：Microstrip Lines and Slotlines 4th ed. §7 multilayer 节 Eq.7.46-
7.50 转述、Getsinger 修正文献对 Svacina q 的引用）。

**UNVERIFIED 清单（如实登记，#118 不虚构）**：
- Svacina 原文 q 的逐系数闭式（映射椭圆积分参数化）付费墙不可达，本仓
  未逐系数对原文——q_sub 锚定在**标准单层微带 HJ 闭式**上（见下），
  q_mask 用"上域映射高度线性占比"近似（本仓实现约定，非原文系数）。
- CPW 顶覆盖延拓（Ghione-Naldi 同族）原文献同样不可达——**只登记未实
  现**（CPW_GHIONE_NALDI_STATUS 常量），后续可达时再补。

单层锚（本模块全部退化的钉子，标准闭式、可与 skrf HJ 链对拍）：
- HJ 空气线 Z0_air(u) = (η0/2π)·ln[f(u)/u + √(1+(2/u)²)]，
  f(u) = 6 + (2π−6)·exp(−(30.666/u)^0.7528)；
- HJ 准静态 εeff(u,εr) = (εr+1)/2 + (εr−1)/2·(1+10/u)^(−a·b)，
  a = 1 + (1/49)·ln[(u⁴+(u/52)²)/(u⁴+0.432)] + (1/18.7)·ln[1+(u/18.1)³]，
  b = 0.564·((εr−0.9)/(εr+3))^0.053。
  来源：E. O. Hammerstad, F. Jensen, "Accurate Models for Microstrip
  Computer-Aided Design", IEEE MTT-S Dig. 1980, pp.407-409（教科书级
  广泛转述；与 core/synthesis.forward_z0 / core/calculators 的
  skrf MLine model='hammerstadjensen' 同一模型——单测互为独立裁判，
  逐系数已对 skrf.media.mline.hammerstad_er/ab/zl 源码核验）。

填充因子构造（几何域，与 εr 无关部分）：
- q_sub(u, εrs) = [εeff_HJ(u, εrs) − 1]/(εrs − 1)：下层（基板）映射
  场能占比——由单层 HJ 闭式反解，b(εr) 使其温和依赖 εrs（如实保留）。
- 上域占比 1 − q_sub(u, εrs) 分配给"掩膜+空气"上域（Wheeler 镜像域
  惯例：上域有效高度 = 2·hs，镜像地平面在 +2hs）。掩膜（厚 tm，贴条带
  上表面）在上域的映射高度线性占比 f = min(tm/(2hs), 1)（**本仓实现
  约定，UNVERIFIED 对原文**；保角映射只保局部长度，全局高度占比线性化
  是受控近似，tm→0 与 tm≥2hs 两端行为精确，中间为近似）。
- q_mask = f·(1 − q_sub)，q_air = 1 − q_sub − q_mask（逐位闭合）。

输出闭式（Svacina 框架直代）：
- εeff = 1 + q_sub·(εrs − 1) + q_mask·(εrm − 1)（加性恒等式，单测
  逐位钉：q_air·1 无贡献）；
- Z0 = Z0_air(u)/√εeff（准静态均匀线缩放，Svacina 同框架）。

硬判据（单测逐位/数值钉，见任务书 §判据）：
1. t_mask→0 ⟹ εeff 逐位退化为单层 HJ 闭式（分支短路实现）；
2. εr,mask=1 ⟹ 掩膜电学隐形，εeff 与 t_mask 无关（逐位）；
3. εeff 介于全空气（=1）与全阻焊上域饱和界（tm≥2hs）之间；εeff 对
   εrm、tm 单调增；Z0 反向单调；
4. 双路径：闭式直代 vs 电容网络装配（1/(c0·Z0) 电容口径重算）——
   rel ≤1e-6（同构异径代数核对；独立裁判是判据 1 的 skrf 对拍与
   判据 2/3 的恒等式，见模块头 #118 说明）。

开窗规则面与材料表：RF 焊盘/耦合缝/CPW 间隙禁阻焊（常量 dict + 判定
函数）；典型 LPI 阻焊材料 Dk/tanδ/厚度带常量（来源登记为 datasheet
典型值转述，**UNVERIFIED 未逐项对原文 datasheet**）。

接口：纯函数零 IO；非法输入显式 ValueError（w≤0/h≤0/tm<0/εr<1，
bool 显式拒收 df7+⑯）；判缺失一律 is not None（#364④）；
dataclass + to_dict()（JSON 可序列化）。不进 calculators 注册表。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "CPW_GHIONE_NALDI_STATUS",
    "MASK_OPENING_RULES",
    "SOLDER_MASK_MATERIALS",
    "SOLDER_MASK_TYPICAL_BANDS",
    "FillingFactors",
    "MaskedLineResult",
    "eps_eff_masked",
    "eps_eff_single_hj",
    "eps_eff_via_capacitance",
    "filling_factors",
    "requires_mask_open",
    "z0_air_hj",
    "z0_masked",
]

#: 真空波阻抗 [Ω]（CODATA 精确值 η0 = μ0·c0 推算值；与 metasurface_lut.ETA0_OHM 同值）
ETA0_OHM = 376.730313668
#: 真空光速 [m/s]（SI 精确定义）
C0_M_S = 299792458.0
#: 真空介电常数 [F/m]（CODATA 2018；与 metasurface_lut.EPS0_F_M 同值）
EPS0_F_M = 8.854187817e-12

#: CPW 顶覆盖延拓（Ghione-Naldi 同族口径）登记：原文献不可达，只登记未实现
CPW_GHIONE_NALDI_STATUS = "registered_not_implemented"

#: RF 特征开窗规则表：feature → (是否禁阻焊/必须开窗, 理由)。
#: 二手工程惯例口径（RF 设计指南族），**UNVERIFIED**（无单一权威文本）。
MASK_OPENING_RULES: dict[str, tuple[bool, str]] = {
    "rf_pad": (True, "RF 焊盘覆阻焊引入并联电容/击穿风险，惯例开窗"),
    "coupled_gap": (True, "耦合缝覆阻焊改变偶奇模比例（εr 加载不对称），惯例开窗"),
    "cpw_gap": (True, "CPW 间隙是主储能区，覆阻焊直接拉低 Z0，惯例开窗"),
    "antenna_radiating_edge": (True, "辐射边覆阻焊牵引谐振频移，惯例开窗"),
    "ground_pour": (False, "地皮覆阻焊无射频语义（防腐蚀常规受益）"),
    "thermal_relief": (False, "热焊盘按工艺能力覆/开均可，非 RF 约束"),
    "dc_trace": (False, "直流走线覆阻焊（默认工艺）"),
}


def requires_mask_open(feature: str) -> bool:
    """判定该 feature 是否禁阻焊/必须开窗。未知 feature 显式 ValueError。"""
    if feature is None or not isinstance(feature, str):
        raise ValueError(f"feature 必须为 str，收到 {feature!r}")
    if feature not in MASK_OPENING_RULES:
        raise ValueError(f"未知 feature={feature!r}（合法键：{sorted(MASK_OPENING_RULES)}）")
    return MASK_OPENING_RULES[feature][0]


#: 典型 LPI（液态感光）阻焊材料表：name → {dk, tan_d, thickness_um 带中心的典型厚}。
#: 来源：各家 datasheet 典型值二手转述（Taiyo/太阳 PSR 系列、EMD/AGP 系列口径），
#: **UNVERIFIED**：未逐项回对原文 datasheet，只作设计初值带参考（#118）。
SOLDER_MASK_MATERIALS: dict[str, dict[str, float]] = {
    "lpi_generic": {"dk": 3.5, "tan_d": 0.025, "thickness_um": 20.0},
    "lpi_low_dk": {"dk": 3.3, "tan_d": 0.020, "thickness_um": 15.0},
    "lpi_high_dk": {"dk": 3.8, "tan_d": 0.030, "thickness_um": 25.0},
}

#: 典型材料参数带（与 SOLDER_MASK_MATERIALS 联合校验，来源同上 UNVERIFIED）：
#: Dk 3.3-3.8 / tanδ 0.02-0.03 / 厚 12-25 µm（任务书口径）
SOLDER_MASK_TYPICAL_BANDS: dict[str, tuple[float, float]] = {
    "dk": (3.3, 3.8),
    "tan_d": (0.02, 0.03),
    "thickness_um": (12.0, 25.0),
}


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _permittivity(value: float, name: str) -> float:
    """介电常数收敛：有限且 ≥1（空气=1 合法，<1 非物理）。"""
    out = _finite(value, name)
    if out < 1.0:
        raise ValueError(f"{name} 必须 >=1（空气=1），收到 {out}")
    return out


# ─── 单层 HJ 锚（标准闭式）───────────────────────────────────────────────────


def z0_air_hj(w_mm: float, h_sub_mm: float) -> float:
    """Hammerstad-Jensen 空气线 Z0（Ω）；u = w/h。

    闭式见模块 docstring（Hammerstad & Jensen 1980）。与 skrf MLine
    model='hammerstadjensen'（ep_r=1、零损耗）同模型，单测互为裁判。
    """
    w = _positive(w_mm, "w_mm")
    h = _positive(h_sub_mm, "h_sub_mm")
    u = w / h
    f_u = 6.0 + (2.0 * math.pi - 6.0) * math.exp(-((30.666 / u) ** 0.7528))
    return ETA0_OHM / (2.0 * math.pi) * math.log(
        f_u / u + math.sqrt(1.0 + (2.0 / u) ** 2)
    )


def eps_eff_single_hj(w_mm: float, h_sub_mm: float, er_sub: float) -> float:
    """Hammerstad-Jensen 准静态单层微带 εeff（闭式，见模块 docstring）。

    (1+10/u)^(−a·b)：指数为 a·b 乘积（原文口径，已对 skrf
    hammerstad_er 源码逐系数核验——勿回退成 12/u 或分离指数的 1975
    简化形混入，df6⑬ 引文腐坏族）。
    """
    w = _positive(w_mm, "w_mm")
    h = _positive(h_sub_mm, "h_sub_mm")
    er = _permittivity(er_sub, "er_sub")
    u = w / h
    a = (
        1.0
        + (1.0 / 49.0) * math.log((u**4 + (u / 52.0) ** 2) / (u**4 + 0.432))
        + (1.0 / 18.7) * math.log(1.0 + (u / 18.1) ** 3)
    )
    b = 0.564 * ((er - 0.9) / (er + 3.0)) ** 0.053
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 10.0 / u) ** (-a * b)


# ─── 三层填充因子（Svacina 框架，本仓实现约定见 docstring UNVERIFIED）────────


@dataclass(frozen=True)
class FillingFactors:
    """三层填充因子（q_sub + q_mask + q_air == 1 逐位闭合）。

    q_sub：基板层映射场能占比（由单层 HJ εeff 反解，温和依赖 εrs）；
    q_mask：阻焊层占比（f_upper_mask·(1−q_sub)，f_upper_mask =
    min(tm/(2hs),1) 线性映射高度近似，UNVERIFIED 对 Svacina 原文）；
    q_air：空气占比。
    """

    q_sub: float
    q_mask: float
    q_air: float
    f_upper_mask: float

    def to_dict(self) -> dict:
        """JSON 可序列化 dict。"""
        return {
            "q_sub": float(self.q_sub),
            "q_mask": float(self.q_mask),
            "q_air": float(self.q_air),
            "f_upper_mask": float(self.f_upper_mask),
        }


def filling_factors(
    w_mm: float, h_sub_mm: float, t_mask_mm: float, er_sub: float
) -> FillingFactors:
    """三层（空气/阻焊/基板）填充因子。

    w_mm：线宽（mm，>0）；h_sub_mm：基板厚（mm，>0）；t_mask_mm：阻焊厚
    （mm，≥0；t_mask→0 ⟹ q_mask→0 逐位退化）；er_sub：基板 εr（≥1）。
    tm ≥ 2hs 时上域饱和为全阻焊（f_upper_mask 钳 1，docstring 约定）。
    """
    w = _positive(w_mm, "w_mm")
    h = _positive(h_sub_mm, "h_sub_mm")
    tm = _finite(t_mask_mm, "t_mask_mm")
    if tm < 0.0:
        raise ValueError(f"t_mask_mm 必须 >=0，收到 {tm}")
    er = _permittivity(er_sub, "er_sub")
    eps_single = eps_eff_single_hj(w, h, er)
    # εrs=1：单层退化为全空气，q_sub 按 (εeff−1)/(εr−1) 极限约定取 0
    # （避免 0/0；εr=1 时加性式对 q_sub 值不敏感——乘 (εr−1)=0）
    q_sub = 0.0 if er == 1.0 else (eps_single - 1.0) / (er - 1.0)
    f_mask = min(tm / (2.0 * h), 1.0)
    q_mask = f_mask * (1.0 - q_sub)
    return FillingFactors(q_sub=q_sub, q_mask=q_mask, q_air=1.0 - q_sub - q_mask, f_upper_mask=f_mask)


# ─── εeff / Z0 输出 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MaskedLineResult:
    """带阻焊微带线准静态结果（εeff/Z0/填充因子一体，JSON 面经 to_dict）。"""

    eps_eff: float
    z0_ohm: float
    filling: FillingFactors

    def to_dict(self) -> dict:
        """JSON 可序列化 dict。"""
        return {
            "eps_eff": float(self.eps_eff),
            "z0_ohm": float(self.z0_ohm),
            "filling": self.filling.to_dict(),
        }


def eps_eff_masked(
    w_mm: float, h_sub_mm: float, t_mask_mm: float, er_sub: float, er_mask: float
) -> float:
    """带阻焊三层微带 εeff（Svacina 框架直代；tm→0 逐位退化单层 HJ）。

    er_mask=1（阻焊换空气）⟹ 与 tm 无关、逐位等于单层值（加性式乘
    (εrm−1)=0）。tm≥2hs 时上域饱和（filling_factors 约定）。
    """
    w = _positive(w_mm, "w_mm")
    h = _positive(h_sub_mm, "h_sub_mm")
    tm = _finite(t_mask_mm, "t_mask_mm")
    if tm < 0.0:
        raise ValueError(f"t_mask_mm 必须 >=0，收到 {tm}")
    er_s = _permittivity(er_sub, "er_sub")
    er_m = _permittivity(er_mask, "er_mask")
    if tm == 0.0 or er_m == 1.0:
        return eps_eff_single_hj(w, h, er_s)  # 硬判据 1/2：逐位短路退化
    ff = filling_factors(w, h, tm, er_s)
    return 1.0 + ff.q_sub * (er_s - 1.0) + ff.q_mask * (er_m - 1.0)


def z0_masked(
    w_mm: float, h_sub_mm: float, t_mask_mm: float, er_sub: float, er_mask: float
) -> MaskedLineResult:
    """带阻焊微带 Z0 = Z0_air(u)/√εeff（准静态均匀线缩放）+ εeff + 填充因子。"""
    w = _positive(w_mm, "w_mm")
    h = _positive(h_sub_mm, "h_sub_mm")
    eps = eps_eff_masked(w, h, t_mask_mm, er_sub, er_mask)
    ff = filling_factors(w, h, t_mask_mm, er_sub)
    return MaskedLineResult(eps_eff=eps, z0_ohm=z0_air_hj(w, h) / math.sqrt(eps), filling=ff)


def eps_eff_via_capacitance(
    w_mm: float, h_sub_mm: float, t_mask_mm: float, er_sub: float, er_mask: float
) -> float:
    """双路径之 B：电容网络装配口径重算 εeff（与 eps_eff_masked 同构异径）。

    路径：先经 Z0_air 反解全线空气电容 C_air = 1/(c0·Z0_air)（阻抗口径），
    再按映射占比装配 C_config = ε0·[εrs·q_sub + εrm·q_mask + 1·q_air]·A_tot
    （A_tot = C_air/ε0，网络加法次序与闭式直代不同），εeff = C_config/C_air。
    内部代数核对路径（同构，抓代数滑手）；独立裁判是 eps_eff_single_hj
    对 skrf HJ 的对拍与 tm→0 逐位退化（#118，见模块 docstring）。
    """
    w = _positive(w_mm, "w_mm")
    h = _positive(h_sub_mm, "h_sub_mm")
    tm = _finite(t_mask_mm, "t_mask_mm")
    if tm < 0.0:
        raise ValueError(f"t_mask_mm 必须 >=0，收到 {tm}")
    er_s = _permittivity(er_sub, "er_sub")
    er_m = _permittivity(er_mask, "er_mask")
    if tm == 0.0 or er_m == 1.0:
        return eps_eff_single_hj(w, h, er_s)
    ff = filling_factors(w, h, tm, er_s)
    c_air_per_m = 1.0 / (C0_M_S * z0_air_hj(w, h))  # 均匀线 C = 1/(v·Z0)，v=c0（空气线）
    a_tot = c_air_per_m / EPS0_F_M  # 映射总纵横比
    c_lo = er_s * ff.q_sub * a_tot
    c_mask = er_m * ff.q_mask * a_tot
    c_up_air = ff.q_air * a_tot
    return (c_lo + c_mask + c_up_air) / (c_air_per_m / EPS0_F_M)


# ─── 开窗规则与材料表面 ──────────────────────────────────────────────────────


def opening_rules_to_dict() -> dict:
    """开窗规则表 JSON 面（feature → {required, reason}）。"""
    return {
        key: {"required": bool(val[0]), "reason": val[1]}
        for key, val in MASK_OPENING_RULES.items()
    }


def materials_to_dict() -> dict:
    """材料表 + 典型带 JSON 面（来源登记见常量注记，UNVERIFIED）。"""
    return {
        "materials": {k: dict(v) for k, v in SOLDER_MASK_MATERIALS.items()},
        "typical_bands": {k: list(v) for k, v in SOLDER_MASK_TYPICAL_BANDS.items()},
        "cpw_extension": CPW_GHIONE_NALDI_STATUS,
        "verified": False,
    }
