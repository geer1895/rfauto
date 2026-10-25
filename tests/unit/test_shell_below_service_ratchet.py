"""壳层 below-service 禁入棘轮（aurora_h W2-S1/T8，2026-10-19，立项#2）。

R1 架构审计（runs/aurora_h/R1_arch_audit_v3.md §六/§三.1）：cli 直连
service 以下 15 边、mcp_tools 13 边（含审计漏计的 diagnose→measurement
2 边）。T8 收口 4 条（_core lifespan 两行删除走 service.api 覆盖面、
diagnose 相关性改 service.api.correlate_files 单点）后余 24 条转入
.importlinter 第三契约 ignore_imports 白名单（**只收不放**）。

本文件与 .importlinter 契约（shell-below-service-no-direct-imports）
互为表里，钉三道门：

1. 契约形态钉死：source_modules 恰为 cli+mcp_tools、forbidden_modules
   覆盖 service 以下全部八层——契约本身不许被悄悄削弱。
2. 白名单棘轮：契约 ignore_imports 与本文件 FROZEN_WHITELIST 逐条相等
   ——加白名单（放）或删边不同步改两边（收）都红。
3. 实树边集钉死：AST 全量扫描 cli/mcp_tools 的 below-service 直连边
   与 FROZEN_WHITELIST 逐条相等——新增直连即红（负控制：任意 cli 文件
   函数体加一行 ``from rfauto.core.synthesis import x`` 本测试与
   lint-imports 双红）。

口径：与 import-linter 同口径——函数体内 lazy import 计边；
``if TYPE_CHECKING`` 与 try/except ImportError 内也计（import-linter
默认不豁免）；``from pkg import name`` 解析到 pkg.name 真实子模块。
白名单条目=「源模块 -> 目标模块」对（目标取实际命中子模块），与
importlinter ignore_imports 语法逐字同构。

白名单条目的逐条理由见 .importlinter 契约注释块（两类：待包 service /
显式豁免）；删除条目时必须同笔改两处（本文件 + .importlinter）。
"""

from __future__ import annotations

import ast
import configparser
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "rfauto"
_IMPORTLINTER = _REPO_ROOT / ".importlinter"
_CONTRACT_SECTION = "importlinter:contract:shell-below-service-no-direct-imports"

#: service 以下八层（内核立规注记 规则 3 分层序：cli/mcp_server → service →
#: linkage/optimization/models → adapters → measurement → pipeline → infra → core）。
BELOW_SERVICE_LAYERS = (
    "rfauto.linkage",
    "rfauto.optimization",
    "rfauto.models",
    "rfauto.adapters",
    "rfauto.measurement",
    "rfauto.pipeline",
    "rfauto.infra",
    "rfauto.core",
)

#: 棘轮冻结白名单（2026-10-19 T8 实测 24 条；只可删不可加，删除须同笔
#: 同步 .importlinter 的 ignore_imports）。
FROZEN_WHITELIST = frozenset({
    # ── cli（16 条）──
    "rfauto.cli.domains._core -> rfauto.infra.logging",
    "rfauto.cli.domains.agent_kicad -> rfauto.adapters.kicad_pcell",
    "rfauto.cli.domains.agent_kicad -> rfauto.adapters.kicad_drc",
    "rfauto.cli.domains.calc_vna -> rfauto.core.closed_form_oracle",
    # aurora_k K8 2026-10-23：THRU 去嵌/器件指标只读出口（A-11 同款裁定
    # ——em deembed/metrics 零逻辑薄壳直连 core/deembed K8 扩展纯函数面，
    # 读 Touchstone+装配即薄 I/O，无状态零写盘；反馈 F6/P14）
    "rfauto.cli.domains.em -> rfauto.core.deembed",
    "rfauto.cli.domains.dag -> rfauto.core.compose.dag_schema",
    "rfauto.cli.domains.dag -> rfauto.pipeline.dag_runner",
    "rfauto.cli.domains.firmware -> rfauto.core.firmware_export",
    "rfauto.cli.domains.jobs -> rfauto.infra.report",
    "rfauto.cli.domains.scattered -> rfauto.core.pcell_dsl",
    "rfauto.cli.domains.stats -> rfauto.core.manufacturing_stats",
    "rfauto.cli.domains.synth -> rfauto.core.synthesis",
    "rfauto.cli.domains.synth -> rfauto.core.block_spec",
    "rfauto.cli.domains.synth -> rfauto.core.budget",
    "rfauto.cli.domains.workflow -> rfauto.optimization.sweep_backend",
    "rfauto.cli.domains.workflow -> rfauto.optimization.optimizer",
    # ── mcp_tools（9 条）──
    "rfauto.mcp_tools._core -> rfauto.models.registry",
    "rfauto.mcp_tools.optim -> rfauto.optimization.sweep_backend",
    "rfauto.mcp_tools.report_bench -> rfauto.infra.report",
    "rfauto.mcp_tools.resources -> rfauto.infra.run_store",
    "rfauto.mcp_tools.resources -> rfauto.core.materials",
    "rfauto.mcp_tools.runs -> rfauto.infra.diagnosis",
    "rfauto.mcp_tools.synth -> rfauto.core.synthesis",
    "rfauto.mcp_tools.synth -> rfauto.core.block_spec",
    "rfauto.mcp_tools.synth -> rfauto.core.budget",
})


