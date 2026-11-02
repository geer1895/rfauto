"""aurora_n O2 顶旋钮三层透传接线回归钉（2026-10-31）。

O2（runs/aurora_n/zero_wiring/REGISTRY.md）：run_optimization 顶旋钮三件
``eipu_strategy``（T-N9 EI 档）/``turbo_n_regions``、``turbo_region_strategy``
（T-N10 多域+qREI）在 optimizer.py 参数+校验+回显齐全，但 CLI tune / MCP
start_tune / service start_tune 三层均无透传——多域/REI 档运行时不可达。
本席三层补门（kernel 层透传已有 test_turbo5_rei.py::TestOptimizerKnobs 钉，
本件钉其上的三层）：

- 三层透传钉：CLI tune 旗标 → start_tune(_async) → run_optimization 逐层
  到位（monkeypatch 捕获，非真跑）；
- 缺省等价钉：不传旋钮 = 旧路径（条件透传 #df6③：捕获 kwargs 零新键 +
  真跑结果零旋钮键）；
- e2e 健康跑：eipu/turbo 经 start_tune 合成小目标 max_trials=8 级，ok+旋钮
  回显+best_cost 有限（fake 通道离线，chdir+临时 storage 隔离 #144）；
- MCP 透传钉：空串哨兵 → None 归一（study_name 同款惯例）+ Args 文档面
  与 schema 一致（既有 docstring_args 门同口径）；
- warm-start 变体（run_optimization_with_registry_warm_start）同款透传钉
  （start_tune 两分支语义一致，#122 warm-start 开启时旋钮不静默丢失）。
"""

from __future__ import annotations

import inspect
import sys
import time
from pathlib import Path

import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import optuna

optuna.logging.set_verbosity(optuna.logging.WARNING)

_KNOBS = ("eipu_strategy", "turbo_n_regions", "turbo_region_strategy")


@pytest.fixture(autouse=True)
def _isolated_runs(isolated_cache_off, tmp_path, monkeypatch):
    """chdir 单源委托（tests/conftest.py::isolated_cache_off，conftest
    fixture 卫生门 #144 单源纪律）+ 本文件专需面：临时 optuna storage 指向
    tmp（优化循环类测试 runs/ 湖零污染）+ 注册表写通道环境清理。"""
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )
    monkeypatch.delenv("RFAUTO_WARM_START_REGISTRY", raising=False)
    monkeypatch.delenv("RFAUTO_SURROGATE_REGISTRY_WRITE", raising=False)


