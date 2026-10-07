"""AP-9 卫星链路预算器锚测试（规格深案 §A-10，2026-10-02）。

锚口径（任务书预声明 + 实现实测写锚 #118 裁判纪律；零外部数据捆绑，
PV-011 无阻碍——全部锚=闭式恒等式/实现实测/公开量级窗）：

- FSPL 恒等：92.44778…+20·log10(f_GHz)+20·log10(d_km) 单源精确常数
  （=20·log10(4π·10¹²/c)，教科书圆整 92.45 偏差 −0.0022dB；多组逐位
  同表达式互证 + 4πdf/c 形态 1e-9 等价 + 独立书写 spot 值）。
- G/T↔NF 分解往返恒等：nf_db 口径解出的 T_sys 回填 t_sys_k 口径 →
  C/N0 与 G/T **逐位相等**（单源复用 core/gt_link.gt_ratio 的结构性
  保证）；T_sys 与 C/N0 链另按独立书写表达式复算。
- LEO 几何：E=90° 天顶斜距逐位 d=h（Re 无关）；斜距对仰角单调减；
  地平极限 E→0⁺ 收敛 √(h(2Re+h))（0.01° 实测 rel −4.1e-4）；圆轨速度
  ISS 量级窗（400km ≈ 7.67km/s 公开量级）；多普勒 rising/setting 逐位
  反号、天顶 |Δf|<1e-6 Hz、地平极限 v·Re/r·f/c（0.01° rel 1.5e-8）、
  550km/2GHz/10° 量级窗 ~45.9kHz（LEO S 波段公开量级，UNVERIFIED 标注）。
- GEO 公开算例：30° 仰角斜距 38611.6 km（公开量级窗）；典型 Ku GEO
  链 EIRP45/GT14.3/L208.3 → C/N0≈79.6 dB·Hz，落任务书指定 70–80
  dB·Hz 量级窗——**UNVERIFIED 量级锚如实标注：具体书值算例（Maral 或
  ITU Handbook）待钉不入硬门**，链内逐项恒等式为硬锚。
- 大气项降级：itu data_status 缺（骨架态恒如此）→ gas_db=0+UNVERIFIED
  注记（atm 轮廓给了也降级，不产假数）；显式 gas_db 直取；表就绪分支
  （monkeypatch）γ×path_len_km 恒等复算 + 缺 path_len_km 显式报错。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import itu_atmosphere
from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.core.sat_link import (
    _FSPL_KM_GHZ_DB,
    C0_M_S,
    EARTH_RADIUS_KM,
    KB_DBW_K_HZ,
    circular_orbit_velocity_m_s,
    doppler_hz,
    fspl_db,
    range_rate_m_s,
    sat_link_budget,
    slant_range_km,
)
from rfauto.service.calculator_service import run_calculator

_KEYS = ("sat_link_budget",)


# ─── 注册面（#231 五钉之一：test_calculators EXPECTED / invariants 输入表 ───
# ─── 同批追加；test_model_docs·test_experimental_calculators 为泛化消费）────


@pytest.mark.parametrize("key", _KEYS)
def test_registered_and_json_contract(key: str):
    assert key in set(CALCULATOR_REGISTRY.names())
    spec = CALCULATOR_REGISTRY.get(key)
    assert spec.description and not spec.experimental
    described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    assert {p["name"] for p in described[key]["params"]} >= set(spec.required)
    json.dumps(described[key], ensure_ascii=False)


def test_run_calculator_json_contract():
    link = {
        "tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
        "path": {"elevation_deg": 30.0, "alt_km": 35786.0},
        "rx": {"g_dbi": 40.0, "nf_db": 2.5, "t_ant_k": 150.0},
    }
    out = run_calculator("sat_link_budget", {"link": link})
    assert out["ok"] is True, out.get("error")
    json.dumps(out, allow_nan=False)
    # 对未来消费面：逐项链 table 化可 JSON 序列化（service 壳 result 内层）
    json.dumps(out["result"]["result"]["chain"], allow_nan=False)


# ─── FSPL 恒等锚 ─────────────────────────────────────────────────────────────

# (d_km, f_ghz) 多组：GEO/LEO/近地/1km·1GHz 角点
_FSPL_PAIRS = [
    (40000.0, 12.0),
    (2000.0, 2.0),
    (550.0, 20.0),
    (38611.642734292975, 14.25),
    (1.0, 1.0),
]


def test_fspl_bitwise_identity_and_exact_constant():
    # 单源精确常数 C=20log10(4π·10¹²/c)；"92.45" 是教科书圆整（偏差<0.005dB）
    c_ref = 20.0 * math.log10(4.0 * math.pi * 1e12 / C0_M_S)
    assert c_ref == _FSPL_KM_GHZ_DB
    assert abs(_FSPL_KM_GHZ_DB - 92.45) < 0.005
    assert abs(_FSPL_KM_GHZ_DB - 92.4477832) < 1e-6
    for d, f in _FSPL_PAIRS:
        got = fspl_db(d, f)
        # 多组逐位：与同表达式书写形态恒等（IEEE 确定性）
        assert got == _FSPL_KM_GHZ_DB + 20.0 * math.log10(f) + 20.0 * math.log10(d)
        # 与 4πdf/c 原始形态数学恒等（同 float 运算次序差异 ≤1e-9 dB）
        assert abs(got - 20.0 * math.log10(4.0 * math.pi * d * 1e3 * f * 1e9 / C0_M_S)) < 1e-9


def test_fspl_spot_value_independent():
    # 独立书写：12GHz/40000km = 21.583625 + 92.041200 + 92.447783 = 206.072608 dB
    fspl = fspl_db(40000.0, 12.0)
    assert fspl == pytest.approx(
        20.0 * math.log10(12.0) + 92.04119982655925 + _FSPL_KM_GHZ_DB, abs=1e-12)
    assert 206.0 < fspl < 206.2  # 量级窗（公开 Ku GEO 路损 ~206dB）


def test_fspl_domain_guards():
    for d, f in ((0.0, 12.0), (-1.0, 12.0), (550.0, 0.0), (550.0, -3.0)):
        with pytest.raises(ValueError):
            fspl_db(d, f)
    with pytest.raises(ValueError):
        fspl_db(True, 12.0)  # bool 显式拒收


# ─── G/T ↔ NF 分解往返恒等锚 ────────────────────────────────────────────────

_RT_LINK = {
    "tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
    "path": {"elevation_deg": 30.0, "alt_km": 35786.0,
             "pointing_loss_db": 1.0, "gas_db": 0.5, "rain_db": 1.0},
    "rx": {"g_dbi": 40.0, "nf_db": 2.5, "t_ant_k": 150.0},
}


def test_gt_nf_roundtrip_bitwise():
    rep_nf = sat_link_budget(_RT_LINK)
    t_sys = rep_nf["rx"]["t_sys_k"]
    assert rep_nf["rx"]["t_sys_path"] == "nf"
    # nf 口径 T_sys = t_ant + T0·(F−1)（独立书写复算，IEEE 加法交换逐位）
    assert t_sys == 150.0 + 290.0 * (10.0 ** (2.5 / 10.0) - 1.0)
    # 往返：t_sys 直接口径回填 → C/N0 与 G/T 逐位相等
    link_ts = {
        "tx": _RT_LINK["tx"],
        "path": _RT_LINK["path"],
        "rx": {"g_dbi": 40.0, "t_sys_k": t_sys},
    }
    rep_ts = sat_link_budget(link_ts)
    assert rep_ts["rx"]["t_sys_path"] == "t_sys_direct"
    assert rep_ts["rx"]["t_sys_k"] == t_sys
    assert rep_ts["rx"]["gt_db_per_k"] == rep_nf["rx"]["gt_db_per_k"]
    assert rep_ts["result"]["cn0_db_hz"] == rep_nf["result"]["cn0_db_hz"]
    # G/T 定义复算：G − 10log10(T_sys)（ITU-R S.733-2 口径，单源 gt_link）
    gt = 40.0 - 10.0 * math.log10(t_sys)
    assert rep_nf["rx"]["gt_db_per_k"] == gt


def test_cn0_chain_recomputation():
    rep = sat_link_budget(_RT_LINK)
    d = slant_range_km(30.0, 35786.0)
    fspl = fspl_db(d, 12.0)
    total = fspl + 1.0 + 0.5 + 1.0
    t_sys = 150.0 + 290.0 * (10.0 ** (2.5 / 10.0) - 1.0)
    gt = 40.0 - 10.0 * math.log10(t_sys)
    cn0 = 45.0 - total + gt + KB_DBW_K_HZ
    assert rep["path"]["fspl_db"] == fspl
    assert rep["path"]["total_loss_db"] == total
    assert rep["result"]["cn0_db_hz"] == cn0
    # 载波功率独立恒等：C = EIRP − L + G（与 C/N0 − G/T + ... 一致性）
    assert rep["result"]["received_carrier_c_dbw"] == 45.0 - total + 40.0
    # KB 单源复算（SI 精确 Boltzmann）
    assert -10.0 * math.log10(1.380649e-23) == KB_DBW_K_HZ
    assert 228.59 < KB_DBW_K_HZ < 228.61  # 工程口 228.6 的精确形


# ─── LEO 几何锚 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("alt", [550.0, 780.0, 35786.0])
def test_slant_zenith_is_exactly_alt(alt: float):
    assert slant_range_km(90.0, alt) == alt  # 天顶逐位（float64 实测恒等）


def test_slant_monotone_and_identity():
    e10 = slant_range_km(10.0, 550.0)
    e30 = slant_range_km(30.0, 550.0)
    e90 = slant_range_km(90.0, 550.0)
    assert e10 > e30 > e90  # 仰角增 → 斜距单调减
    # 独立书写同式逐位
    re = EARTH_RADIUS_KM
    er = math.radians(10.0)
    assert e10 == math.sqrt((re + 550.0) ** 2 - (re * math.cos(er)) ** 2) - re * math.sin(er)
    assert 1810.0 < e10 < 1820.0  # 550km/10° 公开量级 ~1816km


def test_slant_horizon_limit():
    h = 550.0
    horizon = math.sqrt(h * (2.0 * EARTH_RADIUS_KM + h))  # E→0⁺ 闭式极限
    near = slant_range_km(0.01, h)
    assert near / horizon - 1.0 == pytest.approx(0.0, abs=1e-3)


def test_orbit_velocity_iss_scale():
    v400 = circular_orbit_velocity_m_s(400.0)
    assert 7600.0 < v400 < 7750.0  # ISS 量级窗（公开 ~7.66km/s）
    v = math.sqrt(3.986004418e14 / ((EARTH_RADIUS_KM + 400.0) * 1e3))
    assert v400 == v  # 同式逐位


def test_doppler_antisymmetry_and_zenith_zero():
    for f, alt in ((2.0, 550.0), (12.0, 35786.0), (1.625, 780.0)):
        for e in (5.0, 10.0, 45.0, 89.0):
            up = doppler_hz(f, e, alt, direction="rising")
            down = doppler_hz(f, e, alt, direction="setting")
            assert up == -down  # 逐位反号
            assert up > 0.0  # 临近（升段）为正移
    assert abs(doppler_hz(2.0, 90.0, 550.0)) < 1e-6  # 天顶距离率→0
    assert range_rate_m_s(90.0, 550.0) < 1e-12  # cos(90°)~6e-17 的机械残差


def test_doppler_horizon_limit_and_magnitude():
    alt = 550.0
    v = circular_orbit_velocity_m_s(alt)
    max_rr = v * (EARTH_RADIUS_KM / (EARTH_RADIUS_KM + alt))  # 地平极限 v·Re/r
    got = range_rate_m_s(0.01, alt)
    assert got / max_rr - 1.0 == pytest.approx(0.0, abs=1e-6)
    # 550km/2GHz/10° ≈ 45.9kHz（LEO S 波段公开量级窗，UNVERIFIED 标注量级锚）
    dop = doppler_hz(2.0, 10.0, 550.0)
    assert 44000.0 < dop < 48000.0
    assert dop == pytest.approx(2.0e9 / C0_M_S * range_rate_m_s(10.0, 550.0))


def test_doppler_direction_guard():
    with pytest.raises(ValueError):
        doppler_hz(2.0, 10.0, 550.0, direction="up")


# ─── GEO 公开算例（量级窗 UNVERIFIED 标注；链内恒等式硬锚）───────────────────

_GEO_LINK = {
    "tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
    "path": {"elevation_deg": 30.0, "alt_km": 35786.0,
             "pointing_loss_db": 1.0, "gas_db": 0.5, "rain_db": 1.0},
    "rx": {"g_dbi": 40.0, "nf_db": 2.5, "t_ant_k": 150.0},
    "bw_hz": 36e6,
    "required_cn0_db_hz": 75.0,
}


def test_geo_example():
    rep = sat_link_budget(_GEO_LINK)
    # 斜距公开量级：GEO 30° 仰角 ≈ 38611.6 km
    slant = rep["geometry"]["slant_km"]
    assert 38500.0 < slant < 38750.0
    assert slant == slant_range_km(30.0, 35786.0)
    assert rep["geometry"]["mode"] == "elevation_alt"
    # elevation 模式恒产多普勒（机械量；GEO 高度的过境语义由调用方解释）
    assert rep["geometry"]["doppler_hz"] == doppler_hz(12.0, 30.0, 35786.0)
    assert rep["geometry"]["range_rate_m_s"] == range_rate_m_s(30.0, 35786.0)
    # C/N0 量级窗（任务书指定 70–80 dB·Hz；UNVERIFIED 量级锚如实标注——
    # 具体书值算例待钉不入硬门）：EIRP45 − L208.27 + G/T14.25 + 228.60
    cn0 = rep["result"]["cn0_db_hz"]
    assert 70.0 < cn0 < 80.0
    assert cn0 == pytest.approx(79.585, abs=0.05)  # 实现实测锚（#118 实测写锚）
    # C/N 与 margin
    assert rep["result"]["cn_db"] == cn0 - 10.0 * math.log10(36e6)
    assert rep["result"]["margin_db"] == cn0 - 75.0
    assert rep["result"]["margin_basis"] == "cn0"
    assert 4.0 < rep["result"]["margin_db"] < 5.0
    # 逐项链结构与载体
    items = [c["item"] for c in rep["result"]["chain"]]
    assert items == ["eirp_dbw", "total_path_loss_db", "received_carrier_c_dbw",
                     "gt_db_per_k", "boltzmann_minus_10log_k", "cn0_db_hz",
                     "cn_db", "ebn0_db", "margin_db"]


def test_geo_slant_direct_mode_equivalence():
    """slant 直接模式与 elevation 模式同斜距 → FSPL/C/N0 逐位相等。"""
    losses = {"pointing_loss_db": 1.0, "gas_db": 0.5, "rain_db": 1.0}
    direct = sat_link_budget({"tx": _GEO_LINK["tx"],
                              "path": {"slant_km": 38611.642734292975, **losses},
                              "rx": _GEO_LINK["rx"]})
    elev = sat_link_budget({"tx": _GEO_LINK["tx"],
                            "path": {"elevation_deg": 30.0, "alt_km": 35786.0,
                                     **losses},
                            "rx": _GEO_LINK["rx"]})
    assert direct["geometry"]["mode"] == "slant_direct"
    assert direct["geometry"]["doppler_hz"] is None
    assert direct["geometry"]["range_rate_m_s"] is None
    assert direct["path"]["fspl_db"] == elev["path"]["fspl_db"]  # 逐位
    assert direct["result"]["cn0_db_hz"] == elev["result"]["cn0_db_hz"]
    assert direct["path"]["total_loss_db"] == elev["path"]["total_loss_db"]


# ─── 大气项降级面（不产假数）─────────────────────────────────────────────────

def test_gas_degrades_to_zero_with_note_when_no_request():
    link = {"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
            "path": {"slant_km": 40000.0},
            "rx": {"g_dbi": 40.0, "nf_db": 2.5}}
    rep = sat_link_budget(link)
    assert rep["path"]["gas_db"] == 0.0
    assert rep["path"]["gas_source"] == "not_requested"
    # AP-8 落表后 data_status 实态翻转（"unverified"→"verified"）——
    # 断言改读实态防止再翻转时假红（状态值本身由 itu_atmosphere 自身测试钉）
    assert rep["data_status"]["p676_o2_table1"] in ("unverified", "verified")


def test_gas_degrades_to_zero_with_unverified_note_when_atm_given(monkeypatch):
    # 降级机制钉：monkeypatch 表态回 UNVERIFIED 态（AP-8 落表后真态走
    # "表就绪需 path_len_km" 分支，降级路径由同文件
    # test_gas_verified_branch_identity 的镜像态覆盖）
    import rfauto.core.itu_atmosphere as itu
    monkeypatch.setattr(itu, "has_676_tables", lambda: False, raising=False)
    link = {"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
            "path": {"slant_km": 40000.0,
                     "atm": {"p_hpa": 1013.25, "t_k": 288.15,
                             "rho_wv_g_m3": 7.5}},
            "rx": {"g_dbi": 40.0, "nf_db": 2.5}}
    rep = sat_link_budget(link)
    assert rep["path"]["gas_db"] == 0.0  # 不产假数：给 atm 也降级
    assert rep["path"]["gas_source"] == "no_data_zero"
    assert any("UNVERIFIED" in n for n in rep["notes"])


def test_gas_explicit_input_used():
    link = {"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
            "path": {"slant_km": 40000.0, "gas_db": 0.5},
            "rx": {"g_dbi": 40.0, "nf_db": 2.5}}
    rep = sat_link_budget(link)
    assert rep["path"]["gas_db"] == 0.5
    assert rep["path"]["gas_source"] == "explicit_input"
    assert rep["path"]["total_loss_db"] == rep["path"]["fspl_db"] + 0.5


def test_gas_verified_branch_identity(monkeypatch):
    """表就绪分支（monkeypatch 机械验证）：γ×path_len_km 恒等复算。"""
    monkeypatch.setattr(itu_atmosphere, "has_676_tables", lambda: True)
    atm = {"p_hpa": 1013.25, "t_k": 288.15, "rho_wv_g_m3": 7.5,
           "path_len_km": 10.0}
    link = {"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
            "path": {"slant_km": 40000.0, "atm": atm},
            "rx": {"g_dbi": 40.0, "nf_db": 2.5}}
    rep = sat_link_budget(link)
    gamma = itu_atmosphere.gamma_gasses_db_per_km(12e9, 1013.25, 288.15, 7.5)
    assert rep["path"]["gas_db"] == gamma * 10.0
    assert rep["path"]["gas_source"] == "itu_p676_annex1"
    # 表就绪但缺有效路径长 → 显式报错（不隐式建模斜距大气段）
    bad = dict(link)
    bad["path"] = {"slant_km": 40000.0,
                   "atm": {"p_hpa": 1013.25, "t_k": 288.15,
                           "rho_wv_g_m3": 7.5}}
    with pytest.raises(ValueError, match="path_len_km"):
        sat_link_budget(bad)


# ─── 需求门/margin 语义 ──────────────────────────────────────────────────────

def test_margin_requires_explicit_requirement():
    base = {"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
            "path": {"slant_km": 40000.0},
            "rx": {"g_dbi": 40.0, "nf_db": 2.5}}
    rep = sat_link_budget(base)
    assert rep["result"]["margin_db"] is None
    assert rep["result"]["margin_basis"] is None
    assert any("MODCOD" in n for n in rep["notes"])  # UNVERIFIED 档不做注记

    rep2 = sat_link_budget({**base, "bw_hz": 36e6, "required_cn_db": 3.0})
    assert rep2["result"]["margin_basis"] == "cn"
    assert rep2["result"]["margin_db"] == rep2["result"]["cn_db"] - 3.0

    rep3 = sat_link_budget({**base, "rb_bps": 1e6, "required_ebno_db": 5.0})
    assert rep3["result"]["ebn0_db"] == rep3["result"]["cn0_db_hz"] - 60.0
    assert rep3["result"]["margin_basis"] == "ebn0"

    # 多需求门：cn 优先 + 注记；cn0 档并行可查
    rep4 = sat_link_budget({**base, "bw_hz": 36e6, "required_cn_db": 3.0,
                            "required_cn0_db_hz": 70.0})
    assert rep4["result"]["margin_basis"] == "cn"
    assert rep4["result"]["cn0_margin_db"] == rep4["result"]["cn0_db_hz"] - 70.0
    assert any("优先级" in n for n in rep4["notes"])

    # 需求给了但量不可算 → 显式报错（不静默）
    with pytest.raises(ValueError, match="bw_hz"):
        sat_link_budget({**base, "required_cn_db": 3.0})
    with pytest.raises(ValueError, match="rb_bps"):
        sat_link_budget({**base, "required_ebno_db": 5.0})


def test_doppler_direction_in_budget():
    base = {"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
            "path": {"elevation_deg": 10.0, "alt_km": 550.0},
            "rx": {"g_dbi": 40.0, "nf_db": 2.5}}
    rising = sat_link_budget(base)["geometry"]["doppler_hz"]
    setting = sat_link_budget(
        {**base, "path": {**base["path"], "doppler_direction": "setting"}}
    )["geometry"]["doppler_hz"]
    assert rising == -setting
    assert rising == doppler_hz(12.0, 10.0, 550.0)


# ─── 域守卫（显式 ValueError，不静默）────────────────────────────────────────

def _base_link() -> dict:
    return {"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
            "path": {"elevation_deg": 30.0, "alt_km": 550.0},
            "rx": {"g_dbi": 40.0, "nf_db": 2.5}}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda lk: lk.__setitem__("path", {"elevation_deg": 0.0, "alt_km": 550.0}),
        lambda lk: lk.__setitem__("path", {"elevation_deg": -5.0, "alt_km": 550.0}),
        lambda lk: lk.__setitem__("path", {"elevation_deg": 90.5, "alt_km": 550.0}),
        lambda lk: lk.__setitem__("path", {"elevation_deg": 30.0, "alt_km": 0.0}),
        lambda lk: lk.__setitem__("path", {"elevation_deg": 30.0, "alt_km": -100.0}),
        lambda lk: lk.__setitem__("path", {"slant_km": 0.0}),
        lambda lk: lk.__setitem__("path", {"pointing_loss_db": -1.0}),
        lambda lk: lk.__setitem__("path", {"rain_db": -1.0}),
        lambda lk: lk.__setitem__("path", {"gas_db": -0.5}),
        lambda lk: lk["tx"].__setitem__("f_ghz", 0.0),
        lambda lk: lk["tx"].__setitem__("f_ghz", -12.0),
        lambda lk: lk.__setitem__("rx", {"nf_db": 2.5}),  # 缺 g_dbi
        lambda lk: lk.__setitem__("rx", {"g_dbi": 40.0, "nf_db": -1.0}),
        lambda lk: lk.__setitem__("bw_hz", 0.0),
        lambda lk: lk.__setitem__("rb_bps", -1.0),
        lambda lk: lk.__setitem__("path", {"elevation_deg": 30.0}),  # 缺 alt
        lambda lk: lk.__setitem__("path", {"doppler_direction": "up"}),
        lambda lk: lk.__setitem__("bogus_key", 1),  # 未知键显式报错
        lambda lk: lk["tx"].__setitem__("bogus", 1),
        lambda lk: lk["path"].__setitem__("bogus", 1),
        lambda lk: lk["rx"].__setitem__("bogus", 1),
    ],
)
def test_domain_guards_valueerror(mutate):
    link = _base_link()
    mutate(link)
    with pytest.raises(ValueError):
        sat_link_budget(link)


def test_geometry_missing_valueerror():
    link = _base_link()
    link["path"] = {}
    with pytest.raises(ValueError, match="几何缺失"):
        sat_link_budget(link)


def test_link_not_dict_valueerror():
    for bad in (None, "x", 42, [1, 2]):
        with pytest.raises(ValueError):
            sat_link_budget(bad)


def test_missing_tx_or_rx_valueerror():
    with pytest.raises(ValueError, match="tx"):
        sat_link_budget({"rx": {"g_dbi": 40.0, "nf_db": 2.5}})
    # 几何先于 rx 校验（载波链装配序）；带齐几何才能触达 rx 缺失
    with pytest.raises(ValueError, match="rx"):
        sat_link_budget({"tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
                         "path": {"slant_km": 40000.0}})


# ─── 注册路径通用冒烟（service 出口契约；G15 全键面在 physics_invariants）────


def test_service_ok_false_on_bad_input():
    out = run_calculator("sat_link_budget", {"link": {"tx": {}}})
    assert out["ok"] is False and out.get("error")
    out2 = run_calculator("sat_link_budget", {})
    assert out2["ok"] is False and "缺少必需参数" in out2["error"]
