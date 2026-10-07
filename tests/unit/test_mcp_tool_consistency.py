"""§10.20 补强⑮：MCP 工具描述一致性（只读 mcp_server.py，不强判语义）。

口径（全部确定性、无网络、无 LLM）：
- 源码 @mcp.tool 装饰器数（实测）== 运行时注册工具数（fastmcp list_tools）；
- 源码被装饰函数名集合 == 注册工具名集合；工具名唯一、非空；
- 每个工具都有非空描述；
- docstring Args 段记录但实现签名不存在的参数（幽灵参数）= 明显不符，
  硬断言为空；
- 实现签名有、docstring 未记录的参数只列出（report-only），不臆断语义；
- @mcp.resource 只读资源不被计入工具；
- 逐工具可调用性烟测（静态）：函数体全局名引用与惰性 import 目标
  必须可解析（diagnose 死壳实证的系统性盲区，confirm_2 第 1 条）。

记 18 个工具，本文件以源码/运行时实测为准。
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import dis
import importlib
import inspect
import json
import re
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER_PY = REPO_ROOT / "src" / "rfauto" / "mcp_server.py"


def _mcp_source_files() -> list[Path]:
    """AU-1 批3 拆分（2026-09-30）：mcp_server 为 facade + mcp_tools/ 工具组包
    ——源码口径聚合 facade 与全部工具组模块（注册面正则/AST 双检不漏域）。"""
    return [MCP_SERVER_PY, *sorted(MCP_SERVER_PY.parent.glob("mcp_tools/*.py"))]

_TOOL_DECORATOR_RE = re.compile(r"^\s*@mcp\.tool\b", re.MULTILINE)
_RESOURCE_DECORATOR_RE = re.compile(r"^\s*@mcp\.resource\(", re.MULTILINE)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
_ARGS_ENTRY_RE = re.compile(r"^\s{4,}([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:")
_SECTION_END_RE = re.compile(r"^(Args|Returns|Raises|Examples?|Yields|Note|Notes):\s*$")

# 记录值，仅作交叉核对；实测不符时断言会直接暴露
# （18→19：2026-09-13 export_report_pdf 工具入库，/090e631）
# （19→36：2026-09-13 WP3.3 MCP 工具面全量开放 +17——模板库 2/战役 3/
#   数据集 2/bands 10（D9 归口）；数字待主控合流轮同步）
# （36→62：2026-09-15 cli-mcp-api-shell-bundle +26——回归门 2（goldset/agentbench）
#   /多 Agent 4 内核工具+multi_agent_run/autotune_self_verify/uq 3/farfield 2/
#   kicad 2/electrothermal/parasitic/topology/dataset 4/vna_offline_replay/
#   report_narrative/rationale 2；数字待主控合流轮同步）
# （62→64：2026-09-15 F2⑥ RAG 只读检索薄壳 +2——rag_query/rag_explain，词法
#   BM25、citation 可溯；零逻辑转发 rag_service 一步式包装）
# （64→67：2026-09-15 审查接线层装车 +3——self_heal_run（F5 只读自愈环）/
#   log_digest（WP3.6 LogDistiller）/dispersion_report（D1 色散适应性）；
#   零逻辑转发 self_heal_service / dispersion_service 信封）
# （67→73：2026-09-18 w1a-shell-front W1⑫ 注册表数据库薄壳 +6——db_init/
#   db_migrate/db_status/db_reindex_runs/db_query/db_analytics_attach；
#   零逻辑转发 db_service，query 走只读 SELECT 白名单信封）
# （73→78：2026-09-18 w2i-shell-back W2⑨ 槽线与过渡薄壳 +5——slotline_analysis/
#   slotline_synthesis/msl_slot_transition_design/marchand_balun_design/
#   marchand_two_section_synthesis；零逻辑转发 slotline_service，越域拒绝进信封）
# （78→80：2026-09-18 fix-importer 审查修复队列增量③ +2——discover_workdir_runs/
#   import_workdir_runs；工作目录形态真机产物（无 meta.json）导入器薄壳，零逻辑
#   转发 dataset_service.discover_workdir_candidates/import_workdir_runs）
# （83→86：2026-09-24 df6_dp2diag DP-2 耦合矩阵诊断三件套薄壳 +3——
#   cm_diagnose_q/cm_extract_refine/cm_cat_critique；零逻辑转发 diagnosis_service）
# （87→88：2026-09-24 df6_dp11vna DP-11 En 相关性报告薄壳 +1——vna_en_report；
#   零逻辑转发 vna_service.vna_en_report）
# （88→89：2026-09-24 df6_dp1p2 DP-1 MMT 秒级段表求解薄壳 +1——mmt_solve；
#   零逻辑转发 mmt_service.solve_mmt）
# （100→102：2026-09-24 df6_dp3anchors DP-3 物理标定锚注册表薄壳 +2——
#   anchors_list/anchors_inspect；零逻辑转发 anchors_service）
# （102→103：2026-09-25 df7_t2 SI 通道报告薄壳 +1——si_channel_report；
#   零逻辑转发 si_channel_service.si_channel_report）
# （103→105：2026-09-25 df7_f3lake runs 湖薄壳 +2——lake_query_runs/
#   lake_pack_campaign；零逻辑转发 lake_service，index/verify/restore 属
#   本地运维面不进 MCP 最小面）
# （105→106：2026-09-26 df7wire R4 渲染前声明式几何约束一次求解薄壳 +1——
#   render_constraint_check；零逻辑转发 render_constraint_service）
# （106→109：2026-09-26 me17a-shell1 ME-17a 接线批第一组三工具 +3——
#   import_solid_payload/certify_design/port_gate；零逻辑转发
#   solid_import_service/certify_design/port_gate_service）
# （109→110：2026-09-26 qw123 QW-2 知识库统一检索 +1——search_knowledge；
#   零逻辑转发 knowledge_service.search_knowledge）
# （110→113：2026-09-26 ge-fbp2 F-B P2 PI/PDN 三工具 +3——pdn_analyze/
#   pdn_select/pdn_gate；零逻辑转发 pdn_service 同名函数）
# （113→116：2026-09-26 ge-fcp2 F-C P2 器件老化漂移三工具 +3——
#   aging_simulate/aging_verdict/aging_report；零逻辑转发 aging_service
#   同名函数）
# （116→118：2026-09-26 ge-code3 +2——afs_plan（M-3 AFS 扫频计划纯计划面
#   薄壳，零逻辑转发 afs_service.afs_sweep_plan）+ read_hfss_touchstone_comments
#   （ME-10' HFSS 注释块直读薄壳，零逻辑转发 interop_service 同名函数）
# （118→120：2026-09-28 remote-v0 +2——remote_probe_machine/remote_machine_status
#   （多机协同只读探活/状态薄壳，零逻辑转发 remote_service 同名函数）
# （120→123：2026-09-28 me17b-wire +3——even_odd_report/mcts_search/
#   inverse_prefilter（ME-17b 接线批第二组，零逻辑转发 even_odd_service/
#   mcts_search/inverse_prefilter 同名函数；agent 原语 typed tool call）
# （123→132：2026-10-04 x3-wiring +9——W7 台账①态零消费内核接线批：
#   adc_interleave_spurs/jitter_budget_snr（零逻辑转发 adc_budget_service
#   新增函数）+ emc_cispr_band_params/emc_cispr_detect/
#   emc_ground_spacing_check/emc_cm_radiated_budget（零逻辑转发新建
#   emc_service）+ metasurface_coding_pattern/metasurface_quant_loss_db
#   （零逻辑转发新建 metasurface_service）+ com_pam4_run（零逻辑转发
#   si_channel_service 新增函数，挂 si_lake 工具组）
# （132→134：2026-10-05 W1 孤儿接线批 +2——error_hints_lookup（零逻辑转发
#   error_hints_service，挂 explain 工具组）+ run_monitor（零逻辑转发
#   runtime_monitor_service，挂 runs 工具组）
# （134→137：2026-10-05 W2 Phase 2 +3——run_campaign（VI-2 战役执行器，
#   挂 specs_campaign 组）+ recommend_templates（VI-3 推荐器同组）+
#   uq_rare_yield（XD-11 稀有失效 IS，挂 uq 组）
# （137→145：2026-10-05 W3 Phase 3 +8——env_reliability 单文件八工具
#   （F-10 六服务壳 MCP 面，W3-D）
# （145→146：2026-10-05 W5 Phase 5 +1——get_guidelines_for（EC-6
#   guidelines_service 三源检索薄壳，W5-D）
# （146→149：2026-10-06 W6 +3——start_tune/run_sweep（SN-16，W6-A）+
#   preflight_run（D-07，W6-E）
_LEDGER_DECLARED_TOOL_COUNT = 149


def _decorated_function_names(source: str, decorator_re: re.Pattern[str]) -> list[str]:
    """按装饰器行定位其后第一个 def 的名字（确定性、不依赖 AST 解析顺序）。"""
    lines = source.splitlines()
    names: list[str] = []
    for index, line in enumerate(lines):
        if not decorator_re.match(line):
            continue
        for follow in lines[index + 1:]:
            match = _DEF_RE.match(follow)
            if match:
                names.append(match.group(1))
                break
    return names


def _documented_args(fn: Any) -> list[str]:
    """解析 docstring 的 Args 段参数名（inspect.getdoc 已做 dedent）。"""
    doc = inspect.getdoc(fn) or ""
    documented: list[str] = []
    in_args = False
    for line in doc.splitlines():
        if line.strip() == "Args:":
            in_args = True
            continue
        if in_args and _SECTION_END_RE.match(line.strip()):
            break
        if in_args:
            match = _ARGS_ENTRY_RE.match(line)
            if match:
                documented.append(match.group(1))
    return documented


def _schema_params(tool: Any) -> set[str]:
    schema = tool.parameters or {}
    return set(schema.get("properties", {}))


def _audit(mcp_tools: list[Any]) -> dict[str, Any]:
    """一致性审计：幽灵参数（硬判）/ 未记录参数（report-only）/ 空描述。"""
    names = [t.name for t in mcp_tools]
    phantom_args: list[tuple[str, str]] = []
    undocumented: dict[str, list[str]] = {}
    missing_descriptions: list[str] = []
    for tool in mcp_tools:
        params = _schema_params(tool)
        documented = set(_documented_args(tool.fn))
        for arg in sorted(documented - params):
            phantom_args.append((tool.name, arg))
        leftover = sorted(params - documented)
        if leftover:
            undocumented[tool.name] = leftover
        if not (tool.description or "").strip():
            missing_descriptions.append(tool.name)
    return {
        "count": len(mcp_tools),
        "names": names,
        "duplicate_names": sorted({n for n in names if names.count(n) > 1}),
        "empty_names": [n for n in names if not n.strip()],
        "phantom_args": phantom_args,
        "undocumented_params": undocumented,
        "missing_descriptions": missing_descriptions,
    }


# ─── 逐工具可调用性烟测（静态：不执行工具体，零副作用） ──────────────────────
#
# 盲区来源：diagnose 工具惰性 `from rfauto.infra.diagnosis import run_diagnosis`
# 引用了不存在的名字——import mcp_server 成功、注册成功、描述/签名全过，
# 调用即 ImportError。描述/签名类测试对此类死壳天然盲，故补两条静态检查：
# ① LOAD_GLOBAL 名字解析（dis 逐指令，只取真全局查找；LOAD_ATTR/局部名不计，
#    避免 co_names 混入属性名造成误报）；
# ② 函数体内惰性 import 目标解析（AST ImportFrom/Import → import_module +
#    hasattr）。选静态而非"最小参数探测调用"：62 工具含 create_run/kicad/
#    真机求解等 mutating 工具，探测调用不安全且不确定。


def _iter_code_tree(code: types.CodeType) -> Any:
    """递归产出代码对象及其嵌套作用域（推导式/lambda/内层 def）。"""
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _iter_code_tree(const)


def _unresolved_load_globals(fn: Any) -> list[str]:
    """函数体（含嵌套作用域）LOAD_GLOBAL 的名字中不能在 globals∪builtins 解析者。"""
    module_globals = fn.__globals__
    unresolved: set[str] = set()
    for code in _iter_code_tree(fn.__code__):
        for instruction in dis.get_instructions(code):
            if instruction.opname != "LOAD_GLOBAL":
                continue
            name = instruction.argval
            if name not in module_globals and not hasattr(builtins, name):
                unresolved.add(name)
    return sorted(unresolved)


def _module_level_function_node(
        trees: list[ast.Module], name: str) -> ast.AST | None:
    """模块顶层同名函数节点（工具函数均为顶层 def，不下钻嵌套定义；
    AU-1 拆分后在 facade+mcp_tools 全部源码树上查找）。"""
    for tree in trees:
        for node in tree.body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name):
                return node
    return None


def _lazy_import_targets(fn_node: ast.AST) -> list[tuple[str, str | None]]:
    """函数体内惰性 import 的 (模块, 目标名或 None) 列表；`import *` 跳过。"""
    targets: list[tuple[str, str | None]] = []
    for node in ast.walk(fn_node):
        if isinstance(node, ast.ImportFrom) and node.module:
            targets.extend(
                (node.module, alias.name) for alias in node.names if alias.name != "*"
            )
        elif isinstance(node, ast.Import):
            targets.extend((alias.name, None) for alias in node.names)
    return targets


def _import_target_issue(module: str, name: str | None) -> str | None:
    """解析单个 import 目标：None=可解析（或第三方缺失 skip）；str=死引用。

    rfauto 自有模块导入失败硬判（代码缺陷）；第三方依赖缺失不硬判
    （环境限制，且该工具真调用时同样受限，不属于本测试的盲区口径）。
    """
    try:
        module_obj = importlib.import_module(module)
    except Exception as exc:  # 导入失败形态多样（缺依赖/license/语法），按来源分流
        if module.split(".")[0] == "rfauto":
            return f"rfauto 模块导入失败: {module}: {exc!r}"
        return None
    if name is not None and not hasattr(module_obj, name):
        return f"'{name}' 不存在于 {module}（死 import 目标）"
    return None


def _callability_issues(tool: Any, trees: list[ast.Module]) -> list[str]:
    """单工具的全部死引用（全局名 + 惰性 import 目标），空列表=可调用。"""
    fn = tool.fn
    issues = [
        f"LOAD_GLOBAL 名字不可解析: {name}（NameError 隐患）"
        for name in _unresolved_load_globals(fn)
    ]
    fn_node = _module_level_function_node(trees, fn.__name__)
    if fn_node is None:
        return [*issues, f"源码顶层未找到工具函数 def: {fn.__name__}"]
    for module, name in _lazy_import_targets(fn_node):
        issue = _import_target_issue(module, name)
        if issue:
            issues.append(issue)
    return issues


@pytest.fixture(scope="module")
def source_text() -> str:
    # AU-1 批3 拆分：facade + mcp_tools/ 工具组模块聚合（正则口径按行匹配，
    # 拼接不破坏行首语义；断言本身零改动）。
    return "\n".join(
        p.read_text(encoding="utf-8") for p in _mcp_source_files())


@pytest.fixture(scope="module")
def source_trees() -> list[ast.Module]:
    """按文件解析的源码树（`from __future__` 每文件必须居首，不可拼接解析）。"""
    return [ast.parse(p.read_text(encoding="utf-8"))
            for p in _mcp_source_files()]


@pytest.fixture(scope="module")
def mcp_tools() -> list[Any]:
    from rfauto.mcp_server import mcp

    return asyncio.run(mcp.list_tools())


@pytest.fixture(scope="module")
def mcp_function_resources() -> list[Any]:
    """list_resources() 中函数背书的资源（D-02，2026-10-04）。

    fastmcp 3.x list_resources 会附加合成 Prefab 渲染资源（无 .fn），
    本守卫只覆盖 @mcp.resource 装饰的函数资源（死壳盲区与工具同源：
    注册期不炸、调用期才 ImportError）。
    """
    from rfauto.mcp_server import mcp

    resources = asyncio.run(mcp.list_resources())
    return [r for r in resources if hasattr(r, "fn")]


class TestMcpToolRegistryConsistency:
    """源码装饰器 vs 运行时注册：数量/名字/描述一致性。"""

    def test_source_decorator_count_matches_registered(self, source_text, mcp_tools):
        source_names = _decorated_function_names(source_text, _TOOL_DECORATOR_RE)
        assert len(source_names) == len(mcp_tools)
        assert len(mcp_tools) == _LEDGER_DECLARED_TOOL_COUNT

    def test_source_function_names_equal_registered_names(self, source_text, mcp_tools):
        source_names = set(_decorated_function_names(source_text, _TOOL_DECORATOR_RE))
        registered = {t.name for t in mcp_tools}
        assert source_names == registered

    def test_tool_names_unique_and_nonempty(self, mcp_tools):
        audit = _audit(mcp_tools)
        assert audit["duplicate_names"] == []
        assert audit["empty_names"] == []

    def test_every_tool_has_nonempty_description(self, mcp_tools):
        audit = _audit(mcp_tools)
        assert audit["missing_descriptions"] == []
        for tool in mcp_tools:
            assert tool.description.strip()


class TestMcpToolSignatureDescriptionAlignment:
    """描述与实现签名：幽灵参数硬判；未记录参数只列出，不强判语义。"""

    def test_documented_args_exist_in_signature(self, mcp_tools):
        audit = _audit(mcp_tools)
        # docstring 记录但签名不存在的参数 = 明显不符
        assert audit["phantom_args"] == []

    def test_param_partition_is_complete_and_deterministic(self, mcp_tools):
        audit = _audit(mcp_tools)
        assert _audit(mcp_tools) == audit  # 两次审计结果一致（确定性）
        for tool in mcp_tools:
            documented = set(_documented_args(tool.fn))
            undocumented = set(audit["undocumented_params"].get(tool.name, []))
            assert documented | undocumented == _schema_params(tool)
            assert documented.isdisjoint(undocumented)

    def test_undocumented_params_report_only_lists_real_params(self, mcp_tools):
        audit = _audit(mcp_tools)
        by_name = {t.name: t for t in mcp_tools}
        for name, params in audit["undocumented_params"].items():
            # report-only：不判语义，只保证列出的都确实是该工具的真实参数
            assert name in by_name
            assert set(params) <= _schema_params(by_name[name])


class TestMcpResourcesNotCountedAsTools:
    """@mcp.resource 只读资源与 @mcp.tool 分离，不得计入工具数。"""

    def test_resource_decorators_not_counted_as_tools(self, source_text, mcp_tools):
        resource_names = _decorated_function_names(source_text, _RESOURCE_DECORATOR_RE)
        registered = {t.name for t in mcp_tools}
        assert resource_names
        assert registered.isdisjoint(resource_names)


class TestMcpToolBodyCallability:
    """逐工具可调用性烟测：62 个工具函数体的引用必须全部可解析。

    背景（confirm_2 第 1 条）：diagnose 工具引用不存在的 run_diagnosis，
    注册期不炸、描述/签名检查全过、调用即 ImportError——描述/签名类
    测试对此系统性盲。本组静态检查（不执行工具体，零副作用）堵两类
    死引用：
    - 全局名：LOAD_GLOBAL 名字必须能在模块 globals ∪ builtins 解析；
    - 惰性 import：`from M import name` 的目标必须真实存在。
    新增工具天然纳入覆盖（遍历运行时注册表，不靠手维护清单）。
    """

    def test_load_global_names_resolve_for_every_tool(self, mcp_tools):
        offenders = {
            tool.name: _unresolved_load_globals(tool.fn)
            for tool in mcp_tools
            if _unresolved_load_globals(tool.fn)
        }
        assert offenders == {}, (
            f"{len(offenders)} 个工具存在 NameError 隐患（LOAD_GLOBAL 不可解析）: {offenders}"
        )

    def test_lazy_import_targets_resolve_for_every_tool(
            self, source_trees, mcp_tools):
        offenders: dict[str, list[str]] = {}
        for tool in mcp_tools:
            issues = _callability_issues(tool, source_trees)
            if issues:
                offenders[tool.name] = issues
        assert offenders == {}, (
            f"{len(offenders)} 个工具存在死引用（模块在、目标名无/模块坏）: {offenders}"
        )

    def test_diagnose_tool_targets_existing_api(self, source_trees, mcp_tools):
        """历史死壳回归钉：diagnose 的惰性 import 目标必须真实存在。"""
        by_name = {t.name: t for t in mcp_tools}
        assert "diagnose" in by_name
        assert _callability_issues(by_name["diagnose"], source_trees) == []

    def test_detector_flags_dead_import_target_negative_control(self):
        """探测器灵敏度：历史死壳 run_diagnosis 必须被判死，真实 API 必须放行。"""
        assert _import_target_issue("rfauto.infra.diagnosis", "run_diagnosis") is not None
        assert _import_target_issue("rfauto.infra.diagnosis", "diagnose_results") is None
        # rfauto 自有模块不存在 = 硬判；第三方包缺失 = 环境限制不硬判
        assert _import_target_issue("rfauto.__module_that_does_not_exist__", None) is not None
        assert _import_target_issue("__third_party_pkg_that_does_not_exist__", None) is None

    def test_detector_flags_unresolved_global_negative_control(self):
        """探测器灵敏度：不可解析的全局名必须被抓出；局部名/属性名不误报。"""

        def _dead_shell(payload: dict[str, Any]) -> Any:  # pragma: no cover - 仅静态样本
            local_alias = payload.get  # 属性名 get 与局部 local_alias 均不应被计入
            return local_alias("k"), _name_that_does_not_exist_anywhere()  # noqa: F821

        assert _unresolved_load_globals(_dead_shell) == ["_name_that_does_not_exist_anywhere"]


class TestMcpResourceBodyCallability:
    """D-02（2026-10-04）：@mcp.resource 资源函数体双检——与工具同一对探测器。

    背景：resources.py（runs 索引/materials/compat/terminology 四件）的函数体
    惰性 import 形态与工具同源（`from rfauto.infra.run_store import list_runs`），
    describe/签名类检查同样对此盲——死壳资源在 read_resource 调用期才炸。
    遍历 list_resources()（运行时注册面，新增资源天然纳入），只检函数资源
    （合成 Prefab 资源无 fn，不在死壳盲区口径内）。
    """

    def test_function_resources_cover_current_registry(self, mcp_function_resources):
        """守卫遍历面健全性：当前 5 个函数资源全部被 fixture 覆盖
        （W5-D +rfauto://toolsets/definition，2026-10-05）。"""
        uris = {str(r.uri) for r in mcp_function_resources}
        assert uris == {
            "rfauto://runs/index",
            "rfauto://knowledge/materials",
            "rfauto://knowledge/compat_matrix",
            "rfauto://knowledge/terminology",
            "rfauto://toolsets/definition",
        }

    def test_load_global_names_resolve_for_every_resource(self, mcp_function_resources):
        offenders = {
            str(r.uri): _unresolved_load_globals(r.fn)
            for r in mcp_function_resources
            if _unresolved_load_globals(r.fn)
        }
        assert offenders == {}, (
            f"{len(offenders)} 个资源存在 NameError 隐患（LOAD_GLOBAL 不可解析）: {offenders}"
        )

    def test_lazy_import_targets_resolve_for_every_resource(
            self, source_trees, mcp_function_resources):
        offenders: dict[str, list[str]] = {}
        for resource in mcp_function_resources:
            issues = _callability_issues(resource, source_trees)
            if issues:
                offenders[str(resource.uri)] = issues
        assert offenders == {}, (
            f"{len(offenders)} 个资源存在死引用（模块在、目标名无/模块坏）: {offenders}"
        )


