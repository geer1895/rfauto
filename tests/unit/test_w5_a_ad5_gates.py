"""W5-A SK-4 AD-5 工具描述工程门（SK 规格包 V §3.5 Z-10a/b/c + §3.6 门值）。

三面：
  - Z-10b 五段 regex 门（批 1 清单参数化：段 1 ≤80 / Args:/Returns: 段存在
    / 每参数行缩进 / description 含失败语义关键词；终批切全量时删清单）；
  - Z-10a 转发型只读工具 Returns 键集运行时对拍（docstring 列举顶层键
    ⊆ 实际返回键；mutating 静态豁免，#270 纪律）；
  - 签名冻结 + 载荷守卫（改 description 不碰 def 行；max ≤450/median ≤200）；
  - Z-10c 单源锚（段 5 `rfauto <cmd>` 引用 ∈ CLI 注册面；toolsets.yaml
    工具名引用 ∈ 注册面——文件未落时 skip 留口，W5-D EC-6 落地后激活）。

规格：runs/research_seats_20261004/sk_specs5/SPECS.md §三/§四（2026-10-04
快照；#222 接地勘误：MCP 现役 145→并发批 146，本席零新增，清单不含新键）。
"""

from __future__ import annotations

import asyncio
import inspect
import re
import statistics
import typing
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# ─── 批 1 实名清单（SK §3.3：最短 12 + 知识五件 + 最长 3；并发批树面复测）──
BATCH1: tuple[str, ...] = (
    # ① 最短描述优先（2026-10-05 探针 ≤40 chars 全 12 个）
    "correlate_measurement", "budget_analysis", "get_metrics",
    "validate_recipe", "nfc_coil_synthesize", "bands_find",
    "bands_env_find", "sar_analytic_plane_wave", "nfc_coil_q",
    "nfc_coil_evaluate", "bands_env_points", "nfmeas_ffs_info",
    # ② agent 决策路径可见（知识五件）
    "rag_query", "rag_explain", "search_knowledge", "rationale_recall",
    "rationale_checklist",
    # ③ 结构对齐试点（最长 3）
    "pdn_gate", "run_calculator", "list_composable_templates",
)

#: 批 1 改 docstring 前取证签名（runs/w5_phase5/w5a/capture_sigs.py 快照，
#: 2026-10-05 pre-edit；描述批不得触碰 def 行——签名零变钉）。
BATCH1_SIGNATURES: dict[str, str] = {
    "correlate_measurement":
        "(sim_file: 'str', measured_file: 'str', threshold_db: 'float' = 3.0)"
        " -> 'dict[str, Any]'",
    "budget_analysis":
        "(chain: 'list[str]', catalog: 'str' = 'parts/catalog.yaml')"
        " -> 'dict[str, Any]'",
    "get_metrics": "(run_id: 'str') -> 'dict[str, Any]'",
    "validate_recipe": "(recipe_path: 'str') -> 'dict[str, Any]'",
    "nfc_coil_synthesize":
        "(target_l_nh: 'float', shape: 'str', n_turns: 'float',"
        " w_um: 'float', s_um: 'float', expression: 'str' = 'current_sheet')"
        " -> 'dict[str, Any]'",
    "bands_find": "(freq_ghz: 'float') -> 'dict[str, Any]'",
    "bands_env_find": "(t_c: 'float') -> 'dict[str, Any]'",
    "sar_analytic_plane_wave":
        "(freq_mhz: 'float', e0_v_per_m: 'float', sigma_s_per_m: 'float',"
        " epsilon_r: 'float', rho_kg_m3: 'float', depth_mm: 'list[float]')"
        " -> 'dict[str, Any]'",
    "nfc_coil_q":
        "(f_mhz: 'float', l1_nh: 'float', r1_ohm: 'float', m_nh: 'float'"
        " = 0.0, l2_nh: 'float' = 0.0, r2_ohm: 'float' = 0.0)"
        " -> 'dict[str, Any]'",
    "nfc_coil_evaluate":
        "(shape: 'str', n_turns: 'float', d_out_mm: 'float', w_um: 'float',"
        " s_um: 'float') -> 'dict[str, Any]'",
    "bands_env_points": "(key: 'str', n: 'int' = 5) -> 'dict[str, Any]'",
    "nfmeas_ffs_info": "(path: 'str') -> 'dict[str, Any]'",
    "rag_query":
        "(text: 'str', top_k: 'int' = 5, docs_dir: 'str | None' = 'docs',"
        " runs_dir: 'str | None' = 'runs', runs_limit: 'int | None' = None,"
        " mode: 'str' = 'lexical', alpha: 'float' = 0.5)"
        " -> 'dict[str, Any]'",
    "rag_explain":
        "(text: 'str', top_k: 'int' = 5, docs_dir: 'str | None' = 'docs',"
        " runs_dir: 'str | None' = 'runs', runs_limit: 'int | None' = None)"
        " -> 'dict[str, Any]'",
    "search_knowledge": "(query: 'str', scope: 'str' = 'all')"
                        " -> 'dict[str, Any]'",
    "rationale_recall":
        "(task: 'str', memory_path: 'str | None' = None, top_k: 'int' = 5)"
        " -> 'dict[str, Any]'",
    "rationale_checklist":
        "(template: 'str', extras: 'str | None' = None,"
        " memory_path: 'str | None' = None) -> 'dict[str, Any]'",
    "pdn_gate": "(payload: 'dict[str, Any]') -> 'dict[str, Any]'",
    "run_calculator":
        "(name: 'str', params: 'dict[str, Any] | None' = None,"
        " allow_experimental: 'bool | None' = None) -> 'dict[str, Any]'",
    "list_composable_templates": "() -> 'dict[str, Any]'",
}

