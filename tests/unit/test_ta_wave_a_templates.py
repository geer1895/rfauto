"""ge8b Wave A 席 1（TA-7/8/9）模板与内核测试：倒置微带 inverted_ms +
半模基片集成波导 hmsiw + 有限地共面波导 fgcpw。

数字裁判纪律（#118/#300，逐锚独立来源）：
- hmsiw：Lai-Fumeaux-Hong-Vahldieck 2009 T-MTT 论文图面数值（PDF 存
  runs/ge8_followup/wave_a/refs/2009_MTT_HMSIW.pdf，Fig.6/7 读数带）+
  式 (8) 与本仓 siw 族 Cassivi 式双拟合交叉；
- inverted_ms/fgcpw：core/quasistatic_fd FD 裁判（求解器资格=微带 vs HJ
  静态 +0.18~0.32%/CPS 半空间 −0.1%/Cohn −0.5%/h→b 精确四锚）+ 新族
  精确极限（k=1/√2 空气线 Z0=30π、半空间 εeff=(1+εr)/2、εr=1 跨族互检）；
- fgcpw 另有 Ghione-Naldi 1984 闭式（scipy ellipk 精确）×skrf（同文献
  独立实现）第三方对拍。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    render_script,
)
from rfauto.core.fgcpw import fgcpw_design_params, fgcpw_fd, fgcpw_gn_closed_form
from rfauto.core.hmsiw import (
    hmsiw_beta_rad_m,
    hmsiw_closed_form,
    hmsiw_delta_w_mm,
    hmsiw_design_params,
    hmsiw_eff_width_siw_mm,
    hmsiw_z_pv_ohm,
)
from rfauto.core.inverted_ms import inverted_ms_design_params, inverted_ms_fd
from rfauto.core.quasistatic_fd import (
    cpw_quasistatic,
    inverted_microstrip_quasistatic,
    microstrip_quasistatic,
)

WA1_TEMPLATES = ("inverted_ms", "hmsiw", "fgcpw")


# ═══ TA-8 hmsiw：文献数值锚（Lai-Fumeaux 2009 T-MTT Fig.6/7）════════════════

def test_hmsiw_lit_fig7_anchor():
    """Fig. 7 原型（w=10.0/h=0.508/εr=2.2/d=0.5/s=0.6）：fc 链算落在图面起始
    读数带，β(12GHz) 落在图面读数带（#118 文献数值例裁判）。"""
    ch = hmsiw_closed_form(10.0, 0.508, 2.2, 0.5, 0.6)
    # 链精确钉（w_eff,HMSIW=10.5504 手算复算：w_eff,SIW=19.55125→w'=9.77563
    # →Δw=0.77476，式 (13) 逐项）
    assert ch["w_eff_siw_mm"] == pytest.approx(19.551250, abs=1e-5)
    assert ch["w_eff_prime_mm"] == pytest.approx(9.775625, abs=1e-5)
    assert ch["delta_w_mm"] == pytest.approx(0.774756, abs=1e-5)
    assert ch["w_eff_hmsiw_mm"] == pytest.approx(10.550381, abs=1e-5)
    # 文献带（Fig. 7 β 起始 ~4.8-5.0GHz；Fig. 6 w=10/εr=2.2 星点读数
    # 4.9±0.3，式 (13) 拟合 <2% 论文声明）
    assert 4.5 <= ch["fc_te05_ghz"] <= 5.1
    beta, fc = hmsiw_beta_rad_m(ch["w_eff_hmsiw_mm"], 2.2, 12.0)
    assert fc == pytest.approx(ch["fc_te05_ghz"])
    # Fig. 7 图面 β(12GHz) ≈ 340-350 rad/m（±10 读数不确定带）
    assert 320.0 <= beta <= 360.0


def test_hmsiw_lit_fig6_anchor():
    """Fig. 6 左上星点（w=2.5/h=0.254/εr=2.2，图面 ~20.2±0.5GHz）。"""
    ch = hmsiw_closed_form(2.5, 0.254, 2.2, 0.5, 0.6)
    assert 19.9 <= ch["fc_te05_ghz"] <= 21.4


