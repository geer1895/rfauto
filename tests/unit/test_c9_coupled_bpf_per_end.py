"""C9：coupled_bpf 中谐振器逐端 Δl 二阶残差闭合（2026-09-21 复核批）。

登记语境（0-P2 余项③，已落地面）：
各谐振器两开路端 Δl 依赖该端自身线宽（Hammerstad/Pozar eq.4.23），统一 Δl
口径下 res2 残差 6.465µm/182ppm（r_2 声明 35.5107 vs 逐端 35.5042mm）。
本文件钉四件事（与 test_coupled_bpf_template.py 互补，不重复其钉值面）：
① 逐端 vs 统一的段长差向量闭式结构（±(Δl(w1)−Δl(w0))/2，Σdiff=0）；
② 电路级往返 uniform vs per-end（带内 RL 改善方向 + 二阶幅度契约）；
③ NOMINAL 再生一致性（design round4→NOMINAL→docs meta.yaml 三方同值）；
④ #118 合成回收钉（已知 Δl 注入→阶梯解回收）+ 四通道同源
   （design opt-in 键/layout 累积栅格/fake 派生/judge 见键消费）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot

F0 = 2.5
FBW = 0.05
RL_DB = 20.0
NOMINAL = dict(ot.COUPLED_BPF_NOMINAL)
DESIGN = ot.coupled_bpf_design_from_order(3, F0, FBW, RL_DB,
                                          with_section_lengths=True)
FREQS = np.linspace(2.0, 3.0, 1001)
BAND = (FREQS >= F0 * (1 - FBW / 2)) & (FREQS <= F0 * (1 + FBW / 2))


def _design_uniform(design: dict) -> dict:
    return {k: v for k, v in design.items() if k != "section_len_mm"}


# ─── ① 逐端 vs 统一：段长差向量闭式结构 ─────────────────────────────────────

def test_per_end_vs_uniform_difference_vector():
    """N=3 对称设计的差向量闭式：L=[+d,−d,−d,+d]，d=(Δl(w1)−Δl(w0))/2。

    阶梯解（规范 L_0=L_N）在 r_1=r_3=res_len、r_2=res_len−(dl1−dl0) 下
    解析给出 L_0=L_3=res_len/2+(dl1−dl0)/2、L_1=L_2=res_len/2−(dl1−dl0)/2；
    Σdiff=0 逐位成立（阵列总高不变 ⇒ feed_len 不变）。
    """
    widths = NOMINAL["widths_mm"]
    res_len = NOMINAL["res_len_mm"]
    lens = ot._coupled_bpf_section_lengths_mm(widths, res_len, F0)
    dl0 = ot._open_end_delta_mm(widths[0], F0)
    dl1 = ot._open_end_delta_mm(widths[1], F0)
    d_half = (dl1 - dl0) / 2.0
    expect = [res_len / 2.0 + d_half, res_len / 2.0 - d_half,
              res_len / 2.0 - d_half, res_len / 2.0 + d_half]
    assert lens == pytest.approx(expect, rel=1e-12)
    diff = [b - res_len / 2.0 for b in lens]
    assert sum(diff) == pytest.approx(0.0, abs=1e-15)
    assert diff[0] * 1e3 == pytest.approx(3.2324, abs=0.01)      # µm
    # 中谐振器物理长残差（登记语义）：r_2^per-end − r_2^uniform
    r2_fix = (lens[1] + lens[2]) - res_len
    assert r2_fix == pytest.approx(-(dl1 - dl0), rel=1e-12)
    assert r2_fix * 1e3 == pytest.approx(-6.4648, abs=0.01)      # µm
    assert r2_fix / res_len * 1e6 == pytest.approx(-182.05, abs=0.5)  # ppm


# ─── ② 电路级往返：uniform vs per-end（2026-09-21 离线实测）────────────────

def test_circuit_roundtrip_per_end_vs_uniform():
    """综合→电路裁判往返：逐端修正是二阶（带内 max|ΔS21|=0.0106dB<0.05 门）
    且方向确定（res2 去失谐 ⇒ 带内 RL 12.9224→13.1065dB 改善）。"""
    s_uni = ot.coupled_bpf_circuit_sparams(FREQS, _design_uniform(DESIGN))
    s_per = ot.coupled_bpf_circuit_sparams(FREQS, DESIGN)
    d21 = (20 * np.log10(np.abs(s_per[:, 1, 0]) + 1e-300)
           - 20 * np.log10(np.abs(s_uni[:, 1, 0]) + 1e-300))
    assert float(np.max(np.abs(d21[BAND]))) < 0.05          # 二阶门
    assert float(np.max(np.abs(d21[BAND]))) == pytest.approx(
        0.0106, abs=5e-4)                                   # 实测钉
    rl_u = -20.0 * float(np.log10(np.max(np.abs(s_uni[BAND, 0, 0]))))
    rl_p = -20.0 * float(np.log10(np.max(np.abs(s_per[BAND, 0, 0]))))
    assert rl_u == pytest.approx(12.9224, abs=0.01)
    assert rl_p == pytest.approx(13.1065, abs=0.01)
    assert rl_p > rl_u                                      # 方向：改善
    # 带宽二阶不动（25kHz 栅格插值 |ΔBW|<0.05MHz）；带心偏移有界非零
    def _m3bw(s):
        s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
        return float(FREQS[s21 > -3.0].max() - FREQS[s21 > -3.0].min())

    assert abs(_m3bw(s_per) - _m3bw(s_uni)) < 5e-2
    i0 = int(np.argmin(np.abs(FREQS - F0)))
    assert 20 * np.log10(abs(s_per[i0, 1, 0])) > 20 * np.log10(
        abs(s_uni[i0, 1, 0])) - 0.05


# ─── ③ NOMINAL 再生一致性（design → NOMINAL → docs meta.yaml 三方同值）─────

def test_nominal_regeneration_and_meta_sync():
    """NOMINAL=design(3,2.5,0.05,20) 的 4 位舍入；docs meta.yaml 同值
    （#304 消费者：test_template_meta_consistency 同口径的数值半边）。"""
    assert round(DESIGN["res_len_mm"], 4) == NOMINAL["res_len_mm"]
    assert round(DESIGN["feed_len_mm"], 4) == NOMINAL["feed_len_mm"]
    assert round(DESIGN["w_feed_mm"], 4) == NOMINAL["w_feed_mm"]
    assert [round(s["w_mm"], 4) for s in DESIGN["sections"]] \
        == list(NOMINAL["widths_mm"])
    assert [round(s["s_mm"], 4) for s in DESIGN["sections"]] \
        == list(NOMINAL["gaps_mm"])
    # 逐端段长钉值 + ΣL=2·res_len（精确 res_len 口径）⇒ feed=60−ΣL/2
    assert [round(v, 4) for v in DESIGN["section_len_mm"]] == [
        17.7586, 17.7521, 17.7521, 17.7586]
    assert sum(DESIGN["section_len_mm"]) == pytest.approx(
        2.0 * DESIGN["res_len_mm"], rel=1e-12)
    import yaml

    meta = yaml.safe_load(
        (REPO / "docs" / "templates" / "coupled_bpf" / "meta.yaml")
        .read_text(encoding="utf-8"))
    assert meta["nominal_params"] == dict(NOMINAL)


