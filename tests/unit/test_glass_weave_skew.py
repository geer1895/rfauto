"""HS-1 玻纤编织 skew 内核+service 单测（研究扩充 round4 中件包一 HS-1）。

裁判口径（#118/#122 先行）：全部解析常量由测试侧独立代数路径离线推导
（手算常数+同式异构重排），不消费被测实现的表达式；双路径=Δt 直代闭式
L(√εh−√εl)/c vs 内核先算两路径时延再相减。IEEE-754 下两种重排一般在
1-ulp 内不同——逐位断言只放在数学上被 FP 精确保证的恒等式上（等 εr
差恒 0、减法反对称、×2/×0.25 幂标度、退化混合分支、θ=90°），一般情形
用 rel=1e-12 容差（文件头如实登记，不冒充逐位）。

WEAVE_STYLES 参数值出处：PyAEDT main 分支 weave.py（MIT，2026-09-27
逐值抓取核对，见内核 docstring）——表值测试钉的就是源码实测值。
"""

from __future__ import annotations

import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import glass_weave_skew as gws
from rfauto.service import glass_weave_skew_service as svc

# ─── 测试侧独立常量（手算/离线推导，非被测实现产物）─────────────────────────
C0 = 299792458.0
# Δt 手算锚：L=0.25 m、εh=6、εl=3.5 → 0.25·(√6−√3.5)/c ×1e12 ≈ 482.5514 ps
SKEW_ANCHOR_PS = 482.5514
# zigzag θ=5°、pitch=0.4mm → 0.4/sin5° ≈ 4.58949 mm
PEFF_5DEG_1080 = 4.58949
# 25.78125 Gb/s = 825/32 Gb/s（精确有理数）→ UI(NS=2) = 32000/825 ps
RATE_25G = 825.0 / 32.0
UI_25G_PS = 1000.0 * 32.0 / 825.0


# ─── 1. WEAVE_STYLES 参数表：源码实测值钉 ────────────────────────────────────


def test_weave_styles_table_matches_source():
    # 逐值=pyaedt main weave.py WEAVE_STYLES（MIT，2026-09-27 抓取核对）
    assert gws.WEAVE_STYLES["1067"] == dict(
        pitch_x_mm=0.28, pitch_y_mm=0.28, warp_width_mm=0.13, fill_width_mm=0.13,
        amplitude_mm=0.025, er_glass=6.0, tan_delta_glass=0.004,
        ratio_warp=0.077, ratio_fill=0.077,
    )
    assert gws.WEAVE_STYLES["1080"]["pitch_x_mm"] == 0.40
    assert gws.WEAVE_STYLES["2116"]["pitch_y_mm"] == 0.50
    assert gws.WEAVE_STYLES["7628"]["warp_width_mm"] == 0.35
    assert gws.WEAVE_STYLES["7628"]["fill_width_mm"] == 0.28
    # 四样式 εr/tanδ 同源同值（源码实测 6.0/0.004）
    for row in gws.WEAVE_STYLES.values():
        assert row["er_glass"] == 6.0
        assert row["tan_delta_glass"] == 0.004
    assert set(gws.WEAVE_STYLES) == {"1067", "1080", "2116", "7628"}


def test_weave_style_spec_to_dict_and_unknown():
    spec = gws.weave_style_spec("7628")
    d = spec.to_dict()
    assert d["style"] == "7628"
    assert d["pitch_x_mm"] == 0.80 and d["warp_width_mm"] == 0.35
    assert json.loads(json.dumps(d)) == d  # JSON 可序列化往返
    with pytest.raises(ValueError, match="未知 weave style"):
        gws.weave_style_spec("5768")
    with pytest.raises(ValueError):
        gws.weave_style_spec(1080)  # 非 str 显式拒绝


def test_direction_geometry_x_vs_y():
    # x 向跨越 fill 纱（pitch_x, fill_width）；y 向跨越 warp 纱
    gx = gws.direction_geometry("7628", "x")
    gy = gws.direction_geometry("7628", "y")
    assert gx["pitch_mm"] == 0.80 and gx["yarn_width_mm"] == 0.28
    assert gy["pitch_mm"] == 0.80 and gy["yarn_width_mm"] == 0.35
    spec = gws.weave_style_spec("1080")
    assert gws.direction_geometry(spec, "x")["yarn_width_mm"] == 0.18
    with pytest.raises(ValueError, match="direction"):
        gws.direction_geometry("1080", "z")


