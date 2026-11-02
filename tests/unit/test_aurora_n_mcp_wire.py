"""aurora_n MCP 接线补齐席回归钉（2026-10-31）。

zero_wiring 登记欠账清偿的 MCP 侧四工具钉（O4/O5/T-N20 此前仅 CLI 叶；
surrogate uq 经查为同形缺口——uq_yield_at=点值/robustness_report=specs
形态均非 uq_service.surrogate_yield 的 samples+tolerances 报表形态）：

- 注册钉：四工具在位、schema 参数面齐、描述非空（全局计数/双检由
  test_mcp_server/test_mcp_tool_consistency 邻接覆盖，本件不重复）；
- e2e：真内核小档（siren 导出对拍/poly_ridge MC 良率/al legacy+采集族/
  竞赛单族单 seed 小预算）+ 确定性逐位钉；
- 负例：坏 config JSON/未知 kind/样本文件缺席/来源未给或多给/未知采集
  名/未知族/未知引擎/坏 seeds——全部 ok=False 信封同构；
- 转发钉：参数逐键到 service（monkeypatch 捕获，#277 三态语义钉）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

BOUNDS = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}


def _al_samples(n: int = 25, seed: int = 3) -> list[dict]:
    """合成 2 参数 1 指标样本集（同 test_aurora_n_o4_al 语料结构）。"""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        p = {"arm_len_mm": float(rng.uniform(*BOUNDS["arm_len_mm"])),
             "series_w_mm": float(rng.uniform(*BOUNDS["series_w_mm"]))}
        s11 = (-20.0 + 5.0 * (p["arm_len_mm"] - 20.0) ** 2
               + 10.0 * (p["series_w_mm"] - 0.35) ** 2)
        out.append({"params": p,
                    "metrics": {"s11_db_max_in_band": float(s11)}})
    return out


def _field_samples(n: int = 64, seed: int = 1) -> list[dict]:
    """siren 场语料（tiny 档，同 test_tn20_onnx_export 语料族独立重写）。"""

    def _field(x: float, y: float) -> float:
        return (np.cos(2 * np.pi * 3 * x) * np.cos(2 * np.pi * 5 * y)
                + 0.5)

    rng = np.random.default_rng(seed)
    pts = rng.uniform(0.0, 1.0, (n, 2))
    return [{"params": {"x": float(x), "y": float(y)},
             "metrics": {"field": float(_field(x, y))}}
            for x, y in pts]


def _uq_samples_json(tmp_path: Path) -> str:
    """surrogate_yield 语料（bounds/objectives/samples，同 test_contracts）。"""
    data = {"bounds": BOUNDS,
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
            "samples": _al_samples()}
    path = tmp_path / "uq_samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _tool(name: str):
    import asyncio

    from rfauto.mcp_server import mcp as server

    return {t.name: t for t in asyncio.run(server.list_tools())}[name]


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """cwd 隔离单源委托（tests/conftest.py::isolated，#144 家法）。"""
    yield


# ── 注册面（四工具在位+schema 参数面）───────────────────────────────────────


class TestRegistration:
    @pytest.mark.parametrize("name", [
        "surrogate_export_onnx", "surrogate_uq", "al_propose",
        "competition_run",
    ])
    def test_registered_with_schema_and_description(self, name):
        tool = _tool(name)
        assert tool.description.strip()
        schema = (tool.parameters or {}).get("properties") or {}
        assert schema, f"{name} schema 空"

    def test_surrogate_export_onnx_schema_keys(self):
        schema = (_tool("surrogate_export_onnx").parameters or {})[
            "properties"]
        for key in ("kind", "samples_path", "out_path", "config_json",
                    "opset", "verify"):
            assert key in schema, f"surrogate_export_onnx 缺 {key}"
        required = set((_tool("surrogate_export_onnx").parameters
                        or {}).get("required") or [])
        assert {"kind", "samples_path", "out_path"} <= required

    def test_al_propose_schema_keys(self):
        schema = (_tool("al_propose").parameters or {})["properties"]
        for key in ("samples_path", "dataset", "run", "k", "kind",
                    "acquisition", "source", "beta", "xi", "n_candidates",
                    "min_dist", "seed", "conformal_fallback", "max_rows"):
            assert key in schema, f"al_propose 缺 {key}"

    def test_competition_run_schema_keys(self):
        schema = (_tool("competition_run").parameters or {})["properties"]
        for key in ("engines", "problems", "n_eval", "seeds"):
            assert key in schema, f"competition_run 缺 {key}"

    def test_surrogate_uq_schema_keys(self):
        schema = (_tool("surrogate_uq").parameters or {})["properties"]
        for key in ("samples_path", "tolerances", "n", "seed", "kind",
                    "order", "ridge_lambda"):
            assert key in schema, f"surrogate_uq 缺 {key}"


