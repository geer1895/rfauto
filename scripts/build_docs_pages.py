#!/usr/bin/env python3
"""PR-10 文档站机读页生成器（mkdocs-material 路线，round16 规格_PR-10）。

从代码面机读生成 docs_site/ 下的参考页（CLI 树 / MCP 工具清单 / 计算器
注册表）与模板库聚合页，并把既有文档资产（tutorials/explanation/gallery）
同步进站点目录；首页数字条（AUTO-NUMBERS 标记块）同批回填。

同源契约（#97，零手写数字）：
- 计数一律 import scripts/check_numbers.py 的计数函数（构建时实测）；
- 条目枚举与 check_numbers 同口径：CLI=typer→click 树 walk；MCP=@mcp.tool
  装饰器（ast 枚举 + check_numbers 正则计数互证）；CALC=describe()；
  模板=docs/templates/*/meta.yaml 与 TEMPLATE_META 键集互证。
- 生成页内的总数与计数函数逐位互证，不一致即 RuntimeError 拒绝出页。

用法（在 venv 内，仓根执行）：
    python scripts/build_docs_pages.py            # 原地重建 docs_site/
    python scripts/build_docs_pages.py --out DIR  # 重建到指定目录（测试用）

产物确定性：不写时间戳/环境相关内容（锚树测试按逐字节比对钉漂移）。
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_SITE_DEFAULT = REPO_ROOT / "docs_site"
TEMPLATES_DOCS = REPO_ROOT / "docs" / "templates"

# 同步面（源目录 → 站点相对目录；.md 带溯源横幅，其余原样拷贝）
SYNC_DIRS: tuple[tuple[str, str], ...] = (
    ("docs/tutorials", "tutorials"),
    ("docs/explanation", "explanation"),
)
SYNC_STATIC: tuple[tuple[str, str], ...] = (
    ("docs/gallery/index.html", "gallery/index.html"),
)

SYNC_BANNER = (
    "<!-- PR-10 文档站同步副本：源={src}（scripts/build_docs_pages.py 重建，"
    "勿直接改本文件——改动请改源文件后重跑生成器） -->\n\n"
)

AUTO_START = "<!-- AUTO-NUMBERS:START -->"
AUTO_END = "<!-- AUTO-NUMBERS:END -->"


# ─── check_numbers 同源装载 ────────────────────────────────────────────────

def load_check_numbers():
    """按文件路径装载 scripts/check_numbers.py（与 tests/unit/test_check_numbers
    同款 importlib 模式；不依赖 sys.path 含 scripts）。"""
    path = Path(__file__).resolve().parent / "check_numbers.py"
    spec = importlib.util.spec_from_file_location("_pr10_check_numbers", path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── 通用渲染助手 ──────────────────────────────────────────────────────────

def md_cell(text: Any) -> str:
    """表格单元格安全化：竖线转义、换行折叠、None→—。"""
    if text is None:
        return "—"
    s = str(text).replace("|", "\\|")
    s = re.sub(r"\s+", " ", s).strip()
    return s or "—"


def first_line(text: str | None) -> str:
    """help/docstring 首行（供目录/表格摘要；折叠空白）。"""
    if not text:
        return ""
    for raw in str(text).splitlines():
        line = raw.strip()
        if line:
            return re.sub(r"\s+", " ", line)
    return ""


# ─── CLI 参考页（口径=check_numbers.cli_leaf_counts 同款 click 树 walk）───

@dataclass
class CliNode:
    name: str
    help: str
    children: list[CliNode] = field(default_factory=list)

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    def count_leaves(self) -> int:
        if not self.children:
            return 1
        return sum(c.count_leaves() for c in self.children)


def _walk_cli_group(name: str, cmd: Any) -> CliNode:
    help_text = getattr(cmd, "help", None) or getattr(cmd, "short_help", None) or ""
    node = CliNode(name=name, help=first_line(help_text))
    subs = getattr(cmd, "commands", None) or {}
    for sub_name, sub_cmd in subs.items():
        node.children.append(_walk_cli_group(sub_name, sub_cmd))
    return node


def collect_cli_tree() -> list[CliNode]:
    from typer.main import get_command

    from rfauto.cli.main import app

    top = get_command(app)
    if not hasattr(top, "commands"):  # pragma: no cover - 防御
        return []
    return [_walk_cli_group(name, sub) for name, sub in top.commands.items()]


def _render_cli_nodes(nodes: list[CliNode], prefix: str,
                      indent: str = "") -> list[str]:
    lines: list[str] = []
    for node in nodes:
        path = f"{prefix} {node.name}"
        suffix = f"（{node.count_leaves()} 条）" if node.is_group else ""
        lines.append(
            f"{indent}- `{path}`{suffix}" + (f" — {node.help}" if node.help else "")
        )
        if node.is_group:
            lines.extend(_render_cli_nodes(node.children, path, indent + "    "))
    return lines


def build_cli_page(checknum) -> tuple[str, int]:
    tree = collect_cli_tree()
    total = sum(n.count_leaves() for n in tree)
    expected = checknum.count_cli()
    if total != expected:
        raise RuntimeError(
            f"CLI 页枚举叶子数 {total} != check_numbers.count_cli() {expected}"
            "（同源互证失败，拒绝出页）")
    per_top = {n.name: n.count_leaves() for n in tree}
    for name, cnt in checknum.cli_leaf_counts().items():
        if per_top.get(name) != cnt:
            raise RuntimeError(
                f"CLI 顶层 {name} 子树计数 {per_top.get(name)} != "
                f"check_numbers.cli_leaf_counts()[{name}]={cnt}（同源互证失败）")

    lines: list[str] = [
        "# CLI 命令参考",
        "",
        f"> 实注册叶子命令共 **{total}** 条（`typer.main.get_command` 后按 "
        "click 树 walk 展开，含各 `add_typer` 子应用；与 `scripts/check_numbers.py`"
        " 的 `count_cli()` 构建时逐位互证）。本页由 "
        "`scripts/build_docs_pages.py` 机读生成，勿手改。",
        "",
        "用法速查见[用户指南](../guide/cli-quickstart.md)；单命令细节以 "
        "`rfauto <命令> --help` 为准（本页摘 help 首行）。",
        "",
    ]
    for node in tree:
        lines.append(f"## rfauto {node.name}")
        lines.append("")
        if node.help:
            lines.append(node.help)
            lines.append("")
        if node.is_group:
            lines.append(f"共 {node.count_leaves()} 条叶子命令。")
            lines.append("")
            lines.extend(_render_cli_nodes(node.children, f"rfauto {node.name}"))
        elif not node.help:
            lines.append("（见 `--help`）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", total


# ─── MCP 工具参考页（ast 枚举 + check_numbers 正则计数互证）───────────────

def collect_mcp_tools(checknum) -> list[tuple[str, str, str]]:
    """返回 [(模块名, 工具名, docstring 首行)]，按源文件与源码序。"""
    tools: list[tuple[str, str, str]] = []
    for path in checknum.mcp_source_files():
        src = path.read_text(encoding="utf-8")
        module = path.stem if path.stem != "mcp_server" else "mcp_server（facade）"
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if ast.unparse(dec).startswith("mcp.tool"):
                    doc = ast.get_docstring(node) or ""
                    tools.append((module, node.name, first_line(doc)))
                    break
    expected = checknum.count_mcp()
    if len(tools) != expected:
        raise RuntimeError(
            f"MCP 页 ast 枚举数 {len(tools)} != check_numbers.count_mcp() "
            f"{expected}（同源互证失败，拒绝出页）")
    return tools


def build_mcp_page(checknum) -> tuple[str, int]:
    tools = collect_mcp_tools(checknum)
    total = len(tools)
    lines: list[str] = [
        "# MCP 工具参考",
        "",
        f"> `@mcp.tool` 注册工具共 **{total}** 个（ast 枚举与 "
        "`scripts/check_numbers.py` 的 `count_mcp()` 装饰器正则计数构建时逐位"
        "互证）。本页由 `scripts/build_docs_pages.py` 机读生成，勿手改；"
        "逐工具可调用性双检见 `tests/unit/test_mcp_tool_consistency.py`。",
        "",
    ]
    by_module: dict[str, list[tuple[str, str]]] = {}
    for module, name, doc in tools:
        by_module.setdefault(module, []).append((name, doc))
    lines.append("| 工具 | 模块 | 说明 |")
    lines.append("|---|---|---|")
    for module, items in by_module.items():
        for name, doc in items:
            lines.append(f"| `{name}` | {md_cell(module)} | {md_cell(doc)} |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n", total


# ─── 计算器注册表参考页（CALCULATOR_REGISTRY.describe 同源）───────────────

def build_calculators_page(checknum) -> tuple[str, int, int]:
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    rows = CALCULATOR_REGISTRY.describe(include_experimental=True)
    n_plain = checknum.count_calculators()
    n_all = checknum.count_calculators_all()
    if len(rows) != n_all:
        raise RuntimeError(
            f"CALC 页 describe(include_experimental=True) 数 {len(rows)} != "
            f"check_numbers.count_calculators_all() {n_all}（同源互证失败）")
    n_exp = sum(1 for r in rows if r.get("experimental"))
    if n_exp != n_all - n_plain:
        raise RuntimeError(
            f"CALC 页实验键数 {n_exp} != 全键 {n_all} - 实注册 {n_plain}"
            "（同源互证失败）")

    lines: list[str] = [
        "# 计算器注册表参考",
        "",
        f"> `CALCULATOR_REGISTRY` 实注册 **{n_plain}** 个（含实验键共 "
        f"**{n_all}** 个；实验键默认不列、需显式开关）。与 "
        "`scripts/check_numbers.py` 的 `count_calculators()`/"
        "`count_calculators_all()` 构建时逐位互证。运行入口 "
        "`rfauto calc list` / `rfauto calc run <名> -p k=v`。"
        "本页由 `scripts/build_docs_pages.py` 机读生成，勿手改。",
        "",
        "数值只在确定性内核（LLM/agent 永不产生物理数字）；每键的输入表由 "
        "`tests/unit/test_physics_invariants.py` 物理不变量门逐键消费。",
        "",
    ]
    for row in rows:
        tag = "（实验）" if row.get("experimental") else ""
        lines.append(f"## {row['name']}{tag}")
        lines.append("")
        desc = re.sub(r"\s+", " ", str(row.get("description", ""))).strip()
        lines.append(desc or "（无描述）")
        lines.append("")
        params = row.get("params") or []
        if params:
            lines.append("| 参数 | 说明 | 必填 |")
            lines.append("|---|---|---|")
            for p in params:
                req = "是" if p.get("required") else "否"
                lines.append(
                    f"| `{md_cell(p.get('name'))}` | {md_cell(p.get('desc'))} "
                    f"| {req} |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n", n_plain, n_all


# ─── 模板库聚合页（docs/templates/*/meta.yaml 与 TEMPLATE_META 互证）──────

def build_templates_page(checknum) -> tuple[str, int]:
    import yaml

    metas: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(TEMPLATES_DOCS.glob("*/meta.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        metas.append((path.parent.name, data))

    expected = checknum.count_template_meta()
    if len(metas) != expected:
        raise RuntimeError(
            f"模板页 docs/templates/*/meta.yaml 数 {len(metas)} != "
            f"check_numbers.count_template_meta() {expected}（同源互证失败）")

    lines: list[str] = [
        "# 模板库",
        "",
        f"> 器件模板共 **{len(metas)}** 个（`docs/templates/*/meta.yaml` 聚合；"
        "与代码单源 `openems_templates.TEMPLATE_META` 键集/计数构建时互证，"
        "一致性另由 `tests/unit/test_template_meta_consistency.py` 钉死）。"
        "本页由 `scripts/build_docs_pages.py` 机读生成，勿手改；单模板物理"
        "细节（几何画法/标定史/真机锚）以仓内 `docs/templates/<名>/` 为准。",
        "",
        "## 总表",
        "",
        "| 模板 | f0 (GHz) | 端口 | 参数数 | 拓扑摘要 |",
        "|---|---|---|---|---|",
    ]
    for name, meta in metas:
        params = meta.get("params") or []
        topo = first_line(str(meta.get("topology", "")) or "")
        lines.append(
            f"| [{name}](#{name.lower()}) | {md_cell(meta.get('f0_ghz'))} | "
            f"{md_cell(meta.get('n_ports'))} | {len(params)} | {md_cell(topo)} |")
    lines.append("")
    for name, meta in metas:
        lines.append(f"## {name}")
        lines.append("")
        if meta.get("extraction"):
            lines.append(f"- **抽取判据**：{md_cell(meta['extraction'])}")
        substrate = meta.get("substrate") or {}
        if substrate:
            lines.append(
                f"- **基板**：er={md_cell(substrate.get('er'))}，"
                f"h_mm={md_cell(substrate.get('h_mm'))}")
        params = meta.get("params") or []
        if params:
            lines.append(
                "- **参数**：" + "、".join(f"`{p}`" for p in params))
        nominal = meta.get("nominal_params") or {}
        if nominal:
            items = "，".join(f"`{k}`={md_cell(v)}" for k, v in nominal.items())
            lines.append(f"- **名义参数**：{items}")
        if meta.get("topology"):
            lines.append(f"- **拓扑**：{md_cell(meta['topology'])}")
        if meta.get("smoke_note"):
            lines.append(f"- **冒烟注记**：{md_cell(meta['smoke_note'])}")
        if meta.get("mesh_note"):
            lines.append(f"- **网格注记**：{md_cell(meta['mesh_note'])}")
        if meta.get("campaign_capable") is not None:
            lines.append(
                f"- **战役精算能力**：{'可用' if meta.get('campaign_capable') else '受限'}"
                + ("".join(
                    f"；{md_cell(r)}" for r in (meta.get("campaign_capable_reasons") or []))
                   if not meta.get("campaign_capable") else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", len(metas)


# ─── 能力目录页（CLI 组 × MCP 模块同名映射；D4 能力目录生成器 mini）───────

def _norm_cap_key(name: str) -> str:
    """跨面同名归一键（CLI 组名与 MCP 模块名的横杠/下划线归一）。"""
    return name.strip().lower().replace("-", "_")


def build_capability_map_page(checknum) -> tuple[str, int, int]:
    """能力→入口统一目录（CLI×MCP 映射；确定性，零手写数字）。

    同名匹配是"引导性线索"而非强契约：横杠/下划线归一后同名即视为
    同域双入口；其余如实落"仅单侧"表，不硬凑。返回 (markdown,
    cli_total, mcp_total)。"""
    tree = collect_cli_tree()
    cli_total = sum(n.count_leaves() for n in tree)
    if cli_total != checknum.count_cli():
        raise RuntimeError(
            f"能力目录页 CLI 叶子数 {cli_total} != check_numbers.count_cli() "
            f"{checknum.count_cli()}（同源互证失败，拒绝出页）")
    tools = collect_mcp_tools(checknum)  # 内部已与 count_mcp() 互证
    mcp_counts: dict[str, int] = {}
    for module, _name, _doc in tools:
        mcp_counts[module] = mcp_counts.get(module, 0) + 1
    mcp_total = len(tools)

    mcp_by_norm = {_norm_cap_key(m): (m, c) for m, c in mcp_counts.items()}
    matched: set[str] = set()
    rows: list[tuple[str, int, str, str]] = []
    for node in sorted(tree, key=lambda n: n.name):
        hit = mcp_by_norm.get(_norm_cap_key(node.name))
        if hit is not None:
            matched.add(_norm_cap_key(node.name))
            mcp_cell = f"`{hit[0]}`（{hit[1]} 个）"
        else:
            mcp_cell = "—"
        rows.append((node.name, node.count_leaves(), mcp_cell, node.help))

    lines: list[str] = [
        "# 能力目录（CLI × MCP 入口映射）",
        "",
        f"> CLI 顶层 **{len(tree)}** 组 / **{cli_total}** 条叶子命令，"
        f"MCP 工具 **{mcp_total}** 个（分布在 {len(mcp_counts)} 个模块）。"
        "同名行=同域双入口（CLI 给人、MCP 给 agent）；“—”表示该域暂无"
        "同名另一侧入口。本页由 `scripts/build_docs_pages.py` 机读生成，"
        "勿手改；CLI 树与 check_numbers 同源互证，条目明细见"
        "[CLI 参考](cli.md)与[MCP 参考](mcp.md)。",
        "",
        "## 双入口域（CLI 组 ↔ MCP 同名模块）",
        "",
        "| CLI 组 | 叶数 | MCP 同名模块 | CLI 组说明 |",
        "|---|---|---|---|",
    ]
    n_dual = 0
    for name, leaves, mcp_cell, help_text in rows:
        if mcp_cell != "—":
            n_dual += 1
        lines.append(
            f"| `{name}` | {leaves} | {mcp_cell} | {md_cell(help_text)} |")
    lines += [
        "",
        f"双入口域共 **{n_dual}** 个。计算器键与器件模板另见"
        "[计算器注册表](calculators.md)与[模板库](../catalog/index.md)"
        "（数字构建时实测互证）。",
        "",
        "## 仅 MCP 侧模块（无同名 CLI 组）",
        "",
        "| 模块 | 工具数 |",
        "|---|---|",
    ]
    only_mcp = sorted(
        (m, c) for norm_m, (m, c) in mcp_by_norm.items()
        if norm_m not in matched)
    for module, cnt in only_mcp:
        lines.append(f"| `{module}` | {cnt} |")
    lines += [
        "",
        f"共 **{len(only_mcp)}** 个模块（facade 直定义工具也在此列，"
        "如实分标）。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n", cli_total, mcp_total


# ─── 首页数字条（AUTO-NUMBERS 标记块回填）────────────────────────────────

def numbers_strip(checknum) -> str:
    tests_n, tests_src = checknum.count_tests()
    cli_n = checknum.count_cli()
    mcp_n = checknum.count_mcp()
    calc_n = checknum.count_calculators()
    calc_all = checknum.count_calculators_all()
    tmpl_n = checknum.count_template_meta()
    anchors_n = checknum.count_anchors()
    lines = [
        "## 代码面数字（构建时实测）",
        "",
        "以下数字由 `scripts/build_docs_pages.py` 构建时实测回填（与 "
        "`scripts/check_numbers.py` 同源，零手写——#97）:",
        "",
        "| 维度 | 数量 |",
        "|---|---|",
        f"| 全量门测试 | {tests_n} |",
        f"| CLI 叶子命令 | {cli_n} |",
        f"| MCP 工具 | {mcp_n} |",
        f"| 确定性计算器（含实验键） | {calc_n}（{calc_all}） |",
        f"| 器件模板 | {tmpl_n} |",
        f"| 标定锚注册表 | {anchors_n} |",
        "",
        f"（tests 计数来源：{tests_src}）",
        "",
    ]
    return "\n".join(lines)


def fill_index_strip(checknum, docs_site: Path) -> None:
    index_path = docs_site / "index.md"
    text = index_path.read_text(encoding="utf-8")
    start = text.find(AUTO_START)
    end = text.find(AUTO_END)
    if start < 0 or end < 0 or end < start:
        raise RuntimeError(
            f"{index_path} 缺 {AUTO_START}/{AUTO_END} 标记块（数字条回填锚）")
    new_text = (
        text[: start + len(AUTO_START)] + "\n" + numbers_strip(checknum)
        + text[end:]
    )
    index_path.write_text(new_text, encoding="utf-8")


def read_index_strip(docs_site: Path) -> str:
    """读出已提交 index.md 的标记块内容（测试锚用）。"""
    text = (docs_site / "index.md").read_text(encoding="utf-8")
    start = text.find(AUTO_START)
    end = text.find(AUTO_END)
    if start < 0 or end < 0 or end < start:
        raise RuntimeError(f"{docs_site / 'index.md'} 缺数字条标记块")
    return text[start + len(AUTO_START): end].strip("\n")


# ─── 同步既有文档资产 ─────────────────────────────────────────────────────

def _regenerate_gallery() -> bytes | None:
    """E-11（2026-10-04）：build 期直接调 gallery_export.write_gallery 重生成。

    原 sync 只拷贝 docs/gallery/index.html 静态件——该件缺位（干净检出/
    清理后）时画廊静默消失、需另跑 gallery_export 才自愈（双命令不自愈）。
    改为 build 期以确定口径（无 stamp）重生成到临时文件、读出字节再落
    站点（临时目录随上下文回收，路径不可外带），单命令自愈；
    gallery_export 装载失败/生成异常如实返回 None 回退静态拷贝
    （best-effort，不阻塞主构建）。逐字节确定性由 test_docs_site 的
    gallery 保鲜比对钉死（同输入两次生成逐字节一致）。
    """
    import tempfile

    try:
        spec = importlib.util.spec_from_file_location(
            "_pr10_gallery_export",
            Path(__file__).resolve().parent / "gallery_export.py")
        if spec is None or spec.loader is None:  # pragma: no cover - 防御
            raise RuntimeError("无法装载 gallery_export.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="pr10_gallery_") as tmp:
            out = module.write_gallery(Path(tmp) / "index.html")
            return Path(out).read_bytes()
    except Exception as exc:  # best-effort 自愈，失败回退拷贝
        print(f"[warn] 画廊重生成失败，回退 docs/gallery/index.html 静态拷贝: "
              f"{exc!r}", file=sys.stderr)
        return None


def sync_assets(docs_site: Path) -> list[str]:
    written: list[str] = []
    for src_rel, dst_rel in SYNC_DIRS:
        src_dir = REPO_ROOT / src_rel
        dst_dir = docs_site / dst_rel
        dst_dir.mkdir(parents=True, exist_ok=True)
        for md in sorted(src_dir.glob("*.md")):
            dst = dst_dir / md.name
            banner = SYNC_BANNER.format(src=f"{src_rel}/{md.name}")
            dst.write_text(banner + md.read_text(encoding="utf-8"),
                           encoding="utf-8")
            written.append(str(dst.relative_to(docs_site)))
    for src_rel, dst_rel in SYNC_STATIC:
        dst = docs_site / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst_rel == "gallery/index.html":
            fresh = _regenerate_gallery()
            if fresh is not None:
                dst.write_bytes(fresh)  # 字节级落盘（LF/UTF-8 保真，无换行翻译）
                written.append(dst_rel)
                continue
        src = REPO_ROOT / src_rel
        if not src.exists():  # 画廊等可选资产缺位且重生成失败时如实跳过
            continue
        shutil.copyfile(src, dst)
        written.append(str(dst.relative_to(docs_site)))
    return written


# ─── 主流程 ───────────────────────────────────────────────────────────────

def build_all(out_dir: Path, index_src: Path | None = None) -> dict[str, int]:
    """全量重建站点内容页，返回各页计数 manifest（测试同源锚）。

    index_src：手写首页母本来源（缺省=已提交 docs_site/index.md）。out_dir
    无 index.md 时（临时目录重建）先从母本复制再回填数字条——手写壳层只有
    一份单源，生成器只负责其中 AUTO-NUMBERS 标记块。"""
    checknum = load_check_numbers()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reference").mkdir(exist_ok=True)
    (out_dir / "catalog").mkdir(exist_ok=True)
    if not (out_dir / "index.md").exists():
        src_index = index_src if index_src is not None else DOCS_SITE_DEFAULT
        shutil.copyfile(src_index / "index.md", out_dir / "index.md")

    cli_md, cli_n = build_cli_page(checknum)
    mcp_md, mcp_n = build_mcp_page(checknum)
    calc_md, calc_n, _calc_all = build_calculators_page(checknum)
    tmpl_md, tmpl_n = build_templates_page(checknum)
    cap_md, _cap_cli, _cap_mcp = build_capability_map_page(checknum)

    (out_dir / "reference" / "cli.md").write_text(cli_md, encoding="utf-8")
    (out_dir / "reference" / "mcp.md").write_text(mcp_md, encoding="utf-8")
    (out_dir / "reference" / "calculators.md").write_text(calc_md,
                                                          encoding="utf-8")
    (out_dir / "reference" / "capabilities.md").write_text(cap_md,
                                                           encoding="utf-8")
    (out_dir / "catalog" / "index.md").write_text(tmpl_md, encoding="utf-8")
    fill_index_strip(checknum, out_dir)
    sync_assets(out_dir)

    return {
        "cli": cli_n,
        "mcp": mcp_n,
        "calculators": calc_n,
        "templates": tmpl_n,
        "tests": checknum.count_tests()[0],
        "anchors": checknum.count_anchors(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PR-10 文档站机读页生成器")
    parser.add_argument("--out", type=str, default=None,
                        help="输出目录（缺省 docs_site）")
    args = parser.parse_args(argv)
    out = Path(args.out) if args.out else DOCS_SITE_DEFAULT
    manifest = build_all(out)
    print(f"build_docs_pages: rebuilt {out}")
    for key in sorted(manifest):
        print(f"  {key} = {manifest[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