#: 批 1 前描述长度（同上快照；载荷守卫增量 ≤120 chars/工具的基线）。
BATCH1_DESC_LEN_BEFORE: dict[str, int] = {
    "correlate_measurement": 14, "budget_analysis": 18, "get_metrics": 26,
    "validate_recipe": 26, "nfc_coil_synthesize": 27, "bands_find": 28,
    "bands_env_find": 30, "sar_analytic_plane_wave": 33, "nfc_coil_q": 37,
    "nfc_coil_evaluate": 38, "bands_env_points": 40, "nfmeas_ffs_info": 40,
    "rag_query": 326, "rag_explain": 117, "search_knowledge": 203,
    "rationale_recall": 93, "rationale_checklist": 81, "pdn_gate": 397,
    "run_calculator": 396, "list_composable_templates": 368,
}

_FAILURE_KEYWORDS = ("ok=False", "errors", "异常", "UNKNOWN", "ok: False",
                     "报错")


def _tool_map() -> dict[str, object]:
    from rfauto.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name: t for t in tools}


def _split_description(doc: str) -> str:
    """FastMCP description 语义：docstring 中 Args: 段之前的全部文本。"""
    m = re.search(r"^\s*Args:\s*$", doc, flags=re.M)
    return doc[: m.start()] if m else doc


def _docstring_of(name: str) -> str:
    for mod in ("basic", "bands", "diagnose", "explain", "jobs", "knowledge",
                "nfmeas", "pdn", "rationale", "runs", "synth"):
        module = __import__(f"rfauto.mcp_tools.{mod}", fromlist=[name])
        fn = getattr(module, name, None)
        if fn is not None:
            return inspect.getdoc(fn) or ""
    from rfauto import mcp_server
    return inspect.getdoc(getattr(mcp_server, name)) or ""


def _tool_fn(name: str):
    for mod in ("basic", "bands", "diagnose", "explain", "jobs", "knowledge",
                "nfmeas", "pdn", "rationale", "runs", "synth"):
        module = __import__(f"rfauto.mcp_tools.{mod}", fromlist=[name])
        fn = getattr(module, name, None)
        if fn is not None:
            return fn
    from rfauto import mcp_server
    return getattr(mcp_server, name)


# ─── Z-10b：五段 regex 门（批 1 清单参数化）────────────────────────────────

