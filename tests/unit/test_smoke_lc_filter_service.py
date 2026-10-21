"""lc_filter_service 冒烟门（架构批 A5-C 测试盲区批量补冒烟席）。

背景（R8 盘点面 4 + A5-C triple-grep 复核）：src/rfauto/service/ 232 模块中
本服务是全仓零测试消费的 3 个真盲区之一（tests/ 无任何 qualified 引用，
src/scripts/ 亦无 CLI/MCP/api 消费者——孤儿模块，R8 盘点漏计，见
test_smoke_sparse_pce_service.py docstring 盲区总账）。

冒烟口径（最小直测，非内核判据门）：
1. import + 公开 API 面非空（4 入口全 callable + docstring 齐备）；
2. 每入口最小 dry-call（合法最小入参，纯计算零网络零真机）；
3. 信封契约：成功 {"ok": True,...}、非法入参 ok=False 不抛；
4. 全载荷 JSON 可序列化断言（service 层 JSON 进出铁律，规则 4）。

未触达函数：无——4 个公开函数全部直测。
（内核数值正确性归 core/lc_filter 判据门管辖，本文件只钉 service 壳面
接线与信封/序列化契约。）
"""

from __future__ import annotations

import inspect
import json

from rfauto.service import lc_filter_service as lfs

# Foster 教科书例（Foster 前导：jω 轴单极点/零点交错、留数全正）——
# Z(s) = (s²+1)(s²+25)/(s(s²+4)) = (s⁴+26s²+25)/(s³+4s)，pole 0/±j2、zero ±j1/±j5
_FOSTER_NUM = [1.0, 0.0, 26.0, 0.0, 25.0]
_FOSTER_DEN = [1.0, 0.0, 4.0, 0.0]

_EXPECTED_API = (
    "lc_prototype",
    "lc_cauer_ladder",
    "lc_foster",
    "lc_tolerance_study",
)


# ── 1. 公开 API 面 ───────────────────────────────────────────────────────────


def test_public_api_surface():
    for name in _EXPECTED_API:
        fn = getattr(lfs, name)
        assert callable(fn), name
        assert inspect.isfunction(fn), name
        assert fn.__doc__ and fn.__doc__.strip(), f"{name} docstring 缺失"
    assert lfs.LC_FILTER_SERVICE_SCHEMA_VERSION == "1.0"


# ── 2. lc_prototype：最小 dry-call + 信封 + JSON ─────────────────────────────


def test_lc_prototype_minimal_dry_call():
    out = lfs.lc_prototype({"response": "butterworth", "order": 3})
    assert out["ok"] is True
    for key in ("spec", "omega_norm", "power_gain", "power_loss_ratio", "zeros", "poles"):
        assert key in out
    assert len(out["omega_norm"]) == len(out["power_gain"]) == 401
    json.dumps(out)  # 全载荷 JSON 可序列化


def test_lc_prototype_error_envelopes():
    bad = lfs.lc_prototype({"response": "nope", "order": 3})
    assert bad["ok"] is False and bad["errors"]
    short_axis = lfs.lc_prototype({"response": "butterworth", "order": 3, "omega_norm": [1, 2]})
    assert short_axis["ok"] is False and short_axis["errors"]


# ── 3. lc_cauer_ladder：归一化/去归一化 + 自检 pass ──────────────────────────


def test_lc_cauer_ladder_normalized_selfcheck_pass():
    out = lfs.lc_cauer_ladder({"response": "butterworth", "order": 3})
    assert out["ok"] is True
    selfcheck = out["response_selfcheck"]
    assert selfcheck["pass"] is True
    assert selfcheck["max_rel_vs_prototype"] <= selfcheck["tolerance"]
    json.dumps(out)


def test_lc_cauer_ladder_denormalized():
    out = lfs.lc_cauer_ladder(
        {
            "response": "chebyshev1",
            "order": 3,
            "ripple_db": 0.5,
            "fc_hz": 1e9,
            "z0_ohm": 50.0,
        }
    )
    assert out["ok"] is True
    assert out["ladder"]["fc_hz"] == 1e9
    assert out["fc_3db_hz"] > 0.0
    json.dumps(out)


def test_lc_cauer_ladder_partial_denorm_rejected():
    out = lfs.lc_cauer_ladder({"response": "butterworth", "order": 3, "fc_hz": 1e9})
    assert out["ok"] is False and out["errors"]


# ── 4. lc_foster：Foster I/II 回代自检 + 非法 kind ───────────────────────────


def test_lc_foster_roundtrip_pass():
    for kind in ("foster_i", "foster_ii"):
        out = lfs.lc_foster({"kind": kind, "num": _FOSTER_NUM, "den": _FOSTER_DEN})
        assert out["ok"] is True, (kind, out.get("errors"))
        assert out["roundtrip_pass"] is True
        assert out["network"]["kind"] == kind
        json.dumps(out)


def test_lc_foster_bad_kind_envelope():
    out = lfs.lc_foster({"kind": "bogus", "num": [1.0], "den": [1.0]})
    assert out["ok"] is False and out["errors"]


# ── 5. lc_tolerance_study：worst_case 与 monte_carlo 双口径 ──────────────────


def test_lc_tolerance_study_worst_case():
    out = lfs.lc_tolerance_study(
        {
            "response": "butterworth",
            "order": 3,
            "fc_hz": 1e9,
            "z0_ohm": 50.0,
            "tol_frac": 0.05,
        }
    )
    assert out["ok"] is True
    study = out["study"]
    assert study["mode"] == "worst_case"
    assert study["fc_ideal_hz"] > 0.0
    assert "fc_shift_rel" in study
    json.dumps(out)


def test_lc_tolerance_study_monte_carlo():
    out = lfs.lc_tolerance_study(
        {
            "response": "butterworth",
            "order": 3,
            "fc_hz": 1e9,
            "z0_ohm": 50.0,
            "tol_frac": 0.02,
            "mode": "monte_carlo",
            "n_samples": 20,
            "seed": 7,
        }
    )
    assert out["ok"] is True
    assert out["study"]["mode"] == "monte_carlo"
    json.dumps(out)
