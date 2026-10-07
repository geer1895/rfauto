"""QM-11 多引擎差分测试 harness（纯函数，core 叶子，零 IO）。

规格：研究扩充 round16 QM-11（P2/M）——
"engine pair 矩阵自动发现 + FSV 门判 harness，DISAGREE 自动产 pointer 锚候选"。

四个组成面（同一 relation(input, out_a, out_b) 断言模式贯穿）：

1. **元变关系断言内核**（§1）：``check_metamorphic(kernel, inputs, transform,
   relation)``——对每个输入点求 out_a = kernel(x)、out_b = kernel(T(x))，
   relation(input, out_a, out_b) 返回**违例度量**（float，≤ tol 判过）。
   relation 永不抛"关系不满足"（违例走返回值），只对 harness 配置错误
   （轴不配对/缺键）抛 ValueError。
2. **物理等价变换关系库**（§2）：提供四族通用关系构造器，全部为纯闭包——
   - 无耗缩放/正齐次（common-mode 阻抗缩放：lossless 网络整体缩放 k，
     电学长度不变、阻抗量线性随 k）；
   - 频率轴翻转对称（实系数系统的偶幅度对称 |S(−f)| = |S(f)|）；
   - 单位制切换（波长-频率积 = 光速常数，mm·GHz 单位系不变量）；
   - golden 恒等（对钉死的独立来源参考值断言，transform=identity 退化形态）。
   被测轴与 QM-1 四族（互易/线性叠加/无源性/频移等价，见
   tests/unit/test_physics_invariants.py §4）**刻意不重叠**。
3. **FSV 门判**（§3）：``fsv_pair_gate``——消费 core/fsv.py（D12，IEEE
   1597.1 口径）的曲线比较度量，按 FsvGateSpec 阈值给 AGREE/DISAGREE/
   INDETERMINATE 三态判定；FSV 自身守卫炸（点数不足/无公共轴）如实记
   INDETERMINATE 带 reason，不伪造 AGREE 也不上抛（#105 降级不阻塞）。
4. **engine pair 矩阵自动发现 + pointer 锚候选**（§4）：``discover_engine_pairs``
   （全无序对 / reference 星型）+ ``pair_matrix_curves``（逐 pair FSV 门）+
   ``pair_matrix_scalar``（标量观测量逐 pair 相对差门，league_service
   delta_vs_ref 同语义）+ ``pointer_anchor_candidates``——只从 DISAGREE 行
   产 ``<族>.<量>.<引擎对>-v<N>`` pointer 锚候选 dict，形态对齐
   core/anchors.py 的双值分歧指针锚（kind="pointer"、quantity.values=
   {engine: value}、experimental、不就地写库——落库走注册链人工批次）。

分层：core 叶子，仅依赖 numpy + 标准库 + core/fsv.py，不 import 任何
rfauto 其它层（import-linter 契约）。

数值确定性：全部 numpy/stdlib 纯函数，无随机、无 IO、无时间依赖；同一
输入必得同一输出。harness 只做判定机制，不产生物理数字——所有阈值由
调用方显式声明（FsvGateSpec/rel_tol/tol），缺省值只作开箱档并在 docstring
声明（规则 7：数值只在确定性内核）。
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core.calc_families.registry import C_MM_GHZ
from rfauto.core.fsv import fsv

__all__ = [
    "ANCHOR_ID_RE",
    "FsvGateSpec",
    "RelationVerdict",
    "check_metamorphic",
    "discover_engine_pairs",
    "even_symmetry_relation",
    "fsv_pair_gate",
    "golden_identity_relation",
    "linear_scale_relation",
    "pair_matrix_curves",
    "pair_matrix_scalar",
    "pointer_anchor_candidates",
    "slugify",
    "wave_unit_product_relation",
]

#: pointer 锚候选 id 形态守卫（与 core/anchors.py _ANCHOR_ID_RE 同款，
#: 拷贝自该单源——core 内不允许反向 import 同层锚注册表造成环）。
ANCHOR_ID_RE = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_][a-z0-9_\-]*)+-v\d+$")

_AXIS_MATCH_TOL = 1e-6
_DISAGREE = "DISAGREE"
_AGREE = "AGREE"
_INDETERMINATE = "INDETERMINATE"


# --------------------------------------------------------------------------- #
# §1 元变关系断言内核
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RelationVerdict:
    """单输入点的元变关系判定（违例度量 ≤ tol 判过）。

    metric 含义由 relation 定义（通用约定：0 = 关系精确满足）；
    ok=False 即关系被违例——差分测试 harness 的**负例检出**语义。
    """

    relation: str
    ok: bool
    metric: float
    tol: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "ok": self.ok,
            "metric": self.metric,
            "tol": self.tol,
            "detail": self.detail,
        }


def check_metamorphic(
    kernel: Callable[[Any], Any],
    inputs: Sequence[Any],
    transform: Callable[[Any], Any],
    relation: Callable[[Any, Any, Any], float],
    *,
    tol: float,
    name: str = "metamorphic",
    detail_of: Callable[[Any], str] | None = None,
) -> list[RelationVerdict]:
    """对每个输入点执行"原样 vs 变换后"双求值并按 relation 判定。

    参数
    ----
    kernel   : 被测纯内核（单入参；多参数内核用 functools.partial/lambda 收口）
    inputs   : 输入点序列
    transform: 物理等价变换 T（恒等变换 = golden 恒等退化形态）
    relation : relation(input, out_a, out_b) -> 违例度量（float，≤ tol 判过）；
               只许对 harness 配置错误抛 ValueError，不许用异常表达关系违例
    tol      : 违例容差（判定阈值显式声明，不藏缺省魔法数）
    detail_of: 可选，从输入点生成 verdict.detail（定位用，best-effort）

    返回
    ----
    list[RelationVerdict]（与 inputs 等长，顺序保持）。
    """
    if tol < 0:
        raise ValueError(f"tol 必须 ≥ 0，得到 {tol!r}")
    verdicts: list[RelationVerdict] = []
    for point in inputs:
        out_a = kernel(point)
        out_b = kernel(transform(point))
        metric = float(relation(point, out_a, out_b))
        detail = str(detail_of(point)) if detail_of is not None else ""
        verdicts.append(
            RelationVerdict(
                relation=name,
                ok=bool(math.isfinite(metric) and metric <= tol),
                metric=metric,
                tol=float(tol),
                detail=detail,
            )
        )
    return verdicts


# --------------------------------------------------------------------------- #
# §2 物理等价变换关系库（与 QM-1 四族刻意不重叠的轴）
# --------------------------------------------------------------------------- #

def linear_scale_relation(
    get: Callable[[Any], float],
    *,
    scale_factor: float,
    rel_tol: float = 1e-3,
) -> Callable[[Any, Any, Any], float]:
    """正齐次（无耗缩放）关系：out(T_k(x)) == k · out(x)（相对差度量）。

    物理语义：lossless 网络common-mode 阻抗整体缩放 k ⇒ 阻抗量正齐次、
    电学长度不变。被测面示例：quarter_wave_transformer 的 z0_section_ohm。
    """

    def relation(point: Any, out_a: Any, out_b: Any) -> float:
        base = float(get(out_a))
        scaled = float(get(out_b))
        expected = scale_factor * base
        denom = max(abs(expected), 1e-300)
        return abs(scaled - expected) / denom / max(abs(rel_tol), 1e-300)

    return relation


def even_symmetry_relation(
    get_axis: Callable[[Any], Sequence[float]],
    get_series: Callable[[Any], Sequence[float]],
    *,
    tol: float = 1e-9,
) -> Callable[[Any, Any, Any], float]:
    """频率轴翻转对称关系：|series(−f)| == |series(f)|（偶幅度对称）。

    实系数系统的频响满足 S(−f) = conj(S(f)) ⇒ 幅度偶对称。配对语义：
    out_a 的轴点 ω 与 out_b 的轴点 **−ω** 配对（out_b 在翻转轴上采样），
    经各自轴排序后用 searchsorted 建 ω↔−ω 对应；翻转轴值集不闭合
    （轴点 −ω 在 out_b 轴上找不到，典型 = 内核轴口径漂移/变换没真翻转）
    属 harness 配置错误，抛 ValueError（非关系违例）。
    """

    def relation(point: Any, out_a: Any, out_b: Any) -> float:
        ax_a = np.asarray(get_axis(out_a), dtype=float).ravel()
        ax_b = np.asarray(get_axis(out_b), dtype=float).ravel()
        ya = np.asarray(get_series(out_a), dtype=float).ravel()
        yb = np.asarray(get_series(out_b), dtype=float).ravel()
        if ax_a.size != ya.size or ax_b.size != yb.size:
            raise ValueError("axis 与 series 长度不一致（harness 配置错误）")
        order_a = np.argsort(ax_a, kind="stable")
        order_b = np.argsort(ax_b, kind="stable")
        ax_a_s, ax_b_s = ax_a[order_a], ax_b[order_b]
        # 目标配对轴：out_a 每个轴点 ω 在 out_b 轴上找 −ω
        target = -ax_a_s
        idx = np.searchsorted(ax_b_s, target)
        idx_c = np.clip(idx, 0, max(ax_b_s.size - 1, 0))
        if not np.allclose(ax_b_s[idx_c], target, rtol=0.0, atol=_AXIS_MATCH_TOL):
            raise ValueError(
                "翻转轴值集不闭合：out_b 轴上找不到 −ω 配对点"
                f"（max|Δ|={float(np.max(np.abs(ax_b_s[idx_c] - target)))!r}）"
            )
        ya_s = np.abs(ya[order_a])
        yb_paired = np.abs(yb[order_b][idx_c])
        return float(np.max(np.abs(ya_s - yb_paired))) / max(abs(tol), 1e-300)

    return relation


def wave_unit_product_relation(
    get_input: Callable[[Any], float],
    get_output: Callable[[Any], float],
    *,
    expected_product: float = C_MM_GHZ,
    tol: float = 1e-2,
) -> Callable[[Any, Any, Any], float]:
    """单位制切换关系：input × output == 单位系不变量（波长-频率积=光速）。

    mm·GHz 单位系下 λ0[mm]·f[GHz] = 299.792458（C_MM_GHZ）；换单位系
    （µm·THz 等）乘积不变——输出对输入单位制的自洽性断言。双分支各自
    核验（violation = 两分支 |积−C| 的较大者），对输出级公共损坏不抵消
    （该关系是与常数 C 的绝对比较，非比值型）。tol 缺省 1e-2 覆盖内核
    3 位小数舍入 ×10GHz 级输入。
    """

    def relation(point: Any, out_a: Any, out_b: Any) -> float:
        expected = abs(float(expected_product))
        va = abs(float(get_input(point)) * float(get_output(out_a)) - expected)
        vb = abs(float(get_input(point)) * float(get_output(out_b)) - expected)
        return max(va, vb) / max(abs(tol), 1e-300)

    return relation


def golden_identity_relation(
    get: Callable[[Any], float],
    expected: float,
    *,
    tol: float = 1e-8,
) -> Callable[[Any, Any, Any], float]:
    """golden 恒等关系：out == 独立来源钉死的参考值（|差| 绝对度量）。

    transform 取恒等即退化成"内核输出 vs golden"回归断言；expected 必须
    来自独立来源（解析闭式/文献表值），禁用被测内核自身同源推导（#118
    同义反复裁判无效）。
    """

    def relation(point: Any, out_a: Any, out_b: Any) -> float:
        del point, out_b
        return abs(float(get(out_a)) - float(expected)) / max(abs(tol), 1e-300)

    return relation


# --------------------------------------------------------------------------- #
# §3 FSV 门判（消费 core/fsv.py，IEEE 1597.1 口径）
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class FsvGateSpec:
    """FSV 门阈值（显式声明，缺省只作开箱档）。

    max_grade_level : GDM Grade 上限（core/fsv 六级：1=Ex 2=VG 3=G 4=F 5=P 6=VP）
    max_spread      : GDM Spread 上限（覆盖 85% 点的最短相邻区间段长）
    max_gdm_mean    : 逐点 GDM 均值上限（None = 不启用该子门）
    """

    max_grade_level: int = 3
    max_spread: int = 3
    max_gdm_mean: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= int(self.max_grade_level) <= 6:
            raise ValueError(f"max_grade_level 须在 1..6，得到 {self.max_grade_level!r}")
        if not 1 <= int(self.max_spread) <= 6:
            raise ValueError(f"max_spread 须在 1..6，得到 {self.max_spread!r}")
        if self.max_gdm_mean is not None and float(self.max_gdm_mean) < 0:
            raise ValueError(f"max_gdm_mean 须 ≥ 0，得到 {self.max_gdm_mean!r}")


def fsv_pair_gate(
    freq_a: Sequence[float],
    val_a: Sequence[float],
    freq_b: Sequence[float],
    val_b: Sequence[float],
    gate: FsvGateSpec | None = None,
    *,
    n_points: int | None = None,
) -> dict[str, Any]:
    """单对曲线的 FSV 门判：AGREE / DISAGREE / INDETERMINATE 三态。

    INDETERMINATE = FSV 内核守卫拒判（点数不足/无公共轴区间等 ValueError
    族）——如实带 reason 返回，不伪造结论、不上抛（#105 判定面降级语义）。
    """
    spec = gate if gate is not None else FsvGateSpec()
    row: dict[str, Any] = {
        "gate": {"max_grade_level": spec.max_grade_level,
                 "max_spread": spec.max_spread, "max_gdm_mean": spec.max_gdm_mean},
        "decision": _INDETERMINATE,
        "reason": None,
        "grade_level": None,
        "spread": None,
        "gdm_mean": None,
        "adm_mean": None,
        "fdm_mean_abs": None,
    }
    try:
        result = fsv(freq_a, val_a, freq_b, val_b, n_points=n_points)
    except ValueError as exc:
        row["reason"] = f"fsv_rejected:{exc}"
        return row
    grade_level = int(result["gdm_grade_level"])
    spread = int(result["gdm_spread"])
    gdm_mean = float(result["gdm_mean"])
    row.update(
        grade_level=grade_level,
        spread=spread,
        gdm_mean=gdm_mean,
        adm_mean=float(result["adm_mean"]),
        fdm_mean_abs=float(result["fdm_mean_abs"]),
    )
    reasons: list[str] = []
    if grade_level > spec.max_grade_level:
        reasons.append(f"grade_level {grade_level} > {spec.max_grade_level}")
    if spread > spec.max_spread:
        reasons.append(f"spread {spread} > {spec.max_spread}")
    if spec.max_gdm_mean is not None and gdm_mean > float(spec.max_gdm_mean):
        reasons.append(f"gdm_mean {gdm_mean:.6g} > {spec.max_gdm_mean:.6g}")
    if reasons:
        row["decision"] = _DISAGREE
        row["reason"] = "; ".join(reasons)
    else:
        row["decision"] = _AGREE
    return row


# --------------------------------------------------------------------------- #
# §4 engine pair 矩阵自动发现 + pointer 锚候选
# --------------------------------------------------------------------------- #

def discover_engine_pairs(
    engines: Sequence[str],
    *,
    reference: str | None = None,
    exclude: Sequence[str] = (),
) -> list[tuple[str, str]]:
    """引擎名清单 → 待差分 pair 矩阵（确定性序，去重）。

    reference=None：全部无序组合（itertools.combinations 2，字典序）；
    reference=ref：星型 [(ref, e) for e ≠ ref]（HFSS 对齐基准惯例，
     规则"HFSS 结果为对齐基准"）。exclude 命中的引擎不参与配对。
    引擎名 < 2 个 → 空矩阵（合法，无对可差分）。
    """
    seen: dict[str, None] = {}
    for name in engines:
        key = str(name).strip()
        if key and key not in exclude:
            seen.setdefault(key, None)
    names = sorted(seen)
    if reference is not None:
        ref = str(reference).strip()
        if ref not in seen:
            raise ValueError(f"reference 引擎 {ref!r} 不在引擎清单 {names!r} 中")
        return [(ref, e) for e in names if e != ref]
    return list(itertools.combinations(names, 2))


def _pair_slug(a: str, b: str) -> str:
    """引擎对 slug：按字典序拼 ``a-b``（确定性，无序对归一）。"""
    x, y = sorted((str(a), str(b)))
    return f"{slugify(x)}-{slugify(y)}"


def slugify(text: str) -> str:
    """锚 id 词法约束（ANCHOR_ID_RE：[a-z0-9_] 段）下的安全化。"""
    out = re.sub(r"[^a-z0-9_]+", "_", str(text).strip().lower()).strip("_")
    return out or "unnamed"


def pair_matrix_curves(
    curves_by_engine: Mapping[str, tuple[Sequence[float], Sequence[float]]],
    *,
    gate: FsvGateSpec | None = None,
    reference: str | None = None,
    n_points: int | None = None,
) -> list[dict[str, Any]]:
    """逐引擎曲线 → pair 矩阵自动发现 + 逐 pair FSV 门判行。

    curves_by_engine: {engine: (freq, val)}；引擎对由 discover_engine_pairs
    自动发现（reference 语义同上）。返回行含 pair 引擎名 + fsv_pair_gate
    全字段，按 (engine_a, engine_b) 字典序。
    """
    pairs = discover_engine_pairs(list(curves_by_engine), reference=reference)
    rows: list[dict[str, Any]] = []
    for ea, eb in pairs:
        fa, va = curves_by_engine[ea]
        fb, vb = curves_by_engine[eb]
        row = fsv_pair_gate(fa, va, fb, vb, gate, n_points=n_points)
        row = {"engine_a": ea, "engine_b": eb, **row}
        rows.append(row)
    return rows


def pair_matrix_scalar(
    observations: Mapping[str, float],
    *,
    rel_tol: float = 0.05,
    reference: str | None = None,
) -> list[dict[str, Any]]:
    """逐引擎标量观测量（如 f_res_GHz）→ pair 矩阵 + 相对差门判行。

    rel_tol：|a−b| / max(|a|,|b|) 上限，缺省 5%（锚漂移门 5%·|锚值| 同
    量级惯例）；双零特判 AGREE（0 vs 0 无相对差）。行含
    (engine_a, engine_b, value_a, value_b, rel_delta, decision, reason)。
    """
    pairs = discover_engine_pairs(list(observations), reference=reference)
    rows: list[dict[str, Any]] = []
    for ea, eb in pairs:
        va = float(observations[ea])
        vb = float(observations[eb])
        denom = max(abs(va), abs(vb))
        rel_delta = 0.0 if denom == 0.0 else abs(va - vb) / denom
        ok = math.isfinite(rel_delta) and rel_delta <= float(rel_tol)
        rows.append({
            "engine_a": ea,
            "engine_b": eb,
            "value_a": va,
            "value_b": vb,
            "rel_delta": rel_delta,
            "decision": _AGREE if ok else _DISAGREE,
            "reason": None if ok else f"rel_delta {rel_delta:.6g} > {float(rel_tol):.6g}",
        })
    return rows


def pointer_anchor_candidates(
    rows: Sequence[Mapping[str, Any]],
    *,
    template_family: str,
    quantity: str,
    unit: str = "",
    version: int = 1,
    status: str = "experimental",
    provenance: Mapping[str, Any] | None = None,
    extra_quantity: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """从 DISAGREE 行自动产 pointer 锚候选（双值分歧指针，不就地写库）。

    形态对齐 core/anchors.py 双值分歧指针锚：kind="pointer"、
    quantity.values = {engine: value}、experimental、值在模型档案不就地
    求值（resolve 时取双值中位）。只消费 decision=="DISAGREE" 的行
    （AGREE/INDETERMINATE 不产锚候选）；anchor_id =
    ``<族>.<量>.<引擎对slug>-v<N>``，构造期过 ANCHOR_ID_RE 断言。
    """
    family_slug = slugify(template_family)
    quantity_slug = slugify(quantity)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("decision")) != _DISAGREE:
            continue
        values: dict[str, float] = {}
        for eng_key, val_key in (("engine_a", "value_a"), ("engine_b", "value_b")):
            if val_key in row:
                values[str(row[eng_key])] = float(row[val_key])
        if len(values) < 2:
            continue
        pair = _pair_slug(str(row["engine_a"]), str(row["engine_b"]))
        anchor_id = f"{family_slug}.{quantity_slug}.{pair}-v{int(version)}"
        if not ANCHOR_ID_RE.match(anchor_id):
            raise ValueError(f"pointer 锚候选 id 不合规: {anchor_id!r}")
        quantity_block: dict[str, Any] = {
            "name": str(quantity),
            "values": values,
        }
        if unit:
            quantity_block["unit"] = str(unit)
        if extra_quantity:
            quantity_block.update(dict(extra_quantity))
        candidates.append({
            "anchor_id": anchor_id,
            "kind": "pointer",
            "status": str(status),
            "template_family": [str(template_family)],
            "engine_pair": {
                "engines": [str(row["engine_a"]), str(row["engine_b"])],
                "slug": pair,
                "rel_delta": float(row.get("rel_delta", float("nan"))),
            },
            "quantity": quantity_block,
            "provenance": {
                "source": "diff_harness.pair_matrix",
                "decision": _DISAGREE,
                **(dict(provenance) if provenance else {}),
            },
        })
    return candidates
