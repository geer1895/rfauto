"""DA-2 检索式元学习 v0 —— k-NN 元特征相似检索 → warm-start 先验（确定性内核）。

判定与口径来源（研究扩充 round4 DA-2 行）：
学习式 NO（带标签历史战役仅 6-8 个，训练不成立）/ 检索式 GO（1520 trials
+ 元特征现成）——k-NN 元特征相似检索，复用 warm_start_data 既有通道注入
先验。确定性内核：**零学习零随机**——k-NN 是确定性检索
（无训练、无采样、无模型拟合）；LLM/训练模型不进本件。数值只由本内核的
确定性距离/排序产出。

与既有 warm_start 通道的对齐（先读通道代码确定形态再产出）：
- 通道入参形态 = ``optimization/warm_start.py::warm_start_points(
  history_points, bounds=..., top_n=...)`` 与 ``optimizer.run_optimization(
  warm_start=...)`` 的 ``list[dict]``，每点 ``{"params": dict, "cost":
  float, ...}``（多余键被门忽略）；service/warm_start_data.py 的数据面
  样本即此形态（附 run_id/point_index 溯源键）。
- 本内核输出键 ``warm_start_samples`` 即该形态（附 entry_id/similarity
  溯源键），可直接透传既有通道；相似度门（Jaccard 键重叠/落界率/cost
  升序/界外裁剪）仍归通道所有，本件**只做检索选点不重复设门**（分层同
  warm_start_data 数据面先例）。

问题侧元特征 schema（显式；向量顺序 = ``meta_feature_names()`` 顺序）：

    ┌───┬──────────┬────────────────┬──────────────────────────────────┐
    │ # │ 特征名    │ meta 键         │ 语义                              │
    ├───┼──────────┼────────────────┼──────────────────────────────────┤
    │ 0 │ dim      │ meta["dim"]    │ 设计参数维度（库条目缺省回退       │
    │   │          │                │ len(params)；查询必填）            │
    │ 1 │ log10_f0 │ meta["f0_ghz"] │ log10 中心频率（GHz）——频率跨      │
    │   │          │                │ 量级（MHz~THz），线性距离被高端    │
    │   │          │                │ 频带吞没，取对数同权               │
    │ 2 │ log10_bw │ meta["bw_frac"]│ log10 分数带宽 ∈(0,1]——窄带/宽带   │
    │   │          │                │ 同理取对数                         │
    │3+ │ family_* │ meta["model"]  │ 模板族 one-hot（词表见             │
    │   │          │                │ TEMPLATE_FAMILY_VOCAB）            │
    └───┴──────────┴────────────────┴──────────────────────────────────┘

- one-hot 词表 TEMPLATE_FAMILY_VOCAB 是显式冻结快照（截取自
  adapters/openems_templates.TEMPLATE_META 已知族 + hairpin/lange 等
  滤波器/耦合器族）；**core 是无依赖叶，不 import 适配器注册表**（分层
  契约 .importlinter）。meta["model"] 不在词表 → one-hot 全零（"未知族
  桶"，不报错不臆造列——词表漂移安全；检索输出回显 family_known=False
  供 provenance 如实标记）。
- f0_ghz 必须 >0、bw_frac 必须 ∈(0,1]（log10 定义域）；非法显式
  ValueError（bool 显式拒收，df7+⑯）。

历史库条目 schema（调用方显式供给，本件零 IO 不读 runs/——#144 隔离
纪律：真实 runs/ 只由调用方面经 dataset_service 查询）::

    {
      "entry_id": str,   # 溯源 id（如 run_id 或自定 id；缺失→跳过计数）
      "params": {...},   # 历史设计点（喂 warm_start 通道）
      "cost": float,     # 历史性能（喂 warm_start 通道）
      "meta": {"model": str, "dim": int, "f0_ghz": float, "bw_frac": float},
    }

查询（新战役问题侧）取同一 meta schema（无 params/cost）。

距离口径（metric 显式二选一，标准化参数显式回显）：
- "euclidean"：原始特征向量上的欧氏距离。
- "standardized_mahalanobis"（缺省）：**对角马氏**——d²=Σ((x_i−y_i)/σ_i)²，
  σ 取历史库有效条目全体的总体标准差（ddof=0）；等价于 z-score 后欧氏
  （μ 在代数上消去，不出现在成对距离里，只进零方差守卫与 provenance）。
  完整协方差马氏不做（one-hot 列强相关 → 协方差奇异，且求逆引入数值
  不确定面）。σ 的零方差守卫：``σ <= 1e-12·max(1,|μ|)`` 视为零方差
  （库内恒定维，含"同值浮点均值仍带 1e-17 误差"的退化）——该维 σ 视为
  1 按未标准化差²计（查询与库值同则自然为 0，异则有界不爆）。μ/σ 向量
  在输出 ``standardization`` 键显式回传（检索 provenance/复现面）。

相似度得分：``similarity = 1/(1+distance)``（单调递减、有界 (0,1]、
确定性；distance=0 → similarity=1）。

排序与并列：按 ``(distance, 库内原始下标)`` 升序稳定排序——同元特征
查询 → 同 top-k **逐位**（检索恒等式）；同距离按库序不按字典序（库序
是输入的一部分，恒等式仍成立）。

规模降级（判据预声明）：空库/有效条目 < k → 返回全部有效条目
（k_effective=n_valid），ok=True 不抛；库为空时 standardization=None、
先验字段为空列表。条目级数据质量问题（缺 entry_id/params/cost 非法/
meta 非法）→ 跳过该条并计数上报（skip_reasons/skip_examples，对齐
warm_start_data 数据面"喂料合法性清洗"先例，不静默不抛）。

纯算法零 IO 零依赖（连 numpy 也不用——纯 Python float 运算保证跨版本
逐位确定性）；全部输出 JSON 可序列化。不进 calculators 注册表（消费者
是 service/meta_retrieval_service.py 薄壳）。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "METRIC_EUCLIDEAN",
    "METRIC_STANDARDIZED_MAHALANOBIS",
    "SUPPORTED_METRICS",
    "TEMPLATE_FAMILY_VOCAB",
    "build_meta_vector",
    "compute_standardization",
    "meta_feature_names",
    "retrieve_warm_start_prior",
]

# 模板族 one-hot 词表（显式冻结快照；未知族 → 全零桶，见模块 docstring）。
# 与 adapters/openems_templates.TEMPLATE_META 对齐（2026-09-27 快照，含
# hairpin/hairpin_alt/interdigital/lange/marchand 滤波器/耦合器族）；
# 词表漂移安全：新族未登记时走全零桶 + family_known=False，不报错。
TEMPLATE_FAMILY_VOCAB: tuple[str, ...] = (
    "patch", "dipole", "monopole", "pifa", "ifa", "loop", "helix", "slot",
    "patch_array_1x4", "patch_array_2x2", "patch_array_series",
    "wilkinson", "branchline", "ratrace", "gysel", "coupled_line",
    "hairpin", "hairpin_alt", "interdigital", "lange", "marchand",
    "stepped_impedance", "mline", "cpw", "stripline", "cps",
    "suspended_stripline", "wstep", "tjunc", "bend", "via",
    "atten_pi", "atten_t",
)

METRIC_EUCLIDEAN = "euclidean"
METRIC_STANDARDIZED_MAHALANOBIS = "standardized_mahalanobis"
SUPPORTED_METRICS = (METRIC_EUCLIDEAN, METRIC_STANDARDIZED_MAHALANOBIS)

# 数值特征名（one-hot 之前的固定前三列；one-hot 列名 = f"family_{族名}"）
_NUMERIC_FEATURE_NAMES = ("dim", "log10_f0", "log10_bw")
# 零方差守卫的相对阈值（见模块 docstring"零方差守卫"）
_ZERO_STD_REL_EPS = 1e-12


def meta_feature_names() -> list[str]:
    """特征名列表（向量顺序的显式 schema 面，供输出回显/消费方对列）。"""
    return [*_NUMERIC_FEATURE_NAMES, *(f"family_{name}" for name in TEMPLATE_FAMILY_VOCAB)]


def _finite(value: Any, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值（got {value!r}）") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数（got {value!r}）")
    return out


def _dim_int(value: Any, name: str) -> int:
    """维度收敛为正整数（bool 拒收；整数值 float 接受并转 int）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    if isinstance(value, int):
        out = value
    elif isinstance(value, float) and value.is_integer():
        out = int(value)
    else:
        raise ValueError(f"{name} 必须为正整数（got {value!r}）")
    if out < 1:
        raise ValueError(f"{name} 必须 >=1（got {out}）")
    return out