@pytest.fixture(scope="module")
def tools_by_name() -> dict[str, object]:
    return _tool_map()


class TestZ10bFiveSegmentGate:
    def test_batch1_all_registered(self, tools_by_name):
        missing = [n for n in BATCH1 if n not in tools_by_name]
        assert not missing, f"批 1 清单工具未注册: {missing}"

    @pytest.mark.parametrize("name", BATCH1)
    def test_segment1_first_line_within_80(self, name, tools_by_name):
        tool = tools_by_name[name]
        doc = tool.description or ""  # type: ignore[attr-defined]
        first = doc.splitlines()[0].strip() if doc.strip() else ""
        assert first, f"{name}: 段 1（一句功能）首行为空"
        assert len(first) <= 80, f"{name}: 段 1 首行 {len(first)} chars > 80"

    @pytest.mark.parametrize("name", BATCH1)
    def test_segment2_boundary_semantics(self, name, tools_by_name):
        tool = tools_by_name[name]
        desc = tool.description or ""  # type: ignore[attr-defined]
        assert any(k in desc for k in
                   ("不用于", "无副作用", "只读", "UNKNOWN", "如实")), (
            f"{name}: 段 2（边界/何时不用）语义缺失")

    @pytest.mark.parametrize("name", BATCH1)
    def test_failure_semantics_in_description(self, name, tools_by_name):
        tool = tools_by_name[name]
        desc = tool.description or ""  # type: ignore[attr-defined]
        assert any(k in desc for k in _FAILURE_KEYWORDS), (
            f"{name}: description 无失败语义关键词（ok=False/errors/异常）")

    @pytest.mark.parametrize("name", BATCH1)
    def test_args_and_returns_sections_exist(self, name, tools_by_name):
        doc = _docstring_of(name)
        m_args = re.search(r"^\s*Args:\s*$", doc, flags=re.M)
        m_ret = re.search(r"^\s*Returns:\s*$", doc, flags=re.M)
        params = set((tools_by_name[name].parameters or {})  # type: ignore
                     .get("properties", {}))
        if params:
            assert m_args, f"{name}: 有参数但缺 Args: 段（段 3 必填）"
        assert m_ret, f"{name}: 缺 Returns: 段（段 4 必填）"
        if m_args:
            assert m_ret.start() > m_args.start(), f"{name}: Returns 段序非法"

    @pytest.mark.parametrize("name", BATCH1)
    def test_args_lines_well_formed(self, name):
        """参数行格式 + 续行容差：续行只要求保持缩进（零顶格逃逸）。"""
        doc = _docstring_of(name)
        in_args = False
        n_params = 0
        for line in doc.splitlines():
            if line.strip() == "Args:":
                in_args = True
                continue
            if in_args and re.match(r"^\s*Returns:\s*$", line):
                break
            if in_args:
                if not line.strip():
                    continue
                if re.match(r"^\s{4,}([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:",
                            line):
                    n_params += 1
                    continue
                # 续行/注记行：不得顶格逃逸 Args 块
                assert line.startswith("    "), (
                    f"{name}: Args 块顶格行逃逸: {line!r}")
        if _schema_params_of(name):
            assert n_params >= 1, f"{name}: Args 段零参数行"


# ─── 签名冻结 + 载荷守卫 ───────────────────────────────────────────────────

class TestSignatureFreezeAndPayload:
    def test_batch1_signatures_unchanged(self, tools_by_name):
        for name, expected in BATCH1_SIGNATURES.items():
            fn = _tool_fn(name)
            actual = str(inspect.signature(fn))
            assert actual == expected, (
                f"{name}: 签名漂移——描述批不碰 def 行\n  期望 {expected}\n"
                f"  实际 {actual}")

    def test_description_increment_within_120(self, tools_by_name):
        for name, before in BATCH1_DESC_LEN_BEFORE.items():
            tool = tools_by_name[name]
            desc = _split_description(tool.description or "")  # type: ignore
            delta = len(desc) - before
            assert delta <= 120, (
                f"{name}: description 增量 +{delta} > 120 chars（载荷守卫）")

    def test_payload_guard_median_and_max(self, tools_by_name):
        lens = [len(_split_description(t.description or ""))
                for t in tools_by_name.values()]
        assert max(lens) <= 450, f"description max {max(lens)} > 450"
        assert statistics.median(lens) <= 200, (
            f"description median {statistics.median(lens)} > 200")


