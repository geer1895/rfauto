#!/usr/bin/env python3
"""H3 方法学论文图脚本：从 runs/ 既有 JSON 出图到 runs/release_staging/paper/figs/。

数值纪律：图中一切数字 100% 出自 runs/ 既有 JSON 的原值（零算术改写、
零新数字）；本脚本不产生任何物理量。离线（matplotlib Agg，无网络）。
产物：3 张 PNG + manifest.json（每图数据来源文件+SHA256，可溯）。

用法：python scripts/paper_figures.py --outdir runs/release_staging/paper/figs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "runs" / "benchmark"
MESH_CONV_JSON = BENCHMARK_DIR / "mline_mesh_convergence.json"
WP39_SUMMARY = REPO_ROOT / "runs" / "wp39_mvp" / "summary.json"

_DELTA_PCT_RE = re.compile(r"^delta_eps\d*_pct$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _style_axes(ax: Any) -> None:
    ax.grid(True, axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def fig_anchor_delta_eps(figs_dir: Path, sources: list[dict[str, str]]) -> Path:
    """图 1：各引擎基准锚的 eps_eff 偏差（delta_eps*_pct 原值，双端口锚画双柱）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    labels: list[str] = []
    values: list[float] = []
    gates: list[str] = []
    src_files: list[Path] = []
    for path in sorted(BENCHMARK_DIR.glob("*_engine_benchmark.json")):
        data = read_json(path)
        metrics = data.get("metrics") or {}
        criteria = data.get("criteria") or {}
        anchor = str(data.get("anchor") or path.stem)
        keys = sorted(k for k in metrics if _DELTA_PCT_RE.match(k))
        if not keys:
            continue
        for k in keys:
            v = metrics.get(k)
            if v is None:
                continue
            # 端口号映射：delta_epsN_pct 只对 criteria 中同端口号的 *_abs_le 门
            # （如 via 只门 beta1_delta_eps_pct_abs_le，eps2 无门——如实标 no gate）
            m = re.search(r"eps(\d+)_pct$", k)
            port = m.group(1) if m else ""
            matched = [k2 for k2 in sorted(criteria)
                       if k2.endswith("_pct_abs_le")
                       and (not port or port in k2 or f"beta{port}" in k2)
                       and (port or k2 == "delta_eps_pct_abs_le")]
            gate_txt = "/".join(str(criteria[k2]) for k2 in matched) if matched else "no gate"
            labels.append(anchor if len(keys) == 1 else f"{anchor}\n{k.replace('delta_', '').replace('_pct', '')}")
            values.append(float(v))
            gates.append(gate_txt)
        src_files.append(path)

    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    x = np.arange(len(labels))
    ax.bar(x, values, color="#4878a8")
    ax.set_xticks(x, labels)
    ax.set_ylabel("eps_eff deviation from closed form (%)")
    ax.set_title("Engine benchmark anchors: eps_eff deviation (values as recorded)")
    lo, hi = min([*values, 0.0]), max([*values, 0.0])
    span = (hi - lo) or 1.0
    for xi, v, g in zip(x, values, gates, strict=True):
        ax.annotate(f"{v:g}\ngate: {g}", (xi, v), ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=7)
    ax.set_ylim(lo - span * 0.25, hi + span * 0.35)
    _style_axes(ax)
    fig.tight_layout()
    out = figs_dir / "fig_anchor_delta_eps.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    sources.extend({"path": p.relative_to(REPO_ROOT).as_posix(), "sha256": sha256_file(p)}
                   for p in src_files)
    return out