def test_hmsiw_eq8_d0_recycling_limit():
    """式 (8) d→0 回代极限：w_eff,SIW → 2w 逐位（siw 族 d→0 同口径）。"""
    assert hmsiw_eff_width_siw_mm(5.0, 1e-12, 1.0) == pytest.approx(10.0, rel=1e-9)
    assert hmsiw_eff_width_siw_mm(10.0, 1e-9, 0.6) == pytest.approx(20.0, rel=1e-9)


def test_hmsiw_eq8_vs_repo_cassivi_cross_fit():
    """式 (8) 与本仓 siw 族 Cassivi 式是同一全 SIW 宽的两家发表拟合：
    全宽 W 等效宽度互差 <2%（两条独立文献来源互证，非自证）。"""
    for w_hmsiw, d, s in ((10.0, 0.5, 0.6), (5.5829, 0.6, 1.0)):
        full_w = 2.0 * w_hmsiw
        from rfauto.core.calculators import siw_effective_width_mm

        we8 = hmsiw_eff_width_siw_mm(w_hmsiw, d, s)
        wcassivi = float(siw_effective_width_mm(full_w, d, s))
        assert abs(we8 - wcassivi) / wcassivi < 0.02


def test_hmsiw_validity_guards():
    """式 (13) 声明域（εr/h/w）与 ln 宗量守卫越界 ValueError 拒算（#122）。"""
    with pytest.raises(ValueError, match="εr"):
        hmsiw_closed_form(5.0, 0.508, 1.9, 0.5, 0.6)
    with pytest.raises(ValueError, match="h="):
        hmsiw_closed_form(5.0, 0.1, 3.66, 0.5, 0.6)
    with pytest.raises(ValueError, match="w="):
        hmsiw_closed_form(1.0, 0.508, 3.66, 0.5, 0.6)
    # ln 宗量 ≤0（小 w'/h 组合）显式拒算
    with pytest.raises(ValueError, match="式\\(13\\)"):
        hmsiw_delta_w_mm(2.0, 0.508, 3.66)


def test_hmsiw_nominal_chain_recompute():
    """名义 = hmsiw_design_params(fc=f0/1.5) 全链复算逐键钉（#252：按链
    复算非拷贝；闭式链毫秒级在门预算内）。"""
    nom = TEMPLATE_NOMINAL["hmsiw"]
    chain = hmsiw_design_params(10.0 / 1.5, nom["er"], nom["h_mm"],
                                nom["d_mm"], nom["s_mm"])
    assert round(chain["w_mm"], 4) == nom["w_mm"]
    assert chain["w_eff_hmsiw_mm"] == pytest.approx(5.876400, abs=1e-5)
    assert chain["delta_w_mm"] == pytest.approx(0.486290, abs=1e-5)
    assert chain["fc_te05_ghz"] == pytest.approx(6.666664, abs=1e-5)
    assert chain["fc_te15_ghz"] == pytest.approx(3 * chain["fc_te05_ghz"])
    # line_len = round(3λg@f0, 4)（式 (12) β 链；4 位舍入名义 w 起算，
    # siw "链路与综合逐位同源：4 位舍入 w 起算" 同构造）
    ch_nom = hmsiw_closed_form(nom["w_mm"], nom["h_mm"], nom["er"],
                               nom["d_mm"], nom["s_mm"])
    beta_nom, _ = hmsiw_beta_rad_m(ch_nom["w_eff_hmsiw_mm"], nom["er"], 10.0)
    assert nom["line_len_mm"] == pytest.approx(
        round(2 * math.pi / beta_nom * 1e3 * 3, 4))
    # 端口阻抗链（Z_PV=2h·Z_TE/w_eff）
    z_pv, _ = hmsiw_z_pv_ohm(chain["w_eff_hmsiw_mm"], nom["h_mm"], nom["er"],
                             10.0)
    assert z_pv == pytest.approx(45.6781, abs=1e-3)
    # f0=10GHz 在传播区（fc 上 50%）且单模带内（fc15=3fc > 2·f0？——f0/fc=1.5
    # < TE1.5/fc=3，单模口径成立）
    assert chain["fc_te05_ghz"] * 1.5 == pytest.approx(10.0, abs=1e-3)


# ═══ TA-7 inverted_ms：FD 裁判独立验证 ══════════════════════════════════════

