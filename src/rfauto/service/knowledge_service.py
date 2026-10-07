"""知识库统一检索 JSON 面（QW-2，服务层，规则 4：JSON 进出，CLI/MCP 是薄壳）。

对四类知识数据面做大小写不敏感子串检索（纯确定性，零 LLM）：

- ``rules``   knowledge/rules.yaml（规则 id/描述/hint/公式/适用模型）；
- ``anchors`` knowledge/anchors.yaml（锚 id/状态/量名/语义/模板族，
  复用 infra.anchors_store 单源装载器含 mtime 缓存与 #105 best-effort）；
- ``playbook`` knowledge/diagnostics/playbook.yaml（失败指纹库规则 id/
  根因族/症状指纹/取证命令）；
- ``fab``     knowledge/fab_profiles/*.yaml（fab 剖面名/来源/核验状态）。

无命中是正常结果（ok=True + 零 hits），不是错误；非法 scope/空 query 才
ok=False。路径缺省锚定源码布局仓根（与 infra.diagnosis 同口径），测试可
逐路径注入 tmp 构造数据。检索只读，零改写（Agent 写面隔离，规则 6）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rfauto.infra.anchors_store import default_anchors_path, load_anchors
from rfauto.service.envelope import ok_envelope

#: 知识库根（源码布局；service → rfauto → src → 仓根）
_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"

_VALID_SCOPES = ("all", "rules", "anchors", "playbook", "fab")

#: snippet 缺省上限（字符）
_SNIPPET_MAX_DEFAULT = 160

#: 单 scope 命中条数缺省上限（输出体积守卫）
_LIMIT_DEFAULT = 50

#: 检索窗口：命中点前后各取的字符数（再整体截到 snippet_max）
_SNIPPET_CONTEXT_CHARS = 48


def _clean_text(value: Any) -> str:
    """任意 YAML 标量/列表 → 单行规范化文本（空白折叠，None → 空串）。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            parts.append(_clean_text(k))
            parts.append(_clean_text(v))
        return " ".join(p for p in parts if p)
    if isinstance(value, (list, tuple, set)):
        return " ".join(p for p in (_clean_text(v) for v in value) if p)
    return " ".join(str(value).split())


def _make_snippet(text: str, query: str, snippet_max: int) -> str:
    """取命中点附近窗口，折叠空白后截断（≤ snippet_max，截断补省略号）。"""
    lowered = text.lower()
    idx = lowered.find(query.lower())
    if idx < 0:
        window = text
    else:
        start = max(0, idx - _SNIPPET_CONTEXT_CHARS)
        end = min(len(text), idx + len(query) + _SNIPPET_CONTEXT_CHARS)
        window = text[start:end]
    if len(window) > snippet_max:
        window = window[: max(0, snippet_max - 1)] + "…"
    return window


def _load_yaml(path: Path) -> dict[str, Any]:
    """读 YAML 映射（缺失/损坏 → 空映射，检索面如实零命中不阻塞）。"""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return data if isinstance(data, dict) else {}


def _search_rules(path: Path, query: str) -> list[dict[str, Any]]:
    data = _load_yaml(path)
    hits = []
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        text = _clean_text({
            "id": rule.get("id"), "category": rule.get("category"),
            "description": rule.get("description"), "hint": rule.get("hint"),
            "formula": rule.get("formula"), "example": rule.get("example"),
            "values": rule.get("values"),
            "applicable_models": rule.get("applicable_models"),
            "verify": rule.get("verify")})
        if query.lower() in text.lower():
            hits.append({"source": "rules", "name": str(rule.get("id") or ""),
                         "snippet": _make_snippet(text, query,
                                                  _SNIPPET_MAX_DEFAULT),
                         "path": str(path)})
    return hits


def _search_anchors(path: Path, query: str) -> list[dict[str, Any]]:
    # 单源装载器（mtime 缓存 + #105 best-effort 空集）；raw 透传检索。
    anchor_set = load_anchors(path)
    hits = []
    for rec in anchor_set.records:
        raw = rec.raw
        text = _clean_text({
            "anchor_id": rec.anchor_id, "kind": rec.kind,
            "status": rec.status, "value": raw.get("value"),
            "quantity": raw.get("quantity"),
            "template_family": rec.template_family,
            "engine_pair": rec.engine_pair, "domain": raw.get("domain")})
        if query.lower() in text.lower():
            hits.append({"source": "anchors", "name": rec.anchor_id,
                         "snippet": _make_snippet(text, query,
                                                  _SNIPPET_MAX_DEFAULT),
                         "path": str(path)})
    return hits


def _search_playbook(path: Path, query: str) -> list[dict[str, Any]]:
    data = _load_yaml(path)
    hits = []
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        text = _clean_text({
            "id": rule.get("id"),
            "root_cause_family": rule.get("root_cause_family"),
            "symptom_fingerprints": rule.get("symptom_fingerprints"),
            "applicable_templates": rule.get("applicable_templates"),
            "forensic_commands": rule.get("forensic_commands"),
            "note": rule.get("note")})
        if query.lower() in text.lower():
            hits.append({"source": "playbook", "name": str(rule.get("id") or ""),
                         "snippet": _make_snippet(text, query,
                                                  _SNIPPET_MAX_DEFAULT),
                         "path": str(path)})
    return hits


