"""引擎基准扩容：ratrace/atten/via/msl_cpw 四锚判读内核（纯函数零真机）。

背景：mline 锚已有 harness
范式（scripts/engine_benchmark_mline.py + core/anchor_verdict.
mline_benchmark_verdict + tests/golden/mline_benchmark_rescan_20260913.json），
其余四锚判据此前仅内联在各 smoke 脚本（scripts/smoke_*_anchor.py），
无纯函数内核、无 per-anchor benchmark JSON。本内核把四锚判据收编为
确定性纯函数，scripts/engine_benchmark_expand.py 以 --ingest 离线读
smoke 归档（只读）、以 --msl-cpw 真机补跑 msl_cpw 唯一缺档锚，
逐锚落 runs/benchmark/<anchor>_engine_benchmark.json。

判据口径（每锚显式统计量名，#195 谷深/带内 max 语义不混；与 smoke
脚本逐门对齐，五坑 #231 精神——改门=显式重标定决策，须附真机证据，
禁止静默放水）：
- ratrace（smoke_ratrace_anchor.py:91-95 七门，点值语义 @2.5GHz）：
  Σ 馈 p1 β→εeff 对 HJ forward_z0(1.1134) ±2%；|S21|/|S41| −3±1dB
  且均分差 ≤0.5dB；|S31|(Δ) ≤−20dB；|S24|(out1↔out2) ≤−15dB；
  |S11| ≤−10dB（S11_HEALTH_DB）；互易 max||Sij|−|Sji|| ≤0.02（线性）。
- atten（smoke_atten_pi_anchor.py:80 / smoke_atten_t_anchor.py:79 三门）：
  β ±2%；|S21| 带内 mean 对 −10dB 目标 ±0.5dB（平坦均值语义 #195）；
  |S11| 带内 max <−12dB（商用 lumped 衰减模块回损规格地板 12~18dB
  口径，原 −20 门经真机校准落地 −12）。
- via（smoke_via_anchor.py:82 四门 + 20260918a 无源上界）：β1 顶馈 ±2%
  （β2 倒置馈提取污染 real_modal_difference 仅诊断不判，#203 定征）；
  |S11| 带内 max <−10dB；
  |S21| 线性 mean ≥0.90 **且** 带内 max ≤1.02 无源上界（20260918a
  增补，与 msl_cpw 20260915b 同构：无源二端口逐频 |S21|≤1
  是能量守恒硬约束，纯下侧门对 >1 的端口提取伪象会非物理放行；在档
  数据离线复算带内 max 0.9503、401 点全部 ≤1.02，判定零翻转）；互易
  |mean S11−mean S22| ≤0.5dB（sparams.csv 无 S22 列不可复算，只能引
  归档日志转录 0.000dB，source=archive_log）。
- msl_cpw（core/synthesis.py:881 synthesize_msl_cpw_model docstring 口径）：
  port1 β→εeff 对 er_eff1（HJ）±2%；port2 β→εeff 对 er_eff2（CPWG
  共形映射 _cpwg_ri）±2%；|S11| 带内 max <−10dB（保守文献地板，
  #195 worst-case 语义）；|S21| 线性 mean ≥0.90 健康 **且** |S21| 带内
  max ≤1.02 无源上界（2026-09-15 增补：无源二端口逐频
  |S21|≤1 是能量守恒硬约束，>1 只能是端口提取伪象——首轮 msl_cpw 真跑
  mean 1.0296 / 带内 max 1.290 曾在纯下侧门下 PASS，非物理放行；上界
  取带内 max（#195 worst-case 语义，与 |S11| 门同形）而非 mean，mean 会
  被带内健康点稀释；2% 裕量只覆盖单位附近数值噪声，已实证的伪波分解
  伪象量级 ~3%（−30dB 地板）刻意不予吸收——宁保守 FAIL 再审计，
  #122）。对 fake 理想级联（同阻异模对接，|S21| 地板=1）的偏差只作
  信息量不设门。

诚实性（#122 不凑绿）：任何输入 None/NaN（无数据、收敛不可算）→
对应门如实 FAIL 并写明「不可判」，绝不按门内放行。LLM/agent 永不
产生物理数字：锚值与参考值全部来自确定性链路
（openEMS CalcPort β / core/synthesis HJ 与 CPWG 闭式）。

消费方：
- scripts/engine_benchmark_expand.py（--ingest 离线归档入账 / --msl-cpw
  真机补跑，逐锚落 runs/benchmark/<anchor>_engine_benchmark.json）
- tests/unit/test_anchor_benchmark.py（合成数组钉每门 PASS/FAIL 边界
  与 None 诚实性）
- tests/unit/test_engine_benchmark_expand_golden.py（2026-09-15 证据
  快照离线回放）
"""

