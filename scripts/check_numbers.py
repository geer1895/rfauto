#!/usr/bin/env python3
"""Number self-check: assert README numbers match code reality.

公开仓口径：README（英文/中文）声称的统计数字必须与代码实测一致，
文档不沿用上一份的旧数字。三个来源全部可在 CI（无本地产物）复现：
- tests：pytest --collect-only 的收集数（唯一在 CI 可用的确定性来源；
  本仓不带 runs/ 历史门日志，故不用日志口径）。
- CLI：typer 实注册叶子命令数（递归 walk typer 内嵌 vendored click 的
  TyperGroup，鸭子判别 hasattr(commands)，不按 isinstance 漏判）。
- MCP：`^@mcp.tool` 正则口径（mcp_server facade + mcp_tools/ 全集）；
  resources 数双口径核对（list_resources() 注册面 vs `@mcp.resource` 正则）。
- 文档头部核对模式 0 匹配 = 文档格式漂移，直接判红（门不得空转）。
- .venv/Scripts/rfauto-mcp.exe 安装态断言仅在本地 .venv 存在时执行
  （CI 临时环境没有仓库根 .venv，跳过不判红）。
"""

import argparse
import difflib
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs"
MCP_ENTRY_EXE = REPO_ROOT / ".venv" / "Scripts" / "rfauto-mcp.exe"

# EP-2 trace 审计输入面（specs §C-7）
TRACE_MATRIX_PATH = REPO_ROOT / "knowledge" / "trace_matrix.yaml"
TRACE_INDEX_PATH = REPO_ROOT / "knowledge" / "criteria" / "index.yaml"
TRACE_ANCHORS_PATH = REPO_ROOT / "knowledge" / "anchors.yaml"
TRACE_TESTS_CACHE_PATH = REPO_ROOT / "runs" / "ep2" / "test_universe.txt"
TRACE_FIRST_BATCH_FLOORS = {"gate_min_pct": 80.0, "param_min_pct": 60.0}
TRACE_DANGLING_SUGGESTIONS = 3  # 编辑距离 top-3

# tests 徽章为下限式（collect 数随平台/环境小幅浮动，断言 >= 而非 ==）
MIN_TESTS = 21900

# 全量门日志 glob（runs/ 门日志口径判别）：定向门（wf_gate_<task>.log /
# gate_baseline_fix-*.log 任务后缀族）不得入选全量计数。
FULL_GATE_LOG_GLOBS = ("*gate*full*.log", "gate_baseline_2*.log")

# 文档头部核对模式：(正则, label)。期望值不在此绑定——main() 按 label 从
# 实测注入。0 匹配 = 判红（模式必须实际咬合文档）。
# README.md（英文）与 README.zh-CN.md（中文）共用同一组 badge/数字版式。
DOC_PATTERNS: dict[str, list[tuple[str, str]]] = {
    # README.md（英文）与 README.zh-CN.md（中文）共用同一组 badge/数字版式；
    # 数字锚块（numbers-start/end 注释之间）由实测注入，勿手改。
    "README.md": [
        (r"badge/tests-(\d+)", "tests_min"),
        # resources 用捕获组（硬编码字面量会让 README 漂移时门恒绿=结构性失明）
        (r"[（(](\d+) 个工具 \+ (\d+) 个 resources[）)]", "mcp"),
        (r"CLI 命令 (\d+)（叶子）", "cli_leaf"),
        (r"(\d+) parameterized device templates", "templates"),
        (r"CALCULATOR_REGISTRY (\d+)", "calc_registry"),
        (r"TEMPLATE_META (\d+)", "template_meta"),
        (r"EXPECTED_TEMPLATES (\d+)", "expected_templates"),
        (r"ANCHORS (\d+)", "anchors"),
    ],
    "README.zh-CN.md": [
        (r"badge/tests-(\d+)", "tests_min"),
        (r"[（(](\d+) 个工具 \+ (\d+) 个 resources[）)]", "mcp"),
        (r"CLI 命令 (\d+)（叶子）", "cli_leaf"),
        (r"(\d+) 个参数化器件模板", "templates"),
        (r"CALCULATOR_REGISTRY (\d+)", "calc_registry"),
        (r"TEMPLATE_META (\d+)", "template_meta"),
        (r"EXPECTED_TEMPLATES (\d+)", "expected_templates"),
        (r"ANCHORS (\d+)", "anchors"),
    ],
}

