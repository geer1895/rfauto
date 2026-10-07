"""RP-1 复现卡 1/5：Cohn 交指（S. B. Cohn, 平行耦合线谐振器滤波器/交指口径，
Proc. IRE 1958；精确 J↔x 关系亦见 MYJ 1964 §8.03 同口径）。RP-1 首批
（研究扩充 round19 §一）。

复现范围：Cohn 精确 J↔x 关系（仓内核=oe_templates/render_c3 的
c3_cohn_j_from_x / c3_cohn_x_from_j 与 interdigital_design_from_order 综合
链；#222 反向面：实现已存在，本卡只做"论文数值↔内核输出"对拍）。

来源等级标注（#122 如实）：
- PAPER_FORMULA：论文级公式（Cohn 精确关系，经仓内 lineage 与 MYJ §8.03
  转述链记录；原文 PDF 未核验，页码不虚构——"按名称引用，不虚构页号"）。
- REPO_FROZEN：仓内冻结设计常数（IDEAL_NOMINAL，2026-09-15 注册批锚）。

锚数值表（论文值/公式值 vs 复现值 vs 容差 → 全 PASS，2026-10-02 实测）：
| 锚 | 论文/公式值 | 复现值（内核） | 容差 | 来源 | 判 |
|----|------------|---------------|------|------|----|
| j(x)峰位 x²=(√13−1)/6 → x_max（解析） | 0.658982963 | 0.658982963 | 1e-9 | 公式 | PASS |
| 峰值 J·Z0 = x_max/(1+x_max²+x_max⁴)（解析） | 0.406068 | 0.406068 | 5e-7 | 公式 | PASS |
| 内核反演区间端 x<0.65 的保守上限 J·Z0 | 0.405995 | 0.405995 | 5e-7 | 公式 | PASS |
| 恒等式 (Z0e−Z0o)/(2Z0eZ0o)=x/(Z0(1+x²+x⁴)) | 精确 | ≤8.7e-19 | 1e-12 | 公式 | PASS |
| 匹配恒等式 Z0e·Z0o=Z0²(1+x²+x⁴) | 精确 | ≤4.6e-13 | 1e-9 | 公式 | PASS |
| Pozar 小 x 近似偏差 1−1/(1+x²+x⁴) @x=0.1 | 0.009999 | 0.009999 | 1e-6 | 教材式 | PASS |
| J→x brentq 回程（设计点 x=0.2260255） | 0.2260255 | 0.2260255 | 1e-12 | 公式 | PASS |
| IDEAL_NOMINAL w/res_len/feed_len/gaps（4 位冻结） | 1.1117/17.5252/51.2374/[0.2263,1.3567]² | maxdev 4.30e-5 | 5.05e-5 | REPO_FROZEN | PASS |
| Qe 经典式 g0·g1/FBW vs 矩阵路径 | 17.06933 | 17.06895 | 1e-4 rel | MYJ 窄带式 | PASS |
| k12 经典式 FBW/√(g1g2) vs 矩阵路径 | 0.0515133 | 0.0515136 | 1e-4 rel | MYJ 窄带式 | PASS |

偏差来源分类（RP-1 四件套之一）：本卡全部锚为精确代数恒等式或 4 位冻结
常数，无离散/口径偏差；IDEAL_NOMINAL 的 4.30e-5 属"4 位十进制舍入半格"
（离散-印刷类），x 反演的 brentq 残差属数值离散类（xtol=1e-12）。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot

# 交指设计点（与仓内冻结 IDEAL_NOMINAL 同参：N=3 @2.5GHz FBW5% RL20dB）
_F0_GHZ = 2.5
_FBW = 0.05
_RL_DB = 20.0
_Z0 = 50.0
#: 4 位十进制冻结常数的舍入半格 + 浮点余量（#347 家族"恰等会炸"防线）
_TOL_4DEC = 5.05e-5


def _cohn_identity_dev(x: float) -> tuple[float, float]:
    """独立转录 Cohn 精确关系（论文公式，非内核）：Z0e=Z0(1+x+x²)、
    Z0o=Z0(1−x+x²) 下 |J|=(Z0e−Z0o)/(2Z0eZ0o) 与 Z0e·Z0o=Z0²(1+x²+x⁴)。"""
    ze = _Z0 * (1.0 + x + x * x)
    zo = _Z0 * (1.0 - x + x * x)
    j_paper = (ze - zo) / (2.0 * ze * zo)
    j_kernel = ot.c3_cohn_j_from_x(x, _Z0)
    prod_paper = ze * zo
    prod_expect = _Z0 * _Z0 * (1.0 + x * x + x ** 4)
    return abs(j_kernel - j_paper), abs(prod_paper - prod_expect)


def test_cohn_exact_j_x_identity() -> None:
    """Cohn 精确式逐点恒等（论文公式 vs 内核；预声明 1e-12 / 1e-9）。"""
    for x in (0.05, 0.1, 0.226, 0.4, 0.6):
        dev_j, dev_prod = _cohn_identity_dev(x)
        assert dev_j <= 1e-12, f"x={x}: |J| 恒等式偏差 {dev_j:.2e}"
        assert dev_prod <= 1e-9, f"x={x}: Z0e·Z0o 恒等式偏差 {dev_prod:.2e}"


def test_cohn_peak_analytic() -> None:
    """j(x) 解析峰（d[x/(1+x²+x⁴)]/dx=0 → 3x⁴+x²−1=0）与内核可达上限的
    关系：内核反演区间保守取 x<0.65（峰位 0.6590 之前的单调段），上限
    J·Z0=0.405995 与解析峰 0.406068 差 7.33e-5（如实登记的保守裕度）。"""
    y_peak = (math.sqrt(13.0) - 1.0) / 6.0
    x_peak = math.sqrt(y_peak)
    jz_peak = x_peak / (1.0 + y_peak + y_peak * y_peak)
    assert abs(x_peak - 0.658982963) <= 1e-9
    assert abs(jz_peak - 0.406068) <= 5e-7
    # 内核上限 = 区间端 0.65 处的 j 值（保守，< 解析峰）
    jz_cap = ot.c3_cohn_j_from_x(0.65, _Z0) * _Z0
    assert abs(jz_cap - 0.405995) <= 5e-7
    assert 0.0 < jz_peak - jz_cap <= 1e-4
    # 内核单调段内回程逐位闭合（brentq xtol=1e-12；端点 0.65 本身被内核
    # 严格 < 守卫拒绝——恰等边界如实避开，#347 家族）
    x_back = ot.c3_cohn_x_from_j(ot.c3_cohn_j_from_x(0.6499, _Z0), _Z0)
    assert abs(x_back - 0.6499) <= 1e-12
    # 内核单调区守卫：恰在区间端之上的 J 拒绝（可达上限语义）
    j_above = ot.c3_cohn_j_from_x(0.65, _Z0) * (1.0 + 1e-6)
    with pytest.raises(ValueError, match="单调区"):
        ot.c3_cohn_x_from_j(j_above, _Z0)


def test_cohn_vs_pozar_small_x_approximation() -> None:
    """Pozar 小 x 近似 J≈x/Z0 是 Cohn 精确式的一阶截断：
    J_exact/J_approx = 1/(1+x²+x⁴)；x=0.1 时偏差 0.9999%（论文式 vs 内核）。"""
    x = 0.1
    j_exact = ot.c3_cohn_j_from_x(x, _Z0)
    j_approx = x / _Z0
    ratio_paper = 1.0 / (1.0 + x * x + x ** 4)
    assert abs(j_exact / j_approx - ratio_paper) <= 1e-12
    # 论文锚：x=0.1 → 1−ratio = (x²+x⁴)/(1+x²+x⁴) = 0.009999（6 位代数值）
    assert abs((1.0 - ratio_paper) - 0.009999) <= 1e-6
    assert abs(j_exact / j_approx - 0.990001) <= 1e-6
    # 设计量级（x≈0.226）偏差 5.0961%——精确式与近似式的量级分离证据
    x2 = 0.22602553304621395
    r2 = 1.0 / (1.0 + x2 * x2 + x2 ** 4)
    assert abs(ot.c3_cohn_j_from_x(x2, _Z0) / (x2 / _Z0) - r2) <= 1e-12
    assert abs((1.0 - r2) - 0.050961) <= 1e-6


def test_cohn_x_roundtrip_design_point() -> None:
    """J→x brentq 精确反演回程（设计点 x=0.2260255，预声明 1e-12）。"""
    x_design = 0.22602553304621395
    x_back = ot.c3_cohn_x_from_j(ot.c3_cohn_j_from_x(x_design, _Z0), _Z0)
    assert abs(x_back - x_design) <= 1e-12


def test_interdigital_design_recovers_frozen_nominal() -> None:
    """现散件→复现卡：设计链逐值回收 4 位冻结常数 IDEAL_NOMINAL
    （interdigital 模板 2026-09-15 注册锚；预声明容差 5.05e-5）。"""
    d = ot.interdigital_design_from_order(3, _F0_GHZ, _FBW, _RL_DB)
    assert abs(d["w_mm"] - 1.1117) <= _TOL_4DEC
    assert abs(d["res_len_mm"] - 17.5252) <= _TOL_4DEC
    assert abs(d["feed_len_mm"] - 51.2374) <= _TOL_4DEC
    for got, want in zip(d["gaps_mm"], (0.2263, 1.3567, 1.3567, 0.2263),
                         strict=True):
        assert abs(got - want) <= _TOL_4DEC


def test_interdigital_qe_k_vs_classical_g_relations() -> None:
    """MYJ 窄带倒置器关系的经典式回收（论文公式 vs 内核矩阵路径）：
    Qe=g0·g1/FBW、k_ij=FBW/√(g_i·g_j)——N=3/RL20 实测互检偏差 ~2e-5 量级
    （render_c3 段首登记的 3e-5 级一致性），预声明 1e-4 rel。"""
    d = ot.interdigital_design_from_order(3, _F0_GHZ, _FBW, _RL_DB)
    g1, g2 = d["g_list"][1], d["g_list"][2]
    qe_classical = g1 / _FBW  # g0=1
    k_classical = _FBW / math.sqrt(g1 * g2)
    assert abs(d["qe_in"] / qe_classical - 1.0) <= 1e-4
    assert abs(d["qe_out"] / qe_classical - 1.0) <= 1e-4
    for k_kernel in d["k_list"]:
        assert abs(k_kernel / k_classical - 1.0) <= 1e-4
    # 论文锚（4 位）：Qe=17.0693、k12=0.0515（render_c3 段首登记值同源）
    assert abs(qe_classical - 17.0693) <= _TOL_4DEC
    assert abs(k_classical - 0.0515) <= 5.05e-5


def test_cohn_j_monotone_below_peak() -> None:
    """j(x) 在单调段严格递增（Cohn 式的可达域结构；独立数值检查）。"""
    xs = np.linspace(0.02, 0.6, 59)
    js = [ot.c3_cohn_j_from_x(float(x), _Z0) for x in xs]
    assert all(b > a for a, b in pairwise(js))
