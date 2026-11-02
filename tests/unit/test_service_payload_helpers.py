"""S2-8 单源化回归钉（review_ge8e 阶段二 F5）：service 层载荷微助手单源断言。

出处：runs/review_ge8e/s2_service_biz/REPORT.md S2-8——_num/
_require_payload_dict/_err/_optional_num 在 humidity_drift/cryo_materials/
aging/glass_weave_skew 四文件近逐字节拷贝（humidity vs cryo 逐字节同、
aging 仅 docstring 异、gws 同形）；campaign_dashboard._load_trials 与
ui_service._load_run_trials 相似度 0.916。单源化至 service/_helpers.py，
本地副本按 #116 治理纪律删净防遮蔽——本文件钉"删净"（身份断言 + 本地
def 消失文本钉）与单源行为契约（bool 拒收/域校验/loader 跳坏文件）。
"""

from __future__ import annotations

import json
from pathlib import Path

import rfauto.service._helpers as helpers
from rfauto.service import (
    aging_service,
    campaign_dashboard_service,
    cryo_materials_service,
    glass_weave_skew_service,
    humidity_drift_service,
)

_HELPER_CONSUMERS = (
    humidity_drift_service,
    cryo_materials_service,
    aging_service,
    glass_weave_skew_service,
)

#: #116 文本钉标记：四消费模块源码内不允许再出现本地副本 def
_LOCAL_COPY_DEFS = (
    "def _num(",
    "def _require_payload_dict(",
    "def _optional_num(",
    "def _err(",
)


class TestSingleSourceImports:
    def test_parse_num_and_payload_guard_are_import_aliases(self):
        """四消费模块的 _num/_require_payload_dict 必须是 _helpers 单源的
        同一函数对象（本地 def 副本一旦回归，身份断言即红）。"""
        for mod in _HELPER_CONSUMERS:
            assert mod._require_payload_dict is helpers.require_payload_dict, mod.__name__
            assert mod._num is helpers.parse_num, mod.__name__

    def test_optional_num_imported_where_used(self):
        assert humidity_drift_service._optional_num is helpers.optional_num
        assert cryo_materials_service._optional_num is helpers.optional_num

    def test_err_envelope_single_source(self):
        """aging/gws 直引别名；humidity/cryo 为 partial 版本戳绑定
        （func 身份 + 绑定关键字双钉，本地 def 副本回归即红）。"""
        assert aging_service._err is helpers.err_envelope
        assert glass_weave_skew_service._err is helpers.err_envelope
        assert humidity_drift_service._err.func is helpers.err_envelope
        assert humidity_drift_service._err.keywords == {
            "schema_version": humidity_drift_service.HUMIDITY_DRIFT_SCHEMA_VERSION}
        assert cryo_materials_service._err.func is helpers.err_envelope
        assert cryo_materials_service._err.keywords == {
            "schema_version": cryo_materials_service.CRYO_MATERIALS_SCHEMA_VERSION}

    def test_local_copy_defs_deleted(self):
        """#116：旧副本必须删净防遮蔽——四消费模块源码零本地 def（含
        def _err：humidity/cryo 走 partial 绑定、aging/gws 走别名直引）。"""
        for mod in _HELPER_CONSUMERS:
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for marker in _LOCAL_COPY_DEFS:
                assert marker not in src, (mod.__name__, marker)

    def test_dashboard_loader_single_source(self):
        """S2-8②：campaign_dashboard._load_trials 收敛为 _helpers 单源
        loader（原本地副本与 ui_service._load_run_trials 相似 0.916）。"""
        assert campaign_dashboard_service._load_trials is helpers.load_run_trials
        src = Path(campaign_dashboard_service.__file__).read_text(encoding="utf-8")
        assert "def _load_trials(" not in src


class TestSharedHelperContract:
    """单源行为契约钉（四服务既有测试经服务入口覆盖语义，此处直接钉
    单源函数本身的判域，防单源化时行为漂移）。"""

    def test_parse_num_contract(self):
        errors: list[str] = []
        assert helpers.parse_num(1.5, "a", errors) == 1.5 and errors == []
        assert helpers.parse_num(None, "a", errors) is None
        assert errors == ["a 缺失"]
        errors.clear()
        assert helpers.parse_num(True, "a", errors) is None
        assert "bool" in errors[0]
        errors.clear()
        assert helpers.parse_num("xyz", "a", errors) is None
        assert "必须是数字" in errors[0]
        errors.clear()
        assert helpers.parse_num(float("nan"), "a", errors) is None
        assert "有限数" in errors[0]
        errors.clear()
        assert helpers.parse_num(0.0, "a", errors, positive=True) is None
        assert ">0" in errors[0]
        errors.clear()
        assert helpers.parse_num(-1.0, "a", errors, nonneg=True) is None
        assert ">=0" in errors[0]

    def test_optional_num_missing_is_not_error(self):
        errors: list[str] = []
        assert helpers.optional_num(None, "opt", errors) is None and errors == []
        assert helpers.optional_num("bad", "opt", errors) is None and errors

    def test_require_payload_dict_rejects_non_dict(self):
        assert helpers.require_payload_dict({"a": 1}) == {"a": 1}
        try:
            helpers.require_payload_dict([1])
        except ValueError as exc:
            assert "JSON 对象" in str(exc)
        else:
            raise AssertionError("non-dict payload 必须 ValueError")

    def test_err_envelope_shapes(self):
        """带戳/不带戳两形态与历史形状键集一致（humidity/cryo 带版本戳、
        aging/gws 与 error_envelope 同形）。"""
        plain = helpers.err_envelope(["boom"])
        assert plain["ok"] is False and plain["errors"] == ["boom"]
        assert "schema_version" not in plain
        stamped = helpers.err_envelope("boom", schema_version="9.9")
        assert stamped["ok"] is False and stamped["errors"] == ["boom"]
        assert stamped["schema_version"] == "9.9"

    def test_load_run_trials_sorted_skip_bad_and_missing_dir(self, tmp_path):
        tdir = tmp_path / "trials"
        tdir.mkdir()
        (tdir / "trial_0001.json").write_text(
            json.dumps({"trial_number": 1, "cost": 2.0}), encoding="utf-8")
        (tdir / "trial_0000.json").write_text("{broken", encoding="utf-8")
        (tdir / "other.json").write_text("{}", encoding="utf-8")  # 非 trial_* 不收
        out = helpers.load_run_trials(tmp_path)
        assert [t.get("trial_number") for t in out] == [1]
        assert helpers.load_run_trials(tmp_path / "nope") == []
