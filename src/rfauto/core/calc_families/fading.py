"""fading 族（AP-7 多径衰落统计包，§A-9，2026-10-02，追加尾位）。

内核在 core/fading.py（纯函数零 IO），本模块只做注册薄壳（同
propagation/link 惯例）。双键：fade_outage_percent（Rice/Rayleigh/
Nakagami-m/对数正态小尺度衰落 CDF 族）+ availability_margin（可用性↔
衰落裕量双向换算，Vigants-Barnett 简式 vs ITU-R P.530-18 正式式同参
差异带如实报告）。vigants_barnett_outage 为纯辅助不注册（被
availability_margin 内含，单参直算场景走 core 函数）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "fade_outage_percent",
    "AP-7 小尺度/阴影衰落中断概率 [%]（P(接收功率 < 中值−margin_db)，"
    "功率门限相对平均功率归一）：kind='rice' 走非中心 χ² CDF"
    "（≡1−Marcum-Q1，scipy.special.chndtr 等价路径，K 线性值，K→0"
    " 退化为 Rayleigh 实测 3e-17）；'rayleigh' 闭式 1−exp(−h)；"
    "'nakagami' 走正则化不完全 Gamma P(m,mh)（m≥0.5，m=1≡Rayleigh）；"
    "'lognormal' 对数正态阴影 0.5·erfc(M/(σ√2))（M=σ 时 15.87% 锚）",
    (("margin_db", "float dB 衰落裕量（≥0，相对中值/平均功率）"),
     ("kind", "str 'rice'/'rayleigh'/'nakagami'/'lognormal'（默认 'rice'）"),
     ("k", "float Rice K 因子线性值（≥0，默认 10.0≈10dB；仅 rice 用）"),
     ("m", "float Nakagami-m（≥0.5，默认 1.0；仅 nakagami 用）"),
     ("sigma_db", "float 对数正态阴影标准差 dB（>0，默认 8.0；仅 "
      "lognormal 用）")),
    required=("margin_db",),
)
def fade_outage_percent(
    margin_db: float,
    kind: str = "rice",
    k: float = 10.0,
    m: float = 1.0,
    sigma_db: float = 8.0,
) -> dict:
    from rfauto.core.fading import fade_outage_percent as _outage

    percent = _outage(margin_db, kind=kind, k=k, m=m, sigma_db=sigma_db)
    return {
        "outage_percent": percent,
        "outage_fraction": percent / 100.0,
        "kind": kind,
        "margin_db": float(margin_db),
        "time_base": "瞬时衰落统计（分布特性，不随时基/最差月口径）",
    }


@register_calculator(
    "availability_margin",
    "AP-7 可用性↔衰落裕量双向换算+双模型同参差异带（平均最差月）："
    "Vigants-Barnett 简式（Barnett 1972 BSTJ 51(2) §6.3 一手核，"
    "P=c·(f/4)·1e-5·D_mi³·10^(−F/10)，climate 四档 4/1/0.5(UNVERIFIED)"
    "/0.25）vs ITU-R P.530-18 正式式（§2.3.1 式(7) 文本层逐位核，"
    "K·d^3.51·(f²+13)^0.447·10^(几何/气象指数−A/10)）。availability_"
    "percent 与 fade_margin_db 二选一；diff_band 如实记录两式差异"
    "（不设对错门）；P.530 侧 log10_k 缺省 −2.0 为典型温带占位 "
    "UNVERIFIED（LogK.csv 网格零捆绑）",
    (("f_ghz", "float GHz 载波频率（>0）"),
     ("d_km", "float km 路径长度（>0；P.530 侧 d≤5km 记 0 中断）"),
     ("climate", "str 'over_water'/'average'/'rough'/'dry_mountain'"
      "（默认 'average'，V-B 侧 c 档）"),
     ("availability_percent", "float (0,100) 开区间目标时间可用度"
      "（与 fade_margin_db 二选一）"),
     ("fade_margin_db", "float dB 衰落裕量（≥0；与 availability_"
      "percent 二选一）"),
     ("log10_k", "float P.530-18 地理气候因子 K[%] 的常用对数"
      "（默认 -2.0 典型温带占位 UNVERIFIED）"),
     ("eps_p_mrad", "float mrad 路径倾角 |εp|（≥0，默认 10.0）"),
     ("hc_m", "float m 平均路径地形净空 hc（默认 500.0）"),
     ("h_l_m", "float m 较低天线海拔 hL（默认 100.0）"),
     ("vsr", "float 亚折射参数 v_sr（≥0，默认 0.0=无亚折射修正）")),
    required=("f_ghz", "d_km"),
)
def availability_margin(
    f_ghz: float,
    d_km: float,
    climate: str = "average",
    availability_percent: float | None = None,
    fade_margin_db: float | None = None,
    log10_k: float = -2.0,
    eps_p_mrad: float = 10.0,
    hc_m: float = 500.0,
    h_l_m: float = 100.0,
    vsr: float = 0.0,
) -> dict:
    from rfauto.core.fading import availability_margin as _margin

    return _margin(
        f_ghz,
        d_km,
        climate,
        availability_percent=availability_percent,
        fade_margin_db=fade_margin_db,
        log10_k=log10_k,
        eps_p_mrad=eps_p_mrad,
        hc_m=hc_m,
        h_l_m=h_l_m,
        vsr=vsr,
    )
