"""W1-B 孤儿接线批定向门：`rfauto layout` 子应用八叶（VI-1 表行 2-8）。

判据（批 criteria W1-B 预声明，逐条钉住）：

- ①八叶 --help 真跑全过（typer CliRunner 真构建命令面）；help 文案
  卫生自证（无裸 ``[``、无未成对 ``%``，#305 家法）；
- ②每叶 ≥1 条 ``--json`` 双路径（成功信封+失败信封）冒烟；无法离线
  构造成功面的叶（assemble 真 KiCad 子进程、step 真 kicad-cli）用
  monkeypatch 钉 service 调用断言转发正确；
- ③lvs FAIL（LVS_FLAG）→ 退出码 1 语义（拦截门）；
- ④全部 _emit 信封进出（ok/errors 同构；layout_service 裸载荷契约由
  薄壳统一套 ok 信封，不反向改 service）；
- ⑤零数值面：layout.py 源 AST 零 float 字面量（全部转发，铁律 7）；
- ⑥layout 家族 8 service 模块消费点自证（每模块被叶引用的函数真实
  存在且 CLI 源引用）。

注册面计数（test_cli.py/test_check_numbers.py 五钉）不在本文件作用域
（批纪律：主代理合流时集中更新）；本文件只自证本席注册正确性。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains import layout as layout_domain
from rfauto.cli.main import app

runner = CliRunner()


def _click_group():
    """typer.Typer → click TyperGroup（main.app 是 Typer 实例，无 .commands）。"""
    return typer.main.get_group(app)

#: 八叶名单（VI-1 表行 2-8；本席交付面，与批计数账 +8 对应）。
LEAVES = ("build", "assemble", "diff", "lvs",
          "panelize", "simulate", "stencil", "step")

#: 叶 → service 模块 → 该叶消费的函数（判据⑥消费点自证清单）。
LEAF_SERVICE_MAP = {
    "build": ("rfauto.service.layout_service",
              ("generate_layout_payload", "export_layout_payload",
               "import_layout_payload", "round_trip_report")),
    "assemble": ("rfauto.service.layout_assembly_service",
                 ("assembly_payload",)),
    "diff": ("rfauto.service.layout_diff_service",
             ("diff_layout_payload",)),
    "lvs": ("rfauto.service.layout_lvs_service",
            ("lvs_check", "expected_from_compose_netlist")),
    "panelize": ("rfauto.service.layout_panel_service", ("panelize",)),
    "simulate": ("rfauto.service.layout_sim_service",
                 ("layout_sim_prepare",)),
    "stencil": ("rfauto.service.layout_stencil_service",
                ("evaluate_apertures",)),
    "step": ("rfauto.service.layout_step_service", ("export_step",)),
}
# resolve_kicad_cli 不入上表：CLI 叶只转发 export_step（解析在 service 内部）；
# 该函数由 TestStep 的 monkeypatch 钉单独消费（patch 即存在性证明）。


def _walk_click_tree(group, prefix: str = "") -> list[tuple[str, object]]:
    """鸭子判别遍历（#354：typer._click 内嵌 click，isinstance 全漏）。"""
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


def _invoke_json(args: list[str]):
    """跑命令并解析 --json 信封（_emit 走 rich print_json，可 json.loads）。"""
    result = runner.invoke(app, args)
    try:
        payload = json.loads(result.output)
    except ValueError:
        payload = None
    return result, payload


def _layout_payload(name: str = "a", items=None) -> dict:
    return {
        "name": name,
        "layers": [{"name": "F.Cu", "gds_layer": 1, "gds_datatype": 0}],
        "items": items if items is not None else [
            {"kind": "path", "points": [[0.0, 0.0], [10.0, 0.0]],
             "width_mm": 0.5, "layer": "F.Cu"},
        ],
        "annotations": {},
    }


def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# ══ 判据①：八叶 --help 真跑 + help 文案卫生 ═══════════════════════════════


