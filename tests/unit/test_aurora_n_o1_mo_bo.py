"""aurora_n O1 mo_bo 服务包装接线回归钉（2026-10-31）。

O1（runs/aurora_n/zero_wiring/REGISTRY.md）：mo_bo.MultiObjectiveBO
（T-N13 模型驱动 MO-BO，715 行）全仓零消费者——运行时无任何门。本席
三层补门（service/CLI/MCP），本件钉其上：

- service e2e：run_mo_bo 合成族环 ok 信封（HV 曲线单调不降、前沿非空、
  n_evaluations=预算、JSON 往返无损）；
- 确定性钉：同 seed 同参数两次调用 hv_curve/front/front_params/
  acquisitions/ref_point 逐位一致（内核 G4 家法）；
- 负例：未知合成族/指标 1/代理不支持多输出/预算与 ref 点非法——全部
  error_envelope 显式报错，不抛裸 traceback；
- CLI 薄壳钉：`rfauto mo run --json` 成功+失败同构信封（#24/#231 棘轮
  家法）+ --ref-point 解析负例走 usage 信封（exit 2）；
- MCP 薄壳钉：mo_run 注册在位 + ref_point 空串哨兵/逗号解析负例信封。
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.mo_bo_service import (
    MO_PROBLEM_REGISTRY,
    MO_SURROGATE_KINDS,
    MultiObjectiveProblem,
    register_problem,
    run_mo_bo,
)


@pytest.fixture(autouse=True)
def _isolated(isolated_cache_off):
    """cwd 隔离单源委托（tests/conftest.py::isolated_cache_off，#144 家法）。"""
    yield


# ── service e2e ──────────────────────────────────────────────────────────────


class TestRunMoBoEnvelope:
    def test_zdt1_end_to_end(self):
        r = run_mo_bo("zdt1", n_eval=20, seed=0)
        assert r["ok"], r.get("errors")
        assert r["kind"] == "zdt1"
        assert r["metrics"] == ["f1", "f2"]
        assert r["n_evaluations"] == 20
        assert r["n_eval_budget"] == 20
        # hv_curve：初始 1 点 + n_iter 轮逐批（n_iter = (20−6)//1 = 14）
        assert len(r["hv_curve"]) == r["n_iter"] + 1
        # 单调不降（EHVI 贪心收集性质；浮点逐位比较安全——非下降）
        hv = r["hv_curve"]
        assert all(b >= a for a, b in itertools.pairwise(hv))
        assert hv[-1] >= hv[0]
        # 前沿非空且目标值逐点有限
        assert r["front"]
        for pt in r["front"]:
            assert len(pt) == 2 and all(v == v and abs(v) != float("inf")
                                        for v in pt)
        # 前沿参数与采集轨迹同构
        assert len(r["front_params"]) == len(r["front"])
        assert len(r["acquisitions"]) == r["n_iter"] * r["batch_size"]
        assert r["info"]["kind"] == "mo_bo_ehvi_greedy"
        assert r["ref_source"] == "frozen"
        # JSON 往返（服务层 JSON 进出，规则 4）
        json.dumps(r, allow_nan=False)

    def test_dtlz2_two_metrics(self):
        r = run_mo_bo("dtlz2", n_eval=12, seed=0)
        assert r["ok"], r.get("errors")
        assert r["metrics"] == ["f1", "f2"]
        assert r["n_obj"] == 2
        assert r["n_params"] == 3
        assert r["front"]

    def test_dtlz2_three_metrics_mc_path_small_pool(self):
        # M>2 走 MC 采集路径（内核 _score_candidates MC 分支）；小池控时
        r = run_mo_bo("dtlz2", n_eval=10, n_obj=3, n_candidates=32,
                      mc_samples=16, seed=0)
        assert r["ok"], r.get("errors")
        assert r["metrics"] == ["f1", "f2", "f3"]
        assert r["n_obj"] == 3
        assert r["front"] and len(r["front"][0]) == 3
        json.dumps(r, allow_nan=False)

    def test_explicit_ref_point_echoed(self):
        r = run_mo_bo("zdt1", n_eval=6, ref_point=[1.5, 11.0], seed=0)
        assert r["ok"], r.get("errors")
        assert r["ref_source"] == "explicit"
        assert r["ref_point"] == [1.5, 11.0]

    def test_no_samples_flag_omits_samples(self):
        r = run_mo_bo("zdt1", n_eval=6, include_samples=False)
        assert r["ok"] and "samples" not in r
        r2 = run_mo_bo("zdt1", n_eval=6)
        assert r2["ok"] and len(r2["samples"]) == r2["n_evaluations"]

    def test_smt_kriging_arm(self):
        # 第二支持键（逐指标独立 GP 口）全链可达
        r = run_mo_bo("zdt1", n_eval=8, surrogate_kind="smt_kriging", seed=0)
        assert r["ok"], r.get("errors")
        assert r["surrogate_kind"] == "smt_kriging"
        assert r["front"]


