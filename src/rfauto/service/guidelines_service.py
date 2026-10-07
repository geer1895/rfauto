"""EC-6 guidelines 上下文检索服务（W5-D）：坑账/playbook/rules 三源确定性检索。

规格（runs/research_seats_20261004/se_specs3/SPECS.md §2.2.3）：
- 检索链全确定性（零 LLM 零网络，#139 语义）：topic→类别/别名映射→
  pitfalls_index（类别或 id/title/lesson_one_line 关键词）+ playbook rules
  （id/root_cause_family/notes/pit_refs 关键词）+ rules.yaml（id/category/
  description 关键词）；
- 每条带 {source, ref, category, text, anchor} 可溯源——坑号 #NNN 为
  出处标记（D1 裁决保留口径），A 系锚 项目规则 行号；
- 未知名 topic → ok=False errors 非空（附已知词表，不凑）；
- 同输入两次调用逐位一致（源文件序即输出序，零随机）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["get_guidelines_for", "repo_root"]

#: topic→pitfalls 类别别名（词表外主题的确定性映射；词表=
#: knowledge/pitfalls_index.json 的 category_vocab）
TOPIC_ALIASES: dict[str, list[str]] = {
    "fdtd": ["openems"],
    "csxcad": ["openems"],
    "openems": ["openems"],
    "hfss": ["hfss"],
    "pyaedt": ["hfss"],
    "aedt": ["hfss"],
    "kicad": ["kicad"],
    "comsol": ["comsol"],
    "elmer": ["elmer"],
}

_SOURCES_ORDER = ("pitfalls", "playbook", "rules")


def repo_root() -> Path:
    """仓根（本文件三层深 src/rfauto/service/，CWD 无关锚）。"""
    return Path(__file__).resolve().parents[3]


def _load_sources(knowledge_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """读三源（缺文件/坏结构抛 ValueError，由入口归一 error 信封）。"""
    pitfalls_path = knowledge_root / "pitfalls_index.json"
    playbook_path = knowledge_root / "diagnostics" / "playbook.yaml"
    rules_path = knowledge_root / "rules.yaml"
    if not pitfalls_path.is_file():
        raise ValueError(f"pitfalls_index.json 不存在: {pitfalls_path}")
    if not playbook_path.is_file():
        raise ValueError(f"playbook.yaml 不存在: {playbook_path}")
    if not rules_path.is_file():
        raise ValueError(f"rules.yaml 不存在: {rules_path}")
    pitfalls = json.loads(pitfalls_path.read_text(encoding="utf-8"))
    playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8")) or {}
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    if not isinstance(pitfalls, dict) or not isinstance(pitfalls.get("entries"), list):
        raise ValueError("pitfalls_index.json 结构不符（缺 entries 列表）")
    return pitfalls, playbook, rules


def get_guidelines_for(
    topic: str, knowledge_root: str | Path | None = None
) -> dict[str, Any]:
    """按主题检索坑规指南（确定性检索，信封进出——规则 4）。

    Args:
        topic: 主题词（如 openems、hfss、kicad、fdtd、校准；剥空白后须非空；
            大小写不敏感）。
        knowledge_root: 知识库根目录（缺省仓根 knowledge/；测试传 tmp 样本）。

    Returns:
        dict: ok 信封 {ok, topic, hits: [{source, ref, category, text, anchor,
        ...}], counts: {pitfalls, playbook, rules, total}}；空 topic/未知
        topic/数据源缺失 → error 信封 {ok: False, errors: [...]}。
    """
    key = (topic or "").strip().lower()
    if not key:
        return error_envelope(["topic 为空；给一个主题词（如 openems/hfss/kicad/fdtd）"])
    root = Path(knowledge_root) if knowledge_root is not None else repo_root() / "knowledge"
    try:
        pitfalls, playbook, rules = _load_sources(root)
    except (ValueError, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return error_envelope([f"知识源加载失败: {exc}"])

    vocab = [str(c) for c in pitfalls.get("category_vocab") or []]
    categories = set(TOPIC_ALIASES.get(key, []))
    if key in vocab:
        categories.add(key)

    hits: list[dict[str, Any]] = []

    # 源 1：pitfalls 坑账（类别命中或 id/title/lesson 关键词命中）
    for entry in pitfalls["entries"]:
        category = str(entry.get("category") or "")
        hay = " ".join(
            str(entry.get(k) or "") for k in ("id", "title", "lesson_one_line", "category")
        ).lower()
        if category in categories or key in hay:
            src = entry.get("source") or {}
            hits.append(
                {
                    "source": "pitfalls",
                    "ref": str(entry.get("id") or ""),
                    "category": category,
                    "text": (
                        f"{entry.get('title', '')}——{entry.get('lesson_one_line', '')}"
                    ),
                    "anchor": f"{src.get('file', '?')}:{src.get('line_start', '?')}",
                    "devlog_ref": entry.get("devlog_ref"),
                }
            )

    # 源 2：playbook 失败指纹规则（id/root_cause_family/notes/pit_refs 关键词）
    for rule in playbook.get("rules") or []:
        pit_refs = [str(p) for p in rule.get("pit_refs") or []]
        hay = " ".join(
            [
                str(rule.get("id") or ""),
                str(rule.get("root_cause_family") or ""),
                str(rule.get("notes") or ""),
                " ".join(pit_refs),
            ]
        ).lower()
        if key in hay:
            hits.append(
                {
                    "source": "playbook",
                    "ref": str(rule.get("id") or ""),
                    "category": str(rule.get("root_cause_family") or ""),
                    "text": str(rule.get("notes") or ""),
                    "anchor": f"knowledge/diagnostics/playbook.yaml#{rule.get('id', '')}",
                    "pit_refs": pit_refs,
                    "forensic_commands": [
                        str(c) for c in rule.get("forensic_commands") or []
                    ],
                }
            )

    # 源 3：rules.yaml 知识库规则（id/category/description 关键词）
    for rule in rules.get("rules") or []:
        hay = " ".join(
            [
                str(rule.get("id") or ""),
                str(rule.get("category") or ""),
                str(rule.get("description") or ""),
            ]
        ).lower()
        if key in hay:
            hits.append(
                {
                    "source": "rules",
                    "ref": str(rule.get("id") or ""),
                    "category": str(rule.get("category") or ""),
                    "text": str(rule.get("description") or ""),
                    "anchor": f"knowledge/rules.yaml#{rule.get('id', '')}",
                }
            )

    if not hits:
        return error_envelope(
            [
                f"未知主题: {topic!r}（零命中，不凑结果）",
                "已知类别词表: " + ", ".join(vocab),
                "支持别名: " + ", ".join(sorted(TOPIC_ALIASES)),
            ]
        )
    counts: dict[str, Any] = {src: 0 for src in _SOURCES_ORDER}
    for hit in hits:
        counts[hit["source"]] = counts.get(hit["source"], 0) + 1
    counts["total"] = len(hits)
    return ok_envelope(topic=topic, hits=hits, counts=counts)