class TestRegistration:
    def test_layout_subapp_registered_with_exact_leaves(self):
        nodes = dict(_walk_click_tree(_click_group()))
        assert "layout" in nodes, "layout 子应用未注册进顶层 CLI 树"
        children = {
            name for (path, _cmd) in _walk_click_tree(_click_group())
            for name in [path.split()[-1]] if path.startswith("layout ")
            and len(path.split()) == 2
        }
        assert children == set(LEAVES), f"八叶名单漂移: {children}"

    def test_no_shadow_layout_top_level(self):
        """#df6① 防遮蔽钉：顶层 layout 节点必须是本席 TyperGroup（含八叶），
        而非被同名旧命令顶替（顶替时八叶不存在即红）。"""
        nodes = dict(_walk_click_tree(_click_group()))
        sub = nodes["layout"]
        assert set(getattr(sub, "commands", {}) or {}) == set(LEAVES)

    @pytest.mark.parametrize("leaf", LEAVES)
    def test_help_runs(self, leaf):
        result = runner.invoke(app, ["layout", leaf, "--help"])
        assert result.exit_code == 0, result.output

    def test_help_text_hygiene_self_check(self):
        """本席八节点 help/short_help 无裸 [ 与未成对 %（不碰冻结基线门）。"""
        for path, cmd in _walk_click_tree(app):
            if path != "layout" and not path.startswith("layout "):
                continue
            for text in (getattr(cmd, "help", None) or "",
                         getattr(cmd, "short_help", None) or ""):
                assert "[" not in text, (path, text)
                assert text.replace("%%", "").count("%") == 0, (path, text)


# ══ 判据⑥：8 service 模块消费点自证 ═══════════════════════════════════════


class TestServiceConsumption:
    @pytest.mark.parametrize("leaf", sorted(LEAF_SERVICE_MAP))
    def test_leaf_service_functions_exist(self, leaf):
        module_name, functions = LEAF_SERVICE_MAP[leaf]
        import importlib

        mod = importlib.import_module(module_name)
        for fn in functions:
            assert callable(getattr(mod, fn, None)), (leaf, module_name, fn)

    def test_cli_source_references_services(self):
        """CLI 源逐叶引用 service 函数（import 路径在叶可达的静态自证）。"""
        src = ast.parse(
            Path(layout_domain.__file__).read_text(encoding="utf-8"))
        text = ast.unparse(src)
        for leaf, (_mod, functions) in LEAF_SERVICE_MAP.items():
            for fn in functions:
                assert fn in text, (leaf, fn)


# ══ 判据⑤：零数值面（AST 零 float 字面量） ════════════════════════════════


class TestZeroNumericFace:
    def test_no_float_literals_in_cli_source(self):
        tree = ast.parse(
            Path(layout_domain.__file__).read_text(encoding="utf-8"))
        floats = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Constant)
                  and isinstance(node.value, float)]
        assert floats == [], f"CLI 薄壳出现 float 字面量: {floats[:5]}"

    def test_no_math_import(self):
        src = Path(layout_domain.__file__).read_text(encoding="utf-8")
        assert "import math" not in src
        assert "import numpy" not in src


# ══ 判据②③④：逐叶 --json 双路径冒烟 ══════════════════════════════════════


