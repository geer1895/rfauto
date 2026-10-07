"""PT-6 固件工件三出口确定性内核（规格书 规格深案 §B-6）。

三出口口径（铁律 5 来源写 docstring；数值只在确定性内核，铁律 7；裁判=独立
路径不自证，#118）：

- **① beam_codeword_table 波束码字表**：列
  element_id/x_mm/y_mm/u0/phase_target_deg/phase_quant_deg/code_word/bits/
  quant_loss_db/temp_comp_channel，CSV+C 头（const 数组文本）双出。
  相位量化单源消费 metasurface_lut.quantize_phase_deg（栅格取整）与
  quantization_loss_db（:439，E[e^{jε}]² 精确期望口径）；code_word =
  round(φ_target/步长) mod 2^bits，phase_quant_deg = code·步长（规范域
  [0,360)，与 quantize_phase_deg mod 360 逐点相等）。u0=单元幅度权
  （线性，缺省 1.0）；temp_comp_channel=温补通道分配（element 序号模
  通道数，确定性）。
  **回代判据（规格原文）**：码字回代 ΔGain 落 quantization_loss_db 公式带
  ±0.2dB—— ΔGain = 10·log10(|Σ u0·e^{j(φt−φq)}|²/(Σu0)²) 为量化误差实现
  的相干增益因子（error-only：目标相位本身不含入判据，含入则混入指向
  失配噪声——2026-10-02 数值预探 runs/pt6 实证：对均匀随机目标相位按
  |Σe^{jφt}|² 归一波动可达 ±5dB，误差-only 归一后 ≤0.1dB 收敛公式带）。
  大 N 下 |Σe^{jε}|²/N² → sinc²(1/2^b) + (1−sinc²)/N（精确期望+有限 N
  修正项），N=1024..16384 实测带内 ≤0.09dB。u0 非均匀锥削时精确期望含
  锥削超额项 (1−sinc²)·Σu0²/(Σu0)²（实得损失偏小、方向declared），门按
  公式带判时该偏差如实入 notes（缺省 u0=1 判据严格成立）。
- **② varactor_dac_table 变容管 DAC 表**：f→C（varactor.py
  varactor_load_capacitance_pf 主谐振方程闭式逆）→V（bias_for_capacitance_v
  :118 突变结精确逆）→码（LSB=V_ref/2^bw，四舍五入+饱和计数）。
  审计输出={bit_width,monotonic_v,monotonic_c,saturation_count}（规格钉键）：
  monotonic_v/V 随 f 单调增、monotonic_c/C 随 f 单调减（主谐振方程链的
  物理单调性审计，任何 False 即链路配置错误）；saturation_count=码饱和
  （V 超出 DAC 满量程 V_ref·(2^bw−1)/2^bw）行数。f 非严格递增/窗外/
  C>cj0（正偏域）显式 ValueError——固件表不做部分行（不造假数）。
- **③ dpd_fixed_point_table DPD 定点表**：coeffs(K,M+1)（dpd_static.py:143
  MemoryPolyModel.coeffs 同构）Q 格式定标（scale=2^frac_bits，字宽
  word_bits 含符号）+舍入回代预检+溢出告警。回代=apply_memory_polynomial
  （:228）正演 float vs 定点输出：NMSE（量化误差功率/信号功率，dB）+
  复增益漂移 |ΔGain|（amam_linear_fit 口径）；门=规格带"劣化 ≤0.5dB"：
  NMSE ≤ −0.5 dB（字面下限口径：量化误差至少低于信号 0.5dB）且（可选
  提供 pa_coeffs 时）级联 NMSE 劣化 ≤0.5dB（evaluate_dpd_cascade 前后
  残差面——ACPR 精确预测按 dpd_static F-E 表件 8 预声明边界不产数字，
  NMSE 为声明内代理面）。溢出=|round(c·scale)| 超出有符号字域
  [−2^{wb−1}, 2^{wb−1}−1]：告警逐系数落账+饱和钳位（固件惯例），不静默。

全部确定性：纯 numpy 定量，无随机、无网络、无全局状态；dict 进出 JSON
可序列化（复数按 dpd_static.to_dict 的 {"re","im"} 对约定）；接口纪律同
manufacturing_stats.py（bool 显式拒收 df7+⑯、缺失判 is not None #364④、
输入非法 ValueError、无 IO——文件写出由 CLI 薄壳承担）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

#: 波束码字表 CSV 列序（规格书 §B-6① 钉死；C 头数组序同源）
BEAM_COLUMNS = (
    "element_id", "x_mm", "y_mm", "u0", "phase_target_deg",
    "phase_quant_deg", "code_word", "bits", "quant_loss_db",
    "temp_comp_channel",
)

#: varactor DAC 表 CSV 列序（规格钉键外的行级明细，含饱和旗与重建残差）
VARACTOR_COLUMNS = (
    "f_target_ghz", "c_req_pf", "v_bias_v", "dac_code", "v_dac_v",
    "v_residual_v", "saturated",
)

#: DPD 定点表 CSV 列序（逐系数长表：定点整数+回代浮点+溢出旗）
DPD_COLUMNS = (
    "k", "m", "re_int", "im_int", "re_float", "im_float", "overflow",
)

#: 回代判据规格带（|ΔGain − quantization_loss_db| 上限，dB，规格钉值）
BEAM_GAIN_BAND_DB = 0.2

#: DPD 定点回代规格带（NMSE/级联 NMSE 劣化上限，dB，规格钉值）
DPD_DEGRADATION_GATE_DB = 0.5


# ─── 入参守卫（manufacturing_stats.py 口径同源）──────────────────────────────


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数字，实际 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _int_in(value: Any, name: str, lo: int, hi: int) -> int:
    """整数收敛：bool 显式拒收、非整数值拒收、域检查（dpd_static._int_order 同族）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    try:
        iv = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    if not lo <= iv <= hi:
        raise ValueError(f"{name} 须在 [{lo}, {hi}] 内，得 {iv}")
    return iv


