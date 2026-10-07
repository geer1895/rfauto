"""AP-6 ITU 大气/雨衰包（规格深案 §A-8，2026-10-02）。

传播域主线第二件：ITU-R P.676-13 Annex 1 逐线大气吸收 + P.838-3 雨衰
specific attenuation + P.618 R0.01 入口占位。**纯函数零 IO**、单位显式、
零求解器依赖（§A 包跨件裁决）。PV-011 路线：Annex 1 自算零外部数据+
手工录入系数表，**不捆绑任何 ITU 数据文件**。

状态（2026-10-02 AP-8 录入批；式面=AP-6 骨架批逐式核verify）
------------------------------
式实现已**逐式对照官方 PDF 视觉核verify**（runs/ap6/ 本地证据：
R-REC-P.676-13.pdf 32 页 / R-REC-P.838-3.pdf 8 页 + eq*.png 渲染）。
系数表已**逐值录入并验证**（AP-8 批，证据 runs/ap8）：P.676-13
Table 1 全 44 行 + Table 2 全 35 行（含 1780GHz 伪线）经 pypdf 文本层
机械抽取 + 前席 dump 逐 token 对拍 all-equal（553 值）+ 187dpi PNG
视觉抽检；P.838-3 Tables 1-4 四组系数另经官方 **Table 5 全量 116 频点
对拍 max rel dev 0.112%**（≤ 4 位有效数字印刷舍入界，脚本
runs/ap8/crosscheck_838.py）。P.837 R0.01 系数仍 UNVERIFIED（ITU 数据
文件不捆绑，PV-011）：rain_rate_r001_mmh 维持显式 ValueError 占位。

P.676-13 Annex 1 式面（已逐式核verify，式号按 P.676-13 原文）：
- 式(1)：γ = 0.1820·f·N″(f) [dB/km]，f(GHz)；N″ = N″Oxygen + N″WaterVapour
- 式(2a/2b)：N″O = ΣS_iF_i + N″D；N″W = ΣS_iF_i（Table 1/2 全谱线求和）
- 式(3)：线强 S_i = a1×10⁻⁷·p·θ³·exp[a2(1−θ)]（O2）/
    b1×10⁻¹·e·θ^3.5·exp[b2(1−θ)]（H2O）。**注意指数无前导负号**——PDF
    200dpi 渲染与文本层双重独立读均无负号（53GHz 线 Boltzmann 方向
    交叉核验一致：T<300K 变弱），勿按旧版记忆写 exp[−a2(1−θ)]。
- 式(4)：e = ρ·T/216.7 [hPa]（ρ=水汽密度 g/m³，T=K）
- 式(6a)：线宽 Δf = a3×10⁻⁴·(p·θ^(0.8−a4) + 1.1·e·θ)（O2）/
    b3×10⁻⁴·(p·θ^b4 + b5·e·θ^b6)（H2O）。**P.676-13 新形式**，与
    P.676-11 旧式 a3(p(1+1.1e))θ^a4 不同，勿混用。
- 式(6b)：Zeeman/Doppler 修正 Δf' = √(Δf²+2.25×10⁻⁶)（O2）/
    0.535Δf + √(0.217Δf² + 2.1316×10⁻¹²·f_i²/θ)（H2O）
- 式(5)：线形 F_i = (f/f_i)·[（Δf−δ(f_i−f))/((f_i−f)²+Δf²)
    + (Δf−δ(f_i+f))/((f_i+f)²+Δf²)]（**双镜像项** Van Vleck-Weisskopf）
- 式(7)：δ = (a5+a6θ)×10⁻⁴·(p+e)·θ^0.8（O2）；H2O δ=0
- 式(8/9)：干空气连续谱 N″D = f·p·θ²·[6.14×10⁻⁵/(d(1+(f/d)²))
    + 1.4×10⁻¹²·p^1.5/(1+1.9×10⁻⁵·f^1.5)]，d = 5.6×10⁻⁴(p+e)θ^0.8
约定：θ=300/T；p=干空气分压 [hPa]（总压 ptot=p+e）；有效域 f≤1000GHz
（Annex 1 原文 "up to 1 000 GHz"，任意 p/T/湿度）。

P.838-3 式面（已逐式核verify）：
- 式(1)：γ_R = k·R^α [dB/km]，R(mm/h)
- 式(2)：log10 k = Σ_{j=1..4} a_j·exp[−((log10 f − b_j)/c_j)²] + m_k·log10 f + c_k
- 式(3)：α = Σ_{j=1..5} a_j·exp[−((log10 f − b_j)/c_j)²] + m_α·log10 f + c_α
- f(GHz) 有效域 1–1000 GHz；Table 1-4 给 kH/kV/αH/αV 四组系数
  （4+4+4 / 4+4+4 / 5+5+5 / 5+5+5 个标量 + 各自 m/c 线性修正，
  共 62 个标量=14+14+17+17）；式(4/5) 圆/线极化插值（τ=倾角，本轮只做 h/v 直取）。
- **任务书勘误**：§A-8 写 "Table 1 29 行 k/α + log-log 插值"——实际
  P.838-3 的规范路径=上述 Gauss 和式（Tables 1-4）；"逐频率 k/α 表+
  插值"对应的是 P.838-3 **Table 5**（1–90+ GHz spot 值，官方定位=
  供式(4)(5)(1) 用的频点系数）与旧版 P.838-1/-2。Table 5 在录入批
  用作 Gauss 和式实现的**独立对拍裁判**（~60 频点全盖 1-1000GHz）。

P.618-13 式面（W4-C P10 批 2026-10-05，已逐式对照官方 PDF 视觉核verify）
--------------------------------------------------------
链路输入契约：R0.01 与 h0（0°C 层年均高度）为**调用方显式输入**——
P.837 雨率图与 P.839-4 冻结层高度均为 ITU 数字地图数据文件（PV-011：
不捆绑），系数/数据面维持占位如实；本批落的是**公式面**（数据无捆绑
也能用本地实测 R0.01/h0 走完整链）。
- §2.2.1.1 长期雨衰链 Step1-10（式号按原文）：
    等效雨高   hR = h0 + 0.36 km（P.839-4 recommends 2 原式）
    斜路径     Ls = (hR−hs)/sinθ（θ≥5°，式(1)）；
               Ls = 2(hR−hs)/[(sin²θ+2(hR−hs)/Re)^{1/2}+sinθ]（θ<5°，式(2)）；
               hR≤hs → 全链雨衰恒 0（原文零分支）
    水平投影   LG = Ls·cosθ（式(3)）
    特定衰减   γR = k·R0.01^α（式(4)，P.838-3 已录入面复用）
    水平缩减   r0.01 = 1/(1+0.78√(LG·γR/f)−0.38(1−e^{−2LG}))（式(5)）
    垂直调整   ζ = atan((hR−hs)/(LG·r0.01))；ζ>θ → LR=LG·r0.01/cosθ，
               否则 LR=(hR−hs)/sinθ；χ=36−|φ|（|φ|<36°）否则 0；
               ν0.01 = 1/(1+√sinθ·(31(1−e^{−θ/(1+χ)})√(LR·γR)/f²−0.45))
    有效路径   LE = LR·ν0.01（式(6)）；A0.01 = γR·LE（式(7)）
    时间百分数 Ap = A0.01·(p/0.01)^{−(0.655+0.033ln p−0.045ln A0.01−β(1−p)sinθ)}
               （式(8)，p∈[0.001,5]%；β 三分支：p≥1% 或 |φ|≥36° → 0；
               p<1% 且 |φ|<36° 且 θ≥25° → −0.005(|φ|−36)；否则再 +1.8−4.25sinθ）
- §2.4.1 幅度闪烁链（θ≥5°，4≤f≤20GHz，式号按原文）：
    Nwet（P.453-13 承接）：e_s = EF·a·exp[(b−t/d)·t/(t+c)]（水：a=6.1121
    b=18.678 c=257.14 d=234.5，−40..+50°C；EF_water=1+10⁻⁴[7.2+P(0.0320+5.9·
    10⁻⁶t²)]）；e = H·e_s/100（式(8)）；N_wet = 72·e/T + 3.75×10⁵·e/T²（式(4)）
    σ_ref = 3.6×10⁻³ + 10⁻⁴·Nwet dB（式(40)）
    L = 2hL/(√(sin²θ+2.35×10⁻⁴)+sinθ) m，hL=1000 m（式(41)）
    Deff = √η·D m（式(42)）；x = 1.22·Deff²·(f/L)（式(43a)）
    g(x) = √(3.86(x²+1)^{11/12}·sin[(11/6)tan⁻¹(1/x)]−7.08x^{5/6})（式(43)；
    根号内 <0 即 x≥7.0 → 闪烁衰落深度恒 0，原文零分支）
    σ = σ_ref·f^{7/12}·g(x)/(sinθ)^{1.2}（式(44)）
    a(p) = −0.061(log10p)³+0.072(log10p)²−1.71log10p+3.0（式(45)，0.01<p≤50）
    A(p) = a(p)·σ dB（式(46)）
- §4.1 雨致交叉极化 XPD（6≤f≤55GHz，θ≤60°，式号按原文）：
    Cf：60logf−28.3（6≤f<9）/ 26logf+4.1（9≤f<36）/ 35.9logf−11.3（36≤f≤55）（式(65)）
    CA = V(f)·log Ap；V(f)：30.8f^{−0.21}（6≤f<9）/ 12.8f^{0.19}（9≤f<20）/
    22.6（20≤f<40）/ 13.0f^{0.15}（40≤f≤55）（式(66)）
    Cτ = −10log[1−0.484(1+cos4τ)]（式(67)；τ=45° 圆极化 → 0）
    Cθ = −40log(cosθ)（式(68)）；Cσ = 0.0053σ²（式(69)；σ=倾角分布有效
    标准差：1%/0.1%/0.01%/0.001% 时间 → 0°/5°/10°/15°）
    XPD_rain = Cf − CA + Cτ + Cθ + Cσ（式(70)）
    C_ice = XPD_rain·(0.3+0.1log p)/2（式(71)）；XPD_p = XPD_rain − C_ice（式(72)）
- Re = 8500 km（有效地球半径，原文符号表）；ζ>θ 判定留 1e-9 相对浮点
  余量（#347 家族"恰等会炸"——天顶角 ζ=θ 恰等须走 else 分支）。

缺口清单（AP-6 骨架批立账；1-3 已由 AP-8 录入批闭合，见上方状态）
--------------------------------------------------------
1. P.676-13 Table 1（O2，印刷页 8-9 = PDF 页索引 9-10）44 行 ×
   (f0, a1..a6)；表文本层 pypdf 可机械抽取（runs/ap6/page9*.txt
   已留 dump；注意 a5/a6 负号=U+2010 形态、b 列 ".70" 前导零省略）。
2. P.676-13 Table 2（H2O，印刷页 9-10 = PDF 页索引 10-12，末行
   1780GHz 伪线）全部行 × (f0, b1..b6)。
3. P.838-3 Tables 1-4（印刷页 2 = PDF 页索引 1）kH/kV/αH/αV 四组
   (a_j, b_j, c_j, m, c)；对拍裁判=Table 5（页索引 4-7）。
4. P.837 系数（R0.01 指数模型）——P.618 R0.01 入口占位待录
   （规格书无逐值来源，PV-011 数据文件不捆绑，维持占位如实）。

参考：规格深案 §A-8；PV-011（ITU-R
建议书免费公开，本模块只实现公式+待录系数表结构，零 ITU 数据文件
捆绑，runs/ 下 PDF 仅本地证据不入库）。
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

# ─── 系数表哨位（AP-8 录入批已填充；铁律 7 的守卫语义保留在 _require_*）───────


class OxygenLine(NamedTuple):
    """P.676-13 Table 1 单行（O2 谱线，60GHz 带 44 行之一）。"""

    f0_ghz: float  # 线中心频率 [GHz]
    a1: float  # 线强系数（式(3)，×10⁻⁷ p θ³）
    a2: float  # 线强温度指数（式(3)）
    a3: float  # 线宽系数（式(6a)，×10⁻⁴）
    a4: float  # 线宽温度指数（式(6a)）
    a5: float  # δ 干涉修正系数（式(7)）
    a6: float  # δ 干涉修正系数（式(7)）


class WaterLine(NamedTuple):
    """P.676-13 Table 2 单行（H2O 谱线，含 1780GHz 伪线末行）。"""

    f0_ghz: float  # 线中心频率 [GHz]
    b1: float  # 线强系数（式(3)，×10⁻¹ e θ^3.5）
    b2: float  # 线强温度指数（式(3)，Table 2 中多为负值）
    b3: float  # 线宽系数（式(6a)，×10⁻⁴）
    b4: float  # 线宽温度指数（式(6a)）
    b5: float  # 线宽湿度系数（式(6a)）
    b6: float  # 线宽湿度温度指数（式(6a)）


class RainCoeffs(NamedTuple):
    """P.838-3 单极化系数组（Tables 1-4 之一组，式(2)/(3)）。"""

    k_a: tuple[float, float, float, float]  # 式(2) a_j（j=1..4）
    k_b: tuple[float, float, float, float]  # 式(2) b_j
    k_c: tuple[float, float, float, float]  # 式(2) c_j
    k_m: float  # 式(2) m_k（线性修正斜率）
    k_c0: float  # 式(2) c_k（线性修正截距）
    a_a: tuple[float, float, float, float, float]  # 式(3) a_j（j=1..5）
    a_b: tuple[float, float, float, float, float]  # 式(3) b_j
    a_c: tuple[float, float, float, float, float]  # 式(3) c_j
    a_m: float  # 式(3) m_α
    a_c0: float  # 式(3) c_α


# ─── P.676-13 Table 1/2 + P.838-3 Tables 1-4 逐值（AP-8 录入批 2026-10-02）───
# 来源：runs/ap6/ 官方 PDF 文本层机械抽取（脚本 runs/ap8/extract_evidence.py），
# 前席 dump 逐 token 交叉核对 all-equal（553 值）+ 187dpi PNG 视觉抽检；
# P.838-3 另经 Table 5 全量 116 频点对拍（max rel dev 0.112% ≤ 4 位有效数字
# 印刷舍入界，crosscheck_838.csv）。

_O2_LINES: tuple[OxygenLine, ...] = (
    OxygenLine(50.474214, 0.975, 9.651, 6.69, 0.0, 2.566, 6.85),
    OxygenLine(50.987745, 2.529, 8.653, 7.17, 0.0, 2.246, 6.8),
    OxygenLine(51.50336, 6.193, 7.709, 7.64, 0.0, 1.947, 6.729),
    OxygenLine(52.021429, 14.32, 6.819, 8.11, 0.0, 1.667, 6.64),
    OxygenLine(52.542418, 31.24, 5.983, 8.58, 0.0, 1.388, 6.526),
    OxygenLine(53.066934, 64.29, 5.201, 9.06, 0.0, 1.349, 6.206),
    OxygenLine(53.595775, 124.6, 4.474, 9.55, 0.0, 2.227, 5.085),
    OxygenLine(54.130025, 227.3, 3.8, 9.96, 0.0, 3.17, 3.75),
    OxygenLine(54.67118, 389.7, 3.182, 10.37, 0.0, 3.558, 2.654),
    OxygenLine(55.221384, 627.1, 2.618, 10.89, 0.0, 2.56, 2.952),
    OxygenLine(55.783815, 945.3, 2.109, 11.34, 0.0, -1.172, 6.135),
    OxygenLine(56.264774, 543.4, 0.014, 17.03, 0.0, 3.525, -0.978),
    OxygenLine(56.363399, 1331.8, 1.654, 11.89, 0.0, -2.378, 6.547),
    OxygenLine(56.968211, 1746.6, 1.255, 12.23, 0.0, -3.545, 6.451),
    OxygenLine(57.612486, 2120.1, 0.91, 12.62, 0.0, -5.416, 6.056),
    OxygenLine(58.323877, 2363.7, 0.621, 12.95, 0.0, -1.932, 0.436),
    OxygenLine(58.446588, 1442.1, 0.083, 14.91, 0.0, 6.768, -1.273),
    OxygenLine(59.164204, 2379.9, 0.387, 13.53, 0.0, -6.561, 2.309),
    OxygenLine(59.590983, 2090.7, 0.207, 14.08, 0.0, 6.957, -0.776),
    OxygenLine(60.306056, 2103.4, 0.207, 14.15, 0.0, -6.395, 0.699),
    OxygenLine(60.434778, 2438.0, 0.386, 13.39, 0.0, 6.342, -2.825),
    OxygenLine(61.150562, 2479.5, 0.621, 12.92, 0.0, 1.014, -0.584),
    OxygenLine(61.800158, 2275.9, 0.91, 12.63, 0.0, 5.014, -6.619),
    OxygenLine(62.41122, 1915.4, 1.255, 12.17, 0.0, 3.029, -6.759),
    OxygenLine(62.486253, 1503.0, 0.083, 15.13, 0.0, -4.499, 0.844),
    OxygenLine(62.997984, 1490.2, 1.654, 11.74, 0.0, 1.856, -6.675),
    OxygenLine(63.568526, 1078.0, 2.108, 11.34, 0.0, 0.658, -6.139),
    OxygenLine(64.127775, 728.7, 2.617, 10.88, 0.0, -3.036, -2.895),
    OxygenLine(64.67891, 461.3, 3.181, 10.38, 0.0, -3.968, -2.59),
    OxygenLine(65.224078, 274.0, 3.8, 9.96, 0.0, -3.528, -3.68),
    OxygenLine(65.764779, 153.0, 4.473, 9.55, 0.0, -2.548, -5.002),
    OxygenLine(66.302096, 80.4, 5.2, 9.06, 0.0, -1.66, -6.091),
    OxygenLine(66.836834, 39.8, 5.982, 8.58, 0.0, -1.68, -6.393),
    OxygenLine(67.369601, 18.56, 6.818, 8.11, 0.0, -1.956, -6.475),
    OxygenLine(67.900868, 8.172, 7.708, 7.64, 0.0, -2.216, -6.545),
    OxygenLine(68.431006, 3.397, 8.652, 7.17, 0.0, -2.492, -6.6),
    OxygenLine(68.960312, 1.334, 9.65, 6.69, 0.0, -2.773, -6.65),
    OxygenLine(118.750334, 940.3, 0.01, 16.64, 0.0, -0.439, 0.079),
    OxygenLine(368.498246, 67.4, 0.048, 16.4, 0.0, 0.0, 0.0),
    OxygenLine(424.76302, 637.7, 0.044, 16.4, 0.0, 0.0, 0.0),
    OxygenLine(487.249273, 237.4, 0.049, 16.0, 0.0, 0.0, 0.0),
    OxygenLine(715.392902, 98.1, 0.145, 16.0, 0.0, 0.0, 0.0),
    OxygenLine(773.83949, 572.3, 0.141, 16.2, 0.0, 0.0, 0.0),
    OxygenLine(834.145546, 183.1, 0.145, 14.7, 0.0, 0.0, 0.0),
)

_WV_LINES: tuple[WaterLine, ...] = (
    WaterLine(22.23508, 0.1079, 2.144, 26.38, 0.76, 5.087, 1.0),
    WaterLine(67.80396, 0.0011, 8.732, 28.58, 0.69, 4.93, 0.82),
    WaterLine(119.99594, 0.0007, 8.353, 29.48, 0.7, 4.78, 0.79),
    WaterLine(183.310087, 2.273, 0.668, 29.06, 0.77, 5.022, 0.85),
    WaterLine(321.22563, 0.047, 6.179, 24.04, 0.67, 4.398, 0.54),
    WaterLine(325.152888, 1.514, 1.541, 28.23, 0.64, 4.893, 0.74),
    WaterLine(336.227764, 0.001, 9.825, 26.93, 0.69, 4.74, 0.61),
    WaterLine(380.197353, 11.67, 1.048, 28.11, 0.54, 5.063, 0.89),
    WaterLine(390.134508, 0.0045, 7.347, 21.52, 0.63, 4.81, 0.55),
    WaterLine(437.346667, 0.0632, 5.048, 18.45, 0.6, 4.23, 0.48),
    WaterLine(439.150807, 0.9098, 3.595, 20.07, 0.63, 4.483, 0.52),
    WaterLine(443.018343, 0.192, 5.048, 15.55, 0.6, 5.083, 0.5),
    WaterLine(448.001085, 10.41, 1.405, 25.64, 0.66, 5.028, 0.67),
    WaterLine(470.888999, 0.3254, 3.597, 21.34, 0.66, 4.506, 0.65),
    WaterLine(474.689092, 1.26, 2.379, 23.2, 0.65, 4.804, 0.64),
    WaterLine(488.490108, 0.2529, 2.852, 25.86, 0.69, 5.201, 0.72),
    WaterLine(503.568532, 0.0372, 6.731, 16.12, 0.61, 3.98, 0.43),
    WaterLine(504.482692, 0.0124, 6.731, 16.12, 0.61, 4.01, 0.45),
    WaterLine(547.67644, 0.9785, 0.158, 26.0, 0.7, 4.5, 1.0),
    WaterLine(552.02096, 0.184, 0.158, 26.0, 0.7, 4.5, 1.0),
    WaterLine(556.935985, 497.0, 0.159, 30.86, 0.69, 4.552, 1.0),
    WaterLine(620.700807, 5.015, 2.391, 24.38, 0.71, 4.856, 0.68),
    WaterLine(645.766085, 0.0067, 8.633, 18.0, 0.6, 4.0, 0.5),
    WaterLine(658.00528, 0.2732, 7.816, 32.1, 0.69, 4.14, 1.0),
    WaterLine(752.033113, 243.4, 0.396, 30.86, 0.68, 4.352, 0.84),
    WaterLine(841.051732, 0.0134, 8.177, 15.9, 0.33, 5.76, 0.45),
    WaterLine(859.965698, 0.1325, 8.055, 30.6, 0.68, 4.09, 0.84),
    WaterLine(899.303175, 0.0547, 7.914, 29.85, 0.68, 4.53, 0.9),
    WaterLine(902.611085, 0.0386, 8.429, 28.65, 0.7, 5.1, 0.95),
    WaterLine(906.205957, 0.1836, 5.11, 24.08, 0.7, 4.7, 0.53),
    WaterLine(916.171582, 8.4, 1.441, 26.73, 0.7, 5.15, 0.78),
    WaterLine(923.112692, 0.0079, 10.293, 29.0, 0.7, 5.0, 0.8),
    WaterLine(970.315022, 9.009, 1.919, 25.5, 0.64, 4.94, 0.67),
    WaterLine(987.926764, 134.6, 0.257, 29.85, 0.68, 4.55, 0.9),
    WaterLine(1780.0, 17506.0, 0.952, 196.3, 2.0, 24.15, 5.0),
)

_RAIN_COEFFS: dict[str, RainCoeffs] = {
    "h": RainCoeffs(
        k_a=(-5.3398, -0.35351, -0.23789, -0.94158),
        k_b=(-0.10008, 1.2697, 0.86036, 0.64552),
        k_c=(1.13098, 0.454, 0.15354, 0.16817),
        k_m=-0.18961, k_c0=0.71147,
        a_a=(-0.14318, 0.29591, 0.32177, -5.3761, 16.1721),
        a_b=(1.82442, 0.77564, 0.63773, -0.9623, -3.2998),
        a_c=(-0.55187, 0.19822, 0.13164, 1.47828, 3.4399),
        a_m=0.67849, a_c0=-1.95537,
    ),
    "v": RainCoeffs(
        k_a=(-3.80595, -3.44965, -0.39902, 0.50167),
        k_b=(0.56934, -0.22911, 0.73042, 1.07319),
        k_c=(0.81061, 0.51059, 0.11899, 0.27195),
        k_m=-0.16398, k_c0=0.63297,
        a_a=(-0.07771, 0.56727, -0.20238, -48.2991, 48.5833),
        a_b=(2.3384, 0.95545, 1.1452, 0.791669, 0.791459),
        a_c=(-0.76284, 0.54039, 0.26809, 0.116226, 0.116479),
        a_m=-0.053739, a_c0=0.83433,
    ),
}

_F_MAX_GHZ_676 = 1000.0  # P.676-13 Annex 1 有效域上限（原文 "up to 1 000 GHz"）
_F_MIN_GHZ_838, _F_MAX_GHZ_838 = 1.0, 1000.0  # P.838-3 有效域（原文 1–1000 GHz）


def has_676_tables() -> bool:
    """P.676-13 Table 1/2 逐值是否已录入（骨架批恒 False）。"""
    return bool(_O2_LINES) and bool(_WV_LINES)


def has_838_coeffs() -> bool:
    """P.838-3 Tables 1-4 系数是否已录入（骨架批恒 False；h/v 两极化须齐）。"""
    return "h" in _RAIN_COEFFS and "v" in _RAIN_COEFFS


def data_status() -> dict[str, str]:
    """系数表录入状态（服务层/能力卡透出用；诚实 UNVERIFIED 口径）。"""
    return {
        "p676_o2_table1": "verified" if _O2_LINES else "unverified",
        "p676_wv_table2": "verified" if _WV_LINES else "unverified",
        "p838_rain_coeffs": "verified" if _RAIN_COEFFS else "unverified",
        "p837_r001_coeffs": "unverified",  # 无结构位，纯入口占位
    }


# ─── 输入守卫（本地私有，风格同 core/propagation.py；bool 显式拒收）──────────


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _require_676_tables() -> None:
    raise ValueError(
        "P.676-13 Table 1（O2 44 行）与 Table 2（H2O 全行）谱线逐值系数 "
        "UNVERIFIED（规格书 §A-8 仅清单无逐值，铁律 7 拒绝产数）：需录入 "
        "O2 44 行 (f0,a1..a6) + H2O 全行 (f0,b1..b6)（官方 PDF 页索引 9-12，"
        "证据 runs/ap6/，缺口清单见模块 docstring）"
    )


def _require_838_coeffs() -> None:
    raise ValueError(
        "P.838-3 Tables 1-4 k/α 系数 UNVERIFIED（铁律 7 拒绝产数）：需录入 "
        "kH/kV/αH/αV 四组 (a_j,b_j,c_j,m,c) 共 62 标量（官方 PDF 页索引 1，"
        "对拍裁判=Table 5 spot 值，缺口清单见模块 docstring）"
    )


# ─── P.676-13 Annex 1 内部机件（私有纯函数；式号=原文，已逐式核verify）────────


def _line_shape_5(f_ghz: float, f0_ghz: float, df_ghz: float, delta: float) -> float:
    """式(5) 线形因子 F_i（双镜像项 Van Vleck-Weisskopf；f/f_i 预因子）。"""
    lo = f0_ghz - f_ghz
    hi = f0_ghz + f_ghz
    first = (df_ghz - delta * lo) / (lo * lo + df_ghz * df_ghz)
    second = (df_ghz - delta * hi) / (hi * hi + df_ghz * df_ghz)
    return (f_ghz / f0_ghz) * (first + second)


def _width_6b_o2(df_ghz: float) -> float:
    """式(6b) O2：Zeeman 分裂地板 Δf' = √(Δf² + 2.25×10⁻⁶)。"""
    return math.sqrt(df_ghz * df_ghz + 2.25e-6)


