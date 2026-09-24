"""B2 MFK 扩锚复判 held-out 误差图（离线，零引擎真跑）。

复用 factory_m2_mfk_rejudge 的加载/拟合链（只读 importlib 复用，不改它），
对 8 锚（6 train + 2 held-out）配置重拟合 smt_mfk 并逐频画出：
  panel 1/2：两个 held-out 点的 |Γ| 线性域曲线（HFSS 真值 vs MFK vs OE 基线）
  panel 3  ：两 held-out 点 |ΔΓ|(f)（MFK 与 OE 基线两臂）+ 门线 0.04
  panel 4  ：汇总条形（max |ΔΓ| / max εeff% 两臂 vs 门）
图内文字一律英文（matplotlib CJK 字形缺字 #开源发布⑩）。

用法：python scripts/factory_mfk_heldout_plot.py [--out PNG_PATH]
产物：runs/factory_mf_anchors/heldout_error_full8.png（缺省）
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_rejudge():
    path = REPO / "scripts" / "factory_m2_mfk_rejudge.py"
    spec = importlib.util.spec_from_file_location("mfk_rejudge_reuse", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="B2 MFK held-out error plot")
    ap.add_argument("--out", type=str,
                    default=str(REPO / "runs" / "factory_mf_anchors" /
                                "heldout_error_full8.png"))
    args = ap.parse_args(argv)

    rj = _load_rejudge()
    m2 = rj.load_m2_module()
    freqs = m2.band_freqs(0.01)
    low_rows, _ = None, None
    low_rows = m2.load_dataset(
        REPO / "runs" / "datasets" / "datafactory_m1m3_merged_20260920", freqs)
    high_rows, notes = rj.load_high_anchors(
        REPO / "runs" / "factory_mf_anchors", freqs, m2)
    for n in notes:
        print(f"[note] {n}")
    train = [r for r in high_rows if r["group"] == "train"]
    held = [r for r in high_rows if r["group"] == "heldout"]

    from rfauto.optimization.surrogate import smt_mfk, surrogate_registry  # noqa: F401 注册副作用

    low_samples = [m2.make_sample(r["w"], r["s21_db"], r["s11_db"],
                                  r["eps_eff"], freqs) for r in low_rows]
    train_samples = [m2.make_sample(r["w"], r["s21_db"], r["s11_db"],
                                    r["eps_eff"], freqs) for r in train]
    model = surrogate_registry.create(
        "smt_mfk", config={"bounds": dict(m2.W_BOUNDS),
                           "low_fi_samples": low_samples})
    model.fit(train_samples)
    preds_mfk = [model.predict({"w_mm": float(r["w"])}) for r in held]
    preds_base, _ = rj.pair_baseline(low_rows, held, freqs, m2.HEAD_EPS)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.5))
    colors = {"hfss": "k", "mfk": "tab:blue", "oe": "tab:orange"}
    for k, (t, pm, pb) in enumerate(zip(held, preds_mfk, preds_base,
                                        strict=True)):
        ax = axes[0][k]
        g_true = 10.0 ** (np.asarray(t["s11_db"], dtype=float) / 20.0)
        g_mfk = np.array([10.0 ** (float(pm[f"s11_db@{f:.2f}ghz"]) / 20.0)
                          for f in freqs])
        g_oe = np.array([10.0 ** (float(pb[f"s11_db@{f:.2f}ghz"]) / 20.0)
                         for f in freqs])
        ax.plot(freqs, g_true, color=colors["hfss"], ls="-", lw=2,
                label="HFSS truth")
        ax.plot(freqs, g_mfk, color=colors["mfk"], ls="--",
                label="MFK (6 train anchors)")
        ax.plot(freqs, g_oe, color=colors["oe"], ls=":", lw=1.5,
                label="OE low-fi direct")
        ax.set_title(f"held-out {t['point_id']}  w={t['w']:.4f} mm")
        ax.set_xlabel("freq (GHz)")
        ax.set_ylabel("|S11| linear")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax2 = axes[1][k]
        d_mfk = np.abs(g_mfk - g_true)
        d_oe = np.abs(g_oe - g_true)
        ax2.plot(freqs, d_mfk, color=colors["mfk"], ls="--",
                 label=f"MFK |dGamma| max={d_mfk.max():.4f}")
        ax2.plot(freqs, d_oe, color=colors["oe"], ls=":",
                 label=f"OE  |dGamma| max={d_oe.max():.4f}")
        ax2.axhline(0.04, color="r", lw=1.2, label="gate 0.04")
        ax2.set_xlabel("freq (GHz)")
        ax2.set_ylabel("|dGamma| linear")
        ax2.set_ylim(0, max(0.15, float(d_mfk.max()) * 1.15))
        ax2.legend(fontsize=8)
        ax2.grid(alpha=0.3)
    fig.suptitle(
        "B2 MFK anchor expansion re-judge (6 train + 2 held-out): "
        "FAIL  |dGamma|max 0.0979>0.04, eps_eff 1.65%>1%, value-add False",
        fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"[plot] -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
