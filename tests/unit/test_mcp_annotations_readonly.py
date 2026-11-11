"""VB-1（aurora_r Wave2 席 R-10）：MCP 工具注解全覆盖 + 只读声明静态互证.

口径（全部确定性、无网络、无 LLM、无真机）：

- 棘轮钉：运行时注册工具的未注解（annotations is None）计数 == 0（只收不放）；
- 单源覆盖钉：``_annotations`` 分类表键集 == 运行时注册工具名集（无缺登、
  无陈旧）；四类计数与表常量一致（分类面变更=显式评审动作）；
- 派生 hints 钉：注入类 hints 与类别派生映射逐工具一致；既有 20 个装饰器
  注解工具与装饰器源码逐键相等（注入不覆盖）且与表类别不矛盾；
- **只读声明静态互证**（#270 静态双检口径）：对表内声明 read_only 的每个
  工具，AST 扫工具体调用面 + 传递闭包到 service 函数（project 内递归、
  局部/顶层 import 解析），写面黑名单（写文件/删除/子进程发射/线程发射/
  json·yaml·pickle·np 落盘/动态执行）不可达；
- 负例钉（必红）：工具体直接调写面/两跳间接调写面/子进程/删除/json.dump/
  真实 service 写面函数（campaign_manager.save_plan）——探测器全部报违例；
  纯计算链对照零违例（防过杀）。

已知边界（如实登记，不声称完备）：动态分发面（如
``multi_agent_service.call_kernel_tool`` 按字符串名查注册表运行期分发）为
静态闭包盲区——本互证对静态可解析调用面负责，运行期分发由分类依据
（逐工具实读消费面）与信封契约兜底。subprocess 例外白名单：
kicad_extract / kicad_optimize_cpw（KiCad 自带 Python 3.11 子进程只读解析，
AGENTS 硬限制 2）。
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import contextlib
import importlib
import inspect
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
src_dir = REPO_ROOT / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


# ─── 运行时工具面 ───────────────────────────────────────────────────────────


def _list_tools() -> list[Any]:
    from rfauto.mcp_server import mcp

    return asyncio.run(mcp.list_tools(run_middleware=False))


@pytest.fixture(scope="module")
def tools() -> list[Any]:
    return _list_tools()


@pytest.fixture(scope="module")
def tool_map(tools) -> dict[str, Any]:
    return {t.name: t for t in tools}


# ─── 棘轮与覆盖 ─────────────────────────────────────────────────────────────


def test_unannotated_count_is_zero_ratchet(tools):
    """未注解计数 == 0（VB-1 棘轮钉：只收不放，新工具必须入分类表）。"""
    unannotated = sorted(t.name for t in tools if t.annotations is None)
    assert unannotated == [], (
        f"MCP 工具未注解计数回升（棘轮只收不放）: {unannotated}——"
        "请在 src/rfauto/mcp_tools/_annotations.py 单源表补分类条目"
    )


def test_annotation_table_exact_cover(tools):
    """单源表键集 == 运行时注册工具名集（缺登+陈旧双向空）。"""
    from rfauto.mcp_tools import _annotations as ann

    names = {t.name for t in tools}
    snap = ann.classification_snapshot()
    missing = sorted(names - set(snap))
    stale = sorted(set(snap) - names)
    assert missing == [], f"注册面有工具未入分类表: {missing}"
    assert stale == [], f"分类表陈旧条目（运行时无此工具）: {stale}"


def test_category_counts():
    """四类计数（分类面变更=显式评审动作，本钉强制过目）。"""
    from collections import Counter

    from rfauto.mcp_tools import _annotations as ann

    counts = Counter(ann.classification_snapshot().values())
    # R-26（aurora_r 2026-11-10）+6：解析五批扩展 parser_ext.py 六面全
    # READ_ONLY（drc validate 纯读两文件离线求值/veriloga·skill 查询/
    # overlay 三件套纯解析零写盘）——164/25→170/25
    assert counts == {
        "read_only": 170,
        "mutating_non_destructive": 25,
        "long_running": 11,
        "destructive": 2,
    }


def test_injection_neutral_and_idempotent():
    """注入幂等且零元数据漂移（apply 内置前后指纹自证 + 二连调用零再注入）。

    先显式 import facade（pytest_randomly 随机序下本测试可能先于其他
    fixture 测试执行——facade 未导入时组件面为空，幂等断言会空转）。
    """
    _list_tools()  # 确保 facade 已导入、注册+装配层注入已完成
    from rfauto.mcp_tools import _annotations as ann

    report = ann.apply_tool_annotations()
    assert report["n_components"] > 0, "facade 导入后组件面为空（异常态）"
    assert report["meta_drift"] == []
    assert report["injected"] == [], "二次 apply 应为零再注入（幂等）"
    assert report["missing_in_table"] == []
    assert report["stale_table_entries"] == []


# ─── 既有装饰器注解保真与跨检 ───────────────────────────────────────────────


def _decorator_annotations_from_source() -> dict[str, dict[str, Any]]:
    """AST 抽取 mcp_tools 各模块 @mcp.tool(annotations={...}) 的字面 hints。"""
    out: dict[str, dict[str, Any]] = {}
    mcp_tools_dir = src_dir / "rfauto" / "mcp_tools"
    for py in sorted(mcp_tools_dir.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "tool"
                ):
                    continue
                for kw in dec.keywords:
                    if kw.arg == "annotations":
                        try:
                            out[node.name] = ast.literal_eval(kw.value)
                        except (ValueError, SyntaxError):  # pragma: no cover
                            continue
    return out


_PRE_ANNOTATED = {
    "create_run", "create_run_async", "recommend_templates", "save_campaign_plan",
    "run_campaign", "warm_start_optimize", "export_report_pdf", "rf_run_sampler",
    "multi_agent_run", "autotune_self_verify", "dataset_annotate_ground_truth",
    "dataset_set_visibility", "dataset_export_hf", "start_tune", "run_sweep",
    "mo_run", "al_propose", "competition_run", "surrogate_export_onnx",
    "surrogate_uq",
}


def test_preannotated_decorator_hints_preserved(tool_map):
    """既有 20 个装饰器注解工具：运行时 hints 与装饰器源码逐键相等（注入不覆盖）。"""
    declared = _decorator_annotations_from_source()
    assert len(declared) == len(_PRE_ANNOTATED), (
        f"装饰器注解工具数漂移: AST 实测 {sorted(declared)}——请同步 _PRE_ANNOTATED"
    )
    for name, hints in declared.items():
        runtime = tool_map[name].annotations
        assert runtime is not None, f"{name} 注解丢失"
        dump = runtime.model_dump()
        for key, val in hints.items():
            assert dump.get(key) == val, (
                f"工具 {name} 装饰器注解 {key}={val!r} 被注入覆盖为 "
                f"{dump.get(key)!r}（注入必须跳过既有注解）"
            )


def test_preannotated_consistent_with_table_category(tool_map):
    """表类别 vs 既有装饰器 hints 非矛盾（RO⇒readOnlyHint 非 False；DEST⇒destructiveHint True）。"""
    from rfauto.mcp_tools import _annotations as ann

    snap = ann.classification_snapshot()
    for name in sorted(_PRE_ANNOTATED):
        cat = snap[name]
        dump = tool_map[name].annotations.model_dump()
        if cat == "read_only":
            assert dump.get("readOnlyHint") is not False, (
                f"{name} 表类别 read_only 但装饰器显式 readOnlyHint=False"
            )
        if cat != "destructive":
            assert dump.get("destructiveHint") is not True, (
                f"{name} 表类别 {cat} 但装饰器 destructiveHint=True"
            )
        else:
            assert dump.get("destructiveHint") is True, (
                f"{name} 表类别 destructive 但装饰器 destructiveHint 非 True"
            )


def test_derived_hints_match_category(tools):
    """注入类工具的运行时 hints == 类别派生映射（逐工具）。"""
    from mcp.types import ToolAnnotations

    from rfauto.mcp_tools import _annotations as ann

    for t in tools:
        if t.name in _PRE_ANNOTATED:
            continue  # 既有装饰器注解不走派生映射
        entry = ann._TOOLS[t.name]
        expect = ToolAnnotations(**ann._derived_hints(entry))
        assert t.annotations is not None, f"{t.name} 未注解"
        assert t.annotations == expect, (
            f"{t.name} 运行时注解 {t.annotations} != 表派生 {expect}"
        )


# ─── 只读声明静态互证（#270 静态双检口径：AST 调用面+传递闭包）────────────

#: 无条件属性写面（任意接收者都视为写：Path/Dataset/Figure 实例方法等）
_ATTR_SINKS = frozenset({
    "write_text", "write_bytes", "write_lines", "savefig",
    "to_csv", "to_parquet", "to_pickle", "to_hdf", "to_excel",
    "to_feather", "to_stata", "to_msgpack", "to_sql",
    "unlink", "rmdir", "rmtree", "mkdir", "makedirs",
})

#: (规范模块名, 属性) → 限定 import 解析的写面（子进程发射/删除/序列化落盘）
_QUALIFIED_SINKS = frozenset({
    ("subprocess", "run"), ("subprocess", "Popen"), ("subprocess", "call"),
    ("subprocess", "check_call"), ("subprocess", "check_output"),
    ("subprocess", "getoutput"), ("subprocess", "getstatusoutput"),
    ("os", "system"), ("os", "popen"), ("os", "remove"), ("os", "removedirs"),
    ("os", "unlink"), ("os", "rmdir"), ("os", "rename"),
    ("shutil", "rmtree"), ("shutil", "copy"), ("shutil", "copyfile"),
    ("shutil", "copytree"), ("shutil", "move"),
    ("json", "dump"), ("pickle", "dump"),
    ("yaml", "dump"), ("yaml", "safe_dump"),
    ("yaml", "dump_all"), ("yaml", "safe_dump_all"),
    ("numpy", "save"), ("numpy", "savetxt"),
    ("numpy", "savez"), ("numpy", "savez_compressed"),
    ("threading", "Thread"), ("multiprocessing", "Process"),
})

#: subprocess 只读子进程例外（逐工具登记，评审动作）：
#: - kicad_extract / kicad_optimize_cpw：KiCad 自带 Python 3.11 子进程只读
#:   解析 .kicad_pcb（AGENTS 硬限制 2，规则 2 即子进程调用形态）；
#: - build_datasheet：report_render._read_git_commit 的 git rev-parse 只读
#:   provenance 探针（#105 观察面 best-effort，零写零删）。
_SUBPROCESS_ALLOWLIST = frozenset({
    "kicad_extract", "kicad_optimize_cpw", "build_datasheet",
})

_PROJECT_PREFIX = "rfauto."


def _import_map(
    fn: Any, source: str | None = None
) -> dict[str, tuple[str, str | None]]:
    """函数可见名 → (模块规范名, 对象路径或 None)。

    来源：所在模块源码 import 面 + 函数体局部 import（后者覆盖同名）。
    有意过近似：模块内其他函数的 import 也入映射——只影响名字解析宽度，
    调用点驱动判定，不产生凭空命中。``source`` 供合成函数（exec 无盘源）
    覆写函数体源码。
    """
    mapping: dict[str, tuple[str, str | None]] = {}

    def feed(tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    mapping[a.asname or a.name.split(".")[0]] = (a.name, None)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    mapping[a.asname or a.name] = (node.module, a.name)

    try:
        mod = sys.modules.get(fn.__module__)
        if mod is None:
            mod = importlib.import_module(fn.__module__)
        feed(ast.parse(inspect.getsource(mod)))
    except (OSError, TypeError, ImportError):
        pass
    with contextlib.suppress(OSError, TypeError, SyntaxError):
        feed(ast.parse(source if source is not None else inspect.getsource(fn)))
    return mapping


def _resolve_module(name: str) -> Any | None:
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    try:
        return importlib.import_module(name)
    except Exception:
        return None


class _ClosureScanner:
    """从工具体出发的传递闭包写面扫描器（project 内递归，命中即记违例）。"""

    def __init__(self) -> None:
        self.violations: list[str] = []
        # 强引用集合（code 对象/AST 节点本身）：防止 id 复用致漏扫；含深度帽防环
        self._seen_codes: set[Any] = set()
        self._subtree_scanned: set[Any] = set()

    def scan(self, fn: Any, source: str | None = None) -> list[str]:
        self._visit(fn, getattr(fn, "__name__", "fn"), source)
        return self.violations

    def _visit(self, fn: Any, label: str, source: str | None = None) -> None:
        code = getattr(fn, "__code__", None)
        if code is not None:
            if code in self._seen_codes or len(self._seen_codes) > 400:
                return
            self._seen_codes.add(code)
        try:
            tree = ast.parse(source if source is not None else inspect.getsource(fn))
        except (OSError, TypeError, SyntaxError):
            return
        import_map = _import_map(fn, source)
        module_name = getattr(fn, "__module__", "")
        local_defs = {
            sub.name: sub
            for sub in ast.walk(tree)
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                self._check_call(node, module_name, import_map, local_defs, label)

    def _check_call(
        self,
        call: ast.Call,
        module_name: str,
        import_map: dict[str, tuple[str, str | None]],
        local_defs: dict[str, Any],
        label: str,
    ) -> None:
        func = call.func
        if isinstance(func, ast.Attribute):
            attr = func.attr
            base = func.value
            base_name = base.id if isinstance(base, ast.Name) else None
            if attr in _ATTR_SINKS:
                self.violations.append(f"{label}: 属性写面 .{attr}()")
                return
            if base_name is not None and base_name in import_map:
                mod_name, obj_path = import_map[base_name]
                if obj_path is None:  # import X 形态 → X.attr(...)
                    mod = _resolve_module(mod_name)
                    canon = getattr(mod, "__name__", mod_name) if mod else mod_name
                    if (canon, attr) in _QUALIFIED_SINKS:
                        if canon == "subprocess" and label.split("->", 1)[0] in _SUBPROCESS_ALLOWLIST:
                            return  # 登记例外：KiCad 子进程只读解析
                        self.violations.append(f"{label}: 限定写面 {canon}.{attr}()")
                        return
                    if canon.startswith(_PROJECT_PREFIX) and mod is not None:
                        target = getattr(mod, attr, None)
                        if callable(target) and hasattr(target, "__code__"):
                            self._visit(target, f"{label}->{canon}.{attr}")
            # from X import obj 形态：base 是对象实例，非歧义写面已兜住
            return
        if isinstance(func, ast.Name):
            name = func.id
            if name in import_map:
                mod_name, obj_path = import_map[name]
                mod = _resolve_module(mod_name)
                canon = getattr(mod, "__name__", mod_name) if mod else mod_name
                if obj_path is not None:
                    if (canon, obj_path) in _QUALIFIED_SINKS:
                        if canon == "subprocess" and label.split("->", 1)[0] in _SUBPROCESS_ALLOWLIST:
                            return
                        self.violations.append(
                            f"{label}: 限定写面 {canon}.{obj_path}()"
                        )
                        return
                    if canon.startswith(_PROJECT_PREFIX) and mod is not None:
                        target = getattr(mod, obj_path, None)
                        if callable(target) and hasattr(target, "__code__"):
                            self._visit(target, f"{label}->{canon}.{obj_path}")
                return
            if name in ("eval", "exec"):
                self.violations.append(f"{label}: 动态执行 {name}()")
                return
            if name == "open" and name in vars(builtins):
                self._check_open_mode(call, label)
                return
            mod = _resolve_module(module_name) if module_name else None
            if mod is not None:
                cand = getattr(mod, name, None)
                if callable(cand) and hasattr(cand, "__code__"):
                    self._visit(cand, f"{label}->{name}()")
                    return
            sub_def = local_defs.get(name)
            if sub_def is not None and sub_def not in self._subtree_scanned:
                self._subtree_scanned.add(sub_def)
                for node in ast.walk(sub_def):
                    if isinstance(node, ast.Call):
                        self._check_call(node, module_name, import_map,
                                         local_defs, f"{label}->{name}()")

    def _check_open_mode(self, call: ast.Call, label: str) -> None:
        mode = None
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            mode = call.args[1].value
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            self.violations.append(f"{label}: open(mode={mode!r}) 写打开")


def _readonly_violations(fn: Any, source: str | None = None) -> list[str]:
    """单工具只读静态互证：返回违例清单（空=通过）。``source`` 供合成函数覆写。"""
    return _ClosureScanner().scan(fn, source)


def test_readonly_declared_tools_have_no_writeface_closure(tool_map):
    """声明只读工具：传递闭包到写面黑名单零违例（逐工具报违例路径）。"""
    from rfauto.mcp_tools import _annotations as ann

    failures: list[str] = []
    for name in ann.readonly_tool_names():
        tool = tool_map.get(name)
        assert tool is not None, f"表内只读工具 {name} 不在运行时注册面"
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} 无可扫函数体"
        viols = _readonly_violations(fn)
        if viols:
            failures.append(f"{name}: " + "; ".join(viols[:5]))
    assert failures == [], (
        "只读声明静态互证违例（声明 read_only 的工具闭包可达写面黑名单）：\n"
        + "\n".join(failures)
        + "\n处置：复核该工具消费的 service 函数——确有写面则改类别为 "
        "mutating_non_destructive（单源表），属误报则收敛黑名单口径并登记"
    )


def test_readonly_declaration_matches_runtime_hints(tool_map):
    """声明只读 ⇔ 运行时 readOnlyHint=True（注入面一致，双保险）。"""
    from rfauto.mcp_tools import _annotations as ann

    declared = set(ann.readonly_tool_names())
    for t in tool_map.values():
        if t.name in _PRE_ANNOTATED:
            continue  # 既有装饰器注解不强制 readOnlyHint
        if t.name in declared:
            assert t.annotations is not None and t.annotations.readOnlyHint is True, (
                f"{t.name} 表声明只读但运行时 readOnlyHint 非 True"
            )
        elif t.annotations is not None:
            assert t.annotations.readOnlyHint is not True, (
                f"{t.name} 表类别非只读但运行时 readOnlyHint=True"
            )


# ─── 负例钉（探测器必红面）────────────────────────────────────────────────


def _make_fn(source: str, name: str) -> Any:
    mod = types.ModuleType("_synthetic_negative_module")
    exec(compile(source, "<synthetic_negative>", "exec"), mod.__dict__)
    return getattr(mod, name)


_NEG_DIRECT_WRITE = '''
import pathlib

def negative_tool(path: str) -> dict:
    p = pathlib.Path(path)
    p.write_text("data")
    return {"ok": True}
'''

_NEG_INDIRECT_WRITE = '''
def _writer(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("x")

def negative_tool(path: str) -> dict:
    _writer(path)
    return {"ok": True}
'''

_NEG_TRANSITIVE_TWO_HOP = '''
def _writer(path: str) -> None:
    import pathlib
    pathlib.Path(path).write_bytes(b"x")

def _helper(path: str) -> dict:
    _writer(path)
    return {"ok": True}

def negative_tool(path: str) -> dict:
    return _helper(path)
'''

_NEG_SUBPROCESS = '''
import subprocess

def negative_tool(cmd: str) -> dict:
    out = subprocess.run(cmd, capture_output=True)
    return {"ok": True, "rc": out.returncode}
'''

_NEG_DELETE = '''
import shutil

def negative_tool(path: str) -> dict:
    shutil.rmtree(path)
    return {"ok": True}
'''

_NEG_JSON_DUMP = '''
import json

def negative_tool(path: str, obj: dict) -> dict:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return {"ok": True}
'''

_NEG_REAL_SERVICE_WRITEFACE = '''
def negative_tool(plan: dict, out_dir: str) -> dict:
    from rfauto.service.campaign_manager import save_plan
    return save_plan(plan, out_dir)
'''

_NEG_CLEAN_CONTROL = '''
def _pure(x: float) -> float:
    return x * 2.0

def clean_tool(x: float) -> dict:
    v = _pure(x)
    return {"ok": True, "v": str(v)}
'''


@pytest.mark.parametrize(
    ("label", "source", "expect_hit"),
    [
        ("direct_write_text", _NEG_DIRECT_WRITE, True),
        ("indirect_open_w", _NEG_INDIRECT_WRITE, True),
        ("two_hop_write_bytes", _NEG_TRANSITIVE_TWO_HOP, True),
        ("subprocess_run", _NEG_SUBPROCESS, True),
        ("shutil_rmtree", _NEG_DELETE, True),
        ("json_dump_to_file", _NEG_JSON_DUMP, True),
        ("real_service_save_plan", _NEG_REAL_SERVICE_WRITEFACE, True),
        ("clean_compute_control", _NEG_CLEAN_CONTROL, False),
    ],
)
def test_negative_pins(label, source, expect_hit):
    """探测器负例必红/对照必绿：写面闭包命中即违例，纯计算链零违例。"""
    fn_name = source.split("def ")[1].split("(")[0]
    fn = _make_fn(source, fn_name)
    viols = _readonly_violations(fn, source=source)
    if expect_hit:
        assert viols, f"负例 {label} 未被探测器命中（探测器失效）"
    else:
        assert not viols, f"对照 {label} 误报: {viols}"


def test_readonly_gate_rejects_writeface_declaration():
    """端到端负例：写面闭包合成体冒充只读过互证门槛 → 必红（探测器与门槛咬合）。"""
    fn = _make_fn(_NEG_DIRECT_WRITE, "negative_tool")
    viols = _readonly_violations(fn, source=_NEG_DIRECT_WRITE)
    assert viols, "前置：探测器应命中合成写面"
    with pytest.raises(AssertionError):
        assert viols == [], "只读互证门槛"
