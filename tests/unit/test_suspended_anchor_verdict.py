"""Q-X9 悬置带线跨引擎 anchor 判读函数钉（aurora_q 席位 Q-X9）。

外部实测锚（D:/晶圆键合/rfauto_反馈与实测经验.md §2.1，几何 w=0.52/b=0.50/
h=0.05mm/εr=11.9 Si、空气腔 0.9×0.5×5.1mm、两端波端口满截面）：
|S11|max=−23.5dB、|S21|mean=−0.07dB、power_sum_max≈1.0。

本模块 = 判读纯函数单源（真跑驱动 runs/aurora_q/qx9_anchor/qx9_runner.py
经 ``from tests.unit.test_suspended_anchor_verdict import ...`` 复算同一
判读面——判据先冻结后跑（#122），真跑后不因结果改门；闭式锚不硬编码，
每次判读由 _suspended_stripline_ri 现场重算=独立复算锚）。

预声明门（runs/aurora_q/qx9_anchor/spec.md §5，冻结于真跑前）：
  G1（|S21|mean，shield 变体） : |Δ|≤0.3dB PASS / ≤0.5 PARTIAL / FAIL
  G2（|S11|max 深度，shield）   : |Δ|≤6dB PASS / ≤10dB PARTIAL / FAIL
                                 （参考系分支声明见 NOTE_G2_REF）
  G3（εeff，open 变体）        : |Δεeff|/闭式 ≤2% PASS / ≤5% PARTIAL / FAIL
                                 （仓内 SSL 锚既有口径，TEMPLATE_META extraction）
  G4（引擎 ZL，open 变体）     : |ΔZ0|/闭式 ≤10% PASS / ≤15% PARTIAL / FAIL
                                 （引擎 ZL 已知离散偏置带 #280/#313）
  G5（健康，两变体）           : 无源性 ≤1.05 且无 |S|>1 且离线审计守卫全过
                                 且 plane_dist 自洽 ≤2·BASE（二值，无 PARTIAL）
总 verdict：任一 FAIL→DISAGREE；两变体齐+全 PASS→AGREE；否则 PARTIAL
（变体缺=INCOMPLETE，如实不凑）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.calc_families.rf_line import _suspended_stripline_ri

# ── 冻结的锚常量（#122：真跑前冻结，不因结果改）─────────────────────────────
#: 几何（外部 §2.1 实测锚口径，mm）
W_MM, B_MM, H_MM, ER_SI = 0.52, 0.50, 0.05, 11.9
#: HFSS 腔：0.9×0.5×5.1mm（x 半宽 0.45=shield 变体 PEC 墙位）
CAVITY_HALF_X_MM, CAVITY_B_MM, CAVITY_LEN_MM = 0.45, 0.50, 5.1
#: HFSS 外部锚标量（§2.1 原文）
HFSS_S11_MAX_DB = -23.5
HFSS_S21_MEAN_DB = -0.07
HFSS_PORT_Z0_OHM = 50.0   # implied-band 换算参考（50Ω 重归一解读分支）
#: 预声明频带（HFSS 扫频带未声明；均匀无损匹配线 |S| 幅值带平坦，spec §4）
BAND_GHZ = (1.0, 10.0)
C0 = 299792458.0

# ── 门限（预声明冻结）───────────────────────────────────────────────────────
G1_PASS_DB, G1_PARTIAL_DB = 0.3, 0.5
G2_PASS_DB, G2_PARTIAL_DB = 6.0, 10.0
G3_PASS, G3_PARTIAL = 0.02, 0.05
G4_PASS, G4_PARTIAL = 0.10, 0.15
PASSIVITY_MAX = 1.05
#: plane_dist 自洽容差（两端测量面各吸附 ±BASE/2 的 2 倍余量）
PLANE_DIST_TOL_BASE = 2.0

# ── 真跑参数面（runner 与单测同源；spec §4）─────────────────────────────────
COMMON_PARAMS: dict[str, object] = {
    "w_mm": W_MM, "b_mm": B_MM, "line_len_mm": CAVITY_LEN_MM,
    "_board_mm": 5.5,      # y 域半宽=线端 2.55+馈 2.95（#347 探针位守卫余量）
    "_near_ratio": 10,     # NEAR=BASE/10（C9 SSL 真跑复跑款，ZL 离散偏置压制）
    "_nrts": 150000,       # dt≈29fs 细网格防 NrTS 触顶（#266/#268 款）
}
SUBSTRATE: dict[str, float] = {"h_mm": H_MM, "er": ER_SI, "tan_d": 0.0}
SHIELD_PARAMS: dict[str, object] = {
    **COMMON_PARAMS,
    # shield 变体：x 墙=域 PEC（HFSS 腔壁同构）；y 端 PML_8（端口轴不动）；
    # z 上下地 PEC（模板缺省=腔上下接地）
    "_boundary": ["PEC", "PEC", "PML_8", "PML_8", "PEC", "PEC"],
}
OPEN_PARAMS: dict[str, object] = dict(COMMON_PARAMS)   # 侧向开域=闭式定义几何

# ── Q-X19 修复（Q-X13 G1 根因闭环）：测量面移出激励近场 ────────────────────
#: 修复后两端口共用的 MeasPlaneShift（毫米；渲染文本内=米字面 0.002）。
#: 核算（runs/aurora_q/qx13_investigation/DISAGREE_ANALYSIS.md §0/§2.2）：
#: 模板惯例 shift=(BOARD−L/2)/3=0.98333mm → 测量面距激励面仅 0.809mm=
#: 2.83/kc1 → 最低非模残余 e^−2.83≈5.9%（Q-RM-1 实测污染 +6.5%/+7.2%）→
#: S21 分母抬高、平坦压缩 −0.5dB（G1 FAIL 根因）。处方=|激励面−测量面|
#: ≥ 5×1/kc1：kc1=π/0.9mm（shield 腔 x 全宽 2×0.45mm 的 PEC 壁最低横模）
#: → 5/kc1=1.43239mm，加 FeedShift=10·NEAR=BASE=0.17393mm → shift ≥
#: 1.60632mm；取 2.0mm：sep=1.82607mm=6.38/kc1（网格吸附后实况 6.32），
#: 残余 ≤e^−6.38≈0.17%，且 2.0mm < 馈段长 2.95mm（测量面仍在均匀截面
#: 馈段内，测量面间均匀截面判读前提不变，plane_dist 名义式随之同基）。
#: open 变体侧向无 PEC 壁、横向衰减快于封闭腔，同钉保守共用（双变体同修）。
MEASPLANE_SHIFT_MM = 2.0

#: patch 锚（render_script('suspended_stripline', ...) 产物各恰 1 次；
#: 通用脚注 _port3 死路径的 MeasPlaneShift=float(_port3.measplane_shift)
#: 不在本修面，不动）
_MP_ANCHOR_P1 = "MeasPlaneShift=(Y0 + BOARD) / 3"
_MP_ANCHOR_P2 = "MeasPlaneShift=(BOARD - Y1) / 3"


def rendered_base_mesh_m() -> float:
    """渲染自动档 BASE（米）=λ_sub/50@F_MAX，render_core 公式镜像（3e8
    口径；Q-RM-1 audit 实测 BASE=1.7393131e-4 与此一致）。FeedShift=
    10·NEAR=BASE 单源于此（NEAR=BASE/_near_ratio，_near_ratio=10）。"""
    return 3e8 / (BAND_GHZ[1] * 1e9 * math.sqrt(ER_SI)) / 50.0


def nearfield_decay_len_m() -> float:
    """激励近场最低非模衰减长度 1/kc1（米）：shield 腔 x 全宽
    2·CAVITY_HALF_X_MM 的 PEC 壁最低横模 kc1=π/宽（Q-X13 §2.2 口径）。"""
    return 2.0 * CAVITY_HALF_X_MM * 1e-3 / math.pi


def measplane_shift_fix() -> dict[str, float | bool]:
    """Q-X19 修复量核算（runner audit 守卫与本测试钉同源；请求值口径，
    网格吸附实况由 runner audit 另行按吸附值复检同门）。"""
    shift_m = MEASPLANE_SHIFT_MM * 1e-3
    feed_shift_m = rendered_base_mesh_m()          # FeedShift=10·NEAR=BASE
    decay_m = nearfield_decay_len_m()              # 1/kc1
    sep_m = shift_m - feed_shift_m                 # |激励面−测量面|
    feed_len_m = (float(COMMON_PARAMS["_board_mm"])
                  - CAVITY_LEN_MM / 2.0) * 1e-3    # 馈段长=BOARD−L/2
    return {
        "shift_m": shift_m, "feed_shift_m": feed_shift_m, "sep_m": sep_m,
        "decay_len_m": decay_m, "min_sep_m": 5.0 * decay_m,
        "kc1_rad_per_m": math.pi / (2.0 * CAVITY_HALF_X_MM * 1e-3),
        "sep_over_decay": sep_m / decay_m,
        "residual_bound": math.exp(-sep_m / decay_m),
        "legacy_shift_m": feed_len_m / 3.0,
        "feed_len_m": feed_len_m,
        "in_feed": bool(shift_m < feed_len_m),
        "guard_4near_ok": bool(sep_m >= 4.0 * feed_shift_m / 10.0),
    }


def patch_measplane_shift(script_text: str) -> str:
    """Q-X19 修复补丁：两端口 MeasPlaneShift 由模板惯例（(Y0+BOARD)/3 与
    (BOARD−Y1)/3=馈段长/3，测量面距激励面仅 0.809mm 落激励近场，Q-X13
    G1 根因）改为 MEASPLANE_SHIFT_MM 米字面。锚各恰 1 次（缺/多
    ValueError fail-loud，同 patch_shield_cavity 契约）；幂等不可（二次
    调用锚已失）。shield/open 双变体同锚同修；beta_block 的 _plane_dist=
    2·BOARD−mp1−mp2 读端口吸附后属性，随补丁自动同基（无第二锚）。"""
    new_mp = repr(MEASPLANE_SHIFT_MM * 1e-3)
    out = script_text
    for old in (_MP_ANCHOR_P1, _MP_ANCHOR_P2):
        cnt = out.count(old)
        if cnt != 1:
            raise ValueError(
                f"qx9 measplane patch: anchor {old!r} 出现 {cnt} 次（须恰 1）")
        out = out.replace(old, f"MeasPlaneShift={new_mp}")
    return out


def render_qx9_variant_text(variant: str) -> str:
    """双变体渲染组合单源（runner 与测试同源）：render → shield 腔补丁
    （仅 ssl_shield）→ 测量面近场修复补丁（双变体）。两补丁锚不相交，
    次序无关，组合顺序钉进单测。"""
    from rfauto.adapters.openems_templates import render_script

    params = SHIELD_PARAMS if variant == "ssl_shield" else OPEN_PARAMS
    text = render_script("suspended_stripline", dict(params),
                         BAND_GHZ, 0.0, dict(SUBSTRATE))
    if variant == "ssl_shield":
        text = patch_shield_cavity(text)
    return patch_measplane_shift(text)


def nominal_plane_dist_shifted_m(board_mm: float,
                                 meas_shift_mm: float) -> float:
    """修复后两测量面名义间距（米）=2·BOARD−2·shift（双口对称同 shift）；
    与渲染 beta_block _plane_dist=2·BOARD−mp1−mp2 同式（mp 属性=网格吸附
    值，吸附差 ≤±BASE/2×2 由 PLANE_DIST_TOL_BASE=2·BASE 容差吸收）。"""
    return (2.0 * board_mm - 2.0 * meas_shift_mm) * 1e-3

# ── 补丁锚文本（render_script 产物实测存在性由单测钉）───────────────────────
_DOM_X_LINE = "DOM_X = BOARD + AIR_SIDE"
_SUB_X_LO = "sub.AddBox((-BOARD, -BOARD, "
_SUB_X_HI = "), (BOARD, BOARD, "
_SHIELD_DOM_X_LINE = (
    "DOM_X = 0.00045  # qx9 shield: HFSS cavity half-width 0.45mm "
    "(isomorphic PEC side walls)")


def closed_form_anchor() -> dict[str, float]:
    """闭式锚现场重算（独立复算：不读硬编码，每次判读调用 _suspended_stripline_ri）。"""
    eps_eff, z0 = _suspended_stripline_ri(W_MM, B_MM, H_MM, ER_SI)
    return {"eps_eff": eps_eff, "z0_ohm": z0,
            "w_mm": W_MM, "b_mm": B_MM, "h_mm": H_MM, "epsilon_r": ER_SI}


def hfss_implied_z0_band() -> tuple[float, float]:
    """HFSS |S11|max→Z0 隐含带（50Ω 重归一解读分支）：Γ=0.0668→[43.74, 57.16]Ω。"""
    g = 10.0 ** (HFSS_S11_MAX_DB / 20.0)
    z = HFSS_PORT_Z0_OHM
    return (z * (1.0 - g) / (1.0 + g), z * (1.0 + g) / (1.0 - g))


def nominal_plane_dist_m(board_mm: float, line_len_mm: float) -> float:
    """两测量面名义间距（米）=2·BOARD−2·(feed_len/3)，feed_len=BOARD−L/2
    → (4·BOARD+L)/3。与渲染 beta_block _plane_dist 定义同式。"""
    return (4.0 * board_mm + line_len_mm) / 3.0 * 1e-3


def patch_shield_cavity(script_text: str) -> str:
    """shield 变体确定性补丁：x 域半宽→HFSS 腔半宽 0.45mm（腔壁=域 PEC 墙）。

    两处替换（均为 render_script('suspended_stripline', SHIELD_PARAMS) 产物
    的恰好一次出现，缺/多锚即 ValueError fail-loud）：
      1) DOM_X 行 BOARD+AIR_SIDE → 0.00045 字面（y 域 DOM_Y 不动）；
      2) 基板盒 x 坐标 ±BOARD → ±DOM_X（腔内介质只填到墙）。
   BOARD=5.5mm 仍作 y 域/端口馈共享字面量；幂等不可（二次调用锚已失）。
    """
    out = script_text
    for old, new in (
        (_DOM_X_LINE, _SHIELD_DOM_X_LINE),
        (_SUB_X_LO, "sub.AddBox((-DOM_X, -BOARD, "),
        (_SUB_X_HI, "), (DOM_X, BOARD, "),
    ):
        cnt = out.count(old)
        if cnt != 1:
            raise ValueError(
                f"qx9 shield patch: anchor {old!r} 出现 {cnt} 次（须恰 1）")
        out = out.replace(old, new)
    return out


# ── 门函数（每门返回 status/观测/门限/说明，全 JSON 可序列化）───────────────
def gate_g1_s21_mean(s21_mean_db: float) -> dict[str, object]:
    dev = s21_mean_db - HFSS_S21_MEAN_DB
    status = ("PASS" if abs(dev) <= G1_PASS_DB
              else "PARTIAL" if abs(dev) <= G1_PARTIAL_DB else "FAIL")
    return {"gate": "G1", "status": status, "observed_s21_mean_db": s21_mean_db,
            "hfss_db": HFSS_S21_MEAN_DB, "dev_db": dev,
            "pass_db": G1_PASS_DB, "partial_db": G1_PARTIAL_DB,
            "variant": "ssl_shield"}


def gate_g2_s11_max(s11_max_db: float) -> dict[str, object]:
    dev = s11_max_db - HFSS_S11_MAX_DB
    status = ("PASS" if abs(dev) <= G2_PASS_DB
              else "PARTIAL" if abs(dev) <= G2_PARTIAL_DB else "FAIL")
    return {"gate": "G2", "status": status, "observed_s11_max_db": s11_max_db,
            "hfss_db": HFSS_S11_MAX_DB, "dev_db": dev,
            "pass_db": G2_PASS_DB, "partial_db": G2_PARTIAL_DB,
            "variant": "ssl_shield"}


def gate_g3_eps_eff(eps_eff_engine: float) -> dict[str, object]:
    anchor = closed_form_anchor()
    rel = abs(eps_eff_engine - anchor["eps_eff"]) / anchor["eps_eff"]
    status = ("PASS" if rel <= G3_PASS
              else "PARTIAL" if rel <= G3_PARTIAL else "FAIL")
    return {"gate": "G3", "status": status,
            "observed_eps_eff": eps_eff_engine,
            "closed_eps_eff": anchor["eps_eff"], "rel": rel,
            "pass_rel": G3_PASS, "partial_rel": G3_PARTIAL,
            "variant": "ssl_open"}


def gate_g4_z0(z0_engine: float) -> dict[str, object]:
    anchor = closed_form_anchor()
    rel = abs(z0_engine - anchor["z0_ohm"]) / anchor["z0_ohm"]
    status = ("PASS" if rel <= G4_PASS
              else "PARTIAL" if rel <= G4_PARTIAL else "FAIL")
    lo, hi = hfss_implied_z0_band()
    return {"gate": "G4", "status": status, "observed_z0_ohm": z0_engine,
            "closed_z0_ohm": anchor["z0_ohm"], "rel": rel,
            "pass_rel": G4_PASS, "partial_rel": G4_PARTIAL,
            "hfss_implied_band_ohm": [lo, hi],
            "in_hfss_band": bool(lo <= z0_engine <= hi),
            "variant": "ssl_open"}


def gate_g5_health(passivity_max: float, over_unity_cnt: int, audit_ok: bool,
                   plane_dist_ok: bool) -> dict[str, object]:
    ok = (passivity_max <= PASSIVITY_MAX and over_unity_cnt == 0
          and audit_ok and plane_dist_ok)
    return {"gate": "G5", "status": "PASS" if ok else "FAIL",
            "passivity_max": passivity_max,
            "passivity_limit": PASSIVITY_MAX,
            "s_over_unity_cnt": over_unity_cnt,
            "audit_ok": audit_ok, "plane_dist_ok": plane_dist_ok}


def _stats_for_variant(m: dict[str, object] | None,
                       keys: tuple[str, ...]) -> dict[str, object] | None:
    if m is None or any(m.get(k) is None for k in keys):
        return None
    return m


def judge_qx9(measured: dict[str, dict[str, object] | None]) -> dict[str, object]:
    """判读组装（真跑驱动与单测同源）。

    measured 键："ssl_shield"/"ssl_open"；None=该变体未跑（INCOMPLETE）。
    ssl_shield 键：s21_mean_db / s11_max_db / passivity_max / over_unity_cnt /
      audit_ok / plane_dist_ok / zl_re_med（INFO）/ wall_s。
    ssl_open 键：eps_eff_med / zl_re_med / passivity_max / over_unity_cnt /
      audit_ok / plane_dist_ok / wall_s。
    """
    shield_keys = ("s21_mean_db", "s11_max_db", "passivity_max",
                   "over_unity_cnt", "audit_ok", "plane_dist_ok")
    open_keys = ("eps_eff_med", "zl_re_med", "passivity_max",
                 "over_unity_cnt", "audit_ok", "plane_dist_ok")
    sh = _stats_for_variant(measured.get("ssl_shield"), shield_keys)
    op = _stats_for_variant(measured.get("ssl_open"), open_keys)
    anchor = closed_form_anchor()
    lo, hi = hfss_implied_z0_band()
    out: dict[str, object] = {
        "seat": "Q-X9", "campaign": "aurora_q",
        "subject": "suspended_stripline openEMS vs HFSS external anchor",
        "band_ghz": list(BAND_GHZ),
        "anchor": anchor,
        "hfss": {"s11_max_db": HFSS_S11_MAX_DB,
                 "s21_mean_db": HFSS_S21_MEAN_DB,
                 "implied_z0_band_ohm": [lo, hi]},
    }
    if sh is None or op is None:
        out["verdict"] = "INCOMPLETE"
        out["missing"] = [k for k, v in (("ssl_shield", sh),
                                         ("ssl_open", op)) if v is None]
        return out
    gates = {
        "G1": gate_g1_s21_mean(float(sh["s21_mean_db"])),
        "G2": gate_g2_s11_max(float(sh["s11_max_db"])),
        "G3": gate_g3_eps_eff(float(op["eps_eff_med"])),
        "G4": gate_g4_z0(float(op["zl_re_med"])),
        "G5": gate_g5_health(
            max(float(sh["passivity_max"]), float(op["passivity_max"])),
            int(sh["over_unity_cnt"]) + int(op["over_unity_cnt"]),
            bool(sh["audit_ok"]) and bool(op["audit_ok"]),
            bool(sh["plane_dist_ok"]) and bool(op["plane_dist_ok"])),
    }
    sh_zl = float(sh["zl_re_med"])
    gates["G4"]["shield_zl_re_med_ohm_info"] = sh_zl
    gates["G4"]["shield_zl_in_hfss_band_info"] = bool(lo <= sh_zl <= hi)
    statuses = [str(g["status"]) for g in gates.values()]
    verdict = ("DISAGREE" if "FAIL" in statuses
               else "AGREE" if all(s == "PASS" for s in statuses) else "PARTIAL")
    out["verdict"] = verdict
    out["gates"] = gates
    out["notes"] = [
        "openEMS S11 参考=固定 50Ω（CalcPort ref_impedance=50）；HFSS 锚端口"
        "参考=波端口模式阻抗（是否 50Ω 重归一未声明）——G2 深度对照含此参考"
        "系分支，Z0 三方（G4+INFO 带）为物理主判",
        "openEMS 侧 tan_d=0.0（无损 Si 声明）；HFSS 锚未给 tanδ，"
        "power_sum_max≈1.0 支持近无损",
        "外部文档 εeff=1.59/Z0≈50.2 与现行仓内闭式（FD 重定标批后）"
        f"εeff={anchor['eps_eff']:.4f}/Z0={anchor['z0_ohm']:.2f} 的 εeff 差 "
        f"{abs(anchor['eps_eff'] - 1.59) / 1.59 * 100:.1f}% 如实登记（Z0 一致）",
        "频带 (1,10)GHz 为预声明（HFSS 扫频带未声明）；均匀无损匹配线 |S| 幅值"
        "对带平坦，判据不依赖频带对齐",
        "shield 变体=HFSS 腔壁同构（x 域 PEC ±0.45mm）；open 变体=侧向开域"
        "（闭式定义几何）——G3/G4 闭式交叉走 open 变体，G1/G2 标量对照走 "
        "shield 变体",
    ]
    return out


# ── 单测（判读函数钉；阈值边界逐点）─────────────────────────────────────────

def test_closed_form_anchor_recomputed_and_matches_external_doc():
    a1 = closed_form_anchor()
    a2 = closed_form_anchor()
    assert a1 == a2   # 确定性重算
    # 与外部 §2.1 引述值一致（εeff 引述 1.59，现行闭式 1.6034——0.9% 内）
    assert abs(a1["eps_eff"] - 1.59) <= 0.02, a1["eps_eff"]
    assert abs(a1["z0_ohm"] - 50.2) <= 0.5, a1["z0_ohm"]
    assert math.isclose(a1["eps_eff"], 1.6034, rel_tol=2e-3), a1["eps_eff"]
    assert math.isclose(a1["z0_ohm"], 50.25, rel_tol=2e-3), a1["z0_ohm"]


def test_hfss_implied_z0_band_math():
    lo, hi = hfss_implied_z0_band()
    g = 10.0 ** (-23.5 / 20.0)
    assert math.isclose(g, 0.066834, rel_tol=1e-4)
    assert math.isclose(lo, 50.0 * (1 - g) / (1 + g), rel_tol=1e-12)
    assert math.isclose(hi, 50.0 * (1 + g) / (1 - g), rel_tol=1e-12)
    assert abs(lo - 43.74) < 0.02 and abs(hi - 57.16) < 0.02


def test_gate_g1_boundaries():
    assert gate_g1_s21_mean(-0.07 - 0.3)["status"] == "PASS"    # 边界内含
    assert gate_g1_s21_mean(-0.07 + 0.3)["status"] == "PASS"
    assert gate_g1_s21_mean(-0.07 - 0.31)["status"] == "PARTIAL"
    assert gate_g1_s21_mean(-0.07 - 0.5)["status"] == "PARTIAL"
    assert gate_g1_s21_mean(-0.07 - 0.51)["status"] == "FAIL"
    assert gate_g1_s21_mean(-0.07 + 1.0)["status"] == "FAIL"


def test_gate_g2_boundaries():
    assert gate_g2_s11_max(-23.5 - 6.0)["status"] == "PASS"
    assert gate_g2_s11_max(-23.5 + 6.0)["status"] == "PASS"
    assert gate_g2_s11_max(-23.5 - 6.1)["status"] == "PARTIAL"
    assert gate_g2_s11_max(-23.5 - 10.0)["status"] == "PARTIAL"
    assert gate_g2_s11_max(-23.5 - 10.1)["status"] == "FAIL"
    assert gate_g2_s11_max(-23.5 + 10.1)["status"] == "FAIL"


def test_gate_g3_g4_boundaries():
    # 阈值位置用 ±1e-9 相对挪移对跨阈钉住（浮点边界抖动：a·1.02 的重算
    # rel 可能落阈任一侧，1e-9 挪移把 PASS/PARTIAL 分界钉到阈 ±1e-9 内）
    a = closed_form_anchor()
    g3 = gate_g3_eps_eff(a["eps_eff"] * (1.0 + 0.02 - 1e-9))
    assert g3["status"] == "PASS" and math.isclose(g3["rel"], 0.02, rel_tol=1e-7)
    assert gate_g3_eps_eff(a["eps_eff"] * (1.0 + 0.02 + 1e-9))["status"] == "PARTIAL"
    assert gate_g3_eps_eff(a["eps_eff"] * 1.021)["status"] == "PARTIAL"
    assert gate_g3_eps_eff(a["eps_eff"] * 1.051)["status"] == "FAIL"
    g4 = gate_g4_z0(a["z0_ohm"] * (1.0 - 0.10 + 1e-9))
    assert g4["status"] == "PASS"
    assert gate_g4_z0(a["z0_ohm"] * (1.0 - 0.10 - 1e-9))["status"] == "PARTIAL"
    assert gate_g4_z0(a["z0_ohm"] * 0.899)["status"] == "PARTIAL"
    assert gate_g4_z0(a["z0_ohm"] * 1.151)["status"] == "FAIL"
    # G4 附带 HFSS 隐含带 INFO（闭式 50.25 在带内）
    assert g4["in_hfss_band"] is True


def test_gate_g5_health_binary():
    ok = gate_g5_health(0.999, 0, True, True)
    assert ok["status"] == "PASS"
    assert gate_g5_health(1.0500001, 0, True, True)["status"] == "FAIL"
    assert gate_g5_health(0.9, 1, True, True)["status"] == "FAIL"      # |S|>1
    assert gate_g5_health(0.9, 0, False, True)["status"] == "FAIL"    # 审计守卫
    assert gate_g5_health(0.9, 0, True, False)["status"] == "FAIL"    # plane_dist


def test_judge_verdict_mapping():
    good_sh = {"s21_mean_db": -0.10, "s11_max_db": -25.0, "passivity_max": 0.999,
               "over_unity_cnt": 0, "audit_ok": True, "plane_dist_ok": True,
               "zl_re_med": 49.0, "wall_s": 100.0}
    good_op = {"eps_eff_med": 1.610, "zl_re_med": 48.5, "passivity_max": 0.999,
               "over_unity_cnt": 0, "audit_ok": True, "plane_dist_ok": True,
               "wall_s": 100.0}
    v = judge_qx9({"ssl_shield": good_sh, "ssl_open": good_op})
    assert v["verdict"] == "AGREE"
    # 单门 PARTIAL → 总 PARTIAL（不凑绿）
    sh2 = dict(good_sh, s11_max_db=-23.5 - 8.0)
    assert judge_qx9({"ssl_shield": sh2, "ssl_open": good_op})["verdict"] == "PARTIAL"
    # 任一 FAIL → DISAGREE
    sh3 = dict(good_sh, s21_mean_db=-0.07 + 1.0)
    v3 = judge_qx9({"ssl_shield": sh3, "ssl_open": good_op})
    assert v3["verdict"] == "DISAGREE"
    # 变体缺 → INCOMPLETE（如实不凑）
    v4 = judge_qx9({"ssl_shield": good_sh, "ssl_open": None})
    assert v4["verdict"] == "INCOMPLETE" and v4["missing"] == ["ssl_open"]
    # 锚现场重算进 verdict（不硬编码）
    assert v["anchor"]["z0_ohm"] == closed_form_anchor()["z0_ohm"]


def test_nominal_plane_dist_matches_beta_block_formula():
    # (4·BOARD+L)/3 与渲染脚本 _plane_dist=2·BOARD−mp1−mp2（mp=feed/3）同式
    board_mm, line_mm = 5.5, 5.1
    feed = board_mm - line_mm / 2.0
    direct = 2.0 * board_mm - 2.0 * (feed / 3.0)
    assert math.isclose(nominal_plane_dist_m(board_mm, line_mm) * 1e3, direct,
                        rel_tol=1e-12)


def test_patch_shield_cavity_on_rendered_script():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("suspended_stripline", dict(SHIELD_PARAMS),
                         BAND_GHZ, 0.0, dict(SUBSTRATE))
    # 补丁前锚文本恰 1 次（fail-loud 契约的正面）
    assert text.count(_DOM_X_LINE) == 1
    assert text.count(_SUB_X_LO) == 1
    assert text.count(_SUB_X_HI) == 1
    patched = patch_shield_cavity(text)
    assert _SHIELD_DOM_X_LINE in patched
    assert "sub.AddBox((-DOM_X, -BOARD, " in patched
    assert "), (DOM_X, BOARD, " in patched
    assert _DOM_X_LINE not in patched
    # y 域/端口馈共享字面 BOARD 不动
    assert "BOARD = 0.0055" in patched
    assert "DOM_Y = BOARD + AIR_SIDE" in patched
    # 边界六元已含 x 墙 PEC（_boundary 旋钮字面直出）
    assert 'SetBoundaryCond(["PEC", "PEC", "PML_8", "PML_8", "PEC", "PEC"])' \
        in patched
    # 幂等不可：二次调用锚已失 → ValueError
    try:
        patch_shield_cavity(patched)
    except ValueError:
        pass
    else:
        raise AssertionError("二次补丁必须 ValueError（fail-loud）")


def test_patch_shield_cavity_rejects_foreign_text():
    try:
        patch_shield_cavity("no anchors here")
    except ValueError:
        pass
    else:
        raise AssertionError("无锚文本必须 ValueError")


# ── Q-X19 修复钉（新 shift 值 + 近场距离 ≥5×1/kc1 + patch 契约）────────────

def test_measplane_shift_fix_values_pinned():
    fix = measplane_shift_fix()
    assert MEASPLANE_SHIFT_MM == 2.0
    assert fix["shift_m"] == 0.002
    # FeedShift=10·NEAR=BASE（render_core λ_sub/50@F_MAX 3e8 口径镜像；
    # Q-RM-1 audit 实测 BASE=1.7393131e-4 同源）
    assert math.isclose(fix["feed_shift_m"], 0.00017393131069573455,
                        rel_tol=1e-9)
    # 衰减长度：0.9mm 腔宽 → 1/kc1=0.28648mm
    assert math.isclose(fix["decay_len_m"], 0.9e-3 / math.pi, rel_tol=1e-12)
    assert math.isclose(fix["min_sep_m"], 5.0 * 0.9e-3 / math.pi, rel_tol=1e-12)
    # 最小可行 shift=FeedShift+5/kc1=1.60632mm（任务书口径 ≥1.61mm）
    min_shift = fix["feed_shift_m"] + fix["min_sep_m"]
    assert math.isclose(min_shift, 1.60632e-3, rel_tol=1e-4)
    assert fix["shift_m"] >= min_shift
    assert fix["shift_m"] >= 1.61e-3


def test_nearfield_sep_5kc1_pin_and_legacy_contrast():
    fix = measplane_shift_fix()
    # 修复请求值口径：sep=shift−FeedShift ≥ 5×1/kc1，实取倍数 >6（余量钉）
    assert fix["sep_m"] >= 5.0 * fix["decay_len_m"]
    assert fix["sep_over_decay"] >= 5.0
    assert fix["sep_over_decay"] > 6.0
    # 残余近模上界 ≤0.2%（对照 Q-RM-1 实测污染 ~6%）
    assert fix["residual_bound"] <= 0.002
    # 根因对照：旧 shift=(BOARD−L/2)/3=0.98333mm → sep=0.80941mm=2.83/kc1
    # → 残余 ~5.9%（Q-X13 实测 +6.5%/+7.2% 同量级）；修复后残余低 >20×
    legacy_sep = fix["legacy_shift_m"] - fix["feed_shift_m"]
    assert math.isclose(legacy_sep, 0.809402e-3, rel_tol=1e-4)
    legacy_residual = math.exp(-legacy_sep / fix["decay_len_m"])
    assert 0.05 <= legacy_residual <= 0.07, legacy_residual
    assert fix["residual_bound"] <= legacy_residual / 20.0


def test_measplane_shift_guard_347_compat_and_in_feed():
    fix = measplane_shift_fix()
    # #347 守卫兼容：|shift−FeedShift| ≥ 4·NEAR（NEAR=BASE/10）——远超，
    # 与近场 ≥5×1/kc1 新钉并存不冲突
    assert fix["guard_4near_ok"] is True
    # 测量面仍在馈段内（测量面间均匀截面判读前提）：shift < BOARD−L/2=2.95mm
    assert fix["in_feed"] is True
    assert math.isclose(fix["feed_len_m"], 2.95e-3, rel_tol=1e-12)
    assert math.isclose(fix["legacy_shift_m"], 2.95e-3 / 3.0, rel_tol=1e-12)


def test_patch_measplane_shift_on_rendered_script_both_variants():
    from rfauto.adapters.openems_templates import render_script

    for variant, params in (("ssl_shield", SHIELD_PARAMS),
                            ("ssl_open", OPEN_PARAMS)):
        text = render_script("suspended_stripline", dict(params),
                             BAND_GHZ, 0.0, dict(SUBSTRATE))
        if variant == "ssl_shield":
            text = patch_shield_cavity(text)
        # 补丁前：两锚各恰 1 次（fail-loud 契约正面）
        assert text.count(_MP_ANCHOR_P1) == 1, variant
        assert text.count(_MP_ANCHOR_P2) == 1, variant
        patched = patch_measplane_shift(text)
        assert patched.count("MeasPlaneShift=0.002") == 2, variant
        assert _MP_ANCHOR_P1 not in patched, variant
        assert _MP_ANCHOR_P2 not in patched, variant
        # 渲染组合单源与手工组合一致（shield 补丁先于 measplane 补丁；
        # 两补丁锚不相交，次序无关）
        assert render_qx9_variant_text(variant) == patched, variant


def test_patch_measplane_shift_exec_realized_separation():
    # 离线 exec 几何段（#212 手法，零仿真）：吸附后的真测量面（端口属性
    # measplane_shift=吸附值）距激励面仍 ≥5×1/kc1——守卫按吸附实况而非
    # 请求字面；基板线/网格配方可吸附移位，此钉防"请求过门、实况贴脸"。
    fix = measplane_shift_fix()
    text = render_qx9_variant_text("ssl_shield")
    head = text[:text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__", "__file__": "qx19_test_sim.py"}
    exec(compile(head, "qx19_fix_test", "exec"), scope)  # 测试内离线几何段（零仿真）
    mp1 = float(scope["_port1"].measplane_shift)   # 网格吸附值（米）
    mp2 = float(scope["_port2"].measplane_shift)
    feed = 10.0 * float(scope["NEAR"])
    kc1 = float(fix["kc1_rad_per_m"])
    # 吸附值确定性（同一渲染文本同一网格）：Q-X21 线端入网守卫落网格后
    # 复核实测 0.00198409371（前态 Q-RM-1 口径 0.00198362246——线端脱网
    # 2.557µm 时代的吸附基；Q-X21 网格重锚为修复的确定性问题，物理门
    # ≥5×1/kc1 与 ≥6×kc1 断言原样不动且余量不变档：6.318× vs 6.317×）
    assert math.isclose(min(mp1, mp2), 0.001984093711005345, rel_tol=1e-6)
    assert min(mp1, mp2) - feed >= 5.0 / kc1
    assert (min(mp1, mp2) - feed) * kc1 >= 6.0


def test_patch_measplane_shift_rejects_foreign_and_second_apply():
    try:
        patch_measplane_shift("no anchors here")
    except ValueError:
        pass
    else:
        raise AssertionError("无锚文本必须 ValueError")
    from rfauto.adapters.openems_templates import render_script

    text = render_script("suspended_stripline", dict(OPEN_PARAMS),
                         BAND_GHZ, 0.0, dict(SUBSTRATE))
    once = patch_measplane_shift(text)
    try:
        patch_measplane_shift(once)
    except ValueError:
        pass
    else:
        raise AssertionError("二次补丁必须 ValueError（fail-loud）")


def test_nominal_plane_dist_shifted_and_legacy_bridge():
    # 新名义面距（双口同 shift）：2·5.5−2·2.0=7.0mm
    assert math.isclose(nominal_plane_dist_shifted_m(5.5, 2.0), 7.0e-3,
                        rel_tol=1e-12)
    # 与 beta_block 运行式同构：2·BOARD−mp1−mp2（mp=shift）
    board, mp = 5.5, 2.0
    assert math.isclose(nominal_plane_dist_shifted_m(board, mp),
                        (2.0 * board - 2.0 * mp) * 1e-3, rel_tol=1e-15)
    # 桥：旧 shift=(BOARD−L/2)/3 时新旧两式同一量（(4·BOARD+L)/3 恒等）
    board_mm, line_mm = 5.5, 5.1
    legacy_mp = (board_mm - line_mm / 2.0) / 3.0
    assert math.isclose(nominal_plane_dist_shifted_m(board_mm, legacy_mp),
                        nominal_plane_dist_m(board_mm, line_mm),
                        rel_tol=1e-12)


# ── Q-X21 线端 nm 级精确入网守卫钉（G5 带缘噪声根治）────────────────────────
# 根因（Q-RM-4 G5 FAIL：over_unity=306，verdict.json）：SSL 均匀带名义分点
# Y0/Y1 旧口径只有 edges() 括号线（线端外侧 ±0.5mm 近点带），线端脱网
# 2.557µm（audit_ssl_open.json line_end_y0 实测）→ 端口面均匀带分点错位、
# 细档网格带缘曲率分辨不足 → |S|>1 数值噪声。根治（模板族级，oe_templates）：
# ① grid.py _near_points SSL 分支把 ±L/2 精确点加入特征线集（cps 线端同法
#   在先，#212 审计①）；② render_tl.py SSL body 尾部守卫：终网格缺线端
# （残差 >1nm）即 ValueError fail-loud（#152 家法）。本组钉三方同源：
# 特征线集单源 / 渲染守卫文本 / exec 实测终网格 / runner audit 导入常量。

#: 线端精确入网判定容差（米）——渲染端守卫字面 1e-9 / runner audit
#: line_end_on_grid（import 本常量）/ 本模块三方同源；与 #152 近重合去重
#: 的 1µm 口径不同语义（在位判定 vs 去重），不混用。
LINE_END_GRID_TOL_M = 1e-9

#: 渲染端守卫锚文本（_suspended_stripline_lines 尾部守卫循环头；恰 1 次）。
LINE_END_GUARD_ANCHOR = "for _ssl_end in (Y0, Y1):"

#: 守卫 ValueError 诊断锚（消息点名根因面，可判读性钉）。
LINE_END_GUARD_MSG_ANCHOR = "未精确入网"


def _guard_block_text(text: str) -> str:
    """从渲染文本截取守卫块（守卫锚行起、FDTD.Run 止；body 之后无其他块）。
    含 for 头整行（合成作用域 exec 需完整循环语句）。"""
    idx = text.index(LINE_END_GUARD_ANCHOR)
    return text[idx:text.index("FDTD.Run(", idx)]


def _exec_geometry_head(text: str, tag: str) -> dict:
    """离线 exec 几何段（#212 制度化手法，FDTD.Run 之前，秒级零仿真）。"""
    head = text[:text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__", "__file__": f"qx21_{tag}_sim.py"}
    exec(compile(head, f"qx21_{tag}_test", "exec"), scope)
    return scope


def line_end_residuals_m(scope: dict) -> dict[str, float]:
    """exec 后作用域的线端入网残差（米）：Y0/Y1 对终 y 网格线最近距。
    runner audit line_end_on_grid 同式（几何面单源口径）。"""
    ys = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
    return {name: float(np.min(np.abs(ys - float(scope[name]))))
            for name in ("Y0", "Y1")}


def test_line_end_exact_points_in_near_feature_set():
    """①特征线集单源钉：SSL 近点集含 ±L/2 精确点（Q-X21 新增）、带缘
    ±w/2（#198 既有）、edges() 括号线端近点带（junction 加密保留不撤）。"""
    from rfauto.adapters.oe_templates.grid import _near_points

    params = dict(SHIELD_PARAMS)
    nx, ny = _near_points("suspended_stripline", params)
    length = CAVITY_LEN_MM * 1e-3
    w = W_MM * 1e-3
    for end in (-length / 2, length / 2):          # 线端精确点（Q-X21）
        assert min(abs(v - end) for v in ny) <= 1e-12, end
    for edge in (-w / 2, w / 2):                   # 带缘精确点（#198 既有）
        assert min(abs(v - edge) for v in nx) <= 1e-12, edge
    for bracket in (-length / 2 - 0.5e-3, length / 2 + 0.5e-3):
        assert min(abs(v - bracket) for v in ny) <= 1e-12, bracket


def test_line_end_guard_block_in_rendered_script_both_variants():
    """②渲染守卫文本钉：双变体渲染产物各含守卫循环恰 1 次，块内含
    fail-loud raise 与诊断锚（缺/多锚即红——patch 锚契约同款）。"""
    for variant in ("ssl_shield", "ssl_open"):
        text = render_qx9_variant_text(variant)
        assert text.count(LINE_END_GUARD_ANCHOR) == 1, variant
        block = _guard_block_text(text)
        assert "raise ValueError" in block, variant
        assert LINE_END_GUARD_MSG_ANCHOR in block, variant


def test_line_end_tol_single_source_chain():
    """③容差三方同源钉：判读面常量=渲染守卫字面（1e-9 字面同形）；runner
    audit 消费本常量（qx9_runner import 面，C 档 audit 实跑复核）。"""
    assert LINE_END_GRID_TOL_M == 1e-9
    text = render_qx9_variant_text("ssl_open")
    assert "<= 1e-9" in _guard_block_text(text)


def test_line_end_on_grid_exec_realized_both_variants():
    """④exec 实测钉（#212 手法，零仿真）：双变体终网格 Y0/Y1 残差 ≤1nm
    （修复前实测 2.557µm——audit_ssl_open.json line_end_y0 残差）；新增两
    线不触 #152（三轴最小间距 ≥10µm，dt 主导轴 z=12.5µm 不受扰）。"""
    for variant in ("ssl_shield", "ssl_open"):
        scope = _exec_geometry_head(render_qx9_variant_text(variant), variant)
        res = line_end_residuals_m(scope)
        assert max(res.values()) <= LINE_END_GRID_TOL_M, (variant, res)
        for ax in ("x", "y", "z"):
            ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
            assert float(np.min(np.diff(ls))) >= 10e-6, (variant, ax)


def test_line_end_on_grid_nominal_params_exec():
    """⑤模板族级钉（非 qx9 参数专属）：名义几何（w=0.9058/b=1.016/L=40）
    + 审计档 0.4mm 网格同过守卫——render_script 全链（含守卫块 exec 不炸），
    既有 SSL 几何审计（test_suspended_stripline_template）零回归的同源面。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

    text = render_script(
        "suspended_stripline",
        dict(TEMPLATE_NOMINAL["suspended_stripline"]),
        (2.25, 2.75), mesh_resolution_mm=0.4)
    scope = _exec_geometry_head(text, "nominal")
    res = line_end_residuals_m(scope)
    assert max(res.values()) <= LINE_END_GRID_TOL_M, res


class _FakeMesh:
    """合成网格桩（守卫机械行为钉用；只实现 GetLines('y')）。"""

    def __init__(self, ys: np.ndarray) -> None:
        self._ys = ys

    def GetLines(self, ax: str) -> np.ndarray:   # 绑定 API 同名（大小写保持）
        return self._ys


def test_line_end_guard_fail_loud_on_missing_line():
    """⑥守卫机械行为钉（合成作用域，零渲染）：线端脱网（残差 >1nm）→
    ValueError；在位（恰落线）→ 静默过（正常路径零行为变化）。"""
    block = _guard_block_text(render_qx9_variant_text("ssl_open"))
    y_on = np.array([-3.05e-3, -2.55e-3, 0.0, 2.55e-3, 3.05e-3])
    y_off = np.array([-3.05e-3, -2.550003e-3, 0.0, 2.550003e-3, 3.05e-3])
    for ys, expect_raise in ((y_off, True), (y_on, False)):
        scope = {"np": np, "mesh": _FakeMesh(ys),
                 "Y0": -2.55e-3, "Y1": 2.55e-3}
        try:
            exec(compile(block, "qx21_guard_probe", "exec"), scope)
        except ValueError:
            assert expect_raise, "在位路径不得 raise（零行为变化契约）"
        else:
            assert not expect_raise, "脱网路径必须 ValueError（fail-loud）"


def test_line_end_guard_message_names_root_cause():
    """⑦诊断可判读钉：ValueError 消息点名'未精确入网'与根治守卫（#118
    家族：观察/报错文本不得失真，报错必须可归因）。"""
    block = _guard_block_text(render_qx9_variant_text("ssl_open"))
    scope = {"np": np, "mesh": _FakeMesh(np.array([0.0])),
             "Y0": -2.55e-3, "Y1": 2.55e-3}
    with pytest.raises(ValueError, match=LINE_END_GUARD_MSG_ANCHOR):
        exec(compile(block, "qx21_guard_msg", "exec"), scope)


def test_line_end_scope_pinned_cps_intact_mline_unchanged():
    """⑧作用域钉（他模板近点集零漂移）：cps 线端精确点先例原样在位；
    mline/stripline 线端仍=edges() 括号线（Q-X21 只动 SSL 分支——若后续
    席位有意推广到 mline 族，此钉显式红以确认是有意变更而非误伤）。"""
    from rfauto.adapters.oe_templates.grid import _near_points

    cps_ny = _near_points(
        "cps", {"w_mm": 2.95, "gap_mm": 0.5, "line_len_mm": 40.0})[1]
    assert min(abs(v + 0.02) for v in cps_ny) <= 1e-12
    assert min(abs(v - 0.02) for v in cps_ny) <= 1e-12
    for tpl in ("mline", "stripline"):
        ny = _near_points(tpl, {"w_mm": 1.113, "line_len_mm": 40.0})[1]
        assert min(abs(v + 0.02) for v in ny) > 1e-12, tpl
        assert min(abs(v - 0.02) for v in ny) > 1e-12, tpl
        assert min(abs(v + 0.0205) for v in ny) <= 1e-12, tpl   # 括号线仍在


def test_line_end_guard_after_port_and_dedup_in_script_order():
    """⑨脚本序钉：守卫块在双 StripLinePort 构造与 #152 近重合去重之后
    （终网格口径复核=后置语义；若守卫被提前/去重被移后即红——#152 家法
    形态位次守恒）。"""
    text = render_qx9_variant_text("ssl_open")
    guard_at = text.index(LINE_END_GUARD_ANCHOR)
    assert text.index("StripLinePort(CSX, port_nr=1") < guard_at
    assert text.index("StripLinePort(CSX, port_nr=2") < guard_at
    assert text.index("mesh.SetLines(_ax, np.array(_keep))") < guard_at
    assert text.index("FDTD.Run(") > guard_at
