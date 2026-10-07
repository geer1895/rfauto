"""KD-1 公式 provenance 注册表（specs 研究扩充 round16 KD-1）。

把 core 树 docstring 里的自由文本公式出处（铁律 5「来源写 docstring」惯例）
结构化成机读注册表 knowledge/formula_provenance.yaml，供 preflight/能力卡/
XC-F 等消费面查询。与 XC-P 精度档案（knowledge/precision_profiles.yaml）
分工互补：**KD-1 管"出处"（该公式引用了谁），XC-P 管"精度"（偏差分档与
有效域）**——两表同源漂移由 tests/unit/test_formula_provenance.py 的
共享标识符包含钉看管（XC-P refs 里与 docstring 同现的 DOI/arXiv id 必须
被本收集器捕进 refs）。

schema（每条目，多键/缺键=FormulaProvenanceSchemaError）：
  formula_id: str     稳定 id＝"<core 内相对路径去 .py>:<symbol>:<序号>"
  kernel_file: str    仓相对 posix 路径（如 src/rfauto/core/fading.py）
  module: str         点路径（如 rfauto.core.fading）
  symbol: str         函数/类/方法名；模块级 docstring="<module>"
  kind: source|pointer  source=行首标记声明；pointer="出处见…"指针声明
  marker: str         命中的标记词（pointer 固定"出处见"）
  claim_line: str     标记行原文（strip）
  claim_block: str    声明块原文（标记行+续行，规则见 _claim_block）
  refs: [str]         从块内抽取的文献标识（DOI/arXiv/标准号/URL/带年份引文行）
  source_doi: str|null  首个 DOI
  eq_no: str|null     首个式号/章节锚（§x.y、式(n)、Eq. n、Table n）
  expr: str|null      块内首个"公式形"行（启发式，抽取不到如实 null）
  access_status: verified|unverified|null  出处可达性（docstring 自声明词面
                      启发式；判不了如实 null，不编）
  verified_by: str    生成项=收集器转录声明；manual 项人工填写
  origin: docstring|manual

三载体（与 XC-P 同款防漂移裁决）：
1. knowledge/formula_provenance.yaml —— 机器可消费单源（收集器生成+人工可补）；
2. 各内核模块 docstring 出处行 —— 人读面（只读，禁反向改写）；
3. 本模块 —— AST 扫描纯函数/schema 校验/查询面；scripts/
   collect_formula_provenance.py 是再生薄壳（--check 只验漂移不写）。

幂等契约：同一棵树上 render(scan()) 逐字节可重现（无时间戳类字段）；
docstring 改动未再生注册表=一致性门红（tests/unit/test_formula_provenance.py）。
manual_entries 段是人工补录区，再生时逐字保留。

覆盖口径（如实）：只收 docstring 行首标记与"出处见"指针行；# 注释与无标记的
内联 author-year 引文不在收集面（宁缺毋滥）；XC-P「精度档案」镜像行不收
（那是 XC-P 载体，块内剥离防串味）。

分层：core 叶子（仅 stdlib+yaml；XC-P 镜像行剥离用本地正则，避免 core 内
 sibling 顶层耦合）；不定义 ``__all__``（公开 API 金快照只钉带 __all__ 模块，
XC-P 先例）。

铁律 7 合规：本模块零物理数字产出——只搬运 docstring 已声明的出处文本与
可达性词面，不产生任何频率/损耗/几何数值。
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

import yaml

#: 注册表路径覆盖环境变量（设置即信；空串含纯空白视同未设置）。
FORMULA_PROVENANCE_ENV = "RFAUTO_FORMULA_PROVENANCE_YAML"

#: canonical 缺省注册表路径（<repo>/knowledge/formula_provenance.yaml）。
_DEFAULT_RELPATH = Path("knowledge") / "formula_provenance.yaml"

#: canonical 仓根深度：本模块位于 <root>/src/rfauto/core/，parents[3]=仓根。
_CANONICAL_PARENT_DEPTH = 3

#: claim 块最大行数（防超长段落拖爆注册表；出处节超出部分不进块不进 refs）。
_CLAIM_BLOCK_MAX_LINES = 30

#: 条目 kind 受控词表。
CLAIM_KINDS = ("source", "pointer")

#: 条目 origin 受控词表。
ENTRY_ORIGINS = ("docstring", "manual")

#: access_status 受控词表（null 合法——判不了如实不判）。
ACCESS_STATUSES = ("verified", "unverified")

#: 条目 schema 键（多键/缺键即错——漂移负例锚的判定单点）。
_ENTRY_KEYS = (
    "formula_id",
    "kernel_file",
    "module",
    "symbol",
    "kind",
    "marker",
    "claim_line",
    "claim_block",
    "refs",
    "source_doi",
    "eq_no",
    "expr",
    "access_status",
    "verified_by",
    "origin",
)

#: 人工补录条目必需键（其余键可选；formula_id 全表唯一由加载器统一钉）。
_MANUAL_REQUIRED_KEYS = ("formula_id", "claim_line", "verified_by")

#: 人工补录条目允许键（= 条目键全集 + note 自由注记）。
_MANUAL_ALLOWED_KEYS = frozenset(_ENTRY_KEYS) | {"note"}


class FormulaProvenanceSchemaError(ValueError):
    """公式 provenance 注册表违反 schema（负例测试的预期异常类型）。"""


# ─── 标记集（2026-10-02 全树普查定标；噪声全检：参考面/参考值/参考元/参考实现/
# ─── 参考阻抗/参考结构类 prose 已排除——``参考`` 仅裸"参考："计数）─────────────

#: 行首出处标记（含可选 "- "/* " bullet；stem 后允许 ≤8 字连接词再接标点，
#: 覆盖"出处与口径：""法源与核验状态（…）："等头形态）。
MARKER_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s+)?"
    r"(?P<marker>"
    r"(?:机制出处|口径来源|口径与来源|原始文献|参考文献|文献传导链|权威口径"
    r"|[Ss]pec\s+出处|出处|来源|法源|文献|[Rr]eferences?)"
    r"[^（(:：\n]{0,8}?[（(:：]"
    r"|参考\s*[（(:：]"
    r")"
)

#: 指针型出处声明（"出处见模块 docstring"等函数级指向）。
POINTER_RE = re.compile(r"出处见")

#: 行首 bullet（块延续判定用）。
_BULLET_RE = re.compile(r"^\s*[-*•]\s")

#: XC-P「精度档案」镜像行前缀（本注册表不收——那是 XC-P 载体；块内剥离防串味。
#: 镜像行规范单源在 core/precision_profiles.PRECISION_MARKER_RE，这里只按前缀
#: 剥离不重复整套正则——收集器测试钉两侧一致性）。
_PRECISION_MIRROR_SUBSTR = "精度档案"


# ─── 文献标识抽取 ──────────────────────────────────────────────────────────

_PUNCT_TAIL = "，。；）)”』」>.,;:：！？"

#: DOI（DOI: 前缀或 doi.org 链接；尾随标点剔除）。
_DOI_RE = re.compile(
    r"(?:DOI\s*[:：]?\s*|doi\.org/)(10\.\d{4,9}/[^\s，。；、)”\"'』」<>]+)",
    re.IGNORECASE,
)

#: arXiv id（版本号原样保留；并轨比对时两侧去 vN 基底化）。
_ARXIV_RE = re.compile(r"arXiv\s*[:：]\s*([0-9]{4}\.[0-9]{4,5})(v[0-9]+)?", re.IGNORECASE)

#: 标准号（ITU-R/CISPR/IEEE Std/IEC/ECSS/3GPP TS/ASME V&V）。
_STANDARD_RE = re.compile(
    r"(?:ITU-R\s+[A-Z]\.\d+(?:-[0-9]+)?"
    r"|CISPR\s+[0-9]{1,2}(?:-[0-9]+)*"
    r"|IEEE\s+Std\.?\s*[0-9]+(?:-[0-9]+)*"
    r"|IEC\s+[0-9]{4,5}(?:-[0-9]+)*"
    r"|ECSS-[A-Z]+(?:-[A-Z0-9]+)+"
    r"|3GPP\s+TS\s+[0-9]+(?:\.[0-9]+)+"
    r"|ASME\s+V&V\s*[0-9][0-9A-Za-z()\-.]*)"
)

#: URL（尾随标点剔除）。
_URL_RE = re.compile(r"https?://[^\s，。；、)”\"'』」<>]+")

#: 式号/章节锚（§x.y、式(n)、Eq. n、Table n、表 n）。
_EQ_NO_RE = re.compile(
    r"(?:§[0-9A-Z][0-9A-Za-z.\-]*"
    r"|式\s*[（(][^）)]{1,24}[）)]"
    r"|Eq\.?\s*[0-9]+[A-Za-z]?"
    r"|Table\s*[0-9]+"
    r"|表\s*[0-9]+)"
)

#: ISO 日期剔除（防"2026-09-26 实测可达性"被当引文年份）。
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")

#: 年份（引文行判定：剔除 ISO 日期后仍含 19xx/20xx 才算）。
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

#: 公式形行（expr 启发式：行首标识符[可选 (…)] = 右值；排除键值注记行）。
_EXPR_RE = re.compile(r"^\s*[A-Za-z_][\w·\[\]%]*(?:\([^)]{0,48}\))?\s*=(?!=)\s*\S")
_EXPR_EXCLUDE_SUBSTR = (
    "精度档案",
    "last_verified",
    "行为=",
    "docs/",
    "http",
    "knowledge/",
)

#: 出处可达性词面（docstring 自声明；unverified 优先——存疑从严）。
_ACCESS_UNVERIFIED_WORDS = (
    "不可达",
    "未核",
    "未经",
    "付费墙",
    "unverified",
    "未获",
    "原文未读",
    "未读",
)
_ACCESS_VERIFIED_WORDS = (
    "已核",
    "逐位核",
    "逐位核对",
    "实测可达",
    "双源",
    "文本层核",
    "回原文核对",
    "逐段回原文",
)


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise FormulaProvenanceSchemaError(msg)


# ─── AST 扫描（纯函数）───────────────────────────────────────────────────────

def _iter_doc_nodes(tree: ast.Module) -> list[tuple[int, str, str]]:
    """(lineno, symbol, docstring) 三元组，源码序；模块 docstring 记 "<module>"。"""
    out: list[tuple[int, str, str]] = []
    module_doc = ast.get_docstring(tree, clean=True)
    if module_doc:
        out.append((0, "<module>", module_doc))

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbol = prefix + child.name
                doc = ast.get_docstring(child, clean=True)
                if doc:
                    out.append((child.lineno, symbol, doc))
                walk(child, symbol + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _claim_block(lines: list[str], start: int) -> str:
    """标记行起取声明块：非空续行直收；空行后若接 bullet 或更深缩进则续块，
    否则断块（下一段 prose 不属本声明）；命中下一标记行即断；上限 30 行。"""
    block = [lines[start].rstrip()]
    marker_indent = _line_indent(lines[start])
    limit = start + _CLAIM_BLOCK_MAX_LINES
    for j in range(start + 1, min(limit, len(lines))):
        ln = lines[j]
        if MARKER_LINE_RE.match(ln):
            break
        if not ln.strip():
            k = j
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k >= min(limit, len(lines)):
                break
            nxt = lines[k]
            if _BULLET_RE.match(nxt) or _line_indent(nxt) > marker_indent:
                block.append("")
                continue
            break
        block.append(ln.rstrip())
    return "\n".join(block)


def _strip_precision_mirror(text: str) -> str:
    """剥掉 XC-P「精度档案」镜像行（XC-P 载体不进本注册表的块与 refs）。"""
    kept = [ln for ln in text.splitlines() if _PRECISION_MIRROR_SUBSTR not in ln]
    return "\n".join(kept)


def _extract_refs(block: str) -> list[str]:
    """块内文献标识抽取（有序去重）：DOI/arXiv/标准号/URL + 带年份引文行。"""
    refs: list[str] = []
    for m in _DOI_RE.finditer(block):
        refs.append(m.group(1).rstrip(_PUNCT_TAIL))
    for m in _ARXIV_RE.finditer(block):
        refs.append(f"arXiv:{m.group(1)}{m.group(2) or ''}")
    for m in _STANDARD_RE.finditer(block):
        refs.append(m.group(0).rstrip(_PUNCT_TAIL))
    for m in _URL_RE.finditer(block):
        refs.append(m.group(0).rstrip(_PUNCT_TAIL))
    for ln in block.splitlines():
        stripped = ln.strip()
        if len(stripped) < 8:
            continue
        if _YEAR_RE.search(_ISO_DATE_RE.sub("", stripped)) is None:
            continue
        if re.search(r"[A-Za-z]{2}", stripped) is None:
            continue
        refs.append(stripped)
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        r = r.strip().rstrip(_PUNCT_TAIL)
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _extract_eq_no(claim_line: str, block: str) -> str | None:
    m = _EQ_NO_RE.search(claim_line) or _EQ_NO_RE.search(block)
    return m.group(0) if m else None


def _extract_expr(block: str) -> str | None:
    for ln in block.splitlines():
        if any(s in ln for s in _EXPR_EXCLUDE_SUBSTR):
            continue
        if _EXPR_RE.match(ln) is None:
            continue
        # 全角右括号/破折号=跨行 prose 续行（如"k=2π/λ）——逐式出处见下"），
        # 真公式行在本仓 docstring 惯例里用 ASCII 括号。
        if "）" in ln or "——" in ln:
            continue
        return ln.strip()
    return None


def _extract_access_status(claim_line: str, block: str) -> str | None:
    text = f"{claim_line}\n{block}".lower()
    if any(w in text for w in _ACCESS_UNVERIFIED_WORDS):
        return "unverified"
    if any(w in text for w in _ACCESS_VERIFIED_WORDS):
        return "verified"
    return None


def _first_doi(block: str) -> str | None:
    m = _DOI_RE.search(block)
    return m.group(1).rstrip(_PUNCT_TAIL) if m else None


def _bare_ref_has_evidence(claim_line: str) -> bool:
    """裸"参考："声明的证据守卫（行级）：行内须有文献证据（refs 抽取面/§锚/
    docs/ 链接）之一，否则视作 prose 用法（"参考（不做门判）"类）不收。"""
    if _extract_refs(claim_line) or _EQ_NO_RE.search(claim_line):
        return True
    return "docs/" in claim_line


def scan_formula_provenance(
    core_dir: str | Path,
    *,
    module_prefix: str = "rfauto.core",
    kernel_file_base: str | Path | None = None,
) -> list[dict[str, Any]]:
    """AST 扫描 core 树全部 docstring 的出处标记行（纯函数，落盘无关）。

    Args:
        core_dir: core 包目录（如 <repo>/src/rfauto/core；递归含子包，
            跳过 __pycache__；收集器自身模块 formula_provenance.py 自排除——
            其 docstring 引号里的"出处见"样例不是出处声明）。
        module_prefix: 条目 module 字段前缀（tmp 树测试可换词根）。
        kernel_file_base: kernel_file 的相对基准（仓根）；缺省=core_dir
            本身（条目 kernel_file 为 core 内相对路径）。仓级收集走
            scan_repo_formula_provenance（kernel_file=仓相对路径）。

    Returns:
        条目列表（源码序：文件按相对路径排序，文件内按声明位置序）。
    """
    root = Path(core_dir)
    base = Path(kernel_file_base) if kernel_file_base is not None else root
    entries: list[dict[str, Any]] = []
    files = sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
        and p.with_suffix("").name != "formula_provenance"  # 自排除（见 docstring）
    )
    for path in files:
        relstem = path.relative_to(root).with_suffix("").as_posix()
        kernel_file = path.relative_to(base).as_posix()
        module = f"{module_prefix}.{relstem.replace('/', '.')}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        counters: dict[str, int] = {}
        for _lineno, symbol, doc in _iter_doc_nodes(tree):
            lines = doc.splitlines()
            for i, ln in enumerate(lines):
                marker_match = MARKER_LINE_RE.match(ln)
                is_pointer = marker_match is None
                if is_pointer and POINTER_RE.search(ln) is None:
                    continue
                key = f"{relstem}:{symbol}"
                counters[key] = counters.get(key, 0) + 1
                formula_id = f"{relstem}:{symbol}:{counters[key]:02d}"
                if is_pointer:
                    kind = "pointer"
                    marker = "出处见"
                    block = ln.strip()
                else:
                    kind = "source"
                    marker = re.sub(r"\s+", " ", marker_match.group("marker")).strip()
                    block = _claim_block(lines, i)
                claim_line = ln.strip()
                block = _strip_precision_mirror(block)
                if marker.startswith("参考") and not _bare_ref_has_evidence(claim_line):
                    counters[key] -= 1  # prose 用法剔除后序号回退（id 稳定）
                    continue
                entries.append(
                    {
                        "formula_id": formula_id,
                        "kernel_file": kernel_file,
                        "module": module,
                        "symbol": symbol,
                        "kind": kind,
                        "marker": marker,
                        "claim_line": claim_line,
                        "claim_block": block,
                        "refs": _extract_refs(block),
                        "source_doi": _first_doi(block),
                        "eq_no": _extract_eq_no(claim_line, block),
                        "expr": _extract_expr(block),
                        "access_status": _extract_access_status(claim_line, block),
                        "verified_by": "collect_formula_provenance.py（docstring 转录）",
                        "origin": "docstring",
                    }
                )
    return entries


def default_core_dir() -> Path:
    """canonical core 目录（本模块所在目录——src 布局 editable 安装同样成立）。"""
    return Path(__file__).resolve().parent


def scan_repo_formula_provenance(repo_root: str | Path) -> list[dict[str, Any]]:
    """仓级收集口径（script 与一致性门共用的唯一定位）：kernel_file=仓相对路径。"""
    root = Path(repo_root)
    return scan_formula_provenance(
        root / "src" / "rfauto" / "core",
        module_prefix="rfauto.core",
        kernel_file_base=root,
    )


# ─── 路径发现（XC-P 同款：显式 > env 设置即信 > canonical）───────────────────

def default_formula_provenance_yaml_path() -> Path:
    """canonical 缺省路径（<root>/knowledge/formula_provenance.yaml；不查存在性）。"""
    anchor = Path(__file__).resolve()
    return anchor.parents[_CANONICAL_PARENT_DEPTH] / _DEFAULT_RELPATH


def resolve_formula_provenance_yaml_path(path: str | Path | None = None) -> Path:
    """显式入参 > env（设置即信，不存在不静默回退）> canonical。（纯路径，不读档）"""
    if path is not None:
        return Path(path)
    env = os.environ.get(FORMULA_PROVENANCE_ENV, "")
    if env.strip():
        return Path(env)
    anchor = Path(__file__).resolve()
    parents = anchor.parents
    depth = min(_CANONICAL_PARENT_DEPTH, max(len(parents) - 1, 0))
    for i in range(depth, len(parents)):
        candidate = parents[i] / _DEFAULT_RELPATH
        if candidate.is_file():
            return candidate
    return default_formula_provenance_yaml_path()


# ─── schema 校验与加载 ──────────────────────────────────────────────────────

def _validate_entry(entry: Any, where: str) -> dict[str, Any]:
    _need(isinstance(entry, dict), f"{where}: 条目须为 mapping，得到 {type(entry).__name__}")
    keys = set(entry)
    missing = [k for k in _ENTRY_KEYS if k not in keys]
    extra = sorted(keys - set(_ENTRY_KEYS))
    _need(not missing, f"{where}: 缺 schema 必需键 {missing}")
    _need(not extra, f"{where}: 不允许多余键 {extra}")
    for k in (
        "formula_id",
        "kernel_file",
        "module",
        "symbol",
        "marker",
        "claim_line",
        "claim_block",
        "verified_by",
    ):
        _need(isinstance(entry[k], str) and entry[k] != "", f"{where}: {k} 须为非空 str")
    _need(entry["kind"] in CLAIM_KINDS, f"{where}: kind {entry['kind']!r} 不在 {CLAIM_KINDS}")
    _need(entry["origin"] in ENTRY_ORIGINS, f"{where}: origin {entry['origin']!r} 不在 {ENTRY_ORIGINS}")
    refs = entry["refs"]
    _need(isinstance(refs, list) and all(isinstance(r, str) and r for r in refs),
          f"{where}: refs 须为 str list（可为空列表，元素须非空 str）")
    for k in ("source_doi", "eq_no", "expr", "access_status"):
        v = entry[k]
        _need(v is None or (isinstance(v, str) and v != ""), f"{where}: {k} 须为 null 或非空 str")
    _need(entry["access_status"] is None or entry["access_status"] in ACCESS_STATUSES,
          f"{where}: access_status {entry['access_status']!r} 不在 {ACCESS_STATUSES}∪{{null}}")
    return {k: (list(entry[k]) if k == "refs" else entry[k]) for k in _ENTRY_KEYS}


def _validate_manual_entry(entry: Any, where: str) -> dict[str, Any]:
    _need(isinstance(entry, dict), f"{where}: manual 条目须为 mapping")
    keys = set(entry)
    missing = [k for k in _MANUAL_REQUIRED_KEYS if k not in keys]
    extra = sorted(keys - _MANUAL_ALLOWED_KEYS)
    _need(not missing, f"{where}: manual 条目缺必需键 {missing}")
    _need(not extra, f"{where}: manual 条目不允许键 {extra}")
    for k in _MANUAL_REQUIRED_KEYS:
        _need(isinstance(entry[k], str) and entry[k] != "", f"{where}: manual {k} 须为非空 str")
    if "origin" in keys:
        _need(entry["origin"] == "manual", f"{where}: manual 条目 origin 必须为 manual")
    return dict(entry)


def load_formula_provenance(path: str | Path | None = None) -> dict[str, Any]:
    """读档+schema 校验，返回 {schema_version, entries, manual_entries}。

    Raises:
        FileNotFoundError: 路径不存在（env 显式路径不静默回退）。
        FormulaProvenanceSchemaError: schema 违例 / formula_id 重复。
    """
    resolved = resolve_formula_provenance_yaml_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"formula_provenance.yaml 不存在: {resolved}")
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    _need(isinstance(data, dict), "顶层须为 mapping")
    version = data.get("schema_version", 1)
    _need(isinstance(version, int) and not isinstance(version, bool) and version >= 1,
          f"schema_version 须为 >=1 整数，得到 {version!r}")
    entries_raw = data.get("entries")
    _need(isinstance(entries_raw, list), "entries 须为 list")
    manual_raw = data.get("manual_entries", [])
    _need(isinstance(manual_raw, list), "manual_entries 须为 list")
    entries = [_validate_entry(e, f"entries[{i}]") for i, e in enumerate(entries_raw)]
    manual = [_validate_manual_entry(e, f"manual_entries[{i}]") for i, e in enumerate(manual_raw)]
    ids = [e["formula_id"] for e in entries] + [e["formula_id"] for e in manual]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    _need(not dup, f"formula_id 重复: {dup}")
    return {
        "schema_version": version,
        "entries": entries,
        "manual_entries": manual,
    }


# ─── 再生渲染（确定性；无时间戳类字段——幂等契约的前提）──────────────────────

_YAML_HEADER = """\
# KD-1 公式 provenance 注册表（specs 研究扩充 round16 KD-1）。
#
# 定位：core 树 docstring 出处行（铁律 5）的结构化机读面。schema/扫描/查询单源在
#   src/rfauto/core/formula_provenance.py；本文件除 manual_entries 外全部收集器
#   生成，禁手改——再生：.venv/Scripts/python.exe scripts/collect_formula_provenance.py
#   （--check 只验漂移不写）。
#
# 与 XC-P（knowledge/precision_profiles.yaml）分工：KD-1 管"出处"（公式引用了谁），
#   XC-P 管"精度"（偏差分档+有效域）。两表并轨由 tests/unit/test_formula_provenance.py
#   钉共享标识符包含（XC-P refs 中与内核 docstring 同现的 DOI/arXiv id 必须进本表 refs）。
#
# 覆盖口径：只收 docstring 行首标记（出处/来源/法源/文献/参考/References 等惯用语，
#   集见 core.formula_provenance.MARKER_LINE_RE）与"出处见…"指针行；# 注释与无标记
#   内联引文不在收集面——覆盖数如实登记，宁缺毋滥。
#
# entries 逐键 schema 见 core.formula_provenance 模块 docstring；access_status 是
#   docstring 可达性自声明的词面启发式（verified/unverified/null，null=判不了如实
#   不判）；expr 为块内首个公式形行的启发式抽取，抽取不到为 null。
# manual_entries=人工补录区（收集器逐字保留；必需键 formula_id/claim_line/verified_by）。
"""


def render_formula_provenance_yaml(
    entries: list[dict[str, Any]],
    manual_entries: list[dict[str, Any]] | None = None,
) -> str:
    """确定性渲染注册表 YAML 文本（entries 须为 scan/validate 规范化条目）。"""
    validated = [_validate_entry(e, f"entries[{i}]") for i, e in enumerate(entries)]
    payload = {
        "schema_version": 1,
        "generated_by": "scripts/collect_formula_provenance.py",
        "entries": validated,
        "manual_entries": [dict(m) for m in (manual_entries or [])],
    }
    body = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        width=100,
        default_flow_style=False,
    )
    return _YAML_HEADER + body


# ─── 查询面（消费点：preflight / 能力卡 / XC-F）──────────────────────────────

def _as_data(
    entries: list[dict[str, Any]] | None,
    path: str | Path | None,
) -> dict[str, Any]:
    if entries is not None:
        return {"entries": entries, "manual_entries": []}
    return load_formula_provenance(path)


def formula_provenance(
    symbol: str | None = None,
    file: str | None = None,
    *,
    module: str | None = None,
    kind: str | None = None,
    entries: list[dict[str, Any]] | None = None,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """查询公式出处条目（纯过滤，零数值产出——铁律 7）。

    Args:
        symbol: 精确匹配条目 symbol（"<module>"/函数/类/"Class.method"）；None=不限。
        file: kernel_file 匹配（仓相对路径精确或 "/" 后缀匹配，如
            "conductor_loss.py"、"src/rfauto/core/fading.py"）；None=不限。
        module: 点路径精确匹配（如 "rfauto.core.synthesis"）；None=不限。
        kind: "source"|"pointer"；None=不限。
        entries: 已加载条目注入（批量调用免重复读档）。
        path: YAML 路径覆盖（entries 未注入时生效）。

    Returns:
        匹配条目列表（注册表序）。
    """
    data = _as_data(entries, path)
    out: list[dict[str, Any]] = []
    for e in data["entries"]:
        if symbol is not None and e["symbol"] != symbol:
            continue
        if file is not None:
            kf = e["kernel_file"]
            if kf != file and not kf.endswith("/" + file.lstrip("/")):
                continue
        if module is not None and e["module"] != module:
            continue
        if kind is not None and e["kind"] != kind:
            continue
        out.append(e)
    return out


def provenance_summary(
    *,
    entries: list[dict[str, Any]] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """注册表覆盖摘要（如实口径：注释/内联引文不在收集面，宁缺毋滥）。"""
    data = _as_data(entries, path)
    all_entries: list[dict[str, Any]] = list(data["entries"]) + list(data["manual_entries"])
    by_kind: dict[str, int] = {}
    by_access: dict[str, int] = {}
    for e in all_entries:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
        key = e.get("access_status") if e.get("access_status") is not None else "null"
        by_access[key] = by_access.get(key, 0) + 1
    doc_entries = [e for e in all_entries if e["origin"] == "docstring"]
    return {
        "entries": len(all_entries),
        "files": len({e["kernel_file"] for e in doc_entries}),
        "modules": len({e["module"] for e in doc_entries}),
        "by_kind": by_kind,
        "by_access": by_access,
        "with_source_doi": sum(1 for e in all_entries if e.get("source_doi")),
        "with_arxiv_ref": sum(1 for e in all_entries if any(r.startswith("arXiv:") for r in e.get("refs", []))),
        "with_url_ref": sum(1 for e in all_entries if any(r.startswith("http") for r in e.get("refs", []))),
        "with_eq_no": sum(1 for e in all_entries if e.get("eq_no")),
        "manual_entries": len(data["manual_entries"]),
        "kernel_files": sorted({e["kernel_file"] for e in doc_entries}),
    }
