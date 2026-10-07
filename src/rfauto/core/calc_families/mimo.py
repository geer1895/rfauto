"""MIMO 虚拟阵/信道容量族（NX-1+NX-10，内核分别在 core/mimo_virtual_array.py
与 core/mimo_capacity.py，本模块只做注册壳）。

round14 §四 :88「NX-1 MIMO 虚拟阵综合内核（TX×RX Kronecker 展开虚拟阵/
等效孔径/角分辨率闭式，接 sparse_array_cs；验收复现 EuRAD 2023 12×6 案例）」
与 :108「NX-10 MIMO 容量/DGCC 补全（C=log₂det(I+γHH†) 与分集增益，S 参法
直接可得）」（B 流，2026-10-02）。各 1 键：
- mimo_virtual_array：Tx×Rx 位置 → 虚拟阵元（sum/difference 口径）+ 分辨率
  （闭式只对分组权重均匀 ULA / 两因子同距均匀 ULA 给出，适用边界诚实
  标注）+ 乘积 vs 等效物理阵恒等残差；u0=cos(scan_deg)（z 轴 ULA 惯例，
  侧射 scan_deg=90 → u0=0）。位置输入 mm、按 f_ghz 归一到波长单位
  （λ=C_MM_GHZ/f_ghz mm）；权重实数口径（复权重综合走 core 直调）。
- mimo_channel_capacity：H（Nr×Nt，元素=实数或 [re,im] 对）+ 总发射 snr →
  等功率/注水两档容量 + 规格原式 log₂det(I+snr·HH†)（单流 SNR 口径，
  slogdet 独立路径）+ 秩/奇异值/有效分集阶。S 参→H 提取面归 ecc_metrics
  既有语义，本壳不与其重叠。

锚树 tests/unit/test_mimo_virtual_array.py、tests/unit/test_mimo_capacity.py
（EuRAD 12×6→17 元闭式/三角多重数/孔径可加恒等式/乘积≡Kronecker 恒等/
sparse_array_cs.forward_matrix 同构/首零 1/(max(M,N)d) 精确；对角 2×2 容量
求和恒等 log2(52)/秩亏退化/注水闭式+截模/等注水恒等式/规格原式口径恒等/
i.i.d. Rayleigh MC 均值 vs e^{1/γ}E₁(1/γ)·log₂e）。
"""

from __future__ import annotations

from .registry import C_MM_GHZ, register_calculator


@register_calculator(
    "mimo_virtual_array",
    "NX-1 MIMO 虚拟阵（round14 :88，TX×RX Kronecker 展开虚拟阵/等效孔径/"
    "角分辨率闭式）：收发分置两路相位相加 → 虚拟阵元位置 s=p_tx+p_rx"
    "（sum 口径主判；difference=带符号差 Lag 协方差口径伴生）。等距收发"
    "ULA（M,N，同距 d）→ 虚拟 M+N−1 元等距 ULA、三角多重数（EuRAD 2023"
    " 12×6 → 17 元验收锚）。报告：distinct 位置+多重数+成对权重分组、"
    "孔径可加恒等式（L_v=L_tx+L_rx 残差）、乘积路径 vs 等效物理阵路径"
    "逐点恒等残差、数值/闭式 HPBW 与首零分辨率（闭式只对分组权重均匀"
    "ULA 与两因子同距均匀 ULA 给出——三角锥削自然虚拟阵上均匀阵闭式"
    "偏宽 ~29%，不越界外推）、孔径增益 L_v/L_tx、PSLL。前向算子与"
    "sparse_array_cs.forward_matrix 同构（kron 恒等由锚树钉死）。",
    (("f_ghz", "float 频率 GHz（>0；位置归一波长单位 λ=C_MM_GHZ/f_ghz）"),
     ("tx_positions_mm", "array Tx 阵元位置 mm（一维，非空；波长单位口径"
      "自适应，无需等距）"),
     ("rx_positions_mm", "array Rx 阵元位置 mm（一维，非空）"),
     ("tx_weights", "array Tx 权重（实数，缺省全 1；复权重综合走 core）"),
     ("rx_weights", "array Rx 权重（实数，缺省全 1）"),
     ("convention", "str 'sum'|'difference'（默认 'sum'；MIMO 虚拟阵主判"
      "口径）"),
     ("scan_deg", "float 扫描角 θ0（度，z 轴 ULA 惯例 u0=cos θ0；默认 90°"
      "=侧射）"),
     ("u_points", "int u∈[−1,1] 方向余弦网格点数（默认 801，≥3；数值 "
      "HPBW/PSLL 采样密度）")),
    required=("f_ghz", "tx_positions_mm", "rx_positions_mm"),
)
def mimo_virtual_array(
    f_ghz: float,
    tx_positions_mm: list,
    rx_positions_mm: list,
    tx_weights: list | None = None,
    rx_weights: list | None = None,
    convention: str = "sum",
    scan_deg: float = 90.0,
    u_points: int = 801,
) -> dict:
    import math

    from rfauto.core.mimo_virtual_array import (
        mimo_virtual_array_report as _report,
    )

    f_ghz = float(f_ghz)
    if not math.isfinite(f_ghz) or f_ghz <= 0.0:
        raise ValueError(f"f_ghz 必须为正有限数，收到 {f_ghz!r}")
    lam_mm = C_MM_GHZ / f_ghz
    scale = 1.0 / lam_mm
    scan_u0 = math.cos(math.radians(float(scan_deg)))
    return _report(
        [float(v) * scale for v in tx_positions_mm],
        [float(v) * scale for v in rx_positions_mm],
        tx_weights=None if tx_weights is None else [float(v) for v in tx_weights],
        rx_weights=None if rx_weights is None else [float(v) for v in rx_weights],
        convention=convention,
        scan_direction_cosine=scan_u0,
        u_points=int(u_points),
    )


@register_calculator(
    "mimo_channel_capacity",
    "NX-10 MIMO 信道容量/分集（round14 :108，C=log₂det(I+γHH†) 与分集"
    "增益）：Telatar 1999 容量 + Tse-Viswanath 2005 两档功率口径——等功率"
    "（总 snr 均分 Nt：Σlog₂(1+snr·λᵢ/Nt)）与注水（pᵢ=(μ−1/λᵢ)⁺、Σpᵢ=snr，"
    "活性模闭式搜索）；规格原式 log₂det(I+snr·HH†)（γ=单流 SNR 口径）由 "
    "slogdet 独立路径并行输出（与等功率档差 Nt 倍口径，恒等式由锚树钉）。"
    "分集面：rank(HH†) + 有效分集阶 N_eff=(Σλ)²/Σλ²（participation-ratio "
    "有效秩；天线级 DG=10lg(1−ECC) 近似归 ecc_metrics 既有语义不重复）。"
    "S 参→H 提取面归 ecc_metrics（本键只接收已构成的 H）。",
    (("h_matrix", "array Nr×Nt 信道矩阵（元素=实数或 [re,im] 复数对；"
      "矩形非空）"),
     ("snr", "float 总发射信噪比（线性口径，>0；单 RX 天线噪声归一）")),
    required=("h_matrix", "snr"),
)
def mimo_channel_capacity(h_matrix: list, snr: float) -> dict:
    from rfauto.core.mimo_capacity import mimo_capacity_report as _report

    return _report(h_matrix, float(snr))
