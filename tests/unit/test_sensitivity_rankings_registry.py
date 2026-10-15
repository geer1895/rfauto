"""X7 敏感性排序登记表单测（knowledge/sensitivity_rankings.yaml 数据面）。

口径（全确定性、离线、零真机）：
- 登记表过 W8 消费链：capability_cards_export.load_sensitivity_rankings
  （真实路径装载）+ normalize_sensitivity_entry 逐条 PASS + 三态
  resolve_sensitivity computed 胜出（provenance 数据指针）；
- 入表集=COMPUTABLE_TEMPLATES（46 = X7 首批 18 + aurora72 A3-D 扩批 22 +
  R8-KN 扩批 4：diplexer/schiffman/msl_cpw/msl_siw_taper + aurora_d
  SENS-ANC 复核扩批 2：varactor_bpf/xcheb_bpf4；
  teaching 首批 9 模板不入表=test_w6_sensitivity_face_non_regression 的钉
  前提 + 回退卡代表（ring_resonator）维持无条目；aurora72 批起新 teaching
  卡与登记表双源并存，W8 消费优先级 computed>teaching）；
- schema 面：ranking 参数集==模板注册名义参数（TEMPLATE_NOMINAL 单源）、
  分数有限非负、R9 序（-score, param）、n_samples=1+2·n_params、
  method/source_run/registered_at 在场；
- 生成器面：弹性管线已知值（线性=1/平方=2）、整数参数 ±1 单位步、
  非正目标量显式拒收（禁 emit 坏数据）、build_all 两次逐位一致且与
  落档文件逐字节一致（生成器↔登记表一致性钉）；
- 微波物理 sanity 钉（每钉旁注物理依据，与文献直觉冲突即停下核公式）：
  谐振长度族弹性=1、基元线宽 Z0 弹性 HJ 域 ~0.6、via 对数比值弹性
  =1/ln(r_pad/r_via)、atten E4 通道与 Z0 通道分解、SIR/悬置带线族序。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import capability_cards_export as cce
import sensitivity_rankings_build as srb

REGISTRY_PATH = cce.SENSITIVITY_PATH


def _load() -> dict:
    return cce.load_sensitivity_rankings(REGISTRY_PATH)


# ── 入表集与 W8 消费链 ───────────────────────────────────────────────────────

def test_registry_exists_and_matches_computable_set():
    """登记表在场、模板集==生成器可算集（46=X7 首批 18+A3-D 扩批 22
    +R8-KN 扩批 4+SENS-ANC 复核扩批 2，2026-10-14 计数钉按新值更新）。"""
    reg = _load()
    assert set(reg) == set(srb.COMPUTABLE_TEMPLATES)
    assert len(reg) == 46
    assert 35 <= len(reg) <= 50  # 任务书目标带（R8-KN 扩批后）


def test_registry_entries_pass_w8_normalize():
    """逐条过 W8 normalize（坏条目即红——数据面契约主验证）。"""
    reg = _load()
    for name, entry in reg.items():
        out = cce.normalize_sensitivity_entry(entry)
        assert out is not None, name
        ranks = [item["rank"] for item in out["ranking"]]
        assert ranks == list(range(1, len(ranks) + 1)), name
        # R9 序：分数非增（平局按参数名升序）
        keyed = [(-item["score"], item["param"]) for item in out["ranking"]]
        assert keyed == sorted(keyed), name
        assert out["method"] == srb.METHOD
        assert entry["source_run"] == srb.SOURCE_RUN
        assert entry["registered_at"] == srb.BATCH_DATE
        # 确定性口径：零随机
        assert entry["seed"] is None


def test_resolve_sensitivity_computed_wins_for_all_entries():
    """三态①：全条目经 resolve_sensitivity 出 computed+数据指针。"""
    reg = _load()
    for name, entry in reg.items():
        out = cce.resolve_sensitivity(entry, {})
        assert out is not None and out["source"] == "computed", name
        assert out["provenance"]["registry"] == cce.SENSITIVITY_REGISTRY_REL
        assert out["provenance"]["source_run"] == srb.SOURCE_RUN


def test_teaching_templates_excluded_from_registry():
    """teaching 9 模板不入表（W6 面不回归钉的前提钉）：wilkinson 走真实
    装载链仍出 teaching；回退卡代表 ring_resonator 仍无条目。"""
    reg = _load()
    assert not (set(reg) & srb.TEACHING_TEMPLATES)
    wil = cce.collect_card("wilkinson")
    assert wil["sensitivity"]["source"] == "teaching"
    assert "ring_resonator" not in reg


def test_ranking_params_match_template_nominal():
    """ranking 参数集==模板注册名义参数（TEMPLATE_NOMINAL 单源；每参数
    恰一次，禁臆造参数名）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    reg = _load()
    for name, entry in reg.items():
        params = [item["param"] for item in entry["ranking"]]
        assert len(params) == len(set(params)), name
        assert set(params) == set(TEMPLATE_NOMINAL[name]), name
        scores = [item["score"] for item in entry["ranking"]]
        for s in scores:
            assert isinstance(s, (int, float)) and not isinstance(s, bool)
            assert math.isfinite(s) and s >= 0.0, (name, s)


