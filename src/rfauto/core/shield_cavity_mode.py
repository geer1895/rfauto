"""HS-3 屏蔽罩腔模门：矩形封闭腔 TE/TM 模频率闭式 + 最长边半波长 preflight。

模块面（round4 中件包一 HS-3 规格）：
- rect_cavity_modes：矩形腔谐振频率闭式筛查，
  f_mnp = (c0/(2·√εr))·√((m/a)² + (n/b)² + (p/h)²)（介质 εr 显式，c→c0/√εr）。
  **复用共享内核**：面内 (m,n) 频谱网格单源取 core/pdn.py plane_cavity_modes
  （round4 决议"与 PDN 平面腔模同式族共享内核"），z 向贡献
  f_p = p·c0/(2·h·√εr) 按正交恒等式 f_mnp² = f_mn² + f_p² 用 math.hypot
  合成——(m/a,n/b) 公式不在本文件重复（#112 家族：公式单源），pdn.py 只读不改。
- shield_cavity_preflight：courtyard(a,b) + 有效高度 h（元件最大高度/罩内
  净高，取大者责任在调用方）+ εr + 关注频带 → verdict + 带内腔模表 +
  分腔/吸波片建议文档化字段。门判据（预声明，#122）：**最长边几何 <
  λ_min/2（λ_min = c0/(f_max·√εr)）→ pass**；否则 fail 并列出前 n_report 个
  带内模式（f_min ≤ f ≤ f_max，升序）。

容许模集（建模口径，#1b 审计留痕）：本筛查按频率枚举 TE 容许超集
  {(m, n, p) : m,n ≥ 0 且 (m,n) ≠ (0,0), p ≥ 1}：
- TE_mnp（E_z=0）：Hz ∝ cos(mπx/a)cos(nπy/b)·sin(pπz/h)——z 壁法向 B 要求
  sin(pπz/h) ⇒ p ≥ 1；k_c ≠ 0 ⇒ (m,n) ≠ (0,0)（故 TE_100/TE_00p 类不存在，
  封闭盒主模是 TE_101 族，与教科书一致）。
- TM_mnp（H_z=0）：E_z ∝ sin(mπx/a)sin(nπy/b)sin(pπz/h)——六壁切向 E=0
  ⇒ 全部指数 ≥ 1；同指数 TM 与 TE 同频（闭式只含指数二次型），频率值是
  TE 容许集的子集，不重复枚举。
- (0,0,p) p≥1 与一切 p=0 三元组经 Maxwell 方程直验非平凡场不存在
  （∇×H=0 ⇒ E=0 ⇒ 违反 Faraday），已排除。
- 封闭盒假设是预声明口径：罩-板开放侧壁结构存在 p≈0 平板腔模（频率不高于
  封闭盒同指数模），开放结构应以 pdn.plane_cavity_modes 作保守补充筛查。

门判据与波导截止的等价性：任一容许模频率 ≥ c0/(2√εr·最长边)，故
  最长边 < λ_min/2 ⟺ 全部腔模频率 > f_max ⟺ 带内零腔模（充分条件成立，
  单测钉）。法源：f_c(TE10) = c0/(2·a·√εr) 矩形波导截止式（D. M. Pozar,
  Microwave Engineering, 4th ed., Wiley 2012, Ch.3）与腔模闭式（同书
  Ch.6 矩形谐振腔章）；最长边半波长筛查为屏蔽腔 EMC 工程口径。

如实声明（不替用户放宽）：εr 取有效介电常数的责任在调用方（同 pdn.py
口径）；verdict 只按几何判据二值裁决，带内模式表为空不自动翻 pass
（窄带可能几何违例但带内恰无模式——模式表与判据独立呈现，裁决权在
调用方）。简并：a=b=h 立方腔频率只依赖 (m,n,p) 置换不变量（容许集非
置换不变，同频承载于容许置换组，单测钉简并组计数）。

纯函数零 IO；不进 calculators 注册表（免 #231 注册表消费者三表同步，
参照 core/rwg_mmt.py 先例）；不定义 __all__（公开 API 快照只钉带
__all__ 模块）。
精度档案：knowledge/precision_profiles.yaml#shield_cavity_mode（行为=WARN，last_verified=2026-09-28）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from rfauto.core.pdn import C0, plane_cavity_modes

# 单次扫描三元组总数上限（防 f_max 痴肥把网格扫爆；超限显式 ValueError
# 而非静默长跑——扫描规模是调用方责任，模块只守底线）。
_MAX_SCAN_TRIPLES = 1_000_000

_SUGGEST_PARTITION = (
    "分腔 partition：沿最长边方向加屏蔽隔板/结构墙把腔划分为子腔，"
    "使各子腔最长边 < λ_min/2（λ_min=c0/(f_max·√εr)）"
)
_SUGGEST_ABSORBER = (
    "吸波片 absorber：腔内贴装吸波材料压低谐振 Q——只抑制谐振 buildup 幅度，"
    "不改谐振频率位置（对带内模式是缓解不是消除）"
)


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _positive(value: float, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {value!r}")
    return out


def _mode_order(value: object, name: str) -> int:
    """模阶收敛为非负 int：bool/非整数/负数一律 ValueError（截断拒绝）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    try:
        out = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}") from exc
    if out != value:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    if out < 0:
        raise ValueError(f"{name} 必须为非负整数，实际 {value!r}")
    return out


