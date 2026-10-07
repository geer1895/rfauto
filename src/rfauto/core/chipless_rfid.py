"""chipless RFID 频域零点编码闭式（谐振器组编码→合成谱→解码 round-trip）。

权威口径（铁律 1c：公式与出处逐条给出，不凭记忆写系数）
---------------------------------------------------------------------------
- 频域编码（spectral-signature / frequency-domain coding）chipless RFID：
  标签=N 个谐振器（滤波器组），第 i 槽位有谐振器=比特 1、无=比特 0；
  读取端扫频看 |S21| 深谷。文献口径（round6 池「chipless RFID 编码标签」
  条目）：Karmakar 系（R. V. Karmakar et al., "Chipless RFID tag at
  2.4/5.8 GHz", 及 chipless 35-bit 实用上限口径，docs/
  研究扩充 round6 引用 [30]）；滤波器组零点编码
  =本仓资产直接复用（S 参数零点判据统计 #195/#197 收口）。
- 单谷闭式=传输线上并联**串联 RLC**（series-RLC shunt notch）：
  导纳 Y(f)=1/(R+j(ωL−1/(ωC)))；S21=2Y0/(2Y0+Y)（Y0=1/Z0，并联导纳
  二端口 ABCD=[1 0; Y 1]→S21 平凡推导）。定义谐振器电抗斜率参数
  x=ω0·L [Ω]（reactance-slope parameter，滤波器综合惯用口径
  G. L. Matthaei, L. Young, E. M. T. Jones, "Microwave Filters,
  Impedance-Matching Networks, and Coupling Structures", Artech House
  1980, ch.4 斜率参数定义）、 unloaded Q: Q_u=ω0·L/R=x/R → R=x/Q_u。
  谐振点传输零点剩余 |S21_min| = 2R/(2R+Z0)（R→0 ⟹ 完美零点）。
  深谷半宽（无耗极限 |S21|²=1/2 点，X=±Z0/2）：Δf_full = f0·Z0/(2x)
  （薄斜率极限 X≈2x·Δf/f0 逐式推导；有耗时带宽加宽由精确式数值计算，
  本模块给精确复数响应，不给近似带宽）。
- 级联（滤波器组）：各谐振器响应相乘（隔离假设=谐振器间传输线段
  匹配无互耦，等 Q 假设下谷深逐谷叠加 dB——chipless 标签读出
  惯例；互耦修正属电磁仿真域，本模块如实不外推）。
- 解码：槽位窗内 min |S21|_dB 与窗内 max（局部基线）之差=谷深判据；
  谷深 > 阈值 → 该槽位比特 1。汉明距离报告=原始码字与码本最近
  合法码字的逐位异或计数（检测容差失误时的纠错面如实报告）。

域守卫：f_start < f_stop、n_slots ≥ 2、码字长度=n_slots、谐振器频率
落格容差外显式 ValueError（slotline/siw 惯例：越域拒绝不外推）。
陷波带宽 vs 槽距守卫（2026-10-04 A-06）：规划面陷波全宽
f0·Z0/(2x) ≥ 槽距 → 显式 ValueError（带宽≳槽距时邻槽窗整体落入
谷裙/谷底，逐槽谷深判据全域失效=全槽误判域，模型面已知的越域
拒绝）；decode 面全 1 码字与该域误判特征**同象不可分**（合法全 1
标签存在），只降级注记不拒绝（all_slots_decode_one=True，数据面
无法裁决——#122 如实）。
单位纪律：内部 SI（Hz/Ω），输出 JSON 可序列化 dict（round 12 位）。
"""

from __future__ import annotations

import math
from typing import Any

_C0 = 299792458.0  # m/s（真空光速，与 calc_families.registry.C_MM_GHZ 同源）


