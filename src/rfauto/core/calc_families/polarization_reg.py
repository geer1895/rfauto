"""EC-21 极化传输面度量 CALC 注册面薄包装族（aurora_e W4-S18，2026-10-18）。

三键：pol_axial_ratio（轴比标量闭式）/ pol_delta_ipd_il（ΔIPD/ΔIL 传输面
度量主键）/ pol_group_delay_diff（微分群延迟差二点差分）。

**薄注册纪律**（helix_axial_reg 同款）：物理公式单源在
``rfauto.core.polarization``（AP-1 极化指标包 §4.4 闭式 + EC-21 新增
delta_ipd_il/group_delay_diff_ps 纯函数，零 IO）——本模块**只注册不实现**，
零公式复制（#116 死副本教训）。wrapper 是纯委托：入参收敛透传 + dict
字段映射，不做数值变换、不 round——**薄度守卫 = wrapper 输出与 core 直调
逐位一致**（tests/unit/test_polarization_reg.py 逐字段 ``==`` 钉）。

- 出处见 rfauto.core.polarization 模块 docstring（Balanis 4th §4.4 极化
  椭圆：AR/倾角/旋向；IEEE Std 145-1983 旋向；Ludwig-3/XPD/PLF 同模块
  在库不重复注册）。锚树 tests/unit/test_polarization.py（AP-1 在库）+
  tests/unit/test_polarization_reg.py（EC-21 本批：cot 恒等/时域第三法/
  线性相位 τ 回收/等延迟纯转换零差/单源性 #118）。
- 与既有面边界：helix_axial_performance 的 axial_ratio=Kraus 螺旋经验式
  轴上值（天线结构口径，非本键任意两分量极化态口径）；farfield 服务面的
  polarization_state 消费（service 层）不受本族影响——本族只是把 §4.4
  数学面接进 CALC 注册表（EC-21 随 EC-20 PSSFSS/ms_cross 消费面）。
- 诚实边界：pol_group_delay_diff 主值包裹的多周期不可分辨限制（频带须
  单周期推进内）见 core group_delay_diff_ps docstring，wrapper 原样透传。
- aurora_j W4-S13 追加：polarization_loss_factor（PLF 极化失配因子键，
  §4.4.3 同库直取薄注册，见文件尾节；plf=0 时 dB 有限封顶如实）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.polarization import (
    axial_ratio,
    axial_ratio_db,
    axial_ratio_time_domain,
    delta_ipd_il,
    group_delay_diff_ps,
    tilt_angle_deg,
)
from rfauto.core.polarization import (
    polarization_loss_factor as _plf_core,
)

from .registry import register_calculator

_SOURCE = (
    "出处见 rfauto.core.polarization 模块 docstring（Balanis Antenna Theory "
    "4th §4.4 极化椭圆闭式 + IEEE Std 145-1983 旋向；本键为薄注册包装，"
    "公式零复制）"
)


def _deg2rad(value: Any, name: str) -> float:
    """deg→rad 收敛（bool 显式拒收 df7+⑯；有限性校验——thermal._finite 不拒
    bool，float(True)=1.0 静默污染，此处本族自守）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return math.radians(out)