def test_n_samples_is_central_difference_count():
    """n_samples=1+2·n_params（名义点+每参数 ± 两点，中心差分口径）。"""
    reg = _load()
    for name, entry in reg.items():
        assert entry["n_samples"] == 1 + 2 * len(entry["ranking"]), name


# ── 生成器面（弹性管线+确定性）───────────────────────────────────────────────

def test_elasticity_known_values():
    """合成已知量回收（#118 族）：线性目标=1、平方目标=2。"""
    assert srb.elasticity(lambda p: p["x"], {"x": 3.0}, "x") == 1.0
    out = srb.elasticity(lambda p: p["x"] ** 2, {"x": 3.0}, "x")
    assert abs(out - 2.0) < 1e-9


def test_elasticity_integer_param_unit_step():
    """整数参数 ±1 单位步（非 ±1%）：y=x → 弹性仍 1。"""
    assert srb.elasticity(lambda p: p["n"], {"n": 5}, "n") == 1.0


def test_elasticity_rejects_bad_domain():
    """非正目标量/非数值参数显式拒收（禁 emit 坏数据，#316 多报方向）。"""
    import pytest

    with pytest.raises(ValueError, match="越正域"):
        srb.elasticity(lambda p: -abs(p["x"]) - 1.0, {"x": 1.0}, "x")
    with pytest.raises(TypeError):
        srb.elasticity(lambda p: 1.0, {"x": True}, "x")  # bool 显式拒收
    with pytest.raises(TypeError):
        srb.elasticity(lambda p: 1.0, {"x": "wide"}, "x")


def test_build_all_deterministic_and_matches_file():
    """build_all 两次逐位一致；render_yaml 与落档文件逐字节一致
    （生成器↔登记表一致性钉；登记表改动必须同批重跑生成器）。"""
    first = srb.build_all()
    second = srb.build_all()
    assert first == second
    assert srb.render_yaml(first) == REGISTRY_PATH.read_text(encoding="utf-8")


# ── 微波物理 sanity 钉（分数=|Δln y/Δln x|，无量纲弹性）────────────────────

def _scores(reg: dict, name: str) -> dict[str, float]:
    return {item["param"]: item["score"] for item in reg[name]["ranking"]}


def test_sanity_resonant_length_identity_one():
    """谐振长度族：λ/4、λ/2、λ0/4 设计式 |∂lnf0/∂lnL|=1（腔模型恒等式，
    同 teaching EP-5 口径）。"""
    reg = _load()
    for tpl, length_param in (
            ("gysel", "arm_len_mm"), ("coupled_line", "coupled_len_mm"),
            ("monopole", "mon_len_mm"), ("ifa", "ifa_arm_mm"),
            ("loop", "loop_side_mm"), ("pifa", "pifa_l_mm"),
            ("slot", "slot_l_mm"), ("stepped_impedance", "seg_len_mm"),
            ("nway_wilkinson", "arm_len_mm"),
            ("branchline_2sect", "sect_len_mm"),
            ("cline_coupler", "coupled_len_mm"),
            ("lange", "finger_len_mm"),
            ("ms_cross", "arm_len_mm"), ("ms_jcross", "slot_len_mm"),
            ("vivaldi_tsa", "w_mouth_mm")):
        assert _scores(reg, tpl)[length_param] == 1.0, tpl


