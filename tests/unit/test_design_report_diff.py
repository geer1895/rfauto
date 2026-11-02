"""§⑤c 版本对账节钉子测试（aurora_p C2，2026-11-01）。

范围（席位任务书验收 A-F 映射）：

- A 单源逐位：两合成 run fixture → diff 节 ``params_diff``/``metrics_diff``
  的 changes/summary/verdict/labels 与 ``design_version_diff`` 直调逐位
  一致（剥注入 source 后 ==）；手算锚含 0.0 差（base 值 0 → rel_change
  None，#364-④ falsy-0：0.0 行必须在场不得当缺失）与缺键两形态（added/
  removed）；相等键零行；identical/changed/structural 三 verdict 各一例；
- B 降级三态如实（#122 不凑节）：单 run（未传对比对象）→ 模型无 diff 键
  +md 无 ⑤c；缺 run → status=missing+note 含目录名；坏 run（C 族无声明/
  全部不可行）→ missing 注记哪侧；
- C 既有行为零变化：单 run 模型键集==既有 11 键；信封键集零增减；①-⑥
  头部原样、⑥ 不重编号；
- D provenance：``bare_number_fields(model)==[]``（ok/missing 两态）+负例
  （剥 source 必非空）；md 正文零绝对路径；
- E 文案 rider：CLI help 与 MCP 描述节数口径（含 Pareto 扩展节），MCP
  描述 <350、help 零裸 [ 零未成对 %，MCP required 参数零变化；
- F 确定性：两跑 md 逐字节（唯一豁免生成时间行）；CLI 叶可选第二位置
  参数 e2e（--json 信封 + md 含 ⑤c；不传则无）。

全部离线确定性（#139 零网络；#144 tmp fixture 隔离，零 runs/ 污染）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO = Path(__file__).resolve().parents[2]
src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.design_diff_service import design_version_diff
from rfauto.service.design_replay_report import (
    build_design_report_model,
    generate_design_report,
    render_design_report_md,
)
from rfauto.service.report_render import bare_number_fields

# ── 手算锚 fixture ───────────────────────────────────────────────────────────
# base 最优=trial_1（cost 5）；curr 最优=trial_1（cost 3）。
# params：arm_len 21→22（numeric，rel=+1/21）；gap_mm 单侧新增（added）；
#         series_w 相等（零行）→ verdict=structural（含 added）
# metrics：s11 −10→−12（numeric，rel=−0.2）；ripple 0.0→0.5（numeric，
#          base 值 0 → rel None：falsy-0 行必须在场）；q_fac 单侧移除
#          （removed）；bw_ghz 单侧新增（added）；s21 相等（零行）
_BASE_BEST_PARAMS = {"arm_len_mm": 21.0, "series_w_mm": 0.35}
_BASE_BEST_METRICS = {"s11_db_max_in_band": -10.0, "s21_db_mean_in_band": -4.2,
                      "ripple_db": 0.0, "q_fac": 40.0}
_CURR_BEST_PARAMS = {"arm_len_mm": 22.0, "series_w_mm": 0.35, "gap_mm": 0.30}
_CURR_BEST_METRICS = {"s11_db_max_in_band": -12.0, "s21_db_mean_in_band": -4.2,
                      "ripple_db": 0.5, "bw_ghz": 0.4}

_RECIPE = {
    "model": "wilkinson_power_divider",
    "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
    "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
    "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                    "op": "max_below", "value": -15}],
    "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
}

_MODEL_KEYS_SINGLE_RUN = {
    "schema", "run_ref", "goals", "trajectory", "final_design", "diagrams",
    "tradeoff", "pareto", "repro", "anomalies", "base_report",
}
_ENVELOPE_KEYS = {"ok", "run_id", "schema", "report", "diagrams",
                  "design_verdict", "n_gates_pass", "n_gates_fail",
                  "freshness"}


def _write_run(root: Path, name: str, trials: list[dict[str, Any]],
               *, with_recipe: bool = True) -> Path:
    run = root / name
    (run / "trials").mkdir(parents=True)
    for i, tr in enumerate(trials):
        (run / "trials" / f"trial_{i}.json").write_text(
            json.dumps(dict(tr, trial_number=i), indent=1), encoding="utf-8")
    if with_recipe:
        (run / "recipe.snapshot.yaml").write_text(
            yaml.safe_dump(_RECIPE, allow_unicode=True, sort_keys=True),
            encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": name, "model": "wilkinson_power_divider",
        "adapter": "fake", "status": "done"}, indent=1), encoding="utf-8")
    return run


def _make_base(tmp_path: Path) -> Path:
    return _write_run(tmp_path, "run_base", [
        {"params": {"arm_len_mm": 20.0, "series_w_mm": 0.40},
         "metrics": {"s11_db_max_in_band": -9.0, "s21_db_mean_in_band": -4.5,
                     "ripple_db": 0.0, "q_fac": 40.0}, "cost": 6.0},
        {"params": dict(_BASE_BEST_PARAMS),
         "metrics": dict(_BASE_BEST_METRICS), "cost": 5.0},
    ])


def _make_curr(tmp_path: Path) -> Path:
    return _write_run(tmp_path, "run_curr", [
        {"params": {"arm_len_mm": 20.0, "series_w_mm": 0.40},
         "metrics": {"s11_db_max_in_band": -9.0, "s21_db_mean_in_band": -4.5,
                     "ripple_db": 0.0, "bw_ghz": 0.3}, "cost": 6.0},
        {"params": dict(_CURR_BEST_PARAMS),
         "metrics": dict(_CURR_BEST_METRICS), "cost": 3.0},
    ])


def _make_c_run(tmp_path: Path, name: str = "run_c") -> Path:
    """C 校准族形态：meta+calibration/，无 trials 无 results（声明不可得）。"""
    run = tmp_path / name
    (run / "calibration").mkdir(parents=True)
    (run / "calibration" / "gate.json").write_text(json.dumps({
        "verdict": "PASS", "n_samples": 9}), encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": name, "adapter": "calibration:fake", "status": "done"}),
        encoding="utf-8")
    return run


def _make_a_run(tmp_path: Path, name: str = "run_a") -> Path:
    """A 单评族：results/metrics.json（声明=results 面）。"""
    run = tmp_path / name
    (run / "results").mkdir(parents=True)
    (run / "results" / "metrics.json").write_text(json.dumps({
        "run_id": name, "params": {"arm_len_mm": 20.5},
        "metrics": {"s11_db_max_in_band": -11.5}, "cost": 3.5}),
        encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({"run_id": name}),
                                   encoding="utf-8")
    return run


def _strip_sources(node: Any) -> Any:
    """剥除本席注入的 source 键（逐位对拍 design_version_diff 原生信封）。"""
    if isinstance(node, dict):
        return {k: _strip_sources(v) for k, v in node.items() if k != "source"}
    if isinstance(node, list):
        return [_strip_sources(v) for v in node]
    return node


def _section_md(md: str) -> str:
    return md[md.index("## ⑤c"):md.index("## ⑥")]


def _change(node: dict[str, Any], path: str) -> dict[str, Any]:
    return next(c for c in node["changes"] if c["path"] == path)


# ── A 单源逐位（含 falsy-0 与缺键形态） ─────────────────────────────────────


class TestSingleSourceBitwise:
    def test_params_and_metrics_equal_design_version_diff(
            self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        model = build_design_report_model(curr, with_diagrams=False,
                                          diff_run_dir=base)
        diff = model["diff"]
        assert diff["status"] == "ok"
        labels = ("run_base", "run_curr")
        for facet, a, b in (("params", _BASE_BEST_PARAMS, _CURR_BEST_PARAMS),
                            ("metrics", _BASE_BEST_METRICS,
                             _CURR_BEST_METRICS)):
            gold = design_version_diff(a, b, labels=labels)
            got = diff[f"{facet}_diff"]
            assert got["ok"] is True
            assert got["labels"] == gold["labels"] == list(labels)
            assert got["verdict"] == gold["verdict"]
            assert _strip_sources(got["changes"]) == gold["changes"]
            assert _strip_sources(got["summary"]) == gold["summary"]
            # 注入 source 非空（provenance 面）；数值零改写已由上式逐位保证
            assert all(c["source"] for c in got["changes"])
            assert got["summary"]["source"]

    def test_hand_anchor_values_and_kinds(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        diff = build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base)["diff"]
        p = diff["params_diff"]
        assert p["verdict"] == "structural"  # 含 added
        arm = _change(p, "arm_len_mm")
        assert (arm["kind"], arm["a"], arm["b"]) == ("numeric", 21.0, 22.0)
        assert arm["rel_change"] == (22.0 - 21.0) / abs(21.0)
        gap = _change(p, "gap_mm")
        assert gap["kind"] == "added" and gap["b"] == 0.30 and "a" not in gap
        assert not any(c["path"] == "series_w_mm" for c in p["changes"])
        m = diff["metrics_diff"]
        assert m["verdict"] == "structural"  # 含 added+removed
        s11 = _change(m, "s11_db_max_in_band")
        assert s11["rel_change"] == (-12.0 - -10.0) / abs(-10.0) == -0.2
        q = _change(m, "q_fac")
        assert q["kind"] == "removed" and q["a"] == 40.0 and "b" not in q
        bw = _change(m, "bw_ghz")
        assert bw["kind"] == "added" and bw["b"] == 0.4
        assert not any(c["path"] == "s21_db_mean_in_band"
                       for c in m["changes"])
        assert _strip_sources(m["summary"]) == {
            "added": 1, "removed": 1, "numeric": 2}

    def test_zero_base_value_row_present_rel_none(self, tmp_path: Path):
        # #364-④ falsy-0：base ripple_db=0.0 是合法观测值——行必须在场、
        # a 字段==0.0（不得被当缺失顶掉），rel_change 如实 None（不除零）
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        m = build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base)["diff"]["metrics_diff"]
        ripple = _change(m, "ripple_db")
        assert "a" in ripple and ripple["a"] == 0.0 and ripple["a"] is not None
        assert ripple["b"] == 0.5
        assert ripple["kind"] == "numeric"
        assert ripple["rel_change"] is None
        md = _section_md(render_design_report_md(build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base)))
        assert "| ripple_db | numeric | 0 | 0.5 | — |" in md

    def test_md_tables_render_single_source_cells(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        md = _section_md(render_design_report_md(build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base)))
        assert "| arm_len_mm | numeric | 21 | 22 | +4.76% |" in md
        assert "| gap_mm | added | — | 0.3 | — |" in md
        assert "| q_fac | removed | 40 | — | — |" in md
        assert "| s11_db_max_in_band | numeric | -10 | -12 | -20% |" in md
        assert "s21_db_mean_in_band" not in md  # 相等键零行
        assert "series_w_mm" not in md
        assert "verdict=**structural**" in md
        assert "base=`run_base` → 本 run=`run_curr`" in md
        assert "added=1，numeric=1" in md  # params summary 回显（排序键）

    def test_identical_runs_verdict_identical_zero_rows(self, tmp_path: Path):
        curr = _make_curr(tmp_path)
        model = build_design_report_model(curr, with_diagrams=False,
                                          diff_run_dir=curr)
        diff = model["diff"]
        assert diff["status"] == "ok"
        for facet in ("params_diff", "metrics_diff"):
            assert diff[facet]["verdict"] == "identical"
            assert diff[facet]["changes"] == []
            assert _strip_sources(diff[facet]["summary"]) == {}
        md = _section_md(render_design_report_md(model))
        assert md.count("逐键一致：零变更，identical") == 2
        assert "共 0 处变更" in md

    def test_numeric_only_pair_verdict_changed(self, tmp_path: Path):
        base = _make_base(tmp_path)
        curr2 = _write_run(tmp_path, "run_curr2", [
            {"params": {"arm_len_mm": 22.0, "series_w_mm": 0.30},
             "metrics": {"s11_db_max_in_band": -13.0,
                         "s21_db_mean_in_band": -4.2,
                         "ripple_db": 0.1, "q_fac": 42.0}, "cost": 2.0},
        ])
        diff = build_design_report_model(
            curr2, with_diagrams=False, diff_run_dir=base)["diff"]
        assert diff["params_diff"]["verdict"] == "changed"
        assert diff["metrics_diff"]["verdict"] == "changed"
        assert {c["kind"] for c in diff["params_diff"]["changes"]} == {"numeric"}
        gold = design_version_diff(_BASE_BEST_PARAMS,
                                   {"arm_len_mm": 22.0, "series_w_mm": 0.30},
                                   labels=("run_base", "run_curr2"))
        assert _strip_sources(diff["params_diff"]["changes"]) == gold["changes"]

    def test_declaration_sources_recorded(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        diff = build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base)["diff"]
        assert diff["base_ref"]["run_id"] == "run_base"
        assert diff["current_ref"]["run_id"] == "run_curr"
        # 两侧最优=trial_1（§③ 同款 cost 最小重导）
        assert diff["base_ref"]["decl_source"].startswith(
            "trials/trial_1.json")
        assert diff["current_ref"]["decl_source"].startswith(
            "trials/trial_1.json")

    def test_single_eval_family_target_uses_results_metrics(
            self, tmp_path: Path):
        curr = _make_curr(tmp_path)
        a_run = _make_a_run(tmp_path)
        diff = build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=a_run)["diff"]
        assert diff["status"] == "ok"
        assert diff["base_ref"]["decl_source"].startswith(
            "results/metrics.json")
        gold = design_version_diff({"arm_len_mm": 20.5}, _CURR_BEST_PARAMS,
                                   labels=("run_a", "run_curr"))
        assert _strip_sources(diff["params_diff"]["changes"]) == gold["changes"]


# ── B 降级三态 + C 零变化 ───────────────────────────────────────────────────


class TestDegradationAndZeroChange:
    def test_single_run_no_diff_key_no_section(self, tmp_path: Path):
        curr = _make_curr(tmp_path)
        model = build_design_report_model(curr, with_diagrams=False)
        assert "diff" not in model
        assert set(model) == _MODEL_KEYS_SINGLE_RUN  # 既有 11 键零增减
        md = render_design_report_md(model)
        assert "⑤c" not in md and "版本对账" not in md
        headers = [ln for ln in md.splitlines() if ln.startswith("## ")]
        assert headers == [
            "## ① 设计目标与配方摘要",
            "## ② 优化轨迹回放",
            "## ③ 最终设计与 verdict 门表",
            "## ④ 电路图总结（.drawio 附件）",
            "## ⑤ 敏感性 / trade-off 摘要",
            "## ⑤b Pareto 前沿（多目标 run 扩展节）",
            "## ⑥ 复现命令附录",
        ]

    def test_section_inserted_between_5b_and_6(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        md = render_design_report_md(build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base))
        headers = [ln for ln in md.splitlines() if ln.startswith("## ")]
        assert headers[-3:] == [
            "## ⑤b Pareto 前沿（多目标 run 扩展节）",
            "## ⑤c 版本对账（与对比 run 的设计差异）",
            "## ⑥ 复现命令附录",
        ]
        assert len(headers) == 8

    def test_missing_target_dir_degrades_honestly(self, tmp_path: Path):
        curr = _make_curr(tmp_path)
        model = build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=tmp_path / "ghost_run")
        diff = model["diff"]
        assert diff["status"] == "missing"
        assert "不存在" in diff["note"] and "ghost_run" in diff["note"]
        assert diff["params_diff"] is None and diff["metrics_diff"] is None
        md = _section_md(render_design_report_md(model))
        assert "**状态：missing（如实降级）**" in md and "ghost_run" in md
        assert "| 路径 |" not in md  # 不凑表
        assert bare_number_fields(model) == []

    def test_bad_target_no_declaration(self, tmp_path: Path):
        curr = _make_curr(tmp_path)
        c_run = _make_c_run(tmp_path)
        diff = build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=c_run)["diff"]
        assert diff["status"] == "missing"
        assert "run_c" in diff["note"] and "声明不可得" in diff["note"]

    def test_current_run_no_declaration(self, tmp_path: Path):
        base = _make_base(tmp_path)
        c_run = _make_c_run(tmp_path)
        diff = build_design_report_model(
            c_run, with_diagrams=False, diff_run_dir=base)["diff"]
        assert diff["status"] == "missing"
        assert diff["note"].startswith("本 run 最终设计声明不可得")

    def test_all_infeasible_target_degrades(self, tmp_path: Path):
        curr = _make_curr(tmp_path)
        bad = _write_run(tmp_path, "run_infeasible", [
            {"params": {"arm_len_mm": 20.0}, "metrics": {"s11_db": -3.0},
             "cost": 1.0, "constraint_values": {"c1": 5.0}},
        ])
        diff = build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=bad)["diff"]
        assert diff["status"] == "missing"
        assert "run_infeasible" in diff["note"] and "不可行" in diff["note"]

    def test_generate_with_missing_target_still_ok(self, tmp_path: Path):
        curr = _make_curr(tmp_path)
        result = generate_design_report(
            str(curr), output=tmp_path / "dr.md", with_diagrams=False,
            diff_run_id="no_such_run_c2_xyz")
        assert result["ok"] is True  # 对比缺失不升级为错误
        md = (tmp_path / "dr.md").read_text(encoding="utf-8")
        assert "## ⑤c" in md and "如实降级" in md


# ── D provenance + 外发安全 ─────────────────────────────────────────────────


class TestProvenance:
    def test_bare_number_fields_empty_ok_state(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        model = build_design_report_model(curr, with_diagrams=False,
                                          diff_run_dir=base)
        assert bare_number_fields(model) == []

    def test_negative_example_detected(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        model = build_design_report_model(curr, with_diagrams=False,
                                          diff_run_dir=base)
        stripped = json.loads(json.dumps(model))
        del stripped["diff"]["params_diff"]["changes"][0]["source"]
        assert bare_number_fields(stripped) != []
        stripped2 = json.loads(json.dumps(model))
        del stripped2["diff"]["metrics_diff"]["summary"]["source"]
        assert bare_number_fields(stripped2) != []

    def test_md_has_no_absolute_paths(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        md = render_design_report_md(build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base))
        assert str(tmp_path) not in md
        assert str(base) not in md and str(curr) not in md


# ── F 确定性 + 信封 + CLI 叶 + 文案 rider ─────────────────────────────────


class TestDeterminismEnvelopeCli:
    def test_envelope_keys_unchanged_with_diff(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        result = generate_design_report(
            str(curr), output=tmp_path / "dr.md", with_diagrams=False,
            diff_run_id=str(base))
        assert result["ok"] is True
        assert set(result) == _ENVELOPE_KEYS  # 信封零增键（diff 只在模型/md）
        md = (tmp_path / "dr.md").read_text(encoding="utf-8")
        assert "## ⑤c 版本对账（与对比 run 的设计差异）" in md

    def test_md_two_pass_identical_except_timestamp(self, tmp_path: Path):
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        t1 = render_design_report_md(build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base)).splitlines()
        t2 = render_design_report_md(build_design_report_model(
            curr, with_diagrams=False, diff_run_dir=base)).splitlines()
        assert len(t1) == len(t2)
        diffs = [(a, b) for a, b in zip(t1, t2, strict=True) if a != b]
        assert len(diffs) <= 1
        assert all("生成时间" in a and "生成时间" in b for a, b in diffs)

    def test_cli_optional_base_arg_json_and_single_run(self, tmp_path: Path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        base, curr = _make_base(tmp_path), _make_curr(tmp_path)
        out = tmp_path / "dr_cli.md"
        ok = runner.invoke(app, ["design-report", str(curr), str(base),
                                 "--out", str(out), "--no-diagrams", "--json"])
        assert ok.exit_code == 0, ok.output
        envelope = json.loads(ok.output)
        assert envelope["ok"] is True
        assert set(envelope) == _ENVELOPE_KEYS
        md = out.read_text(encoding="utf-8")
        assert "## ⑤c" in md and "| arm_len_mm | numeric | 21 | 22 | +4.76% |" in md
        # 不传第二位置参数=单 run：无 ⑤c（既有调用形态零变化）
        out2 = tmp_path / "dr_cli_single.md"
        ok2 = runner.invoke(app, ["design-report", str(curr),
                                  "--out", str(out2), "--no-diagrams", "--json"])
        assert ok2.exit_code == 0, ok2.output
        assert json.loads(ok2.output)["ok"] is True
        assert "⑤c" not in out2.read_text(encoding="utf-8")

    def test_cli_help_copy_rider_and_hygiene(self):
        from typer.main import get_command

        from rfauto.cli.main import app as root_app

        click_cmd = get_command(root_app).commands["design-report"]
        help_text = click_cmd.help or ""
        # 任务 4 rider：节数口径与实际节清单一致（六节+⑤b Pareto+⑤c 对账）
        assert "Pareto" in help_text and "版本对账" in help_text
        assert "扩展节" in help_text
        # D-06 家法：零裸 [ 零未成对 %（help 卫生门同判定面）
        for text in (help_text, getattr(click_cmd, "short_help", None) or ""):
            assert "[" not in text
            assert text.count("%") % 2 == 0
        # 第二位置参数在册（可选；零新叶）
        names = [p.name for p in click_cmd.params]
        assert names[:2] == ["run_id", "base_run_id"]
        base_param = next(p for p in click_cmd.params if p.name == "base_run_id")
        assert base_param.required is False

    def test_mcp_description_copy_rider_under_350_required_unchanged(self):
        import asyncio

        from rfauto.mcp_server import mcp as server

        tools = {t.name: t for t in asyncio.run(server.list_tools())}
        tool = tools["design_report"]
        desc = tool.description
        assert "Pareto" in desc  # 节数口径含扩展节
        assert len(desc) < 350, f"design_report 描述 {len(desc)} 字符 ≥350"
        assert set(tool.parameters["required"]) == {"run_id"}  # 签名零变化
        assert set(tool.parameters.get("properties") or {}) == {
            "run_id", "out", "with_diagrams"}
