"""aurora_k K16 指标绑定组+收敛门测试（反馈 P14/P6）。

覆盖面（全离线确定性）：
- core.metric_groups 绑定组：series 族 Q 触发附带+提示文案（P14 原话）、
  shunt 族 L/Q/SRF 不提示、容性/感性候选键落位、0.0 合法读数不顶掉
  （#364④ 显式 None 判）、None/空串如实 missing、双族歧义不猜、未知
  族显式拒绝；
- UI 展示链路验证（件一④）：q_factor 词典条目可查询（get_metric ok+
  list keys 含 q_factor）——UI 消费链=/api/metric-glossary → kit.js
  metricBadgeHtml data-mkey 悬浮（view_detail.js 已接线，本席只验证
  数据面在链）；
- service.em_metrics_service：run 目录双路采集（metrics.json 主口径+
  Touchstone K8 家族键 setdefault 补缺）、em_metrics_from_run 绑定信封
  （advisory/missing 入 notes）、convergence_check 判定语义（<10%
  converged / >10% not_converged / 恰等边界 converged（#376 家法：含
  等号边界显式钉）/ 双零 dev=0 / 单零 dev=1 / 别名两侧落位键不同加
  note / insufficient_data 如实 / rel_tol 非法拒绝 / run 目录形态
  mesh_distinct 三态）；
- em sweep 汇总收敛列（K16/P6）：mesh 轴自动识别+相邻档配对
  not_converged/converged、显式 convergence_axis、非法轴名拒绝、无
  mesh 轴零改动（K10 形态不变）、双网格轴歧义不猜；
- CLI 冒烟：em metrics --run/--converged-with --json 信封+人读面
  （advisory/not_converged 文案在 stdout）、--s2p/--run 二选一守卫、
  K8 --s2p 旧路径回归。

隔离（#144）：全程 monkeypatch.chdir(tmp_path)——run 目录落 tmp，
绝不污染仓 runs/ 湖。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.metric_groups import (
    SERIES_ADVISORY,
    bind_metric_group,
    detect_metric_group,
)
from rfauto.service import em_metrics_service as msvc
from rfauto.service import em_sweep_service as svc

# ── 件一：绑定组纯函数 ────────────────────────────────────────────────────────


def test_bind_series_full_family_attaches_all():
    out = bind_metric_group({
        "c_series_f": 173.5, "r_series_ohm": 1.4, "q_series": 12.3,
        "s21_db": -0.4,
    })
    assert out["group"] == "series_family" and out["detected"] is True
    assert out["attached"] == {"c_series_f": 173.5, "r_series_ohm": 1.4,
                               "q_series": 12.3, "s21_db": -0.4}
    assert out["missing"] == []
    # P14 文案触发：series 族 Q 在场 → advisory 恒附
    assert out["advisory"] == SERIES_ADVISORY
    assert out["glossary_ref"] == "q_factor"


def test_bind_series_q_only_marks_rest_missing():
    """只有 Q 在盘：同族其余键如实标 missing（不凑、不编）。"""
    out = bind_metric_group({"q_series": 12.3})
    assert out["group"] == "series_family"
    assert out["attached"] == {"q_series": 12.3}
    assert out["missing"] == ["c_series_f", "l_series_h",
                              "r_series_ohm", "s21_db"]
    assert out["members"]["Q_series"]["status"] == "ok"
    assert out["members"]["C"]["status"] == "missing"
    assert out["advisory"] == SERIES_ADVISORY


def test_bind_shunt_family_no_prompt_even_with_q():
    out = bind_metric_group({
        "l_shunt_h": 4.2e-9, "q_shunt": 30.0, "srf_hz": 8e9,
    })
    assert out["group"] == "shunt_family"
    assert out["attached"] == {"l_shunt_h": 4.2e-9, "q_shunt": 30.0,
                               "srf_hz": 8e9}
    # shunt 族 L/Q/SRF 天然配套——即使 Q 在场也不触发 series 文案
    assert out["advisory"] is None


def test_bind_shunt_capacitive_slot_resolves_c():
    out = bind_metric_group({"c_shunt_f": 173.5, "q_shunt": 30.0})
    assert out["group"] == "shunt_family"
    assert out["members"]["L"] == {"key": "c_shunt_f", "value": 173.5,
                                   "status": "ok"}
    assert out["missing"] == ["srf_hz"]


def test_bind_series_inductive_slot_resolves_l():
    out = bind_metric_group({"l_series_h": 4.2e-9, "q_series": 25.0})
    assert out["members"]["C"]["key"] == "l_series_h"
    assert out["advisory"] == SERIES_ADVISORY


def test_bind_zero_is_legal_reading_not_missing():
    """0.0 是合法读数（#364④：数值可达 0 的面禁 or 惯语顶掉）。"""
    out = bind_metric_group({"r_series_ohm": 0.0, "q_series": 12.3})
    assert out["members"]["R_series"] == {"key": "r_series_ohm", "value": 0.0,
                                          "status": "ok"}