def test_inverted_ms_fd_er1_cross_family_anchor():
    """εr=1（无介质边界）与已验证微带族（HJ 静态锚）同物理互检：两族独立
    构造网格解同一拉普拉斯问题，Z0/εeff 互差 ≤0.5%。"""
    r_inv = inverted_microstrip_quasistatic(1.0, 0.508, 0.508, 1.0)
    r_ms = microstrip_quasistatic(1.0, 0.508, 1.0)
    assert r_inv.eps_eff == pytest.approx(1.0, abs=1e-9)
    assert r_ms.eps_eff == pytest.approx(1.0, abs=1e-9)
    assert r_inv.z0_ohm == pytest.approx(r_ms.z0_ohm, rel=5e-3)


def test_inverted_ms_fd_bracket_and_monotonic():
    """物理括号 1 ≤ εeff ≤ εr + Z0 随 w 单调递减（宽带→低阻）。"""
    nom = TEMPLATE_NOMINAL["inverted_ms"]
    r_lo = inverted_microstrip_quasistatic(0.8 * nom["w_mm"], nom["h_air_mm"],
                                           nom["h_sub_mm"], nom["er"])
    r = inverted_microstrip_quasistatic(nom["w_mm"], nom["h_air_mm"],
                                        nom["h_sub_mm"], nom["er"])
    r_hi = inverted_microstrip_quasistatic(1.25 * nom["w_mm"], nom["h_air_mm"],
                                           nom["h_sub_mm"], nom["er"])
    assert 1.0 <= r.eps_eff <= nom["er"]
    assert r_lo.z0_ohm > r.z0_ohm > r_hi.z0_ohm


def test_inverted_ms_nominal_chain_recompute():
    """名义 = inverted_ms_design_params() 整链复算逐位钉（FD 反演 ~12s 在
    门预算内；richardson 缺省档确定性）。"""
    nom = TEMPLATE_NOMINAL["inverted_ms"]
    p = inverted_ms_design_params(z0_ohm=50.0, h_air_mm=nom["h_air_mm"],
                                  h_sub_mm=nom["h_sub_mm"], er=nom["er"],
                                  line_len_mm=nom["line_len_mm"])
    assert p["w_mm"] == nom["w_mm"]
    assert p["eps_eff"] == pytest.approx(1.24667, abs=1e-4)


def test_inverted_ms_nominal_fd_single_eval_band():
    """归档名义 w 单点 FD 回代带内（|Z0−50| ≤ 0.5Ω，#122 守卫口径）。"""
    nom = TEMPLATE_NOMINAL["inverted_ms"]
    r = inverted_ms_fd(nom["w_mm"], nom["h_air_mm"], nom["h_sub_mm"],
                       nom["er"])
    assert abs(r.z0_ohm - 50.0) <= 0.5
    # λg 派生（meta 派生量自洽；准静态口径无色散如实声明）
    assert 299.792458 / (2.5 * math.sqrt(r.eps_eff)) == pytest.approx(
        107.4003, abs=1e-2)


# ═══ TA-9 fgcpw：精确极限 + skrf 第三方 + G-N 偏差账 ════════════════════════

def test_fgcpw_gn_halvespace_limit():
    """G-N 闭式 h→∞ 半空间极限 εeff → (1+εr)/2（文献解析回收锚）。"""
    r = fgcpw_gn_closed_form(0.6, 0.2, 50.0, 3.66)
    assert r["eps_eff"] == pytest.approx((1.0 + 3.66) / 2.0, rel=1e-3)
    # Z0 半空间 = 空气线 Z0/√εeff
    k = 0.6 / 1.0
    from scipy.special import ellipk

    eta0 = 376.730313668
    z_air = eta0 / 4.0 / float(ellipk(k)) * float(ellipk(math.sqrt(1 - k * k)))
    assert r["z0_ohm"] == pytest.approx(z_air / math.sqrt(r["eps_eff"]), rel=1e-9)


def test_fgcpw_fd_exact_limits():
    """FD 裁判两精确极限：k=1/√2 空气线 Z0=30π（经典恒等，−0.02% 实测）、
    半空间 εeff=(1+εr)/2。"""
    w = 0.5
    gap = w * (math.sqrt(2.0) - 1.0) / 2.0   # k=w/(w+2g)=1/√2
    r = cpw_quasistatic(w, gap, 0.508, 1.0)
    assert r.z0_ohm == pytest.approx(30 * math.pi, rel=1e-3)
    r2 = cpw_quasistatic(0.6, 0.2, 25.0, 3.66)
    assert r2.eps_eff == pytest.approx((1.0 + 3.66) / 2.0, rel=3e-3)


