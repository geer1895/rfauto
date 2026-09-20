"""可视化模块。

可视化功能：
- S 参数曲线图（幅度/相位）
- 优化收敛图
- Pareto 前沿图
- 相关性散点图

设计原则：
- 模块化：每个图表是独立函数
- 可替换：后端可选 matplotlib/plotly
- 报告集成：生成 HTML/Markdown 报告
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class PlotConfig:
    """绘图配置。"""
    backend: str = "matplotlib"  # "matplotlib" | "plotly"
    figsize: tuple[int, int] = (10, 6)
    dpi: int = 150
    style: str = "seaborn-v0_8"
    save_format: str = "png"  # "png" | "svg" | "html"


def plot_s_params(
    freq_ghz: np.ndarray,
    s_params: np.ndarray,
    output_path: str | Path | None = None,
    config: PlotConfig | None = None,
) -> str:
    """绘制 S 参数曲线。

    Args:
        freq_ghz: 频率轴 (GHz)
        s_params: S 参数 (n_freq, n_ports, n_ports)
        output_path: 输出文件路径
        config: 绘图配置

    Returns:
        图表内容（HTML 或文件路径）
    """
    config = config or PlotConfig()

    try:
        # 设置样式
        import contextlib

        import matplotlib.pyplot as plt
        with contextlib.suppress(OSError):
            plt.style.use(config.style)

        _fig, (ax1, ax2) = plt.subplots(2, 1, figsize=config.figsize, dpi=config.dpi)

        # S11 幅度
        s11_db = 20 * np.log10(np.abs(s_params[:, 0, 0]) + 1e-10)
        ax1.plot(freq_ghz, s11_db, label='S11', color='blue')
        ax1.set_xlabel('Frequency (GHz)')
        ax1.set_ylabel('Magnitude (dB)')
        ax1.set_title('S11 Parameter')
        ax1.grid(True, alpha=0.3)
        ax1.legend()

        # S21 幅度
        s21_db = 20 * np.log10(np.abs(s_params[:, 1, 0]) + 1e-10)
        ax2.plot(freq_ghz, s21_db, label='S21', color='red')
        ax2.set_xlabel('Frequency (GHz)')
        ax2.set_ylabel('Magnitude (dB)')
        ax2.set_title('S21 Parameter')
        ax2.grid(True, alpha=0.3)
        ax2.legend()

        plt.tight_layout()

        if output_path:
            plt.savefig(str(output_path), format=config.save_format, bbox_inches='tight')
            plt.close()
            return str(output_path)
        else:
            # 返回 base64 编码的图片
            import base64
            import io
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            plt.close()
            buf.seek(0)
            return base64.b64encode(buf.read()).decode('utf-8')

    except ImportError:
        return "matplotlib not available"


def plot_optimization_convergence(
    trials: list[dict[str, Any]],
    output_path: str | Path | None = None,
    config: PlotConfig | None = None,
) -> str:
    """绘制优化收敛图。

    Args:
        trials: trial 数据列表 [{"number": int, "cost": float}, ...]
        output_path: 输出文件路径
        config: 绘图配置

    Returns:
        图表内容
    """
    config = config or PlotConfig()

    try:
        import matplotlib.pyplot as plt

        _fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)

        numbers = [t["number"] for t in trials]
        costs = [t["cost"] for t in trials]

        ax.plot(numbers, costs, 'b-o', markersize=4, alpha=0.7)
        ax.set_xlabel('Trial Number')
        ax.set_ylabel('Cost')
        ax.set_title('Optimization Convergence')
        ax.grid(True, alpha=0.3)

        # 标记最优
        best_idx = np.argmin(costs)
        ax.plot(numbers[best_idx], costs[best_idx], 'r*', markersize=15, label=f'Best: {costs[best_idx]:.4f}')
        ax.legend()

        plt.tight_layout()

        if output_path:
            plt.savefig(str(output_path), format=config.save_format, bbox_inches='tight')
            plt.close()
            return str(output_path)
        else:
            import base64
            import io
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            plt.close()
            buf.seek(0)
            return base64.b64encode(buf.read()).decode('utf-8')

    except ImportError:
        return "matplotlib not available"


def generate_html_report(
    title: str,
    sections: list[dict[str, Any]],
    output_path: str | Path,
) -> str:
    """生成 HTML 报告。

    Args:
        title: 报告标题
        sections: 章节列表 [{"title": str, "content": str, "type": "text"|"table"|"plot"}]
        output_path: 输出文件路径

    Returns:
        HTML 内容
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f5f5f5; }}
        .plot {{ text-align: center; margin: 20px 0; }}
        .plot img {{ max-width: 100%; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
"""

    for section in sections:
        html += f"    <h2>{section['title']}</h2>\n"

        if section.get("type") == "table":
            html += "    <table>\n"
            if "headers" in section:
                html += "        <tr>" + "".join(f"<th>{h}</th>" for h in section["headers"]) + "</tr>\n"
            for row in section.get("rows", []):
                html += "        <tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>\n"
            html += "    </table>\n"
        elif section.get("type") == "plot":
            html += f'    <div class="plot"><img src="data:image/png;base64,{section["content"]}" /></div>\n'
        else:
            html += f"    <p>{section.get('content', '')}</p>\n"

    html += """
</body>
</html>
"""

    Path(output_path).write_text(html, encoding="utf-8")
    return html


# ═══ 场可视化 3D：openEMS DumpHDF5 → 切片/等值面 web 化 ═══
#
# 设计（数值只在确定性内核 + #105 best-effort）：
# - 本节 = 确定性 numpy 内核：只做求解器产物的几何/代数变换（|E| 包络、
#   轴对齐切片、等值面/等值线、dB 归一、Γ→阻抗），不发明任何物理数字；
# - PyVista（VTK）只在 field_isosurface(engine="auto"|"pyvista") 内惰性
#   import（extras [viz3d]）；未安装 → matplotlib 等值线降级（每个切片一组
#   等值线），engine 标签如实回写，可视化故障永不阻塞主路径（#105）；
# - HDF5 契约按真机产物逐字段核对（nf2ff 冒烟产物）：
#   * TD 矢量 dump（dump_type 0）：FieldData/TD/<step> (3,nx,ny,nz) float32，
#     d_order='NXYZ'，逐步 attrs.time；
#   * FD 矢量 dump（dump_type 29，Python 绑定）：FieldData/FD/f0 (3,nx,ny,nz)
#     complex64；C++ 引擎旧式写法为 f0_real/f0_imag 成对（nf2ff.h5 同形）；
#   * FD 标量 dump（SAR_1g.h5）：FieldData/FD/f0 (nx,ny,nz) float32，
#     d_order='XYZ'，attrs.frequency；
#   * Mesh/x|y|z 米制坐标（attrs.mesh_scaling 标量缩放，mesh_type 0=直角）。

#: 等值面缺省电平（相对体峰值 dB）；线性电平 = peak·10^(dB/20)
DEFAULT_ISO_LEVELS_DB: tuple[float, ...] = (-3.0, -10.0, -20.0)
#: dB 归一下限（JSON 不能承载 -inf/NaN，零场点钳到此值）
FIELD_DB_FLOOR = -60.0
_AXIS_NAMES = ("x", "y", "z")


@dataclass
class FieldVolume:
    """openEMS DumpHDF5 标量化体数据（矢量场取 |E|，标量 dump 原值）。

    magnitude 形状 (nx, ny, nz)，与 x_m/y_m/z_m 轴一一对应；面 dump
    （nf2ff 盒六面）表现为某一轴长度 1 的退化体。
    """
    x_m: np.ndarray
    y_m: np.ndarray
    z_m: np.ndarray
    magnitude: np.ndarray
    domain: str  # "fd" | "td_envelope" | "fd_scalar"
    dump_type: int | None = None
    frequency_hz: float | None = None
    n_timesteps: int | None = None
    source: str = ""

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(int(n) for n in self.magnitude.shape)  # type: ignore[return-value]

    @property
    def peak(self) -> float:
        m = self.magnitude
        return float(np.nanmax(m)) if m.size else 0.0

    def axis(self, name: str) -> np.ndarray:
        return {"x": self.x_m, "y": self.y_m, "z": self.z_m}[name]


def viz3d_available() -> bool:
    """PyVista（extras [viz3d]）是否可 import——只探测，不抛。"""
    try:
        import pyvista  # noqa: F401
    except Exception:
        return False
    return True


def _h5py():
    try:
        import h5py
    except ImportError as e:  # pragma: no cover - 环境相关
        raise RuntimeError("读取 openEMS HDF5 dump 需要 h5py（extras [openems]）") from e
    return h5py


def _mesh_axes(h5file: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if "Mesh" not in h5file:
        raise ValueError("HDF5 缺少 Mesh 组，不是 openEMS DumpHDF5 产物")
    mesh = h5file["Mesh"]
    scale = 1.0
    if "mesh_scaling" in mesh.attrs:
        s = np.asarray(mesh.attrs["mesh_scaling"], dtype=float)
        if s.size == 1 and np.isfinite(float(s)) and float(s) > 0:
            scale = float(s)
    axes = []
    for name in _AXIS_NAMES:
        if name not in mesh:
            raise ValueError(f"HDF5 Mesh 缺少 {name} 轴（仅支持直角 dump，mesh_type 0）")
        axes.append(np.asarray(mesh[name][...], dtype=float).ravel() * scale)
    return axes[0], axes[1], axes[2]


def _vector_magnitude(arr: np.ndarray) -> np.ndarray:
    """(3,nx,ny,nz) 复/实矢量 → (nx,ny,nz) 模长；(nx,ny,nz) 标量 → |·|。"""
    a = np.asarray(arr)
    if a.ndim == 4 and a.shape[0] == 3:
        return np.sqrt(np.sum(np.abs(a) ** 2, axis=0)).astype(float)
    if a.ndim == 3:
        return np.abs(a).astype(float)
    raise ValueError(f"不支持的场数据形状 {a.shape}（期望 (3,nx,ny,nz) 或 (nx,ny,nz)）")


def read_field_dump(path: str | Path) -> FieldVolume:
    """读 openEMS DumpHDF5（TD 矢量/FD 矢量/FD 标量）→ FieldVolume。

    TD dump 取逐步矢量模长的时间包络 max_t |E(t)|（脉冲激励下的峰值场
    分布，纯数据变换）；FD dump 取 |E(f0)|；标量 dump 原值取绝对值。
    布局不符 → ValueError（如实报错，不猜）。
    """
    p = Path(path)
    h5py = _h5py()
    with h5py.File(p, "r") as h:
        x, y, z = _mesh_axes(h)
        expect = (x.size, y.size, z.size)
        dump_type = None
        if "dump_type" in h.attrs:
            dump_type = int(np.asarray(h.attrs["dump_type"]).ravel()[0])
        if "FieldData" not in h:
            raise ValueError("HDF5 缺少 FieldData 组")
        fd_grp = h["FieldData"]
        if "FD" in fd_grp:
            fd = fd_grp["FD"]
            freq = None
            if "f0" in fd:
                ds = fd["f0"]
                data = np.asarray(ds[...])
                if "frequency" in ds.attrs:
                    freq = float(np.asarray(ds.attrs["frequency"]).ravel()[0])
            elif "f0_real" in fd and "f0_imag" in fd:
                data = (np.asarray(fd["f0_real"][...], dtype=float)
                        + 1j * np.asarray(fd["f0_imag"][...], dtype=float))
                if "frequency" in fd["f0_real"].attrs:
                    freq = float(np.asarray(fd["f0_real"].attrs["frequency"]).ravel()[0])
            else:
                raise ValueError(f"FieldData/FD 无 f0 数据集：{sorted(fd.keys())}")
            mag = _vector_magnitude(data)
            domain = "fd" if np.asarray(data).ndim == 4 else "fd_scalar"
            if mag.shape != expect:
                raise ValueError(f"FD 场形状 {mag.shape} 与 Mesh 轴 {expect} 不符")
            return FieldVolume(x, y, z, mag, domain, dump_type, freq, None, str(p))
        if "TD" in fd_grp:
            td = fd_grp["TD"]
            keys = sorted(td.keys())
            if not keys:
                raise ValueError("FieldData/TD 为空")
            env: np.ndarray | None = None
            for k in keys:  # 逐步累计包络，不整段驻留内存
                mag = _vector_magnitude(np.asarray(td[k][...]))
                if mag.shape != expect:
                    raise ValueError(f"TD 场形状 {mag.shape} 与 Mesh 轴 {expect} 不符（步 {k}）")
                env = mag if env is None else np.maximum(env, mag)
            assert env is not None
            return FieldVolume(x, y, z, env, "td_envelope", dump_type, None,
                               len(keys), str(p))
    raise ValueError("FieldData 既无 FD 也无 TD 组")


def field_db(magnitude: np.ndarray, peak: float | None = None,
             floor_db: float = FIELD_DB_FLOOR) -> np.ndarray:
    """|E| → 相对峰值 dB（20·log10），零/NaN 钳到 floor_db（JSON 安全）。"""
    m = np.asarray(magnitude, dtype=float)
    pk = float(np.nanmax(m)) if peak is None and m.size else float(peak or 0.0)
    if pk <= 0.0 or not np.isfinite(pk):
        return np.full(m.shape, floor_db)
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 20.0 * np.log10(m / pk)
    db = np.where(np.isfinite(db), db, floor_db)
    return np.maximum(db, floor_db)


def _round_list(a: np.ndarray, nd: int) -> list[Any]:
    return np.round(np.asarray(a, dtype=float), nd).tolist()


def _sig_list(a: np.ndarray, digits: int = 6) -> list[Any]:
    """按有效数字舍入的嵌套列表（线性场量跨多个数量级，定小数位会压成 0）。"""
    arr = np.asarray(a, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        mag = np.where(arr == 0.0, 0.0, np.floor(np.log10(np.abs(arr))))
    scale = 10.0 ** (digits - 1 - mag)
    return np.where(arr == 0.0, 0.0, np.round(arr * scale) / scale).tolist()


def _raw_slice(vol: FieldVolume, ax: str, index: int | None = None
               ) -> tuple[int, str, str, np.ndarray, np.ndarray, np.ndarray]:
    """轴对齐切片原始浮点数据：(idx, u_axis, v_axis, u_m, v_m, plane[v][u])。"""
    if ax not in _AXIS_NAMES:
        raise ValueError(f"未知切片轴: {ax}")
    k = _AXIS_NAMES.index(ax)
    n = vol.magnitude.shape[k]
    idx = n // 2 if index is None else int(index)
    idx = min(max(idx, 0), n - 1)
    plane = np.take(vol.magnitude, idx, axis=k)  # 余下两轴按 x<y<z 顺序 (n_u, n_v)
    others = [a for a in _AXIS_NAMES if a != ax]
    return idx, others[0], others[1], vol.axis(others[0]), vol.axis(others[1]), plane.T


def field_slices(
    vol: FieldVolume,
    indices: dict[str, int] | None = None,
    axes: tuple[str, ...] = _AXIS_NAMES,
    db: bool = True,
) -> list[dict[str, Any]]:
    """轴对齐切片（缺省各轴中面）→ JSON 友好字典列表。

    每项：{axis, index, position_mm, u_axis, v_axis, u_mm[], v_mm[],
           values[v][u]}；values 为相对体峰值 dB（db=True）或线性 |E|
           （6 位有效数字）。切轴长度 1（面 dump）时切片即整面；请求索引
           越界钳到合法范围。
    """
    indices = dict(indices or {})
    out: list[dict[str, Any]] = []
    peak = vol.peak
    for ax in axes:
        idx, u_name, v_name, u_m, v_m, vals = _raw_slice(vol, ax, indices.get(ax))
        out.append({
            "axis": ax,
            "index": idx,
            "n": int(vol.magnitude.shape[_AXIS_NAMES.index(ax)]),
            "position_mm": round(float(vol.axis(ax)[idx]) * 1e3, 4),
            "u_axis": u_name,
            "v_axis": v_name,
            "u_mm": _round_list(u_m * 1e3, 4),
            "v_mm": _round_list(v_m * 1e3, 4),
            "values": _round_list(field_db(vals, peak), 3) if db else _sig_list(vals),
            "unit": "dB_rel_peak" if db else "linear",
        })
    return out


def _levels_linear(peak: float, levels_db: tuple[float, ...]) -> list[float]:
    """dB 电平 → 线性（升序去重：matplotlib/VTK 均要求电平单调递增）。"""
    return sorted({float(peak * 10.0 ** (ldb / 20.0)) for ldb in levels_db})


def _sig(v: float, digits: int = 6) -> float:
    """按有效数字舍入（场量跨 1e-25..1e3 量级，定小数位会把小量压成 0）。"""
    return float(f"{float(v):.{digits}g}")


def _contour_segments(u: np.ndarray, v: np.ndarray, values: np.ndarray,
                      levels: list[float]) -> list[dict[str, Any]]:
    """matplotlib 等值线抽取（无 GUI 后端：直接用 Figure），返回折线段。"""
    from matplotlib.figure import Figure

    fig = Figure()
    ax = fig.add_subplot(111)
    segs: list[dict[str, Any]] = []
    try:
        cs = ax.contour(u, v, values, levels=levels)
    except Exception:
        return segs
    paths = cs.get_paths() if hasattr(cs, "get_paths") else []
    lv = list(cs.levels)
    for li, path in enumerate(paths):
        level = float(lv[li]) if li < len(lv) else float("nan")
        verts = np.asarray(path.vertices, dtype=float)
        codes = path.codes
        if verts.size == 0:
            continue
        if codes is None:
            segs.append({"level": level, "points": _round_list(verts, 4)})
            continue
        cur: list[list[float]] = []
        for pt, code in zip(verts, codes, strict=False):
            if code == 1 and cur:  # MOVETO 起新段
                segs.append({"level": level, "points": _round_list(np.asarray(cur), 4)})
                cur = []
            if code != 79:  # CLOSEPOLY 不带新点
                cur.append([float(pt[0]), float(pt[1])])
        if cur:
            segs.append({"level": level, "points": _round_list(np.asarray(cur), 4)})
    return segs


def field_isosurface(
    vol: FieldVolume,
    levels_db: tuple[float, ...] = DEFAULT_ISO_LEVELS_DB,
    engine: str = "auto",
    max_vertices: int = 60000,
) -> dict[str, Any]:
    """等值面（PyVista/VTK 移动立方体）；无 PyVista 时降级为切片等值线。

    engine: "auto"（有 PyVista 用之，否则降级）| "pyvista"（缺依赖时
    ok=False 如实报错）| "numpy"（强制等值线降级）。
    返回 JSON 友好：pyvista → {vertices_mm[[x,y,z]], faces[[i,j,k]], ...}；
    降级 → {contours: [{axis, position_mm, segments:[{level, points}]}]}。
    """
    if engine not in ("auto", "pyvista", "numpy"):
        return {"ok": False, "engine": engine, "errors": [f"未知 engine: {engine}"]}
    peak = vol.peak
    levels = _levels_linear(peak, levels_db) if peak > 0 else []
    base: dict[str, Any] = {
        "levels_db": sorted(set(float(v) for v in levels_db)),
        "levels_linear": [_sig(v) for v in levels],
        "peak": _sig(peak, 9),
        "warnings": [],
    }
    degenerate = min(vol.shape) < 2
    if engine in ("auto", "pyvista") and not degenerate:
        try:
            import pyvista as pv

            grid = pv.RectilinearGrid(vol.x_m * 1e3, vol.y_m * 1e3, vol.z_m * 1e3)
            # VTK 点序 x 最快 → Fortran 展平
            grid.point_data["mag"] = np.asarray(vol.magnitude, dtype=float).ravel(order="F")
            surf = grid.contour(isosurfaces=levels, scalars="mag").triangulate()
            pts = np.asarray(surf.points, dtype=float)
            faces = (np.asarray(surf.faces).reshape(-1, 4)[:, 1:] if surf.n_cells > 0
                     else np.zeros((0, 3), int))
            scal = np.asarray(surf.point_data["mag"]) if "mag" in surf.point_data else np.zeros(len(pts))
            if len(pts) > max_vertices:
                base["warnings"].append(
                    f"等值面顶点 {len(pts)} 超上限 {max_vertices}，按 decimate 抽稀")
                surf = surf.decimate(1.0 - max_vertices / len(pts))
                pts = np.asarray(surf.points, dtype=float)
                faces = np.asarray(surf.faces).reshape(-1, 4)[:, 1:]
                scal = np.asarray(surf.point_data["mag"]) if "mag" in surf.point_data else np.zeros(len(pts))
            return {**base, "ok": True, "engine": "pyvista",
                    "vertices_mm": _round_list(pts, 4),
                    "faces": np.asarray(faces, dtype=int).tolist(),
                    "vertex_db": _round_list(field_db(scal, peak), 3),
                    "n_vertices": len(pts), "n_faces": len(faces)}
        except ImportError:
            if engine == "pyvista":
                return {**base, "ok": False, "engine": "pyvista",
                        "errors": ["PyVista 未安装：pip install rfauto[viz3d]"]}
            base["warnings"].append("PyVista 未安装（extras [viz3d]）：降级为切片等值线")
        except Exception as e:  # VTK 内部故障：降级，不阻塞（#105）
            if engine == "pyvista":
                return {**base, "ok": False, "engine": "pyvista", "errors": [f"PyVista 等值面失败: {e}"]}
            base["warnings"].append(f"PyVista 等值面失败，降级为切片等值线: {e}")
    elif engine == "pyvista" and degenerate:
        return {**base, "ok": False, "engine": "pyvista",
                "errors": [f"面 dump（形状 {vol.shape}）无体积，等值面不适用；请用切片等值线"]}
    # ── 降级：三中面等值线（或退化面 dump 的整面等值线），原始浮点不经 JSON 舍入 ──
    contours: list[dict[str, Any]] = []
    for ax in _AXIS_NAMES:
        idx, u_name, v_name, u_m, v_m, vals = _raw_slice(vol, ax)
        if vals.shape[0] < 2 or vals.shape[1] < 2 or not levels:
            continue
        segs = _contour_segments(u_m * 1e3, v_m * 1e3, vals, levels)
        contours.append({"axis": ax, "index": idx,
                         "position_mm": round(float(vol.axis(ax)[idx]) * 1e3, 4),
                         "u_axis": u_name, "v_axis": v_name, "segments": segs})
    return {**base, "ok": True, "engine": "numpy_contour", "contours": contours}


def farfield_pattern_from_h5(path: str | Path) -> dict[str, Any]:
    """CalcNF2FF 原生 HDF5（nf2ff.h5 / farfield_3d.h5）→ 方向图网格（dB 归一）。

    契约（真机产物核对）：Mesh/theta|phi 弧度；nf2ff/E_theta|E_phi/FD/
    f0_real|f0_imag 形状 (n_phi, n_theta)；nf2ff attrs Dmax（线性）、
    Frequency、Prad。返回 theta_deg[]、phi_deg[]、db[theta][phi]（与
    nf2ff_service.pattern3d 同向：theta 行 × phi 列）。
    """
    from rfauto.core.farfield import (
        dmax_dbi,
        dmax_from_pattern,
        hemisphere_power,
        pattern_db,
    )

    p = Path(path)
    h5py = _h5py()
    with h5py.File(p, "r") as h:
        if "Mesh" not in h or "nf2ff" not in h:
            raise ValueError("不是 CalcNF2FF HDF5 产物（缺 Mesh/nf2ff 组）")
        theta = np.asarray(h["Mesh/theta"][...], dtype=float).ravel()
        phi = np.asarray(h["Mesh/phi"][...], dtype=float).ravel()
        nf = h["nf2ff"]
        comps = []
        for name in ("E_theta", "E_phi"):
            grp = nf[name]["FD"]
            comps.append(np.asarray(grp["f0_real"][...], dtype=float)
                         + 1j * np.asarray(grp["f0_imag"][...], dtype=float))
        e_norm = np.sqrt(np.abs(comps[0]) ** 2 + np.abs(comps[1]) ** 2)
        if e_norm.shape != (phi.size, theta.size):
            raise ValueError(f"远场形状 {e_norm.shape} 与 (n_phi={phi.size}, n_theta={theta.size}) 不符")
        attrs = {k: np.asarray(v, dtype=float).ravel() for k, v in nf.attrs.items()}
    db = pattern_db(e_norm.T)  # → (n_theta, n_phi)
    db = np.where(np.isfinite(db), db, FIELD_DB_FLOOR)
    dmax_lin = float(attrs["Dmax"][0]) if "Dmax" in attrs and attrs["Dmax"].size else None
    # 图形自归一方向性（教科书 D=4πU_max/∫U dΩ，尺度无关）：仅 φ 覆盖整周的
    # 3D 网格可积；切面产物（φ=0/90）不构成球面 → None。PEC 地器件取
    # 上半球（core.farfield.correct_pec_mirror 注记：openEMS Dmax 属性折半）
    pattern_dir: dict[str, float | None] = {
        "dmax_pattern_dbi": None, "dmax_pattern_upper_dbi": None,
        "lower_upper_power_ratio": None,
    }
    if phi.size >= 3 and np.all(theta >= -1e-9):
        try:
            p_rad = (e_norm.T) ** 2
            hp = hemisphere_power(p_rad, theta, phi)
            pattern_dir["dmax_pattern_dbi"] = round(
                dmax_dbi(dmax_from_pattern(p_rad, theta, phi, "full")), 4)
            if hp["upper"] > 0.0:
                pattern_dir["dmax_pattern_upper_dbi"] = round(
                    dmax_dbi(dmax_from_pattern(p_rad, theta, phi, "upper")), 4)
                pattern_dir["lower_upper_power_ratio"] = round(
                    hp["lower"] / hp["upper"], 4)
        except ValueError:
            pass
    return {
        "theta_deg": _round_list(np.degrees(theta), 3),
        "phi_deg": _round_list(np.degrees(phi), 3),
        "db": _round_list(np.maximum(db, FIELD_DB_FLOOR), 3),
        "dmax_dbi": (round(dmax_dbi(dmax_lin), 4) if dmax_lin and dmax_lin > 0 else None),
        **pattern_dir,
        "frequency_ghz": (round(float(attrs["Frequency"][0]) / 1e9, 6)
                          if "Frequency" in attrs and attrs["Frequency"].size else None),
        "prad_w": (float(attrs["Prad"][0]) if "Prad" in attrs and attrs["Prad"].size else None),
        "source": str(p),
    }


# ═══ Smith 圆图内核（S 参数页增强）═══════════════════════════════════════════
#
# 纯几何：Γ 平面上恒电阻圆 |Γ − r/(1+r)| = 1/(1+r)、恒电抗圆
# |Γ − (1 + j/x)| = 1/|x|（Pozar §2.4），Z = Z0·(1+Γ)/(1−Γ)。数据 Γ 全部来自
# 求解器/测量 Touchstone，本节不产生任何物理数字。

DEFAULT_SMITH_R = (0.2, 0.5, 1.0, 2.0, 5.0)
DEFAULT_SMITH_X = (0.2, 0.5, 1.0, 2.0, 5.0)


def _contiguous_arc(pts: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """圆周采样点按掩码保留并旋转到连续弧起点（弧跨越数组末尾时不断线）。"""
    if not keep.any():
        return pts[:0]
    if keep.all():
        return pts
    idx = np.flatnonzero(keep)
    gaps = np.flatnonzero(np.diff(idx) > 1)
    if gaps.size == 0:
        return pts[idx]
    start = idx[gaps[0] + 1]  # 首个断口之后开始
    order = np.concatenate([idx[idx >= start], idx[idx < start]])
    return pts[order]


def smith_grid(
    r_values: tuple[float, ...] = DEFAULT_SMITH_R,
    x_values: tuple[float, ...] = DEFAULT_SMITH_X,
    n_arc: int = 181,
) -> dict[str, Any]:
    """Smith 网格几何（单位圆、恒 r 圆、恒 ±x 弧，裁剪到 |Γ|≤1）。"""
    t = np.linspace(0.0, 2.0 * np.pi, n_arc, endpoint=False)
    unit = np.stack([np.cos(t), np.sin(t)], axis=1)
    r_circles = []
    for r in r_values:
        c, rad = r / (1.0 + r), 1.0 / (1.0 + r)
        pts = np.stack([c + rad * np.cos(t), rad * np.sin(t)], axis=1)
        r_circles.append({"r": float(r), "center": [round(c, 9), 0.0],
                          "radius": round(rad, 9), "points": _round_list(pts, 5)})
    x_arcs = []
    for xv in x_values:
        for sign in (1.0, -1.0):
            x = sign * xv
            cy, rad = 1.0 / x, 1.0 / abs(x)
            pts = np.stack([1.0 + rad * np.cos(t), cy + rad * np.sin(t)], axis=1)
            keep = np.hypot(pts[:, 0], pts[:, 1]) <= 1.0 + 1e-9
            arc = _contiguous_arc(pts, keep)
            x_arcs.append({"x": float(x), "center": [1.0, round(cy, 9)],
                           "radius": round(rad, 9), "points": _round_list(arc, 5)})
    return {"unit_circle": _round_list(np.vstack([unit, unit[:1]]), 5),
            "r_circles": r_circles, "x_arcs": x_arcs}


def smith_chart_data(
    freq_ghz: np.ndarray,
    gamma: np.ndarray,
    z0: float = 50.0,
    max_points: int = 2000,
    with_grid: bool = True,
) -> dict[str, Any]:
    """反射系数轨迹 → Smith 圆图 JSON（点列 + 阻抗读数 + 网格几何）。

    gamma 为复反射系数（Touchstone S_ii）；|Γ|→1 时阻抗读数置 None（不
    除零）。点数超 max_points 均匀抽稀（首尾保留）。
    """
    f = np.asarray(freq_ghz, dtype=float).ravel()
    g = np.asarray(gamma, dtype=complex).ravel()
    if f.shape != g.shape:
        raise ValueError(f"freq 与 gamma 长度不符: {f.shape} vs {g.shape}")
    n = f.size
    if n > max_points:
        pick = np.unique(np.linspace(0, n - 1, max_points).round().astype(int))
        f, g = f[pick], g[pick]
    denom = 1.0 - g
    z_re: list[float | None] = []
    z_im: list[float | None] = []
    for gi, d in zip(g, denom, strict=True):
        if abs(d) < 1e-9:
            z_re.append(None)
            z_im.append(None)
        else:
            z = z0 * (1.0 + gi) / d
            z_re.append(round(float(z.real), 4))
            z_im.append(round(float(z.imag), 4))
    out: dict[str, Any] = {
        "z0": float(z0),
        "n_points": int(f.size),
        "freq_ghz": _round_list(f, 6),
        "re": _round_list(g.real, 6),
        "im": _round_list(g.imag, 6),
        "mag": _round_list(np.abs(g), 6),
        "z_re_ohm": z_re,
        "z_im_ohm": z_im,
    }
    if with_grid:
        out["grid"] = smith_grid()
    return out