class TestDiagnoseToolEndToEnd:
    """diagnose 修复钉：经 fastmcp call_tool 真调用（原缺陷正是调用期才炸）。

    chdir 隔离到 tmp_path（#144：不触真实 runs）；run 目录手工落盘，不跑
    求解。规则引擎读 knowledge/rules.yaml（按 __file__ 定位的绝对路径，
    不受 chdir 影响），R001-R004 判定全确定性。
    """

    @staticmethod
    def _call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from rfauto.mcp_server import mcp

        result = asyncio.run(mcp.call_tool(tool_name, arguments))
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        return json.loads(result.content[0].text)

    def test_missing_run_returns_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = self._call("diagnose", {"run_id": "nonexistent_run_id"})
        assert data["ok"] is False
        assert data["errors"]

    def test_run_with_metrics_returns_rule_diagnosis(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "runs" / "r1"
        (run_dir / "results").mkdir(parents=True)
        (run_dir / "results" / "metrics.json").write_text(json.dumps({
            "run_id": "r1",
            "metrics": {"s11_db_max_in_band": -3.0, "s21_db_mean_in_band": -1.0},
        }), encoding="utf-8")
        (run_dir / "meta.json").write_text(
            json.dumps({"model": "wilkinson_power_divider"}), encoding="utf-8")

        data = self._call("diagnose", {"run_id": "r1"})

        assert data["ok"] is True
        body = data["data"]
        assert body["ok"] is True
        # R002（S11 偏高：-3 > -10）触发；R003（S21：-1 > -6）不触发
        assert {d["rule_id"] for d in body["diagnoses"]} == {"R002"}
        # 模型名取自 meta.json → wilkinson 限定的 R001 初值规则适用
        assert "arm_len_mm" in body["initial_values"]
        assert body["suggestions"]
        assert body["rules_applied"] == 2

    def test_meta_missing_falls_back_to_generic_rules_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        results_dir = tmp_path / "runs" / "r2" / "results"
        results_dir.mkdir(parents=True)
        (results_dir / "metrics.json").write_text(
            json.dumps({"metrics": {"s11_db_max_in_band": -20.0}}), encoding="utf-8")

        data = self._call("diagnose", {"run_id": "r2"})

        assert data["ok"] is True
        # 无 meta.json → 模型名回退 "all"：模型限定规则跳过、不臆测初值
        assert data["data"]["initial_values"] == {}
        # -20 < -10 不触发 R002
        assert data["data"]["diagnoses"] == []

    def test_run_without_metrics_section_returns_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        results_dir = tmp_path / "runs" / "r3" / "results"
        results_dir.mkdir(parents=True)
        (results_dir / "metrics.json").write_text(json.dumps({"run_id": "r3"}), encoding="utf-8")

        data = self._call("diagnose", {"run_id": "r3"})

        assert data["ok"] is False
        assert data["errors"]