from __future__ import annotations

import math

from rfauto.core.anchor_verdict import S11_HEALTH_DB

# 判据版本（判据/门常量集的时点戳；改任一门=显式重标定，须递增并附真机证据）
# 20260915b：msl_cpw 传输门增补无源上界 CPW_S21_MAX_LIN（证据=
# 归档 sparams.csv 离线复算 带内 max 1.290 与 零仿真重归一查证）
# 20260918a：via 传输门同构增补无源上界 VIA_S21_MAX_LIN（证据=
# 归档 sparams.csv 离线复算 带内 max 0.9503
# @2.25GHz、401 点全部 ≤1.02——收紧为预防性，判定零翻转）
GATE_VERSION = "20260918a"

# 公共：β 金标准 εeff 对闭式（HJ/CPWG）容差
EPS_EFF_TOL_PCT = 2.0

# ratrace 七门（点值语义 @2.5GHz，沿 smoke_ratrace_anchor.py:91-95）
RATRACE_SPLIT_TARGET_DB = -3.0   # 均分目标 |S21|/|S41|
RATRACE_SPLIT_TOL_DB = 1.0       # 对 -3dB ±1dB
RATRACE_BALANCE_MAX_DB = 0.5     # 均分差 ≤0.5dB
RATRACE_ISO_DELTA_MAX_DB = -20.0  # |S31|(Δ) ≤ -20dB
RATRACE_ISO_OUT_MAX_DB = -15.0   # |S24|(out1↔out2) ≤ -15dB
RATRACE_RECIP_MAX_LIN = 0.02     # 互易 max||Sij|-|Sji|| ≤0.02（线性）
# ratrace |S11| 门 = S11_HEALTH_DB（-10dB，单一事实源 core/anchor_verdict）

# atten 三门（atten_pi/atten_t 共用；沿 smoke_atten_*_anchor.py:80/:79）
ATTEN_TARGET_DB = -10.0          # 衰减目标（ABCD 电阻网络确定性裁判同源）
ATTEN_FLAT_TOL_DB = 0.5          # |S21| 带内 mean 对目标 ±0.5dB（#195 平坦均值）
ATTEN_S11_FLOOR_DB = -12.0       # 商用 lumped 地板（真机校准记录）

# via 四门（沿 smoke_via_anchor.py:82 + 20260918a 无源上界折入 thru）
VIA_S21_MIN_LIN = 0.90           # |S21| 线性 mean ≥0.90（过渡损耗宽于均匀线）
VIA_RECIP_MAX_DB = 0.5           # 互易 |mean S11-mean S22| ≤0.5dB
# 无源上界（上侧，带内 max 语义，20260918a 增补）：与 msl_cpw
# CPW_S21_MAX_LIN 同构——无源二端口逐频 |S21|≤1 是能量守恒硬约束，纯下侧
# mean 门对 >1 的端口提取伪象（伪波分解/时域截断/参考阻抗口径）会非物理
# 放行；理想无源地板 1.0 + 0.02 裕量仅覆盖单位附近数值噪声，已实证伪象
# ~3%（−30dB 地板）刻意不吸收，超门=先审计提取口径再谈校准。
# 独立常量不引用 CPW_*：门重标定按锚显式、互不牵连（#231）。
VIA_S21_MAX_LIN = 1.0 + 0.02
# via |S11| 门 = S11_HEALTH_DB（-10dB 绝对门）

# msl_cpw 五门（core/synthesis.py:881 docstring 口径 + 20260915b 无源上界）
CPW_S21_MIN_LIN = 0.90           # |S21| 线性 mean ≥0.90 健康（下侧）
CPW_IDEAL_S21_LIN = 1.0          # 理想级联地板（同阻异模对接，仅信息量）
# 无源上界（上侧，带内 max 语义）：无源二端口逐频 |S21|≤1 是能量守恒硬约束，
# 超出只能是端口提取伪象（伪波分解 / 时域截断 / 参考阻抗口径），不是器件
# 性能。裕量 0.02 仅覆盖单位附近数值噪声；已实证伪象 ~3%（−30dB 地板）刻意
# 不吸收，超门=先审计提取口径再谈校准。
CPW_S21_MAX_LIN = CPW_IDEAL_S21_LIN + 0.02
# msl_cpw |S11| 门 = S11_HEALTH_DB（-10dB 保守文献地板，#195 worst-case）