def _real_vector(value: Any, name: str, *, positive: bool = False) -> np.ndarray:
    """实向量收敛：1-D、有限、bool 拒收（manufacturing_stats._sample_vector 同族）。"""
    if isinstance(value, (str, bytes, bool)):
        raise ValueError(f"{name} 必须是数值序列（不接受标量/字符串）")
    if isinstance(value, (list, tuple)) and any(isinstance(v, bool) for v in value):
        raise ValueError(f"{name} 不接受 bool 元素（float(True)=1.0 静默污染统计）")
    raw = np.asarray(value)
    if raw.dtype == bool:
        raise ValueError(f"{name} 不接受 bool 序列（float(True)=1.0 静默污染统计）")
    try:
        arr = raw.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须可转换为实数数组: {exc}") from None
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须为 1-D 数组，实际 ndim={arr.ndim}")
    if arr.size == 0:
        raise ValueError(f"{name} 不能为空")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 必须全为有限数")
    if positive and float(np.min(arr)) <= 0.0:
        raise ValueError(f"{name} 必须全 >0")
    return arr


def _circ_diff_deg(a: float, b: float) -> float:
    """相位圆周差（度，[−180,180]，metasurface_lut 同口径）。"""
    return (a - b + 180.0) % 360.0 - 180.0


# ═══ ① 波束码字表（CSV+C 头双出）══════════════════════════════════════════


