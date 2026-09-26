"""DP-13 U1 双输出报告链：run → 报告模型 → typst PDF ‖ plotly 自包含 HTML 同源双出。

合规形态（确定性内核铁律 + #105/#122）：

1. **同源双出**：:func:`build_report_model` 产出唯一报告模型（schema
   ``rfauto-report/v1``，纯 dict、可直接 json.dumps）；:func:`render_typ` 与
   :func:`render_html` 只消费该模型——渲染器零二次采数（不读 run 目录）。
2. **数字 100% provenance**：凡 dict 节点直接或经 list 间接持有数值叶
   （int/float；bool 显式豁免），该节点必须带非空字符串 ``source`` 键；
   :func:`bare_number_fields` 是判定式（测试断言裸数字字段=0）。
3. **判据对照表=合同级工件**：消费 knowledge/criteria/v2 YAML（只读）
   逐条「指标-阈值-出处-判定」；无适用模板的 run 如实
   ``criteria: none-provided``，不虚构（#122）。判定核心
   （map_verdict/nearest_reference_decision/budget_conditional）全部
   只读消费 core/vv_mapping.py，本模块不自创判定公式。
4. **缺产物如实降级**：meta/verdict/csv 任一缺失→对应节点
   ``status: missing`` + 异常清单记一条，构建与双渲染不崩（#105）。
5. **HTML 零外网**：plotly ``include_plotlyjs=True`` 全量内联；
   :func:`external_resource_refs` 列出可发起外部取回的资源引用
   （script/link/img/iframe 的 src·href、@import、url()），测试断言空。
   内联 plotly.js 源码内的 URL 字符串（license 注释/xmlns）不是取回
   引用，不算违规。
6. **零网络零真机**：本模块全部离线；typst/plotly/jinja2 均本地渲染。

与 report_narrative（LLM 叙述+数字白名单链）互补不替换：本件是确定性
结构化渲染链，不做叙述生成，也不做叙述数字校验。
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from datetime import datetime
from html.parser import HTMLParser as HtmlParser
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "rfauto-report/v1"
_CRITERIA_V2_SCHEMA = "criteria/v2"
_CRITERIA_NONE = "none-provided"

# 曲线显示上限（声明式截断，超出记异常清单；不改数据文件本身）
_MAX_TRACES = 8
# 曲线 dB 转换的显示地板（|S|<1e-9 时防 log10(0)=-inf 炸 plotly；纯显示层）
_DB_FLOOR_ABS = 1e-9

_MISSING = object()  # 证据路径解析的「键不存在」哨兵（None 是合法值）

# 方法配置字段白名单（声明式采集；来源逐键记 provenance）
_METHOD_KEYS = (
    "template", "engine", "adapter", "stage", "study", "seed",
    "mesh_mm", "base_mm", "nr_ts", "n_ports", "n_freq_points",
    "freq_range_ghz", "band_ghz", "reference_impedance",
    "topology_key", "stackup", "k_applied", "k_override",
    "k_eff_avg", "k_eff_balance", "solve_s", "excite_port",
)

# ── 判定式（测试与实现同源） ────────────────────────────────────────────────


def fmt_value(value: Any) -> str:
    """模型叶值的统一展示格式（两渲染器与 d2 测试共用）。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        if math.isnan(value):
            return "nan"
        return f"{value:.6g}"
    return str(value)


def typ_escape(text: str) -> str:
    """typst markup 特殊字符转义（反斜杠最先；共享函数，d2 测试同源）。"""
    out = text.replace("\\", "\\\\")
    return re.sub(r"([#$%&_*@\"'\[\]<>~])", r"\\\1", out)


_EXTERNAL_URL_RE = re.compile(
    r"(?:@import\s+(?:url\s?\()?\s*[\"']?|url\(\s*[\"']?)\s*((?:https?:)?//[^)\"'\s]+)",
    re.IGNORECASE,
)
_RESOURCE_TAGS = frozenset({
    "script", "link", "img", "iframe", "source", "video", "audio",
    "embed", "track", "object",
})
_URL_ATTRS = frozenset({"src", "href"})