def _load_contract() -> dict[str, list[str]]:
    cp = configparser.ConfigParser()
    read = cp.read(_IMPORTLINTER, encoding="utf-8")
    assert read, f".importlinter 读取失败: {_IMPORTLINTER}"
    assert cp.has_section(_CONTRACT_SECTION), (
        f"契约节缺失（不得改名/删除）: [{_CONTRACT_SECTION}]")
    section = cp[_CONTRACT_SECTION]

    def _lines(key: str) -> list[str]:
        raw = section.get(key, "")
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]

    return {
        "sources": _lines("source_modules"),
        "forbidden": _lines("forbidden_modules"),
        "ignore": [ln for ln in _lines("ignore_imports")
                   if not ln.startswith("#")],
    }


def _module_name(path: Path) -> str:
    rel = path.relative_to(_SRC).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["rfauto", *parts])


def _resolve_targets(node: ast.ImportFrom | ast.Import) -> list[str]:
    """一条 import 语句命中的 below-service 目标模块（子模块优先）。"""
    hits: list[str] = []
    candidates: list[str] = []
    if isinstance(node, ast.ImportFrom):
        if node.level:  # 相对导入只指向包内（cli/mcp_tools 自身），不越层
            base = node.module or ""
            for name in node.names:
                candidates.append(f"{base}.{name.name}" if base else name.name)
            # 相对导入目标必在本包子树内，不可能命中 below-service 层
            return []
        base = node.module or ""
        if not base.startswith("rfauto"):
            return []
        for name in node.names:
            if name.name == "*":
                candidates.append(base)
            else:
                candidates.append(f"{base}.{name.name}")
                candidates.append(base)
    else:
        for alias in node.names:
            if alias.name.startswith("rfauto"):
                candidates.append(alias.name)
    for cand in candidates:
        parts = cand.split(".")[1:]  # _SRC 已是 rfauto/ 目录
        p = _SRC.joinpath(*parts)
        if p.with_suffix(".py").exists() or (p / "__init__.py").exists():
            for layer in BELOW_SERVICE_LAYERS:
                if cand == layer or cand.startswith(layer + "."):
                    hits.append(cand)
                    break
    return hits


def _observed_edges() -> set[str]:
    """AST 全量扫描 cli/mcp_tools 的 below-service 直连边（含函数体内 lazy）。"""
    edges: set[str] = set()
    for pkg in ("cli", "mcp_tools"):
        for py in sorted((_SRC / pkg).rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            src = _module_name(py)
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for target in _resolve_targets(node):
                        edges.add(f"{src} -> {target}")
    return edges


def test_contract_shape_pinned() -> None:
    """契约形态：sources 恰为两壳层、forbidden 覆盖八层（不许削弱）。"""
    contract = _load_contract()
    assert sorted(contract["sources"]) == ["rfauto.cli", "rfauto.mcp_tools"], (
        f"source_modules 被改动: {contract['sources']}")
    for layer in BELOW_SERVICE_LAYERS:
        assert layer in contract["forbidden"], (
            f"forbidden_modules 丢失下层 {layer}（契约被削弱）")


def test_ignore_imports_equals_frozen() -> None:
    """白名单棘轮：契约 ignore_imports 与冻结清单逐条相等（只收不放）。"""
    actual = set(_load_contract()["ignore"])
    frozen = set(FROZEN_WHITELIST)
    added = sorted(actual - frozen)
    removed = sorted(frozen - actual)
    assert not added and not removed, (
        "白名单棘轮失守（只收不放）：\n"
        f"  新增（放，禁止）: {added or '无'}\n"
        f"  删除（收，允许但须同笔改 FROZEN_WHITELIST）: {removed or '无'}\n"
        "  收口一条边时：删 .importlinter 对应行 + 删本文件 FROZEN_WHITELIST "
        "对应条目，两处同笔。")


def test_observed_edges_equal_frozen() -> None:
    """实树边集棘轮：AST 实测直连边与冻结清单逐条相等（新增直连即红）。"""
    observed = _observed_edges()
    frozen = set(FROZEN_WHITELIST)
    new_violations = sorted(observed - frozen)
    stale = sorted(frozen - observed)
    assert not new_violations, (
        "cli/mcp_tools 出现白名单外的 below-service 直连边（分层契约 "
        "AGENTS 规则 3：壳层业务消费一律走 service）：\n  "
        + "\n  ".join(new_violations)
        + "\n  新增直连须改走 service 面；确需直连的走契约白名单评审。")
    assert not stale, (
        "白名单存在失效条目（代码里已无对应直连边）——收口后请同笔从 "
        ".importlinter ignore_imports 与本文件 FROZEN_WHITELIST 删除:\n  "
        + "\n  ".join(stale))