def _bad(v: float | None) -> bool:
    """None/NaN 一律不可判（诚实 FAIL，不凑绿）。"""
    return v is None or (isinstance(v, float) and math.isnan(v))


def _reason_join(reasons: list[str]) -> str:
    return "; ".join(reasons)


def ratrace_benchmark_verdict(
    delta_eps_pct: float | None,
    s21_db: float | None,
    s41_db: float | None,
    s31_db: float | None,
    s24_db: float | None,
    s11_db: float | None,
    recip_lin: float | None,
) -> dict[str, object]:
    """rat-race 七门判读（点值语义 @2.5GHz，纯函数零真机）。

    输入 None/NaN → 对应门如实 FAIL（reason 写明不可判），不凑绿。
    """
    reasons: list[str] = []

    if _bad(delta_eps_pct):
        beta_ok = False
        reasons.append("β 金标准不可判（εeff 缺失），如实 FAIL")
    else:
        beta_ok = bool(abs(float(delta_eps_pct)) <= EPS_EFF_TOL_PCT)
        if not beta_ok:
            reasons.append(
                f"β 金标准超门：εeff 对 HJ {delta_eps_pct:+.2f}% 超 "
                f"±{EPS_EFF_TOL_PCT}%")

    if _bad(s21_db) or _bad(s41_db):
        split_ok = False
        balance_ok = False
        balance = None
        reasons.append("均分门不可判（|S21|/|S41| 缺失），如实 FAIL")
    else:
        s21v, s41v = float(s21_db), float(s41_db)  # type: ignore[arg-type]
        balance = abs(s21v - s41v)
        split_ok = bool(
            abs(s21v - RATRACE_SPLIT_TARGET_DB) <= RATRACE_SPLIT_TOL_DB
            and abs(s41v - RATRACE_SPLIT_TARGET_DB) <= RATRACE_SPLIT_TOL_DB)
        balance_ok = bool(balance <= RATRACE_BALANCE_MAX_DB)
        if not split_ok:
            reasons.append(
                f"均分超门：|S21|={s21v:.2f}dB/|S41|={s41v:.2f}dB 偏离 "
                f"{RATRACE_SPLIT_TARGET_DB}±{RATRACE_SPLIT_TOL_DB}dB")
        if not balance_ok:
            reasons.append(
                f"均分差超门：{balance:.2f}dB 超 {RATRACE_BALANCE_MAX_DB}dB")

    if _bad(s31_db):
        iso_delta_ok = False
        reasons.append("Δ 隔离门不可判（|S31| 缺失），如实 FAIL")
    else:
        iso_delta_ok = bool(float(s31_db) <= RATRACE_ISO_DELTA_MAX_DB)
        if not iso_delta_ok:
            reasons.append(
                f"Δ 隔离超限：|S31|={s31_db:.2f}dB 未深于 "
                f"{RATRACE_ISO_DELTA_MAX_DB}dB")

    if _bad(s24_db):
        iso_out_ok = False
        reasons.append("out1↔out2 隔离门不可判（|S24| 缺失），如实 FAIL")
    else:
        iso_out_ok = bool(float(s24_db) <= RATRACE_ISO_OUT_MAX_DB)
        if not iso_out_ok:
            reasons.append(
                f"out 隔离超限：|S24|={s24_db:.2f}dB 未深于 "
                f"{RATRACE_ISO_OUT_MAX_DB}dB")

    if _bad(s11_db):
        match_ok = False
        reasons.append("匹配门不可判（|S11| 缺失），如实 FAIL")
    else:
        match_ok = bool(float(s11_db) <= S11_HEALTH_DB)
        if not match_ok:
            reasons.append(
                f"匹配超限：|S11|@2.5GHz={s11_db:.2f}dB 未深于 "
                f"{S11_HEALTH_DB}dB")

    if _bad(recip_lin):
        recip_ok = False
        reasons.append("互易门不可判（缺 4 端口全矩阵），如实 FAIL")
    else:
        recip_ok = bool(float(recip_lin) <= RATRACE_RECIP_MAX_LIN)
        if not recip_ok:
            reasons.append(
                f"互易超门：max||Sij|-|Sji||={recip_lin:.4f} 超 "
                f"{RATRACE_RECIP_MAX_LIN}（线性）")

    gates = (beta_ok, split_ok, balance_ok, iso_delta_ok, iso_out_ok,
             match_ok, recip_ok)
    verdict = "PASS" if all(gates) else "FAIL"
    return {
        "verdict": verdict,
        "beta_ok": beta_ok,
        "split_ok": split_ok,
        "balance_ok": balance_ok,
        "iso_delta_ok": iso_delta_ok,
        "iso_out_ok": iso_out_ok,
        "match_ok": match_ok,
        "recip_ok": recip_ok,
        "balance_db": balance,
        "reason": _reason_join(reasons),
    }


