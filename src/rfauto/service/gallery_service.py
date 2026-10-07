"""PR-5 画廊交互化：模板卡 + 名义参数 + 闭式预览通道（数值只在确定性内核）。

规格=研究扩充 round16 §四 PR-5："参数滑块→闭式
响应即时预览（calculators 端点零后端计算）"。职责切分：

- **服务层**：模板卡（TEMPLATE_META/TEMPLATE_NOMINAL 全量，只读）+ 预览
  通道映射（:data:`PREVIEW_RULES` 显式白名单）+ 初始参数解析（名义参数/
  ``@f0_ghz`` → calculator 形参）+ 滑块量程（名义 ±50%，步长 1%）；
- **前端**：滑块改值 → ``POST /api/calculators/run``（既有端点，闭式纯
  函数零 EM 求解）→ 渲染返回字段；映射逻辑零 JS；
- **诚实边界**：未映射模板 ``preview=None``（"未配闭式预览通道"如实显示，
  不猜不硬凑）；映射规则的形参来源必须能在 nominal/meta 解出有限值，
  解不出则该模板 preview=None（构造期自检，测试钉全量）。

物理数字出处：预览输出全部来自 CALCULATOR_REGISTRY 闭式纯函数（确定性
内核，规则 7）；滑块初值=注册表名义参数（meta.yaml 同源），不是本模块
产生的新数字。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.service.envelope import ok_envelope

__all__ = [
    "FAMILY_LABELS",
    "PREVIEW_RULES",
    "RECOMMEND_F0_TOL",
    "TEMPLATE_FAMILIES",
    "gallery_cards",
    "recommend_templates",
    "resolve_preview_params",
    "template_family",
]

#: 模板 → 闭式预览通道（显式白名单）。map: calculator 形参 → 来源
#: （名义参数键 | ``"@f0_ghz"``=TEMPLATE_META.f0_ghz）。形参全集必须与
#: CALCULATOR_REGISTRY 对应 calculator 的必填集一致（不一致由 run 端点
#: 显式报缺，测试逐规则真跑钉住）。
PREVIEW_RULES: dict[str, dict[str, dict[str, str]]] = {
    "siw": {
        "siw_analysis": {
            "w_mm": "w_mm", "d_mm": "d_mm", "s_mm": "s_mm",
            "epsilon_r": "er", "freq_ghz": "@f0_ghz",
        },
    },
    "slotline": {
        "slotline_analysis": {
            "w_mm": "w_mm", "h_mm": "h_mm", "epsilon_r": "er",
            "freq_ghz": "@f0_ghz",
        },
    },
}

#: F0 占位源键（TEMPLATE_META.f0_ghz）。
_F0_KEY = "@f0_ghz"

#: 推荐器 f0 带内容差缺省档（sp_specs6 §VI-3 预声明 ±30%）。
RECOMMEND_F0_TOL = 0.30


# ── 模板族分类（X1 席 PR-5 静态画廊页 data-* 数据源）─────────────────────────
#
# 单一事实源在本模块：两个静态导出器（scripts/gallery_export.py QW-4 单页
# 画廊、scripts/capability_cards_export.py QW-5 能力卡索引）渲染 data-*
# 属性时消费，前端零分类逻辑。
# 归类依据=能力卡"适用场景"拓扑文本与模板库总表（docs/capability_cards/
# <t>.md、docs_site/catalog/index.md）逐模板显式策展，非字段推断——
# 未登记模板如实回退 "other"（不猜；注入 fixture 同样安全）。
# 新模板注册须同批登记族键（test_gallery_interactive_service 全量覆盖钉，
# #231/#304 注册表消费者纪律）。

#: 族键 → 中文标签（chips 渲染单源；含 "other" 如实兜底标签）。
FAMILY_LABELS: dict[str, str] = {
    "line": "传输线与均匀段",
    "filter": "滤波器与双工器",
    "coupler": "功分/耦合/移相/巴伦",
    "antenna": "天线与阵列",
    "transition": "过渡与馈电夹具",
    "fss": "FSS/反射阵（EMC 面）",
    "material": "材料提取与测量校准件",
    "other": "其他",
}

#: 模板名 → 族键（71 键全量显式映射；键序=字母序，与注册表同序便于对账）。
TEMPLATE_FAMILIES: dict[str, str] = {
    "atten_pi": "material",
    "atten_t": "material",
    "bend": "line",
    "branchline": "coupler",
    "branchline_2sect": "coupler",
    "cline_coupler": "coupler",
    "coax_waveguide_transition": "transition",
    "coil_nfc": "antenna",
    "combline": "filter",
    "coupled_bpf": "filter",
    "coupled_line": "line",
    "cps": "line",
    "cpw": "line",
    "diplexer": "filter",
    "dipole": "antenna",
    "embedded_ms": "line",
    "fgcpw": "line",
    "gysel": "coupler",
    "hairpin": "filter",
    "hairpin_alt": "filter",
    "helix": "antenna",
    "hmsiw": "line",
    "ifa": "antenna",
    "interdigital": "filter",
    "inverted_ms": "line",
    "isl_shielded": "line",
    "lange": "coupler",
    "loop": "antenna",
    "marchand_balun": "coupler",
    "mline": "line",
    "mmwave_series_array": "antenna",
    "monopole": "antenna",
    "ms_array_NxN": "fss",
    "ms_cross": "fss",
    "ms_jcross": "fss",
    "ms_patch": "fss",
    "ms_ring_patch": "fss",
    "msl_cpw": "transition",
    "msl_siw_taper": "transition",
    "msl_slot_transition": "transition",
    "nway_wilkinson": "coupler",
    "patch": "antenna",
    "patch_array_1x4": "antenna",
    "patch_array_2x2": "antenna",
    "patch_array_series": "antenna",
    "patch_eep_1x4": "antenna",
    "patch_eep_2x2": "antenna",
    "pifa": "antenna",
    "pyramid_horn": "antenna",
    "qwt_multisection": "transition",
    "ratrace": "coupler",
    "ridged_wg": "line",
    "ring_resonator": "material",
    "schiffman": "coupler",
    "sicl": "line",
    "sir_bpf": "filter",
    "siw": "line",
    "slot": "antenna",
    "slotline": "line",
    "slotline_lumped": "line",
    "sma_launcher": "transition",
    "stepped_impedance": "filter",
    "stripline": "line",
    "suspended_stripline": "line",
    "tjunc": "coupler",
    "varactor_bpf": "filter",
    "via": "line",
    "vivaldi_tsa": "antenna",
    "wilkinson": "coupler",
    "wstep": "line",
    "xcheb_bpf4": "filter",
}


def template_family(name: str) -> str:
    """模板名 → 族键；未登记如实 "other"（注入 fixture/新模板不炸不猜）。"""
    return TEMPLATE_FAMILIES.get(str(name), "other")


def resolve_preview_params(
    rule_map: dict[str, str],
    nominal: dict[str, Any],
    meta_f0: Any,
) -> dict[str, float] | None:
    """映射规则 → calculator 初始参数 dict；任一来源解不出有限数值→None。"""
    params: dict[str, float] = {}
    for calc_param, source in rule_map.items():
        value = meta_f0 if source == _F0_KEY else nominal.get(source)
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not math.isfinite(float(value)):
            return None
        params[calc_param] = float(value)
    return params


def _slider_meta(params: dict[str, float], sliders: list[str]) -> dict[str, dict[str, float]]:
    """滑块量程（名义 ±50%，步长 1% 名义值；下限防零防负：max(min, step)）。"""
    out: dict[str, dict[str, float]] = {}
    for key in sliders:
        v = params[key]
        step = abs(v) / 100.0 if v != 0.0 else 0.01
        out[key] = {
            "min": round(max(v * 0.5, step), 9),
            "max": round(v * 1.5, 9),
            "step": round(step, 9),
            "initial": round(v, 9),
        }
    return out


def gallery_cards() -> dict[str, Any]:
    """模板画廊交互卡清单（JSON 信封；TEMPLATE_META 全量、字母序、只读）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

    cards: list[dict[str, Any]] = []
    for name in sorted(TEMPLATE_META):
        meta = TEMPLATE_META[name] or {}
        nominal = TEMPLATE_NOMINAL.get(name) or {}
        rule_entry = PREVIEW_RULES.get(name)
        preview: dict[str, Any] | None = None
        if rule_entry:
            calc_name, rule_map = next(iter(rule_entry.items()))
            params = resolve_preview_params(rule_map, nominal, meta.get("f0_ghz"))
            if params is not None:
                sliders = sorted(
                    (p for p, src in rule_map.items() if src != _F0_KEY))
                preview = {
                    "calculator": calc_name,
                    "params": {k: round(v, 9) for k, v in sorted(params.items())},
                    "sliders": sliders,
                    "slider_meta": _slider_meta(params, sliders),
                    "sources": dict(sorted(rule_map.items())),
                }
        cards.append({
            "name": name,
            "topology": meta.get("topology"),
            "f0_ghz": meta.get("f0_ghz"),
            "n_ports": meta.get("n_ports"),
            "params": list(meta.get("params") or []),
            "param_semantics": meta.get("param_semantics"),
            "nominal_params": dict(nominal),
            "preview": preview,
            # UX-A7 画廊深链（VI-3 并档）：模板文档 meta.yaml 仓库相对路径
            # 一行（路径存在性由 test 逐一 os.path 断言，71 卡全链接）。
            "docs_link": f"docs/templates/{name}/meta.yaml",
        })
    return ok_envelope(
        n_templates=len(cards),
        n_previews=sum(1 for c in cards if c["preview"] is not None),
        preview_rules=sorted(PREVIEW_RULES),
        cards=cards,
    )