def beam_codeword_table(
    element_ids: Any,
    x_mm: Any,
    y_mm: Any,
    phase_target_deg: Any,
    *,
    bits: int,
    u0: Any = None,
    temp_comp_channels: int = 4,
) -> dict[str, Any]:
    """波束码字表（PT-6①）：目标相位 → b-bit 码字 + 期望量化损失列。

    Args:
        element_ids: 单元编号序列（int，bool 拒收）。
        x_mm / y_mm: 单元平面坐标（mm，有限实数）。
        phase_target_deg: 目标相位（度，任意实数——mod 360 圆周量）。
        bits: 相位量化位宽（1..16）。
        u0: 单元幅度权（线性，正实数；None=全 1.0）。
        temp_comp_channels: 温补通道数（≥1；channel = 序号 mod 通道数）。

    Returns:
        {ok, bits, n_elements, n_levels, quant_step_deg, temp_comp_channels,
        quant_loss_db, columns, rows, notes}——rows 逐 dict 按
        BEAM_COLUMNS 键序；phase_quant_deg=code·步长（规范域，与
        quantize_phase_deg(target) mod 360 逐点相等——单测钉）；code_word
        ∈[0, 2^bits)；quant_loss_db 列=quantization_loss_db(bits)（逐行
        同值：期望口径）。

    Raises:
        ValueError: 入参非法（长度不等/空序列/bits 越域/u0 非正等）。
    """
    from rfauto.core.metasurface_lut import quantization_loss_db, quantize_phase_deg

    b = _int_in(bits, "bits", 1, 16)
    n_ch = _int_in(temp_comp_channels, "temp_comp_channels", 1, 4096)
    xv = _real_vector(x_mm, "x_mm")
    yv = _real_vector(y_mm, "y_mm")
    pv = _real_vector(phase_target_deg, "phase_target_deg")
    if not (xv.size == yv.size == pv.size):
        raise ValueError(
            f"x_mm/y_mm/phase_target_deg 长度不等: {xv.size}/{yv.size}/{pv.size}")
    if u0 is None:
        uv = np.ones(xv.size)
    else:
        uv = _real_vector(u0, "u0", positive=True)
        if uv.size != xv.size:
            raise ValueError(f"u0 长度 {uv.size} != 单元数 {xv.size}")
    raw_ids = np.asarray(element_ids)
    if raw_ids.ndim != 1 or raw_ids.size != xv.size:
        raise ValueError(
            f"element_ids 须为长度 {xv.size} 的 1-D 序列，得 ndim={raw_ids.ndim} "
            f"size={raw_ids.size}")
    ids: list[int] = []
    for k, eid in enumerate(raw_ids.tolist()):
        if isinstance(eid, bool):
            raise ValueError("element_ids 不接受 bool")
        if isinstance(eid, float) and not eid.is_integer():
            raise ValueError(f"element_ids[{k}]={eid!r} 非整数")
        ids.append(int(eid))

    n_levels = 2 ** b
    step = 360.0 / n_levels
    loss_db = quantization_loss_db(b)
    rows: list[dict[str, Any]] = []
    for k in range(xv.size):
        tgt = float(pv[k])
        q = quantize_phase_deg(tgt, b)          # 内核单源取整（可落 ±步长/2 外沿）
        code = round(q / step) % n_levels  # 由 q 反解码（q/step 为整数±浮点 eps）
        rows.append({
            "element_id": ids[k],
            "x_mm": float(xv[k]),
            "y_mm": float(yv[k]),
            "u0": float(uv[k]),
            "phase_target_deg": tgt,
            "phase_quant_deg": float(code * step),  # 规范域 [0,360)
            "code_word": code,
            "bits": b,
            "quant_loss_db": loss_db,
            "temp_comp_channel": k % n_ch,
        })
    return {
        "ok": True,
        "bits": b,
        "n_elements": int(xv.size),
        "n_levels": n_levels,
        "quant_step_deg": step,
        "temp_comp_channels": n_ch,
        "quant_loss_db": loss_db,
        "columns": list(BEAM_COLUMNS),
        "rows": rows,
        "notes": [
            "phase_quant_deg=code_word·步长（规范域），与 metasurface_lut."
            "quantize_phase_deg(target) mod 360 逐点相等",
            "quant_loss_db 列为 quantization_loss_db(bits) 期望口径（逐行同值）；"
            "单表实现回代判据见 beam_backsub_audit",
        ],
    }


