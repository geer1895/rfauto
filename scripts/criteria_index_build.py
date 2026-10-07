"""criteria_index_build：历史 runs/**/criteria.md 批量抽取 → knowledge/criteria/index.yaml。

DP-13 Z1（specs §13.4）。只读登记：runs/ 零改写（#325/#326 历史零改写），
产物只落 knowledge/criteria/index.yaml（本脚本 --out 写点）。schema 落点=
DP-12 criteria/v2，本工具不另立 schema——index 只是"历史判据清单"的
只读登记，status 双态标迁移资格：

- ``migrate_to_v2``：≥1 行被门阈值 regex 抽中（含结构化判据，迁移候选）；
- ``legacy_only``：0 行（纯散文人工判读，不迁移）。

无静默漏抽：单测断言 index 行数==rglob 扫描文件数
（tests/unit/test_criteria_index_build.py）。输出确定性：同树重跑逐字节
一致（无时间戳键）。

门阈值行 regex（预声明 runs/df6_dp13/criteria.md §Z1）：行含比较符
(≤|≥|<|>) 且含单位词（dB/GHz/%/mm/ns/µm/um/数字+s 秒）之一，或含
``±数值`` 门；逐行抽原文 raw + 比较符后首个数值 threshold（best-effort，
行数如实，不凑全）。

EP-2 四向追溯矩阵（specs §C-7，--migrate-v2 模式）：
- 三档机械化迁移：A 档（index 已抽 threshold）→模板生成 v2 骨架
  （u_val 缺省 none_declared 不虚构）；B 档（raw 表格行）→extract_gate_
  lines 表格解析（name/op/unit/observed 结构化字段，匹配集不变=368 行
  登记稳定）；C 档（纯叙述 legacy_only）→维持不迁移。迁移=附加不替代
  （md 零改写 #325/#326）；既有人工 curated v2（knowledge/criteria/v2/
  顶层 *.yaml）按 provenance.referee_run/gate_db_legacy 识别并跳过骨架
  （零改写逐位）。
- 四向键：gate_id=<criteria_id>#<门序号> / param_key=CALCULATOR 键空间 /
  test_id=pytest nodeid 模块路径（只读 collect）/ anchor_id=锚注册表键；
  载体 knowledge/trace_matrix.yaml{links:[{gate_id,param_key,test_id,
  anchor_id,strength}]}，strength 恒=mechanical（语义误抽风险→人工复核
  清单由 scripts/check_numbers.py trace 审计输出，绝不冒充 declared）。
- 覆盖率棘轮：首批 gate≥80%/param≥60%，update 只取 max（只升不降），
  重生成保留既有更高 floor。
- 审计 CLI=scripts/check_numbers.py trace（coverage_pct/by_dim/dangling
  编辑距离 top-3/status），本脚本只产不审。

用法：
    python scripts/criteria_index_build.py --runs-root runs --out knowledge/criteria/index.yaml
    python scripts/criteria_index_build.py --migrate-v2 --quiet
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

INDEX_SCHEMA = "rfauto-criteria-index-v1"
TRACE_SCHEMA = "trace-matrix/v1"
SKELETON_SCHEMA = "criteria/v2"

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = REPO_ROOT / "knowledge" / "criteria" / "index.yaml"
DEFAULT_V2_DIR = REPO_ROOT / "knowledge" / "criteria" / "v2"
DEFAULT_SKELETON_DIR = DEFAULT_V2_DIR / "skeleton"
DEFAULT_TRACE_OUT = REPO_ROOT / "knowledge" / "trace_matrix.yaml"
DEFAULT_TESTS_CACHE = REPO_ROOT / "runs" / "ep2" / "test_universe.txt"

# 覆盖率棘轮首批 floor（specs §C-7：gate≥80%/param≥60%，只升不降）
FIRST_BATCH_FLOORS = {"gate_min_pct": 80.0, "param_min_pct": 60.0}

# 比较符（含 Unicode ≤ ≥）与单位词；\ds\b 按预声明 "s\b" 的秒语义实现为
# "数字+s"（裸 s\b 会把英文复数词尾全吞进来，属实现保真而非改口径）。
_OPERATOR_RE = re.compile(r"[≤≥<>]")
_UNIT_RE = re.compile(r"dB|GHz|%|mm|ns|µm|um|\ds\b")
_PLUS_MINUS_RE = re.compile(r"±\s*\d")
_NUMBER_AFTER_OP_RE = re.compile(r"[≤≥<>]\s*-?(\d+(?:\.\d+)?)")
_NUMBER_AFTER_PM_RE = re.compile(r"±\s*(\d+(?:\.\d+)?)")
_UNIT_AFTER_OP_RE = re.compile(r"\s*(dB|GHz|%|mm|ns|µm|um|s\b)")
# B 档表格解析：单元格切分按未转义竖线（raw 里的 \|b₈\| 转义竖线不切）；
# token 匹配一律词边界（全字母数字邻接不咬合，防 "via"⊂"deviation"、
# "cpw"⊂"mcp_wp33" 类子串假阳性——实测后者正是真误报）。
_TABLE_SPLIT_RE = re.compile(r"(?<!\\)\|")
_TABLE_SEP_CELL_RE = re.compile(r":?-{2,}:?")


def _tok_re(tok: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])")


def parse_table_row(line: str) -> list[str] | None:
    """B 档：markdown 表格数据行 → 单元格列表；非表格行/分隔行 → None。

    匹配面零扩张：本函数只对已被门阈值 regex 抽中的行做结构化，不新增
    抽中行（368 行登记稳定的实现保证）。"""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and len(s) >= 2):
        return None
    cells = [c.strip() for c in _TABLE_SPLIT_RE.split(s[1:-1])]
    if not cells:
        return None
    if all(_TABLE_SEP_CELL_RE.fullmatch(c) for c in cells if c) and any(c for c in cells):
        return None  # |---|---| 分隔行
    if len(cells) < 2 or not cells[0]:
        return None
    return cells


def extract_gate_lines(text: str) -> list[dict[str, Any]]:
    """从 criteria.md 文本抽取门阈值行（best-effort，逐行原文+阈值）。

    B 档扩展（EP-2 C-7）：表格行附加 ``table`` 结构化键
    {name, op, unit, observed}——name=首列门名、op/unit=与 threshold 同源
    匹配位的比较符/单位、observed=门限列之后的可解析实测值。匹配集与
    threshold 语义不变（既有 368 行登记稳定的实现保证）。"""
    gates: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        is_gate = (
            bool(_OPERATOR_RE.search(line)) and bool(_UNIT_RE.search(line))
        ) or bool(_PLUS_MINUS_RE.search(line))
        if not is_gate:
            continue
        m_op = _NUMBER_AFTER_OP_RE.search(line)
        m_pm = _NUMBER_AFTER_PM_RE.search(line)
        m = m_op or m_pm
        entry: dict[str, Any] = {
            "raw": line,
            "threshold": float(m.group(1)) if m else None,
        }
        cells = parse_table_row(line)
        if cells is not None:
            op: str | None = None
            unit: str | None = None
            observed: list[float] = []
            gate_cell_idx: int | None = None
            if m_op is not None:
                op = line[m_op.start()]
                m_unit = _UNIT_AFTER_OP_RE.match(line, m_op.end())
                unit = m_unit.group(1) if m_unit else None
            elif m_pm is not None:
                m_unit = _UNIT_AFTER_OP_RE.match(line, m_pm.end())
                unit = m_unit.group(1) if m_unit else None
            for i, cell in enumerate(cells):
                if _NUMBER_AFTER_OP_RE.search(cell) or _NUMBER_AFTER_PM_RE.search(cell):
                    gate_cell_idx = i
                    break
            if gate_cell_idx is not None:
                for cell in cells[gate_cell_idx + 1:]:
                    try:
                        observed.append(float(cell))
                    except ValueError:
                        continue
            entry["table"] = {
                "name": cells[0],
                "op": op,
                "unit": unit,
                "observed": observed,
            }
        gates.append(entry)
    return gates


# ── EP-2 C-7 机械链接器（四向键候选）─────────────────────────────────────
# 全部为确定性声明表；语义误抽风险由 strength=mechanical + 人工复核清单
# 承担（specs §C-7 风险条），绝不冒充 declared。
# 战役别名（战役代号 → 模板族）证据：
#   c3 → combline/interdigital/sir_bpf = knowledge/anchors.yaml c3.* 锚的
#        template_family 注册值（注册表面，非臆测）；
#   c4 → lange/cline_coupler/branchline = c4_z_substrate 门行 lange/
#        cline_coupler 字面 + c4 批=耦合器网格收敛批；
#   marchand → marchand_balun = 族名前缀（marchand_* 战役系列）。
FAMILY_ALIAS: dict[str, tuple[str, ...]] = {
    "marchand": ("marchand_balun",),
    "c3": ("combline", "interdigital", "sir_bpf"),
    "c4": ("lange", "cline_coupler", "branchline"),
}
# 耦合谐振器滤波器族 → coupling_matrix_* CALCULATOR 组（c3 族=耦合矩阵
# 滤波器，core/calculators coupling_matrix_* 的直接服务对象）。
FILTER_FAMILIES: tuple[str, ...] = (
    "combline", "interdigital", "sir_bpf", "hairpin", "hairpin_alt",
    "coupled_bpf", "coupled_line",
)
# 族名子串桥覆盖不到的显式桥：mline 模板=微带线基准档，几何参数经
# microstrip_synthesis/analysis 综合与分析（HJ 线宽综合同源口径）。
FAMILY_CALC_BRIDGE: dict[str, tuple[str, ...]] = {
    "mline": ("microstrip_analysis", "microstrip_synthesis"),
}
# 每门最多产出的分维候选数（链路数上限；不影响覆盖面，只控矩阵规模）
MAX_PARAMS_PER_GATE = 2
MAX_TESTS_PER_GATE = 2
MAX_ANCHORS_PER_GATE = 2


def _template_families() -> tuple[str, ...]:
    from rfauto.adapters.openems_templates import TEMPLATE_META

    return tuple(sorted(TEMPLATE_META))


def _calc_names() -> tuple[str, ...]:
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    return tuple(sorted(CALCULATOR_REGISTRY.names(include_experimental=True)))


def _anchor_pairs(anchors_path: str | Path = REPO_ROOT / "knowledge" / "anchors.yaml"
                  ) -> list[tuple[str, list[str]]]:
    data = yaml.safe_load(Path(anchors_path).read_text(encoding="utf-8")) or {}
    anchors = data.get("anchors") if isinstance(data, dict) else None
    pairs: list[tuple[str, list[str]]] = []
    for a in anchors or []:
        if isinstance(a, dict) and a.get("anchor_id"):
            pairs.append((a["anchor_id"], list(a.get("template_family") or [])))
    return pairs


def family_tokens_for(text: str,
                      families: tuple[str, ...] | None = None) -> set[str]:
    """路径/标题/门行原文 → 模板族 token 集（词边界匹配 + 战役别名）。"""
    low = text.lower()
    fams = families if families is not None else _template_families()
    out = {f for f in fams if _tok_re(f).search(low)}
    for tok, fs in FAMILY_ALIAS.items():
        if _tok_re(tok).search(low):
            out.update(fs)
    return out


def calc_candidates(fams: set[str], calc_names: tuple[str, ...] | None = None
                    ) -> list[str]:
    names = calc_names if calc_names is not None else _calc_names()
    out: set[str] = set()
    for f in fams:
        rex = _tok_re(f)
        out.update(c for c in names if rex.search(c))
    for f, cs in FAMILY_CALC_BRIDGE.items():
        if f in fams:
            out.update(cs)
    if fams & set(FILTER_FAMILIES):
        out.update(c for c in names if c.startswith("coupling_matrix"))
    return sorted(out)


def test_candidates(fams: set[str], test_modules: tuple[str, ...] | list[str]
                    ) -> list[str]:
    return sorted(m for m in test_modules
                  for f in fams if _tok_re(f).search(Path(m).stem))


def anchor_candidates(fams: set[str],
                      anchor_pairs: list[tuple[str, list[str]]]) -> list[str]:
    return sorted(a for a, fams2 in anchor_pairs if fams & set(fams2))


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


def _git_head() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=30,
                           cwd=str(REPO_ROOT))
        return r.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _title_of(text: str, fallback: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            return line[2:].strip()
        if line:  # 无标题时取首个非空行
            return line
    return fallback


def build_index(runs_root: str | Path) -> dict[str, Any]:
    """扫 runs_root 下全部 criteria.md（rglob），构建只读 index 文档。"""
    root = Path(runs_root)
    if not root.is_dir():
        return {"ok": False, "errors": [f"runs 根不存在: {root}"]}
    files = sorted(
        (p for p in root.rglob("criteria.md") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    entries: list[dict[str, Any]] = []
    n_gate_rows = 0
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(root).as_posix()
        gates = extract_gate_lines(text)
        n_gate_rows += len(gates)
        entries.append({
            "path": rel,
            "title": _title_of(text, rel),
            "status": "migrate_to_v2" if gates else "legacy_only",
            "n_gates": len(gates),
            "gates": gates,
        })
    return {
        "ok": True,
        "schema": INDEX_SCHEMA,
        "runs_root": root.as_posix(),
        "n_files": len(files),
        "n_gate_rows": n_gate_rows,
        "entries": entries,
    }


def _dump_yaml(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                          default_flow_style=None, width=100)


def write_index(index: dict[str, Any], out_path: str | Path) -> Path:
    """index 文档落盘（确定性：sort_keys + 固定缩进，无时间戳键）。"""
    payload = {k: v for k, v in index.items() if k != "ok"}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_dump_yaml(payload), encoding="utf-8")
    return out


# ── EP-2：三档迁移 + 四向追溯矩阵生成 ─────────────────────────────────────


def criteria_id_of(rel_path: str) -> str:
    """runs 相对路径 → criteria_id（"a/b/criteria.md" → "a_b"）。"""
    rel = rel_path.replace("\\", "/")
    if rel.endswith("criteria.md"):
        rel = rel[: -len("criteria.md")]
    rel = rel.strip("/")
    return rel.replace("/", "_") if rel else "criteria"


def curated_v2_run_keys(v2_dir: str | Path) -> list[str]:
    """人工 curated v2（顶层 *.yaml）的裁判 run 识别串（referee_run +
    gate_db_legacy 拼接）——骨架跳过依据，curated 文件本身零改写。"""
    keys: list[str] = []
    for p in sorted(Path(v2_dir).glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict):
            continue
        prov = doc.get("provenance") or {}
        keys.append(str(prov.get("referee_run") or ""))
        keys.append(str(prov.get("gate_db_legacy") or ""))
    return [k for k in keys if k]


def _gate_tier(gate: dict[str, Any]) -> str:
    return "B" if "table" in gate else "A"


def _skeleton_doc(entry: dict[str, Any], gates: list[dict[str, Any]],
                  criteria_id: str, families: list[str], head_commit: str,
                  from_md: bool) -> dict[str, Any]:
    rel = entry["path"]
    run_dir = rel.replace("\\", "/").split("/")[0]
    file_tier = "B" if any(g.get("table") for g in gates) else "A"
    gate_rows = []
    evidence: list[str] = []
    for i, g in enumerate(gates, start=1):
        gid = f"{criteria_id}#{i}"
        evidence.append(gid)
        row: dict[str, Any] = {
            "gate_id": gid,
            "tier": _gate_tier(g),
            "raw": g["raw"],
            "threshold": g.get("threshold"),
        }
        tbl = g.get("table")
        if tbl:
            row["table"] = tbl
        gate_rows.append(row)
    return {
        "schema": SKELETON_SCHEMA,
        "criteria_id": criteria_id,
        "title": entry.get("title") or criteria_id,
        "status": "skeleton_v2",
        "runner_binding": "unmigrated",
        # 骨架语义：md=人读渲染产物零改写，本文件=机械转写骨架（附加不替代，
        # #325/#326）；门值尚未经预声明冻结，禁止当机器判据源直接消费。
        "claim": {
            "quantity": "undeclared_skeleton",
            "template": families[0] if families else "unknown_skeleton",
            "f_ghz": None,
        },
        "migration": {
            "tier": file_tier,
            "source_index": DEFAULT_INDEX.name,
            "source_md": f"runs/{rel}" if from_md else None,
            "families": families,
            "n_gates": len(gates),
        },
        "evidence_fields": evidence,
        "u_val": {
            "u_num": {
                "source": "none_declared",
                "rule": "骨架缺省 none_declared——不确定度分量不虚构（EP-2 C-7 预声明；待人工复核后按 criteria/v2 契约回填）",
            },
            "u_input": {
                "source": "none_declared",
                "rule": "骨架缺省 none_declared——不确定度分量不虚构。",
            },
            "u_D": {
                "source": "none_declared",
                "rule": "骨架缺省 none_declared——不确定度分量不虚构。",
            },
        },
        "decision_rule": {
            "form": "unmigrated_skeleton",
            "gates": gate_rows,
            "overall": "骨架未判读——门值待人工复核冻结（预声明）后方可消费；"
                       "本文件不是机器判据源（status=skeleton_v2 非 active_v2）",
        },
        "verdict_map": {},
        "provenance": {
            "commit": head_commit,
            "devlog": "EP-2 C-7 三档机械化迁移骨架（strength=mechanical 同源；"
                      "三禁不写账本，账目由主代理补记）",
            "referee_run": f"runs/{run_dir}",
            "gate_db_legacy": f"knowledge/criteria/index.yaml#{rel} gates[1..{len(gates)}]",
        },
    }


def build_links(entries: list[dict[str, Any]], gates_by_path: dict[str, list[dict[str, Any]]],
                calc_names: tuple[str, ...], anchor_pairs: list[tuple[str, list[str]]],
                test_modules: tuple[str, ...] | list[str]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """四向键链接生成（机械，strength 恒=mechanical）。

    返回 (links, unmatched_paths)：每门每分维候选一条 link（各维候选数
    上限见 MAX_*_PER_GATE）；三候选全空的门不产 link（如实留白，不凑链）。"""
    links: list[dict[str, Any]] = []
    unmatched: dict[str, list[str]] = {}
    for entry in entries:
        rel = entry["path"]
        gates = gates_by_path[rel]
        cid = criteria_id_of(rel)
        text = f"{rel} {entry.get('title') or ''} " + " ".join(
            g["raw"] for g in gates)
        fams = family_tokens_for(text)
        params = calc_candidates(fams, calc_names)[:MAX_PARAMS_PER_GATE]
        tests = test_candidates(fams, test_modules)[:MAX_TESTS_PER_GATE]
        anchors = anchor_candidates(fams, anchor_pairs)[:MAX_ANCHORS_PER_GATE]
        n_comb = max(len(params), len(tests), len(anchors))
        if n_comb == 0:
            unmatched[rel] = []
            continue
        for i, _g in enumerate(gates, start=1):
            gid = f"{cid}#{i}"
            for k in range(n_comb):
                links.append({
                    "gate_id": gid,
                    "param_key": params[k] if k < len(params) else None,
                    "test_id": tests[k] if k < len(tests) else None,
                    "anchor_id": anchors[k] if k < len(anchors) else None,
                    "strength": "mechanical",
                })
    return links, unmatched


def migrate_v2(index_doc: dict[str, Any], index_sha256: str,
               runs_root: str | Path | None, skeleton_dir: str | Path,
               trace_out: str | Path, curated_v2_dir: str | Path | None = None,
               calc_names: tuple[str, ...] | None = None,
               anchor_pairs: list[tuple[str, list[str]]] | None = None,
               test_modules: tuple[str, ...] | list[str] | None = None,
               head_commit: str | None = None) -> dict[str, Any]:
    """三档机械化迁移 + 四向追溯矩阵生成（幂等：同树同参二跑逐字节一致）。

    - 只读源：index 文档与 runs/**/criteria.md 零改写（#325/#326）；
    - 附加不替代：只写 skeleton_dir/*.yaml 与 trace_out；
    - curated v2（v2_dir 顶层）按 referee_run 识别跳过骨架（零改写）；
    - 覆盖率棘轮：trace_out 已存在时 floor 取 max(既有, 首批)——重生成
      不降棘轮。
    """
    runs = Path(runs_root) if runs_root is not None else None
    skel_dir = Path(skeleton_dir)
    out_path = Path(trace_out)
    calc = calc_names if calc_names is not None else _calc_names()
    apairs = anchor_pairs if anchor_pairs is not None else _anchor_pairs()
    if test_modules is not None:
        mods: tuple[str, ...] = tuple(test_modules)
    elif DEFAULT_TESTS_CACHE.exists():
        mods = tuple(_read_tests_cache(DEFAULT_TESTS_CACHE))
    else:
        mods = tuple(collect_test_modules())
    commit = head_commit if head_commit is not None else _git_head()

    curated_keys = curated_v2_run_keys(curated_v2_dir) if curated_v2_dir else []
    errors: list[str] = []
    gates_by_path: dict[str, list[dict[str, Any]]] = {}
    tier_files = {"A": 0, "B": 0, "curated": 0}
    tier_gates = {"A": 0, "B": 0}
    n_legacy = 0
    skipped_curated: list[str] = []
    skeletons: list[tuple[Path, dict[str, Any]]] = []
    migrate_entries: list[dict[str, Any]] = []

    for entry in index_doc.get("entries", []):
        rel = entry["path"]
        if entry.get("status") != "migrate_to_v2":
            n_legacy += 1
            continue
        run_dir = rel.replace("\\", "/").split("/")[0]
        if any(run_dir and run_dir in k for k in curated_keys):
            tier_files["curated"] += 1
            skipped_curated.append(rel)
            # curated 门不产骨架，但门仍进四向矩阵（gates 用 index 抽取行）
            gates_by_path[rel] = list(entry.get("gates") or [])
            migrate_entries.append(entry)
            continue
        md_text: str | None = None
        if runs is not None:
            md = runs / rel
            if md.is_file():
                md_text = md.read_text(encoding="utf-8", errors="replace")
        if md_text is not None:
            gates = extract_gate_lines(md_text)
            if len(gates) != entry.get("n_gates"):
                errors.append(
                    f"{rel}: 重抽门行数 {len(gates)} != index 登记 "
                    f"{entry.get('n_gates')}（登记面漂移，fail-closed 不产骨架）")
                continue
        else:
            gates = list(entry.get("gates") or [])
        gates_by_path[rel] = gates
        fams = sorted(family_tokens_for(
            f"{rel} {entry.get('title') or ''} " +
            " ".join(g["raw"] for g in gates)))
        cid = criteria_id_of(rel)
        doc = _skeleton_doc(entry, gates, cid, fams, commit,
                            from_md=md_text is not None)
        skeletons.append((skel_dir / f"{cid}.yaml", doc))
        migrate_entries.append(entry)
        if any(g.get("table") for g in gates):
            tier_files["B"] += 1
        else:
            tier_files["A"] += 1
        tier_gates["A"] += sum(1 for g in gates if not g.get("table"))
        tier_gates["B"] += sum(1 for g in gates if g.get("table"))

    if errors:
        return {"ok": False, "errors": errors}

    links, unmatched = build_links(migrate_entries, gates_by_path, calc, apairs, mods)

    # 覆盖率棘轮：既有 trace_out 的 floor 只升不降（重生成保留更高 floor）
    floors = dict(FIRST_BATCH_FLOORS)
    if out_path.exists():
        try:
            prev = yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
            prev_r = prev.get("ratchet") or {}
            for k in FIRST_BATCH_FLOORS:
                v = prev_r.get(k)
                if isinstance(v, (int, float)):
                    floors[k] = max(floors[k], float(v))
        except (OSError, yaml.YAMLError):
            pass

    trace_doc: dict[str, Any] = {
        "schema": TRACE_SCHEMA,
        "note": "EP-2 C-7 四向追溯矩阵（机械生成；strength=mechanical 待人工"
                "复核，四向键=gate/param/test/anchor；审计=check_numbers trace）",
        "criteria_index_sha256": index_sha256,
        "source": {
            "index": str(Path(DEFAULT_INDEX.name)),
            "n_files": index_doc.get("n_files"),
            "n_gate_rows": index_doc.get("n_gate_rows"),
            "n_migrate_files": len(migrate_entries),
            "n_legacy_files": n_legacy,
            "n_curated_skipped": len(skipped_curated),
            "n_test_modules": len(mods),
        },
        "ratchet": {
            "gate_min_pct": floors["gate_min_pct"],
            "param_min_pct": floors["param_min_pct"],
            "note": "首批棘轮（specs C-7）：只升不降——update 只取 max，重生成保留既有更高 floor",
        },
        "links": links,
    }
    skel_dir.mkdir(parents=True, exist_ok=True)
    for path, doc in skeletons:
        path.write_text(_dump_yaml(doc), encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_dump_yaml(trace_doc), encoding="utf-8")

    return {
        "ok": True,
        "n_files": index_doc.get("n_files"),
        "n_migrate": len(migrate_entries),
        "n_legacy": n_legacy,
        "tier_files": tier_files,
        "tier_gates": tier_gates,
        "n_skeletons": len(skeletons),
        "skipped_curated": skipped_curated,
        "unmatched_paths": sorted(unmatched),
        "n_links": len(links),
        "skeleton_dir": str(skel_dir),
        "trace_out": str(out_path),
    }


def _read_tests_cache(path: str | Path) -> list[str]:
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def _sha256_of_index(index_path: str | Path) -> str:
    return hashlib.sha256(Path(index_path).read_bytes()).hexdigest()


def load_index_or_build(index_path: str | Path,
                        runs_root: str | Path) -> dict[str, Any]:
    """迁移模式的 index 来源：--index 在场读文件（登记冻结面），缺失则内存
    build（绝不落盘 index——迁移模式零 index 写点）。"""
    p = Path(index_path)
    if p.is_file():
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"entries": []}
    return build_index(runs_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="扫 runs/**/criteria.md 构建只读判据清单（DP-13 Z1）；"
                    "--migrate-v2 产 v2 骨架+四向追溯矩阵（EP-2 C-7）")
    parser.add_argument("--runs-root", default="runs",
                        help="runs 根目录（缺省 runs）")
    parser.add_argument("--out", default="knowledge/criteria/index.yaml",
                        help="输出 index.yaml 路径（--migrate-v2 模式忽略）")
    parser.add_argument("--migrate-v2", action="store_true",
                        help="三档机械化迁移：产 v2 骨架 + knowledge/trace_matrix.yaml")
    parser.add_argument("--index", default=str(DEFAULT_INDEX),
                        help="迁移模式的 index 来源（缺省登记冻结面；缺失则内存构建）")
    parser.add_argument("--skeleton-dir", default=str(DEFAULT_SKELETON_DIR),
                        help="v2 骨架输出目录")
    parser.add_argument("--trace-out", default=str(DEFAULT_TRACE_OUT),
                        help="四向追溯矩阵输出路径")
    parser.add_argument("--v2-dir", default=str(DEFAULT_V2_DIR),
                        help="人工 curated v2 目录（顶层文件识别跳过，零改写）")
    parser.add_argument("--tests-cache", default=str(DEFAULT_TESTS_CACHE),
                        help="pytest nodeid 模块路径缓存（缺失则只读 collect）")
    parser.add_argument("--quiet", action="store_true",
                        help="只打一行摘要")
    args = parser.parse_args(argv)

    if args.migrate_v2:
        summary = migrate_v2(
            index_doc=load_index_or_build(args.index, args.runs_root),
            index_sha256=(_sha256_of_index(args.index)
                          if Path(args.index).is_file() else "in-memory"),
            runs_root=args.runs_root,
            skeleton_dir=args.skeleton_dir,
            trace_out=args.trace_out,
            curated_v2_dir=args.v2_dir,
        )
        if not summary.get("ok"):
            for err in summary.get("errors", ["未知错误"]):
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        if args.quiet:
            print(
                f"migrate-v2: skeletons={summary['n_skeletons']} "
                f"links={summary['n_links']} -> {summary['trace_out']}")
        else:
            tf = summary["tier_files"]
            print(f"三档迁移：文件 A={tf['A']} B={tf['B']} "
                  f"C(legacy_only)={summary['n_legacy']} "
                  f"curated跳过={len(summary['skipped_curated'])}；"
                  f"门行 A={summary['tier_gates']['A']} B={summary['tier_gates']['B']}；"
                  f"骨架 {summary['n_skeletons']} 件 → {summary['skeleton_dir']}；"
                  f"四向 links {summary['n_links']} 条 → {summary['trace_out']}")
            if summary["unmatched_paths"]:
                print(f"未链接 run（人工复核清单）："
                      f"{len(summary['unmatched_paths'])} 件（见矩阵 note）")
        return 0

    index = build_index(args.runs_root)
    if not index.get("ok"):
        for err in index.get("errors", ["未知错误"]):
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    out = write_index(index, args.out)
    n_migrate = sum(1 for e in index["entries"] if e["status"] == "migrate_to_v2")
    if args.quiet:
        print(f"criteria index: {index['n_files']} files, "
              f"{index['n_gate_rows']} gate rows -> {out}")
    else:
        print(f"扫描 {index['n_files']} 份 criteria.md "
              f"（migrate_to_v2={n_migrate}, legacy_only="
              f"{index['n_files'] - n_migrate}），"
              f"门阈值行 {index['n_gate_rows']} 行 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
