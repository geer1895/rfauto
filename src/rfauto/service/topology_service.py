"""E10 TopologyProposer（生成式综合，方案 §3 E10 / §4 WP4.6 首案例）。

链路：**拓扑提议（typed，禁数值字段）→ synthesis 初值 → 小战役精算**。
铁律 7 口径（数值只在确定性内核）：LLM/提议器只产出「结构族/阶数/耦合
形式」三类结构字段（schema 校验拒绝一切浮点与未注册字段）；频率/损耗/
几何等物理数字一律由确定性综合引擎（core/synthesis + adapters 综合链）
与评判器（C13 耦合矩阵频响、平行耦合 BPF 电路裁判）产出。

首案例 = 滤波器家族（WP4.6 依赖 WP2.3 滤波器族落地）：
- coupled_bpf：平行耦合 λ/4 段 BPF（综合+战役精算双能力）；
- hairpin：发夹谐振器族（仅综合初值；几何↔电气标定未闭环——
  fake_adapter 口径「未定标前不引入未验证耦合物理」，故 campaign 不支持）。

战役精算口径（WP4.6「小战役精算」）：
- 快裁判 = adapters.coupled_bpf_circuit_sparams（真偶/奇模准静态级联）；
- 目标曲线 = C13 裁判 coupling_matrix_response（综合矩阵的理想频响），
  代价 = 带内回损短欠 + 4×带外(±fbw)抑制超理想上限 + 工艺缝下限罚；
- optuna TPE（内存 study，种子确定），**综合初值经 enqueue_trial 入队**
  ——「确定性算初值、战役只做有界精化」；单测离线秒级（无真机求解）。

已知边界（如实）：C13 coupling_matrix_extract 反提对
含馈线/λ/4 段参考面相位的电路裁判输出：原始 rms ~6e-2（±5% 窗）> 1e-2 门不
收敛。根因=参考面相位在 Ω 域非有理（馈线时延 e^{−j2πfτ} + λ/4 commensurate
段，Richards 变量 tan(θ) ≠ Ω 映射）；已败三策略：相位滚转 ±（滚不动 f 的
函数）、ABCD 精确逆（λ/4 段=4 端口+交叉口开路复合结构不可分离）、纯时延扫描
（能开门：馈线量 τ_feed 去嵌后 rms 7.2e-3，但 kij 0.08 不收敛——窄带错 τ 可
被多项式翘曲补偿，重建放大离流形距离 ~10³ 倍）。收敛口径=domain="magnitude"
幅值域反提（|S|² 相位免疫；sync TEM 裁判 ±3% 窗 fit 8.7e-3 过门 + kij 逐元素
1.95e-2，tests/unit/test_c13_refplane_deembed.py 钉）；色散模式裁判与理想矩阵
带内 |S11| 差 ~0.16（εeff_e/o 模型差异，归 #11）。战役闭环仍以响应域 hinge
收敛为准。
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np

# 提议阶数上限（结构计数；>12 的综合链数值病态，无工程意义）
MAX_ORDER = 12
# 默认工艺缝下限（mm）：标准 PCB 机械钻孔/蚀刻下限口径，防「缝换回损」
DEFAULT_GAP_FLOOR_MM = 0.10
# 默认战役预算/种子（确定性复现）
DEFAULT_N_TRIALS = 80
DEFAULT_SEED = 20260914

_ALLOWED_PROPOSAL_KEYS = frozenset(
    {"family", "order", "coupling_form", "rationale", "source"})
_ALLOWED_SOURCES = frozenset({"rule", "llm"})


class TopologyProposalError(ValueError):
    """拓扑提议违反 typed schema（未知字段/数值字段/未注册族）。"""


class TopologyCampaignError(ValueError):
    """家族不具备战役精算能力或战役输入非法。"""


@dataclass(frozen=True)
class FilterSpec:
    """滤波器规格（用户侧确定性数字——永不来自提议器）。

    - f0_ghz/fbw/rl_db：中心频率（GHz）/相对带宽（全带宽口径，带边
      f0·(1±fbw/2)，与 synthesize_bpf_model 同口径）/带内回损目标（dB）；
    - stop_rejection_db：阻带抑制要求（dB，选阶用，可省略→默认阶数 3）；
    - stop_fbw_mult：阻带边 = f0·(1±stop_fbw_mult·fbw/2)（默认 2×带边）；
    - order_hint/family_hint：上层显式指定（否则由规则推导/默认首案例族）。
    """

    f0_ghz: float
    fbw: float
    rl_db: float
    stop_rejection_db: float | None = None
    stop_fbw_mult: float = 2.0
    order_hint: int | None = None
    family_hint: str | None = None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.f0_ghz) and self.f0_ghz > 0):
            raise TopologyProposalError(f"f0_ghz={self.f0_ghz} 须为正有限数")
        if not 0 < self.fbw <= 1:
            raise TopologyProposalError(f"fbw={self.fbw} 须在 (0,1]")
        if not (math.isfinite(self.rl_db) and self.rl_db > 0):
            raise TopologyProposalError(f"rl_db={self.rl_db} 须为正有限数")
        if self.stop_rejection_db is not None \
                and not (math.isfinite(self.stop_rejection_db)
                         and self.stop_rejection_db > 0):
            raise TopologyProposalError(
                f"stop_rejection_db={self.stop_rejection_db} 须为正有限数")
        if not (math.isfinite(self.stop_fbw_mult) and self.stop_fbw_mult > 1):
            raise TopologyProposalError(
                f"stop_fbw_mult={self.stop_fbw_mult} 须 >1（阻带边在带外）")
        if self.order_hint is not None \
                and (isinstance(self.order_hint, bool)
                     or not isinstance(self.order_hint, int)
                     or not 1 <= self.order_hint <= MAX_ORDER):
            raise TopologyProposalError(
                f"order_hint={self.order_hint} 须为 1..{MAX_ORDER} 整数")
        if self.family_hint is not None \
                and self.family_hint not in list_families():
            raise TopologyProposalError(
                f"family_hint={self.family_hint} 未注册"
                f"（可用: {list_families()}）")

    def to_dict(self) -> dict[str, Any]:
        return {"f0_ghz": float(self.f0_ghz), "fbw": float(self.fbw),
                "rl_db": float(self.rl_db),
                "stop_rejection_db": (None if self.stop_rejection_db is None
                                      else float(self.stop_rejection_db)),
                "stop_fbw_mult": float(self.stop_fbw_mult),
                "order_hint": self.order_hint, "family_hint": self.family_hint}


@dataclass(frozen=True)
class TopologyProposal:
    """typed 拓扑提议（结构族/阶数/耦合形式；schema 禁数值字段）。

    order 是谐振器个数（结构计数，整数）；除它之外任何字段都不得是数字
    ——物理数字（GHz/mm/dB/Ω）只能出自确定性综合引擎与评判器。
    """

    family: str
    order: int
    coupling_form: str
    rationale: str = ""
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return {"family": self.family, "order": int(self.order),
                "coupling_form": self.coupling_form,
                "rationale": self.rationale, "source": self.source}


def parse_topology_proposal(payload: Any,
                            *, source: str = "rule") -> TopologyProposal:
    """严格 schema 校验：拒绝未知字段与一切数值字段（铁律 7 零冲突）。

    payload 键集合 ⊆ {family, order, coupling_form, rationale, source}；
    family/coupling_form 须在家族注册表内；order 须为 1..MAX_ORDER 的
    int（bool 与 float 一律拒绝——LLM 借阶数字段走私物理数字的通道封死）。
    source 入参覆盖 payload 内的 source（通道归属由调用方声明，不信任载荷）。
    """
    if not isinstance(payload, dict):
        raise TopologyProposalError(
            f"提议载荷须为 dict，实得 {type(payload).__name__}")
    unknown = sorted(set(payload) - _ALLOWED_PROPOSAL_KEYS)
    if unknown:
        raise TopologyProposalError(
            f"提议含未注册字段（schema 禁数值字段）：{unknown}")
    family = payload.get("family")
    if not isinstance(family, str) or family not in list_families():
        raise TopologyProposalError(
            f"family={family!r} 未注册（可用: {list_families()}）")
    forms = FILTER_FAMILY_REGISTRY[family]["coupling_forms"]
    coupling_form = payload.get("coupling_form", forms[0])
    if not isinstance(coupling_form, str) or coupling_form not in forms:
        raise TopologyProposalError(
            f"coupling_form={coupling_form!r} 不属于家族 {family}"
            f"（可用: {list(forms)}）")
    order = payload.get("order")
    if isinstance(order, bool) or not isinstance(order, int):
        raise TopologyProposalError(
            f"order={order!r} 须为 int（bool/float 拒绝；"
            "物理数字由综合引擎产出）")
    if not 1 <= order <= MAX_ORDER:
        raise TopologyProposalError(f"order={order} 须在 1..{MAX_ORDER}")
    rationale = payload.get("rationale", "")
    if not isinstance(rationale, str):
        raise TopologyProposalError("rationale 须为 str")
    src = source if source != "rule" else payload.get("source", "rule")
    if not isinstance(src, str) or src not in _ALLOWED_SOURCES:
        raise TopologyProposalError(
            f"source={src!r} 须为 {'/'.join(sorted(_ALLOWED_SOURCES))}")
    return TopologyProposal(family=family, order=order,
                            coupling_form=coupling_form,
                            rationale=rationale, source=src)


def _family_entry(family: str) -> dict[str, Any]:
    entry = FILTER_FAMILY_REGISTRY.get(family)
    if entry is None:
        raise TopologyProposalError(
            f"family={family!r} 未注册（可用: {list_families()}）")
    return entry


def list_families() -> list[str]:
    """已注册滤波器家族（确定性顺序）。"""
    return sorted(FILTER_FAMILY_REGISTRY)


def _coupled_bpf_synthesis(order: int, spec: FilterSpec) -> dict[str, Any]:
    from rfauto.adapters.openems_templates import coupled_bpf_design_from_order

    design = coupled_bpf_design_from_order(
        int(order), float(spec.f0_ghz), float(spec.fbw), float(spec.rl_db))
    # 渲染参数（COUPLED_BPF_NOMINAL 同键位）：全部由综合链产出
    template_params = {
        "order": int(order),
        "w_feed_mm": round(float(design["w_feed_mm"]), 4),
        "widths_mm": [round(float(s["w_mm"]), 4) for s in design["sections"]],
        "gaps_mm": [round(float(s["s_mm"]), 4) for s in design["sections"]],
        "res_len_mm": round(float(design["res_len_mm"]), 4),
        "feed_len_mm": round(float(design["feed_len_mm"]), 4),
    }
    return {"design": design, "template_params": template_params}


def _hairpin_synthesis(order: int, spec: FilterSpec) -> dict[str, Any]:
    from rfauto.adapters.openems_templates import hairpin_design_from_order

    design = hairpin_design_from_order(
        int(order), float(spec.f0_ghz), float(spec.fbw), float(spec.rl_db))
    return {"design": design, "template_params": None}


#: 滤波器家族注册表（基类+注册表模式的家族能力面；新增族=加一个条目）。
FILTER_FAMILY_REGISTRY: dict[str, dict[str, Any]] = {
    "coupled_bpf": {
        # 平行耦合 λ/4 段（Chebyshev 全极点，C13 folded 口径）
        "coupling_forms": ("chebyshev_parallel",),
        "campaign_capable": True,
        "synthesis": _coupled_bpf_synthesis,
    },
    "hairpin": {
        # 发夹谐振器族（C13 folded 折返口径；几何↔电气未定标，
        # fake_adapter 口径——战役精算不支持，仅综合初值）
        "coupling_forms": ("chebyshev_parallel",),
        "campaign_capable": False,
        "synthesis": _hairpin_synthesis,
    },
}


# ─── E10 提议器（基类+注册表，同 AgentRuntime/RuntimeRegistry 模式）──────────

class TopologyProposer(ABC):
    """可插拔拓扑提议器接口：spec（用户数字）→ typed 提议（结构字段）。"""

    name: str = "base"

    @abstractmethod
    def propose(self, spec: FilterSpec) -> TopologyProposal:
        """产出 typed 拓扑提议（禁止携带物理数字）。"""


class TopologyProposerRegistry:
    """提议器注册表。"""

    _proposers: ClassVar[dict[str, type[TopologyProposer]]] = {}

    @classmethod
    def register(cls, proposer_cls: type[TopologyProposer]) \
            -> type[TopologyProposer]:
        cls._proposers[proposer_cls.name] = proposer_cls
        return proposer_cls

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> TopologyProposer:
        if name not in cls._proposers:
            raise KeyError(
                f"未注册的提议器: {name}（可用: {cls.available()}）")
        return cls._proposers[name](**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._proposers)


def _order_from_rejection(spec: FilterSpec) -> int:
    """切比雪夫选阶（Pozar eq.8.13 口径，确定性闭式）。

    n ≥ arcosh(√((10^(Rs/10)−1)/(10^(RL/10)−1))) / arcosh(Ωs)，
    Ωs = (fs/f0 − f0/fs)/fbw，fs = f0·(1+stop_fbw_mult·fbw/2)。
    """
    ratio = (10.0 ** (float(spec.stop_rejection_db) / 10.0) - 1.0) \
        / (10.0 ** (float(spec.rl_db) / 10.0) - 1.0)
    m = float(spec.stop_fbw_mult) * float(spec.fbw) / 2.0
    fs_over_f0 = 1.0 + m
    omega_s = (fs_over_f0 - 1.0 / fs_over_f0) / float(spec.fbw)
    n_need = math.acosh(math.sqrt(ratio)) / math.acosh(omega_s)
    return int(min(MAX_ORDER, max(1, math.ceil(n_need - 1e-12))))


@TopologyProposerRegistry.register
class RuleBasedTopologyProposer(TopologyProposer):
    """确定性规则提议器（默认；离线、零网络、零 LLM）。

    规则（全部可复现，无隐藏数字）：
    - family = family_hint 或 "coupled_bpf"（首案例默认：唯一战役精算可用族）；
    - order = order_hint，或按阻带要求闭式选阶（Pozar eq.8.13），
      或无阻带要求时默认 3（首案例基准，与 COUPLED_BPF_NOMINAL 同源）；
    - coupling_form = 家族注册的唯一形式（chebyshev_parallel）。
    """

    name = "rule_based"

    def propose(self, spec: FilterSpec) -> TopologyProposal:
        family = spec.family_hint or "coupled_bpf"
        entry = _family_entry(family)
        if spec.order_hint is not None:
            order = int(spec.order_hint)
            order_src = f"order_hint={order}"
        elif spec.stop_rejection_db is not None:
            order = _order_from_rejection(spec)
            order_src = (f"选阶（Rs={spec.stop_rejection_db:g}dB@"
                         f"{spec.stop_fbw_mult:g}×带边，Pozar eq.8.13）")
        else:
            order = 3
            order_src = "默认 N=3（首案例基准）"
        form = entry["coupling_forms"][0]
        return TopologyProposal(
            family=family, order=order, coupling_form=form,
            rationale=f"规则提议：family={family}（默认首案例族）；"
                      f"{order_src}；coupling_form={form}",
            source="rule")


@TopologyProposerRegistry.register
class LLMTopologyProposer(TopologyProposer):
    """LLM 提议器（typed 通道）：LLM 只答结构 JSON，schema 拒绝数值字段。

    llm_call 必须由调用方注入（prompt → 文本）；本类**不内置任何网络通道**
    ——「存在配置则走外部服务」的分支在单测中一律 monkeypatch 注入
    （#139），构造时无 llm_call 即显式报错，杜绝意外真连。
    LLM 输出走与规则提议器同一个 parse_topology_proposal 严格校验：
    结构对→typed 提议；走私数字/未注册字段→TopologyProposalError（不静默回退）。
    """

    name = "llm"

    def __init__(self, llm_call: Callable[[str], str]) -> None:
        if llm_call is None:
            raise TopologyProposalError(
                "LLMTopologyProposer 需注入 llm_call(prompt)->str"
                "（本类不内置网络通道，#139）")
        self._llm_call = llm_call

    def propose(self, spec: FilterSpec) -> TopologyProposal:
        families = "; ".join(
            f"{name}（耦合形式: {','.join(_family_entry(name)['coupling_forms'])}）"
            for name in list_families())
        prompt = (
            "你是射频滤波器拓扑提议器。只输出一个 JSON 对象（无其他文字）："
            '{"family": "<家族>", "order": <1-12 整数>, '
            '"coupling_form": "<耦合形式>", "rationale": "<一句话理由>"}。'
            f"可选家族与耦合形式：{families}。"
            "禁止输出任何其他数值字段——频率/尺寸/损耗等物理数字由确定性"
            "综合引擎计算，你只猜结构。\n"
            f"用户指标（仅作选型背景，不得复制进输出）：f0={spec.f0_ghz:g}GHz，"
            f"fbw={spec.fbw:g}，带内回损≥{spec.rl_db:g}dB"
            + (f"，阻带抑制≥{spec.stop_rejection_db:g}dB"
               f"@{spec.stop_fbw_mult:g}×带边"
               if spec.stop_rejection_db is not None else "") + "。")
        raw = self._llm_call(prompt)
        return parse_topology_proposal(_extract_json_object(raw),
                                       source="llm")


def _extract_json_object(raw: str) -> dict[str, Any]:
    """从 LLM 文本中取出第一个 JSON 对象（容忍 ```json 围栏）。"""
    if not isinstance(raw, str):
        raise TopologyProposalError("LLM 通道返回须为 str")
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.removeprefix("json").strip()
            if part.startswith("{"):
                text = part
                break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise TopologyProposalError(
            f"LLM 输出不含 JSON 对象：{raw[:120]!r}")
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise TopologyProposalError(f"LLM 输出 JSON 解析失败: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TopologyProposalError("LLM 输出 JSON 须为对象")
    return parsed


# ─── synthesis 初值（数值只在确定性内核）─────────────────────────────────────

def design_initial_values(proposal: TopologyProposal, spec: FilterSpec) \
        -> dict[str, Any]:
    """提议 → 确定性综合初值（几何/电气全由综合引擎产出）。

    返回 {"family","order","coupling_form","spec","design","template_params",
    "campaign_capable","notes"}；coupled_bpf 的 template_params 与
    COUPLED_BPF_NOMINAL 同键位（可直接渲染/入沙箱）。
    """
    if not isinstance(proposal, TopologyProposal):
        proposal = parse_topology_proposal(proposal)
    if isinstance(spec, dict):
        spec = FilterSpec(**spec)
    if not isinstance(spec, FilterSpec):
        raise TypeError(f"spec 须为 FilterSpec/dict，实得 {type(spec).__name__}")
    entry = _family_entry(proposal.family)
    synth = entry["synthesis"](proposal.order, spec)
    notes = [
        "数值初值全部由确定性综合链产出（core/synthesis + KJ 反解），"
        "提议器零数字输入",
    ]
    if not entry["campaign_capable"]:
        notes.append(
            f"家族 {proposal.family} 暂不具备战役精算能力"
            "（几何↔电气标定未闭环），仅提供综合初值")
    return {"family": proposal.family, "order": proposal.order,
            "coupling_form": proposal.coupling_form,
            "spec": spec.to_dict(), "design": synth["design"],
            "template_params": synth["template_params"],
            "campaign_capable": bool(entry["campaign_capable"]),
            "notes": notes}


# ─── 小战役精算（WP4.6：电路裁判 + C13 理想目标曲线 + 初值入队 TPE）──────────

def _c13_targets(spec: FilterSpec, matrix: list) -> dict[str, Any]:
    """C13 裁判（coupling_matrix_response）：综合矩阵理想频响 → hinge 目标。"""
    from rfauto.core.calculators import coupling_matrix_response

    f0 = float(spec.f0_ghz)
    fbw = float(spec.fbw)
    half = fbw / 2.0
    freqs = np.linspace(f0 * (1 - 2 * fbw), f0 * (1 + 2 * fbw), 161)
    resp = coupling_matrix_response(freq_ghz=[float(v) for v in freqs],
                                    f0_ghz=f0, fbw=fbw, matrix=matrix)
    s11 = np.asarray(resp["s11_db"], dtype=float)
    s21 = np.asarray(resp["s21_db"], dtype=float)
    band = (freqs >= f0 * (1 - half)) & (freqs <= f0 * (1 + half))
    stop = np.abs(freqs / f0 - 1.0) >= fbw        # ±fbw（2× 带边）阻带锚
    return {"rl_ideal_db": float(-s11[band].max()),
            "stop_ideal_db": float(s21[stop].max()),
            "freq_ghz": freqs, "band": band, "stop": stop}


def run_fine_campaign(proposal: TopologyProposal, spec: FilterSpec, *,
                      n_trials: int = DEFAULT_N_TRIALS,
                      seed: int = DEFAULT_SEED,
                      gap_floor_mm: float = DEFAULT_GAP_FLOOR_MM) \
        -> dict[str, Any]:
    """小战役精算：综合初值入队 → TPE 有界精化 → 电路裁判+C13 目标判读。

    - 快裁判：coupled_bpf_circuit_sparams（真偶/奇模准静态，离线秒级）；
    - 精算语义 = **约束精化**：主指标带内回损最大化，C13 理想频响
      （coupling_matrix_response）给出 RL/阻带参考锚；阻带守卫取综合初值
      已达水平（理想锚不可达，约束锚=初值本身）——
      代价 = −RL + 40·(阻带劣化量)_+ + 20·(缝下限违反量/下限)_+；
      由「初值点惩罚恒 0 + 初值入队」可证 best 的 RL 恒 ≥ 初值 RL
      （代价 ≤ 初值代价 ⟹ RL_best ≥ RL_init + P_best ≥ RL_init），
      杜绝「牺牲回损换阻带」的指标作弊（探针实测教训）；
    - 搜索域（有界精化）：res_len ±2%、逐段宽 [0.85,1.2]×、逐段缝 [0.6,1.6]×；
      综合初值经 enqueue_trial 首点入队（#123：不等返回值，优化后按
      study.trials 校验入队点被评估）。
    返回 JSON 化 record（初值/最优全指标 + 代价分解 + 可渲染配方参数）。
    """
    entry = _family_entry(proposal.family)
    if not entry["campaign_capable"]:
        raise TopologyCampaignError(
            f"家族 {proposal.family} 不具备战役精算能力"
            "（几何↔电气标定未闭环）；当前仅 coupled_bpf 支持")
    if n_trials < 1:
        raise TopologyCampaignError(f"n_trials={n_trials} 须 ≥1")
    import optuna

    base = design_initial_values(proposal, spec)["design"]
    f0 = float(spec.f0_ghz)
    er = float(base["er"])
    h_mm = float(base["h_mm"])
    targets = _c13_targets(spec, base["coupling_matrix"])
    freqs: np.ndarray = targets.pop("freq_ghz")
    band = targets.pop("band")
    stop = targets.pop("stop")
    res_len0 = float(base["res_len_mm"])
    n_sec = int(proposal.order) + 1

    from rfauto.adapters.openems_templates import (
        coupled_bpf_circuit_sparams,
        coupled_microstrip_even_odd_ohm,
    )

    def realize(res_len_scale: float, w_scales: list[float],
                s_scales: list[float]) -> dict[str, Any]:
        sections = []
        for sec, wsc, ssc in zip(base["sections"], w_scales, s_scales,
                                 strict=True):
            w_new = float(sec["w_mm"]) * wsc
            s_new = float(sec["s_mm"]) * ssc
            ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
                w_new, s_new, f0, er, h_mm)
            sections.append({**sec, "w_mm": w_new, "s_mm": s_new,
                             "zee_ohm": ze, "zoo_ohm": zo,
                             "ere_e": ere_e, "ere_o": ere_o})
        res_len = res_len0 * res_len_scale
        return {**base, "sections": sections, "res_len_mm": res_len,
                "lc_mm": res_len / 2.0}

    def evaluate(design: dict[str, Any], guard_db: float) \
            -> dict[str, Any]:
        s = coupled_bpf_circuit_sparams(freqs, design)
        s11 = 20.0 * np.log10(np.abs(s[:, 0, 0]) + 1e-300)
        s21 = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
        rl = float(-s11[band].max())
        stp = float(s21[stop].max())
        min_gap = min(float(sec["s_mm"]) for sec in design["sections"])
        stop_degr = max(0.0, stp - guard_db)
        gap_viol = max(0.0, (gap_floor_mm - min_gap) / gap_floor_mm)
        return {"rl_min_db": round(rl, 6), "stop_max_db": round(stp, 6),
                "min_gap_mm": round(min_gap, 6),
                "shortfall_rl_db": round(max(0.0,
                                             targets["rl_ideal_db"] - rl), 6),
                "excess_stop_db": round(max(0.0, stp
                                            - targets["stop_ideal_db"]), 6),
                "stop_degradation_db": round(stop_degr, 6),
                "gap_violation": round(gap_viol, 6),
                "cost": round(-rl + 40.0 * stop_degr + 20.0 * gap_viol, 6)}

    def objective(trial: optuna.Trial) -> float:
        rl_scale = trial.suggest_float("res_len_scale", 0.98, 1.02)
        w = [trial.suggest_float(f"w{j}", 0.85, 1.2) for j in range(n_sec)]
        sc = [trial.suggest_float(f"s{j}", 0.6, 1.6) for j in range(n_sec)]
        return evaluate(realize(rl_scale, w, sc), stop_guard)["cost"]

    initial_params = {"res_len_scale": 1.0,
                      **{f"w{j}": 1.0 for j in range(n_sec)},
                      **{f"s{j}": 1.0 for j in range(n_sec)}}
    # 阻带守卫 = 综合初值已达水平（约束锚=初值而非理想锚）；初值点自身
    # 守卫取 −inf（自身零惩罚），此后 best 的 RL 恒 ≥ 初值 RL（见 docstring）。
    initial = evaluate(realize(1.0, [1.0] * n_sec, [1.0] * n_sec),
                       -math.inf)
    stop_guard = initial["stop_max_db"]
    initial["stop_degradation_db"] = 0.0
    initial["cost"] = round(-initial["rl_min_db"], 6)
    verbosity = optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        study = optuna.create_study(
            sampler=optuna.samplers.TPESampler(seed=seed),
            direction="minimize")
        # 确定性锚定 DOE：初值 + 单轴探针（长 ±1% / 缝 ±10% / 宽 ∓5%），
        # 给 TPE 提供初值邻域的梯度锚点（全部确定性，无随机 DOE）。
        axis_probes = [{"res_len_scale": 0.99}, {"res_len_scale": 1.01}]
        axis_probes += [{**{f"s{j}": v for j in range(n_sec)}}
                        for v in (0.9, 1.1)]
        axis_probes += [{**{f"w{j}": v for j in range(n_sec)}}
                        for v in (0.95, 1.05)]
        for probe in axis_probes:
            study.enqueue_trial({**initial_params, **probe})
        study.enqueue_trial(initial_params)     # 综合初值首点入队
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    finally:
        optuna.logging.set_verbosity(verbosity)

    bp = study.best_params
    best_params = dict(bp)
    best_design = realize(bp["res_len_scale"],
                          [bp[f"w{j}"] for j in range(n_sec)],
                          [bp[f"s{j}"] for j in range(n_sec)])
    best = evaluate(best_design, stop_guard)
    stage = "tpe" if best["cost"] < initial["cost"] else "initial"
    anchored = [t.params for t in study.trials[:len(axis_probes) + 1]]
    if not any(p == initial_params for p in anchored):
        raise TopologyCampaignError("综合初值入队点未被评估（optuna 行为漂移）")

    # 阶段 2：确定性坐标精化（pattern search，步长折半；同守卫下单调不劣化，
    # 从 TPE 最优与初值中较优者出发）。TPE 在 9 维有界域内常锁死初值，
    # 局部精化补最后一段「精算」（探针实测）。
    bounds: dict[str, tuple[float, float]] = {"res_len_scale": (0.98, 1.02)}
    steps: dict[str, float] = {"res_len_scale": 0.005}
    for j in range(n_sec):
        bounds[f"w{j}"] = (0.85, 1.2)
        bounds[f"s{j}"] = (0.6, 1.6)
        steps[f"w{j}"] = 0.03
        steps[f"s{j}"] = 0.08

    def clamp(v: float, key: str) -> float:
        lo, hi = bounds[key]
        return min(hi, max(lo, v))

    cur = dict(best_params if stage == "tpe" else initial_params)
    cur_cost = min(best["cost"], initial["cost"])
    for _ in range(3):
        improved = False
        for key, step in list(steps.items()):
            for sign in (1.0, -1.0):
                cand = dict(cur)
                cand[key] = clamp(cand[key] + sign * step, key)
                if cand[key] == cur[key]:
                    continue
                c_cost = evaluate(
                    realize(cand["res_len_scale"],
                            [cand[f"w{j}"] for j in range(n_sec)],
                            [cand[f"s{j}"] for j in range(n_sec)]),
                    stop_guard)["cost"]
                if c_cost < cur_cost - 1e-9:
                    cur, cur_cost = cand, c_cost
                    improved = True
        if not improved:
            steps = {k: v / 2.0 for k, v in steps.items()}
    if cur_cost < best["cost"] - 1e-9:
        stage = "polish"
        best_params = cur
        best_design = realize(cur["res_len_scale"],
                              [cur[f"w{j}"] for j in range(n_sec)],
                              [cur[f"s{j}"] for j in range(n_sec)])
        best = evaluate(best_design, stop_guard)

    recipe_params = {
        "order": int(proposal.order),
        "w_feed_mm": round(float(best_design["w_feed_mm"]), 4),
        "widths_mm": [round(float(s["w_mm"]), 4)
                      for s in best_design["sections"]],
        "gaps_mm": [round(float(s["s_mm"]), 4)
                    for s in best_design["sections"]],
        "res_len_mm": round(float(best_design["res_len_mm"]), 4),
        "feed_len_mm": round(float(best_design["feed_len_mm"]), 4),
    }
    return {
        "ok": True, "family": proposal.family, "order": proposal.order,
        "coupling_form": proposal.coupling_form, "spec": spec.to_dict(),
        "n_trials": int(n_trials), "seed": int(seed),
        "gap_floor_mm": float(gap_floor_mm), "stage": stage,
        "targets": {k: round(float(v), 6)
                    for k, v in targets.items()},
        "initial": {**initial, "params": initial_params},
        "best": {**best, "params": {k: round(float(v), 9)
                                    for k, v in best_params.items()}},
        "improvement": {
            "cost_delta": round(initial["cost"] - best["cost"], 6),
            "rl_delta_db": round(best["rl_min_db"] - initial["rl_min_db"], 6),
            "stop_delta_db": round(best["stop_max_db"]
                                   - initial["stop_max_db"], 6)},
        "recipe_params": recipe_params,
        "notes": [
            "裁判：coupled_bpf_circuit_sparams（真偶/奇模准静态级联，"
            "宽度台阶/开路端残差不进模型，假设清单见 openems_templates "
            "WP2.3 平行耦合 BPF 段）",
            f"目标曲线：C13 综合矩阵理想频响（RL_ideal="
            f"{targets['rl_ideal_db']:.3f}dB、±fbw 阻带上限 "
            f"{targets['stop_ideal_db']:.3f}dB）",
            "两阶段精算：TPE（初值入队+确定性单轴探针 DOE，有界域 "
            "res_len ±2%、宽 [0.85,1.2]×、缝 [0.6,1.6]×）→ 确定性坐标"
            "精化（步长折半）；"
            f"阻带守卫=初值已达水平 {stop_guard:.3f}dB（±fbw），"
            "best 的 RL 恒 ≥ 初值 RL（代价结构可证，见 docstring）",
            "C13 coupling_matrix_extract 反提对含馈线/λ/4 段参考面相位的"
            "电路裁判输出不收敛（原始 rms ~6e-2 > 1e-2 门，根因 Ω 域非有理"
            "相位；收敛口径=幅值域 magnitude：fit 8.7e-3 + kij 1.95e-2，见 "
            "tests/unit/test_c13_refplane_deembed.py），"
            "故精算闭环以响应域 hinge 收敛为准",
        ],
    }


def stage_design_to_sandbox(recipe_params: dict[str, Any], name: str, *,
                            root: Any = None) -> dict[str, Any]:
    """把精算后的配方参数落成沙箱草稿（写面隔离）。

    仅写 runs/recipe_sandbox（或显式 root）内以 name 派生的草稿文件，
    生效必须走既有三层 Gate——本函数不做任何 promote。
    """
    from rfauto.service.agent_sandbox import RecipeSandbox

    if not name.endswith(".yaml"):
        name = f"{name}.yaml"
    draft_doc = {
        "model": "coupled_bpf", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in recipe_params.items()},
        "meta": {"origin": "e10_topology_service",
                 "note": "生成式综合 E10 首案例草稿；数值由综合链+战役产出"},
    }
    import yaml

    return RecipeSandbox(root).write_yaml(
        name, yaml.safe_dump(draft_doc, allow_unicode=True, sort_keys=False))


# ─── JSON 进出入口（CLI/MCP 薄壳消费）─────────────────────────
_SPEC_KEYS = frozenset({"f0_ghz", "fbw", "rl_db", "stop_rejection_db",
                        "stop_fbw_mult", "order_hint", "family_hint"})


def propose_topology(
    spec: Any,
    *,
    proposer: str = "rule_based",
    campaign: bool = False,
    n_trials: int = DEFAULT_N_TRIALS,
    seed: int = DEFAULT_SEED,
    gap_floor_mm: float = DEFAULT_GAP_FLOOR_MM,
    sandbox_name: str | None = None,
    promote: bool = False,
) -> dict[str, Any]:
    """E10 链路 JSON 进出：spec → typed 提议 → 综合初值（→ 可选小战役精算
    → 可选沙箱草稿 → 可选 promote 准入链）。

    - spec：FilterSpec 字段 dict（f0_ghz/fbw/rl_db 必填；stop_rejection_db/
      stop_fbw_mult/order_hint/family_hint 可选）——用户侧确定性数字；
    - proposer：注册表名（默认 rule_based；llm 提议器须注入 llm_call，
      JSON 入口不可用，显式报错不静默回退）；
    - campaign=True 时对 campaign_capable 家族跑 run_fine_campaign
      （离线秒级，电路裁判）；不具备能力的家族如实 skipped；
    - sandbox_name 给定时把（精算后的）recipe_params 落沙箱草稿
      （写面隔离，规则 6；本函数不做 promote）；
    - promote=True（须同时给 sandbox_name）时草稿继续走
      proposal_chain_service.promote_topology_draft（L1 白名单 / L2 模板离线
      试运行 / L3 token → 迁 runs/recipe_sandbox/promoted/），结果落
      out["promote"]；未给 sandbox_name 时如实 skipped。
    异常一律折成 {ok: False, error}（确定性、可序列化）。
    """
    try:
        if not isinstance(spec, dict):
            raise TopologyProposalError(
                f"spec 须为 dict，实得 {type(spec).__name__}")
        unknown = sorted(set(spec) - _SPEC_KEYS)
        if unknown:
            raise TopologyProposalError(
                f"spec 含未知字段 {unknown}（可用: {sorted(_SPEC_KEYS)}）")
        fspec = FilterSpec(**spec)
        try:
            engine = TopologyProposerRegistry.create(proposer)
        except TypeError as exc:
            raise TopologyProposalError(
                f"提议器 {proposer} 需要额外注入参数，JSON 入口不可用: {exc}"
            ) from None
        proposal = engine.propose(fspec)
        initial = design_initial_values(proposal, fspec)
        out: dict[str, Any] = {
            "ok": True, "proposer": engine.name,
            "proposal": proposal.to_dict(), "initial": initial,
            "campaign": None, "sandbox": None, "promote": None,
        }
        recipe_params: dict[str, Any] | None = None
        if campaign:
            if initial["campaign_capable"]:
                camp = run_fine_campaign(
                    proposal, fspec, n_trials=int(n_trials), seed=int(seed),
                    gap_floor_mm=float(gap_floor_mm))
                out["campaign"] = camp
                recipe_params = dict(camp.get("recipe_params") or {})
            else:
                out["campaign"] = {
                    "ok": False, "skipped": True,
                    "reason": f"家族 {proposal.family} 不具备战役精算能力"}
        if sandbox_name:
            if recipe_params is None:
                recipe_params = dict(initial.get("template_params") or {})
            out["sandbox"] = stage_design_to_sandbox(recipe_params, sandbox_name)
        if promote:
            if out["sandbox"] and out["sandbox"].get("draft"):
                from rfauto.service.proposal_chain_service import (
                    promote_topology_draft,
                )
                out["promote"] = promote_topology_draft(out["sandbox"]["draft"])
            else:
                out["promote"] = {
                    "ok": False, "skipped": True,
                    "reason": "promote 需要先落沙箱草稿（给 sandbox_name）"}
    except (TopologyProposalError, TopologyCampaignError, KeyError,
            ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return out
