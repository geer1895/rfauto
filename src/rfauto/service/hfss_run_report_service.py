"""HFSS run 四联图 service（晶圆键合反馈 P2：S 参数+相位+群时延+εeff）。

外部借用者反馈（D:/晶圆键合/rfauto_反馈与实测经验.md §3 P2 表）：跑完 HFSS
后缺一个自动出「S 参数 + 相位 + 群时延 + εeff」四联图的入口——借用了 rfauto
venv 后四张图全靠手写。本服务补齐该面：输入 = Touchstone（.sNp）路径或
run 目录（``results/params.s*p`` / 掩码 sparams.csv，与 SI 通道报告同源装载），
输出 = 单张四联 PNG（matplotlib Agg OO API，零 GUI 依赖）+ JSON 信封。

四联图面板（编号即 summary 键）：
1. S 参数幅值（|S11| / |S21| dB vs freq）；
2. 相位（∠S21 展开相位 deg vs freq，``np.unwrap``）；
3. 群时延（τ = -dφ/dω，``np.gradient`` 数值差分（中心差分+二阶端点
   edge_order=2）+ Savitzky-Golay 相位平滑，平滑窗为声明式参数
   ``gd_smooth_window``——缺省 1=关闭；窗宽/polyorder 随信封 ``notes`` 与
   ``summary.group_delay.smooth_window`` 落档）；
4. εeff（β²/(ω²·μ₀ε₀) 从 S21 相位提取）。

εeff 口径（**#364-② 参考面纪律**）::

    εeff_i = (β_i / ω_i)² · c²，  β_i = φ_i / L

- **L 必须取参考面跨度（=端口面间距），禁用名义线长手拍**——S21 相位含
  馈段总电长度，参考面在端口面（port_ut 头 start-coordinates 是免费证据）；
  名义 40 mm 线实测跨度 ~93 mm 的先例（#364-②）系直接错 5.4×。L 由调用方
  显式声明（``ref_span_m``，缺省 None → εeff 面跳过并落 skip 注记，零手拍）；
- φ 取 S21 展开相位（绝对传播相位口径：波端口数据参考面已嵌在端口面上，
  S21 相位=−β·L；文件自带非零参考偏移时结果含偏置，如实不修正）；
- c = 299792458.0 m/s（SI 定义精确值，μ₀ε₀ = 1/c² 同口径）；
- 标量 vs 曲线二选一按数据形态：逐点 εeff 相对散布
  ``(max−min)/|median| ≤ eps_scalar_spread_tol``（缺省 0.05）→ 标量
  （中位数+散布落档），否则曲线（min/median/max 落档）。PNG 第 4 联
  恒出逐点曲线（标量模式叠加中位线）。

铁律 7：全部数字出自数据源（skrf 读入的 S 矩阵），平滑/差分/εeff 公式
均为声明式参数（docstring+信封 notes 双落档），合成解析锚测试见
``tests/unit/test_hfss_run_report.py``（理想无耗线已知 εeff 独立复算）。

单源消费（Q-W8-4 家法）：缺省 dpi/尺寸全部取自 :mod:`rfauto.core.plot_style`
（``STYLE["savefig.dpi"]`` / ``PAPER_FIGSIZE_DOUBLE``），本模块不新造数值；
确定性：OO API（Figure+FigureCanvasAgg）+ 显式 metadata + 零时间戳零随机
——同输入两跑逐字节（design_replay_report Pareto 散点同款先例）。

信封（规则 4）：``{"ok": True, "png_paths": [...], "summary": {...}}`` /
``error_envelope``，走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，
禁裸 dict）。1 端口数据如实降级（S21 三联落 skip 注记，ok 仍 True）。
分层：service（本模块）→ service（si_channel 装载单源）/ core（plot_style）。

不设 ``__all__``（无 __all__ 的非门面文件不进 tests/gold/public_api.json
——plot_style 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rfauto.core.plot_style import PAPER_FIGSIZE_DOUBLE, STYLE
from rfauto.service.envelope import error_envelope, ok_envelope

# ── 单源消费钉（plot_style Q-W8-4 冻结面——只读消费，禁改 plot_style）──────
#: 保存 dpi 单源（STYLE["savefig.dpi"]）
_FIG_DPI: int = int(STYLE["savefig.dpi"])
#: 四联图 figsize 单源（IEEE 全宽 PAPER_FIGSIZE_DOUBLE，2×2 版面）
_FIGSIZE_FOURPANEL: tuple[float, float] = PAPER_FIGSIZE_DOUBLE

#: εeff 光速（SI 定义精确值；μ₀ε₀ = 1/c²，与 scipy.constants.c 逐位同值）
_C_LIGHT_M_S = 299792458.0

#: dB 地板（|S|=0 防 log0 非有限值；仅绘图/摘要面，声明随 notes 落档）
_DB_FLOOR = -200.0

#: εeff 标量模式缺省相对散布阈值（max−min)/|median| ≤ 该值 → 标量报告
_EPS_SCALAR_SPREAD_TOL = 0.05

#: 产物固定文件名（确定性：同输入两跑同路径同字节）
_PNG_NAME = "hfss_run_figures.png"

#: Touchstone 源装载复用（si_channel_service 单源——文件/run 目录/掩码 csv
#: 三形态同源，零装载漂移；私有导入在 service 层有先例：si_channel ← health）


def _validate_ports(n_ports: int, s21_ports: tuple[int, int]) -> str | None:
    """端口对校验 → 错误消息（None=通过）。1 起物理口号。"""
    a, b = s21_ports
    for p in (a, b):
        if not (isinstance(p, int) and 1 <= p <= n_ports):
            return (f"S21 端口号 {p!r} 越界（数据 {n_ports} 端口，物理口号 "
                    f"1..{n_ports}）")
    if a == b:
        return f"S21 端口对 from,to 不得相同（实为 {a},{b}）"
    return None


def _compute_panels(
    freq_hz: Any,
    s_matrix: Any,
    s21_ports: tuple[int, int],
    gd_smooth_window: int,
    ref_span_m: float | None,
    eps_scalar_spread_tol: float,
    two_port: bool,
) -> dict[str, Any]:
    """四联图全部数值面（纯计算，零 I/O——独立复算锚测试消费此函数）。

    ``two_port=False``（1 端口数据）时 S21 相位/群时延/εeff 三面如实置
    None（数据无 S21，不硬算不伪造）。返回 {f_ghz, s11_db, s21_db,
    phase_deg, gd_ps, eps_eff_pts, eps_eff_med, eps_eff_mode,
    eps_eff_rel_spread, notes, ...}；所有数字出自 s_matrix。
    """
    import numpy as np

    notes: list[str] = []
    f = np.asarray(freq_hz, dtype=float)
    s = np.asarray(s_matrix, dtype=complex)
    n_f = int(f.shape[0])
    f_ghz = f * 1e-9

    # 频率轴单调性守卫（unwrap/gradient/数值差分前提；乱序如实报错不硬算）
    if n_f < 2 or not np.all(np.diff(f) > 0):
        raise ValueError(
            f"频率轴须严格单调递增且 ≥2 点（实测 n={n_f}），无法做展开相位/"
            "数值差分")

    s11 = s[:, 0, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        s11_db = 20.0 * np.log10(np.abs(s11))
    s11_db = np.maximum(s11_db, _DB_FLOOR)
    notes.append(f"|S| dB 地板 {_DB_FLOOR:g}（|S| 零点防 log0，仅绘图/摘要面）")

    s21_db: Any = None
    phase_deg: Any = None
    gd_ps: Any = None
    eps_eff_pts: Any = None
    eps_eff_med: float | None = None
    eps_eff_mode: str | None = None
    eps_eff_rel_spread: float | None = None
    smooth_window = int(gd_smooth_window)

    if two_port:
        a, b = s21_ports
        s21 = s[:, b - 1, a - 1]  # skrf 约定 s[to, from]
        with np.errstate(divide="ignore", invalid="ignore"):
            s21_db = 20.0 * np.log10(np.abs(s21))
        s21_db = np.maximum(s21_db, _DB_FLOOR)

        phase_rad = np.unwrap(np.angle(s21))
        phase_deg = np.degrees(phase_rad)

        # ── 群时延：τ = -dφ/dω（np.gradient 中心差分）+ Savitzky-Golay 相位平滑
        # （声明式：gd_smooth_window=1 关；≥3 奇数开，polyorder=2——线性相位
        # 精确不变（2 阶多项式基含线性），真实数据相位噪声平滑后差分）
        omega = 2.0 * np.pi * f
        w = int(gd_smooth_window)
        if w < 1:
            raise ValueError(f"gd_smooth_window 须 ≥1（实测 {w}）")
        if w > 1 and w % 2 == 0:
            w += 1
            notes.append(f"gd_smooth_window 偶数入参已上调为奇数 {w}")
        if w > n_f:
            w = n_f if n_f % 2 == 1 else n_f - 1
            notes.append(f"gd_smooth_window 超过点数，截到 {w}")
        smooth_window = w
        smooth_on = w >= 3
        phi_for_grad = phase_rad
        if smooth_on:
            from scipy.signal import savgol_filter

            phi_for_grad = savgol_filter(phase_rad, w, 2, mode="interp")
        gd_s = -np.gradient(phi_for_grad, omega, edge_order=2)
        gd_ps = gd_s * 1e12
        notes.append(
            "群时延 = -dφ/dω（np.gradient 中心差分+edge_order=2 二阶端点）"
            "+ Savitzky-Golay 相位平滑窗 "
            f"{w} 点 polyorder=2（{'开' if smooth_on else '关：1=缺省关闭'}），"
            "声明式参数随本注记落档")

        # ── εeff（#364-② 参考面跨度口径；ref_span_m 缺省 None → 跳过零手拍）
        if ref_span_m is not None:
            L = float(ref_span_m)
            if not (math.isfinite(L) and L > 0):
                raise ValueError(
                    f"ref_span_m 须为正有限数（实测 {ref_span_m!r}）")
            mask_pos = f > 0
            if not bool(mask_pos.any()):
                raise ValueError("频率轴无正频点，εeff 无法定义（ω=0 除零）")
            beta = (-phase_rad[mask_pos]) / L
            eps_full = (beta / omega[mask_pos]) ** 2 * _C_LIGHT_M_S ** 2
            eps_eff_pts = eps_full
            eps_eff_med = float(np.median(eps_full))
            if eps_eff_med == 0.0:
                eps_eff_rel_spread = float("inf")
                eps_eff_mode = "curve"
            else:
                eps_eff_rel_spread = float(
                    (float(eps_full.max()) - float(eps_full.min()))
                    / abs(eps_eff_med))
                eps_eff_mode = ("scalar"
                                if eps_eff_rel_spread <= eps_scalar_spread_tol
                                else "curve")
            notes.append(
                "εeff = (β/ω)²·c² = β²/(ω²·μ₀ε₀)，β=|∠S21|unwrap/L；"
                f"L={L:g} m 由调用方显式声明（#364-② 口径：L 取参考面跨度="
                "端口面间距，禁名义线长手拍）；c=299792458.0 m/s（SI 定义，"
                "μ₀ε₀=1/c²）；标量/曲线阈值 eps_scalar_spread_tol="
                f"{eps_scalar_spread_tol:g}（相对散布实测 "
                f"{eps_eff_rel_spread:.3g} → {eps_eff_mode}）")
            if int(mask_pos.sum()) != n_f:
                notes.append(
                    f"εeff 面跳过 {n_f - int(mask_pos.sum())} 个非正频点"
                    "（ω=0 除零守卫）")
        else:
            notes.append(
                "εeff 面跳过：ref_span_m 未由调用方声明（#364-② 零手拍口径"
                "——L 必须取参考面跨度=端口面间距，缺省不猜长度）")

    return {
        "f_ghz": f_ghz,
        "s11_db": s11_db,
        "s21_db": s21_db,
        "phase_deg": phase_deg,
        "gd_ps": gd_ps,
        "eps_eff_pts": eps_eff_pts,
        "eps_eff_med": eps_eff_med,
        "eps_eff_mode": eps_eff_mode,
        "eps_eff_rel_spread": eps_eff_rel_spread,
        "smooth_window": smooth_window,
        "notes": notes,
        "n_freqs": n_f,
    }


def _calm_ylim(ax: Any, values: Any) -> None:
    """近常值曲线 y 轴地板（显示面 cosmetics，零数据改动）。

    数据纵向散布 < 中位绝对值 1e-3（=fp 噪声尺度，非物理起伏）时，
    自动定标会把噪声放大成满轴"抖动"误导读图——扩 y 轴到
    center±max(span, 1e-3·|median|)/2 量级，视觉呈平直线（真实噪声
    超过地板时不触发，正常定标）。
    """
    import numpy as np

    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return
    lo, hi = float(v.min()), float(v.max())
    med = float(np.median(v))
    span = max(hi - lo, 1e-3 * abs(med) if med != 0.0 else 0.0, 1e-30)
    center = 0.5 * (lo + hi)
    ax.set_ylim(center - 0.75 * span, center + 0.75 * span)


def _render_fourpanel_png(
    out_path: Path,
    panels: dict[str, Any],
    *,
    two_port: bool,
    source_label: str,
    ref_span_m: float | None,
) -> None:
    """四联 PNG 落盘（Agg OO API + plot_style 单源 + 零时间戳确定性）。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from rfauto.core.plot_style import paper_figure_context

    with paper_figure_context():
        fig = Figure(figsize=_FIGSIZE_FOURPANEL, dpi=100)
        FigureCanvasAgg(fig)
        f_ghz = panels["f_ghz"]
        fig.suptitle(f"HFSS run figures: {source_label}")

        ax1 = fig.add_subplot(2, 2, 1)
        ax1.plot(f_ghz, panels["s11_db"], label="|S11|")
        if two_port:
            ax1.plot(f_ghz, panels["s21_db"], label="|S21|")
            ax1.legend(loc="best")
        ax1.set_xlabel("Frequency (GHz)")
        ax1.set_ylabel("Magnitude (dB)")
        ax1.set_title("S-parameters")
        ax1.grid(True, alpha=0.3)

        if two_port:
            ax2 = fig.add_subplot(2, 2, 2)
            ax2.plot(f_ghz, panels["phase_deg"])
            ax2.set_xlabel("Frequency (GHz)")
            ax2.set_ylabel("Phase (deg)")
            ax2.set_title("S21 phase (unwrapped)")
            ax2.grid(True, alpha=0.3)

            ax3 = fig.add_subplot(2, 2, 3)
            ax3.plot(f_ghz, panels["gd_ps"])
            ax3.set_xlabel("Frequency (GHz)")
            ax3.set_ylabel("Group delay (ps)")
            ax3.set_title("Group delay")
            _calm_ylim(ax3, panels["gd_ps"])
            ax3.grid(True, alpha=0.3)

        ax4 = fig.add_subplot(2, 2, 4)
        if two_port and panels["eps_eff_pts"] is not None:
            eps_pts = panels["eps_eff_pts"]
            ax4.plot(f_ghz[f_ghz > 0], eps_pts)
            if panels["eps_eff_mode"] == "scalar":
                ax4.axhline(panels["eps_eff_med"], linestyle="--",
                            color="#d62728",
                            label=f"median = {panels['eps_eff_med']:.4g}")
                ax4.legend(loc="best")
            ax4.set_xlabel("Frequency (GHz)")
            ax4.set_ylabel("eps_eff")
            ax4.set_title(
                "eps_eff"
                + (f" (L = {ref_span_m:g} m)" if ref_span_m else ""))
            _calm_ylim(ax4, eps_pts)
            ax4.grid(True, alpha=0.3)
        else:
            ax4.set_axis_off()
            reason = ("1-port data: S21 unavailable"
                      if not two_port
                      else "ref_span_m not declared by caller "
                           "(#364-02 zero hand-tapping)")
            ax4.text(0.5, 0.5, f"eps_eff panel skipped\n{reason}",
                     ha="center", va="center", fontsize=9.0)

        fig.tight_layout()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(out_path), format="png", dpi=_FIG_DPI,
                    metadata={"Software": "rfauto hfss_run_report_service"})