# ─── 2. 均匀化：退化边界逐位 + 单调有界 ──────────────────────────────────────


def test_series_mixture_degenerate_bounds_bitwise():
    # f=0 → 全树脂、f=1 → 全玻璃：物理恒等式退化分支逐位（判据先行 #122）
    assert gws.series_mixture_er(6.0, 3.5, 0.0) == 3.5
    assert gws.series_mixture_er(6.0, 3.5, 1.0) == 6.0
    # 一般路径在极限附近与退化值一致（rel 1e-9，浮点 1/(1/x) 往返的 1-ulp 差）
    assert gws.series_mixture_er(6.0, 3.5, 1e-16) == pytest.approx(3.5, rel=1e-9)
    assert gws.series_mixture_er(6.0, 3.5, 1.0 - 1e-16) == pytest.approx(6.0, rel=1e-9)


def test_series_mixture_monotone_bounded():
    eg, er = 6.0, 3.5
    prev = er
    for k in range(1, 21):
        f = k / 20.0
        val = gws.series_mixture_er(eg, er, f)
        assert er <= val <= eg  # 有界（混合介于两组分之间）
        assert val >= prev  # εg>εr 时对 f 单调不减
        prev = val
    assert gws.series_mixture_er(eg, er, 0.5) == pytest.approx(1.0 / (0.5 / 6.0 + 0.5 / 3.5), rel=1e-15)


def test_homogenize_bounds_identities():
    # 窄走线理想化：f_lo=0 → 下界==树脂 εr 逐位；er_lower==er_in_resin
    b_narrow = gws.homogenize_er_bounds(0.4, 0.18, 6.0, 3.5)
    assert b_narrow["f_lo"] == 0.0
    assert b_narrow["er_lower"] == 3.5
    assert b_narrow["er_in_resin"] == 3.5
    assert b_narrow["f_hi"] == pytest.approx(0.18 / 0.4, rel=1e-15)
    # 走线宽 ≥ pitch：f_hi=1 → 上界==玻璃 εg 逐位
    b_wide = gws.homogenize_er_bounds(0.4, 0.18, 6.0, 3.5, trace_width_mm=0.5)
    assert b_wide["f_hi"] == 1.0
    assert b_wide["er_upper"] == 6.0
    assert b_wide["er_on_yarn"] == 6.0
    # 中间态严格介于两界之间（网格断言）
    b_mid = gws.homogenize_er_bounds(0.4, 0.18, 6.0, 3.5, trace_width_mm=0.3)
    assert b_mid["er_lower"] < b_mid["er_upper"]
    assert b_mid["er_lower"] >= 3.5 and b_mid["er_upper"] <= 6.0


def test_homogenize_resin_pocket_trace_width():
    # 1080：pitch 0.4、纱 0.18 → 树脂槽 0.22；w≤槽宽 → f_lo=0；w>槽宽 → 0<f_lo<f_hi
    b_small = gws.homogenize_er_bounds(0.4, 0.18, 6.0, 3.5, trace_width_mm=0.2)
    assert b_small["f_lo"] == 0.0
    b_large = gws.homogenize_er_bounds(0.4, 0.18, 6.0, 3.5, trace_width_mm=0.3)
    assert 0.0 < b_large["f_lo"] < b_large["f_hi"] <= 1.0
    # f_lo = (0.3−0.22)/0.3（测试侧独立重排，rel 1e-12）
    assert b_large["f_lo"] == pytest.approx((0.3 - 0.22) / 0.3, rel=1e-12)


# ─── 3. Δt 闭式：双路径 + 对称性 + 手算锚 ────────────────────────────────────


def test_path_delay_recycle():
    # T = L√ε/c 手算回收：L=1m、ε=4 → 2/c s
    assert gws.path_delay_s(1.0, 4.0) == pytest.approx(2.0 / C0, rel=1e-15)
    # ε=1 → T = L/c 逐位（sqrt(1)=1 精确）
    assert gws.path_delay_s(0.25, 1.0) == 0.25 / C0


