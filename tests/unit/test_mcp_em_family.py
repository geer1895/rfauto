"""em 族五只读 MCP 薄壳测试（aurora_l Wave-C C1 席，2026-10-23）。

覆盖面（全离线确定性，零真机零网络零 runs/ 湖写入——run 目录/清单走
tmp_path + monkeypatch.chdir，#144 纪律）：
- 注册面：五工具注册（157 锚）+ 注册序尾 append-only 钉（金快照同源）；
- 每工具经 mcp.call_tool 端到端：ok 信封正路径 + 路径不存在 error 信封；
- 薄壳单源（D2）：AST 断言工具体零业务逻辑（无信封构造/无 print/
  无数值常量，只 import+透传）——service 单源转发，数字只出自确定性
  service（铁律 7）。

service 正路径语料复用 aurora_k 各 service 测试的 fixture 形态（好模型
清单八角电感/runs verify 合成 run/em sweep 实战矩阵），但独立内联不跨
测试模块 import（收集期耦合盲区）。
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

# ── 复用 aurora_k service 测试的语料形态（独立内联） ────────────────────────

_HFSS_HEADER = (
    "! Touchstone file exported from HFSS 2025.1.0\n"
    "# Hz S RI R 50\n"
)

# 八角电感好模型（test_em_doctor_service._good_manifest 同源语料：全绿）


def _good_manifest() -> dict:
    return {
        "units": "um",
        "domain": {"bbox": [-800, -700, 0, 800, 700, 500]},
        "device_topology": "series",
        "connectivity": {"signal": 1, "ground": 2},
        "objects": [
            {"name": "coil", "bbox": [-60, -60, 200.2, 60, 60, 205.2],
             "net": "signal", "material": "Au", "thickness_z": 5.0},
            {"name": "feed_l", "bbox": [-40, -700, 200.2, 0, -60, 205.2],
             "net": "signal", "material": "Au"},
            {"name": "feed_r", "bbox": [0, 60, 200.2, 40, 700, 205.2],
             "net": "signal", "material": "Au"},
            {"name": "gnd_left", "bbox": [-800, -700, 200.2, -500, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_right", "bbox": [500, -700, 200.2, 800, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_top_l", "bbox": [-500, 300, 200.2, -30, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_top_r", "bbox": [70, 300, 200.2, 500, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_bl", "bbox": [-500, -700, 200.2, -70, -300, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_br", "bbox": [30, -700, 200.2, 500, -300, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "sinx", "bbox": [-800, -700, 200.0, 800, 700, 200.2],
             "net": "other", "kind": "dielectric", "material": "SiNx",
             "thickness_z": 0.2},
            {"name": "gaas", "bbox": [-800, -700, 0, 800, 700, 200.0],
             "net": "other", "kind": "dielectric", "material": "GaAs",
             "thickness_z": 200.0},
        ],
        "ports": [
            {"name": "P1", "plane": {"axis": "y", "at": -700},
             "aperture_bbox": [-450, -700, 0, 100, -700, 295.2],
             "integration_line": {"start": [-450, -700, 202.7],
                                  "end": [-20, -700, 202.7]},
             "num_modes": 1, "on_boundary": True, "gap": 30},
            {"name": "P2", "plane": {"axis": "y", "at": 700},
             "aperture_bbox": [-650, 700, 0, 60, 700, 295.2],
             "integration_line": {"start": [-650, 700, 202.7],
                                  "end": [20, 700, 202.7]},
             "num_modes": 1, "on_boundary": True, "gap": 30},
        ],
        "stackup": [
            {"name": "GaAs", "thickness": 200.0, "material": "GaAs",
             "z_range": [0.0, 200.0]},
            {"name": "SiNx1", "thickness": 0.2, "material": "SiNx",
             "z_range": [200.0, 200.2]},
            {"name": "FM", "thickness": 5.0, "material": "Au",
             "z_range": [200.2, 205.2]},
        ],
    }


_BASE_RECIPE = {
    "model": "oct_ind",
    "params": {"W_um": 15, "sub_t_um": 200, "er": 12.85},
    "objectives": [{"metric": "L_nh", "op": "target", "value": 4.2,
                    "band": [2.0, 3.0]}],
}

_CASES_YAML = """
base_recipe: base.yaml
matrix:
  device: [ind, idc]
  thickness: [200, 150, 100, 50]
axis_key:
  thickness: sub_t_um