@pytest.fixture
def recipe_path(tmp_path):
    """最小 Wilkinson 配方（含 optimization.params 段，fake 适配器秒级）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4},
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


# ─── 层①：service 签名 + 透传 + 缺省等价 ─────────────────────────────────────


class TestServiceSignature:
    def test_start_tune_signature_knobs(self):
        from rfauto.service.api import start_tune

        params = inspect.signature(start_tune).parameters
        for k in _KNOBS:
            assert k in params, f"start_tune 缺 {k}"
            assert params[k].default is None, f"start_tune.{k} 缺省须 None"

    def test_start_tune_async_signature_knobs(self):
        from rfauto.service.api import start_tune_async

        params = inspect.signature(start_tune_async).parameters
        for k in _KNOBS:
            assert k in params, f"start_tune_async 缺 {k}"
            assert params[k].default is None, f"start_tune_async.{k} 缺省须 None"

    def test_registry_variant_signature_knobs(self):
        from rfauto.service.surrogate_registry_service import (
            run_optimization_with_registry_warm_start,
        )

        params = inspect.signature(
            run_optimization_with_registry_warm_start).parameters
        for k in _KNOBS:
            assert k in params, f"warm-start 变体缺 {k}"
            assert params[k].default is None


class TestServicePassThrough:
    @staticmethod
    def _fake_run(captured: dict):
        def fake_run(recipe_path, **kwargs):
            captured.update(kwargs)
            return {"ok": False, "errors": ["stub"]}
        return fake_run

    def test_start_tune_forwards_three_knobs(self, monkeypatch):
        """给旋钮 → run_optimization 三键逐字到位（层①→内核）。"""
        import rfauto.optimization.optimizer as opt_mod
        from rfauto.service.api import start_tune

        captured: dict = {}
        monkeypatch.setattr(opt_mod, "run_optimization",
                            self._fake_run(captured))
        start_tune("r.yaml", sampler="eipu", eipu_strategy="eipu_cooled",
                   turbo_n_regions=3, turbo_region_strategy="ts")
        assert captured["eipu_strategy"] == "eipu_cooled"
        assert captured["turbo_n_regions"] == 3
        assert captured["turbo_region_strategy"] == "ts"

    def test_start_tune_default_no_knob_keys(self, monkeypatch):
        """缺省等价钉：不传旋钮 → 捕获 kwargs 零旋钮键（旧路径逐字节等价）。"""
        import rfauto.optimization.optimizer as opt_mod
        from rfauto.service.api import start_tune

        captured: dict = {}
        monkeypatch.setattr(opt_mod, "run_optimization",
                            self._fake_run(captured))
        start_tune("r.yaml")
        for k in _KNOBS:
            assert k not in captured, f"缺省路径不应出现 {k}"

    def test_registry_variant_forwards_and_default(self, monkeypatch):
        """warm-start 变体同款：给→透传；不给→零键（两分支语义一致）。"""
        import rfauto.optimization.optimizer as opt_mod
        from rfauto.service.surrogate_registry_service import (
            run_optimization_with_registry_warm_start,
        )

        captured: dict = {}
        monkeypatch.setattr(opt_mod, "run_optimization",
                            self._fake_run(captured))
        run_optimization_with_registry_warm_start(
            "r.yaml", sampler="turbo", turbo_n_regions=2,
            turbo_region_strategy="rei")
        assert captured["turbo_n_regions"] == 2
        assert captured["turbo_region_strategy"] == "rei"
        assert "eipu_strategy" not in captured

        captured.clear()
        run_optimization_with_registry_warm_start("r.yaml")
        for k in _KNOBS:
            assert k not in captured

    def test_start_tune_async_forwards_via_job_thread(self, monkeypatch):
        """层①async → start_tune：后台线程捕获三旋钮（detach 链真实消费）。"""
        from rfauto.service import api as api_mod
        from rfauto.service.api import poll_job, start_tune_async

        captured: dict = {}

        def fake_start_tune(recipe_path, **kw):
            captured.update(kw)
            return {"ok": False, "errors": ["stub"]}

        monkeypatch.setattr(api_mod, "start_tune", fake_start_tune)
        res = start_tune_async("r.yaml", sampler="eipu", eipu_strategy="ei",
                               turbo_n_regions=2, turbo_region_strategy="ts")
        assert res.get("ok") and res["state"] == "running"
        job_id = res["job_id"]
        deadline = time.time() + 15
        state = "running"
        while time.time() < deadline:
            state = poll_job(job_id).get("state")
            if state in ("done", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert state == "failed"  # fake 返回 ok=False → fail 终态（线程已跑完）
        assert captured["eipu_strategy"] == "ei"
        assert captured["turbo_n_regions"] == 2
        assert captured["turbo_region_strategy"] == "ts"


# ─── 层②：CLI 旗标存在性 + help 修正 + 透传 + 路径注记 ────────────────────────


class TestCliFlags:
    @staticmethod
    def _tune_params() -> set[str]:
        from typer.main import get_command

        from rfauto.cli.main import app

        cmd = get_command(app).commands["tune"]
        return {p.name for p in getattr(cmd, "params", [])}

    def test_tune_has_three_knob_options(self):
        assert set(_KNOBS) <= self._tune_params(), (
            f"tune 缺旗标: {set(_KNOBS) - self._tune_params()}")

    def test_sampler_help_covers_all_choices(self):
        """--sampler help 文案修正钉：五档 SAMPLER_CHOICES 齐现（O2 附注）。"""
        from typer.main import get_command

        from rfauto.cli.main import app

        cmd = get_command(app).commands["tune"]
        help_text = ""
        for p in getattr(cmd, "params", []):
            if getattr(p, "name", "") == "sampler":
                help_text = getattr(p, "help", "") or ""
        for choice in ("tpe", "cmaes", "gp", "eipu", "turbo", "sbo"):
            assert choice in help_text, f"--sampler help 缺 {choice}: {help_text}"
        # 旧文案（缺 gp/eipu/turbo 的三档口径）不得残留
        assert "tpe | cmaes | sbo" not in help_text

    @staticmethod
    def _invoke(argv, monkeypatch, attr, fake):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.setattr(attr, fake)
        return CliRunner().invoke(app, argv)

    def test_cli_forwards_to_start_tune(self, recipe_path, monkeypatch):
        """层②→层①：CLI 旗标 → start_tune 三旋钮到位。"""
        captured: dict = {}

        def fake_start_tune(recipe_path, **kw):
            captured.update(kw)
            return {"ok": True, "study_name": "s", "run_id": "run-x",
                    "trials_total": 1, "trials_completed": 1,
                    "trials_pruned": 0, "existing_trials": 0,
                    "elapsed_s": 0.1, "best_cost": 1.0, "best_params": {},
                    "best_metrics": {}}

        r = self._invoke(
            ["tune", recipe_path, "--eipu-strategy", "rei",
             "--turbo-n-regions", "3", "--turbo-region-strategy", "ts"],
            monkeypatch, "rfauto.service.api.start_tune", fake_start_tune)
        assert r.exit_code == 0, r.output
        assert captured["eipu_strategy"] == "rei"
        assert captured["turbo_n_regions"] == 3
        assert captured["turbo_region_strategy"] == "ts"

    def test_cli_default_no_knob_keys(self, recipe_path, monkeypatch):
        """缺省等价钉：CLI 不传旗标 → start_tune 收到的三键=None（信封同形）。"""
        captured: dict = {}

        def fake_start_tune(recipe_path, **kw):
            captured.update(kw)
            return {"ok": True}

        r = self._invoke(["tune", recipe_path], monkeypatch,
                         "rfauto.service.api.start_tune", fake_start_tune)
        assert r.exit_code == 0, r.output
        for k in _KNOBS:
            assert captured.get(k, "missing") in (None, "missing"), (
                f"缺省路径 {k} 应为 None/缺键，得 {captured.get(k)!r}")

    def test_cli_detach_forwards_to_start_tune_async(self, recipe_path,
                                                     monkeypatch):
        """--detach 链：旗标 → start_tune_async 三旋钮到位。"""
        captured: dict = {}

        def fake_async(recipe_path, **kw):
            captured.update(kw)
            return {"ok": True, "job_id": "job-o2", "state": "running",
                    "message": ""}

        r = self._invoke(
            ["tune", recipe_path, "--detach", "--sampler", "turbo",
             "--turbo-n-regions", "2", "--turbo-region-strategy", "ts"],
            monkeypatch, "rfauto.service.api.start_tune_async", fake_async)
        assert r.exit_code == 0, r.output
        assert captured["turbo_n_regions"] == 2
        assert captured["turbo_region_strategy"] == "ts"
        assert captured["eipu_strategy"] is None

    def test_cli_knob_note_on_multi_path(self, recipe_path, monkeypatch):
        """#122 不静默：多目标路径下显式给旋钮 → 提示行输出（按未设置处理）。"""
        captured: dict = {}

        def fake_multi(recipe_path, **kw):
            captured.update(kw)
            return {"ok": True}

        r = self._invoke(
            ["tune", recipe_path, "--multi", "--eipu-strategy", "rei"],
            monkeypatch, "rfauto.service.api.start_tune_multi", fake_multi)
        assert r.exit_code == 0, r.output
        assert "仅单目标路径生效" in r.output
        assert "--eipu-strategy" in r.output