def beam_backsub_audit(table: dict[str, Any], *,
                       band_db: float = BEAM_GAIN_BAND_DB) -> dict[str, Any]:
    """码字回代判据（PT-6①规格原文）：ΔGain 落 quantization_loss_db 带 ±0.2dB。

    ΔGain = 10·log10(|Σ u0·e^{j(φt−φq)}|²/(Σu0)²)——量化误差实现的相干
    增益因子（error-only 归一，见模块 docstring 预探结论）。两级判据：
    phase_ok=逐行圆周回代相位误差 ≤ 步长/2（取整性质，恒真面）；gain 门=
    |ΔGain − (−quantization_loss_db(bits))| ≤ band_db。u0 非均匀锥削的
    期望超额项如实入 notes（方向：实得损失偏小）。

    Returns:
        {ok, verdict(PASS|FAIL), phase_ok, max_phase_err_deg, phase_gate_deg,
        gain_loss_db, formula_loss_db, delta_db, band_db, n_elements, notes}。
    """
    from rfauto.core.metasurface_lut import quantization_loss_db

    rows = table.get("rows")
    if not rows:
        raise ValueError("table 缺 rows（先经 beam_codeword_table 生成）")
    bits_v = _int_in(table.get("bits"), "table.bits", 1, 16)
    step = float(table["quant_step_deg"])
    band = _finite(band_db, "band_db")
    if band <= 0.0:
        raise ValueError(f"band_db 必须 >0，得 {band_db!r}")

    max_err = 0.0
    num = 0.0 + 0.0j
    w_sum = 0.0
    for row in rows:
        err = abs(_circ_diff_deg(float(row["phase_target_deg"]),
                                 float(row["phase_quant_deg"])))
        if err > max_err:
            max_err = err
        w = _finite(row["u0"], "row.u0")
        eps = math.radians(_circ_diff_deg(float(row["phase_target_deg"]),
                                          float(row["phase_quant_deg"])))
        num += w * complex(math.cos(eps), math.sin(eps))
        w_sum += w
    if w_sum <= 0.0:
        raise ValueError("u0 权和为 0——增益因子无定义")
    gain_loss_db = 10.0 * math.log10(abs(num) ** 2 / w_sum ** 2)
    formula_loss_db = -quantization_loss_db(bits_v)
    delta_db = abs(gain_loss_db - formula_loss_db)
    w_arr = np.asarray([_finite(r["u0"], "row.u0") for r in rows])
    sinc = 10.0 ** (-quantization_loss_db(bits_v) / 10.0)  # = sinc²(1/2^b)
    excess = float((1.0 - sinc) * np.sum(w_arr**2) / w_sum**2)

    notes: list[str] = []
    if excess > 1e-9:
        notes.append(
            f"u0 非均匀锥削：精确期望含超额项 {excess:.4g}（实得损失较公式"
            f"偏小 ~{10 * math.log10(1.0 + excess / max(sinc, 1e-30)):.3f}dB），"
            "公式带判据按均匀权口径预声明")
    phase_ok = max_err <= step / 2.0 + 1e-9
    verdict = "PASS" if phase_ok and delta_db <= band else "FAIL"
    return {
        "ok": True,
        "verdict": verdict,
        "bits": bits_v,
        "n_elements": len(rows),
        "quant_step_deg": step,
        "phase_ok": phase_ok,
        "max_phase_err_deg": max_err,
        "phase_gate_deg": step / 2.0,
        "gain_loss_db": gain_loss_db,
        "formula_loss_db": formula_loss_db,
        "delta_db": delta_db,
        "band_db": band,
        "notes": notes,
    }


def _fmt(v: Any) -> str:
    """CSV 数值格式化：int 直写、float 全精度 repr（metasurface_lut.to_csv 同款）。"""
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    return repr(float(v))


def beam_table_csv(table: dict[str, Any]) -> str:
    """波束码字表 CSV 文本（列序=BEAM_COLUMNS 规格钉死）。"""
    cols = list(BEAM_COLUMNS)
    lines = [",".join(cols)]
    for row in table["rows"]:
        lines.append(",".join(_fmt(row[c]) for c in cols))
    return "\n".join(lines) + "\n"


def beam_table_c_header(table: dict[str, Any], *,
                        array_name: str = "beam_code_table") -> str:
    """波束码字表 C 头文本（const 数组；code_word uint16 + x/y/u0 float）。

    纯文本拼装（无 IO）；确定性格式：每元素一行带 element_id 注释。
    """
    name = str(array_name)
    if not name.isidentifier():
        raise ValueError(f"array_name 须为合法 C 标识符，得 {array_name!r}")
    rows = table["rows"]
    n = len(rows)
    b = int(table["bits"])
    step = float(table["quant_step_deg"])
    macro = name.upper()
    out: list[str] = []
    out.append("/* rfauto firmware beam — generated by core/firmware_export.py;"
               " do not edit by hand. */")
    out.append(f"/* n_elements={n} bits={b} quant_step_deg={step:.6f} */")
    out.append("#include <stdint.h>")
    out.append("")
    out.append(f"#define {macro}_N_ELEMENTS {n}u")
    out.append(f"#define {macro}_PHASE_BITS {b}u")
    out.append("")
    out.append(f"static const uint16_t {name}_code_word[{macro}_N_ELEMENTS] = {{")
    for row in rows:
        out.append(f"    {int(row['code_word'])}u, "
                   f"/* element_id={int(row['element_id'])} */")
    out.append("};")
    out.append("")
    for col in ("x_mm", "y_mm", "u0"):
        out.append(f"static const float {name}_{col}[{macro}_N_ELEMENTS] = {{")
        for row in rows:
            out.append(f"    {float(row[col]):.9g}, "
                       f"/* element_id={int(row['element_id'])} */")
        out.append("};")
        out.append("")
    return "\n".join(out)


