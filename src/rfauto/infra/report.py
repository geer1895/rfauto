"""rfauto report generator — Markdown + matplotlib figures.

线程安全说明（C3 修复）：原先使用 matplotlib.pyplot（全局 figure 管理器，
官方明确非线程安全），多线程并发 generate_report 会间歇性崩溃。现改用
OO API（Figure + FigureCanvasAgg），每个调用自建 Figure、无共享状态。
"""

from __future__ import annotations

import numbers
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.image import imread

# ---------------------------------------------------------------------------
# Figure helpers
# ---------------------------------------------------------------------------

def _new_axes(figsize: tuple[float, float], nrows: int = 1, ncols: int = 1):
    """创建独立 Figure + axes（不经过 pyplot 全局状态，线程安全）。"""
    fig = Figure(figsize=figsize)
    FigureCanvasAgg(fig)
    axes = fig.subplots(nrows=nrows, ncols=ncols)
    return fig, axes


def _save_fig(fig: Figure, figs_dir: Path, name: str) -> str:
    """Save figure and return the relative Markdown image reference."""
    figs_dir.mkdir(parents=True, exist_ok=True)
    path = figs_dir / f"{name}.png"
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    # Markdown 相对引用基于 run 目录（figs_dir == <run_dir>/results/figs）
    try:
        ref = figs_dir.parent.parent
        return str(path.relative_to(ref)).replace("\\", "/")
    except ValueError:
        return f"results/figs/{name}.png"


def plot_s11(
    freqs: Sequence[float],
    s11_db: Sequence[float],
    figs_dir: Path,
) -> str:
    """Generate an S11 (return-loss) curve and return its relative path."""
    fig, ax = _new_axes((8, 4))
    ax.plot(freqs, s11_db, linewidth=1.2)
    ax.set_xlabel("Frequency")
    ax.set_ylabel("S11 (dB)")
    ax.set_title("Return Loss (S11)")
    ax.grid(True, alpha=0.3)
    return _save_fig(fig, figs_dir, "s11_curve")


def plot_s21(
    freqs: Sequence[float],
    s21_db: Sequence[float],
    figs_dir: Path,
) -> str:
    """Generate an S21 (insertion-loss) curve and return its relative path."""
    fig, ax = _new_axes((8, 4))
    ax.plot(freqs, s21_db, linewidth=1.2, color="tab:orange")
    ax.set_xlabel("Frequency")
    ax.set_ylabel("S21 (dB)")
    ax.set_title("Insertion Loss (S21)")
    ax.grid(True, alpha=0.3)
    return _save_fig(fig, figs_dir, "s21_curve")


def plot_convergence(
    iterations: Sequence[int],
    residuals: Sequence[float],
    figs_dir: Path,
) -> str:
    """Generate a convergence plot and return its relative path."""
    fig, ax = _new_axes((8, 4))
    ax.semilogy(iterations, residuals, linewidth=1.0, color="tab:green")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Residual")
    ax.set_title("Solver Convergence")
    ax.grid(True, alpha=0.3, which="both")
    return _save_fig(fig, figs_dir, "convergence")


# ---------------------------------------------------------------------------
# Smith Chart
# ---------------------------------------------------------------------------