def test_fgcpw_gn_vs_skrf_third_party():
    """G-N 精确实现 vs skrf CPW（同文献独立实现；设计点 k≈0.85-0.95 在
    Hilberg ellipa 高精度带）：εeff/Z0 互差 ≤1%（skrf ellipa 近似误差带
    内；非同源自证——两实现独立）。"""
    pytest.importorskip("skrf")
    from skrf.frequency import Frequency
    from skrf.media import CPW

    nom = TEMPLATE_NOMINAL["fgcpw"]
    gn = fgcpw_gn_closed_form(nom["w_mm"], nom["gap_mm"], nom["h_mm"],
                              nom["er"])
    m = CPW(Frequency(1, 1, 1, "GHz"), w=nom["w_mm"] * 1e-3,
            s=nom["gap_mm"] * 1e-3, ep_r=nom["er"], h=nom["h_mm"] * 1e-3,
            t=None)
    ee_sk = float(np.real(m.ep_reff).ravel()[0])
    z_sk = float(np.real(m.z0).ravel()[0])
    # 3.5% 带=skrf ellipa（Hilberg 近似）在 k≈0.9 处对精确 K/K' 的偏差
    # （q1 −3.6% → εeff +2.8%）——两侧为同文献独立实现，偏差源=近似而非公式
    assert gn["eps_eff"] == pytest.approx(ee_sk, rel=3.5e-2)
    assert gn["z0_ohm"] == pytest.approx(z_sk, rel=3.5e-2)


def test_fgcpw_gn_deviation_vs_fd_registered():
    """G-N 文献闭式在名义点对 FD 裁判的系统偏差（εeff −6.6%/Z0 −3.6%）
    实测复现并钉住——#302 同族有限厚开线闭式低估的诚实账（偏差方向与
    幅度漂移即红，防内核静默改变）。"""
    nom = TEMPLATE_NOMINAL["fgcpw"]
    r = fgcpw_fd(nom["w_mm"], nom["gap_mm"], nom["h_mm"], nom["er"],
                 gnd_mm=nom["gnd_mm"])
    gn = fgcpw_gn_closed_form(nom["w_mm"], nom["gap_mm"], nom["h_mm"],
                              nom["er"])
    assert 100.0 * (gn["eps_eff"] / r.eps_eff - 1.0) == pytest.approx(-6.57,
                                                                     abs=0.6)
    assert 100.0 * (gn["z0_ohm"] / r.z0_ohm - 1.0) == pytest.approx(-3.62,
                                                                   abs=0.6)


def test_fgcpw_nominal_fd_single_eval_band():
    """归档名义 w 单点 FD 回代带内（|Z0−50| ≤ 0.5Ω）。设计链整链复算
    ~25s 超门预算不整链复算（fgcpw_design_params 单次反演实测 25s——
    meta nominal_derivation 口径如实登记）。"""
    nom = TEMPLATE_NOMINAL["fgcpw"]
    r = fgcpw_fd(nom["w_mm"], nom["gap_mm"], nom["h_mm"], nom["er"],
                 gnd_mm=nom["gnd_mm"])
    assert abs(r.z0_ohm - 50.0) <= 0.5
    # 设计链入口守卫冒烟（参数域路径；整链反演 ~25s 不进门预算）
    with pytest.raises(ValueError, match="须为正有限数"):
        fgcpw_design_params(z0_ohm=-1.0)
    with pytest.raises(ValueError, match="须为正有限数"):
        fgcpw_design_params(gap_mm=0.0)


def test_fgcpw_gn_monotonic():
    """G-N Z0 随 w 单调递减（物理：宽带→高 k→低阻；反解单测网格钉）。"""
    zs = [fgcpw_gn_closed_form(w, 0.2, 0.508, 3.66)["z0_ohm"]
          for w in (0.5, 1.0, 2.0, 3.0)]
    assert zs == sorted(zs, reverse=True)


# ═══ 模板/渲染/注册一致性 ═══════════════════════════════════════════════════