def atten_benchmark_verdict(
    delta_eps_pct: float | None,
    s21_db_band_mean: float | None,
    s11_db_band_max: float | None,
    atten_target_db: float = ATTEN_TARGET_DB,
) -> dict[str, object]:
    """atten（π/T 共用）三门判读（纯函数零真机）。

    平坦均值语义（#195）：|S21| 用带内 mean 对目标 ±0.5dB；|S11| 用
    带内 max <−12dB 商用 lumped 地板。None/NaN → 对应门如实 FAIL。
    """
    reasons: list[str] = []

    if _bad(delta_eps_pct):
        beta_ok = False
        reasons.append("β 金标准不可判（εeff 缺失），如实 FAIL")
    else:
        beta_ok = bool(abs(float(delta_eps_pct)) <= EPS_EFF_TOL_PCT)
        if not beta_ok:
            reasons.append(
                f"β 金标准超门：εeff 对 HJ {delta_eps_pct:+.2f}% 超 "
                f"±{EPS_EFF_TOL_PCT}%")

    if _bad(s21_db_band_mean):
        atten_ok = False
        atten_dev_db = None
        reasons.append("衰减门不可判（|S21| 带内 mean 缺失），如实 FAIL")
    else:
        atten_dev_db = abs(float(s21_db_band_mean) - atten_target_db)
        atten_ok = bool(atten_dev_db <= ATTEN_FLAT_TOL_DB)
        if not atten_ok:
            reasons.append(
                f"衰减超门：|S21| 带内 mean={s21_db_band_mean:.2f}dB 对目标 "
                f"{atten_target_db}dB 偏差 {atten_dev_db:.2f}dB 超 "
                f"{ATTEN_FLAT_TOL_DB}dB")

    if _bad(s11_db_band_max):
        match_ok = False
        reasons.append("匹配门不可判（|S11| 带内 max 缺失），如实 FAIL")
    else:
        match_ok = bool(float(s11_db_band_max) < ATTEN_S11_FLOOR_DB)
        if not match_ok:
            reasons.append(
                f"匹配超限：|S11| 带内 max={s11_db_band_max:.2f}dB 未深于 "
                f"{ATTEN_S11_FLOOR_DB}dB（商用 lumped 地板）")

    verdict = "PASS" if (beta_ok and atten_ok and match_ok) else "FAIL"
    return {
        "verdict": verdict,
        "beta_ok": beta_ok,
        "atten_ok": atten_ok,
        "match_ok": match_ok,
        "atten_dev_db": atten_dev_db,
        "reason": _reason_join(reasons),
    }