def plot_smith_chart(
    freqs: Sequence[float],
    s11_complex: Sequence[complex],
    figs_dir: Path,
    z0: float = 50.0,
) -> str:
    """Generate a Smith chart and return its relative path.

    Parameters
    ----------
    freqs:
        Frequency points in Hz.
    s11_complex:
        Complex S11 values.
    figs_dir:
        Directory to save the figure.
    z0:
        Reference impedance (default 50Ω).
    """
    import numpy as np
    try:
        import skrf
        # Create skrf Network
        freq = skrf.Frequency.from_f([f / 1e9 for f in freqs], unit="ghz")
        s = np.array(s11_complex).reshape(-1, 1, 1)
        ntwk = skrf.Network(frequency=freq, s=s, z0=z0)

        # Plot Smith chart
        fig, ax = _new_axes((8, 8))
        ntwk.plot_s_smith(ax=ax, draw_labels=True)
        ax.set_title("Smith Chart (S11)")
        return _save_fig(fig, figs_dir, "smith_chart")
    except ImportError:
        # Fallback: plot impedance on rectangular grid
        fig, (ax1, ax2) = _new_axes((12, 5), ncols=2)
        s11_arr = np.array(s11_complex)
        # Convert to impedance
        z = z0 * (1 + s11_arr) / (1 - s11_arr)
        freqs_ghz = [f / 1e9 for f in freqs]
        ax1.plot(freqs_ghz, z.real, label="Re(Z)")
        ax1.plot(freqs_ghz, z.imag, label="Im(Z)")
        ax1.set_xlabel("Frequency (GHz)")
        ax1.set_ylabel("Impedance (Ω)")
        ax1.set_title("Input Impedance")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # S11 magnitude
        s11_db = 20 * np.log10(np.abs(s11_arr) + 1e-15)
        ax2.plot(freqs_ghz, s11_db)
        ax2.set_xlabel("Frequency (GHz)")
        ax2.set_ylabel("S11 (dB)")
        ax2.set_title("Return Loss")
        ax2.grid(True, alpha=0.3)
        return _save_fig(fig, figs_dir, "smith_chart")


# ---------------------------------------------------------------------------
# Pareto front plot
# ---------------------------------------------------------------------------