# ─── Z-10a：只读工具 Returns 键集运行时对拍（批 1 试点 5 件）───────────────

def _returns_top_level_keys(doc: str) -> list[str]:
    """解析 docstring Returns 段首个顶层 {…} 的键名（深度感知，确定性）。"""
    m = re.search(r"^\s*Returns:\s*$", doc, flags=re.M)
    assert m, "Returns 段缺失（Z-10b 先行门管）"
    block = doc[m.end():]
    brace = block.find("{")
    if brace < 0:
        return []
    depth = 0
    end = -1
    for i, ch in enumerate(block[brace:], start=brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    inner = block[brace + 1: end]
    keys: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in inner + ",":
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            current = []
            token = re.match(r"(\w+)\s*(?:[:\[(]|$)", part)
            if token:
                keys.append(token.group(1))
        else:
            current.append(ch)
    return keys


class TestZ10aReturnsKeyRuntime:
    #: 转发型只读试点（tool → (service 调用, kwargs)；mutating 静态豁免 #270）
    PILOT: typing.ClassVar[dict[str, tuple[str, str, dict]]] = {
        "search_knowledge": ("rfauto.service.knowledge_service",
                             "search_knowledge",
                             {"query": "网格"}),
        "rationale_recall": ("rfauto.service.rationale_memory",
                             "recall_with_memory",
                             {"task": "wilkinson 网格 冒烟"}),
        "rationale_checklist": ("rfauto.service.rationale_memory",
                                "checklist_with_memory",
                                {"template": "patch"}),
        "list_composable_templates": ("rfauto.service.compose_service",
                                      "list_composable_templates", {}),
    }

    @pytest.mark.parametrize("name", sorted(PILOT))
    def test_docstring_returns_keys_subset_of_actual(self, name):
        mod_name, fn_name, kwargs = self.PILOT[name]
        module = __import__(mod_name, fromlist=[fn_name])
        result = getattr(module, fn_name)(**kwargs)
        assert isinstance(result, dict) and result.get("ok"), (
            f"{name}: 试点调用未成功，对拍面失效")
        listed = _returns_top_level_keys(_docstring_of(name))
        assert listed, f"{name}: Returns 段未解析出顶层键"
        absent = [k for k in listed if k not in result]
        assert not absent, (
            f"{name}: docstring Returns 列举键 {absent} 不在实际返回键 "
            f"{sorted(result)} 中（Z-10a 单源锚失守）")

    def test_rag_query_returns_keys_subset_of_actual(self, tmp_path):
        """rag_query 试点：tmp 微型语料（秒级，不触真实 docs 索引）。"""
        from rfauto.service.rag_service import query_corpus

        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(
            "# 网格审计\nopenEMS 网格最小间距守卫与 CFL 时间步。\n",
            encoding="utf-8")
        result = query_corpus("网格 守卫", top_k=2, docs_dir=docs,
                              runs_dir=None, base_dir=tmp_path)
        assert result.get("ok")
        listed = _returns_top_level_keys(_docstring_of("rag_query"))
        absent = [k for k in listed if k not in result]
        assert not absent, (
            f"rag_query: docstring Returns 列举键 {absent} 不在实际返回键 "
            f"{sorted(result)} 中")


# ─── Z-10c：单源锚 ─────────────────────────────────────────────────────────

def _cli_command_names() -> set[str]:
    """typer 实注册命令/组名全集（与 check_numbers.cli_leaf_counts 同法）。"""
    from typer.main import get_command

    from rfauto.cli.main import app

    cmd = get_command(app)
    names: set[str] = set()
    if not hasattr(cmd, "commands"):
        return names

    def _walk(group) -> None:
        for name, sub in getattr(group, "commands", {}).items():
            names.add(name)
            if hasattr(sub, "commands"):
                _walk(sub)

    _walk(cmd)
    return names


class TestZ10cSingleSourceAnchors:
    def test_rfauto_command_references_in_descriptions(self, tools_by_name):
        """段 5 时序陷阱引用的 `rfauto <cmd>` ∈ CLI 注册面（锚 ①）。"""
        pattern = re.compile(r"\brfauto\s+([a-z][a-z0-9-]*)")
        cli_names = _cli_command_names()
        for tool in tools_by_name.values():
            desc = tool.description or ""
            for match in pattern.finditer(desc):
                assert match.group(1) in cli_names, (
                    f"{tool.name}: description 引用 rfauto {match.group(1)}"
                    f" 不在 CLI 注册面（Z-10c① 单源锚）")

    def test_toolsets_yaml_tool_references_in_registry(self, tools_by_name):
        """toolsets.yaml 的 tools 清单引用 ∈ 注册面（锚 ②；未落留口 skip）。

        W5-D（EC-6）在制期只做形态最小锚：凡条目带 ``tools`` 列表键，
        其元素必须全部是注册工具名——EC-6 落定后由其判据①（tools 并集
        ==list_tools()）承接全量正向锚，本锚补文本内引用反向面。
        """
        path = REPO / "knowledge" / "toolsets.yaml"
        if not path.exists():
            pytest.skip("knowledge/toolsets.yaml 未落（EC-6/W5-D 落地后激活）")
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict) and data, "toolsets.yaml 形态非法"
        known = set(tools_by_name) | _cli_command_names()  # hint 可引 CLI 名
        checked = 0
        for entry in data.get("toolsets") or []:
            if not isinstance(entry, dict):
                continue
            tools = entry.get("tools_hint")
            if tools is None:
                continue
            assert isinstance(tools, list), (
                f"toolsets.yaml[{entry.get('name')}] tools_hint 须为列表")
            unknown = [t for t in tools if t not in known]
            assert not unknown, (
                f"toolsets.yaml[{entry.get('name')}] 引用未注册名 {unknown}"
                f"（Z-10c② 单源锚；新工具须与 yaml 同批入库）")
            checked += len(tools)
        # 文件在档即至少核到一条 tools_hint 引用（防锚空转）
        assert checked >= 1, "toolsets.yaml 存在但零 tools_hint 引用被核对"