def via_benchmark_verdict(
    delta_eps1_pct: float | None,
    s11_db_band_max: float | None,
    s21_lin_mean: float | None,
    recip_db: float | None,
    delta_eps2_pct: float | None = None,
    *,
    s21_lin_band_max: float | None = None,
) -> dict[str, object]:
    """via 四门判读（β1 顶馈单判，β2 仅诊断，纯函数零真机）。

    β2（倒置馈 CalcPort 提取污染，real_modal_difference）不设门——
    #203 定征，
    只回传 beta2_modal_difference_pct 供诊断。传输门为双侧（20260918a
    增补，与 msl_cpw 20260915b 同构）：|S21| 线性 mean
    ≥0.90 健康（下侧）**且** |S21| 带内 max ≤ VIA_S21_MAX_LIN=1.02
    无源上界（上侧），上下侧共同折入 thru_ok，另以 passive_ok 单独回传
    上侧结果供诊断。recip_db 来源只可能是归档日志转录
    （sparams.csv 无 S22 列），调用方须标 source=archive_log。

    s21_lin_band_max 为 keyword-only 可选：旧调用（五位置参数）不抛
    TypeError，但缺失时上界如实「不可判 FAIL」（#122 不凑绿，与本文件
    其余 None 语义一致），harness 须补传带内 max 才能重新过门。
    其余 None/NaN → 如实 FAIL。
    """
    reasons: list[str] = []

    if _bad(delta_eps1_pct):
        beta1_ok = False
        reasons.append("β1 金标准不可判（顶馈 εeff 缺失），如实 FAIL")
    else:
        beta1_ok = bool(abs(float(delta_eps1_pct)) <= EPS_EFF_TOL_PCT)
        if not beta1_ok:
            reasons.append(
                f"β1 金标准超门：顶馈 εeff 对 HJ {delta_eps1_pct:+.2f}% 超 "
                f"±{EPS_EFF_TOL_PCT}%")

    if _bad(s11_db_band_max):
        match_ok = False
        reasons.append("匹配门不可判（|S11| 带内 max 缺失），如实 FAIL")
    else:
        match_ok = bool(float(s11_db_band_max) < S11_HEALTH_DB)
        if not match_ok:
            reasons.append(
                f"匹配超限：|S11| 带内 max={s11_db_band_max:.2f}dB 未深于 "
                f"{S11_HEALTH_DB}dB 绝对门")

    if _bad(s21_lin_mean):
        floor_ok = False
        reasons.append("传输门不可判（|S21| 线性 mean 缺失），如实 FAIL")
    else:
        floor_ok = bool(float(s21_lin_mean) >= VIA_S21_MIN_LIN)
        if not floor_ok:
            reasons.append(
                f"传输超门：|S21| 线性 mean={s21_lin_mean:.4f} 未达 "
                f"{VIA_S21_MIN_LIN}")

    # 无源上界（上侧，带内 max 语义，20260918a）：缺失即不可判——旧五参
    # 调用不会静默过门（与 msl_cpw 20260915b 同构）
    if _bad(s21_lin_band_max):
        passive_ok = False
        reasons.append(
            "无源上界不可判（|S21| 带内 max 缺失，harness 须补传 "
            "s21_lin_band_max），如实 FAIL")
    else:
        s21max = float(s21_lin_band_max)  # type: ignore[arg-type]
        passive_ok = bool(s21max <= VIA_S21_MAX_LIN)
        if not passive_ok:
            reasons.append(
                f"无源上界超门：|S21| 带内 max={s21max:.4f} 超 "
                f"{VIA_S21_MAX_LIN:.2f}（无源二端口逐频 |S21|≤1 能量守恒；"
                f"超出=端口提取伪象，先审计口径再校准）")

    thru_ok = bool(floor_ok and passive_ok)

    if _bad(recip_db):
        recip_ok = False
        reasons.append(
            "互易门不可判（sparams.csv 无 S22 列且无归档日志值），如实 FAIL")
    else:
        recip_ok = bool(float(recip_db) <= VIA_RECIP_MAX_DB)
        if not recip_ok:
            reasons.append(
                f"互易超门：|mean S11-mean S22|={recip_db:.3f}dB 超 "
                f"{VIA_RECIP_MAX_DB}dB")

    verdict = "PASS" if (beta1_ok and match_ok and thru_ok and recip_ok) \
        else "FAIL"
    return {
        "verdict": verdict,
        "beta1_ok": beta1_ok,
        "match_ok": match_ok,
        "thru_ok": thru_ok,
        "passive_ok": passive_ok,  # 诊断：上侧（无源上界）单独结果
        "recip_ok": recip_ok,
        "beta2_modal_difference_pct": (
            None if _bad(delta_eps2_pct) else float(delta_eps2_pct)),  # type: ignore[arg-type]
        "reason": _reason_join(reasons),
    }