class TestDeterminism:
    def test_same_seed_bitwise_identical(self):
        a = run_mo_bo("zdt1", n_eval=16, seed=7)
        b = run_mo_bo("zdt1", n_eval=16, seed=7)
        assert a["ok"] and b["ok"]
        assert a["hv_curve"] == b["hv_curve"]
        assert a["front"] == b["front"]
        assert a["front_params"] == b["front_params"]
        assert a["acquisitions"] == b["acquisitions"]
        assert a["ref_point"] == b["ref_point"]
        assert a["samples"] == b["samples"]

    def test_explicit_ref_determinism_dtlz2(self):
        a = run_mo_bo("dtlz2", n_eval=10, n_obj=3, n_candidates=32,
                      mc_samples=16, seed=3)
        b = run_mo_bo("dtlz2", n_eval=10, n_obj=3, n_candidates=32,
                      mc_samples=16, seed=3)
        assert a["hv_curve"] == b["hv_curve"]
        assert a["acquisitions"] == b["acquisitions"]


# ── 负例（显式报错信封，不抛裸异常）─────────────────────────────────────────


class TestNegativeCases:
    def test_unknown_kind(self):
        r = run_mo_bo("no_such_problem")
        assert not r["ok"]
        assert any("可用" in e and "zdt1" in e for e in r["errors"])

    def test_single_objective_rejected(self):
        # 负例=指标 1：退化标量问题显式拒绝并指引 SBO 通道
        r = run_mo_bo("dtlz2", n_obj=1)
        assert not r["ok"]
        assert any("SBO" in e for e in r["errors"])

    def test_surrogate_without_multi_output_contract_rejected(self):
        # 负例=代理不支持多输出：白名单外键显式拒绝（不静默放行）
        r = run_mo_bo("zdt1", surrogate_kind="poly_ridge")
        assert not r["ok"]
        assert any("多目标" in e and "mt_gp" in e for e in r["errors"])

    def test_budget_too_small(self):
        r = run_mo_bo("zdt1", n_eval=1)
        assert not r["ok"]
        assert any("n_eval" in e for e in r["errors"])

    def test_ref_point_length_mismatch(self):
        r = run_mo_bo("zdt1", ref_point=[1.0])
        assert not r["ok"]
        assert any("ref_point" in e for e in r["errors"])

    def test_n_params_below_contract(self):
        r = run_mo_bo("dtlz2", n_params=1)
        assert not r["ok"]
        assert any("n_params" in e for e in r["errors"])

    def test_bounds_wrong_keyset(self):
        r = run_mo_bo("zdt1", bounds={"w": [0.0, 1.0]})
        assert not r["ok"]
        assert any("bounds" in e for e in r["errors"])

    def test_batch_larger_than_pool(self):
        r = run_mo_bo("zdt1", batch_size=8, n_candidates=4)
        assert not r["ok"]
        assert any("n_candidates" in e for e in r["errors"])

    def test_n_obj_fixed_problem_rejects(self):
        r = run_mo_bo("zdt1", n_obj=3)
        assert not r["ok"]
        assert any("dtlz2" in e for e in r["errors"])


# ── 回调注册面（Python 编程层；JSON 面只承载键名）───────────────────────────


class TestRegisterProblemFace:
    def test_register_and_run_custom_problem(self):
        def custom(x):
            return {"f1": float(x["x0"]) + float(x["x1"]),
                    "f2": (float(x["x0"]) - float(x["x1"])) ** 2}

        register_problem(MultiObjectiveProblem(
            "o1_custom_probe", custom, ["f1", "f2"],
            default_n_params=2, min_n_params=2))
        try:
            assert "o1_custom_probe" in MO_PROBLEM_REGISTRY
            r = run_mo_bo("o1_custom_probe", n_eval=8, seed=0)
            assert r["ok"], r.get("errors")
            assert r["metrics"] == ["f1", "f2"]
            assert r["front"]
        finally:
            MO_PROBLEM_REGISTRY.pop("o1_custom_probe", None)

    def test_register_single_metric_rejected(self):
        with pytest.raises(ValueError, match="SBO"):
            register_problem(MultiObjectiveProblem(
                "bad_single", lambda x: {"f1": 0.0}, ["f1"]))

    def test_surrogate_kinds_whitelist_documented(self):
        assert MO_SURROGATE_KINDS == ("mt_gp", "smt_kriging")


# ── CLI 薄壳（成功+失败同构信封）─────────────────────────────────────────────