def test_bind_none_and_empty_string_are_missing():
    out = bind_metric_group({"q_series": None, "c_series_f": "",
                             "r_series_ohm": 1.0})
    assert out["group"] is None or out["group"] == "series_family"
    # q_series=None 不算 Q 在场 → 无 advisory；r 在场 → series 族仍判出
    assert out["group"] == "series_family"
    assert out["advisory"] is None
    assert set(out["missing"]) >= {"q_series", "c_series_f", "l_series_h",
                                   "s21_db"}


def test_bind_ambiguous_both_families_returns_none():
    metrics = {"q_series": 1.0, "r_series_ohm": 1.0,
               "q_shunt": 2.0, "srf_hz": 3e9}
    assert detect_metric_group(metrics) is None
    out = bind_metric_group(metrics)
    assert out["group"] is None and out["detected"] is False


def test_bind_unknown_group_raises():
    with pytest.raises(ValueError, match="未知 metric 族"):
        bind_metric_group({}, group="nope")


# ── 件一④：UI 词典链路数据面验证（不改 UI） ─────────────────────────────────


def test_ui_glossary_chain_serves_q_factor():
    """展示链路=/api/metric-glossary（list keys）→ kit.js metricBadgeHtml
    （view_detail.js data-mkey 悬浮）；本测试只验证词典数据面在链。"""
    from rfauto.service.metric_glossary_service import (
        get_metric,
        list_metric_glossary,
    )

    listing = list_metric_glossary()
    assert listing["ok"] is True
    assert "q_factor" in listing["keys"]
    single = get_metric("q_factor")
    assert single["ok"] is True
    entry = single["metric"]
    assert "not mean low loss" in entry["plain_en"]
    assert entry.get("computed_by"), "q_factor 条目带 computed_by 出处"


# ── 件一：run 目录采集 + em_metrics_from_run ────────────────────────────────

_R_DUT, _C_DUT = 1.4, 173.5e-15
_FREQ_GRID = np.linspace(1e9, 5e9, 41)


def _q_series_expect(r_ohm: float = 1.4, c_ff: float = 173.5) -> float:
    """K8 口径期望值：f_eval=带内几何中心的最近栅格点，Q=|X|/R。"""
    center = (1e9 * 5e9) ** 0.5
    f_eval = _FREQ_GRID[int(np.argmin(np.abs(_FREQ_GRID - center)))]
    return (1.0 / (2 * np.pi * f_eval * c_ff * 1e-15)) / r_ohm


def _make_touchstone(run_dir: Path, c_ff: float = 173.5,
                     r_ohm: float = 1.4) -> None:
    """合成 2 端口 T 型串联 RC 的 Touchstone（K8 面可逐位回收的已知量）。"""
    import skrf

    freq = skrf.Frequency.from_f(np.linspace(1e9, 5e9, 41), unit="hz")
    omega = 2 * np.pi * freq.f
    z12 = r_ohm + 1 / (1j * omega * c_ff * 1e-15)
    z = np.zeros((len(freq.f), 2, 2), dtype=complex)
    z[:, 0, 0] = z[:, 1, 1] = z[:, 0, 1] = z[:, 1, 0] = z12
    net = skrf.Network(frequency=freq, s=skrf.network.z2s(z, z0=50), z0=50)
    out = run_dir / "results" / "params.s2p"
    out.parent.mkdir(parents=True, exist_ok=True)
    net.write_touchstone(str(out))


