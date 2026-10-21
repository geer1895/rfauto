"""vibration_srs_service 冒烟门（架构批 A5-C 测试盲区批量补冒烟席）。

背景：全仓 232 个 service 模块中 3 个零测试消费真盲区之一（R8 点名，
复核与总账见 test_smoke_sparse_pce_service.py docstring）。

冒烟口径（最小直测，纯计算零网络零真机）：
1. import + 公开 API 面（2 入口 callable + docstring 齐备）；
2. g_sensitivity_query：已知族 dry-call（UNVERIFIED 透传+免责声明）；
   未知族的 ValueError 是内核显式契约（列可用族），直测钉住；
3. vibration_srs_report：Miles 单段（缺省）/ SRS+边带全段（族名 γ 与
   显值 γ 两分支）三态 dry-call + JSON 可序列化；γ 二者皆缺的
   ValueError 是显式 API 误用契约，直测钉住；
4. 全载荷 JSON 可序列化断言（service 层 JSON 进出铁律，规则 4）。

未触达函数：无——2 个公开函数全部分支直测。
（内核数值正确性归 core/vibration_srs 判据门管辖，本文件只钉 service
壳面接线与信封/序列化契约。）
"""

from __future__ import annotations

import inspect
import json

import pytest

from rfauto.service import vibration_srs_service as vss

_EXPECTED_API = ("g_sensitivity_query", "vibration_srs_report")


# ── 1. 公开 API 面 ───────────────────────────────────────────────────────────


def test_public_api_surface():
    for name in _EXPECTED_API:
        fn = getattr(vss, name)
        assert callable(fn), name
        assert inspect.isfunction(fn), name
        assert fn.__doc__ and fn.__doc__.strip(), f"{name} docstring 缺失"
    assert vss.VIBRATION_SRS_SERVICE_SCHEMA_VERSION == "1.0"


# ── 2. g_sensitivity_query ───────────────────────────────────────────────────


def test_g_sensitivity_query_known_family():
    out = vss.g_sensitivity_query("quartz_oscillator")
    assert out["ok"] is True
    assert out["entry"]["family"] == "quartz_oscillator"
    assert out["entry"]["gamma_per_g"] > 0.0
    assert out["disclaimer"]  # UNVERIFIED 免责声明透传
    assert "UNVERIFIED" in out["provenance"]["g_sensitivity"]
    json.dumps(out)


def test_g_sensitivity_query_unknown_family_raises():
    # 内核显式契约：未知族报错并列可用族（非信封，直抛）
    with pytest.raises(ValueError, match="未知器件族"):
        vss.g_sensitivity_query("unobtainium")


# ── 3. vibration_srs_report 三态 ─────────────────────────────────────────────


def test_miles_only_minimal_dry_call():
    out = vss.vibration_srs_report(f_n_hz=1e4, q=50.0, psd_g2_hz=1e-4)
    assert out["ok"] is True
    assert out["miles"]["g_rms"] > 0.0
    assert out["half_sine_srs"] is None  # 未给脉冲段 → 如实 None
    assert out["sideband"] is None
    json.dumps(out)


def test_full_report_all_segments():
    out = vss.vibration_srs_report(
        f_n_hz=1e4,
        q=50.0,
        psd_g2_hz=1e-4,
        pulse_a_g=50.0,
        pulse_t_s=0.011,
        f0_hz=10e9,
        gamma_family="quartz_oscillator",  # 族名查表分支
        vib_a_g=5.0,
        vib_f_v_hz=1e3,
    )
    assert out["ok"] is True
    srs = out["half_sine_srs"]
    assert srs["pulse_a_g"] == 50.0
    assert {"closed_form_undamped", "numerical_damped", "asymptotic_regime"} <= set(srs)
    sb = out["sideband"]
    assert sb["gamma_source_family"] == "quartz_oscillator"
    assert sb["delta_f_hz"] > 0.0
    assert sb["sideband_dbc_hz"] < 0.0  # dBc/Hz 必为负
    json.dumps(out)


def test_sideband_explicit_gamma_branch():
    out = vss.vibration_srs_report(
        f_n_hz=1e4,
        q=50.0,
        psd_g2_hz=1e-4,
        f0_hz=10e9,
        gamma_per_g=1e-9,  # 显值分支
        vib_a_g=5.0,
        vib_f_v_hz=1e3,
    )
    assert out["ok"] is True
    assert out["sideband"]["gamma_per_g"] == 1e-9
    assert out["sideband"]["gamma_source_family"] is None
    json.dumps(out)


def test_sideband_missing_gamma_raises():
    # 显式 API 误用契约：gamma_family/gamma_per_g 二者皆缺 → 直抛 ValueError
    with pytest.raises(ValueError, match="二选一"):
        vss.vibration_srs_report(
            f_n_hz=1e4,
            q=50.0,
            psd_g2_hz=1e-4,
            f0_hz=10e9,
            vib_a_g=5.0,
            vib_f_v_hz=1e3,
        )