def test_weave_skew_zero_when_equal_er_bitwise():
    # ε_hi == ε_lo → skew 恒 0（判据：逐位）
    out = gws.weave_skew_ps(0.25, 4.3, 4.3)
    assert out["skew_ps"] == 0.0
    assert out["delay_hi_ps"] == out["delay_lo_ps"]


def test_weave_skew_double_path_and_antisymmetry():
    eh, el, lm = 4.3077, 3.5, 0.25
    out = gws.weave_skew_ps(lm, eh, el)
    # 双路径裁判：内核（先各算 T 再相减）vs 测试侧直代闭式 L(√εh−√εl)/c
    direct_ps = lm * (math.sqrt(eh) - math.sqrt(el)) / C0 * 1e12
    assert out["skew_ps"] == pytest.approx(direct_ps, rel=1e-12)
    # 反对称（上下界交换 → 变号绝对值逐位不变；IEEE 减法反对称保证）
    out_rev = gws.weave_skew_ps(lm, el, eh)
    assert out_rev["skew_ps"] == -out["skew_ps"]
    assert abs(out_rev["skew_ps"]) == abs(out["skew_ps"])


def test_weave_skew_magnitude_hand_anchor_and_linear():
    out = gws.weave_skew_ps(0.25, 6.0, 3.5)
    assert out["skew_ps"] == pytest.approx(SKEW_ANCHOR_PS, rel=1e-4)  # 手算独立锚
    # 线性性：L 翻倍 → skew 恰翻倍（×2 幂标度 FP 精确 → 逐位）
    out2 = gws.weave_skew_ps(0.5, 6.0, 3.5)
    assert out2["skew_ps"] == 2.0 * out["skew_ps"]
    # delay 两路各自回收
    assert out["delay_hi_ps"] == pytest.approx(0.25 * math.sqrt(6.0) / C0 * 1e12, rel=1e-15)


def test_skew_expected_matches_worst_and_scaling():
    eh, el, lm = 4.3077, 3.5, 0.3
    worst = gws.weave_skew_ps(lm, eh, el)["skew_ps"]
    # Δρ=1 → 与最坏口径逐位一致；Δρ=0 → 0.0 逐位
    assert gws.weave_skew_expected_ps(lm, 1.0, eh, el)["skew_expected_ps"] == worst
    assert gws.weave_skew_expected_ps(lm, 0.0, eh, el)["skew_expected_ps"] == 0.0
    # Δρ 缩放：×0.25/×(−0.5) 均幂标度精确（逐位）
    assert gws.weave_skew_expected_ps(lm, 0.25, eh, el)["skew_expected_ps"] == 0.25 * worst
    assert gws.weave_skew_expected_ps(lm, -0.5, eh, el)["skew_expected_ps"] == -0.5 * worst
    # 域外拒绝
    with pytest.raises(ValueError, match="coverage_delta"):
        gws.weave_skew_expected_ps(lm, 1.5, eh, el)
    with pytest.raises(ValueError, match="coverage_delta"):
        gws.weave_skew_expected_ps(lm, -1.5, eh, el)


# ─── 4. weave-aware 布线：p_eff 恒等式 + 残余期望 ────────────────────────────


def test_zigzag_period_identities_and_guards():
    # θ=90° 正交 → p_eff == pitch 逐位（zigzag 恒等式判据）
    assert gws.zigzag_effective_period_mm(0.4, 90.0) == 0.4
    # θ=30° → pitch/sin30° ≈ 2·pitch（sin(π/6) 非精确 0.5，rel 1e-12）
    assert gws.zigzag_effective_period_mm(0.4, 30.0) == pytest.approx(0.8, rel=1e-12)
    # θ=5° 手算锚
    assert gws.zigzag_effective_period_mm(0.4, 5.0) == pytest.approx(PEFF_5DEG_1080, rel=1e-4)
    # 单调：θ 增大 p_eff 减小（θ→0 发散方向）
    assert gws.zigzag_effective_period_mm(0.4, 10.0) > gws.zigzag_effective_period_mm(0.4, 30.0)
    # 域外 (0,90] 拒绝
    for bad in (0.0, -5.0, 95.0, 180.0, float("nan")):
        with pytest.raises(ValueError, match="theta_deg"):
            gws.zigzag_effective_period_mm(0.4, bad)


