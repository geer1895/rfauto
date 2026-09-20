"""接线层装车测试（内核能力接入生产路径的回归钉）。

三个"造了零件没装上车"的内核接进生产路径的回归钉：
- 零件 1：pipeline/self_heal.self_heal_loop → service.self_heal_service.
  self_heal_run_for_run → MCP self_heal_run / CLI self-heal run（只读诊断）
- 零件 2：pipeline/log_distiller → ①run_once 收尾 best-effort 钩子
  （runs/<id>/log_digest.json，#105 异常吞掉）②CLI logs digest / MCP log_digest
- 零件 3：core/dispersion → service.dispersion_service.dispersion_fitness_report
  → CLI materials dispersion-report / MCP dispersion_report（只读报告，不改
  模板/适配器渲染）

全部离线（零网络、零真机、零 LLM）；run 目录一律 chdir 隔离（#144）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service.dispersion_service import dispersion_fitness_report
from rfauto.service.self_heal_service import (
    log_digest_for_path,
    self_heal_run_for_run,
    write_log_digest_for_run,
)

runner = CliRunner()

# openEMS 网格守卫失守的真实指纹（#152）：timestep 塌缩 + CalcPort IndexError
_TIMESTEP_COLLAPSE_LOG = """\
[INFO] openEMS v0.6.35 -- start
time step: 1.2e-13 s
CalcPort: port_index out of range
Traceback (most recent call last):
IndexError: calcport index error
return code: 1
"""


def _make_run(tmp_path: Path, run_id: str, log_text: str) -> Path:
    """隔离 cwd 下手工搭最小 run 目录（meta.json 为真伪判据，#144）。"""
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps({
        "run_id": run_id, "model": "wilkinson_power_divider",
        "adapter": "openems", "status": "done",
    }), encoding="utf-8")
    (run_dir / "solver.log").write_text(log_text, encoding="utf-8")
    return run_dir


def _call_mcp(tool_name: str, arguments: dict) -> dict:
    """经 fastmcp call_tool 真调用（原 diagnose 死壳正是调用期才炸，#270）。"""
    from rfauto.mcp_server import mcp

    result = asyncio.run(mcp.call_tool(tool_name, arguments))
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return json.loads(result.content[0].text)


# ─── 零件 1：self_heal_loop 只读自愈环装车 ────────────────────────────────────

