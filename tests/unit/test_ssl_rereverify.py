"""Q-X27 悬置带线双修复重验判读函数钉（aurora_q 席位 Q-X27）。

对象=Q-RM-1（污染态，Q-X9 真跑）→ Q-RM-4（Q-X19 MeasPlaneShift 近场修复后
重跑）→ 重验（Q-X19+Q-X21 双修复后真跑，2026-11-07 11:35 落树终态）三态的
判读纯函数单源：三态对照表、G5 归因检验、G3 基准切换（闭式 1.6034 → FD
真值 1.58537）。判读驱动=runs/aurora_q/qx27_rereverify/{qx27_framework.py,
qx27_verdict.py}（import 本模块同一判读面，Q-X9 runner 同款倒挂依赖）。

预声明与冻结纪律（#122）：
- 冻结门=tests.unit.test_suspended_anchor_verdict（G1–G5 门限、闭式锚与
  gate_g5_health/gate_g3_eps_eff 原样消费，不复制不放宽）；
- G3 FD 基准=Q-X20 第三方裁判收敛真值（runs/aurora_q/qx20_fd_judge/
  judge_result.json，2026-11-07 10:22 冻结）——早于重验真跑落树（11:34），
  故"重验 G3 对照基准切 FD 真值"的预声明时序在数据之前；FD 基准=分析面
  旁证口径，冻结门锚仍=闭式（不因结果改门）；
- G5 归因阈值（大幅≥50% / 不变≤10%）系任务书两分支定性规则的本席数值
  操作化——重验已落树后定标，时序如实登记于 REPORT §6（定性分支本身
  先于落树：任务书预声明）；观测值 306→190（−37.9%）落中带，不凑两端。

数字锚来源（本席落树时点快照；runs/ 湖 gitignored——测试以常量随行登记
出处，不运行时读湖）：
- Q-RM-1：runs/aurora_q/qx19_fix/prefix_backup_q_rm1/verdict.json；
- Q-RM-4：runs/aurora_q/qx19_fix/rerun_log.txt（10:13；verdict 全文无
  JSON 备份，数值=rerun_log + qx25_verify/VERIFY_REPORT.md §1 表双源一致）；
- 重验：runs/aurora_q/qx9_anchor/verdict.json（11:35 终态）+ ssl_*/stats.json
  （over_unity 分变体：shield 139 + open 41 = 180，本席 csv 重数互证一致；
  11:35 前一度读到重跑中途态 verdict（count=190，与 stats 和不符）——
  终态以三源一致（verdict=stats 和=csv 重数）为准，中途态已过，框架
  驱动带三源一致 fail-loud 守卫防同类混态）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tests.unit.test_suspended_anchor_verdict import (  # 冻结门单源（不复制）
    G3_PARTIAL,
    G3_PASS,
    PASSIVITY_MAX,
    closed_form_anchor,
    gate_g3_eps_eff,
    gate_g5_health,
)

# ── FD 第三方真值（Q-X20 判读冻结值；#118 独立裁判身份三重互证在案）──────────
#: runs/aurora_q/qx20_fd_judge/judge_result.json（六级阶梯三点 Richardson 外推，
#: 2026-11-07 10:22 冻结——早于重验真跑 11:34 落树）
FD_EPS_EFF = 1.5853718267559125
FD_Z0_OHM = 50.48231944295761
#: FD 基准 ±2% 门（任务书预声明口径：门限承袭冻结 G3 的 2%/5% 不放宽）
G3_FD_PASS, G3_FD_PARTIAL = G3_PASS, G3_PARTIAL

# ── G5 归因检验阈值（本席数值操作化；时序如实登记 REPORT §6）─────────────────
#: 「大幅下降」线：drop_ratio ≥ 0.50 → 线端入网修复为主导成分被清偿
G5_SUBSTANTIAL_DROP_RATIO = 0.50
#: 「不变」线：drop_ratio ≤ 0.10 → 计数对 ±0.15% 提取偏置底的敏感带内视同不变
G5_NO_DROP_RATIO = 0.10
#: passivity floor（50Ω 失配偏置能量面）基本未动的容差（|Δ| ≤ 0.5pp）
G5_FLOOR_TOL = 0.005

# ── 三态快照（判读函数输入面；出处见模块 docstring）─────────────────────────
V_RM1: dict = {
    "verdict": "DISAGREE",
    "gates": {
        "G1": {"status": "FAIL", "observed_s21_mean_db": -0.5764673318969037},
        "G2": {"status": "PASS", "observed_s11_max_db": -19.651581971118137},
        "G3": {"status": "PARTIAL", "observed_eps_eff": 1.5551136839380097,
               "rel": 0.030125588765482297},
        "G4": {"status": "PASS", "observed_z0_ohm": 50.46607768614223,
               "rel": 0.004274454519440311},
        "G5": {"status": "PASS", "passivity_max": 0.8912247435527315,
               "s_over_unity_cnt": 0},
    },
}
V_RM4: dict = {
    "verdict": "DISAGREE",
    "gates": {
        "G1": {"status": "PASS", "observed_s21_mean_db": -0.002122154550186237},
        "G2": {"status": "PASS", "observed_s11_max_db": -19.552961114403015},
        "G3": {"status": "PARTIAL", "observed_eps_eff": 1.5543533774814462,
               "rel": 0.030599767460283606},
        "G4": {"status": "PASS", "observed_z0_ohm": 48.78393643639454,
               "rel": 0.029200139969976318},
        "G5": {"status": "FAIL", "passivity_max": 1.0142031805205316,
               "s_over_unity_cnt": 306},
    },
}
V_REVERIFY: dict = {
    "verdict": "DISAGREE",
    "gates": {
        "G1": {"status": "PASS", "observed_s21_mean_db": -0.0009062191977738067},
        "G2": {"status": "PASS", "observed_s11_max_db": -19.656569100630634},
        "G3": {"status": "PARTIAL", "observed_eps_eff": 1.5572964825028963,
               "rel": 0.028764247472669587},
        "G4": {"status": "PASS", "observed_z0_ohm": 48.83535658735172,
               "rel": 0.028176879466653964},
        "G5": {"status": "FAIL", "passivity_max": 1.0123252067043993,
               "s_over_unity_cnt": 180},
    },
}
#: G5 分变体超一点数（Q-RM-4：qx25_verify/VERIFY_REPORT.md §2.1；
#: 重验：qx9_anchor/ssl_{shield,open}/stats.json，139+41=180=verdict 总数）
OU_RM4_VARIANTS: dict[str, int] = {"ssl_shield": 98, "ssl_open": 208}
OU_REVERIFY_VARIANTS: dict[str, int] = {"ssl_shield": 139, "ssl_open": 41}


# ── G3 基准切换（闭式冻结锚 ↔ FD 第三方真值双轨并列）────────────────────────
def g3_fd_band() -> tuple[float, float]:
    """FD 真值 ±2% 带（任务书预声明 [1.5537, 1.6171] 的精确值）。"""
    return (FD_EPS_EFF * (1.0 - G3_FD_PASS), FD_EPS_EFF * (1.0 + G3_FD_PASS))


def _rel_status(rel_abs: float) -> str:
    if rel_abs <= G3_FD_PASS:
        return "PASS"
    return "PARTIAL" if rel_abs <= G3_FD_PARTIAL else "FAIL"


def g3_basis_switch(eps_eff_observed: float) -> dict[str, object]:
    """G3 双基准并列判读：冻结门锚=闭式（现场重算，#122 不改门）；FD 真值=
    分析面旁证口径（Q-X20 预声明时序先于重验数据）。rel 带符号（负=观测
    低于基准），门判读用 |rel|。"""
    closed = closed_form_anchor()["eps_eff"]
    rel_closed_signed = (eps_eff_observed - closed) / closed
    rel_fd_signed = (eps_eff_observed - FD_EPS_EFF) / FD_EPS_EFF
    lo, hi = g3_fd_band()
    return {
        "gate": "G3",
        "observed_eps_eff": eps_eff_observed,
        "closed_eps_eff": closed,
        "rel_vs_closed_signed": rel_closed_signed,
        "rel_vs_closed": abs(rel_closed_signed),
        "status_vs_closed": _rel_status(abs(rel_closed_signed)),
        "fd_eps_eff": FD_EPS_EFF,
        "rel_vs_fd_signed": rel_fd_signed,
        "rel_vs_fd": abs(rel_fd_signed),
        "status_vs_fd": _rel_status(abs(rel_fd_signed)),
        "fd_band_2pct": [lo, hi],
        "in_fd_band": bool(lo <= eps_eff_observed <= hi),
    }


# ── 三态对照表（Q-RM-1 → Q-RM-4 → 重验；G1–G5 逐门 before/after/expected）────
_STATUS_RANK = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}
_GATE_ORDER = ("G1", "G2", "G3", "G4", "G5")
_GATE_METRIC_KEY = {
    "G1": "observed_s21_mean_db",
    "G2": "observed_s11_max_db",
    "G3": "observed_eps_eff",
    "G4": "observed_z0_ohm",
}


def status_movement(status_a: str, status_b: str) -> str:
    """门态迁移分类（PASS 优 / FAIL 劣）：improved / unchanged / degraded。"""
    ra, rb = _STATUS_RANK[status_a], _STATUS_RANK[status_b]
    if rb < ra:
        return "improved"
    return "degraded" if rb > ra else "unchanged"


def _fail_gates(gates: dict) -> list[str]:
    return sorted(k for k, v in gates.items() if v["status"] == "FAIL")


def three_state_gate_table(before: dict, near_fix: dict, reverify: dict,
                           expected: dict | None = None) -> dict[str, object]:
    """三态五门对照表（全 JSON 可序列化）。

    before/near_fix/reverify = verdict 字典（verdict + gates，见本模块三态
    快照 schema）；expected = 预声明重验态（键 ``<G>_status``）。逐门行含
    三态观测+状态、两步迁移分类、重验态对预声明吻合位；顶层带三态总
    verdict 与各态 FAIL 驱动门清单。
    """
    expected = expected or {}
    gb, gn, gr = before["gates"], near_fix["gates"], reverify["gates"]
    rows: list[dict[str, object]] = []
    for gate in _GATE_ORDER:
        row: dict[str, object] = {"gate": gate,
                                  "metric": _GATE_METRIC_KEY.get(gate)}
        for label, g in (("before", gb[gate]), ("near_fix", gn[gate]),
                         ("reverify", gr[gate])):
            if gate == "G5":
                entry = {"status": g["status"],
                         "passivity_max": g.get("passivity_max"),
                         "over_unity_cnt": g.get("s_over_unity_cnt")}
            else:
                entry = {"status": g["status"],
                         "observed": g.get(row["metric"]),
                         "rel_vs_closed": g.get("rel")}
            row[label] = entry
        row["move_before_to_near"] = status_movement(gb[gate]["status"],
                                                     gn[gate]["status"])
        row["move_near_to_reverify"] = status_movement(gn[gate]["status"],
                                                       gr[gate]["status"])
        exp_key = f"{gate}_status"
        if exp_key in expected:
            row["expected_reverify"] = expected[exp_key]
            row["reverify_matches_expected"] = (
                gr[gate]["status"] == expected[exp_key])
        rows.append(row)
    return {
        "rows": rows,
        "verdict_before": before["verdict"],
        "verdict_near_fix": near_fix["verdict"],
        "verdict_reverify": reverify["verdict"],
        "fail_gates_before": _fail_gates(gb),
        "fail_gates_near_fix": _fail_gates(gn),
        "fail_gates_reverify": _fail_gates(gr),
    }


# ── G5 归因检验（任务书两分支 + 中带如实分支）───────────────────────────────
_G5_BRANCH_TEXT = {
    "SUBSTANTIAL_DROP": (
        "Q-X21 线端入网修复有效（G5 超一点主导成分被清偿）；"
        "Q-X25 50Ω 失配偏置仍为剩余面（floor 未清零）"),
    "MIXED_PARTIAL_DROP": (
        "Q-X21 线端入网修复部分有效（少数成分被清偿，未达大幅线）；"
        "主导剩余面=Q-X25 50Ω 失配偏置（floor 未动，超一点未清零）"),
    "NO_DROP": (
        "Q-X21 线端入网修复对 G5 无效或另有根因（如实登记）；"
        "归因面维持 Q-X25 50Ω 失配偏置"),
    "NO_BASELINE": ("无 Q-RM-4 基线（over_unity=0），归因检验不适用"),
}


def g5_attribution_test(
    over_unity_before: int,
    over_unity_after: int,
    passivity_before: float,
    passivity_after: float,
    per_variant_before: dict[str, int] | None = None,
    per_variant_after: dict[str, int] | None = None,
) -> dict[str, object]:
    """G5 归因检验：Q-RM-4 → 重验的超一点计数迁移分类与剩余面判读。

    分支语义（任务书预声明两分支 + 本席中带分支，#122 如实不凑两端）：
    SUBSTANTIAL_DROP（≥50%）→ 任务分支①（线端入网修复有效+失配偏置仍为
    剩余面）；NO_DROP（≤10%）→ 任务分支②（修复无效或另有根因）；
    其间 → MIXED_PARTIAL_DROP（部分有效，主导剩余面仍=失配偏置）。
    passivity floor（能量面）|Δ|≤G5_FLOOR_TOL 视为"未动"——floor 未动且
    超一点未清零 ⇒ 剩余面=50Ω 失配偏置（Q-X25 归因）不被本修动摇。
    归因分类不改变冻结 G5 门（over_unity==0 零容差，#122）。
    """
    if over_unity_before <= 0:
        classification = "NO_BASELINE"
        drop_ratio = None
    else:
        drop_ratio = (over_unity_before - over_unity_after) / over_unity_before
        if drop_ratio >= G5_SUBSTANTIAL_DROP_RATIO:
            classification = "SUBSTANTIAL_DROP"
        elif drop_ratio <= G5_NO_DROP_RATIO:
            classification = "NO_DROP"
        else:
            classification = "MIXED_PARTIAL_DROP"
    floor_delta = passivity_after - passivity_before
    floor_unchanged = abs(floor_delta) <= G5_FLOOR_TOL
    per_variant: dict[str, object] | None = None
    if per_variant_before and per_variant_after:
        drops: dict[str, float] = {}
        for k, b in per_variant_before.items():
            a = per_variant_after.get(k)
            if a is not None:
                drops[k] = (b - a) / b if b > 0 else 0.0
        any_substantial_drop = any(d > G5_NO_DROP_RATIO for d in drops.values())
        any_rise = any(d < 0.0 for d in drops.values())
        variant_asymmetric = bool(drops) and any_substantial_drop and any_rise
        per_variant = {"before": dict(per_variant_before),
                       "after": dict(per_variant_after),
                       "drop_ratio": drops,
                       "variant_asymmetric": variant_asymmetric}
    residual_face = ("Q-X25_50ohm_mismatch_bias"
                     if floor_unchanged
                     and classification in ("MIXED_PARTIAL_DROP", "NO_DROP")
                     else "reassess_floor_and_components")
    if over_unity_after > 0:
        frozen_note = ("冻结 G5 门（over_unity==0 零容差）不受归因分类影响；"
                       f"重验超一点 {over_unity_after}>0 ⇒ 冻结门仍 FAIL"
                       "（#122 不改门）")
    else:
        frozen_note = "重验超一点=0：冻结 G5 门 PASS（归因检验使命完成）"
    return {
        "over_unity_before": over_unity_before,
        "over_unity_after": over_unity_after,
        "drop_ratio": drop_ratio,
        "classification": classification,
        "branch_text": _G5_BRANCH_TEXT[classification],
        "passivity_before": passivity_before,
        "passivity_after": passivity_after,
        "floor_delta": floor_delta,
        "floor_unchanged": floor_unchanged,
        "residual_face": residual_face,
        "per_variant": per_variant,
        "frozen_gate_note": frozen_note,
    }


# ── 重验态预声明期望与吻合核对（fix_evidence.json expectation + 任务书）──────
def predeclared_expectations() -> dict[str, object]:
    """重验态预声明期望（Q-X19 fix_evidence.json expectation 承袭 + 任务书
    G5 count 分支）：冻结门锚下 G3=PARTIAL（FD 基准旁证口径另列 PASS 预期）；
    G5 冻结门要求超一点归零才 PASS，任务书预期=计数大幅下降分支。"""
    return {
        "G1_status": "PASS",
        "G2_status": "PASS",
        "G3_status": "PARTIAL",
        "G3_fd_basis_status": "PASS",
        "G4_status": "PASS",
        "G5_status": "FAIL",
        "G5_count_branch": "SUBSTANTIAL_DROP",
        "verdict": "PARTIAL",
    }


def expectation_check(reverify: dict, g5_classification: str,
                      g3_fd_status: str) -> dict[str, object]:
    """重验态对预声明期望的逐项吻合核对（hits/misses 双清单，如实不凑）。"""
    exp = predeclared_expectations()
    gates = reverify["gates"]
    hits: list[str] = []
    misses: list[str] = []
    for gate in ("G1", "G2", "G3", "G4", "G5"):
        key = f"{gate}_status"
        actual = gates[gate]["status"]
        entry = f"{key}: expected={exp[key]} actual={actual}"
        (hits if actual == exp[key] else misses).append(entry)
    if g3_fd_status == exp["G3_fd_basis_status"]:
        hits.append(f"G3_fd_basis_status: expected=PASS actual={g3_fd_status}")
    else:
        misses.append(f"G3_fd_basis_status: expected=PASS "
                      f"actual={g3_fd_status}")
    if g5_classification == exp["G5_count_branch"]:
        hits.append(f"G5_count_branch: expected={exp['G5_count_branch']} "
                    f"actual={g5_classification}")
    else:
        misses.append(f"G5_count_branch: expected={exp['G5_count_branch']} "
                      f"actual={g5_classification}")
    actual_verdict = reverify["verdict"]
    if actual_verdict == exp["verdict"]:
        hits.append(f"verdict: expected={exp['verdict']} "
                    f"actual={actual_verdict}")
    else:
        misses.append(f"verdict: expected={exp['verdict']} "
                      f"actual={actual_verdict}")
    return {"hits": hits, "misses": misses,
            "n_hits": len(hits), "n_misses": len(misses)}


# ══ 单测（判读函数钉；数字锚=本席落树时点快照，出处见 docstring）════════════

def test_fd_truth_anchor_pinned():
    """FD 真值常量钉（Q-X20 judge_result.json 冻结值）+ ±2% 带=任务书
    [1.5537, 1.6171] + 对闭式偏差落 Q-X20 定论带（+1.14%）。"""
    assert math.isclose(FD_EPS_EFF, 1.5853718267559125, abs_tol=1e-15)
    assert math.isclose(FD_Z0_OHM, 50.48231944295761, abs_tol=1e-12)
    lo, hi = g3_fd_band()
    assert round(lo, 4) == 1.5537 and round(hi, 4) == 1.6171
    closed = closed_form_anchor()["eps_eff"]
    bias = (closed - FD_EPS_EFF) / FD_EPS_EFF
    assert 0.0113 <= bias <= 0.01145, bias           # Q-X20 §0.2：闭式高 +1.14%
    # FD 与 Q-X9 冻结门锚独立两源：闭式现场重算仍=1.6034 口径
    assert math.isclose(closed, 1.6034175826523378, rel_tol=1e-9)


def test_g3_basis_switch_three_states_real_values():
    """三态 εeff 双基准并列判读钉：冻结锚（闭式）全 PARTIAL；FD 基准全 PASS
    （重验 1.769% / Q-RM-4 1.957% / Q-RM-1 1.909%，均带内、带符号负向）。"""
    cases = (
        ("Q-RM-1", V_RM1["gates"]["G3"]["observed_eps_eff"], 0.019086, 0.030126),
        ("Q-RM-4", V_RM4["gates"]["G3"]["observed_eps_eff"], 0.019566, 0.030600),
        ("reverify", V_REVERIFY["gates"]["G3"]["observed_eps_eff"], 0.017709,
         0.028764),
    )
    for label, obs, fd_rel, closed_rel in cases:
        r = g3_basis_switch(obs)
        assert r["status_vs_closed"] == "PARTIAL", label   # 冻结锚不因切换改
        assert r["status_vs_fd"] == "PASS", label          # FD 基准带内
        assert r["in_fd_band"] is True, label
        assert r["rel_vs_fd"] == pytest.approx(fd_rel, abs=2e-5), label
        assert r["rel_vs_closed"] == pytest.approx(closed_rel, abs=2e-5), label
        assert r["rel_vs_fd_signed"] < 0, label            # 引擎低于 FD 真值


def test_g3_basis_switch_band_boundaries_and_clean_port():
    """FD 带边界跨阈钉（±1e-9 挪移）+ 干净口 1.54594（Q-X13/Q-X20 口径）
    对 FD=2.488% 落 PARTIAL 带（与 Q-X20 §0.5 判语闭环）。"""
    lo, hi = g3_fd_band()
    assert g3_basis_switch(lo)["status_vs_fd"] == "PASS"           # 下界含
    assert g3_basis_switch(lo - 1e-9)["status_vs_fd"] == "PARTIAL"
    assert g3_basis_switch(hi)["status_vs_fd"] == "PASS"           # 上界含
    assert g3_basis_switch(hi + 1e-9)["status_vs_fd"] == "PARTIAL"
    clean = 1.5459354578508522
    r = g3_basis_switch(clean)
    assert r["status_vs_fd"] == "PARTIAL"
    assert r["rel_vs_fd"] == pytest.approx(0.024877, abs=2e-5)
    # 任务书口径数值复核：openEMS 1.5544（Q-RM-4）在带内
    assert g3_fd_band()[0] <= 1.5544 <= g3_fd_band()[1]


def _mk_synthetic(statuses: tuple[str, str, str, str, str]) -> dict:
    return {"verdict": "DISAGREE", "gates": {
        "G1": {"status": statuses[0], "observed_s21_mean_db": -0.1, "rel": None},
        "G2": {"status": statuses[1], "observed_s11_max_db": -20.0, "rel": None},
        "G3": {"status": statuses[2], "observed_eps_eff": 1.55, "rel": 0.03},
        "G4": {"status": statuses[3], "observed_z0_ohm": 49.0, "rel": 0.03},
        "G5": {"status": statuses[4], "passivity_max": 1.0,
               "s_over_unity_cnt": 1},
    }}


def test_three_state_table_structure_and_movement():
    """表结构+迁移分类钉：合成三态（状态迁移受控）→ 5 行、两步迁移、
    FAIL 驱动门清单、expected 吻合位逐行核对。"""
    before = _mk_synthetic(("FAIL", "PASS", "PARTIAL", "PASS", "PASS"))
    near = _mk_synthetic(("PASS", "PASS", "PARTIAL", "PASS", "FAIL"))
    reverify = _mk_synthetic(("PASS", "PASS", "PARTIAL", "FAIL", "FAIL"))
    exp = {"G1_status": "PASS", "G2_status": "PASS", "G3_status": "PARTIAL",
           "G4_status": "FAIL", "G5_status": "FAIL"}
    tbl = three_state_gate_table(before, near, reverify, exp)
    assert len(tbl["rows"]) == 5
    rows = {r["gate"]: r for r in tbl["rows"]}
    assert rows["G1"]["move_before_to_near"] == "improved"     # F→P
    assert rows["G1"]["move_near_to_reverify"] == "unchanged"
    assert rows["G4"]["move_before_to_near"] == "unchanged"    # P→P
    assert rows["G4"]["move_near_to_reverify"] == "degraded"   # P→F
    assert rows["G5"]["move_before_to_near"] == "degraded"     # P→F
    assert rows["G5"]["move_near_to_reverify"] == "unchanged"
    assert tbl["fail_gates_before"] == ["G1"]
    assert tbl["fail_gates_near_fix"] == ["G5"]
    assert tbl["fail_gates_reverify"] == ["G4", "G5"]
    assert tbl["verdict_reverify"] == "DISAGREE"
    for row in tbl["rows"]:
        assert row["reverify_matches_expected"] is True


def test_three_state_real_states_pinned():
    """三态真值钉（落树快照）：G1 FAIL→PASS→PASS；G2/G4 全 PASS；
    G3 全 PARTIAL；G5 PASS→FAIL→FAIL（306→190 状态未变计数降）；
    总 verdict 三态全 DISAGREE，驱动门 G1 → G5 → G5。"""
    tbl = three_state_gate_table(V_RM1, V_RM4, V_REVERIFY)
    rows = {r["gate"]: r for r in tbl["rows"]}
    g1, g3, g5 = rows["G1"], rows["G3"], rows["G5"]
    assert (g1["before"]["status"], g1["near_fix"]["status"],
            g1["reverify"]["status"]) == ("FAIL", "PASS", "PASS")
    assert g1["move_before_to_near"] == "improved"
    assert g1["move_near_to_reverify"] == "unchanged"
    assert g5["before"]["over_unity_cnt"] == 0
    assert g5["near_fix"]["over_unity_cnt"] == 306
    assert g5["reverify"]["over_unity_cnt"] == 180
    assert (g5["move_before_to_near"], g5["move_near_to_reverify"]) == (
        "degraded", "unchanged")
    assert (g3["before"]["status"], g3["near_fix"]["status"],
            g3["reverify"]["status"]) == ("PARTIAL", "PARTIAL", "PARTIAL")
    assert tbl["verdict_before"] == tbl["verdict_near_fix"] == \
        tbl["verdict_reverify"] == "DISAGREE"
    assert tbl["fail_gates_before"] == ["G1"]
    assert tbl["fail_gates_near_fix"] == tbl["fail_gates_reverify"] == ["G5"]


def test_g5_attribution_threshold_boundaries():
    """归因分支阈值边界钉（本席操作化常量）：≥0.50 大幅（含界）、≤0.10
    不变（含界）、其间中带；零基线守卫 NO_BASELINE。"""
    def mk(b: int, a: int) -> str:
        return g5_attribution_test(b, a, 1.01, 1.01)["classification"]

    assert mk(200, 100) == "SUBSTANTIAL_DROP"    # 0.50 含界
    assert mk(200, 101) == "MIXED_PARTIAL_DROP"  # 0.495
    assert mk(200, 120) == "MIXED_PARTIAL_DROP"  # 0.40
    assert mk(200, 180) == "NO_DROP"             # 0.10 含界
    assert mk(200, 181) == "NO_DROP"             # 0.095
    assert mk(200, 179) == "MIXED_PARTIAL_DROP"  # 0.105
    assert mk(0, 0) == "NO_BASELINE"
    assert G5_SUBSTANTIAL_DROP_RATIO == 0.50
    assert G5_NO_DROP_RATIO == 0.10


def test_g5_attribution_real_observed_mixed():
    """真值钉：306→180（drop 41.2%）落中带 MIXED；floor Δ=−0.00188 未动
    （≤0.5pp）→ 剩余面=Q-X25 50Ω 失配偏置；冻结门注记仍 FAIL。"""
    r = g5_attribution_test(306, 180, 1.0142031805205316, 1.0123252067043993)
    assert r["drop_ratio"] == (306 - 180) / 306      # 同式逐位（≈0.4118 中带）
    assert r["classification"] == "MIXED_PARTIAL_DROP"
    assert r["floor_delta"] == pytest.approx(-0.0018779738161323, abs=1e-12)
    assert r["floor_unchanged"] is True
    assert r["residual_face"] == "Q-X25_50ohm_mismatch_bias"
    assert "部分有效" in r["branch_text"]
    assert "失配偏置" in r["branch_text"]
    assert "仍 FAIL" in r["frozen_gate_note"]


def test_g5_attribution_branch_texts_and_asymmetry():
    """分支文本钉（两分支语义逐字关键词）+ 分变体非对称钉：重验实测
    shield 98→139（升 42%）、open 208→41（降 80.3%）→ 非对称 True；
    计数和一致性 139+41=190=verdict 总数。"""
    sub = g5_attribution_test(306, 100, 1.01, 1.01)
    assert sub["classification"] == "SUBSTANTIAL_DROP"
    assert "线端入网修复有效" in sub["branch_text"]
    assert "剩余面" in sub["branch_text"]
    nod = g5_attribution_test(306, 300, 1.01, 1.01)
    assert nod["classification"] == "NO_DROP"
    assert "无效或另有根因" in nod["branch_text"]
    r = g5_attribution_test(
        306, 180, 1.0142031805205316, 1.0123252067043993,
        per_variant_before=OU_RM4_VARIANTS,
        per_variant_after=OU_REVERIFY_VARIANTS)
    pv = r["per_variant"]
    assert pv is not None and pv["variant_asymmetric"] is True
    assert pv["drop_ratio"]["ssl_open"] == (208 - 41) / 208   # −80.3%
    assert pv["drop_ratio"]["ssl_shield"] < 0.0    # shield 反升 41 点
    assert (OU_REVERIFY_VARIANTS["ssl_shield"]
            + OU_REVERIFY_VARIANTS["ssl_open"]) == \
        V_REVERIFY["gates"]["G5"]["s_over_unity_cnt"] == 180


def test_g5_frozen_gate_unaffected_by_attribution():
    """冻结门不受归因分析影响钉：重验实测（passivity 1.01235、超一点 190、
    audit/plane_dist 双 true）经 gate_g5_health（Q-X9 冻结判读面原函数）
    仍 FAIL；passivity ≤1.05 子门独立为真（能量面未破 1.05 线）。"""
    g = gate_g5_health(1.0123252067043993, 180, True, True)
    assert g["status"] == "FAIL"
    assert g["passivity_max"] <= g["passivity_limit"] == PASSIVITY_MAX
    # 反例：仅当超一点归零才翻 PASS（冻结零容差语义）
    assert gate_g5_health(1.0123252067043993, 0, True, True)["status"] == "PASS"
    assert gate_g5_health(1.05 + 1e-9, 0, True, True)["status"] == "FAIL"


def test_passivity_floor_tolerance_semantics():
    """floor 容差语义钉：|Δ|≤0.005 视为未动（剩余面=失配偏置）；|Δ| 越界
    或 floor 实质性下移 → residual_face 进 reassess 分支（不强行归因）。"""
    same = g5_attribution_test(306, 190, 1.0142, 1.0124)
    assert same["floor_unchanged"] is True
    moved = g5_attribution_test(306, 190, 1.0142, 1.0070)
    assert moved["floor_unchanged"] is False
    assert moved["residual_face"] == "reassess_floor_and_components"
    cured = g5_attribution_test(306, 10, 1.0142, 1.0000)
    assert cured["classification"] == "SUBSTANTIAL_DROP"
    assert cured["residual_face"] == "reassess_floor_and_components"


def test_predeclared_expectation_check_real_state():
    """重验态对预声明期望的吻合核对钉：4 门状态+G5 冻结门态+FD 基准 G3 共
    6 项命中；G5 count 分支（预期 SUBSTANTIAL、实落 MIXED）与 verdict
    （预期 PARTIAL、实落 DISAGREE）两项如实 miss——不凑绿。"""
    chk = expectation_check(V_REVERIFY, "MIXED_PARTIAL_DROP", "PASS")
    assert chk["n_hits"] == 6      # G1 G2 G3 G4 G5_status + G3_fd_basis
    assert chk["n_misses"] == 2    # G5_count_branch + verdict
    assert any("G5_count_branch" in m for m in chk["misses"])
    assert any(m.startswith("verdict:") for m in chk["misses"])
    # FD 基准 G3=PASS 预期命中（重验 εeff 带内）
    assert any("G3_fd_basis_status" in h for h in chk["hits"])


def test_g3_frozen_gate_anchor_unchanged_declaration():
    """基准切换不触碰冻结门钉：g3_basis_switch 的 status_vs_closed 与
    Q-X9 冻结 G3 门（2%/5% 阈、闭式锚）对三态观测逐位一致——FD 基准仅
    并列旁证，不改变冻结判读面输出。"""
    for v in (V_RM1, V_RM4, V_REVERIFY):
        obs = v["gates"]["G3"]["observed_eps_eff"]
        frozen = gate_g3_eps_eff(obs)
        switched = g3_basis_switch(obs)
        assert frozen["status"] == switched["status_vs_closed"]
        assert math.isclose(frozen["rel"], switched["rel_vs_closed"],
                            rel_tol=1e-12)
        assert switched["closed_eps_eff"] == frozen["closed_eps_eff"]


def test_fd_z0_leg_side_note():
    """Z0 腿旁证钉（Q-X20 §3）：FD Z0=50.482 vs 闭式 50.251（−0.46%）、
    vs 重验 open ZL 48.833（−3.27%）——G4 冻结 10% 宽门下引擎 ZL 与 FD
    的分歧如实并列，不进判读（Q-X20 同口径）。"""
    rel_closed = (closed_form_anchor()["z0_ohm"] - FD_Z0_OHM) / FD_Z0_OHM
    assert rel_closed == pytest.approx(-0.0046, abs=2e-4)    # 闭式低 0.46%
    zl_reverify = V_REVERIFY["gates"]["G4"]["observed_z0_ohm"]
    rel_engine = (zl_reverify - FD_Z0_OHM) / FD_Z0_OHM
    assert rel_engine == pytest.approx(-0.0326, abs=5e-4)    # 引擎 ZL 低 3.26%
    assert rel_engine < rel_closed                           # 双负向、引擎更深