def test_zigzag_residual_identities():
    eh, el = 4.3077, 3.5
    worst = gws.weave_skew_ps(1.0, eh, el)["skew_ps"]
    # 完全对齐 → 残余 0 逐位
    out0 = gws.zigzag_residual_expected_ps(1.0, 0.4, 45.0, 0.0, eh, el)
    assert out0["residual_ps"] == 0.0
    # L ≤ p_eff（未满一个周期）且 phase=1 → 残余==同 L 最坏 逐位（n_avg=1）
    out_short = gws.zigzag_residual_expected_ps(0.0002, 0.4, 90.0, 1.0, eh, el)
    worst_short = gws.weave_skew_ps(0.0002, eh, el)["skew_ps"]
    assert out_short["n_periods"] < 1.0
    assert out_short["residual_ps"] == worst_short
    assert out_short["worst_case_ps"] == worst_short
    # 多周期：残余=worst/n_periods（测试侧同式重排 rel 1e-12）
    out_long = gws.zigzag_residual_expected_ps(1.0, 0.4, 90.0, 1.0, eh, el)
    assert out_long["n_periods"] == pytest.approx(2500.0, rel=1e-9)
    assert out_long["residual_ps"] == pytest.approx(worst / 2500.0, rel=1e-12)
    # phase_error_frac 域外拒绝
    with pytest.raises(ValueError, match="phase_error_frac"):
        gws.zigzag_residual_expected_ps(1.0, 0.4, 45.0, 1.5, eh, el)


def test_routing_rules_table():
    rows = gws.routing_rules_table(0.4)
    assert [r["theta_deg"] for r in rows] == [5.0, 10.0, 15.0, 30.0, 45.0, 90.0]
    # p_eff 随 θ 单调下降；θ=90 行逐位等于 pitch
    for a, b in pairwise(rows):
        assert a["p_eff_mm"] > b["p_eff_mm"]
    assert rows[-1]["p_eff_mm"] == 0.4
    # 建议角标记（≥5° 方案口径；缺省档全在建议域内）
    assert all(r["recommended"] for r in rows)
    shallow = gws.routing_rules_table(0.4, thetas_deg=(1.0, 5.0))
    assert shallow[0]["recommended"] is False
    assert shallow[1]["recommended"] is True
    with pytest.raises(ValueError):
        gws.routing_rules_table(0.4, thetas_deg=(0.0,))


# ─── 5. 奈奎斯特对照面：UI 换算与 verdict ────────────────────────────────────


def test_ui_ps_reference_point():
    # 25.78125 Gb/s NS=2 → UI=38.7879 ps 量级（公算路径；32000/825 精确有理锚）
    ui = gws.ui_ps(RATE_25G)
    assert ui == UI_25G_PS  # 同一实数的 IEEE 除法正确舍入 → 逐位
    assert ui == pytest.approx(38.79, abs=0.01)
    # PAM4（NS=4）：波特率减半 → UI 翻倍（幂标度逐位）
    assert gws.ui_ps(RATE_25G, 4) == 2.0 * ui
    with pytest.raises(ValueError):
        gws.ui_ps(RATE_25G, 1)  # NS≥2
    with pytest.raises(ValueError):
        gws.ui_ps(RATE_25G, 2.5)  # 电平数必须整数
    with pytest.raises(ValueError):
        gws.ui_ps(RATE_25G, True)  # bool 显式拒收


def test_skew_ui_verdict():
    ui = UI_25G_PS
    v1 = gws.skew_ui_verdict(ui, RATE_25G, 2, 0.1)
    assert v1["skew_over_ui"] == 1.0  # skew==UI → 比值逐位 1
    assert v1["within_budget"] is False
    assert v1["allowed_ps"] == pytest.approx(0.1 * ui, rel=1e-15)
    # 恰等判达标（ge1③ 口径）
    v_eq = gws.skew_ui_verdict(0.1 * ui, RATE_25G, 2, 0.1)
    assert v_eq["within_budget"] is True
    # 负 skew 取绝对值判
    v_neg = gws.skew_ui_verdict(-1.0, RATE_25G, 2, 0.1)
    assert v_neg["skew_ps"] == -1.0 and v_neg["within_budget"] is True
    assert v_neg["skew_over_ui"] == pytest.approx(1.0 / ui, rel=1e-15)