class _ExternalRefScanner(HtmlParser):
    """解析器级资源引用扫描（只算真标签属性，不算脚本字符串字面量）。

    内联 plotly.js/maplibre 源码内含 ``t.href="https://…"`` 之类的 JS 字符串
    赋值与地图 attribution 模板——它们不是文档资源引用（不发起加载），在
    CDATA 数据层出现，本扫描器不会误报。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []
        self._style_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        name = tag.lower()
        if name == "style":
            self._style_depth += 1
        if name in _RESOURCE_TAGS:
            for attr, value in attrs:
                if attr and attr.lower() in _URL_ATTRS and value:
                    v = value.strip()
                    if v.startswith("//") or v.lower().startswith(("http://", "https:")):
                        self.refs.append(f"<{name} {attr.lower()}={value!r}>")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style" and self._style_depth:
            self._style_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            for match in _EXTERNAL_URL_RE.finditer(data):
                self.refs.append(f"style:{match.group(1)}")


def external_resource_refs(html: str) -> list[str]:
    """列出 HTML 里可发起外部取回的资源引用（零外网判定式，与测试同源）。

    判定面（runs/df6_dp13u1/criteria.md §一.3）=HTML 解析层的资源标签属性
    （script/link/img/iframe/source/video/audio/embed/track/object 的
    src·href）与 style 层的 @import/url() 指向协议相对或 http(s) 地址。
    脚本源码内的 URL 字符串字面量不是取回引用，不算违规。
    """
    scanner = _ExternalRefScanner()
    scanner.feed(html)
    scanner.close()
    return scanner.refs


def _dict_directly_holds_numbers(node: dict) -> bool:
    """dict 自身（或其 list 值内，不经嵌套 dict）是否持有数值叶。"""
    for value in node.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, bool):
                    continue
                if isinstance(item, (int, float)):
                    return True
    return False


def bare_number_fields(node: Any, path: str = "model") -> list[str]:
    """provenance 判定式：返回缺 source 键却持有数值叶的 dict 节点路径。

    规则（runs/df6_dp13u1/criteria.md §一.2）：凡 dict 节点直接或经 list
    间接持有数值叶（int/float，bool 豁免），必须带非空字符串 source。
    """
    out: list[str] = []
    if isinstance(node, dict):
        if _dict_directly_holds_numbers(node):
            source = node.get("source")
            if not (isinstance(source, str) and source.strip()):
                out.append(path)
        for key, value in node.items():
            out.extend(bare_number_fields(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            out.extend(bare_number_fields(item, f"{path}[{i}]"))
    return out


# ── run 目录读取（全部只读） ────────────────────────────────────────────────


def _load_json_docs(run_dir: Path) -> dict[str, Any]:
    """顶层 *.json → {文件名: 解析对象}（文件名排序保证解析顺序确定）。"""
    docs: dict[str, Any] = {}
    for path in sorted(run_dir.glob("*.json")):
        try:
            docs[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            docs[path.name] = None  # 坏文档如实保留占位（#105 不崩）
    return docs


def _resolve_in(doc: Any, parts: list[str]) -> tuple[Any, str]:
    """在单文档内解析点分路径；``<setup>`` 段=该位置任意单键首个命中。

    返回 (值, 实际命中路径)；键不存在返回 (_MISSING, "")（None 是合法值，
    不可当缺失哨兵）。
    """
    node, consumed = doc, []
    for idx, part in enumerate(parts):
        if isinstance(node, dict) and part in node:
            node = node[part]
            consumed.append(part)
            continue
        if isinstance(node, dict) and part.startswith("<") and part.endswith(">"):
            for key in node:  # 通配段：插入序首个可继续命中的键
                sub, sub_path = _resolve_in(node[key], parts[idx + 1:])
                if sub is not _MISSING:
                    pieces = [*consumed, str(key), *([sub_path] if sub_path else [])]
                    return sub, ".".join(pieces)
        return _MISSING, ""
    return node, ".".join(consumed)


def resolve_evidence(docs: dict[str, Any], path_str: str) -> tuple[Any, str]:
    """跨文档解析证据字段；返回 (值, 出处串「文件名:实际路径」) 或 (None, "")。"""
    parts = path_str.split(".")
    for fname in sorted(docs):
        doc = docs[fname]
        if not isinstance(doc, dict):
            continue
        value, actual = _resolve_in(doc, parts)
        if value is not _MISSING:
            return value, f"{fname}:{actual or path_str}"
    return None, ""


def _read_git_commit(run_dir: Path) -> str:
    """best-effort 读 git commit（#105：观测面失败不阻塞主路径）。"""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(run_dir), capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


# ── 报告模型构建 ────────────────────────────────────────────────────────────


def _unit_from_key(key: str) -> str:
    """从键名后缀推断展示单位（仅标注展示单位，不改数值）。"""
    if key.endswith("_db") or "_db_" in key:
        return "dB"
    if key.endswith("_mm"):
        return "mm"
    if key.endswith("_ghz"):
        return "GHz"
    if key.endswith("_hz"):
        return "Hz"
    if key.endswith("_pct"):
        return "%"
    if key.endswith("_s") and not key.endswith("_mm"):
        return "s"
    if "impedance" in key:
        return "ohm"
    return ""