def count_tests() -> tuple[int, str]:
    """测试收集数（pytest --collect-only；CI 与本地同一确定性来源）。"""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-q", "--co", "--no-header"],
        capture_output=True, text=True, timeout=600, cwd=REPO_ROOT,
    )
    m = re.search(r"(\d+) tests collected", r.stdout)
    n = int(m.group(1)) if m else 0
    return n, "pytest --collect-only"


def _count_group_leaves(group) -> int:
    """递归数一个 click Group 下注册的叶子命令数。

    typer 内嵌的是 vendored click（typer._click），子应用组是 TyperGroup——
    对 standalone click.Group 做 isinstance 会全部漏判，
    以 hasattr(commands) 鸭子判别。"""
    total = 0
    for sub in group.commands.values():
        total += _count_group_leaves(sub) if hasattr(sub, "commands") else 1
    return total


def cli_leaf_counts() -> dict[str, int]:
    """顶层入口（含各 add_typer 子应用）各自辖下的叶子命令数。

    局部导入：保持脚本轻量，且避免 import 副作用早于参数检查。"""
    from typer.main import get_command

    from rfauto.cli.main import app

    cmd = get_command(app)
    if not hasattr(cmd, "commands"):
        return {}
    counts: dict[str, int] = {}
    for name, sub in cmd.commands.items():
        counts[name] = _count_group_leaves(sub) if hasattr(sub, "commands") else 1
    return counts


def count_cli() -> int:
    """实注册叶子命令总数。"""
    return sum(cli_leaf_counts().values())


def mcp_source_files() -> list[Path]:
    """MCP 源码文件集：facade + mcp_tools/ 工具组包（rglob 递归口径——
    mcp_tools 将来出子包时非递归 glob 会静默漏扫 MCP 计数）。"""
    base = REPO_ROOT / "src" / "rfauto"
    return [base / "mcp_server.py", *sorted((base / "mcp_tools").rglob("*.py"))]


def count_mcp() -> int:
    """MCP 工具数：`^@mcp.tool` 装饰器行正则（facade + mcp_tools/ 全集）。"""
    n = 0
    for f in mcp_source_files():
        n += len(re.findall(r"^@mcp\.tool", f.read_text(encoding="utf-8"),
                            re.MULTILINE))
    return n


def count_mcp_resources_regex() -> int:
    """MCP resources 源码面计数：`@mcp.resource` 装饰器行正则（回退口径）。"""
    n = 0
    for f in mcp_source_files():
        n += len(re.findall(r"^@mcp\.resource", f.read_text(encoding="utf-8"),
                            re.MULTILINE))
    return n


def count_mcp_resources() -> tuple[int, str]:
    """MCP resources 实注册数（主口径=list_resources()，失败回退正则）。

    Returns:
        (n, source_desc)：n=resources 数，source_desc=计数来源描述。
    """
    try:
        import asyncio

        from rfauto.mcp_server import mcp as mcp_server

        n = len(asyncio.run(mcp_server.list_resources()))
        return n, "list_resources()"
    except Exception as exc:  # 注册面不可达（import 失败/环境残缺）→ 正则回退
        return (count_mcp_resources_regex(),
                f"@mcp.resource regex fallback ({type(exc).__name__})")


def check_mcp_resources_vs_source() -> str | None:
    """resources 双口径核对：注册面 list_resources() vs 装饰器正则。

    一致 → None；注册面不可达（正则回退属合法降级）→ None；
    两口径数目分歧 → 失败描述。"""
    try:
        import asyncio

        from rfauto.mcp_server import mcp as mcp_server

        n_registry = len(asyncio.run(mcp_server.list_resources()))
    except Exception:
        return None
    n_regex = count_mcp_resources_regex()
    if n_registry != n_regex:
        return (f"MCP resources 口径分歧: list_resources()={n_registry} != "
                f"@mcp.resource regex={n_regex}（双口径必核对——注册面与"
                "源码面漂移，新增/删除 resource 未落另一面）")
    return None


def count_calculators() -> int:
    """CALCULATOR_REGISTRY 实注册键数（names() 缺省不含 experimental 键）。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    return len(CALCULATOR_REGISTRY.names())

def count_calculators_all() -> int:
    """CALCULATOR_REGISTRY 全键数（含实验键）。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    return len(CALCULATOR_REGISTRY.names(include_experimental=True))


