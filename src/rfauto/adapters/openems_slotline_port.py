"""openEMS 槽线 WaveguidePort 桥（W3⑧a 路线 A）：NGSolve 模场 → HDF5 模式文件 → 端口。

契约（逐条对照源码）
--------------------------------
- 模式文件格式（vendor/openEMS/install/include/CSXCAD/CSModeData.h）：HDF5，
  一维 double 数据集 ``/x``、``/y``（≥2 点，可非均匀）；二维 double ``/Vx``、
  ``/Vy``（shape nx×ny，行主序 data[i,j] @ (x[i], y[j])）；根标量属性
  ``Version``=1.0。Vx/Vy 为模式场的**两个横向分量**，E 或 H 由调用方决定
  （激励用 E 文件，I 探针用 H 文件）。引擎双线性插值，出界夹到边界。
- 轴映射（thliebig/CSXCAD master ``CSPropExcitation::GetWeightedExcitation`` 逐字）：
  传播轴 nPy（由 SetPropagationDir 唯一非零分量给出），``nPyp=(nPy+1)%3``、
  ``nPypp=(nPy+2)%3``；``LinInterp2(loc[nPyp], loc[nPypp])`` → ``fields[0]``=Vx
  归给分量 nPyp、``fields[1]``=Vy 归给分量 nPypp；loc = 绘图单位全局坐标减
  WeightOrigin（本桥不传 local_origin → 文件坐标 = 全局米坐标）。
  exc_dir='x'（nPy=0）：文件 /x ↔ 全局 y、/y ↔ 全局 z、Vx=E_y、Vy=E_z。
- WaveguidePort（.venv openEMS/ports.py L379-549）：``excite≠0`` 时激励盒在
  start 面（沿 exc_dir 零厚）、U/I 模式匹配探针（p_type 10/11）在 stop 面；
  ``E_WG_file/H_WG_file`` 路径必须都是 str；``excite_type=0`` 用 E 文件加权；
  ``CalcPort(..., ZL)``：β=√(k²−kc²)（kc **SI 1/m**，仅 Python 侧消费）、
  ZL≤0 时 ZL=k·Z0/β（空波导 TE 口径，槽线不适用→必须显式传 ZL=Z_mode）。
- 幅值归一（RectWGPort TE10 惯例反推）：E/H 模函数取**同幅值**归一（TE10 的
  E_y=−(1/a)sin、H_x=+(1/a)sin），纯模态下 U/I = 真实模阻抗；故 H 文件写
  ``Z_mode·H_t``（物理 H 乘模阻抗），CalcPort 传 ZL=Z_mode 即参考阻抗自洽。

kc 色散假设（路线 A 已知局限，必须量化）
--------------------------------------
槽线为非均匀介质非 TEM 模，β(f) 不满足空波导色散；kc 只能在 f0 处反解
kc²=k0²−β0²（β0>k0 → kc 纯虚，Python 复数合法：k²−kc² 仍为实）。带内端口
假设 β_port(f)=√(k(f)²−kc²) 与真实 β(f) 的偏差由 smoke 用探针相位斜率量化。
"""

from __future__ import annotations

import cmath
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

C0 = 299792458.0
MODE_FILE_VERSION = 1.0


def mode_file_axes_for_prop_dir(exc_dir: int | str) -> tuple[int, int]:
    """返回 (nPyp, nPypp)：文件 /x、/y 分别对应的全局坐标轴序号（0=x,1=y,2=z）。"""
    n = {"x": 0, "y": 1, "z": 2}.get(exc_dir, exc_dir) if isinstance(exc_dir, str) else int(exc_dir)
    if n not in (0, 1, 2):
        raise ValueError(f"exc_dir 须为 0/1/2 或 x/y/z，得到 {exc_dir!r}")
    return (n + 1) % 3, (n + 2) % 3