# ── surrogate_export_onnx（T-N20 导出面）────────────────────────────────────


class TestSurrogateExportOnnxTool:
    def test_missing_samples_file_envelope(self, tmp_path):
        out = _tool("surrogate_export_onnx").fn(
            "siren", str(tmp_path / "nope.json"), str(tmp_path / "o.onnx"))
        assert out["ok"] is False and out["errors"]

    def test_bad_config_json_envelope(self, tmp_path):
        samples = tmp_path / "s.json"
        samples.write_text(json.dumps(_field_samples(n=8)), encoding="utf-8")
        out = _tool("surrogate_export_onnx").fn(
            "siren", str(samples), str(tmp_path / "o.onnx"),
            config_json="{not json")
        assert out["ok"] is False
        assert any("JSON" in e for e in out["errors"])

    def test_config_root_not_object_envelope(self, tmp_path):
        samples = tmp_path / "s.json"
        samples.write_text(json.dumps(_field_samples(n=8)), encoding="utf-8")
        out = _tool("surrogate_export_onnx").fn(
            "siren", str(samples), str(tmp_path / "o.onnx"),
            config_json="[1, 2]")
        assert out["ok"] is False
        assert any("对象" in e for e in out["errors"])

    def test_unknown_kind_envelope(self, tmp_path):
        samples = tmp_path / "s.json"
        samples.write_text(json.dumps(_field_samples(n=8)), encoding="utf-8")
        out = _tool("surrogate_export_onnx").fn(
            "poly_ridge", str(samples), str(tmp_path / "o.onnx"))
        assert out["ok"] is False
        assert any("siren" in e for e in out["errors"])

    def test_siren_end_to_end_export_and_verify(self, tmp_path):
        pytest.importorskip("torch")
        pytest.importorskip("onnx")
        pytest.importorskip("onnxruntime")
        samples = tmp_path / "s.json"
        samples.write_text(
            json.dumps(_field_samples()), encoding="utf-8")
        out_path = tmp_path / "siren_mcp.onnx"
        out = _tool("surrogate_export_onnx").fn(
            "siren", str(samples), str(out_path),
            config_json=json.dumps({
                "coord_keys": ["x", "y"], "field_key": "field",
                "width": 8, "n_hidden": 1, "epochs": 30, "seed": 42}))
        assert out["ok"], out.get("errors")
        assert out["kind"] == "siren"
        assert out["path"] and Path(out["path"]).is_file()
        assert out["sha256"]
        assert out.get("n_samples") == 64
        assert out["input"].get("name") and out["input"].get("shape")
        assert out.get("verified") is True, out.get("verify_note")

    def test_forwarding_payload_keys(self, monkeypatch, tmp_path):
        captured: dict = {}

        def fake_service(payload):
            captured.update(payload)
            return {"ok": True, "kind": payload["kind"]}

        monkeypatch.setattr(
            "rfauto.service.surrogate_export_service.surrogate_export_onnx",
            fake_service)
        samples = tmp_path / "s.json"
        samples.write_text("[]", encoding="utf-8")
        out = _tool("surrogate_export_onnx").fn(
            "fno", str(samples), str(tmp_path / "o.onnx"),
            config_json='{"seed": 7}', opset=17, verify=False)
        assert out["ok"] is True
        assert captured["kind"] == "fno"
        assert captured["config"] == {"seed": 7}
        assert captured["samples_path"] == str(samples)
        assert captured["out_path"] == str(tmp_path / "o.onnx")
        assert captured["opset"] == 17
        assert captured["verify"] is False


# ── surrogate_uq（代理 MC 良率报表面）───────────────────────────────────────


