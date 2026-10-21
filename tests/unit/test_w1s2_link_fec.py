"""架构批 W1-S2 席锚树：link_limits 链路极限面三键 + fec_codes FEC 块码族三键。

数值断言口径（#118 不自证）：
- Shannon 族：①η=2 → Eb/N0_min=1.5=1.76091dB（教科书点，独立解析算术
  复算）；②η→0 极限 ln2=−1.59175dB（小 SNR 数值逼近 + 常数字段双路）；
  ③dB/线性双口径同参一致；④C=B·log2(1+SNR) 独立复算。
- FSPL 族：①精确 SI 光速双点 1km@1GHz=92.4477832 / 1m@1GHz=32.4477832
  （教科书 92.44/32.44=c≈3e8 圆化口径，带对拍 ≤0.01dB 不凑逐位）；②
  d/f 加倍 +6.0205999dB 精确；③真空恒等式残差 ~0；④独立复算
  20lg(d_km)+20lg(f_MHz)+常数形。
- 链路账族：①逐项可加恒等（margin/Friis 交叉自检残差 ~0）；②d 加倍/
  灵敏度平移精确响应；③同仓双源 rfid_forward_link 内嵌式对拍
  （p_tag==P_r，R2 C1 锚）。
- Hamming 族：①(7,4) 完全码 Hamming bound 取等（2^4·8=128=2^7 精确
  整数）；②m=2..7 全系 perfect+k=n−m 恒等。
- RS 族：①RS(255,223) NASA 标准码 d=33→t=16 逐位+Singleton slack=0+
  突发 121bit；②奇余量档 (255,240) n−k=15→t=7/d=16。
- 编码增益族：①n=k,t=0 → G≡0（二项均值恒等式）；②union bound 独立
  实现互证（scipy.stats.binom 生存函数/恒等变形 P_b=p·P[Bin(n−1,p)≥t]
  双路，非同式复抄）；③P_b 全 γ 扫描单调降（二分前提复核）；④量级序
  RS(255,223) > Hamming(7,4)（同点结构钉）；⑤G 回灌 coded_ber_estimate
  闭环复现 target（coded_ber_estimate_gain_db 回灌面，接线钉）+双口径
  恒等（G_loop−G_net=−10lg(R_c)）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.calculator_service import run_calculator

_C0 = 299792458.0


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _err(key: str, params: dict) -> str:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 对非法输入未报错: {out!r}"
    return out["error"]


# ─── shannon_capacity：教科书锚 / ln2 极限 / 双口径 / 守卫 ──────────────────


def test_shannon_capacity_eta2_textbook_anchor():
    """η=2 → Eb/N0_min=(2²−1)/2=1.5=1.76091dB（独立解析复算）。"""
    r = _run("shannon_capacity", {"bandwidth_hz": 1.0, "snr_linear": 3.0})
    assert r["capacity_bps"] == pytest.approx(2.0, abs=1e-9)
    assert r["spectral_efficiency_bps_hz"] == pytest.approx(2.0, abs=1e-9)
    # 独立算术：10log10(1.5)
    assert r["shannon_limit_ebn0_min_db"] == pytest.approx(
        10.0 * math.log10(1.5), abs=1e-9)
    assert r["shannon_limit_ebn0_min_db"] == pytest.approx(1.760912591,
                                                           abs=1e-6)


def test_shannon_floor_ln2_limit():
    """η→0 极限 ln2=−1.59175dB：常数字段与深衰点数值逼近双路。"""
    r0 = _run("shannon_capacity", {"bandwidth_hz": 1.0, "snr_linear": 1.0})
    assert r0["shannon_floor_ebn0_db"] == pytest.approx(
        10.0 * math.log10(math.log(2.0)), abs=1e-9)
    # 深衰逼近：SNR=1e-9 → η→0，limit→floor（差 <1e-5 dB）
    r1 = _run("shannon_capacity", {"bandwidth_hz": 1.0, "snr_linear": 1e-9})
    assert r1["shannon_limit_ebn0_min_db"] == pytest.approx(
        r1["shannon_floor_ebn0_db"], abs=1e-5)


def test_shannon_dual_caliber_and_capacity_identity():
    """dB/线性双口径同参一致 + C=B·log2(1+SNR) 独立复算。"""
    rd = _run("shannon_capacity", {"bandwidth_hz": 1e6, "snr_db": 10.0})
    rl = _run("shannon_capacity", {"bandwidth_hz": 1e6,
                                   "snr_linear": 10.0 ** 1.0})
    assert rd["capacity_bps"] == rl["capacity_bps"]
    assert rd["spectral_efficiency_bps_hz"] == rl["spectral_efficiency_bps_hz"]
    assert rd["shannon_limit_ebn0_min_db"] == rl["shannon_limit_ebn0_min_db"]
    assert rd["spectral_efficiency_bps_hz"] == pytest.approx(
        math.log2(11.0), abs=1e-12)
    assert rd["capacity_bps"] == pytest.approx(1e6 * math.log2(11.0),
                                               abs=1e-3)


def test_shannon_capacity_guards():
    """域守卫：B≤0 / SNR 双口径歧义与全缺 / 线性值≤0 / 非有限。"""
    assert "bandwidth_hz" in _err("shannon_capacity",
                                  {"bandwidth_hz": 0.0, "snr_db": 10.0})
    assert "恰好给其一" in _err("shannon_capacity", {
        "bandwidth_hz": 1e6, "snr_db": 10.0, "snr_linear": 10.0})
    assert "恰好给其一" in _err("shannon_capacity", {"bandwidth_hz": 1e6})
    assert "snr_linear" in _err("shannon_capacity",
                                {"bandwidth_hz": 1e6, "snr_linear": 0.0})
    assert "有限" in _err("shannon_capacity",
                          {"bandwidth_hz": 1e6, "snr_db": float("inf")})


# ─── free_space_path_loss：精确 SI 双点 / 教科书带 / 加倍律 / 守卫 ──────────


def test_fspl_exact_si_anchors_and_textbook_band():
    """1km@1GHz=92.4477832、1m@1GHz=32.4477832（精确 SI）；教科书
    92.44/32.44=c≈3e8 圆化口径带对拍 ≤0.01dB。"""
    r_km = _run("free_space_path_loss", {"distance_m": 1000.0,
                                         "freq_hz": 1e9})
    r_m = _run("free_space_path_loss", {"distance_m": 1.0, "freq_hz": 1e9})
    assert r_km["fspl_db"] == pytest.approx(92.4477832, abs=1e-6)
    assert r_m["fspl_db"] == pytest.approx(32.4477832, abs=1e-6)
    assert r_km["fspl_db"] == pytest.approx(92.44, abs=0.01)
    assert r_m["fspl_db"] == pytest.approx(32.44, abs=0.01)
    # 独立复算：常数形（c≈3e8 教科书口径）32.44+20lg(d_km)+20lg(f_MHz)
    textbook = 32.44 + 20.0 * math.log10(1.0) + 20.0 * math.log10(1000.0)
    assert r_km["fspl_db"] == pytest.approx(textbook, abs=0.01)
    assert r_km["wavelength_m"] == pytest.approx(_C0 / 1e9, abs=1e-12)


def test_fspl_doubling_law_and_vacuum_identity():
    """d/f 加倍恒 +6.0205999dB（精确）；真空恒等式残差逐位 ~0。"""
    base = _run("free_space_path_loss", {"distance_m": 7000.0,
                                         "freq_hz": 2.4e9})
    d2 = _run("free_space_path_loss", {"distance_m": 14000.0,
                                       "freq_hz": 2.4e9})
    f2 = _run("free_space_path_loss", {"distance_m": 7000.0,
                                       "freq_hz": 4.8e9})
    shift = 20.0 * math.log10(2.0)
    assert d2["fspl_db"] - base["fspl_db"] == pytest.approx(shift, abs=1e-9)
    assert f2["fspl_db"] - base["fspl_db"] == pytest.approx(shift, abs=1e-9)
    assert base["identity_residual_db"] == pytest.approx(0.0, abs=1e-9)
    # FSPL_linear=(4πd/λ)² 独立复算
    lam = _C0 / 2.4e9
    assert base["fspl_linear"] == pytest.approx((4.0 * math.pi * 7000.0
                                                 / lam) ** 2, rel=1e-9)


def test_fspl_excess_port_and_guards():
    """excess_loss_db 显式加性端口（真空/总量分列）+ 域守卫。"""
    r = _run("free_space_path_loss", {"distance_m": 1000.0, "freq_hz": 1e9,
                                      "excess_loss_db": 12.5})
    assert r["total_loss_db"] == pytest.approx(r["fspl_db"] + 12.5, abs=1e-9)
    assert "distance_m" in _err("free_space_path_loss",
                                {"distance_m": 0.0, "freq_hz": 1e9})
    assert "freq_hz" in _err("free_space_path_loss",
                             {"distance_m": 1.0, "freq_hz": -5.0})
    assert "有限" in _err("free_space_path_loss",
                          {"distance_m": 1.0, "freq_hz": 1e9,
                           "excess_loss_db": float("nan")})


# ─── link_margin_calc：可加恒等 / 平移律 / 同仓双源 / 守卫 ──────────────────

_LM = {"tx_power_dbm": 40.0, "tx_gain_dbi": 30.0, "rx_gain_dbi": 15.0,
       "distance_m": 50000.0, "freq_hz": 10e9, "rx_sensitivity_dbm": -85.0,
       "misc_loss_db": 3.0}


def test_link_margin_additive_identity_and_friis_crosscheck():
    """逐项 dB 加账恒等（margin 残差）+ Friis 线性式交叉自检（传播点
    口径对齐 misc）双残差 ~0 + 手工复算接收功率。"""
    r = _run("link_margin_calc", _LM)
    assert r["margin_identity_residual_db"] == pytest.approx(0.0, abs=1e-9)
    assert r["friis_crosscheck_residual_db"] == pytest.approx(0.0, abs=1e-6)
    fs = _run("free_space_path_loss", {"distance_m": _LM["distance_m"],
                                       "freq_hz": _LM["freq_hz"]})
    assert r["fspl_db"] == fs["fspl_db"]  # FSPL 单源同值
    manual = (_LM["tx_power_dbm"] + _LM["tx_gain_dbi"] + _LM["rx_gain_dbi"]
              - fs["fspl_db"] - _LM["misc_loss_db"])
    assert r["rx_power_dbm"] == pytest.approx(manual, abs=1e-9)
    assert r["link_margin_db"] == pytest.approx(
        manual - _LM["rx_sensitivity_dbm"], abs=1e-9)
    assert r["link_closed"] is True


def test_link_margin_distance_and_sensitivity_shift():
    """d 加倍 → margin 精确 −6.0205999dB；灵敏度 +3dB → margin −3dB。"""
    base = _run("link_margin_calc", _LM)
    far = _run("link_margin_calc", {**_LM, "distance_m": 100000.0})
    assert far["link_margin_db"] - base["link_margin_db"] == pytest.approx(
        -20.0 * math.log10(2.0), abs=1e-9)
    hot = _run("link_margin_calc", {**_LM,
                                    "rx_sensitivity_dbm": -82.0})
    assert hot["link_margin_db"] == pytest.approx(
        base["link_margin_db"] - 3.0, abs=1e-9)


def test_link_margin_rfid_forward_link_dual_source():
    """同仓双源对拍（R2 C1 锚）：rfid_forward_link 内嵌 20lg(4πd/λ) 同式
    ——p_tag==P_r（915MHz/5m 名义点，<1e-9）。"""
    f, d = 915e6, 5.0
    rf = _run("rfid_forward_link", {"frequency_hz": f, "eirp_dbm": 36.0,
                                    "g_tag_dbi": 2.0, "distance_m": d,
                                    "sensitivity_dbm": -60.0})
    lm = _run("link_margin_calc", {"tx_power_dbm": 33.0, "tx_gain_dbi": 3.0,
                                   "rx_gain_dbi": 2.0, "distance_m": d,
                                   "freq_hz": f, "rx_sensitivity_dbm": -60.0})
    assert lm["rx_power_dbm"] == pytest.approx(rf["p_tag_dbm"], abs=1e-9)


def test_link_margin_guards():
    """域守卫：距离/频率 ≤0、非有限功率。"""
    assert "distance_m" in _err("link_margin_calc", {**_LM,
                                                     "distance_m": -5.0})
    assert "freq_hz" in _err("link_margin_calc", {**_LM, "freq_hz": 0.0})
    assert "有限" in _err("link_margin_calc",
                          {**_LM, "tx_power_dbm": float("inf")})


# ─── hamming_code_design：完全码 bound 取等 / 家族 / 守卫 ───────────────────


def test_hamming_74_perfect_code_bound_equality():
    """Hamming(7,4)：bound 2^4·(1+7)=128=2^7 精确整数取等+参数面。"""
    r = _run("hamming_code_design", {"parity_bits_m": 3})
    assert r["block_length_n"] == 7
    assert r["info_bits_k"] == 4
    assert r["d_min"] == 3
    assert r["t_correct"] == 1
    assert r["code_rate"] == pytest.approx(4.0 / 7.0, abs=1e-12)
    assert r["hamming_bound_left"] == 128
    assert r["hamming_bound_right"] == 128
    assert r["perfect_code"] is True
    assert r["hamming_bound_satisfied"] is True
    assert r["identity_k_eq_n_minus_m"] is True
    assert r["parity_matrix_shape"] == [3, 7]


def test_hamming_family_all_perfect():
    """m=2..7 全系完全码（原生 Hamming 码 bound 取等）+k=n−m 恒等。"""
    for m in range(2, 8):
        r = _run("hamming_code_design", {"parity_bits_m": m})
        assert r["block_length_n"] == 2 ** m - 1
        assert r["info_bits_k"] == 2 ** m - 1 - m
        assert r["perfect_code"] is True
        assert r["d_min"] == 3 and r["t_correct"] == 1


def test_hamming_guards():
    """域守卫：m<2 / m>16 / 非整数 / 布尔值。"""
    assert "parity_bits_m" in _err("hamming_code_design",
                                   {"parity_bits_m": 1})
    assert "parity_bits_m" in _err("hamming_code_design",
                                   {"parity_bits_m": 17})
    assert "整数" in _err("hamming_code_design", {"parity_bits_m": 4.5})
    assert "整数" in _err("hamming_code_design", {"parity_bits_m": True})


# ─── reed_solomon_capacity：NASA 标准码 / 奇余量档 / 守卫 ───────────────────


def test_rs_255_223_nasa_standard_anchor():
    """RS(255,223)（GF(256)）NASA 标准码：d=33→t=16 逐位+Singleton
    slack=0+突发 (16−1)·8+1=121bit+擦除面 32。"""
    r = _run("reed_solomon_capacity", {"n_sym": 255, "k_sym": 223,
                                       "symbol_bits_m": 8})
    assert r["d_min"] == 33
    assert r["t_correct_sym"] == 16
    assert r["singleton_slack"] == 0
    assert r["burst_guarantee_bits"] == 121
    assert r["max_erasures_only"] == 32
    assert r["code_rate"] == pytest.approx(223.0 / 255.0, abs=1e-12)
    assert r["gf_size"] == 256
    assert r["errors_erasures_rule"] == "2*e + f <= n-k（e=符号错数, f=擦除数）"


def test_rs_odd_parity_budget_and_singleton_identity():
    """奇余量档 RS(255,240)：n−k=15 → d=16、t=7（⌊15/2⌋）+Singleton
    恒等式 slack=0+突发 (7−1)·8+1=49bit。"""
    r = _run("reed_solomon_capacity", {"n_sym": 255, "k_sym": 240,
                                       "symbol_bits_m": 8})
    assert r["d_min"] == 16
    assert r["t_correct_sym"] == 7
    assert r["singleton_slack"] == 0  # MDS 恒等式取等
    assert r["burst_guarantee_bits"] == 49
    assert r["max_erasures_only"] == 15


def test_rs_guards():
    """域守卫：码长超 GF 域 / k≥n / k=0 / 符号位宽越界。"""
    assert "n_sym" in _err("reed_solomon_capacity",
                           {"n_sym": 256, "k_sym": 223, "symbol_bits_m": 8})
    assert "k_sym" in _err("reed_solomon_capacity",
                           {"n_sym": 255, "k_sym": 255, "symbol_bits_m": 8})
    assert "k_sym" in _err("reed_solomon_capacity",
                           {"n_sym": 255, "k_sym": 0, "symbol_bits_m": 8})
    assert "symbol_bits_m" in _err("reed_solomon_capacity",
                                   {"n_sym": 7, "k_sym": 3,
                                    "symbol_bits_m": 2})


# ─── coded_ebn0_requirement：G 恒等 / 独立实现互证 / 单调 / 序 / 闭环 ────────

_H74 = {"scheme": "bpsk", "target_ber": 1e-5, "block_n": 7, "info_k": 4,
        "t_correct": 1}


def _post_decode_ber_indep(n: int, t: int, p: float) -> float:
    """union bound 独立实现（scipy binom 恒等变形双路）：

    P_b = (1/n)Σ_{i=t+1}^n i·C(n,i)p^i(1−p)^(n−i)
        = p·P[Bin(n−1,p) ≥ t]（i·C(n,i)=n·C(n−1,i−1) 恒等变形）
    """
    from scipy.stats import binom

    if p <= 0.0:
        return 0.0
    return float(p * binom.sf(t - 1, n - 1, p))


def test_coded_gain_zero_identity_uncoded_degenerate():
    """n=k、t=0 → G≡0（二项均值恒等式精确还原）+coded==uncoded。"""
    r = _run("coded_ebn0_requirement", {"scheme": "bpsk", "target_ber": 1e-5,
                                        "block_n": 7, "info_k": 7,
                                        "t_correct": 0})
    assert r["net_coding_gain_db"] == pytest.approx(0.0, abs=1e-9)
    assert r["coded_required_ebn0_db"] == pytest.approx(
        r["uncoded_required_ebn0_db"], abs=1e-9)
    assert r["channel_ber_at_coded_req"] == pytest.approx(1e-5, rel=1e-8)


def test_coded_union_bound_independent_implementation():
    """union bound 独立实现互证（#118 同式双实现）：块错率=binom.sf(t,n,p)
    + 译码后 BER=p·P[Bin(n−1,p)≥t] 恒等变形双路逐位。"""
    from scipy.stats import binom

    r = _run("coded_ebn0_requirement", _H74)
    p = r["channel_ber_at_coded_req"]
    # 块错率：P[X≥t+1]（Bin(n,p)）独立算术
    assert r["block_error_rate_union"] == pytest.approx(
        float(binom.sf(1, 7, p)), rel=1e-9)
    # 译码后 BER：i·C(n,i)=n·C(n−1,i−1) 恒等变形（独立路线）
    assert r["achieved_post_ber"] == pytest.approx(
        _post_decode_ber_indep(7, 1, p), rel=1e-9)
    assert r["achieved_post_ber"] == pytest.approx(1e-5, rel=1e-5)


def test_coded_post_ber_monotone_in_gamma():
    """P_b 对 γ 全扫描单调降（dB 域二分前提复核——独立实现载体）。"""
    from rfauto.core.calc_families.fec_codes import _coded_face_ber

    prev = float("inf")
    for g_db in range(-10, 41):  # −10..40 dB 步进 1
        pb = _coded_face_ber("bpsk", float(g_db), 7, 4, 1)
        assert pb <= prev + 1e-15, f"P_b 在 γ={g_db}dB 非单调"
        prev = pb


def test_coded_gain_band_and_ordering_structure():
    """量级序结构钉：Hamming(7,4) 正增益带 (0,6)dB+目标越严增益不降+
    RS(255,223) > Hamming(7,4)（同点纠错能力序）。"""
    g_5 = _run("coded_ebn0_requirement", _H74)["net_coding_gain_db"]
    g_8 = _run("coded_ebn0_requirement", {**_H74, "target_ber": 1e-8})
    g_rs = _run("coded_ebn0_requirement", {"scheme": "bpsk",
                                           "target_ber": 1e-5,
                                           "block_n": 255, "info_k": 223,
                                           "t_correct": 16})
    assert 0.0 < g_5 < 6.0
    assert g_8["net_coding_gain_db"] >= g_5
    assert g_rs["net_coding_gain_db"] > g_5


def test_coded_loopback_into_coded_ber_estimate():
    """G 回灌 coded_ber_estimate 闭环复现 target（coded_ber_estimate_gain_
    db 回灌面，接线钉）+双口径恒等（G_loop−G_net=−10lg(R_c)）。"""
    r = _run("coded_ebn0_requirement", _H74)
    # 双口径记账恒等：净增益−回灌面=码率扩张
    assert (r["net_coding_gain_db"] - r["coded_ber_estimate_gain_db"]
            == pytest.approx(r["rate_expansion_db"], abs=2e-6))
    lb = _run("coded_ber_estimate", {
        "scheme": "bpsk", "ebn0_db": r["coded_required_ebn0_db"],
        "code_rate": 4.0 / 7.0,
        "coding_gain_db": r["coded_ber_estimate_gain_db"]})
    assert abs(math.log10(lb["ber"]) + 5.0) < 1e-5  # 复现 target=1e-5


def test_coded_uncoded_branch_matches_required_ebn0_key():
    """未编码支路与 required_ebn0 键同源一致（同仓消费链接线钉）。"""
    r = _run("coded_ebn0_requirement", _H74)
    ref = _run("required_ebn0", {"target_ber": 1e-5, "scheme": "bpsk"})
    assert r["uncoded_required_ebn0_db"] == ref["required_ebn0_db"]


def test_coded_requirement_guards():
    """域守卫：t 超 (n−k)/2 必要条件 / target 越域 / 非整块长 / k>n。"""
    assert "t_correct" in _err("coded_ebn0_requirement",
                               {**_H74, "t_correct": 2})
    assert "target_ber" in _err("coded_ebn0_requirement",
                                {**_H74, "target_ber": 1.0})
    assert "target_ber" in _err("coded_ebn0_requirement",
                                {**_H74, "target_ber": 1e-16})
    assert "block_n" in _err("coded_ebn0_requirement",
                             {**_H74, "block_n": 7.5})
    assert "info_k" in _err("coded_ebn0_requirement",
                            {**_H74, "info_k": 8})
