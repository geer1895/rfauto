r"""实档损耗 dump 读取器（openEMS SAR/AddDump HDF5，dump_type=29 形态）。

定位：core/loss_density.py 是纯 numpy 内核（不引 h5py），本模块是它的
infra 侧实档入口——把 openEMS 落盘的 HDF5 解析成逐 cell 对齐的
(E 相量, 电导率, 单元体积)，再交内核积分。分层 service → infra → core
（.importlinter layers），h5py 只在本层出现，走 visualization._h5py 的
懒加载守卫（extras [openems]）。

实档布局（离线实测，SAR 冒烟产物的 fdtd/ 目录）
--------------------------------------------------------------------
``SAR_raw.h5``（根 attrs dump_type=29、dual_mesh=1、openEMS_HDF5_version=0.3）::

    FieldData/FD              attrs frequency=[2.5e9]
    FieldData/FD/f0           (3, nx, ny, nz) complex64   d_order="NXYZ"（峰值相量 E）
    CellData/Conductivity     (nx, ny, nz)    float32     d_order="XYZ"  [S/m]
    CellData/Density          (nx, ny, nz)    float32     d_order="XYZ"  [kg/m^3]
    CellData/Volume           (nx, ny, nz)    float32     d_order="XYZ"  [m^3]
    CellWidth/{x,y,z}         (nx,), (ny,), (nz,) float64 attrs mesh_scaling/mesh_type
    Mesh/{x,y,z}              (nx,), (ny,), (nz,) float64 节点坐标（同 DumpHDF5）

``SAR_1g.h5``（openEMS 自算 SAR 后处理产物，根 attrs 无 dump_type）::

    FieldData/FD/f0           (nx, ny, nz) float32  attrs power / maxSAR / maxSAR_idx / frequency

实档锚（逐位对齐实证，本模块 docstring 与单测同源）
--------------------------------------------------------
对 SAR_raw.h5 逐 cell 求和 ``sum(0.5 * sigma * |E|^2 * Volume)`` =
9.619087151749182e-27 W，与 openEMS 自算 SAR_1g.h5 ``FieldData/FD/f0`` 的
``power`` 属性（float32 9.619087e-27）以及同目录 sar.csv 的 p_abs_w 同值
（float32 精度内逐位一致）。这证明：① 内核的峰值相量口径
（q = 0.5σ|E|²，Jackson §6.9）与 openEMS 的 E 相量定义一致；② CellData
与 FieldData 逐 cell 对齐（无需再采样）；③ CellData/Volume 即积分测度
（与 CellWidth 三轴外积一致到 4.5e-8 相对差）。

介损语义边界（如实记录，不猜）
--------------------------------
openEMS 模板把基板 tanδ 折算成电导率写入材料
（adapters/openems_templates.py：AddMaterial kappa = tanδ·2πf0·ε0·εr），因此
实档 CellData 只有 Conductivity，**介损全在 σ 项，没有独立的 ε″ 项可读**。
本读取器只积分欧姆项 0.5σ|E|²；调用方不得再叠加 LossMaterial.tan_delta
（会双计）。频率外推的介损（tanδ 折算只在 f0 精确）属 followUp。

API
---
- ``read_loss_dump(path)`` → :class:`LossDump`（两种形态：``raw_field``
  含 E 相量+CellData，可积分；``processed_sar`` 只带 openEMS 自算 power
  属性，供自检对照）。布局不符 → ValueError（如实报错不猜）。
- ``LossDump.integrate_power_w()`` → 欧姆损耗功率 [W]（走
  core.loss_density.integrate_loss_density 逐 cell 测度）；processed 形态
  返回 None。
- ``find_volume_loss_dumps(run_dir)`` → run 目录下全部可积分的 dump_type=29
  体 dump 路径（排序、best-effort：不可读文件跳过）。不 import ui_service。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.loss_density import integrate_loss_density
from rfauto.infra.visualization import _h5py

#: openEMS Dump_Type 枚举里 SAR 原始体 dump 的编号（实档根 attrs 实测值）
SAR_RAW_DUMP_TYPE = 29

KIND_RAW_FIELD = "raw_field"
KIND_PROCESSED_SAR = "processed_sar"

_AXIS_NAMES = ("x", "y", "z")
_DUMP_SUFFIXES = (".h5", ".hdf5")

__all__ = [
    "KIND_PROCESSED_SAR",
    "KIND_RAW_FIELD",
    "SAR_RAW_DUMP_TYPE",
    "LossDump",
    "find_volume_loss_dumps",
    "read_loss_dump",
]


@dataclass(frozen=True)
class LossDump:
    """一份已解析的损耗 dump（数组按 (nx, ny, nz) 逐 cell 对齐）。

    Attributes:
        path: 源文件路径字符串。
        kind: ``raw_field``（E 相量 + CellData）或 ``processed_sar``
            （openEMS SAR 后处理产物，只带 power 属性）。
        freq_hz: FD 频率 [Hz]（attrs frequency）；缺失为 None。
        dump_type: 根 attrs dump_type；缺失为 None。
        e_field: (3, nx, ny, nz) complex128 峰值相量；processed 形态为 None。
        conductivity: (nx, ny, nz) float64 [S/m]；缺失为 None。
        density: (nx, ny, nz) float64 [kg/m^3]；缺失为 None。
        cell_volume: (nx, ny, nz) float64 [m^3]（CellData/Volume 优先，
            否则 CellWidth 三轴外积）；processed 形态可为 None。
        openems_power_w: openEMS 自算 power 属性 [W]（processed 形态）；
            缺失为 None。
        attrs: 其他 JSON 友好的标量属性（maxSAR、mass、air_cubes 等）。
    """

    path: str
    kind: str
    freq_hz: float | None
    dump_type: int | None
    e_field: np.ndarray | None
    conductivity: np.ndarray | None
    density: np.ndarray | None
    cell_volume: np.ndarray | None
    openems_power_w: float | None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int, int] | None:
        """逐 cell 网格形状 (nx, ny, nz)。"""
        for arr in (self.conductivity, self.cell_volume, self.density):
            if arr is not None:
                return tuple(int(n) for n in arr.shape)  # type: ignore[return-value]
        if self.e_field is not None:
            return tuple(int(n) for n in self.e_field.shape[1:])  # type: ignore[return-value]
        return None

    @property
    def total_volume_m3(self) -> float | None:
        """全部 cell 体积之和 [m^3]。"""
        return None if self.cell_volume is None else float(np.sum(self.cell_volume))

    def ohmic_loss_density(self) -> np.ndarray | None:
        """逐 cell 欧姆损耗密度 q = 0.5·σ·|E|² [W/m^3]（峰值相量口径，
        与 core.loss_density.loss_density(rms=False) 的 σ 项逐字一致；
        σ 逐 cell 变化故不能直接用标量 LossMaterial）。"""
        if self.e_field is None or self.conductivity is None:
            return None
        mag2 = np.sum(np.abs(self.e_field) ** 2, axis=0)
        return np.asarray(0.5 * self.conductivity * mag2, dtype=float)

    def integrate_power_w(self) -> float | None:
        """欧姆损耗总功率 ∫q dV [W]（core.integrate_loss_density 逐 cell 测度）。

        processed 形态（无 E/σ/体积）返回 None。介损语义边界见模块 docstring。
        """
        q = self.ohmic_loss_density()
        if q is None or self.cell_volume is None:
            return None
        return integrate_loss_density(q, cell_measure=self.cell_volume)

    def summary(self) -> dict[str, Any]:
        """JSON 友好摘要（不含大数组）。"""
        return {
            "path": self.path,
            "kind": self.kind,
            "freq_hz": self.freq_hz,
            "dump_type": self.dump_type,
            "shape": list(self.shape) if self.shape else None,
            "total_volume_m3": self.total_volume_m3,
            "openems_power_w": self.openems_power_w,
            "attrs": dict(self.attrs),
        }


# ---------------------------------------------------------------------------
# HDF5 解析
# ---------------------------------------------------------------------------

def _scalar_attr(attrs: Any, key: str) -> float | None:
    """attrs[key] → float（数组取第一个元素）；缺失/非有限 → None。"""
    if key not in attrs:
        return None
    try:
        v = float(np.asarray(attrs[key]).ravel()[0])
    except (TypeError, ValueError, IndexError):
        return None
    return v if np.isfinite(v) else None


def _json_attrs(attrs: Any) -> dict[str, Any]:
    """把 HDF5 attrs 收敛为 JSON 友好标量/列表（字节串解码，数组转 list）。"""
    out: dict[str, Any] = {}
    for key in attrs:
        raw = attrs[key]
        if isinstance(raw, bytes):
            out[str(key)] = raw.decode("utf-8", errors="replace")
            continue
        arr = np.asarray(raw)
        if arr.dtype.kind in "SU":
            out[str(key)] = str(arr.ravel()[0]) if arr.size else ""
        elif arr.size == 1:
            v = arr.ravel()[0]
            out[str(key)] = int(v) if arr.dtype.kind in "iu" else float(v)
        else:
            out[str(key)] = arr.tolist()
    return out


def _cell_widths(h5file: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """CellWidth/{x,y,z}（乘 mesh_scaling）；组缺失返回 None。"""
    if "CellWidth" not in h5file:
        return None
    grp = h5file["CellWidth"]
    scale = 1.0
    s = _scalar_attr(grp.attrs, "mesh_scaling")
    if s is not None and s > 0:
        scale = s
    axes = []
    for name in _AXIS_NAMES:
        if name not in grp:
            raise ValueError(f"HDF5 CellWidth 缺少 {name} 轴")
        axes.append(np.asarray(grp[name][...], dtype=float).ravel() * scale)
    return axes[0], axes[1], axes[2]


def _read_fd_field(fd: Any) -> tuple[np.ndarray, float | None]:
    """FieldData/FD → (f0 数据, frequency)。支持复数 f0 与 f0_real/f0_imag 拆分。"""
    freq = _scalar_attr(fd.attrs, "frequency")
    if "f0" in fd:
        ds = fd["f0"]
        data = np.asarray(ds[...])
        if freq is None:
            freq = _scalar_attr(ds.attrs, "frequency")
        return data, freq
    if "f0_real" in fd and "f0_imag" in fd:
        data = (np.asarray(fd["f0_real"][...], dtype=float)
                + 1j * np.asarray(fd["f0_imag"][...], dtype=float))
        if freq is None:
            freq = _scalar_attr(fd["f0_real"].attrs, "frequency")
        return data, freq
    raise ValueError(f"FieldData/FD 无 f0 数据集：{sorted(fd.keys())}")


def read_loss_dump(path: str | Path) -> LossDump:
    """读 openEMS SAR/AddDump HDF5 → :class:`LossDump`（布局见模块 docstring）。

    形态判定：
    - ``FieldData/FD/f0`` 为 (3, nx, ny, nz) 复矢量 → ``raw_field``；要求
      CellData/Conductivity 与体积测度（CellData/Volume 或 CellWidth 外积）
      形状与场一致。
    - ``FieldData/FD/f0`` 为 (nx, ny, nz) 实标量且带 ``power`` 属性 →
      ``processed_sar``（openEMS 自算 SAR，power 即其吸收功率）。

    Raises:
        RuntimeError: h5py 不可用（extras [openems]）。
        ValueError: 不是 HDF5、缺 FieldData/FD、形状不对齐、数据含 NaN/Inf。
    """
    p = Path(path)
    h5py = _h5py()
    try:
        handle = h5py.File(p, "r")
    except OSError as exc:
        raise ValueError(f"无法以 HDF5 打开 {p}: {exc}") from exc
    with handle as h:
        dump_type = None
        if "dump_type" in h.attrs:
            try:
                dump_type = int(np.asarray(h.attrs["dump_type"]).ravel()[0])
            except (TypeError, ValueError, IndexError):
                dump_type = None
        if "FieldData" not in h or "FD" not in h["FieldData"]:
            raise ValueError(f"{p.name}: HDF5 缺少 FieldData/FD 组（非 FD 损耗 dump）")
        fd = h["FieldData"]["FD"]
        data, freq = _read_fd_field(fd)

        root_attrs = _json_attrs(h.attrs)
        fd_attrs = _json_attrs(fd.attrs)
        ds_attrs = _json_attrs(fd["f0"].attrs) if "f0" in fd else {}
        extra = {k: v for k, v in {**root_attrs, **fd_attrs, **ds_attrs}.items()
                 if k not in ("dump_type", "frequency", "d_order", "power")}

        # ---- processed SAR 形态：实标量 + power 属性 ----
        if data.ndim == 3 and not np.iscomplexobj(data):
            power = _scalar_attr(fd["f0"].attrs, "power") if "f0" in fd else None
            if power is None:
                raise ValueError(
                    f"{p.name}: FieldData/FD/f0 为实标量 {data.shape} 但无 power 属性，"
                    "既非原始体 dump 也非 openEMS SAR 后处理产物")
            return LossDump(
                path=str(p), kind=KIND_PROCESSED_SAR, freq_hz=freq, dump_type=dump_type,
                e_field=None, conductivity=None, density=None, cell_volume=None,
                openems_power_w=power, attrs=extra,
            )

        # ---- raw field 形态：复矢量 + CellData ----
        if data.ndim != 4 or data.shape[0] != 3:
            raise ValueError(
                f"{p.name}: FieldData/FD/f0 形状 {data.shape} 不是 (3, nx, ny, nz) 复矢量")
        e = np.asarray(data, dtype=complex)
        if not (np.all(np.isfinite(e.real)) and np.all(np.isfinite(e.imag))):
            raise ValueError(f"{p.name}: E 场含 NaN/Inf")
        expect = tuple(int(n) for n in e.shape[1:])

        if "CellData" not in h:
            raise ValueError(f"{p.name}: dump_type={dump_type} 缺少 CellData 组，无法逐 cell 积分")
        cell = h["CellData"]

        def _cell_array(name: str, required: bool) -> np.ndarray | None:
            if name not in cell:
                if required:
                    raise ValueError(f"{p.name}: CellData 缺少 {name}")
                return None
            arr = np.asarray(cell[name][...], dtype=float)
            if arr.shape != expect:
                raise ValueError(
                    f"{p.name}: CellData/{name} 形状 {arr.shape} 与场 {expect} 不对齐")
            if not np.all(np.isfinite(arr)):
                raise ValueError(f"{p.name}: CellData/{name} 含 NaN/Inf")
            return arr

        sigma = _cell_array("Conductivity", required=True)
        density = _cell_array("Density", required=False)
        volume = _cell_array("Volume", required=False)
        if volume is None:
            widths = _cell_widths(h)
            if widths is None:
                raise ValueError(f"{p.name}: 既无 CellData/Volume 也无 CellWidth，缺积分测度")
            wx, wy, wz = widths
            if (wx.size, wy.size, wz.size) != expect:
                raise ValueError(
                    f"{p.name}: CellWidth 轴长 {(wx.size, wy.size, wz.size)} 与场 {expect} 不对齐")
            volume = wx[:, None, None] * wy[None, :, None] * wz[None, None, :]
        if bool(np.any(volume <= 0.0)):
            raise ValueError(f"{p.name}: 单元体积含非正值")
        assert sigma is not None
        if bool(np.any(sigma < 0.0)):
            raise ValueError(f"{p.name}: 电导率含负值")

        return LossDump(
            path=str(p), kind=KIND_RAW_FIELD, freq_hz=freq, dump_type=dump_type,
            e_field=e, conductivity=sigma, density=density, cell_volume=volume,
            openems_power_w=None, attrs=extra,
        )


# ---------------------------------------------------------------------------
# run 目录发现
# ---------------------------------------------------------------------------

def _root_dump_type(h5py: Any, path: Path) -> int | None:
    """只读根 attrs 的 dump_type（不加载数据集）；不可读 → None。"""
    try:
        with h5py.File(path, "r") as h:
            if "dump_type" not in h.attrs:
                return None
            return int(np.asarray(h.attrs["dump_type"]).ravel()[0])
    except Exception:
        return None


def find_volume_loss_dumps(run_dir: str | Path) -> list[Path]:
    """run 目录下全部可积分的体损耗 dump（dump_type=29 且 raw_field 形态）。

    best-effort：h5py 缺失 → 空列表；不可读/布局不符的文件跳过；结果按
    路径排序（确定性）。独立实现，不 import ui_service。
    """
    base = Path(run_dir)
    if not base.is_dir():
        return []
    try:
        h5py = _h5py()
    except RuntimeError:
        return []
    found: list[Path] = []
    for path in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in _DUMP_SUFFIXES):
        if _root_dump_type(h5py, path) != SAR_RAW_DUMP_TYPE:
            continue
        try:
            dump = read_loss_dump(path)
        except Exception:
            continue
        if dump.kind == KIND_RAW_FIELD:
            found.append(path)
    return found
