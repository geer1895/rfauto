"""数据工厂 M3 谷区加密采集单测（合成数据钉死，零真机零长跑零仓库 IO）。

被测对象：scripts/factory_m3_valley.py 的纯逻辑
（core_grid_points / nudge_free / build_valley_plan / judge_batch /
core_min_spacing_um）与采集链复用契约（factory_m1_collect re-export 面）。
真跑面不在单测范围——真机批量按判据文件独立执行
（共享锁 + #261 互斥 + 首点探针）。

数值口径（#118 合成注入→回收）：查重/重采样用合成指纹集验证确定性回收；
判据门用构造输入逐门验证（#364④ 数值判缺 is not None 语义随行钉）。
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import factory_m1_collect as m1
import factory_m3_valley as fv
from factory_m3_valley import (
    build_valley_plan,
    core_grid_points,
    core_min_spacing_um,
    judge_batch,
    nudge_free,
    w_fingerprint,
)

# ─── 谷芯均匀网格 ─────────────────────────────────────────────────────────────

def test_core_grid_endpoints_and_step():
    grid = core_grid_points()
    assert len(grid) == 10
    assert grid[0] == pytest.approx(0.900, abs=1e-12)
    assert grid[-1] == pytest.approx(0.920, abs=1e-12)
    steps = [b - a for a, b in itertools.pairwise(grid)]
    assert all(abs(s - (0.920 - 0.900) / 9) < 1e-12 for s in steps)
    assert abs(steps[0] * 1000 - 2.2222) < 1e-3  # 步距 ~2.2µm（criteria）


# ─── 撞点重采样（nudge_free） ─────────────────────────────────────────────────

def test_nudge_free_returns_free_fingerprint_monotonic():
    w = 0.9044444
    taken = {w_fingerprint(w)}
    w2, n = nudge_free(w, taken)
    assert n >= 1
    assert w2 > w  # 单调 +10nm 步进（不破坏 ~2.2µm 步距语义）
    assert w_fingerprint(w2) not in taken
    assert w_fingerprint(w2) != w_fingerprint(w)


def test_nudge_free_second_call_takes_next_slot():
    w = 0.9111111
    taken = {w_fingerprint(w)}
    w2, _ = nudge_free(w, taken)
    taken.add(w_fingerprint(w2))
    w3, _ = nudge_free(w, taken)
    assert w3 > w2
    assert w_fingerprint(w3) not in taken


def test_nudge_free_rejects_when_exhausted():
    # 邻域 100nm 全占（指纹 900000..900099 = w 0.900000..0.900099 的 nm 网格）
    with pytest.raises(ValueError):
        nudge_free(0.900, set(range(900_000, 900_100)), max_iter=5)


# ─── 采样计划（查重/重采样/恰 30 点语义） ─────────────────────────────────────

def test_plan_clean_dedup_exact_30_points():
    plan = build_valley_plan([0.5, 1.113, 2.0])  # 与谷区不相交的合成库存
    pts = plan["points"]
    assert plan["stats"]["n_plan_total"] == 30
    assert len(pts) == 30
    core = [p for p in pts if p["kind"] == "core"]
    lhs = [p for p in pts if p["kind"] == "lhs"]
    assert len(core) == 10 and len(lhs) == 20
    assert all(0.900 <= p["w_mm"] <= 0.920 for p in core)
    assert all(0.70 <= p["w_mm"] <= 1.00 for p in lhs)
    ids = [p["point_id"] for p in pts]
    assert len(set(ids)) == 30
    assert all(p["line_len_mm"] == 40.0 for p in pts)


def test_plan_dedup_no_fingerprint_overlap_with_inventory():
    plan = build_valley_plan([0.5, 1.113, 2.0])
    inv = {w_fingerprint(w) for w in [0.5, 1.113, 2.0]}
    seen = set()
    for p in plan["points"]:
        fp = w_fingerprint(p["w_mm"])
        assert fp not in inv  # 查重面零交集
        assert fp not in seen  # 批内唯一（#322 折叠语义）
        seen.add(fp)


def test_plan_core_collision_nudged_and_still_uniform():
    # 库存含谷芯第 3 点精确指纹（1nm 口径撞点）→ nudge 重采样保 10 点
    collision = core_grid_points()[2]
    plan = build_valley_plan([collision])
    assert plan["stats"]["n_core_nudged"] == 1
    core_w = sorted(p["w_mm"] for p in plan["points"] if p["kind"] == "core")
    assert len(core_w) == 10
    assert all(w_fingerprint(w) != w_fingerprint(collision) for w in core_w)
    gaps = [b - a for a, b in itertools.pairwise(core_w)]
    assert min(gaps) * 1000 > 2.0  # 重采样后最小间距仍 ~µm 级（非塌缩）
    assert max(gaps) * 1000 < 2.5


def test_plan_core_collision_matches_m1_valley_point_semantics():
    # M1 库存真实深谷点 w=0.910346（1nm 指纹）不撞本计划谷芯网格点
    m1_valley = 0.910346
    plan = build_valley_plan([m1_valley])
    core_w = [p["w_mm"] for p in plan["points"] if p["kind"] == "core"]
    assert all(w_fingerprint(w) != w_fingerprint(m1_valley) for w in core_w)
    assert plan["stats"]["n_core_nudged"] == 0


def test_plan_lhs_resample_survives_dense_inventory():
    # LHS 域 [0.70,1.00] 被 1nm 指纹网格占满、仅 (0.880,0.920) 窗空闲
    # → 池重采样后 20 点如实全部落入空闲窗（不静默凑数、不崩溃）
    inv = ([0.70 + i * 1e-6 for i in range(180_000)]        # 0.700..0.879999
           + [0.92 + i * 1e-6 for i in range(1, 80_001)])   # 0.920001..0.999999
    inv_fps = {w_fingerprint(w) for w in inv}
    plan = build_valley_plan(inv)
    assert plan["stats"]["n_plan_total"] == (
        10 + plan["stats"]["n_lhs_kept"])
    lhs_w = [p["w_mm"] for p in plan["points"] if p["kind"] == "lhs"]
    assert all(0.880 <= w <= 0.920 for w in lhs_w)
    assert all(w_fingerprint(w) not in inv_fps for w in lhs_w)


def test_plan_core_nudge_exhaustion_raises_honest():
    # 谷芯窗局部被 1nm 网格占满（[0.900,0.910] 全占）→ nudge 10µm 内无空闲
    # → build_valley_plan 显式 ValueError（计划拒绝生成，不静默出坏计划）
    inv = [0.900 + i * 1e-6 for i in range(10_001)]  # 0.900..0.910
    with pytest.raises(ValueError):
        build_valley_plan(inv)


def test_plan_lhs_points_within_declared_domain():
    plan = build_valley_plan([])
    lhs = [p["w_mm"] for p in plan["points"] if p["kind"] == "lhs"]
    assert len(lhs) == 20
    assert all(0.70 <= w <= 1.00 for w in lhs)


# ─── 批内三门（judge_batch） ──────────────────────────────────────────────────

def test_judge_batch_pass():
    res = judge_batch(30, 30, [80.0, 90.0, 85.0])
    assert res["pass"] is True
    assert res["verdict"] == "PASS"
    assert all(g["pass"] for g in res["gates"].values())


def test_judge_batch_median_gate_boundary():
    assert judge_batch(30, 30, [90.0, 90.0])["pass"] is True  # ≤90s 含等号
    res = judge_batch(30, 30, [90.1, 90.2])
    assert res["gates"]["G2_median_wall_le_90s"]["pass"] is False
    assert res["pass"] is False


def test_judge_batch_row_rate_and_scale_fail():
    res = judge_batch(30, 29, [80.0])
    assert res["gates"]["G1_row_rate_100pct"]["pass"] is False
    assert res["gates"]["G3_rows_eq_30"]["pass"] is False
    empty = judge_batch(0, 0, [])
    assert empty["pass"] is False  # 零 attempted 不凑绿
    assert empty["gates"]["G2_median_wall_le_90s"]["median_wall_s"] is None


def test_judge_batch_no_falsy_trap_on_zero_wall():
    # #364④：数值可 0 的面禁 or 缺省——wall=0.0 合法值须如实进中位统计
    res = judge_batch(30, 30, [0.0, 0.0, 0.0])
    assert res["gates"]["G2_median_wall_le_90s"]["pass"] is True
    assert res["gates"]["G2_median_wall_le_90s"]["median_wall_s"] == 0.0


# ─── 快检量（core_min_spacing_um） ────────────────────────────────────────────

def test_core_min_spacing_um_filters_and_measures():
    ws = [0.900, 0.9111111, 0.9088889, 0.5, 1.5]  # 非谷芯点不参与
    assert core_min_spacing_um(ws) == pytest.approx(2.2222, abs=1e-3)


def test_core_min_spacing_um_insufficient_points():
    assert core_min_spacing_um([0.9]) is None
    assert core_min_spacing_um([]) is None


# ─── 采集链复用契约（只 import 不改源；provenance 覆盖面） ────────────────────

def test_reexport_contract_with_m1_collect():
    # 复用面逐个可从本模块导入（import 面钉死，防改名漂移）
    from factory_m3_valley import (  # noqa: F401
        beta_metrics_from_port_beta,
        compute_point_metrics,
        existing_mline_w,
        write_run_products,
    )
    assert fv.w_fingerprint is m1.w_fingerprint  # 同源指纹函数


def test_study_override_target_is_module_attribute():
    # provenance 覆盖机制：write_run_products 运行时读 m1.STUDY——
    # 本脚本采集前 m1.STUDY = fv.STUDY（criteria 落盘节），此处钉机制前提
    assert fv.STUDY == "datafactory_m3"
    assert m1.STUDY == "datafactory_m1"  # 导入默认不被污染
    m1.STUDY = fv.STUDY
    try:
        assert m1.STUDY == "datafactory_m3"
    finally:
        m1.STUDY = "datafactory_m1"  # 还原（测试进程内不串味）


def test_lock_path_is_shared_protocol():
    # 共享锁路径=与并行 M4 任务互斥协议（criteria 互斥节），钉路径与原子语义常量
    assert fv.LOCK_PATH == REPO / "runs" / ".oe_collect.lock"
    assert fv.LOCK_POLL_S == 60.0


def test_beta_metrics_from_port_beta_synthetic_recovery(tmp_path):
    # #118 合成注入→回收：已知 β/ZL 的 port_beta.csv 经复用内核精确回收
    import csv
    import math

    beta = 2.0 * math.pi * 2.5e9 * (3.0 ** 0.5) / 299792458.0  # εeff=3 的 β
    rows = []
    for f_ghz in (2.4, 2.5, 2.6):
        rows.append({"freq_hz": f_ghz * 1e9,
                     "beta_rad_per_m": beta,
                     "re_zl1_ohm": 50.0,
                     "re_zl2_ohm": 50.25})
    p = tmp_path / "port_beta.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    got = fv.beta_metrics_from_port_beta(p)
    assert got is not None
    assert got["eps_eff_beta_mean_in_band"] == pytest.approx(3.0, rel=1e-9)
    assert got["zl1_re_ohm_med_in_band"] == pytest.approx(50.0)
    assert got["zl2_re_ohm_med_in_band"] == pytest.approx(50.25)


def test_quota_and_budget_constants_match_criteria():
    # criteria 运行口径常量（改门先改 criteria 再改这里）
    assert fv.QUOTA_TRIALS == 30
    assert fv.QUOTA_WALL_H == 1.0
    assert fv.SOLVE_TIMEOUT_S == 900.0
    assert fv.BUDGET_WALL_S == 45.0 * 60.0
    assert fv.PARTIAL_FACTOR == 1.5
    assert fv.MEDIAN_WALL_GATE_S == 90.0
    assert fv.N_ROWS_TARGET == 30
    assert fv.DATASET_NAME == "datafactory_m3_valley_20260920"
    assert fv.M1_DATASET == "datafactory_m1_mline_20260919"
    assert (fv.V_LOW, fv.V_HIGH) == (0.70, 1.00)
    assert (fv.CORE_LO, fv.CORE_HI) == (0.900, 0.920)