# ── SO-3 模板推荐器（VI-3，2026-10-05 W2-B 席）────────────────────────────────
#
# 确定性 filter+rank（铁律 7：零 LLM 零数值产出——只检索 TEMPLATE_META
# 元数据，输出=模板名+排序分解，不产任何物理数字；f0_dev 是检索排序键
# =查询 f0 与元数据 f0 的相对偏差，非物理预测）。全序确定性保证：排序
# 键末位=模板名字典序（同键并列稳定、跨进程跨平台逐位一致）。


def _recommend_f0_dev(meta_f0: Any, f0_ghz: float) -> float | None:
    """模板 f0 → 主排序键 |f_t−f0|/f0；元数据 f0 缺失/非有限如实 None
    （调用方按"不可排序"处理，不猜缺省值）。"""
    if not isinstance(meta_f0, (int, float)) or isinstance(meta_f0, bool):
        return None
    meta_f0 = float(meta_f0)
    if not math.isfinite(meta_f0) or meta_f0 <= 0.0:
        return None
    return abs(meta_f0 - f0_ghz) / f0_ghz


def _recommend_topology_match(name: str, meta: dict[str, Any],
                              wanted: str) -> bool:
    """topology 族匹配：族键/族标签精确命中，或模板 topology 文本子串
    （大小写不敏感；"bpf"/"filter"/"阵列"等自然语输入均可命中）。"""
    fam = template_family(name)
    wanted_cf = str(wanted).strip().casefold()
    if not wanted_cf:
        return True
    if wanted_cf == fam or wanted_cf == FAMILY_LABELS.get(fam, ""):
        return True
    topo_text = str(meta.get("topology") or "")
    return wanted_cf in topo_text.casefold()