def _width_6b_wv(df_ghz: float, f0_ghz: float, theta: float) -> float:
    """式(6b) H2O：Doppler 展宽 0.535Δf + √(0.217Δf² + 2.1316×10⁻¹²·f_i²/θ)。"""
    return 0.535 * df_ghz + math.sqrt(
        0.217 * df_ghz * df_ghz + 2.1316e-12 * f0_ghz * f0_ghz / theta
    )


def _delta_7_o2(a5: float, a6: float, p_hpa: float, e_hpa: float, theta: float) -> float:
    """式(7) O2 干涉修正 δ = (a5+a6θ)×10⁻⁴·(p+e)·θ^0.8（H2O 恒 0）。"""
    return (a5 + a6 * theta) * 1e-4 * (p_hpa + e_hpa) * theta**0.8


def _dry_continuum_89(f_ghz: float, p_hpa: float, e_hpa: float, theta: float) -> float:
    """式(8/9) 干空气连续谱 N″D（Debye 非谐振谱 + 压致 N₂ 吸收）。

    d = 5.6×10⁻⁴(p+e)θ^0.8；N″D = f·p·θ²·[6.14×10⁻⁵/(d(1+(f/d)²))
    + 1.4×10⁻¹²·p^1.5/(1+1.9×10⁻⁵·f^1.5)]。
    """
    d = 5.6e-4 * (p_hpa + e_hpa) * theta**0.8
    debye = 6.14e-5 / (d * (1.0 + (f_ghz / d) ** 2))
    n2 = 1.4e-12 * p_hpa**1.5 / (1.0 + 1.9e-5 * f_ghz**1.5)
    return f_ghz * p_hpa * theta * theta * (debye + n2)