def _make_run(tmp_path: Path, name: str, *, metrics: dict | None,
              mesh: dict | None = None, touchstone: bool = False,
              c_ff: float = 173.5) -> Path:
    run_dir = tmp_path / name
    run_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {"run_id": name, "status": "done", "adapter": "fake"}
    if mesh is not None:
        meta["params"] = mesh
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if metrics is not None:
        (run_dir / "results").mkdir(exist_ok=True)
        (run_dir / "results" / "metrics.json").write_text(
            json.dumps({"metrics": metrics, "cost": 0.1}, ensure_ascii=False),
            encoding="utf-8")
    if touchstone:
        _make_touchstone(run_dir, c_ff=c_ff)
    return run_dir


def test_collect_run_metrics_merges_dual_sources(tmp_path):
    run = _make_run(tmp_path, "r1", metrics={"L_nh": 4.2},
                    touchstone=True)
    out = msvc.collect_run_metrics(run)
    assert out["errors"] == []
    assert out["sources"]["metrics_json"] and out["sources"]["touchstone"]
    assert out["metrics"]["L_nh"] == 4.2
    # K8 家族键来自 Touchstone 现场提取（f_eval=带内几何中心最近栅格点）
    assert out["metrics"]["q_series"] == pytest.approx(
        _q_series_expect(), rel=1e-6)
    assert out["metrics"]["r_series_ohm"] == pytest.approx(1.4, rel=1e-9)
    assert out["mesh"] == {}


def test_collect_run_metrics_mesh_params_and_errors(tmp_path):
    run = _make_run(tmp_path, "r2", metrics=None, mesh={"mesh_mm": 0.5})
    out = msvc.collect_run_metrics(run)
    assert out["mesh"] == {"mesh_mm": 0.5}
    assert out["metrics"] == {}
    # 无 metrics.json 不算失败（sources 如实 None）；Touchstone 缺失逐路报原因
    assert out["sources"]["metrics_json"] is None
    assert any("Touchstone" in e for e in out["errors"])


def test_em_metrics_from_run_binding_and_notes(tmp_path):
    run = _make_run(tmp_path, "r3", metrics={
        "q_series": 12.3, "r_series_ohm": 1.4, "c_series_f": 173.5})
    out = msvc.em_metrics_from_run(run)
    assert out["ok"] is True, out.get("errors")
    assert out["binding"]["group"] == "series_family"
    # C 槽已有 c_series_f 在场——l_series_h 不算 missing；缺的只有 S21
    assert out["binding"]["missing"] == ["s21_db"]
    assert any(SERIES_ADVISORY in n for n in out["notes"])
    assert out["command"] == "em metrics"


def test_em_metrics_from_run_no_family_honest(tmp_path):
    run = _make_run(tmp_path, "r4", metrics={"L_nh": 4.2})
    out = msvc.em_metrics_from_run(run)
    assert out["ok"] is True
    assert out["binding"]["group"] is None
    assert any("不在任何绑定族" in e for e in out["errors"])


def test_em_metrics_from_run_errors(tmp_path):
    out = msvc.em_metrics_from_run(tmp_path / "nope")
    assert out["ok"] is False
    empty = _make_run(tmp_path, "empty", metrics=None)
    out2 = msvc.em_metrics_from_run(empty)
    assert out2["ok"] is False and out2["errors"]


# ── 件二：convergence_check 判定语义 ─────────────────────────────────────────


def test_conv_mapping_below_tol_converged():
    out = msvc.convergence_check({"q_series": 100.0}, {"q_series": 95.0})
    assert out["ok"] and out["verdict"] == "converged"
    assert out["converged"] is True
    assert out["rel_dev"] == pytest.approx(0.05)
    assert out["mesh_distinct"] is None


def test_conv_mapping_above_tol_not_converged():
    out = msvc.convergence_check({"q_series": 100.0}, {"q_series": 120.0})
    assert out["verdict"] == "not_converged" and out["converged"] is False
    assert out["rel_dev"] == pytest.approx(0.2 / 1.2)
    assert any("默认网格能解≠数值可用" in n for n in out["notes"])