def test_sanity_a3d_expansion_closed_chains():
    """aurora72 扩批闭式链 sanity 钉（每钉旁注物理依据，#118 纪律）。"""
    reg = _load()
    # siw：fc=c/(2·w_eff·√εr)、w_eff=w−d²/(0.95s)（Cassivi 反解正向）——
    # dw 弹性=w/w_eff 解析精确（1.032246…）、der=1/2（fc∝εr^−1/2 恒等式）
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    nom = TEMPLATE_NOMINAL["siw"]
    w_eff = nom["w_mm"] - nom["d_mm"] ** 2 / (0.95 * nom["s_mm"])
    assert abs(_scores(reg, "siw")["w_mm"] - nom["w_mm"] / w_eff) < 1e-5
    assert abs(_scores(reg, "siw")["er"] - 0.5) < 1e-6
    # 贴片族 λ/2 腔模型 f∝1/(px·√εeff(px))：εeff(px) 通道使弹性>1（HJ 域）
    assert _scores(reg, "ms_patch")["px_mm"] > 1.0
    assert _scores(reg, "ms_ring_patch")["patch_px_mm"] > 1.0
    # 单侧基板加载 εeff=(1+εr)/2（Luukkonen eq.3）：der=0.5·εr/(1+εr) 解析精确
    expected = 0.5 * 3.66 / (1.0 + 3.66)
    assert abs(_scores(reg, "ms_cross")["er"] - expected) < 1e-5
    assert abs(_scores(reg, "ms_jcross")["er"] - expected) < 1e-5
    # AMC LC 模型 L=μ0·h（Sievenpiper 过孔电感律）：dh 弹性=1/2 恒等式
    assert abs(_scores(reg, "ms_mushroom")["h_mm"] - 0.5) < 1e-6
    # coil_nfc：电流片式 L 的 n² 通道被 d_avg=(d_out−(n−1)(w+s)) 随 n 同变
    # 稀释（±1 整数步复合弹性 1.26，非纯 2.0）——钉"圈数通道强于 w/s 几何
    # 修正通道"的序关系，不钉解析精确值（复合式无闭式常值）
    scores_coil = _scores(reg, "coil_nfc")
    assert 1.0 < scores_coil["n_turns"] < 2.5
    assert scores_coil["n_turns"] > scores_coil["w_mm"]
    assert scores_coil["n_turns"] > scores_coil["s_mm"]


def test_sanity_r8kn_expansion_closed_chains():
    """R8-KN 扩批 +4 闭式链 sanity 钉（每钉旁注物理依据，#118 纪律）。"""
    reg = _load()
    # diplexer：一阶 CR 对偶 fc=Z0/(2πL)（diplexer_lpf_hpf element_values
    # 单源）——L 反比恒等式弹性=1 精确；HPF 臂 C=L/Z0² 对偶锁定同一 ωc
    # （非独立维=0）、w_feed 不进截止式=0
    scores_dip = _scores(reg, "diplexer")
    assert scores_dip["l_lpf_nh"] == 1.0
    assert scores_dip["c_hpf_pf"] == 0.0 and scores_dip["w_feed_mm"] == 0.0
    # schiffman：Δφ(f0)=β_ref·L_ref−Φ_c（内核相位链）——参考段长为 β_ref·
    # L_ref=Φ_c+90° 主控通道、耦合段 Φ_c 通道次之（ABCD 对 l 非线性无解析
    # 常值，只钉序关系）、w_ref 不进相位式=0（内核 v1 参考段 εeff 取偶/奇
    # 模相速平均口径）
    scores_sch = _scores(reg, "schiffman")
    assert scores_sch["l_ref_mm"] > scores_sch["l_coupled_mm"] > 1.0
    assert scores_sch["w_ref_mm"] == 0.0
    assert scores_sch["gap_mm"] > 0.0  # KJ εeff_e/o 通道在场
    # msl_siw_taper：与 siw 同链 Cassivi 截止——w 弹性=w/w_eff 解析精确
    # 1.032246…、der=1/2 恒等式、传输段长（taper/siw_len）与 h/tan_d 不进
    # 截止式=0
    scores_tap = _scores(reg, "msl_siw_taper")
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    nom_tap = TEMPLATE_NOMINAL["msl_siw_taper"]
    w_eff_tap = (nom_tap["w_mm"] - nom_tap["d_mm"] ** 2
                 / (0.95 * nom_tap["s_mm"]))
    assert abs(scores_tap["w_mm"] - nom_tap["w_mm"] / w_eff_tap) < 1e-5
    assert abs(scores_tap["er"] - 0.5) < 1e-6
    for zero_p in ("taper_len_mm", "siw_len_mm", "h_mm", "tan_d"):
        assert scores_tap[zero_p] == 0.0, zero_p
    # msl_cpw：CPWG 段 Z0（_cpwg_ri 单源）——窄缝域缝控电容量（cps 同族
    # 序）：gap 通道虽小于 w（k4 接地映射摊薄）但双双在场；微带段/版图量
    # 六参数不进 CPWG Z0 恒等式=0
    scores_cpw = _scores(reg, "msl_cpw")
    assert scores_cpw["w_cpw_mm"] > scores_cpw["gap_cpw_mm"] > 0.0
    for zero_p in ("w_msl_mm", "line_len_mm", "trans_len_mm", "r_via_mm",
                   "via_spacing_mm", "via_offset_mm"):
        assert scores_cpw[zero_p] == 0.0, zero_p