def plot_pareto_front(
    pareto_front: Sequence[Sequence[float]],
    metric_names: Sequence[str],
    figs_dir: Path,
) -> str:
    """Generate a Pareto front plot and return its relative path.

    Parameters
    ----------
    pareto_front:
        List of [obj1, obj2, ...] points.
    metric_names:
        Names for each objective axis.
    figs_dir:
        Directory to save the figure.
    """
    import numpy as np
    pareto = np.array(pareto_front)
    if pareto.size == 0 or pareto.ndim < 2 or pareto.shape[1] < 2:
        return ""

    fig, ax = _new_axes((8, 6))
    ax.scatter(pareto[:, 0], pareto[:, 1], c="tab:blue", s=50, alpha=0.7)
    ax.plot(pareto[:, 0], pareto[:, 1], "--", alpha=0.5, color="tab:blue")

    x_label = metric_names[0] if len(metric_names) > 0 else "Objective 1"
    y_label = metric_names[1] if len(metric_names) > 1 else "Objective 2"
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title("Pareto Front")
    ax.grid(True, alpha=0.3)
    return _save_fig(fig, figs_dir, "pareto_front")


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_report(
    run_dir: str | Path,
    metrics: dict[str, Any],
    objectives: dict[str, Any] | None = None,
    *,
    format: str = "markdown",
    freq_data: dict[str, Sequence[float]] | None = None,
    convergence_data: dict[str, Sequence[float]] | None = None,
    diagnosis: dict[str, Any] | None = None,
) -> Path:
    """Write a report into *run_dir* and return its path.

    Parameters
    ----------
    run_dir:
        The run directory (must exist).
    metrics:
        Flat dict of metric name → value (e.g. ``{"s11_min_db": -22.5}``).
    objectives:
        Optional dict of objective specs (name → target/threshold).
    format:
        Output format — ``"markdown"``（默认，写 report.md）或
        ``"html"``（缺口 8：写 report.html，原先该参数是死代码）。
    freq_data:
        Optional ``{"freqs": [...], "s11_db": [...], "s21_db": [...]}`` for
        S-parameter plots.
    convergence_data:
        Optional ``{"iterations": [...], "residuals": [...]}`` for
        convergence plot.
    diagnosis:
        Optional 诊断引擎输出（diagnose_results 的返回值，孤岛接线），
        渲染为 Diagnosis 章节。
    """
    run_dir = Path(run_dir)
    figs_dir = run_dir / "results" / "figs"

    fig_refs: list[str] = []

    # --- Generate figures if data provided ----------------------------------
    if freq_data and freq_data.get("freqs"):
        freqs = freq_data["freqs"]
        if freq_data.get("s11_db"):
            fig_refs.append(plot_s11(freqs, freq_data["s11_db"], figs_dir))
        if freq_data.get("s21_db"):
            fig_refs.append(plot_s21(freqs, freq_data["s21_db"], figs_dir))

    if convergence_data and convergence_data.get("iterations"):
        fig_refs.append(
            plot_convergence(
                convergence_data["iterations"],
                convergence_data["residuals"],
                figs_dir,
            )
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    sections = {
        "metrics": sorted(metrics.items()),
        "objectives": list((objectives or {}).items()),
        "figures": [
            (Path(ref).stem.replace("_", " ").title(), ref) for ref in fig_refs
        ],
        "diagnosis": diagnosis,
    }

    if format == "html":
        report_path = run_dir / "report.html"
        report_path.write_text(
            _render_html(now, sections), encoding="utf-8"
        )
        return report_path
    if format != "markdown":
        raise ValueError(f"未知报告格式: {format}（可选 markdown | html）")

    # --- Markdown body ------------------------------------------------------
    lines: list[str] = []
    lines.append("# Run Report")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append("")

    # Metrics table
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    for k, v in sections["metrics"]:
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # Objectives
    if sections["objectives"]:
        lines.append("## Objectives")
        lines.append("")
        lines.append("| Objective | Target | Status |")
        lines.append("|-----------|--------|--------|")
        for name, spec in sections["objectives"]:
            target = spec.get("target", "—")
            status = spec.get("status", "—")
            lines.append(f"| {name} | {target} | {status} |")
        lines.append("")

    # Figures
    if sections["figures"]:
        lines.append("## Figures")
        lines.append("")
        for name, ref in sections["figures"]:
            lines.append(f"### {name}")
            lines.append(f"![{name}]({ref})")
            lines.append("")

    # Diagnosis（诊断引擎输出，孤岛接线）
    diag = sections["diagnosis"]
    if diag:
        lines.append("## Diagnosis")
        lines.append("")
        diags = diag.get("diagnoses", [])
        if diags:
            lines.append("| Rule | Severity | Metric | Value | Hint |")
            lines.append("|------|----------|--------|-------|------|")
            for d in diags:
                lines.append(
                    f"| {d.get('rule_id', '')} | {d.get('severity', '')} "
                    f"| {d.get('metric', '')} | {d.get('value', '')} "
                    f"| {d.get('hint', '')} |"
                )
            lines.append("")
        suggestions = diag.get("suggestions", [])
        if suggestions:
            lines.append("**Suggestions:**")
            lines.append("")
            for s in suggestions:
                lines.append(f"- {s}")
            lines.append("")
        if not diags and not suggestions:
            lines.append("无异常（未触发诊断规则）。")
            lines.append("")

    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _render_html(now: str, sections: dict[str, Any]) -> str:
    """极简 HTML 渲染（无外部模板依赖）。"""
    import html as _html

    def esc(v: Any) -> str:
        return _html.escape(str(v))

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>Run Report</title>",
        "<style>body{font-family:sans-serif;max-width:900px;margin:2rem auto;"
        "padding:0 1rem}table{border-collapse:collapse}td,th{border:1px solid #ccc;"
        "padding:4px 10px}img{max-width:100%}</style></head><body>",
        "<h1>Run Report</h1>",
        f"<p><b>Generated:</b> {esc(now)}</p>",
        "<h2>Metrics</h2><table><tr><th>Metric</th><th>Value</th></tr>",
    ]
    for k, v in sections["metrics"]:
        parts.append(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>")
    parts.append("</table>")

    if sections["objectives"]:
        parts.append(
            "<h2>Objectives</h2><table><tr><th>Objective</th><th>Target</th>"
            "<th>Status</th></tr>"
        )
        for name, spec in sections["objectives"]:
            target = spec.get("target", "—")
            status = spec.get("status", "—")
            parts.append(
                f"<tr><td>{esc(name)}</td><td>{esc(target)}</td><td>{esc(status)}</td></tr>"
            )
        parts.append("</table>")

    if sections["figures"]:
        parts.append("<h2>Figures</h2>")
        for name, ref in sections["figures"]:
            parts.append(f"<h3>{esc(name)}</h3><img src='{esc(ref)}' alt='{esc(name)}'>")

    diag = sections.get("diagnosis")
    if diag:
        parts.append("<h2>Diagnosis</h2>")
        diags = diag.get("diagnoses", [])
        if diags:
            parts.append(
                "<table><tr><th>Rule</th><th>Severity</th><th>Metric</th>"
                "<th>Value</th><th>Hint</th></tr>"
            )
            for d in diags:
                parts.append(
                    f"<tr><td>{esc(d.get('rule_id', ''))}</td>"
                    f"<td>{esc(d.get('severity', ''))}</td>"
                    f"<td>{esc(d.get('metric', ''))}</td>"
                    f"<td>{esc(d.get('value', ''))}</td>"
                    f"<td>{esc(d.get('hint', ''))}</td></tr>"
                )
            parts.append("</table>")
        for s in diag.get("suggestions", []):
            parts.append(f"<p>• {esc(s)}</p>")
        if not diags and not diag.get("suggestions"):
            parts.append("<p>无异常（未触发诊断规则）。</p>")

    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# PDF export：FSV 等级 / 成本表 / 叙述位（数值 100% 可溯）
#
# 渲染层只做「把传入值转成字符串并排版」，不计算 / 不四舍五入 / 不硬编码任何
# 物理数字：PDF 里出现的每个数值都必须来自调用方传入的
# report data / sections。多页输出用 matplotlib PdfPages（matplotlib 是既有
# 核心依赖，不引入新 GUI 依赖）。叙述位只放传入文本 / None，绝不调用 LLM。
# ---------------------------------------------------------------------------

#: A4 纵向（英寸）——纯版面常数，不进入 PDF 文本。
_PDF_PAGE_SIZE: tuple[float, float] = (8.27, 11.69)
#: 每页文本行数缺省值（版面常数，不进入 PDF 文本）。
_PDF_LINES_PER_PAGE = 34
#: CostLedger.rollup() 成本表展示列（只选取，不计算）。
_COST_COLUMNS: tuple[str, ...] = (
    "total_tokens",
    "solve_hours",
    "seat_hours",
    "gpu_hours",
    "cost",
)


def _as_items(value: Any) -> list[tuple[Any, Any]]:
    """把 metrics/objectives/figures 归一为 (name, value) 列表（dict 保持插入序）。"""
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.items())
    return [tuple(item) for item in value]


