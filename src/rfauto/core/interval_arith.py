"""S-4 区间算术试点：mpmath.iv 定向舍入四则 + 单调函数区间化 + 传播小管线。

法源（铁律 5：来源写 docstring；裁判=独立路径，不自证，#118）：

- R.E. Moore, Interval Analysis (Prentice-Hall, 1966)——包含单调性
  （区间算术基本定理）：A ⊆ B ⇒ F(A) ⊆ F(B)；输入区间变宽 ⇒ 输出区间
  不窄（宽度单调性，由此直接导出）。区间运算结果恒包含真值范围
  （sound over-approximation），单测以「真值/真范围 ∈ 区间」恒等式钉。
- mpmath 1.3.0 文档（mpmath.iv：定向舍入区间算术；iv.dps 控制内部精度；
  闭式函数 iv.exp/iv.sqrt/iv.sin 返回严格包围区间）。本模块内部精度
  dps=30，float64 边界导出时端点各外扩 1 ulp（math.nextafter 反向），
  包含关系在 float 域保持严格。
- 本仓既有区间传播面（对拍对象，只读，#222 语境钉）：
  service/certify_design.py 的 Lipschitz 保守带——指标区间 =
  中心预测 ± Σ L_i·Δx_i（L 由有限差分网格估计，sound-but-conservative）。
- 对拍结论（试点留档，供后批 affine 形式 200 行简化裁决——本试点不做
  affine，Rump-Kashiwagi 2014，round3 [26]）：
  ① 仿射函数（f=ax+b）：区间算术与 Lipschitz 带等宽——区间算术无
     过保守，affine 形式的「相关性追踪」收益在纯仿射传播里为零；
  ② 非线性单调函数（单调域上 f=x²）：区间算术严格更窄（单调函数
     端点即精确范围；Lipschitz 带以中心切线斜率外推，系统性偏宽）；
  ③ 两者对同一例子包含关系一致（真值范围都在两者之内）。
  ⇒ 后批裁决输入：若传播链以仿射为主，affine 收益有限；相关性
  （同一变量多次出现，如 x−x、x·x 非单调段）才是 affine 的真实战场。
- mpmath 非核心依赖（lit-mining extras 的 sympy 附带，实测 1.3.0 在装）：
  惰性导入通道 _import_mpmath()（z3 先例 render_constraints.py），缺装抛
  ImportError 由调用方降级；mpmath 只在本模块出现（任务书面约束）。

接口：IVal dataclass（lo/hi float，to_dict JSON 可序列化）；全部纯函数
零 IO；数值 0.0 合法（判缺失 is not None，#364④）；除零/负开方/跨
单调分支显式 ValueError，不静默。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

__all__ = [
    "IVal",
    "iadd",
    "idiv",
    "iexp",
    "imul",
    "isin_monotone",
    "isqrt",
    "isub",
    "ival",
    "lipschitz_band",
    "point",
    "propagate",
]

#: mpmath 内部区间精度（十进制有效位；导出 float64 时端点再外扩 1 ulp）
_IV_DPS = 30


# ─── IVal：float 边界的封闭区间 ──────────────────────────────────────────────


@dataclass(frozen=True)
class IVal:
    """封闭区间 [lo, hi]（float 端点，保证包含真值范围——见 _to_ival）。

    IVal 本身即 JSON 友好形态（to_dict）；区间运算的严格性由 mpmath.iv
    在内部 dps=30 定向舍入保证，导出时端点外扩 1 ulp。
    """

    lo: float
    hi: float

    def width(self) -> float:
        """区间宽度 hi−lo（>=0）。"""
        return self.hi - self.lo

    def mid(self) -> float:
        """中点（无信息损失要求时作中心用）。"""
        return 0.5 * (self.lo + self.hi)

    def contains_point(self, x: float) -> bool:
        """点包含恒等式：lo ≤ x ≤ hi。"""
        return self.lo <= x <= self.hi

    def encloses(self, other: IVal) -> bool:
        """区间包含：other ⊆ self。"""
        return self.lo <= other.lo and other.hi <= self.hi

    def to_dict(self) -> dict:
        return {"lo": self.lo, "hi": self.hi, "width": self.width()}


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def ival(lo: float, hi: float) -> IVal:
    """构造并校验区间（lo ≤ hi、均有限；lo==hi 退化为点区间合法）。"""
    lo_ = _finite(lo, "lo")
    hi_ = _finite(hi, "hi")
    if lo_ > hi_:
        raise ValueError(f"区间非法：lo={lo_} > hi={hi_}")
    return IVal(lo=lo_, hi=hi_)


def point(x: float) -> IVal:
    """点区间 [x, x]（标量进区间管线的便捷入口）。"""
    return ival(x, x)


# ─── mpmath 惰性导入通道（唯一 import 点；#139：测试 monkeypatch 本函数钉通道）──


def _import_mpmath() -> Any:
    """返回 mpmath 模块；缺装抛 ImportError——由调用方降级，不外泄。

    单独成函数便于测试 monkeypatch 钉通道（#139 同族纪律：不依赖真实
    卸载）。每次调用走 sys.modules 缓存，开销可忽略。
    """
    import mpmath

    return mpmath


def _iv() -> Any:
    """取 iv 区间命名空间并确保内部精度（幂等设置）。"""
    mpmath = _import_mpmath()
    mpmath.iv.dps = _IV_DPS
    return mpmath.iv


def _widen_ulp(value: float, direction: int) -> float:
    """端点外扩 1 ulp（direction<0 向下 / >0 向上），float 导出保严格。"""
    return math.nextafter(value, -math.inf if direction < 0 else math.inf)


def _to_ival(mp_interval: Any) -> IVal:
    """mpmath.iv 区间 → IVal：float 端点各外扩 1 ulp（包含关系不丢）。"""
    a = float(mp_interval.a)
    b = float(mp_interval.b)
    return IVal(lo=_widen_ulp(a, -1), hi=_widen_ulp(b, +1))


def _to_iv_interval(x: IVal) -> Any:
    """IVal → mpmath.iv 区间（float→mpf 二进制精确转换）。"""
    iv = _iv()
    return iv.mpf([x.lo, x.hi])


# ─── 区间四则（Moore 1966；mpmath.iv 定向舍入） ──────────────────────────────


def iadd(a: IVal, b: IVal) -> IVal:
    """[a.lo,a.hi] + [b.lo,b.hi] = [a.lo+b.lo, a.hi+b.hi]（定向舍入包围）。"""
    _ival_pair_guard(a, b)
    return _to_ival(_to_iv_interval(a) + _to_iv_interval(b))


def isub(a: IVal, b: IVal) -> IVal:
    """区间减法 [a.lo−b.hi, a.hi−b.lo]。"""
    _ival_pair_guard(a, b)
    return _to_ival(_to_iv_interval(a) - _to_iv_interval(b))


def imul(a: IVal, b: IVal) -> IVal:
    """区间乘法（四端点积取 min/max，mpmath.iv 定向舍入）。"""
    _ival_pair_guard(a, b)
    return _to_ival(_to_iv_interval(a) * _to_iv_interval(b))


def idiv(a: IVal, b: IVal) -> IVal:
    """区间除法；除数含 0（b.lo ≤ 0 ≤ b.hi）显式 ValueError，不产无穷区间。"""
    _ival_pair_guard(a, b)
    if b.lo <= 0.0 <= b.hi:
        raise ValueError(f"除数区间 [{b.lo}, {b.hi}] 含 0——结果无界，本试点不产无穷区间")
    return _to_ival(_to_iv_interval(a) / _to_iv_interval(b))


def _ival_pair_guard(a: object, b: object) -> None:
    """运算入参守卫：两端必须是 IVal。"""
    if not isinstance(a, IVal) or not isinstance(b, IVal):
        raise ValueError("区间运算入参必须为 IVal（用 ival()/point() 构造）")


# ─── 单调函数区间化（正单调域试点） ──────────────────────────────────────────


def iexp(a: IVal) -> IVal:
    """exp 单调递增全域：[exp(lo), exp(hi)]（iv 定向舍入严格包围）。"""
    if not isinstance(a, IVal):
        raise ValueError("入参必须为 IVal")
    return _to_ival(_iv().exp(_to_iv_interval(a)))


def isqrt(a: IVal) -> IVal:
    """sqrt 单调递增、定义域 [0,∞)：lo<0 显式 ValueError。"""
    if not isinstance(a, IVal):
        raise ValueError("入参必须为 IVal")
    if a.lo < 0.0:
        raise ValueError(f"sqrt 定义域要求 lo ≥ 0，得到 [{a.lo}, {a.hi}]")
    return _to_ival(_iv().sqrt(_to_iv_interval(a)))


def isin_monotone(a: IVal) -> IVal:
    """sin 在单个单调分支内的严格包围（跨分支显式拒绝，不产过保守外包围）。

    递增分支 [−π/2+2πk, π/2+2πk]、递减分支 [π/2+2πk, 3π/2+2πk]。区间
    必须整支落在同一分支内（端点严格内缩守卫——恰在分支端点的浮点
    边界情形拒绝，保守但试点可接受）；跨分支调用方应走
    certify_design Lipschitz 外包围路线（本模块 docstring 对拍结论③）。
    """
    if not isinstance(a, IVal):
        raise ValueError("入参必须为 IVal")
    mpmath = _import_mpmath()
    mp = mpmath.mp
    mp.dps = _IV_DPS
    lo_mp = mp.mpf(a.lo)  # float→mpf 二进制精确
    two_pi = 2 * mp.pi
    # 递增分支候选：k 由 lo 定
    k_inc = int(mp.floor((lo_mp + mp.pi / 2) / two_pi))
    inc_lo, inc_hi = -mp.pi / 2 + two_pi * k_inc, mp.pi / 2 + two_pi * k_inc
    # 递减分支候选：k 由 lo 定
    k_dec = int(mp.floor((lo_mp - mp.pi / 2) / two_pi))
    dec_lo, dec_hi = mp.pi / 2 + two_pi * k_dec, 3 * mp.pi / 2 + two_pi * k_dec

    def _strictly_inside(lo_bound: Any, hi_bound: Any) -> bool:
        """float 端点严格落在分支内（分支界外扩 1 ulp 后比较，浮点安全）。"""
        return a.lo > _widen_ulp(float(lo_bound), -1) and a.hi < _widen_ulp(
            float(hi_bound), +1
        )

    if not _strictly_inside(inc_lo, inc_hi) and not _strictly_inside(dec_lo, dec_hi):
        raise ValueError(
            f"区间 [{a.lo}, {a.hi}] 跨 sin 单调分支（或恰触分支端点）——"
            "本试点只做单调域严格包围，跨分支走 Lipschitz 外包围路线"
        )
    return _to_ival(_iv().sin(_to_iv_interval(a)))


# ─── 区间传播小管线（直线程序：命名区间 + 算子序列） ─────────────────────────

#: call 算子支持的函数名（单调域守卫在各自实现内）
_PIPELINE_FNS = ("exp", "sqrt", "sin")


def propagate(inputs: dict[str, IVal], ops: list[dict]) -> dict:
    """区间传播小管线：inputs 命名区间 + ops 直线程序 → 全部中间区间。

    ops 每步 {"op": "add"|"sub"|"mul"|"div", "out": 名, "a": 名, "b": 名}
    或 {"op": "call", "fn": "exp"|"sqrt"|"sin", "out": 名, "a": 名}。
    操作数必须已在 values 中（前序 out 或 inputs），缺键显式 ValueError。
    返回 {"values": {名: IVal}, "final": 末步 out}——values 为 IVal 对象
    （JSON 由调用方逐个 to_dict）。
    """
    values: dict[str, IVal] = dict(inputs)
    final: str | None = None
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise ValueError(f"ops[{i}] 必须为 dict")
        out = op.get("out")
        if out is None or not isinstance(out, str):
            raise ValueError(f"ops[{i}] 缺 out（str 命名）")
        kind = op.get("op")
        name_a = op.get("a")
        if name_a not in values:
            raise ValueError(f"ops[{i}] 操作数 a={name_a!r} 不在 inputs/前序 out 中")
        a = values[name_a]
        if kind == "call":
            fn = op.get("fn")
            if fn not in _PIPELINE_FNS:
                raise ValueError(f"ops[{i}] fn={fn!r} 不支持（{_PIPELINE_FNS}）")
            values[out] = {"exp": iexp, "sqrt": isqrt, "sin": isin_monotone}[fn](a)
        elif kind in ("add", "sub", "mul", "div"):
            name_b = op.get("b")
            if name_b not in values:
                raise ValueError(f"ops[{i}] 操作数 b={name_b!r} 不在 inputs/前序 out 中")
            fn = {"add": iadd, "sub": isub, "mul": imul, "div": idiv}[kind]
            values[out] = fn(a, values[name_b])
        else:
            raise ValueError(f"ops[{i}] op={kind!r} 不支持（add/sub/mul/div/call）")
        final = out
    if final is None:
        raise ValueError("ops 不能为空")
    return {"values": values, "final": final}


# ─── certify_design 口径对照带（只读对拍用；本仓既有面见 service/certify_design.py）


def lipschitz_band(center_value: float, radius: float) -> IVal:
    """certify_design 的 Lipschitz 保守带 [center−radius, center+radius]。

    service/certify_design.py 口径：radius = Σ L_i·Δx_i（L 有限差分估计）。
    本函数只是该带的 IVal 包装（对照/对拍便捷入口），不重实现 L 估计。
    """
    c = _finite(center_value, "center_value")
    r = _finite(radius, "radius")
    if r < 0.0:
        raise ValueError(f"radius 必须 >=0，得到 {r}")
    return ival(c - r, c + r)