def test_sanity_sensanc_expansion_closed_chains():
    """SENS-ANC 复核扩批 +2 闭式链 sanity 钉（每钉旁注物理依据，#118 纪律）。"""
    reg = _load()
    # varactor_bpf：装载谐振链（突变结 C(bias)→主谐振方程正解）——βL<π
    # 装载臂长通道 0.90<1（C 装载使 f0 对 L 次线性）、cj0 通道次之（C∝cj0
    # 线性→f0 弹性 ~0.10）、bias/phi 突变结幂律通道减半（(1+V/φ)^-1/2 链
    # 折半）、w 经 εeff 弱通道；耦合缝/抽头/阶数不进装载谐振式=0
    scores_var = _scores(reg, "varactor_bpf")
    assert 0.8 < scores_var["arm_len_mm"] < 1.0
    assert 0.05 < scores_var["cj0_pf"] < 0.2
    assert abs(scores_var["bias_v"] - scores_var["phi_v"]) < 1e-6
    assert scores_var["bias_v"] < scores_var["cj0_pf"]
    assert 0.0 < scores_var["w_mm"] < 0.1
    for zero_p in ("order", "arm_gap_mm", "gap_mm", "tap_frac"):
        assert scores_var[zero_p] == 0.0, zero_p
    # xcheb_bpf4：开路环周长恒等式（perimeter=4a+2Δl）——a 通道 ≈−1（边缘
    # 延伸 Δl 稀释至 0.988）、er 经 εeff+Δl 双通道 ~0.44（λg/2 腔模型
    # 0.5·dlnεeff/dlnεr 主项）、h/w 经 Δl/εeff 弱通道；耦合缝/版图量/
    # tan_d 不进环谐振式=0
    scores_xch = _scores(reg, "xcheb_bpf4")
    assert 0.95 < scores_xch["a_mm"] < 1.0
    assert abs(scores_xch["er"] - 0.5 * 3.66 / (1.0 + 3.66)) < 0.1
    assert 0.0 < scores_xch["w_mm"] < 0.1
    assert 0.0 < scores_xch["h_mm"] < 0.1
    for zero_p in ("g12_mm", "g23_mm", "g34_mm", "g14_mm", "g_open_mm",
                   "g_pos_mm", "tap_t_mm", "tan_d"):
        assert scores_xch[zero_p] == 0.0, zero_p


def test_sanity_helix_wire_linear_chain():
    """螺旋总线长式 f∝1/(N(4dN+Np))：turns 弹性=1（线性链）、d+p 弹性
    之和=1（d 份额 4dN/wire + p 份额 Np/wire）。"""
    scores = _scores(_load(), "helix")
    assert scores["helix_turns"] == 1.0
    assert abs(scores["helix_d_mm"] + scores["helix_pitch_mm"] - 1.0) < 0.01
    assert scores["feed_gap_mm"] == 0.0 and scores["helix_w_mm"] == 0.0


def test_sanity_line_width_z0_hj_regime():
    """基元线宽 Z0 弹性：HJ w/h≈2.2 域 ~0.6（薄线极限 0.5 与宽线极限间）；
    长度不进 Z0 恒等式=0。"""
    reg = _load()
    for tpl in ("bend", "tjunc", "atten_pi", "atten_t"):
        w_key = "w_feed_mm" if tpl == "tjunc" else "w_mm"
        s = _scores(reg, tpl)
        assert 0.5 < s[w_key] < 0.8, (tpl, s[w_key])
    assert _scores(reg, "bend")["arm_len_mm"] == 0.0