def _scalar_text(value: Any) -> str:
    """值原样转字符串——渲染层不做任何算术或重格式化（可溯性保证）。"""
    return "" if value is None else str(value)


def _is_scalar(value: Any) -> bool:
    """标量判定（含 numpy 标量：numpy 标量类型已注册 numbers ABC）。"""
    return value is None or isinstance(value, (str, bool, numbers.Real))


def _fsv_lines(fsv: Any) -> list[str]:
    """FSV 位：评级结果（core/fsv.py 输出）逐字段写入，含 gdm_grade。"""
    lines = ["FSV Validation"]
    if not isinstance(fsv, dict) or not fsv:
        lines.append("  (not provided)")
        return lines
    for key, value in fsv.items():
        if _is_scalar(value):
            lines.append(f"  {key}: {_scalar_text(value)}")
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if _is_scalar(sub_value):
                    lines.append(f"  {key}.{sub_key}: {_scalar_text(sub_value)}")
    return lines


def _cost_lines(cost_rollup: Any) -> list[str]:
    """成本位：CostLedger.rollup() 表（batch / actor 两级，值原样）。"""
    lines = ["Orchestration Cost", "  scope | " + " | ".join(_COST_COLUMNS)]
    if not isinstance(cost_rollup, dict) or not cost_rollup:
        lines.append("  (not provided)")
        return lines
    for batch in sorted(cost_rollup):
        row = cost_rollup[batch]
        if not isinstance(row, dict):
            continue
        cells = " | ".join(_scalar_text(row.get(col, "-")) for col in _COST_COLUMNS)
        lines.append(f"  {batch} | {cells}")
        actors = row.get("actors")
        if isinstance(actors, dict):
            for actor in sorted(actors):
                actor_row = actors[actor]
                if not isinstance(actor_row, dict):
                    continue
                actor_cells = " | ".join(
                    _scalar_text(actor_row.get(col, "-")) for col in _COST_COLUMNS
                )
                lines.append(f"    {actor} | {actor_cells}")
    return lines