"""


# ── MCP 调用与注册面 helpers ────────────────────────────────────────────────

_EM_FAMILY_TOOLS = (
    "em_doctor_check", "runs_verify", "em_diff_runs",
    "em_metrics_from_run", "em_sweep_plan",
)


def _call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """经 fastmcp call_tool 真调用（TestDiagnoseToolEndToEnd 同款走法）。"""
    from rfauto.mcp_server import mcp

    result = asyncio.run(mcp.call_tool(tool_name, arguments))
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return json.loads(result.content[0].text)


@pytest.fixture()
def mcp_server():
    from rfauto.mcp_server import mcp
    return mcp


class TestEmFamilyRegistration:
    """注册面：五工具在册 + 计数锚 157 + 注册序尾 append-only。"""

    def test_tools_count_157(self, mcp_server):
        tools = asyncio.run(mcp_server.list_tools())
        assert len(tools) == 157

    def test_five_tools_registered(self, mcp_server):
        tools = asyncio.run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert set(_EM_FAMILY_TOOLS) <= names

    def test_registration_order_tail_append_only(self, mcp_server):
        """新五工具在注册序尾（append-only 惯例；金快照同源钉）。"""
        tools = asyncio.run(mcp_server.list_tools())
        tail = tuple(t.name for t in tools[-5:])
        assert tail == _EM_FAMILY_TOOLS


# ── em_doctor_check ─────────────────────────────────────────────────────────


class TestEmDoctorCheck:
    def test_good_manifest_all_green(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = tmp_path / "manifest.yaml"
        path.write_text(
            yaml.safe_dump(_good_manifest(), allow_unicode=True),
            encoding="utf-8")
        data = _call("em_doctor_check", {"manifest_path": str(path)})
        # 好模型 → 体检结论 PASS（ok=True）；16 行检查逐表在场
        assert data["ok"] is True
        assert data["verdict"] == "PASS"
        assert len(data["checks"]) == 16
        assert data["summary"]["n_fail"] == 0
        assert data["manifest_dir"] == str(tmp_path)

    def test_missing_file_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = _call("em_doctor_check",
                     {"manifest_path": str(tmp_path / "nope.yaml")})
        assert data["ok"] is False
        assert data["errors"]


# ── runs_verify ─────────────────────────────────────────────────────────────


def _make_run(tmp_path: Path, name: str = "run_c1") -> Path:
    """合成 run（test_runs_verify_service._make_run 同款最小形态）。"""
    run = tmp_path / name
    (run / "results").mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({
        "run_id": name, "adapter": "hfss", "model": "patch_antenna",
        "status": "done", "study_name": name,
    }), encoding="utf-8")
    (run / "recipe.snapshot.yaml").write_text(
        "model: patch_antenna\nparams: {}\n", encoding="utf-8")
    (run / "results" / "params.s1p").write_text(
        _HFSS_HEADER + "1.0e9 0.1 0.0\n", encoding="utf-8")
    return run


def _stamp(run: Path) -> None:
    """收官指纹（run_once 收尾链路同序：sidecar+manifest）。"""
    from rfauto.service.runs_verify_service import (
        write_manifest,
        write_touchstone_sidecar,
    )

    snp = sorted((run / "results").glob("params.s*p"))[0]
    write_touchstone_sidecar(
        snp, run_id=run.name, design_name="RFADesign",
        setup="Setup1", sweep="Sweep1")
    write_manifest(run)


class TestRunsVerify:
    def test_fresh_run_ok(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run = _make_run(tmp_path)
        _stamp(run)
        data = _call("runs_verify", {"run_id_or_dir": str(run)})
        assert data["ok"] is True
        assert data["status"] == "fresh"
        assert data["run_id"] == run.name

    def test_replaced_touchstone_is_stale(self, tmp_path, monkeypatch):
        """验收场景原话：旧 s1p 顶替新 run → stale，不静默放行。"""
        monkeypatch.chdir(tmp_path)
        run = _make_run(tmp_path)
        _stamp(run)
        (run / "results" / "params.s1p").write_text(
            _HFSS_HEADER + "1.0e9 0.9 0.0\n", encoding="utf-8")
        data = _call("runs_verify", {"run_id_or_dir": str(run)})
        assert data["ok"] is False
        assert data["status"] == "stale"
        kinds = {i["kind"] for i in data["issues"]}
        assert "stale_replaced" in kinds

    def test_run_id_resolves_against_runs_root(self, tmp_path, monkeypatch):
        """run_id 双口径：显式目录优先，回退 runs/<run_id>。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        run = _make_run(tmp_path / "runs", name="run_by_id")
        _stamp(run)
        data = _call("runs_verify", {"run_id_or_dir": "run_by_id"})
        assert data["ok"] is True
        assert data["status"] == "fresh"

    def test_legacy_run_without_manifest_passes_with_note(self, tmp_path,
                                                          monkeypatch):
        monkeypatch.chdir(tmp_path)
        run = _make_run(tmp_path, name="run_legacy")  # 不 stamp
        data = _call("runs_verify", {"run_id_or_dir": str(run)})
        assert data["ok"] is True
        assert data["status"] == "legacy"
        assert data["note"]

    def test_missing_dir_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = _call("runs_verify",
                     {"run_id_or_dir": str(tmp_path / "no_such_run")})
        assert data["ok"] is False
        assert data["status"] == "error"
        assert data["errors"]