class TestSurrogateUqTool:
    def test_end_to_end_poly_ridge(self, tmp_path):
        path = _uq_samples_json(tmp_path)
        out = _tool("surrogate_uq").fn(
            path, {"arm_len_mm": 0.1, "series_w_mm": 0.01}, n=1000, seed=1)
        assert out["ok"], out.get("errors")
        assert 0.0 <= out["yield_rate"] <= 1.0
        assert out["metric_stats"]
        assert out["sensitivity_ranking"]
        assert out["surrogate_kind"] == "poly_ridge"
        assert out["n_draws"] == 1000

    def test_deterministic_bitwise(self, tmp_path):
        path = _uq_samples_json(tmp_path)
        tool = _tool("surrogate_uq")
        a = tool.fn(path, {"arm_len_mm": 0.1}, n=500, seed=2)
        b = tool.fn(path, {"arm_len_mm": 0.1}, n=500, seed=2)
        assert a["ok"] and b["ok"]
        a.pop("elapsed_s", None)
        b.pop("elapsed_s", None)
        assert a == b

    def test_missing_samples_envelope(self, tmp_path):
        out = _tool("surrogate_uq").fn(
            str(tmp_path / "nope.json"), {"arm_len_mm": 0.1})
        assert out["ok"] is False and out["errors"]

    def test_tolerance_out_of_bounds_envelope(self, tmp_path):
        path = _uq_samples_json(tmp_path)
        out = _tool("surrogate_uq").fn(path, {"nope_param": 0.1})
        assert out["ok"] is False
        assert any("搜索空间" in e for e in out["errors"])

    def test_forwarding_kwargs(self, monkeypatch, tmp_path):
        captured: dict = {}

        def fake_yield(samples_path, tolerances, **kw):
            captured.update({"samples_path": samples_path,
                             "tolerances": tolerances, **kw})
            return {"ok": True}

        monkeypatch.setattr(
            "rfauto.service.uq_service.surrogate_yield", fake_yield)
        out = _tool("surrogate_uq").fn(
            "p.json", {"a": 0.1}, n=123, seed=9, kind="nn", order=3,
            ridge_lambda=0.5)
        assert out["ok"] is True
        assert captured == {"samples_path": "p.json", "tolerances": {"a": 0.1},
                            "n": 123, "seed": 9, "kind": "nn", "order": 3,
                            "ridge_lambda": 0.5}


# ── al_propose（T-N9 采集三族运行时门）──────────────────────────────────────


class TestAlProposeTool:
    @pytest.fixture
    def samples_file(self, tmp_path):
        path = tmp_path / "samples.json"
        path.write_text(json.dumps(
            {"bounds": BOUNDS, "objectives": [],
             "samples": _al_samples()}), encoding="utf-8")
        return str(path)

    def test_legacy_samples_path_e2e(self, samples_file):
        out = _tool("al_propose").fn(samples_path=samples_file, k=3)
        assert out["ok"], out.get("errors")
        assert len(out["proposed"]) == 3
        assert out["n_existing"] == 25
        assert out["surrogate_kind"] == "nn"
        # samples_path 形态=宿主信封直通（零改动转发）——无 sample_source
        # 标注（dataset/run 与采集族形态才有）
        assert out["samples_path"] == samples_file

    def test_acquisition_ucb_e2e(self, samples_file):
        out = _tool("al_propose").fn(
            samples_path=samples_file, k=2, acquisition="ucb", source="gp")
        assert out["ok"], out.get("errors")
        assert out["mode"] == "acquisition"
        assert out["acquisition"] == "ucb"
        assert len(out["proposed"]) == 2
        for item in out["proposed"]:
            for name, v in item["params"].items():
                lo, hi = BOUNDS[name]
                assert lo <= v <= hi

    def test_deterministic_bitwise(self, samples_file):
        tool = _tool("al_propose")
        a = tool.fn(samples_path=samples_file, k=2, acquisition="ei")
        b = tool.fn(samples_path=samples_file, k=2, acquisition="ei")
        assert a["ok"] and b["ok"]
        for env in (a, b):
            env.pop("elapsed_s", None)
        assert a == b

    def test_no_source_envelope(self):
        out = _tool("al_propose").fn()
        assert out["ok"] is False and out["errors"]

    def test_two_sources_envelope(self, samples_file, tmp_path):
        out = _tool("al_propose").fn(
            samples_path=samples_file, dataset="some_dataset")
        assert out["ok"] is False
        assert any("互斥" in e for e in out["errors"])

    def test_missing_samples_file_envelope(self, tmp_path):
        out = _tool("al_propose").fn(
            samples_path=str(tmp_path / "nope.json"))
        assert out["ok"] is False and out["errors"]

    def test_unknown_acquisition_envelope(self, samples_file):
        out = _tool("al_propose").fn(
            samples_path=samples_file, acquisition="nope")
        assert out["ok"] is False and out["errors"]

    def test_tri_state_conformal_forwarding(self, monkeypatch, samples_file):
        cases: list[tuple[dict, object]] = []
        real = None

        import rfauto.service.al_service as al_mod

        real = al_mod.al_propose

        def spy(*args, **kwargs):
            cases.append((kwargs, args))
            return {"ok": True}

        monkeypatch.setattr(al_mod, "al_propose", spy)
        tool = _tool("al_propose")
        # 缺省（None）=按路径三态；显式 True/False 字面透传（#277）
        tool.fn(samples_path=samples_file)
        tool.fn(samples_path=samples_file, conformal_fallback=True)
        tool.fn(samples_path=samples_file, conformal_fallback=False)
        assert [kw.get("conformal_fallback") for kw, _ in cases] == [
            None, True, False]
        assert real is not None

    def test_forwarding_flag_values(self, monkeypatch, samples_file):
        captured: dict = {}

        def spy(*args, **kwargs):
            captured.update(kwargs)
            captured["args"] = args
            return {"ok": True}

        monkeypatch.setattr(
            "rfauto.service.al_service.al_propose", spy)
        _tool("al_propose").fn(
            samples_path=samples_file, k=7, kind="poly_ridge",
            acquisition="lcb", source="bootstrap", beta=1.5, xi=0.2,
            n_candidates=64, min_dist=0.05, seed=11, max_rows=99)
        assert captured["args"] == (samples_file, None, None)
        assert captured["k"] == 7
        assert captured["kind"] == "poly_ridge"
        assert captured["acquisition"] == "lcb"
        assert captured["source"] == "bootstrap"
        assert captured["beta"] == 1.5
        assert captured["xi"] == 0.2
        assert captured["n_candidates"] == 64
        assert captured["min_dist"] == 0.05
        assert captured["seed"] == 11
        assert captured["max_rows"] == 99