def test_conv_boundary_exact_tol_converged():
    """恰等边界（#376 家法）：偏差 == rel_tol 判 converged（>rel_tol 才违约）。"""
    out = msvc.convergence_check({"q_series": 1.0}, {"q_series": 0.9},
                                 rel_tol=0.10)
    assert out["verdict"] == "converged"
    assert out["rel_dev"] == pytest.approx(0.10)


def test_conv_symmetric_denominator_order_invariant():
    a = msvc.convergence_check({"q_series": 1.0}, {"q_series": 1.2})
    b = msvc.convergence_check({"q_series": 1.2}, {"q_series": 1.0})
    assert a["rel_dev"] == b["rel_dev"] == pytest.approx(0.2 / 1.2)
    assert a["verdict"] == b["verdict"] == "not_converged"


def test_conv_double_zero_and_single_zero():
    both = msvc.convergence_check({"q_series": 0.0}, {"q_series": 0.0})
    assert both["converged"] is True and both["rel_dev"] == 0.0
    single = msvc.convergence_check({"q_series": 0.0}, {"q_series": 5.0})
    assert single["converged"] is False and single["rel_dev"] == 1.0


def test_conv_alias_and_case_insensitive_resolution():
    out = msvc.convergence_check({"Q": 12.0}, {"q_factor": 12.5})
    assert out["verdict"] == "converged"
    assert out["values"]["m1"]["key"] == "Q"
    assert out["values"]["m2"]["key"] == "q_factor"
    assert any("落位键不同" in n for n in out["notes"])


def test_conv_direct_key_metric():
    out = msvc.convergence_check({"L_nh": 4.20}, {"L_nh": 4.80},
                                 metric="L_nh")
    assert out["values"]["m1"]["key"] == "L_nh"
    assert out["verdict"] == "not_converged"
    assert out["rel_dev"] == pytest.approx(0.6 / 4.8)


def test_conv_insufficient_data_honest():
    out = msvc.convergence_check({"r_series_ohm": 1.0}, {"q_series": 5.0},
                                 metric="Q")
    assert out["ok"] is True and out["verdict"] == "insufficient_data"
    assert out["converged"] is None
    assert "m1" in out["notes"][0]


def test_conv_rel_tol_validation():
    for bad in (0, -0.1, float("nan"), "abc"):
        out = msvc.convergence_check({"q_series": 1.0}, {"q_series": 1.0},
                                     rel_tol=bad)
        assert out["ok"] is False, bad


def test_conv_unsupported_input_form():
    out = msvc.convergence_check(42, {"q_series": 1.0})
    assert out["ok"] is False and "m1" in out["errors"][0]


def test_conv_run_dirs_mesh_distinct_tri_state(tmp_path):
    fine = _make_run(tmp_path, "fine", metrics={"q_series": 100.0},
                     mesh={"mesh_mm": 0.25})
    coarse = _make_run(tmp_path, "coarse", metrics={"q_series": 95.0},
                       mesh={"mesh_mm": 0.5})
    out = msvc.convergence_check(coarse, fine)
    assert out["verdict"] == "converged"
    assert out["mesh_distinct"] is True
    assert out["values"]["m1"]["mesh"] == {"mesh_mm": 0.5}
    same = _make_run(tmp_path, "same", metrics={"q_series": 99.0},
                     mesh={"mesh_mm": 0.5})
    out2 = msvc.convergence_check(coarse, same)
    assert out2["mesh_distinct"] is False
    assert any("不是网格收敛对" in n for n in out2["notes"])
    missing_dir = msvc.convergence_check(coarse, tmp_path / "nope")
    assert missing_dir["ok"] is False


# ── 件二：em sweep 汇总收敛列 ────────────────────────────────────────────────

_BASE_RECIPE = {
    "model": "idc", "design_name": "IDC",
    "params": {"W_um": 10, "sub_t_um": 200},
    "objectives": [{"metric": "q_series", "op": "target", "value": 12.0,
                    "band": [2.0, 3.0]}],
}


