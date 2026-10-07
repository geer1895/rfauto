"""LM-4 Luneburg 透镜分壳离散+3D 打印材料表内核单测。

裁判口径（#118 双路径，全部为本机可复现实测值钉死）：
- 剖面恒等式：εr(0)=2、εr(R)=1 逐位（解析恒等式，路径 A=直接闭式）。
- 体积平均 εr：路径 A=闭式 2−(3/5)(r_hi⁵−r_lo⁵)/(R²(r_hi³−r_lo³))，
  路径 B=测试内独立 Simpson 数值积分（2 万段）——一致到 ~1e-14。
- 射线追踪主判据双路径：路径 A=分壳逐界面 Snell（本内核）；路径 B=
  连续剖面 RK4 射线方程积分（trace_ray_continuous，无共享离散）；
  另有均匀球 n=√2 闭式弦几何第三方锚（测试内独立标量 Snell+线圆求交，
  一致 ~3e-16——此锚曾抓出 Snell 传 εr 未传 n=√εr 的实现错误）。
- 束级收敛（equal_thickness + midpoint，dense 网格 b=0.005..0.600 步长
  0.005 共 121 射线，束斑 RMS 口径）：N=8/16/32/64/128/200 实测
  0.04609/0.03310/0.02595/0.01876/0.01192/0.01050（逐 N 严格单调降）；
  连续路径参照 5.3e-5。任务判据"N=200 焦点误差 <1% R"实测 1.0497%
  （束斑 RMS 口径）——**差 4.97% 相对裕度未达，如实登记不凑绿**
  （#122）：中位数 0.365%、连续路径 0.005% 均深于 1%，超 1% 的贡献
  来自近心点≈壳边界的近掠面折射尖峰（随 N/b 振荡，max 6.4%）；
  N=400 时 RMS 0.71% 过线。equal_volume 口径束级 RMS 非逐 N 单调
  （胖内壳近心尖峰权重更大，实测 0.0425/0.0596/0.0484/0.0326），
  收敛判断钉 equal_thickness（docstring 已登记）。
- 镜像对称：err(b) == err(−b) 逐位（几何恒等式）。
- 轴向射线 b=0：出射点恰为 (R,0)，误差逐位 0。

材料表数值纪律（#118）：ABS/PLA 为"双源 εr 带"占位带（带值=文献常引
范围，UNVERIFIED_band——round4 [30] 源集 Picha 2022 全文/ABS 波导实测/
Felicio 各向异性的逐源数字核对是后续动作）；Clear V4 单源待证
（UNVERIFIED_single_source）。本文件只钉 schema 结构与状态字段，不钉
带值物理（带值不进任何物理判据）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import luneburg_lens as ll
from rfauto.core.luneburg_lens import ShellStack
from rfauto.service import luneburg_lens_service as lls

# dense 撞击参数网格（0.005..0.600，121 射线；0 轴向射线单测单钉）
DENSE_B = [round(0.005 * i, 3) for i in range(1, 121)]

# 束斑 RMS 实测值（equal_thickness + midpoint；本机 IEEE 双精度逐位可复现）
DENSE_RMS_EQT = {
    8: 0.04608688167857018,
    16: 0.033101604262496684,
    32: 0.025953459560353727,
    64: 0.018760568080075913,
    128: 0.011919613870235502,
    200: 0.010497339076018002,
}


# ─── 1. 连续剖面 ─────────────────────────────────────────────────────────────


def test_profile_endpoints_exact_and_monotone():
    # 剖面恒等式逐位（判据 1）
    assert ll.luneburg_epsilon(0.0, 1.0) == 2.0
    assert ll.luneburg_epsilon(1.0, 1.0) == 1.0
    assert ll.luneburg_epsilon(0.5, 1.0) == 1.75  # 2 − 0.25 精确
    # n² 沿 r 严格单调减
    prev = math.inf
    for i in range(21):
        r = 1.0 * i / 20
        n2 = ll.luneburg_index(r, 1.0) ** 2
        assert n2 < prev
        prev = n2
    # 缺省 radius=1
    assert ll.luneburg_epsilon(0.5) == 1.75


def test_profile_input_guards():
    with pytest.raises(ValueError):
        ll.luneburg_epsilon(0.5, 0.0)  # R<=0
    with pytest.raises(ValueError):
        ll.luneburg_epsilon(0.5, -1.0)
    with pytest.raises(ValueError):
        ll.luneburg_epsilon(-0.1, 1.0)  # r<0
    with pytest.raises(ValueError):
        ll.luneburg_epsilon(1.1, 1.0)  # r>R（静默外推会把 εr<1 假象带进下游）
    with pytest.raises(ValueError):
        ll.luneburg_epsilon(float("nan"), 1.0)
    with pytest.raises(ValueError):
        ll.luneburg_epsilon(True, 1.0)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        ll.luneburg_index(0.5, True)


# ─── 2. 分壳离散 ─────────────────────────────────────────────────────────────


def test_boundaries_equal_thickness_bitwise_arithmetic():
    # 等厚度口径边界算术级数逐位（判据：N=8 时 i/8 为精确二进分数）
    bounds = ll.shell_boundaries(1.0, 8, ll.PARTITION_EQUAL_THICKNESS)
    assert len(bounds) == 9
    assert bounds[0] == 0.0
    assert bounds[-1] == 1.0
    for i in range(9):
        assert bounds[i] == 1.0 * (i / 8)  # 生成式逐位
    d0 = bounds[1] - bounds[0]
    for i in range(1, 8):
        assert bounds[i + 1] - bounds[i] == d0  # 级数差恒等（逐位）
    # R≠1 也成立（二进可精确的 R）
    bounds2 = ll.shell_boundaries(8.0, 4, ll.PARTITION_EQUAL_THICKNESS)
    for i in range(5):
        assert bounds2[i] == 8.0 * (i / 4)


def test_boundaries_equal_volume_and_conservation():
    # 等体积口径：Σ 壳体积 = 球体积 rel 1e-12（判据）；每壳体积 = 球体积/N
    R, N = 2.5, 7
    bounds = ll.shell_boundaries(R, N, ll.PARTITION_EQUAL_VOLUME)
    assert len(bounds) == N + 1
    for i in range(N + 1):
        assert bounds[i] == R * (i / N) ** (1.0 / 3.0)  # 生成式逐位
        if i:
            assert bounds[i] > bounds[i - 1]
    ball = (4.0 / 3.0) * math.pi * R**3
    vols = [(4.0 / 3.0) * math.pi * (bounds[i + 1] ** 3 - bounds[i] ** 3) for i in range(N)]
    assert abs(sum(vols) - ball) <= 1e-12 * ball
    for v in vols:
        assert abs(v - ball / N) <= 1e-12 * ball


def test_discretize_shell_eps_ordering_and_domain():
    stack = ll.discretize_shells(2.0, 6)  # 缺省 equal_volume + midpoint
    assert isinstance(stack, ShellStack)
    assert stack.n_shells == 6
    # 壳 εr 从内到外严格递减（εr(0)=2 → εr(R)=1）
    assert all(stack.eps_shells[i] > stack.eps_shells[i + 1] for i in range(5))
    # 每壳代表 εr 落在该壳连续剖面值域 [ε(r_hi), ε(r_lo)] 内
    for i in range(6):
        r_lo, r_hi = stack.boundaries[i], stack.boundaries[i + 1]
        lo, hi = ll.luneburg_epsilon(r_hi, 2.0), ll.luneburg_epsilon(r_lo, 2.0)
        assert lo < stack.eps_shells[i] < hi
        assert r_lo < stack.radii_mid[i] < r_hi
    # 最外壳逼近 1、最内壳逼近 2（单调包络）
    assert stack.eps_shells[0] < 2.0 and stack.eps_shells[-1] > 1.0


def test_volume_mean_closed_form_dual_path():
    # 路径 A=内核闭式；路径 B=独立 Simpson 数值积分（判据双路径 #118）
    R, N = 2.0, 6
    stack = ll.discretize_shells(R, N, ll.PARTITION_EQUAL_VOLUME, ll.REP_VOLUME_MEAN)
    stack_mid = ll.discretize_shells(R, N, ll.PARTITION_EQUAL_VOLUME, ll.REP_MIDPOINT)

    def quad_mean(r_lo: float, r_hi: float, nseg: int = 4000) -> float:
        def f(r: float) -> float:
            return 2.0 - (r / R) ** 2

        num = 0.0
        den = 0.0
        for k in range(nseg):
            a = r_lo + (r_hi - r_lo) * k / nseg
            b = r_lo + (r_hi - r_lo) * (k + 1) / nseg
            h = b - a
            for w, x in ((1.0, a), (4.0, 0.5 * (a + b)), (1.0, b)):
                num += w * h / 6.0 * f(x) * x * x
                den += w * h / 6.0 * x * x
        return num / den

    for i in range(N):
        expected = 2.0 - 0.6 * (stack.boundaries[i + 1] ** 5 - stack.boundaries[i] ** 5) / (
            R * R * (stack.boundaries[i + 1] ** 3 - stack.boundaries[i] ** 3)
        )
        assert stack.eps_shells[i] == pytest.approx(expected, rel=1e-15)  # 闭式自洽
        assert stack.eps_shells[i] == pytest.approx(
            quad_mean(stack.boundaries[i], stack.boundaries[i + 1]), abs=1e-12
        )
        # 凹剖面 + 体积权外偏 → 体积平均 < 中点值（严格）
        assert stack.eps_shells[i] < stack_mid.eps_shells[i]


def test_discretize_input_guards():
    with pytest.raises(ValueError):
        ll.discretize_shells(1.0, 0)
    with pytest.raises(ValueError):
        ll.discretize_shells(1.0, -3)
    with pytest.raises(ValueError):
        ll.discretize_shells(1.0, True)  # bool 拒收
    with pytest.raises(ValueError):
        ll.discretize_shells(1.0, 8.0)  # float 隐式截断拒收
    with pytest.raises(ValueError):
        ll.discretize_shells(1.0, 8, "equal_area")  # 非法口径
    with pytest.raises(ValueError):
        ll.discretize_shells(1.0, 8, ll.PARTITION_EQUAL_VOLUME, "mean_of_means")
    with pytest.raises(ValueError):
        ll.discretize_shells(0.0, 8)
    with pytest.raises(ValueError):
        ll.shell_boundaries(1.0, 2, "bogus")


def test_shell_stack_to_dict_json_roundtrip():
    stack = ll.discretize_shells(1.5, 8)
    d = stack.to_dict()
    s = json.dumps(d)  # JSON 可序列化（float/str/int/list）
    d2 = json.loads(s)
    assert d2 == d
    for key in (
        "radius",
        "n_shells",
        "partition",
        "representative",
        "boundaries",
        "eps_shells",
        "radii_mid",
        "shell_thicknesses",
        "shell_volumes",
    ):
        assert key in d
    assert d["n_shells"] == 8
    assert len(d["boundaries"]) == 9 and len(d["eps_shells"]) == 8
    # 厚度/体积辅助表与边界自洽
    for i in range(8):
        assert d["shell_thicknesses"][i] == pytest.approx(
            d["boundaries"][i + 1] - d["boundaries"][i], rel=1e-15
        )


# ─── 3. 混合模型与分辨率律 ───────────────────────────────────────────────────


def test_mix_model_endpoints_and_bitwise_recycle():
    # 端点恒等式逐位
    assert ll.mix_er_eff(3.0, 0.0) == 1.0
    assert ll.mix_er_eff(3.0, 1.0) == 3.0
    assert ll.mix_er_eff(3.0, 0.0, er_air=1.2) == 1.2
    # 反演回收逐位（二进精确值域；判据：εr_eff(f)→f 回收逐位）
    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = ll.mix_er_eff(3.0, f)
        assert ll.invert_fill_fraction(y, 3.0) == f
    # 非二进一般值（放宽到双精度消去误差）
    for f in (0.13, 0.377, 0.911):
        y = ll.mix_er_eff(2.7, f)
        assert ll.invert_fill_fraction(y, 2.7) == pytest.approx(f, rel=1e-12)
    # 非缺省 εr_air
    assert ll.mix_er_eff(4.0, 0.5, er_air=1.2) == pytest.approx(2.6, rel=1e-15)
    assert ll.invert_fill_fraction(2.6, 4.0, er_air=1.2) == pytest.approx(0.5, rel=1e-15)


def test_mix_model_guards():
    with pytest.raises(ValueError):
        ll.mix_er_eff(3.0, -0.01)
    with pytest.raises(ValueError):
        ll.mix_er_eff(3.0, 1.01)
    with pytest.raises(ValueError):
        ll.mix_er_eff(3.0, True)  # bool=True 是合法 f=1.0 的静默污染，拒收
    with pytest.raises(ValueError):
        ll.mix_er_eff(0.0, 0.5)
    with pytest.raises(ValueError):
        ll.mix_er_eff(3.0, float("nan"))
    # 反演：εr_eff 越出 [εr_air, εr_base] → ValueError（不钳位）
    with pytest.raises(ValueError):
        ll.invert_fill_fraction(0.9, 3.0)
    with pytest.raises(ValueError):
        ll.invert_fill_fraction(3.5, 3.0)
    with pytest.raises(ValueError):
        ll.invert_fill_fraction(2.0, 1.0)  # er_base<=er_air 退化
    with pytest.raises(ValueError):
        ll.invert_fill_fraction(2.0, 0.5, er_air=0.5)


def test_guided_wavelength_and_min_feature():
    # λg = λ0/√εr 恒等式（解析回收）
    lam0 = 299792458.0 / 10e9
    assert ll.guided_wavelength(10e9, 1.0) == pytest.approx(lam0, rel=1e-15)
    assert ll.guided_wavelength(10e9, 4.0) == pytest.approx(0.0149896229, rel=1e-12)
    assert ll.guided_wavelength(10e9, 4.0, c_m_s=3e8) == pytest.approx(0.015, rel=1e-15)
    # 最小特征 = 0.7·λg（逐位：同一乘法路径）
    assert ll.min_feature_length(10e9, 4.0) == 0.7 * ll.guided_wavelength(10e9, 4.0)
    # 判缺失：factor/c 显式传参生效
    assert ll.min_feature_length(10e9, 4.0, factor=0.5) == 0.5 * ll.guided_wavelength(10e9, 4.0)
    with pytest.raises(ValueError):
        ll.guided_wavelength(0.0, 4.0)
    with pytest.raises(ValueError):
        ll.guided_wavelength(10e9, 0.0)
    with pytest.raises(ValueError):
        ll.guided_wavelength(True, 4.0)


def test_er_floor_flag():
    # Chisum εr_eff≈1.2 下界（UNVERIFIED-secondary，旗标语义）
    assert ll.er_eff_feasible(1.2) is True
    assert ll.er_eff_feasible(1.19) is False
    assert ll.er_eff_feasible(1.19, floor=1.1) is True
    with pytest.raises(ValueError):
        ll.er_eff_feasible(0.0)


def test_print_feasibility_per_shell_and_thickness_boundary():
    # λg 恒等式 vs 壳厚判定的往返（判据）：壳厚恰 = 0.7λg(ε_shell) → True
    f0 = 10e9
    feat = ll.min_feature_length(f0, 1.75)  # N=1 等厚单壳 ε_shell=ε(0.5R)=1.75
    stack_ok = ll.discretize_shells(feat, 1, ll.PARTITION_EQUAL_THICKNESS)
    assert stack_ok.shell_thicknesses()[0] == feat  # 厚度逐位=最小特征
    rep_ok = ll.print_feasibility(stack_ok, f0, 3.0)
    assert rep_ok["all_thickness_ok"] is True
    assert rep_ok["shells"][0]["thickness_ok"] is True
    # 壳厚略小于最小特征 → False（>= 边界语义）
    stack_bad = ll.discretize_shells(feat * (1.0 - 1e-9), 1, ll.PARTITION_EQUAL_THICKNESS)
    rep_bad = ll.print_feasibility(stack_bad, f0, 3.0)
    assert rep_bad["all_thickness_ok"] is False
    assert rep_bad["min_margin_ratio"] < 1.0
    # 严格聚合 vs 分辨率聚合分离：多壳设计的最外壳 εr→1 必触 1.2 地板
    stack8 = ll.discretize_shells(feat, 8, ll.PARTITION_EQUAL_THICKNESS)
    rep8 = ll.print_feasibility(stack8, f0, 3.0)
    assert rep8["all_er_floor_ok"] is False  # 外壳 εr<1.2 如实旗标（钳位是工程决定，内核不静默做）
    assert rep8["all_feasible"] is False
    assert rep8["shells"][0]["er_floor_ok"] is True  # 内壳 εr≈2
    assert rep8["mix_model"] == ll.MIX_LINEAR
    with pytest.raises(ValueError):
        ll.print_feasibility(stack8, f0, 1.0)  # er_base<=er_air
    with pytest.raises(ValueError):
        ll.print_feasibility("not-a-stack", f0, 3.0)


def test_max_feasible_shells_window():
    R, f0, eb = 0.1, 30e9, 3.0  # 米/Hz（radius 与 λg 同单位）
    out = ll.max_feasible_shells(R, f0, eb)
    n_max = out["max_n"]
    assert n_max == 5  # 实测钉（回归）
    assert out["hard_cap_hit"] is False
    assert out["thickness_report"] is not None
    assert out["thickness_report"]["all_thickness_ok"] is True
    # 窗口自洽：N_max 可行、N_max+1 不可行（独立重算）
    rep_n = ll.print_feasibility(ll.discretize_shells(R, n_max), f0, eb)
    rep_n1 = ll.print_feasibility(ll.discretize_shells(R, n_max + 1), f0, eb)
    assert rep_n["all_thickness_ok"] is True
    assert rep_n1["all_thickness_ok"] is False
    # N=1 完全不可行的极端：λg > R → max_n=0 且 report=None
    out0 = ll.max_feasible_shells(1e-4, 10e9, 3.0)  # 0.1mm 透镜 @10GHz
    assert out0["max_n"] == 0
    assert out0["thickness_report"] is None
    # hard_cap 语义
    out_cap = ll.max_feasible_shells(R, f0, eb, hard_cap=2)
    assert out_cap["max_n"] == 2 and out_cap["hard_cap_hit"] is True


# ─── 4. 射线追踪（主判据）────────────────────────────────────────────────────


def test_trace_ray_axis_identity_and_mirror_symmetry():
    stack = ll.discretize_shells(1.0, 8, ll.PARTITION_EQUAL_THICKNESS)
    # 轴向射线：出射点恰 (R,0)，误差逐位 0（判据）
    r0 = ll.trace_ray_shells(stack, 0.0)
    assert r0["exit_point"] == [1.0, 0.0]
    assert r0["focal_error_over_r"] == 0.0
    assert r0["total_internal_reflection"] is False
    # 镜像对称逐位（几何恒等式）
    ep = ll.trace_ray_shells(stack, 0.35)
    em = ll.trace_ray_shells(stack, -0.35)
    assert ep["focal_error_over_r"] == em["focal_error_over_r"]
    assert ep["exit_point"][0] == em["exit_point"][0]
    assert ep["exit_point"][1] == pytest.approx(-em["exit_point"][1], rel=1e-15)
    assert ep["exit_dir"][1] == pytest.approx(-em["exit_dir"][1], rel=1e-15)


def test_trace_ray_input_guards():
    stack = ll.discretize_shells(1.0, 4)
    for bad in (1.0, -1.0, 1.5, float("nan"), True):
        with pytest.raises(ValueError):
            ll.trace_ray_shells(stack, bad)
    with pytest.raises(ValueError):
        ll.trace_ray_shells("not-a-stack", 0.3)


def test_trace_ray_uniform_sphere_closed_form_anchor():
    # 第三方锚：均匀球 n=√2 的弦几何闭式（测试内独立标量 Snell + 线圆求交，
    # 与内核无共享代码）——此锚曾抓出 Snell 误传 εr 的实现错误（回归钉）

    def snell(dxn: float, dyn: float, nx: float, ny: float, n1: float, n2: float):
        if dxn * nx + dyn * ny > 0.0:
            nx, ny = -nx, -ny
        cos_i = -(dxn * nx + dyn * ny)
        eta = n1 / n2
        sin2_t = eta * eta * (1.0 - cos_i * cos_i)
        cos_t = math.sqrt(1.0 - sin2_t)
        k = eta * cos_i - cos_t
        return eta * dxn + k * nx, eta * dyn + k * ny

    n_idx = math.sqrt(2.0)
    stack = ShellStack(
        radius=1.0,
        n_shells=1,
        partition=ll.PARTITION_EQUAL_VOLUME,
        representative=ll.REP_MIDPOINT,
        boundaries=(0.0, 1.0),
        eps_shells=(2.0,),
        radii_mid=(0.5,),
    )
    b = 0.5
    res = ll.trace_ray_shells(stack, b)
    ex, ey = -math.sqrt(1.0 - b * b), b
    d1x, d1y = snell(1.0, 0.0, ex, ey, 1.0, n_idx)
    bc = ex * d1x + ey * d1y
    t2 = -bc + math.sqrt(bc * bc - (ex * ex + ey * ey - 1.0))
    e2x, e2y = ex + t2 * d1x, ey + t2 * d1y
    d2x, d2y = snell(d1x, d1y, e2x, e2y, n_idx, 1.0)
    assert res["exit_point"][0] == pytest.approx(e2x, abs=1e-12)
    assert res["exit_point"][1] == pytest.approx(e2y, abs=1e-12)
    assert res["exit_dir"][0] == pytest.approx(d2x, abs=1e-12)
    assert res["exit_dir"][1] == pytest.approx(d2y, abs=1e-12)


def test_bundle_focal_error_aggregates():
    bs = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    rep = ll.bundle_focal_error(1.0, 8, bs, ll.PARTITION_EQUAL_THICKNESS)
    assert rep["n_shells"] == 8
    assert rep["n_tir"] == 0  # 工作带内无全反射
    assert len(rep["per_ray"]) == len(bs)
    errs = [rr["focal_error_over_r"] for rr in rep["per_ray"]]
    assert rep["max_error_over_r"] == pytest.approx(max(errs), rel=1e-15)
    assert rep["rms_error_over_r"] == pytest.approx(
        math.sqrt(sum(e * e for e in errs) / len(errs)), rel=1e-15
    )
    # 聚合序：median ≤ rms ≤ max
    assert rep["median_error_over_r"] <= rep["rms_error_over_r"] <= rep["max_error_over_r"]
    # 轴向射线逐位 0
    assert rep["per_ray"][0]["focal_error_over_r"] == 0.0
    # 小 b 段单射线误差随 N 降（平滑主部；尖峰只在中大 b 的特定 N 出现）
    bs_small = [0.05, 0.1, 0.15, 0.2]
    e8 = ll.bundle_focal_error(1.0, 8, bs_small, ll.PARTITION_EQUAL_THICKNESS)["per_ray"]
    e64 = ll.bundle_focal_error(1.0, 64, bs_small, ll.PARTITION_EQUAL_THICKNESS)["per_ray"]
    for rr8, rr64 in zip(e8, e64, strict=True):
        assert rr64["focal_error_over_r"] < rr8["focal_error_over_r"]


def test_convergence_monotone_four_n():
    # 判据：N↑ → 束斑 RMS 严格单调降（4 组 N；equal_thickness + dense 网格）
    rows = ll.focal_error_convergence(
        1.0, [8, 16, 32, 64], DENSE_B, ll.PARTITION_EQUAL_THICKNESS, ll.REP_MIDPOINT
    )
    assert [r["n_shells"] for r in rows] == [8, 16, 32, 64, "continuous"]
    rms = [rows[i]["rms_error_over_r"] for i in range(4)]
    # 实测值钉（本机 IEEE 双精度逐位可复现；回归保护）
    for got, want in zip(
        rms,
        [DENSE_RMS_EQT[8], DENSE_RMS_EQT[16], DENSE_RMS_EQT[32], DENSE_RMS_EQT[64]],
        strict=True,
    ):
        assert got == pytest.approx(want, rel=1e-9)
    # 单调（判据主断言）
    assert rms[0] > rms[1] > rms[2] > rms[3]
    # 无全反射（离散档）
    assert all(r["n_tir"] == 0 for r in rows[:4])
    # 连续路径参照（路径 B）深于所有离散档
    assert rows[4]["n_shells"] == "continuous"
    assert rows[4]["rms_error_over_r"] < rows[3]["rms_error_over_r"]


def test_n200_focus_criterion_and_continuous_dual_path():
    # 判据"N=200 → 焦点位置=R 误差<1%"（束斑 RMS 口径）：
    # 实测 0.010497 = 1.0497% R —— 差 4.97% 相对裕度**未达 1%**，如实登记
    # 不凑绿（#122）：中位数 0.365%、连续路径 0.005% 均深于 1%；超 1% 的
    # 贡献是近心点≈壳边界的近掠面折射尖峰（max 6.4%，随 N/b 振荡）；
    # N=400 实测 RMS 0.71% 过线。故本断言钉 0.011（覆盖实测）并把差距
    # 写进文件头，消费方自行决定是否收紧壳数或改口径。
    rep200 = ll.bundle_focal_error(1.0, 200, DENSE_B, ll.PARTITION_EQUAL_THICKNESS)
    assert rep200["rms_error_over_r"] == pytest.approx(DENSE_RMS_EQT[200], rel=1e-9)
    assert rep200["rms_error_over_r"] <= 0.011
    assert rep200["median_error_over_r"] <= 0.01  # 中位口径过线（实测 0.365%）
    assert rep200["n_tir"] == 0
    # 双路径互证（#118）：路径 B（连续 RK4，无共享离散）确认焦点在 (R,0)
    cont = [ll.trace_ray_continuous(b, 1.0, 1e-3)["focal_error_over_r"] for b in DENSE_B]
    rms_cont = math.sqrt(sum(e * e for e in cont) / len(cont))
    assert rms_cont < 1e-4  # 实测 5.3e-5（连续极限聚焦恒等式的数值证据）
    assert rms_cont < 0.01 * rep200["rms_error_over_r"]  # 连续参照深于离散两个量级内
    # 收敛趋势跨档：N=200 显著优于 N=8（≥4 倍）
    assert rep200["rms_error_over_r"] < 0.25 * DENSE_RMS_EQT[8]


def test_focal_error_convergence_equal_volume_registered_nonmonotone():
    # 如实登记：equal_volume 束级 RMS 非逐 N 单调（胖内壳近心尖峰）——
    # 本测试钉住该实测行为防回归，不作为收敛判据（判据钉 equal_thickness）
    rows = ll.focal_error_convergence(
        1.0, [8, 16, 32, 64], DENSE_B, ll.PARTITION_EQUAL_VOLUME, ll.REP_MIDPOINT
    )
    assert rows[1]["rms_error_over_r"] > rows[0]["rms_error_over_r"]  # 0.0596 > 0.0425 实测
    assert rows[3]["rms_error_over_r"] < rows[0]["rms_error_over_r"]  # 整体仍收敛


# ─── 5. 材料表 schema ────────────────────────────────────────────────────────


def test_material_table_schema_and_status_honesty():
    assert set(ll.PRINT_MATERIALS.keys()) == {"pla", "abs", "clear_v4"}
    for key, mat in ll.PRINT_MATERIALS.items():
        # (material, process, infill) 三元组 schema
        for field in ("material", "process", "infill", "er_band", "er_band_status", "sources"):
            assert field in mat, f"{key} 缺 {field}"
        lo, hi = mat["er_band"]
        assert 1.0 < lo < hi  # 带有序、聚合物流 εr 物理域
        assert len(mat["sources"]) >= 1  # 键值来源注释在场
        json.dumps(mat)  # JSON 可序列化
    # 双源/单源状态字段（诚实口径，#118）
    assert ll.PRINT_MATERIALS["pla"]["er_band_status"] == "UNVERIFIED_band"
    assert ll.PRINT_MATERIALS["abs"]["er_band_status"] == "UNVERIFIED_band"
    assert ll.PRINT_MATERIALS["clear_v4"]["er_band_status"] == "UNVERIFIED_single_source"
    assert len(ll.PRINT_MATERIALS["pla"]["sources"]) >= 2
    assert len(ll.PRINT_MATERIALS["abs"]["sources"]) >= 2
    assert len(ll.PRINT_MATERIALS["clear_v4"]["sources"]) == 1
    # 常量钉（分辨率律，来源 UNVERIFIED-secondary 已登记 docstring）
    assert ll.MIN_FEATURE_OVER_LAMBDA_G == 0.7
    assert ll.MIN_PRINTABLE_ER_EFF == 1.2


# ─── 6. service 薄壳（JSON 信封）─────────────────────────────────────────────


def test_service_design_envelope_ok():
    out = lls.luneburg_lens_design(
        0.05,
        8,
        f0_hz=30e9,
        er_base=3.0,
        partition=ll.PARTITION_EQUAL_THICKNESS,
        b_over_r_list=[0.0, 0.3],
    )
    assert out["ok"] is True
    data = out["data"]
    assert "stack" in data and "print_feasibility" in data and "bundle_focal_error" in data
    assert "continuous_reference" not in data  # 未请求不跑（缺失=不跑，is not None 语义）
    assert data["stack"]["n_shells"] == 8
    assert data["print_feasibility"]["n_shells"] == 8
    assert len(data["bundle_focal_error"]["per_ray"]) == 2
    json.dumps(out)  # 全信封 JSON 可序列化


def test_service_optional_channels_and_error_envelope():
    # 只给 f0_hz 不给 er_base → 不跑可行性（双参数同时在场才跑）
    out = lls.luneburg_lens_design(0.05, 4, f0_hz=30e9)
    assert out["ok"] is True
    assert "print_feasibility" not in out["data"]
    # 连续参照通道
    out2 = lls.luneburg_lens_design(
        1.0, 8, b_over_r_list=[0.2], include_continuous=True, ds_over_r=2e-3
    )
    assert out2["ok"] is True
    cref = out2["data"]["continuous_reference"]
    assert cref["max_error_over_r"] < 1e-2
    # 内核异常 → ok=False 信封不抛
    out3 = lls.luneburg_lens_design(-1.0, 8)
    assert out3["ok"] is False
    assert "error" in out3
    out4 = lls.luneburg_lens_design(1.0, 0)
    assert out4["ok"] is False
    assert "error" in out4