# ═══ ② varactor DAC 表 ══════════════════════════════════════════════════════


def varactor_dac_table(
    f_targets_ghz: Any,
    *,
    line_len_mm: float,
    z0_ohm: float,
    ereff: float,
    cj0_pf: float,
    phi_v: float,
    v_ref_v: float,
    bit_width: int,
) -> dict[str, Any]:
    """变容管 DAC 偏置表（PT-6②）：f→C→V→码，物理单调性审计+饱和计数。

    链路（只读消费既有内核，不改语义）：主谐振方程闭式逆
    varactor.varactor_load_capacitance_pf（f 须在装载窗 (f_λ/4, f_λ/2)）
    → 突变结精确逆 varactor.bias_for_capacitance_v（V=φ((Cj0/C)²−1)，
    0<C≤Cj0 反偏域）→ DAC 码 = round(V/LSB) 饱和于 2^bw−1，
    LSB = V_ref/2^bw（规格书 §B-6② 口径）。

    Args:
        f_targets_ghz: 目标频率序列（GHz，**严格递增**——单调审计的
            自变量序；乱序显式 ValueError 不静默排序）。
        line_len_mm / z0_ohm / ereff: 装载臂长（mm）/阻抗（Ω）/有效介电常数。
        cj0_pf / phi_v: 突变结零偏电容（pF）/内建电位（V）。
        v_ref_v: DAC 满量程参考电压（V，>0）。
        bit_width: DAC 位宽 bw（1..24）。

    Returns:
        {ok, bit_width, v_ref_v, lsb_v, full_scale_v, columns, rows,
        audit:{bit_width, monotonic_v, monotonic_c, saturation_count}, notes}
        ——rows 列见 VARACTOR_COLUMNS（v_dac_v=code·LSB 重建值，
        v_residual_v=v_dac−v_bias：非饱和行 |残差| ≤ LSB/2）。

    Raises:
        ValueError: 频率乱序/窗外/C>cj0（正偏域）/入参非法——固件表不做
            部分行（tuning_bias_plan 的 feasible=False 逐行口径在此不适用：
            缺行 DAC 表会静默改变器件调谐覆盖）。
    """
    from rfauto.core.varactor import bias_for_capacitance_v, varactor_load_capacitance_pf

    fv = _real_vector(f_targets_ghz, "f_targets_ghz", positive=True)
    if fv.size < 2:
        raise ValueError("f_targets_ghz 至少 2 点（单调审计需要）")
    if not bool(np.all(np.diff(fv) > 0.0)):
        raise ValueError("f_targets_ghz 须严格递增（单调审计自变量序；"
                         "乱序请调用方先排序）")
    bw = _int_in(bit_width, "bit_width", 1, 24)
    v_ref = _finite(v_ref_v, "v_ref_v")
    if v_ref <= 0.0:
        raise ValueError(f"v_ref_v 必须 >0，得 {v_ref_v!r}")
    l_len = _finite(line_len_mm, "line_len_mm")
    z0 = _finite(z0_ohm, "z0_ohm")
    er = _finite(ereff, "ereff")
    cj0 = _finite(cj0_pf, "cj0_pf")
    phi = _finite(phi_v, "phi_v")
    if l_len <= 0.0 or z0 <= 0.0 or er <= 0.0:
        raise ValueError("line_len_mm/z0_ohm/ereff 须 >0")
    if cj0 <= 0.0 or phi <= 0.0:
        raise ValueError("cj0_pf/phi_v 须 >0")

    n_levels = 2 ** bw
    lsb = v_ref / n_levels
    full_scale = (n_levels - 1) * lsb
    rows: list[dict[str, Any]] = []
    saturation_count = 0
    for f_t in fv.tolist():
        f = float(f_t)
        try:
            c_req = varactor_load_capacitance_pf(f, l_len, z0, er)
        except ValueError as exc:
            raise ValueError(f"f={f}GHz：{exc}") from None
        if c_req > cj0:
            raise ValueError(
                f"f={f}GHz 需 C={c_req:.6g}pF > cj0={cj0}pF（正偏域，反偏"
                "闭式不可达）——下移调谐窗或增大 cj0")
        v_bias = bias_for_capacitance_v(c_req, cj0, phi)
        code_f = v_bias / lsb
        code = round(code_f)
        saturated = code > n_levels - 1
        if saturated:
            code = n_levels - 1
            saturation_count += 1
        v_dac = code * lsb
        rows.append({
            "f_target_ghz": f,
            "c_req_pf": c_req,
            "v_bias_v": v_bias,
            "dac_code": code,
            "v_dac_v": v_dac,
            "v_residual_v": v_dac - v_bias,
            "saturated": saturated,
        })
    # 物理单调性审计（主谐振方程链：f↑ ⇒ C↓ ⇒ V↑；容差 1e-9 相对）
    cs = [r["c_req_pf"] for r in rows]
    vs = [r["v_bias_v"] for r in rows]
    tol_c = 1e-9 * max(abs(c) for c in cs)
    tol_v = 1e-9 * max(abs(v) for v in vs)
    monotonic_c = all(cs[i + 1] <= cs[i] + tol_c for i in range(len(cs) - 1))
    monotonic_v = all(vs[i + 1] >= vs[i] - tol_v for i in range(len(vs) - 1))
    return {
        "ok": True,
        "bit_width": bw,
        "v_ref_v": v_ref,
        "lsb_v": lsb,
        "full_scale_v": full_scale,
        "n_levels": n_levels,
        "columns": list(VARACTOR_COLUMNS),
        "rows": rows,
        "audit": {
            "bit_width": bw,
            "monotonic_v": monotonic_v,
            "monotonic_c": monotonic_c,
            "saturation_count": saturation_count,
        },
        "notes": [
            "链路：varactor_load_capacitance_pf（主谐振方程闭式逆）→ "
            "bias_for_capacitance_v（突变结精确逆）→ code=round(V/LSB) "
            "饱和于 2^bw−1；LSB=V_ref/2^bw（规格 §B-6②）",
            "monotonic_v/monotonic_c 为主谐振方程链物理单调性审计（f↑⇒C↓⇒V↑），"
            "False 即链路配置错误（非量化效应）",
        ],
    }