def msl_cpw_benchmark_verdict(
    delta_eps1_pct: float | None,
    delta_eps2_pct: float | None,
    s11_db_band_max: float | None,
    s21_lin_mean: float | None,
    *,
    s21_lin_band_max: float | None = None,
) -> dict[str, object]:
    """msl_cpw（MSL↔CPWG 过渡）五门判读（core/synthesis.py:881 口径 +
    20260915b 无源上界）。

    主锚：port1 β→εeff 对 er_eff1（HJ）±2%；副锚：port2 β→εeff 对
    er_eff2（CPWG 共形映射）±2%；健康：|S11| 带内 max <−10dB 文献
    地板（#195 worst-case）、|S21| 线性 mean ≥0.90（下侧）且 |S21|
    带内 max ≤ CPW_S21_MAX_LIN=1.02（无源上界，上侧）。上下侧共同折入
    thru_ok（harness gate_flags 四键自洽：thru_ok False ⟹ FAIL），另以
    passive_ok 单独回传上侧结果供诊断。理想级联（同阻异模对接）偏差只作
    信息量不设门。

    无源上界依据：无源二端口逐频 |S21|≤1 是能量守恒硬约束；带内 max >1
    只能是端口提取伪象（伪波分解 (U+Z_ref·I)/2 对非 50Ω 模式的混叠、
    NrTS 定步截断、参考阻抗口径）而非器件性能，须先审计提取口径再谈
    校准。首轮真跑 mean 1.0296 / max 1.290 曾在纯下侧门下
    PASS——本门即为堵住该非物理放行而立。

    s21_lin_band_max 为 keyword-only 可选：旧调用（四位置参数）不抛
    TypeError，但缺失时上界如实「不可判 FAIL」（#122 不凑绿，与本文件
    其余 None 语义一致），harness 须补传带内 max 才能重新过门。
    None/NaN → 对应门如实 FAIL。
    """
    reasons: list[str] = []

    if _bad(delta_eps1_pct):
        beta1_ok = False
        reasons.append("主锚不可判（port1 εeff 缺失），如实 FAIL")
    else:
        beta1_ok = bool(abs(float(delta_eps1_pct)) <= EPS_EFF_TOL_PCT)
        if not beta1_ok:
            reasons.append(
                f"主锚超门：port1 εeff 对 er_eff1（HJ）{delta_eps1_pct:+.2f}%"
                f" 超 ±{EPS_EFF_TOL_PCT}%")

    if _bad(delta_eps2_pct):
        beta2_ok = False
        reasons.append("副锚不可判（port2 εeff 缺失），如实 FAIL")
    else:
        beta2_ok = bool(abs(float(delta_eps2_pct)) <= EPS_EFF_TOL_PCT)
        if not beta2_ok:
            reasons.append(
                f"副锚超门：port2 εeff 对 er_eff2（CPWG）{delta_eps2_pct:+.2f}%"
                f" 超 ±{EPS_EFF_TOL_PCT}%")

    if _bad(s11_db_band_max):
        match_ok = False
        reasons.append("匹配门不可判（|S11| 带内 max 缺失），如实 FAIL")
    else:
        match_ok = bool(float(s11_db_band_max) < S11_HEALTH_DB)
        if not match_ok:
            reasons.append(
                f"匹配超限：|S11| 带内 max={s11_db_band_max:.2f}dB 未深于 "
                f"{S11_HEALTH_DB}dB 文献地板")

    if _bad(s21_lin_mean):
        floor_ok = False
        s21_ideal_dev = None
        reasons.append("传输门不可判（|S21| 线性 mean 缺失），如实 FAIL")
    else:
        s21v = float(s21_lin_mean)  # type: ignore[arg-type]
        floor_ok = bool(s21v >= CPW_S21_MIN_LIN)
        s21_ideal_dev = abs(s21v - CPW_IDEAL_S21_LIN)
        if not floor_ok:
            reasons.append(
                f"传输超门：|S21| 线性 mean={s21v:.4f} 未达 "
                f"{CPW_S21_MIN_LIN}")

    # 无源上界（上侧，带内 max 语义）：缺失即不可判——旧四参调用不会静默过门
    if _bad(s21_lin_band_max):
        passive_ok = False
        reasons.append(
            "无源上界不可判（|S21| 带内 max 缺失，harness 须补传 "
            "s21_lin_band_max），如实 FAIL")
    else:
        s21max = float(s21_lin_band_max)  # type: ignore[arg-type]
        passive_ok = bool(s21max <= CPW_S21_MAX_LIN)
        if not passive_ok:
            reasons.append(
                f"无源上界超门：|S21| 带内 max={s21max:.4f} 超 "
                f"{CPW_S21_MAX_LIN:.2f}（无源二端口逐频 |S21|≤1 能量守恒；"
                f"超出=端口提取伪象，先审计口径再校准）")

    thru_ok = bool(floor_ok and passive_ok)

    verdict = "PASS" if (beta1_ok and beta2_ok and match_ok and thru_ok) \
        else "FAIL"
    return {
        "verdict": verdict,
        "beta1_ok": beta1_ok,
        "beta2_ok": beta2_ok,
        "match_ok": match_ok,
        "thru_ok": thru_ok,
        "passive_ok": passive_ok,  # 诊断：上侧（无源上界）单独结果
        "s21_vs_ideal_lin_dev": s21_ideal_dev,  # 信息量：理想级联地板偏差
        "reason": _reason_join(reasons),
    }
