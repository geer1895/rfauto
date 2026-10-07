"""QW-5 模板能力卡完整版导出器：每模板一页"适用场景/判据/已知边界"。

与 QW-4（scripts/gallery_export.py 能力卡 lite）互补：画廊=单 HTML 全模板
浏览；能力卡=每模板一页 Markdown + 索引 HTML，落 docs/capability_cards/。

数据面（全只读、全离线；逐源只挑键，零计算零物理数字——铁律 7）：
- 主源：docs/templates/<t>/meta.yaml（键集与 TEMPLATE_META 交叉钉于
  test_gallery_export；#97 口径不在 docstring 钉死键数）；
- 回退：TEMPLATE_META（param_semantics/mesh_note/topology 的全量覆盖面，
  meta.yaml 缺该键时回退，两源一致性同钉）；
- 判据：core/anchors 锚注册表（通配 + 专属覆盖，infra/anchors_store 装载）；
- 失败模式坑账链：knowledge/diagnostics/playbook.yaml（applicable_templates
  含通配或本模板的规则 → root_cause_family + pit_refs 坑号链）；
- 健康门：G11 九因子（core/solve_health，通用参考文案）+ 模板作用域门
  （#274：非适用族 gate 如实不判——现役仅 patch 效率窗，常量 live import
  ui_service.PATCH_ETA_GATE 防数字腐化）。

B3-2 两增量节（数据源挂接设计定稿见
runs/qw5_b32_capability_cards/design_note.md）：
- 敏感性排序（R9 先承诺）：统一消费源 resolve_sensitivity（W8 桥接，
  review_ge8e F1 处置②收口）——三态优先级：①计算数据面
  knowledge/sensitivity_rankings.yaml（幅值分数，数据落档批创建；有则
  provenance=computed+数据指针）→ ②meta.yaml teaching 兜底
  teaching.sensitivity_ranking（EP-5 口径：order 名次 + basis 依据，
  卡面标注出处=teaching；W6 批落地）→ ③双缺卡面如实回退"暂无已落档"，
  不硬凑不即时仿真；坏块逐级拒收如实降级（#105 best-effort）。
  幅值排序复用 optimization/eipu.commitment_order（live import）。
- 引擎精度卡（跨引擎仲裁锚）：源 knowledge/anchors.yaml（判据节同源
  records 逐键挑取；kind=constant/pointer/formula/curve 分支渲染；
  pointer 双值并列禁平均 #122；零计算零求值——铁律 7）。

产物：docs/capability_cards/<t>.md（每模板一页）+ index.html（索引；
确定性输出：无时间戳进产物，同输入两次生成逐字节一致；HTML 全插值
html.escape）。模板顺序字母序。

PR-5 X1 交互化：index.html 行内嵌 data-* 属性（族/锚覆盖/搜索文本——
族分类单一事实源=service/gallery_service.TEMPLATE_FAMILIES）+ 隐藏工具栏
+ 渐进增强内联脚本（与 QW-4 画廊页共用实现）；禁用 JS 时全部行照常可见
=零 JS 现态。

用法：
    python scripts/capability_cards_export.py                 # 缺省 docs/capability_cards/
    python scripts/capability_cards_export.py --out-dir <dir>
    python scripts/capability_cards_export.py --template patch
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "capability_cards"
META_ROOT = REPO_ROOT / "docs" / "templates"
PLAYBOOK_PATH = REPO_ROOT / "knowledge" / "diagnostics" / "playbook.yaml"
# B3-2 敏感性排序节设计源（契约见 runs/qw5_b32_capability_cards/
# design_note.md；文件由数据落档批创建——缺省缺失时如实回退，不硬凑）
SENSITIVITY_PATH = REPO_ROOT / "knowledge" / "sensitivity_rankings.yaml"
SENSITIVITY_DESIGN_NOTE_REL = "runs/qw5_b32_capability_cards/design_note.md"
# W8 桥接：统一消费源的数据指针（卡面 provenance 注记用仓库相对路径）
SENSITIVITY_REGISTRY_REL = "knowledge/sensitivity_rankings.yaml"

# ── 健康门文案（G 系口径）───────────────────────────────────────────────────

_G11_FACTORS = (
    "passivity", "reciprocity", "timestep", "cost_distribution",
    "excitation", "probe_scale", "power_balance", "thermal_plausibility",
    "eps_eff_beta",
)
_G11_NOTE = ("求解健康度体检 G11 九因子（core/solve_health；"
             "service/health_service.health_check_run 按 run 装载产物判定）")


def _template_gate_notes(template: str) -> list[str]:
    """模板作用域健康门注记（#274：按 template 作用域分派，非适用不判）。"""
    notes: list[str] = []
    # 效率窗门仅 patch 族适用（ui_service.PATCH_ETA_GATE，live import 防腐化）
    if template == "patch" or template.startswith("patch"):
        try:
            from rfauto.service.ui_service import PATCH_ETA_GATE
            notes.append(
                f"效率窗门 η∈[{PATCH_ETA_GATE[0]}, {PATCH_ETA_GATE[1]}]"
                "（ui_service.PATCH_ETA_GATE；#274 模板作用域：仅 patch 族适用）")
        except Exception:  # 观测性注记 best-effort（#105）
            notes.append("效率窗门常量读取失败（如实注记，不阻塞出卡）")
    if not notes:
        notes.append("无模板作用域专属健康门（gate 如实不判，#274 口径）")
    return notes