def _gamma_dry_wet(
    f_ghz: float,
    p_hpa: float,
    theta: float,
    e_hpa: float,
    o2_lines: tuple[OxygenLine, ...],
    wv_lines: tuple[WaterLine, ...],
) -> tuple[float, float]:
    """式(1)/(2a)/(2b) 装配：返回 (γ_dry, γ_wet) [dB/km]。

    输入谱线表显式传参（公共函数供模块哨位表，测试可注合成表验机件）。
    """
    n_d = _dry_continuum_89(f_ghz, p_hpa, e_hpa, theta)
    n_o = n_d
    for ln in o2_lines:
        df = ln.a3 * 1e-4 * (
            p_hpa * theta ** (0.8 - ln.a4) + 1.1 * e_hpa * theta
        )  # 式(6a) O2
        df = _width_6b_o2(df)  # 式(6b)
        delta = _delta_7_o2(ln.a5, ln.a6, p_hpa, e_hpa, theta)  # 式(7)
        s = ln.a1 * 1e-7 * p_hpa * theta**3 * math.exp(ln.a2 * (1.0 - theta))  # 式(3)
        n_o += s * _line_shape_5(f_ghz, ln.f0_ghz, df, delta)
    n_w = 0.0
    for ln in wv_lines:
        df = ln.b3 * 1e-4 * (
            p_hpa * theta ** ln.b4 + ln.b5 * e_hpa * theta ** ln.b6
        )  # 式(6a) H2O
        df = _width_6b_wv(df, ln.f0_ghz, theta)  # 式(6b)
        s = ln.b1 * 1e-1 * e_hpa * theta**3.5 * math.exp(ln.b2 * (1.0 - theta))  # 式(3)
        n_w += s * _line_shape_5(f_ghz, ln.f0_ghz, df, 0.0)  # H2O δ=0
    return 0.1820 * f_ghz * n_o, 0.1820 * f_ghz * n_w


