"""AX-3（aurora_r R-03）run 级引擎身份离线钉。

判据对照（席位任务书预声明验收面）：
1. 纯函数构造器 build_engine_identity：正例 canonical 形态（engine/
   version/version_probe?/detail? + 自报随行键 commit）；
   缺字段/空值/非 dict 垃圾如实 unknown 不伪造；输入不被变异（纯函数）。
2. write_meta 可选参数：engine_identity=None 与不传逐字节一致且无新键
   （缺省零变化判据——W3-B derived_from 同款回归钉）；显式传入落
   meta["engine_identity"]（经构造器归一）；显式参数单源（meta_dict 同名
   键不得覆盖）；传空 dict 萨 unknown 不伪造。
3. probe_engine_identity：fake 通道 n/a 不伪造；hfss/ads 消费
   version_probe 现有探测结果（monkeypatch 钉通道，零真机依赖 #139）；
   探测抛异常降级 unknown 永不 raise（#105）；未知引擎通道如实 unknown。
4. 真实消费点接入：openEMS 模板直跑链（template_recipe_service）与
   run_once fake/model 链（run_core）端到端——meta.json 携带
   engine_identity 且引擎名与通道一致（openEMS 离线 monkeypatch 求解器，
   零真机）。

chdir 隔离零污染（#144 家族：run 目录解析在调用时取 cwd）；无网络依赖。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.infra import run_store
from rfauto.infra.run_store import (
    build_engine_identity,
    probe_engine_identity,
    write_meta,
)

# ---------------------------------------------------------------------------
# 共享基建：确定性 meta 写入（W3-B fast_meta 同款——字节比对确定性+提速）
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_meta(monkeypatch):
    monkeypatch.setattr(run_store, "_git_sha", lambda: "cafe123")
    monkeypatch.setattr(
        run_store, "collect_provenance",
        lambda **kw: {"python_version": "3.12.0", "os": "test-os",
                      "pip_freeze_sha": "fixed0123456789ef",
                      "solver_versions": {},
                      "optuna_seed": kw.get("optuna_seed"),
                      "numeric_env": {"available": False}})


class _FrozenDatetime:
    @classmethod
    def now(cls, tz=None):
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        return _dt(2026, 11, 10, 12, 0, 0, tzinfo=_tz.utc)


# ---------------------------------------------------------------------------
# 1. build_engine_identity 纯函数构造器
# ---------------------------------------------------------------------------


class TestBuildEngineIdentity:
    def test_full_positive_canonical(self):
        info = {
            "engine": "openems",
            "version": "0.6.2",
            "version_probe": "importlib.metadata",
            "commit": "abc1234",
            "detail": {"abi": "cp312", "support_tier": "full"},
        }
        out = build_engine_identity(info)
        assert out == {
            "engine": "openems",
            "version": "0.6.2",
            "version_probe": "importlib.metadata",
            "commit": "abc1234",
            "detail": {"abi": "cp312", "support_tier": "full"},
        }

    def test_missing_fields_unknown_not_fabricated(self):
        out = build_engine_identity({})
        assert out == {"engine": "unknown", "version": "unknown"}
        out2 = build_engine_identity({"engine": "hfss", "version": None,
                                      "version_probe": "", "detail": {}})
        assert out2 == {"engine": "hfss", "version": "unknown"}
        # version_probe 空串/detail 空 dict：如实不落键
        assert "version_probe" not in out2
        assert "detail" not in out2

    def test_garbage_input_degrades_honest(self):
        for junk in ("garbage", None, 123, ["engine"], object()):
            out = build_engine_identity(junk)
            assert out == {"engine": "unknown", "version": "unknown"}

    def test_version_probe_dict_passthrough(self):
        out = build_engine_identity({
            "engine": "hfss", "version": "2025.1",
            "version_probe": {"source": "registry", "build": 251},
        })
        assert out["version_probe"] == {"source": "registry", "build": 251}

    def test_non_str_coercion_and_empty_drop(self):
        out = build_engine_identity({"engine": "ads", "version": 2027,
                                     "commit": ""})
        assert out["version"] == "2027"
        assert "commit" not in out  # 空值随行键如实丢弃

    def test_pure_function_no_input_mutation(self):
        info = {"engine": "openems", "version": "0.6.2",
                "detail": {"abi": "cp312"}}
        snapshot = json.dumps(info, sort_keys=True)
        build_engine_identity(info)
        assert json.dumps(info, sort_keys=True) == snapshot


# ---------------------------------------------------------------------------
# 2. write_meta 可选参数（缺省零变化判据）
# ---------------------------------------------------------------------------


class TestWriteMetaEngineIdentity:
    def test_signature_keyword_only_default_none(self):
        import inspect

        sig = inspect.signature(write_meta)
        param = sig.parameters["engine_identity"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is None

    def test_default_zero_change_byte_identical_and_absent(
            self, tmp_path, fast_meta, monkeypatch):
        """engine_identity=None 与不传：meta.json 逐字节一致，且均无
        engine_identity 键（回归钉：全部既有调用零改动——判据 b）。"""
        monkeypatch.setattr(run_store, "datetime", _FrozenDatetime)
        body = {"run_id": "r1", "model": "wilkinson", "status": "done"}
        p1 = write_meta(tmp_path / "a", body, run_id="r1")
        p2 = write_meta(tmp_path / "b", body, run_id="r1",
                        engine_identity=None)
        assert p1.read_bytes() == p2.read_bytes()
        meta1 = json.loads(p1.read_text(encoding="utf-8"))
        assert "engine_identity" not in meta1

    def test_explicit_param_lands_normalized(
            self, tmp_path, fast_meta):
        path = write_meta(
            tmp_path, {"run_id": "r1", "status": "done"}, run_id="r1",
            engine_identity={"engine": "hfss", "version": "2025.1",
                             "version_probe": "auto-probe"})
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["engine_identity"] == {
            "engine": "hfss", "version": "2025.1",
            "version_probe": "auto-probe"}

    def test_explicit_param_single_source_overrides_meta_dict(
            self, tmp_path, fast_meta):
        """显式参数单源（derived_from 同款纪律）：meta_dict 同名键不得覆盖。"""
        path = write_meta(
            tmp_path,
            {"run_id": "r1", "engine_identity": {"engine": "evil"}},
            run_id="r1",
            engine_identity={"engine": "good", "version": "1.0"})
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["engine_identity"]["engine"] == "good"

    def test_empty_dict_honest_unknown(self, tmp_path, fast_meta):
        path = write_meta(tmp_path, {"run_id": "r1"}, run_id="r1",
                          engine_identity={})
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["engine_identity"] == {
            "engine": "unknown", "version": "unknown"}

    def test_garbage_param_never_raises(self, tmp_path, fast_meta):
        """垃圾入参降级不炸 meta 写主路径（#105 同族）。"""
        path = write_meta(tmp_path, {"run_id": "r1"}, run_id="r1",
                          engine_identity="junk")  # type: ignore[arg-type]
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["engine_identity"] == {
            "engine": "unknown", "version": "unknown"}