def _num(value: Any, name: str) -> float:
    """数值入参收敛：拒 bool（df7+⑯）+ 非有限数。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: Any, name: str) -> float:
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def slot_grid(f_start_hz: float, f_stop_hz: float, n_slots: int) -> list[float]:
    """编码槽格：[f_start, f_stop] 均分 n_slots 个槽中心（含两端半步内缩）。

    槽中心 f_i = f_start + (i+0.5)·Δf，Δf=(f_stop−f_start)/n_slots——
    槽中心不贴扫描带缘（带缘谷检窗会越出数据范围）。"""
    fs = _pos(f_start_hz, "f_start_hz")
    fe = _pos(f_stop_hz, "f_stop_hz")
    n = int(n_slots)
    if n < 2:
        raise ValueError("n_slots 必须 ≥2（单槽无编码容量意义）")
    if fe <= fs:
        raise ValueError("f_stop_hz 必须 > f_start_hz")
    df = (fe - fs) / n
    return [fs + (i + 0.5) * df for i in range(n)]


def plan_resonator_bank(code: list[int] | tuple[int, ...], f_start_hz: float,
                        f_stop_hz: float, q_unloaded: float,
                        slope_ohm: float,
                        z0_ohm: float = 50.0) -> dict[str, Any]:
    """码字→谐振器组频率/带宽/预期谷深规划（等 Q 假设）。

    code[i]∈{0,1}：1=槽 i 放谐振器（读出谱呈深谷）。谐振器参数：
    f_i=槽中心、Q_u 统一、电抗斜率 x 统一 → R_i=x/Q_u、
    谐振点谷深 |S21_min|=2R/(2R+Z0)、无耗近似全带宽 f_i·Z0/(2x)。
    域守卫（A-06）：任一谐振器无耗近似全带宽 ≥ 槽距 → 显式
    ValueError（谷深判据在"陷波带宽≳槽距"域全槽误判——邻槽窗落入
    谷裙，局部基线 max−min 不再反映本槽有无谐振器；模型面已知的
    越域拒绝，参数回显在报错内）。
    """
    n = len(code)
    grid = slot_grid(f_start_hz, f_stop_hz, n)
    q = _pos(q_unloaded, "q_unloaded")
    x = _pos(slope_ohm, "slope_ohm")
    z0 = _pos(z0_ohm, "z0_ohm")
    if q <= 1.0:
        raise ValueError("q_unloaded 必须 >1（谐振器定义域）")
    clean = tuple(int(b) for b in code)
    if any(b not in (0, 1) for b in clean):
        raise ValueError("code 必须只含 0/1")
    df = (float(f_stop_hz) - float(f_start_hz)) / n
    for i, bit in enumerate(clean):
        if bit != 1:
            continue
        bw_i = grid[i] * z0 / (2.0 * x)
        if bw_i >= df:
            raise ValueError(
                f"槽位 {i}（f0={grid[i]:.6g} Hz）陷波全宽 {bw_i:.6g} Hz ≥ "
                f"槽距 {df:.6g} Hz——谷深判据域外（陷波带宽≳槽距时全槽"
                "误判，A-06；增大 slope_ohm 收窄带宽或减少 n_slots 加大槽距）")
    r_ohm = x / q
    depth_db = 20.0 * math.log10(2.0 * r_ohm / (2.0 * r_ohm + z0))
    resonators: list[dict[str, Any]] = []
    for i, bit in enumerate(clean):
        if bit != 1:
            continue
        f0 = grid[i]
        resonators.append({
            "slot_index": i,
            "freq_hz": round(f0, 6),
            "r_ohm": round(r_ohm, 12),
            "slope_ohm": round(x, 12),
            "q_unloaded": round(q, 12),
            "notch_depth_db": round(depth_db, 9),
            "notch_bw_approx_hz": round(f0 * z0 / (2.0 * x), 6),
        })
    return {"code": list(clean), "n_slots": n, "slot_freqs_hz":
            [round(v, 6) for v in grid], "resonators": resonators,
            "notch_depth_db_common": round(depth_db, 9),
            "r_ohm_common": round(r_ohm, 12),
            "note": "等 Q 假设：全部谐振器共用 q_unloaded/slope_ohm；"
                    "深谷=串联 RLC 并联于 Z0 传输线（Matthaei 斜率参数口径）"}


def notch_s21_mag(f_hz: float, f0_hz: float, q_unloaded: float,
                  slope_ohm: float, z0_ohm: float = 50.0) -> float:
    """单个串联 RLC 并联陷波器 |S21|（精确复数式，无近似）。"""
    f = _pos(f_hz, "f_hz")
    f0 = _pos(f0_hz, "f0_hz")
    q = _pos(q_unloaded, "q_unloaded")
    x = _pos(slope_ohm, "slope_ohm")
    z0 = _pos(z0_ohm, "z0_ohm")
    omega = 2.0 * math.pi * f
    omega0 = 2.0 * math.pi * f0
    l_h = x / omega0
    c_f = 1.0 / (omega0 * omega0 * l_h)
    r = x / q
    z_rlc = complex(r, omega * l_h - 1.0 / (omega * c_f))
    y = 1.0 / z_rlc
    y0 = 1.0 / z0
    s21 = 2.0 * y0 / (2.0 * y0 + y)
    return abs(s21)


def bank_s21_mag(f_hz: float, resonator_freqs_hz: list[float],
                 q_unloaded: float, slope_ohm: float,
                 z0_ohm: float = 50.0) -> float:
    """谐振器组级联 |S21|（相乘；隔离/无互耦假设，出处见模块 docstring）。"""
    mag = 1.0
    for f0 in resonator_freqs_hz:
        mag *= notch_s21_mag(f_hz, float(f0), q_unloaded, slope_ohm, z0_ohm)
    return mag


def encode_tag_code(resonance_freqs_hz: list[float], f_start_hz: float,
                    f_stop_hz: float, n_slots: int,
                    tol_frac: float = 0.4) -> dict[str, Any]:
    """实测谐振频点列表→比特码字（频点→最近槽位映射）。

    tol_frac：允许偏差=tol_frac×槽距（0.4=半槽内再收紧 20%）；
    越容差或两频点映同槽 → 显式 ValueError（不静默丢位）。"""
    grid = slot_grid(f_start_hz, f_stop_hz, n_slots)
    df = (float(f_stop_hz) - float(f_start_hz)) / int(n_slots)
    tol = _pos(tol_frac, "tol_frac") * df
    if tol <= 0.0:
        raise ValueError("tol_frac 必须 >0")
    code = [0] * int(n_slots)
    used: dict[int, float] = {}
    for fr in resonance_freqs_hz:
        fv = _pos(fr, "resonance_freqs_hz 元素")
        if fv < float(f_start_hz) or fv > float(f_stop_hz):
            raise ValueError(f"谐振频点 {fv} 落在扫描带外"
                             f"[{f_start_hz}, {f_stop_hz}]（越域拒绝）")
        i_near = min(range(len(grid)), key=lambda i: abs(grid[i] - fv))
        if abs(grid[i_near] - fv) > tol:
            raise ValueError(
                f"谐振频点 {fv} 距最近槽位 {grid[i_near]} 偏差 "
                f"{abs(grid[i_near] - fv):.6g} Hz 超容差 {tol:.6g} Hz"
                "（tol_frac×槽距；不静默丢位）")
        if i_near in used:
            raise ValueError(
                f"两个谐振频点（{used[i_near]}, {fv}）映入同一槽位 {i_near}"
                "（编码冲突，拒绝不猜）")
        used[i_near] = fv
        code[i_near] = 1
    return {"code": code, "n_slots": int(n_slots),
            "assignments": [{"freq_hz": round(used[i], 6), "slot_index": i}
                            for i in sorted(used)],
            "tol_hz": round(tol, 6)}


def decode_from_spectrum(freq_hz: list[float], s21_db: list[float],
                         f_start_hz: float, f_stop_hz: float, n_slots: int,
                         codebook: list[list[int]] | None = None,
                         depth_threshold_db: float = 3.0,
                         window_frac: float = 0.8) -> dict[str, Any]:
    """扫频谱→码字反解（逐槽谷深判据 + 汉明距离报告）。

    判据：槽 i 窗宽=window_frac×槽距（窗心=槽中心），谷深=
    窗内 max−min（|S21|_dB）；谷深 > depth_threshold_db → 比特 1。
    给 codebook（合法码字表）时另报最近合法码字与汉明距离；
    窗内采样点 <2 的槽如实记 unresolved=True（数据不足不猜）。
    带宽 vs 槽距同象注记（A-06）：全槽（无 unresolved）解码全 1
    时与"陷波带宽≳槽距"全域误判特征同象——谱面不可区分合法全 1
    标签，降级注记 all_slots_decode_one=True 不拒绝（#122 如实；
    该域核对走规划面 plan_resonator_bank 的显式守卫）。
    """
    if len(freq_hz) != len(s21_db):
        raise ValueError("freq_hz 与 s21_db 长度必须一致")
    if len(freq_hz) < 4:
        raise ValueError("谱数据至少 4 点（每槽窗内 ≥2 采样）")
    freqs = [_num(v, "freq_hz 元素") for v in freq_hz]
    mags = [_num(v, "s21_db 元素") for v in s21_db]
    if any(freqs[i + 1] < freqs[i] for i in range(len(freqs) - 1)):
        raise ValueError("freq_hz 必须单调递增（扫频谱口径）")
    if freqs[0] == freqs[-1]:
        raise ValueError("freq_hz 首末不得重合")
    n = int(n_slots)
    if n < 2:
        raise ValueError("n_slots 必须 ≥2")
    grid = slot_grid(f_start_hz, f_stop_hz, n)
    df = (_pos(f_stop_hz, "f_stop_hz") - _pos(f_start_hz, "f_start_hz")) / n
    half_win = _pos(window_frac, "window_frac") * df / 2.0
    if not (0.0 < window_frac <= 1.0):
        raise ValueError("window_frac 必须 ∈(0,1]（槽距比例）")
    thr = _num(depth_threshold_db, "depth_threshold_db")
    if thr <= 0.0:
        raise ValueError("depth_threshold_db 必须 >0（dB 谷深门限）")
    code: list[int] = []
    depths: list[float | None] = []
    unresolved = 0
    for fc in grid:
        win = [m for m, f in zip(mags, freqs, strict=True)
               if abs(f - fc) <= half_win]
        if len(win) < 2:
            code.append(0)
            depths.append(None)
            unresolved += 1
            continue
        depth = max(win) - min(win)
        depths.append(round(depth, 9))
        code.append(1 if depth > thr else 0)
    hamming = 0
    matched: list[int] | None = None
    if codebook is not None:
        if not codebook:
            raise ValueError("codebook 不得为空（判距离需合法码字表）")
        for row in codebook:
            if len(row) != n or any(int(b) not in (0, 1) for b in row):
                raise ValueError("codebook 码字长度必须=n_slots 且只含 0/1")
        best = min(codebook,
                   key=lambda row: sum(1 for a, b in zip(code, row,
                                                         strict=True)
                                       if int(a) != int(b)))
        matched = [int(b) for b in best]
        hamming = sum(1 for a, b in zip(code, matched, strict=True)
                      if a != b)
    all_one = unresolved == 0 and all(b == 1 for b in code)
    note = ("谷深=槽窗内 max−min(|S21|_dB)；"
            "unresolved=窗内采样不足如实不计码")
    if all_one:
        note += ("；全槽解码为 1——与'陷波带宽≳槽距'全域误判特征同象"
                 "（合法全 1 码字谱面不可区分，谷深判据在该域失效，"
                 "A-06 降级注记；请核对标签规划带宽 vs 槽距）")
    out: dict[str, Any] = {"code": code, "slot_depths_db": depths,
                           "depth_threshold_db": round(thr, 9),
                           "window_frac": round(float(window_frac), 9),
                           "n_unresolved_slots": unresolved,
                           "all_slots_decode_one": all_one,
                           "note": note}
    if matched is not None:
        out["matched_codebook_code"] = matched
        out["hamming_distance"] = hamming
    return out