def gamma_gasses_db_per_km(
    f_hz: float, p_hpa: float, t_k: float, rho_wv_g_m3: float
) -> float:
    """大气气体 specific attenuation γ [dB/km]（P.676-13 Annex 1 逐线求和）。

    参数：f_hz 频率 [Hz]（有效域 (0, 1000GHz]，域外 ValueError）；
    p_hpa **干空气**分压 [hPa]（P.676 约定，总压 ptot=p+e）；t_k 温度 [K]；
    rho_wv_g_m3 水汽密度 [g/m³]（0=干空气）。

    系数表已逐值录入（AP-8 批，验证链见模块 docstring 与 runs/ap8）；
    量级锚 γO(60GHz,1013hPa,15℃)≈15、γW(22.235GHz,7.5g/m³)≈0.19 见测试
    （窗值先于落表钉死，#122）。
    """
    f_ghz = _num(f_hz, "f_hz") / 1e9
    p = _num(p_hpa, "p_hpa")
    t = _num(t_k, "t_k")
    rho = _num(rho_wv_g_m3, "rho_wv_g_m3")
    if f_ghz <= 0.0 or f_ghz > _F_MAX_GHZ_676:
        raise ValueError(
            f"f_hz 有效域 (0, {_F_MAX_GHZ_676:.0f}GHz]（P.676-13 Annex 1），得 {f_hz}")
    if p <= 0.0:
        raise ValueError(f"p_hpa 必须 > 0（干空气分压），得 {p}")
    if t <= 0.0:
        raise ValueError(f"t_k 必须 > 0，得 {t}")
    if rho < 0.0:
        raise ValueError(f"rho_wv_g_m3 必须 >= 0（干空气传 0），得 {rho}")
    if not has_676_tables():
        _require_676_tables()
    theta = 300.0 / t
    e = rho * t / 216.7  # 式(4)
    g_dry, g_wet = _gamma_dry_wet(f_ghz, p, theta, e, _O2_LINES, _WV_LINES)
    return g_dry + g_wet