def _narrative_lines(narrative: Any) -> list[str]:
    """叙述位：只放传入文本 / None 占位——本模块不做任何 LLM 调用。"""
    lines = ["F9 Narrative"]
    if narrative is None or narrative == "":
        lines.append("  (not provided)")
        return lines
    lines.extend(f"  {raw}" for raw in str(narrative).splitlines())
    return lines


def _diagnosis_lines(diagnosis: Any) -> list[str]:
    """诊断引擎输出（沿用 generate_report 的 diagnoses/suggestions 结构）。"""
    lines = ["Diagnosis"]
    if not isinstance(diagnosis, dict) or not diagnosis:
        lines.append("  (none)")
        return lines
    diagnoses = diagnosis.get("diagnoses") or []
    for item in diagnoses:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"  {item.get('rule_id', '')} | {item.get('severity', '')} | "
            f"{item.get('metric', '')} | {_scalar_text(item.get('value', ''))} | "
            f"{item.get('hint', '')}"
        )
    suggestions = diagnosis.get("suggestions") or []
    lines.extend(f"  suggestion: {s}" for s in suggestions)
    if not diagnoses and not suggestions:
        lines.append("  (no rule triggered)")
    return lines


def _figure_index_lines(figures: Any) -> list[str]:
    """图清单（名称 + 既有相对路径；路径缺失时图页显式跳过，清单仍保留）。"""
    lines = ["Figures"]
    items = _as_items(figures)
    if not items:
        lines.append("  (none)")
        return lines
    lines.extend(f"  {name}: {ref}" for name, ref in items)
    return lines