def build_meta_vector(meta: dict[str, Any]) -> list[float]:
    """问题侧 meta dict → 特征向量（顺序 = meta_feature_names()）。

    未知族 → one-hot 全零；f0_ghz>0、bw_frac∈(0,1] 显式守卫。
    纯函数：不修改入参。
    """
    if not isinstance(meta, dict):
        raise ValueError("meta 必须为 dict")
    dim = _dim_int(meta.get("dim"), 'meta["dim"]')
    f0 = _finite(meta.get("f0_ghz"), 'meta["f0_ghz"]')
    if f0 <= 0.0:
        raise ValueError(f'meta["f0_ghz"] 必须 >0（log10 定义域，got {f0}）')
    bw = _finite(meta.get("bw_frac"), 'meta["bw_frac"]')
    if not (0.0 < bw <= 1.0):
        raise ValueError(f'meta["bw_frac"] 必须 ∈(0,1]（log10 定义域，got {bw}）')
    model = str(meta.get("model") or "")
    vec = [float(dim), math.log10(f0), math.log10(bw)]
    vec.extend(1.0 if model == name else 0.0 for name in TEMPLATE_FAMILY_VOCAB)
    return vec


def compute_standardization(
    vectors: list[list[float]],
) -> dict[str, list[float]] | None:
    """历史库特征向量的总体标准化参数（μ/σ，ddof=0）；空库返回 None。

    零方差维 σ 落地板 0.0（消费端检索按"零方差守卫"分支处理，本函数
    如实报 0.0 不伪装成小方差）。
    """
    n = len(vectors)
    if n == 0:
        return None
    n_feat = len(vectors[0])
    mean = [0.0] * n_feat
    for vec in vectors:
        for i in range(n_feat):
            mean[i] += vec[i]
    mean = [m / n for m in mean]
    std = [0.0] * n_feat
    for vec in vectors:
        for i in range(n_feat):
            std[i] += (vec[i] - mean[i]) ** 2
    std = [math.sqrt(s / n) for s in std]
    # 零方差守卫：同值浮点均值带 ~1e-17 误差 → 相对阈值判零（docstring）
    for i in range(n_feat):
        if std[i] <= _ZERO_STD_REL_EPS * max(1.0, abs(mean[i])):
            std[i] = 0.0
    return {"mean": mean, "std": std}