def _sweep_env(tmp_path, monkeypatch, cases_yaml: str, q_by_mesh: dict):
    """搭 sweep 语料+mock 执行核（按 mesh 轴 label 出 Q），返回 (plan, summary)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "base.yaml").write_text(
        yaml.safe_dump(_BASE_RECIPE), encoding="utf-8")
    (tmp_path / "cases.yaml").write_text(cases_yaml, encoding="utf-8")

    def _execute(recipe_path: Path, adapter_name: str) -> dict:
        recipe = yaml.safe_load(Path(recipe_path).read_text(encoding="utf-8"))
        case_id = Path(recipe_path).parent.name
        mesh_label = str((recipe.get("params") or {}).get("mesh", "coarse"))
        run_dir = Path(recipe_path).parent / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(json.dumps(
            {"run_id": case_id, "status": "done", "adapter": adapter_name,
             "params": {"mesh": mesh_label}}), encoding="utf-8")
        (run_dir / "results").mkdir(exist_ok=True)
        (run_dir / "results" / "metrics.json").write_text(json.dumps(
            {"metrics": {"Q": q_by_mesh[mesh_label]}, "cost": 0.1}),
            encoding="utf-8")
        return {"ok": True, "run_id": case_id, "run_dir": str(run_dir)}

    monkeypatch.setattr("rfauto.service.resource_janitor_service.memory_gate",
                        lambda gb: {"ok": True, "available_gb": 99.0,
                                    "threshold_gb": gb, "message": "闸放行",
                                    "channel": "test"})
    plan = svc.plan_sweep(str(tmp_path / "cases.yaml"))
    assert plan["ok"], plan.get("errors")
    run = svc.run_sweep(plan, execute_fn=_execute)
    assert run["ok"], run.get("errors")
    return plan, svc.summarize_sweep(plan)


_MESH_YAML = """
base_recipe: base.yaml
adapter: fake
matrix:
  device: [idc]
  mesh: [coarse, fine]
"""


def test_sweep_mesh_axis_auto_detected_not_converged(tmp_path, monkeypatch):
    plan, summary = _sweep_env(tmp_path, monkeypatch, _MESH_YAML,
                               {"coarse": 100.0, "fine": 120.0})
    assert plan["convergence_axis"] == "mesh"
    assert summary["ok"] and len(summary["convergence_pairs"]) == 1
    pair = summary["convergence_pairs"][0]
    assert pair["metric"] == "Q" and pair["verdict"] == "not_converged"
    assert pair["rel_dev"] == pytest.approx(0.2 / 1.2)
    by_id = {r["case_id"]: r for r in summary["rows"]}
    assert all(r["convergence"].startswith("not_converged(Q")
               for r in by_id.values())
    assert "convergence" in summary["columns"]


def test_sweep_pair_converged(tmp_path, monkeypatch):
    _plan, summary = _sweep_env(tmp_path, monkeypatch, _MESH_YAML,
                                {"coarse": 100.0, "fine": 104.0})
    pair = summary["convergence_pairs"][0]
    assert pair["verdict"] == "converged"
    assert pair["rel_dev"] == pytest.approx(4.0 / 104.0)


def test_sweep_explicit_axis_and_invalid_axis(tmp_path, monkeypatch):
    explicit = _MESH_YAML + "convergence_axis: mesh\n"
    plan, _summary = _sweep_env(tmp_path, monkeypatch, explicit,
                                {"coarse": 100.0, "fine": 101.0})
    assert plan["convergence_axis"] == "mesh"
    bad = _MESH_YAML + "convergence_axis: nope\n"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cases_bad.yaml").write_text(bad, encoding="utf-8")
    plan_bad = svc.plan_sweep(str(tmp_path / "cases_bad.yaml"))
    assert plan_bad["ok"] is False
    assert any("convergence_axis" in e for e in plan_bad["errors"])


def test_sweep_no_mesh_axis_unchanged_shape(tmp_path, monkeypatch):
    legacy = """
base_recipe: base.yaml
adapter: fake
matrix:
  device: [idc]
  thickness: [200, 50]
axis_key:
  thickness: sub_t_um
