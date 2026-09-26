"""DP-3 物理标定锚注册表——纯求值内核（零 IO）。

规格：docs/plan_deepdive_specs_20260924.md §DP-3。锚 = (模板族 × 引擎对 ×
域) → (常量 | 曲线 | 公式)，描述引擎对系统偏差（PDK corner/compact model
类比）。本模块只做求值与域守卫，一切 IO（YAML 装载/provenance 路径核对）
在 infra/anchors_store.py，JSON 薄面在 service/anchors_service.py。

核心语义（消费者 API）：
- ``AnchorSet.resolve_anchor(anchor_id, params)`` ->
  ``{hit, value, source: anchor|fallback, version, domain_ok, ...}``；
  域外/未知/非 active 一律 source=fallback（结构化回退闭式，不抛）；
- ``AnchorSet.note_anchor_residual(anchor_id, point, observed)``：漂移检测，
  |残差| > max(3σ, 5%·|锚值|) → 内存面翻 stale + 告警字段（注册表运行时
  只读，落盘回填走人工 commit——Agent 写面隔离，仓内分层约定）。

求值安全（铁律 6/7 同源）：公式锚表达式只允许 build_library 词表能产出的
语法（常量/已声明变量/四则/幂、sqrt/log），复用 0cz register_symbolic_formula
的 AST 白名单校验器（core/calculators._validate_symbolic_node，单一白名单
源）后才 eval；拒绝任何经表达式字符串进入的任意代码。

曲线锚：pchip（Fritsch-Carlson 保单调三次插值，自含实现零 scipy 依赖）
+ 构造期单调断言 + ``extrapolate: forbidden`` 域外显式 ValueError
（cps_corner2d"不外推"同款）。

单源计数：EXPECTED_ANCHORS / EXPECTED_ANCHOR_COUNT 与 knowledge/anchors.yaml
同步维护（#231/#304 注册表消费者纪律；check_numbers 绑定建议见
runs/df6_dp3anchors/criteria.md 判据 d2）。
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# 首批锚单源（DP-3 P1，2026-09-24）：与 knowledge/anchors.yaml 逐条对应。
# 新增/退役锚：先改 anchors.yaml 再同步本单源 + 定向测试。
EXPECTED_ANCHORS = frozenset({
    "c3.l_via_h.openems-hfss-v1",
    "patch.f_dip_l.openems-v1",
    "patch.f_dip_l.hfss-v1",
    "cps.gamma_er.fdref-v1",
    "siw.w_eff.lit-v1",
    "c3.k_of_g.openems-hfss-v1",
})
EXPECTED_ANCHOR_COUNT = len(EXPECTED_ANCHORS)

#: 锚型与状态枚举（awaiting_data 为 P1 批预声明扩展：骨架锚 data 未回填）。
ANCHOR_KINDS = ("constant", "curve", "formula", "pointer")
ANCHOR_STATUSES = ("active", "stale", "experimental", "retired",
                   "awaiting_data")

#: anchor_id 形如 <族>.<量>.<引擎对|来源>-v<N>（引擎段允许连字符）。
_ANCHOR_ID_RE = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_][a-z0-9_\-]*)+-v\d+$")

#: 漂移检测门：|残差| > max(3σ, 5%·|锚值|) → stale（规格书 §3 口径）。
_RESIDUAL_SIGMA_FACTOR = 3.0
_RESIDUAL_REL_FLOOR = 0.05

_UNCERTAINTY_RELATIVE_KINDS = frozenset({"relative"})


# ── 公式锚：AST 白名单（复用 0cz 校验器，单一白名单源）────────────────────

def compile_anchor_formula(expr: str, variables: Sequence[str]) -> Any:
    """把公式锚表达式编译为可求值代码对象（^→** 归一后过 0cz 白名单）。

    词表与 core/calculators.register_symbolic_formula 完全一致：数值常量、
    已声明变量、+ - * / **、一元 ±、sqrt/log 单参调用；其余一律 ValueError
    （显式拒绝，不静默降级）。
    """
    from rfauto.core.calculators import _validate_symbolic_node

    try:
        tree = ast.parse(str(expr).replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"公式锚表达式语法错误: {expr!r}（{exc}）") from exc
    _validate_symbolic_node(tree, frozenset(variables))
    return compile(tree, f"<anchor:{expr}>", "eval")


def eval_anchor_formula(code: Any, namespace: Mapping[str, float]) -> float:
    """确定性求值公式锚（纯 float 闭式；sqrt/log 来自 math，无内建）。

    env 无 __builtins__、代码对象已过 AST 白名单——eval 面只暴露白名单
    词表（安全语义同 0cz _eval_symbolic_terms）。
    """
    env = {"sqrt": math.sqrt, "log": math.log, "__builtins__": {}}
    return float(eval(code, env, dict(namespace)))


# ── 曲线锚：pchip（Fritsch-Carlson 保单调三次插值，自含实现）───────────────

def _pchip_slopes(xs: list[float], ys: list[float]) -> list[float]:
    """Fritsch-Carlson 端点+内部斜率（scipy PchipInterpolator 同公式）。"""
    n = len(xs)
    if n < 2:
        raise ValueError("曲线锚至少需要 2 个点")
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    if any(hi <= 0.0 for hi in h):
        raise ValueError("曲线锚 x 必须严格递增")
    delta = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    if n == 2:
        return [delta[0], delta[0]]

    def _edge(d0: float, d1: float, h0: float, h1: float) -> float:
        # scipy _edge_case：端点斜率符号/幅值钳制保单调
        m = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if math.copysign(1.0, m) != math.copysign(1.0, d0):
            return 0.0
        if (math.copysign(1.0, d0) != math.copysign(1.0, d1)
                and abs(m) > 3.0 * abs(d0)):
            return 3.0 * d0
        return m

    m = [0.0] * n
    m[0] = _edge(delta[0], delta[1], h[0], h[1])
    m[-1] = _edge(delta[-1], delta[-2], h[-1], h[-2])
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0.0:
            m[i] = 0.0
        else:
            # 加权调和平均（Fritsch-Carlson），同号 δ 下保单调
            w1 = 2.0 * h[i] + h[i - 1]
            w2 = h[i] + 2.0 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    return m


def eval_pchip(xs: Sequence[float], ys: Sequence[float], x: float,
               slopes: list[float] | None = None) -> float:
    """pchip 单点求值（Hermite 基）；x 必须落在 [xs[0], xs[-1]] 内。"""
    xs_l = [float(v) for v in xs]
    ys_l = [float(v) for v in ys]
    if slopes is None:
        slopes = _pchip_slopes(xs_l, ys_l)
    if not xs_l[0] <= float(x) <= xs_l[-1]:
        raise ValueError(
            f"曲线锚域外求值 x={x} 超出 [{xs_l[0]}, {xs_l[-1]}]"
            "（extrapolate: forbidden，不外推）")
    # 线性定位区间（锚点数 ≤ 数十，无需二分）
    i = 0
    for j in range(len(xs_l) - 1):
        if x <= xs_l[j + 1] or j == len(xs_l) - 2:
            i = j
            break
    hi_ = xs_l[i + 1] - xs_l[i]
    t = (float(x) - xs_l[i]) / hi_
    h00 = (1.0 + 2.0 * t) * (1.0 - t) ** 2
    h10 = t * (1.0 - t) ** 2
    h01 = t * t * (3.0 - 2.0 * t)
    h11 = t * t * (t - 1.0)
    return float(h00 * ys_l[i] + h10 * hi_ * slopes[i]
                 + h01 * ys_l[i + 1] + h11 * hi_ * slopes[i + 1])


# ── 锚记录与锚集 ───────────────────────────────────────────────────────────

@dataclass
class AnchorRecord:
    """单条锚（dict 背书，构造期做求值阻断性校验）。"""

    anchor_id: str
    kind: str
    status: str
    version: int
    template_family: list[str]
    engine_pair: dict[str, str] | None
    quantity: dict[str, Any]
    value: float | None
    expr: str | None
    variables: list[str] | None
    points: list[dict[str, float]] | None
    interp: dict[str, Any] | None
    axis: dict[str, str] | None
    uncertainty: dict[str, Any] | None
    domain: dict[str, list[float]] | None
    provenance: dict[str, Any]
    registered_at: str | None
    last_verified: dict[str, Any] | None
    fallback: str | None
    consumers: list[str]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    _formula_code: Any = field(default=None, repr=False)
    _curve_xs: list[float] = field(default_factory=list, repr=False)
    _curve_ys: list[float] = field(default_factory=list, repr=False)
    _curve_slopes: list[float] = field(default_factory=list, repr=False)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AnchorRecord:
        anchor_id = str(raw.get("anchor_id") or "")
        if not _ANCHOR_ID_RE.match(anchor_id):
            raise ValueError(
                f"anchor_id 不合规格 <族>.<量>.<引擎对>-v<N>: {anchor_id!r}")
        kind = str(raw.get("kind") or "")
        if kind not in ANCHOR_KINDS:
            raise ValueError(f"未知锚型 kind={kind!r}（{anchor_id}）")
        status = str(raw.get("status") or "")
        if status not in ANCHOR_STATUSES:
            raise ValueError(f"未知状态 status={status!r}（{anchor_id}）")
        version = int(anchor_id.rsplit("-v", 1)[1])
        rec = cls(
            anchor_id=anchor_id,
            kind=kind,
            status=status,
            version=version,
            template_family=[str(t) for t in (raw.get("template_family") or [])],
            engine_pair=raw.get("engine_pair"),
            quantity=raw.get("quantity") or {},
            value=raw.get("value"),
            expr=raw.get("expr"),
            variables=list(raw.get("variables") or []) or None,
            points=list(raw.get("points") or []) or None,
            interp=raw.get("interp"),
            axis=raw.get("axis"),
            uncertainty=raw.get("uncertainty"),
            domain=raw.get("domain"),
            provenance=raw.get("provenance") or {},
            registered_at=raw.get("registered_at"),
            last_verified=raw.get("last_verified"),
            fallback=raw.get("fallback"),
            consumers=[str(c) for c in (raw.get("consumers") or [])],
            raw=dict(raw),
        )
        rec._prepare_evaluator()
        return rec

    # 构造期求值准备（阻断性问题 fail-fast；schema/provenance 校验在 infra）

    def _prepare_evaluator(self) -> None:
        if self.kind == "constant":
            if self.value is None:
                raise ValueError(f"constant 锚缺 value: {self.anchor_id}")
            self.value = float(self.value)
        elif self.kind == "formula":
            if not self.expr or not self.variables:
                raise ValueError(
                    f"formula 锚缺 expr/variables: {self.anchor_id}")
            self._formula_code = compile_anchor_formula(
                str(self.expr), self.variables)
        elif self.kind == "curve":
            pts = self.points or []
            if not pts:
                if self.status != "awaiting_data":
                    raise ValueError(
                        f"curve 锚无 points 只允许 awaiting_data: "
                        f"{self.anchor_id}")
                return
            self._curve_xs = [float(p["x"]) for p in pts]
            self._curve_ys = [float(p["y"]) for p in pts]
            # 单调断言（hairpin 先例）：非严格单调（同号或零），符号混杂即拒
            deltas = [b - a for a, b in
                      zip(self._curve_ys, self._curve_ys[1:], strict=False)]
            if any(d > 0.0 for d in deltas) and any(d < 0.0 for d in deltas):
                raise ValueError(
                    f"曲线锚 points 非单调: {self.anchor_id}"
                    "（单调断言失败，疑似判读/转录错误）")
            self._curve_slopes = _pchip_slopes(self._curve_xs,
                                               self._curve_ys)
            if not self.axis or not self.axis.get("param"):
                raise ValueError(
                    f"curve 锚缺 axis.param: {self.anchor_id}")
            method = (self.interp or {}).get("method", "pchip")
            if method != "pchip":
                raise ValueError(
                    f"曲线锚仅支持 pchip 插值，收到 {method!r}"
                    f"（{self.anchor_id}）")

    # 求值

    @property
    def curve_axis_param(self) -> str:
        if not self.axis or not self.axis.get("param"):
            raise ValueError(f"curve 锚缺 axis.param: {self.anchor_id}")
        return str(self.axis["param"])

    def check_domain(self, params: Mapping[str, float]) -> bool:
        """参数盒守卫；domain=null（未定维）恒 True（曲线锚另受点域约束）。"""
        if self.kind == "curve" and self._curve_xs:
            # 曲线自变量必须落在点域内（extrapolate: forbidden 的结构化面；
            # 直接 evaluate 走 eval_pchip 的显式 ValueError，双保险）
            key = self.curve_axis_param
            if key not in params:
                return False
            v = float(params[key])
            if not (self._curve_xs[0] <= v <= self._curve_xs[-1]):
                return False
        if not self.domain:
            return True
        for key, box in self.domain.items():
            if key not in params:
                return False
            lo, hi = float(box[0]), float(box[1])
            v = float(params[key])
            if not (lo <= v <= hi) or not math.isfinite(v):
                return False
        return True

    def evaluate(self, params: Mapping[str, float]) -> float | None:
        """域内求值（调用方先过 check_domain；曲线域外抛 ValueError）。"""
        if self.kind == "constant":
            return self.value
        if self.kind == "formula":
            ns: dict[str, float] = {}
            for var in self.variables or []:
                if var not in params:
                    raise ValueError(
                        f"公式锚缺变量 {var}: {self.anchor_id}")
                ns[var] = float(params[var])
            return eval_anchor_formula(self._formula_code, ns)
        if self.kind == "curve":
            if not self.points:
                raise ValueError(
                    f"曲线锚数据未回填（awaiting_data）: {self.anchor_id}")
            key = self.curve_axis_param
            if key not in params:
                raise ValueError(f"曲线锚缺自变量 {key}: {self.anchor_id}")
            return eval_pchip(self._curve_xs, self._curve_ys,
                              float(params[key]), self._curve_slopes)
        return None  # pointer：值在模型档案，不就地求值

    def uncertainty_sigma_abs(self, expected: float) -> float | None:
        """不确定度绝对值（relative 按期望值折算；缺失/为 None → None）。"""
        unc = self.uncertainty
        if not unc or unc.get("value") is None:
            return None
        sigma = float(unc["value"])
        if str(unc.get("kind") or "") in _UNCERTAINTY_RELATIVE_KINDS:
            sigma = sigma * abs(expected)
        return sigma

    def to_dict(self) -> dict[str, Any]:
        """JSON 安全全量记录（raw 透传 + 解析字段）。"""
        out = dict(self.raw)
        out["version"] = self.version
        return out


class AnchorSet:
    """锚集合（纯内存；由 infra 装载层喂 raw dict 列表）。"""

    def __init__(self, raw_anchors: Any = None) -> None:
        self._records: dict[str, AnchorRecord] = {}
        self.load_errors: list[str] = []
        for raw in list(raw_anchors or []):
            try:
                rec = AnchorRecord.from_dict(raw)
            except (ValueError, TypeError, KeyError) as exc:
                # 单锚坏不拖垮整表（#105 best-effort）；错误留痕供 validate 报
                self.load_errors.append(f"{raw.get('anchor_id')!r}: {exc}")
                continue
            if rec.anchor_id in self._records:
                self.load_errors.append(
                    f"{rec.anchor_id!r}: 重复 anchor_id（后者丢弃）")
                continue
            self._records[rec.anchor_id] = rec

    # 容器语义

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, anchor_id: object) -> bool:
        return anchor_id in self._records

    def get(self, anchor_id: str) -> AnchorRecord | None:
        return self._records.get(anchor_id)

    @property
    def anchor_ids(self) -> list[str]:
        return sorted(self._records)

    @property
    def records(self) -> list[AnchorRecord]:
        return [self._records[k] for k in sorted(self._records)]

    # 消费者 API

    def resolve_anchor(self, anchor_id: str,
                       params: Mapping[str, float] | None = None) -> dict[str, Any]:
        """规格书核心语义：{hit, value, source: anchor|fallback, version,
        domain_ok}；域外/未知/非可消费状态一律结构化 fallback（不抛）。"""
        rec = self._records.get(str(anchor_id))
        if rec is None:
            return {"hit": False, "value": None, "source": "fallback",
                    "version": None, "domain_ok": False, "stale": False,
                    "reason": "unknown_anchor", "anchor_id": str(anchor_id)}
        out: dict[str, Any] = {
            "hit": True, "anchor_id": rec.anchor_id, "kind": rec.kind,
            "version": rec.version, "status": rec.status,
            "stale": rec.status == "stale", "source": "anchor",
            "domain_ok": True, "value": None, "reason": None,
        }
        if rec.status in ("awaiting_data", "retired"):
            out.update(hit=False, source="fallback", domain_ok=False,
                       reason=rec.status)
            return out
        params = dict(params or {})
        if rec.kind == "formula" and rec.variables:
            missing = [v for v in rec.variables if v not in params]
            if missing:
                out.update(source="fallback", domain_ok=False,
                           reason=f"missing_params:{','.join(missing)}")
                return out
        if not rec.check_domain(params):
            out.update(source="fallback", domain_ok=False,
                       reason="out_of_domain")
            return out
        out["value"] = rec.evaluate(params)
        return out

    def note_anchor_residual(self, anchor_id: str,
                             point: Mapping[str, float],
                             observed: float) -> dict[str, Any]:
        """漂移检测：|残差| > max(3σ, 5%·|锚值|) → 内存面翻 stale + 告警。

        注册表运行时只读（YAML 零改写）；落盘回填走人工 commit/ingest
        （P2 战役 ingest 自动回填挂点）。
        """
        res = self.resolve_anchor(anchor_id, point)
        base: dict[str, Any] = {
            "ok": False, "anchor_id": str(anchor_id),
            "point": dict(point), "observed": float(observed),
            "expected": None, "residual": None, "threshold": None,
            "stale": False, "alarm": None,
        }
        if not res["hit"] or res["value"] is None or not res["domain_ok"]:
            base["reason"] = res.get("reason") or "not_resolvable"
            return base
        expected = float(res["value"])
        residual = float(observed) - expected
        sigma = self._records[str(anchor_id)].uncertainty_sigma_abs(expected)
        parts = []
        if sigma is not None:
            parts.append(_RESIDUAL_SIGMA_FACTOR * sigma)
        parts.append(_RESIDUAL_REL_FLOOR * abs(expected))
        threshold = max(parts)
        stale = abs(residual) > threshold
        base.update(ok=True, expected=expected, residual=residual,
                    threshold=threshold, stale=stale,
                    alarm=("residual_exceeds_max(3sigma,5%)——锚疑似 stale，"
                           "请登记复验" if stale else None))
        if stale:
            rec = self._records[str(anchor_id)]
            rec.status = "stale"
            rec.raw["status"] = "stale"
        return base


# ── 活注册表接插点（DP-3 第二批消费接线，df7 锚消费第二批）──────────────────
# core 是分层 leaf（零 IO，不 import infra）：由上层装载层 infra/anchors_store
# 在模块导入时把 load_anchors 注册为 provider（infra→core 合法方向）。消费者
# （core/calculators 等）经 live_anchor_set() 惰性取用；provider 未注册
# （进程未导入锚装载层）或调用失败 → 返回 None，消费者走字面/闭式回退
# （零行为变化兜底，#105 best-effort：锚系统任何故障不阻塞业务主路径）。

_LIVE_SET_PROVIDER: Callable[[], AnchorSet] | None = None


def set_live_anchor_set_provider(
        provider: Callable[[], AnchorSet] | None) -> None:
    """注册活注册表 provider（infra/anchors_store 导入时调用；测试可替换）。"""
    global _LIVE_SET_PROVIDER
    _LIVE_SET_PROVIDER = provider


def live_anchor_set() -> AnchorSet | None:
    """取活锚注册表（惰性；provider 未注册/任何异常 → None，消费者走回退）。

    返回对象由装载层缓存（mtime 键），本函数不持有状态——重复调用共享同一
    AnchorSet；调用方只读消费（note_anchor_residual 的内存面翻 stale 语义
    归装载层缓存对象所有）。"""
    provider = _LIVE_SET_PROVIDER
    if provider is None:
        return None
    try:
        anchor_set = provider()
    except Exception:  # best-effort：provider 任何故障都走消费者回退（#105）
        return None
    return anchor_set if isinstance(anchor_set, AnchorSet) else None