def slotline_port_kc(beta0_rad_m: float, f0_hz: float) -> complex:
    """kc = √(k0² − β0²)（SI 1/m）；慢波 β0>k0 时为纯虚（j·√(β0²−k0²)）。"""
    k0 = 2.0 * math.pi * float(f0_hz) / C0
    if not (math.isfinite(beta0_rad_m) and beta0_rad_m > 0):
        raise ValueError(f"beta0 必须为正有限，得到 {beta0_rad_m!r}")
    return cmath.sqrt(complex(k0 * k0 - beta0_rad_m * beta0_rad_m))


def port_beta_from_kc(freq_hz: np.ndarray | float, kc: complex) -> np.ndarray:
    """openEMS WaveguidePort.CalcPort 的 β 假设：β=√(k²−kc²)（k=2πf/c，ref_index=1）。"""
    f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    k = 2.0 * math.pi * f / C0
    return np.sqrt((k * k - kc * kc).astype(complex)).real


@dataclass(frozen=True)
class ModeFilePair:
    e_path: str
    h_path: str
    z_mode_ohm: float
    beta0_rad_m: float
    f0_hz: float
    kc: complex
    grid_shape: tuple[int, int]
    meta_path: str


def _write_mode_h5(path: Path, x_axis: np.ndarray, y_axis: np.ndarray,
                   vx: np.ndarray, vy: np.ndarray) -> None:
    import h5py

    x_axis = np.ascontiguousarray(np.asarray(x_axis, dtype=np.float64))
    y_axis = np.ascontiguousarray(np.asarray(y_axis, dtype=np.float64))
    vx = np.ascontiguousarray(np.asarray(vx, dtype=np.float64))
    vy = np.ascontiguousarray(np.asarray(vy, dtype=np.float64))
    if x_axis.ndim != 1 or y_axis.ndim != 1 or len(x_axis) < 2 or len(y_axis) < 2:
        raise ValueError("模式文件轴须为 ≥2 点的一维数组")
    if vx.shape != (len(x_axis), len(y_axis)) or vy.shape != vx.shape:
        raise ValueError(f"Vx/Vy 形状须为 (nx, ny)={(len(x_axis), len(y_axis))}，"
                         f"得到 {vx.shape}/{vy.shape}")
    if np.any(np.diff(x_axis) <= 0) or np.any(np.diff(y_axis) <= 0):
        raise ValueError("模式文件轴必须严格单调递增")
    with h5py.File(str(path), "w") as f:
        f.create_dataset("x", data=x_axis)
        f.create_dataset("y", data=y_axis)
        f.create_dataset("Vx", data=vx)
        f.create_dataset("Vy", data=vy)
        f.attrs["Version"] = np.float64(MODE_FILE_VERSION)


def read_mode_h5(path: str | Path) -> dict[str, Any]:
    """读回模式文件（测试/审计用）。"""
    import h5py

    with h5py.File(str(path), "r") as f:
        return {"x": f["x"][()], "y": f["y"][()], "Vx": f["Vx"][()], "Vy": f["Vy"][()],
                "Version": float(f.attrs["Version"])}