def fig_mline_mesh_convergence(figs_dir: Path, sources: list[dict[str, str]]) -> Path:
    """图 2：mline 网格收敛（entries 原值：mesh_mm vs delta_vs_hj/gold_pct）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = read_json(MESH_CONV_JSON)
    entries = [e for e in (data.get("entries") or []) if e.get("ok") is not None]
    labels = [str(e.get("mesh_mm")) + (" (auto)" if e.get("mesh_mm") == 0 else "")
              for e in entries]
    hj = [e.get("delta_vs_hj_pct") for e in entries]
    gold = [e.get("delta_vs_gold_pct") for e in entries]

    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    x = range(len(entries))
    ax.plot(x, hj, marker="o", label="delta_vs_hj_pct")
    ax.plot(x, gold, marker="s", label="delta_vs_gold_pct")
    ax.set_xticks(list(x), labels)
    ax.set_xlabel("mesh resolution (mm; 0 = auto)")
    ax.set_ylabel("deviation (%)")
    ax.set_title("mline mesh convergence (values as recorded)")
    ax.legend()
    _style_axes(ax)
    fig.tight_layout()
    out = figs_dir / "fig_mline_mesh_convergence.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    sources.append({"path": MESH_CONV_JSON.relative_to(REPO_ROOT).as_posix(),
                    "sha256": sha256_file(MESH_CONV_JSON)})
    return out


def fig_wp39_candidate_vs_baseline(figs_dir: Path, sources: list[dict[str, str]]) -> Path:
    """图 3：WP3.9 工厂基准（summary problems 原值：candidate vs baseline metric）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    data = read_json(WP39_SUMMARY)
    problems = data.get("problems") or {}
    names = sorted(problems)
    cand = [problems[n].get("metric_candidate") for n in names]
    base = [problems[n].get("metric_baseline") for n in names]
    verdicts = [str(problems[n].get("verdict") or "") for n in names]

    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    x = np.arange(len(names))
    w = 0.38
    ax.bar(x - w / 2, [float(v) for v in cand], w, label="candidate (surrogate loop)")
    ax.bar(x + w / 2, [float(v) for v in base], w, label="baseline (pattern search)")
    for xi, v in zip(x, cand, strict=True):
        ax.annotate(f"{v:.6g}", (xi - w / 2, float(v)), ha="center", va="bottom", fontsize=7)
    for xi, v in zip(x, base, strict=True):
        ax.annotate(f"{v:.6g}", (xi + w / 2, float(v)), ha="center", va="bottom", fontsize=7)
    for xi, vd in zip(x, verdicts, strict=True):
        ax.annotate(f"verdict={vd}", (xi, ax.get_ylim()[0]), ha="center",
                    va="bottom", fontsize=8, color="#7a2020")
    ax.set_xticks(x, names)
    ax.set_ylabel("cost metric (as recorded)")
    ax.set_title("WP3.9 template factory: candidate vs baseline (values as recorded)")
    ax.legend()
    _style_axes(ax)
    fig.tight_layout()
    out = figs_dir / "fig_wp39_candidate_vs_baseline.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    sources.append({"path": WP39_SUMMARY.relative_to(REPO_ROOT).as_posix(),
                    "sha256": sha256_file(WP39_SUMMARY)})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H3 论文图（离线，数字全出 runs/ 既有 JSON）")
    parser.add_argument("--outdir", default=str(REPO_ROOT / "runs" / "release_staging" / "paper" / "figs"))
    args = parser.parse_args(argv)
    figs_dir = Path(args.outdir)
    figs_dir.mkdir(parents=True, exist_ok=True)

    sources: list[dict[str, str]] = []
    produced = [
        fig_anchor_delta_eps(figs_dir, sources),
        fig_mline_mesh_convergence(figs_dir, sources),
        fig_wp39_candidate_vs_baseline(figs_dir, sources),
    ]
    manifest = {
        "kind": "rfauto_paper_figures_manifest",
        "figures": [{"file": p.name, "bytes": p.stat().st_size} for p in produced],
        "sources": sources,
        "note": "图中一切数字 100% 出自上列 runs/ 既有 JSON（原值，零算术改写）。",
    }
    (figs_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    for p in produced:
        print(f"[fig] {p.name}")
    print(f"manifest: {figs_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