def _recommend_keywords_match(name: str, meta: dict[str, Any],
                              keywords: str) -> bool:
    """keywords 子串过滤（规格口径：name/topology/param_semantics 三字段；
    空格分词后每个 token 须至少命中一字段，大小写不敏感）。"""
    text = " ".join((
        str(name),
        str(meta.get("topology") or ""),
        str(meta.get("param_semantics") or ""),
    )).casefold()
    return all(tok in text for tok in str(keywords).split())


def _recommend_semantics_cover(meta: dict[str, Any]) -> int:
    """次排序键：meta.params 中在 param_semantics 文本里有解释的键数
    （元数据完整性度量，非物理量）。"""
    semantics = str(meta.get("param_semantics") or "").casefold()
    return sum(1 for p in (meta.get("params") or [])
               if str(p).casefold() in semantics)


def _recommend_validate_permutation(order: Any,
                                    candidates: list[str]) -> list[str] | None:
    """provider 返回 → 候选名单置换；非法（非列表/重复/越界/缺名）如实
    None（调用方走降级兜底，#105 同族：决策通道永不阻塞主路径）。"""
    if not isinstance(order, (list, tuple)):
        return None
    names = [str(x) for x in order]
    if sorted(names) != sorted(candidates):
        return None
    return names


def recommend_templates(
    *,
    f0_ghz: float,
    topology: str | None = None,
    n_ports: int | None = None,
    fbw: float | None = None,
    keywords: str | None = None,
    top_k: int = 5,
    f0_tol: float = RECOMMEND_F0_TOL,
    rerank_provider: Any = None,
) -> dict[str, Any]:
    """模板推荐（SO-3 断点 A2 闭环）：指标查询 → 确定性 filter+rank 排序。

    **确定性内核**（铁律 7）：只检索 :data:`TEMPLATE_META` 元数据，输出=
    模板名+排序分解，零 LLM 零物理数字产出。全序=四元组排序键（主键 f0
    贴近度、次键 param_semantics 覆盖数、三键 preview 白名单命中、并列
    模板名字典序），跨进程逐位可复现。

    filter（全部命中才入选）：
    - topology：族键/族标签精确或 topology 文本子串（大小写不敏感）；
    - n_ports：TEMPLATE_META.n_ports 相等；
    - f0 带内：|f_t−f0|/f0 ≤ f0_tol（缺省 ±30%，规格 VI-3 预声明）；
    - keywords：空格分词逐 token 对 name/topology/param_semantics 子串。

    rank（升序）：主键=|f_t−f0|/f0；次键=param_semantics 覆盖键数（多者
    优先）；三键=PREVIEW_RULES 命中（有闭式预览通道者优先）；并列=name
    字典序。

    Args:
        f0_ghz: 查询中心频率 GHz（正有限，必填）。
        topology: 族键（line/filter/coupler/antenna/transition/fss/
            material）、族中文标签或 topology 文本子串。
        n_ports: 端口数相等过滤（ms_array_NxN 类软激励面 n_ports=0）。
        fbw: 相对带宽——**预留形参**：TEMPLATE_META 无逐模板 fbw 字段，
            当前面如实只回显进 query（不猜语义不硬凑）。
        keywords: 子串过滤词（空格分词，AND 语义）。
        top_k: 返回条数（≥1）。
        f0_tol: f0 带内容差（0<tol<1；缺省 0.30）。
        rerank_provider: **System One 可选重排口（缺省 None=纯确定性路径
            逐字节不变）**。契约：以 ``provider(candidates, query)`` 调用——
            ``candidates``=确定性序候选名单（list[str]）、``query``=查询
            context dict；返回值可为候选名单置换（list[str]），或
            :func:`rfauto.service.systemone_service.ask_systemone` 同形信封
            （``{"answer": {"order": [...]}}``，kind=ordering 口径）。任何
            异常/非法（非置换）→ 如实降级：保持确定性序 + ``degraded:
            true`` + ``degrade_reason``（#105：决策通道永不阻塞主路径）。
            本模块不 import systemone——调用方自行传
            ``lambda c, q: ask_systemone({"kind": "ordering", ...})``。

    Returns:
        dict: ok 信封 ``{ok, query, n_candidates, recommendations, provider,
        reranked, degraded, degrade_reason}``；recommendations 每条含
        name/family/family_label/topology/f0_ghz/n_ports/docs_link/preview
        与 rank 排序分解。
    """
    try:
        f0 = float(f0_ghz)
    except (TypeError, ValueError):
        # 非数值入参走 degraded 信封不抛（审查 P3：CLI/MCP 面传坏值时
        # 与 f0≤0 同口径如实降级，#122 不炸面）
        return ok_envelope(
            query={"f0_ghz": f0_ghz}, n_candidates=0, recommendations=[],
            provider="deterministic", reranked=False, degraded=True,
            degrade_reason=f"f0_ghz 须为正有限数，得到 {f0_ghz!r}")
    if not math.isfinite(f0) or f0 <= 0.0:
        return ok_envelope(
            query={"f0_ghz": f0_ghz}, n_candidates=0, recommendations=[],
            provider="deterministic", reranked=False, degraded=True,
            degrade_reason=f"f0_ghz 须为正有限数，得到 {f0_ghz!r}")
    tol = float(f0_tol)
    if not (0.0 < tol < 1.0):
        return ok_envelope(
            query={"f0_ghz": f0, "f0_tol": f0_tol}, n_candidates=0,
            recommendations=[], provider="deterministic", reranked=False,
            degraded=True, degrade_reason=f"f0_tol 须在 (0,1)，得到 {f0_tol!r}")
    k = int(top_k)
    if k < 1:
        return ok_envelope(
            query={"f0_ghz": f0, "top_k": top_k}, n_candidates=0,
            recommendations=[], provider="deterministic", reranked=False,
            degraded=True, degrade_reason=f"top_k 须 ≥1，得到 {top_k!r}")
    if n_ports is not None:
        try:
            n_ports = int(n_ports)
        except (TypeError, ValueError):
            return ok_envelope(
                query={"f0_ghz": f0, "n_ports": n_ports}, n_candidates=0,
                recommendations=[], provider="deterministic", reranked=False,
                degraded=True,
                degrade_reason=f"n_ports 须为整数，得到 {n_ports!r}")

    from rfauto.adapters.openems_templates import TEMPLATE_META

    query_echo = {
        "f0_ghz": f0, "topology": topology, "n_ports": n_ports, "fbw": fbw,
        "keywords": keywords, "f0_tol": tol, "top_k": k,
    }
    rows: list[tuple[tuple[float, int, int, str], dict[str, Any]]] = []
    for name, meta in sorted(TEMPLATE_META.items()):
        if topology is not None and not _recommend_topology_match(
                name, meta, str(topology)):
            continue
        if n_ports is not None and meta.get("n_ports") != int(n_ports):
            continue
        f0_dev = _recommend_f0_dev(meta.get("f0_ghz"), f0)
        if f0_dev is None or f0_dev > tol:
            continue
        if keywords and not _recommend_keywords_match(name, meta, keywords):
            continue
        sem_cover = _recommend_semantics_cover(meta)
        preview_hit = 1 if name in PREVIEW_RULES else 0
        card = {
            "name": name,
            "family": template_family(name),
            "family_label": FAMILY_LABELS.get(template_family(name), ""),
            "topology": meta.get("topology"),
            "f0_ghz": meta.get("f0_ghz"),
            "n_ports": meta.get("n_ports"),
            "docs_link": f"docs/templates/{name}/meta.yaml",
            "preview": bool(preview_hit),
            "rank": {
                "f0_dev": round(f0_dev, 9),
                "semantics_covered": sem_cover,
                "preview": bool(preview_hit),
            },
        }
        rows.append(((f0_dev, -sem_cover, -preview_hit, name), card))
    rows.sort(key=lambda item: item[0])
    candidates = [card for _, card in rows]

    provider_name = "deterministic"
    reranked = False
    degraded = False
    degrade_reason: str | None = None
    if rerank_provider is not None:
        try:
            raw = rerank_provider(
                [c["name"] for c in candidates],
                {k_: v for k_, v in query_echo.items()})
            order = (raw.get("answer", {}).get("order")
                     if isinstance(raw, dict) and "answer" in raw else raw)
            names = _recommend_validate_permutation(order,
                                                    [c["name"] for c
                                                     in candidates])
            if names is None:
                raise ValueError(
                    f"provider 返回非候选名单置换: {order!r}")
            by_name = {c["name"]: c for c in candidates}
            candidates = [by_name[n] for n in names]
            reranked = True
            provider_name = str(getattr(rerank_provider, "__name__",
                                        "provider"))
        except Exception as exc:  # #105：provider 故障只降级不外抛
            degraded = True
            degrade_reason = str(exc)
    return ok_envelope(
        query=query_echo,
        n_candidates=len(candidates),
        recommendations=candidates[:k],
        provider=provider_name,
        reranked=reranked,
        degraded=degraded,
        degrade_reason=degrade_reason,
    )