@register_calculator(
    "pol_axial_ratio",
    "极化椭圆轴比闭式（EC-21）：两正交线极化分量幅度 E1/E2 与相位差 "
    "delta_phase_deg → AR=√[(S+√D)/(S−√D)]（Balanis 4th §4.4，S=E1²+E2²、"
    "D=E1⁴+E2⁴+2E1²E2²cos2δ）线性+dB、倾角 τ=½·atan2(2E1E2cosδ, E1²−E2²)、"
    "旋向（IEEE Std 145-1983：δ=−90°=RH 主锚）+ 时域椭圆第三法对照 dB "
    "（#118 双源，闭式 vs 数值 ~1e-10 一致）。线极化 AR 真值发散，按 "
    "AR_LINEAR_DB_CAP=100 dB 封顶如实返回。锚：圆极化 E1=E2,δ=±90° → "
    "AR=1（0 dB）；等幅 δ=45° → AR=1+√2（cot 22.5° 恒等）",
    (("e1", "float 第一正交分量幅度（≥0；θ̂ 或 x̂ 口径，两分量不全零）"),
     ("e2", "float 第二正交分量幅度（≥0）"),
     ("delta_phase_deg", "float ° 相位差 phase(E2)−phase(E1)（任意实数，"
      "闭式按 2δ 周期自然处理）")),
    required=("e1", "e2", "delta_phase_deg"),
)
def pol_axial_ratio(e1: float, e2: float, delta_phase_deg: float) -> dict[str, Any]:
    """薄委托 axial_ratio/axial_ratio_db/tilt_angle_deg（deg→rad 单点换算）。"""
    d_rad = _deg2rad(delta_phase_deg, "delta_phase_deg")
    ar = axial_ratio(e1, e2, d_rad)
    return {
        "ar_linear": ar,
        "ar_db": axial_ratio_db(e1, e2, d_rad),
        "ar_db_time_domain": 20.0 * math.log10(
            axial_ratio_time_domain(e1, e2, d_rad)),
        "tilt_deg": tilt_angle_deg(e1, e2, d_rad),
        "note": (
            "薄注册包装：线极化按 100 dB 封顶（真值发散）；时域第三法为 "
            "#118 对照旁证非主判；旋向/圆极化判别面见 pol_delta_ipd_il"),
        "source": _SOURCE,
    }


@register_calculator(
    "pol_delta_ipd_il",
    "极化传输面 ΔIPD/ΔIL 度量：两正交线极化透射系数 t_x/t_y（[re,im] 服务"
    "复数约定）→ ΔIPD=phase(t_y)−phase(t_x)（主值 (−180°,180°]）、"
    "ΔIL=20log10(|t_y|/|t_x|)（dB）+ §4.4 极化态链（AR/倾角/旋向/regime "
    "三段）。EC-21 主键（随 EC-20 PSSFSS/ms_cross 极化转换面消费）——"
    "线-圆转换面设计判据：ΔIPD→±90° 且 ΔIL→0 dB ⟺ AR→1（0 dB 圆极化，"
    "Balanis §4.4 圆极化条件的传输面对偶）。任一分量为 0 → ValueError"
    "（相位无定义不猜）",
    (("t_x", "float|[re,im] x 极化透射系数（复数；同频同参考基）"),
     ("t_y", "float|[re,im] y 极化透射系数（复数）")),
    required=("t_x", "t_y"),
)
def pol_delta_ipd_il(t_x: Any, t_y: Any) -> dict[str, Any]:
    """薄委托 delta_ipd_il（core 单源，字段原样透传）。"""
    out = delta_ipd_il(t_x, t_y)
    out["note"] = (
        "薄注册包装：AR/旋向链与 §4.4 单源同径（正交线极化对与 (θ̂,φ̂) 基"
        "同构）；regime=3/20 dB 工程惯例三段非标准强约束")
    out["source"] = _SOURCE
    return out


@register_calculator(
    "pol_group_delay_diff",
    "极化微分群延迟差（EC-21）：两频点各极化透射系数 → τ_g=−(1/360)·"
    "Δφ_deg/Δf（ps）逐路 + delta_tau_g=τ_gy−τ_gx + 两频点 ΔIPD 与扫频"
    "变化量（二点差分）。诚实边界：主值包裹使各路 [f1,f2] 相位推进 "
    "|Δφ|>180° 的多周期不可分辨（Δτ_g 假归零族）——频带须窄到单周期推进"
    "内（宽带给定须调用方自行去包裹）。锚：线性相位网络 φ=−360·f·τ 回收 "
    "τ 精确；等延迟纯转换（ΔIPD 常数 ±90°）→ delta_tau_g=0",
    (("f1_ghz", "float GHz 频点 1（>0）"),
     ("f2_ghz", "float GHz 频点 2（>f1_ghz）"),
     ("t_x_f1", "float|[re,im] f1 频点 x 极化透射系数"),
     ("t_x_f2", "float|[re,im] f2 频点 x 极化透射系数"),
     ("t_y_f1", "float|[re,im] f1 频点 y 极化透射系数"),
     ("t_y_f2", "float|[re,im] f2 频点 y 极化透射系数")),
    required=("f1_ghz", "f2_ghz", "t_x_f1", "t_x_f2", "t_y_f1", "t_y_f2"),
)
def pol_group_delay_diff(
    f1_ghz: float,
    f2_ghz: float,
    t_x_f1: Any,
    t_x_f2: Any,
    t_y_f1: Any,
    t_y_f2: Any,
) -> dict[str, Any]:
    """薄委托 group_delay_diff_ps（core 单源，字段原样透传）。"""
    out = group_delay_diff_ps(f1_ghz, f2_ghz, t_x_f1, t_x_f2, t_y_f1, t_y_f2)
    out["note"] = (
        "薄注册包装：二点差分=区间平均群延迟（弯相位为平均语义）；主值"
        "包裹多周期不可分辨限制见 core docstring，wrapper 原样透传")
    out["source"] = _SOURCE
    return out


