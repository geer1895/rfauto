"""声表面波（SAW）IDT 换能器设计族（aurora72 A5-A 席域 1，R7 第二梯队 T12=G14）。

三键：saw_idt_sync_design（IDT 同步设计双向：指对周期 pitch↔同步频率 f0=v/λ0，
λ0=pitch 口径写死） / saw_idt_frequency_response（δ 函数模型频响：Dirichlet 核
精确闭式 + sinc 近似档双实现，零点栅格 f0·k/N_p 恒等） / saw_delay_line（延迟线：
τ=L/v 恒等 + 传播损耗经验系数注入 + 双向换能器 2×10lg2 辐射损耗写死口径）。

与既有声波/滤波器面的边界（语义防撞，R7 §③ T12 + 本次 triple-grep 证据）
--------------------------------------------------------
- baw_ladder（calc_families/baw_ladder.py）= BAW/SAW **梯形滤波器**电路综合
  （串/并臂谐振器 fs/fp 阻抗梯）；本族只做 **IDT 换能器级**（周期/指对数/
  频响/延迟线），不做梯形电路——docstring 交叉注记互指。
- 全仓 grep（\\bsaw\\b 大小写敏感 / 声表面波 / surface acoustic / Rayleigh 波）
  除上述 baw_ladder docstring 一句与 fading/mimo 的 "Rayleigh 衰落/距离"
  （通信信道语义，非声波）外零命中——本族是仓内首个声表面波键面。
- coupled_line_bpf/interdigital_bpf=电磁传输线滤波器实现族；mask_filter=
  规格级——声波器件机理（压电基板声速定频）不并入。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 同步设计：IDT 指对周期 pitch ≡ 一个指对（同极性相邻指）长度 = 同步声波长
  λ0（指宽=缝宽=pitch/2 同步占空 0.5 惯例，如实注记）：

      f0 = v_R / λ0        （v_R=基板表面声速；双向解 λ0=v_R/f0）
      L_IDT = N_p·λ0       （N_p=指对数）
      τ_IDT = L_IDT / v_R
      零点-零点带宽 Δf_NN = 2·f0/N_p，分数带宽 = 2/N_p（N_p↔带宽倒数关系）

  文献典型值带：v_R(LiNbO3 Y-Z) = 3488 m/s、v_R(ST-cut 石英) = 3158 m/s、
  v_R(36°YX-LiTaO3) ≈ 4212 m/s（声速为基板材料文献典型值，本仓不做实测
  标定；覆盖值由 v_sound_m_s 注入）。ST 石英 pitch=1µm → f0=3.158GHz 教科
  书常数锚（测试侧独立换算）。
- δ 函数模型频响（Morgan 口径：指纹格=δ 源阵列，忽略指内电学再生二阶项，
  如实注记模型档位）：指对位置 x_n=n·λ0 →

      H(f) = Σ_{n=0}^{N_p-1} e^{-j2πn·f/f0}
           |H(f0+Δf)|² = [sin(πN_p·Δf/f0) / (N_p·sin(π·Δf/f0))]²   （归一功率）

  零点栅格恒等式（测试钉）：Δf = k·f0/N_p（k≠0 且 k≢0 mod N_p）处 |H|=0；
  栅瓣 f=(m+1)·f0 处归一功率=1（阵列因子混叠，如实报告）。sinc 近似档
  [sinc(N_p·Δf/f0)]² 仅主瓣区有效（相对偏差 O((πΔf/f0)²)，栅瓣区失效如实
  返回不匹配）。测试侧独立路线=几何级数逐项 cmath 求和（#118 双实现互证）。
- 延迟线：τ = L/v_R 恒等；传播损耗系数注入式（α₁=loss_db_per_us_1ghz，
  频率标度 n=2 写死——黏滞衰减经典 f² 律；材料实测系数文献发散，不做缺省
  物理值，α₁ 缺省 0=纯延迟）；双向换能器单只辐射损耗 10lg2=3.0103dB（双向
  IDT 两路均分，匹配单电极口径），双端合计 2×10lg2=6.0206dB 恒等式测试钉。

验证（in-output xcheck + 测试侧独立重算，#118 不自证）
------------------------------------------------------
- 同步键：pitch→f0→pitch 往返逐位；f0=v/λ0 测试侧独立换算；Δf_NN·N_p=2f0
  恒等；L=N_p·λ0、τ=L/v 恒等；ST 石英 1µm→3.158GHz 常数窗。
- 频响键：几何级数逐项和 vs Dirichlet 闭式 ≤1e-12；首零点 f0(1±1/N_p) 处
  |H|²<1e-24；半零点 f0(1+1/(2N_p)) 处 → (2/π)² 经典常数窗；峰点 0dB；小
  失谐 sinc 档与精确档 O(u²) 窗互证。
- 延迟键：τ=L/v 测试侧独立换算；α(f)=α₁·f²·τ 标度（f×2→×4）；双端 6.0206dB
  常数。

守卫：v_sound_m_s>0；n_finger_pairs 整数 ∈[1,10⁶]；pitch_um/f0_ghz 恰给其一
（双向互斥，双给/都不给显式拒绝）且 >0；freq_ghz 全部 >0 有限；idt_gap_mm>0；
loss_db_per_us_1ghz≥0；越界一律显式拒绝。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

# 指对数防呆上限（δ 模型求和规模护栏；实际 SAW 器件 N_p 常见 10²–10³）
_N_P_MAX = 1_000_000
# 相位归零判据（栅瓣/峰点 0/0 极限处理阈）
_U_INT_TOL = 1e-12

_SOURCES = {
    "sync": "同步设计闭式 f0=v_R/λ0（λ0=pitch 指对周期口径写死）；Δf_NN=2f0/N_p "
            "与分数带宽 2/N_p（N_p↔带宽倒数）；基板声速文献典型值见模块 docstring",
    "response": "δ 函数模型（Morgan 口径）：|H(f0+Δf)|²=[sin(πN·u)/(N·sin(πu))]²"
                "（u=Δf/f0，几何级数闭式）；零点栅格 Δf=k·f0/N；sinc 近似档仅主瓣"
                "区有效（如实注记）",
    "delay": "τ=L/v_R 恒等；传播损耗 α₁·f²·τ（f² 黏滞律写死、α₁ 注入缺省 0）；"
             "双向 IDT 辐射损耗 10lg2/只（匹配单电极口径），双端 2×10lg2=6.0206dB",
}


def _require_n_finger_pairs(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{key}: n_finger_pairs 须为整数（指对数离散量），得到 {value!r}")
    n = int(value)
    if not 1 <= n <= _N_P_MAX:
        raise ValueError(
            f"{key}: n_finger_pairs 须 ∈[1,{_N_P_MAX}]（δ 模型求和规模护栏），"
            f"得到 {value!r}")
    return n


def _rel_dev(p_ref: float, p_other: float) -> float:
    """相对偏差（分母=max 两者：深零点两侧同为浮点噪声时不互相放大）。"""
    denom = max(p_ref, p_other)
    if denom <= 0.0:
        return 0.0
    return abs(p_ref - p_other) / denom


# ─── 键 1：IDT 同步设计（pitch↔f0 双向）─────────────────────────────────────

@register_calculator(
    "saw_idt_sync_design",
    "声表面波 IDT 同步设计（双向）：指对周期 pitch≡同步声波长 λ0（指宽=缝宽="
    "pitch/2 占空 0.5 惯例）↔ 同步频率 f0=v_R/λ0 双向解；N_p 指对数 → 换能器"
    "长度 L=N_p·λ0、自延迟 τ=L/v_R、零点-零点带宽 Δf_NN=2f0/N_p 与分数带宽 "
    "2/N_p（N_p↔带宽倒数关系）。锚：pitch→f0→pitch 往返逐位；Δf_NN·N_p=2f0 "
    "恒等；ST 石英 1µm→3.158GHz 教科书常数窗。基板声速文献典型值带见模块"
    " docstring（LiNbO3 Y-Z 3488 / ST 石英 3158 / 36°YX-LiTaO3 ≈4212 m/s）",
    (("v_sound_m_s", "float m/s 基板表面声速 v_R（>0；缺省无物理值，覆盖注入）"),
     ("n_finger_pairs", "int 指对数 N_p（∈[1,10⁶]）"),
     ("pitch_um", "float µm 指对周期（≡λ0；与 f0_ghz 恰给其一）"),
     ("f0_ghz", "float GHz 同步频率（与 pitch_um 恰给其一）")),
    required=("v_sound_m_s", "n_finger_pairs"),
)
def saw_idt_sync_design(v_sound_m_s: float, n_finger_pairs: int,
                        pitch_um: float | None = None,
                        f0_ghz: float | None = None) -> dict[str, Any]:
    v = _finite(v_sound_m_s, "v_sound_m_s")
    n_p = _require_n_finger_pairs(n_finger_pairs, "saw_idt_sync_design")
    if v <= 0.0:
        raise ValueError(
            f"saw_idt_sync_design: v_sound_m_s 必须 >0，得到 {v_sound_m_s!r}")
    given = [name for name, val in (("pitch_um", pitch_um), ("f0_ghz", f0_ghz))
             if val is not None]
    if len(given) != 1:
        raise ValueError(
            "saw_idt_sync_design: pitch_um 与 f0_ghz 须恰给其一（双向互斥），"
            f"得到 {given!r}")
    if pitch_um is not None:
        pitch_um_v = _finite(pitch_um, "pitch_um")
        if pitch_um_v <= 0.0:
            raise ValueError(
                "saw_idt_sync_design: pitch_um 必须 >0，得到 "
                f"{pitch_um!r}")
        f0_hz = v / (pitch_um_v * 1e-6)
        lam0_um = pitch_um_v
        solve_dir = "pitch_to_f0"
    else:
        f0_in = _finite(f0_ghz, "f0_ghz")
        if f0_in <= 0.0:
            raise ValueError(
                "saw_idt_sync_design: f0_ghz 必须 >0，得到 "
                f"{f0_ghz!r}")
        f0_hz = f0_in * 1e9
        lam0_um = v / f0_hz * 1e6
        pitch_um_v = lam0_um
        solve_dir = "f0_to_pitch"
    length_um = n_p * lam0_um
    delay_us = length_um * 1e-6 / v * 1e6
    bw_nn_hz = 2.0 * f0_hz / n_p
    return {
        "solve_dir": solve_dir,
        "v_sound_m_s": v,
        "n_finger_pairs": n_p,
        "pitch_um": round(pitch_um_v, 15),
        "f0_ghz": round(f0_hz / 1e9, 15),
        "lambda0_um": round(lam0_um, 15),
        "idt_length_um": round(length_um, 15),
        "idt_delay_us": round(delay_us, 15),
        "null_null_bw_ghz": round(bw_nn_hz / 1e9, 15),
        "fractional_bw_null_null": round(2.0 / n_p, 15),
        "note": (
            "pitch≡λ0 口径（一个指对长度=同步声波长；指宽=缝宽=pitch/2 占空 "
            "0.5 同步惯例）；Δf_NN=2f0/N_p 为 δ 模型零点-零点主瓣宽（−3dB 宽"
            "约 0.89·Δf_NN 量级，精确值走 saw_idt_frequency_response）；基板"
            "声速按文献典型值覆盖注入，实际基板切型/工艺以实测为准"),
        "source": _SOURCES["sync"],
    }


# ─── 键 2：δ 函数模型频响（Dirichlet 核 + sinc 近似档）───────────────────────

@register_calculator(
    "saw_idt_frequency_response",
    "声表面波 IDT δ 函数模型频响：指对=δ 源阵列 → H(f)=Σ e^{-j2πn·f/f0} 几何"
    "级数，归一功率 |H|²=[sin(πN·u)/(N·sin(πu))]²（u=Δf/f0，Dirichlet 核精确"
    "闭式）；零点栅格 Δf=k·f0/N（k=±1…）恒等、栅瓣 f=(m+1)f0 处归一功率=1（阵"
    "列因子混叠如实报告）；同点给 sinc 近似档 [sinc(N·u)]² 与相对偏差（仅主瓣区"
    "有效）。锚：测试侧几何级数逐项和互证 ≤1e-12；首零点 f0(1±1/N) |H|²→0；"
    "半零点 (2/π)² 经典常数；峰点 0dB",
    (("f0_ghz", "float GHz 同步频率（>0）"),
     ("n_finger_pairs", "int 指对数 N_p（∈[1,10⁶]）"),
     ("freq_ghz", "float|list[float] GHz 工作频点（逐点 >0；给绝对频率，失谐"
      "u=(f−f0)/f0 内部换算）")),
    required=("f0_ghz", "n_finger_pairs", "freq_ghz"),
)
def saw_idt_frequency_response(f0_ghz: float, n_finger_pairs: int,
                               freq_ghz: float | list[float]) -> dict[str, Any]:
    f0_hz = _finite(f0_ghz, "f0_ghz") * 1e9
    n_p = _require_n_finger_pairs(n_finger_pairs, "saw_idt_frequency_response")
    if f0_hz <= 0.0:
        raise ValueError(
            f"saw_idt_frequency_response: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    if isinstance(freq_ghz, (list, tuple)):
        freq_list = [_finite(fv, f"freq_ghz[{i}]")
                     for i, fv in enumerate(freq_ghz)]
    else:
        freq_list = [_finite(freq_ghz, "freq_ghz")]
    for i, fv in enumerate(freq_list):
        if fv <= 0.0:
            raise ValueError(
                f"saw_idt_frequency_response: freq_ghz[{i}] 必须 >0（声频点"
                f"物理域），得到 {fv!r}")

    def _dirichlet_power(u: float) -> float:
        """归一功率 [sin(πNu)/(N·sin(πu))]²（0/0 栅瓣/峰点极限=1）。"""
        if abs(u - round(u)) < _U_INT_TOL:
            return 1.0
        return (math.sin(math.pi * n_p * u)
                / (n_p * math.sin(math.pi * u))) ** 2

    def _geometric_power(f_over_f0: float) -> float:
        """第二路线：几何级数逐项复数求和（#118 双实现载体），
        与 Dirichlet 闭式互为独立数值路线，逐点出偏差列。"""
        acc = 0.0 + 0.0j
        for n in range(n_p):
            acc += cmath.exp(-2j * math.pi * n * f_over_f0)
        return (abs(acc) / n_p) ** 2

    rows: list[dict[str, Any]] = []
    for f_ghz in freq_list:
        f_hz = f_ghz * 1e9
        u = (f_hz - f0_hz) / f0_hz
        p_exact = _dirichlet_power(u)
        p_geo = _geometric_power(f_hz / f0_hz)
        p_sinc = (math.sin(math.pi * n_p * u)
                  / (math.pi * n_p * u)) ** 2 if abs(u) > _U_INT_TOL else 1.0
        rows.append({
            "f_ghz": round(f_ghz, 15),
            "detune_frac": round(u, 15),
            "power_exact": round(p_exact, 18),
            "mag_db": (
                None if p_exact <= 0.0
                else round(10.0 * math.log10(p_exact), 12)),
            "power_geometric_sum": round(p_geo, 18),
            "exact_vs_geo_rel_dev": round(_rel_dev(p_exact, p_geo), 18),
            "power_sinc_approx": round(p_sinc, 18),
            "sinc_rel_dev": round(_rel_dev(p_exact, p_sinc), 18),
        })
    first_null_offset_ghz = f0_ghz / n_p
    return {
        "f0_ghz": f0_ghz,
        "n_finger_pairs": n_p,
        "n_points": len(rows),
        "points": rows,
        "first_null_offsets_ghz": [
            round(f0_ghz - first_null_offset_ghz, 15),
            round(f0_ghz + first_null_offset_ghz, 15)],
        "null_null_bw_ghz": round(2.0 * first_null_offset_ghz, 15),
        "model": "delta_function",
        "note": (
            "δ 函数模型档位：忽略指间电学再生/内反射/压电指边缘效应二阶项"
            "（精确器件响应走 TCWT/COM 建模，不在本键口径）；栅瓣 f=(m+1)·f0"
            " 处归一功率=1 为 δ 阵列因子混叠（真实 IDT 被指内频响压低，如实"
            "注记）；sinc 近似档仅主瓣区（|u|≪1）有效，栅瓣区偏差大属模型"
            "性质非数值误差"),
        "source": _SOURCES["response"],
    }


# ─── 键 3：SAW 延迟线（τ=L/v + 损耗预算）────────────────────────────────────

@register_calculator(
    "saw_delay_line",
    "声表面波延迟线：τ=L/v_R 恒等（L=收发 IDT 中心距）+ 传播损耗预算 "
    "α=α₁·(f/1GHz)²·τ（f² 黏滞衰减律写死；α₁=1GHz 每微秒损耗系数注入，缺省 "
    "0=纯延迟——材料系数文献发散不做缺省物理值）+ 双向换能器辐射损耗 10lg2="
    "3.0103dB/只（匹配单电极口径，双端合计 6.0206dB 恒等锚）+ 波长数标尺。锚："
    "τ=L/v 测试侧独立换算；f×2→损耗×4 标度；双端 2×10lg2 常数",
    (("f0_ghz", "float GHz 工作频率（>0）"),
     ("v_sound_m_s", "float m/s 基板声速（>0）"),
     ("idt_gap_mm", "float mm 收发 IDT 中心距（>0）"),
     ("loss_db_per_us_1ghz", "float dB/µs@1GHz 传播损耗系数 α₁（≥0，缺省 0；"
      "f² 标度口径，实测系数按材料文献/实验覆盖注入）")),
    required=("f0_ghz", "v_sound_m_s", "idt_gap_mm"),
)
def saw_delay_line(f0_ghz: float, v_sound_m_s: float, idt_gap_mm: float,
                   loss_db_per_us_1ghz: float = 0.0) -> dict[str, Any]:
    f_hz = _finite(f0_ghz, "f0_ghz") * 1e9
    v = _finite(v_sound_m_s, "v_sound_m_s")
    gap_mm = _finite(idt_gap_mm, "idt_gap_mm")
    a1 = _finite(loss_db_per_us_1ghz, "loss_db_per_us_1ghz")
    if f_hz <= 0.0:
        raise ValueError(
            f"saw_delay_line: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    if v <= 0.0:
        raise ValueError(
            f"saw_delay_line: v_sound_m_s 必须 >0，得到 {v_sound_m_s!r}")
    if gap_mm <= 0.0:
        raise ValueError(
            f"saw_delay_line: idt_gap_mm 必须 >0，得到 {idt_gap_mm!r}")
    if a1 < 0.0:
        raise ValueError(
            "saw_delay_line: loss_db_per_us_1ghz 必须 ≥0（损耗系数非负），"
            f"得到 {loss_db_per_us_1ghz!r}")
    delay_us = gap_mm * 1e-3 / v * 1e6
    lam0_um = v / f_hz * 1e6
    n_wavelengths = gap_mm * 1e3 / lam0_um
    prop_loss_db = a1 * (f0_ghz ** 2.0) * delay_us
    bilateral_per_idt_db = 10.0 * math.log10(2.0)
    total_loss_db = prop_loss_db + 2.0 * bilateral_per_idt_db
    return {
        "f0_ghz": f0_ghz,
        "v_sound_m_s": v,
        "idt_gap_mm": gap_mm,
        "lambda0_um": round(lam0_um, 15),
        "gap_wavelengths": round(n_wavelengths, 15),
        "delay_us": round(delay_us, 15),
        "loss_db_per_us_1ghz": a1,
        "propagation_loss_db": round(prop_loss_db, 12),
        "bilateral_idt_loss_db_each": round(bilateral_per_idt_db, 12),
        "bilateral_idt_loss_db_total": round(2.0 * bilateral_per_idt_db, 12),
        "total_loss_db": round(total_loss_db, 12),
        "note": (
            "总损耗口径=传播+双向辐射两项（未含 IDT 变损/压电耦合损耗/TTE "
            "三次渡越等，如实注记）；10lg2/只=双向 IDT 激励两路均分的匹配单电"
            "极口径，单向化结构（SPUDT）不适用；α₁ 缺省 0=不冒充材料常数，"
            "实测系数按基板/频率覆盖注入"),
        "source": _SOURCES["delay"],
    }
