"""LT-1 G/T 组合键锚测试（round18 :129，2026-10-02）。

锚口径（任务书预声明）：G/T 恒等式回收——G/T = G − 10log10(T290+Te)
一类组合与手算**逐位**（同一浮点运算序，`==` 断言）；级联消费链 =
cascade_budget 输出（gain_total_db/nf_total_db 同名直连）→ gt_ratio
对照 Friis 手链。方法定义出处 ITU-R S.733-2（定义级引用，数值锚全部
恒等式/手算，不引外部表值）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_KEY = "gt_ratio"


# ─── 注册面（接口先行）────────────────────────────────────────────────────

def test_gt_ratio_registered_and_described():
    assert _KEY in set(CALCULATOR_REGISTRY.names())
    spec = CALCULATOR_REGISTRY.get(_KEY)
    assert spec.description and not spec.experimental
    described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    assert {p["name"] for p in described[_KEY]["params"]} >= set(spec.required)
    json.dumps(described[_KEY], ensure_ascii=False)  # JSON 进出契约


# ─── 恒等式锚（手算逐位）─────────────────────────────────────────────────

def test_identity_t_sys_direct_bitwise():
    """T_sys 直接给定：G/T = G − 10·log10(T_sys)，同运算序逐位相等。"""
    out = run_calculator(_KEY, {"gain_db": 40.0, "t_sys_k": 100.0})
    assert out["ok"], out
    r = out["result"]
    assert r["gt_db_per_k"] == 40.0 - 10.0 * math.log10(100.0)  # log10(100)=2 精确 → 20.0
    assert r["path"] == "t_sys_direct"
    assert r["t_e_k"] is None


def test_identity_nf_path_bitwise():
    """NF 路径恒等式：G/T = G − 10log10(T290 + T0·(F−1))（任务书原式）。

    F = 10^(NF/10)；同一浮点运算序 → `==` 逐位。
    """
    g_db, nf_db = 40.0, 3.0
    f_lin = 10.0 ** (nf_db / 10.0)
    expected = g_db - 10.0 * math.log10(290.0 + 290.0 * (f_lin - 1.0))
    out = run_calculator(_KEY, {"gain_db": g_db, "nf_db": nf_db})
    assert out["ok"], out
    r = out["result"]
    assert r["gt_db_per_k"] == expected  # 逐位（非 approx）
    assert r["path"] == "nf"
    assert r["t_sys_k"] == 290.0 + 290.0 * (f_lin - 1.0)
    assert r["t_e_k"] == 290.0 * (f_lin - 1.0)


def test_identity_te_path_bitwise():
    """te 路径恒等式：T_sys = T_ant + T_e，G/T = G − 10log10(T_sys)。"""
    g_db, te, t_ant = 25.0, 95.0, 45.0
    expected = g_db - 10.0 * math.log10(t_ant + te)
    out = run_calculator(_KEY, {"gain_db": g_db, "t_e_k": te,
                                "t_ant_k": t_ant})
    assert out["ok"], out
    r = out["result"]
    assert r["gt_db_per_k"] == expected
    assert r["path"] == "te" and r["t_sys_k"] == t_ant + te


def test_antenna_only_path_labeled():
    """三输入全缺省 → T_sys=t_ant_k（antenna_only，如实标注）。"""
    out = run_calculator(_KEY, {"gain_db": 30.0})
    assert out["ok"], out
    r = out["result"]
    assert r["path"] == "antenna_only"
    assert r["gt_db_per_k"] == 30.0 - 10.0 * math.log10(290.0)
    assert r["t_e_k"] is None and r["note"] is None


def test_priority_and_redundancy_note():
    """t_sys_k > nf_db > t_e_k 择用；冗余输入如实报告不静默。"""
    out = run_calculator(_KEY, {"gain_db": 40.0, "t_sys_k": 100.0,
                                "nf_db": 3.0, "t_e_k": 50.0})
    assert out["ok"], out
    r = out["result"]
    assert r["path"] == "t_sys_direct"
    assert r["gt_db_per_k"] == 40.0 - 10.0 * math.log10(100.0)
    assert r["note"] is not None and "nf_db" in r["note"] and "t_e_k" in r["note"]
    # 仅 nf+t_e 冗余对：nf 胜出，note 只报 t_e_k
    out2 = run_calculator(_KEY, {"gain_db": 40.0, "nf_db": 3.0, "t_e_k": 50.0})
    assert out2["result"]["path"] == "nf"
    assert out2["result"]["note"] is not None and "t_e_k" in out2["result"]["note"]


def test_negative_gt_and_custom_t0():
    """负 G/T 合法（低增益高噪声）；t0_k 可换基准（290→75 深空口径）。"""
    out = run_calculator(_KEY, {"gain_db": 10.0, "t_sys_k": 5000.0})
    assert out["result"]["gt_db_per_k"] == 10.0 - 10.0 * math.log10(5000.0)
    assert out["result"]["gt_db_per_k"] < 0.0
    f_lin = 10.0 ** (2.0 / 10.0)
    out2 = run_calculator(_KEY, {"gain_db": 30.0, "nf_db": 2.0, "t0_k": 75.0})
    assert out2["result"]["t_e_k"] == 75.0 * (f_lin - 1.0)


# ─── 显式报错面（域守卫）─────────────────────────────────────────────────

@pytest.mark.parametrize("params,match", [
    ({"gain_db": 40.0, "t_sys_k": 0.0}, "必须为正"),
    ({"gain_db": 40.0, "nf_db": -1.0}, "nf_db"),
    ({"gain_db": 40.0, "t_e_k": -5.0}, "t_e_k"),
    ({"gain_db": 40.0, "t_ant_k": 0.0}, "t_ant_k"),
    ({"gain_db": 40.0, "t0_k": 0.0}, "t0_k"),
    ({"gain_db": True, "t_sys_k": 100.0}, "bool"),
    ({"gain_db": float("nan")}, "有限"),
    ({"t_sys_k": 100.0}, "缺少必需参数"),
])
def test_domain_errors_translated_ok_false(params, match):
    out = run_calculator(_KEY, params)
    assert out["ok"] is False, f"{params} 应显式报错: {out}"
    assert match in out["error"]


# ─── 消费链：cascade_budget 输出同名直连 ─────────────────────────────────

def test_cascade_budget_output_feeds_gt_ratio():
    """round18 "cascade 直连"：级联 (gain_total_db, nf_total_db) → G/T，
    对照 Friis 手链逐位。"""
    cas = run_calculator("cascade_budget", {
        "stages": [
            {"type": "amp", "gain_db": 30.0, "nf_db": 2.0, "bw_hz": 1e6},
            {"type": "cable", "gain_db": -1.0, "nf_db": 1.0},
        ],
        "rx_power_dbm": -90.0,
    })
    assert cas["ok"], cas
    g = cas["result"]["gain_total_db"]
    nf = cas["result"]["nf_total_db"]
    assert g == 29.0  # 级联总增益（30−1）
    # Friis 手链：F = F1 + (F2−1)/G1（线性域）
    f1 = 10.0 ** (2.0 / 10.0)
    f2 = 10.0 ** (1.0 / 10.0)
    f_tot = f1 + (f2 - 1.0) / 10.0 ** (30.0 / 10.0)
    nf_hand = 10.0 * math.log10(f_tot)
    assert nf == pytest.approx(nf_hand, rel=1e-12)
    out = run_calculator(_KEY, {"gain_db": g, "nf_db": nf})
    assert out["ok"], out
    # 期望式按本键同一运算序自 nf 反推（键内 F=10^(NF/10)），逐位可 `==`
    f_from_nf = 10.0 ** (nf / 10.0)
    expected = g - 10.0 * math.log10(290.0 + 290.0 * (f_from_nf - 1.0))
    assert out["result"]["gt_db_per_k"] == expected  # 逐位
    assert out["result"]["path"] == "nf"