# ─── P.838-3 雨衰（式(1)/(2)/(3)；Tables 1-4 系数 AP-8 批已录入）──────────────


def _gauss_sum_logf(
    f_ghz: float,
    a: tuple[float, ...],
    b: tuple[float, ...],
    c: tuple[float, ...],
    m: float,
    c0: float,
) -> float:
    """P.838-3 式(2)/(3) 公共形：Σ a_j·exp[−((log10 f − b_j)/c_j)²] + m·log10 f + c0。"""
    lf = math.log10(f_ghz)
    s = 0.0
    for aj, bj, cj in zip(a, b, c, strict=True):
        q = (lf - bj) / cj
        s += aj * math.exp(-q * q)
    return s + m * lf + c0


def _rain_k_alpha(f_ghz: float, coeffs: RainCoeffs) -> tuple[float, float]:
    """式(2)/(3)：返回 (k, α)。"""
    log_k = _gauss_sum_logf(f_ghz, coeffs.k_a, coeffs.k_b, coeffs.k_c,
                            coeffs.k_m, coeffs.k_c0)
    alpha = _gauss_sum_logf(f_ghz, coeffs.a_a, coeffs.a_b, coeffs.a_c,
                            coeffs.a_m, coeffs.a_c0)
    return 10.0**log_k, alpha


def gamma_rain_db_per_km(
    f_ghz: float, rain_rate_mmh: float, pol: str = "h"
) -> float:
    """雨衰 specific attenuation γ_R [dB/km]（P.838-3 式(1) γ_R=k·R^α）。

    参数：f_ghz 频率 [GHz]（有效域 [1, 1000]，域外 ValueError）；
    rain_rate_mmh 雨率 R [mm/h]（0 合法 → 0.0，无雨无衰减，不触系数守卫）；
    pol "h"/"v"（水平/垂直极化 → kH/kV 表）。

    Tables 1-4 系数已逐值录入（AP-8 批）：经官方 Table 5 全量 116 频点
    对拍验证（max rel dev 0.112%，证据 runs/ap8/crosscheck_838.csv）。
    """
    f = _num(f_ghz, "f_ghz")
    r = _num(rain_rate_mmh, "rain_rate_mmh")
    if pol not in ("h", "v"):
        raise ValueError(f"pol 只收 'h'/'v'，得 {pol!r}")
    if not (_F_MIN_GHZ_838 <= f <= _F_MAX_GHZ_838):
        raise ValueError(
            f"f_ghz 有效域 [{_F_MIN_GHZ_838:.0f},{_F_MAX_GHZ_838:.0f}]GHz"
            f"（P.838-3），得 {f_ghz}")
    if r < 0.0:
        raise ValueError(f"rain_rate_mmh 必须 >= 0，得 {r}")
    if r == 0.0:
        return 0.0  # 无雨恒无衰减（不需系数，非产数路径）
    if not has_838_coeffs():
        _require_838_coeffs()
    k, alpha = _rain_k_alpha(f, _RAIN_COEFFS[pol])
    return k * r**alpha  # 式(1)


