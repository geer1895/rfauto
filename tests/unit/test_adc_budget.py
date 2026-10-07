"""F-E.1 ADC 噪声预算内核单测（研究扩充 round3 F-E 表件 1）。

判据（#122 先行，任务书预声明）：①合成回收逐位；②RSS 恒等式；③ENOB
恒等式 ENOB(6.02·12+1.76)=12.000 rel 1e-9；④数值边界（σ_j→0 → +inf 钉死、
非法入参 ValueError）。

裁判口径（#118 双路径独立推导，不自证）：
- 抖动 SNR：路径 A = 直代 −20·log10(2π·f_in·σ_j)（内核式）；路径 B = 从
  采样物理出发——抖动 τ 经 dv/dt = A·2πf·cos(2πft) 折成误差 RMS
  （= A·2πf·σ_j/√2），对信号 RMS（= A/√2）求功率比再转 dB。两路径代数
  同源、数值路线独立（实错常数在测试内独立键入）。
- 量化 SNR：路径 A = MT-001 圆整常数 6.02N+1.76（内核口径）；路径 B =
  精确推导 10·log10(1.5·2^2N)（量化噪声 ∆²/12 对满量程正弦功率
  (2^N·∆)²/8 之比）。圆整残差 ≤0.0106 dB@N≤16（诚实边界 abs 容差钉）。
- RSS：路径 A = rss_snr_db；路径 B = 手工线性功率和（10^(−SNR/10) 逐项
  相加）反推；另加第三径 p_jitter=(2πfσ)²、p_quant=1/(1.5·2^2N) 直接从
  物理线性域相加（与圆整常数路径差 ~7.4e-4 dB = 量化常数圆整残差）。
- kT/C：路径 B = 线性功率比 v_fs_rms²/(k_B·T/C) 再转 dB（k_B 独立键入）。

口径登记（如实，任务书判据文字 vs 物理方向）：任务书判据"任取两源 RSS
结果 ≥ 单源 max"按**噪声域**解读成立——RSS 本义是噪声幅度合成
sqrt(Σv_i²) ≥ max(v_i)，等价于总噪声功率 ≥ 任一单源噪声功率，故 SNR 域
方向相反：SNR_total ≤ min(SNR_i)（合并只会更差不会更好）。本文件按物理
正确方向钉：SNR 域单调性用 ≤min 断言 + 噪声功率域 ≥ 断言双写。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import adc_budget
from rfauto.service import adc_budget_service

# ─── 双路径离线推导常量（独立键入，#118）─────────────────────────────────────
K_B_TEST = 1.380649e-23  # J/K，SI 精确定义值（CODATA 2018，独立于内核键入）

F_100M = 100.0e6  # Hz
SIGMA_1PS = 1.0e-12  # s
# −20·log10(2π·1e8·1e-12)，MT-007 教科书算例量级（100 MHz/1 ps → ~64 dB）
SNR_JITTER_100M_1PS = 64.0364026328377
# MT-001 圆整常数闭合（6.02·N+1.76）
SNR_QUANT_8 = 49.92
SNR_QUANT_12 = 74.0
SNR_QUANT_16 = 98.08
# kT/C：300 K/1 pF/满量程正弦 v_fs_rms=1/√2 → 10·log10(0.5/(k_B·300/1e-12))
SNR_KTC_300K_1PF = 80.81765466938123

# RSS(74.0, 64.0364026328377)：p1=10^-7.4=3.981071705534969e-08、
# p2=3.9478417604357333e-07，功率和反推
SNR_RSS_JQ = 63.619153813564715


# ─── 1. 孔径抖动 SNR（MT-007）────────────────────────────────────────────────


def test_snr_jitter_analytic_recycle():
    out = adc_budget.snr_jitter_db(F_100M, SIGMA_1PS)
    assert out == pytest.approx(SNR_JITTER_100M_1PS, rel=1e-12)
    # 60 MHz/0.5 ps 手算第二钉：2π·6e7·5e-13 = 6πe-5
    out2 = adc_budget.snr_jitter_db(60.0e6, 0.5e-12)
    assert out2 == pytest.approx(-20.0 * math.log10(2.0 * math.pi * 60.0e6 * 0.5e-12), rel=1e-15)


def test_snr_jitter_dual_path_physical_derivation():
    """路径 B：dv/dt 误差 RMS 对信号 RMS 的功率比（与直代式数值路线独立）。"""
    a_peak = 2.5  # 幅值任意（比值中消去），取非 1 证幅值无关
    for f_hz, sj in ((F_100M, SIGMA_1PS), (10.0e6, 5.0e-12), (1.0e9, 0.1e-12)):
        sig_rms = a_peak / math.sqrt(2.0)
        err_rms = a_peak * 2.0 * math.pi * f_hz * sj / math.sqrt(2.0)
        path_b = 10.0 * math.log10(sig_rms**2 / err_rms**2)
        assert adc_budget.snr_jitter_db(f_hz, sj) == pytest.approx(path_b, rel=1e-12)


def test_snr_jitter_scaling_identity():
    # f×10 → −20 dB 逐位级；σ×10 → −20 dB（对数斜率物理恒等式）
    base = adc_budget.snr_jitter_db(F_100M, SIGMA_1PS)
    assert adc_budget.snr_jitter_db(10.0 * F_100M, SIGMA_1PS) == pytest.approx(
        base - 20.0, rel=1e-12
    )
    assert adc_budget.snr_jitter_db(F_100M, 10.0 * SIGMA_1PS) == pytest.approx(
        base - 20.0, rel=1e-12
    )


def test_snr_jitter_zero_jitter_returns_inf_pinned():
    # 边界钉死（docstring 承诺）：σ_j=0 → float('inf')，不返回 None
    out = adc_budget.snr_jitter_db(F_100M, 0.0)
    assert out == math.inf
    assert isinstance(out, float)


def test_snr_jitter_input_guards():
    for args in (
        (0.0, SIGMA_1PS),  # f_in ≤ 0 → ValueError
        (-1.0e6, SIGMA_1PS),
        (F_100M, -1.0e-12),  # σ_j < 0 → ValueError
        (float("nan"), SIGMA_1PS),
        (F_100M, float("nan")),
        (float("inf"), SIGMA_1PS),
        (True, SIGMA_1PS),  # bool 显式拒收（df7+⑯）
        (F_100M, True),
    ):
        with pytest.raises(ValueError):
            adc_budget.snr_jitter_db(*args)


# ─── 2. 量化 SNR（MT-001）────────────────────────────────────────────────────


def test_snr_quant_analytic_recycle():
    assert adc_budget.snr_quant_db(8) == pytest.approx(SNR_QUANT_8, rel=1e-12)
    assert adc_budget.snr_quant_db(12) == pytest.approx(SNR_QUANT_12, rel=1e-12)
    assert adc_budget.snr_quant_db(16) == pytest.approx(SNR_QUANT_16, rel=1e-12)


def test_snr_quant_exact_derivation_path_b():
    """路径 B：精确式 10·log10(1.5·2^2N)；圆整常数残差 ≤0.0106 dB@N≤16。"""
    exact = 10.0 * math.log10(1.5) + 12.0 * 20.0 * math.log10(2.0)
    assert abs(adc_budget.snr_quant_db(12) - exact) == pytest.approx(0.0081115499, abs=1e-6)
    for n in range(1, 17):
        exact_n = 10.0 * math.log10(1.5) + n * 20.0 * math.log10(2.0)
        assert abs(adc_budget.snr_quant_db(float(n)) - exact_n) < 0.0106


def test_snr_quant_drive_fraction_k():
    # k=0.5 → 10·log10(0.5) = −3.0103 dB；k=1 与缺省逐位相同（无修正项）
    base = adc_budget.snr_quant_db(12)
    assert adc_budget.snr_quant_db(12, 0.5) == pytest.approx(
        base + 10.0 * math.log10(0.5), rel=1e-12
    )
    assert adc_budget.snr_quant_db(12, 1.0) == base
    # 单调性：k↑ → SNR↑（欠驱动降 SNR）
    assert adc_budget.snr_quant_db(12, 0.25) < adc_budget.snr_quant_db(12, 0.5) < base


def test_snr_quant_input_guards():
    for args in (
        (0.5,),  # N < 1
        (0.0,),
        (float("nan"),),
        (True,),  # bool 拒收
        (12, 0.0),  # k ≤ 0
        (12, -0.5),
        (12, float("nan")),
        (12, True),
    ):
        with pytest.raises(ValueError):
            adc_budget.snr_quant_db(*args)


# ─── 3. kT/C 热噪声（可选源）─────────────────────────────────────────────────


def test_snr_ktc_analytic_recycle_and_dual_path():
    v_fs_rms = 1.0 / math.sqrt(2.0)
    out = adc_budget.snr_ktc_db(300.0, 1.0e-12, v_fs_rms)
    assert out == pytest.approx(SNR_KTC_300K_1PF, rel=1e-9)
    # 路径 B：线性功率比 v²/(k_B·T/C) 再转 dB（k_B 独立键入）
    noise_v2 = K_B_TEST * 300.0 / 1.0e-12
    path_b = 10.0 * math.log10(0.5 / noise_v2)
    assert out == pytest.approx(path_b, rel=1e-12)


def test_snr_ktc_scaling_identity():
    v = 1.0 / math.sqrt(2.0)
    base = adc_budget.snr_ktc_db(300.0, 1.0e-12, v)
    # C×100 → 噪声功率 ÷100 → SNR +20 dB
    assert adc_budget.snr_ktc_db(300.0, 1.0e-10, v) == pytest.approx(base + 20.0, rel=1e-12)
    # v_fs_rms×2 → 功率×4 → +10·log10(4)
    assert adc_budget.snr_ktc_db(300.0, 1.0e-12, 2.0 * v) == pytest.approx(
        base + 10.0 * math.log10(4.0), rel=1e-12
    )
    # T×4 → 噪声×4 → −10·log10(4)
    assert adc_budget.snr_ktc_db(1200.0, 1.0e-12, v) == pytest.approx(
        base - 10.0 * math.log10(4.0), rel=1e-12
    )


def test_snr_ktc_input_guards():
    v = 1.0 / math.sqrt(2.0)
    for args in (
        (0.0, 1.0e-12, v),
        (-5.0, 1.0e-12, v),
        (300.0, 0.0, v),
        (300.0, 1.0e-12, 0.0),  # v_fs_rms ≤ 0
        (float("nan"), 1.0e-12, v),
        (True, 1.0e-12, v),
        (300.0, True, v),
        (300.0, 1.0e-12, False),
    ):
        with pytest.raises(ValueError):
            adc_budget.snr_ktc_db(*args)


# ─── 4. RSS 合成恒等式 ───────────────────────────────────────────────────────


def test_rss_hand_power_sum_backout():
    """路径 B：手工线性功率和反推（任取两源 + 三源）。"""
    two = adc_budget.rss_snr_db(SNR_QUANT_12, SNR_JITTER_100M_1PS)
    assert two == pytest.approx(SNR_RSS_JQ, rel=1e-12)
    p = 10.0 ** (SNR_QUANT_12 / -10.0) + 10.0 ** (SNR_JITTER_100M_1PS / -10.0)
    assert two == pytest.approx(-10.0 * math.log10(p), rel=1e-15)
    three = adc_budget.rss_snr_db(SNR_QUANT_12, SNR_JITTER_100M_1PS, SNR_KTC_300K_1PF)
    p3 = p + 10.0 ** (SNR_KTC_300K_1PF / -10.0)
    assert three == pytest.approx(-10.0 * math.log10(p3), rel=1e-12)


def test_rss_total_noise_dominates_single_source():
    """RSS 单调性（噪声域方向，见文件头口径登记）：总噪声 ≥ 任一单源
    （SNR 域即 SNR_total ≤ min 且 ≥ min − 10·log10(k源数)）。"""
    pairs = ((74.0, 64.0364026328377), (60.0, 80.0), (50.0, 52.0), (90.0, 30.0))
    for a, b in pairs:
        total = adc_budget.rss_snr_db(a, b)
        lo = min(a, b)
        assert total <= lo  # SNR 域：合并后不优于任一单源
        assert total >= lo - 10.0 * math.log10(2.0) - 1e-9  # 两源上界 3.01 dB
        # 噪声功率域：总噪声 ≥ max(单源噪声)（任务书判据的本义方向）
        p_total = 10.0 ** (total / -10.0)
        assert p_total >= 10.0 ** (max(a, b) / -10.0) - 1e-18


def test_rss_noiseless_source_identity_exact():
    # +inf 源 = 零噪声：不改变合成结果（逐位）
    assert adc_budget.rss_snr_db(74.0, math.inf) == 74.0
    assert adc_budget.rss_snr_db(math.inf, 64.0) == 64.0
    assert adc_budget.rss_snr_db(math.inf, math.inf) == math.inf
    assert adc_budget.rss_snr_db(math.inf) == math.inf


def test_rss_equal_sources_3db_offset():
    # 两等源 → −10·log10(2) = −3.0103 dB 偏移（功率加倍恒等式）
    total = adc_budget.rss_snr_db(74.0, 74.0)
    assert total == pytest.approx(74.0 - 10.0 * math.log10(2.0), rel=1e-12)


def test_rss_input_guards():
    with pytest.raises(ValueError):
        adc_budget.rss_snr_db()  # 空入参
    for args in (
        (float("nan"),),
        (74.0, float("nan")),
        (True,),
        (74.0, True),
    ):
        with pytest.raises(ValueError):
            adc_budget.rss_snr_db(*args)


# ─── 5. ENOB 恒等式（MT-001）─────────────────────────────────────────────────


def test_enob_identity_12bit_exact():
    # 判据 ③：ENOB(SINAD=6.02·12+1.76) ≈ 12.000 逐位级（rel 1e-9）
    sinad_12 = 6.02 * 12 + 1.76
    assert adc_budget.enob_from_snr_db(sinad_12) == pytest.approx(12.0, rel=1e-9)
    assert adc_budget.enob_from_snr_db(6.02 * 8 + 1.76) == pytest.approx(8.0, rel=1e-9)
    assert adc_budget.enob_from_snr_db(6.02 * 16 + 1.76) == pytest.approx(16.0, rel=1e-9)


def test_enob_linear_mapping_all_bits():
    for n in range(1, 17):
        assert adc_budget.enob_from_snr_db(6.02 * n + 1.76) == pytest.approx(
            float(n), rel=1e-9
        )


def test_enob_negative_and_extremes():
    # 负 ENOB 合法（劣于 1 bit 噪底，不硬钳）；±inf 透传
    assert adc_budget.enob_from_snr_db(0.0) == pytest.approx(-1.76 / 6.02, rel=1e-12)
    assert adc_budget.enob_from_snr_db(math.inf) == math.inf
    assert adc_budget.enob_from_snr_db(-math.inf) == -math.inf


def test_enob_input_guards():
    for args in (
        (float("nan"),),
        (True,),
    ):
        with pytest.raises(ValueError):
            adc_budget.enob_from_snr_db(*args)


# ─── 6. 三源预算聚合 ─────────────────────────────────────────────────────────


def test_budget_aggregator_jitter_plus_quant():
    res = adc_budget.adc_noise_budget(
        f_in_hz=F_100M, sigma_jitter_s=SIGMA_1PS, n_bits=12
    )
    assert res.snr_jitter_db == pytest.approx(SNR_JITTER_100M_1PS, rel=1e-12)
    assert res.snr_quant_db == pytest.approx(SNR_QUANT_12, rel=1e-12)
    assert res.snr_ktc_db is None
    assert res.snr_total_db == pytest.approx(SNR_RSS_JQ, rel=1e-12)
    # ENOB_total = ENOB(SNR_total)；ENOB_quant = ENOB(量化 SNR) = 12
    assert res.enob_total_bits == pytest.approx((SNR_RSS_JQ - 1.76) / 6.02, rel=1e-9)
    assert res.enob_quant_bits == pytest.approx(12.0, rel=1e-9)
    assert res.dominant_source == "jitter"  # 抖动噪声功率 ≥ 量化噪声功率
    assert res.drive_fraction_k == 1.0


def test_budget_aggregator_ktc_dominant():
    # 小采样电容 → kT/C 噪声最大 → dominant="ktc"
    res = adc_budget.adc_noise_budget(
        f_in_hz=F_100M,
        sigma_jitter_s=SIGMA_1PS,
        n_bits=12,
        t_kelvin=300.0,
        capacitance_f=1.0e-15,
        v_fs_rms=1.0 / math.sqrt(2.0),
    )
    assert res.snr_ktc_db is not None
    assert res.snr_ktc_db < res.snr_quant_db
    assert res.snr_ktc_db < res.snr_jitter_db
    assert res.dominant_source == "ktc"
    # RSS 恒等式在聚合器内同样成立（≤ min 单调方向）
    assert res.snr_total_db <= min(
        res.snr_jitter_db, res.snr_quant_db, res.snr_ktc_db
    )


def test_budget_aggregator_quant_only_exact():
    res = adc_budget.adc_noise_budget(n_bits=12)
    assert res.snr_total_db == res.snr_quant_db  # 单源 RSS = 自身（逐位）
    assert res.enob_total_bits == pytest.approx(12.0, rel=1e-9)
    assert res.dominant_source == "quant"
    assert res.snr_jitter_db is None and res.snr_ktc_db is None


def test_budget_aggregator_partial_sources_rejected():
    # 抖动源必须成对；kT/C 源必须成组；至少一源
    with pytest.raises(ValueError):
        adc_budget.adc_noise_budget(f_in_hz=F_100M)  # 缺 sigma_jitter_s
    with pytest.raises(ValueError):
        adc_budget.adc_noise_budget(sigma_jitter_s=SIGMA_1PS)  # 缺 f_in_hz
    with pytest.raises(ValueError):
        adc_budget.adc_noise_budget(t_kelvin=300.0, capacitance_f=1.0e-12)  # 缺 v_fs_rms
    with pytest.raises(ValueError):
        adc_budget.adc_noise_budget(capacitance_f=1.0e-12, v_fs_rms=0.7)  # 缺 t_kelvin
    with pytest.raises(ValueError):
        adc_budget.adc_noise_budget()  # 零源
    with pytest.raises(ValueError):
        adc_budget.adc_noise_budget(drive_fraction_k=0.0)  # 传参即校验


def test_budget_aggregator_zero_jitter_degenerate():
    # σ_j=0 合法（0.0 ≠ 缺失，#364④）：jitter 项 +inf 零功率参与，dominant 跳过
    res = adc_budget.adc_noise_budget(f_in_hz=F_100M, sigma_jitter_s=0.0, n_bits=12)
    assert res.snr_jitter_db == math.inf
    assert res.snr_total_db == pytest.approx(SNR_QUANT_12, rel=1e-12)
    assert res.dominant_source == "quant"


def test_budget_result_to_dict_json_roundtrip():
    res = adc_budget.adc_noise_budget(
        f_in_hz=F_100M, sigma_jitter_s=SIGMA_1PS, n_bits=12
    )
    d = res.to_dict()
    # 全部值 JSON 可序列化类型（float/str/bool/None，无 inf 退化档）
    for val in d.values():
        assert val is None or isinstance(val, (int, float, str, bool))
    payload = json.dumps(d)
    d2 = json.loads(payload)
    assert set(d2.keys()) == set(d.keys())
    assert d2["snr_jitter_db"] == pytest.approx(SNR_JITTER_100M_1PS, rel=1e-12)
    assert d2["snr_ktc_db"] is None  # 未参与源为 None（is not None 语义，#364④）
    assert d2["dominant_source"] == "jitter"
    assert d2["enob_total_bits"] == pytest.approx((SNR_RSS_JQ - 1.76) / 6.02, rel=1e-9)


# ─── 7. service 薄壳（ok 信封，不抛异常）─────────────────────────────────────


def test_service_ok_envelope_matches_core():
    payload = {"f_in_hz": F_100M, "sigma_jitter_s": SIGMA_1PS, "n_bits": 12}
    out = adc_budget_service.adc_budget_compute(payload)
    assert out["ok"] is True
    assert "errors" not in out or not out.get("errors")
    core = adc_budget.adc_noise_budget(
        f_in_hz=F_100M, sigma_jitter_s=SIGMA_1PS, n_bits=12
    )
    # service 零物理公式：与内核同参调用逐位一致（#118 不自证——service 只是壳）
    assert out["result"] == core.to_dict()
    assert out["schema_version"] == adc_budget_service.ADC_BUDGET_SERVICE_SCHEMA_VERSION
    assert out["provenance"]["kernel"] == "rfauto.core.adc_budget"


def test_service_ok_with_drive_fraction_and_ktc():
    payload = {
        "n_bits": 12,
        "drive_fraction_k": 0.5,
        "t_kelvin": 300.0,
        "capacitance_f": 1.0e-12,
        "v_fs_rms": 0.7071067811865476,
    }
    out = adc_budget_service.adc_budget_compute(payload)
    assert out["ok"] is True
    res = out["result"]
    assert res["snr_quant_db"] == pytest.approx(74.0 + 10.0 * math.log10(0.5), rel=1e-12)
    assert res["snr_ktc_db"] is not None
    assert res["dominant_source"] == "quant"


def test_service_error_envelope_never_raises():
    # 非法 payload 全走 ok=False 信封，不抛异常
    bad_payloads = (
        "not-a-dict",
        42,
        {},  # 零源
        {"f_in_hz": F_100M},  # 抖动源缺伴字段
        {"sigma_jitter_s": -1.0},  # 负 σ_j
        {"n_bits": 0.5},  # N < 1
        {"n_bits": True},  # bool 拒收
        {"drive_fraction_k": "high"},  # 非数字
        {"f_in_hz": float("nan"), "sigma_jitter_s": SIGMA_1PS},  # NaN 由内核拒
    )
    for bad in bad_payloads:
        out = adc_budget_service.adc_budget_compute(bad)
        assert out["ok"] is False, f"payload {bad!r} 应 ok=False"
        assert isinstance(out.get("errors"), list) and out["errors"]
        assert all(isinstance(e, str) for e in out["errors"])


def test_service_null_field_equals_absent():
    # JSON null = 不计该源（与缺键同语义）
    full = adc_budget_service.adc_budget_compute({"n_bits": 12})
    nulled = adc_budget_service.adc_budget_compute(
        {"n_bits": 12, "f_in_hz": None, "t_kelvin": None, "v_fs_rms": None}
    )
    assert full == nulled


def test_service_output_json_roundtrip():
    payload = {"f_in_hz": F_100M, "sigma_jitter_s": SIGMA_1PS, "n_bits": 12}
    out = adc_budget_service.adc_budget_compute(json.loads(json.dumps(payload)))
    payload_out = json.dumps(out)  # 有限档严格 JSON 可序列化
    out2 = json.loads(payload_out)
    assert out2["ok"] is True
    assert out2["result"]["snr_total_db"] == pytest.approx(SNR_RSS_JQ, rel=1e-12)