def _search_fab(fab_dir: Path, query: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not fab_dir.is_dir():
        return hits
    for prof_path in sorted(fab_dir.glob("*.yaml")):
        data = _load_yaml(prof_path)
        profile = data.get("profile")
        if not isinstance(profile, dict):
            continue
        text = _clean_text({
            "name": profile.get("name"),
            "profile_version": profile.get("profile_version"),
            "source_url": profile.get("source_url"),
            "verification": profile.get("verification"),
            "retrieved_date": profile.get("retrieved_date")})
        if query.lower() in text.lower():
            hits.append({"source": "fab",
                         "name": str(profile.get("name")
                                     or prof_path.stem),
                         "snippet": _make_snippet(text, query,
                                                  _SNIPPET_MAX_DEFAULT),
                         "path": str(prof_path)})
    return hits


def search_knowledge(
    query: str,
    scope: str = "all",
    *,
    limit: int = _LIMIT_DEFAULT,
    snippet_max: int = _SNIPPET_MAX_DEFAULT,
    rules_path: str | Path | None = None,
    anchors_path: str | Path | None = None,
    playbook_path: str | Path | None = None,
    fab_dir: str | Path | None = None,
) -> dict[str, Any]:
    """知识库统一检索（QW-2；大小写不敏感子串，纯确定性）。

    Args:
        query: 检索词（剥空白后非空；大小写不敏感子串匹配）。
        scope: "all" | "rules" | "anchors" | "playbook" | "fab"。
        limit: 单 scope 命中条数上限（输出体积守卫）。
        snippet_max: 单条 snippet 最大字符数。
        rules_path / anchors_path / playbook_path / fab_dir: 数据面路径
            覆盖（缺省仓根 knowledge/ 同名文件与 fab_profiles/ 目录；
            测试注入 tmp 构造数据用）。

    Returns:
        {ok, query, scope, hits: [{source, name, snippet, path}],
        counts: {scope → 命中数, total}, scanned: {scope → 扫描条数}}；
        无命中 ok=True 零 hits；空 query/非法 scope → ok=False。
    """
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "query": str(query or ""), "scope": str(scope),
                "errors": ["query 为空（剥空白后须非空）"]}
    sc = str(scope or "").strip().lower()
    if sc not in _VALID_SCOPES:
        return {"ok": False, "query": q, "scope": str(scope),
                "errors": [f"非法 scope {scope!r}（须为 "
                           f"{'/'.join(_VALID_SCOPES)}）"]}

    r_path = Path(rules_path) if rules_path else _KNOWLEDGE_DIR / "rules.yaml"
    a_path = (Path(anchors_path) if anchors_path
              else default_anchors_path())
    p_path = (Path(playbook_path) if playbook_path
              else _KNOWLEDGE_DIR / "diagnostics" / "playbook.yaml")
    f_dir = Path(fab_dir) if fab_dir else _KNOWLEDGE_DIR / "fab_profiles"

    scopes = ("rules", "anchors", "playbook", "fab") if sc == "all" else (sc,)
    runners = {"rules": lambda: _search_rules(r_path, q),
               "anchors": lambda: _search_anchors(a_path, q),
               "playbook": lambda: _search_playbook(p_path, q),
               "fab": lambda: _search_fab(f_dir, q)}
    scanned = {"rules": _count_entries(r_path, "rules"),
               "anchors": len(load_anchors(a_path)),
               "playbook": _count_entries(p_path, "rules"),
               "fab": _count_fab_profiles(f_dir)}

    hits: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for name in scopes:
        found = runners[name]()
        counts[name] = len(found)
        hits.extend(found[: max(0, int(limit))])
    # snippet 上限在 _make_snippet 缺省已用 160；显式 snippet_max 时再收紧
    if snippet_max != _SNIPPET_MAX_DEFAULT:
        for h in hits:
            if len(h["snippet"]) > snippet_max:
                h["snippet"] = h["snippet"][: max(0, snippet_max - 1)] + "…"
    counts["total"] = sum(counts.values())
    return ok_envelope(query=q, scope=sc, hits=hits, counts=counts, scanned=scanned)


def _count_entries(path: Path, key: str) -> int:
    data = _load_yaml(path)
    entries = data.get(key) or []
    return sum(1 for e in entries if isinstance(e, dict))


def _count_fab_profiles(fab_dir: Path) -> int:
    if not fab_dir.is_dir():
        return 0
    n = 0
    for prof_path in sorted(fab_dir.glob("*.yaml")):
        data = _load_yaml(prof_path)
        if isinstance(data.get("profile"), dict):
            n += 1
    return n