def write_slotline_mode_files(mode, out_dir: str | Path, stem: str = "slot_mode",
                              exc_dir: str = "x") -> ModeFilePair:
    """把 TransverseMode 写成 openEMS E/H 模式文件对（exc_dir='x' 轴映射）。

    - E 文件：Vx=Re E_y、Vy=Re E_z（横向分量，规一后实部；虚部残差写 meta）；
    - H 文件：Vx=Re(Z_mode·H_y)、Vy=Re(Z_mode·H_z)（同幅值归一，见模块 docstring）；
    - 轴：/x=y_grid（米，全局）、/y=z_grid（米，全局），不传 local_origin。
    仅支持 exc_dir='x'（截面 (u,v)=(y,z) 与 nPyp/nPypp=(1,2) 恰一致）。
    """
    if exc_dir != "x":
        raise ValueError("本桥只实现 exc_dir='x'（截面 (y,z) ↔ 文件 (/x,/y)）")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    z_mode = float(mode.z0_ohm)
    if not (math.isfinite(z_mode) and z_mode > 0):
        raise ValueError(f"模阻抗非法 {mode.z0_ohm!r}（功率流 ≤0？）")
    e_t = np.asarray(mode.e_t)
    h_t = np.asarray(mode.h_t)
    e_path = out / f"{stem}_E.h5"
    h_path = out / f"{stem}_H.h5"
    _write_mode_h5(e_path, mode.y_grid_m, mode.z_grid_m, e_t[:, :, 0].real, e_t[:, :, 1].real)
    _write_mode_h5(h_path, mode.y_grid_m, mode.z_grid_m,
                   (z_mode * h_t[:, :, 0]).real, (z_mode * h_t[:, :, 1]).real)
    f0 = float(mode.freq_ghz) * 1e9
    kc = slotline_port_kc(float(mode.beta_rad_m), f0)
    meta = {
        "format": "CSModeData v1.0 (/x,/y,/Vx,/Vy; row-major nx×ny)",
        "exc_dir": exc_dir,
        "file_axes_global": {"x": "y_global_m", "y": "z_global_m"},
        "e_components": ["E_y", "E_z"],
        "h_components_scaled": ["Z_mode*H_y", "Z_mode*H_z"],
        "z_mode_ohm": z_mode, "beta0_rad_m": float(mode.beta_rad_m), "f0_hz": f0,
        "kc_re": kc.real, "kc_im": kc.imag,
        "imag_residual_e": float(getattr(mode, "imag_residual", float("nan"))),
        "imag_residual_h": float(np.abs(h_t.imag).max() / max(np.abs(h_t).max(), 1e-300)),
        "grid_shape": [int(e_t.shape[0]), int(e_t.shape[1])],
        "y_range_m": [float(mode.y_grid_m[0]), float(mode.y_grid_m[-1])],
        "z_range_m": [float(mode.z_grid_m[0]), float(mode.z_grid_m[-1])],
    }
    meta_path = out / f"{stem}_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return ModeFilePair(e_path=str(e_path.resolve()), h_path=str(h_path.resolve()),
                        z_mode_ohm=z_mode, beta0_rad_m=float(mode.beta_rad_m), f0_hz=f0,
                        kc=kc, grid_shape=(int(e_t.shape[0]), int(e_t.shape[1])),
                        meta_path=str(meta_path.resolve()))


def slotline_port_boxes(x_exc: float, x_meas: float, y_half: float,
                        z_lo: float, z_hi: float) -> tuple[np.ndarray, np.ndarray]:
    """WaveguidePort start/stop：start 面=激励 x_exc、stop 面=U/I 测量 x_meas，
    横向覆盖整个截面 [−y_half, y_half]×[z_lo, z_hi]（米）。direction=sign(x_meas−x_exc)。"""
    if x_exc == x_meas:
        raise ValueError("激励面与测量面不得重合（excite≠0 要求端口沿 exc_dir 非零长）")
    return (np.array([x_exc, -y_half, z_lo], dtype=float),
            np.array([x_meas, y_half, z_hi], dtype=float))


def add_slotline_wg_port(csx, port_nr: int, x_exc: float, x_meas: float,
                         y_half: float, z_lo: float, z_hi: float,
                         files: ModeFilePair, excite: float = 0.0, **kw):
    """创建槽线 WaveguidePort（exc_dir='x'，文件模式，kc 由 files 给出，不传 origin）。"""
    from openEMS.ports import WaveguidePort

    start, stop = slotline_port_boxes(x_exc, x_meas, y_half, z_lo, z_hi)
    return WaveguidePort(csx, port_nr, start, stop, "x", None, None, files.kc,
                         excite=excite, excite_type=0, E_WG_file=files.e_path,
                         H_WG_file=files.h_path, local_origin=None, **kw)