# ─── aurora_j W4-S13：PLF 极化失配因子键（§4.4.3 同库直取薄注册）──────────────
#
# 口径：PLF=|ê_r·ê_t|²（Balanis 4th §4.4.3 + IEEE Std 145-1983；公式单源
# core/polarization.polarization_loss_factor，本面零公式复制）。收发极化态
# 各给 (E1,E2,delta_deg)（两正交分量幅度+相位差，同横截面基），deg→rad 是
# wrapper 唯一数值变换（pol_axial_ratio 同款）。
# 诚实边界：plf=0（正交线/反旋向圆）→ plf_db 真值 −∞，按
# _PLF_ZERO_DB_FLOOR=−300 dB 地板截断（max 语义，浮点近零残留同此一致
# 截断；JSON 安全，core xpd_db 有限封顶同族口径，真值发散语义如实不猜）。

#: plf→0 时 plf_db 的有限地板（真值 −∞；与 core xpd_db cap 同族惯例）。
_PLF_ZERO_DB_FLOOR = -300.0


@register_calculator(
    "polarization_loss_factor",
    "极化失配因子 PLF（W4-S13）：PLF=|ê_r·ê_t|²（Balanis 4th §4.4.3 + "
    "IEEE Std 145-1983 薄注册；公式单源 core/polarization 零复制）。"
    "收发各给极化态 (E1,E2,delta_deg)（两正交分量幅度+相位差，"
    "同横截面基）→ plf_linear∈[0,1] 与 plf_db。经典锚：对齐线 1/正交线 0/"
    "45° 交叉 0.5（−3.0103 dB）/同向圆 1/反向圆 0/圆×线 0.5（−3.0103 dB）。"
    "plf→0 时 plf_db 按 −300 dB 地板截断（真值 −∞，JSON 安全如实）",
    (("e1_rx", "float 收端第一正交分量幅度（≥0）"),
     ("e2_rx", "float 收端第二正交分量幅度（≥0；两分量不全零）"),
     ("delta_rx_deg", "float ° 收端相位差 phase(E2)−phase(E1)（任意实数）"),
     ("e1_tx", "float 发端第一正交分量幅度（≥0）"),
     ("e2_tx", "float 发端第二正交分量幅度（≥0；两分量不全零）"),
     ("delta_tx_deg", "float ° 发端相位差 phase(E2)−phase(E1)（任意实数）")),
    required=("e1_rx", "e2_rx", "delta_rx_deg", "e1_tx", "e2_tx",
              "delta_tx_deg"),
)
def polarization_loss_factor(
    e1_rx: float,
    e2_rx: float,
    delta_rx_deg: float,
    e1_tx: float,
    e2_tx: float,
    delta_tx_deg: float,
) -> dict[str, Any]:
    """薄委托 core polarization_loss_factor（deg→rad 单点换算）。"""
    plf = _plf_core(
        e1_rx, e2_rx, _deg2rad(delta_rx_deg, "delta_rx_deg"),
        e1_tx, e2_tx, _deg2rad(delta_tx_deg, "delta_tx_deg"),
    )
    plf_db = max(10.0 * math.log10(plf) if plf > 0.0 else -math.inf,
                 _PLF_ZERO_DB_FLOOR)
    return {
        "plf_linear": plf,
        "plf_db": plf_db,
        "note": (
            "薄注册包装：plf_db 对 plf→0（正交线/反旋向圆）按 −300 dB 地板"
            "截断（真值 −∞，浮点近零残留一致截断，有限封顶口径同 core "
            "xpd_db）；旋向约定与极化椭圆参数面见 pol_axial_ratio/"
            "pol_delta_ipd_il"),
        "source": _SOURCE,
    }
