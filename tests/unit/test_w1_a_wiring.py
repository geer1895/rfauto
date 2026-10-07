"""W1-A 孤儿接线批定向门：5 单元（VI-1 表行 1/9/13/15a/15b）+ MCP 两工具。

判据（批 criteria W1-A 预声明，逐条钉住）：

- ①5 单元 --help 真跑全过（typer CliRunner 真构建命令面）；help 文案
  卫生自证（无裸 ``[``、无 ``%``——typer 面全角替代，#305 家法）；
- ②每命令 ≥1 条 ``--json`` 双路径（成功信封+失败信封）冒烟；真机子进程
  面（kicad gerber）成功臂 monkeypatch 钉 service 转发；
- ③hints 主挂点：``_emit`` 失败信封含 ``hints`` 键且原错误文本逐字节
  保留；成功路径零变化（hint_for_message 被钉炸也不进成功信封）。
  接地勘误（#222）：批 criteria 字面命令 ``run recipes/__not_exist__.yaml
  --json`` 不成立——``run`` 命令无 ``--json`` 旗标（typer 解析层即拒，
  不经 _emit）；回归钉改走同挂点的真实 ``--json`` 失败路径（kicad gerber
  板缺失 / monkeypatch 信封失败臂），挂点机制（_core._emit →
  _attach_error_hints）同一份代码；
- ④全部 _emit 信封进出（ok/errors 同构）；
- ⑤零数值面：本席新增文件/新增函数 AST 零 float 字面量、零 math/numpy
  导入（全部转发，铁律 7）；
- ⑥MCP 两工具（error_hints_lookup/run_monitor）经 mcp 注册面可发现且
  可调用（不动计数测试——test_mcp_server/test_mcp_tool_consistency 归
  主代理合流批集中更新）。

注册面计数（test_cli.py/test_check_numbers.py 五钉）不在本文件作用域
（批纪律：主代理合流时集中更新）；本文件只自证本席注册正确性。
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app

runner = CliRunner()


def _walk_click_tree(group, prefix: str = "") -> list[tuple[str, object]]:
    """鸭子判别遍历（#354：typer._click 内嵌 click，isinstance 全漏）。

    入参须是 typer.main.get_command(app) 产出的 click 树（typer.Typer
    实例本身无 .commands）。
    """
    out: list[tuple[str, object]] = []
    commands = getattr(group, "commands", None)
    if not isinstance(commands, dict):
        return out
    for name in sorted(commands):
        sub = commands[name]
        path = f"{prefix} {name}".strip()
        out.append((path, sub))
        out.extend(_walk_click_tree(sub, path))
    return out


def _click_tree() -> list[tuple[str, object]]:
    from typer.main import get_command

    return _walk_click_tree(get_command(app))


def _invoke_json(args: list[str]):
    """跑命令并解析 --json 信封（_emit 走 rich print_json，可 json.loads）。"""
    result = runner.invoke(app, args)
    try:
        payload = json.loads(result.output)
    except ValueError:
        payload = None
    return result, payload


#: 本席 5 单元节点路径（VI-1 表行 1/9/13/15a/15b）+ hints 子应用节点。
SEAT_NODE_PATHS = (
    "kicad gerber",
    "tolerance-allocate",
    "hints",
    "hints list",
    "runs monitor",
    "runs retrieve-similar",
)

#: 零数值面自证清单： wholly-new 文件 + 本席新增函数（模块路径, 函数名）。
NEW_FILES = (
    "src/rfauto/cli/domains/hints.py",
    "src/rfauto/service/pcb_export_service.py",
)
SEAT_FUNCTIONS = (
    ("src/rfauto/cli/domains/agent_kicad.py", "kicad_gerber_cmd"),
    ("src/rfauto/cli/domains/scattered.py", "tolerance_allocate_cmd"),
    ("src/rfauto/cli/domains/surrogate.py", "runs_monitor_cmd"),
    ("src/rfauto/cli/domains/surrogate.py", "runs_retrieve_similar_cmd"),
    ("src/rfauto/cli/domains/surrogate.py", "_load_retrieval_inputs"),
    ("src/rfauto/mcp_tools/explain.py", "error_hints_lookup"),
    ("src/rfauto/mcp_tools/runs.py", "run_monitor"),
)


# ══ 判据①：5 单元 --help 真跑 + 注册/防遮蔽 + help 文案卫生 ═══════════════


class TestRegistration:
    def test_seat_nodes_registered(self):
        nodes = dict(_click_tree())
        for path in SEAT_NODE_PATHS:
            assert path in nodes, f"本席节点未注册: {path}"

    def test_tolerance_allocate_does_not_shadow_tolerance(self):
        """#df6① 防遮蔽钉：顶层 tolerance（MC 良率，workflow.py）与
        tolerance-allocate（本席单命令）并存且互不顶替。"""
        nodes = dict(_click_tree())
        assert "tolerance" in nodes, "既有顶层 tolerance（MC 良率）丢失"
        assert "tolerance-allocate" in nodes
        tol_children = set(getattr(nodes["tolerance"], "commands", {}) or {})
        assert tol_children == set(), "tolerance 被子应用顶替（遮蔽事故形态）"

    def test_hints_subapp_leaf_set_is_exactly_list(self):
        nodes = dict(_click_tree())
        children = set(getattr(nodes["hints"], "commands", {}) or {})
        assert children == {"list"}, f"hints 子应用叶集漂移: {children}"

    @pytest.mark.parametrize("node_path", SEAT_NODE_PATHS)
    def test_help_runs(self, node_path):
        result = runner.invoke(app, [*node_path.split(), "--help"])
        assert result.exit_code == 0, result.output

    def test_help_text_hygiene_self_check(self):
        """本席节点 help/short_help 无裸 [ 与 %（不碰冻结基线门，全角替代）。"""
        for path, cmd in _click_tree():
            if path not in SEAT_NODE_PATHS and path != "kicad":
                continue
            for text in (getattr(cmd, "help", None) or "",
                         getattr(cmd, "short_help", None) or ""):
                assert "[" not in text, (path, text)
                assert "%" not in text, (path, text)


# ══ 判据⑤：零数值面（AST 零 float 字面量、零 math/numpy） ═════════════════

_REPO = Path(__file__).resolve().parents[2]


class TestZeroNumericFace:
    @pytest.mark.parametrize("rel", NEW_FILES)
    def test_no_float_literals_in_new_files(self, rel):
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        floats = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Constant)
                  and isinstance(node.value, float)]
        assert floats == [], f"{rel} 出现 float 字面量: {floats[:5]}"

    @pytest.mark.parametrize(("rel", "func"), SEAT_FUNCTIONS)
    def test_seat_functions_forward_only(self, rel, func):
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        fns = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == func]
        assert fns, f"{rel} 缺本席函数 {func}"
        body_src = ast.unparse(fns[0])
        assert "import math" not in body_src and "import numpy" not in body_src
        floats = [node for node in ast.walk(fns[0])
                  if isinstance(node, ast.Constant)
                  and isinstance(node.value, float)]
        assert floats == [], f"{rel}:{func} 出现 float 计算体: {floats[:5]}"


# ══ 单元 1：kicad gerber（真机子进程面：失败臂零子进程、成功臂钉转发） ═════


class TestKicadGerber:
    def test_missing_board_failure_envelope_with_hints(self, tmp_path):
        """失败信封 + hints 键恒存在 + 原错误文本逐字节保留（判据③④钉）。"""
        board = tmp_path / "nope.kicad_pcb"
        result, payload = _invoke_json(
            ["kicad", "gerber", str(board), "--out", str(tmp_path / "g"),
             "--json"])
        assert result.exit_code == 1
        assert payload is not None and payload["ok"] is False
        expected = f"板文件不存在: {board.resolve()}"
        assert payload["errors"] == [expected], "原错误文本被改写"
        assert "hints" in payload, "失败信封缺 hints 键（主挂点未生效）"

    def test_success_forwards_to_service(self, tmp_path, monkeypatch):
        import rfauto.service.pcb_export_service as svc

        calls: dict = {}

        def _fake(pcb_path, out_dir, *, kicad_python=None):
            calls.update(pcb=str(pcb_path), out=str(out_dir), kp=kicad_python)
            return {"ok": True, "pcb": str(pcb_path), "out_dir": str(out_dir),
                    "files": {"F.Cu": "a.gbr"}, "job_file": None,
                    "drill_files": [], "missing_x2": [], "errors": []}

        monkeypatch.setattr(svc, "export_pcb_gerber_x2", _fake)
        board = tmp_path / "b.kicad_pcb"
        board.write_text("(kicad_pcb)", encoding="utf-8")
        result, payload = _invoke_json([
            "kicad", "gerber", str(board), "--out", str(tmp_path / "g"),
            "--kicad-python", "E:/fake/python.exe", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True and payload["files"] == {"F.Cu": "a.gbr"}
        assert calls == {"pcb": str(board), "out": str(tmp_path / "g"),
                         "kp": "E:/fake/python.exe"}

    def test_service_shell_is_thin_wrapper(self):
        """分层自证：service 薄壳直通 core 同名入口（cli→service→core）。"""
        from rfauto.core.gerber_export import export_gerber_x2 as core_fn
        from rfauto.service.pcb_export_service import export_pcb_gerber_x2

        assert getattr(export_pcb_gerber_x2, "__wrapped__", None) is None
        import inspect
        sig = inspect.signature(export_pcb_gerber_x2)
        assert list(sig.parameters) == ["pcb_path", "out_dir", "kicad_python"]
        assert callable(core_fn)


# ══ 单元 9：tolerance-allocate（顶层单命令） ═══════════════════════════════


class TestToleranceAllocate:
    @staticmethod
    def _payload_file(tmp_path: Path, payload: dict) -> Path:
        p = tmp_path / "payload.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_success_envelope(self, tmp_path):
        payload = self._payload_file(tmp_path, {
            "sensitivities": {"w": 1.0, "h": 2.0},
            "cost_coeffs": {"w": 1.0, "h": 1.0},
            "mode": "cost_budget", "budget_c": 10.0,
        })
        result, payload_out = _invoke_json(
            ["tolerance-allocate", "--payload", str(payload), "--json"])
        assert result.exit_code == 0, result.output
        assert payload_out["ok"] is True
        assert set(payload_out["allocation"]["keys"]) == {"w", "h"}
        assert payload_out["allocation"]["tols"]

    def test_missing_target_failure_envelope(self, tmp_path):
        payload = self._payload_file(tmp_path, {
            "sensitivities": {"w": 1.0},
            "cost_coeffs": {"w": 1.0},
            "mode": "cost_budget",  # budget_c 缺失 → service 显式报缺
        })
        result, payload_out = _invoke_json(
            ["tolerance-allocate", "--payload", str(payload), "--json"])
        assert result.exit_code == 1
        assert payload_out["ok"] is False
        assert any("budget_c" in e for e in payload_out["errors"])
        assert "hints" in payload_out

    def test_missing_payload_file_exit_2(self, tmp_path):
        result = runner.invoke(app, [
            "tolerance-allocate", "--payload", str(tmp_path / "gone.json")])
        assert result.exit_code == 2


# ══ 单元 13：hints list 只读叶 ═════════════════════════════════════════════


class TestHintsList:
    def test_success_envelope(self):
        result, payload = _invoke_json(["hints", "list", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["n_rules"] == len(payload["rules"])
        assert payload["n_rules"] > 0
        for rule in payload["rules"]:
            assert {"pattern", "match", "hint", "refs", "severity"} <= set(rule)

    def test_service_error_failure_envelope(self, monkeypatch):
        """service 裁决失败 → _emit 失败信封（hints 键恒存在，判据③④）。"""
        import rfauto.service.error_hints_service as svc

        monkeypatch.setattr(svc, "list_hint_rules",
                            lambda: {"ok": False, "errors": ["规则表损坏(合成)"]})
        result, payload = _invoke_json(["hints", "list", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"] == ["规则表损坏(合成)"]
        assert "hints" in payload


# ══ 判据③：hints 主挂点（_emit 失败路径注入；成功路径零变化） ═════════════


class TestEmitHintHook:
    def test_matched_rule_surfaces_in_failure_envelope(self, tmp_path,
                                                       monkeypatch):
        """错误文本命中指纹 → hints 非空且原 errors 逐字节保留。"""
        import rfauto.service.tolerance_allocation_service as svc

        original = "license checkout failed (合成错误文本)"
        monkeypatch.setattr(
            svc, "tolerance_allocate",
            lambda payload: {"ok": False, "errors": [original]})
        payload_file = tmp_path / "p.json"
        payload_file.write_text("{}", encoding="utf-8")
        result, payload = _invoke_json(
            ["tolerance-allocate", "--payload", str(payload_file), "--json"])
        assert result.exit_code == 1
        assert payload["errors"] == [original], "原错误文本被改写"
        hints = payload["hints"]
        assert hints, "license 指纹未命中提示表"
        assert any("license_preflight" in h["hint"] for h in hints)
        assert all(set(h) >= {"pattern", "hint", "refs", "severity"}
                   for h in hints)

    def test_hint_generation_failure_never_masks_error(self, monkeypatch):
        """hint 生成炸 → hints=[] 如实回退，原错误不受影响（#105 钉）。"""
        import rfauto.service.error_hints_service as svc
        from rfauto.cli.domains._core import _attach_error_hints

        def _boom(_text):
            raise RuntimeError("hint 引擎炸(合成)")

        monkeypatch.setattr(svc, "hint_for_message", _boom)
        envelope = {"ok": False, "errors": ["原始错误逐字节保留"]}
        _attach_error_hints(envelope)
        assert envelope["errors"] == ["原始错误逐字节保留"]
        assert envelope["hints"] == []

    def test_success_path_has_no_hints_key(self, monkeypatch):
        """成功路径零变化：hint_for_message 被钉炸也不进成功信封。"""
        import rfauto.service.error_hints_service as svc

        def _boom(_text):
            raise RuntimeError("钉炸")

        monkeypatch.setattr(svc, "hint_for_message", _boom)
        result, payload = _invoke_json(["hints", "list", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert "hints" not in payload, "成功信封被注入 hints（热路径被污染）"


# ══ 单元 15a：runs monitor（单 run + 周期面） ══════════════════════════════


def _write_series(path: Path, t: np.ndarray, v: np.ndarray) -> None:
    lines = ["% t/s\tvalue"]
    lines += [f"{ti}\t{vi}" for ti, vi in zip(t, v, strict=True)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _excitation(n: int = 200, dt: float = 1e-12,
                tau: float = 2e-11) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(n) * dt
    v = np.exp(-((t - 5 * tau) ** 2) / (2 * tau ** 2))
    return t, v


class TestRunsMonitor:
    def test_single_run_green_envelope(self, tmp_path):
        _write_series(tmp_path / "port_ut_1A", *_excitation())
        result, payload = _invoke_json(
            ["runs", "monitor", str(tmp_path), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["verdict"] == "green"

    def test_missing_dir_failure_envelope(self, tmp_path):
        result, payload = _invoke_json(
            ["runs", "monitor", str(tmp_path / "nope"), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "hints" in payload

    def test_nrts_ceiling_red_exit_1(self, tmp_path):
        """门禁语义：verdict=red（NrTS 触顶）→ 退出码 1（信封本身 ok=True）。"""
        t, v = _excitation()
        _write_series(tmp_path / "et", t, v)
        t_pt = t[-1] + 1e-12 + np.arange(400) * 1e-12
        v_pt = 1e-3 * np.exp(-1e8 * (t_pt - t[-1] - 1e-12))
        _write_series(tmp_path / "port_ut_1A", t_pt, v_pt)
        result, payload = _invoke_json(
            ["runs", "monitor", str(tmp_path), "--nr-ts", "200", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is True
        assert payload["verdict"] == "red"

    def test_cycle_aggregates(self, tmp_path):
        red = tmp_path / "20261005_red"
        red.mkdir()
        t, v = _excitation()
        _write_series(red / "et", t, v)
        green = tmp_path / "20261005_green"
        green.mkdir()
        _write_series(green / "port_ut_1A", *_excitation())
        result, payload = _invoke_json(
            ["runs", "monitor", str(tmp_path), "--cycle", "--nr-ts", "200",
             "--json"])
        assert result.exit_code == 1, "红名单非空须 rc 1"
        assert payload["ok"] is True
        assert payload["n_monitored"] == 2
        assert payload["red"] == ["20261005_red"]


# ══ 单元 15b：runs retrieve-similar（k-NN 元特征检索） ══════════════════════


class TestRunsRetrieveSimilar:
    @staticmethod
    def _recipe(tmp_path: Path, *, with_meta: bool = True) -> Path:
        params: dict = {}
        if with_meta:
            params = {"f0_ghz": {"value": 10.0}, "bw_frac": {"value": 0.1}}
        recipe = {"model": "patch", "params": params}
        p = tmp_path / "recipe.yaml"
        p.write_text(json.dumps(recipe), encoding="utf-8")  # JSON ⊂ YAML 合法
        return p

    @staticmethod
    def _library(tmp_path: Path) -> Path:
        lib = [
            {"entry_id": "run_a", "params": {"w_mm": 0.5}, "cost": 1.5,
             "meta": {"model": "patch", "dim": 2, "f0_ghz": 10.0,
                      "bw_frac": 0.1}},
            {"entry_id": "run_b", "params": {"w_mm": 0.7}, "cost": 2.5,
             "meta": {"model": "patch", "dim": 2, "f0_ghz": 1.0,
                      "bw_frac": 0.05}},
        ]
        p = tmp_path / "library.json"
        p.write_text(json.dumps(lib), encoding="utf-8")
        return p

    def test_success_envelope_nearest_neighbor(self, tmp_path):
        recipe = self._recipe(tmp_path)
        library = self._library(tmp_path)
        result, payload = _invoke_json([
            "runs", "retrieve-similar", "--recipe", str(recipe),
            "--library", str(library), "--top", "2", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["neighbors"][0]["entry_id"] == "run_a"
        assert payload["warm_start_samples"]
        assert payload["n_library"] == 2

    def test_missing_recipe_failure_envelope(self, tmp_path):
        result, payload = _invoke_json([
            "runs", "retrieve-similar", "--recipe",
            str(tmp_path / "recipes" / "__not_exist__.yaml"), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert any("配方不可读" in e for e in payload["errors"])
        assert "hints" in payload

    def test_query_missing_meta_kernel_error_envelope(self, tmp_path):
        """配方缺 f0/bw 元特征 → 内核显式 ValueError → ok=False 信封。"""
        recipe = self._recipe(tmp_path, with_meta=False)
        library = self._library(tmp_path)
        result, payload = _invoke_json([
            "runs", "retrieve-similar", "--recipe", str(recipe),
            "--library", str(library), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]


# ══ 判据⑥：MCP 两工具注册面可发现且可调用 ═════════════════════════════════


def _extract_result(tool_result):
    if hasattr(tool_result, "structured_content") \
            and tool_result.structured_content is not None:
        return tool_result.structured_content
    if hasattr(tool_result, "content") and tool_result.content:
        return json.loads(tool_result.content[0].text)
    return json.loads(str(tool_result))


class TestMcpTools:
    def test_both_tools_discoverable(self):
        from rfauto.mcp_server import mcp

        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        assert {"error_hints_lookup", "run_monitor"} <= names

    def test_error_hints_lookup_call(self):
        from rfauto.mcp_server import mcp

        out = _extract_result(asyncio.run(mcp.call_tool(
            "error_hints_lookup", {"message": "license checkout failed"})))
        assert out["ok"] is True
        assert out["n_hits"] >= 1
        assert {"pattern", "hint", "refs", "severity"} <= set(out["hits"][0])

    def test_error_hints_lookup_no_match_honest_empty(self):
        from rfauto.mcp_server import mcp

        out = _extract_result(asyncio.run(mcp.call_tool(
            "error_hints_lookup", {"message": "毫无指纹的合成错误"})))
        assert out["ok"] is True
        assert out["hits"] == []

    def test_run_monitor_missing_dir_error_envelope(self, tmp_path,
                                                    monkeypatch):
        monkeypatch.chdir(tmp_path)  # #144：MCP 面测试 cwd 隔离
        from rfauto.mcp_server import mcp

        out = _extract_result(asyncio.run(mcp.call_tool(
            "run_monitor", {"run_dir": str(tmp_path / "nope")})))
        assert out["ok"] is False

    def test_run_monitor_green_and_cycle(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.mcp_server import mcp

        run_dir = tmp_path / "run_g"
        run_dir.mkdir()
        _write_series(run_dir / "port_ut_1A", *_excitation())
        out = _extract_result(asyncio.run(mcp.call_tool(
            "run_monitor", {"run_dir": str(run_dir)})))
        assert out["ok"] is True and out["verdict"] == "green"

        root = tmp_path / "runs_root"
        root.mkdir()
        (root / "r1").mkdir()
        _write_series(root / "r1" / "port_ut_1A", *_excitation())
        out = _extract_result(asyncio.run(mcp.call_tool(
            "run_monitor", {"run_dir": str(root), "cycle": True})))
        assert out["ok"] is True
        assert out["n_monitored"] == 1
