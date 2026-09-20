"""G11 求解健康度体检器测试——历史教训（#174/#195/#152/1.0491）四态覆盖。

- core/solve_health.py：合成 skrf.Network / S 矩阵 / cost 序列构造
  PASS / WARN / FAIL / UNKNOWN 四态，多 FAIL 叠加 verdict=unhealthy，
  单项检查异常不传染（#105）；九因子含 §10.21 补强的 power_balance
  （∫q dV vs P_in(1−Σ|S|²)，non_passive FAIL / rel>3% WARN）与
  thermal_plausibility（热源非负 / #233 恒温陷阱 / 额定超温 / 量级窗）。
- service/health_service.py：tmp_path 手写假 run 目录端到端
  （meta.json / trials/*.json / Touchstone / sparams.csv / run.log /
  port_beta.csv / dump_type=29 体 dump + SAR 自算 / 已知热归档 JSON）。
- CLI：typer CliRunner 驱动 ``rfauto runs health <run_id>`` 薄壳。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from rfauto.core.solve_health import solve_health_check
from rfauto.service.health_service import health_check_run

runner = CliRunner()


# ---------------------------------------------------------------------------
# 合成数据助手
# ---------------------------------------------------------------------------

def _healthy_s(n_freq: int = 64, n_ports: int = 2) -> np.ndarray:
    """健康无源互易 S 矩阵：|S11|=0.1、|Sij(i≠j)|=0.9，互易且无增益。"""
    s = np.zeros((n_freq, n_ports, n_ports), dtype=complex)
    for i in range(n_ports):
        s[:, i, i] = 0.1
        for j in range(n_ports):
            if i != j:
                s[:, i, j] = 0.9
    return s


def _freq_hz(n_freq: int = 64) -> np.ndarray:
    return np.linspace(2e9, 3e9, n_freq)


def _network(s: np.ndarray | None = None):
    """内存构造 skrf.Network（顶层不 import，按用例需要）。"""
    import skrf

    s = _healthy_s() if s is None else s
    freq = skrf.Frequency.from_f(_freq_hz(len(s)), unit="Hz")
    return skrf.Network(frequency=freq, s=s)


def _factor_map(report: dict) -> dict:
    return {f["factor"]: f for f in report["factors"]}


# ---------------------------------------------------------------------------
# core 内核：#174 激励体积死
# ---------------------------------------------------------------------------

class TestExcitationCheck:
    def test_all_zero_s_fails(self):
        """#174：全带宽透射峰值为 0（<1e-6）→ FAIL excitation_dead。"""
        s = np.zeros((32, 2, 2), dtype=complex)
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        f = _factor_map(report)["excitation"]
        assert f["status"] == "FAIL"
        assert f["lesson_ref"] == "#174"
        assert report["verdict"] == "unhealthy"
        assert report["ok"] is False

    def test_single_port_all_zero_fails(self):
        """单端口无透射列，退化口径：全零 |S11| 同为激励死指纹。"""
        s = np.zeros((32, 1, 1), dtype=complex)
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        assert _factor_map(report)["excitation"]["status"] == "FAIL"

    def test_weak_but_nonzero_passes(self):
        """峰值 1e-4（弱耦合但激励活着）不误报。"""
        s = _healthy_s(32)
        s[:, 1, 0] = 1e-4
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        assert _factor_map(report)["excitation"]["status"] == "PASS"

    def test_missing_s_unknown(self):
        report = solve_health_check(freq_hz=None, s_matrix=None)
        assert _factor_map(report)["excitation"]["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# core 内核：#195 cost 退化常数
# ---------------------------------------------------------------------------

class TestCostCheck:
    def test_constant_cost_fails(self):
        """#195：6 个 trial cost 全等 → FAIL cost_degenerate。"""
        report = solve_health_check(costs=[3.95] * 6)
        f = _factor_map(report)["cost_distribution"]
        assert f["status"] == "FAIL"
        assert f["lesson_ref"] == "#195"

    def test_near_constant_variance_fails(self):
        """方差 <1e-12（浮点长尾噪声级）同样判退化。"""
        costs = [3.0, 3.0 + 1e-6, 3.0 - 1e-6, 3.0 + 1e-7, 3.0 - 1e-7, 3.0]
        assert np.var(costs) < 1e-12
        report = solve_health_check(costs=costs)
        assert _factor_map(report)["cost_distribution"]["status"] == "FAIL"

    def test_varied_cost_passes(self):
        report = solve_health_check(costs=[3.9, 2.1, 0.5, 1.2, 3.3, 0.8])
        assert _factor_map(report)["cost_distribution"]["status"] == "PASS"

    def test_too_few_trials_unknown(self):
        """4 个全等 trial 样本不足 → UNKNOWN 不误报。"""
        report = solve_health_check(costs=[3.95] * 4)
        f = _factor_map(report)["cost_distribution"]
        assert f["status"] == "UNKNOWN"
        assert report["verdict"] == "healthy"  # UNKNOWN 不进 verdict

    def test_missing_cost_unknown(self):
        report = solve_health_check(costs=None)
        assert _factor_map(report)["cost_distribution"]["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# core 内核：#152 CFL 时间步塌缩
# ---------------------------------------------------------------------------

class TestTimestepCheck:
    def test_collapsed_timestep_fails(self):
        """#152：min/max 比 1e-6 < 1e-3 → FAIL timestep_collapse。"""
        report = solve_health_check(timestep_values=[1.7e-13, 1.7e-19])
        f = _factor_map(report)["timestep"]
        assert f["status"] == "FAIL"
        assert f["lesson_ref"] == "#152"
        assert report["verdict"] == "unhealthy"

    def test_stable_timestep_passes(self):
        report = solve_health_check(timestep_values=[1.7e-13, 1.72e-13])
        assert _factor_map(report)["timestep"]["status"] == "PASS"

    def test_missing_unknown(self):
        """字段缺失 → UNKNOWN 不误报（#152 惯例）。"""
        f = _factor_map(solve_health_check(timestep_values=None))["timestep"]
        assert f["status"] == "UNKNOWN"

    def test_single_record_unknown(self):
        f = _factor_map(solve_health_check(timestep_values=[1.7e-13]))["timestep"]
        assert f["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# core 内核：1.0491 探针窗
# ---------------------------------------------------------------------------

class TestProbeScaleCheck:
    def test_ratio_in_window_warns(self):
        """两端口 εeff 比值 1.0491 落窗 → WARN probe_scale_anomaly（不 FAIL）。"""
        eps = {"port1": 2.33, "port2": 2.33 * 1.0491}
        report = solve_health_check(eps_eff_by_port=eps)
        f = _factor_map(report)["probe_scale"]
        assert f["status"] == "WARN"
        assert report["verdict"] == "suspect"
        assert report["ok"] is False  # suspect 不可采信

    def test_symmetry_declaration_passes(self):
        """镜像对称声明可解释窗内比值 → 降为 PASS。"""
        eps = {"port1": 2.33, "port2": 2.33 * 1.0491}
        report = solve_health_check(eps_eff_by_port=eps, mirror_symmetric=True)
        assert _factor_map(report)["probe_scale"]["status"] == "PASS"
        assert report["verdict"] == "healthy"

    def test_ratio_outside_window_passes(self):
        report = solve_health_check(eps_eff_by_port={"port1": 2.0, "port2": 3.0})
        assert _factor_map(report)["probe_scale"]["status"] == "PASS"

    def test_missing_or_single_port_unknown(self):
        assert _factor_map(solve_health_check(eps_eff_by_port=None))["probe_scale"]["status"] == "UNKNOWN"
        assert _factor_map(solve_health_check(eps_eff_by_port={"port1": 2.33}))["probe_scale"]["status"] == "UNKNOWN"

    def test_list_input_normalized(self):
        report = solve_health_check(eps_eff_by_port=[2.33, 2.33 * 1.0491])
        assert _factor_map(report)["probe_scale"]["status"] == "WARN"


# ---------------------------------------------------------------------------
# core 内核：无源性 / 互易性 / 非物理增益（SpecEvaluator 口径）
# ---------------------------------------------------------------------------

class TestPassivityReciprocityGain:
    def test_passivity_violation_fails(self):
        s = _healthy_s(32)
        s[:, 1, 0] = 1.5
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        assert _factor_map(report)["passivity"]["status"] == "FAIL"

    def test_passivity_within_tolerance_passes(self):
        s = _healthy_s(32)
        s[:, 1, 0] = 1.005
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        assert _factor_map(report)["passivity"]["status"] == "PASS"

    def test_reciprocity_violation_fails(self):
        s = _healthy_s(32)
        s[:, 0, 1] = 0.9 + 0.1j  # 与 S21 相差 0.1 ≥ 0.01
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        assert _factor_map(report)["reciprocity"]["status"] == "FAIL"

    def test_reciprocity_generalizes_to_three_ports(self):
        """从 SpecEvaluator 的 (0,1)/(1,0) 推广到全部 i<j 端口对。"""
        s = _healthy_s(32, n_ports=3)
        s[:, 2, 1] = 0.9
        s[:, 1, 2] = 0.5  # |S32−S23|=0.4
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        assert _factor_map(report)["reciprocity"]["status"] == "FAIL"

    def test_reciprocity_single_port_not_applicable(self):
        s = np.ones((16, 1, 1), dtype=complex) * 0.3
        report = solve_health_check(freq_hz=_freq_hz(16), s_matrix=s)
        assert _factor_map(report)["reciprocity"]["status"] == "PASS"

    def test_unphysical_gain_fails(self):
        """全带宽透射均值 >0.5 dB → FAIL unphysical_gain（|S21|=1.2 → 1.58dB）。"""
        s = _healthy_s(32)
        s[:, 1, 0] = 1.2
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        f = _factor_map(report)["gain"]
        assert f["status"] == "FAIL"
        assert report["verdict"] == "unhealthy"

    def test_physical_transmission_passes(self):
        s = _healthy_s(32)
        s[:, 1, 0] = 0.9  # −0.92 dB
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=s)
        assert _factor_map(report)["gain"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# core 内核：报告形态 / verdict / 不传染 / skrf 入参
# ---------------------------------------------------------------------------

class TestReportShape:
    def test_healthy_report_all_pass(self):
        """健康合成 run：提供全输入的 7 项老因子全 PASS，verdict=healthy，
        新两因子（power_balance/thermal_plausibility）无输入 → UNKNOWN 共 9 项。"""
        report = solve_health_check(
            freq_hz=_freq_hz(),
            s_matrix=_healthy_s(),
            costs=[3.9, 2.1, 0.5, 1.2, 3.3, 0.8],
            timestep_values=[1.7e-13, 1.71e-13],
            eps_eff_by_port={"port1": 2.33, "port2": 2.33},
        )
        assert report["ok"] is True
        assert report["verdict"] == "healthy"
        assert len(report["factors"]) == 9
        assert all(f["status"] == "PASS" for f in report["factors"][:7])
        statuses = {f["factor"]: f["status"] for f in report["factors"]}
        assert statuses["power_balance"] == "UNKNOWN"
        assert statuses["thermal_plausibility"] == "UNKNOWN"
        for f in report["factors"]:
            assert set(f) >= {"factor", "status", "detail", "lesson_ref"}
        json.dumps(report, ensure_ascii=False)  # JSON 友好

    def test_multi_fail_stacks_to_unhealthy(self):
        """多 FAIL 叠加：零激励 + cost 退化 + timestep 塌缩 → unhealthy。"""
        report = solve_health_check(
            freq_hz=_freq_hz(32),
            s_matrix=np.zeros((32, 2, 2), dtype=complex),
            costs=[3.95] * 6,
            timestep_values=[1.7e-13, 1.7e-19],
        )
        statuses = {f["factor"]: f["status"] for f in report["factors"]}
        assert statuses["excitation"] == "FAIL"
        assert statuses["cost_distribution"] == "FAIL"
        assert statuses["timestep"] == "FAIL"
        assert report["verdict"] == "unhealthy"

    def test_single_check_exception_does_not_propagate(self, monkeypatch):
        """单项检查炸 → 该项 UNKNOWN，其余项照常评估（#105）。"""
        def _boom(s_matrix):
            raise RuntimeError("synthetic boom")

        monkeypatch.setattr("rfauto.core.solve_health._check_passivity", _boom)
        report = solve_health_check(freq_hz=_freq_hz(32), s_matrix=_healthy_s(32))
        f = _factor_map(report)["passivity"]
        assert f["status"] == "UNKNOWN"
        assert "synthetic boom" in f["detail"]
        # 其余项不受传染
        assert _factor_map(report)["excitation"]["status"] == "PASS"
        assert _factor_map(report)["gain"]["status"] == "PASS"
        assert report["verdict"] == "healthy"

    def test_malformed_cost_input_contained(self):
        """畸形输入在检查内部爆炸 → 该项 UNKNOWN 而非整体抛异常。"""
        report = solve_health_check(costs={"a": object()})
        assert _factor_map(report)["cost_distribution"]["status"] == "UNKNOWN"

    def test_skrf_network_input(self):
        """network= 入参（duck-type .s/.frequency.f）与裸数组等价。"""
        via_net = solve_health_check(network=_network())
        via_arr = solve_health_check(freq_hz=_freq_hz(), s_matrix=_healthy_s())
        assert via_net == via_arr

    def test_provenance_dict_merge(self):
        """provenance dict 携带 timestep/eps/mirror，kwargs 缺省时生效。"""
        report = solve_health_check(
            provenance={
                "timesteps": [1.7e-13, 1.7e-19],
                "eps_eff_by_port": {"port1": 2.33, "port2": 2.33 * 1.0491},
                "mirror_symmetric": True,
            },
        )
        statuses = {f["factor"]: f["status"] for f in report["factors"]}
        assert statuses["timestep"] == "FAIL"       # provenance 的塌缩记录生效
        assert statuses["probe_scale"] == "PASS"    # 对称声明生效（WARN 降 PASS）


# ---------------------------------------------------------------------------
# service 层：假 run 目录端到端
# ---------------------------------------------------------------------------

def _write_meta(run_dir: Path, **extra) -> None:
    meta = {"run_id": run_dir.name, "model": "wilkinson_power_divider", "adapter": "fake",
            "status": "done", "schema_version": "1.0"}
    meta.update(extra)
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_trials(run_dir: Path, costs: list[float]) -> None:
    trials = run_dir / "trials"
    trials.mkdir(parents=True, exist_ok=True)
    for i, cost in enumerate(costs):
        (trials / f"trial_{i}.json").write_text(
            json.dumps({"trial_number": i, "params": {"x": 1.0},
                        "metrics": {"s11_db_max_in_band": -10.0}, "cost": cost}),
            encoding="utf-8",
        )


def _write_sparams_csv(run_dir: Path, s21: float = 0.9, rel: Path | None = None) -> None:
    target = run_dir / (rel or Path("fdtd"))
    target.mkdir(parents=True, exist_ok=True)
    lines = ["freq_hz,re_S11,im_S11,re_S21,im_S21"]
    for k in range(5):
        lines.append(f"{2e9 + k * 0.25e9:.1f},0.1,0.0,{s21},0.0")
    (target / "sparams.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_port_beta(run_dir: Path, betas: list[float], n_freq: int = 4) -> None:
    cols = ",".join(["freq_hz"] + [f"beta{i + 1}_rad_per_m" for i in range(len(betas))])
    lines = [cols]
    for k in range(n_freq):
        f = 2e9 + k * 0.25e9
        lines.append(",".join([f"{f:.1f}"] + [f"{b:.6f}" for b in betas]))
    (run_dir / "port_beta.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestHealthCheckRun:
    def test_missing_run_dir(self, tmp_path):
        result = health_check_run("no_such_run", runs_dir=tmp_path)
        assert result["ok"] is False
        assert result["factors"] == []
        assert "不存在" in result["errors"][0]

    def test_empty_run_dir(self, tmp_path):
        (tmp_path / "ghost_run").mkdir()
        result = health_check_run("ghost_run", runs_dir=tmp_path)
        assert result["ok"] is False
        assert any("无可识别体检产物" in e for e in result["errors"])

    def test_meta_only_run_is_not_ok(self, tmp_path):
        run_dir = tmp_path / "meta_only"
        run_dir.mkdir()
        _write_meta(run_dir)
        result = health_check_run("meta_only", runs_dir=tmp_path)
        assert result["ok"] is False

    def test_end_to_end_healthy_run(self, tmp_path):
        """meta+trials+Touchstone+run.log+port_beta 全齐且健康 → healthy。"""
        run_dir = tmp_path / "healthy_run"
        (run_dir / "results").mkdir(parents=True)
        _write_meta(run_dir)
        _write_trials(run_dir, [3.9, 2.1, 0.5, 1.2, 3.3, 0.8])
        _network(_healthy_s()).write_touchstone(str(run_dir / "results" / "params.s2p"))
        (run_dir / "run.log").write_text(
            "FDTD timestep is: 1.7e-13 s\n"      # 激励 1（双激励 openEMS 惯例）
            "FDTD timestep is: 1.7e-13 s\n"      # 激励 2：同量级 → PASS
            "Max. number of timesteps: 100000\n",
            encoding="utf-8",
        )
        _write_port_beta(run_dir, [80.0, 80.0])

        result = health_check_run("healthy_run", runs_dir=tmp_path)
        assert result["ok"] is True
        assert result["verdict"] == "healthy"
        assert result["meta"]["adapter"] == "fake"
        statuses = {f["factor"]: f["status"] for f in result["factors"]}
        assert statuses["excitation"] == "PASS"
        assert statuses["cost_distribution"] == "PASS"
        assert statuses["timestep"] == "PASS"
        assert statuses["passivity"] == "PASS"
        assert statuses["probe_scale"] == "PASS"

    def test_end_to_end_unhealthy_run(self, tmp_path):
        """cost 恒定 + 全零 sparams.csv → 双 FAIL verdict=unhealthy。"""
        run_dir = tmp_path / "sick_run"
        run_dir.mkdir()
        _write_meta(run_dir)
        _write_trials(run_dir, [3.95] * 6)
        _write_sparams_csv(run_dir, s21=0.0)

        result = health_check_run("sick_run", runs_dir=tmp_path)
        statuses = {f["factor"]: f["status"] for f in result["factors"]}
        assert statuses["excitation"] == "FAIL"
        assert statuses["cost_distribution"] == "FAIL"
        assert result["verdict"] == "unhealthy"
        assert result["ok"] is False

    def test_openems_csv_products_and_unknown_fill(self, tmp_path):
        """只有 sparams.csv（openEMS schema）：S 检查生效，缺失因子 UNKNOWN。"""
        run_dir = tmp_path / "csv_run"
        run_dir.mkdir()
        _write_sparams_csv(run_dir, s21=0.9)

        result = health_check_run("csv_run", runs_dir=tmp_path)
        assert result["verdict"] == "healthy"
        statuses = {f["factor"]: f["status"] for f in result["factors"]}
        assert statuses["excitation"] == "PASS"
        assert statuses["passivity"] == "PASS"
        assert statuses["cost_distribution"] == "UNKNOWN"  # 无 trials → 不误报
        assert statuses["timestep"] == "UNKNOWN"
        assert statuses["probe_scale"] == "UNKNOWN"

    def test_run_log_timestep_collapse_detected(self, tmp_path):
        """run.log 双激励 timestep 塌缩（#152）→ FAIL。"""
        run_dir = tmp_path / "cfl_run"
        run_dir.mkdir()
        _write_sparams_csv(run_dir, s21=0.9)
        (run_dir / "run.log").write_text(
            "FDTD timestep is: 1.7e-13 s\n"
            "FDTD timestep is: 2.1e-19 s\n",  # 塌缩 6 个量级
            encoding="utf-8",
        )
        result = health_check_run("cfl_run", runs_dir=tmp_path)
        f = {x["factor"]: x for x in result["factors"]}["timestep"]
        assert f["status"] == "FAIL"
        assert f["lesson_ref"] == "#152"
        assert result["verdict"] == "unhealthy"

    def test_port_beta_probe_anomaly_warns(self, tmp_path):
        """port_beta.csv 反推 εeff 比值 1.0491 → WARN probe_scale_anomaly。"""
        run_dir = tmp_path / "probe_run"
        run_dir.mkdir()
        _write_sparams_csv(run_dir, s21=0.9)
        # εeff ∝ β²：比值 1.0491 ← β2/β1 = √1.0491
        _write_port_beta(run_dir, [80.0, 80.0 * np.sqrt(1.0491)])

        result = health_check_run("probe_run", runs_dir=tmp_path)
        f = {x["factor"]: x for x in result["factors"]}["probe_scale"]
        assert f["status"] == "WARN"
        assert result["verdict"] == "suspect"
        assert result["ok"] is False

    def test_trials_cost_ordering_by_trial_number(self, tmp_path):
        """trial 文件乱序落盘时按 trial_number 排序收集 cost。"""
        run_dir = tmp_path / "order_run"
        trials = run_dir / "trials"
        trials.mkdir(parents=True)
        costs = [3.0, 1.0, 5.0, 2.0, 4.0]
        for i, cost in zip((2, 0, 4, 1, 3), costs, strict=True):
            (trials / f"trial_{i}.json").write_text(
                json.dumps({"trial_number": i, "cost": cost}), encoding="utf-8",
            )
        _write_sparams_csv(run_dir, s21=0.9)
        result = health_check_run("order_run", runs_dir=tmp_path)
        f = {x["factor"]: x for x in result["factors"]}["cost_distribution"]
        assert f["status"] == "PASS"
        assert f["evidence"]["n_trials"] == 5


# ---------------------------------------------------------------------------
# CLI 薄壳：rfauto runs health <run_id>
# ---------------------------------------------------------------------------

@pytest.fixture()
def cli_run_env(tmp_path, monkeypatch):
    """chdir 隔离到 tmp_path，服务层解析相对 runs/ 目录（#144 惯例）。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestCliRunsHealth:
    def _make_healthy(self, base: Path, run_id: str = "cli_ok") -> None:
        run_dir = base / "runs" / run_id
        run_dir.mkdir(parents=True)
        _write_sparams_csv(run_dir, s21=0.9)
        _write_trials(run_dir, [3.9, 2.1, 0.5, 1.2, 3.3])

    def test_healthy_run_exits_zero(self, cli_run_env):
        self._make_healthy(cli_run_env)
        result = runner.invoke(app_for_test(), ["runs", "health", "cli_ok"])
        assert result.exit_code == 0, result.output
        assert "healthy" in result.output

    def test_unhealthy_run_exits_one(self, cli_run_env):
        run_dir = cli_run_env / "runs" / "cli_bad"
        run_dir.mkdir(parents=True)
        _write_trials(run_dir, [3.95] * 6)
        _write_sparams_csv(run_dir, s21=0.0)
        result = runner.invoke(app_for_test(), ["runs", "health", "cli_bad"])
        assert result.exit_code == 1
        assert "unhealthy" in result.output

    def test_missing_run_exits_one(self, cli_run_env):
        result = runner.invoke(app_for_test(), ["runs", "health", "ghost"])
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_json_output(self, cli_run_env):
        self._make_healthy(cli_run_env, "cli_json")
        result = runner.invoke(app_for_test(), ["runs", "health", "cli_json", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["verdict"] == "healthy"
        assert len(payload["factors"]) == 9


def app_for_test():
    """延迟 import CLI app（避免模块级 import 拖慢其余用例收集）。"""
    from rfauto.cli.main import app

    return app


class TestNaNGuard:
    """全 NaN S 参数不得假 PASS（健康门禁穿透防线）。"""

    def test_all_nan_sparams_not_false_pass(self):
        nf, np_ = 11, 2
        s = np.full((nf, np_, np_), np.nan, dtype=complex)
        res = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, nf), s_matrix=s)
        factors = {f["factor"]: f["status"] for f in res["factors"]}
        # 激励/互易/增益对全 NaN 退化为 UNKNOWN，不得给 PASS
        assert factors.get("excitation") == "UNKNOWN"
        assert factors.get("reciprocity") == "UNKNOWN"
        assert factors.get("gain") == "UNKNOWN"
        assert factors.get("passivity") == "UNKNOWN"

    def test_partial_nan_pair_skipped_not_false_pass(self):
        # 部分频点 NaN：有限值参与统计，NaN 不贡献假证据
        nf, npt = 21, 2
        rng = np.random.default_rng(7)
        s = (rng.normal(size=(nf, npt, npt)) * 0.1)
        s[:10, :, :] = np.nan  # 前 10 点全 NaN
        res = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, nf), s_matrix=s)
        factors = {f["factor"]: f["status"] for f in res["factors"]}
        assert factors.get("passivity") in ("PASS", "FAIL")
        assert factors.get("excitation") in ("PASS", "FAIL")


# ---------------------------------------------------------------------------
# §10.21 补强：power_balance / thermal_plausibility 内核四态
# ---------------------------------------------------------------------------

class TestPowerBalanceCheck:
    def test_appended_not_reordered(self):
        """顺序契约：新两因子追加在尾部，前 7 项顺序不变（消费方按序渲染）。"""
        report = solve_health_check()
        names = [f["factor"] for f in report["factors"]]
        assert names == [
            "excitation", "cost_distribution", "timestep", "probe_scale",
            "passivity", "reciprocity", "gain", "power_balance",
            "thermal_plausibility",
        ]

    def test_closed_within_tolerance_passes(self):
        report = solve_health_check(power_balance_inputs={
            "field_power_w": 1.0 * (1.0 - 0.2) * 1.01,  # rel ≈ 0.99%
            "incident_power_w": 1.0, "reflected_fraction": 0.2})
        f = _factor_map(report)["power_balance"]
        assert f["status"] == "PASS"
        assert f["evidence"]["rel_error"] <= 0.03

    def test_open_over_tolerance_warns_not_fails(self):
        """rel > 3% → WARN 不 FAIL：dump 覆盖不全/辐射是诊断不是病，
        防误杀既有归档 run 进 dataset health_gate。"""
        report = solve_health_check(power_balance_inputs={
            "field_power_w": 0.5, "incident_power_w": 1.0,
            "reflected_fraction": 0.1})
        f = _factor_map(report)["power_balance"]
        assert f["status"] == "WARN"
        assert report["verdict"] == "suspect"
        assert report["ok"] is False

    def test_non_passive_s_row_fails(self):
        """Σ|S_ij|² > 1（S 行非无源）→ FAIL，耗散功率为负。"""
        report = solve_health_check(power_balance_inputs={
            "field_power_w": 1e-3, "incident_power_w": 1.0,
            "s_row": [0.9 + 0.5j, 0.9 - 0.5j]})  # Σ|S|² = 2.12
        f = _factor_map(report)["power_balance"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["non_passive"] is True
        assert report["verdict"] == "unhealthy"

    def test_field_power_only_unknown_keeps_evidence(self):
        """只有 ∫q dV（归档无 P_in 口径）→ UNKNOWN 但证据已留。"""
        report = solve_health_check(power_balance_inputs={
            "field_power_w": 9.6e-27, "reflected_fraction": 0.46})
        f = _factor_map(report)["power_balance"]
        assert f["status"] == "UNKNOWN"
        assert f["evidence"]["field_power_w"] == pytest.approx(9.6e-27)
        assert f["evidence"]["reflected_fraction"] == pytest.approx(0.46)

    def test_sparams_power_side_direct(self):
        """耗散功率直接给定（不经 P_in·(1−Σ|S|²)）也能闭合。"""
        f = _factor_map(solve_health_check(power_balance_inputs={
            "field_power_w": 0.98, "sparams_power_w": 1.0}))["power_balance"]
        assert f["status"] == "PASS"

    def test_nan_inputs_unknown_not_false_pass(self):
        """同族：NaN/Inf 入参 → UNKNOWN，不因比较恒 False 假 PASS。"""
        for bad in ({"field_power_w": float("nan"), "incident_power_w": 1.0,
                     "reflected_fraction": 0.1},
                    {"field_power_w": 1.0, "incident_power_w": float("inf"),
                     "reflected_fraction": 0.1},
                    {"field_power_w": 1.0, "s_row": [complex("nan")]},
                    {"field_power_w": 1.0, "tolerance": 1.5}):
            f = _factor_map(solve_health_check(power_balance_inputs=bad))["power_balance"]
            assert f["status"] == "UNKNOWN", bad

    def test_bogus_input_keys_contained(self):
        """畸形 dict（不可解析键值）→ 该项 UNKNOWN，不炸体检（#105）。"""
        f = _factor_map(solve_health_check(
            power_balance_inputs={"incident_power_w": object()}))["power_balance"]
        assert f["status"] == "UNKNOWN"

    def test_provenance_fallback_for_new_factors(self):
        report = solve_health_check(provenance={
            "power_balance": {"field_power_w": 0.98, "sparams_power_w": 1.0},
            "thermal": {"rise_k": 6.0, "heat_source_w": 100.0},
        })
        statuses = {f["factor"]: f["status"] for f in report["factors"]}
        assert statuses["power_balance"] == "PASS"
        assert statuses["thermal_plausibility"] == "PASS"


class TestThermalPlausibilityCheck:
    def test_negative_heat_source_fails(self):
        """热源 < 0 → FAIL（方案 §10.21 G11 行原文：热源非负）→ verdict unhealthy。"""
        report = solve_health_check(thermal_inputs={"heat_source_w": -1.0, "rise_k": 5.0})
        f = _factor_map(report)["thermal_plausibility"]
        assert f["status"] == "FAIL"
        assert report["verdict"] == "unhealthy"

    def test_positive_source_zero_rise_fails_233_trap(self):
        """正热源且 ΔT==0 → FAIL（#233 Elmer HeatSolver 恒温陷阱）。"""
        f = _factor_map(solve_health_check(thermal_inputs={
            "t_max_c": 25.0, "t_ambient_c": 25.0, "heat_source_w": 5.0}))["thermal_plausibility"]
        assert f["status"] == "FAIL"
        assert "#233" in f["lesson_ref"]

    def test_tmax_over_material_rating_fails(self):
        """T_max > material_rating_c → FAIL（D3-2 稳态 7215°C 非物理族）。"""
        f = _factor_map(solve_health_check(thermal_inputs={
            "t_max_c": 7215.0, "material_rating_c": 150.0}))["thermal_plausibility"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["t_max_c"] == pytest.approx(7215.0)

    def test_magnitude_window_out_warns(self):
        """ΔT/(P·R_th) 出 [0.1, 10] 量级窗 → WARN（诊断量）。"""
        report = solve_health_check(thermal_inputs={
            "t_max_c": 219.73, "t_ambient_c": 25.0, "heat_source_w": 0.5,
            "thermal_resistance_k_per_w": 3.3625})  # ΔT=194.73 vs P·R=1.68
        f = _factor_map(report)["thermal_plausibility"]
        assert f["status"] == "WARN"
        assert f["evidence"]["rise_ratio"] > 10.0
        assert report["verdict"] == "suspect"

    def test_real_archive_anchors_pass(self):
        """真档裁判数值：COMSOL 炉 ΔT=6.374K/P=637.9W 与 icepak 锚
        rise=0.7938K（=0.5W×1.5875K/W，相对差 6.3e-5）都应 PASS。"""
        d32 = solve_health_check(thermal_inputs={
            "rise_k": 6.373947868736336, "heat_source_w": 637.8948769854694})
        assert _factor_map(d32)["thermal_plausibility"]["status"] == "PASS"
        icepak = solve_health_check(thermal_inputs={
            "rise_k": 0.793800000000001,
            "heat_source_w": 0.5, "thermal_resistance_k_per_w": 1.5875})
        f = _factor_map(icepak)["thermal_plausibility"]
        assert f["status"] == "PASS"
        assert 0.1 <= f["evidence"]["rise_ratio"] <= 10.0

    def test_all_nan_unknown_not_fake_pass(self):
        """同族：全 NaN 热入参 → UNKNOWN，不得假 PASS。"""
        f = _factor_map(solve_health_check(thermal_inputs={
            "t_max_c": float("nan"), "t_ambient_c": float("nan"),
            "heat_source_w": float("nan")}))["thermal_plausibility"]
        assert f["status"] == "UNKNOWN"

    def test_all_missing_unknown(self):
        f = _factor_map(solve_health_check())["thermal_plausibility"]
        assert f["status"] == "UNKNOWN"
        assert "无热产物" in f["detail"]

    def test_rise_k_overrides_tmax_minus_ambient(self):
        """rise_k 显式给出时优先于 t_max_c − t_ambient_c。"""
        f = _factor_map(solve_health_check(thermal_inputs={
            "t_max_c": 219.73, "t_ambient_c": 25.0, "rise_k": 0.7938,
            "heat_source_w": 0.5, "thermal_resistance_k_per_w": 1.5875}))["thermal_plausibility"]
        assert f["status"] == "PASS"
        assert f["evidence"]["delta_t_k"] == pytest.approx(0.7938)

    def test_input_power_w_as_heat_source_fallback(self):
        """无 heat_source_w 时 input_power_w 充当热源（同判负值/恒温/量级窗）。"""
        f = _factor_map(solve_health_check(thermal_inputs={
            "input_power_w": -0.5}))["thermal_plausibility"]
        assert f["status"] == "FAIL"


# ---------------------------------------------------------------------------
# §10.21 补强：service 层 dump 功率 + 热归档发现（h5py 逐用例探测）
# ---------------------------------------------------------------------------

def _write_sar_raw_h5(path: Path, freq_hz: float = 2.5e9) -> None:
    """最小 dump_type=29 体 dump（均匀场/均匀 σ，闭式 P=0.5σ|E0|²V）。"""
    h5py = pytest.importorskip("h5py")
    import numpy as _np

    shape, e0, sigma = (4, 3, 2), 40.0, 0.02
    spacing = (0.5e-3, 0.5e-3, 1.0e-3)
    with h5py.File(path, "w") as h:
        h.attrs["dump_type"] = _np.int32(29)
        mesh = h.create_group("Mesh")
        mesh.attrs["mesh_scaling"] = 1.0
        cw = h.create_group("CellWidth")
        cw.attrs["mesh_scaling"] = 1.0
        for name, n, s in zip("xyz", shape, spacing, strict=True):
            cw.create_dataset(name, data=_np.full(n, s))
            mesh.create_dataset(name, data=_np.linspace(0.0, n * s, n))
        fd = h.create_group("FieldData").create_group("FD")
        fd.attrs["frequency"] = _np.array([freq_hz])
        e = _np.zeros((3, *shape), dtype=_np.complex64)
        e[0] = e0
        fd.create_dataset("f0", data=e).attrs["d_order"] = "NXYZ"
        cd = h.create_group("CellData")
        cd.create_dataset("Conductivity", data=_np.full(shape, sigma, dtype=_np.float32))
        vol = _np.prod(spacing)
        cd.create_dataset("Volume", data=_np.full(shape, vol, dtype=_np.float32))


def _write_sar_1g_h5(path: Path, power_w: float, freq_hz: float = 2.5e9) -> None:
    h5py = pytest.importorskip("h5py")
    import numpy as _np

    with h5py.File(path, "w") as h:
        fd = h.create_group("FieldData").create_group("FD")
        fd.attrs["frequency"] = _np.array([freq_hz], dtype=_np.float32)
        ds = fd.create_dataset("f0", data=_np.ones((4, 3, 2), dtype=_np.float32))
        ds.attrs["power"] = _np.float32(power_w)
        ds.attrs["frequency"] = _np.float32(freq_hz)


class TestDumpAndThermalDiscovery:
    def test_dump_power_wired_with_selfcheck(self, tmp_path):
        """体 dump → field_power_w + sparams 插值 s_row + SAR 自检 ≤1e-3；
        P_in 无归档口径 → power_balance UNKNOWN 只留证据。"""
        run = tmp_path / "dump_run"
        (run / "fdtd").mkdir(parents=True)
        _write_sar_raw_h5(run / "fdtd" / "SAR_raw.h5")
        p_closed = 0.5 * 0.02 * 40.0**2 * (4 * 3 * 2 * 0.5e-3 * 0.5e-3 * 1e-3)
        _write_sar_1g_h5(run / "fdtd" / "SAR_1g.h5", p_closed)
        _write_sparams_csv(run, s21=0.9)  # 2–3 GHz，覆盖 dump 频点 2.5 GHz
        result = health_check_run("dump_run", runs_dir=tmp_path)
        statuses = {f["factor"]: f["status"] for f in result["factors"]}
        assert statuses["power_balance"] == "UNKNOWN"
        ev = {x["factor"]: x for x in result["factors"]}["power_balance"]["evidence"]
        assert ev["field_power_w"] == pytest.approx(p_closed, rel=1e-5)
        assert ev["reflected_fraction"] == pytest.approx(0.1**2 + 0.9**2)
        ld = result["loss_dump"]
        assert ld["freq_hz"] == 2.5e9
        assert ld["sar_power_selfcheck_rel"] <= 1e-3
        assert ld["s_row_at_dump_freq"] == [[0.1, 0.0], [0.9, 0.0]]

    def test_thermal_archive_d32_mapping(self, tmp_path):
        """d32_closure_summary.json → thermal PASS（ΔT=6.374K，P=637.9W）。"""
        run = tmp_path / "oven_run"
        run.mkdir()
        (run / "d32_closure_summary.json").write_text(json.dumps({
            "transient_run": {
                "t_max_c": 64.37296682516069,
                "p_absorbed_w": 637.8948769854694,
                "measured_delta_t_k": 6.373947868736336,
                "predicted_delta_t_k": 6.373942850721081,
            }}), encoding="utf-8")
        result = health_check_run("oven_run", runs_dir=tmp_path)
        statuses = {f["factor"]: f["status"] for f in result["factors"]}
        assert statuses["thermal_plausibility"] == "PASS"
        assert result["thermal_source"]["archive_json"].endswith("d32_closure_summary.json")
        assert "transient_run.measured_delta_t_k->rise_k" in result["thermal_source"]["source_keys"]
        json.dumps(result, ensure_ascii=False)  # JSON 友好

    def test_pure_thermal_run_gets_real_check_not_suspect_by_absence(self, tmp_path):
        """『全空』早退扩到新产物：纯热归档进得了真体检（不再 suspect-by-absence）。"""
        run = tmp_path / "thermal_only"
        run.mkdir()
        (run / "closure.json").write_text(json.dumps({
            "transient_run": {"t_max_c": 7215.0, "p_absorbed_w": 637.9,
                              "measured_delta_t_k": 6900.0}}), encoding="utf-8")
        result = health_check_run("thermal_only", runs_dir=tmp_path)
        assert result["factors"], "纯热归档不得走无可识别产物早退"
        statuses = {f["factor"]: f["status"] for f in result["factors"]}
        # t_max=7215°C 无额定 → 量级窗缺 R_th 不判 → PASS（非恒温/非负热源）
        assert statuses["thermal_plausibility"] == "PASS"
        assert statuses["power_balance"] == "UNKNOWN"
        assert result["verdict"] == "healthy"

    def test_meta_thermal_block_wins_over_archive_json(self, tmp_path):
        run = tmp_path / "meta_thermal"
        run.mkdir()
        (run / "meta.json").write_text(json.dumps({
            "run_id": "meta_thermal", "thermal": {"t_max_c": 64.0, "t_ambient_c": 63.0,
                                                  "heat_source_w": 100.0}}), encoding="utf-8")
        (run / "closure.json").write_text(json.dumps({
            "transient_run": {"t_max_c": 1.0, "p_absorbed_w": 1.0,
                              "measured_delta_t_k": 1.0}}), encoding="utf-8")
        result = health_check_run("meta_thermal", runs_dir=tmp_path)
        f = {x["factor"]: x for x in result["factors"]}["thermal_plausibility"]
        assert f["status"] == "PASS"
        assert f["evidence"]["delta_t_k"] == pytest.approx(1.0)
        assert result["thermal_source"]["archive_json"] == "meta.json"

    def test_icepak_sim_anchor_priority_no_cross_block_mixing(self, tmp_path):
        """icepak 归档：anchor.sim 真跑锚优先，不与 chain.thermal 注入场景混合。"""
        run = tmp_path / "et_run"
        run.mkdir()
        (run / "electrothermal_case.json").write_text(json.dumps({
            "icepak": {"anchor": {"sim": {"t_sim_c": 25.7938,
                                          "rise_sim_k": 0.793800000000001,
                                          "rise_closed_form_k": 0.79375}}},
            "chain": {"thermal": {"t_hot_c": 219.73, "ambient_c": 25.0,
                                  "rise_k": 194.73}}}), encoding="utf-8")
        result = health_check_run("et_run", runs_dir=tmp_path)
        f = {x["factor"]: x for x in result["factors"]}["thermal_plausibility"]
        assert f["status"] == "PASS"
        assert f["evidence"]["delta_t_k"] == pytest.approx(0.793800000000001)
        assert "t_max_c" not in f["evidence"]  # 注入的 t_hot_c 不混入
        assert result["thermal_source"]["source_keys"] == ["icepak.anchor.sim.rise_sim_k->rise_k"]

    def test_negative_source_archive_fails_gate(self, tmp_path):
        """热源为负的归档 → thermal FAIL → verdict unhealthy（门禁可拦）。"""
        run = tmp_path / "bad_thermal"
        run.mkdir()
        (run / "meta.json").write_text(json.dumps({
            "run_id": "bad_thermal", "thermal": {"heat_source_w": -2.0, "rise_k": 1.0}}),
            encoding="utf-8")
        result = health_check_run("bad_thermal", runs_dir=tmp_path)
        statuses = {f["factor"]: f["status"] for f in result["factors"]}
        assert statuses["thermal_plausibility"] == "FAIL"
        assert result["verdict"] == "unhealthy"
