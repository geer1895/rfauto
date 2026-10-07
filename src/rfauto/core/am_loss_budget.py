r"""PK-8 增材制造（AM）RF 损耗预算与公差敏感性内核。

规格：研究扩充 round14 §五 PK-8（P2/M）：
"打印金属有效电导率+Ra→Hammerstad/Huray 映射（Ra≠Rq 换算声明）+波导衰减
预算（WR 表+horn 复用）；公差敏感性走 tolerance_allocation/pce 链。验收：
复现 MNSL 2024 WR-10 超损 4.02dB 分解量级"。

纯算法零 IO 零外部进程（铁律 7）；不进注册表、不定义 ``__all__``
（PK-1 acoustic_resonator 先例）。单源纪律：波导衰减闭式用
core/rwg_mmt.alpha_c_te10/alpha_d_te10、WR 尺寸表用 core/rw_tables、
粗糙度增益（Hammerstad/Huray）与趋肤深度用 core/conductor_loss——
本模块零新物理闭式，只做**映射与预算分解**。

模型与出处
----------
1. **Ra→Rq 换算（声明面）**：Rq = √(π/2)·Ra ≈ 1.2533·Ra **仅当高度
   分布为高斯型**——高斯分布 E|X| = σ·√(2/π)（解析可推导，tests 以
   数值积分独立裁判）。非高斯面（AM 熔道周期结构可为强非高斯）该系数
   不成立，本模块只登记 gaussian 档、其它分布显式拒绝不外推（#118）。
   Hammerstad 侧只吃 Rq；Huray 需铜瘤几何（r, N, A_flat）——**Ra 不映射
   到 Huray 铜瘤半径**（行业存在 ~4.4·Rq 类经验映射，检索未获可核出处，
   不引入；调用方自供铜瘤参数）。
2. **打印金属有效电导率**：AM 孔洞（porosity）金属的两相（金属+气孔）
   Wiener 混合界——并联界（层理对齐）σ_par = (1−φ)·σ 精确、串联界
   （层理垂直，气孔 σ=0）σ_ser = 0 精确（分层复合材料两极限的精确解，
   非近似）。实测/厂商声称的 σ_eff 落在 [σ_ser, σ_par] 外即非法（守卫）。
   **本模块不代填任何工艺档数值**（SLM/EBM/BinderJet 的实测 σ_eff 带
   检索未获可核公开值——AM_PRINT_METAL_NOTES 显式 UNVERIFIED 登记，
   数值由调用方提供）。
3. **波导衰减预算**：TE10 导体衰减（rwg_mmt.alpha_c_te10，仓内手推
   在档）× 粗糙度增益（conductor_loss.roughness_gain 单源，K 乘 Rs 的
   物理依据=粗糙度修正作用于表面阻抗、同场分布下 α_c ∝ Rs）+ 介质衰减
   （alpha_d_te10）——dB 域线性分解。WR 尺寸/推荐带取 rw_tables（3src
   核对表）。
4. **MNSL 2024 WR-10 锚（UNVERIFIED_literature）**：规格点名的"3D
   金属打印波导较商版超损 4.02 dB"数字，2026-10-03 检索仅命中搜索引擎
   摘要转述（ResearchGate 页未直达、原文刊名/页码未核实）——按引用腐坏
   纪律**只作登记槽不进判据**：MNSL_2024_WR10_EXCESS_DB 提供
   status="UNVERIFIED_literature" 的登记与纯对比报告，任何分解复现须
   调用方自供实测超损值（required_roughness_gain_for_excess 反演 K）。

公差敏感性面：按规格走 tolerance_allocation/pce 既有链（不在本模块
重做）；本模块输出逐项 dB 分解即敏感性的一阶投入面。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import conductor_loss
from rfauto.core.rw_tables import wr_lookup
from rfauto.core.rwg_mmt import Waveguide, alpha_c_te10, alpha_d_te10

_MU0 = 4.0e-7 * math.pi
_DB_PER_NP = 8.685889638065035  # 20/ln(10)（dB/Np，与 10·log10(e²) 同值）

#: MNSL 2024 WR-10 超损登记槽（规格 round14 §五 PK-8 验收锚；文献未核实）
MNSL_2024_WR10_EXCESS_DB: dict[str, Any] = {
    "value_db": 4.02,
    "context": "3D 金属打印 WR-10 波导较商用波导的超损（分解量级验收锚）",
    "status": "UNVERIFIED_literature",
    "note": ("2026-10-03 检索：数字仅见于搜索引擎摘要转述，原文刊名/页码"
             "未核实（MNSL 刊名缩写未解析）。不进物理判据（#118/#122）；"
             "实测超损由调用方提供后走 required_roughness_gain_for_excess"),
}

#: 打印金属工艺档登记槽（无值登记——检索未获可核公开值，不代填，#118）
AM_PRINT_METAL_NOTES: dict[str, Any] = {
    "status": "UNVERIFIED_no_value_registered",
    "processes": ("SLM/EBM/BinderJet 的 σ_eff 与 Ra 带：本模块不登记数值；"
                  "调用方以 sigma_eff_s_per_m + 实测 Ra 自供，"
                  "经 wiener_bounds 守卫后进预算"),
    "retrieval_pointers": ("round14 规格建议源（打印金属电导率实测文献）；"
                           "2026-10-03 检索未获可核公开值"),
}


def _nonneg(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（df7+⑯）")
    v = float(value)
    if not (math.isfinite(v) and v >= 0.0):
        raise ValueError(f"{name} 必须为非负有限数，得到 {value!r}")
    return v


def _positive(value: float, name: str) -> float:
    v = _nonneg(value, name)
    if v <= 0.0:
        raise ValueError(f"{name} 必须 >0，得到 {value!r}")
    return v


# ─── Ra→Rq（高斯声明面）──────────────────────────────────────────────────────


def gaussian_rq_over_ra() -> float:
    """高斯高度分布的 Rq/Ra = √(π/2)（解析常数，来源=分布矩推导）。

    高斯 N(0, σ²)：Rq=σ、Ra=E|X|=σ·√(2/π) → Rq/Ra=√(π/2)≈1.2533。
    出处为概率论标准结果（无页码可引；tests 以梯形积分数值独立复核）。
    """
    return math.sqrt(math.pi / 2.0)


def rq_from_ra_gaussian(ra_m: float) -> float:
    """Ra→Rq 高斯换算（唯一登记分布；非高斯显式拒绝——声明面见 docstring）。

    Args:
        ra_m: 算术平均粗糙度 Ra [m]（>=0）。

    Raises:
        ValueError: 负值/非有限（bool 拒收）。
    """
    return gaussian_rq_over_ra() * _nonneg(ra_m, "ra_m")


# ─── 打印金属有效电导率（Wiener 界守卫）─────────────────────────────────────


def wiener_conductivity_bounds(sigma_matrix_s_per_m: float,
                               void_fraction: float) -> dict[str, Any]:
    """金属+气孔两相有效电导率 Wiener 界（分层极限精确解）。

    - 并联界（层理与电场平行）：σ_par = (1−φ)·σ_matrix（精确，气孔
      σ=0 不导电层贡献零）；
    - 串联界（层理与电场垂直，气孔 σ=0）：σ_ser = 0（谐波混合含零相
      精确为零）。

    实测 σ_eff ∈ [0, σ_par] 为合法性域（守卫用）；真实 AM 金属通常显著
    低于并联界（孔洞三维分布非层理），界只做合法性不做估计（#118）。

    Raises:
        ValueError: σ<=0、φ∉[0,1] 或 bool 混入。
    """
    sigma = _positive(sigma_matrix_s_per_m, "sigma_matrix_s_per_m")
    phi = _nonneg(void_fraction, "void_fraction")
    if phi > 1.0:
        raise ValueError(f"void_fraction 必须 ∈[0,1]，得到 {phi!r}")
    return {
        "parallel_upper_s_per_m": (1.0 - phi) * sigma,
        "series_lower_s_per_m": 0.0,
        "void_fraction": phi,
        "sigma_matrix_s_per_m": sigma,
    }


def validate_printed_sigma_eff(sigma_eff_s_per_m: float,
                               sigma_matrix_s_per_m: float,
                               void_fraction: float) -> dict[str, Any]:
    """调用方自供 σ_eff 的合法性守卫（落在 Wiener 界内才进预算）。"""
    bounds = wiener_conductivity_bounds(sigma_matrix_s_per_m, void_fraction)
    sigma_eff = _positive(sigma_eff_s_per_m, "sigma_eff_s_per_m")
    upper = bounds["parallel_upper_s_per_m"]
    ok = sigma_eff <= upper * (1.0 + 1e-12)
    return {
        "ok": bool(ok),
        "sigma_eff_s_per_m": sigma_eff,
        "allowed_upper_s_per_m": upper,
        "message": ("" if ok else
                    f"sigma_eff={sigma_eff:.4g} 超出并联上界 {upper:.4g} S/m"
                    f"（φ={void_fraction!r}）——孔洞率或 σ_eff 声明不一致"),
    }


# ─── 波导衰减预算（WR 表 + 单源闭式 + 粗糙度映射）───────────────────────────


def _roughness_cfg(roughness: dict[str, Any] | None, f_hz: float,
                   sigma_s_per_m: float) -> tuple[float, dict[str, Any]]:
    """粗糙度配置 → K（conductor_loss.roughness_gain 单源）+ 配置回执。"""
    if roughness is None:
        roughness = {"model": "smooth"}
    if not isinstance(roughness, dict):
        raise ValueError("roughness 必须是 dict（model 键必给）")
    model = str(roughness.get("model", "")).strip().lower()
    delta = conductor_loss.skin_depth(f_hz, sigma_s_per_m)
    if model == "smooth":
        return 1.0, {"model": "smooth"}
    if model == "hammerstad":
        ra = _nonneg(roughness["ra_m"], "roughness.ra_m")  # type: ignore[call-arg]
        rq = rq_from_ra_gaussian(ra)
        rf = float(roughness.get("roughness_factor", 2.0))
        k = conductor_loss.hammerstad_roughness_factor(rq, delta, rf)
        return k, {"model": "hammerstad", "ra_m": ra, "rq_m": rq,
                   "rq_conversion": "gaussian_sqrt_pi_over_2",
                   "roughness_factor": rf}
    if model == "huray":
        kwargs = {
            "nodule_radius_m": _positive(
                roughness["nodule_radius_m"], "nodule_radius_m"),
            "nodules_per_cell": _nonneg(
                roughness["nodules_per_cell"], "nodules_per_cell"),
            "cell_area_m2": _positive(
                roughness["cell_area_m2"], "cell_area_m2"),
        }
        if "relative_matte_area" in roughness:
            kwargs["relative_matte_area"] = _positive(
                roughness["relative_matte_area"], "relative_matte_area")
        k = conductor_loss.roughness_gain("huray", delta_m=delta, **kwargs)
        return k, {"model": "huray", **kwargs}
    raise ValueError(
        f"未知粗糙度模型 {model!r}（smooth/hammerstad/huray）；"
        "Ra→Huray 铜瘤半径的经验映射无可核出处，不提供（自供铜瘤参数）")


def wr_loss_budget(
    wr_name: str,
    f_ghz: float,
    length_m: float,
    *,
    sigma_s_per_m: float,
    tan_d: float = 0.0,
    eps_r: float = 1.0,
    roughness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """WR 波导段损耗预算分解（光滑导体/粗糙度超损/介质，dB 域线性）。

    链路：rw_tables.wr_lookup（尺寸+推荐带）→ rwg_mmt.Waveguide →
    alpha_c_te10（光滑导体，仓内单源）→ 粗糙度增益 K（conductor_loss
    单源；α_c_rough = K·α_c_smooth，依据=粗糙度作用于表面阻抗、同场
    分布下 α_c ∝ Rs）→ alpha_d_te10（介质）。

    Returns:
        dict：alpha 各分量 [Np/m 与 dB]，total_db、ideal_db、excess_db、
        dielectric_db（total = ideal + excess + dielectric，构造恒等）、
        wr 元数据与 roughness 配置回执。

    Raises:
        KeyError: 未知名 WR（wr_lookup 契约）；ValueError: 频率在截止下、
        粗糙度配置非法等（下游单源契约原样透传）。
    """
    rec = wr_lookup(wr_name)
    f_hz = _positive(f_ghz, "f_ghz") * 1e9
    length = _positive(length_m, "length_m")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    tand = _nonneg(tan_d, "tan_d")
    wg = Waveguide(a=rec.a_mm * 1e-3, b=rec.b_mm * 1e-3, eps_r=eps_r,
                   tan_d=tand, sigma=sigma)
    k_rough, rough_receipt = _roughness_cfg(roughness, f_hz, sigma)
    a_c_smooth = alpha_c_te10(wg, f_hz)  # 截止下显式 ValueError（不外推）
    a_c_total = k_rough * a_c_smooth
    a_d = alpha_d_te10(wg, f_hz) if tand > 0.0 else 0.0
    a_total = a_c_total + a_d
    ideal_db = a_c_smooth * _DB_PER_NP * length
    excess_db = (k_rough - 1.0) * a_c_smooth * _DB_PER_NP * length
    dielectric_db = a_d * _DB_PER_NP * length
    return {
        "wr_name": rec.wr_name,
        "a_mm": rec.a_mm,
        "b_mm": rec.b_mm,
        "fc10_ghz": rec.fc10_ghz,
        "f_ghz": f_ghz,
        "length_m": length,
        "in_recommended_band": bool(rec.f_start_ghz <= f_ghz <= rec.f_end_ghz),
        "alpha_c_smooth_np_per_m": a_c_smooth,
        "alpha_c_total_np_per_m": a_c_total,
        "alpha_d_np_per_m": a_d,
        "alpha_total_np_per_m": a_total,
        "roughness_gain_k": k_rough,
        "ideal_db": ideal_db,
        "excess_db": excess_db,
        "dielectric_db": dielectric_db,
        "total_db": ideal_db + excess_db + dielectric_db,
        "roughness": rough_receipt,
        "sources": {
            "alpha_c": "core/rwg_mmt.alpha_c_te10（仓内单源）",
            "wr_table": "core/rw_tables（3src/2src 逐行来源标注）",
            "roughness": "core/conductor_loss（Hammerstad/Huray 单源）",
            "ra_rq": "gaussian 档解析推导（非高斯不适用，见模块 docstring）",
        },
    }


def required_roughness_gain_for_excess(
    excess_db: float,
    wr_name: str,
    f_ghz: float,
    length_m: float,
    *,
    sigma_s_per_m: float,
    tan_d: float = 0.0,
    eps_r: float = 1.0,
) -> dict[str, Any]:
    """由实测超损反演所需粗糙度增益 K（确定性反演，非拟合）。

    excess_db = (K−1)·α_c_smooth·(dB/Np)·L  →  K = 1 + excess/基准项。
    实测超损（如 MNSL 锚声称的 4.02 dB，须调用方核实文献后提供）由此
    进入"分解量级"分析：K 反演值再喂 _roughness_cfg 对照可得等效 Ra
    或铜瘤参数的可行性判断。
    """
    excess = _nonneg(excess_db, "excess_db")
    budget = wr_loss_budget(
        wr_name, f_ghz, length_m, sigma_s_per_m=sigma_s_per_m,
        tan_d=tan_d, eps_r=eps_r, roughness=None)
    base = budget["alpha_c_smooth_np_per_m"] * _DB_PER_NP * length_m
    if base <= 0.0:
        raise ValueError("基准项为零（PEC 或零长），K 反演不可行")
    k_required = 1.0 + excess / base
    return {
        "k_required": k_required,
        "excess_db": excess,
        "reference_db_per_unit_roughness": base,
        "wr_name": budget["wr_name"],
        "f_ghz": f_ghz,
        "length_m": length_m,
    }


def compare_excess_to_registered_anchor(excess_db: float) -> dict[str, Any]:
    """实测/设计超损 vs MNSL 登记锚的纯对比报告（无判据，锚 UNVERIFIED）。"""
    excess = _nonneg(excess_db, "excess_db")
    anchor = MNSL_2024_WR10_EXCESS_DB
    return {
        "excess_db": excess,
        "anchor_db": anchor["value_db"],
        "ratio_to_anchor": excess / float(anchor["value_db"]),
        "anchor_status": anchor["status"],
        "verdict": "report_only（锚未核实，不构成 PASS/FAIL 判据，#122）",
    }