def _flatten_method_fields(meta: dict | None, result: dict | None,
                           anomalies: list[str]) -> tuple[list[dict], str]:
    """方法配置字段：白名单键自 meta.json 优先、result.json 兜底逐键溯源。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for fname, doc in (("meta.json", meta), ("result.json", result)):
        if not isinstance(doc, dict):
            continue
        candidates: list[tuple[str, Any]] = [
            (k, v) for k, v in doc.items() if k in _METHOD_KEYS and k not in seen
        ]
        sub = doc.get("sub")
        if isinstance(sub, dict):
            candidates += [(f"sub.{k}", v) for k, v in sub.items() if k not in seen]
        for key, value in candidates:
            if isinstance(value, (dict,)) or value is None:
                continue
            seen.add(key.split(".", 1)[-1])
            rows.append({
                "name": key,
                "value": value,
                "unit": _unit_from_key(key),
                "source": f"{fname}:{key}",
            })
    if not rows:
        anomalies.append("方法配置无可用字段（meta.json 与 result.json 均缺失或无白名单键）")
        return rows, "missing"
    if meta is None:
        anomalies.append("meta.json 缺失：方法配置降级自 result.json（字段可能不全）")
        return rows, "partial"
    return rows, "ok"


def _load_curves(run_dir: Path, anomalies: list[str]) -> dict:
    """sparams.csv → 曲线模型（复数列成对解析，dB 仅显示层转换）。"""
    csv_path = run_dir / "sparams.csv"
    curves: dict[str, Any] = {
        "source": str(csv_path),
        "status": "missing",
        "freq_ghz": [],
        "traces": [],
        "n_points": 0,
        "n_traces": 0,
        "note": "",
    }
    if not csv_path.is_file():
        anomalies.append(f"sparams.csv 缺失：曲线图降级（{csv_path.name} 不在场）")
        return curves
    try:
        lines = [ln for ln in csv_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        header = lines[0].split(",")
        rows = [ln.split(",") for ln in lines[1:]]
        col = {name: i for i, name in enumerate(header)}
        if "freq_hz" not in col:
            raise ValueError("缺 freq_hz 列")
        pairs = []
        i = 0
        while i < len(header):
            name = header[i]
            if name.startswith("re_S") and i + 1 < len(header) \
                    and header[i + 1] == "im_" + name[3:]:
                pairs.append(name[3:])
                i += 2
            else:
                i += 1
        freq = [float(r[col["freq_hz"]]) / 1e9 for r in rows]
        traces = []
        for label in pairs[:_MAX_TRACES]:
            re_col, im_col = col[f"re_{label}"], col[f"im_{label}"]
            values = [
                20.0 * math.log10(max(math.hypot(float(r[re_col]), float(r[im_col])),
                                      _DB_FLOOR_ABS))
                for r in rows
            ]
            traces.append({"label": label, "values_db": values,
                           "source": f"sparams.csv:{label}"})
        curves.update(status="ok", freq_ghz=freq, traces=traces,
                      n_points=len(freq), n_traces=len(traces))
        if len(pairs) > _MAX_TRACES:
            anomalies.append(
                f"曲线 trace 数 {len(pairs)} 超显示上限 {_MAX_TRACES}，已声明式截断")
            curves["note"] = f"truncated to {_MAX_TRACES}/{len(pairs)}"
    except (OSError, ValueError, IndexError, TypeError) as exc:
        curves["status"] = "corrupt"
        anomalies.append(f"sparams.csv 解析失败：{exc}（证据损坏如实留痕，不回退猜测）")
    return curves


def _row_unit(metric: str) -> str:
    if metric.endswith("_db"):
        return "dB"
    if metric.endswith("_rel"):
        return "ratio"
    if metric.endswith("_pct"):
        return "%"
    return ""


def _judge(observed: Any, op: str, threshold: Any) -> str:
    """单门判定：PASS/FAIL/UNKNOWN（观测缺失→UNKNOWN，不虚构）。"""
    if observed is None or threshold is None or not isinstance(op, str):
        return "UNKNOWN"
    try:
        obs, thr = float(observed), float(threshold)
    except (TypeError, ValueError):
        return "UNKNOWN"
    ok = {"<=": obs <= thr, ">=": obs >= thr, "<": obs < thr,
          ">": obs > thr, "==": obs == thr}.get(op.strip())
    return {True: "PASS", False: "FAIL"}.get(ok, "UNKNOWN")


def _vv_from_map(verdict_map: dict, overall: str) -> str | None:
    """yaml verdict_map 优先，缺键回退 core/vv_mapping.map_verdict（只读）。"""
    status = verdict_map.get(overall)
    if status is not None:
        return status
    from rfauto.core.vv_mapping import map_verdict

    return map_verdict(overall)["vv_status"]


def _evaluate_multi_gate_all_pass(rule: dict, docs: dict[str, Any],
                                  verdict_map: dict, yaml_name: str) -> dict:
    """multi_gate_all_pass 形：逐门「指标-阈值-出处-判定」+ 预算条件注记。"""
    rows: list[dict] = []
    for name, spec in (rule.get("gates") or {}).items():
        observed, source = resolve_evidence(docs, str(spec.get("evidence", "")))
        if not source:
            # 观测缺失时出处=判据 yaml 自身（阈值/操作符正出自该文件，如实引）
            source = f"{yaml_name}:decision_rule.gates.{name}"
        rows.append({
            "metric": name,
            "op": str(spec.get("op", "")),
            "threshold": spec.get("threshold"),
            "observed": observed,
            "unit": _row_unit(name),
            "source": source,
            "judgment": _judge(observed, str(spec.get("op", "")), spec.get("threshold")),
        })
    judgments = [r["judgment"] for r in rows]
    if rows and all(j == "PASS" for j in judgments):
        overall = "PASS"
    elif "FAIL" in judgments:
        overall = "FAIL"
    else:
        overall = "UNKNOWN"
    vv_status = _vv_from_map(verdict_map, overall)
    notes: list[str] = []
    budget = rule.get("budget_conditional")
    if isinstance(budget, dict):
        declared, declared_src = resolve_evidence(docs, "budget.declared")
        actual, actual_src = resolve_evidence(docs, "budget.actual")
        if isinstance(declared, (int, float)) and isinstance(actual, (int, float)) \
                and float(declared) > 0:
            from rfauto.core.vv_mapping import budget_conditional

            ratio = float(actual) / float(declared)
            result = budget_conditional(ratio, float(budget.get("ratio_limit", 1.5)))
            rows.append({
                "metric": "budget_ratio", "op": "<=",
                "threshold": result["budget_limit"], "observed": ratio,
                "unit": "ratio",
                "source": "; ".join(filter(None, [declared_src, actual_src])) or "missing",
                "judgment": "FAIL" if result["triggered"] else "PASS",
            })
            if result["triggered"]:
                notes.append(str(result.get("vv_note") or "超预算注记"))
                if overall == "PASS":
                    vv_status = verdict_map.get("PARTIAL", vv_status)
        else:
            rows.append({
                "metric": "budget_ratio", "op": "<=",
                "threshold": budget.get("ratio_limit"), "observed": None,
                "unit": "ratio",
                "source": "; ".join(filter(None, [declared_src, actual_src])) or "missing",
                "judgment": "UNKNOWN",
            })
            notes.append("预算 declared/actual 缺失：budget 条件门 UNKNOWN（不虚构）")
    return {"rows": rows, "overall": overall, "vv_status": vv_status, "notes": notes}


def _evaluate_nearest_reference(rule: dict, claim: dict, docs: dict[str, Any],
                                verdict_map: dict, yaml_name: str) -> dict:
    """nearest_reference_gate 形：先找 claim.quantity 证据，走只读判向内核。"""
    from rfauto.core.vv_mapping import nearest_reference_decision

    quantity = str(claim.get("quantity", ""))
    rows: list[dict] = []
    notes = ["preflight（资格/饱和/健全性）v1 不消费：如实注记（runner_binding=followUp）"]
    observed, source = None, ""
    for field_path in claim.get("_evidence_fields") or []:
        last = str(field_path).split(".")[-1]
        if last == quantity:
            observed, source = resolve_evidence(docs, str(field_path))
            if observed is not None:
                break
    gate_db = rule.get("gate_db")
    references = rule.get("references") or {}
    if observed is None or gate_db is None or not references:
        rows.append({
            "metric": quantity or "(claim.quantity 缺失)", "op": "<=",
            "threshold": gate_db, "observed": observed, "unit": "dB",
            "source": source or f"{yaml_name}:decision_rule.references",
            "judgment": "UNKNOWN",
        })
        return {"rows": rows, "overall": "UNKNOWN",
                "vv_status": _vv_from_map(verdict_map, "UNKNOWN"), "notes": notes}
    result = nearest_reference_decision(observed, references, float(gate_db))
    for ref_name, delta in result["deltas"].items():
        rows.append({
            "metric": f"|{quantity}-{ref_name}|", "op": "<=",
            "threshold": float(gate_db), "observed": delta, "unit": "dB",
            "source": f"{source} vs reference:{ref_name}={references[ref_name]}",
            "judgment": "PASS" if result["matched"] == ref_name else "FAIL",
        })
    verdict_str = f"AGREE_{str(result['matched']).upper()}" if result["matched"] else "SPLIT"
    return {"rows": rows, "overall": verdict_str,
            "vv_status": _vv_from_map(verdict_map, verdict_str), "notes": notes}


def _evaluate_v2_yaml(yaml_path: Path, doc: dict, docs: dict[str, Any]) -> dict:
    """单份 criteria/v2 YAML → 对照表（指标-阈值-出处-判定）+ 汇总。"""
    verdict_map = doc.get("verdict_map") or {}
    rule = doc.get("decision_rule") or {}
    claim = doc.get("claim") or {}
    claim = dict(claim)
    claim["_evidence_fields"] = doc.get("evidence_fields") or []
    form = str(rule.get("form", ""))
    yaml_name = yaml_path.name
    if form == "multi_gate_all_pass":
        evaluated = _evaluate_multi_gate_all_pass(rule, docs, verdict_map, yaml_name)
    elif form == "nearest_reference_gate":
        evaluated = _evaluate_nearest_reference(rule, claim, docs, verdict_map, yaml_name)
    else:
        evaluated = {
            "rows": [{
                "metric": str(claim.get("quantity", "")), "op": "",
                "threshold": None, "observed": None, "unit": "",
                "source": f"{yaml_name}:decision_rule.form",
                "judgment": "UNKNOWN",
            }],
            "overall": "UNKNOWN",
            "vv_status": _vv_from_map(verdict_map, "UNKNOWN"),
            "notes": [f"未支持的 decision_rule.form={form or '(缺省)'}：如实 UNKNOWN"],
        }
    evaluated["criteria_id"] = doc.get("criteria_id")
    evaluated["title"] = doc.get("title")
    evaluated["source"] = str(yaml_path)
    return evaluated


def _run_template(meta: dict | None, docs: dict[str, Any]) -> str | None:
    """run 模板解析序：meta.json:template → 各 json 的 run.template → None。"""
    if isinstance(meta, dict) and isinstance(meta.get("template"), str):
        return meta["template"]
    for fname in sorted(docs):
        doc = docs[fname]
        if isinstance(doc, dict):
            run = doc.get("run")
            if isinstance(run, dict) and isinstance(run.get("template"), str):
                return run["template"]
    return None


def _harvest_bool_gates(docs: dict[str, Any]) -> tuple[list[str], list[str]]:
    """run 级布尔门采集（gates/readout_gates 任一顶层 dict-of-bool）。"""
    passed: list[str] = []
    failed: list[str] = []
    for fname in sorted(docs):
        doc = docs[fname]
        if not isinstance(doc, dict):
            continue
        for key in ("readout_gates", "gates"):
            block = doc.get(key)
            if not isinstance(block, dict):
                continue
            for name, value in block.items():
                if isinstance(value, bool):
                    (passed if value else failed).append(name)
    return passed, failed


def _build_criteria_section(run_dir: Path, docs: dict[str, Any], template: str | None,
                            criteria_dir: Path | None,
                            anomalies: list[str]) -> dict:
    """§3 数据 vs 判据：v2 YAML 逐条对照；无适用→none-provided 不虚构。"""
    section: dict[str, Any] = {
        "source": "", "status": _CRITERIA_NONE, "criteria_id": None,
        "title": None, "template": template, "rows": [], "overall": None,
        "vv_status": None, "notes": [],
    }
    if template is None:
        section["notes"].append(
            "run 无 template 字段：无法匹配 criteria/v2 模板，如实 none-provided")
        section["source"] = _CRITERIA_NONE
        anomalies.append("无判据模板可匹配：criteria=none-provided（不虚构对照表）")
        return section
    base = criteria_dir if criteria_dir is not None else _default_criteria_dir()
    if base is None or not Path(base).is_dir():
        section["notes"].append(f"criteria/v2 目录不在场：{base}（如实 none-provided）")
        section["source"] = _CRITERIA_NONE
        anomalies.append("criteria/v2 目录缺失：无机器判据可消费")
        return section
    import yaml

    applied: list[dict] = []
    for yaml_path in sorted(Path(base).glob("*.yaml")):
        try:
            doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            anomalies.append(f"criteria YAML 解析失败 {yaml_path.name}：{exc}")
            continue
        if not isinstance(doc, dict) or doc.get("schema") != _CRITERIA_V2_SCHEMA:
            continue
        if (doc.get("claim") or {}).get("template") != template:
            continue
        applied.append(_evaluate_v2_yaml(yaml_path, doc, docs))
    if not applied:
        section["notes"].append(
            f"knowledge/criteria/v2 中无 claim.template=={template!r} 的判据：如实 none-provided")
        section["source"] = _CRITERIA_NONE
        anomalies.append(f"模板 {template} 无适用 criteria/v2 判据：none-provided（不虚构）")
        return section
    first = applied[0]
    section.update({
        "source": "; ".join(a["source"] for a in applied),
        "status": "applied",
        "criteria_id": "; ".join(str(a["criteria_id"]) for a in applied),
        "title": first["title"],
        "rows": [row for a in applied for row in a["rows"]],
        "overall": "; ".join(str(a["overall"]) for a in applied),
        "vv_status": "; ".join(str(a["vv_status"]) for a in applied),
        "notes": section["notes"] + [n for a in applied for n in a["notes"]],
    })
    return section


def _default_criteria_dir() -> Path | None:
    """仓库 knowledge/criteria/v2（service 目录向上四级到仓根）。"""
    base = Path(__file__).resolve().parents[3] / "knowledge" / "criteria" / "v2"
    return base if base.is_dir() else None


def build_report_model(run_dir: str | Path, *, criteria_dir: str | Path | None = None,
                       git_commit: str | None = None) -> dict:
    """run 目录 → 报告模型（schema ``rfauto-report/v1``，纯 dict 可 json 化）。

    四段式大纲：identification / method / criteria / conclusion；
    全部数值载体节点带 ``source`` 键（:func:`bare_number_fields` 判零）。
    """
    run_path = Path(run_dir)
    if not run_path.is_dir():
        raise FileNotFoundError(f"run 目录不存在：{run_path}")
    anomalies: list[str] = []
    docs = _load_json_docs(run_path)
    meta = docs.get("meta.json")
    result = docs.get("result.json")
    template = _run_template(meta if isinstance(meta, dict) else None, docs)
    method_rows, method_status = _flatten_method_fields(
        meta if isinstance(meta, dict) else None,
        result if isinstance(result, dict) else None, anomalies)
    curves = _load_curves(run_path, anomalies)
    criteria = _build_criteria_section(run_path, docs, template,
                                       Path(criteria_dir) if criteria_dir else None,
                                       anomalies)
    passed, failed = _harvest_bool_gates(docs)
    run_verdict = ""
    for fname in sorted(docs):
        doc = docs[fname]
        if isinstance(doc, dict) and isinstance(doc.get("verdict"), str):
            run_verdict = doc["verdict"]
            break
    conclusion_verdict = run_verdict or criteria.get("overall") or "UNKNOWN"
    from rfauto.core.vv_mapping import map_verdict

    vv = map_verdict(conclusion_verdict)
    if failed:
        anomalies.append(f"布尔门 FAIL：{', '.join(sorted(failed))}")
    if criteria["status"] == "applied" and "FAIL" in str(criteria.get("overall", "")):
        anomalies.append("判据对照表存在 FAIL 行（如实记，不翻案不凑绿 #122）")
    conclusion_source = ("verdict.json:verdict" if run_verdict
                         else (criteria["source"] or "none:missing"))
    model: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "identification": {
            "source": str(run_path),
            "run_id": run_path.name,
            "run_dir": str(run_path),
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "git_commit": git_commit if git_commit is not None else _read_git_commit(run_path),
            "artifacts": [
                {"artifact": name, "path": str(run_path / name),
                 "exists": (run_path / name).is_file(), "role": role}
                for name, role in (
                    ("meta.json", "方法配置"), ("result.json", "run 结果"),
                    ("verdict.json", "判读"), ("sparams.csv", "S 参数曲线"),
                    ("criteria.md", "历史预声明（只读）"),
                )
            ],
        },
        "method": {
            "source": "; ".join(sorted({str(r["source"]).split(":")[0]
                                        for r in method_rows})) or "none:missing",
            "status": method_status,
            "template": template,
            "fields": method_rows,
        },
        "criteria": criteria,
        "conclusion": {
            "source": conclusion_source,
            "verdict": conclusion_verdict,
            "vv_status": vv["vv_status"],
            "vv_basis": vv["vv_basis"],
            "gates_pass": passed,
            "gates_fail": failed,
            "criteria_overall": criteria.get("overall"),
            "anomalies": anomalies,
        },
        "curves": curves,
    }
    return model


# ── 渲染（只消费模型，零二次采数） ──────────────────────────────────────────

_SECTION_TITLES = (
    ("identification", "标识引用"),
    ("method", "方法配置"),
    ("criteria", "数据与判据"),
    ("conclusion", "结论与异常"),
)


def _typ_cell(text: str) -> str:
    return f"[{typ_escape(text)}]"


_TYP_TEMPLATE = r"""#set text(font: ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC"), lang: "zh")
#set page(margin: 2cm, numbering: "1")
#set heading(numbering: none)
#set par(justify: true)