class TestSelfHealRunWiring:
    def test_failed_run_diagnosed_with_cause_and_actions(self, tmp_path, monkeypatch):
        """正常路径：#152 指纹日志 → diagnosed + 根因/教训/建议动作。"""
        monkeypatch.chdir(tmp_path)
        _make_run(tmp_path, "r_fail", _TIMESTEP_COLLAPSE_LOG)

        result = self_heal_run_for_run("r_fail")

        assert result["ok"] is True
        assert result["verdict"] == "diagnosed"
        assert result["root_cause_id"] in {"timestep_collapse", "calcport_index_error"}
        assert result["lesson_ref"] == "#152"
        assert result["severity"] == "error"
        assert result["actions"], "过根因目录命中时必须给建议动作"
        assert any("#152" in a or "网格" in a for a in result["actions"])
        assert result["llm_used"] is False, "铁律 7：判定与建议不出自 LLM"
        assert result["advisory_only"] is True
        assert "Gate" in result["note"]
        assert result["digest"]["ok"] is True
        assert result["log_surface_chars"] > 0

    def test_clean_run_verdict_clean(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_run(tmp_path, "r_ok", "[INFO] simulation finished successfully\nreturn code: 0\n")

        result = self_heal_run_for_run("r_ok")

        assert result["ok"] is True
        assert result["verdict"] == "clean"
        assert result["root_cause_id"] is None
        assert result["actions"] == []

    def test_missing_run_returns_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self_heal_run_for_run("no_such_run")
        assert result["ok"] is False
        assert result["errors"]
        assert "meta.json" in result["errors"][0]

    def test_mcp_self_heal_run_end_to_end(self, tmp_path, monkeypatch):
        """经 fastmcp call_tool 真调用（可调用性双检之外的运行期证据）。"""
        monkeypatch.chdir(tmp_path)
        _make_run(tmp_path, "r_mcp", _TIMESTEP_COLLAPSE_LOG)

        data = _call_mcp("self_heal_run", {"run_id": "r_mcp"})

        assert data["ok"] is True
        assert data["verdict"] == "diagnosed"
        assert data["actions"]

    def test_cli_self_heal_run(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_run(tmp_path, "r_cli", _TIMESTEP_COLLAPSE_LOG)

        result = runner.invoke(app, ["self-heal", "run", "r_cli"])
        assert result.exit_code == 0, result.output
        assert "diagnosed" in result.output

        result_json = runner.invoke(app, ["self-heal", "run", "r_cli", "--json"])
        assert result_json.exit_code == 0, result_json.output
        data = json.loads(result_json.output)
        assert data["verdict"] == "diagnosed"


# ─── 零件 2：LogDistiller 收尾钩子 + CLI/MCP 消费端 ──────────────────────────

class TestLogDigestWiring:
    def test_write_log_digest_writes_structured_digest(self, tmp_path):
        """正常路径：失败日志面 → log_digest.json（rc/签名落盘可解析）。"""
        run_dir = _make_run(tmp_path, "r_digest", _TIMESTEP_COLLAPSE_LOG)

        result = write_log_digest_for_run(run_dir)

        assert result["ok"] is True
        out = Path(result["path"])
        assert out == run_dir / "log_digest.json"
        assert out.is_file()
        digest = json.loads(out.read_text(encoding="utf-8"))
        assert digest["ok"] is True
        assert digest["rc"] == 1
        assert "calcport_index_error" in digest["signatures"]
        assert digest["metrics"]["timestep_s"] == pytest.approx(1.2e-13)

    def test_write_log_digest_skips_empty_surface(self, tmp_path):
        """空 run（无文本产物）→ 跳过不写文件，不报错。"""
        run_dir = tmp_path / "runs" / "r_empty"
        run_dir.mkdir(parents=True)

        result = write_log_digest_for_run(run_dir)

        assert result["ok"] is True
        assert result["skipped"] is True
        assert not (run_dir / "log_digest.json").exists()

    def test_write_log_digest_swallows_internal_errors(self, tmp_path, monkeypatch):
        """best-effort 异常路径（#105）：蒸馏内核抛异常 → 降级信封，绝不外抛。"""
        run_dir = _make_run(tmp_path, "r_boom", "some log\n")

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("rfauto.pipeline.log_distiller.distill_log", _boom)

        result = write_log_digest_for_run(run_dir)

        assert result["ok"] is False
        assert result["skipped"] is True
        assert "boom" in result["reason"]

    def test_run_once_finalize_hook_writes_log_digest(self, tmp_path, monkeypatch):
        """生产接线证据：fake run_once 收尾后 runs/<id>/log_digest.json 存在。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        recipe = {
            "model": "wilkinson_power_divider",
            "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(recipe), encoding="utf-8")

        from rfauto.service.api import run_once

        result = run_once(recipe_path, adapter_name="fake")
        assert result["ok"] is True, result

        digest_path = Path(result["run_dir"]) / "log_digest.json"
        assert digest_path.is_file(), "run_once 收尾钩子应落 log_digest.json"
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
        assert digest["ok"] is True

    def test_log_digest_for_path_file_and_missing(self, tmp_path):
        log_path = tmp_path / "solver.log"
        log_path.write_text("time step: 5e-17 s\n[Error] diverged\n", encoding="utf-8")

        result = log_digest_for_path(log_path)
        assert result["ok"] is True
        assert result["digest"]["metrics"]["timestep_s"] == pytest.approx(5e-17)
        assert "timestep_collapse" in result["digest"]["signatures"]

        missing = log_digest_for_path(tmp_path / "nope.log")
        assert missing["ok"] is False
        assert missing["errors"]

    def test_cli_logs_digest_and_mcp_log_digest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        log_path = tmp_path / "openems_stdout.log"
        log_path.write_text(_TIMESTEP_COLLAPSE_LOG, encoding="utf-8")

        cli_result = runner.invoke(app, ["logs", "digest", str(log_path)])
        assert cli_result.exit_code == 0, cli_result.output
        assert "calcport_index_error" in cli_result.output

        mcp_result = _call_mcp("log_digest", {"path": str(log_path)})
        assert mcp_result["ok"] is True
        assert mcp_result["digest"]["rc"] == 1


# ─── 零件 3：D1 色散适应性报告（最小安全口径，只读） ─────────────────────────

class TestDispersionReportWiring:
    def test_ro4350b_in_band_constant_approximation_ok(self):
        """正常路径：RO4350B 1–10GHz 带内 ε' 漂移 < 2% 门 → 常数近似成立。"""
        result = dispersion_fitness_report("rogers4350b_h0.508_dispersion", [1.0, 10.0])

        assert result["ok"] is True
        assert result["gate"]["passed"] is True
        assert result["gate"]["verdict"] == "constant_eps_r_ok"
        assert result["eps_r_drift_pct"] < 2.0
        assert result["eps_r_at_meas"] == pytest.approx(3.66)
        assert result["tan_delta_at_meas"] == pytest.approx(0.0037, rel=1e-6)
        assert len(result["samples"]) >= 2
        assert "correction" not in result, "过门不应给修正参数"
        assert "rogers4350b_h0.508_dispersion" in result["config_note"]
        assert "语义变更" in result["follow_up_note"]

    def test_wide_band_over_gate_offers_openems_correction(self):
        """过门路径：全拟合带 1MHz–200GHz 漂移 > 2% → 修正建议含 openEMS 参数，
        且参数回代 D-S 核在测量点精确复原 datasheet 值（确定性内核自洽）。"""
        result = dispersion_fitness_report("rogers4350b_h0.508_dispersion", [0.001, 200.0])

        assert result["ok"] is True
        assert result["gate"]["passed"] is False
        assert result["gate"]["verdict"] == "dispersion_recommended"
        correction = result["correction"]
        kwargs = correction["openems_sarkar_kwargs"]
        assert kwargs["epsRMeas"] == pytest.approx(3.66)
        assert kwargs["tandMeas"] == pytest.approx(0.0037)
        assert kwargs["fMeas"] == pytest.approx(10e9)

        from rfauto.core.dispersion import DjordjevicSarkar

        rebuilt = DjordjevicSarkar.from_single_point(
            eps_r=kwargs["epsRMeas"], loss_tangent=kwargs["tandMeas"],
            f_meas_hz=kwargs["fMeas"], f1_hz=kwargs["f1"], f2_hz=kwargs["f2"])
        assert float(rebuilt.epsilon_r(10e9)) == pytest.approx(3.66, rel=1e-9)
        assert float(rebuilt.loss_tangent(10e9)) == pytest.approx(0.0037, rel=1e-9)

    def test_default_band_uses_fit_band(self):
        result = dispersion_fitness_report("rogers4350b_h0.508_dispersion")
        assert result["ok"] is True
        assert result["band_ghz"][0] == pytest.approx(0.001, rel=1e-6)
        assert result["band_ghz"][1] == pytest.approx(200.0, rel=1e-6)

    def test_material_without_dispersion_entry_reports_available(self):
        """常数 εr 材料如实报不可评估 + 给出可用色散材料（不臆造漂移）。"""
        result = dispersion_fitness_report("fr4_h1.6", [1.0, 10.0])

        assert result["ok"] is False
        assert "dispersion" in result["errors"][0]
        assert "rogers4350b_h0.508_dispersion" in result["available_dispersion_materials"]

    def test_unknown_material_and_bad_band_return_errors(self):
        unknown = dispersion_fitness_report("no_such_material", [1.0, 10.0])
        assert unknown["ok"] is False
        assert unknown["errors"]

        bad_band = dispersion_fitness_report(
            "rogers4350b_h0.508_dispersion", [10.0, 1.0])
        assert bad_band["ok"] is False
        assert "f_low <= f_high" in bad_band["errors"][0]

    def test_cli_and_mcp_dispersion_report(self):
        cli_result = runner.invoke(app, [
            "materials", "dispersion-report", "rogers4350b_h0.508_dispersion",
            "1.0", "10.0"])
        assert cli_result.exit_code == 0, cli_result.output
        assert "constant_eps_r_ok" in cli_result.output

        mcp_result = _call_mcp("dispersion_report", {
            "material": "rogers4350b_h0.508_dispersion",
            "band_ghz": [1.0, 10.0],
        })
        assert mcp_result["ok"] is True
        assert mcp_result["gate"]["passed"] is True