def _sq_delta_standardized(
    query: list[float], vec: list[float], std_params: dict[str, list[float]]
) -> list[float]:
    """逐维标准化差²（对角马氏：d²=Σ((q−v)/σ)²，μ 在代数上消去不出现在
    距离里——只在零方差守卫与 provenance 回显中出现）。

    零方差维（σ 守卫落 0）：σ 视为 1，按未标准化差²计——查询与库值同
    则自然为 0，异则有界不爆。
    """
    std = std_params["std"]
    out = [0.0] * len(query)
    for i in range(len(query)):
        d = query[i] - vec[i]
        out[i] = d * d if std[i] == 0.0 else (d / std[i]) ** 2
    return out


def _sq_delta_raw(query: list[float], vec: list[float]) -> list[float]:
    return [(q - v) ** 2 for q, v in zip(query, vec, strict=True)]


def _has_nonfinite(value: Any) -> bool:
    """递归判定容器内是否含 NaN/Inf 浮点（与 warm_start_data 纵深防御同口径）。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, dict):
        return any(_has_nonfinite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_nonfinite(v) for v in value)
    return False


def _validate_entry(index: int, entry: Any) -> tuple[dict[str, Any] | None, str, str]:
    """单条历史库条目校验。

    Returns:
        ``(规整条目或 None, 稳定类别键, 明细)``——合法条目类别键为 ""；
        非法条目类别键固定（skip_reasons 计数面），明细带 tag/id 供
        skip_examples 溯源（对齐 collect_warm_start_samples 先例）。
    """
    tag = f"library[{index}]"
    if not isinstance(entry, dict):
        return None, "条目非对象", f"{tag} 条目非对象"
    entry_id = str(entry.get("entry_id") or "")
    if not entry_id:
        return None, "entry_id 缺失", f"{tag} entry_id 缺失"
    params = entry.get("params")
    if not isinstance(params, dict):
        return None, "params 非对象", f"{tag}({entry_id}) params 非对象"
    if _has_nonfinite(params):
        return None, "params 含 NaN/Inf", f"{tag}({entry_id}) params 含 NaN/Inf"
    cost = entry.get("cost")
    if cost is None or isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return None, "cost 缺失或非数值", f"{tag}({entry_id}) cost 缺失或非数值"
    cost_f = float(cost)
    if not math.isfinite(cost_f):
        return None, "cost 含 NaN/Inf", f"{tag}({entry_id}) cost 含 NaN/Inf"
    meta = entry.get("meta")
    if not isinstance(meta, dict):
        return None, "meta 非对象", f"{tag}({entry_id}) meta 非对象"
    # meta 数值合法性（dim 缺省回退 len(params)，回显 dim_source）
    meta_norm: dict[str, Any] = dict(meta)
    if meta_norm.get("dim") is None:
        meta_norm["dim"] = len(params)
    try:
        vec = build_meta_vector(meta_norm)
    except ValueError as exc:
        return None, "meta 非法", f"{tag}({entry_id}) meta 非法（{exc}）"
    family_known = str(meta.get("model") or "") in TEMPLATE_FAMILY_VOCAB
    return (
        {
            "entry_id": entry_id,
            "params": params,
            "cost": cost_f,
            "vector": vec,
            "family_known": family_known,
            "dim_source": "meta" if meta.get("dim") is not None else "params_len",
        },
        "",
        "",
    )


def retrieve_warm_start_prior(
    query_meta: dict[str, Any],
    library: list[dict[str, Any]],
    *,
    k: int = 5,
    metric: str = METRIC_STANDARDIZED_MAHALANOBIS,
) -> dict[str, Any]:
    """k-NN 元特征相似检索 → warm-start 先验点集（确定性内核，JSON 可序列化）。

    Args:
        query_meta: 新战役问题侧元特征（schema 见模块 docstring；
            ``dim``/``f0_ghz``/``bw_frac`` 必填）。
        library: 历史库条目列表（schema 见模块 docstring；调用方显式
            供给，本件零 IO）。
        k: 检索近邻数（>=1；库小于 k 时返回全部有效条目）。
        metric: 距离口径 ``"euclidean"`` 或
            ``"standardized_mahalanobis"``（缺省）。

    Returns:
        ``{"ok": True, "metric", "feature_names", "query_features",
        "query_family_known", "k_requested", "k_effective", "n_library",
        "n_valid", "n_skipped_invalid", "skip_reasons", "skip_examples",
        "neighbors": [{"rank", "entry_id", "distance", "similarity",
        "params", "cost", "family_known", "dim_source"}, ...],
        "warm_start_samples": [{"params", "cost", "entry_id"}, ...],
        "standardization": {"mean", "std"} | None}``。

        ``warm_start_samples`` 与既有 warm_start 通道入参形态对齐
        （``list[{"params", "cost", ...}]``，多余溯源键被门忽略），可
        直接透传 ``optimization.warm_start.warm_start_points`` /
        ``optimizer.run_optimization(warm_start=...)``。

        空库/库小于 k → ok=True 且先验字段降级（k_effective<n 侧如实
        回显），不抛（判据预声明）。``standardization`` 仅
        standardized_mahalanobis 口径回显（euclidean 不消费标准化参数，
        回 None）。查询/k/metric 非法 → ValueError
        （调用方编程错误，service 层转 ok=False 信封）。
    """
    if not isinstance(k, int) or isinstance(k, bool):
        raise ValueError(f"k 必须为 int（got {k!r}）")
    if k < 1:
        raise ValueError(f"k 必须 >=1（got {k}）")
    if metric not in SUPPORTED_METRICS:
        raise ValueError(
            f"metric 必须为 {'/'.join(SUPPORTED_METRICS)}（got {metric!r}）"
        )
    if not isinstance(library, list):
        raise ValueError(f"library 必须为 list（got {type(library).__name__}）")
    query_vec = build_meta_vector(query_meta)
    model = str(query_meta.get("model") or "")
    query_family_known = model in TEMPLATE_FAMILY_VOCAB

    # 条目清洗（跳过+计数，喂料合法性纵深防御，docstring"规模降级"节）
    valid: list[dict[str, Any]] = []
    skip_reasons: dict[str, int] = {}
    skip_examples: list[str] = []
    for i, entry in enumerate(library):
        norm, category, detail = _validate_entry(i, entry)
        if norm is None:
            skip_reasons[category] = skip_reasons.get(category, 0) + 1
            if len(skip_examples) < 3:
                skip_examples.append(detail)
            continue
        valid.append(norm)

    # 标准化参数只对 standardized_mahalanobis 有距离语义（euclidean 不消费，
    # 回 None 防消费方误读）；零方差守卫见 compute_standardization。
    std_params: dict[str, list[float]] | None = None
    if metric == METRIC_STANDARDIZED_MAHALANOBIS and valid:
        std_params = compute_standardization([v["vector"] for v in valid])

    # 距离 + 稳定排序（(distance, 库序)，检索恒等式）
    scored: list[tuple[float, int]] = []
    for idx, item in enumerate(valid):
        if metric == METRIC_EUCLIDEAN:
            sq = _sq_delta_raw(query_vec, item["vector"])
        else:
            sq = _sq_delta_standardized(query_vec, item["vector"], std_params)  # type: ignore[arg-type]
        scored.append((math.sqrt(sum(sq)), idx))
    scored.sort(key=lambda t: (t[0], t[1]))

    take = min(k, len(scored))
    neighbors: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for rank, (dist, idx) in enumerate(scored[:take], start=1):
        item = valid[idx]
        neighbors.append(
            {
                "rank": rank,
                "entry_id": item["entry_id"],
                "distance": dist,
                "similarity": 1.0 / (1.0 + dist),
                "params": item["params"],
                "cost": item["cost"],
                "family_known": item["family_known"],
                "dim_source": item["dim_source"],
            }
        )
        # 通道对齐形态：{"params", "cost", ...}（溯源键被既有门忽略）
        samples.append(
            {
                "params": item["params"],
                "cost": item["cost"],
                "entry_id": item["entry_id"],
            }
        )

    return {
        "ok": True,
        "metric": metric,
        "feature_names": meta_feature_names(),
        "query_features": query_vec,
        "query_family_known": query_family_known,
        "k_requested": k,
        "k_effective": len(neighbors),
        "n_library": len(library),
        "n_valid": len(valid),
        "n_skipped_invalid": len(library) - len(valid),
        "skip_reasons": skip_reasons,
        "skip_examples": skip_examples,
        "neighbors": neighbors,
        "warm_start_samples": samples,
        "standardization": std_params,
    }