# ── em_diff_runs ────────────────────────────────────────────────────────────


class TestEmDiffRuns:
    def test_two_dirs_sections_skip_honestly(self, tmp_path, monkeypatch):
        """两个空 run 目录：缺节如实 skip（不伪造空 diff 冒充可比）。"""
        monkeypatch.chdir(tmp_path)
        a = tmp_path / "run_a"
        b = tmp_path / "run_b"
        a.mkdir()
        b.mkdir()
        data = _call("em_diff_runs",
                     {"run_a": str(a), "run_b": str(b)})
        assert data["ok"] is True
        assert data["run_a"] == str(a)
        assert data["run_b"] == str(b)
        # freshness 恒出（不随裁剪）；params/manifest/sparams 缺料如实 skip
        assert "freshness" in data
        assert data["sparam_diff"]["status"] == "skip"

    def test_unknown_section_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        a = tmp_path / "a"
        a.mkdir()
        (tmp_path / "b").mkdir()
        data = _call("em_diff_runs", {
            "run_a": str(a), "run_b": str(tmp_path / "b"),
            "sections": "params,bogus"})
        assert data["ok"] is False
        assert any("bogus" in e for e in data["errors"])

    def test_sections_string_split_and_freshness_always(self, tmp_path,
                                                        monkeypatch):
        monkeypatch.chdir(tmp_path)
        a = tmp_path / "a"
        a.mkdir()
        (tmp_path / "b").mkdir()
        data = _call("em_diff_runs", {
            "run_a": str(a), "run_b": str(tmp_path / "b"),
            "sections": " params , freshness "})
        assert data["ok"] is True
        assert data["requested_sections"] == ["params", "freshness"]
        assert "freshness" in data

    def test_missing_dir_a_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        b = tmp_path / "b"
        b.mkdir()
        data = _call("em_diff_runs",
                     {"run_a": str(tmp_path / "gone"), "run_b": str(b)})
        assert data["ok"] is False
        assert data["errors"]


# ── em_metrics_from_run ─────────────────────────────────────────────────────


