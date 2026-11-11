"""悬置带线 G3 FD 第三方仲裁服务壳（Q-X20 / aurora_q，2026-11-07）。

规则 4（服务层 JSON 进出）：本模块只做组装与 JSON 化——FD 数值内核单源
core/suspended_stripline_fd_judge.py（静流裁判，零仿真铁律 7）；闭式腿经
rfauto.core.calculators facade 取 `_suspended_stripline_ri`（禁改其实现，
被裁判对象）。外部观测腿（openEMS/HFSS 数）由调用方以参数注入（缺省=
qx9_anchor/qx13 冻结锚值，出处随行登记），服务不读 runs/。

交付面：
- `suspended_stripline_g3_fd_judge`：一次调用产出完整仲裁 dict（收敛阶梯+
  锚资格+run 网格仿真+z 假说分类+三方对照表+偏差归因）。
- `suspended_stripline_closed_form_bias`：给定 (u,s,εr,eps_fd) 角点表算
  闭式偏差（w2f 288 点扫描角点复核入口，eps_fd 由调用方供给）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.calculators import _suspended_stripline_ri
from rfauto.core.suspended_stripline_fd_judge import (
    G3_B_MM,
    G3_EPS_R,
    G3_H_MM,
    G3_W_MM,
    RUN_X_NEAR_MM,
    RUN_Z_LINES_MM,
    classify_z_airgap_hypothesis,
    cohn_air_anchor,
    exact_limit_anchors,
    judge_ladder,
    referee_cross_check,
    run_mesh_emulation_eps_eff,
)

# ── 外部观测锚（冻结常量，出处随行；调用方可覆盖重跑点）──────────────────────

#: openEMS 干净口 εeff（runs/aurora_q/qx13_investigation/spectrum_analysis.json
#: ssl_open.eps_eff.p2_med——port2 距激励 9.84mm 近场死区=干净模参照）。
OPENEMS_EPS_EFF_CLEAN = 1.5459354578508522
#: openEMS verdict 口 εeff（verdict.json G3.observed_eps_eff=双口中位均值，
#: port1 受近场污染抬高 +0.6%——主归因对象=干净口，verdict 口随行登记）。
OPENEMS_EPS_EFF_VERDICT = 1.5551136839380097
#: openEMS ZL 中位（verdict.json G4.observed_z0_ohm，双口均值）。
OPENEMS_Z0_OHM = 50.46607768614223
#: HFSS 外部实测锚 εeff（qx9 spec.md §1「外部引述」；反馈 §2.1 实测口径）。
HFSS_IMPLIED_EPS_EFF = 1.59
#: HFSS 外部锚 Z0（同上 Z0≈50.2；|S11|max 隐含弱带 [43.74,57.16] 随注）。
HFSS_IMPLIED_Z0_OHM = 50.2


def suspended_stripline_closed_form_bias(
    corners: list[dict[str, float]],
) -> list[dict[str, Any]]:
    """角点表闭式偏差复核：(u,s,εr,eps_fd) → 闭式 εeff 与相对 FD 偏差。

    corners 元素键：u（=w/b）、s（=h/b）、epsilon_r、eps_fd（w2f FD 真值）。
    b 取 G3 名义 0.50mm（几何族缩放不变量，u/s 决定归一形状）。纯函数。
    """
    out: list[dict[str, Any]] = []
    for c in corners:
        b = G3_B_MM
        w = c["u"] * b
        h = c["s"] * b
        eps_cf, _ = _suspended_stripline_ri(w, b, h, c["epsilon_r"])
        out.append({
            "u": c["u"], "s": c["s"], "epsilon_r": c["epsilon_r"],
            "eps_fd": c["eps_fd"], "eps_closed_form": eps_cf,
            "bias_rel": eps_cf / c["eps_fd"] - 1.0,
        })
    return out


def suspended_stripline_g3_fd_judge(
    w_mm: float = G3_W_MM,
    b_mm: float = G3_B_MM,
    h_mm: float = G3_H_MM,
    epsilon_r: float = G3_EPS_R,
    openems_eps_eff_clean: float = OPENEMS_EPS_EFF_CLEAN,
    openems_eps_eff_verdict: float = OPENEMS_EPS_EFF_VERDICT,
    openems_z0_ohm: float = OPENEMS_Z0_OHM,
    hfss_implied_eps_eff: float = HFSS_IMPLIED_EPS_EFF,
    hfss_implied_z0_ohm: float = HFSS_IMPLIED_Z0_OHM,
    run_cohn_tolerance: float = 5e-3,
) -> dict[str, Any]:
    """G3 精确点 FD 第三方仲裁（零仿真纯数值，铁律 7 确定性产出）。

    返回 JSON 安全 dict：fd（收敛阶梯+预声明门）、anchors（裁判资格三锚）、
    emulation（run 网格静流仿真 E1/E2/E3+z 空气隙假说分类）、three_way
    （四方对照）、attribution（偏差分解）。fd.status=INCOMPLETE 时如实降级
    （emulation/attribution 仍产出，verdict 字段=INCOMPLETE 不凑）。
    """
    eps_cf, z0_cf = _suspended_stripline_ri(w_mm, b_mm, h_mm, epsilon_r)
    lad = judge_ladder(w_mm=w_mm, b_mm=b_mm, h_mm=h_mm, eps_r=epsilon_r)
    anchors: dict[str, Any] = {
        "cohn_air_z0": cohn_air_anchor(w_mm=w_mm, b_mm=b_mm),
        "exact_limits": exact_limit_anchors(w_mm=w_mm, b_mm=b_mm,
                                            h_mm=h_mm, eps_r=epsilon_r),
    }
    anchors["cohn_air_z0"]["within_tolerance"] = (
        abs(anchors["cohn_air_z0"]["rel"]) <= run_cohn_tolerance)
    if lad.status == "CONVERGED":
        anchors["referee_cross_check"] = referee_cross_check(
            w_mm=w_mm, b_mm=b_mm, h_mm=h_mm, eps_r=epsilon_r,
            eps_self=lad.eps_eff)

    emulation: dict[str, Any] = {"cases": []}
    # refined 轴参考格宽 b/320（shake-down 实测：两级一阶外推后残余轴误差
    # ~3e-5，较最细档 b/1280 变化 <2e-5——对 ~1e-2 级偏移信号 100× 余量）
    d0_ref = b_mm / 320.0
    for xm, zm in (("run", "run"), ("refined", "run"), ("run", "refined")):
        emulation["cases"].append(run_mesh_emulation_eps_eff(
            lad.eps_eff, w_mm=w_mm, b_mm=b_mm, h_mm=h_mm, eps_r=epsilon_r,
            x_mode=xm, z_mode=zm, d0_refined_mm=d0_ref).as_dict())
    by_tag = {c["tag"]: c for c in emulation["cases"]}
    residual_clean = openems_eps_eff_clean / lad.eps_eff - 1.0
    residual_verdict = openems_eps_eff_verdict / lad.eps_eff - 1.0
    emulation["z_airgap_hypothesis"] = classify_z_airgap_hypothesis(
        residual_clean, by_tag["E2"]["shift_rel"], by_tag["E1"]["shift_rel"])

    three_way = {
        "closed_form": {"eps_eff": eps_cf, "z0_ohm": z0_cf,
                        "source": "_suspended_stripline_ri(0.52,0.50,0.05,11.9)"
                                  " 现场重算"},
        "fd_converged": {"eps_eff": lad.eps_eff, "z0_ohm": lad.z0_ohm,
                         "status": lad.status,
                         "source": "core.suspended_stripline_fd_judge 六级阶梯"
                                   "+三点 Richardson 外推"},
        "openems": {"eps_eff_clean": openems_eps_eff_clean,
                    "eps_eff_verdict": openems_eps_eff_verdict,
                    "z0_ohm": openems_z0_ohm,
                    "source": "qx9_anchor ssl_open 真跑（qx13 干净口谱）"},
        "hfss_implied": {"eps_eff": hfss_implied_eps_eff,
                         "z0_ohm": hfss_implied_z0_ohm,
                         "source": "外部实测锚（qx9 spec.md §1 引述）"},
    }
    bias = {
        "closed_form_vs_fd": eps_cf / lad.eps_eff - 1.0,
        "openems_clean_vs_fd": residual_clean,
        "openems_verdict_vs_fd": residual_verdict,
        "hfss_implied_vs_fd": hfss_implied_eps_eff / lad.eps_eff - 1.0,
        "closed_form_vs_openems_clean": eps_cf / openems_eps_eff_clean - 1.0,
        "fd_z0_vs_openems_zl": lad.z0_ohm / openems_z0_ohm - 1.0,
        "fd_z0_vs_closed_z0": lad.z0_ohm / z0_cf - 1.0,
    }
    attribution = {
        "closed_form_bias_rel": bias["closed_form_vs_fd"],
        "engine_residual_vs_fd_rel": residual_clean,
        "static_mesh_emulated_rel": by_tag["E1"]["shift_rel"],
        "z_axis_emulated_rel": by_tag["E2"]["shift_rel"],
        "x_axis_emulated_rel": by_tag["E3"]["shift_rel"],
        "static_mesh_share": (by_tag["E1"]["shift_rel"] / residual_clean
                              if residual_clean != 0.0 else None),
        "z_airgap_hypothesis": emulation["z_airgap_hypothesis"],
        "unattributed_rel": (residual_clean - by_tag["E1"]["shift_rel"]),
    }
    status = ("CONVERGED" if lad.status == "CONVERGED"
              and anchors["cohn_air_z0"]["within_tolerance"]
              else "INCOMPLETE")
    return {
        "seat": "Q-X20",
        "campaign": "aurora_q",
        "subject": "suspended_stripline G3 residual FD quasi-static arbitration",
        "point": {"w_mm": w_mm, "b_mm": b_mm, "h_mm": h_mm,
                  "epsilon_r": epsilon_r, "u": w_mm / b_mm, "s": h_mm / b_mm,
                  "u_outside_fit_domain": w_mm / b_mm > 1.0},
        "run_mesh_profile": {"z_lines_mm": list(RUN_Z_LINES_MM),
                             "z_air_gap_cells": 2,
                             "z_air_gap_cell_mm": 0.1125,
                             "x_near_mm": RUN_X_NEAR_MM,
                             "source": "qx9_anchor ssl_open simulation.py+audit"},
        "fd": lad.as_dict(),
        "anchors": anchors,
        "emulation": emulation,
        "three_way": three_way,
        "bias_rel": bias,
        "attribution": attribution,
        "status": status,
        "notes": [
            "FD=静流第三方裁判（零仿真）；不覆盖 FDTD 动态/Yee 差异/探针链"
            "系统差——attribution.unattributed_rel 为静态网格仿真外余项",
            "z 假说分类阈值预声明冻结：share≥0.60 CONFIRMED / ≥0.25 PARTIAL"
            " / 其余 REFUTED（classify_z_airgap_hypothesis 常量）",
        ],
    }


def attribution_one_liner(result: dict[str, Any]) -> str:
    """人读一句话定论（报告/交付面消费；纯拼装不含数值计算）。"""
    att = result["attribution"]
    hyp = att["z_airgap_hypothesis"]
    return (
        f"闭式对 FD 真值偏 {att['closed_form_bias_rel']*100:+.2f}%；"
        f"openEMS 干净口对 FD 残余 {att['engine_residual_vs_fd_rel']*100:+.2f}%，"
        f"其中静态网格离散仿真 {att['static_mesh_emulated_rel']*100:+.2f}%"
        f"（占比 {att['static_mesh_share']*100:.0f}%，z 轴 "
        f"{att['z_axis_emulated_rel']*100:+.2f}%）；"
        f"z 空气隙假说={hyp['verdict']}"
        f"（share={hyp.get('share', 0.0)*100:.0f}%）；"
        f"静态仿真外余项 {att['unattributed_rel']*100:+.2f}%")
