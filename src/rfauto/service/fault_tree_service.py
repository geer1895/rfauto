"""fault_tree：故障树自动生成 + 最小割集（QM-FTA，round19 P2 前半）。

**接口原型级**（ge8c 席C5 口径）。round19 原文：playbook 17 规则
（symptom AND→root cause）天然是 OR-of-AND 树——树生成 + Z3 求最小割集
+ Mermaid 图（explain_run 报告消费面）。验收（round19）：17 规则全树
无孤儿 + 置空一指纹后 MCS 收窄。

结构语义：顶事件 T="run 失败需根因调查" = OR over 规则；规则 r 在其全部
symptom_fingerprints 同时在场（AND）时触发 → 割集=使 T 成立的指纹集合。
**MCS 数学口径**：OR-of-AND DNF 的最小割集=按包含序极小的 AND 子句——
单指纹子句存在时其超集子句非最小（fdtd_truncation 的 {passivity,tail} vs
sparam_nonphysical 的 {passivity} 即此形态），如实进 nonminimal 列表。

引擎双轨：
- ``enumerate``：子句族⊂过滤（纯确定性，恒可用，主口径）；
- ``z3``：**可选依赖**（extras 不加，import 探测；未安装 ok=False 如实）。
  对每个候选割集做三重形式验证——有效性（子句⇒T 可满足）、最小性
  （去任一字面量则 UNSAT）、完备性（避开全部 MCS 时 T 不可满足=SAT
  即漏割集）。z3-solver 经 ``rfauto[z3]`` extras 安装（pyproject 已有
  z3 extras 条目，本面不新增）。

孤儿口径（explain_run 同源）：规则引用 detector_vocab 之外的指纹 → 该规
则 skip 如实计数（#321 思想），不进树；空指纹规则同理跳过（空 AND=永真
，语义非法）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope
from rfauto.service.explain_run import DEFAULT_PLAYBOOK_PATH, load_playbook

_SOURCE = "rfauto.service.fault_tree_service"
_TOP_ID = "run_failure_investigation"


def build_fault_tree(playbook_path: str | Path | None = None
                     ) -> dict[str, Any]:
    """playbook.yaml → OR-of-AND 故障树（含孤儿审计；零仿真纯结构变换）。

    Returns:
        {ok, tree: {top, rules[]}, audit: {n_rules_total, n_rules_in_tree,
        orphan_rules[], no_orphan, detector_vocab, unused_vocab[]},
        playbook_path}；load 失败 ok=False 透传 reason。
    """
    book = load_playbook(playbook_path)
    if not book.get("ok"):
        return {"ok": False, "source": _SOURCE, "reason": book.get("reason")}
    vocab = set(book.get("detector_vocab") or [])
    rules_in: list[dict[str, Any]] = []
    orphans: list[dict[str, str]] = []
    used: set[str] = set()
    for rule in book["rules"]:
        rid = str(rule.get("id") or f"rule_{len(rules_in)}")
        fps = [str(f) for f in (rule.get("symptom_fingerprints") or [])]
        unknown = sorted(set(fps) - vocab)
        if not fps:
            orphans.append({"rule_id": rid,
                            "reason": "空指纹列表（空 AND=永真，语义非法）"})
            continue
        if unknown:
            orphans.append({"rule_id": rid,
                            "reason": f"引用词表外指纹: {unknown}"})
            continue
        used |= set(fps)
        rules_in.append({"rule_id": rid,
                         "root_cause_family":
                             str(rule.get("root_cause_family") or rid),
                         "gate": "AND", "fingerprints": fps})
    tree = {"top": {"id": _TOP_ID, "gate": "OR",
                    "label": "run 失败需根因调查"},
            "rules": rules_in}
    audit = {"n_rules_total": len(book["rules"]),
             "n_rules_in_tree": len(rules_in),
             "orphan_rules": orphans,
             "no_orphan": len(orphans) == 0,
             "n_detector_vocab": len(vocab),
             "unused_vocab": sorted(vocab - used)}
    return ok_envelope(source=_SOURCE, tree=tree, audit=audit, playbook_path=str(book.get("path") or DEFAULT_PLAYBOOK_PATH))


def blank_fingerprints(tree: dict[str, Any],
                       blanked: set[str] | list[str]) -> dict[str, Any]:
    """置空指纹：从树中剔除引用任一 blanked 指纹的规则（收窄验收用）。"""
    blank = set(blanked)
    rules = [r for r in tree["rules"]
             if not (set(r["fingerprints"]) & blank)]
    return {"top": dict(tree["top"]), "rules": rules}


def _clauses(tree: dict[str, Any]) -> list[frozenset[str]]:
    out: list[frozenset[str]] = []
    for r in tree["rules"]:
        c = frozenset(r["fingerprints"])
        if c and c not in out:
            out.append(c)
    return out


def _enumerate_mcs(clauses: list[frozenset[str]]) -> tuple[list[frozenset[str]],
                                                           list[frozenset[str]]]:
    """子句族 → (最小割集, 非最小割集)：C 最小 ⇔ 无其他子句 C'⊂C。"""
    minimal, nonminimal = [], []
    for c in clauses:
        if any(other < c for other in clauses):
            nonminimal.append(c)
        else:
            minimal.append(c)
    return sorted(minimal, key=lambda s: (len(s), sorted(s))), \
        sorted(nonminimal, key=lambda s: (len(s), sorted(s)))


