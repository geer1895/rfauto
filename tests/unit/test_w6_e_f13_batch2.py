"""W6-E F-13 批 2 单源身份钉：_num 族余量文件无损切换（2026-10-06）。

判据（ra_criteria SPECS §3.3 批 2 口径，W2-G 批 1 同款纪律）：
- 单源身份断言：pdn/dpd_static/fpa_antenna/layout_sim 的
  ``_require_payload_dict`` 与单源 ``require_payload_dict`` 同一函数对象；
  pdn ``_num`` 与 ``parse_num`` 同一函数对象；emc/metasurface 为
  ``partial(parse_num, accept_str=False)``（func 身份+绑定关键字双钉，
  service payload helpers 的 ``_err`` partial 钉先例同形）；
- #116 旧副本删净文本钉：七并入文件源码零本地 ``def _num`` /
  ``def _require_payload_dict(``；
- ``accept_str`` 策略参双钉（防静默漂移）：缺省 True 数字字符串收敛、
  False 严格拒收（emc 现行为保真）；
- pa_architectures ``unit_interval`` 本地后置检查钉（不撑大单源签名）；
- 文案分歧件（fpa/layout_sim）统一为单源文案的冻结样本（已声明变更）；
- C 组两文件（papr/physics_funnel）本地保留 + docstring 指认非 _helpers 族。
"""

from __future__ import annotations

import inspect

import pytest

from rfauto.service import (
    dpd_static_service,
    emc_service,
    fpa_antenna_service,
    layout_sim_service,
    metasurface_service,
    pa_architectures_service,
    papr_service,
    pdn_service,
    physics_funnel_service,
)
from rfauto.service._helpers import parse_num, require_payload_dict

_ALIAS_GUARD_MODULES = (
    pdn_service,
    dpd_static_service,
    fpa_antenna_service,
    layout_sim_service,
    pa_architectures_service,
)
_BATCH2_MODULES = (*_ALIAS_GUARD_MODULES, emc_service, metasurface_service)

_MODULE_NAMES = {id(m): m.__name__.rsplit(".", 1)[-1] for m in _BATCH2_MODULES}


class TestSingleSourceIdentity:
    def test_require_payload_dict_alias_modules(self):
        """五文件载荷守卫 = 单源同一函数对象（别名 import 落地）。"""
        for mod in _ALIAS_GUARD_MODULES:
            assert mod._require_payload_dict is require_payload_dict, (
                _MODULE_NAMES[id(mod)])

    def test_pdn_num_is_parse_num(self):
        """pdn _num（positive+nonneg 全在单源签名内）= 纯别名。"""
        assert pdn_service._num is parse_num

    def test_emc_metasurface_partial_binding(self):
        """emc/metasurface _num = partial(parse_num, accept_str=False)
        （func 身份 + 绑定关键字双钉，partial 副本回归即红）。"""
        for mod in (emc_service, metasurface_service):
            assert mod._num.func is parse_num, _MODULE_NAMES[id(mod)]
            assert mod._num.keywords == {"accept_str": False}, (
                _MODULE_NAMES[id(mod)])

    def test_local_def_text_gone(self):
        """#116：旧副本删净防遮蔽——六纯并入文件零本地 def 文本。

        pa_architectures 豁免 ``def _num(``（SPECS §3.2 批 2 明文：本地薄
        包装=parse_num 委托+unit_interval 后置检查，非副本）；其遮蔽回归
        由下方专钉守护（包装体必须委托单源、旧 float 收敛体必须消失）。
        """
        for mod in _BATCH2_MODULES:
            src = inspect.getsource(mod)
            if mod is not pa_architectures_service:
                assert "def _num(" not in src, _MODULE_NAMES[id(mod)]
            assert "def _require_payload_dict(" not in src, (
                _MODULE_NAMES[id(mod)])

    def test_pa_wrapper_is_delegation_not_copy(self):
        """pa 薄包装守护：_num 体必须调 parse_num；旧本地收敛体消失。"""
        src = inspect.getsource(pa_architectures_service)
        assert "def _num(" in src
        assert "val = float(value)" not in src      # 旧 float 收敛体
        assert "def _num(\n    value: Any,\n    name: str,\n    errors: list[str],\n    *,\n    positive: bool = False,\n    nonneg: bool = False,\n    unit_interval: bool = False,\n) -> float | None:\n    \"\"\"入参收敛（F-13 批 2：单源 ``parse_num`` 委托 + unit_interval 本地" in src


