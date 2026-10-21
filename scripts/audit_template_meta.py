"""模板 meta.yaml 健康度审计门（架构批 R8 面 3 常驻化，2026-10-11 A8-C 席）。

R8 侦察（runs/架构批/R8_other_optimizations.md 面 3）：docs/templates 77 目录
=注册 72 + edb_* 5 族独立通道，meta.yaml 全量解析 nominal/链接面健康，但当时
teaching 仅 9/77——此后 teaching 已扩到 51 族。本脚本把 meta 健康度制度化
（只读审计，零写面）：

审计维度（每模板 5 维，违例逐条出清单）：
  1. schema——必备键在位（对照 tests/unit/test_template_meta_consistency 的
     EXPECTED 形态；注册族与 edb 通道各一套核心键）+ 顶层标量 sane
     （f0_ghz>0、n_ports≥0（0=探针读出无端口，ms_array_NxN 先例）、
     mesh_resolution_mm≥0、max_time_ns>0、n_segments null/≥0）+ params 列表
     合法且 ⊆ nominal_params + template==目录名 + campaign_capable=false
     必带 reasons+unlock_criteria 三键；
  2. nominal——非空且数值叶按键名语义粗守卫：*_ghz/*_ohm/*_pf/*_nh>0、
     er/er_fill≥1、tan_d/loss_tangent≥0、*_mm>0（h_mm==0 豁免=空波导/
     喇叭族无基板，coax_waveguide_transition/pyramid_horn/ridged_wg 实例）、
     *_frac∈(0,1]、count 类≥0、offset 类≥0；非数值叶仅 cell_id 豁免
     （ms_array_NxN cell_map 逐胞表）；bool 拒收、非有限值拒收；
  3. placeholder——全文扫占位符残留：TBD/FIXME/待填/待补/lorem/xxx 词与
     裸 TODO（非台账引用——"TODO 0dk"类坑账编号引用是合法溯源记号）；
  4. teaching——在场则按 rfauto-teaching/v1 schema 校验（与 service/
     teaching_service.load_teaching 同规则：physics.summary、derivations
     三键、sensitivity_ranking 名次 1..N 连续；另钉 quiz_refs 形态与
     ranking.param ⊆ params∪nominal∪substrate∪基片别名）；
  5. link——文中仓内路径引用存在性（docs/knowledge/scripts/src/runs/
     recipes/tests/configs/adapters/core/service/linkage/infra/oe_templates
     前缀；解析链=仓根直指 → src/rfauto/ → src/rfauto/adapters/，逐级
     补 .py/.yaml/.md/.json 扩展名，"file.symbol" 记号按末点分段重试）。
     runs/ 前缀=工作区证据面（gitignored，#289 口径），缺失只进报告面
     永不打红——防 runs/ 生命周期轮转打红无关席位；其余前缀缺失=硬红。

豁免清单 EXEMPTIONS（现值空；维护规则）：误报类合法形态走
(template, dim, detail 子串) 三元组豁免，每条必须带理由注记；修复后移除
（只收不放语义同 test_w2_c_json_coverage WITHOUT_JSON 先例）。挂
merge_preflight 面 15 的前置=现树零违例且豁免清单为空（2026-10-11 A8-C
实测达成：唯一实违例 ms_ring_patch 死链已修复，无豁免条目）。

rc：0=绿（零硬违例）；1=红（违例清单非空）；2=templates 根不可读/空集
——诚实降级 SKIP（merge_preflight 同 pip-audit/锚面口径，#122 三分法）。

用法：
  .venv/Scripts/python.exe scripts/audit_template_meta.py
      [--templates-root <dir>] [--json <out>] [--verbose]

--templates-root 仅供单测注入合成树；生产缺省=仓内 docs/templates。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

REPORT_SCHEMA = "r8/template_meta_health/1"

#: 注册族必备核心键（test_template_meta_consistency EXPECTED 形态的 docs 侧子集）。
REGISTERED_CORE = (
    "template", "params", "nominal_params", "substrate", "f0_ghz", "n_ports",
    "extraction", "mesh_resolution_mm", "n_segments", "max_time_ns",
)

#: EDB 快车道通道必备核心键（schema 单源=adapters/edb_templates/schema.py；
#: meta.yaml 为信息文档形态，见 docs/templates/edb_*/meta.yaml 头注）。
EDB_CORE = (
    "template", "schema_version", "edb_lane", "registry_status", "f0_ghz",
    "n_ports", "units", "substrate", "params", "nominal_params", "topology",
    "extraction",
)

#: 长度键允许取 0（空波导/喇叭族无基板：h_mm=0 合法，2026-10-11 三实例实测）。
LENGTH_ZERO_OK = frozenset({"h_mm"})

#: 偏移/位置类键允许取 0（feed_off_mm/shunt_off_mm/via_offset_mm/g_pos_mm）。
OFFSET_ZERO_OK = frozenset({"feed_off_mm", "shunt_off_mm", "via_offset_mm",
                            "g_pos_mm", "feed_offset_mm"})

#: 非数值叶白名单（键名级）：ms_array_NxN cell_map 逐胞表的 cell_id。
STRING_LEAF_OK = frozenset({"cell_id"})

#: 教学敏感度排序 param 的基片属性别名（substrate 块拼写不一但物理同量）。
SUBSTRATE_ALIASES = frozenset({"tan_d", "loss_tangent", "er", "h_mm", "f0_ghz"})

#: 豁免清单（现值空）：(template, dim, detail 子串)。每条带理由注记；修复后移除。
EXEMPTIONS: tuple[tuple[str, str, str], ...] = ()

# ─── 占位符残留（维度 3）─────────────────────────────────────────────────────

#: "TODO 0dk"/"TODO 0df④"类坑账编号引用是合法溯源记号——负向前瞻放行
#: "TODO+空白+字母数字"形态，裸 "TODO"/"TODO："才是残留。
_PLACEHOLDER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bTBD\b"), "TBD"),
    (re.compile(r"\bFIXME\b"), "FIXME"),
    (re.compile(r"待填|待补"), "待填/待补"),
    (re.compile(r"\bxxx\b", re.IGNORECASE), "xxx"),
    (re.compile(r"lorem ipsum", re.IGNORECASE), "lorem"),
    (re.compile(r"TODO(?![ \t]*[0-9A-Za-z])"), "裸 TODO（非台账引用形态）"),
)

# ─── 链接解析（维度 5）───────────────────────────────────────────────────────

_REF_TOKEN_RE = re.compile(
    r"(?:docs|knowledge|scripts|src|runs|recipes|tests|configs|adapters|core"
    r"|service|linkage|infra|oe_templates)/[A-Za-z0-9_\-./]+")
_REF_EXTS = (".py", ".yaml", ".md", ".json")
_REF_BASES = ("", "src/rfauto", "src/rfauto/adapters")
_EVIDENCE_PREFIX = "runs/"


def resolve_ref(token: str, repo: Path) -> Path | None:
    """仓内路径引用 → 实际存在路径；全链未命中返回 None。

    解析链：仓根直指 → src/rfauto/ → src/rfauto/adapters/（模块路径引用
    core/synthesis、oe_templates/render_tl.py 等形态），逐级补扩展名；
    "file.symbol" 记号（scripts/build_docs_pages.build_templates_page、
    scripts/hairpin_q_extract.HAIRPIN_ALT_KGAP_GATE）按末点分段重试。
    """
    token = token.rstrip("./")
    bases = [repo, repo / "src" / "rfauto", repo / "src" / "rfauto" / "adapters"]
    cands = [token] + [token + e for e in _REF_EXTS]
    if "." in token:
        base = token.rsplit(".", 1)[0]
        cands += [base] + [base + e for e in _REF_EXTS]
    for b in bases:
        for c in cands:
            p = b / c
            if p.exists():
                return p
    return None


# ─── 数值语义守卫（维度 2）───────────────────────────────────────────────────


def _check_numeric_leaf(template: str, key: str, v: object, out: list[dict]) -> None:
    """nominal_params 数值叶按键名语义粗守卫（误报走 EXEMPTIONS）。"""
    where = f"nominal.{key}"
    if key in STRING_LEAF_OK:
        return
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        out.append({"template": template, "dim": "nominal",
                    "detail": f"{where}={v!r} 非数值叶（白名单外）"})
        return
    f = float(v)
    if not math.isfinite(f):
        out.append({"template": template, "dim": "nominal",
                    "detail": f"{where}={v!r} 非有限值"})
        return
    bad = None
    if key.endswith("_ghz") and f <= 0:
        bad = "频率须>0"
    elif key.endswith("_ohm") and f <= 0:
        bad = "阻抗须>0"
    elif key in ("er", "er_fill") and f < 1.0:
        bad = "介电常数须≥1"
    elif "tan_d" in key or key == "loss_tangent":
        if f < 0:
            bad = "损耗角正切须≥0"
    elif (key.endswith("_pf") or key.endswith("_nh")) and f <= 0:
        bad = "集总值须>0"
    elif key.endswith("_frac") and not 0.0 < f <= 1.0:
        bad = "比例须∈(0,1]"
    elif key.endswith("_mm"):
        if key in LENGTH_ZERO_OK:
            if f < 0:
                bad = "厚度须≥0（0=无基板合法）"
        elif key in OFFSET_ZERO_OK:
            if f < 0:
                bad = "偏移须≥0"
        elif f <= 0:
            bad = "长度须>0"
    elif (key.startswith("n_") or key in ("order", "helix_turns")) and f < 0:
        bad = "计数须≥0"
    if bad:
        out.append({"template": template, "dim": "nominal",
                    "detail": f"{where}={v!r}（{bad}）"})


def _walk_nominal(template: str, node: object, key: str, out: list[dict]) -> None:
    """递归叶子（标量/列表/逐胞 dict 表）逐叶守卫；key 沿结构下传。"""
    if isinstance(node, dict):
        for k, x in node.items():
            _walk_nominal(template, x, str(k), out)
    elif isinstance(node, (list, tuple)):
        for x in node:
            _walk_nominal(template, x, key, out)
    else:
        _check_numeric_leaf(template, key, node, out)


# ─── teaching 校验（维度 4；与 teaching_service.load_teaching 同规则）─────────


def _check_teaching(template: str, data: dict, out: list[dict]) -> None:
    teaching = data.get("teaching")
    if teaching is None:
        return
    if not isinstance(teaching, dict):
        out.append(_v(template, "teaching", "teaching 块必须为 dict"))
        return
    if teaching.get("schema") != "rfauto-teaching/v1":
        out.append(_v(template, "teaching", "teaching.schema 必须=rfauto-teaching/v1"))
    physics = teaching.get("physics")
    if not isinstance(physics, dict) or not str(physics.get("summary") or "").strip():
        out.append(_v(template, "teaching", "physics.summary 必须非空"))
    deriv = physics.get("derivations") if isinstance(physics, dict) else None
    if not isinstance(deriv, list) or not deriv:
        out.append(_v(template, "teaching", "physics.derivations 必须为非空列表"))
    else:
        for i, d in enumerate(deriv):
            if not isinstance(d, dict):
                out.append(_v(template, "teaching", f"derivations[{i}] 必须为 dict"))
                continue
            for key in ("claim", "formula", "source"):
                if not isinstance(d.get(key), str) or not d[key].strip():
                    out.append(_v(template, "teaching",
                                  f"derivations[{i}].{key} 必须为非空字符串"))
    ranking = teaching.get("sensitivity_ranking")
    if not isinstance(ranking, list) or not ranking:
        out.append(_v(template, "teaching", "sensitivity_ranking 必须为非空列表"))
        ranking = []
    orders = []
    universe = (set(data.get("params") or []) | set(data.get("nominal_params") or {})
                | set(data.get("substrate") or {}) | SUBSTRATE_ALIASES)
    for i, r in enumerate(ranking):
        if not isinstance(r, dict):
            out.append(_v(template, "teaching", f"sensitivity_ranking[{i}] 必须为 dict"))
            continue
        for key in ("param", "basis"):
            if not isinstance(r.get(key), str) or not r[key].strip():
                out.append(_v(template, "teaching",
                              f"sensitivity_ranking[{i}].{key} 必须为非空字符串"))
        order = r.get("order")
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            out.append(_v(template, "teaching",
                          f"sensitivity_ranking[{i}].order 必须为正整数名次"))
        else:
            orders.append(order)
        if isinstance(r.get("param"), str) and r["param"] not in universe:
            out.append(_v(template, "teaching",
                          f"sensitivity_ranking[{i}].param={r['param']!r} "
                          "不在 params∪nominal∪substrate∪基片别名宇宙"))
    if orders and sorted(orders) != list(range(1, len(orders) + 1)):
        out.append(_v(template, "teaching", "sensitivity_ranking 名次必须为 1..N 连续"))
    quiz = teaching.get("quiz_refs")
    if quiz is not None and (not isinstance(quiz, list)
                             or not all(isinstance(x, str) and x.strip() for x in quiz)):
        out.append(_v(template, "teaching", "quiz_refs 必须为非空字符串列表"))


def _v(template: str, dim: str, detail: str) -> dict:
    return {"template": template, "dim": dim, "detail": detail}


# ─── 单模板审计（维度 1/2/3/4/5）─────────────────────────────────────────────


def audit_template(
    template: str,
    data: object,
    raw_text: str,
    repo: Path,
    exemptions: tuple[tuple[str, str, str], ...] = EXEMPTIONS,
) -> tuple[list[dict], list[dict]]:
    """单模板 5 维审计 → (违例清单, 证据面缺失清单)。

    data=yaml 解析结果；raw_text=原文（占位符/链接扫描面）；repo=仓根
    （链接解析基准）。纯函数，零 IO 写面（resolve_ref 只读存在性）。
    """
    violations: list[dict] = []
    evidence_missing: list[dict] = []
    if not isinstance(data, dict):
        return [_v(template, "schema", "meta.yaml 顶层必须是 mapping")], evidence_missing

    # 维度 1：schema——族分类（edb 通道自声明 edb_lane/registry_status）
    is_edb = bool({"edb_lane", "registry_status"} & set(data))
    core = EDB_CORE if is_edb else REGISTERED_CORE
    for k in core:
        if k not in data:
            violations.append(_v(template, "schema", f"缺必备键 {k}"
                                 f"（{'edb 通道' if is_edb else '注册族'}核心）"))
    if data.get("template") != template:
        violations.append(_v(template, "schema",
                             f"template={data.get('template')!r} ≠ 目录名 {template!r}"))
    f0 = data.get("f0_ghz")
    if isinstance(f0, bool) or not isinstance(f0, (int, float)) or f0 <= 0:
        violations.append(_v(template, "schema", f"f0_ghz={f0!r} 须为正数"))
    npn = data.get("n_ports")
    if isinstance(npn, bool) or not isinstance(npn, int) or npn < 0:
        violations.append(_v(template, "schema", f"n_ports={npn!r} 须为非负整数"
                             "（0=探针读出无端口，ms_array_NxN 先例）"))
    if not is_edb:
        mesh = data.get("mesh_resolution_mm")
        if mesh is not None and (isinstance(mesh, bool) or not isinstance(mesh, (int, float))
                                 or mesh < 0):
            violations.append(_v(template, "schema",
                                 f"mesh_resolution_mm={mesh!r} 须为 null 或 ≥0（0=自动）"))
        mt = data.get("max_time_ns")
        if isinstance(mt, bool) or not isinstance(mt, (int, float)) or mt <= 0:
            violations.append(_v(template, "schema", f"max_time_ns={mt!r} 须为正数"))
        ns = data.get("n_segments")
        if ns is not None and (isinstance(ns, bool) or not isinstance(ns, int) or ns < 0):
            violations.append(_v(template, "schema",
                                 f"n_segments={ns!r} 须为 null 或 ≥0"))
    params = data.get("params")
    if not isinstance(params, list) or not params:
        violations.append(_v(template, "schema", "params 必须为非空列表"))
        params = []
    else:
        if any(not isinstance(x, str) or not x.strip() for x in params):
            violations.append(_v(template, "schema", "params 必须全为非空字符串"))
        if len(set(params)) != len(params):
            violations.append(_v(template, "schema", "params 含重复键"))
    nominal = data.get("nominal_params")
    if not isinstance(nominal, dict) or not nominal:
        violations.append(_v(template, "schema", "nominal_params 必须为非空映射"))
        nominal = {}
    missing_nominal = set(params) - set(nominal)
    if missing_nominal and not is_edb:
        # 注册族不变量（test_template_meta_consistency src 侧同款）；edb 通道
        # params=发射器入参（f0_ghz/z0_ohm 等缺省在发射器 docstring），nominal
        # 只承载综合几何——不适用。
        violations.append(_v(template, "schema",
                             f"params 缺标称值 {sorted(missing_nominal)}"))
    sub = data.get("substrate")
    if not isinstance(sub, dict) or "er" not in sub or "h_mm" not in sub:
        violations.append(_v(template, "schema", "substrate 必须为含 er/h_mm 的映射"))
    else:
        er = sub.get("er")
        if isinstance(er, bool) or not isinstance(er, (int, float)) or er < 1.0:
            violations.append(_v(template, "schema", f"substrate.er={er!r} 须≥1"))
        h = sub.get("h_mm")
        if isinstance(h, bool) or not isinstance(h, (int, float)) or h < 0:
            violations.append(_v(template, "schema", f"substrate.h_mm={h!r} 须≥0"))
        for k in ("tan_d", "loss_tangent"):
            if k in sub:
                td = sub[k]
                if isinstance(td, bool) or not isinstance(td, (int, float)) or td < 0:
                    violations.append(_v(template, "schema",
                                         f"substrate.{k}={td!r} 须≥0"))
    if data.get("campaign_capable") is False:
        reasons = data.get("campaign_capable_reasons")
        if not isinstance(reasons, list) or not reasons \
                or not all(isinstance(r, str) and r for r in reasons):
            violations.append(_v(template, "schema",
                                 "campaign_capable=false 必带非空字符串列表 "
                                 "campaign_capable_reasons"))
        criteria = data.get("campaign_unlock_criteria")
        if not isinstance(criteria, dict) or not criteria:
            violations.append(_v(template, "schema",
                                 "campaign_capable=false 必带 campaign_unlock_criteria"))

    # 维度 2：nominal 数值语义
    if isinstance(nominal, dict) and nominal:
        _walk_nominal(template, nominal, "", violations)

    # 维度 3：占位符残留
    for pat, label in _PLACEHOLDER_PATTERNS:
        if pat.search(raw_text):
            violations.append(_v(template, "placeholder",
                                 f"占位符残留：{label}"))

    # 维度 4：teaching
    _check_teaching(template, data, violations)

    # 维度 5：链接存在性
    seen: set[str] = set()
    for tok in _REF_TOKEN_RE.findall(raw_text):
        tok = tok.rstrip("./")
        if tok in seen:
            continue
        seen.add(tok)
        if resolve_ref(tok, repo) is None:
            if tok.startswith(_EVIDENCE_PREFIX):
                # runs/=工作区证据面（gitignored）——报告面留痕，永不打红
                evidence_missing.append({"template": template, "ref": tok})
            else:
                violations.append(_v(template, "link", f"断链：{tok}"))

    # 豁免清单消费（template, dim, detail 子串）
    if exemptions:
        kept = []
        for item in violations:
            hit = any(t == item["template"] and d == item["dim"] and sub_ in item["detail"]
                      for t, d, sub_ in exemptions)
            if not hit:
                kept.append(item)
        violations = kept
    return violations, evidence_missing


# ─── 全树审计 ────────────────────────────────────────────────────────────────


def audit_tree(
    templates_root: Path,
    repo: Path = REPO,
    exemptions: tuple[tuple[str, str, str], ...] = EXEMPTIONS,
) -> dict:
    """docs/templates 全目录审计 → 报告 dict（green/violations/证据面清单）。"""
    report: dict = {
        "schema": REPORT_SCHEMA,
        "templates_root": str(templates_root),
        "violations": [],
        "evidence_links_missing": [],
        "exemptions": [list(x) for x in exemptions],
    }
    dirs = sorted(d for d in templates_root.iterdir() if (d / "meta.yaml").is_file())
    if not dirs:
        report["error"] = f"templates 根不可读/空集: {templates_root}"
        return report
    n_teaching = 0
    n_edb = 0
    all_tokens: set[str] = set()
    for d in dirs:
        raw = (d / "meta.yaml").read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        viols, evid = audit_template(d.name, data, raw, repo, exemptions)
        report["violations"].extend(viols)
        report["evidence_links_missing"].extend(evid)
        if isinstance(data, dict):
            if {"edb_lane", "registry_status"} & set(data):
                n_edb += 1
            if isinstance(data.get("teaching"), dict):
                n_teaching += 1
        all_tokens.update(tok.rstrip("./")
                          for tok in _REF_TOKEN_RE.findall(raw))
    report["counts"] = {
        "dirs": len(dirs),
        "edb": n_edb,
        "registered": len(dirs) - n_edb,
        "teaching": n_teaching,
    }
    report["links"] = {
        "tokens": len(all_tokens),
        "evidence_missing": len(report["evidence_links_missing"]),
    }
    report["green"] = not report["violations"]
    return report


def verdict(report: dict) -> int:
    """报告 → 退出码（0 绿 / 1 红 / 2 环境类 SKIP）。"""
    if report.get("error"):
        return 2
    return 0 if report.get("green") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="模板 meta.yaml 健康度审计门（R8 面 3）")
    ap.add_argument("--templates-root", default="",
                    help="覆盖 docs/templates 根（仅供单测合成树）")
    ap.add_argument("--json", dest="json_out", default="",
                    help="报告 JSON 落盘路径（缺省只打印摘要）")
    ap.add_argument("--verbose", action="store_true", help="违例逐条打印")
    args = ap.parse_args(argv)

    root = Path(args.templates_root) if args.templates_root else REPO / "docs" / "templates"
    report = audit_tree(root, REPO)
    rc = verdict(report)
    if rc == 2:
        print(f"[SKIP] 模板 meta 审计：{report.get('error')}——诚实降级"
              "（环境类，不判绿不判红 #122）")
        return 2

    counts = report["counts"]
    print(
        f"templates={counts['dirs']}（registered={counts['registered']} "
        f"edb={counts['edb']} teaching={counts['teaching']}） "
        f"violations={len(report['violations'])} "
        f"evidence_links_missing={report['links']['evidence_missing']} "
        f"(report-only) -> {'GREEN' if report['green'] else 'RED'}"
    )
    if args.verbose:
        for item in report["violations"]:
            print(f"  [{item['dim']}] {item['template']}: {item['detail']}")
        for item in report["evidence_links_missing"]:
            print(f"  [evidence] {item['template']}: {item['ref']}")
    if not report["green"]:
        print("[FAIL] 模板 meta 存在硬违例——修复 meta.yaml 面最小修（不动物理值）；"
              "误报合法形态走脚本 EXEMPTIONS 带理由注记（只收不放）")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
