"""W6-D 席位测试：SO 残件 P4-P6 提案形态 mini 展开面。

覆盖五件功能面与文档面自证：
1. 版图生成器 hairpin_bpf（adapters/layout_generator，模板参数语义同源）；
2. 测量闭环桥（service/measurement_loop_service，P4/B4：实测偏差→侦探叙事）；
3. dev 脚手架（service/dev_scaffold_service，P5/E4：骨架+消费钉清单）；
4. run→design JSON 桥（service/design_bridge_service，③A8）；
5. 能力目录生成（scripts/build_docs_pages.build_capability_map_page，D4）
   与 CONTRIBUTING 数字自洽钉（P6）。

铁律 7 对应断言：桥面数字全部来自确定性内核（correlate/FSV/En），
matched_rules 如实为空；脚手架清单零计数字面量。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import typing
from pathlib import Path

import numpy as np
import pytest
import skrf
import yaml
from skrf.frequency import Frequency

from rfauto.cli.main import app
from rfauto.service.design_bridge_service import (
    layout_to_pcb_design,
    run_to_design_json,
)
from rfauto.service.dev_scaffold_service import (
    CALCULATOR_PIN_CHECKLIST,
    TEMPLATE_PIN_CHECKLIST,
    scaffold_calculator,
    scaffold_template,
)
from rfauto.service.measurement_loop_service import (
    MEASUREMENT_LOOP_SCHEMA,
    measurement_deviation_report,
    measurement_loop_propose,
)

_REPO = Path(__file__).resolve().parents[2]


# ─── 合成网络工具（双端口，可调 f0 制造偏差） ──────────────────────────────

def _make_net(f0_ghz: float, n_points: int = 101) -> skrf.Network:
    freq = Frequency(2.0, 4.0, n_points, unit="GHz")
    f_ghz = freq.f / 1e9
    s11 = (0.05 * np.exp(-1j * 2 * np.pi * f_ghz * 0.1)
           + 0.3 / (1 + 1j * (f_ghz - f0_ghz) / 0.05))
    s21 = 0.95 * np.exp(-1j * 2 * np.pi * f_ghz * 0.2)
    s = np.zeros((n_points, 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21
    s[:, 1, 1] = s11
    return skrf.Network(frequency=freq, s=s)


@pytest.fixture()
def s2p_pair(tmp_path: Path) -> tuple[Path, Path]:
    sim_p, meas_p = tmp_path / "sim.s2p", tmp_path / "meas.s2p"
    _make_net(2.50).write_touchstone(str(sim_p))
    _make_net(2.62).write_touchstone(str(meas_p))
    return sim_p, meas_p


# ─── 1. 版图生成器 hairpin_bpf ─────────────────────────────────────────────

class TestHairpinBpfGenerator:
    def test_registered_and_geometry_derivation(self) -> None:
        from rfauto.adapters.layout_generator import (
            LAYOUT_GENERATORS,
            LayoutPath,
            LayoutPolygon,
            generate_layout,
        )

        assert "hairpin_bpf" in LAYOUT_GENERATORS
        lay = generate_layout("hairpin_bpf", dict(
            order=3, w_mm=1.113, arm_len_mm=30.0, arm_gap_mm=3.0,
            gap_mm=0.5, tap_frac=0.4))
        # 板框 1 + 谐振器 3 + 馈线 2
        polys = [i for i in lay.items if isinstance(i, LayoutPolygon)]
        paths = [i for i in lay.items if isinstance(i, LayoutPath)]
        assert len(polys) == 1 and len(paths) == 5
        # 模板中心线口径：arm_len = 2·arm + arm_gap
        resonators = [p for p in paths
                      if len(p.points) == 4]  # U 形四点折线
        assert len(resonators) == 3
        arm = (30.0 - 3.0) / 2.0
        u0 = resonators[0]
        assert u0.points[0] == (0.0, 0.0)
        assert u0.points[1] == (0.0, pytest.approx(arm))
        # 相邻谐振器间距 = arm_gap + 2w + gap（边缘到边缘缝口径）
        pitch = 3.0 + 2.0 * 1.113 + 0.5
        assert resonators[1].points[0][0] == pytest.approx(pitch)
        # 抽头馈线 y = tap_frac·arm，自开口端（y=0）计
        feeds = [p for p in paths if len(p.points) == 2]
        assert len(feeds) == 2
        assert feeds[0].points[0][1] == pytest.approx(0.4 * arm)
        assert feeds[1].points[1][1] == pytest.approx(0.4 * arm)

    def test_board_covers_artwork(self) -> None:
        from rfauto.adapters.layout_generator import (
            LayoutPolygon,
            generate_layout,
        )

        lay = generate_layout("hairpin_bpf", dict(
            order=2, w_mm=1.0, arm_len_mm=20.0, arm_gap_mm=2.0,
            gap_mm=0.4, tap_frac=0.5, margin_mm=2.5))
        board = next(i for i in lay.items if isinstance(i, LayoutPolygon))
        xs = [p[0] for p in board.points]
        ys = [p[1] for p in board.points]
        assert min(xs) == 0.0 and min(ys) == 0.0
        # 板高 = arm + 2·margin
        assert max(ys) == pytest.approx((20.0 - 2.0) / 2.0 + 2.0 * 2.5)

    def test_default_width_from_synthesis_single_source(self) -> None:
        from rfauto.adapters.layout_generator import generate_layout
        from rfauto.core.synthesis import nominal_width_mm

        lay = generate_layout("hairpin_bpf", dict(
            order=2, arm_len_mm=30.0, arm_gap_mm=3.0, gap_mm=0.5,
            tap_frac=0.4, f0_ghz=2.5, stackup="rogers4350b_h0.508"))
        feeds = [i for i in lay.items if hasattr(i, "width_mm")]
        expected = nominal_width_mm(50.0, 2.5, "rogers4350b_h0.508")
        assert feeds[0].width_mm == expected

    @pytest.mark.parametrize("bad,match", [
        (dict(order=0, arm_len_mm=30.0, arm_gap_mm=3.0, gap_mm=0.5,
              tap_frac=0.4, w_mm=1.0), "order"),
        (dict(order=1, arm_len_mm=2.0, arm_gap_mm=3.0, gap_mm=0.5,
              tap_frac=0.4, w_mm=1.0), "arm_len_mm"),
        (dict(order=1, arm_len_mm=30.0, arm_gap_mm=3.0, gap_mm=0.5,
              tap_frac=1.5, w_mm=1.0), "tap_frac"),
    ])
    def test_param_guards(self, bad: dict, match: str) -> None:
        from rfauto.adapters.layout_generator import generate_layout

        with pytest.raises(ValueError, match=match):
            generate_layout("hairpin_bpf", bad)


# ─── 2. 测量闭环桥（P4/B4） ────────────────────────────────────────────────

class TestMeasurementLoopBridge:
    def test_deviation_report_envelope_and_detective(
            self, s2p_pair: tuple[Path, Path], tmp_path: Path) -> None:
        sim_p, meas_p = s2p_pair
        result = measurement_deviation_report(
            sim_p, meas_p, run_dir=str(tmp_path))
        assert result["ok"] is True
        assert result["schema"] == MEASUREMENT_LOOP_SCHEMA
        corr = result["correlation"]
        assert isinstance(corr.get("is_correlated"), bool)
        # FSV 两迹线都有结论（短码或 error 条目，不静默丢）
        assert set(result["fsv"]) >= {"s11", "s21"}
        detective = result["detective"]
        assert detective["ok"] is True
        assert set(detective["sections"]) == {
            "findings", "hypotheses", "evidence", "conclusion"}
        # 实测链暂无 playbook 规则——matched_rules 如实为空（不冒充）
        assert detective["sections"]["hypotheses"] == []
        # 数字白名单审计：确定性模板叙述零未授权数字
        assert detective["audit"]["ok"] is True

    def test_markdown_and_en_report_optional(
            self, s2p_pair: tuple[Path, Path], tmp_path: Path) -> None:
        sim_p, meas_p = s2p_pair
        md = tmp_path / "report.md"
        result = measurement_deviation_report(
            sim_p, meas_p, markdown_path=md)
        assert result["markdown_path"] == str(md)
        assert md.exists() and "# 数据侦探报告" in md.read_text("utf-8")
        result_en = measurement_deviation_report(
            sim_p, meas_p, en_report=True)
        assert "en_report" in result_en

    def test_missing_input_is_error_envelope(
            self, s2p_pair: tuple[Path, Path]) -> None:
        sim_p, _ = s2p_pair
        result = measurement_deviation_report(sim_p, sim_p.parent / "no.s2p")
        assert result["ok"] is False
        assert result["errors"]

    def test_propose_forwarder_rejects_non_ok_report(self) -> None:
        result = measurement_loop_propose(
            {"ok": False, "errors": ["x"]}, "whatever.yaml")
        assert result["ok"] is False
        assert "measurement_deviation_report" in result["errors"][0]


# ─── 3. dev 脚手架（P5/E4） ────────────────────────────────────────────────

class TestDevScaffold:
    def test_template_scaffold_creates_four_files(self, tmp_path: Path) -> None:
        out = tmp_path / "tmpl"
        result = scaffold_template("my_bpf", out)
        assert result["ok"] is True
        created = {Path(p).name for p in result["created"]}
        assert created == {"meta.yaml.draft", "render_skeleton.py",
                           "test_skeleton.py", "CHECKLIST.md"}

    def test_no_overwrite_rerun_errors(self, tmp_path: Path) -> None:
        out = tmp_path / "tmpl"
        assert scaffold_template("my_bpf", out)["ok"] is True
        rerun = scaffold_template("my_bpf", out)
        assert rerun["ok"] is False
        assert "已存在" in rerun["errors"][0] or "未写任何文件" in rerun["errors"][0]

    def test_skeletons_compile_and_no_literal_counts(
            self, tmp_path: Path) -> None:
        out = tmp_path / "tmpl"
        result = scaffold_template("my_bpf", out)
        assert result["ok"] is True
        render_py = out / "render_skeleton.py"
        compile(render_py.read_text("utf-8"), str(render_py), "exec")
        checklist = (out / "CHECKLIST.md").read_text("utf-8")
        # 消费钉单源：五钉齐 + 零字面计数（len 单源口径）
        for _, location in TEMPLATE_PIN_CHECKLIST:
            key = location.split("（")[0].split("的")[0]
            assert key.split("/")[-1] in checklist
        assert not re.search(r"== ?\d{2,}", checklist), "清单禁字面计数"

    def test_calculator_scaffold_pins(self, tmp_path: Path) -> None:
        out = tmp_path / "calc"
        result = scaffold_calculator("my_calc", out)
        assert result["ok"] is True
        skeleton = out / "my_calc_calculator_skeleton.py"
        compile(skeleton.read_text("utf-8"), str(skeleton), "exec")
        assert "register_calculator" in skeleton.read_text("utf-8")
        checklist = (out / "my_calc_CHECKLIST.md").read_text("utf-8")
        assert len(CALCULATOR_PIN_CHECKLIST) == 5
        assert "test_physics_invariants" in checklist

    def test_illegal_and_sanitized_names(self, tmp_path: Path) -> None:
        # 非法名（空净化/首位数字）显式报错；净化合法名如实回报名单源
        # （adapter_kit.scaffold_adapter 同款净化语义）
        assert scaffold_template("9bad", tmp_path)["ok"] is False
        assert scaffold_calculator("---", tmp_path)["ok"] is False
        ok = scaffold_calculator("bad-name", tmp_path)
        assert ok["ok"] is True
        assert ok["name"] == "badname"  # 横杠净化为合法蛇形


# ─── 4. run→design JSON 桥（③A8） ─────────────────────────────────────────

def _write_fake_run(root: Path, model: str,
                    params: dict) -> Path:
    run = root / "runs" / "20261005_000000_deadbeef"
    run.mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text(
        json.dumps({"model": model, "run_id": run.name}), encoding="utf-8")
    lines = [f"model: {model}", "params:"]
    for key, val in params.items():
        lines += [f"  {key}:", f"    value: {val}"]
    (run / "recipe.snapshot.yaml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return run


class TestDesignBridge:
    HAIRPIN_PARAMS: typing.ClassVar[dict] = dict(
        order=3, w_mm=1.113, arm_len_mm=30.0,
        arm_gap_mm=3.0, gap_mm=0.5, tap_frac=0.4)

    def test_hairpin_run_to_design(self, tmp_path: Path) -> None:
        run = _write_fake_run(tmp_path, "hairpin", self.HAIRPIN_PARAMS)
        result = run_to_design_json(run)
        assert result["ok"] is True
        assert result["model"] == "hairpin"
        assert result["kind"] == "hairpin_bpf"
        design = result["design"]
        assert len(design["traces"]) == 11  # 3×U(3 段) + 2 馈线
        assert design["board_size"] == pytest.approx([20.565, 18.5])
        assert design["edge_cuts"]
        # 下一步指针：kicad pcb → kicad drc
        assert any("kicad pcb" in s for s in result["next_steps"])

    def test_output_write_and_overrides(self, tmp_path: Path) -> None:
        params = dict(self.HAIRPIN_PARAMS)
        params.pop("w_mm")  # 缺线宽 → 须显式补（不臆造）
        run = _write_fake_run(tmp_path, "hairpin", params)
        missing = run_to_design_json(run)
        assert missing["ok"] is False
        assert "w_mm" in missing["errors"][0]
        out = tmp_path / "design.json"
        ok = run_to_design_json(run, param_overrides={"w_mm": 1.113},
                                output=out)
        assert ok["ok"] is True and out.exists()
        loaded = json.loads(out.read_text("utf-8"))
        assert loaded["traces"] == ok["design"]["traces"]

    def test_unknown_model_lists_known_mapping(self, tmp_path: Path) -> None:
        run = _write_fake_run(tmp_path, "wilkinson_power_divider", {})
        result = run_to_design_json(run)
        assert result["ok"] is False
        assert "mline" in result["errors"][0]  # 已知映射清单如实列出

    def test_mline_run_maps_to_microstrip(self, tmp_path: Path) -> None:
        run = _write_fake_run(tmp_path, "mline",
                              {"w_mm": 1.113, "line_len_mm": 40.0})
        result = run_to_design_json(run)
        assert result["ok"] is True
        assert result["kind"] == "microstrip"

    def test_layout_to_pcb_splits_polylines(self) -> None:
        from rfauto.adapters.layout_generator import (
            Layout,
            LayoutPath,
            LayoutPolygon,
        )

        lay = Layout(items=(
            LayoutPolygon(points=((0.0, 0.0), (10.0, 0.0), (10.0, 5.0),
                                  (0.0, 5.0)), layer="Edge.Cuts"),
            LayoutPath(points=((0.0, 2.5), (5.0, 2.5), (5.0, 4.5)),
                       width_mm=0.5, layer="F.Cu"),
        ))
        design = layout_to_pcb_design(lay)
        assert design["board_size"] == [10.0, 5.0]
        assert len(design["traces"]) == 2  # 折线拆两点段
        assert design["traces"][0]["start"] == [0.0, 2.5]
        assert design["traces"][1]["end"] == [5.0, 4.5]


# ─── 5. 新 CLI 叶：--json 双路径 + help 卫生 ───────────────────────────────

from typer.testing import CliRunner

_runner = CliRunner()


class TestNewCliLeaves:
    def test_dev_new_template_json_double_path(self, tmp_path: Path) -> None:
        out = tmp_path / "s"
        r1 = _runner.invoke(app, ["dev", "new-template", "t_bpf",
                                  "--out", str(out), "--json"])
        assert r1.exit_code == 0
        payload = json.loads(r1.output)
        assert payload["ok"] is True
        r2 = _runner.invoke(app, ["dev", "new-template", "t_bpf",
                                  "--out", str(out), "--json"])
        assert r2.exit_code == 1
        assert json.loads(r2.output)["ok"] is False

    def test_dev_new_calculator_json(self, tmp_path: Path) -> None:
        r = _runner.invoke(app, ["dev", "new-calculator", "t_calc",
                                 "--out", str(tmp_path), "--json"])
        assert r.exit_code == 0
        assert json.loads(r.output)["kind"] == "calculator"

    def test_diagnose_deviation_json(self, s2p_pair: tuple[Path, Path]) -> None:
        sim_p, meas_p = s2p_pair
        r = _runner.invoke(app, ["diagnose", "deviation", str(sim_p),
                                 str(meas_p), "--json"])
        assert r.exit_code == 0
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["detective"]["ok"] is True

    def test_diagnose_deviation_missing_input_json(self, tmp_path: Path) -> None:
        r = _runner.invoke(app, ["diagnose", "deviation",
                                 str(tmp_path / "a.s2p"),
                                 str(tmp_path / "b.s2p"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_kicad_design_from_run_json(self, tmp_path: Path) -> None:
        run = _write_fake_run(tmp_path, "hairpin",
                              TestDesignBridge.HAIRPIN_PARAMS)
        out = tmp_path / "d.json"
        r = _runner.invoke(app, ["kicad", "design-from-run", str(run),
                                 "--output", str(out), "--json"])
        assert r.exit_code == 0
        payload = json.loads(r.output)
        assert payload["ok"] is True and out.exists()

    def test_new_leaves_help_hygiene(self) -> None:
        # help 串禁 `[` 与 `%`（#305：argparse _expand_help 对 % 直接抛错；
        # 断言面=click 树里本席新叶的 help 字面量，非渲染输出——渲染里的
        # [OPTIONS]/[required] 是 click 自有装饰，不在约束面）。
        from typer.main import get_command

        top = get_command(app)
        targets = {
            ("dev", "new-template"), ("dev", "new-calculator"),
            ("diagnose", "deviation"), ("kicad", "design-from-run"),
        }
        checked: set[tuple[str, str]] = set()
        for group_name, leaf_name in targets:
            group = top.commands[group_name]
            leaf = group.commands[leaf_name]
            texts = [leaf.help or ""]
            for param in getattr(leaf, "params", []):
                texts.append(getattr(param, "help", None) or "")
            for text in texts:
                assert "[" not in text, (group_name, leaf_name, text)
                assert "%" not in text, (group_name, leaf_name, text)
            checked.add((group_name, leaf_name))
        assert checked == targets


# ─── 6. 能力目录生成（D4 mini）+ CONTRIBUTING 自洽钉（P6） ──────────────────

def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestCapabilityMapPage:
    def test_capability_page_live_counts_and_structure(
            self, tmp_path: Path) -> None:
        build = _load_script(
            "_w6d_bdp", _REPO / "scripts" / "build_docs_pages.py")
        checknum = build.load_check_numbers()
        md, cli_total, mcp_total = build.build_capability_map_page(checknum)
        assert cli_total == checknum.count_cli()
        assert mcp_total == checknum.count_mcp()
        assert f"**{cli_total}** 条叶子命令" in md
        assert f"**{mcp_total}** 个" in md
        # 双入口域与仅单侧表都存在（结构面）
        assert "## 双入口域" in md and "## 仅 MCP 侧模块" in md
        out = tmp_path / "site"
        build.build_all(out)
        page = out / "reference" / "capabilities.md"
        assert page.exists()

    def test_committed_capabilities_page_in_canonical_freshness_set(
            self) -> None:
        # 保鲜比对由 tests/unit/test_docs_site.py 的 canonical 测试承担
        # （本席已把 reference/capabilities.md 加进其 GENERATED_PAGES）——
        # 此处只钉"新页已入 canonical 清单 + nav"，避免双钉在他轨并发
        # 推进 CLI 计数时互相打红（#228/#247：门作用域限本项文件）。
        docs_test = (_REPO / "tests" / "unit" / "test_docs_site.py").read_text(
            "utf-8")
        assert '"reference/capabilities.md"' in docs_test
        import yaml

        nav = yaml.safe_load(
            (_REPO / "mkdocs.yml").read_text(encoding="utf-8"))["nav"]

        def _iter(node):
            if isinstance(node, str):
                yield node
            elif isinstance(node, dict):
                for v in node.values():
                    yield from _iter(v)
            elif isinstance(node, list):
                for item in node:
                    yield from _iter(item)

        assert "reference/capabilities.md" in list(_iter(nav))


class TestContributingNumbers:
    """CONTRIBUTING 数字自洽钉：数字必须与其点名的门日志逐位一致。

    刷新 CONTRIBUTING 时更新文本里的日志名+数字即可——钉是自洽的
    （对名日志实算），不随最新门漂移。
    """

    def test_count_matches_named_gate_log(self) -> None:
        # 公开分发视图：公开 CONTRIBUTING 为独立版本，不带内部全量门日志
        # 计数注记（runs/ 历史门日志亦不入公开仓）——本测属内部账本耦合面，
        # 公开仓如实 skip。
        if "runs/" not in (_REPO / "CONTRIBUTING.md").read_text(
                encoding="utf-8"):
            pytest.skip("公开 CONTRIBUTING 无门日志注记（分发视图分歧），如实 skip")
        text = (_REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
        m = re.search(
            r"`(runs/[^`]+\.log)`: (\d+) passed \+ (\d+) failed", text)
        assert m, "CONTRIBUTING 缺门日志计数注记"
        log_path = _REPO / m.group(1)
        if not log_path.exists():
            # 公开分发视图：runs/ 历史门日志不入公开仓——如实 skip
            pytest.skip(f"点名的门日志不在公开仓（证据缺席）: {log_path}")
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        tm = re.search(
            r"TOTAL: (\d+) passed, (\d+) failed", tail)
        assert tm, "门日志缺 TOTAL 行"
        assert int(m.group(2)) + int(m.group(3)) == (
            int(tm.group(1)) + int(tm.group(2)))

    def test_guide_links_resolve(self) -> None:
        text = (_REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
        for link in re.findall(r"\((docs/[^)]+)\)", text):
            assert (_REPO / link).exists(), f"CONTRIBUTING 串引用不存在: {link}"

    def test_stale_gate_reference_gone(self) -> None:
        text = (_REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "rx_batch2" not in text, "旧门日志引用未刷新"


# ─── 7. 教程/how-to 页面串引用自证（#89：文档串引用必须真实存在） ──────────

@pytest.mark.parametrize("rel", [
    "docs/tutorials/measurement-alignment.md",
    "docs/tutorials/campaign-walkthrough.md",
    "docs/how-to/new-surface-checklist.md",
    "docs/how-to/add-new-solver-engine.md",
])
class TestNewGuidePages:
    def test_referenced_repo_paths_exist(self, rel: str) -> None:
        page = _REPO / rel
        assert page.exists()
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"`(docs/[\w\-./]+)`", text):
            if "*" in target or "<" in target:
                continue
            assert (_REPO / target).exists(), f"{rel} 串引用不存在: {target}"

    def test_synced_into_docs_site(self, rel: str) -> None:
        if "/tutorials/" not in rel:
            pytest.skip("how-to 页为仓内面（不入站点同步清单）")
        synced = _REPO / "docs_site" / rel.replace("docs/", "", 1)
        assert synced.exists(), (
            f"docs_site/{synced.name} 缺同步副本——仓根重跑 "
            "scripts/build_docs_pages.py 再生")
        banner = synced.read_text("utf-8")
        assert "build_docs_pages.py 重建" in banner


# ─── 8. 教程面：recipe 快照 YAML 可解析性（桥契约输入） ─────────────────────

def test_recipe_snapshot_yaml_shape_contract(tmp_path: Path) -> None:
    run = _write_fake_run(tmp_path, "hairpin",
                          TestDesignBridge.HAIRPIN_PARAMS)
    recipe = yaml.safe_load(
        (run / "recipe.snapshot.yaml").read_text(encoding="utf-8"))
    assert recipe["model"] == "hairpin"
    assert set(recipe["params"]) == set(TestDesignBridge.HAIRPIN_PARAMS)
    assert all(
        isinstance(v, dict) and "value" in v
        for v in recipe["params"].values())