# ── competition_run（T-N5 标量竞赛架运行时门）───────────────────────────────


class TestCompetitionRunTool:
    def test_small_tier_end_to_end(self):
        out = _tool("competition_run").fn(
            engines="tpe", problems="concave2d", n_eval=6, seeds="0")
        assert out["ok"], out.get("errors")
        assert out["schema"] == "competition-scalar-v1"
        assert out["engines"] == ["tpe"]
        assert out["problems"] == ["concave2d"]
        assert out["seeds"] == [0]
        assert out["n_runs"] == 1
        assert out["result"]["runs"]
        assert out["report_md"].strip()

    def test_deterministic_bitwise_after_strip_elapsed(self):
        from rfauto.service.competition_service import strip_elapsed_s

        tool = _tool("competition_run")
        a = tool.fn(engines="tpe", problems="concave2d", n_eval=6, seeds="0")
        b = tool.fn(engines="tpe", problems="concave2d", n_eval=6, seeds="0")
        assert a["ok"] and b["ok"]
        # 内核报表剥离 elapsed_s 后逐位（O5 家法：report_md 含逐 run 耗时
        # 渲染不进确定性钉，result 递归剥离才是单源）
        assert (json.dumps(strip_elapsed_s(a["result"]), sort_keys=True)
                == json.dumps(strip_elapsed_s(b["result"]), sort_keys=True))

    def test_unknown_problem_envelope(self):
        out = _tool("competition_run").fn(problems="nope")
        assert out["ok"] is False
        assert any("concave2d" in e for e in out["errors"])

    def test_unknown_engine_envelope(self):
        out = _tool("competition_run").fn(engines="nope")
        assert out["ok"] is False and out["errors"]

    def test_bad_seeds_envelope(self):
        out = _tool("competition_run").fn(seeds="x,y")
        assert out["ok"] is False
        assert any("seeds" in e for e in out["errors"])

    def test_empty_sentinels_forward_none(self, monkeypatch):
        captured: dict = {}

        def fake_run(engines, problems, *, n_eval, seeds):
            captured.update({"engines": engines, "problems": problems,
                             "n_eval": n_eval, "seeds": seeds})
            return {"ok": True}

        monkeypatch.setattr(
            "rfauto.service.competition_service.run_competition", fake_run)
        out = _tool("competition_run").fn(
            engines="", problems="", n_eval=9, seeds=" 0 , 2 ")
        assert out["ok"] is True
        assert captured["engines"] is None
        assert captured["problems"] is None
        assert captured["n_eval"] == 9
        assert captured["seeds"] == [0, 2]
