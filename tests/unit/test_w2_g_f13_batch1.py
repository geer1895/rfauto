"""F-13 批1 单源身份钉（W2-G）：_num/_require_payload_dict 并入 _helpers 单源。

判据（ra_criteria SPECS §3.3 批 1 口径）：
- 单源身份断言：并入模块的 ``_num``/``_require_payload_dict`` 与
  ``service/_helpers`` 单源为**同一函数对象**（is）——别名 import 落地、
  本地副本按 #116 治理纪律删净防遮蔽（本地 def 文本消失钉）；
- 行为冻结样本：每并入文件取合法/非法 payload 各一例，断言 ok 与
  errors 文案改前改后逐位一致（批 1 = 零语义变化）。
"""

from __future__ import annotations

import pytest

from rfauto.service import (
    bias_tee_service,
    clock_noise_service,
    jitter_budget_service,
    pll_budget_service,
    return_path_check_service,
)
from rfauto.service._helpers import parse_num, require_payload_dict

_BATCH1_MODULES = (
    bias_tee_service,
    clock_noise_service,
    jitter_budget_service,
    pll_budget_service,
    return_path_check_service,
)

_MODULE_NAMES = {id(m): m.__name__.rsplit(".", 1)[-1] for m in _BATCH1_MODULES}


class TestSingleSourceIdentity:
    def test_num_is_single_source(self):
        """单源身份断言：_num 与 parse_num 同一函数对象（is）。"""
        for mod in _BATCH1_MODULES:
            assert mod._num is parse_num, _MODULE_NAMES[id(mod)]

    def test_require_payload_dict_is_single_source(self):
        """带 _require_payload_dict 副本的批 1 文件（clock/jitter/pll）同源。"""
        for mod in (clock_noise_service, jitter_budget_service,
                    pll_budget_service):
            assert mod._require_payload_dict is require_payload_dict, (
                _MODULE_NAMES[id(mod)])

    def test_local_def_text_gone(self):
        """本地 def 消失文本钉（#116 遮蔽治理）：源码不含 ``def _num``。"""
        import inspect

        for mod in _BATCH1_MODULES:
            src = inspect.getsource(mod)
            assert "def _num(" not in src, _MODULE_NAMES[id(mod)]
            assert "def _require_payload_dict(" not in src, (
                _MODULE_NAMES[id(mod)])


class TestBehaviorFrozen:
    """行为冻结样本：切换前后 errors 文案逐位一致（合法/非法各一例）。"""

    def test_parse_num_messages_unchanged(self):
        errors: list[str] = []
        assert parse_num(None, "f_x", errors) is None
        assert errors == ["f_x 缺失"]
        errors = []
        assert parse_num(True, "b_x", errors) is None
        assert errors == ["b_x 不接受 bool（float(True)=1.0 静默污染）"]
        errors = []
        assert parse_num("abc", "s_x", errors) is None
        assert errors == ["s_x 必须是数字，实际 'abc'"]
        errors = []
        assert parse_num(0.0, "p_x", errors, positive=True) is None
        assert errors == ["p_x 必须 >0，实际 0.0"]
        errors = []
        assert parse_num(-1.0, "n_x", errors, nonneg=True) is None
        assert errors == ["n_x 必须 >=0，实际 -1.0"]
        assert parse_num("3.5", "ok_x", [], positive=True) == 3.5

    def test_require_payload_dict_message_unchanged(self):
        with pytest.raises(ValueError) as ei:
            require_payload_dict([1, 2])
        assert str(ei.value) == "payload 必须是 JSON 对象，实际 list"

    def test_service_error_envelopes_bitwise(self):
        """每并入文件一例非法 payload：errors 文案逐位（冻结样本）。

        文案样本切前置各文件本地副本实测值（批 1 判据：改前改后逐位一致）。
        """
        r = bias_tee_service.bias_tee_report({"f_corner_hz": None})
        assert not r["ok"] and r["errors"] == ["f_corner_hz 缺失"]

        r = clock_noise_service.clock_noise_jitter("not-a-dict")
        assert not r["ok"]
        assert r["errors"] == ["payload 必须是 JSON 对象，实际 str"]

        r = jitter_budget_service.jitter_budget_table("not-a-dict")
        assert not r["ok"]
        assert r["errors"] == ["payload 必须是 JSON 对象，实际 str"]

        r = pll_budget_service.pll_budget("not-a-dict")
        assert not r["ok"]
        assert r["errors"] == ["payload 必须是 JSON 对象，实际 str"]

        r = return_path_check_service.check_return_path_report(
            {"vias": "bad", "traces": "bad"})
        assert not r["ok"]
        assert r["errors"] == ["traces 缺失或非列表（须为列表，可为空）"]

    def test_positive_legal_payload_still_ok(self):
        """合法 payload 走单源后 ok 面不变（bias_tee 最小合法例）。"""
        r = bias_tee_service.bias_tee_report({"f_corner_hz": 1e6})
        assert r["ok"], r.get("errors")