# ─── ④ #118 合成回收钉：已知 Δl 注入 → 阶梯解回收 ──────────────────────────

def test_synthetic_delta_l_recovery_pin(monkeypatch):
    """合成已知量注入→回收（#118）：钉死 Δl 表后 helper 的阶梯解必须精确
    回收 r_i=res_len+Δl(w0)+Δl(w1)−Δl(w[i−1])−Δl(w[i]) 与 res2 修量。"""
    widths = list(NOMINAL["widths_mm"])
    res_len = NOMINAL["res_len_mm"]
    dl_tab = {0.8952: 0.2000, 1.0956: 0.2065}          # 已知注入（mm）

    def fake_dl(w_mm, freq_ghz, er=3.66, h_mm=0.508):
        return dl_tab[round(float(w_mm), 4)]

    monkeypatch.setattr(ot, "_open_end_delta_mm", fake_dl)
    lens = ot._coupled_bpf_section_lengths_mm(widths, res_len, F0)
    dl_end, dl_mid = dl_tab[0.8952], dl_tab[1.0956]
    r_exp = [res_len + dl_end + dl_mid
             - dl_tab[round(widths[i - 1], 4)]
             - dl_tab[round(widths[i], 4)] for i in range(1, 4)]
    got = [lens[i - 1] + lens[i] for i in range(1, 4)]
    assert got == pytest.approx(r_exp, rel=1e-12)
    # res2 修量回收 = 已知量差（非零注入 ⇒ 非平凡回收）
    assert (got[1] - got[0]) == pytest.approx(
        -(dl_tab[1.0956] - dl_tab[0.8952]), rel=1e-12)
    assert round((got[1] - got[0]) * 1e3, 6) == -6.5
    # 规范自由度 L_0=L_N（奇 N）在合成域同样成立
    assert lens[0] == pytest.approx(lens[-1], rel=1e-12)
    assert sum(lens) == pytest.approx(2.0 * res_len, rel=1e-12)
    # 守卫面不受 monkeypatch 影响
    with pytest.raises(ValueError):
        ot._coupled_bpf_section_lengths_mm([0.9], 35.0)
    with pytest.raises(ValueError):
        ot._coupled_bpf_section_lengths_mm([0.9, 1.1], 0.0)