@dataclass(frozen=True)
class ShieldCavityMode:
    """矩形腔模 (m, n, p) 及其谐振频率（按 f_hz 升序参与排序）。"""

    m: int
    n: int
    p: int
    f_hz: float

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {"m": self.m, "n": self.n, "p": self.p, "f_hz": self.f_hz}


def rect_cavity_modes(
    a_m: float,
    b_m: float,
    h_m: float,
    er: float,
    m_max: int,
    n_max: int,
    p_max: int,
) -> list[ShieldCavityMode]:
    """矩形封闭腔模频率闭式筛查（TE 容许超集，f_hz 升序）。

    f_mnp = (c0/(2·√εr))·√((m/a)² + (n/b)² + (p/h)²)。面内 (m,n) 网格经
    pdn.plane_cavity_modes 取得（单源复用），z 向按正交恒等式
    f_mnp = hypot(f_mn, f_p)、f_p = p·c0/(2·h·√εr) 合成（hypot(x, y) 即
    √(x²+y²)，数值口径见模块 docstring 容许模集节）。

    Args:
        a_m / b_m / h_m: 腔三边长（m，正数）。
        er: 相对介电常数（正数；有效介电常数责任在调用方）。
        m_max / n_max: x/y 方向最高模阶（非负整数，不同时为 0）。
        p_max: z 方向最高模阶（正整数——p ≥ 1 才有容许模）。

    Returns:
        ShieldCavityMode 列表（f_hz 升序）。
    """
    a = _positive(a_m, "a_m")
    b = _positive(b_m, "b_m")
    h = _positive(h_m, "h_m")
    eps = _positive(er, "er")
    mm = _mode_order(m_max, "m_max")
    nn = _mode_order(n_max, "n_max")
    pp = _mode_order(p_max, "p_max")
    if mm == 0 and nn == 0:
        raise ValueError(f"m_max=n_max=0 时无容许模（(m,n)≠(0,0)），实际 ({m_max!r}, {n_max!r})")
    if pp < 1:
        raise ValueError(f"p_max 必须 ≥1（容许模要求 p≥1），实际 {p_max!r}")
    if (mm + 1) * (nn + 1) * pp > _MAX_SCAN_TRIPLES:
        raise ValueError(
            f"扫描规模 (m_max+1)·(n_max+1)·p_max={(mm + 1) * (nn + 1) * pp} 超上限 {_MAX_SCAN_TRIPLES}，"
            "请收窄模阶"
        )
    # 面内网格：单源取 PDN 平面腔内核（升序返回，(0,0) 直流模已被排除）。
    plane = plane_cavity_modes(a, b, eps, mm, nn)
    f_p_unit = C0 / (2.0 * math.sqrt(eps) * h)
    modes: list[ShieldCavityMode] = []
    for p in range(1, pp + 1):
        f_p = p * f_p_unit
        for entry in plane:
            modes.append(
                ShieldCavityMode(entry.m, entry.n, p, math.hypot(entry.f_hz, f_p))
            )
    modes.sort(key=lambda mode: mode.f_hz)
    return modes