# ── 数据组装 ────────────────────────────────────────────────────────────────

def _load_meta_yaml(template: str) -> dict[str, Any]:
    path = META_ROOT / template / "meta.yaml"
    if not path.is_file():
        return {}
    import yaml

    meta = yaml.safe_load(path.read_text(encoding="utf-8"))
    return meta if isinstance(meta, dict) else {}


def match_playbook_rules(template: str,
                         rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """playbook 规则匹配：applicable_templates 含通配 "*" 或本模板名。"""
    matched = []
    for rule in rules:
        scope = rule.get("applicable_templates") or []
        if "*" in scope or template in scope:
            matched.append({
                "rule_id": str(rule.get("id") or "?"),
                "root_cause_family": str(rule.get("root_cause_family") or "?"),
                "pit_refs": [str(p) for p in rule.get("pit_refs") or []],
                "notes": str(rule.get("notes") or ""),
            })
    return matched


def load_playbook_rules(path: str | Path | None = None) -> list[dict[str, Any]]:
    """读 playbook.yaml 的 rules（缺文件/结构不合法 → 空列表如实）。"""
    p = Path(path) if path else PLAYBOOK_PATH
    if not p.is_file():
        return []
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # 数据面读取失败不阻塞出卡
        return []
    rules = data.get("rules")
    return [r for r in rules if isinstance(r, dict)] if isinstance(
        rules, list) else []


def match_anchor_records(template: str,
                         anchor_records: list[Any]) -> list[Any]:
    """锚覆盖记录（通配计入；按 anchor_id 字母序；判据/精度卡同口径）。"""
    return sorted(
        (r for r in anchor_records
         if "*" in r.template_family or template in r.template_family),
        key=lambda r: str(r.anchor_id))


def match_anchor_ids(template: str, anchor_records: list[Any]) -> list[str]:
    """锚覆盖（通配计入）；与 gallery_export.match_anchor_ids 同口径。"""
    return [str(r.anchor_id)
            for r in match_anchor_records(template, anchor_records)]


def pick_precision_anchor(record: Any) -> dict[str, Any]:
    """仲裁锚 → 精度卡字段（逐键挑取零计算；长文 semantics/devlog 不上卡）。"""
    provenance = getattr(record, "provenance", None) or {}
    quantity = getattr(record, "quantity", None) or {}
    axis = getattr(record, "axis", None) or {}
    points = getattr(record, "points", None) or []
    return {
        "anchor_id": str(record.anchor_id),
        "kind": str(record.kind),
        "status": str(record.status),
        "engine_pair": getattr(record, "engine_pair", None),
        "quantity_name": quantity.get("name"),
        "unit": quantity.get("unit"),
        # constant：注册常数
        "value": getattr(record, "value", None),
        # pointer：双值指针（OE/HFSS 并列，禁平均 #122）
        "values": quantity.get("values"),
        "value_unit": quantity.get("value_unit"),
        "metric": quantity.get("metric"),
        # formula：闭式/文献公式
        "expr": getattr(record, "expr", None),
        "variables": getattr(record, "variables", None),
        # curve：偏差修正曲线
        "n_points": len(points),
        "axis_param": axis.get("param"),
        "uncertainty": getattr(record, "uncertainty", None),
        "verdict_state": provenance.get("verdict_state"),
        "arbitration_runs": provenance.get("arbitration_runs"),
    }


def load_sensitivity_rankings(
        path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """读敏感性排序登记表（B3-2 设计源；缺文件/坏结构 → 空映射如实）。

    契约（runs/qw5_b32_capability_cards/design_note.md）：schema
    sensitivity_rankings/v1，templates.<名>.ranking=[{param, score}]；
    运行时只读、写入只经人工 commit（anchors.yaml 家法）。
    """
    p = Path(path) if path else SENSITIVITY_PATH
    if not p.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # 数据面读取失败不阻塞出卡（#105）
        return {}
    templates = data.get("templates")
    if not isinstance(templates, dict):
        return {}
    return {str(k): v for k, v in templates.items() if isinstance(v, dict)}


def normalize_sensitivity_entry(entry: Any) -> dict[str, Any] | None:
    """单模板敏感性条目校验+排序（复用 R9 commitment_order；坏条目如实 None）。

    排序是确定性键序（-score, param 升名），非物理计算（铁律 7：分数本身
    必须来自 source_run 已落档产物）；bool/str 数字显式拒收（df7+⑯ 口径）。
    """
    if not isinstance(entry, dict):
        return None
    raw = entry.get("ranking")
    if not isinstance(raw, list):
        return None
    scores: dict[str, float] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        param = item.get("param")
        score = item.get("score")
        if not isinstance(param, str) or not param:
            continue
        if isinstance(score, (bool, str)):
            continue
        if not isinstance(score, (int, float)) or not math.isfinite(score) \
                or float(score) < 0.0:
            continue
        scores[param] = float(score)
    if not scores:
        return None
    try:
        from rfauto.optimization.eipu import commitment_order
        ranked = commitment_order(scores)
    except ImportError:  # R9 件缺席时回退本地同规则排序
        ranked = [{"rank": i + 1, "param": k, "score": v}
                  for i, (k, v) in enumerate(
                      sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])))]
    out: dict[str, Any] = {"ranking": ranked}
    for key in ("method", "n_samples", "seed", "source_run", "registered_at"):
        if entry.get(key) is not None:
            out[key] = entry[key]
    return out


