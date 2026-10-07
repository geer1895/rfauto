"""EP-6 RF 设计模式库（拓扑→模式卡：问题情境/方案/权衡/反例/关联）。

规格 研究扩充 round18 §二 EP-6：
``knowledge/patterns.yaml{问题情境/方案/权衡/反例/关联}``，首批从
R006/R008/R009 战役结论提炼。

**知识治理口径**：patterns.yaml 为归属面文件（knowledge/ 不在本席可写
文件面），首批模式卡以模块内常量 ``PATTERNS`` 承载（结构=patterns.yaml
同构 schema，``to_yaml_dict`` 可确定性导出落档——晋升到 knowledge/
patterns.yaml 时由归属面执行，不双写双维护，emi_diagnostics playbook
先例同纪律）。内容**全部提炼自仓内战役结论**（knowledge/rules.yaml
R006/R008/R009，逐条 source 指回），零新物理数字（铁律 7：数字只在
rules.yaml 原文随行透传并带坑号/规则号出处）。

查询面（确定性）：``search_patterns``（关键词命中计数评分，平局按 id
升名）；``pattern_by_topology``（关联拓扑键精确匹配）；``list_patterns``。

接口纪律：dict/JSON 进出；零网络零 IO；纯 stdlib。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PATTERNS",
    "PATTERNS_SCHEMA",
    "list_patterns",
    "pattern_by_topology",
    "search_patterns",
    "to_yaml_dict",
]

PATTERNS_SCHEMA = "rfauto-patterns/v1"

#: 首批三卡（R006/R008/R009 战役结论提炼；字段=patterns.yaml schema 原文五键）
PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "id": "PAT-001",
        "title": "阻抗失配伪装成拓扑瓶颈（耦合度平台）",
        "problem_context": [
            "定向耦合器/功分器耦合度卡在非设计值平台（如 -6dB plateau）",
            "纯几何参数（臂长）扫参无法突破平台",
            "线宽名义值与实际阻抗不符（历史配方沿用了未回代的毫米数）",
        ],
        "solution": (
            "先回代核线宽-阻抗：用综合引擎（core/synthesis HJ）把配方线宽"
            "反解成实际阻抗对名义值核对；失配即改用综合定案线宽，并把线宽"
            "参数纳入二维调参面；再核对端口 renormalization 参考阻抗口径。"
        ),
        "tradeoffs": (
            "综合定案线宽=确定性初值（可复核），代价是放弃沿用旧配方毫米数；"
            "线宽进调参面后搜索维数+1，需更长战役预算。"
        ),
        "counterexamples": (
            "纯臂长（arm_len）调参在该病因下是无效维——平台由阻抗失配主导，"
            "几何调参无法突破（R006 反例实录）。"
        ),
        "relations": {
            "rules": ["R005", "R006", "R007"],
            "templates": ["branchline_coupler"],
            "modules": ["core/synthesis.py", "knowledge/rules.yaml"],
        },
        "source": "knowledge/rules.yaml R006/R005/R007（G0 gate 2026-09：2.20mm 实测 ~31ohm 偏 -12%，35.35ohm 定案 1.87mm）",
    },
    {
        "id": "PAT-002",
        "title": "预筛职责分离：fake/公式通道不承担响应预测预筛",
        "problem_context": [
            "想用解析模型/fake 通道给真机战役做候选点预筛排序",
            "跨保真排序一致性差但各通道单看都'看着对'",
        ],
        "solution": (
            "预筛职责交给校准代理（NN，LOOCV ρ 口径验收）；fake 降级为"
            "冒烟/CI/UI 通道；权威公式的正确位置=综合层、代理物理特征、"
            "锚反推——不承担响应预测。"
        ),
        "tradeoffs": (
            "校准代理需要足够真机样本才有预筛价值（样本不足期预筛空转）；"
            "换来的是排序决策不建立在排序分歧由公式看不见的物理主导"
            "（结效应/臂间耦合/馈线真实阻抗）的沙堆上。"
        ),
        "counterexamples": (
            "fake 解析模型与一切公式通道（含 Pozar 偶/奇模电路分析）的跨保真"
            "排序一致性 ρ 均 <0.7（四级实验 0.377/0.608/0.183/-0.278）——"
            "单通道'看着对'不构成预筛资格（R008 反例实录）。"
        ),
        "relations": {
            "rules": ["R008"],
            "templates": [],
            "modules": [
                "docs/fake_channel_investigation.md",
                "knowledge/rules.yaml",
                "service/rationale_memory.py",
            ],
        },
        "source": "knowledge/rules.yaml R008（v1 收官调查 2026-09-05，docs/fake_channel_investigation.md 五级实验）",
    },
    {
        "id": "PAT-003",
        "title": "辐射器件战役前置三查（网格档/参数消费/先冒烟）",
        "problem_context": [
            "辐射器件（λ0/4 空气盒）战役单点超默认 solve 上限被杀",
            "优化参数被模板静默忽略，16 点产生相同响应、代理拟合全废",
            "模板从未真跑过就直接上战役",
        ],
        "solution": (
            "战役开跑前三查：①网格档=辐射器件用 auto（λ_sub/50）或显式"
            "solve_timeout_s=36000，0.45/0.5 收敛档只留 guided 结构；②配方"
            "参数逐一核对模板消费（adapter_kit.check_param_semantics 或对"
            "TEMPLATE_META params 核对）；③模板未真跑过=先冒烟后战役"
            "（冒烟判据预声明，如谷位/深度窗）。"
        ),
        "tradeoffs": (
            "auto 网格档单点更贵（时长上限放宽到 10×）；换来战役不再整批"
            "废于单点超时或常数响应——三查均为秒级离线动作，前置成本远低于"
            "战役报废。"
        ),
        "counterexamples": (
            "feed_offset_mm 被 openEMS patch 模板静默忽略（R009 实录：优化"
            "16 点相同响应、代理拟合全废）；0.45mm base 辐射器件单点超默认"
            "10000s 上限被杀。"
        ),
        "relations": {
            "rules": ["R009"],
            "templates": ["patch_antenna"],
            "modules": [
                "service/adapter_kit.py",
                "core/anchors.py",
                "knowledge/rules.yaml",
            ],
        },
        "source": "knowledge/rules.yaml R009（patch 校准战役前置教训 2026-09-05）",
    },
)


def _as_query_list(query: Any) -> list[str]:
    """查询串 → 词元列表（空白切分；中英混排逐词匹配）。"""
    if isinstance(query, str):
        return [tok for tok in query.split() if tok]
    return [str(tok) for tok in query]


def search_patterns(query: Any) -> dict[str, Any]:
    """关键词检索：词元在 title/问题情境/方案/权衡/反例 的命中计数评分。

    全部词元至少命中一词才入榜（AND-any 语义：query 整体至少沾一词，
    避免全无关噪声）；排序 (-score, id) 确定性全序；零命中如实空榜。
    """
    tokens = _as_query_list(query)
    if not tokens:
        return {"schema": PATTERNS_SCHEMA, "query": tokens, "hits": []}
    hits: list[dict[str, Any]] = []
    for pat in PATTERNS:
        fields = [
            pat["title"], pat["solution"], pat["tradeoffs"], pat["counterexamples"],
            *pat["problem_context"], *pat["relations"]["templates"],
        ]
        text = "\n".join(fields)
        score = sum(1 for tok in tokens if tok in text)
        if score > 0:
            hits.append({"id": pat["id"], "title": pat["title"], "score": score})
    hits.sort(key=lambda h: (-h["score"], h["id"]))
    return {"schema": PATTERNS_SCHEMA, "query": tokens, "hits": hits}


def pattern_by_topology(topology: str) -> dict[str, Any]:
    """关联拓扑键精确匹配（relations.templates 含该键的卡，id 升序）。"""
    key = topology.strip()
    if not key:
        raise ValueError("topology 必须为非空字符串")
    matched = [dict(p) for p in PATTERNS if key in p["relations"]["templates"]]
    matched.sort(key=lambda p: p["id"])
    return {"schema": PATTERNS_SCHEMA, "topology": key, "patterns": matched}


def list_patterns() -> dict[str, Any]:
    """全卡清单（id/title/问题情境行数/关联计数——摘要面）。"""
    return {
        "schema": PATTERNS_SCHEMA,
        "n_patterns": len(PATTERNS),
        "patterns": [
            {
                "id": p["id"],
                "title": p["title"],
                "n_contexts": len(p["problem_context"]),
                "templates": list(p["relations"]["templates"]),
                "rules": list(p["relations"]["rules"]),
            }
            for p in PATTERNS
        ],
    }


def to_yaml_dict() -> dict[str, Any]:
    """patterns.yaml 同构导出（归属面晋升 knowledge/patterns.yaml 时直接
    yaml.safe_dump 本返回值；schema 版本头随行）。"""
    return {"schema": PATTERNS_SCHEMA, "patterns": [dict(p) for p in PATTERNS]}