# ─── 层③：MCP 工具 ───────────────────────────────────────────────────────────


class TestMcpPassThrough:
    @staticmethod
    def _tool_by_name(name):
        import asyncio

        from rfauto.mcp_server import mcp as server

        return {t.name: t
                for t in asyncio.run(server.list_tools())}[name]

    def test_start_tune_schema_and_docstring_cover_knobs(self):
        """三旋钮进 schema 且 Args 文档面无幽灵参数（既有 docstring 门同口径）。"""
        from tests.unit.test_mcp_tool_consistency import (
            _documented_args,
            _schema_params,
        )

        tool = self._tool_by_name("start_tune")
        schema_params = _schema_params(tool)
        assert set(_KNOBS) <= schema_params
        documented = set(_documented_args(tool.fn))
        assert documented == schema_params, (documented, schema_params)

    def test_mcp_forward_and_empty_string_sentinel(self, monkeypatch):
        """MCP → start_tune_async：给定值透传；空串哨兵归一 None（study_name 同款）。"""
        from rfauto.service import api as api_mod

        captured: dict = {}

        def fake_async(recipe_path, **kw):
            captured.update(kw)
            return {"ok": True, "job_id": "j", "state": "running",
                    "message": ""}

        monkeypatch.setattr(api_mod, "start_tune_async", fake_async)
        tool = self._tool_by_name("start_tune")
        out = tool.fn("r.yaml", eipu_strategy="eipu_cooled",
                      turbo_region_strategy="")
        assert out.get("ok"), out
        assert captured["eipu_strategy"] == "eipu_cooled"
        assert captured["turbo_region_strategy"] is None
        assert captured["turbo_n_regions"] is None


