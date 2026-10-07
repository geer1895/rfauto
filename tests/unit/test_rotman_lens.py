"""Rotman 透镜内核单测（研究扩充 round3 §二 F-F 表件 5）。

裁判口径（#118 双路径，不自证）：
- 路径 A = Rotman-Turner 1963 原文二次方程 (12)（n=1 时逐式核对原文系数，
  文献锚 = 原文附录数值表 α=30°、g=1.137，print 舍入域内回收）；
- 路径 B = 数值路径积分：焦点/轮廓点坐标直接 hypot 电路径（不经任何综合
  代数），三焦点逐口相位残差 <1e-9 周期（实测 ~4.4e-16，逐位级）；
- 路径 C = 二分法直接解轴上等光程方程（未消元的原方程）回收 w，
  与二次方程根互证（差 ~4e-16）。
- 指向恒等式：焦点馈电 → 拟合指向 = 0/±α（解析精确，实测 ~7e-15 deg，
  门 ±0.01°）；焦弧半径文献锚 0.597（原文附录 r=R/F）。

原文附录表 η=0.10 行 w=0.00012 为**原文自身 typo**（同表 y=0.09996 代入
原文式 (8) 强制 w=0.0004，同表 x=0.00483 亦只与 w≈0.00042 相容）——
本文件按式 (8) 自洽口径钉（详见内核 docstring 勘误节）。
全部确定性、无网络、无真机。
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import rotman_lens as rl
from rfauto.service import rotman_lens_service as rls

# 原文附录表（rotman63.pdf p.632；列：η, w, −x, y）
# η=0.10 行 w 值为原文 typo（见文件头），w 列该行不参与回收。
PAPER_TABLE = [
    (0.00, 0.00000, 0.00000, 0.00000),
    (0.05, 0.00011, 0.00121, 0.04999),
    (0.10, None, 0.00483, 0.09996),
    (0.15, 0.00091, 0.01084, 0.14986),
    (0.20, 0.00153, 0.01922, 0.19969),
    (0.25, 0.00217, 0.02993, 0.24946),
    (0.30, 0.00273, 0.04290, 0.29918),
    (0.35, 0.00301, 0.05803, 0.34895),
    (0.40, 0.00273, 0.07519, 0.39891),
    (0.45, 0.00147, 0.09416, 0.44934),
    (0.50, -0.00142, 0.11461, 0.50071),
    (0.55, -0.00701, 0.13600, 0.55385),
    (0.60, -0.01717, 0.15739, 0.61030),
    (0.65, -0.03543, 0.17699, 0.67303),
    (0.70, -0.06935, 0.19097, 0.74855),
    (0.75, -0.13861, 0.18940, 0.85395),
    (0.80, -0.3172, 0.1349, 1.054),  # 原文此行仅 4 位小数
]


# ─── 1. 文献锚：原文附录表回收（α=30°, g=1.137, n=1）─────────────────────────


def test_appendix_table_anchor():
    for eta, w_t, x_t, y_t in PAPER_TABLE:
        sol = rl.solve_port(eta, 30.0, g=1.137, n_refractive=1.0)
        if w_t is not None:
            w_tol = 6e-4 if eta == 0.80 else 3e-5
            assert sol["w"] == pytest.approx(w_t, abs=w_tol), f"w@eta={eta}"
        x_tol = 6e-4 if eta == 0.80 else 3e-5
        assert sol["x"] == pytest.approx(x_t, abs=x_tol), f"x@eta={eta}"
        y_tol = 6e-4 if eta == 0.80 else 3e-5
        assert sol["y"] == pytest.approx(y_t, abs=y_tol), f"y@eta={eta}"


def test_appendix_eta010_source_typo_registration():
    # 原文印 w=0.00012 与其自身矛盾：式 (8) y=η(1−w) 用同表 y=0.09996 强制 w=0.0004
    forced = 1.0 - 0.09996 / 0.10
    sol = rl.solve_port(0.10, 30.0, g=1.137, n_refractive=1.0)
    assert sol["w"] == pytest.approx(forced, abs=1e-4)  # 0.0004（式 (8) 强制值）
    assert sol["w"] == pytest.approx(0.00042, abs=5e-5)  # 平滑序列值
    # 同表 x/y 与本解逐位回收（该行其余列自洽）
    assert sol["x"] == pytest.approx(0.00483, abs=3e-5)
    assert sol["y"] == pytest.approx(0.09996, abs=3e-5)


# ─── 2. 等光程主判据（数值路径 B，与综合代数零共享）──────────────────────────


def test_equal_path_n1_paper_optimum():
    d = rl.design_rotman_lens(
        alpha_deg=30.0, n_ports=17, d_over_lambda=0.5, f_over_lambda=5.0,
        g=1.137, n_refractive=1.0,
    )
    v = rl.verify_equal_path(d)
    assert v["pass"] is True
    assert v["max_cycles"] < 1e-9  # 任务书门；实测 ~4.4e-16
    assert v["max_cycles"] < 1e-12  # 实测逐位级，收严钉
    for name, focus in v["per_focus"].items():
        assert len(focus["residuals_cycles"]) == 17, name
        assert focus["max_cycles"] < 1e-9, name


def test_equal_path_task_geometry_g1_with_refractive_fill():
    # 任务书字面几何（g=1：F0=(F,0), F1/F2=(F cosα, ±F sinα)）+ 介质填充板 n=1.35
    d = rl.design_rotman_lens(
        alpha_deg=25.0, n_ports=9, d_over_lambda=0.5, f_over_lambda=3.0,
        g=1.0, n_refractive=1.35,
    )
    v = rl.verify_equal_path(d)
    assert v["pass"] is True
    assert v["max_cycles"] < 1e-9
    s = rl.verify_beam_steering(d)
    assert s["pass"] is True
    assert s["max_identity_error_deg"] < 1e-9


# ─── 3. 中心口与镜像对称恒等式 ────────────────────────────────────────────────


def test_center_port_identity_exact():
    d = rl.design_rotman_lens(
        alpha_deg=30.0, n_ports=11, d_over_lambda=0.5, f_over_lambda=4.0, g=1.137
    )
    mid = d.n_ports // 2
    # 原文口径：w=(W−W₀)/F 在中心口恒等于 0（逐位）；W₀=F 钉下绝对线长 W/F=1
    assert d.w[mid] == 0.0
    assert d.x[mid] == 0.0
    assert d.y[mid] == 0.0
    assert d.eta[mid] == 0.0
    row = rl.design_table(10e9, 30.0, 4.0, 11, 0.5, g=1.137)["ports"][mid]
    assert row["w_excess"] == 0.0
    assert row["line_over_f"] == 1.0  # "中口线长=F"（W₀=F 口径）


def test_mirror_symmetry_bitwise():
    d = rl.design_rotman_lens(
        alpha_deg=30.0, n_ports=17, d_over_lambda=0.5, f_over_lambda=5.0, g=1.137
    )
    n = d.n_ports
    for i in range(n // 2):
        j = n - 1 - i
        assert d.x[i] == d.x[j], f"x even @pair({i},{j})"
        assert d.w[i] == d.w[j], f"w even @pair({i},{j})"
        assert d.y[i] == -d.y[j], f"y odd @pair({i},{j})"
        assert d.eta[i] == -d.eta[j]


# ─── 4. 波束指向面 ───────────────────────────────────────────────────────────


def test_steering_identity_foci():
    d = rl.design_rotman_lens(
        alpha_deg=30.0, n_ports=17, d_over_lambda=0.5, f_over_lambda=5.0, g=1.137
    )
    s = rl.verify_beam_steering(d, angle_band_deg=0.01)
    assert s["pass"] is True
    # 焦点馈电指向 = 0/±α 是解析恒等式，实测 ~7e-15 deg（远紧于 ±0.01° 门）
    assert s["max_identity_error_deg"] < 1e-9
    by_name = {f["feed"]: f for f in s["per_feed"]}
    assert by_name["f1_off_axis_plus"]["theta_deg"] == pytest.approx(30.0, abs=1e-9)
    assert by_name["f2_off_axis_minus"]["theta_deg"] == pytest.approx(-30.0, abs=1e-9)
    assert by_name["f0_on_axis"]["theta_deg"] == pytest.approx(0.0, abs=1e-12)


def test_steering_interpolated_arc_feed():
    d = rl.design_rotman_lens(
        alpha_deg=30.0, n_ports=17, d_over_lambda=0.5, f_over_lambda=5.0, g=1.137
    )
    # β=±α/2 焦弧插值馈电：非完美焦点（透镜像差），实测指向偏差 ~0.09°
    s = rl.verify_beam_steering(d)
    for it in s["interpolated"]:
        assert abs(it["error_deg"]) < 1.0  # 预声明软带（像差限制，非恒等式）
        assert 0.0 < it["fit_residual_rad"] < 1.0  # 残差如实非零、有限
    # β=±α 端点必须精确落焦点（参数化恒等式）
    fx, fy = rl.focal_arc_feed(30.0, 30.0, 1.137)
    a0, b0 = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    assert fx == pytest.approx(a0, rel=1e-12)
    assert fy == pytest.approx(b0, rel=1e-12)
    fx0, fy0 = rl.focal_arc_feed(0.0, 30.0, 1.137)
    assert fx0 == pytest.approx(1.137, rel=1e-12)  # β=0 → 精确落轴上焦点 G
    assert fy0 == 0.0


# ─── 5. 设计助手锚 ───────────────────────────────────────────────────────────


def test_focal_arc_radius_anchor_and_circumcircle():
    r = rl.focal_arc_radius(30.0, 1.137)
    assert r == pytest.approx(0.597, abs=5e-4)  # 原文附录：r = R/F = 0.597
    # 外接圆过三焦点（圆心在轴上 cx=(g²−1)/(2(g−a₀))）
    a0, b0 = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    g = 1.137
    cx = (g * g - 1.0) / (2.0 * (g - a0))
    for fxyz in ((g, 0.0), (a0, b0), (a0, -b0)):
        dist = math.hypot(fxyz[0] - cx, fxyz[1])
        assert dist == pytest.approx(r, rel=1e-12)


def test_optimum_focal_ratio_eq13():
    # 原文式 (13)：g = 1 + α²/2（α 弧度）
    for deg in (10.0, 25.0, 30.0, 45.0):
        expect = 1.0 + math.radians(deg) ** 2 / 2.0
        assert rl.optimum_focal_ratio(deg) == pytest.approx(expect, rel=1e-12)
    # 原文全文口径：α=30° → 1.137
    assert rl.optimum_focal_ratio(30.0) == pytest.approx(1.137, abs=5e-4)


# ─── 6. 设计参数面：单位换算与 JSON ──────────────────────────────────────────


def test_design_table_units_mm_lambda():
    t = rl.design_table(
        f0_hz=10e9, alpha_deg=30.0, f_over_lambda=3.0, n_ports=7,
        d_over_lambda=0.5, g=1.137, n_refractive=1.0,
    )
    assert t["lambda_mm"] == pytest.approx(29.9792458, rel=1e-12)
    assert t["f_mm"] == pytest.approx(3.0 * t["lambda_mm"], rel=1e-12)
    assert t["n_ports"] == 7 and t["eta_max"] == pytest.approx(0.5, abs=1e-12)
    assert t["in_paper_table_flag"] is True
    rows = t["ports"]
    # 直线轮廓口等间距 d/λ=0.5，关于 0 对称
    n_mm = [r["n_mm"] for r in rows]
    step = 0.5 * t["lambda_mm"]
    for a, b in itertools.pairwise(n_mm):
        assert b - a == pytest.approx(step, rel=1e-12)
    assert n_mm[3] == 0.0
    # 毫米/λ 双出自洽：x_mm = x_over_lambda·λ_mm；line_mm = line_over_f·F_mm
    for r in rows:
        assert r["x_mm"] == pytest.approx(r["x_over_lambda"] * t["lambda_mm"], rel=1e-12)
        assert r["y_mm"] == pytest.approx(r["y_over_lambda"] * t["lambda_mm"], rel=1e-12)
        assert r["line_mm"] == pytest.approx(r["line_over_f"] * t["f_mm"], rel=1e-12)
        assert r["line_over_lambda"] == pytest.approx(
            r["line_over_f"] * t["f_over_lambda"], rel=1e-12
        )
    # 验证摘要进表且通过
    assert t["equal_path"]["pass"] is True
    assert t["beam_steering"]["pass"] is True


def test_design_table_json_serializable():
    t = rl.design_table(
        f0_hz=10e9, alpha_deg=30.0, f_over_lambda=3.0, n_ports=7,
        d_over_lambda=0.5, g=1.137,
    )
    assert isinstance(json.dumps(t), str)  # 全量可序列化（无 tuple/ndarray 泄漏）


def test_eta_grid_properties():
    d = rl.design_rotman_lens(
        alpha_deg=30.0, n_ports=9, d_over_lambda=0.5, f_over_lambda=3.0, g=1.0
    )
    step = 0.5 / 3.0
    for j, eta in enumerate(d.eta):
        assert eta == pytest.approx((j - 4.0) * step, rel=1e-15)
    assert d.eta_max == pytest.approx(4.0 * step, rel=1e-15)
    assert d.n_ports == 9


def test_design_to_dict_json():
    d = rl.design_rotman_lens(
        alpha_deg=30.0, n_ports=7, d_over_lambda=0.5, f_over_lambda=4.0,
        g=1.137, n_refractive=1.2,
    )
    dd = d.to_dict()
    for key in ("alpha_deg", "g", "n_refractive", "f_over_lambda", "d_over_lambda",
                "n_ports", "eta_max", "eta", "x", "y", "w"):
        assert key in dd
    assert isinstance(json.dumps(dd), str)
    assert json.loads(json.dumps(dd))["n_ports"] == 7


# ─── 7. n=1 系数逐式退化到原文 (12) ──────────────────────────────────────────


def test_n1_coeffs_reduce_to_paper():
    """n=1 二次式与原文可读形态的逐式锚（见内核 docstring 式 (12) 登记节）。"""
    a0, b0 = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    g = 1.137
    m = (g - 1.0) / (g - a0)
    scale = -4.0 * (g - a0) ** 2
    for eta in (0.0, 0.1, 0.3, 0.55, 0.8):
        # a 系数：扫描可读形态逐式钉（比例 −4(g−a₀)²）
        a_paper = 1.0 - eta * eta - m * m
        expected_a = scale * a_paper
        coef_a, coef_b, coef_c = rl._port_quadratic_coeffs(eta, a0, b0, g, 1.0)
        assert coef_a == pytest.approx(expected_a, rel=1e-12, abs=1e-15)
        # b/c：扫描件指数不可靠判读，不按转写钉；改钉"两根回代原文式 (8)(9)(11)"
        disc = coef_b * coef_b - 4.0 * coef_a * coef_c
        assert disc >= 0.0
        sq = math.sqrt(disc)
        for w in ((-coef_b + sq) / (2.0 * coef_a), (-coef_b - sq) / (2.0 * coef_a)):
            y = eta * (1.0 - w)  # 式 (8)
            x_paper = -(b0 * b0 * eta * eta + 2.0 * w * (g - 1.0)) / (2.0 * (g - a0))
            eq9 = x_paper**2 + y**2 + 2.0 * a0 * x_paper - (w * w + b0 * b0 * eta * eta - 2.0 * w)
            eq11 = x_paper**2 + y**2 + 2.0 * g * x_paper - (w * w - 2.0 * g * w)
            assert abs(eq9) < 1e-10, f"(9) @eta={eta}, w={w}"
            assert abs(eq11) < 1e-10, f"(11) @eta={eta}, w={w}"


# ─── 8. 双路径 C：二分法直接解未消元方程回收 w（#118）────────────────────────


def _bisect_w(eta: float, alpha_deg: float, g: float, n: float) -> float:
    """轴上等光程方程 n·|GP|+W = n·G+W₀ 的直接数值解（沿 y(w), x(w) 流形）。"""
    a0 = math.cos(math.radians(alpha_deg))
    b0 = math.sin(math.radians(alpha_deg))

    def x_impl(w):
        return (b0 * b0 * eta * eta / (n * n) + 2.0 * w * (g - 1.0) / n) / (2.0 * (g - a0))

    def y(w):
        return eta * (n - w) / (n * n)

    def f(w):
        return n * math.hypot(g - x_impl(w), y(w)) + 1.0 + w - (n * g + 1.0)

    lo, hi = -2.0, 2.0
    assert f(lo) * f(hi) <= 0.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(lo) * f(mid) <= 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def test_dual_path_bisection_w_recovers_quadratic_root():
    for alpha_deg, g, n, eta in ((30.0, 1.137, 1.0, 0.3), (30.0, 1.137, 1.0, 0.55),
                                 (25.0, 1.1, 1.5, 0.4), (45.0, 1.0, 1.0, 0.2)):
        sol = rl.solve_port(eta, alpha_deg, g=g, n_refractive=n)
        w_bis = _bisect_w(eta, alpha_deg, g, n)
        assert sol["w"] == pytest.approx(w_bis, abs=1e-10), (alpha_deg, g, n, eta)
        # 二分 w 的离轴残差同样归零（三路径一致）
        a0 = math.cos(math.radians(alpha_deg))
        b0 = math.sin(math.radians(alpha_deg))
        x = (b0 * b0 * eta * eta / (n * n) + 2.0 * w_bis * (g - 1.0) / n) / (2.0 * (g - a0))
        y = eta * (n - w_bis) / (n * n)
        path = n * math.hypot(a0 - x, b0 - y) + 1.0 + w_bis + eta * b0
        assert abs(path - (n + 1.0)) < 1e-9


# ─── 9. 输入守卫与显式错误 ───────────────────────────────────────────────────


def test_input_guards():
    ok = dict(alpha_deg=30.0, n_ports=7, d_over_lambda=0.5, f_over_lambda=3.0)
    # α 开区间 (0, 90)
    for bad_alpha in (0.0, 90.0, -5.0, 95.0, float("nan"), True):
        with pytest.raises(ValueError):
            rl.design_rotman_lens(alpha_deg=bad_alpha, n_ports=7,
                                  d_over_lambda=0.5, f_over_lambda=3.0)
    # N<3 / 非整数 / bool
    for bad_n in (2, 0, -1, 2.5, True):
        with pytest.raises(ValueError):
            rl.design_rotman_lens(n_ports=bad_n, **{k: v for k, v in ok.items() if k != "n_ports"})
    # d/λ 与 F/λ
    for key in ("d_over_lambda", "f_over_lambda"):
        for bad in (0.0, -1.0, float("inf")):
            with pytest.raises(ValueError):
                rl.design_rotman_lens(**{**ok, key: bad})
    # g：正数且 ≠ cos α
    for bad_g in (0.0, -0.5, float("inf")):
        with pytest.raises(ValueError):
            rl.design_rotman_lens(**ok, g=bad_g)
    with pytest.raises(ValueError):
        rl.design_rotman_lens(**ok, g=math.cos(math.radians(30.0)))
    # n 折射率
    for bad_n_r in (0.0, -1.0):
        with pytest.raises(ValueError):
            rl.design_rotman_lens(**ok, n_refractive=bad_n_r)
    # f0
    for bad_f0 in (0.0, -1e9):
        with pytest.raises(ValueError):
            rl.design_table(f0_hz=bad_f0, alpha_deg=30.0, f_over_lambda=3.0,
                            n_ports=7, d_over_lambda=0.5)
    # solve_port η 非有限
    with pytest.raises(ValueError):
        rl.solve_port(float("nan"), 30.0)


def test_no_real_root_explicit_error():
    # g=1.0、α=30° 的无实根区：|η|≳1.17 → 判别式 <0，显式 ValueError 不静默
    with pytest.raises(ValueError, match="无实根"):
        rl.solve_port(1.5, 30.0, g=1.0)
    with pytest.raises(ValueError, match="无实根"):
        rl.solve_port(1.2, 30.0, g=1.0)
    # 退化（二次/一次项同零）：g=1、α=30°、η=1.0（a=1−η²−m²=0 且 b=2η²−2g=0）
    with pytest.raises(ValueError, match="退化"):
        rl.solve_port(1.0, 30.0, g=1.0)
    # 整镜综合路径同样显式失败（core 抛出，仅 service 层转信封）
    with pytest.raises(ValueError):
        rl.design_rotman_lens(alpha_deg=30.0, n_ports=9, d_over_lambda=1.0,
                              f_over_lambda=1.0, g=1.0)


# ─── 10. service 薄壳信封 ────────────────────────────────────────────────────


def test_service_design_and_payload_envelopes():
    out = rls.rotman_lens_design(
        alpha_deg=30.0, n_ports=9, d_over_lambda=0.5, f_over_lambda=3.0, g=1.137
    )
    assert out["ok"] is True
    assert out["data"]["equal_path"]["pass"] is True
    assert out["data"]["beam_steering"]["pass"] is True
    assert out["data"]["design"]["n_ports"] == 9
    assert isinstance(json.dumps(out), str)

    payload = rls.rotman_lens_payload(
        f0_hz=10e9, alpha_deg=30.0, f_over_lambda=3.0, n_ports=7,
        d_over_lambda=0.5, g=1.137,
    )
    assert payload["ok"] is True
    assert payload["data"]["table"]["n_ports"] == 7
    assert isinstance(json.dumps(payload), str)


def test_service_error_envelope_no_raise():
    # 非法输入 → ok=False + error 字符串，绝不抛出
    out = rls.rotman_lens_design(alpha_deg=30.0, n_ports=2,
                                 d_over_lambda=0.5, f_over_lambda=3.0)
    assert out["ok"] is False
    assert isinstance(out["error"], str) and out["error"]
    payload = rls.rotman_lens_payload(f0_hz=10e9, alpha_deg=95.0, f_over_lambda=3.0,
                                      n_ports=7, d_over_lambda=0.5)
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