def normalize_teaching_sensitivity(
        meta_yaml: dict[str, Any] | None) -> dict[str, Any] | None:
    """meta.yaml teaching.sensitivity_ranking 兜底源（F1 处置②；EP-5 口径）。

    教学块用 order（名次）+ basis（依据）而非臆造幅值——名次来自可复核
    闭式恒等式（EP-5 铁律 7 口径，见 service/teaching_service docstring）；
    幅值分数留给 sensitivity_rankings.yaml 数据管线。校验同
    teaching_service.load_teaching（order 正整数、1..N 连续全序、
    param/basis 非空串），但导出面 best-effort（#105）：坏块如实 None
    不阻塞出卡。返回带 source="teaching" 出处标注（卡面注明，不冒充
    幅值数据面）。
    """
    if not isinstance(meta_yaml, dict):
        return None
    teaching = meta_yaml.get("teaching")
    if not isinstance(teaching, dict):
        return None
    raw = teaching.get("sensitivity_ranking")
    if not isinstance(raw, list) or not raw:
        return None
    entries: list[tuple[int, str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        param = item.get("param")
        order = item.get("order")
        basis = item.get("basis")
        if not isinstance(param, str) or not param:
            return None
        if not isinstance(basis, str) or not basis:
            return None
        if isinstance(order, bool) or not isinstance(order, int) or order <= 0:
            return None
        entries.append((order, param, basis))
    if sorted(e[0] for e in entries) != list(range(1, len(entries) + 1)):
        return None  # 名次必须 1..N 连续（teaching_service 同口径）
    return {
        "source": "teaching",
        "ranking": [{"rank": order, "param": param, "basis": basis}
                    for order, param, basis in sorted(entries)],
    }


def resolve_sensitivity(sensitivity_entry: Any,
                        meta_yaml: dict[str, Any] | None,
                        ) -> dict[str, Any] | None:
    """敏感性统一消费源（W8 桥接；三态优先级 computed > teaching > None）。

    F1 登记的"双数据路径未桥接"收口：两条来源路径（计算数据面登记表 /
    meta.yaml teaching 兜底）收敛为单一出口，卡面渲染与字段 schema 对齐
    W6 卡面（ranking=[{rank, param, ...}] + source 出处标注）：

    ① computed：登记表条目经 normalize_sensitivity_entry 校验+R9 排序，
       有则 source="computed" + provenance 数据指针（登记表路径+source_run
       证据面），不冒充 teaching；
    ② teaching：登记表缺/坏（坏条目如实降级，#105）→ teaching 兜底源；
    ③ None：双缺（或 teaching 块亦坏）→ 如实 None，卡面渲染"暂无已落档"。
    """
    computed = normalize_sensitivity_entry(sensitivity_entry)
    if computed is not None:
        computed["source"] = "computed"
        provenance: dict[str, Any] = {"registry": SENSITIVITY_REGISTRY_REL}
        if computed.get("source_run") is not None:
            provenance["source_run"] = computed["source_run"]
        computed["provenance"] = provenance
        return computed
    return normalize_teaching_sensitivity(meta_yaml)


def collect_card(template: str, *,
                 meta_yaml: dict[str, Any] | None = None,
                 template_meta: dict[str, Any] | None = None,
                 anchor_records: list[Any] | None = None,
                 playbook_rules: list[dict[str, Any]] | None = None,
                 sensitivity_entry: dict[str, Any] | None = None,
                 ) -> dict[str, Any]:
    """单模板能力卡（meta.yaml 主源 + TEMPLATE_META 回退 + 锚 + 坑账链）。

    B3-2 增量：precision_anchors（跨引擎仲裁锚逐键挑取）+ sensitivity
    （统一消费源 resolve_sensitivity：计算数据面 → teaching 兜底（W8 桥接
    三态优先级）→ 双缺如实 None）。
    """
    if meta_yaml is None:
        meta_yaml = _load_meta_yaml(template)
    if template_meta is None:
        from rfauto.adapters.openems_templates import TEMPLATE_META
        template_meta = TEMPLATE_META.get(template, {})
    if anchor_records is None:
        from rfauto.infra.anchors_store import load_anchors
        anchor_records = load_anchors().records
    if playbook_rules is None:
        playbook_rules = load_playbook_rules()
    if sensitivity_entry is None:
        sensitivity_entry = load_sensitivity_rankings().get(template)

    def pick(key: str) -> Any:
        """meta.yaml 主源；缺失回退 TEMPLATE_META；双缺如实 None。"""
        return meta_yaml.get(key) if meta_yaml.get(key) is not None \
            else template_meta.get(key)

    sensitivity = resolve_sensitivity(sensitivity_entry, meta_yaml)

    # PR-5 X1 交互化字段（索引 HTML data-* 数据源；MD 卡面零改动）：
    # 族键=service/gallery_service 单一事实源（未登记名如实 "other"）；
    # 搜索文本=卡名+族标签+拓扑（卡内字段，无独立别名字段不臆造）。
    from rfauto.service.gallery_service import FAMILY_LABELS, template_family
    family = template_family(template)
    family_label = FAMILY_LABELS.get(family, family)
    search_text = " ".join(
        s for s in (template, family_label, _fmt(pick("topology")))
        if s and s != "-")

    return {
        "name": template,
        # 适用场景
        "topology": pick("topology"),
        "f0_ghz": pick("f0_ghz"),
        "n_ports": pick("n_ports"),
        "extraction": pick("extraction"),
        "params": list(pick("params") or []),
        "nominal_params": meta_yaml.get("nominal_params"),
        "substrate": meta_yaml.get("substrate"),
        # 已知边界
        "param_semantics": pick("param_semantics"),
        "mesh_note": pick("mesh_note"),
        "smoke_note": meta_yaml.get("smoke_note")
        or template_meta.get("smoke_note"),
        "max_time_ns": pick("max_time_ns"),
        "mesh_resolution_mm": pick("mesh_resolution_mm"),
        # 判据
        "anchor_ids": match_anchor_ids(template, anchor_records),
        "gate_notes": _template_gate_notes(template),
        "failure_modes": match_playbook_rules(template, playbook_rules),
        # B3-2 引擎精度卡：跨引擎仲裁锚（判据节同源 records，逐键挑取）
        "precision_anchors": [
            pick_precision_anchor(r)
            for r in match_anchor_records(template, anchor_records)],
        # B3-2 敏感性排序：统一消费源三态（computed → teaching 兜底 → 如实
        # None；W8 桥接，F1 处置②收口）
        "sensitivity": sensitivity,
        "meta_yaml_rel": f"docs/templates/{template}/meta.yaml",
        # PR-5 X1 交互化字段
        "family": family,
        "search_text": search_text,
    }


def collect_cards(*, templates: list[str] | None = None,
                  anchor_records: list[Any] | None = None,
                  playbook_rules: list[dict[str, Any]] | None = None,
                  template_meta_all: dict[str, dict[str, Any]] | None = None,
                  sensitivity_all: dict[str, dict[str, Any]] | None = None,
                  ) -> list[dict[str, Any]]:
    """全模板能力卡（字母序；数据源可注入以便离线测试）。"""
    if templates is None:
        from rfauto.adapters.openems_templates import TEMPLATE_META
        templates = sorted(TEMPLATE_META)
    if template_meta_all is None:
        from rfauto.adapters.openems_templates import TEMPLATE_META
        template_meta_all = TEMPLATE_META
    if anchor_records is None:
        from rfauto.infra.anchors_store import load_anchors
        anchor_records = load_anchors().records
    if playbook_rules is None:
        playbook_rules = load_playbook_rules()
    if sensitivity_all is None:
        sensitivity_all = load_sensitivity_rankings()
    return [
        collect_card(name, anchor_records=anchor_records,
                     playbook_rules=playbook_rules,
                     template_meta=template_meta_all.get(name, {}),
                     sensitivity_entry=sensitivity_all.get(name))
        for name in sorted(templates)
    ]


# ── Markdown 渲染（每模板一页）─────────────────────────────────────────────

def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    return str(value)


def render_card_md(card: dict[str, Any]) -> str:
    """单模板能力卡 Markdown（值一律 _fmt；无生成时刻=确定性）。"""
    name = card["name"]
    lines: list[str] = [f"# 能力卡：{name}", ""]
    lines.append("> 由 scripts/capability_cards_export.py 离线生成"
                 "（确定性输出）；数据源与坑号链见文中逐条标注。")
    lines.append("")

    lines.append("## 适用场景")
    lines.append("")
    lines.append(f"- 拓扑：{_fmt(card['topology'])}")
    lines.append(f"- f0：{_fmt(card['f0_ghz'])} GHz ｜ 端口："
                 f"{_fmt(card['n_ports'])} ｜ 时长 ≤{_fmt(card['max_time_ns'])} ns"
                 f" ｜ 网格档：{_fmt(card['mesh_resolution_mm'])} mm")
    lines.append(f"- 提取口径：{_fmt(card['extraction'])}")
    lines.append(f"- 参数：{', '.join(card['params']) or '-'}")
    if card["substrate"]:
        lines.append(f"- 基板：{_fmt(card['substrate'])}")
    lines.append("")

    lines.append("## 名义参数")
    lines.append("")
    np_ = card["nominal_params"]
    if np_:
        lines.append("| 参数 | 名义值 |")
        lines.append("|---|---|")
        for k in sorted(np_):
            lines.append(f"| {k} | {_fmt(np_[k])} |")
    else:
        lines.append("-（meta.yaml 未声明名义参数）")
    lines.append(f"- 名义参数来源：`{card['meta_yaml_rel']}`"
                 "（与 TEMPLATE_NOMINAL 一致性由 test_gallery_export 钉）")
    lines.append("")
    lines.extend(_render_sensitivity_lines(card))

    lines.append("## 判据")
    lines.append("")
    anchors = card["anchor_ids"]
    if anchors:
        lines.append(f"- 锚覆盖 {len(anchors)}：{'、'.join(anchors)}"
                     "（core/anchors；通配 + 专属）")
    else:
        lines.append("- 锚覆盖 0（无覆盖，如实标注）")
    for note in card["gate_notes"]:
        lines.append(f"- 健康门：{note}")
    lines.append(f"- 通用体检：{_G11_NOTE}")
    lines.append("")
    lines.extend(_render_precision_lines(card))

    lines.append("## 已知边界")
    lines.append("")
    lines.append(f"- 参数语义：{_fmt(card['param_semantics'])}")
    lines.append(f"- 网格：{_fmt(card['mesh_note'])}")
    if card["smoke_note"]:
        lines.append(f"- 冒烟现状：{_fmt(card['smoke_note'])}")
    modes = card["failure_modes"]
    if modes:
        lines.append(f"- 失败模式坑账链（playbook 命中 {len(modes)} 条，"
                     "坑号 #NNN 为 出处标记）：")
        for m in modes:
            pits = "、".join(m["pit_refs"]) or "-"
            lines.append(f"  - `{m['rule_id']}`（{m['root_cause_family']}；"
                         f"坑：{pits}）{_m_note(m['notes'])}")
    else:
        lines.append("- playbook 无本模板适用规则（如实，不凑全）")
    lines.append("")
    return "\n".join(lines)


def _m_note(note: str) -> str:
    note = (note or "").strip()
    return f"——{note}" if note else ""


def _engine_pair_note(engine_pair: Any) -> str:
    if isinstance(engine_pair, dict) and engine_pair:
        calibrated = engine_pair.get("calibrated", "?")
        referee = engine_pair.get("referee", "?")
        return f"引擎对 {calibrated}（{referee} 仲裁）"
    return "闭式/文献锚（无引擎对）"


def _precision_value_note(a: dict[str, Any]) -> str:
    """按 kind 渲染锚值面（逐键挑取；pointer 双值并列禁平均 #122）。"""
    kind = a["kind"]
    if kind == "constant" and a.get("value") is not None:
        return f"= {_fmt(a['value'])} {_fmt(a.get('unit'))}"
    if kind == "pointer" and isinstance(a.get("values"), dict) and a["values"]:
        pairs = " / ".join(f"{k}={_fmt(a['values'][k])}"
                           for k in sorted(a["values"]))
        return (f"双值 {pairs} {_fmt(a.get('value_unit'))}"
                "（不取平均，#122）")
    if kind == "formula" and a.get("expr"):
        variables = "、".join(a.get("variables") or [])
        return f"expr = {a['expr']}" + (f"（变量：{variables}）"
                                        if variables else "")
    if kind == "curve":
        return (f"曲线 {_fmt(a.get('n_points'))} 点"
                f"（横轴 {_fmt(a.get('axis_param'))}）")
    return f"值面 {_fmt(None)}（kind={_fmt(kind)}）"


def _precision_uncertainty_note(a: dict[str, Any]) -> str:
    u = a.get("uncertainty")
    if not isinstance(u, dict) or u.get("value") is None:
        return ""
    return f"±{_fmt(u.get('value'))}（{_fmt(u.get('kind'))}）"


def _render_sensitivity_lines(card: dict[str, Any]) -> list[str]:
    """敏感性排序节（统一消费源三态渲染；双缺如实回退不凑数）。

    computed（登记表幅值分，W8 桥接）渲染出处+数据指针 + method/n/seed/
    证据 + 分数表；teaching 兜底源（F1 处置②/W6）渲染名次+依据表并标注
    出处；双缺如实"暂无已落档"。
    """
    lines = ["## 敏感性排序（R9 先承诺）", ""]
    sens = card.get("sensitivity")
    if sens and sens.get("source") == "teaching":
        lines.append(
            "- 出处=teaching（`docs/templates/<模板名>/meta.yaml` "
            "teaching.sensitivity_ranking；EP-5 口径：order 名次 + basis "
            "依据，来自可复核闭式恒等式而非幅值——幅值分数待 "
            "`knowledge/sensitivity_rankings.yaml` 数据管线落档后重跑"
            "导出器上卡）")
        lines.append("")
        lines.append("| 名次 | 参数 | 依据 |")
        lines.append("|---|---|---|")
        for item in sens["ranking"]:
            lines.append(f"| {_fmt(item['rank'])} | {_fmt(item['param'])} "
                         f"| {_fmt(item['basis'])} |")
        lines.append("- 排序=teaching 名次全序（1..N 连续；人工 commit 写入，"
                     "引用锚文本由 test_teaching_service 对 grounding 文件"
                     "核验）")
    elif sens:
        if sens.get("source") == "computed":
            # W8 桥接：计算数据面上卡标注 provenance + 数据指针
            prov = sens.get("provenance")
            bits = [f"`{_fmt(prov.get('registry'))}`"
                    if isinstance(prov, dict) and prov.get("registry")
                    else f"`{SENSITIVITY_REGISTRY_REL}`"]
            if isinstance(prov, dict) and prov.get("source_run"):
                bits.append(f"证据 {_fmt(prov['source_run'])}")
            lines.append(f"- 出处=computed（幅值分数登记表 {'；'.join(bits)}"
                         "；坏条目拒收如实降级 #105）")
            lines.append("")
        meta_bits = [f"方法 {_fmt(sens.get('method'))}"]
        if sens.get("n_samples") is not None:
            meta_bits.append(f"n={_fmt(sens.get('n_samples'))}")
        if sens.get("seed") is not None:
            meta_bits.append(f"seed={_fmt(sens.get('seed'))}")
        lines.append(f"- {' ｜ '.join(meta_bits)}"
                     + (f" ｜ 证据：{_fmt(sens.get('source_run'))}"
                        if sens.get("source_run") else ""))
        lines.append("")
        lines.append("| rank | 参数 | 分数 |")
        lines.append("|---|---|---|")
        for item in sens["ranking"]:
            lines.append(f"| {_fmt(item['rank'])} | {_fmt(item['param'])} "
                         f"| {_fmt(item['score'])} |")
        lines.append("- 排序=R9 commitment_order（optimization/eipu；"
                     "高敏感先钉死，平局按参数名升序）")
    else:
        lines.append(f"-（暂无已落档敏感度排序——挂接契约："
                     f"`knowledge/sensitivity_rankings.yaml`，设计见 "
                     f"`{SENSITIVITY_DESIGN_NOTE_REL}`；数据落档后重跑"
                     f"导出器自动上卡，不硬凑）")
    lines.append("")
    return lines


def _render_precision_lines(card: dict[str, Any]) -> list[str]:
    """引擎精度卡节（跨引擎仲裁锚；anchors.yaml 判据节同源逐键挑取）。"""
    lines = ["## 引擎精度卡（跨引擎仲裁锚）", ""]
    anchors = card.get("precision_anchors") or []
    if anchors:
        for a in anchors:
            parts = [
                f"`{a['anchor_id']}`（{a['kind']}/{a['status']}；"
                f"{_engine_pair_note(a.get('engine_pair'))}）",
                f"{_fmt(a.get('quantity_name'))} "
                f"{_precision_value_note(a)}",
            ]
            unc = _precision_uncertainty_note(a)
            if unc:
                parts.append(unc)
            if a.get("verdict_state") is not None:
                parts.append(f"verdict {_fmt(a['verdict_state'])}")
            runs = a.get("arbitration_runs")
            if isinstance(runs, list) and runs:
                parts.append(f"证据：{'、'.join(str(r) for r in runs)}")
            lines.append(f"- {parts[0]}：{parts[1]}"
                         + ("".join(f"；{p}" for p in parts[2:])))
    else:
        lines.append("-（暂无覆盖锚，如实标注）")
    lines.append("- 数据源：`knowledge/anchors.yaml`（仲裁锚注册表，"
                 "status/版本演进口径见该文件头注；本节零计算零求值）")
    lines.append("")
    return lines


# ── 索引 HTML ───────────────────────────────────────────────────────────────

def render_index_html(cards: list[dict[str, Any]]) -> str:
    """索引页（确定性、零外链；全插值 escape）。

    PR-5 X1 交互化：行内 data-* 属性（族/锚覆盖/搜索文本）+ 隐藏工具栏
    + 渐进增强内联脚本（与 QW-4 画廊页共用同一实现，scripts/gallery_export.
    INTERACTIVE_JS/render_filter_toolbar 单源消费）——禁用 JS 时工具栏保持
    hidden、全部行照常可见=零 JS 现态。"""
    e = html.escape
    from gallery_export import INTERACTIVE_JS, render_filter_toolbar
    n_anchored = sum(1 for c in cards if c["anchor_ids"])
    n_playbook = sum(1 for c in cards if c["failure_modes"])
    n_precision = sum(1 for c in cards if c.get("precision_anchors"))
    parts = [
        "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>rfauto 模板能力卡索引</title><style>",
        "body{font-family:sans-serif;margin:1.5rem;color:#222}",
        "table{border-collapse:collapse}th,td{border:1px solid #ccc;"
        "padding:2px 8px;font-size:.85rem;text-align:left}th{background:#f0f0f0}",
        # PR-5 X1 工具栏样式（与 QW-4 画廊页同款，focus-visible 沿 PR-1 钉）
        "#gf-toolbar{margin:.6rem 0;padding:.5rem .7rem;background:#f4f6f8;"
        "border:1px solid #ccd;font-size:.88rem}",
        "#gf-toolbar button{cursor:pointer;font:inherit;margin:1px 2px;"
        "padding:0 .45rem;background:#fff;border:1px solid #99c;"
        "border-radius:3px}",
        "#gf-toolbar button[aria-pressed=\"true\"]{background:#345;"
        "color:#fff;border-color:#345}",
        "#gf-toolbar input{font:inherit;padding:2px 6px;min-width:16rem}",
        "#gf-status{margin-left:.5rem;color:#555}",
        "#gf-empty{color:#a66}",
        "button:focus-visible,input:focus-visible{outline:2px solid #b60;"
        "outline-offset:1px}",
        "</style></head><body>",
        "<h1>rfauto 模板能力卡索引（QW-5）</h1>",
        f"<p>共 {e(str(len(cards)))} 张能力卡；有锚覆盖 "
        f"{e(str(n_anchored))} 张；有 playbook 坑账链命中 "
        f"{e(str(n_playbook))} 张；有引擎精度卡锚 "
        f"{e(str(n_precision))} 张。每模板一页："
        "<code>docs/capability_cards/&lt;模板名&gt;.md</code>。</p>",
        render_filter_toolbar(cards),
        "<p id=\"gf-empty\" hidden>无匹配卡片——调整搜索词或筛选条件。</p>",
        "<table><tr><th>模板</th><th>f0 (GHz)</th><th>端口</th>"
        "<th>锚覆盖</th><th>坑账链</th><th>精度锚</th></tr>",
    ]
    for c in cards:
        coverage = "covered" if c["anchor_ids"] else "none"
        parts.append(
            f"<tr data-tpl=\"{e(c['name'])}\" data-family=\"{e(c['family'])}\" "
            f"data-anchors=\"{e(str(len(c['anchor_ids'])))}\" "
            f"data-coverage=\"{coverage}\" "
            f"data-search=\"{e(c['search_text'])}\">"
            f"<td><a href=\"{e(c['name'])}.md\">{e(c['name'])}</a></td>"
            f"<td>{e(_fmt(c['f0_ghz']))}</td><td>{e(_fmt(c['n_ports']))}</td>"
            f"<td>{e(str(len(c['anchor_ids'])))}</td>"
            f"<td>{e(str(len(c['failure_modes'])))}</td>"
            f"<td>{e(str(len(c.get('precision_anchors') or [])))}</td></tr>")
    parts.append("</table><p style='color:#666;font-size:.85rem'>"
                 "本页由 scripts/capability_cards_export.py 生成"
                 "（确定性输出，无时间戳；内联脚本为渐进增强筛选，"
                 "禁用 JS 时全部行照常可见）。</p>"
                 f"{INTERACTIVE_JS}</body></html>")
    return "\n".join(parts)


# ── 落盘 ────────────────────────────────────────────────────────────────────

def write_cards(out_dir: str | Path, *, template_filter: str | None = None,
                anchor_records: list[Any] | None = None,
                playbook_rules: list[dict[str, Any]] | None = None,
                templates: list[str] | None = None,
                sensitivity_all: dict[str, dict[str, Any]] | None = None,
                ) -> Path:
    """生成 <t>.md 全集 + index.html（返回 out_dir）。"""
    root = Path(out_dir)
    if templates is None:
        from rfauto.adapters.openems_templates import TEMPLATE_META
        templates = sorted(TEMPLATE_META)
    if template_filter is not None and template_filter not in templates:
        raise SystemExit(
            f"--template {template_filter!r} 不在注册表；可用："
            f"{'，'.join(templates)}")
    sel = ([template_filter] if template_filter is not None else templates)
    cards = collect_cards(templates=sel, anchor_records=anchor_records,
                          playbook_rules=playbook_rules,
                          sensitivity_all=sensitivity_all)
    root.mkdir(parents=True, exist_ok=True)
    for card in cards:
        page = root / f"{card['name']}.md"
        page.write_text(render_card_md(card), encoding="utf-8",
                        newline="\n")
    (root / "index.html").write_text(render_index_html(cards),
                                     encoding="utf-8", newline="\n")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capability_cards_export",
        description="QW-5：全模板能力卡（每模板一页 MD+索引 HTML）离线导出")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help=f"输出目录（缺省 {DEFAULT_OUT_DIR}）")
    parser.add_argument("--template", default=None,
                        help="过滤单模板（精确名，调试用）")
    args = parser.parse_args(argv)
    out_dir = write_cards(args.out_dir, template_filter=args.template)
    print(f"capability cards written: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