= rfauto 仿真报告：{{ model.identification.run_id | tc }}

{{ model.schema | tc }} ｜ 生成时间 {{ model.identification.generated_at | tc }} ｜ git {{ model.identification.git_commit | tc }}

== 标识引用

#table(
  columns: (auto, auto, auto, auto),
  table.header([ artifact ], [ path ], [ exists ], [ role ]),
{% for row in model.identification.artifacts %}  {{ row.artifact | tc }}, {{ row.path | tc }}, {{ (row.exists | fv) | tc }}, {{ row.role | tc }},
{% endfor %})
#v(4mm)

run_dir：{{ model.identification.run_dir | tc }} ｜ source：{{ model.identification.source | tc }}

== 方法配置

模板：{{ model.method.template | fv }}（status：{{ model.method.status | tc }}；source：{{ model.method.source | tc }}）

#table(
  columns: (auto, auto, auto, auto),
  table.header([ 字段 ], [ 值 ], [ 单位 ], [ 出处 ]),
{% for row in model.method.fields %}  {{ row.name | tc }}, {{ (row.value | fv) | tc }}, {{ (row.unit or "") | tc }}, {{ row.source | tc }},
{% endfor %})

== 数据与判据

判据状态：{{ model.criteria.status | tc }}；criteria_id：{{ model.criteria.criteria_id | fv }}；模板：{{ model.criteria.template | fv }}；汇总：{{ model.criteria.overall | fv }}；vv_status：{{ model.criteria.vv_status | fv }}