@dataclass(frozen=True)
class ShieldCavityVerdict:
    """屏蔽腔 preflight 结果（verdict + 全部中间量，不替用户放宽判据）。"""

    verdict: str  # "pass" | "fail"
    courtyard_a_m: float
    courtyard_b_m: float
    height_m: float
    er: float
    f_min_hz: float
    f_max_hz: float
    longest_edge_m: float  # max(a, b, h)
    lambda_min_m: float  # c0/(f_max·√εr)（介质内最短波长）
    threshold_m: float  # λ_min/2（几何判据阈）
    margin_m: float  # threshold − longest_edge（负=违例量）
    scan_orders: tuple[int, int, int]  # 自动导出的 (m_max, n_max, p_max)
    n_modes_in_band: int  # 带内模式总数（可 > len(modes)）
    modes: tuple[ShieldCavityMode, ...]  # 前 n_report 个带内模式（升序）
    suggestions: tuple[str, ...]  # 分腔/吸波片建议（pass 时为空）

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可直接渲染的字典（递归含模式表）。"""
        return {
            "verdict": self.verdict,
            "courtyard_a_m": self.courtyard_a_m,
            "courtyard_b_m": self.courtyard_b_m,
            "height_m": self.height_m,
            "er": self.er,
            "f_min_hz": self.f_min_hz,
            "f_max_hz": self.f_max_hz,
            "longest_edge_m": self.longest_edge_m,
            "lambda_min_m": self.lambda_min_m,
            "threshold_m": self.threshold_m,
            "margin_m": self.margin_m,
            "scan_orders": list(self.scan_orders),
            "n_modes_in_band": self.n_modes_in_band,
            "modes": [mode.to_dict() for mode in self.modes],
            "suggestions": list(self.suggestions),
        }


def shield_cavity_preflight(
    courtyard_a_m: float,
    courtyard_b_m: float,
    height_m: float,
    er: float,
    f_min_hz: float,
    f_max_hz: float,
    n_report: int = 8,
) -> ShieldCavityVerdict:
    """屏蔽腔 preflight：courtyard(a,b)+有效高度 h+εr+关注频带 → verdict+模式表。

    判据（预声明，#122）：longest_edge < λ_min/2 → "pass"；否则 "fail"，
    suggestions 给分腔/吸波片两条文档化建议。模式表列出带内
    （f_min ≤ f ≤ f_max）前 n_report 个模式（升序）；n_modes_in_band 是
    带内总数（截断时 > len(modes)）。扫描阶自动导出为覆盖 f_max 的最小
    整数阶（m ≤ 2·a·f_max·√εr/c0 上取整，单轴独立，额外阶被带内过滤
    无害吸收），随 scan_orders 落盘保证可复现。

    Args:
        courtyard_a_m / courtyard_b_m: 屏蔽域 courtyard 两边长（m，正数）。
        height_m: 腔有效高度（m，正数；元件最大高度或罩内净高，取大者
            责任在调用方）。
        er: 相对介电常数（正数）。
        f_min_hz / f_max_hz: 关注频带（Hz，0 < f_min ≤ f_max）。
        n_report: 模式表最多列出的模式数（正整数）。

    Returns:
        ShieldCavityVerdict（verdict="pass" 当 longest_edge < threshold，
        严格小于；恰等于阈值判 fail，margin_m=0 留痕）。
    """
    a = _positive(courtyard_a_m, "courtyard_a_m")
    b = _positive(courtyard_b_m, "courtyard_b_m")
    h = _positive(height_m, "height_m")
    eps = _positive(er, "er")
    f_lo = _positive(f_min_hz, "f_min_hz")
    f_hi = _positive(f_max_hz, "f_max_hz")
    if f_lo > f_hi:
        raise ValueError(f"f_min_hz 不得大于 f_max_hz，实际 ({f_min_hz!r}, {f_max_hz!r})")
    report = _mode_order(n_report, "n_report")
    if report < 1:
        raise ValueError(f"n_report 必须 ≥1，实际 {n_report!r}")

    longest = max(a, b, h)
    lambda_min = C0 / (f_hi * math.sqrt(eps))
    threshold = lambda_min / 2.0
    margin = threshold - longest
    verdict = "pass" if longest < threshold else "fail"

    # 自动扫描阶：容许模 f ≤ f_max 要求单轴 m ≤ 2·a·f_max·√εr/c0，上取整
    # +max(1,·) 保证覆盖（浮点上取整的边界误差只会多扫，带内过滤吸收）。
    k_norm = 2.0 * f_hi * math.sqrt(eps) / C0
    m_max = max(1, math.ceil(a * k_norm))
    n_max = max(1, math.ceil(b * k_norm))
    p_max = max(1, math.ceil(h * k_norm))
    if (m_max + 1) * (n_max + 1) * p_max > _MAX_SCAN_TRIPLES:
        raise ValueError(
            f"关注频带对该几何过高：扫描规模 {(m_max + 1) * (n_max + 1) * p_max} "
            f"超上限 {_MAX_SCAN_TRIPLES}，请收窄 f_max_hz"
        )
    all_modes = rect_cavity_modes(a, b, h, eps, m_max, n_max, p_max)
    in_band = [mode for mode in all_modes if f_lo <= mode.f_hz <= f_hi]

    suggestions: tuple[str, ...] = ()
    if verdict == "fail":
        suggestions = (_SUGGEST_PARTITION, _SUGGEST_ABSORBER)
    return ShieldCavityVerdict(
        verdict=verdict,
        courtyard_a_m=a,
        courtyard_b_m=b,
        height_m=h,
        er=eps,
        f_min_hz=f_lo,
        f_max_hz=f_hi,
        longest_edge_m=longest,
        lambda_min_m=lambda_min,
        threshold_m=threshold,
        margin_m=margin,
        scan_orders=(m_max, n_max, p_max),
        n_modes_in_band=len(in_band),
        modes=tuple(in_band[:report]),
        suggestions=suggestions,
    )
