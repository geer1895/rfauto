"""F-E 件 3 Y 因子噪声测量内核单测（研究扩充 round3 F-E 表件 3 判据）。

裁判口径（#118：裁判=独立来源，不自证）：
- 路径 A = (T_hot − Y·T_cold)/(Y − 1)（模块 te_from_y）；
- 路径 B = ENR/(Y − 1)（AN 57-2 原文式，T_cold=T0；测试本地独立转录
  _nf_path_b，与模块实现零共享）；
- GUM 闭式偏导用数值差分（中心差分）独立裁判（_fd）；
- MC 固定 seed 统计裁判（预声明阈值 rel <= 0.10）；
- 手算钉值（ENR 15 dB → T_hot = 9460.6052144883 K @ Tc=290）为外部
  计算路径，不经模块公式。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import nf_measurement as nfm

T0 = nfm.T0_K
ENR15_LIN = 10.0**1.5  # 31.622776601683793
T_HOT_15 = 9460.6052144883  # 手算钉：290×(1+10^1.5)（ENR=15 dB @ Tc=290 K）
NF_F2_DB = 10.0 * math.log10(2.0)  # 3.0102999566398 dB（F=2）
Y_F2_ENR15 = 1.0 + ENR15_LIN / 2.0  # 16.811388300841897（F=2、ENR 15 dB、Tc=T0）


def _nf_path_b(enr_lin: float, y: float) -> float:
    """测试本地独立实现（AN 57-2 F=ENR/(Y−1) → dB）：与模块实现零共享。"""
    return 10.0 * math.log10(enr_lin / (y - 1.0))


def _nf_path_a(t_hot_k: float, t_cold_k: float, y: float, t0: float) -> float:
    """测试本地独立实现（一般温度式 NF=10log10(1+Te/T0)）。"""
    te = (t_hot_k - y * t_cold_k) / (y - 1.0)
    return 10.0 * math.log10(1.0 + te / t0)


def _fd(fn, xs: list[float], i: int, h: float = 1e-6) -> float:
    """中心差分偏导（GUM 闭式偏导的独立数值裁判）。"""
    xs_p = list(xs)
    xs_m = list(xs)
    xs_p[i] += h
    xs_m[i] -= h
    return (fn(*xs_p) - fn(*xs_m)) / (2.0 * h)


# ─── 1. 定义式：ENR / Y ──────────────────────────────────────────────────────


def test_enr_definition_pins():
    # ENR=15 dB @ Tc=290：手算钉 T_hot=9460.6052144883（外部计算路径）
    assert nfm.enr_linear(T_HOT_15, 290.0) == pytest.approx(ENR15_LIN, rel=1e-12)
    assert nfm.enr_db(T_HOT_15, 290.0) == pytest.approx(15.0, rel=1e-12)
    # T_cold=295（源物理温度显式）：分母仍是 T0=290（定义口径）
    th295 = 295.0 + 290.0 * 10.0**0.6
    assert nfm.enr_linear(th295, 295.0) == pytest.approx(10.0**0.6, rel=1e-15)
    assert nfm.enr_linear(th295, 295.0, t0_k=145.0) == pytest.approx(
        290.0 * 10.0**0.6 / 145.0, rel=1e-15
    )
    with pytest.raises(ValueError):  # T_hot <= T_cold 越定义域
        nfm.enr_linear(290.0, 290.0)
    with pytest.raises(ValueError):
        nfm.enr_linear(280.0, 290.0)


def test_y_factor_definition_and_guards():
    assert nfm.y_factor(2.0, 1.0) == 2.0
    assert nfm.y_factor(1.0, 2.0) == 0.5  # 定义式层不做物理域校验
    for args in ((True, 1.0), (2.0, True), (0.0, 1.0), (1.0, 0.0), (float("nan"), 1.0)):
        with pytest.raises(ValueError):
            nfm.y_factor(*args)


# ─── 2. 合成回收：T_e → Y → T_e 逐位（判据 1）───────────────────────────────


def test_te_from_y_path_a_recycle():
    # AN 57-2 典型工况：ENR 15 dB（T_hot=T0·(1+ENR)，T_cold=T0），DUT F=2
    te = nfm.te_from_y(Y_F2_ENR15, T_HOT_15, T0)
    assert te == pytest.approx(290.0, rel=1e-12)
    y_rt = nfm.y_from_te(te, T_HOT_15, T0)
    assert y_rt == pytest.approx(Y_F2_ENR15, rel=1e-12)
    assert nfm.te_from_y(y_rt, T_HOT_15, T0) == pytest.approx(te, rel=1e-12)


def test_recycle_grid_paths_a_b():
    # 判据 1+2：NF×ENR 网格合成回收，路径 A 与测试本地路径 B rel 1e-12
    for nf_db in (0.5, 1.0, 3.0, 6.0, 10.0):
        for enr_db in (6.0, 15.0):
            enr_lin = 10.0 ** (enr_db / 10.0)
            th = 290.0 * (1.0 + enr_lin)
            te_true = nfm.te_from_nf(nf_db)
            y = nfm.y_from_te(te_true, th, T0)
            te_a = nfm.te_from_y(y, th, T0)
            f_a = 1.0 + te_a / T0
            f_b = nfm.f_from_enr_y(enr_lin, y)
            assert te_a == pytest.approx(te_true, rel=1e-12), (nf_db, enr_db)
            assert f_a == pytest.approx(f_b, rel=1e-12), (nf_db, enr_db)
            assert nfm.nf_from_te(te_a) == pytest.approx(nf_db, rel=1e-12)
            assert _nf_path_b(enr_lin, y) == pytest.approx(
                _nf_path_a(th, T0, y, T0), rel=1e-12
            )


def test_path_b_module_vs_local_and_nf_decomposition():
    # 路径 B 模块实现（线性域 F）vs 测试本地独立转录（经 10^(dB/10) 回线性域）
    f_mod = nfm.f_from_enr_y(ENR15_LIN, Y_F2_ENR15)
    assert f_mod == pytest.approx(10.0 ** (_nf_path_b(ENR15_LIN, Y_F2_ENR15) / 10.0), rel=1e-12)
    assert f_mod == pytest.approx(2.0, rel=1e-12)
    # dB 域分解恒等式（T_cold=T0）：NF = ENR_dB − 10·log10(Y−1)
    nf_mod = nfm.nf_from_te(nfm.te_from_y(Y_F2_ENR15, T_HOT_15, T0))
    nf_decomp = 15.0 - 10.0 * math.log10(Y_F2_ENR15 - 1.0)
    assert nf_mod == pytest.approx(nf_decomp, rel=1e-12)
    assert nf_mod == pytest.approx(NF_F2_DB, rel=1e-12)


def test_path_b_tc_contract_general_tc_not_equal():
    # T_cold=295 ≠ T0：路径 B 不再精确（契约差异如实呈现，非 bug）
    enr_lin_295 = nfm.enr_linear(T_HOT_15, 295.0)
    y_295 = nfm.y_from_te(290.0, T_HOT_15, 295.0)
    f_a = 1.0 + nfm.te_from_y(y_295, T_HOT_15, 295.0) / T0
    f_b = nfm.f_from_enr_y(enr_lin_295, y_295)
    assert f_a != pytest.approx(f_b, rel=1e-6)  # 契约外确不相等
    # 温度参数化 GUM 与路径 A 一致（一般 T_cold 的正道）
    assert f_a == pytest.approx(2.0, rel=1e-9)


def test_nf_te_roundtrip_identity():
    assert nfm.nf_from_te(0.0) == 0.0  # 逐位恒等（判据：NF=0 dB ⇔ T_e=0）
    for te in (-100.0, 0.0, 50.0, 290.0, 5000.0):
        nf = nfm.nf_from_te(te)
        assert nfm.te_from_nf(nf) == pytest.approx(te, rel=1e-12)
    assert nfm.te_from_nf(NF_F2_DB) == pytest.approx(290.0, rel=1e-12)
    with pytest.raises(ValueError):  # T_e <= −T0 → F<=0 越定义域
        nfm.nf_from_te(-290.0)
    with pytest.raises(ValueError):
        nfm.nf_from_te(-1000.0)


# ─── 3. 边界与守卫（判据 3：发散/Y<1/bool/NaN）──────────────────────────────


def test_y_singularity_and_unreachable():
    # Y=1 发散极限：分子符号定号，±inf 合法（预声明）
    assert nfm.te_from_y(1.0, T_HOT_15, T0) == math.inf
    assert nfm.te_from_y(1.0, 290.0, 9460.6) == -math.inf
    with pytest.raises(ValueError):  # 0/0 不定
        nfm.te_from_y(1.0, 290.0, 290.0)
    # Y<1 物理不可达（预声明 ValueError）
    with pytest.raises(ValueError):
        nfm.te_from_y(0.5, T_HOT_15, T0)
    with pytest.raises(ValueError):
        nfm.te_from_y(1e-9, T_HOT_15, T0)
    # Y→1⁺：发散前的巨大有限值
    huge = nfm.te_from_y(1.0 + 1e-13, T_HOT_15, T0)
    assert math.isfinite(huge) and huge > 1e13
    # 路径 B 同边界
    assert nfm.f_from_enr_y(ENR15_LIN, 1.0) == math.inf
    with pytest.raises(ValueError):
        nfm.f_from_enr_y(ENR15_LIN, 0.9)


def test_negative_te_inconsistency_flag():
    # Y 相对 ENR 过大 → T_e<0 不自洽标志：照实返回不拦（只算不判）
    te = nfm.te_from_y(1.5, 310.0, 290.0)
    assert te == pytest.approx((310.0 - 1.5 * 290.0) / 0.5, rel=1e-15)
    assert te == pytest.approx(-250.0, rel=1e-12)


def test_bool_and_nonfinite_guards():
    with pytest.raises(ValueError):  # bool 显式拒收（df7+⑯）
        nfm.te_from_y(True, T_HOT_15, T0)
    with pytest.raises(ValueError):
        nfm.nf_from_te(True)
    with pytest.raises(ValueError):
        nfm.nf_from_te(float("nan"))
    with pytest.raises(ValueError):
        nfm.te_from_nf(True)
    with pytest.raises(ValueError):
        nfm.y_from_te(True, T_HOT_15, T0)
    with pytest.raises(ValueError):
        nfm.enr_linear(True, 290.0)
    with pytest.raises(ValueError):
        nfm.apply_input_loss(100.0, True)
    with pytest.raises(ValueError):
        nfm.y_uncertainty(2.0, 1.0, 0.1, -0.05)


# ─── 4. 源端损耗修正（Friis 逐级）────────────────────────────────────────────


def test_apply_input_loss_friis_crosscheck():
    # 独立对照路径：F_sys = L·F_DUT（损耗在 T0 的 Friis 代数）
    loss = 10.0**0.05  # 0.5 dB
    te_dut = 100.0
    f_dut = 1.0 + te_dut / T0
    f_sys = loss * f_dut
    expected = T0 * (f_sys - 1.0)
    assert nfm.apply_input_loss(te_dut, loss) == pytest.approx(expected, rel=1e-12)


def test_loss_roundtrip_and_guards():
    loss = 10.0**0.1  # 1 dB
    for te in (0.0, 50.0, 290.0, 3000.0):
        referred = nfm.apply_input_loss(te, loss)
        assert nfm.remove_input_loss(referred, loss) == pytest.approx(te, rel=1e-12)
        assert nfm.apply_input_loss(nfm.remove_input_loss(te, loss), loss) == pytest.approx(
            te, rel=1e-12
        )
    assert nfm.apply_input_loss(100.0, 1.0) == 100.0  # 无损耗逐位恒等
    assert nfm.remove_input_loss(100.0, 1.0) == 100.0
    with pytest.raises(ValueError):  # <1 是增益，不在口径
        nfm.apply_input_loss(100.0, 0.9)
    with pytest.raises(ValueError):
        nfm.remove_input_loss(100.0, 0.9)


def test_end_to_end_pad_measurement():
    # 正向（任务口径）：测得 DUT 本征 T_e（无垫测量）→ 经 L 折算 = 含垫表观值
    te_dut = 290.0  # F=2
    loss = 10.0**0.1  # 1 dB 垫
    th, tc = T_HOT_15, T0
    apparent = nfm.apply_input_loss(te_dut, loss)
    y_dut = nfm.y_from_te(te_dut, th, tc)  # 无垫测量的 Y
    res_fwd = nfm.measure_yfactor(y_dut, 1.0, th, tc, input_loss_lin=loss)
    assert res_fwd.t_e_k == pytest.approx(te_dut, rel=1e-12)
    assert res_fwd.t_e_corrected_k == pytest.approx(apparent, rel=1e-12)
    assert res_fwd.nf_corrected_db == pytest.approx(nfm.nf_from_te(apparent), rel=1e-12)
    # 反向（去嵌）：含垫实测的 Y → 表观值 → remove → DUT 本征值
    y_apparent = nfm.y_from_te(apparent, th, tc)
    res_meas = nfm.measure_yfactor(y_apparent, 1.0, th, tc)
    assert res_meas.t_e_k == pytest.approx(apparent, rel=1e-12)
    assert res_meas.input_loss_lin is None
    assert res_meas.t_e_corrected_k is None
    assert nfm.remove_input_loss(res_meas.t_e_k, loss) == pytest.approx(te_dut, rel=1e-12)


# ─── 5. 不确定度：Y 的 RSS + GUM 闭式（FD 裁判）+ MC 对照 ────────────────────


def test_y_uncertainty_rss():
    # 手算钉：Y=2（Ph=2, Pc=1），σh=σc=0.05 → σ_Y = 2·0.05·√2
    assert nfm.y_uncertainty(2.0, 1.0, 0.1, 0.05) == pytest.approx(
        0.14142135623730951, rel=1e-12
    )
    assert nfm.y_uncertainty(1.0, 1.0, 0.01, 0.0) == pytest.approx(0.01, rel=1e-15)
    assert nfm.y_uncertainty(1.0, 1.0, 0.0, 0.0) == 0.0


def test_gum_enr_fd_sensitivities():
    enr, y = ENR15_LIN, Y_F2_ENR15
    u_e, u_y = 1.4562828, 0.05  # ENR 15 dB ± 0.2 dB 的线性折算量级
    gum = nfm.nf_uncertainty_gum_enr(enr, y, u_e, u_y)
    # dB 域偏导闭式 vs 中心差分（_fd 差分的 _nf_path_b 本就是 dB 域）
    s_e_fd = _fd(lambda e, yy: _nf_path_b(e, yy), [enr, y], 0)
    s_y_fd = _fd(lambda e, yy: _nf_path_b(e, yy), [enr, y], 1)
    assert gum["sensitivity_dnf_denr_db"] == pytest.approx(s_e_fd, rel=1e-6)
    assert gum["sensitivity_dnf_dy_db"] == pytest.approx(s_y_fd, rel=1e-6)
    # F 域偏导 = dB 域偏导 × ln10·F/10（域换算互证）
    f = enr / (y - 1.0)
    assert gum["sensitivity_df_denr"] == pytest.approx(s_e_fd * math.log(10.0) * f / 10.0, rel=1e-6)
    assert gum["sensitivity_df_dy"] == pytest.approx(s_y_fd * math.log(10.0) * f / 10.0, rel=1e-6)
    # u_c vs FD 敏感度直接 RSS（dB 域偏导 × 线性域 u）
    u_nf_fd = math.sqrt((s_e_fd * u_e) ** 2 + (s_y_fd * u_y) ** 2)
    assert gum["u_nf_db"] == pytest.approx(u_nf_fd, rel=1e-6)
    # ∂NF/∂ENR_dB = 1 的恒等式（dB 域分解的推论）
    s_enr_db_fd = _fd(lambda d: _nf_path_b(10.0 ** (d / 10.0), y), [15.0], 0, h=1e-4)
    assert s_enr_db_fd == pytest.approx(1.0, rel=1e-6)
    with pytest.raises(ValueError):  # 负不确定度拒绝
        nfm.nf_uncertainty_gum_enr(enr, y, -0.1, u_y)
    with pytest.raises(ValueError):  # Y=1 奇点
        nfm.nf_uncertainty_gum_enr(enr, 1.0, u_e, u_y)


def test_gum_temp_fd_sensitivities():
    y = Y_F2_ENR15
    uth = T0 * ENR15_LIN * math.log(10.0) / 10.0 * 0.2  # ENR ±0.2 dB 折到 T_hot（固定 Tc）
    utc = 0.5
    gum = nfm.nf_uncertainty_gum(y, T_HOT_15, T0, 0.05, uth, utc)
    # dB 域偏导 vs 中心差分（_nf_path_a 返回 dB，FD 自然是 dB 域偏导）
    s_y_fd = _fd(lambda yy, th, tc: _nf_path_a(th, tc, yy, T0), [y, T_HOT_15, T0], 0)
    s_th_fd = _fd(lambda yy, th, tc: _nf_path_a(th, tc, yy, T0), [y, T_HOT_15, T0], 1)
    s_tc_fd = _fd(lambda yy, th, tc: _nf_path_a(th, tc, yy, T0), [y, T_HOT_15, T0], 2)
    assert gum["sensitivity_dnf_dy_db"] == pytest.approx(s_y_fd, rel=1e-6)
    assert gum["sensitivity_dnf_dt_hot_db"] == pytest.approx(s_th_fd, rel=1e-6)
    assert gum["sensitivity_dnf_dt_cold_db"] == pytest.approx(s_tc_fd, rel=1e-6)
    # F 域偏导 = dB 域偏导 × ln10·F/10（域换算互证）
    f = 2.0
    assert gum["sensitivity_df_dy"] == pytest.approx(s_y_fd * math.log(10.0) * f / 10.0, rel=1e-6)
    # u_c vs FD 敏感度直接 RSS（dB 域）
    u_nf_fd = math.sqrt(
        (s_y_fd * 0.05) ** 2 + (s_th_fd * uth) ** 2 + (s_tc_fd * utc) ** 2
    )
    assert gum["u_nf_db"] == pytest.approx(u_nf_fd, rel=1e-6)


def test_gum_parameterization_consistency():
    # 温度参数化（u_tc=0，u_th=T0·u_enr_lin）与 ENR 参数化逐位一致（Tc=T0 契约）
    u_e = ENR15_LIN * math.log(10.0) / 10.0 * 0.2
    gum_enr = nfm.nf_uncertainty_gum_enr(ENR15_LIN, Y_F2_ENR15, u_e, 0.05)
    gum_temp = nfm.nf_uncertainty_gum(
        Y_F2_ENR15, T_HOT_15, T0, 0.05, T0 * u_e, 0.0
    )
    assert gum_temp["u_f_linear"] == pytest.approx(gum_enr["u_f_linear"], rel=1e-12)
    assert gum_temp["u_nf_db"] == pytest.approx(gum_enr["u_nf_db"], rel=1e-12)
    # 量级 sanity：ENR 15 dB ±0.2 dB、u_Y=0.05 → u_NF ≈ 0.20 dB（AN 57-2 量级）
    assert 0.15 < gum_enr["u_nf_db"] < 0.25


def test_mc_vs_gum_closed_form():
    # 判据 5：MC（固定 seed 10000 样本）对照 GUM 闭式，预声明阈值 rel <= 0.10
    y = Y_F2_ENR15
    uth = T0 * ENR15_LIN * math.log(10.0) / 10.0 * 0.2
    utc = 0.5
    gum = nfm.nf_uncertainty_gum(y, T_HOT_15, T0, 0.05, uth, utc)
    mc = nfm.mc_nf_std(y, T_HOT_15, T0, 0.05, uth, utc, n_samples=10000, seed=20260927)
    assert mc["n_valid"] == 10000.0
    rel_gap = abs(mc["std_nf_db"] - gum["u_nf_db"]) / gum["u_nf_db"]
    assert rel_gap <= 0.10, f"MC {mc['std_nf_db']:.6f} vs GUM {gum['u_nf_db']:.6f}, rel={rel_gap:.4f}"


def test_mc_deterministic_and_invalid_regime():
    uth = T0 * ENR15_LIN * math.log(10.0) / 10.0 * 0.2
    a = nfm.mc_nf_std(Y_F2_ENR15, T_HOT_15, T0, 0.05, uth, 0.5, seed=42)
    b = nfm.mc_nf_std(Y_F2_ENR15, T_HOT_15, T0, 0.05, uth, 0.5, seed=42)
    assert a["std_nf_db"] == b["std_nf_db"]  # 同 seed 逐位复现
    assert a["std_nf_db"] != nfm.mc_nf_std(
        Y_F2_ENR15, T_HOT_15, T0, 0.05, uth, 0.5, seed=43
    )["std_nf_db"]
    with pytest.raises(ValueError):  # u_Y 相对 Y−1 过大 → 有效占比崩 → 如实拒绝
        nfm.mc_nf_std(1.5, T_HOT_15, T0, 5.0, uth, 0.5)
    with pytest.raises(ValueError):
        nfm.mc_nf_std(Y_F2_ENR15, T_HOT_15, T0, 0.05, uth, 0.5, n_samples=1)


# ─── 6. 端到端评估与 dataclass ───────────────────────────────────────────────


def test_measure_yfactor_result_and_to_dict():
    res = nfm.measure_yfactor(Y_F2_ENR15, 1.0, T_HOT_15, T0)
    assert res.y_linear == pytest.approx(Y_F2_ENR15, rel=1e-15)
    assert res.t_e_k == pytest.approx(290.0, rel=1e-12)
    assert res.f_linear == pytest.approx(2.0, rel=1e-12)
    assert res.nf_db == pytest.approx(NF_F2_DB, rel=1e-12)
    assert res.f_enr_path == pytest.approx(2.0, rel=1e-12)  # Tc==T0 → 路径 B 附带
    assert res.input_loss_lin is None and res.t_e_corrected_k is None
    d = res.to_dict()
    assert d["t_e_corrected_k"] is None
    json.dumps(d)  # JSON 可序列化
    # Tc≠T0 → 路径 B 不适用（None，#364④ is not None 口径）
    res295 = nfm.measure_yfactor(Y_F2_ENR15, 1.0, T_HOT_15, 295.0)
    assert res295.f_enr_path is None
    assert res295.t_e_k != pytest.approx(290.0, rel=1e-6)
    # 发散测量端到端拒绝
    with pytest.raises(ValueError):
        nfm.measure_yfactor(1.0, 1.0, T_HOT_15, T0)


def test_docstring_sources_pinned():
    # 口径钉：docstring 必须引 AN 57-2 与 T0=290（铁律 5）
    doc = nfm.__doc__ or ""
    assert "AN 57-2" in doc
    assert "290" in doc
    assert nfm.T0_K == 290.0
