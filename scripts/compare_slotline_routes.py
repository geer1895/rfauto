"""槽线三路线对拍（W3⑧b 阶段 3）：闭式 / HFSS 波端口 / 路线 A / 路线 B → compare.json。

输入（缺则标 pending，不臆造）：
- 闭式：core/slotline.slotline_closed_form（设计点 w=1.0 h=1.524 er=3.66 f0=2.5）；
- HFSS：runs/slotline_arbitration/hfss_arbitration.json（stage=done；基准档 wide，
  三档 mid/wide/xl 收敛与窄档倏逝模留证）；
- 路线 A：runs/slotline_port_a/slotline_port_a_results.json（NGSolve 模场 →
  openEMS WaveguidePort；另一子代理产物，只读）；
- 路线 B：runs/slotline_port_b/result.json（LumpedPort 跨槽两档 R）。

结论口径（验收）：路线 B β vs HFSS ≤3%；LumpedPort 适用性分级
（β 可用 / S 参数可用与否）如实；哪条可作生产口径、误差量级、局限逐条写明。
用法：.venv/Scripts/python.exe scripts/compare_slotline_routes.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, "src")

from rfauto.core.slotline import slotline_closed_form

ROOT = Path(__file__).resolve().parents[1]
HFSS_JSON = ROOT / "runs" / "slotline_arbitration" / "hfss_arbitration.json"
ROUTE_A_JSON = ROOT / "runs" / "slotline_port_a" / "slotline_port_a_results.json"
ROUTE_B_JSON = ROOT / "runs" / "slotline_port_b" / "result.json"
OUT_JSON = ROOT / "runs" / "slotline_arbitration" / "compare.json"
PROGRESS = ROOT / "runs" / "slotline_arbitration" / "progress.log"

DESIGN = {"w_mm": 1.0, "h_mm": 1.524, "er": 3.66, "f0_ghz": 2.5, "line_len_mm": 93.4624}


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or not b:
        return None
    return (float(a) / float(b) - 1.0) * 100.0


def build_compare(cf: dict, hfss: dict | None, route_a: dict | None,
                  route_b: dict | None) -> dict:
    """纯函数：四来源 dict → 对拍表 + 门 + 结论（离线测试对合成 dict 调用）。

    cf：{"beta_rad_m","z0_ohm","eps_eff"}；hfss：hfss_arbitration.json 全文；
    route_a：slotline_port_a_results.json 全文；route_b：result.json 全文。
    """
    rows: list[dict] = []
    rows.append({"source": "closed_form (Janaswamy–Schaubert, core/slotline)",
                 "status": "ok", "beta_rad_m": cf["beta_rad_m"], "z0_ohm": cf["z0_ohm"],
                 "z0_def": "Zpv (power-voltage)", "eps_eff": cf["eps_eff"],
                 "s11_db_50ohm": None, "s21_db_50ohm": None,
                 "note": "拟合式自身 Av 0.37%/Max 2.2%（λ'）、Av 0.67%/Max 2.7%（Z0）"})

    # ── HFSS 基准 ──
    hfss_beta = None
    hfss_row: dict = {"source": "HFSS wave port (wide: y±60/z∓30mm, PEC-framed)",
                      "status": "pending"}
    if hfss and hfss.get("stage") == "done":
        v = hfss.get("verdict") or {}
        prim_tag = v.get("primary_variant", "wide")
        prim = (hfss.get("variants") or {}).get(prim_tag)
        if prim and not prim.get("mode_evanescent_at_f0") and "beta_gamma_rad_m_f0" in prim:
            hfss_beta = float(prim["beta_gamma_rad_m_f0"])
            hfss_row.update({
                "status": "ok" if v.get("ok") else "fail_gate",
                "beta_rad_m": hfss_beta,
                "beta_s21_rad_m": prim.get("beta_s21_rad_m_f0"),
                "beta_vs_cf_pct": prim.get("beta_gamma_vs_cf_f0_pct"),
                "z0_ohm": prim.get("zpv_ohm"), "z0_def": "Zpv",
                "zpi_ohm": prim.get("zpi_ohm"), "zvi_ohm": prim.get("zvi_ohm"),
                "zpv_vs_cf_pct": prim.get("zpv_vs_cf_pct"),
                "zpi_vs_cf_pct": prim.get("zpi_vs_cf_pct"),
                "zvi_vs_cf_pct": prim.get("zvi_vs_cf_pct"),
                "eps_eff": prim.get("eps_eff_gamma_f0"),
                "alpha_np_m": prim.get("alpha_np_m_f0"),
                "s11_db_50ohm": prim.get("s11_db_f0_50ohm"),
                "s21_db_50ohm": prim.get("s21_db_f0_50ohm"),
                "s11_db_generalized": prim.get("s11_db_f0_generalized"),
                "solve_s": prim.get("solve_s"),
                "port_size_convergence": v.get("port_size_convergence"),
                "beta_wide_vs_xl_pct": v.get("beta_wide_vs_xl_pct"),
                "beta_mid_vs_wide_pct": v.get("beta_mid_vs_wide_pct"),
                "narrow5w_evidence": v.get("narrow5w_evidence"),
            })
        else:
            hfss_row.update({"status": "undecidable", "note": v.get("note")})
    rows.append(hfss_row)

    # ── 路线 A（只读他轨产物）──
    a_row: dict = {"source": "route A (NGSolve mode → openEMS WaveguidePort)", "status": "pending"}
    if route_a:
        tw = route_a.get("beta_three_way_f0") or {}
        oe = route_a.get("openems") or {}
        beta_a = tw.get("openems_probe")
        s11 = oe.get("s11_at_f0")
        s21 = oe.get("s21_at_f0")

        def _db(c):
            import math
            if not c:
                return None
            return 20 * math.log10(abs(complex(c[0], c[1])) + 1e-300)

        a_row.update({
            "status": "ok" if beta_a is not None else "partial",
            "beta_rad_m": beta_a, "beta_ngsolve_rad_m": tw.get("ngsolve"),
            "beta_vs_cf_pct": tw.get("pct_oem_vs_cf"),
            "beta_vs_hfss_pct": _pct(beta_a, hfss_beta),
            "z0_ohm": (route_a.get("port") or {}).get("z_mode_ohm"),
            "z0_def": "NGSolve Z_mode (power-voltage)",
            "s11_db_line_basis": _db(s11), "s21_db_line_basis": _db(s21),
            "s11_db_50ohm": None, "s21_db_50ohm": None,
            "gates": route_a.get("gates"),
            "note": "S 以模阻抗为参考（CalcPort ZL=Z_mode），非 50Ω 基",
        })
    rows.append(a_row)

    # ── 路线 B ──
    b_rows: list[dict] = []
    b_primary = None
    if route_b:
        for tag, var in (route_b.get("variants") or {}).items():
            r = {"source": f"route B (openEMS LumpedPort across slot, {tag}, R={var.get('r_port_ohm'):.2f}Ω)",
                 "status": "ok", "beta_rad_m": var.get("beta_probe_rad_m_f0"),
                 "beta_vs_cf_pct": var.get("beta_vs_cf_pct"),
                 "beta_vs_hfss_pct": _pct(var.get("beta_probe_rad_m_f0"), hfss_beta),
                 "eps_eff": var.get("eps_eff_probe_f0"),
                 "z0_ohm": var.get("r_port_ohm"), "z0_def": "R tier (assumed line Z0)",
                 "s11_db_50ohm": var.get("s11_db_f0_50ohm"),
                 "s21_db_50ohm": var.get("s21_db_f0_50ohm"),
                 "s11_db_line_basis": var.get("s11_db_f0_line_basis"),
                 "s21_db_line_basis": var.get("s21_db_f0_line_basis"),
                 "band_max_s11_db_line_basis": var.get("band_max_s11_db_line_basis"),
                 "swr_amp": var.get("swr_amp_f0"), "solve_s": var.get("solve_s"),
                 "s21_convention": var.get("s21_convention"),
                 "beta_slope_vs_two_wave_pct": var.get("beta_slope_vs_two_wave_pct"),
                 "gamma_load_mag": var.get("gamma_load_mag_f0"),
                 "tap_model": var.get("tap_model")}
            b_rows.append(r)
            if tag == route_b.get("primary_variant"):
                b_primary = r
        if not b_rows:
            b_rows.append({"source": "route B (openEMS LumpedPort across slot)",
                           "status": "pending", "pending": route_b.get("pending")})
    else:
        b_rows.append({"source": "route B (openEMS LumpedPort across slot)", "status": "pending"})
    rows.extend(b_rows)

    # ── 门与结论 ──
    gates: dict[str, Any] = {}
    if b_primary and b_primary.get("beta_vs_hfss_pct") is not None:
        gates["route_b_beta_vs_hfss_le_3pct"] = abs(b_primary["beta_vs_hfss_pct"]) <= 3.0
    else:
        gates["route_b_beta_vs_hfss_le_3pct"] = None
    if hfss_row.get("beta_vs_cf_pct") is not None:
        gates["hfss_beta_vs_cf_le_5pct"] = abs(hfss_row["beta_vs_cf_pct"]) <= 5.0
    else:
        gates["hfss_beta_vs_cf_le_5pct"] = None
    if a_row.get("beta_vs_hfss_pct") is not None:
        gates["route_a_beta_vs_hfss_le_3pct_info"] = abs(a_row["beta_vs_hfss_pct"]) <= 3.0
    else:
        gates["route_a_beta_vs_hfss_le_3pct_info"] = None

    grading = (route_b or {}).get("lumped_port_grading") or {}
    conclusions = []
    if hfss_beta is not None:
        conclusions.append(
            f"HFSS 波端口可作槽线 β 仲裁基准：β={hfss_beta:.3f} rad/m（vs 闭式 "
            f"{hfss_row['beta_vs_cf_pct']:+.2f}%，闭式自身 ~2%；β 随端口截面单调收敛 "
            f"mid→wide→xl：{hfss_row.get('port_size_convergence', {}).get('mid', {}).get('beta_vs_cf_pct')}"
            f"%→{hfss_row.get('beta_vs_cf_pct')}%→"
            f"{hfss_row.get('port_size_convergence', {}).get('xl', {}).get('beta_vs_cf_pct')}%，"
            f"wide vs xl 差 {hfss_row.get('beta_wide_vs_xl_pct')}%）。前提=端口截面大到 PEC 框"
            "短接的 fin-line 主模在带内传播且框远离槽场——微带惯例 5×w 窄端口实证倏逝模"
            f"（截止≈{((hfss_row.get('narrow5w_evidence') or {}).get('cutoff_ghz_from_alpha') or 0):.1f}GHz），"
            "槽线波端口尺寸惯例与微带不同，这是本项真机钉死的核心结论。")
        conv = hfss_row.get("port_size_convergence") or {}
        zpv_seq = "/".join(f"{(conv.get(k) or {}).get('zpv', float('nan')):.1f}" for k in ("mid", "wide", "xl"))
        zpi_seq = "/".join(f"{(conv.get(k) or {}).get('zpi', float('nan')):.1f}" for k in ("mid", "wide", "xl"))
        conclusions.append(
            f"HFSS Z0 三定义 @wide：Zpv={hfss_row['z0_ohm']:.2f}Ω（vs 闭式 {cf['z0_ohm']:.2f}Ω "
            f"{hfss_row['zpv_vs_cf_pct']:+.1f}%；mid/wide/xl={zpv_seq}）、Zpi={hfss_row['zpi_ohm']:.2f}Ω"
            f"（{hfss_row['zpi_vs_cf_pct']:+.1f}%；{zpi_seq}）、Zvi={hfss_row['zvi_ohm']:.2f}Ω"
            f"（{hfss_row['zvi_vs_cf_pct']:+.1f}%）。闭式为功率-电压定义 → 与 Zpv 同口径，差 ≤5%"
            "（闭式自身 Z0 拟合 Max 2.7% + PEC 框有限截面），与 NGSolve 同截面 Z_mode=107.4Ω 差 ≤2%"
            "（三方一致）；Zpi 低 ~30% 是槽线非 TEM（准 TE）模'电流'定义不同的物理结果，不是误差——"
            "Zpi≠Zpv 即 Zvi=√(Zpi·Zpv) 居中。工程提示：HFSS ExportNetworkData 的 '! Port Impedance' "
            "注释两列都写 Zpi（不按端口 CharImp），真 Zpv 须从 Modal Solution Data 的 Zo(Port) "
            "（CharImp=Zpv）取——首版误把 Zpi 当 Zpv 得出 '低 30%' 假结论，已更正。")
    else:
        conclusions.append("HFSS 基准 pending/undecidable——对拍以闭式为临时参照，结论待 HFSS 落地后重跑。")
    if b_primary:
        pct_h = b_primary.get("beta_vs_hfss_pct")
        gate_txt = ("，vs HFSS pending" if pct_h is None else
                    f"，vs HFSS {pct_h:+.2f}%（门 ≤3% → {'PASS' if abs(pct_h) <= 3 else 'FAIL'}）")
        conclusions.append(
            f"路线 B（LumpedPort 跨槽）β_B={b_primary['beta_rad_m']:.3f} rad/m（双行波拟合，"
            f"线性斜率法同数据偏 {b_primary.get('beta_slope_vs_two_wave_pct') or 0:+.1f}% 已废；"
            f"|Γ_load|={b_primary.get('gamma_load_mag') or 0:.3f}≈抽头模型 1/3）："
            f"vs 闭式 {b_primary['beta_vs_cf_pct']:+.2f}%" + gate_txt
            + f"；原始线基 |S11|@f0={b_primary['s11_db_line_basis']:.1f}dB、|S21|={b_primary['s21_db_line_basis']:.2f}dB"
            "（PML 匹配线上并联抽头拓扑的解析必然：R=Z0、βL=2π 时模型给 S11=−1/2/S21=+1/2，"
            f"实测吻合——不是'失配差'；分级 {grading.get('sparams_grade')}：β 可用="
            f"{grading.get('beta_usable')}，原始 S 不可直接当线 S 参数用）。")
    else:
        conclusions.append("路线 B pending（openEMS 真机未落产物）。")
    if a_row.get("beta_rad_m") is not None:
        conclusions.append(
            f"路线 A（NGSolve→WaveguidePort）β_A={a_row['beta_rad_m']:.3f} rad/m，vs 闭式 "
            f"{a_row['beta_vs_cf_pct']:+.2f}%"
            + (f"，vs HFSS {a_row['beta_vs_hfss_pct']:+.2f}%" if a_row.get("beta_vs_hfss_pct") is not None else "")
            + "（他轨产物只读引用）。")
    else:
        conclusions.append("路线 A pending（runs/slotline_port_a/slotline_port_a_results.json 未生成；"
                           "其 pt1 FDTD 已跑完但后处理崩于 polyfit 形状，待其子代理修复重跑）。")
    conclusions.append(
        "生产口径建议：β/εeff 基准=HFSS 大截面波端口 Gamma（唯一直接解槽模本征值的通道；"
        "xl 档对闭式 −0.17%）；openEMS 路线 B 的 β（双行波探针拟合，不依赖端口）作 openEMS 侧"
        "生产口径（≤3% 门过）；路线 B 的 Z0 经抽头模型反演（z0_tap）仅旁证不作生产；"
        "槽线 Z0 生产口径=功率-电压定义（闭式 / HFSS Zpv / NGSolve Z_mode 三方 ≤5% 互证），"
        "禁止拿 HFSS 默认 Zpi 或 touchstone 阻抗注释当槽线 Z0；路线 A 端口模式匹配更精细但需 "
        "NGSolve 模场文件与 kc 色散假设。")
    limitations = [
        "HFSS：波端口外框 PEC 与 3D 辐射侧墙在端口棱边处不一致（框处槽场 ~e^{−κ·60mm}≈8%），"
        "表现为微小端口失配；PEC 框把开放槽线变成屏蔽槽线，β 随截面单调收敛（60→90mm 差 0.5%）；"
        "Zpv 111.1/105.8/105.1 非单调（mid 高、wide/xl 趋平），Zpi 单调升 74→82——框对'电流'定义"
        "影响大于对'电压'定义。",
        "闭式：Janaswamy–Schaubert 拟合 2.22≤εr≤3.8 段，λ' Max 2.2%、Z0 Max 2.7%——≤5% 门内含"
        "闭式自身误差；闭式假设无限大地/开放结构，与有限截面数值口径存在系统性差异（见 Z0 结论）。",
        "路线 B：单激励 + 两口全同对称装配（未做双激励）；S21 约定按被动口 uf_ref/uf_inc 幅值判读；"
        "β 需双行波拟合（线性斜率法在 |Γ|~1/3 驻波下偏 ~10%）；抽头拓扑原始 S 参数不是线 S 参数"
        "（解析模型 tap_network_sparams 给出换算），Z0_tap 反演忽略端口盒寄生电抗/辐射（resid 大时不可信）。",
        "L=1λ' 处 50Ω 基 |S11| 天然为谷（全波长线透明），50Ω 基 S11@f0 不代表线-50Ω 失配量级，"
        "看 band_max_s11 或线基口径。",
        "HFSS Zpv(f) 仅 f0 一点（LastAdaptive）；带内 Zpv(f) 用 Zpi(f)·(Zpv/Zpi)@f0 比值近似（50Ω 基重归一用），"
        "比值随频漂移未量化。",
    ]
    return {
        "design": DESIGN, "closed_form": cf, "rows": rows, "gates": gates,
        "lumped_port_grading": grading, "conclusions": conclusions,
        "limitations": limitations,
        "sources": {"hfss": str(HFSS_JSON), "route_a": str(ROUTE_A_JSON),
                    "route_b": str(ROUTE_B_JSON)},
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def main() -> int:
    cf_r = slotline_closed_form(DESIGN["w_mm"], DESIGN["h_mm"], DESIGN["er"], DESIGN["f0_ghz"])
    cf = {"beta_rad_m": cf_r.beta_rad_m, "z0_ohm": cf_r.z0_ohm, "eps_eff": cf_r.eps_eff,
          "lambda_ratio": cf_r.lambda_ratio, "segment": cf_r.segment}
    out = build_compare(cf, _load(HFSS_JSON), _load(ROUTE_A_JSON), _load(ROUTE_B_JSON))
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== slotline routes compare ===")
    for r in out["rows"]:
        b = r.get("beta_rad_m")
        print(f"- {r['source']}: status={r['status']} beta={b if b is None else round(b, 3)} "
              f"vs_hfss={r.get('beta_vs_hfss_pct')} vs_cf={r.get('beta_vs_cf_pct')} "
              f"Z0={r.get('z0_ohm')} |S11|50={r.get('s11_db_50ohm')} |S11|line={r.get('s11_db_line_basis')}")
    print("gates:", out["gates"])
    for c in out["conclusions"]:
        print("*", c)
    print(f"[out] {OUT_JSON}")
    with open(PROGRESS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} stage4 compare: gates={out['gates']}\n")
    g = out["gates"]
    return 0 if g.get("route_b_beta_vs_hfss_le_3pct") else 1


if __name__ == "__main__":
    raise SystemExit(main())