def varactor_table_csv(table: dict[str, Any]) -> str:
    """varactor DAC 表 CSV 文本（列序=VARACTOR_COLUMNS）。"""
    cols = list(VARACTOR_COLUMNS)
    lines = [",".join(cols)]
    for row in table["rows"]:
        lines.append(",".join(_fmt(row[c]) for c in cols))
    return "\n".join(lines) + "\n"


# ═══ ③ DPD 定点表 ════════════════════════════════════════════════════════════


def _coeffs_matrix(coeffs: Any, name: str = "coeffs") -> np.ndarray:
    """(K, M+1) 复系数矩阵收敛：MemoryPolyModel 或 2-D 数组、有限性。"""
    if hasattr(coeffs, "coeffs"):  # MemoryPolyModel 鸭子接收（dpd_static:143）
        coeffs = coeffs.coeffs
    arr = np.asarray(coeffs, dtype=complex)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.ndim != 2:
        raise ValueError(f"{name} 必须为 1-D/2-D 数组，实际 ndim={arr.ndim}")
    if arr.shape[0] < 1 or arr.shape[1] < 1:
        raise ValueError(f"{name} 形状须 (K>=1, M+1>=1)，得 {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含 NaN/Inf（非有限系数）")
    return arr


def _complex_vector(value: Any, name: str) -> np.ndarray:
    """复基带向量收敛：元素 {"re","im"} 对 / [re,im] 对 / 复数序列。"""
    if isinstance(value, (str, bytes, bool)):
        raise ValueError(f"{name} 必须是数值序列（不接受标量/字符串）")
    raw = np.asarray(value)
    if raw.dtype == bool:
        raise ValueError(f"{name} 不接受 bool 序列（df7+⑯）")
    try:
        arr = raw.astype(complex)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须可转换为复数数组: {exc}") from None
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须为 1-D 数组，实际 ndim={arr.ndim}")
    if arr.size == 0:
        raise ValueError(f"{name} 不能为空")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含 NaN/Inf（非有限样本）")
    return arr


