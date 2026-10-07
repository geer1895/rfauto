"""F-E 件 4：抖动预算/双狄拉克 TJ 内核（RJ/DJ 分离、bathtub、TJ@BER 外推）。

定位
----
信号完整性抖动预算的确定性闭式内核：总抖动 TJ 对误码率 BER 的外推
（双狄拉克模型）、随机/确定性抖动分离（RJ/DJ）、浴盆曲线（bathtub）、
多源抖动分量合成。与 core/si_channel.py 的关系：si_channel 已有眼高/
眼宽/jitter_pp/jitter_rms 的**确定性实测口径**（有限 PRBS，无 BER 语义），
本模块补**统计口径**（RJ/DJ 分离与 TJ@BER 外推）——COM 类工具不输出
这些中间量。si_channel 不动，互证接口见 :func:`rms_ui_to_sigma_rj`。

口径来源（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）
----------------------------------------------------------------
- 双狄拉克模型 TJ(BER) = DJ_δδ + 2·Q(BER)·σ_RJ，其中 Q(BER) =
  √2·erfc⁻¹(2·BER)：Ransom Stephens, "Jitter Analysis: The dual-Dirac
  Model, RJ/DJ Separation"（Agilent/Keysight 白皮书 5989-3206EN, 2004）
  + R. Stephens, IEEE Communications Magazine 42(2) (2004) 双核
  （研究扩充 round3 F-E 表件 4 指定权威）。
  行业钉：BER=1e-12 时 Q=7.0344（白皮书口径引用值），2Q=14.069——即
  "峰峰抖动 ≈ 14σ_RJ @ 1e-12" 经验法则的精确出处。本内核 scipy 实测
  Q(1e-12) = 7.034483825301131（special.erfcinv 与 stats.norm.isf 两条
  独立实现路径逐位一致；与引用值 7.0344 符合到引用的 5 位有效数字）。
- 浴盆曲线闭式 BER(u) = Q((u−DJ/2)/σ) + Q((1−u−DJ/2)/σ)（u 为采样相位，
  UI）：同白皮书浴盆曲线节——DJ_δδ 使眼两边缘各内缩 DJ/2，每侧贡献一条
  高斯尾（Q 为标准正态右上尾 Q(x)=0.5·erfc(x/√2)）。
- RJ 高斯 RSS 合成 σ_total = √Σσᵢ²：独立高斯源方差相加（概率论恒等式）。
- DJ 峰峰线性合成（上界口径）DJ_pp = Σ|分量|：行业抖动预算分解表惯例
  （PCI-SIG/OIF-CEI 预算表口径）——各 DJ 分量按最坏相位对齐的线性和是
  保守上界；统计独立分量的精确合成是分布卷积（≤线性和）。PJ 以峰值幅
  度给入（峰峰 = 2×峰值），DCD/BUJ 直接给峰峰。

诚实边界（预声明，先写后跑）
----------------------------
1. TJ 闭式丢掉对侧尾部交叉项：精确两尾式为
   BER_total(TJ) = Q((TJ−D)/(2σ)) + Q((TJ+D)/(2σ))，标准双狄拉克取首项
   （深 BER 域第二项相对首项 <1e-50，工程口径忽略）；浴盆曲线与 TJ 的
   互证残差在单测给实测数。
2. 预算里 DJ_δδ 取 DJ 峰峰和作**上界**：双狄拉克 DJ_δδ 是模型等效参数，
   与任意 DJ 分量分布的峰峰值不恒等；上界口径保守可辩护（同 aging
   fill_fraction=1 的上界先例），逐分量换算未建模。
3. σ_RJ = 0（无随机展宽）：TJ = DJ 逐位恒等（任意 BER）；浴盆曲线在
   σ=0 退化为阶跃 → :func:`bathtub_ber` 显式 ValueError（确定性口径请走
   :func:`tj_dual_dirac` 的 σ=0 分支）。
4. PJ 各分量间相位相关性未建模：线性和 = 完全相关（最坏对齐）上界；
   DCD/PJ/BUJ 内部统计形态（如 BUJ 的分布族）不影响峰峰上界口径。
5. BER 合法域为开区间 (0, 0.5)：BER→0 使 erfcinv 上溢（2·BER 下溢为 0
   时显式 ValueError），BER≥0.5 时 Q≤0 无物理意义。
6. 本模块是闭式统计预算，不替代 BER 仿真（如 Markov 链/ statistical
   eye）；DDJ 的图案相关性（finite-PRBS 实测 vs 无限统计）归 si_channel
   口径，两边数字不可直接混读（经 :func:`rms_ui_to_sigma_rj` 显式换算）。

接口：纯函数零 IO（math/numpy/scipy.special）；全部返回 JSON 可序列化
float/dict（dataclass 带 to_dict，ndarray 面仅 bathtub 显式声明）；
判缺失一律 ``is not None``（#364④，禁 ``or 缺省``）；bool 显式拒收
（df7+⑯）。不进 calculators 注册表（F-E P1 域内约定，消费者是 service
薄壳）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.special import erfcinv

__all__ = [
    "JitterComponents",
    "RJDJFit",
    "bathtub_ber",
    "bathtub_curve",
    "combine_rj",
    "compose_dj_pp",
    "eye_width_ui",
    "gauss_tail_q",
    "q_from_ber",
    "rms_ui_to_sigma_rj",
    "separate_rj_dj",
    "tj_dual_dirac",
]

_SQRT2 = math.sqrt(2.0)
#: BER 合法域开区间上端（erfcinv(2·BER) 的定义域上界）
_BER_MAX = 0.5


# ---------------------------------------------------------------------------
# 入参守卫（#140：注解不等于调用方真的传了；bool 显式拒收 df7+⑯）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收）。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，实际 {out!r}")
    return out


def _nonneg(value: Any, name: str) -> float:
    """把入参收敛为有限非负 float，非法即显式报错。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0，实际 {out!r}")
    return out