"""
    plan, summary = _sweep_env(tmp_path, monkeypatch, legacy,
                               {"coarse": 100.0, "fine": 120.0})
    assert plan["convergence_axis"] is None
    assert summary["convergence_pairs"] == []
    assert "convergence" not in summary["columns"]
    assert all("convergence" not in r for r in summary["rows"])


def test_sweep_ambiguous_mesh_axes_no_guess(tmp_path, monkeypatch):
    ambiguous = """
base_recipe: base.yaml
adapter: fake
matrix:
  device: [idc]
  mesh: [coarse, fine]
  grid: [g1, g2]
"""
    plan, _summary = _sweep_env(tmp_path, monkeypatch, ambiguous,
                                {"coarse": 100.0, "fine": 120.0})
    assert plan["convergence_axis"] is None


# ── CLI 冒烟 ─────────────────────────────────────────────────────────────────


def _invoke(*args: str):
    from typer.testing import CliRunner

    from rfauto.cli.main import app as root_app

    return CliRunner().invoke(root_app, ["em", "metrics", *args])


def test_cli_em_metrics_run_json(tmp_path, monkeypatch):
    run = _make_run(tmp_path, "cli1", metrics={
        "q_series": 12.3, "r_series_ohm": 1.4, "c_series_f": 173.5})
    monkeypatch.chdir(tmp_path)
    result = _invoke("--run", str(run), "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["binding"]["group"] == "series_family"
    assert payload["binding"]["advisory"] == SERIES_ADVISORY
    assert payload["metrics"]["q_series"] == 12.3


def test_cli_em_metrics_run_converged_with(tmp_path, monkeypatch):
    fine = _make_run(tmp_path, "fine", metrics={"q_series": 100.0},
                     mesh={"mesh_mm": 0.25})
    coarse = _make_run(tmp_path, "coarse", metrics={"q_series": 120.0},
                       mesh={"mesh_mm": 0.5})
    monkeypatch.chdir(tmp_path)
    result = _invoke("--run", str(coarse), "--converged-with", str(fine),
                     "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    conv = payload["convergence"]
    assert conv["verdict"] == "not_converged"
    assert conv["mesh_distinct"] is True
    assert conv["values"]["m1"]["path"].endswith("coarse")


def test_cli_em_metrics_run_human_output(tmp_path, monkeypatch, capsys):
    run = _make_run(tmp_path, "human", metrics={
        "q_series": 12.3, "r_series_ohm": 1.4})
    monkeypatch.chdir(tmp_path)
    result = _invoke("--run", str(run))
    assert result.exit_code == 0, result.output
    assert "series_family" in result.output
    assert "Q 随 C 变" in result.output
    assert "missing" in result.output


def test_cli_em_metrics_run_touchstone_extraction(tmp_path, monkeypatch):
    run = _make_run(tmp_path, "ts", metrics=None, touchstone=True)
    monkeypatch.chdir(tmp_path)
    result = _invoke("--run", str(run), "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["metrics"]["q_series"] == pytest.approx(
        _q_series_expect(), rel=1e-6)
    assert payload["sources"]["metrics_json"] is None
    assert payload["sources"]["touchstone"]


def test_cli_em_metrics_usage_guards(tmp_path, monkeypatch):
    run = _make_run(tmp_path, "g", metrics={"q_series": 1.0})
    monkeypatch.chdir(tmp_path)
    both = _invoke("--s2p", "x.s2p", "--run", str(run), "--json")
    assert both.exit_code == 2
    assert json.loads(both.output)["ok"] is False
    conv_only = _invoke("--converged-with", str(run), "--json")
    assert conv_only.exit_code == 2
    missing = _invoke("--run", str(tmp_path / "nope"), "--json")
    assert missing.exit_code == 1
    assert json.loads(missing.output)["ok"] is False


def test_cli_em_metrics_s2p_legacy_path_regression(tmp_path, monkeypatch):
    run = tmp_path / "legacy"
    _make_touchstone(run)
    s2p = run / "results" / "params.s2p"
    monkeypatch.chdir(tmp_path)
    result = _invoke("--s2p", str(s2p), "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["series"]["r_series_ohm"] == pytest.approx(1.4, rel=1e-9)