class TestCliLeaf:
    @staticmethod
    def _invoke_json(args: list[str]) -> tuple[int, dict | None, str]:
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        result = CliRunner().invoke(app, args)
        out = result.output or ""
        # console.print_json 起点（--json 下失败路径不许非 JSON，#24 口径）
        start = out.find("{")
        payload = json.loads(out[start:]) if start >= 0 else None
        return result.exit_code, payload, out

    def test_mo_run_json_success(self):
        rc, payload, out = self._invoke_json(
            ["mo", "run", "--kind", "zdt1", "--n-eval", "20", "--json"])
        assert rc == 0, out
        assert payload is not None and payload["ok"] is True
        assert payload["kind"] == "zdt1"
        assert payload["hv_curve"] and payload["front"]
        assert payload["n_evaluations"] == 20

    def test_mo_run_json_failure_same_shape(self):
        rc, payload, _ = self._invoke_json(
            ["mo", "run", "--kind", "nope", "--json"])
        assert rc == 1
        assert payload is not None and payload["ok"] is False
        assert payload["errors"]

    def test_mo_run_default_path_renders(self):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        result = CliRunner().invoke(
            app, ["mo", "run", "--kind", "zdt1", "--n-eval", "8"])
        assert result.exit_code == 0, result.output
        assert "帕累托前沿" in result.output
        assert "HV" in result.output

    def test_mo_run_ref_point_parse_error_usage_envelope(self):
        rc, payload, _ = self._invoke_json(
            ["mo", "run", "--ref-point", "abc", "--json"])
        assert rc == 2  # usage 类错误（_emit_usage_error 家法）
        assert payload is not None and payload["ok"] is False
        assert payload["errors"]

    def test_mo_run_forwards_flags(self, monkeypatch):
        captured: dict = {}

        def fake_run_mo_bo(kind, **kw):
            captured.update({"kind": kind, **kw})
            return {"ok": True, "kind": kind, "metrics": ["f1", "f2"],
                    "hv_curve": [1.0, 2.0], "front": [[0.1, 0.9]],
                    "front_params": [{"x0": 0.1, "x1": 0.2}],
                    "ref_point": [1.0, 2.0], "ref_source": "explicit",
                    "acquisitions": [], "n_evaluations": 6,
                    "n_eval_budget": 6, "n_init": 2, "n_iter": 4,
                    "batch_size": 1, "n_params": 2, "surrogate_kind": "mt_gp",
                    "seed": 5, "elapsed_s": 0.01, "info": {}}

        monkeypatch.setattr(
            "rfauto.service.mo_bo_service.run_mo_bo", fake_run_mo_bo)
        rc, payload, _ = self._invoke_json([
            "mo", "run", "--kind", "dtlz2", "--n-obj", "3", "--n-eval", "9",
            "--surrogate", "smt_kriging", "--seed", "5",
            "--ref-point", "1.0,2.0", "--batch-size", "2",
            "--n-candidates", "64", "--mc-samples", "32",
            "--no-fantasy", "--no-samples", "--json"])
        assert rc == 0 and payload["ok"]
        assert captured["kind"] == "dtlz2"
        assert captured["n_obj"] == 3
        assert captured["n_eval"] == 9
        assert captured["surrogate_kind"] == "smt_kriging"
        assert captured["seed"] == 5
        assert captured["ref_point"] == [1.0, 2.0]
        assert captured["batch_size"] == 2
        assert captured["n_candidates"] == 64
        assert captured["mc_samples"] == 32
        assert captured["fantasy"] is False
        assert captured["include_samples"] is False


# ── MCP 薄壳（注册在位 + 哨兵解析）───────────────────────────────────────────


class TestMcpTool:
    @staticmethod
    def _tool_by_name(name):
        import asyncio

        from rfauto.mcp_server import mcp as server

        return {t.name: t for t in asyncio.run(server.list_tools())}[name]

    def test_mo_run_registered(self):
        tool = self._tool_by_name("mo_run")
        assert tool.description
        schema = (tool.parameters or {}).get("properties") or {}
        for key in ("kind", "n_eval", "n_obj", "surrogate", "seed",
                    "ref_point", "n_candidates", "mc_samples", "fantasy"):
            assert key in schema, f"mo_run schema 缺 {key}"

    def test_mo_run_ref_point_sentinel_and_parse(self):
        tool = self._tool_by_name("mo_run")
        # 空串哨兵 = 缺省冻结路径（真内核小预算）
        out = tool.fn("zdt1", n_eval=6, ref_point="")
        assert out.get("ok"), out.get("errors")
        assert out["ref_source"] == "frozen"
        # 逗号解析 → 显式参考点
        out2 = tool.fn("zdt1", n_eval=6, ref_point="1.5,11.0")
        assert out2["ok"] and out2["ref_point"] == [1.5, 11.0]
        assert out2["ref_source"] == "explicit"

    def test_mo_run_bad_ref_point_returns_error_envelope(self):
        tool = self._tool_by_name("mo_run")
        out = tool.fn("zdt1", n_eval=6, ref_point="abc")
        assert out["ok"] is False and out["errors"]

    def test_mo_run_negative_kind_envelope(self):
        tool = self._tool_by_name("mo_run")
        out = tool.fn("nope")
        assert out["ok"] is False and any("zdt1" in e for e in out["errors"])