# ─── ⑤ 四通道同源：design opt-in 键 / layout 栅格 / fake 派生 / judge 消费 ──

def test_four_channel_same_source():
    """同源 helper 单源派生：layout lens（m）逐位=helper；fake 响应=judge
    逐端口径（同 NOMINAL 几何构造）且 ≠ 均匀口径（fake 走逐端路径实证）。"""
    from rfauto.adapters.fake_adapter import _coupled_bpf_sparams

    lens_ref = ot._coupled_bpf_section_lengths_mm(
        NOMINAL["widths_mm"], NOMINAL["res_len_mm"], F0)
    lay = ot._coupled_bpf_layout(dict(NOMINAL))
    assert [v * 1e3 for v in lay["lens"]] == pytest.approx(lens_ref, rel=1e-12)
    assert DESIGN["section_len_mm"] == pytest.approx(
        ot._coupled_bpf_section_lengths_mm(
            [s["w_mm"] for s in DESIGN["sections"]], DESIGN["res_len_mm"], F0),
        rel=1e-12)
    # fake 通道：与"同 NOMINAL 几何 + helper 段长"的 judge 逐位一致
    sections = []
    for w, s in zip(NOMINAL["widths_mm"], NOMINAL["gaps_mm"], strict=True):
        ze, zo, ere_e, ere_o = ot.coupled_microstrip_even_odd_ohm(w, s, F0)
        sections.append({"zee_ohm": ze, "zoo_ohm": zo,
                         "ere_e": ere_e, "ere_o": ere_o})
    d_geo = {"order": 3, "f0_ghz": F0,
             "feed_len_mm": NOMINAL["feed_len_mm"], "sections": sections,
             "section_len_mm": lens_ref}
    s_fake = _coupled_bpf_sparams(FREQS, NOMINAL["widths_mm"],
                                  NOMINAL["gaps_mm"], NOMINAL["res_len_mm"],
                                  NOMINAL["feed_len_mm"], f0_ghz=F0)
    s_judge = ot.coupled_bpf_circuit_sparams(FREQS, d_geo)
    assert np.allclose(s_fake, s_judge, rtol=0, atol=1e-12)
    s_uni = ot.coupled_bpf_circuit_sparams(
        FREQS, dict(d_geo, section_len_mm=None, lc_mm=NOMINAL["res_len_mm"]
                    / 2.0))
    assert not np.allclose(s_fake, s_uni, rtol=0, atol=1e-9)


def test_optin_key_contract_unchanged():
    """opt-in 契约（topology_service 锚零）复核：缺省不带键、带键值=helper。"""
    d = ot.coupled_bpf_design_from_order(3, F0, FBW, RL_DB)
    assert "section_len_mm" not in d
    assert ot.coupled_bpf_circuit_sparams(FREQS, d).__class__ is np.ndarray