判据标题：{{ model.criteria.title | fv }} ｜ 出处：{{ model.criteria.source | tc }}

{% if model.criteria.rows %}#table(
  columns: (auto, auto, auto, auto, auto),
  table.header([ 指标 ], [ 阈值 ], [ 观测 ], [ 判定 ], [ 出处 ]),
{% for row in model.criteria.rows %}  {{ row.metric | tc }}, {{ ((row.op or "") ~ " " ~ (row.threshold | fv) ~ " " ~ (row.unit or "")) | tc }}, {{ (((row.observed | fv)) ~ " " ~ (row.unit or "")) | tc }}, {{ row.judgment | tc }}, {{ row.source | tc }},
{% endfor %})
{% else %}无适用判据模板：criteria: {{ model.criteria.status | tc }}（如实标注，不虚构对照表）。#v(2mm)
{% endif %}
{% for note in model.criteria.notes %}注记：{{ note | tc }}
{% endfor %}
== 结论与异常

verdict：{{ model.conclusion.verdict | tc }}；vv_status：{{ model.conclusion.vv_status | tc }}（{{ model.conclusion.vv_basis | tc }}）

判据汇总：{{ model.conclusion.criteria_overall | fv }}；PASS 门：{{ ((model.conclusion.gates_pass | join(", ")) or "无") | tc }}；FAIL 门：{{ ((model.conclusion.gates_fail | join(", ")) or "无") | tc }}