def render_hfss_run_report(
    source: str | Path,
    out_dir: str | Path | None = None,
    *,
    ref_span_m: float | None = None,
    s21_ports: tuple[int, int] = (1, 2),
    gd_smooth_window: int = 1,
    eps_scalar_spread_tol: float = _EPS_SCALAR_SPREAD_TOL,
) -> dict[str, Any]:
    """HFSS run 四联图主入口（run 目录或 Touchstone → 四联 PNG + 信封）。

    Args:
        source: Touchstone 文件（.s2p/.s3p/...）或 run 目录（sparams.csv
            掩码口径优先 / ``results/params.s*p``，si_channel_service
            ``_load_source`` 单源装载）。
        out_dir: 产物目录（缺省 = 源旁 ``hfss_run_figures/``；文件名恒
            ``hfss_run_figures.png``——确定性命名）。
        ref_span_m: 参考面跨度 m（**#364-②**：必须取端口面间距=参考面跨度，
            禁名义线长手拍；由调用方显式给出。None → εeff 面跳过并落
            注记，零手拍）。
        s21_ports: S21 端口对 (from, to)，1 起物理口号（skrf 约定
            ``s[to, from]``）。
        gd_smooth_window: 群时延相位平滑窗（点数，1=关闭；偶数自动上调
            奇数；>点数自动截断）——声明式参数，随 notes/summary 落档。
        eps_scalar_spread_tol: εeff 标量模式相对散布阈值（缺省 0.05）。

    Returns:
        信封：ok=True 时 ``{"ok", "png_paths", "summary"}``；summary 键：
        source_kind/source_path/n_ports/n_freqs/f_min_ghz/f_max_ghz/
        s11_db{s11_port,min,max}/s21{ports,mag_db_min,mag_db_max,
        phase_unwrap_start_deg,phase_unwrap_end_deg}/group_delay{median_ps,
        min_ps,max_ps,smooth_window}/eps_eff(None|{mode,value或median,min,
        max,rel_spread,ref_span_m,method})/notes。失败 error_envelope。
    """
    try:
        from rfauto.service.si_channel_service import _load_source

        loaded = _load_source(source)
    except Exception as exc:
        return error_envelope(
            f"源装载失败: {exc}",
            source=str(source))

    try:
        import numpy as np

        freq_hz = loaded["freq_hz"]
        s = loaded["s"]
        n_ports = int(loaded["n_ports"])
        two_port = n_ports >= 2

        port_err = _validate_ports(n_ports, s21_ports) if two_port else None
        if port_err:
            return error_envelope(port_err, source=str(source))

        panels = _compute_panels(
            freq_hz, s, s21_ports,
            gd_smooth_window=gd_smooth_window,
            ref_span_m=ref_span_m if two_port else None,
            eps_scalar_spread_tol=eps_scalar_spread_tol,
            two_port=two_port,
        )
        notes = list(loaded.get("notes") or []) + panels["notes"]
        if not two_port:
            notes.append(
                "1 端口数据：S21 相位/群时延/εeff 三联如实跳过（数据无 "
                "S21），仅出 |S11| 联")

        src_path = Path(str(loaded["path"]))
        if out_dir is None:
            base = src_path.parent if src_path.is_file() else src_path
            out_path = Path(base) / "hfss_run_figures" / _PNG_NAME
        else:
            out_path = Path(out_dir) / _PNG_NAME

        _render_fourpanel_png(
            out_path, panels,
            two_port=two_port,
            source_label=src_path.name,
            ref_span_m=ref_span_m,
        )

        f = np.asarray(freq_hz, dtype=float)
        s11_db = panels["s11_db"]
        eps_block: dict[str, Any] | None = None
        if two_port and panels["eps_eff_mode"] is not None:
            eps_pts = panels["eps_eff_pts"]
            base_block: dict[str, Any] = {
                "mode": panels["eps_eff_mode"],
                "rel_spread": panels["eps_eff_rel_spread"],
                "ref_span_m": float(ref_span_m) if ref_span_m else None,
                "method": "eps_eff=(beta/omega)^2*c^2, beta=|unwrap(angle(S21))|/ref_span_m",
            }
            if panels["eps_eff_mode"] == "scalar":
                eps_block = {**base_block, "value": panels["eps_eff_med"]}
            else:
                eps_block = {**base_block,
                             "median": panels["eps_eff_med"],
                             "min": float(np.min(eps_pts)),
                             "max": float(np.max(eps_pts))}

        summary: dict[str, Any] = {
            "source_kind": loaded["kind"],
            "source_path": str(src_path),
            "n_ports": n_ports,
            "n_freqs": int(panels["n_freqs"]),
            "f_min_ghz": float(f.min() * 1e-9),
            "f_max_ghz": float(f.max() * 1e-9),
            "s11_db": {
                "port": 1,
                "min": float(np.min(s11_db)),
                "max": float(np.max(s11_db)),
            },
            "s21": ({
                "ports": [s21_ports[0], s21_ports[1]],
                "mag_db_min": float(np.min(panels["s21_db"])),
                "mag_db_max": float(np.max(panels["s21_db"])),
                "phase_unwrap_start_deg": float(panels["phase_deg"][0]),
                "phase_unwrap_end_deg": float(panels["phase_deg"][-1]),
            } if two_port else None),
            "group_delay": ({
                "median_ps": float(np.median(panels["gd_ps"])),
                "min_ps": float(np.min(panels["gd_ps"])),
                "max_ps": float(np.max(panels["gd_ps"])),
                "smooth_window": int(panels["smooth_window"]),
            } if two_port else None),
            "eps_eff": eps_block,
            "png_path": str(out_path),
            "notes": notes,
        }
        return ok_envelope(png_paths=[str(out_path)], summary=summary)
    except Exception as exc:
        return error_envelope(
            f"四联图生成失败: {type(exc).__name__}: {exc}",
            source=str(source))