def count_template_meta() -> int:
    """TEMPLATE_META 实条目数（openems_templates 单源）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META

    return len(TEMPLATE_META)


def count_expected_templates() -> int:
    """EXPECTED_TEMPLATES 条目数（test_template_geometry_audit.py 冻结集合
    字面量 regex 实测；格式漂移得 0 → 与文档比对必红，门不空转）。"""
    src = (REPO_ROOT / "tests" / "unit" / "test_template_geometry_audit.py"
           ).read_text(encoding="utf-8")
    m = re.search(r"EXPECTED_TEMPLATES = frozenset\(\{(.*?)\}\)", src, re.S)
    return len(re.findall(r'"([^"]+)"', m.group(1))) if m else 0


def count_templates() -> int:
    """参数化器件模板数（docs/templates/*/meta.yaml 目录数）。"""
    root = REPO_ROOT / "docs" / "templates"
    return sum(1 for p in root.iterdir() if p.is_dir()) if root.is_dir() else 0


def count_anchors() -> int:
    """锚注册表条目实数（knowledge/anchors.yaml 顶层 anchors 列表 raw 长度）。

    raw 口径（不进 AnchorSet 构造）：单锚 schema 坏被构造层丢进 load_errors
    时不该在计数面静默蒸发——raw 计数与 core 单源不一致即判红，让坏锚现形
    而不是被"合法丢弃"吞掉（#231 注册表消费者纪律）。"""
    data = yaml.safe_load(
        (REPO_ROOT / "knowledge" / "anchors.yaml").read_text(encoding="utf-8")
    ) or {}
    anchors = data.get("anchors") if isinstance(data, dict) else None
    return len(anchors) if isinstance(anchors, list) else 0


def check_anchors_vs_core() -> str | None:
    """绑锚双向核对：yaml raw 条数 vs core EXPECTED_ANCHOR_COUNT 单源。

    一致 → None；不一致 → 失败描述（main() 收进 failures 判红）。"""
    from rfauto.core.anchors import EXPECTED_ANCHOR_COUNT

    n_yaml = count_anchors()
    if n_yaml != EXPECTED_ANCHOR_COUNT:
        return (f"anchors: knowledge/anchors.yaml 条数 {n_yaml} != "
                f"core/anchors.py EXPECTED_ANCHOR_COUNT "
                f"{EXPECTED_ANCHOR_COUNT}（#231 单源同步，双向必核对）")
    return None


def mcp_entry_missing_message(exe: Path = MCP_ENTRY_EXE) -> str | None:
    """安装态断言：仅当本地 .venv 存在时检查 console script exe；
    CI 临时环境没有仓库根 .venv，返回 None 跳过。"""
    if exe == MCP_ENTRY_EXE and not (REPO_ROOT / ".venv").is_dir():
        return None
    if exe.exists():
        return None
    return (
        f"MCP entry script missing: {exe} "
        f"(fix: {REPO_ROOT / '.venv' / 'Scripts' / 'python.exe'} -m pip install "
        f"-e . --no-deps to regenerate [project.scripts] entry points)"
    )


def read_head(name: str, limit: int = 60) -> str:
    p = REPO_ROOT / name
    if not p.exists():
        return ""
    return "\n".join(p.read_text(encoding="utf-8").splitlines()[:limit])


def check_doc(
    name: str,
    patterns: list[tuple[str, str]],
    expected: dict[str, tuple[int, ...]],
    failures: list[str],
) -> None:
    text = read_head(name)
    if not text:
        failures.append(f"{name}: header unreadable/missing")
        return
    for pat, label in patterns:
        exp = expected.get(label)
        if exp is None:
            failures.append(f"{name}: no expected binding for label {label!r}")
            continue
        hits = [tuple(int(g) for g in m.groups()) for m in re.finditer(pat, text)]
        if not hits:
            failures.append(
                f"{name}: pattern 0 匹配（文档格式漂移，门空转）: {label} ({pat})")
            continue
        for got in hits:
            if got != exp:
                failures.append(f"{name}: {label}={got}, actual {exp} ({pat})")


# ── EP-2 trace 子命令：四向追溯矩阵审计（specs §C-7）────────────────────────


def criteria_id_of(rel_path: str) -> str:
    """runs 相对路径 → criteria_id（"a/b/criteria.md" → "a_b"）。

    与 criteria_index_build.criteria_id_of 同口径（两脚本各自独立实现，
    scripts 层零交叉 import——test_check_numbers 按 spec 装载本模块时不带
    scripts 目录入 sys.path）。"""
    rel = rel_path.replace("\\", "/")
    if rel.endswith("criteria.md"):
        rel = rel[: -len("criteria.md")]
    rel = rel.strip("/")
    return rel.replace("/", "_") if rel else "criteria"


def trace_gate_universe(index_doc: dict) -> dict[str, int]:
    """gate 全集：{gate_id: 门行数序号}（index migrate_to_v2 条目 1..n_gates）。"""
    universe: dict[str, int] = {}
    for entry in index_doc.get("entries", []):
        if entry.get("status") != "migrate_to_v2":
            continue
        cid = criteria_id_of(entry.get("path", ""))
        for seq in range(1, int(entry.get("n_gates", 0)) + 1):
            universe[f"{cid}#{seq}"] = seq
    return universe


def collect_test_modules(tests_dir: str | Path | None = None,
                         timeout: int = 600) -> list[str]:
    """只读 collect：pytest --collect-only 取 nodeid 的模块路径集（零执行）。"""
    td = Path(tests_dir) if tests_dir else REPO_ROOT / "tests" / "unit"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(td), "-q", "--collect-only",
         "--no-header"],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT))
    mods: set[str] = set()
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if "::" in ln and ln.startswith("tests"):
            mods.add(ln.split("::")[0])
    return sorted(mods)


def read_tests_cache(path: str | Path) -> list[str]:
    return [ln.strip()
            for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def trace_audit(matrix: dict, index_doc: dict, calc_names: list[str] | tuple,
                anchor_ids: list[str] | tuple,
                test_modules: list[str] | tuple) -> dict:
    """四向审计：coverage_pct / by_dim / dangling(编辑距离 top-3) / status。

    - 覆盖面口径：gate=全集门中 ≥1 link 者；param/test/anchor=该门 ≥1 link
      且对应键在各自注册域内可解析者（dangling 键不计入覆盖）；
    - dangling：link 任一键指向域外 → 记录 + 该域编辑距离 top-3 建议；
    - status：覆盖率过棘轮 floor 且零断链 → PASS，否则 FAIL（fail-closed）。"""
    universe = trace_gate_universe(index_doc)
    n_univ = len(universe)
    covered = {"gate": set(), "param": set(), "test": set(), "anchor": set()}
    dangling: list[dict] = []
    universe_ids = list(universe)
    for link in matrix.get("links", []):
        if not isinstance(link, dict):
            dangling.append({"gate_id": None, "field": "link", "value": repr(link),
                             "suggestions": []})
            continue
        gid = link.get("gate_id")
        if gid in universe:
            covered["gate"].add(gid)
        else:
            dangling.append({
                "gate_id": gid, "field": "gate_id", "value": gid,
                "suggestions": difflib.get_close_matches(
                    str(gid), universe_ids, n=TRACE_DANGLING_SUGGESTIONS)})
        pk = link.get("param_key")
        if pk is not None:
            if pk in calc_names:
                covered["param"].add(gid)
            else:
                dangling.append({
                    "gate_id": gid, "field": "param_key", "value": pk,
                    "suggestions": difflib.get_close_matches(
                        str(pk), list(calc_names), n=TRACE_DANGLING_SUGGESTIONS)})
        tid = link.get("test_id")
        if tid is not None:
            if tid in test_modules:
                covered["test"].add(gid)
            else:
                dangling.append({
                    "gate_id": gid, "field": "test_id", "value": tid,
                    "suggestions": difflib.get_close_matches(
                        str(tid), list(test_modules), n=TRACE_DANGLING_SUGGESTIONS)})
        aid = link.get("anchor_id")
        if aid is not None:
            if aid in anchor_ids:
                covered["anchor"].add(gid)
            else:
                dangling.append({
                    "gate_id": gid, "field": "anchor_id", "value": aid,
                    "suggestions": difflib.get_close_matches(
                        str(aid), list(anchor_ids), n=TRACE_DANGLING_SUGGESTIONS)})

    def _pct(n: int) -> float:
        return round(100.0 * n / n_univ, 2) if n_univ else 0.0

    by_dim = {dim: {"n": len(ids), "pct": _pct(len(ids))}
              for dim, ids in covered.items()}
    ratchet = matrix.get("ratchet") or {}
    floor_gate = float(ratchet.get(
        "gate_min_pct", TRACE_FIRST_BATCH_FLOORS["gate_min_pct"]))
    floor_param = float(ratchet.get(
        "param_min_pct", TRACE_FIRST_BATCH_FLOORS["param_min_pct"]))
    coverage_pct = by_dim["gate"]["pct"]
    param_pct = by_dim["param"]["pct"]
    reasons: list[str] = []
    if coverage_pct < floor_gate:
        reasons.append(f"gate 覆盖 {coverage_pct}% < 棘轮 floor {floor_gate}%")
    if param_pct < floor_param:
        reasons.append(f"param 覆盖 {param_pct}% < 棘轮 floor {floor_param}%")
    if dangling:
        reasons.append(f"断链 {len(dangling)} 条（键指向域外，见 dangling）")
    status = "PASS" if not reasons else "FAIL"
    return {
        "coverage_pct": coverage_pct,
        "by_dim": by_dim,
        "dangling": dangling,
        "status": status,
        "ratchet": {"gate_min_pct": floor_gate, "param_min_pct": floor_param},
        "universe": {"n_gates": n_univ, "n_links": len(matrix.get("links", [])),
                     "n_mechanical": sum(
                         1 for lk in matrix.get("links", [])
                         if isinstance(lk, dict) and lk.get("strength") == "mechanical")},
        "reasons": reasons,
    }


def update_ratchet(matrix: dict, audit: dict) -> tuple[dict, list[str]]:
    """棘轮只升不降：floor 取 max(既有 floor, 当前覆盖)；返回 (新矩阵, 变更说明)。"""
    ratchet = dict(matrix.get("ratchet") or {})
    notes: list[str] = []
    for key, cur in (("gate_min_pct", audit["coverage_pct"]),
                     ("param_min_pct", audit["by_dim"]["param"]["pct"])):
        old = float(ratchet.get(key, TRACE_FIRST_BATCH_FLOORS[key]))
        new = max(old, float(cur))
        if new > old:
            ratchet[key] = new
            notes.append(f"{key}: {old} -> {new}（棘轮上抬）")
        else:
            notes.append(f"{key}: {old} 保持（当前 {cur} 未超既有 floor，棘轮不降）")
    out = dict(matrix)
    out["ratchet"] = ratchet
    return out, notes


def cmd_trace(args: argparse.Namespace) -> int:
    matrix_path = Path(args.matrix)
    if not matrix_path.is_file():
        print(f"trace matrix 缺失: {matrix_path}（EP-2 产物；生成="
              f"python scripts/criteria_index_build.py --migrate-v2）")
        return 2
    index_path = Path(args.index)
    if not index_path.is_file():
        print(f"criteria index 缺失: {index_path}")
        return 2
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8")) or {}
    index_doc = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    anchors_doc = yaml.safe_load(
        Path(args.anchors).read_text(encoding="utf-8")) or {}
    anchor_ids = [a.get("anchor_id") for a in (anchors_doc.get("anchors") or [])
                  if isinstance(a, dict) and a.get("anchor_id")]
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    calc_names = list(CALCULATOR_REGISTRY.names(include_experimental=True))
    cache = Path(args.tests_cache)
    if cache.is_file():
        test_modules = read_tests_cache(cache)
        tests_source = f"cache:{cache}"
    else:
        test_modules = collect_test_modules()
        tests_source = "pytest --collect-only (只读)"
    audit = trace_audit(matrix, index_doc, calc_names, anchor_ids, test_modules)
    audit["tests_source"] = tests_source

    if args.update_ratchet:
        new_matrix, notes = update_ratchet(matrix, audit)
        matrix_path.write_text(
            yaml.safe_dump(new_matrix, allow_unicode=True, sort_keys=False,
                           default_flow_style=None, width=100),
            encoding="utf-8")
        for n in notes:
            print(f"ratchet: {n}")

    if args.json:
        import json

        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        bd = audit["by_dim"]
        print(f"trace: coverage_pct={audit['coverage_pct']} "
              f"status={audit['status']} "
              f"(gate {bd['gate']['n']}/{audit['universe']['n_gates']}, "
              f"param {bd['param']['pct']}%, test {bd['test']['pct']}%, "
              f"anchor {bd['anchor']['pct']}%; links="
              f"{audit['universe']['n_links']} mechanical="
              f"{audit['universe']['n_mechanical']}; tests_source="
              f"{tests_source})")
        if audit["dangling"]:
            print(f"dangling（前 {min(len(audit['dangling']), 10)} 条，每键"
                  f"编辑距离 top-{TRACE_DANGLING_SUGGESTIONS}）：")
            for d in audit["dangling"][:10]:
                print(f"  {d['gate_id']} {d['field']}={d['value']!r} -> "
                      f"{d['suggestions']}")
        for r in audit["reasons"]:
            print(f"  FAIL 原因: {r}")
    return 0 if audit["status"] == "PASS" else 1


def _number_gate() -> int:
    cli_total = count_cli()
    tc, tsrc = count_tests()
    mc = count_mcp()
    rc, rsrc = count_mcp_resources()
    tpl = count_templates()
    ac = count_anchors()
    calc = count_calculators()
    tmeta = count_template_meta()
    etpl = count_expected_templates()
    print(f"Actual: tests={tc} (source: {tsrc}), CLI={cli_total}, "
          f"MCP={mc}+{rc}res (source: {rsrc}), templates={tpl}, ANCHORS={ac}, "
          f"CALC={calc}, TEMPLATE_META={tmeta}, EXPECTED_TEMPLATES={etpl}")
    failures: list[str] = []

    # 锚注册表双向核对（yaml 数据面 vs core 单源，不一致判红）
    anchors_mismatch = check_anchors_vs_core()
    if anchors_mismatch:
        failures.append(anchors_mismatch)

    # resources 双口径核对（注册面 list_resources() vs 装饰器正则）
    res_mismatch = check_mcp_resources_vs_source()
    if res_mismatch:
        failures.append(res_mismatch)

    expected = {
        "mcp": (mc, rc),
        "cli_leaf": (cli_total,),
        "templates": (tpl,),
        "calc_registry": (calc,),
        # （含实验键形态由 README 载体行决定；公开版单数口径）
        "template_meta": (tmeta,),
        "expected_templates": (etpl,),
        "anchors": (ac,),
    }
    # tests 徽章=下限承诺（>= MIN_TESTS，跨平台 collect 数有浮动）；其余精确
    for name, patterns in DOC_PATTERNS.items():
        text = read_head(name)
        if not text:
            failures.append(f"{name}: header unreadable/missing")
            continue
        m = re.search(r"badge/tests-(\d+)", text)
        if not m:
            failures.append(f"{name}: tests badge 缺失")
            continue
        if int(m.group(1)) < MIN_TESTS:
            failures.append(f"{name}: tests badge {m.group(1)} < {MIN_TESTS}")
        check_doc(name, [p for p in patterns if p[1] != "tests_min"],
                  expected, failures)

    missing = mcp_entry_missing_message()
    if missing:
        failures.append(missing)
    else:
        print(f"MCP entry: {MCP_ENTRY_EXE.name} OK")

    if failures:
        print("MISMATCH:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("All numbers consistent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="数字自检门（无子命令=文档数字核对）+ EP-2 trace 审计")
    sub = parser.add_subparsers(dest="command")
    p_trace = sub.add_parser(
        "trace", help="EP-2 四向追溯矩阵审计（specs §C-7）")
    p_trace.add_argument("--matrix", default=str(TRACE_MATRIX_PATH))
    p_trace.add_argument("--index", default=str(TRACE_INDEX_PATH))
    p_trace.add_argument("--anchors", default=str(TRACE_ANCHORS_PATH))
    p_trace.add_argument("--tests-cache", default=str(TRACE_TESTS_CACHE_PATH),
                         help="nodeid 模块路径缓存（缺失则只读 collect）")
    p_trace.add_argument("--json", action="store_true", help="JSON 输出")
    p_trace.add_argument("--update-ratchet", action="store_true",
                         help="覆盖率过 floor 时上抬棘轮（只升不降）")
    args = parser.parse_args(argv)
    if args.command == "trace":
        return cmd_trace(args)
    return _number_gate()


if __name__ == "__main__":
    sys.exit(main())