def _ber(value: Any, name: str = "ber") -> float:
    """BER 合法域校验：开区间 (0, 0.5)，且 2·ber 不得下溢为 0。"""
    out = _finite(value, name)
    if out <= 0.0 or out >= _BER_MAX:
        raise ValueError(f"{name} 必须落在开区间 (0, 0.5)，实际 {out!r}")
    if 2.0 * out == 0.0:  # pragma: no cover - 子下溢防御（out>0 已挡住绝大多数）
        raise ValueError(f"{name} 过小致 2·BER 下溢为 0（erfcinv 无定义），实际 {out!r}")
    return out


# ---------------------------------------------------------------------------
# Q 函数族（双狄拉克的两根柱子）
# ---------------------------------------------------------------------------

def gauss_tail_q(x: Any) -> float:
    """标准正态右上尾 Q(x) = 0.5·erfc(x/√2)（浴盆曲线与 TJ 共用的尾函数）。

    恒等式：Q(0) = 0.5（逐位）；Q(−x) = 1 − Q(x)。
    """
    return 0.5 * math.erfc(_finite(x, "x") / _SQRT2)


def q_from_ber(ber: Any) -> float:
    """BER → 高斯归一化分位 Q(BER) = √2·erfc⁻¹(2·BER)（双狄拉克斜率因子）。

    这是 TIE 尾部概率 BER 换成"距眼边缘多少 σ"的标准正态分位（即
    Φ⁻¹(1−BER)）。行业钉：Q(1e-12) = 7.0344…（scipy 实测
    7.034483825301131），2Q = 14.069 ≈ "峰峰 ≈ 14σ" 经验法则。

    例外：ber ∉ (0, 0.5) 或 2·ber 下溢为 0 → ValueError。
    """
    b = _ber(ber)
    return _SQRT2 * float(erfcinv(2.0 * b))


# ---------------------------------------------------------------------------
# 双狄拉克 TJ 与浴盆曲线
# ---------------------------------------------------------------------------