# ---------------------------------------------------------------------------
# 3. probe_engine_identity（version_probe 通道 monkeypatch 钉住，#139）
# ---------------------------------------------------------------------------


class TestProbeEngineIdentity:
    def test_fake_channel_honest_na(self):
        out = probe_engine_identity("fake")
        assert out == {"engine": "fake", "version": "n/a",
                       "version_probe": "built-in"}

    def test_hfss_consumes_version_probe_result(self, monkeypatch):
        """d 项验收：HFSS 消费 infra/version_probe 现有探测结果。"""
        monkeypatch.setattr(
            "rfauto.infra.version_probe.resolve_aedt_install",
            lambda: {"path": "/x", "aedt_version": "2025.1",
                     "source": "auto-probe"})
        out = probe_engine_identity("hfss")
        assert out == {"engine": "hfss", "version": "2025.1",
                       "version_probe": "auto-probe"}

    def test_hfss_probe_failure_degrades_unknown(self, monkeypatch):
        def _boom():
            raise RuntimeError("probe down")

        monkeypatch.setattr(
            "rfauto.infra.version_probe.resolve_aedt_install", _boom)
        out = probe_engine_identity("hfss")
        assert out == {"engine": "hfss", "version": "unknown"}

    def test_ads_consumes_detect_ads_version(self, monkeypatch):
        monkeypatch.setattr(
            "rfauto.infra.version_probe.detect_ads_version",
            lambda: "2027")
        out = probe_engine_identity("ads")
        assert out == {"engine": "ads", "version": "2027",
                       "version_probe": "hpeesof_dir"}

    def test_openems_real_or_unknown_string(self):
        """openEMS：本机有绑定=真实版本串；无绑定=unknown——两态均诚实。"""
        out = probe_engine_identity("openems")
        assert out["engine"] == "openems"
        assert isinstance(out["version"], str) and out["version"]
        assert out["version_probe"] in ("importlib.metadata", "unknown")

    def test_unknown_engine_channel_honest(self):
        out = probe_engine_identity("comsol")
        assert out == {"engine": "comsol", "version": "unknown"}

    def test_ads_probe_failure_degrades_unknown(self, monkeypatch):
        """#105：探测段异常降级 unknown，probe 自身永不 raise。"""
        def _boom():
            raise RuntimeError("settings unreadable")

        monkeypatch.setattr(
            "rfauto.infra.version_probe.detect_ads_version", _boom)
        out = probe_engine_identity("ads")
        assert out == {"engine": "ads", "version": "unknown"}