def rain_attenuation_db(
    f_ghz: float, rain_rate_mmh: float, path_len_km: float, pol: str = "h"
) -> float:
    """路径雨衰 A = γ_R × d [dB]（P.618 完整链路含缩减因子 r——后续批）。

    path_len_km 路径长 [km]（>0）。系数录入与验证状态同
    gamma_rain_db_per_km（γ_R×d 的 d>0 守卫先行，无雨 R=0 → 0.0）。
    """
    d = _num(path_len_km, "path_len_km")
    if d <= 0.0:
        raise ValueError(f"path_len_km 必须 > 0，得 {d}")
    return gamma_rain_db_per_km(f_ghz, rain_rate_mmh, pol=pol) * d


def rain_rate_r001_mmh() -> float:
    """R0.01（年均 0.01% 时间超越雨率）入口占位（P.618-13 §1/P.837 系）。

    P.837 系指数/统计模型的系数来自 ITU-R 数据文件（PV-011：不再分发
    捆绑）——系数表 UNVERIFIED，本占位显式 ValueError 拒产数；录入批
    按 P.837 现行版逐值落表后按其正式式实现（签名随实现定，禁凭想象
    预写 API，#215）。
    """
    raise ValueError(
        "P.837 R0.01 模型系数 UNVERIFIED（ITU 数据文件不捆绑，PV-011；"
        "铁律 7 拒绝产数）——待录入批按 P.837 现行版落表后实现"
    )


# ─── P.618-13 全链（W4-C P10 批 2026-10-05；式号=原文，逐式核verify）──────────
#
# 输入契约：R0.01 与 h0 为调用方显式输入（P.837/P.839 数字地图数据文件
# PV-011 不捆绑；本地实测/气象数据可直接进链）。公式面零新增系数表，
# data_status 契约不动（P.837 占位语义不变）。

#: 有效地球半径 [km]（P.618-13 符号表原文 "effective radius of the Earth (8 500 km)"）
EFFECTIVE_EARTH_RADIUS_KM = 8500.0

#: ζ>θ 判定的浮点余量 [度]（#347 家族：天顶角 ζ=θ 恰等必须走 else 分支，
#: 贴界浮点噪声不许翻分支）。
_ZETA_TOL_DEG = 1e-9

_XPD_CANTING_SIGMA = ((1.0, 0.0), (0.1, 5.0), (0.01, 10.0), (0.001, 15.0))


def effective_rain_height_km(h0_km: float) -> float:
    """等效雨高 hR = h0 + 0.36 km（P.839-4 recommends 2 原式）。

    h0_km 为年均 0°C 层（冻结层）高度 [km]，来自 P.839-4 数字地图或本地
    气象数据——**调用方显式输入**（P.839-4 的 h0 是数据文件不是闭式，
    PV-011 不捆绑；本函数只实现 h0→hR 的 +0.36 km 转换式）。
    """
    h0 = _num(h0_km, "h0_km")
    if h0 <= 0.0:
        raise ValueError(f"h0_km 必须 > 0（冻结层高度），得 {h0}")
    return h0 + 0.36


def slant_path_rain_km(
    h_r_km: float, h_s_km: float, elevation_deg: float,
    re_km: float = EFFECTIVE_EARTH_RADIUS_KM,
) -> float:
    """雨高以下斜路径长 Ls [km]（P.618-13 式(1)/(2)）。

    θ≥5° 走式(1) Ls=(hR−hs)/sinθ；θ<5° 走式(2)（含 Re 地球曲率项）。
    hR ≤ hs → 返回 0.0（原文零分支：hR−hs≤0 时任意时间百分数雨衰为 0）。
    """
    h_r = _num(h_r_km, "h_r_km")
    h_s = _num(h_s_km, "h_s_km")
    theta = _num(elevation_deg, "elevation_deg")
    re = _num(re_km, "re_km")
    if theta <= 0.0 or theta > 90.0:
        raise ValueError(f"elevation_deg 有效域 (0, 90]，得 {theta}")
    if re <= 0.0:
        raise ValueError(f"re_km 必须 > 0，得 {re}")
    if h_s < 0.0:
        raise ValueError(f"h_s_km 必须 >= 0，得 {h_s}")
    dh = h_r - h_s
    if dh <= 0.0:
        return 0.0  # 原文零分支
    s = math.sin(math.radians(theta))
    if theta >= 5.0:
        return dh / s  # 式(1)
    return 2.0 * dh / (math.sqrt(s * s + 2.0 * dh / re) + s)  # 式(2)


def _vertical_adjust_nu001(
    l_r_km: float, gamma_r: float, f_ghz: float,
    theta_deg: float, chi_deg: float,
) -> float:
    """Step7 ν0.01 = 1/(1+√sinθ·(31(1−e^{−θ/(1+χ)})√(LR·γR)/f²−0.45))。"""
    s = math.sin(math.radians(theta_deg))
    bracket = (
        31.0 * (1.0 - math.exp(-theta_deg / (1.0 + chi_deg)))
        * math.sqrt(l_r_km * gamma_r) / (f_ghz * f_ghz)
        - 0.45
    )
    return 1.0 / (1.0 + math.sqrt(s) * bracket)


