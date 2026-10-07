"""r6 插② UHF RFID 链路预算闭式单测（rfid_forward_link / rfid_backscatter_link）。

锚值口径（#118 双路径纪律）：每个物理量先走两条独立推导（dB 链 vs 线性 SI
比），再钉字面常量抓系统性错——手算锚：
- 正向 @915 MHz/EIRP 36 dBm/G_tag 2 dBi/d=3 m：FSPL=41.2186 dB、
  P_tag=−3.2186 dBm；
- σm 短路/开路态（|Γ₁−Γ₂|=2）：λ²G²/π=0.085832 m²；
- 反向 @G_rx 6 dBi：P_rx=−30.4167 dBm；距离翻倍 Δ=−40·log10(2) dB（1/R⁴）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_C0 = 299792458.0
_F_HZ = 915e6
_LAMBDA = _C0 / _F_HZ  # 0.32764203060109287 m
_FWD_IN = {"frequency_hz": _F_HZ, "eirp_dbm": 36.0, "g_tag_dbi": 2.0,
           "distance_m": 3.0, "sensitivity_dbm": -15.0}
_BS_IN = {"frequency_hz": _F_HZ, "eirp_dbm": 36.0, "g_reader_rx_dbi": 6.0,
          "distance_m": 3.0, "rx_sensitivity_dbm": -70.0,
          "gamma_1": -1.0, "gamma_2": 1.0, "g_tag_dbi": 2.0}


# ─── 注册面（接口先行）───────────────────────────────────────────────────────

def test_rfid_keys_registered_and_described():
    names = CALCULATOR_REGISTRY.names()
    assert {"rfid_forward_link", "rfid_backscatter_link"} <= set(names)
    for key in ("rfid_forward_link", "rfid_backscatter_link"):
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.description
        assert not spec.experimental  # 正式键：默认名单含、默认可跑
        described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
        assert {p["name"] for p in described[key]["params"]} >= set(spec.required)


# ─── 正向 Friis：dB 链 vs 线性 SI 双路径回收 + 字面锚 ────────────────────────

def test_forward_friis_dual_path_and_literal_anchor():
    """dB 链（20log10 路径损耗）与线性 SI（功率比）两路独立推导逐位一致；
    字面锚 41.2186/−3.2186 抓系统性错（两推导同错的双保险）。"""
    r = run_calculator("rfid_forward_link", _FWD_IN)
    assert r["ok"]
    out = r["result"]
    # 路径 A：dB 链
    fspl_a = 20.0 * math.log10(4.0 * math.pi * 3.0 / _LAMBDA)
    ptag_a = 36.0 + 2.0 - fspl_a
    assert out["path_loss_db"] == pytest.approx(fspl_a, rel=1e-9)
    assert out["p_tag_dbm"] == pytest.approx(ptag_a, rel=1e-9)
    # 路径 B：线性 SI（EIRP_W·G·(λ/4πd)²→dBm）
    p_w = 10 ** 3.6 * 1e-3 * 10 ** 0.2 * (_LAMBDA / (4.0 * math.pi * 3.0)) ** 2
    assert out["p_tag_dbm"] == pytest.approx(10.0 * math.log10(p_w / 1e-3),
                                             rel=1e-9)
    # 字面锚（独立手算落定；输出按注册表惯例 round 9 位 → rel 1e-9）
    assert out["path_loss_db"] == pytest.approx(41.21863019760559, rel=1e-9)
    assert out["p_tag_dbm"] == pytest.approx(-3.2186301976055915, rel=1e-9)
    # 门判定：margin=P_tag−灵敏度，read_ok 恰等容差 ≥
    assert out["margin_db"] == pytest.approx(out["p_tag_dbm"] + 15.0, rel=1e-9)
    assert out["read_ok"] is True


def test_forward_max_distance_inverse_consistency():
    """d_max 反解自洽：在 d=d_max 处 P_tag=灵敏度（正反解同式闭环）。"""
    out = run_calculator("rfid_forward_link", _FWD_IN)["result"]
    d_max = out["max_distance_m"]
    assert d_max == pytest.approx(
        _LAMBDA / (4.0 * math.pi) * 10 ** ((36.0 + 2.0 + 15.0) / 20),
        rel=1e-9)
    edge = run_calculator("rfid_forward_link",
                          {**_FWD_IN, "distance_m": d_max})["result"]
    # 恰等边界（ge1③）：dB 域 1e-9 容差内 read_ok 不翻 False
    assert edge["margin_db"] == pytest.approx(0.0, abs=1e-6)
    assert edge["read_ok"] is True


def test_forward_polarization_loss_enters_chain():
    plain = run_calculator("rfid_forward_link", _FWD_IN)["result"]
    with_pol = run_calculator("rfid_forward_link",
                              {**_FWD_IN, "polarization_loss_db": 3.0}
                              )["result"]
    assert with_pol["p_tag_dbm"] == pytest.approx(
        plain["p_tag_dbm"] - 3.0, rel=1e-9)


# ─── 差分 RCS：短路/开路闭式锚 + 同负载零锚 ──────────────────────────────────

def test_backscatter_sigma_short_open_closed_form():
    """γ₁=−1/γ₂=+1（短路/开路）→ |ΔΓ|=2 → σm=λ²G²/π（Nikitin 2007 锚）。"""
    out = run_calculator("rfid_backscatter_link", _BS_IN)["result"]
    g_lin = 10 ** 0.2
    sigma_expected = _LAMBDA ** 2 * g_lin ** 2 / math.pi
    assert out["sigma_m_m2"] == pytest.approx(sigma_expected, rel=1e-12)
    assert out["sigma_m_m2"] == pytest.approx(0.08583202228255889, rel=1e-12)


def test_backscatter_sigma_same_load_is_zero_and_reported_honestly():
    """同负载态 |ΔΓ|=0 → σm=0：无背散射信号如实 None/False（不造假数值，
    JSON 契约禁非有限数）。"""
    out = run_calculator("rfid_backscatter_link",
                         {**_BS_IN, "gamma_1": 0.5, "gamma_2": 0.5})
    assert out["ok"] and out["result"]["sigma_m_m2"] == 0.0
    assert out["result"]["prx_dbm"] is None
    assert out["result"]["margin_db"] is None
    assert out["result"]["read_ok"] is False
    assert out["result"]["max_distance_m"] == 0.0


def test_backscatter_rcs_direct_mode_matches_gamma_mode():
    """直给 rcs_diff_m2 与 γ 态内部算 σm 两通道同数（公式通道自洽）。"""
    via_gamma = run_calculator("rfid_backscatter_link", _BS_IN)["result"]
    rcs_base = {k: v for k, v in _BS_IN.items()
                if k not in ("gamma_1", "gamma_2")}
    via_rcs = run_calculator("rfid_backscatter_link",
                             {**rcs_base, "rcs_diff_m2":
                              via_gamma["sigma_m_m2"]})
    assert via_rcs["ok"]
    # σm 经 round(9 位) 回灌 → prx 相对扰动 ~1e-11，容差取 1e-9
    assert via_rcs["result"]["prx_dbm"] == pytest.approx(
        via_gamma["prx_dbm"], rel=1e-9)
    assert via_rcs["result"]["sigma_m_m2"] == pytest.approx(
        via_gamma["sigma_m_m2"], rel=1e-9)


# ─── 反向 1/R⁴ 律：距离翻倍 → −40·log10(2) dB 逐位 ──────────────────────────

def test_backscatter_inverse_fourth_power_law():
    near = run_calculator("rfid_backscatter_link", _BS_IN)["result"]
    far = run_calculator("rfid_backscatter_link",
                         {**_BS_IN, "distance_m": 6.0})["result"]
    assert far["prx_dbm"] - near["prx_dbm"] == pytest.approx(
        -40.0 * math.log10(2.0), rel=1e-9)  # 输出 round 9 位 → 1e-9 容差


def test_backscatter_power_dual_path_and_literal_anchor():
    """线性 SI 雷达方程链（EIRP→密度→dRCS 重辐射→有效口径）独立回收 +
    字面锚 −30.4167 dBm。"""
    out = run_calculator("rfid_backscatter_link", _BS_IN)["result"]
    g_rx_lin, g_tag_lin = 10 ** 0.6, 10 ** 0.2
    sigma = _LAMBDA ** 2 * g_tag_lin ** 2 * 4.0 / (4.0 * math.pi)
    # 有效口径三步链（独立于实现内部单式）
    s_inc = 10 ** 3.6 * 1e-3 / (4.0 * math.pi * 9.0)
    s_back = s_inc * sigma / (4.0 * math.pi * 9.0)
    p_rx_w = s_back * g_rx_lin * _LAMBDA ** 2 / (4.0 * math.pi)
    assert out["prx_dbm"] == pytest.approx(10.0 * math.log10(p_rx_w / 1e-3),
                                           rel=1e-9)
    assert out["prx_dbm"] == pytest.approx(-30.41666048193155, rel=1e-9)


def test_backscatter_max_distance_inverse_consistency():
    """d_max^(1/4) 反解自洽：d=d_max 处 P_rx=rx 灵敏度（恰等容差）。"""
    out = run_calculator("rfid_backscatter_link", _BS_IN)["result"]
    edge = run_calculator("rfid_backscatter_link",
                          {**_BS_IN, "distance_m":
                           out["max_distance_m"]})["result"]
    assert edge["margin_db"] == pytest.approx(0.0, abs=1e-6)
    assert edge["read_ok"] is True


# ─── 读写距离合成：双门取小，两方向主导各验一例 ────────────────────────────────

def test_read_range_forward_gate_dominates():
    """灵敏度门主导：标签激活门（d≈11.65 m）近于反向门（rx −70 dBm→
    d≈29.29 m）→ read_range=正向门、limiting 如实报 forward。"""
    out = run_calculator("rfid_backscatter_link",
                         {**_BS_IN, "tag_sensitivity_dbm": -15.0})["result"]
    d_fwd = _LAMBDA / (4.0 * math.pi) * 10 ** ((36.0 + 2.0 + 15.0) / 20)
    assert out["limiting_gate"] == "forward_tag_sensitivity"
    assert out["read_range_m"] == pytest.approx(d_fwd, rel=1e-9)
    assert out["read_range_m"] == pytest.approx(11.6463475143173, rel=1e-9)


def test_read_range_backscatter_gate_dominates():
    """SNR 门主导：rx 灵敏度收紧到 −30 dBm（d≈2.929 m < 正向 11.65 m）
    → read_range=反向门、limiting 如实报 backscatter。"""
    out = run_calculator("rfid_backscatter_link",
                         {**_BS_IN, "rx_sensitivity_dbm": -30.0,
                          "tag_sensitivity_dbm": -15.0})["result"]
    assert out["limiting_gate"] == "backscatter_reader_sensitivity"
    assert out["read_range_m"] == pytest.approx(2.9289013396414676, rel=1e-9)
    # 与该键自身 max_distance（同门反解）一致
    assert out["read_range_m"] == pytest.approx(out["max_distance_m"],
                                                rel=1e-12)


# ─── 域守卫与入参契约 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["rfid_forward_link", "rfid_backscatter_link"])
def test_nfc_band_explicitly_rejected(key: str):
    """13.56 MHz（NFC 族域）显式 ValueError——UHF/NFC 域分离，禁缺省频段。"""
    nfc = {"frequency_hz": 13.56e6, "eirp_dbm": 36.0, "g_tag_dbi": 2.0,
           "g_reader_rx_dbi": 6.0, "distance_m": 0.05,
           "rx_sensitivity_dbm": -70.0, "sensitivity_dbm": -15.0,
           "rcs_diff_m2": 0.01}
    spec = CALCULATOR_REGISTRY.get(key)
    params = {k: v for k, v in nfc.items()
              if k in {pn for pn, _ in spec.params}}
    out = run_calculator(key, params)
    assert not out["ok"] and "UHF RFID 频域" in out["error"]


def test_upper_band_edge_and_above_rejected():
    out = run_calculator("rfid_forward_link",
                         {**_FWD_IN, "frequency_hz": 2.4e9})
    assert not out["ok"] and "UHF RFID 频域" in out["error"]
    # 带缘恰等（860/960 MHz）合法
    for f in (860e6, 960e6):
        assert run_calculator("rfid_forward_link",
                              {**_FWD_IN, "frequency_hz": f})["ok"]


def test_input_contract_errors_are_explicit():
    # 缺必需参数 / 未知参数
    out = run_calculator("rfid_forward_link", {"frequency_hz": _F_HZ})
    assert not out["ok"] and "缺少必需参数" in out["error"]
    out = run_calculator("rfid_forward_link",
                         {**_FWD_IN, "bogus_k": 1})
    assert not out["ok"] and "参数不匹配" in out["error"]
    # bool 拒收（df7+⑯：float(True)=1.0 静默污染链路预算）；rcs 通道
    # 需先剥掉 _BS_IN 的 γ 态（σm 来源二选一守卫先于数值校验）
    bs_rcs_base = {k: v for k, v in _BS_IN.items()
                   if k not in ("gamma_1", "gamma_2")}
    for key, base, field in (("rfid_forward_link", _FWD_IN, "eirp_dbm"),
                             ("rfid_forward_link", _FWD_IN, "distance_m"),
                             ("rfid_backscatter_link", bs_rcs_base,
                              "rcs_diff_m2")):
        out = run_calculator(key, {**base, field: True})
        assert not out["ok"] and "bool" in out["error"], (key, field)
    # σm 来源二选一：同给 / 都不给
    out = run_calculator("rfid_backscatter_link",
                         {**_BS_IN, "rcs_diff_m2": 0.01})
    assert not out["ok"] and "二选一" in out["error"]
    out = run_calculator("rfid_backscatter_link",
                         {k: v for k, v in _BS_IN.items()
                          if k not in ("gamma_1", "gamma_2")})
    assert not out["ok"] and "二选一" in out["error"]
    # γ 态残缺：只给 gamma_1 / 缺 g_tag_dbi
    out = run_calculator("rfid_backscatter_link",
                         {**_BS_IN, "gamma_2": None})
    assert not out["ok"]
    out = run_calculator("rfid_backscatter_link",
                         {k: v for k, v in _BS_IN.items()
                          if k != "g_tag_dbi"})
    assert not out["ok"] and "g_tag_dbi" in out["error"]
    # 物理符号守卫：负距离/负损耗显式报错
    out = run_calculator("rfid_forward_link", {**_FWD_IN, "distance_m": -1.0})
    assert not out["ok"]
    out = run_calculator("rfid_forward_link",
                         {**_FWD_IN, "polarization_loss_db": -0.1})
    assert not out["ok"]


def test_service_results_json_serializable():
    import json

    for key, params in (("rfid_forward_link", _FWD_IN),
                        ("rfid_backscatter_link",
                         {**_BS_IN, "tag_sensitivity_dbm": -15.0})):
        out = run_calculator(key, params)
        assert out["ok"]
        json.dumps(out, ensure_ascii=False, allow_nan=False)
