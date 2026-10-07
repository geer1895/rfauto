"""RIS 级联闭式表征族（NX-4，内核在 core/ris_cascade.py，本模块只做注册壳）。

round14 §四 :96-97 规格「NX-4 RIS 级联闭式表征（P1/M）：BS-RIS-UE 几何
级联+路径损耗∝N²（Björnson TWC 2020）+无源波束指向角谱验证，挂
metasurface_lut 量化损失」（2026-10-02）。单键 ris_cascade_budget：
一键报告几何级联精确和/远场 N² 闭式/共轭 vs 随机相位面/指向角谱验证/
量化损失挂接/直连对比与交叉距离（d_cross=4π·d1·d2/(N·λ)）。物理口径、
ETSI GR RIS 001 用例/KPI 语义引用与锚树见 core/ris_cascade.py docstring
与 tests/unit/test_ris_cascade.py（单元镜面退化/四次律 vs 平方律/交叉
点翻转/谱峰对准/量化 sinc² 带/N² 律手算）。fspl_db/直连 Friis/
conjugate_phases_rad 等为 core 纯函数不注册（分析面走 core 直调）；
阵因子综合面归 array_synthesis 既有语义，本壳不与其重叠。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    "ris_cascade_budget",
    "NX-4 RIS 级联闭式表征（round14 :96-97，Björnson TWC 2020 N² 律；"
    "ETSI GR RIS 001 用例/KPI 语义引用，不抄数值）：BS-RIS-UE 三段几何"
    "级联（product-distance 逐元精确和+远场 N² 闭式）一键报告。缺省几何"
    "=RIS 在原点 xy 面、BS/UE 对称 30° 仰角（bs_pos_m/ue_pos_m [x,y,z] m "
    "可覆盖）；共轭匹配相位 φ_n=k(d1n+d2n)（闭式对角化）vs 随机相位"
    "（固定种子 MC）vs 全零基线；无源波束指向角谱验证（谱峰 vs UE 几何"
    "方向偏角+均匀阵 −3dB 束宽锚）；b-bit 相位量化经验损失对拍 "
    "metasurface_lut.quantization_loss_db 解析 sinc² 带；直连 FSPL 对比"
    "与交叉距离 d_cross=4π·d1·d2/(N·λ)（短距直链占优的经典定量形态）。"
    "远场适用性按 Fraunhofer 2D²/λ 逐段诚实标注（近场精确和仍在场）",
    (("f_ghz", "float 频率 GHz（>0）"),
     ("n_x", "int RIS 单元列数（≥1；n_x=1 退化为点镜面）"),
     ("n_y", "int RIS 单元行数（≥1）"),
     ("d1_m", "float BS→RIS 中心距离 m（>0；缺省几何用）"),
     ("d2_m", "float RIS→UE 中心距离 m（>0；缺省几何用）"),
     ("period_mm", "float 单元间距 mm（>0；缺省 λ/2）"),
     ("bs_pos_m", "array BS 位置 [x,y,z] m（缺省几何可省）"),
     ("ue_pos_m", "array UE 位置 [x,y,z] m（缺省几何可省；与任一单元"
      "重合显式拒绝）"),
     ("tx_power_dbm", "float 发射功率 dBm（缺省 0，报告 received_power_"
      "dbm 用）"),
     ("gt_db", "float BS 天线增益 dBi（缺省 0 各向同性）"),
     ("gr_db", "float UE 天线增益 dBi（缺省 0）"),
     ("phase_mode", "str 'conjugate'|'random'|'none'（缺省 'conjugate'）"),
     ("bits", "int 相位量化位数（缺省 0=不量化；≥1 时挂 "
      "metasurface_lut 量化损失）"),
     ("random_seed", "int 随机相位种子（缺省 0；固定可复现）"),
     ("n_random_trials", "int 随机相位 MC trial 数（缺省 4096）"),
     ("include_direct", "bool 是否含直连对比与交叉距离（缺省 True）")),
    required=("f_ghz", "n_x", "n_y", "d1_m", "d2_m"),
)
def ris_cascade_budget(
    f_ghz: float,
    n_x: int,
    n_y: int,
    d1_m: float,
    d2_m: float,
    period_mm: float | None = None,
    bs_pos_m: list[float] | None = None,
    ue_pos_m: list[float] | None = None,
    tx_power_dbm: float = 0.0,
    gt_db: float = 0.0,
    gr_db: float = 0.0,
    phase_mode: str = "conjugate",
    bits: int = 0,
    random_seed: int = 0,
    n_random_trials: int = 4096,
    include_direct: bool = True,
) -> dict[str, Any]:
    import math

    import numpy as np

    from rfauto.core.ris_cascade import (
        ris_cascade_report,
        ris_positions_ura,
    )

    f_hz = f_ghz * 1.0e9
    lam_m = 299792458.0 / f_hz
    period_m = (lam_m / 2.0) if period_mm is None else period_mm * 1.0e-3
    pos = ris_positions_ura(n_x, n_y, period_m)
    if bs_pos_m is None or ue_pos_m is None:
        s, c = 0.5, math.sqrt(3.0) / 2.0
        default_bs = [-d1_m * s, 0.0, d1_m * c]
        default_ue = [d2_m * s, 0.0, d2_m * c]
    else:
        default_bs, default_ue = None, None
    return ris_cascade_report(
        f_hz,
        pos,
        np.asarray(bs_pos_m if bs_pos_m is not None else default_bs,
                   dtype=float),
        np.asarray(ue_pos_m if ue_pos_m is not None else default_ue,
                   dtype=float),
        tx_power_dbm=tx_power_dbm,
        gt_db=gt_db,
        gr_db=gr_db,
        phase_mode=phase_mode,
        bits=bits,
        random_seed=random_seed,
        n_random_trials=n_random_trials,
        include_direct=include_direct,
    )