def rain_attenuation_r001(
    f_ghz: float,
    r001_mmh: float,
    elevation_deg: float,
    h0_km: float,
    h_s_km: float,
    lat_deg: float,
    *,
    pol: str = "h",
    re_km: float = EFFECTIVE_EARTH_RADIUS_KM,
) -> dict[str, Any]:
    """P.618-13 §2.2.1.1 长期雨衰全链 R0.01 → A0.01（Step1-9，式(1)-(7)）。

    参数：f_ghz 频率 [GHz]（γR 走 P.838-3 已录入面，域 [1,1000]）；
    r001_mmh = R0.01 [mm/h]（0 合法 → 全链 0，无雨零分支）；elevation_deg
    仰角 (0,90]；h0_km 冻结层年均高度 [km]（P.839 数据面，显式输入）；
    h_s_km 站址海拔 [km]（≥0）；lat_deg 纬度 [度]（式内取 |φ|）；pol "h"/"v"。

    返回 dict 全中间量（h_r_km/l_s_km/l_g_km/gamma_r/r001/zeta_deg/l_r_km/
    chi_deg/nu001/l_e_km/a001_db）——链路逐步留痕供对拍与上游消费
    （sat_link rain 项）。hR≤hs 或 R0.01=0 → a001_db=0 且 zero_reason 注记
    （原文零分支，非产数路径）。
    """
    f = _num(f_ghz, "f_ghz")
    r001 = _num(r001_mmh, "r001_mmh")
    theta = _num(elevation_deg, "elevation_deg")
    lat = _num(lat_deg, "lat_deg")
    if theta <= 0.0 or theta > 90.0:
        raise ValueError(f"elevation_deg 有效域 (0, 90]，得 {theta}")
    if r001 < 0.0:
        raise ValueError(f"r001_mmh 必须 >= 0，得 {r001}")
    h_r = effective_rain_height_km(h0_km)
    h_s = _num(h_s_km, "h_s_km")
    if h_s < 0.0:
        raise ValueError(f"h_s_km 必须 >= 0，得 {h_s}")
    out: dict[str, Any] = {
        "f_ghz": f, "r001_mmh": r001, "elevation_deg": theta,
        "h0_km": _num(h0_km, "h0_km"), "h_s_km": h_s, "lat_deg": lat,
        "pol": pol, "h_r_km": h_r, "re_km": _num(re_km, "re_km"),
    }
    if h_r <= h_s:
        out.update({"zero_reason": "h_r<=hs (P.618 Step2 零分支)", "a001_db": 0.0})
        return out
    if r001 == 0.0:
        out.update({"zero_reason": "r001=0 (P.618 Step4 零分支)", "a001_db": 0.0})
        return out
    l_s = slant_path_rain_km(h_r, h_s, theta, re_km=re_km)
    l_g = l_s * math.cos(math.radians(theta))  # Step3 式(3)
    gamma_r = gamma_rain_db_per_km(f, r001, pol=pol)  # Step5 式(4)
    # Step6 式(5) 水平缩减因子
    r_001 = 1.0 / (
        1.0 + 0.78 * math.sqrt(l_g * gamma_r / f) - 0.38 * (1.0 - math.exp(-2.0 * l_g))
    )
    # Step7 垂直调整因子（ζ 恰等/浮点噪声走 else 分支，#347 余量）
    zeta_deg = math.degrees(math.atan((h_r - h_s) / (l_g * r_001)))
    if zeta_deg > theta + _ZETA_TOL_DEG:
        l_r = l_g * r_001 / math.cos(math.radians(theta))
    else:
        l_r = (h_r - h_s) / math.sin(math.radians(theta))
    abs_lat = abs(lat)
    chi_deg = 36.0 - abs_lat if abs_lat < 36.0 else 0.0
    nu001 = _vertical_adjust_nu001(l_r, gamma_r, f, theta, chi_deg)
    l_e = l_r * nu001  # Step8 式(6)
    a001 = gamma_r * l_e  # Step9 式(7)
    out.update({
        "l_s_km": l_s, "l_g_km": l_g, "gamma_r_dbkm": gamma_r,
        "r001_factor": r_001, "zeta_deg": zeta_deg, "l_r_km": l_r,
        "chi_deg": chi_deg, "nu001": nu001, "l_e_km": l_e,
        "a001_db": a001,
    })
    return out


def rain_attenuation_ap(
    a001_db: float, p_percent: float, lat_deg: float, elevation_deg: float,
) -> float:
    """时间百分数换算 A0.01 → Ap（P.618-13 Step10，式(8)，p∈[0.001, 5]%）。

    β 三分支按原文；p=0.01 恒等回 A0.01（(0.01/0.01)^k=1，结构锚）。
    """
    a001 = _num(a001_db, "a001_db")
    p = _num(p_percent, "p_percent")
    lat = _num(lat_deg, "lat_deg")
    theta = _num(elevation_deg, "elevation_deg")
    if not (0.001 <= p <= 5.0):
        raise ValueError(f"p_percent 有效域 [0.001, 5]%（式(8) 声明域），得 {p}")
    if a001 < 0.0:
        raise ValueError(f"a001_db 必须 >= 0，得 {a001}")
    abs_lat = abs(lat)
    if p >= 1.0 or abs_lat >= 36.0:
        beta = 0.0
    elif theta >= 25.0:
        beta = -0.005 * (abs_lat - 36.0)
    else:
        beta = -0.005 * (abs_lat - 36.0) + 1.8 - 4.25 * math.sin(math.radians(theta))
    expo = -(0.655 + 0.033 * math.log(p) - 0.045 * math.log(a001) - beta * (1.0 - p) * math.sin(math.radians(theta)))
    return a001 * (p / 0.01) ** expo


# ─── P.453-13 承接面（闪烁链 Step1-2 需要的 e_s/e/N_wet；式号=P.453-13 原文）──


def saturation_vapour_pressure_hpa(
    t_c: float, p_hpa: float = 1013.25, medium: str = "water",
) -> float:
    """饱和水汽压 e_s [hPa]（P.453-13 式(9)，含 EF 增压修正因子）。

    e_s = EF·a·exp[(b−t/d)·t/(t+c)]；水：a=6.1121/b=18.678/c=257.14/d=234.5
    （有效域 −40..+50°C，原文声明），EF_water = 1+10⁻⁴[7.2+P(0.0320+5.9·
    10⁻⁶t²)]；冰：a=6.1115/b=23.036/c=279.82/d=333.7（−80..0°C），
    EF_ice = 1+10⁻⁴[2.2+P(0.0383+6.4·10⁻⁶t²)]。p_hpa=总大气压 P。
    """
    t = _num(t_c, "t_c")
    p = _num(p_hpa, "p_hpa")
    if p <= 0.0:
        raise ValueError(f"p_hpa 必须 > 0，得 {p}")
    if medium == "water":
        if not (-40.0 <= t <= 50.0):
            raise ValueError(f"水相 e_s 有效域 [−40,+50]°C（原文声明），得 {t}")
        ef = 1.0 + 1e-4 * (7.2 + p * (0.0320 + 5.9e-6 * t * t))
        a, b, c, d = 6.1121, 18.678, 257.14, 234.5
    elif medium == "ice":
        if not (-80.0 <= t <= 0.0):
            raise ValueError(f"冰相 e_s 有效域 [−80,0]°C（原文声明），得 {t}")
        ef = 1.0 + 1e-4 * (2.2 + p * (0.0383 + 6.4e-6 * t * t))
        a, b, c, d = 6.1115, 23.036, 279.82, 333.7
    else:
        raise ValueError(f"medium 只收 'water'/'ice'，得 {medium!r}")
    return ef * a * math.exp((b - t / d) * t / (t + c))


def vapour_pressure_hpa(t_c: float, rh_pct: float, p_hpa: float = 1013.25) -> float:
    """相对湿度 → 水汽压 e = H·e_s/100 [hPa]（P.453-13 式(8)，水相）。"""
    h = _num(rh_pct, "rh_pct")
    if not (0.0 <= h <= 100.0):
        raise ValueError(f"rh_pct 有效域 [0,100]%，得 {h}")
    es = saturation_vapour_pressure_hpa(t_c, p_hpa, medium="water")
    return h * es / 100.0


def refractivity_wet(t_k: float, e_hpa: float) -> float:
    """湿项无线电折射率 N_wet = 72·e/T + 3.75×10⁵·e/T²（P.453-13 式(4)，N-units）。

    t_k 绝对温度 [K]；e_hpa 水汽压 [hPa]。
    """
    t = _num(t_k, "t_k")
    e = _num(e_hpa, "e_hpa")
    if t <= 0.0:
        raise ValueError(f"t_k 必须 > 0，得 {t}")
    if e < 0.0:
        raise ValueError(f"e_hpa 必须 >= 0，得 {e}")
    return 72.0 * e / t + 3.75e5 * e / (t * t)


def scintillation_nwet(t_c: float, rh_pct: float, p_hpa: float = 1013.25) -> float:
    """湿项折射率 Nwet（P.618-13 §2.4.1 Step1-2 → P.453-13 式(9)/(8)/(4)）。

    t_c 月均地表温度 [°C]；rh_pct 月均地表相对湿度 [%]；p_hpa 总压 [hPa]
    （e_s 的 EF 修正用；原文 NOTE1 无实测 t/H 时可用 P.453 Nwet 地图）。
    """
    e = vapour_pressure_hpa(t_c, rh_pct, p_hpa)
    return refractivity_wet(t_c + 273.15, e)