source：{{ model.conclusion.source | tc }}

{% for a in model.conclusion.anomalies %}异常：{{ a | tc }}
{% else %}异常：无
{% endfor %}
曲线：{{ model.curves.n_traces | fv }} 条 trace × {{ model.curves.n_points | fv }} 点（status：{{ model.curves.status | tc }}；source：{{ model.curves.source | tc }}；note：{{ model.curves.note | fv }}；交互图见同源 HTML 版）

trace 标签：{{ ((model.curves.traces | map(attribute="label") | join(", ")) or "无") | tc }}

trace 出处：{% for t in model.curves.traces %}{{ (t.label ~ "(" ~ t.source ~ ")") | tc }} {% else %}无
{% endfor %}
"""


def _jinja_env() -> Any:
    from jinja2 import Environment

    env = Environment(autoescape=False, keep_trailing_newline=True)
    env.filters["fv"] = fmt_value
    # tc 只接受字符串（模板侧先经 fv 组串），统一走 typst 转义
    env.filters["tc"] = _typ_cell
    env.filters["typ"] = lambda v: typ_escape(v if isinstance(v, str) else fmt_value(v))
    return env


def render_typ(model: dict) -> str:
    """报告模型 → typst 源（只消费模型；值统一走 fmt_value+typst 转义）。"""
    return _jinja_env().from_string(_TYP_TEMPLATE).render(model=model)


def _font_paths() -> list[str]:
    """CJK 字体目录（Windows 系统字体；其他平台靠 typst 系统字体扫描）。"""
    import os

    if os.name == "nt":
        win_fonts = r"C:\Windows\Fonts"
        return [win_fonts] if Path(win_fonts).is_dir() else []
    for candidate in ("/usr/share/fonts", "/usr/local/share/fonts"):
        if Path(candidate).is_dir():
            return [candidate]
    return []


def render_pdf(model: dict) -> bytes:
    """报告模型 → PDF 字节（typst-py，font_paths 指系统字体防 CJK 豆腐块）。"""
    import typst

    return typst.compile(render_typ(model).encode("utf-8"),
                         font_paths=_font_paths())


_HTML_STYLE = """
body { font-family: "Microsoft YaHei", "SimHei", sans-serif; margin: 24px auto; max-width: 960px; }
h1 { border-bottom: 2px solid #334; }
h2 { border-bottom: 1px solid #99a; margin-top: 28px; }
table { border-collapse: collapse; margin: 8px 0; }
th, td { border: 1px solid #bbb; padding: 3px 8px; text-align: left; }
th { background: #eef; }
td.num { text-align: right; }
.judge-PASS { color: #070; font-weight: bold; }
.judge-FAIL { color: #c00; font-weight: bold; }
.judge-UNKNOWN { color: #880; }
.meta { color: #556; }
ul { margin: 4px 0; }
"""


def _html_table(headers: list[str], rows: list[list[str]], *,
                judge_col: int | None = None) -> str:
    out = ["<table><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"]
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            cls = f' class="judge-{cell}"' if i == judge_col and cell in (
                "PASS", "FAIL", "UNKNOWN") else ""
            cells.append(f"<td{cls}>{cell}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def render_html(model: dict) -> str:
    """报告模型 → 自包含 HTML（plotly include_plotlyjs=True 零外网 CDN）。

    只消费模型：四段字段与 PDF 同源；曲线图由 model.curves 构建。
    """
    import html as _html
    from html import escape as esc

    def e(value: Any) -> str:
        return _html.escape(fmt_value(value))

    parts = [
        "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">",
        f"<title>rfauto 报告 {esc(model['identification']['run_id'])}</title>",
        f"<style>{_HTML_STYLE}</style></head><body>",
        "<h1>rfauto 仿真报告：", esc(model["identification"]["run_id"]), "</h1>",
        "<p class=\"meta\">", e(model["schema"]), " ｜ 生成时间 ",
        e(model["identification"]["generated_at"]), " ｜ git ",
        e(model["identification"]["git_commit"]), "</p>",
    ]

    # ① 标识引用
    parts.append("<h2 id=\"sec-identification\">标识引用</h2>")
    ident = model["identification"]
    parts.append(_html_table(
        ["字段", "值", "出处"],
        [["run_id", e(ident["run_id"]), e(ident["run_dir"])],
         ["schema", e(ident["schema"]), e(ident["source"])],
         ["run_dir", esc(ident["run_dir"]), e(ident["source"])],
         ["git_commit", e(ident["git_commit"]), "git rev-parse"],
         ["generated_at", e(ident["generated_at"]), e(ident["source"])]]))
    parts.append(_html_table(
        ["artifact", "path", "exists", "role"],
        [[esc(a["artifact"]), esc(a["path"]),
          "<span class=\"judge-PASS\">true</span>" if a["exists"]
          else "<span class=\"judge-UNKNOWN\">false</span>",
          esc(a["role"])]
         for a in ident["artifacts"]]))

    # ② 方法配置
    parts.append("<h2 id=\"sec-method\">方法配置</h2>")
    method = model["method"]
    parts.extend(("<p class=\"meta\">template：", e(method["template"]),
                  " ｜ status：", e(method["status"]), " ｜ source：",
                  e(method["source"]), "</p>"))
    parts.append(_html_table(
        ["字段", "值", "单位", "出处"],
        [[esc(r["name"]), e(r["value"]), esc(r["unit"]), esc(r["source"])]
         for r in method["fields"]]))

    # ③ 数据与判据
    parts.append("<h2 id=\"sec-criteria\">数据与判据</h2>")
    crit = model["criteria"]
    parts.extend(("<p class=\"meta\">criteria 状态：<b>", e(crit["status"]),
                  "</b> ｜ criteria_id：", e(crit["criteria_id"]),
                  " ｜ 模板：", e(crit["template"]),
                  " ｜ 汇总：", e(crit["overall"]),
                  " ｜ vv_status：", e(crit["vv_status"]), "</p>"))
    parts.extend(("<p class=\"meta\">判据标题：", e(crit["title"]),
                  " ｜ 出处：", esc(crit["source"]), "</p>"))
    if crit["rows"]:
        parts.append(_html_table(
            ["指标", "阈值", "观测", "判定", "出处"],
            [[esc(r["metric"]),
              f"{esc(r['op'])} {e(r['threshold'])} {esc(r['unit'])}".strip(),
              f"{e(r['observed'])} {esc(r['unit'])}".strip(),
              f"<span class=\"judge-{r['judgment']}\">{r['judgment']}</span>",
              esc(r["source"])] for r in crit["rows"]], judge_col=3))
    else:
        parts.extend(("<p>无适用判据模板：criteria: ", e(crit["status"]),
                      "（如实标注，不虚构对照表）</p>"))
    for note in crit["notes"]:
        parts.extend(("<p class=\"meta\">注记：", esc(str(note)), "</p>"))

    # ④ 结论与异常
    parts.append("<h2 id=\"sec-conclusion\">结论与异常</h2>")
    concl = model["conclusion"]
    parts.extend(("<p>verdict：<b>", e(concl["verdict"]), "</b> ｜ vv_status：",
                  e(concl["vv_status"]), "（", e(concl["vv_basis"]), "）</p>"))
    parts.extend(("<p>判据汇总：", e(concl["criteria_overall"]),
                  " ｜ PASS 门：", e(", ".join(concl["gates_pass"]) or "无"),
                  " ｜ FAIL 门：", e(", ".join(concl["gates_fail"]) or "无"),
                  " ｜ source：", esc(concl["source"]), "</p>"))
    if concl["anomalies"]:
        parts.append("<ul>")
        for a in concl["anomalies"]:
            parts.extend(("<li>", esc(str(a)), "</li>"))
        parts.append("</ul>")
    else:
        parts.append("<p>异常：无</p>")
    curves = model["curves"]
    parts.extend(("<p class=\"meta\">曲线：", e(curves["n_traces"]), " 条 trace × ",
                  e(curves["n_points"]), " 点 ｜ status：", e(curves["status"]),
                  " ｜ source：", e(curves["source"]),
                  " ｜ note：", e(curves["note"]), "</p>"))
    parts.extend(("<p class=\"meta\">trace 标签：",
                  e(", ".join(t["label"] for t in curves["traces"]) or "无"), "</p>"))
    parts.extend(("<p class=\"meta\">trace 出处：",
                  esc(", ".join(f"{t['label']}({t['source']})"
                                for t in curves["traces"]) or "无"), "</p>"))
    if curves["status"] == "ok" and curves["traces"]:
        fig = _build_figure(curves)
        parts.append(fig.to_html(full_html=False, include_plotlyjs=True,
                                 config={"displaylogo": False}))
    parts.append("</body></html>")
    return "".join(parts)


def _build_figure(curves: dict) -> Any:
    """model.curves → plotly 图（零模型外采数）。"""
    import plotly.graph_objects as go

    fig = go.Figure()
    for trace in curves["traces"]:
        fig.add_trace(go.Scatter(
            x=curves["freq_ghz"], y=trace["values_db"],
            mode="lines", name=str(trace["label"])))
    fig.update_layout(
        title="|S| (dB) vs 频率（GHz）",
        xaxis_title="频率 (GHz)", yaxis_title="|S| (dB)",
        hovermode="x unified")
    return fig


# ── 落盘入口（service 层 JSON 进出，CLI/MCP 薄壳） ─────────────────────────


def render_run_report(run_dir: str | Path, out_dir: str | Path | None = None, *,
                      criteria_dir: str | Path | None = None) -> dict:
    """构建模型 → 双产物落盘（report.pdf / report.html / report.typ）。

    返回 JSON 面结果 dict（ok/paths/schema/criteria_status/verdict/…）；
    out_dir 缺省=run_dir/_report。
    """
    run_path = Path(run_dir)
    try:
        model = build_report_model(run_path, criteria_dir=criteria_dir)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}
    target = Path(out_dir) if out_dir is not None else run_path / "_report"
    try:
        target.mkdir(parents=True, exist_ok=True)
        typ_src = render_typ(model)
        (target / "report.typ").write_text(typ_src, encoding="utf-8")
        pdf_bytes = render_pdf(model)
        pdf_path = target / "report.pdf"
        pdf_path.write_bytes(pdf_bytes)
        html_path = target / "report.html"
        html_path.write_text(render_html(model), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"报告产物写盘失败：{exc}"}
    except Exception as exc:  # 渲染链故障如实上报，不让调用方拿半截产物（#105）
        return {"ok": False, "error": f"报告渲染失败：{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "pdf_path": str(pdf_path),
        "html_path": str(html_path),
        "typ_path": str(target / "report.typ"),
        "run_id": model["identification"]["run_id"],
        "criteria_status": model["criteria"]["status"],
        "verdict": model["conclusion"]["verdict"],
        "vv_status": model["conclusion"]["vv_status"],
        "n_anomalies": len(model["conclusion"]["anomalies"]),
    }