def test_sanity_via_log_ratio_elasticity():
    """反焊盘同轴口径 Z=(60/√εr)·ln(pad/r_via)：对数比值弹性
    =1/ln(pad/r_via)≈0.597（非 1——比值弹性定义），双向对称。"""
    scores = _scores(_load(), "via")
    expected = 1.0 / math.log(0.8 / 0.15)
    assert abs(scores["antipad_mm"] - expected) < 1e-3
    assert abs(scores["r_via_mm"] - expected) < 1e-3
    assert scores["w_mm"] == 0.0


def test_sanity_attenuator_e4_vs_z0_channels():
    """衰减器 E4 闭式主输出：atten_db 通道（π 型 n²−1 强于 T 型 n−1）
    与 Z0(w) 线性通道分解——10dB 档 π 型弹性 ~1.41、T 型 ~0.81（数值核：
    dlnr/dlnA=(·)·(A/20)·ln10）；布局偏移 shunt_off 不进闭式=0。"""
    reg = _load()
    pi_s = _scores(reg, "atten_pi")
    t_s = _scores(reg, "atten_t")
    assert abs(pi_s["atten_db"] - 1.406814) < 1e-6
    assert abs(t_s["atten_db"] - 0.808491) < 1e-6
    assert pi_s["atten_db"] > pi_s["w_mm"] > 0.0
    assert t_s["atten_db"] > t_s["w_mm"] > 0.0
    assert pi_s["shunt_off_mm"] == 0.0 and t_s["shunt_off_mm"] == 0.0


def test_sanity_cps_gap_dominated_narrow_gap():
    """CPS 窄缝域（a=gap/2=0.25、b=w+gap/2）：缝控电容量→gap 弹性>w 弹性
    （共形映射 k1=a/b 双通道方向已核：dgap→Z 升、dw→Z 降）。"""
    scores = _scores(_load(), "cps")
    assert scores["gap_mm"] > scores["w_mm"] > 0.0
    assert scores["line_len_mm"] == 0.0


def test_sanity_wstep_difference_of_large_numbers():
    """wstep 阶跃反射 |Γ|=差比和大数之差：双线宽弹性 >1（高相对敏感）
    且 w2>w1（|dΓ/dZ2|/|dΓ/dZ1|=Z1/Z2>1 通道）；长度不进=0。"""
    scores = _scores(_load(), "wstep")
    assert scores["w2_mm"] > scores["w1_mm"] > 1.0
    assert scores["line_len_mm"] == 0.0


def test_sanity_suspended_stripline_cavity_height_dominant():
    """悬置带线（FD softmin 定标域，b=1.016 邻 1.37·h 守卫带）：腔高 b
    弹性>线宽 w（q 填充比 b/h 主导）；长度=0。"""
    scores = _scores(_load(), "suspended_stripline")
    assert scores["b_mm"] > scores["w_mm"] > 0.0
    assert scores["line_len_mm"] == 0.0


def test_sanity_pifa_design_semantics_pins():
    """PIFA L 路径式（居中短路板不绕行，真机两轮实证）：L=1 主导、W 经
    εeff 弱进入（0<w<0.1）、Ws/pin 不进谐振式=0（param_semantics 明示）。"""
    scores = _scores(_load(), "pifa")
    assert scores["pifa_l_mm"] == 1.0
    assert 0.0 < scores["pifa_w_mm"] < 0.1
    assert scores["pifa_ws_mm"] == 0.0
    assert scores["pin_back_mm"] == 0.0 and scores["pin_y_mm"] == 0.0


def test_sanity_zero_elasticity_is_explicit_identity_statement():
    """零弹性=设计恒等式不含该参数的显式陈述（如 slot 馈线宽/板边距）：
    非缺失非编造，schema 收 0 分（finite>=0）。"""
    scores = _scores(_load(), "slot")
    assert scores["slot_l_mm"] == 1.0
    assert scores["slot_w_mm"] == 0.0
    assert scores["feed_w_mm"] == 0.0
    assert scores["feed_margin_mm"] == 0.0