# ─── P.618-13 §2.4.1 幅度闪烁链（θ≥5°，4≤f≤20GHz）────────────────────────────


def scintillation_sigma_ref_db(nwet: float) -> float:
    """参考信号幅度标准差 σ_ref = 3.6×10⁻³ + 10⁻⁴·Nwet [dB]（式(40)）。"""
    n = _num(nwet, "nwet")
    if n < 0.0:
        raise ValueError(f"nwet 必须 >= 0（N-units 湿项非负），得 {n}")
    return 3.6e-3 + 1e-4 * n


def scintillation_std_db(
    f_ghz: float, theta_deg: float, nwet: float, d_m: float, eta: float = 0.5,
) -> float:
    """幅度闪烁信号标准差 σ [dB]（P.618-13 式(40)-(44)，θ≥5°，4≤f≤20GHz）。

    d_m 天线物理直径 [m]；eta 天线效率（原文 "if unknown, η=0.5 is a
    conservative estimate"）。g(x) 根号内 <0（x≥7.0）→ 返回 0.0（原文
    零分支：闪烁衰落深度恒 0）。
    """
    f = _num(f_ghz, "f_ghz")
    theta = _num(theta_deg, "theta_deg")
    d = _num(d_m, "d_m")
    eta_v = _num(eta, "eta")
    if not (4.0 <= f <= 20.0):
        raise ValueError(f"f_ghz 有效域 [4,20]GHz（式面声明域），得 {f}")
    if not (5.0 <= theta <= 90.0):
        raise ValueError(f"theta_deg 有效域 [5,90]°（§2.4.1 声明 θ≥5°），得 {theta}")
    if d <= 0.0:
        raise ValueError(f"d_m 必须 > 0，得 {d}")
    if not (0.0 < eta_v <= 1.0):
        raise ValueError(f"eta 有效域 (0,1]，得 {eta_v}")
    sigma_ref = scintillation_sigma_ref_db(nwet)
    # 式(41) 湍流层有效路径 L（hL=1000 m）
    h_l = 1000.0
    s = math.sin(math.radians(theta))
    length_m = 2.0 * h_l / (math.sqrt(s * s + 2.35e-4) + s)
    # 式(42)/(43a) 有效天线直径与 x
    d_eff = math.sqrt(eta_v) * d
    x = 1.22 * d_eff * d_eff * (f / length_m)
    # 式(43) 天线平均因子 g(x)；根号内 <0 → 原文零分支
    radicand = (
        3.86 * (x * x + 1.0) ** (11.0 / 12.0)
        * math.sin((11.0 / 6.0) * math.atan(1.0 / x))
        - 7.08 * x ** (5.0 / 6.0)
    )
    if radicand < 0.0:
        return 0.0
    g = math.sqrt(radicand)
    # 式(44)
    return sigma_ref * f ** (7.0 / 12.0) * g / s ** 1.2


def scintillation_fade_db(p_percent: float, sigma_db: float) -> float:
    """时间百分数 p 的闪烁衰落深度 A(p) = a(p)·σ [dB]（P.618-13 式(45)/(46)）。

    p ∈ (0.01, 50]%（式(45) 声明域）；σ_db 为 scintillation_std_db 输出。
    """
    p = _num(p_percent, "p_percent")
    sigma = _num(sigma_db, "sigma_db")
    if not (0.01 < p <= 50.0):
        raise ValueError(f"p_percent 有效域 (0.01, 50]%（式(45) 声明域），得 {p}")
    if sigma < 0.0:
        raise ValueError(f"sigma_db 必须 >= 0，得 {sigma}")
    lg = math.log10(p)
    a_p = -0.061 * lg**3 + 0.072 * lg**2 - 1.71 * lg + 3.0  # 式(45)
    return a_p * sigma  # 式(46)


# ─── P.618-13 §4.1 雨致交叉极化 XPD（6≤f≤55GHz，θ≤60°）───────────────────────


def xpd_rain_db(
    f_ghz: float,
    ap_db: float,
    p_percent: float,
    tau_deg: float = 45.0,
    *,
    elevation_deg: float,
) -> float:
    """雨/冰晶致交叉极化鉴别度 XPD_p [dB]（P.618-13 §4.1 式(65)-(72)）。

    f_ghz 频率 [GHz]（声明域 [6,55]）；ap_db = Ap 同百分数共极化雨衰 [dB]
    （>0）；p_percent 时间百分数 [%]（倾角分布有效标准差 σ 只在
    1/0.1/0.01/0.001% 四档有原文值，p 须为其中之一）；tau_deg 线极化电场
    倾角 [度]（圆极化 45°，缺省）；elevation_deg 仰角 [度]（声明域 (0,60]）。
    """
    f = _num(f_ghz, "f_ghz")
    ap = _num(ap_db, "ap_db")
    p = _num(p_percent, "p_percent")
    tau = _num(tau_deg, "tau_deg")
    theta = _num(elevation_deg, "elevation_deg")
    if not (6.0 <= f <= 55.0):
        raise ValueError(f"f_ghz 有效域 [6,55]GHz（§4.1 声明域），得 {f}")
    if ap <= 0.0:
        raise ValueError(f"ap_db 必须 > 0（CA=V(f)·log Ap 需正衰减），得 {ap}")
    if not (0.0 < theta <= 60.0):
        raise ValueError(f"elevation_deg 有效域 (0,60]°（§4.1 声明 θ≤60°），得 {theta}")
    # 式(65) Cf 分段
    if 6.0 <= f < 9.0:
        c_f = 60.0 * math.log10(f) - 28.3
    elif 9.0 <= f < 36.0:
        c_f = 26.0 * math.log10(f) + 4.1
    else:
        c_f = 35.9 * math.log10(f) - 11.3
    # 式(66) CA = V(f)·log Ap
    if 6.0 <= f < 9.0:
        v_f = 30.8 * f ** -0.21
    elif 9.0 <= f < 20.0:
        v_f = 12.8 * f**0.19
    elif 20.0 <= f < 40.0:
        v_f = 22.6
    else:
        v_f = 13.0 * f**0.15
    c_a = v_f * math.log10(ap)
    # 式(67)/(68)/(69)
    c_tau = -10.0 * math.log10(1.0 - 0.484 * (1.0 + math.cos(4.0 * math.radians(tau))))
    c_theta = -40.0 * math.log10(math.cos(math.radians(theta)))
    sigma_cant = None
    for key, val in _XPD_CANTING_SIGMA:
        if abs(p - key) <= 1e-12:
            sigma_cant = val
            break
    if sigma_cant is None:
        raise ValueError(
            f"p_percent 须为 1/0.1/0.01/0.001% 之一（式(69) σ 原文四档），得 {p}")
    c_sigma = 0.0053 * sigma_cant * sigma_cant
    # 式(70)/(71)/(72)
    xpd_rain = c_f - c_a + c_tau + c_theta + c_sigma
    c_ice = xpd_rain * (0.3 + 0.1 * math.log10(p)) / 2.0
    return xpd_rain - c_ice
