"""接收机损伤族（MT-4，内核在 core/rx_impairments.py，本模块只做注册壳）。

round17 §二 MT-4 规格「IQ 失衡 IRR（3GPP TS 38.141 口径钉死）、相噪→
积分 EVM、blocking/信道选择性预算（复用 cascade spur_search）」
（2026-10-02）。三键逐件对应规格三件；core 直调面
iq_imbalance_irr/phase_noise_evm/blocking_budget 保持纯函数语义（相噪
积分消费 core/clock_noise、杂散搜索消费 core/cascade——既有语义零改动，
只读消费）。blocking_budget 注册面 stages schema 与 core/cascade 完全
一致（NF/P1dB/噪声底走 cascade_budget 聚总）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "iq_imbalance_irr",
    "MT-4 件 1 IQ 失衡 → 镜像抑制比 + EVM 贡献（round17 MT-4，Razavi "
    "式 IRR=(1+ε²+2εcosφ)/(1+ε²−2εcosφ)，ε=Q/I 增益比线性、φ=正交相位"
    "误差；ε=1 退化 cot²(φ/2)）+ 3GPP TS 38.141-1 EVM 消费口径折算"
    "（evm_rms²=镜像/信号功率=1/IRR；IRR 本身不设 3GPP 限值门——限值面"
    "out-of-scope 如实注明）。完全平衡（0 dB+0°）→ irr_db=None（∞ 的 "
    "JSON 契约面）、evm=0；完全反相（0 dB+±180°）→ 信号支路零输出、"
    "EVM 无界走 None+full_image 旗标。|φ|>180° 显式拒绝",
    (("amp_imbalance_db", "float I/Q 增益失衡 dB（ε=10^(a/20)；同值异号 "
      "IRR 相同）"),
     ("phase_imbalance_deg", "float 正交相位误差 deg（|φ|≤180；符号=旋转"
      "方向，IRR 同值）")),
    required=("amp_imbalance_db", "phase_imbalance_deg"),
)
def iq_imbalance_irr(amp_imbalance_db: float, phase_imbalance_deg: float) -> dict:
    from rfauto.core.rx_impairments import iq_imbalance_irr as _core

    return _core(amp_imbalance_db, phase_imbalance_deg)


@register_calculator(
    "phase_noise_evm",
    "MT-4 件 2 相噪 → 积分 EVM（round17 MT-4；σ_φ²=2∫10^(L/10)df ADI "
    "MT-008 口径，积分复用 core/clock_noise.phase_jitter_from_l 不重复"
    "实现）→ EVM_rms=σ_φ（小角度平稳高斯口径，σ_φ>0.5 rad 打 "
    "small_angle_ok=False 不静默）+ evm_db/evm_percent + 可选 rms 抖动。"
    "f_edges=严格递增偏移频率边界 Hz；l_dbc 按 interp 取边界值"
    "（db_linear，长度=N）或段值（const，长度=N−1）；积分区间不外推。"
    "σ_φ=0 → evm_db=None（dB 域无定义，JSON 契约禁 −Inf）",
    (("f_edges", "list[float] 偏移频率边界 Hz（严格递增，N≥2，全>0）"),
     ("l_dbc", "list[float] 单边带相噪 dBc/Hz（db_linear=边界值 N 个 / "
      "const=段值 N−1 个）"),
     ("interp", "str 'db_linear'|'const'（默认 'db_linear'）"),
     ("f_carrier_hz", "float 可选载波 Hz（>0；给了才输出 jitter_s）")),
    required=("f_edges", "l_dbc"),
)
def phase_noise_evm(
    f_edges: list,
    l_dbc: list,
    interp: str = "db_linear",
    f_carrier_hz: float | None = None,
) -> dict:
    from rfauto.core.rx_impairments import phase_noise_evm as _core

    return _core(f_edges, l_dbc, interp=interp, f_carrier_hz=f_carrier_hz)


@register_calculator(
    "blocking_budget",
    "MT-4 件 3 阻塞/信道选择性预算（round17 MT-4，杂散面复用 core/cascade"
    ".spur_search，链路基线复用 cascade_budget——既有语义零改动）。三面："
    "①倒易混频 N_rm=P_blk@mixer+L(f_offset)+10log10(B) → desense="
    "10log10(1+10^((N_rm−N_floor)/10))（等效 NF 抬升=灵敏度恶化）；"
    "②线性度 p1db_margin=链路输入 P1dB−阻塞电平（无 p1db 级→None 不判）；"
    "③阻塞×本振 |m·f_blk±n·f_LO| 落带杂散（fundamental 不计；hazard="
    "'high' 落带判负）。pass=三面合取；L(f_offset) 为标量（裙边分段积分"
    "不在此层，可走 clock_noise 幂律谱合成取值）；filter_rejection_db="
    "阻塞偏移处前端聚总选择性",
    (("stages", "list[dict] 接收链级表（schema 同 cascade_budget：type/"
      "gain_db/nf_db/iip3_dbm/p1db_dbm/bw_hz…；NF/P1dB/噪声底走其聚总）"),
     ("bw_hz", "float 信道噪声带宽 Hz（>0）"),
     ("blocker_dbm", "float 链路输入处阻塞电平 dBm"),
     ("f_blocker_hz", "float 阻塞频率 Hz（>0）"),
     ("f_lo_hz", "float 本振频率 Hz（>0）"),
     ("lo_phase_noise_dbc_hz", "float 阻塞偏移处 LO 单边带相噪 dBc/Hz"
      "（标量）"),
     ("f_rx_hz", "float 期望信道频率 Hz（if_center_hz 缺省时 IF=|f_rx−f_lo|；"
      "两者必给其一）"),
     ("if_center_hz", "float 显式信道 IF Hz（≥0，缺省由 f_rx 解析）"),
     ("filter_rejection_db", "float 前端聚总选择性 dB（≥0，默认 0）"),
     ("desense_limit_db", "float desense 判过限值 dB（≥0，默认 3.0）"),
     ("max_order", "int 杂散最大阶 m+n（≥1，默认 7）"),
     ("t_kelvin", "float 热噪声温度 K（>0，默认 290）")),
    required=("stages", "bw_hz", "blocker_dbm", "f_blocker_hz", "f_lo_hz",
              "lo_phase_noise_dbc_hz"),
)
def blocking_budget(
    stages: list,
    bw_hz: float,
    blocker_dbm: float,
    f_blocker_hz: float,
    f_lo_hz: float,
    lo_phase_noise_dbc_hz: float,
    f_rx_hz: float | None = None,
    if_center_hz: float | None = None,
    filter_rejection_db: float = 0.0,
    desense_limit_db: float = 3.0,
    max_order: int = 7,
    t_kelvin: float = 290.0,
) -> dict:
    from rfauto.core.rx_impairments import blocking_budget as _core

    return _core(
        stages, bw_hz, blocker_dbm, f_blocker_hz, f_lo_hz,
        lo_phase_noise_dbc_hz,
        f_rx_hz=f_rx_hz, if_center_hz=if_center_hz,
        filter_rejection_db=filter_rejection_db,
        desense_limit_db=desense_limit_db, max_order=max_order,
        t_kelvin=t_kelvin)