# ─── 全量非空/计数面不越界（与既有门互补的本席自证）────────────────────────

def _schema_params_of(name: str) -> set[str]:
    try:
        tool = _tool_map()[name]
    except Exception:
        return set()
    return set((tool.parameters or {}).get("properties", {}))  # type: ignore


def _documented_arg_names(fn) -> set[str]:
    """docstring Args 段参数名（test_mcp_tool_consistency 同口径本地实现）。"""
    documented: set[str] = set()
    in_args = False
    for line in (_docstring_of_fn(fn) or "").splitlines():
        if line.strip() == "Args:":
            in_args = True
            continue
        if in_args and re.match(r"^\s*(Returns|Raises|Notes|Examples?):\s*$",
                                line):
            break
        if in_args:
            m = re.match(r"^\s{4,}([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:", line)
            if m:
                documented.add(m.group(1))
    return documented


def _docstring_of_fn(fn) -> str:
    return inspect.getdoc(fn) or ""


class TestRegistryHygiene:
    def test_batch1_args_documentation_complete(self, tools_by_name):
        """批 1 的 Args 段全覆盖自有参数（phantom 门 :343 的正向补钉）。"""
        for name in BATCH1:
            fn = _tool_fn(name)
            documented = _documented_arg_names(fn)
            params = set((tools_by_name[name].parameters or {})  # type: ignore
                         .get("properties", {}))
            assert documented <= params, (
                f"{name}: Args 段幽灵参数 {sorted(documented - params)}")
            assert not (params - documented), (
                f"{name}: 参数 {sorted(params - documented)} 未入 Args 段")
