#!/usr/bin/env python3
"""从 openEMS 参考曲线推导 fake 联合校准锚（A1）。

读取 knowledge/reference/openems_nominal/<tpl>_s11.csv，按结构物理公式：
- wilkinson（λ/4）：eps_eff = (c/(4·L·f_res))²
- patch（λ/2）：eps_eff = (c/(2·L·f_res))²
输出 configs/fake_calibration.yaml 建议值（s11_floor_db 取带内最深点；
s11_edge_scale 取带边幅值 / sin(θ_band_edge)）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

C_MM_GHZ = 299.792458
TEMPLATE_GEOM = {
    "wilkinson": {"mode": "lambda4", "len_param": "arm_len_mm", "len_mm": 18.4},
    "patch": {"mode": "lambda2", "len_param": "patch_len_mm", "len_mm": 34.9},
}
TEMPLATE_F0 = {"wilkinson": 2.5, "patch": 2.4}


def derive(template: str, ref_dir: Path) -> dict:
    geo = TEMPLATE_GEOM[template]
    f0 = TEMPLATE_F0[template]
    path = ref_dir / f"{template}_s11.csv"
    lines = path.read_text(encoding="utf-8").strip().splitlines()[1:]
    data = np.array([[float(x) for x in ln.split(",")] for ln in lines])
    f, s11 = data[:, 0], data[:, 1]

    # 谐振点 = 带内最深点；窗口与验收口径一致（f0±5%，同 template_deviation_report）
    band = (f >= f0 * 0.95) & (f <= f0 * 1.05)
    i_res = int(np.argmin(np.where(band, s11, 0)))
    f_res = float(f[i_res])
    floor_db = float(s11[i_res])

    # eps_eff 反演
    if geo["mode"] == "lambda4":
        eps_eff = (C_MM_GHZ / (4 * geo["len_mm"] * f_res)) ** 2
    else:
        eps_eff = (C_MM_GHZ / (2 * geo["len_mm"] * f_res)) ** 2

    # 带边斜率：|S11(f0+5%带宽)| / sin(θ@f0±5%)
    f_edge = f_res * 1.05
    j = int(np.argmin(np.abs(f - f_edge)))
    theta = np.pi / 2 * (f[j] / f_res)
    s_edge = 10 ** (s11[j] / 20)
    edge_scale = s_edge / max(abs(float(np.sin(theta))), 1e-3)

    return {
        "template": template,
        "f_res_ghz": round(f_res, 4),
        "eps_eff": round(eps_eff, 3),
        "s11_floor_db": round(floor_db, 2),
        "s11_edge_scale": round(edge_scale, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive fake calibration from openEMS reference")
    parser.add_argument("--ref-dir", default="knowledge/reference/openems_nominal")
    parser.add_argument("--out", default="configs/fake_calibration.yaml")
    args = parser.parse_args()

    ref_dir = Path(args.ref_dir)
    results = {t: derive(t, ref_dir) for t in ("wilkinson", "patch")}
    print(json.dumps(results, indent=2, ensure_ascii=False))

    yaml_text = (
        "# fake 联合校准锚（自动推导：scripts/derive_fake_calibration.py）\n"
        "# 数据源：knowledge/reference/openems_nominal/（多模态审计后的正确拓扑，\n"
        "# openEMS 0.5mm 网格真跑）；修模型 → 再校准。\n"
        "models:\n"
        + "".join(
            f"  {t}:\n"
            f"    eps_eff: {r['eps_eff']}          # 由 f_res={r['f_res_ghz']}GHz 反演\n"
            f"    s11_floor_db: {r['s11_floor_db']}\n"
            f"    s11_edge_scale: {r['s11_edge_scale']}\n"
            for t, r in results.items()
        )
    )
    Path(args.out).write_text(yaml_text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