# ─── 6. 入参守卫（bool 拒收/非有限/域外）─────────────────────────────────────


def test_input_guards_reject_bool_and_nonfinite():
    with pytest.raises(ValueError):
        gws.path_delay_s(True, 4.0)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        gws.path_delay_s(0.25, float("nan"))
    with pytest.raises(ValueError):
        gws.path_delay_s(0.0, 4.0)  # L≤0
    with pytest.raises(ValueError):
        gws.path_delay_s(-1.0, 4.0)
    with pytest.raises(ValueError):
        gws.weave_skew_ps(0.25, 0.0, 3.5)  # εr≤0
    with pytest.raises(ValueError):
        gws.series_mixture_er(6.0, -1.0, 0.5)
    with pytest.raises(ValueError):
        gws.homogenize_er_bounds(0.0, 0.18, 6.0, 3.5)  # pitch≤0
    with pytest.raises(ValueError):
        gws.homogenize_er_bounds(0.4, 0.18, 6.0, 3.5, trace_width_mm=True)
    with pytest.raises(ValueError):
        gws.zigzag_effective_period_mm(True, 45.0)
    with pytest.raises(ValueError):
        gws.skew_ui_verdict(float("inf"), RATE_25G)


# ─── 7. service 薄面：JSON 信封 ok=False 不抛 ────────────────────────────────


def test_service_estimate_ok_envelope_matches_core():
    payload = {
        "style": "1080",
        "length_mm": 250.0,
        "er_resin": 3.5,
        "data_rate_gbps": RATE_25G,
        "coverage_delta": 0.5,
        "theta_deg": 10.0,
        "phase_error_frac": 0.2,
    }
    out = svc.weave_skew_estimate(payload)
    assert out["ok"] is True
    assert out["provenance"]["license"] == "MIT"
    assert out["geometry"]["pitch_mm"] == 0.40
    assert out["geometry"]["length_m"] == 0.25
    # 服务数字必须与内核同参直调逐位一致（薄壳规则 4）
    bounds = gws.homogenize_er_bounds(0.4, 0.18, 6.0, 3.5)
    core_skew = gws.weave_skew_ps(0.25, bounds["er_upper"], bounds["er_lower"])
    assert out["skew_worst"]["skew_ps"] == core_skew["skew_ps"]
    assert out["er_bounds"] == bounds
    assert out["skew_expected"]["skew_expected_ps"] == 0.5 * core_skew["skew_ps"]
    assert out["zigzag_residual"]["p_eff_mm"] == pytest.approx(
        0.4 / math.sin(math.radians(10.0)), rel=1e-15
    )
    assert out["ui_verdict"]["within_budget"] is False
    assert json.loads(json.dumps(out))["ok"] is True  # 全信封 JSON 可序列化


def test_service_error_envelopes_no_raise():
    # 未知样式 / 缺 er_resin / 长度域外 / 二选一冲突 / θ 域外 / 非对象 payload
    for payload in (
        {"style": "9999", "length_m": 0.1, "er_resin": 3.5},
        {"style": "1080", "length_m": 0.1},
        {"style": "1080", "length_m": 0.0, "er_resin": 3.5},
        {"style": "1080", "length_m": 0.1, "length_mm": 100.0, "er_resin": 3.5},
        {"style": "1080", "length_m": 0.1, "er_resin": 3.5, "theta_deg": 95.0},
        {"style": "1080", "length_m": 0.1, "er_resin": 3.5, "data_rate_gbps": -1.0},
        "not-a-dict",
    ):
        out = svc.weave_skew_estimate(payload)
        assert out["ok"] is False, f"payload 应失败: {payload!r}"
        assert isinstance(out.get("errors"), list) and out["errors"]
    assert svc.weave_skew_estimate(None)["ok"] is False


def test_service_style_info_envelope():
    all_styles = svc.weave_style_info()
    assert all_styles["ok"] is True
    assert set(all_styles["styles"]) == {"1067", "1080", "2116", "7628"}
    one = svc.weave_style_info({"style": "2116"})
    assert one["styles"]["2116"]["pitch_x_mm"] == 0.50
    bad = svc.weave_style_info({"style": "1234"})
    assert bad["ok"] is False and bad["errors"]