def tj_dual_dirac(ber: Any, sigma_rj: Any, dj_dd: Any) -> float:
    """双狄拉克总抖动 TJ(BER) = DJ_δδ + 2·Q(BER)·σ_RJ（UI 或 s，单位随入参）。

    sigma_rj：随机抖动（高斯）σ（>=0，与 DJ 同单位）；dj_dd：双狄拉克
    确定性抖动 DJ_δδ（>=0）。σ_RJ = 0 时无随机展宽，TJ = DJ 逐位恒等
    （任意合法 BER）——确定性极限分支（规格预声明）。
    """
    b = _ber(ber)
    s = _nonneg(sigma_rj, "sigma_rj")
    d = _nonneg(dj_dd, "dj_dd")
    if s == 0.0:
        return d
    return d + 2.0 * s * q_from_ber(b)


def eye_width_ui(ber: Any, sigma_rj: Any, dj_dd: Any) -> float:
    """给定 BER 容限下的眼宽 EW = 1 − TJ(BER)（UI；恒等式，可为负=眼闭合）。

    与 :func:`tj_dual_dirac` 互补：EW + TJ = 1 UI 逐位成立。负值表示该
    BER 容限下眼已闭合（预算超标信号，如实返回不截断）。
    """
    return 1.0 - tj_dual_dirac(ber, sigma_rj, dj_dd)


def bathtub_ber(u_ui: Any, sigma_rj: Any, dj_dd: Any) -> np.ndarray:
    """浴盆曲线 BER(u) = Q((u−DJ/2)/σ) + Q((1−u−DJ/2)/σ)（UI 单位）。

    u_ui：采样相位（标量或一维数组，[0, 1] UI）；返回同长 np.ndarray
    （标量入 → 形状 (1,)）。最小点在眼中心 u=0.5（DJ 两边缘 D/2 与
    1−D/2 的中点），缝宽由 :func:`eye_width_ui` 给出（单测互证）。

    例外：σ_RJ = 0 → ValueError（退化为阶跃，确定性口径走
    :func:`tj_dual_dirac`）；DJ_δδ > 1 UI → ValueError（眼确定性全闭合，
    浴盆无定义）；u 越界/非有限 → ValueError。
    """
    if isinstance(u_ui, (bool, np.bool_)):
        raise ValueError("u_ui 不接受 bool")
    if np.asarray(u_ui).dtype == bool:
        raise ValueError("u_ui 不接受布尔数组（True/False 会被静默转 0/1 UI）")
    u = np.atleast_1d(np.asarray(u_ui, dtype=float))
    if u.ndim != 1:
        raise ValueError(f"u_ui 必须是标量或一维数组，实际 ndim={np.asarray(u_ui).ndim}")
    if not bool(np.all(np.isfinite(u))):
        raise ValueError("u_ui 含非有限值")
    if float(u.min()) < 0.0 or float(u.max()) > 1.0:
        raise ValueError(f"u_ui 必须落在 [0, 1] UI，实际范围 [{u.min()!r}, {u.max()!r}]")
    s = _nonneg(sigma_rj, "sigma_rj")
    if s == 0.0:
        raise ValueError(
            "sigma_rj=0 时浴盆曲线退化为阶跃（无统计展宽）；"
            "确定性口径请用 tj_dual_dirac 的 σ=0 分支"
        )
    d = _nonneg(dj_dd, "dj_dd")
    if d > 1.0:
        raise ValueError(f"dj_dd > 1 UI（眼确定性全闭合），浴盆无定义，实际 {d!r}")
    half = 0.5 * d
    # 向量化口径：0.5·erfc(x/√2) 直接用 scipy.special.erfc（与 gauss_tail_q 同式）
    left = 0.5 * _erfc_vec((u - half) / s)
    right = 0.5 * _erfc_vec((1.0 - u - half) / s)
    return left + right


def _erfc_vec(x: np.ndarray) -> np.ndarray:
    """erfc 的向量化薄壳（避免在模块顶层多引一个名字）。"""
    from scipy.special import erfc

    return erfc(x / _SQRT2)