def _z3_available() -> tuple[bool, str]:
    try:
        import z3  # noqa: F401 可选依赖探测（extras 不加，skipif 诚实）
        return True, ""
    except ImportError as exc:
        return False, (f"z3 未安装（可选依赖 pip install rfauto[z3]）: {exc}")


def _z3_verify(clauses: list[frozenset[str]],
               mcs: list[frozenset[str]]) -> dict[str, Any]:
    """Z3 三重形式验证：有效性/最小性/完备性（全部通过 checks_all_pass）。

    割集语义编码：S 是割集 ⇔ 恰 S 中事件在场（S 内全真、S 外全假）时
    顶事件成立——OR-of-AND 的其他分支在 S 外全假下不可触发，恰集编码
    才是割集语义（自由赋值编码会把"其他分支可触发"误判成非最小）。
    """
    import z3

    fps = sorted({f for c in clauses for f in c})
    var = {f: z3.Bool(f"f_{i}") for i, f in enumerate(fps)}
    top = z3.Or([z3.And([var[f] for f in c]) for c in clauses])

    def _exactly(s: frozenset[str]):
        return [var[f] if f in s else z3.Not(var[f]) for f in fps]

    validity_fail: list[str] = []
    minimality_fail: list[tuple[str, str]] = []
    for c in mcs:
        s1 = z3.Solver()
        s1.add(top)
        for lit in _exactly(c):
            s1.add(lit)
        if s1.check() != z3.sat:  # 有效性：恰 S 在场时 T 成立
            validity_fail.append(sorted(c))
        for drop in c:  # 最小性：S\{drop} 不再是割集（恰集下 UNSAT）
            smaller = frozenset(f for f in c if f != drop)
            s2 = z3.Solver()
            s2.add(top)
            for lit in _exactly(smaller):
                s2.add(lit)
            if s2.check() == z3.sat:
                minimality_fail.append((sorted(c), drop))
    # 完备性：任一满足 T 的赋值（=某割集的特征向量）必包含某枚 MCS——
    # "每枚 MCS 至少缺一字面量"约束下 T 应不可满足；SAT 即漏割集
    s3 = z3.Solver()
    s3.add(top)
    for c in mcs:
        s3.add(z3.Or([z3.Not(var[f]) for f in c]))
    completeness_sat = s3.check() == z3.sat
    return {"validity_fail": validity_fail,
            "minimality_fail": minimality_fail,
            "completeness_sat": completeness_sat,
            "checks_all_pass": (not validity_fail and not minimality_fail
                                and not completeness_sat)}


def minimal_cut_sets(tree: dict[str, Any] | None = None, *,
                     playbook_path: str | Path | None = None,
                     engine: str = "enumerate") -> dict[str, Any]:
    """最小割集：enumerate 主口径恒可用；engine="z3" 加形式验证（可选依赖）。

    Returns:
        {ok, mcs[[fp...]], n_mcs, n_clauses, nonminimal[[fp...]], engine,
        z3_checked: bool|None, z3_report?}；engine 未知/未安装如实
        ok=False（不静默回退——判据面诚实，#122）。
    """
    if tree is None:
        built = build_fault_tree(playbook_path)
        if not built.get("ok"):
            return built
        tree = built["tree"]
    if engine not in ("enumerate", "z3"):
        return {"ok": False, "source": _SOURCE,
                "reason": f"未知 engine {engine!r}（可选 enumerate|z3）"}
    clauses = _clauses(tree)
    if not clauses:
        return {"ok": False, "source": _SOURCE,
                "reason": "树无有效规则（空割集族）"}
    mcs, nonminimal = _enumerate_mcs(clauses)
    out: dict[str, Any] = ok_envelope(
        source=_SOURCE,
        mcs=[sorted(c) for c in mcs],
        nonminimal=[sorted(c) for c in nonminimal],
        n_mcs=len(mcs),
        n_clauses=len(clauses),
        engine=engine,
        z3_checked=None,
    )
    if engine == "z3":
        ok, reason = _z3_available()
        if not ok:
            return {"ok": False, "source": _SOURCE, "reason": reason,
                    "engine": "z3", "hint": "engine='enumerate' 恒可用"}
        report = _z3_verify(clauses, mcs)
        out["z3_checked"] = True
        out["z3_report"] = report
        out["ok"] = bool(report["checks_all_pass"])
        if not out["ok"]:
            out["reason"] = "Z3 形式验证未全通过（有效性/最小性/完备性）"
    return out


def mermaid_fault_tree(tree: dict[str, Any]) -> dict[str, Any]:
    """故障树 → Mermaid 文本（graph TD；OR/AND 门标注，explain_run 消费面）。"""
    lines = ["graph TD"]
    top_id = tree["top"]["id"]
    lines.append(f"    {top_id}[\"{tree['top'].get('label', top_id)}\"]")
    for i, rule in enumerate(tree["rules"]):
        rid = f"R{i}"
        lines.append(f"    {rid}{{\"{rule['rule_id']} ({rule.get('gate', 'AND')}"
                     f"）\"}}")
        lines.append(f"    {top_id} --> {rid}")
        for fp in rule["fingerprints"]:
            fid = "F_" + "".join(ch if ch.isalnum() else "_"
                                 for ch in fp)
            lines.append(f"    {rid} --> {fid}[\"{fp}\"]")
    return ok_envelope(source=_SOURCE, mermaid="\n".join(lines), n_lines=len(lines))