def _pdf_text_lines(sections: dict[str, Any], now: str) -> list[str]:
    """把 report sections 摊平成文本行（纯排版，不含任何计算）。"""
    lines: list[str] = ["Run Report", f"Generated: {now}", ""]

    lines.append("Metrics")
    metrics = _as_items(sections.get("metrics"))
    if metrics:
        lines.extend(f"  {key}: {_scalar_text(value)}" for key, value in metrics)
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Objectives")
    objectives = _as_items(sections.get("objectives"))
    if objectives:
        for name, spec in objectives:
            target = spec.get("target", "-") if isinstance(spec, dict) else "-"
            status = spec.get("status", "-") if isinstance(spec, dict) else "-"
            lines.append(
                f"  {name}: target={_scalar_text(target)} status={_scalar_text(status)}"
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.extend(_fsv_lines(sections.get("fsv")))
    lines.append("")
    lines.extend(_cost_lines(sections.get("cost_rollup")))
    lines.append("")
    lines.extend(_diagnosis_lines(sections.get("diagnosis")))
    lines.append("")
    lines.extend(_narrative_lines(sections.get("narrative")))
    lines.append("")
    lines.extend(_figure_index_lines(sections.get("figures")))
    return lines


def _pdf_text_page(lines: Sequence[str], *, fontsize: float = 8.5) -> Figure:
    """单页文本 Figure（每行一个 fig.text，避免 axes 刻度引入额外数字）。"""
    fig = Figure(figsize=_PDF_PAGE_SIZE)
    FigureCanvasAgg(fig)
    y = 0.95
    for line in lines:
        fig.text(0.07, y, line, fontsize=fontsize, family="monospace", va="top")
        y -= 0.026
    return fig


def _pdf_image_page(name: str, image_path: Path) -> Figure | None:
    """图页；图片缺失 / 损坏时返回 None（显式降级，不抛）。"""
    try:
        image = imread(str(image_path))
    except (OSError, ValueError):
        return None
    fig, ax = _new_axes((8.27, 10.5))
    ax.imshow(image)
    ax.axis("off")
    ax.set_title(str(name))
    return fig


def export_report_pdf(
    run_dir: str | Path,
    metrics: dict[str, Any] | None = None,
    objectives: dict[str, Any] | None = None,
    *,
    sections: dict[str, Any] | None = None,
    fsv: dict[str, Any] | None = None,
    cost_rollup: dict[str, Any] | None = None,
    narrative: str | None = None,
    freq_data: dict[str, Sequence[float]] | None = None,
    convergence_data: dict[str, Sequence[float]] | None = None,
    diagnosis: dict[str, Any] | None = None,
    filename: str = "report.pdf",
    lines_per_page: int = _PDF_LINES_PER_PAGE,
) -> Path:
    """把报告 sections 渲染为多页 PDF 并落盘（additive，不影响 generate_report）。

    参数
    ----
    run_dir:
        run 目录（不存在时创建）。
    metrics / objectives / freq_data / convergence_data / diagnosis:
        与 generate_report 同义；仅在未传 sections 时用于构建 sections。
    sections:
        既有报告 sections（metrics / objectives / figures / diagnosis），
        可选附 fsv / cost_rollup / narrative。传入时直接渲染，不重算任何内容。
    fsv:
        FSV 位——core/fsv.py 评级结果（如 gdm_grade）；值原样写入 PDF。
    cost_rollup:
        成本位——pipeline/quota_guard.py CostLedger.rollup() 表；值原样写入。
    narrative:
        叙述位——叙述文本 / None 占位。**不触发任何 LLM 调用。**
    filename:
        输出文件名（默认 report.pdf）。
    lines_per_page:
        文本分页行数（版面参数，不进入 PDF 文本）。
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    if sections is None:
        fig_refs: list[str] = []
        figs_dir = run_dir / "results" / "figs"
        if freq_data and freq_data.get("freqs"):
            freqs = freq_data["freqs"]
            if freq_data.get("s11_db"):
                fig_refs.append(plot_s11(freqs, freq_data["s11_db"], figs_dir))
            if freq_data.get("s21_db"):
                fig_refs.append(plot_s21(freqs, freq_data["s21_db"], figs_dir))
        if convergence_data and convergence_data.get("iterations"):
            fig_refs.append(
                plot_convergence(
                    convergence_data["iterations"],
                    convergence_data["residuals"],
                    figs_dir,
                )
            )
        metric_items = sorted((metrics or {}).items())
        sections = {
            "metrics": metric_items,
            "objectives": list((objectives or {}).items()),
            "figures": [
                (Path(ref).stem.replace("_", " ").title(), ref) for ref in fig_refs
            ],
            "diagnosis": diagnosis,
        }
    else:
        sections = dict(sections)

    if fsv is not None:
        sections["fsv"] = fsv
    if cost_rollup is not None:
        sections["cost_rollup"] = cost_rollup
    if narrative is not None:
        sections["narrative"] = narrative

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text_lines = _pdf_text_lines(sections, now)
    page_size = max(int(lines_per_page), 1)

    report_path = run_dir / filename
    with PdfPages(str(report_path)) as pdf:
        for start in range(0, len(text_lines), page_size):
            pdf.savefig(_pdf_text_page(text_lines[start : start + page_size]))
        for name, ref in _as_items(sections.get("figures")):
            image_page = _pdf_image_page(str(name), run_dir / str(ref))
            if image_page is not None:
                pdf.savefig(image_page)
    return report_path
