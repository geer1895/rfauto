r"""D1 色散材料库演示：扫频打印 RO4350B 的 εr(f)/tanδ(f) 与微带 εeff(f)。

数据源 = configs/materials.yaml 的 dispersion 条目（datasheet 单点 + D-S 因果
拟合），纯解析求值，**不调用任何 EM solver**（真机 openEMS 宽带 mline 冒烟需
后台 + 日志轮询且可跳过）。

用法：
    .venv\Scripts\python.exe scripts/dispersion_demo.py

输出：D-S 拟合参数、基板 εr(f)/tanδ(f) 表、K-K 残差、微带 εeff(f) 表与
openEMS 材料导出摘要。
"""

from __future__ import annotations

import numpy as np

from rfauto.core.dispersion import kramers_kronig_residual, load_dispersion_material

MATERIAL = "rogers4350b_h0.508_dispersion"
SCAN_GHZ = np.array([1.0, 2.4, 5.0, 10.0, 20.0, 30.0, 40.0])
MICROSTRIP_WIDTH_MM = 1.113
MICROSTRIP_H_MM = 0.508


def substrate_table(model) -> None:
    """基板 εr(f)/tanδ(f) 表（D-S 解析求值）。"""
    freqs = SCAN_GHZ * 1.0e9
    eps_r = np.real(np.asarray(model.epsilon_r(freqs)))
    tand = np.asarray(model.loss_tangent(freqs))
    print(f"[RO4350B D-S] epsInf={model.eps_inf:.6f} deltaEps={model.delta_eps:.6f} "
          f"f1={model.f1_hz:.4g} Hz f2={model.f2_hz:.4g} Hz")
    print("   f/GHz     eps_r      tanD")
    for f_ghz, er, td in zip(SCAN_GHZ, eps_r, tand, strict=True):
        print(f"  {f_ghz:6.2f}  {er:8.4f}  {td:9.6f}")
    residual = np.max(np.asarray(kramers_kronig_residual(model, freqs)))
    print(f"  max Kramers-Kronig relative residual over scan: {residual:.3e}")


def microstrip_table(model) -> None:
    """微带线 εeff(f) 表（skrf Hammerstad-Jensen，色散基板）。"""
    import skrf

    freqs = SCAN_GHZ * 1.0e9
    freq = skrf.Frequency(SCAN_GHZ[0], SCAN_GHZ[-1], len(SCAN_GHZ), unit="GHz")
    mline = skrf.media.MLine(
        frequency=freq,
        w=MICROSTRIP_WIDTH_MM * 1e-3,
        h=MICROSTRIP_H_MM * 1e-3,
        ep_r=np.asarray(model.epsilon_r(freqs)),
        tand=np.asarray(model.loss_tangent(freqs)),
        rho=1.724e-8,
        rough=0.5e-6,
        model="hammerstadjensen",
    )
    eps_eff = getattr(mline, "ep_reff", None)
    if eps_eff is None:
        eps_eff = mline.er_eff
    eps_eff = np.real(np.asarray(eps_eff))
    print(f"\n[microstrip] 50Ohm-ish w={MICROSTRIP_WIDTH_MM:.3f}mm h={MICROSTRIP_H_MM:.3f}mm "
          "(skrf HJ, dispersive substrate)")
    print("   f/GHz   eps_eff")
    for f_ghz, ee in zip(SCAN_GHZ, eps_eff, strict=True):
        print(f"  {f_ghz:6.2f}  {ee:8.4f}")
    total = (eps_eff[0] - eps_eff[-1]) / eps_eff[0] * 100.0
    monotonic = bool(np.all(np.diff(eps_eff) <= 0.0))
    print(f"  total variation 1-40GHz: {total:.3f}% (monotonic non-increasing: {monotonic})")


def openems_export(model) -> None:
    """openEMS 材料导出摘要（多极 Debye 编码 + 单点拟合 kwargs）。"""
    payload = model.to_openems()
    kwargs = model.to_openems_sarkar_kwargs()
    print(f"\n[openEMS] Debye poles={len(payload['poles'])} epsInf={payload['epsilon']:.6f} "
          f"kappa={payload['kappa']:.3g}")
    print("[openEMS] AddDjordjevicSarkarMaterial kwargs: "
          f"fMeas={kwargs['fMeas']:.4g} epsRMeas={kwargs['epsRMeas']:.4f} "
          f"tandMeas={kwargs['tandMeas']:.5f} f1={kwargs['f1']:.4g} f2={kwargs['f2']:.4g}")


def main() -> int:
    model = load_dispersion_material(MATERIAL)
    substrate_table(model)
    microstrip_table(model)
    openems_export(model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