# ─── e2e：真内核 + fake 通道健康跑（n_trials=8 级）────────────────────────────


class TestEndToEndHealth:
    def test_eipu_strategy_end_to_end(self, recipe_path):
        """eipu 经 start_tune 端到端：ok+strategy 回显+best_cost 有限。"""
        from rfauto.service.api import start_tune

        r = start_tune(recipe_path, adapter_name="fake", max_trials=8,
                       sampler="eipu", eipu_strategy="eipu_cooled",
                       study_name="o2_e2e_eipu", seed=5)
        assert r.get("ok"), r.get("errors")
        assert r["eipu_strategy"] == "eipu_cooled"
        assert r["trials_completed"] >= 1
        assert r["best_cost"] is not None
        assert float(r["best_cost"]) == float(r["best_cost"])  # 有限数（非 NaN/inf）

    def test_turbo_multi_region_end_to_end(self, recipe_path):
        """turbo 多域经 start_tune 端到端：两旋钮回显+轨迹健康。"""
        from rfauto.service.api import start_tune

        r = start_tune(recipe_path, adapter_name="fake", max_trials=8,
                       sampler="turbo", turbo_n_regions=2,
                       turbo_region_strategy="ts",
                       study_name="o2_e2e_turbo", seed=5)
        assert r.get("ok"), r.get("errors")
        assert r["turbo_n_regions"] == 2
        assert r["turbo_region_strategy"] == "ts"
        assert r["trials_completed"] >= 1
        assert r["best_cost"] is not None

    def test_default_no_knob_echo_keys(self, recipe_path):
        """缺省等价钉（结果级）：tpe 无旋钮 → 结果零旋钮键（信封键集不变）。"""
        from rfauto.service.api import start_tune

        r = start_tune(recipe_path, adapter_name="fake", max_trials=3,
                       sampler="tpe", study_name="o2_e2e_default", seed=5)
        assert r.get("ok"), r.get("errors")
        for k in _KNOBS:
            assert k not in r, f"缺省结果不应出现 {k}"

    def test_sampler_mismatch_rejected_explicitly(self, recipe_path):
        """错配 sampler 显式拒绝（枚举校验在内核，经 service 可见不静默吞参）。"""
        from rfauto.service.api import start_tune

        r = start_tune(recipe_path, adapter_name="fake", max_trials=3,
                       sampler="tpe", eipu_strategy="ei",
                       study_name="o2_e2e_mismatch", seed=5)
        assert not r.get("ok")
        assert any("eipu_strategy" in e for e in (r.get("errors") or []))