def dpd_fixed_point_table(
    coeffs: Any,
    x: Any,
    *,
    word_bits: int = 16,
    frac_bits: int = 12,
    pa_coeffs: Any = None,
    nmse_gate_db: float = DPD_DEGRADATION_GATE_DB,
) -> dict[str, Any]:
    """DPD 定点表（PT-6③）：Q 格式定标 + 舍入回代预检 + 溢出告警。

    定点口径：有符号字宽 word_bits（含符号位）、小数位 frac_bits，
    scale=2^frac_bits；q = round(c·scale)（numpy.rint 银行家舍入——
    固件实现若为四舍五入差异 ≤0.5 LSB，预声明面）；溢出=出有符号域
    [−2^{wb−1}, 2^{wb−1}−1]，逐系数告警+饱和钳位。

    回代预检（规格：apply_memory_polynomial 正演 NMSE/劣化 ≤0.5dB 门）：
    - nmse_db = 10·log10(Σ|y_q−y_f|²/Σ|y_f|²)（量化误差功率/信号功率），
      门1（字面下限口径）：nmse_db ≤ −nmse_gate_db（误差至少低于信号
      0.5dB——粗 Q 档在此翻车，见锚树 FAIL 例）；
    - gain_delta_db = |20·log10(|g_q|/|g_f|)|（amam_linear_fit 复增益漂移）；
    - pa_coeffs 给出时加门2（级联劣化口径）：evaluate_dpd_cascade 的
      residual_post 前/后 NMSE 差 ≤ nmse_gate_db。ACPR 精确预测按
      dpd_static F-E 表件 8 预声明边界不产数字（NMSE 为声明内代理面）。

    Args:
        coeffs: (K, M+1) 复系数（MemoryPolyModel 或数组）。
        x: 回代评估激励（复基带，1-D，非空——NMSE 依激励面，调用方声明）。
        word_bits / frac_bits: 字宽（2..32）/小数位（1..word_bits−1）。
        pa_coeffs: 可选 PA 系数（同形态）——启用级联劣化门2。
        nmse_gate_db: 规格带（dB，>0，缺省 0.5）。

    Returns:
        {ok, word_bits, frac_bits, q_format, scale, lsb, x_len,
        coeffs_int, overflow(list of {k,m,part,value,clamped}),
        warnings_count, nmse_db, gain_delta_db, gain_float, gain_quant,
        cascade(None|{nmse_before_db, nmse_after_db, degradation_db}),
        nmse_gate_db, verdict, notes}。verdict=PASS 当全部适用门绿。
    """
    from rfauto.core.dpd_static import amam_linear_fit, apply_memory_polynomial, evaluate_dpd_cascade

    c = _coeffs_matrix(coeffs)
    xv = _complex_vector(x, "x")
    wb = _int_in(word_bits, "word_bits", 2, 32)
    fb = _int_in(frac_bits, "frac_bits", 1, wb - 1)
    gate = _finite(nmse_gate_db, "nmse_gate_db")
    if gate <= 0.0:
        raise ValueError(f"nmse_gate_db 必须 >0，得 {nmse_gate_db!r}")

    scale = float(2 ** fb)
    half = 2 ** (wb - 1)
    q_re = np.rint(c.real * scale)
    q_im = np.rint(c.imag * scale)
    overflow: list[dict[str, Any]] = []
    k_order, m_depth_p1 = c.shape
    for ki in range(k_order):
        for mi in range(m_depth_p1):
            for part, qv, cv in (("re", q_re[ki, mi], c[ki, mi].real),
                                 ("im", q_im[ki, mi], c[ki, mi].imag)):
                if not (-half <= qv <= half - 1):
                    clamped = float(np.clip(qv, -half, half - 1))
                    overflow.append({
                        "k": ki, "m": mi, "part": part,
                        "value": float(qv), "clamped": clamped,
                        "float": float(cv),
                    })
    # 定点整数=固件实收工件（饱和钳位后；溢出原值只在告警列表留痕）
    re_int = np.clip(q_re, -half, half - 1).astype(int)
    im_int = np.clip(q_im, -half, half - 1).astype(int)
    coeffs_int = [[{"re": int(re_int[ki, mi]), "im": int(im_int[ki, mi])}
                   for mi in range(m_depth_p1)] for ki in range(k_order)]
    coeffs_q = (re_int + 1j * im_int) / scale

    y_f = apply_memory_polynomial(xv, c)
    y_q = apply_memory_polynomial(xv, coeffs_q)
    p_f = float(np.sum(np.abs(y_f) ** 2))
    if p_f <= 0.0:
        raise ValueError("回代参考输出零功率（激励/系数退化）——NMSE 无定义")
    err_p = float(np.sum(np.abs(y_q - y_f) ** 2))
    nmse_db = -math.inf if err_p == 0.0 else 10.0 * math.log10(err_p / p_f)
    g_f = amam_linear_fit(xv, y_f)["gain"]
    g_q = amam_linear_fit(xv, y_q)["gain"]
    if abs(g_f) == 0.0 or abs(g_q) == 0.0:
        raise ValueError("复增益为零——增益漂移面无定义")
    gain_delta_db = abs(20.0 * math.log10(abs(g_q) / abs(g_f)))

    cascade: dict[str, Any] | None = None
    if pa_coeffs is not None:
        pa = _coeffs_matrix(pa_coeffs, "pa_coeffs")
        res_f = evaluate_dpd_cascade(xv, pa, c)["residual_post"]
        res_q = evaluate_dpd_cascade(xv, pa, coeffs_q)["residual_post"]
        if res_f == 0.0 and res_q == 0.0:
            degradation_db = 0.0          # 完全线化前后均零残差：零劣化（恒等退化）
        elif res_f == 0.0:
            degradation_db = math.inf     # 浮点模型完美线化、定点引入残差
        else:
            nmse_before_db = 20.0 * math.log10(res_f)
            nmse_after_db = -math.inf if res_q == 0.0 else 20.0 * math.log10(res_q)
            degradation_db = nmse_after_db - nmse_before_db
        cascade = {
            "nmse_before_db": (-math.inf if res_f == 0.0
                               else 20.0 * math.log10(res_f)),
            "nmse_after_db": (-math.inf if res_q == 0.0
                              else 20.0 * math.log10(res_q)),
            "degradation_db": degradation_db,
        }

    notes = [
        "ACPR 精确预测按 dpd_static F-E 表件 8 预声明边界不产数字；"
        "NMSE/级联 NMSE 为规格声明内代理面",
        f"定点口径 Q{wb - fb - 1}.{fb}（有符号，LSB={1.0 / scale:.6g}）；"
        "舍入=numpy.rint（银行家），与四舍五入固件差 ≤0.5 LSB 预声明",
    ]
    gates_ok = nmse_db <= -gate
    if not gates_ok:
        notes.append(
            f"门1 FAIL：nmse_db={nmse_db:.2f} 未低于 −{gate}dB 下限"
            "（Q 档过粗，量化误差吃掉模型）")
    if cascade is not None:
        deg = float(cascade["degradation_db"])
        if not deg <= gate:
            gates_ok = False
            notes.append(
                f"门2 FAIL：级联 NMSE 劣化 {deg:.3f}dB > {gate}dB 规格带")
    verdict = "PASS" if gates_ok else "FAIL"
    if overflow:
        notes.append(f"溢出告警 {len(overflow)} 项：定点整数值超出有符号字域，"
                     "已饱和钳位（详见 overflow 列表）——增大 word_bits 或"
                     "降 frac_bits/缩放系数")
    return {
        "ok": True,
        "word_bits": wb,
        "frac_bits": fb,
        "q_format": f"Q{wb - fb - 1}.{fb}",
        "scale": scale,
        "lsb": 1.0 / scale,
        "x_len": int(xv.size),
        "coeffs_int": coeffs_int,
        "overflow": overflow,
        "warnings_count": len(overflow),
        "nmse_db": nmse_db,
        "gain_delta_db": gain_delta_db,
        "gain_float": {"re": float(g_f.real), "im": float(g_f.imag)},
        "gain_quant": {"re": float(g_q.real), "im": float(g_q.imag)},
        "cascade": cascade,
        "nmse_gate_db": gate,
        "verdict": verdict,
        "notes": notes,
    }


def dpd_table_csv(table: dict[str, Any]) -> str:
    """DPD 定点表 CSV 文本（逐系数长表，列序=DPD_COLUMNS）。"""
    cols = list(DPD_COLUMNS)
    lines = [",".join(cols)]
    scale = float(table["scale"])
    ov_set = {(o["k"], o["m"], o["part"]) for o in table.get("overflow", [])}
    for ki, row in enumerate(table["coeffs_int"]):
        for mi, pair in enumerate(row):
            ov_flags = sorted(
                part for part in ("re", "im") if (ki, mi, part) in ov_set)
            lines.append(",".join([
                str(ki), str(mi), str(pair["re"]), str(pair["im"]),
                repr(pair["re"] / scale), repr(pair["im"] / scale),
                "1" if ov_flags else "0",
            ]))
    return "\n".join(lines) + "\n"