# ---------------------------------------------------------------------------
# 4. 真实消费点端到端（openEMS 模板直跑链离线 + fake/model 链）
# ---------------------------------------------------------------------------


class TestConsumerWiring:
    def test_template_fake_channel_meta_has_engine_identity(
            self, tmp_path, monkeypatch):
        from rfauto.service.api.run_core import run_once
        from rfauto.service.template_recipe_service import (
            export_template_recipe,
        )

        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        res = run_once(result["path"], adapter_name="fake")
        assert res["ok"] is True, res.get("errors")
        meta = json.loads(
            (Path(res["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        assert meta["engine_identity"] == {
            "engine": "fake", "version": "n/a", "version_probe": "built-in"}

    def test_template_openems_channel_meta_has_engine_identity(
            self, tmp_path, monkeypatch):
        """c 项验收：openEMS 渲染/求解链真实消费点（离线 monkeypatch）。"""
        import numpy as np

        from rfauto.service.api.run_core import run_once
        from rfauto.service.template_recipe_service import (
            export_template_recipe,
        )

        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")

        class _FakeResult:
            success = True
            freq_ghz = np.linspace(1.68, 3.43, 41)
            s_params = None
            wall_time_s = 1.0
            message = "injected"

            def __init__(self) -> None:
                n = len(self.freq_ghz)
                s = np.ones((n, 1, 1), dtype=complex) * 0.1
                s[:, 0, 0] = 0.3
                self.s_params = s

        class _FakeSolver:
            def __init__(self, config) -> None:
                pass

            def connect(self) -> bool:
                return True

            def build_geometry(self, geometry: dict) -> bool:
                return True

            def solve(self):
                return _FakeResult()

        monkeypatch.setattr(
            "rfauto.adapters.openems_solver.OpenEMSSolver", _FakeSolver)
        monkeypatch.setattr(
            "rfauto.adapters.em_solver_base.resolve_openems_exe",
            lambda: "openEMS-injected")
        res = run_once(result["path"], adapter_name="openems")
        assert res["ok"] is True, res.get("errors")
        meta = json.loads(
            (Path(res["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        ident = meta["engine_identity"]
        assert ident["engine"] == "openems"
        # 版本两态均诚实：本机有绑定=真实串；无绑定=unknown（#105 降级）
        assert isinstance(ident["version"], str) and ident["version"]

    def test_run_once_model_fake_channel_meta_has_engine_identity(
            self, tmp_path, monkeypatch):
        """run_core.run_once fake 通道消费点（model 形态配方）。"""
        from rfauto.service.api.run_core import run_once

        monkeypatch.chdir(tmp_path)
        recipe = tmp_path / "wilkinson.yaml"
        recipe.write_text(
            "model: wilkinson_power_divider\nschema_version: 1\n"
            "params:\n"
            "  arm_len_mm: {value: 20.5, unit: mm, bounds: [15.0, 30.0]}\n",
            encoding="utf-8")
        res = run_once(recipe, adapter_name="fake")
        assert res["ok"] is True, res.get("errors")
        meta = json.loads(
            (Path(res["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        assert meta["engine_identity"]["engine"] == "fake"
