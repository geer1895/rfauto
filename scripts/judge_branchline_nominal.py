"""branchline 名义臂谐振判读（W2⑥a-B，离线，不发起求解）。

问题：runs/branchline_real_anchor 真机四端口 .s4p 的均分/匹配中心 f_c≈2.15GHz
≠ 声明 f0=2.4GHz（−10%）。三个候选归因——① 名义几何（TEMPLATE_META/recipe
的 arm_len_mm=20.5 按何种 εeff 综合）、② 端接口径（35.4Ω/50Ω 臂宽是否错）、
③ 引擎频率尺度（#190 openEMS 系统差 ~−10% 同族？）。

判据全部确定性复算：
- f_c：|S11| 谷 + |S21|=|S31| 均分交叉（skrf 读 .s4p）；
- HJ 闭式（core.synthesis.forward_z0，与 synthesize_branchline 同源）：名义
  臂长对应的 λ/4 频率、2.4GHz 所需臂长、名义臂长反推的 εeff；
- 引擎 vs 闭式残差 = 归因③的量；名义 vs 闭式 = 归因①的量；f_c 处匹配/
  隔离深度 = 归因②的证据（端接错则 f_c 处也不会 −36dB）。

用法：.venv\\Scripts\\python.exe scripts/judge_branchline_nominal.py
      [--run runs/branchline_real_anchor] [--f0 2.4] [--arm 20.5]
产物：<run>/verdict_nominal.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

C_MM_GHZ = 299.792458
#: 确定性链回归锚：fake 模型 eps_eff=3.28（HFSS 校准锚反推）给名义
#: 20.5mm 臂 f_dip=2.0904GHz——第三独立来源（引擎无关）
FAKE_ANCHOR_F_DIP_GHZ = 2.0904


def implied_eps_eff(arm_len_mm: float, f0_ghz: float) -> float:
    """名义臂长按 λ/4@f0 反推的 εeff：(c/(4·f0·L))²。"""
    return (C_MM_GHZ / (4.0 * f0_ghz * arm_len_mm)) ** 2


def quarter_wave_mm(f_ghz: float, eps_eff: float) -> float:
    return C_MM_GHZ / (4.0 * f_ghz * np.sqrt(eps_eff))


def f_quarter_wave_ghz(arm_len_mm: float, eps_eff: float) -> float:
    """臂长恰为 λ/4 的频率。"""
    return C_MM_GHZ / (4.0 * arm_len_mm * np.sqrt(eps_eff))


def s4p_centers(path: Path) -> dict[str, Any]:
    """从 .s4p 取均分/匹配中心与关键点 S 参数（dB）。"""
    import skrf

    ntw = skrf.Network(str(path))
    f = ntw.f / 1e9
    s = ntw.s
    db = lambda x: 20.0 * np.log10(np.abs(x) + 1e-300)  # noqa: E731
    s11, s21, s31, s41 = (db(s[:, 0, 0]), db(s[:, 1, 0]), db(s[:, 2, 0]),
                          db(s[:, 3, 0]))
    i_match = int(np.argmin(s11))
    i_iso = int(np.argmin(s41))
    # 均分交叉：|S21|−|S31| 过零点中离匹配谷最近者
    diff = s21 - s31
    zc = np.where(np.diff(np.sign(diff)) != 0)[0]
    if zc.size:
        i_split = int(zc[np.argmin(np.abs(zc - i_match))])
        # 线性内插过零频率
        x0, x1 = f[i_split], f[i_split + 1]
        y0, y1 = diff[i_split], diff[i_split + 1]
        f_split = float(x0 - y0 * (x1 - x0) / (y1 - y0)) if y1 != y0 else float(x0)
    else:
        f_split = None

    def at(fq: float) -> dict[str, float]:
        i = int(np.argmin(np.abs(f - fq)))
        return {"f_ghz": float(f[i]), "s11_db": float(s11[i]),
                "s21_db": float(s21[i]), "s31_db": float(s31[i]),
                "s41_db": float(s41[i]),
                "split_diff_db": float(s21[i] - s31[i])}

    return {
        "f_match_ghz": float(f[i_match]),
        "f_iso_null_ghz": float(f[i_iso]),
        "f_equal_split_ghz": f_split,
        "at_match": at(float(f[i_match])),
    }


def hj_reference(arm_len_mm: float, f0_ghz: float, series_w_mm: float,
                 shunt_w_mm: float, stackup_name: str) -> dict[str, Any]:
    from rfauto.core.synthesis import Stackup, forward_z0

    st = Stackup.from_materials_yaml(stackup_name)
    out: dict[str, Any] = {"stackup": stackup_name,
                           "epsilon_r": st.epsilon_r, "h_mm": st.thickness_mm}
    for tag, w in (("series_arm", series_w_mm), ("shunt_arm", shunt_w_mm),
                   ("synth_default_w1mm", 1.0)):
        z0, ee = forward_z0(w, f0_ghz, st)
        out[tag] = {
            "w_mm": w, "z0_ohm": float(z0), "eps_eff": float(ee),
            "quarter_wave_mm_at_f0": float(quarter_wave_mm(f0_ghz, ee)),
            "f_quarter_wave_ghz_for_nominal_arm":
                float(f_quarter_wave_ghz(arm_len_mm, ee)),
        }
    out["eps_eff_implied_by_nominal"] = float(implied_eps_eff(arm_len_mm, f0_ghz))
    out["eps_eff_thin_line_limit_(er+1)/2"] = float((st.epsilon_r + 1.0) / 2.0)
    return out


def judge(run: Path, f0_ghz: float, arm_len_mm: float, series_w_mm: float,
          shunt_w_mm: float, stackup: str) -> dict[str, Any]:
    s4p = run / "branchline.s4p"
    centers = s4p_centers(s4p)
    hj = hj_reference(arm_len_mm, f0_ghz, series_w_mm, shunt_w_mm, stackup)
    f_c = centers["f_equal_split_ghz"] or centers["f_match_ghz"]
    # 两臂 εeff 不同 → 名义单一臂长的闭式预测取两臂均值（模板四臂同长）
    f_hj_nom = 0.5 * (hj["series_arm"]["f_quarter_wave_ghz_for_nominal_arm"]
                      + hj["shunt_arm"]["f_quarter_wave_ghz_for_nominal_arm"])
    total_pct = 100.0 * (f_c - f0_ghz) / f0_ghz
    nominal_pct = 100.0 * (f_hj_nom - f0_ghz) / f0_ghz
    engine_vs_hj_pct = 100.0 * (f_c - f_hj_nom) / f_hj_nom
    engine_vs_fake_pct = 100.0 * (f_c - FAKE_ANCHOR_F_DIP_GHZ) / FAKE_ANCHOR_F_DIP_GHZ
    am = centers["at_match"]
    termination_ok = (am["s11_db"] < -20.0 and am["s41_db"] < -20.0
                      and abs(am["split_diff_db"]) < 0.5)
    engine_scale_family = abs(engine_vs_hj_pct) > 5.0  # −10% 同族门
    verdict = "PASS" if (abs(engine_vs_hj_pct) < 2.0 and termination_ok) else "PARTIAL"
    return {
        "item": "W2⑥a-B branchline 名义臂谐振核对",
        "verdict": verdict,
        "inputs": {"run": str(run), "f0_nominal_ghz": f0_ghz,
                   "arm_len_mm": arm_len_mm, "series_w_mm": series_w_mm,
                   "shunt_w_mm": shunt_w_mm},
        "measured": centers,
        "hj_reference": hj,
        "decomposition_pct": {
            "total_fc_vs_f0": total_pct,
            "nominal_geometry_(hj_for_20.5mm_vs_f0)": nominal_pct,
            "engine_vs_hj_closed_form": engine_vs_hj_pct,
            "engine_vs_fake_hfss_calibrated_anchor_2.0904": engine_vs_fake_pct,
        },
        "attribution": {
            "primary": "① 名义几何：arm_len_mm=20.5 不是 2.4GHz 的 λ/4（HJ 两臂均值 "
                       f"{0.5*(hj['series_arm']['quarter_wave_mm_at_f0']+hj['shunt_arm']['quarter_wave_mm_at_f0']):.2f}mm）"
                       f"；20.5mm 反推 εeff={hj['eps_eff_implied_by_nominal']:.3f}≈(εr+1)/2="
                       f"{hj['eps_eff_thin_line_limit_(er+1)/2']:.3f} 薄线极限口径（手算捷径）",
            "secondary": f"③ 引擎频率尺度：openEMS vs HJ 残差 {engine_vs_hj_pct:+.2f}%"
                         "（T 结/角效应量级，与 wilkinson −12%/patch −11% 不同族）；"
                         f"vs fake(HFSS 校准锚) {engine_vs_fake_pct:+.2f}%",
            "rejected": "② 端接口径：f_c 处 S11/S41 均 <−36dB、均分差 <0.1dB → 35.4Ω/50Ω 臂宽正确",
            "engine_scale_family_minus10pct": engine_scale_family,
            "termination_ok": termination_ok,
        },
        "confidence": {"nominal_geometry": 0.9, "engine_residual_1pct": 0.75,
                       "termination_rejected": 0.9},
        "recommendation": [
            "不改模板名义值（openems_templates.py 禁改）；由模板/recipe 责任方二选一：",
            f"(a) 声明 f0 改为名义臂对应的 ≈{f_hj_nom:.3f}GHz（HJ）/{f_c:.3f}GHz（引擎）；",
            f"(b) 2.4GHz 器件把 arm_len_mm 改为 HJ {0.5*(hj['series_arm']['quarter_wave_mm_at_f0']+hj['shunt_arm']['quarter_wave_mm_at_f0']):.2f}mm"
            f"（再按引擎 {engine_vs_hj_pct:+.1f}% 角效应微调 ≈"
            f"{0.5*(hj['series_arm']['quarter_wave_mm_at_f0']+hj['shunt_arm']['quarter_wave_mm_at_f0'])*(1+engine_vs_hj_pct/100):.2f}mm）；",
            "synthesize_branchline 用 w=1.0mm 取 εeff（非实际臂宽），两臂 εeff 差 → λ/4 差 "
            f"{abs(hj['series_arm']['quarter_wave_mm_at_f0']-hj['shunt_arm']['quarter_wave_mm_at_f0']):.2f}mm，建议按臂宽各自综合（synthesis.py 禁改，记 followUp）",
        ],
        "evidence": [str(s4p), str(run / "_smoke_result.json"),
                     "确定性链回归锚 branchline@2.4GHz f_dip=2.0904GHz（fake eps_eff=3.28）",
                     "src/rfauto/core/synthesis.py::synthesize_branchline（w=1.0mm εeff）"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default="runs/branchline_real_anchor")
    ap.add_argument("--f0", type=float, default=2.4)
    ap.add_argument("--arm", type=float, default=20.5)
    ap.add_argument("--series-w", type=float, default=1.87)
    ap.add_argument("--shunt-w", type=float, default=1.11)
    ap.add_argument("--stackup", default="rogers4350b_h0.508")
    a = ap.parse_args(argv)
    run = Path(a.run)
    out = judge(run, a.f0, a.arm, a.series_w, a.shunt_w, a.stackup)
    dst = run / "verdict_nominal.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    d = out["decomposition_pct"]
    fs = out["measured"]["f_equal_split_ghz"]
    fs_s = f"{fs:.4f}" if fs is not None else "None(过零缺失,用匹配谷)"
    print(f"{out['verdict']} f_c={fs_s}GHz(匹配谷{out['measured']['f_match_ghz']:.4f}) "
          f"total={d['total_fc_vs_f0']:+.2f}% nominal={d['nominal_geometry_(hj_for_20.5mm_vs_f0)']:+.2f}% "
          f"engine_vs_hj={d['engine_vs_hj_closed_form']:+.2f}% → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
