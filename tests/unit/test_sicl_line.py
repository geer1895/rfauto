"""SICL（基片集成同轴线）闭式内核单测（B2 器件族批 2，round3 F-F 表件 7）。

判据预声明（#122，先写判据后跑）与裁判口径（#118 双路径，不自证）：

1. 主判据（闭式 vs 独立数值裁判）：本文件实现二维矩形腔准静态电容 FD 求解器
   （节点型五点差分 + 变 ε 调和平均 + 能量积分），与被测闭式（
   src/rfauto/core/sicl_line.py，共形模数 + 椭圆积分）**零共享代码路径**。
   声明域（1.5≤a/b≤4、0.3≤w/b≤0.9、gap=(a−w)/2≥0.5b、t/b=0.02、均匀介质）
   内 10 点网格 |Z0_闭式/Z0_FD − 1| ≤ 5%（预声明带；实测 max +4.54%）。
2. 裁判自身验证（裁判才有资格裁判闭式，#300）：
   a/b=8 方格网（dx=dy）对 repo exact 零厚带状线共形闭式
   （core/calculators._stripline_z0，同族不同源）实测 −0.9%~−1.8%，
   预声明带 [−3%, 0]（方向：FD 含有限厚 + 离散，Z0 低于零厚精确值）；
   平行板极限 FD < η0·b/(4w)（边缘场只增电容，方向断言）且 |rel|≤8%；
   加密收敛步差单调降（实测 6.01% → 0.441% → 0.178%）。
3. 极限恒等式：a→∞ 逐点退化 repo exact 带状线闭式（≤0.3%）；b/w→0 平行板
   η0·b/(4w√εr)（渐近分支，≤1%）；w→0 对数发散方向（Z0 单调升且 >200Ω）。
4. 面内恒等式：Z0·C·c0 = √εr（均匀介质，模块解析恒等，≤1e-12 相对）；
   裁判 ε 缩放 C(εr)=εr·C(1) 逐位（求解器线性，≤1e-9）。
5. 悬置（部分填充）路径：UNVERIFIED-3 线性填充因子为上界锚——εeff 对双层 FD
   高估 +16.8%/+15.7%（h/b=0.5/0.8，εr=4.4），预声明登记带 [+12%, +20%]；
   Z0 净差（t=0.05 处 t 扩展 +7% 与悬置 −7.5% 相消）只作 ≤3% 回归锚；
   h_frac=1 与均匀口径逐位恒等。
6. 越域退化如实标记：gap=0.3b 实测 +9.5%（壁槽电容缺失），预声明带 (5%, 12%]
   且 in_referee_band=False。
7. 边界：w≥a / t≥b / t<0 / εr<1 / bool / 非有限 / h_frac∉[0,1] → ValueError。

文献锚与 UNVERIFIED 清单详见模块 docstring（src/rfauto/core/sicl_line.py）。
注意：FD 裁判类测试（#14/15/16/18 等）各需数秒（稀疏直解），定向门可接受
成本（同批 test_ridged_waveguide FEM 先例）。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
import scipy.sparse as sp
import scipy.sparse.linalg as spl

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import calculators
from rfauto.core import sicl_line as sl

EPS0 = 8.8541878128e-12
C0 = 299792458.0
ETA0 = 376.730313668


# ─── 独立数值裁判：矩形腔准静态电容 FD（与闭式零共享代码，#118）──────────────


def _fd_c_norm(
    a: float,
    b: float,
    w: float,
    t: float,
    nx: int = 300,
    ny: int = 250,
    h_frac: float | None = None,
    eps_r: float = 1.0,
) -> float:
    """矩形腔 a×b 内中心条带 w×t 的归一化电容 C/ε0（εr 加权，F/m per ε0）。

    节点型五点差分：外壁 V=0、条带 V=1；变 ε 用相邻单元调和平均（守恒型），
    悬置介质以条带为中面对称占 h_frac·b（单元中心采样）。能量积分
    C = Σ_edges g·ΔV² / V²（= 2W/V²）。与闭式零共享代码（#118）。
    """
    dx = a / nx
    dy = b / ny
    if h_frac is None:
        eps_c = np.full((nx, ny), float(eps_r))
    else:
        yc = (np.arange(ny) + 0.5) * dy
        in_d = np.abs(yc - b / 2) <= h_frac * b / 2
        eps_c = np.ones((nx, ny))
        eps_c[:, in_d] = float(eps_r)
    x = np.arange(nx + 1) * dx
    y = np.arange(ny + 1) * dy
    node = np.zeros((nx + 1, ny + 1), dtype=np.int8)  # 0 待解 / 1 条带 / 2 壁
    node[0, :] = node[nx, :] = node[:, 0] = node[:, ny] = 2
    in_sx = (x >= a / 2 - w / 2 - 1e-9) & (x <= a / 2 + w / 2 + 1e-9)
    in_sy = (y >= b / 2 - t / 2 - 1e-9) & (y <= b / 2 + t / 2 + 1e-9)
    node[np.outer(in_sx, in_sy)] = 1
    free = node == 0
    nid = -np.ones((nx + 1, ny + 1), dtype=np.int64)
    nid[free] = np.arange(int(free.sum()))
    n = int(free.sum())

    def cell(i: int, j: int) -> float:
        return float(eps_c[min(max(i, 0), nx - 1), min(max(j, 0), ny - 1)])

    def harm(e1: float, e2: float) -> float:
        return 2.0 * e1 * e2 / (e1 + e2)

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    rhs = np.zeros(n)
    for i in range(nx + 1):
        for j in range(ny + 1):
            if not free[i, j]:
                continue
            k = nid[i, j]
            diag = 0.0
            for i2 in (i + 1, i - 1):
                if 0 <= i2 <= nx:
                    g = harm((cell(i, j - 1) + cell(i, j)) / 2.0,
                             (cell(i2, j - 1) + cell(i2, j)) / 2.0) * dy / dx
                    if node[i2, j] == 0:
                        rows.append(k)
                        cols.append(nid[i2, j])
                        vals.append(-g)
                        diag += g
                    elif node[i2, j] == 1:
                        rhs[k] += g
                        diag += g
                    else:
                        diag += g
            for j2 in (j + 1, j - 1):
                if 0 <= j2 <= ny:
                    g = harm((cell(i - 1, j) + cell(i, j)) / 2.0,
                             (cell(i - 1, j2) + cell(i, j2)) / 2.0) * dx / dy
                    if node[i, j2] == 0:
                        rows.append(k)
                        cols.append(nid[i, j2])
                        vals.append(-g)
                        diag += g
                    elif node[i, j2] == 1:
                        rhs[k] += g
                        diag += g
                    else:
                        diag += g
            rows.append(k)
            cols.append(k)
            vals.append(diag)
    mat = sp.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    v = spl.spsolve(mat, rhs)
    vf = np.zeros((nx + 1, ny + 1))
    vf[node == 1] = 1.0
    vf[free] = v
    e_sum = 0.0
    for i in range(nx + 1):
        for j in range(ny + 1):
            if i + 1 <= nx:
                g = harm((cell(i, j - 1) + cell(i, j)) / 2.0,
                         (cell(i + 1, j - 1) + cell(i + 1, j)) / 2.0) * dy / dx
                e_sum += g * (vf[i, j] - vf[i + 1, j]) ** 2
            if j + 1 <= ny:
                g = harm((cell(i - 1, j) + cell(i, j)) / 2.0,
                         (cell(i - 1, j + 1) + cell(i, j + 1)) / 2.0) * dx / dy
                e_sum += g * (vf[i, j] - vf[i, j + 1]) ** 2
    return e_sum


def _fd_z0(a: float, b: float, w: float, t: float, **kw: float) -> float:
    """FD 裁判 Z0（均匀介质时 sqrt(eps_r) 因子进 z0_fd 由 eps_r 承担）。"""
    eps_r = kw.pop("eps_r", 1.0)
    return math.sqrt(eps_r) / (C0 * EPS0 * _fd_c_norm(a, b, w, t, **kw))


# ─── 输入校验（边界 ValueError）──────────────────────────────────────────────


def test_validation_w_ge_a_rejected():
    with pytest.raises(ValueError, match="小于外腔宽"):
        sl.sicl_closed_form(w_mm=2.0, a_mm=2.0, b_mm=1.0)
    with pytest.raises(ValueError, match="小于外腔宽"):
        sl.sicl_closed_form(w_mm=2.5, a_mm=2.0, b_mm=1.0)


def test_validation_t_ge_b_rejected():
    with pytest.raises(ValueError, match="小于腔高"):
        sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, t_mm=1.0)
    with pytest.raises(ValueError, match="小于腔高"):
        sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, t_mm=1.2)


def test_validation_t_negative_rejected():
    with pytest.raises(ValueError, match=">=0"):
        sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, t_mm=-0.1)


def test_validation_eps_r_rejected():
    with pytest.raises(ValueError, match="eps_r"):
        sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, eps_r=-2.0)
    with pytest.raises(ValueError, match="eps_r"):
        sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, eps_r=0.5)


def test_validation_bool_rejected():
    """df7+⑯：数值入参显式拒收 bool（float(True)=1.0 静默污染）。"""
    with pytest.raises(ValueError, match="bool"):
        sl.sicl_closed_form(w_mm=True, a_mm=2.0, b_mm=1.0)
    with pytest.raises(ValueError, match="bool"):
        sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, eps_r=False)


def test_validation_nonfinite_rejected():
    for bad in (float("inf"), float("nan")):
        with pytest.raises(ValueError, match="有限"):
            sl.sicl_closed_form(w_mm=0.5, a_mm=bad, b_mm=1.0)
        with pytest.raises(ValueError, match="有限"):
            sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, eps_r=bad)


def test_validation_h_frac_domain():
    for bad in (-0.1, 1.5):
        with pytest.raises(ValueError, match="h_frac"):
            sl.sicl_closed_form(w_mm=0.5, a_mm=2.0, b_mm=1.0, h_frac=bad)


def test_h_frac_endpoints_exact():
    """h_frac=0 → 纯空气 εeff=1；h_frac=1 → 均匀 εeff=εr（逐位）。"""
    r0 = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02,
                             eps_r=4.4, h_frac=0.0)
    r1 = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02,
                             eps_r=4.4, h_frac=1.0)
    ru = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02, eps_r=4.4)
    assert r0.eps_eff == 1.0
    assert r1.eps_eff == 4.4
    assert r1.eps_eff == ru.eps_eff
    assert r1.z0_ohm == pytest.approx(ru.z0_ohm, rel=0.0)


# ─── 极限恒等式 ───────────────────────────────────────────────────────────────


def test_limit_stripline_identity_a_infty():
    """a→∞ 恒等退化 repo exact 带状线闭式（预声明 ≤0.3%）。"""
    for wb in (0.4, 0.8):
        for er in (1.0, 4.4):
            got = sl.sicl_z0(w_mm=wb, a_mm=200.0, b_mm=1.0, t_mm=0.0, eps_r=er)
            ref = calculators._stripline_z0(w_mm=wb, b_mm=1.0, epsilon_r=er)
            assert got == pytest.approx(ref, rel=0.003), (wb, er, got, ref)


def test_limit_parallel_plate():
    """b/w→0 平行板极限 Z0→η0·b/(4w·√εr)（渐近分支）。

    预声明 ≤2% @b/w=0.02：共形闭式在 PP 极限带 +O(1) 常数边缘项
    （渐近展开 C = 4w/b + 8·ln2/π + O(b/w)，b/w=0.02 时 +0.9%），实测 −0.9%。
    """
    zpp = ETA0 * 0.02 / (4.0 * 1.0) / math.sqrt(2.25)
    got = sl.sicl_z0(w_mm=1.0, a_mm=4.0, b_mm=0.02, t_mm=0.0, eps_r=2.25)
    assert got == pytest.approx(zpp, rel=0.02), (got, zpp)


def test_limit_narrow_strip_diverges():
    """w→0 对数发散方向：Z0 单调升且进入高阻区（零厚细条 C→0）。"""
    z_coarse = sl.sicl_z0(w_mm=0.02, a_mm=3.0, b_mm=1.0)
    z_fine = sl.sicl_z0(w_mm=0.005, a_mm=3.0, b_mm=1.0)
    assert z_coarse > 200.0
    assert z_fine > z_coarse


def test_identity_z0_c_c0():
    """无耗 TEM 面内恒等式 Z0·C·c0 = √εr（均匀介质，解析恒等）。"""
    for er in (1.0, 2.2, 4.4):
        r = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.0, eps_r=er)
        lhs = r.z0_ohm * r.c_f_m * C0
        assert lhs == pytest.approx(math.sqrt(er), rel=1e-12), (er, lhs)
        # 模型恒等 c = eps_eff·c_air（悬置路径同构）
        assert r.c_f_m == pytest.approx(r.eps_eff * r.c_air_f_m, rel=1e-15)


# ─── 裁判自身验证（裁判才有资格裁判闭式，#300）────────────────────────────────


def test_referee_anchor_vs_exact_stripline():
    """FD 裁判 vs repo exact 带状线（a/b=8 方格网，同族不同源）。

    预声明带 [−3%, 0]：FD 含有限厚（3 节点行块，t_eff≈0.033b）与离散，
    Z0 必低于零厚精确值且偏差有界（实测 −0.9%~−1.8%）。
    """
    for wb in (0.3, 0.6, 1.0):
        c_fd = _fd_c_norm(8.0, 1.0, wb, 1.0 / 60.0, nx=480, ny=60)
        z_fd = 1.0 / (C0 * EPS0 * c_fd)
        z_exact = calculators._stripline_z0(w_mm=wb, b_mm=1.0, epsilon_r=1.0)
        rel = z_fd / z_exact - 1.0
        assert -0.03 <= rel <= 0.0, (wb, rel)


def test_referee_parallel_plate_limit():
    """裁判平行板极限：FD 低于 η0·b/(4w)（边缘场只增电容，方向断言）且 |rel|≤8%。"""
    z_pp = ETA0 * 0.1 / 4.0
    z_fd = _fd_z0(a=4.0, b=0.1, w=1.0, t=0.002, nx=400, ny=120)
    rel = z_fd / z_pp - 1.0
    assert -0.08 <= rel < 0.0, rel


def test_referee_convergence_monotone():
    """加密收敛：步差单调降（预声明）且末档步差 ≤0.5%。"""
    cs = [
        _fd_c_norm(3.0, 1.0, 0.6, 0.05, nx=nx, ny=nx * 2 // 5)
        for nx in (60, 120, 240, 480)
    ]
    steps = [abs(cs[i + 1] - cs[i]) / cs[i + 1] for i in range(3)]
    assert steps[1] < steps[0], steps
    assert steps[2] < steps[1], steps
    assert steps[2] <= 0.005, steps


def test_referee_eps_scaling_exact():
    """裁判 ε 缩放恒等 C(εr)=εr·C(1)（求解器线性，逐位级 ≤1e-9）。"""
    c1 = _fd_c_norm(3.0, 1.0, 0.6, 0.02, nx=120, ny=100)
    c44 = _fd_c_norm(3.0, 1.0, 0.6, 0.02, nx=120, ny=100, eps_r=4.4)
    assert c44 == pytest.approx(4.4 * c1, rel=1e-9)
    # 模块侧 √εr 缩放恒等（同一闭式严格重标定）
    z1 = sl.sicl_z0(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.0, eps_r=1.0)
    z44 = sl.sicl_z0(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.0, eps_r=4.4)
    assert z44 == pytest.approx(z1 / math.sqrt(4.4), rel=1e-15)


# ─── 主判据：闭式 vs FD 裁判（声明域 10 点，±5%，#122 预声明）─────────────────


_JUDGE_GRID = [
    (1.5, 0.3), (2.0, 0.3), (2.0, 0.6), (2.0, 0.9),
    (3.0, 0.3), (3.0, 0.6), (3.0, 0.9),
    (4.0, 0.3), (4.0, 0.6), (4.0, 0.9),
]  # (a/b, w/b)，t/b=0.02，b=1；gap<0.5b 的 (1.5,0.6)/(1.5,0.9) 不入声明域


def test_closed_form_vs_fd_referee_band():
    """主判据：声明域内闭式 vs FD ≤±5%（实测 max +4.54%，系统性为正）。"""
    worst = 0.0
    for ab, wb in _JUDGE_GRID:
        t = 0.02
        z_fd = 1.0 / (C0 * EPS0 * _fd_c_norm(ab, 1.0, wb, t))
        r = sl.sicl_closed_form(w_mm=wb, a_mm=ab, b_mm=1.0, t_mm=t, eps_r=1.0)
        rel = r.z0_ohm / z_fd - 1.0
        assert abs(rel) <= 0.05, (ab, wb, rel)
        assert r.in_referee_band, (ab, wb)
        worst = max(worst, abs(rel))
    assert worst <= 0.05


def test_wall_proximity_degradation_marked():
    """越域（gap=0.3b）退化如实标记：带内 (5%, 12%] 且 in_referee_band=False。"""
    z_fd = 1.0 / (C0 * EPS0 * _fd_c_norm(1.5, 1.0, 0.9, 0.02))
    r = sl.sicl_closed_form(w_mm=0.9, a_mm=1.5, b_mm=1.0, t_mm=0.02, eps_r=1.0)
    rel = r.z0_ohm / z_fd - 1.0
    assert 0.05 < rel <= 0.12, rel
    assert r.in_referee_band is False


def test_suspended_vs_layered_fd():
    """悬置线性填充（UNVERIFIED-3 上界锚）vs 双层 FD。

    - εeff 偏差（模型高估，预声明登记带 [+12%, +20%]；实测 +16.8%/+15.7%）：
      FD 的 εeff = C(混合)/C(空气) 是与闭式无关的直接量；
    - Z0 净差 |rel| ≤ 3%（回归锚；t=0.05 处模块 t 扩展 +7% 与悬置 −7.5%
      意外相消，此项不作精度声明——精度声明只看 εeff 偏差带）；
    - h_frac=1 与均匀口径逐位恒等（同一代码路径，解析恒等）。
    """
    for hb in (0.5, 0.8):
        e_air = _fd_c_norm(3.0, 1.0, 0.6, 0.05, h_frac=hb, eps_r=1.0)
        e_mix = _fd_c_norm(3.0, 1.0, 0.6, 0.05, h_frac=hb, eps_r=4.4)
        eps_eff_fd = e_mix / e_air
        r = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.05,
                                eps_r=4.4, h_frac=hb)
        eff_dev = r.eps_eff / eps_eff_fd - 1.0
        assert 0.12 <= eff_dev <= 0.20, (hb, eff_dev)
        z_fd = ETA0 / (e_air * math.sqrt(eps_eff_fd))
        rel = r.z0_ohm / z_fd - 1.0
        assert abs(rel) <= 0.03, (hb, rel)
    r1 = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.05,
                             eps_r=4.4, h_frac=1.0)
    ru = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.05, eps_r=4.4)
    assert r1.z0_ohm == ru.z0_ohm
    assert r1.eps_eff == ru.eps_eff == 4.4


# ─── 结果对象契约 ─────────────────────────────────────────────────────────────


def test_result_to_dict_json_roundtrip():
    r = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02, eps_r=4.4)
    d = r.to_dict()
    assert set(d) >= {
        "z0_ohm", "eps_eff", "c_f_m", "c_air_f_m", "k_conformal",
        "a_over_b", "w_over_b", "t_over_b", "gap_over_b", "h_frac",
        "in_referee_band",
    }
    assert r.h_frac is None  # 判缺失 is not None（#364④）
    blob = json.dumps(json.loads(r.to_json()), ensure_ascii=False)
    assert "z0_ohm" in blob
    for key in ("z0_ohm", "c_f_m", "c_air_f_m"):
        assert math.isfinite(d[key]) and d[key] > 0.0


def test_convenience_wrappers_consistent():
    r = sl.sicl_closed_form(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02, eps_r=2.2)
    assert sl.sicl_z0(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02, eps_r=2.2) == r.z0_ohm
    assert sl.sicl_eps_eff(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02, eps_r=2.2) == r.eps_eff
    assert sl.sicl_c_total(w_mm=0.6, a_mm=3.0, b_mm=1.0, t_mm=0.02, eps_r=2.2) == r.c_f_m
    assert sl.sicl_k_conformal(w_mm=0.6, a_mm=3.0, b_mm=1.0) == r.k_conformal
    assert 0.0 < r.k_conformal < 1.0
