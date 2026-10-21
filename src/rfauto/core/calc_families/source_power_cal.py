"""源功率校准族（架构批 W5-S18 席域，R2_core_tier3 边际池立项）。

单键 source_power_cal_table：源功率校准的功率计闭环方程——固定源设定下
逐频功率计读数 → 参考面 offset 表 → 源编程设定闭式（参考面交付功率平坦
档），+平坦设定对照档/单调方向旗标/不确定度传播/源上限可行性判读。

边界（#222 triple-grep 证据，2026-10-18 实测）
--------------------------------------------------------
- 全仓 grep（source power cal/flat.falling/源功率校准）src/tests 零实现
  零键（"源功率"命中=adc_budget/error_budget 的**噪声源功率**叠加语义，
  行级剔除），本族为该域首个注册键。
- core/calc_families/power_cal.py + core/power_calibration.py（SB22-MS-1，
  W2 落地）= 功率**测量端**校准链：单次功率计读数 → 校准因子/缆损/失配
  补偿 → 参考面可用功率 + GUM 预算（读数方向，+缆损回补）；本键=源**编
  程端**闭环：修正后逐频读数 → offset 表 → 源设定表（源方向，−offset）。
  语义握手：本键输入=该链输出（参考面修正后读数 p_available_dbm）——
  链把读数加回损耗、本键把损耗从源设定减去，交付恒等式两端互补（同仓
  双源互证见锚树测试）。detector_device/six_port=检波器件/反演架构不并
  入（边界互指见各模块 docstring）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **闭环方程**（VNA/信号源源功率校准定义惯例，Keysight 帮助"Source
  Power Calibration"语义，二级转引）：固定源设定 p_set 扫频，参考面修正
  读数 p_meas(f)（已按 power_cal_chain 补偿校准因子/缆损/失配——输入语
  义=该链输出），则

      offset(f) = p_meas(f) − p_set            （测量端传递/损耗表，dB）
      program(f) = p_target − offset(f)        （源编程设定表，dBm）

      交付恒等式：program(f) + offset(f) = p_target（逐位）。

- **flat-falling 双读法**（两种设定闭式都在域内，方向旗标如实自报）：
  ① 平坦交付档（上式）——原始端口功率随频下坠（耦合器/缆损滚降）时，
  补偿设定反向回补：offset 随 f 下降（损耗上升）⇒ program 随 f 上升，
  参考面功率平坦；② 平坦设定对照档 p_flat(f) = p_target + offset(f)
  （源设定不补偿、停在目标值）⇒ 交付 = p_flat + offset 随 f 下坠——
  "flat 设定 → falling 交付"。两档的逐频列表与 span/单调方向全部落盘。
- **不确定度传播**（dB 域 1:1 线性）：u_program(f) = u_meas(f)（参考面
  修正读数的标准不确定度，来自调用方；功率计链 GUM 预算见
  power_cal_chain 的 u_components 面），展伸 U = k=2·u。
- **可行性判读**：可选源上限 p_src_max_dbm——program(p) > 上限的点记
  infeasible + 超限 dB（源功率上限触顶时平坦交付不可达，如实不裁剪）。
- **诚实边界（预声明）**：①逐频点独立闭式（无跨频拟合/插值面，源平滑
  约束不在本域）；②读数端校准因子/失配补偿不在本键（输入必须已是参考
  面修正值——原始读数请先走 power_cal_chain，#118 语义单一事实源）；
  ③接收机/频响线性度假设（dB 域叠加）由调用方保证。

出处
----
- VNA/信号源源功率校准 offset 表定义惯例（Keysight 帮助"Source Power
  Calibration"语义，二级转引——定义惯例出处而非厂商数值）。
- 参考面修正读数语义与 core/power_calibration.py 同源（Keysight AN
  64-1A 的 K_b/链补偿口径，同仓单源引用）。

守卫：freq_ghz/p_meas_dbm 等长非空、freq 有限>0、p_meas 有限；
p_set/p_target 有限（p_target 缺省=p_set）；u_meas_db 逐点列表（等长）或
标量 ≥0；p_src_max_dbm 有限可选；越界一律显式 ValueError。

出处（"Source Power Calibration"定义惯例二级转引；同仓双源）：
- source_power_cal_table：源功率校准损耗闭环方程（功率计闭环 offset
  口径，与 power_cal_chain 测量端/源编程端边界互指同仓双源；
  "Source Power Calibration"语义二级转引——定义惯例出处而非厂商数值）。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = ["source_power_cal_table"]

_SOURCE = (
    "VNA/信号源源功率校准 offset 表定义惯例（Keysight 'Source Power "
    "Calibration' 语义，二级转引）；参考面修正读数语义与 power_cal_chain "
    "同源（Keysight AN 64-1A 链补偿口径，同仓单源引用）")


@register_calculator(
    "source_power_cal_table",
    "源功率校准表：功率计闭环方程——修正后逐频参考面读数 → offset="
    "p_meas−p_set → 源编程设定 program=p_target−offset（参考面交付平坦"
    "档，交付恒等式逐位），+平坦设定对照档（flat 设定→falling 交付）/"
    "单调方向旗标/u 传播与展伸/源上限可行性。锚：交付恒等式逐位+合成损"
    "耗表精确回收+power_cal_chain 链间握手同仓互证",
    (("freq_ghz", "array 频率列表 GHz（有限 >0，与 p_meas_dbm 等长）"),
     ("p_meas_dbm", "array 参考面修正后功率计读数列表 dBm（输入语义="
                    "power_cal_chain 输出 p_available_dbm）"),
     ("p_set_dbm", "float dBm 读数扫描期间的固定源设定"),
     ("p_target_dbm", "float dBm 目标交付功率（缺省=p_set）"),
     ("u_meas_db", "修正读数标准不确定度 dB——标量或逐点列表（≥0，可选）"),
     ("p_src_max_dbm", "float dBm 源设定上限（可选；触顶点记 infeasible "
                       "不裁剪）")),
    required=("freq_ghz", "p_meas_dbm", "p_set_dbm"),
)
def source_power_cal_table(
    freq_ghz: list,
    p_meas_dbm: list,
    p_set_dbm: float,
    p_target_dbm: float | None = None,
    u_meas_db: float | list | None = None,
    p_src_max_dbm: float | None = None,
) -> dict[str, Any]:
    if not isinstance(freq_ghz, (list, tuple)) or not freq_ghz:
        raise ValueError(
            f"source_power_cal: freq_ghz 须为非空列表，收到 {freq_ghz!r}")
    if not isinstance(p_meas_dbm, (list, tuple)) or not p_meas_dbm:
        raise ValueError(
            f"source_power_cal: p_meas_dbm 须为非空列表，收到 "
            f"{p_meas_dbm!r}")
    if len(freq_ghz) != len(p_meas_dbm):
        raise ValueError(
            f"source_power_cal: freq_ghz({len(freq_ghz)}) 与 "
            f"p_meas_dbm({len(p_meas_dbm)}) 须等长")
    freqs = []
    for v in freq_ghz:
        f = _finite(v, "freq_ghz")
        if f <= 0.0:
            raise ValueError(
                f"source_power_cal: freq_ghz 须有限 >0，收到 {v!r}")
        freqs.append(f)
    meas = [_finite(v, "p_meas_dbm") for v in p_meas_dbm]
    p_set = _finite(p_set_dbm, "p_set_dbm")
    p_target = (p_set if p_target_dbm is None
                else _finite(p_target_dbm, "p_target_dbm"))

    # 不确定度收敛：标量广播 / 逐点列表（≥0 无源检验）
    if u_meas_db is None:
        u_list: list[float] | None = None
    elif isinstance(u_meas_db, (list, tuple)):
        u_list = []
        for v in u_meas_db:
            u = _finite(v, "u_meas_db")
            if u < 0.0:
                raise ValueError(
                    f"source_power_cal: u_meas_db 须 ≥0，收到 {v!r}")
            u_list.append(u)
        if len(u_list) == 1:
            u_list = u_list * len(freqs)
        if len(u_list) != len(freqs):
            raise ValueError(
                f"source_power_cal: u_meas_db({len(u_list)}) 与频点数"
                f"({len(freqs)}) 须等长（或标量/单点广播）")
    else:
        u0 = _finite(u_meas_db, "u_meas_db")
        if u0 < 0.0:
            raise ValueError(
                f"source_power_cal: u_meas_db 须 ≥0，收到 {u0!r}")
        u_list = [u0] * len(freqs)

    p_max = (None if p_src_max_dbm is None
             else _finite(p_src_max_dbm, "p_src_max_dbm"))

    # ── 闭环方程 ─────────────────────────────────────────────────────────
    offset = [m - p_set for m in meas]
    program = [p_target - o for o in offset]
    # 交付恒等式：program + offset = p_target（逐位构造，残差为浮点噪声）
    delivered_dev = max(abs((pr + o) - p_target)
                        for pr, o in zip(program, offset, strict=True))
    # 平坦设定对照档：p_flat = p_target（不补偿）→ 交付 = p_target+offset
    flat_delivered = [p_target + o for o in offset]

    def _mono(vals: list[float]) -> str:
        tol = 1e-12
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        inc = all(d >= -tol for d in diffs)
        dec = all(d <= tol for d in diffs)
        if inc and not dec:
            return "nondecreasing"
        if dec and not inc:
            return "nonincreasing"
        return "flat" if all(abs(v - vals[0]) <= tol for v in vals) \
            else "mixed"

    span = max(offset) - min(offset)
    offset_dir = _mono(offset)

    u_program = (None if u_list is None
                 else [round(u, 15) for u in u_list])
    u_expanded = (None if u_list is None
                  else [round(2.0 * u, 15) for u in u_list])

    infeasible_idx: list[int] = []
    over_db: float = 0.0
    if p_max is not None:
        for i, pr in enumerate(program):
            if pr > p_max:
                infeasible_idx.append(i)
                over_db = max(over_db, pr - p_max)

    return {
        "freq_ghz": [round(f, 15) for f in freqs],
        "p_set_dbm": p_set,
        "p_target_dbm": p_target,
        "offset_db": [round(o, 12) for o in offset],
        "program_dbm": [round(p, 12) for p in program],
        "delivered_check_max_dev_db": round(delivered_dev, 15),
        "program_flat_setting_delivered_dbm": [round(v, 12)
                                               for v in flat_delivered],
        "offset_span_db": round(span, 12),
        "program_span_db": round(span, 12),
        "offset_direction": offset_dir,
        "program_direction": _mono(program),
        "u_program_db": u_program,
        "u_expanded_k2_db": u_expanded,
        "src_max_dbm": p_max,
        "infeasible_idx": infeasible_idx,
        "max_overdrive_db": (round(over_db, 12) if p_max is not None
                             else None),
        "note": (
            "闭环方程：offset(f)=p_meas−p_set、program(f)=p_target−offset"
            "，交付恒等式 program+offset=p_target 逐位（"
            "delivered_check_max_dev_db=构造残差，浮点噪声量级）。输入读"
            "数语义=power_cal_chain 输出 p_available_dbm（测量端链把损耗"
            "加回读数，本键把损耗从源设定减去——两端互补闭环，同仓双源）。"
            "flat-falling 双读法：①平坦交付档=program 表（offset 随 f 下"
            "坠/损耗上升 ⇒ program 上翘，原始 falling 剖面被补平）；②平"
            "坦设定对照档 program_flat_setting_delivered_dbm（源停目标值 "
            "⇒ 交付随损耗下坠）。u_program_db=u_meas 1:1 传播（dB 域线性"
            "），U=k=2；p_src_max 触顶点记 infeasible_idx 不裁剪"),
        "source": _SOURCE,
    }