class TestBuild:
    def test_generate_success_envelope(self, tmp_path):
        result, payload = _invoke_json([
            "layout", "build", "--kind", "microstrip",
            "-p", "width_mm=0.5", "-p", "length_mm=10", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["exported_path"] is None
        assert payload["layout"]["items"]

    def test_generate_with_export_success(self, tmp_path):
        out = tmp_path / "out.dxf"
        result, payload = _invoke_json([
            "layout", "build", "--kind", "microstrip",
            "-p", "width_mm=0.5", "-p", "length_mm=10",
            "--fmt", "dxf", "--output", str(out), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert out.is_file()
        # generate+export 返回 exported_path/exported_format（无 n_items 键，
        # service 契约如实；条目数经 round-trip 模式的 n_items 单独钉）
        assert payload["exported_path"] == str(out)
        assert payload["exported_format"] == "dxf"

    def test_export_mode_success(self, tmp_path):
        _r, gen = _invoke_json([
            "layout", "build", "--kind", "microstrip",
            "-p", "width_mm=0.5", "-p", "length_mm=10", "--json"])
        payload_file = _write_json(tmp_path / "payload.json", gen["layout"])
        out = tmp_path / "rt.gds"
        result, payload = _invoke_json([
            "layout", "build", "--from-payload", str(payload_file),
            "--fmt", "gdsii", "--output", str(out), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True and out.is_file()

    def test_import_mode_success(self, tmp_path):
        _r, gen = _invoke_json([
            "layout", "build", "--kind", "microstrip",
            "-p", "width_mm=0.5", "-p", "length_mm=10", "--json"])
        payload_file = _write_json(tmp_path / "payload.json", gen["layout"])
        dxf = tmp_path / "x.dxf"
        _r2, _exp = _invoke_json([
            "layout", "build", "--from-payload", str(payload_file),
            "--fmt", "dxf", "--output", str(dxf), "--json"])
        assert _r2.exit_code == 0, _r2.output
        result, payload = _invoke_json([
            "layout", "build", "--import-file", str(dxf),
            "--fmt", "dxf", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["layout"]["items"]

    def test_round_trip_mode_success(self, tmp_path):
        _r, gen = _invoke_json([
            "layout", "build", "--kind", "microstrip",
            "-p", "width_mm=0.5", "-p", "length_mm=10", "--json"])
        payload_file = _write_json(tmp_path / "payload.json", gen["layout"])
        result, payload = _invoke_json([
            "layout", "build", "--round-trip", str(payload_file),
            "--workdir", str(tmp_path / "rt"),
            "--fmt-list", "dxf,gdsii", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["all_lossless"] is True

    def test_generate_unknown_kind_failure_envelope(self):
        result, payload = _invoke_json([
            "layout", "build", "--kind", "__no_such_gen__", "--json"])
        assert result.exit_code == 1
        assert payload is not None and payload["ok"] is False
        assert payload["errors"]

    def test_no_mode_failure_envelope(self):
        result, payload = _invoke_json(["layout", "build", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


class TestAssemble:
    def test_missing_board_failure_envelope(self, tmp_path):
        result, payload = _invoke_json([
            "layout", "assemble", str(tmp_path / "nope.kicad_pcb"),
            "--out-dir", str(tmp_path / "asm"), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "不存在" in payload["errors"][0]

    def test_success_forwards_to_service(self, tmp_path, monkeypatch):
        import rfauto.service.layout_assembly_service as svc

        calls: dict = {}

        def _fake(pcb_path, out_dir, *, kicad_python=None, timeout_s=120.0):
            calls.update(pcb=str(pcb_path), out=str(out_dir),
                         kp=kicad_python, ts=timeout_s)
            return {"ok": True, "n_placed": 3, "pos_path": "p",
                    "bom_path": "b"}

        monkeypatch.setattr(svc, "assembly_payload", _fake)
        result, payload = _invoke_json([
            "layout", "assemble", str(tmp_path / "b.kicad_pcb"),
            "--out-dir", str(tmp_path / "o"), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True and payload["n_placed"] == 3
        assert calls["pcb"] == str(tmp_path / "b.kicad_pcb")
        assert calls["out"] == str(tmp_path / "o")

    def test_service_error_envelope_passthrough_rc1(self, tmp_path, monkeypatch):
        """service 已裁决失败（error 信封）→ 退出码 1（不二次包装）。"""
        import rfauto.service.layout_assembly_service as svc

        monkeypatch.setattr(
            svc, "assembly_payload",
            lambda *a, **k: {"ok": False, "errors": ["KiCad 装配导出失败"]})
        result, payload = _invoke_json([
            "layout", "assemble", str(tmp_path / "b.kicad_pcb"),
            "--out-dir", str(tmp_path / "o"), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


class TestDiff:
    def test_identical_success_envelope(self, tmp_path):
        a = _write_json(tmp_path / "a.json", _layout_payload())
        result, payload = _invoke_json(
            ["layout", "diff", str(a), str(a), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True and payload["identical"] is True

    def test_changed_success_envelope(self, tmp_path):
        a = _write_json(tmp_path / "a.json", _layout_payload())
        b = _write_json(tmp_path / "b.json", _layout_payload(items=[
            {"kind": "path", "points": [[0.0, 0.0], [12.0, 0.0]],
             "width_mm": 0.5, "layer": "F.Cu"}]))
        result, payload = _invoke_json(
            ["layout", "diff", str(a), str(b), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["identical"] is False
        assert payload["items"]["added"] or payload["items"]["removed"]

    def test_bad_payload_failure_envelope(self, tmp_path):
        a = _write_json(tmp_path / "a.json", _layout_payload())
        bad = _write_json(tmp_path / "bad.json",
                          {"name": "x", "items": [{"kind": "wat"}]})
        result, payload = _invoke_json(
            ["layout", "diff", str(a), str(bad), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False

    def test_missing_file_exit_2(self, tmp_path):
        a = _write_json(tmp_path / "a.json", _layout_payload())
        result = runner.invoke(
            app, ["layout", "diff", str(a), str(tmp_path / "gone.json")])
        assert result.exit_code == 2


class TestLvs:
    @staticmethod
    def _two_net_fixtures(tmp_path: Path):
        """两条不连通走线 + 两端口（p1/p2 落不同连通分量）。"""
        layout = _layout_payload(items=[
            {"kind": "path", "points": [[0.0, 0.0], [10.0, 0.0]],
             "width_mm": 0.5, "layer": "F.Cu"},
            {"kind": "path", "points": [[0.0, 50.0], [10.0, 50.0]],
             "width_mm": 0.5, "layer": "F.Cu"},
        ])
        layout_file = _write_json(tmp_path / "lay.json", layout)
        ports = _write_json(tmp_path / "ports.json", {"ports": [
            {"port_id": "p1", "position_mm": [0.0, 0.0],
             "direction": [1, 0], "width_mm": 0.5, "layer": "F.Cu"},
            {"port_id": "p2", "position_mm": [10.0, 50.0],
             "direction": [1, 0], "width_mm": 0.5, "layer": "F.Cu"},
        ]})
        return layout_file, ports

    @pytest.mark.skipif(
        __import__("importlib.util", fromlist=["util"]).find_spec("shapely")
        is None, reason="shapely 未装（LC-7 可选依赖，诚实 skip）")
    def test_match_rc0_and_flag_rc1(self, tmp_path):
        pytest.importorskip("shapely")
        layout_file, ports = self._two_net_fixtures(tmp_path)
        expected = _write_json(tmp_path / "exp.json",
                               {"connections": [], "ports": ["p1", "p2"]})
        result, payload = _invoke_json([
            "layout", "lvs", str(layout_file), str(expected),
            "--ports-file", str(ports), "--netlist-fmt", "pin", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["verdict"] == "LVS_MATCH"

        # 判据③：期望连接与几何矛盾（p1-p2 应同网）→ LVS_FLAG → rc 1
        conflicting = _write_json(
            tmp_path / "conflict.json",
            {"connections": [["p1", "p2"]], "ports": ["p1", "p2"]})
        result, payload = _invoke_json([
            "layout", "lvs", str(layout_file), str(conflicting),
            "--ports-file", str(ports), "--netlist-fmt", "pin", "--json"])
        assert result.exit_code == 1, result.output
        assert payload["ok"] is True  # 信封本身成功，失败在判定语义
        assert payload["verdict"] == "LVS_FLAG"

    @pytest.mark.skipif(
        __import__("importlib.util", fromlist=["util"]).find_spec("shapely")
        is None, reason="shapely 未装（LC-7 可选依赖，诚实 skip）")
    def test_compose_netlist_fold_path(self, tmp_path):
        pytest.importorskip("shapely")
        from rfauto.core.compose.layout_netlist import COMPOSE_NETLIST_SCHEMA

        layout_file, ports = self._two_net_fixtures(tmp_path)
        netlist = _write_json(tmp_path / "net.json", {
            "schema": COMPOSE_NETLIST_SCHEMA,
            "connections": [{"a": ["X", "p1"], "b": ["Y", "p2"]}],
            "exposed_ports": [{"instance": "X", "pin": "p1"},
                              {"instance": "Y", "pin": "p2"}],
        })
        result, payload = _invoke_json([
            "layout", "lvs", str(layout_file), str(netlist),
            "--ports-file", str(ports), "--json"])
        assert result.exit_code == 1  # p1/p2 分属两网 → compose 连接 disagree
        assert payload["verdict"] == "LVS_FLAG"
        assert payload["connections"][0]["flag"] == "disagree"

    def test_bad_compose_schema_failure_envelope(self, tmp_path):
        layout_file = _write_json(tmp_path / "lay.json", _layout_payload())
        netlist = _write_json(tmp_path / "net.json", {"schema": "other"})
        result, payload = _invoke_json([
            "layout", "lvs", str(layout_file), str(netlist), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "折叠失败" in payload["errors"][0]


class TestPanelize:
    def test_vcut_success_envelope(self):
        result, payload = _invoke_json([
            "layout", "panelize", "--board-w-mm", "50",
            "--board-h-mm", "40", "--cols", "2", "--rows", "2", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["n_boards"] == 4
        assert payload["separation_spec"]["method"] == "vcut"
        assert len(payload["fiducials"]) == 3

    def test_tab_missing_gap_failure_envelope(self):
        result, payload = _invoke_json([
            "layout", "panelize", "--board-w-mm", "50",
            "--board-h-mm", "40", "--separation", "tab", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


class TestSimulate:
    @staticmethod
    def _sim_payload() -> dict:
        h = 5.08e-4
        return {
            "stackup": {"name": "s", "layers": [
                {"name": "dielectric 1", "zmin_m": 0.0, "thickness_m": h,
                 "material": "fr4", "kind": "dielectric"},
                {"name": "F.Cu", "zmin_m": h, "thickness_m": 0.0,
                 "material": "copper", "kind": "signal"},
                {"name": "GND", "zmin_m": h, "thickness_m": 0.0,
                 "material": "copper", "kind": "ground"},
            ]},
            "material_props": {
                "dielectric 1": {"epsilon_r": 4.4, "loss_tangent": 0.02}},
            "layout": {
                "name": "demo",
                "layers": [
                    {"name": "F.Cu", "gds_layer": 1, "gds_datatype": 0},
                    {"name": "GND", "gds_layer": 2, "gds_datatype": 0},
                    {"name": "PORT", "gds_layer": 3, "gds_datatype": 0},
                ],
                "items": [
                    {"kind": "path", "points": [[0.0, 0.0], [10.0, 0.0]],
                     "width_mm": 0.5, "layer": "F.Cu"},
                    {"kind": "polygon",
                     "points": [[-2.0, -2.0], [12.0, -2.0],
                                [12.0, 2.0], [-2.0, 2.0]],
                     "layer": "GND"},
                    {"kind": "path", "points": [[0.0, 0.0], [1.0, 0.0]],
                     "width_mm": 0.5, "layer": "PORT"},
                ],
                "annotations": {},
            },
            "ports": {"marker_layer": "PORT", "port_layer": "F.Cu"},
            "sim": {"f0_ghz": 2.5, "fc_ghz": 1.0},
        }

    def test_prepare_success_and_out_dir(self, tmp_path):
        payload_file = _write_json(tmp_path / "sim.json", self._sim_payload())
        out_dir = tmp_path / "run1"
        result, payload = _invoke_json([
            "layout", "simulate", "--payload", str(payload_file),
            "--out-dir", str(out_dir), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True and payload["zero_solve"] is True
        assert payload["render_script"]
        assert Path(payload["script_path"]).is_file()
        assert Path(payload["script_path"]).name == "simulation.py"

    def test_missing_sections_failure_envelope(self, tmp_path):
        payload_file = _write_json(
            tmp_path / "bad.json", {"sim": {"f0_ghz": 1.0, "fc_ghz": 1.0}})
        result, payload = _invoke_json([
            "layout", "simulate", "--payload", str(payload_file), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False and payload["errors"]


class TestStencil:
    def test_pass_and_fail_verdicts(self, tmp_path):
        apertures = _write_json(tmp_path / "ap.json", {"apertures": [
            {"name": "R1", "shape": "rect", "length_mm": 0.5,
             "width_mm": 0.3}]})
        result, payload = _invoke_json([
            "layout", "stencil", "--apertures", str(apertures),
            "--foil-thickness-mm", "0.1", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True and payload["all_pass"] is True

        result, payload = _invoke_json([
            "layout", "stencil", "--apertures", str(apertures),
            "--foil-thickness-mm", "0.5", "--json"])
        assert result.exit_code == 0  # 评估成功≠判据全过（如实区分）
        assert payload["all_pass"] is False
        assert payload["n_fail"] == 1

    def test_invalid_thickness_failure_envelope(self, tmp_path):
        apertures = _write_json(tmp_path / "ap.json", {"apertures": [
            {"name": "R1", "shape": "rect", "length_mm": 0.5,
             "width_mm": 0.3}]})
        result, payload = _invoke_json([
            "layout", "stencil", "--apertures", str(apertures),
            "--foil-thickness-mm", "-1", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


class TestStep:
    def test_missing_board_failure_envelope(self, tmp_path):
        """板缺失在子进程发射前拦截（hermetic，不依赖 KiCad 是否在装）。"""
        result, payload = _invoke_json([
            "layout", "step", str(tmp_path / "nope.kicad_pcb"), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "不存在" in payload["errors"][0]

    def test_skipped_envelope_when_no_cli(self, tmp_path, monkeypatch):
        import rfauto.service.layout_step_service as svc

        monkeypatch.setattr(svc, "resolve_kicad_cli",
                            lambda *a, **k: None)
        result, payload = _invoke_json([
            "layout", "step", str(tmp_path / "b.kicad_pcb"), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True  # skipped=前置不满足如实跳过，非错误
        assert payload.get("skipped") is True
        assert "kicad-cli" in (payload.get("reason") or "")

    def test_success_forwards_to_service(self, tmp_path, monkeypatch):
        import rfauto.service.layout_step_service as svc

        calls: dict = {}

        def _fake(board_path, out_path=None, *, cli_path=None,
                  timeout_s=180.0, extra_args=None):
            calls.update(board=str(board_path), out=(
                None if out_path is None else str(out_path)),
                extra=extra_args)
            return {"ok": True, "out_path": str(out_path),
                    "size_bytes": 10, "cmd": ["kicad-cli"]}

        monkeypatch.setattr(svc, "export_step", _fake)
        board = tmp_path / "b.kicad_pcb"
        board.write_text("(kicad_pcb)", encoding="utf-8")
        result, payload = _invoke_json([
            "layout", "step", str(board), "--output", str(tmp_path / "b.step"),
            "--extra-arg", "--subst-models", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert calls["board"] == str(board)
        assert calls["out"] == str(tmp_path / "b.step")
        assert calls["extra"] == ["--subst-models"]