def bathtub_curve(
    sigma_rj: Any, dj_dd: Any, n_points: Any = 801
) -> tuple[np.ndarray, np.ndarray]:
    """在 [0, 1] UI 均匀网格上取浴盆曲线，返回 (u, ber) 两个一维数组。

    n_points：网格点数（>=2，缺省 801 ≈ 1.25e-3 UI 分辨率）。
    """
    if isinstance(n_points, bool) or not isinstance(n_points, (int, np.integer)):
        raise TypeError(f"n_points 必须是整数，实际 {type(n_points).__name__}")
    n = int(n_points)
    if n < 2:
        raise ValueError(f"n_points 必须 >=2，实际 {n}")
    u = np.linspace(0.0, 1.0, n)
    return u, bathtub_ber(u, sigma_rj, dj_dd)


# ---------------------------------------------------------------------------
# RJ/DJ 分离（双狄拉克拟合反演：两 BER 点两未知，闭式解）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RJDJFit:
    """两点双狄拉克拟合结果（全部 JSON 可序列化；to_dict 输出）。

    sigma_rj：随机抖动 σ（UI 或 s，单位随测量）；dj_dd：双狄拉克
    DJ_δδ。ber_1/ber_2 为较低/较高 BER（按 Q 排序），tj_1/tj_2 为对应
    TJ 测量。
    """

    sigma_rj: float
    dj_dd: float
    ber_1: float
    tj_1: float
    ber_2: float
    tj_2: float

    def to_dict(self) -> dict[str, float]:
        return {
            "sigma_rj": self.sigma_rj,
            "dj_dd": self.dj_dd,
            "ber_1": self.ber_1,
            "tj_1": self.tj_1,
            "ber_2": self.ber_2,
            "tj_2": self.tj_2,
        }


def _parse_point(point: Any, label: str) -> tuple[float, float]:
    """(TJ, BER) 测量点收敛：二元数值序列 → (tj>=0, ber∈(0,0.5))。"""
    if isinstance(point, (str, bytes)) or not isinstance(point, (list, tuple)):
        raise ValueError(f"{label} 必须是 (TJ, BER) 二元序列，实际 {point!r}")
    if len(point) != 2:
        raise ValueError(f"{label} 必须恰好含 (TJ, BER) 两个元素，实际长度 {len(point)}")
    tj = _nonneg(point[0], f"{label}[0]（TJ）")
    ber = _ber(point[1], f"{label}[1]（BER）")
    return tj, ber


def separate_rj_dj(point_1: Any, point_2: Any) -> RJDJFit:
    """两 BER 点 TJ 测量 → 双狄拉克 RJ/DJ 分离（两方程两未知闭式解）。

    联立 TJᵢ = DJ + 2·Qᵢ·σ（i=1,2，Qᵢ=q_from_ber(BERᵢ)）：

        σ_RJ = (TJ₁ − TJ₂) / (2·(Q₁ − Q₂))
        DJ_δδ = (Q₁·TJ₂ − Q₂·TJ₁) / (Q₁ − Q₂)   （对称闭式，两点等价）

    预声明有效性条件（违反即 ValueError，#122 先行）：
    - 两点 BER 必须不同（Q₁=Q₂ 斜率不可辨）；
    - σ_RJ 必须 > 0：TJ 必须随 BER 降低而单调增大（斜率合理）；
    - DJ_δδ 必须 >= 0：解出负 DJ 说明两点与双狄拉克模型不一致（非物理）。

    前向合成 → 反演回收逐位闭合（rel 1e-9 门，单测钉）。
    """
    tj1, ber1 = _parse_point(point_1, "point_1")
    tj2, ber2 = _parse_point(point_2, "point_2")
    q1 = q_from_ber(ber1)
    q2 = q_from_ber(ber2)
    if q1 == q2:
        raise ValueError(
            f"两点 BER 相同（{ber1!r}）→ 双狄拉克斜率不可辨，需两个不同 BER 点"
        )
    sigma = (tj1 - tj2) / (2.0 * (q1 - q2))
    if not sigma > 0.0:
        raise ValueError(
            f"解出 σ_RJ={sigma!r} <= 0：TJ 未随 BER 降低而增大"
            f"（(TJ₁={tj1!r} @ Q₁={q1!r}) vs (TJ₂={tj2!r} @ Q₂={q2!r}），"
            "两点斜率与双狄拉克模型不一致"
        )
    dj = (q1 * tj2 - q2 * tj1) / (q1 - q2)
    if dj < 0.0:
        raise ValueError(
            f"解出 DJ_δδ={dj!r} < 0（非物理）：两点 TJ 差相对 "
            f"σ_RJ={sigma!r} 的随机展宽过小，与双狄拉克模型不一致"
        )
    # 输出按 BER 升序（Q 降序）排列，便于阅读"更低 BER → 更大 TJ"
    if ber1 <= ber2:
        return RJDJFit(sigma_rj=sigma, dj_dd=dj, ber_1=ber1, tj_1=tj1, ber_2=ber2, tj_2=tj2)
    return RJDJFit(sigma_rj=sigma, dj_dd=dj, ber_1=ber2, tj_1=tj2, ber_2=ber1, tj_2=tj1)


