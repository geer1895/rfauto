"""design_lint 统一门面（W4）单元测试：聚合语义/注册表/各子检查/CLI 双形态。

门面契约（service/design_lint_service.py）：
- lint=聚合器不是新判据：每子检查真调既有 service/core 函数（零 mock 主路径，
  全部合成 payload 离线秒级，不真机）；
- absent/参数不足→unknown 不炸（#105）；检出 fail 必须拦（verdict=issues）；
- bounds 信息级不设门（info 不影响 verdict）；
- CLI exit code 三态：0=无 fail / 1=检出 fail>0 / 2=payload 程序性错误。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service.design_lint_service import LINT_REGISTRY, design_lint

runner = CliRunner()


# ── 注册表与聚合语义 ─────────────────────────────────────────────────────────


class TestRegistryAndAggregate:
    def test_registry_has_expected_checks(self):
        assert set(LINT_REGISTRY.names()) == {
            "constraints", "fab", "bounds", "pdn", "stub"}

    def test_empty_payload_all_unknown_attention(self):
        r = design_lint({})
        assert r["ok"] is True
        assert r["verdict"] == "attention"
        assert len(r["checks"]) == 5
        assert all(row["status"] == "unknown" for row in r["checks"])
        assert r["summary"]["unknown"] == 5
        assert r["summary"]["fail"] == 0

    def test_checks_filter_runs_subset(self):
        r = design_lint({"checks": ["stub", "fab"],
                         "stub": {"stub_len_mm": 10.0, "er_eff": 2.25}})
        assert [row["name"] for row in r["checks"]] == ["stub", "fab"]

    def test_checks_unknown_name_raises_valueerror(self):
        with pytest.raises(ValueError, match="未知子检查"):
            design_lint({"checks": ["nope"]})

    def test_checks_non_list_raises_valueerror(self):
        with pytest.raises(ValueError, match="checks 必须是字符串列表"):
            design_lint({"checks": "stub"})

    def test_duplicate_registration_rejected(self):
        reg = type(LINT_REGISTRY)()
        reg.register("x")(lambda payload: {})
        with pytest.raises(ValueError, match="重复注册"):
            reg.register("x")(lambda payload: {})

    def test_verdict_fail_overrides_attention(self):
        # warn（ratrace 保守扫描）+ fail（stub 带内）并存 → issues 优先
        r = design_lint({"template": "ratrace",
                         "stub": {"stub_len_mm": 10.0, "er_eff": 2.25,
                                  "nyquist_ghz": 6.0}})
        statuses = {row["name"]: row["status"] for row in r["checks"]}
        assert statuses["fab"] == "warn"
        assert statuses["stub"] == "fail"
        assert r["verdict"] == "issues"


# ── fab 子检查 ───────────────────────────────────────────────────────────────


class TestFabCheck:
    def test_pass_on_nominal_mline(self):
        r = design_lint({"checks": ["fab"], "template": "mline"})
        assert r["checks"][0]["status"] == "pass"
        assert r["verdict"] == "clean"

    def test_fail_on_thin_trace_violation(self):
        r = design_lint({"checks": ["fab"], "template": "mline",
                         "params": {"w_mm": 0.05}})
        row = r["checks"][0]
        assert row["status"] == "fail"
        assert "violations" in row["result"]

    def test_fail_on_unknown_template(self):
        r = design_lint({"checks": ["fab"], "template": "no_such_tmpl"})
        assert r["checks"][0]["status"] == "fail"
        assert "未知模板" in r["checks"][0]["detail"]

    def test_warn_on_unregistered_facts_scan(self):
        # ratrace 不在 FAB_GEOMETRY_FACTS → 保守后缀扫描 → 可信度降级 warn
        r = design_lint({"checks": ["fab"], "template": "ratrace"})
        assert r["checks"][0]["status"] == "warn"
        assert r["verdict"] == "attention"


# ── constraints 子检查（Z3 真调，合成 payload 毫秒级） ────────────────────────


class TestConstraintsCheck:
    def test_pass_on_feasible_bounds(self):
        r = design_lint({"checks": ["constraints"],
                         "constraints": {"mesh_resolution_mm":
                                         {"low": 0.4, "high": 0.5},
                                         "gaps_mm": [1.0]}})
        assert r["checks"][0]["status"] == "pass"

    def test_fail_on_unsat_conflict(self):
        # #266 守卫同构：NEAR=base/4 ≤ 缝/3 与 base∈[0.4,0.5] 对 0.14mm 缝不可行
        r = design_lint({"checks": ["constraints"],
                         "constraints": {"mesh_resolution_mm":
                                         {"low": 0.4, "high": 0.5},
                                         "gaps_mm": [0.14]}})
        assert r["checks"][0]["status"] == "fail"
        assert "UNSAT" in r["checks"][0]["detail"]

    def test_top_level_constraint_keys_fallback(self):
        r = design_lint({"checks": ["constraints"],
                         "mesh_resolution_mm": 0.5})
        assert r["checks"][0]["status"] == "pass"

    def test_unknown_when_no_constraint_params(self):
        r = design_lint({"checks": ["constraints"]})
        assert r["checks"][0]["status"] == "unknown"

    def test_fail_on_malformed_config(self):
        r = design_lint({"checks": ["constraints"],
                         "constraints": {"mesh_resolution_mm": "not-a-number"}})
        assert r["checks"][0]["status"] == "fail"

    def test_unknown_when_z3_missing(self, monkeypatch):
        from rfauto.core import render_constraints as rc

        def _boom():
            raise ImportError("No module named 'z3'")

        monkeypatch.setattr(rc, "_import_z3", _boom)
        r = design_lint({"checks": ["constraints"],
                         "constraints": {"mesh_resolution_mm": 0.5}})
        assert r["checks"][0]["status"] == "unknown"
        assert r["verdict"] == "attention"


# ── bounds 子检查（信息级不设门） ─────────────────────────────────────────────


class TestBoundsCheck:
    def test_info_on_bbox_and_freq(self):
        r = design_lint({"checks": ["bounds"],
                         "bounds": {"bbox_m": [0.03, 0.02, 0.005],
                                    "f_ghz": 2.4}})
        row = r["checks"][0]
        assert row["status"] == "info"
        assert row["result"]["chu"]["name"] == "chu_q_min_mclean1996"
        assert row["result"]["directivity"]["sphere_directivity"][
            "limit_value"] is not None
        assert r["verdict"] == "clean"  # info 不影响 verdict

    def test_unknown_when_params_missing(self):
        r = design_lint({"checks": ["bounds"]})
        assert r["checks"][0]["status"] == "unknown"

    def test_fail_on_invalid_bbox(self):
        # 垃圾入参 fail-fast（core bbox_to_ka ValueError）→ 门面如实记 fail
        r = design_lint({"checks": ["bounds"],
                         "bounds": {"bbox_m": [0.0, 0.02], "f_hz": 2.4e9}})
        assert r["checks"][0]["status"] == "fail"


# ── pdn 子检查（腔模真调，纯数学） ────────────────────────────────────────────


_PDN_PLANE = {"plane": {"a_m": 0.02, "b_m": 0.02, "er": 4.4}}


class TestPdnCheck:
    def test_fail_on_cavity_mode_in_band(self):
        # f_10 = (c/2√εr)·(1/a) ≈ 3.577GHz 落入 [3.5, 3.6]GHz
        payload = dict(_PDN_PLANE)
        payload["interest_band"] = {"f_lo_hz": 3.5e9, "f_hi_hz": 3.6e9}
        r = design_lint({"checks": ["pdn"], "pdn": payload})
        assert r["checks"][0]["status"] == "fail"

    def test_pass_on_mode_free_band(self):
        payload = dict(_PDN_PLANE)
        payload["interest_band"] = {"f_lo_hz": 4.6e9, "f_hi_hz": 4.7e9}
        r = design_lint({"checks": ["pdn"], "pdn": payload})
        assert r["checks"][0]["status"] == "pass"
        assert r["verdict"] == "clean"

    def test_unknown_when_plane_absent(self):
        r = design_lint({"checks": ["pdn"], "pdn": {}})
        assert r["checks"][0]["status"] == "unknown"

    def test_unknown_when_pdn_absent(self):
        r = design_lint({"checks": ["pdn"]})
        assert r["checks"][0]["status"] == "unknown"


# ── stub 子检查（HS-2 残桩谐振） ─────────────────────────────────────────────


class TestStubCheck:
    def test_fail_on_in_band_resonance(self):
        # fres(10mm, εr 2.25)≈4.997GHz < 6GHz → STUB_RES 硬违规
        r = design_lint({"checks": ["stub"],
                         "stub": {"stub_len_mm": 10.0, "er_eff": 2.25,
                                  "nyquist_ghz": 6.0}})
        assert r["checks"][0]["status"] == "fail"
        assert r["verdict"] == "issues"

    def test_pass_on_out_of_band_resonance(self):
        r = design_lint({"checks": ["stub"],
                         "stub": {"stub_len_mm": 10.0, "er_eff": 2.25,
                                  "nyquist_ghz": 4.0}})
        assert r["checks"][0]["status"] == "pass"

    def test_info_without_nyquist(self):
        # nyquist_ghz 缺省 → 只出 STUB_RES_INFO 信息行，不算违规
        r = design_lint({"checks": ["stub"],
                         "stub": {"stub_len_mm": 10.0, "er_eff": 2.25}})
        assert r["checks"][0]["status"] == "info"
        assert r["verdict"] == "clean"

    def test_unknown_when_stub_params_insufficient(self):
        r = design_lint({"checks": ["stub"], "stub": {"stub_len_mm": 10.0}})
        assert r["checks"][0]["status"] == "unknown"


# ── CLI 双形态 + exit code 三态 ──────────────────────────────────────────────


class TestCliLint:
    def test_lint_no_payload_exit_zero_reports_unknown(self):
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 0
        assert "unknown" in result.output

    def test_lint_payload_fail_exit_one(self, tmp_path: Path):
        p = tmp_path / "lint_payload.json"
        p.write_text(json.dumps(
            {"stub": {"stub_len_mm": 10.0, "er_eff": 2.25,
                      "nyquist_ghz": 6.0}}), encoding="utf-8")
        result = runner.invoke(app, ["lint", str(p)])
        assert result.exit_code == 1
        assert "issues" in result.output

    def test_lint_json_output_parseable(self, tmp_path: Path):
        p = tmp_path / "lint_payload.json"
        p.write_text(json.dumps({"checks": ["fab"], "template": "mline"}),
                     encoding="utf-8")
        result = runner.invoke(app, ["lint", str(p), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["verdict"] == "clean"
        assert data["checks"][0]["name"] == "fab"

    def test_lint_bad_checks_file_exit_two(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"checks": ["nope"]}), encoding="utf-8")
        result = runner.invoke(app, ["lint", str(p)])
        assert result.exit_code == 2

    def test_lint_missing_payload_file_exit_two(self):
        result = runner.invoke(app, ["lint", "no_such_payload.json"])
        assert result.exit_code == 2

    def test_lint_registered_top_level(self):
        names = {cmd.name for cmd in app.registered_commands}
        assert "lint" in names
