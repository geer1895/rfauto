"""Multimodal audit round 2: three-view (top/front/side) orthographic drawings."""
import sys

sys.path.insert(0, "src")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, geometry_spec


def draw_three_view(template: str, out: str) -> None:
    spec = geometry_spec(template, TEMPLATE_NOMINAL[template])
    boxes = spec["boxes"]
    fig, axes = plt.subplots(1, 3, figsize=(19, 7))

    def _rect(ax, b, i, j, title, xl, yl):
        x0, y0 = b["start_mm"][i], b["start_mm"][j]
        w = b["stop_mm"][i] - x0
        h = b["stop_mm"][j] - y0
        face = "#c8a020" if b["material"] == "metal" else "#7aa6c2"
        alpha = 0.35 if b["material"] == "substrate" else 0.9
        ax.add_patch(plt.Rectangle((x0, y0), w, h, facecolor=face,
                                   edgecolor="k", lw=0.6, alpha=alpha))
        if max(w, h) > 6:
            ax.text(x0 + w / 2, y0 + h / 2, b["name"], fontsize=6, ha="center")

    views = [(0, 1, "TOP (x-y)", "x mm", "y mm"),
             (0, 2, "FRONT (x-z)", "x mm", "z mm"),
             (1, 2, "SIDE (y-z)", "y mm", "z mm")]
    for ax, (i, j, title, xl, yl) in zip(axes, views, strict=True):
        for b in boxes:
            _rect(ax, b, i, j, title, xl, yl)
        for p in spec["ports"]:
            px, py = p["pos_mm"][i], p["pos_mm"][j]
            ax.plot(px, py, "r^", ms=11)
            ax.annotate(p["name"].split("（")[0], (px, py), xytext=(px + 2, py + 2),
                        fontsize=7, color="r")
        for el in spec.get("elements", []):
            if el["kind"] == "lumped_r":
                y0 = el["y_mm"]
                ax.add_patch(plt.Rectangle((el["span_mm"][0], y0 - 1),
                                           el["span_mm"][1] - el["span_mm"][0], 2,
                                           facecolor="#e06040",
                                           edgecolor="k"))
                ax.text(0, y0 + 1.5, "R100", fontsize=7, color="#a03010", ha="center")
        ax.set_title(f"{template} — {title}")
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.set_xlim(-65, 65)
        ax.set_ylim(-65, 20 if j == 2 else 65)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)
    fig.savefig(out, dpi=100, bbox_inches="tight")
    print("wrote", out)


for t in ("wilkinson", "patch"):
    draw_three_view(t, f"audit2_{t}.png")