# ---------------------------------------------------------------------------
# 分量合成（RJ RSS；DJ 峰峰线性上界）
# ---------------------------------------------------------------------------

def combine_rj(sigmas: Any) -> float:
    """独立高斯 RJ 源 RSS 合成 σ_total = √Σσᵢ²（概率论恒等式）。

    sigmas：各源 σ 的非空性不要求——空表返回 0.0（无随机源）；每个元素
    必须 >=0 且非 bool。同源重复计入是调用方错误（本函数不去重）。
    """
    if isinstance(sigmas, (str, bytes)) or not isinstance(sigmas, (list, tuple)):
        raise ValueError("sigmas 必须是 σ 序列（list/tuple）")
    total_sq = 0.0
    for idx, s in enumerate(sigmas):
        total_sq += _nonneg(s, f"sigmas[{idx}]") ** 2
    return math.sqrt(total_sq)


def compose_dj_pp(
    pj_amp_ui: Any = None,
    dcd_pp_ui: Any = None,
    buj_pp_ui: Any = None,
) -> float:
    """DJ 分量峰峰线性合成（上界口径）：DJ_pp = 2·PJ_amp + DCD + BUJ。

    pj_amp_ui：周期性抖动（PJ）**峰值**幅度（峰峰 = 2×峰值）；
    dcd_pp_ui：占空比失真（DCD）峰峰；buj_pp_ui：有界不相关抖动（BUJ）
    峰峰。缺省 None = 该分量不存在（判缺失 is not None，#364④；数值
    0.0 合法）。全部缺省 → ValueError（无分量的合成是调用方错误；
    纯 RJ 预算请直接用 combine_rj）。

    口径：线性和 = 各分量最坏相位对齐的保守上界（统计独立分量的精确
    合成是分布卷积，≤ 线性和）。
    """
    total = 0.0
    n_present = 0
    if pj_amp_ui is not None:
        total += 2.0 * _nonneg(pj_amp_ui, "pj_amp_ui")
        n_present += 1
    if dcd_pp_ui is not None:
        total += _nonneg(dcd_pp_ui, "dcd_pp_ui")
        n_present += 1
    if buj_pp_ui is not None:
        total += _nonneg(buj_pp_ui, "buj_pp_ui")
        n_present += 1
    if n_present == 0:
        raise ValueError("至少给一个 DJ 分量（pj_amp_ui/dcd_pp_ui/buj_pp_ui 之一）")
    return total