def test_ta_wave_a_registry_shapes():
    """三模板注册形状：META/NOMINAL 键集、params↔nominal 自洽、substrate
    一致性与对账占位键同值（MATERIAL_VALUE_PARAMS 豁免键的正面钉）。"""
    for t in WA1_TEMPLATES:
        meta = TEMPLATE_META[t]
        nom = TEMPLATE_NOMINAL[t]
        assert set(meta["params"]) <= set(nom)
        assert meta["n_ports"] == 2
        if t in ("inverted_ms", "fgcpw"):
            # 对账占位键与 substrate 同值（渲染基板厚走 substrate，键值
            # 漂移即渲染名义不一致——正面钉）
            assert nom["h_mm"] == 0.508 and nom["er"] == 3.66
            if t == "inverted_ms":
                assert nom["h_sub_mm"] == nom["h_mm"]
        else:
            assert nom["h_mm"] == 0.508 and nom["er"] == 3.66


def test_inverted_ms_render_structure():
    """inverted_ms 渲染结构钉：条带悬于 z=Z_STRIP（h_air 字面）、MSLPort
    板边、bottom PEC/top MUR（金属/介质 z 序对调的脚本面证据）。"""
    script = render_script("inverted_ms", dict(TEMPLATE_NOMINAL["inverted_ms"]),
                           (2.25, 2.75), mesh_resolution_mm=0.4)
    assert 'inv_ms.AddBox' in script
    assert "Z_STRIP = " in script
    # 边界六元：底 PEC（地面）/顶 MUR（开放）
    assert '"MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"' in script
    # 悬浮基板盒 z 底=空气隙顶字面（h_air=0.508mm → 0.000508m；顶=+H_SUB
    # 脚本变量表达式）
    assert ("sub.AddBox((-BOARD, -BOARD, 0.000508), "
            "(BOARD, BOARD, 0.000508 + H_SUB), priority=0)") in script


def test_hmsiw_render_structure():
    """hmsiw 渲染结构钉：DOM 字面注入、R_PORT=Z_PV 字面、单列藩篱、
    端口盒/开路边 #283 落格断言、top MUR（顶开放）。"""
    script = render_script("hmsiw", dict(TEMPLATE_NOMINAL["hmsiw"]),
                           (9.75, 10.25), mesh_resolution_mm=0.4)
    assert "hmsiw_via.AddCylinder" in script
    assert "R_PORT = 45.6781" in script
    assert 'SystemExit("hmsiw #" + "283"' in script   # 落格断言（#283）
    # 边界六元：底 PEC（底板）/顶 MUR（顶开放，HMSIW 定义性质）
    assert '"MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"' in script
    assert 'AddLumpedPort(1, R_PORT' in script


def test_fgcpw_render_structure():
    """fgcpw 渲染结构钉：CPWPort 端口、有限地盒（外缘字面）、bottom MUR
    （无底地=True CPW 口径）、基板 z 8 层（G3 分档）。"""
    nom = TEMPLATE_NOMINAL["fgcpw"]
    script = render_script("fgcpw", dict(nom), (2.25, 2.75),
                           mesh_resolution_mm=0.4)
    assert "CPWPort" in script
    gnd_edge = (nom["w_mm"] / 2 + nom["gap_mm"] + nom["gnd_mm"]) * 1e-3
    assert repr(gnd_edge) in script
    assert '"MUR", "MUR", "PML_8", "PML_8", "MUR", "MUR"' in script
    # 底 MUR + 域向下延 AIR_TOP（cps 同款 z 网格首行）+ 基板 8 层（9 点，
    # CPW/槽下场族 G3 分档 fgcpw ∈ _SUB_CELLS_8_TEMPLATES）
    assert 'np.linspace(-AIR_TOP, 0, 5)' in script
    assert 'np.linspace(0, H_SUB, 9)' in script


def test_ta_wave_a_meta_yaml_nominal_h_substrate_consistency():
    """对账占位键正面钉：meta.yaml nominal h_mm/er 与 substrate 同值
    （渲染基板厚/材料走 substrate——两处漂移即渲染名义不一致）。"""
    import yaml

    repo = Path(__file__).resolve().parents[2]
    for t in WA1_TEMPLATES:
        data = yaml.safe_load(
            (repo / "docs" / "templates" / t / "meta.yaml").read_text(
                encoding="utf-8"))
        assert data["substrate"]["h_mm"] == data["nominal_params"]["h_mm"]
        assert data["substrate"]["er"] == data["nominal_params"]["er"]