class TestEmMetricsFromRun:
    @staticmethod
    def _run_with_metrics(tmp_path: Path) -> Path:
        run = tmp_path / "run_m"
        (run / "results").mkdir(parents=True)
        (run / "results" / "metrics.json").write_text(json.dumps({
            "metrics": {"s11_db": -18.0, "cost": 0.05},
        }), encoding="utf-8")
        return run

    def test_metrics_json_route_ok_with_binding(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run = self._run_with_metrics(tmp_path)
        data = _call("em_metrics_from_run", {"run_dir": str(run)})
        assert data["ok"] is True
        assert data["metrics"]["s11_db"] == -18.0
        assert "binding" in data
        assert data["sources"]["metrics_json"] is not None

    def test_at_ghz_passthrough_ok(self, tmp_path, monkeypatch):
        """at_ghz 透传（f_eval_ghz）：metrics.json 主口径路径不因定点失败。"""
        monkeypatch.chdir(tmp_path)
        run = self._run_with_metrics(tmp_path)
        data = _call("em_metrics_from_run",
                     {"run_dir": str(run), "at_ghz": 2.4})
        assert data["ok"] is True
        assert data["metrics"]

    def test_missing_dir_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = _call("em_metrics_from_run",
                     {"run_dir": str(tmp_path / "gone")})
        assert data["ok"] is False
        assert data["errors"]

    def test_empty_run_error_envelope(self, tmp_path, monkeypatch):
        """双路全空（无 metrics.json 无 Touchstone）→ error 信封。"""
        monkeypatch.chdir(tmp_path)
        run = tmp_path / "run_empty"
        run.mkdir()
        data = _call("em_metrics_from_run", {"run_dir": str(run)})
        assert data["ok"] is False
        assert data["errors"]


# ── em_sweep_plan ───────────────────────────────────────────────────────────


class TestEmSweepPlan:
    def test_matrix_expansion_read_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "base.yaml").write_text(
            yaml.safe_dump(_BASE_RECIPE), encoding="utf-8")
        cases = tmp_path / "cases.yaml"
        cases.write_text(_CASES_YAML, encoding="utf-8")
        data = _call("em_sweep_plan", {"cases_yaml": str(cases)})
        assert data["ok"] is True
        assert data["n_cases"] == 8  # 2 device × 4 thickness
        assert data["resume"] is False
        assert all(c["status"] == "pending" for c in data["cases"])
        # 只读：plan 零落盘（sweep_root 目录不存在）
        assert not Path(data["sweep_root"]).exists()

    def test_missing_cases_file_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = _call("em_sweep_plan",
                     {"cases_yaml": str(tmp_path / "nope.yaml")})
        assert data["ok"] is False
        assert data["errors"]

    def test_bad_adapter_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "base.yaml").write_text(
            yaml.safe_dump(_BASE_RECIPE), encoding="utf-8")
        cases = tmp_path / "cases.yaml"
        cases.write_text(_CASES_YAML + "adapter: openems\n", encoding="utf-8")
        data = _call("em_sweep_plan", {"cases_yaml": str(cases)})
        assert data["ok"] is False
        assert any("adapter" in e for e in data["errors"])


# ── 薄壳单源（D2）：工具体零业务逻辑 ────────────────────────────────────────


class TestThinShellSingleSource:
    """AST 断言：本文件工具只做 import+透传，信封/数值全在 service 单源。"""

    @staticmethod
    def _is_tool_decorator(dec: ast.expr) -> bool:
        """@mcp.tool（Attribute）或 @mcp.tool()（Call 包 Attribute）皆认。"""
        if isinstance(dec, ast.Attribute):
            return dec.attr == "tool"
        if isinstance(dec, ast.Call):
            return isinstance(dec.func, ast.Attribute) and dec.func.attr == "tool"
        return False

    @classmethod
    def _tool_functions(cls) -> list[ast.FunctionDef]:
        tree = ast.parse(_em_family_source())
        return [node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and any(cls._is_tool_decorator(d) for d in node.decorator_list)]

    def test_exactly_five_tools(self):
        fns = self._tool_functions()
        assert [f.name for f in fns] == list(_EM_FAMILY_TOOLS)

    def test_no_envelope_construction_no_print_no_numeric_business(self):
        source = _em_family_source()
        # 信封只出自 service/构造器 import，薄壳禁止裸 dict 信封与 print
        assert "ok_envelope(" not in source
        assert "print(" not in source
        assert '"ok":' not in source
        # 数值只出自确定性 service（铁律 7）：工具体无数值业务常量
        for fn in self._tool_functions():
            for node in ast.walk(fn):
                if isinstance(node, ast.Constant) and isinstance(
                        node.value, (int, float)) and not isinstance(
                        node.value, bool):
                    pytest.fail(
                        f"{fn.name} 工具体出现数值常量 {node.value!r}"
                        "（业务逻辑越面）")

    def test_lazy_imports_target_service_single_source(self):
        fns = {f.name: f for f in self._tool_functions()}
        expected = {
            "em_doctor_check": ("rfauto.service.em_doctor_service",
                                "doctor_from_file"),
            "runs_verify": ("rfauto.service.runs_verify_service", None),
            "em_diff_runs": ("rfauto.service.em_diff_service", "diff_runs"),
            "em_metrics_from_run": ("rfauto.service.em_metrics_service",
                                    "em_metrics_from_run"),
            "em_sweep_plan": ("rfauto.service.em_sweep_service", "plan_sweep"),
        }
        for name, (module, target) in expected.items():
            imports = [
                (n.module, [a.name for a in n.names])
                for n in ast.walk(fns[name])
                if isinstance(n, ast.ImportFrom) and n.module
            ]
            modules = {m for m, _ in imports}
            assert modules == {module}, f"{name} 必须单源转发 {module}"
            if target is not None:
                flat = {a for _, names in imports for a in names}
                assert target in flat


def _em_family_source() -> str:
    from rfauto.mcp_tools import em_family

    return Path(em_family.__file__).read_text(encoding="utf-8")