@dataclass(frozen=True)
class JitterComponents:
    """抖动预算分量容器（RJ 多源 + DJ 三类显式分量）→ 总预算面。

    rj_sigmas：各独立高斯源 σ 序列（总 σ=RSS）；pj_amp_ui：PJ 峰值
    （None=无）；dcd_pp_ui / buj_pp_ui：DCD/BUJ 峰峰（None=无）。
    tj_at_ber / eye_width_at_ber 里 DJ_δδ 取 DJ 峰峰和（上界口径，
    见模块 docstring 诚实边界 2）。
    """

    rj_sigmas: tuple[float, ...]
    pj_amp_ui: float | None = None
    dcd_pp_ui: float | None = None
    buj_pp_ui: float | None = None

    def __post_init__(self) -> None:
        # frozen dataclass 的收敛走 object.__setattr__（只做校验/形态归一）
        if isinstance(self.rj_sigmas, (str, bytes)) or not isinstance(
            self.rj_sigmas, (list, tuple)
        ):
            raise ValueError("rj_sigmas 必须是 σ 序列（list/tuple）")
        object.__setattr__(
            self,
            "rj_sigmas",
            tuple(_nonneg(s, f"rj_sigmas[{i}]") for i, s in enumerate(self.rj_sigmas)),
        )
        if self.pj_amp_ui is not None:
            object.__setattr__(self, "pj_amp_ui", _nonneg(self.pj_amp_ui, "pj_amp_ui"))
        if self.dcd_pp_ui is not None:
            object.__setattr__(self, "dcd_pp_ui", _nonneg(self.dcd_pp_ui, "dcd_pp_ui"))
        if self.buj_pp_ui is not None:
            object.__setattr__(self, "buj_pp_ui", _nonneg(self.buj_pp_ui, "buj_pp_ui"))

    def total_sigma_rj(self) -> float:
        """RJ 总 σ = √Σσᵢ²（RSS）。"""
        return combine_rj(list(self.rj_sigmas))

    def total_dj_pp(self) -> float:
        """DJ 总峰峰 = 2·PJ_amp + DCD + BUJ（存在的分量线性和上界）。"""
        total = 0.0
        if self.pj_amp_ui is not None:
            total += 2.0 * self.pj_amp_ui
        if self.dcd_pp_ui is not None:
            total += self.dcd_pp_ui
        if self.buj_pp_ui is not None:
            total += self.buj_pp_ui
        return total

    def tj_at_ber(self, ber: Any) -> float:
        """该分量组合在 BER 容限下的总抖动 TJ（DJ_δδ 取峰峰和上界）。"""
        return tj_dual_dirac(ber, self.total_sigma_rj(), self.total_dj_pp())

    def eye_width_at_ber(self, ber: Any) -> float:
        """该分量组合在 BER 容限下的眼宽 EW = 1 − TJ（UI，可为负）。"""
        return eye_width_ui(ber, self.total_sigma_rj(), self.total_dj_pp())

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化面（rj_sigmas 转 list，None 保留原语义）。"""
        return {
            "rj_sigmas": [float(s) for s in self.rj_sigmas],
            "sigma_rj_total": self.total_sigma_rj(),
            "pj_amp_ui": None if self.pj_amp_ui is None else float(self.pj_amp_ui),
            "dcd_pp_ui": None if self.dcd_pp_ui is None else float(self.dcd_pp_ui),
            "buj_pp_ui": None if self.buj_pp_ui is None else float(self.buj_pp_ui),
            "dj_pp_total": self.total_dj_pp(),
        }


# ---------------------------------------------------------------------------
# 与 si_channel 互证接口
# ---------------------------------------------------------------------------

def rms_ui_to_sigma_rj(rms_ui: Any) -> float:
    """si_channel 的 jitter_rms_ui → σ_RJ（显式换算桩 + 口径对照钉）。

    si_channel.EyeMetrics.jitter_rms_ui 在 RJ 主导（无 DDJ）通道下就是
    高斯 σ——本函数做显式校验换算（非负有限），并把峰峰口径恒等式钉在
    单测：TJ_pp(1e-12) = 2·Q(1e-12)·σ = 14.0690·σ（白皮书引用值 14.069
    ≈ "≈14σ 经验法则"；实测对 14 的相对偏差 0.4926%，双狄拉克 2·Q(ber)
    口径是正确值，14 是其舍入记忆）。
    """
    return _nonneg(rms_ui, "rms_ui")