class TestAcceptStrStrategy:
    def test_default_true_converts_numeric_string(self):
        """缺省 accept_str=True：'3.5' → 3.5（单源现行为，防漂移钉）。"""
        errors: list[str] = []
        assert parse_num("3.5", "ok_x", errors, positive=True) == 3.5
        assert errors == []

    def test_false_rejects_numeric_string(self):
        """accept_str=False：'3.5' 字符串入参 → error（emc 现行为）。"""
        errors: list[str] = []
        assert parse_num("3.5", "s_x", errors, accept_str=False) is None
        assert errors == ["s_x 必须是实数，实际 '3.5'"]

    def test_emc_strict_semantics_preserved(self):
        """emc _num 数字字符串拒收（isinstance 严格语义经 partial 保真）。"""
        errors: list[str] = []
        assert emc_service._num("3.5", "f_mhz", errors) is None
        assert errors == ["f_mhz 必须是实数，实际 '3.5'"]
        errors = []
        assert emc_service._num(3.5, "f_mhz", errors, positive=True) == 3.5
        assert errors == []

    def test_metasurface_strict_semantics_preserved(self):
        errors: list[str] = []
        assert metasurface_service._num("abc", "w_mm", errors) is None
        assert errors == ["w_mm 必须是实数，实际 'abc'"]


class TestPaUnitIntervalPostCheck:
    def test_in_range_passes(self):
        errors: list[str] = []
        assert pa_architectures_service._num(
            0.5, "sigma", errors, unit_interval=True) == 0.5
        assert errors == []

    def test_boundaries_inclusive(self):
        """0≤v≤1 闭区间（原本地副本 `not (0.0 <= val <= 1.0)` 语义）。"""
        errors: list[str] = []
        assert pa_architectures_service._num(
            0.0, "sigma", errors, unit_interval=True) == 0.0
        assert pa_architectures_service._num(
            1.0, "sigma", errors, unit_interval=True) == 1.0
        assert errors == []

    def test_out_of_range_message_unchanged(self):
        errors: list[str] = []
        assert pa_architectures_service._num(
            1.2, "sigma", errors, unit_interval=True) is None
        assert errors == ["sigma 必须 ∈ [0,1]，实际 1.2"]

    def test_none_short_circuits_post_check(self):
        """缺失（None）由单源记「缺失」；后置检查不得对 None 二次报错。"""
        errors: list[str] = []
        assert pa_architectures_service._num(
            None, "sigma", errors, unit_interval=True) is None
        assert errors == ["sigma 缺失"]


class TestDeclaredMessageUnification:
    """文案分歧件统一为单源文案（批 2 判据：差异仅为已声明文案统一）。"""

    def test_fpa_payload_guard_message(self):
        """fpa 原「payload 必须为 dict」→ 单源「payload 必须是 JSON 对象…」。"""
        with pytest.raises(ValueError, match="payload 必须是 JSON 对象"):
            fpa_antenna_service._require_payload_dict([1])

    def test_fpa_design_error_envelope_carries_unified_text(self):
        r = fpa_antenna_service.fpa_design("not-a-dict")
        assert r["ok"] is False
        assert r["errors"] == ["payload 必须是 JSON 对象，实际 str"]

    def test_layout_sim_payload_guard_message(self):
        """layout_sim 原「payload 必须为映射: X」→ 单源文案。"""
        with pytest.raises(ValueError, match="payload 必须是 JSON 对象"):
            layout_sim_service._require_payload_dict("x")

    def test_dpd_payload_guard_message_unchanged(self):
        """dpd 原本地副本与单源逐字节同 → 文案零变化（无损切换对照面）。"""
        with pytest.raises(ValueError) as ei:
            dpd_static_service._require_payload_dict(3.14)
        assert str(ei.value) == "payload 必须是 JSON 对象，实际 float"

    def test_pdn_bool_message_unified(self):
        """pdn 三处文案分歧之一（bool）：本地「不接受布尔值」→ 单源文案。"""
        errors: list[str] = []
        assert pdn_service._num(True, "p_x", errors) is None
        assert errors == ["p_x 不接受 bool（float(True)=1.0 静默污染）"]

    def test_pdn_none_message_unified(self):
        """pdn None 语义：本地「必须是数字，实际 None」→ 单源「缺失」。"""
        errors: list[str] = []
        assert pdn_service._num(None, "p_x", errors, positive=True) is None
        assert errors == ["p_x 缺失"]


class TestCGroupStayLocal:
    """C 组两文件永不并（SPECS §3.1）：本地保留 + docstring 指认。"""

    def test_papr_local_def_marked_non_helpers(self):
        src = inspect.getsource(papr_service)
        assert "def _num(" in src          # 本地副本在（raise 式契约）
        assert "非 _helpers 族" in src      # docstring 指认在

    def test_physics_funnel_row_taker_marked_non_helpers(self):
        src = inspect.getsource(physics_funnel_service)
        assert "def _num(" in src          # 行取值器，完全不同源
        assert "非 _helpers 族" in src
