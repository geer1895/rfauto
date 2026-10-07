"""SV-4：FDTDX 通道扩面——周期边界器件案例（规格层 + 支持性实录探针）。

规格（round14 §六 SV-4）："周期边界器件案例+nf2ff（先源码实录，文档未
证实项标待证）"。

**架构位置**（任务书禁改"既有 adapter"）：本模块不修改
``adapters/fdtd_diff.py``——新增周期边界规格层
:class:`PeriodicSlabSpec`（纯校验面，离线可测）与 fdtdx 引擎侧的
**运行时源码实录探针** :func:`probe_fdtdx_periodic_support`：

- fdtdx 缺席（本席 venv 实况）→ 探针如实返回 ``not_installed``，
  apply 路径显式报错指路 extras（``diff-fdtd``）；
- fdtdx 在场 → 探针 ``inspect.getsource`` 直读
  ``fdtdx/objects/boundaries/initialization.py``（fdtd_diff.py 实录的
  BoundaryConfig 所在源文件）检索周期边界证据词——**支持性以安装版
  源码为准**（round14 "先源码实录" 原文），无证据词 → apply 拒绝
  （fail-closed 待证，不猜 API）；
- 有证据词 → apply 仍不在本席承诺内（真机面），返回探测证据供实录
  批接线。

纯函数判据面（离线完整可测）：
- :func:`pass_band_mask` / :func:`band_edges`——周期结构通带提取
  （|S21| dB 门限 + 带边/带宽），Floquet 带判读的确定性锚；
- :class:`PeriodicSlabSpec`——单胞周期向（x）/吸收向（y）几何与
  体素预算守卫（同 fdtd_diff CavitySpec 守卫家族口径）。

铁律：本模块不产物理数字（判据输入由求解/调用方注入）。
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

#: fdtdx 边界初始化源码中检索的周期证据词（大小写不敏感；命中=支持性
#: 有源码证据，未命中=待证拒绝）
PERIODIC_EVIDENCE_TOKENS: tuple[str, ...] = (
    "periodic", "PERIODIC", "Periodic",
)


@dataclass
class PeriodicSlabSpec:
    """周期单胞介质板规格（x 周期 / y 吸收或 PEC，TMz 型薄板）。

    几何沿 fdtd_diff.CavitySpec 惯例：resolution 米/体素；四周壳层由
    引擎侧（fdtdx BoundaryConfig）处理，本规格只描述芯层。
    """

    #: x 向体素数（周期向单胞）
    nx: int = 24
    #: y 向体素数（传播/吸收向芯层）
    ny: int = 24
    #: z 向芯层体素数（TMz 型薄板=1）
    nz_core: int = 1
    #: 空间分辨率（米）
    resolution: float = 20e-9
    #: 时间步数（CPU 小算例口径 ≤320，同 fdtd_diff）
    steps: int = 320
    #: 激励波长（米）
    wavelength: float = 600e-9
    #: 介质板占单胞的 x/y 体素数（居中放置）
    slab_voxels_x: int = 12
    slab_voxels_y: int = 6
    #: y 向边界："pec"（腔口径）| "pml"（开放传播口径——周期结构
    #: 透射判读的正确档）
    y_boundary: str = "pml"
    #: pml 厚度（体素；y_boundary="pml" 时生效）
    pml_thickness: int = 2
    #: 两材料插值端点（同 fdtd_diff 口径）
    eps_air: float = 1.0
    eps_diel: float = 6.0
    #: CPU 体素预算（芯层 nx*ny*nz）
    voxel_budget: int = 4096

    def validate(self) -> None:
        if self.nx < 2 or self.ny < 2 or self.nz_core < 1:
            raise ValueError(
                f"单胞体素数须 nx,ny≥2 / nz≥1，实得 "
                f"{self.nx}x{self.ny}x{self.nz_core}")
        if self.nx > 64 or self.ny > 64:
            raise ValueError(
                f"CPU 小算例约束 nx,ny ≤ 64，实得 nx={self.nx}, ny={self.ny}")
        if not 0 < self.steps <= 320:
            raise ValueError(
                f"CPU 小算例约束 0 < steps ≤ 320，实得 steps={self.steps}")
        if self.resolution <= 0 or self.wavelength <= 0:
            raise ValueError("resolution/wavelength 必须为正")
        if not (0 < self.slab_voxels_x <= self.nx
                and 0 < self.slab_voxels_y <= self.ny):
            raise ValueError(
                f"slab 体素数须落在 (0, 单胞] 内："
                f"{self.slab_voxels_x}x{self.slab_voxels_y} vs "
                f"{self.nx}x{self.ny}")
        if self.eps_air <= 0 or self.eps_diel <= 0:
            raise ValueError("介电常数必须为正（fdtdx 材料口径）")
        if self.y_boundary not in ("pec", "pml"):
            raise ValueError(
                f"y_boundary 必须为 pec|pml，实得 {self.y_boundary}")
        if self.y_boundary == "pml":
            if self.pml_thickness < 1:
                raise ValueError("pml_thickness 必须 ≥1")
            free_y = self.ny - 2 * self.pml_thickness
            if free_y < 1:
                raise ValueError(
                    f"pml 厚度 {self.pml_thickness} 放不进 ny={self.ny} 芯层")
            if self.slab_voxels_y > free_y:
                raise ValueError(
                    f"slab_voxels_y={self.slab_voxels_y} 超出 pml 内侧自由区 "
                    f"{free_y}")
        core = self.nx * self.ny * self.nz_core
        if core > self.voxel_budget:
            raise ValueError(
                f"芯层体素预算超限：nx*ny*nz={core} > {self.voxel_budget}"
                "（请缩单胞或调 voxel_budget）")

    @property
    def total_voxels(self) -> tuple[int, int, int]:
        """芯层体素数（壳层由引擎侧边界配置处理，不含在本口径）。"""
        return (self.nx, self.ny, self.nz_core)

    def time_total(self, courant_factor: float = 0.99) -> float:
        """总时长（秒）= steps × dt，dt=courant·resolution/(c√3)（3D CFL，
        同 fdtd_diff 口径）。"""
        c0 = 299_792_458.0
        dt = courant_factor * self.resolution / (c0 * math.sqrt(3.0))
        return self.steps * dt


def pass_band_mask(
    s21_db: Any, threshold_db: float,
) -> np.ndarray:
    """|S21| dB 通带掩码（s21_db ≥ threshold_db；fail-closed 形状校验）。"""
    arr = np.asarray(s21_db, dtype=float)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError(f"s21_db 须为非空一维数组，实得 {arr.shape}")
    if not math.isfinite(float(threshold_db)):
        raise ValueError(f"threshold_db 必须有限，实得 {threshold_db!r}")
    return arr >= float(threshold_db)


def band_edges(
    freqs: Any, mask: Any,
) -> tuple[float, float, float] | None:
    """通带掩码 → (f_lo, f_hi, bandwidth)；无通带点如实 None。"""
    f = np.asarray(freqs, dtype=float).ravel()
    m = np.asarray(mask, dtype=bool).ravel()
    if f.size != m.size or f.size == 0:
        raise ValueError(
            f"freqs/mask 形状不符: {f.shape} vs {m.shape}")
    idx = np.flatnonzero(m)
    if idx.size == 0:
        return None
    # 带边=首个/末个通带点（单点带带宽=0）；带内空洞如实不合并
    # （判读人看掩码形态，本函数不做插值补洞——不虚构带结构）
    return float(f[idx[0]]), float(f[idx[-1]]), float(f[idx[-1]] - f[idx[0]])


def probe_fdtdx_periodic_support(
    fdtdx_module: Any | None = None,
) -> tuple[str, str]:
    """fdtdx 周期边界支持性运行时实录探针（源码证据，非文档转述）。

    Returns:
        (status, evidence)：status ∈ {"not_installed", "unsupported",
        "supported"}；evidence 为命中源码行（截断 400 字符）或空。
        fdtdx_module 供测试注入（None=真实 import 探测；注入模块含
        ``boundaries``（或 ``boundaries.initialization``）子模块时直读
        其源码——测试面可达；否则落真实 fdtdx 导入链）。
    """
    if fdtdx_module is None:
        try:
            import fdtdx as fdtdx_module  # type: ignore[no-redef]
        except ImportError:
            return ("not_installed",
                    "fdtdx 未安装（可选依赖 extras: diff-fdtd）")
    bnd_init = getattr(fdtdx_module, "boundaries", None)
    if bnd_init is not None:
        bnd_init = getattr(bnd_init, "initialization", bnd_init)
    else:
        try:
            from fdtdx.objects.boundaries import initialization as bnd_init
        except ImportError:
            try:
                from fdtdx.objects import boundaries as bnd_init  # type: ignore[no-redef]
            except ImportError:
                return ("unsupported",
                        "fdtdx.objects.boundaries.initialization 不可导入"
                        "（与 fdtd_diff.py 实录的模块布局不符）")
    try:
        src = inspect.getsource(bnd_init)
    except (OSError, TypeError) as exc:
        return ("unsupported", f"源码不可读（{exc!r}）——支持性无法实录")
    for token in PERIODIC_EVIDENCE_TOKENS:
        for line in src.splitlines():
            if token in line and not line.strip().startswith("#"):
                return ("supported", line.strip()[:400])
    return ("unsupported",
            "boundaries 初始化源码无周期证据词"
            f"（tokens={PERIODIC_EVIDENCE_TOKENS}）——周期边界待证")


def require_fdtdx_periodic(
    fdtdx_module: Any | None = None,
) -> tuple[str, str]:
    """apply 前置门：fdtdx 在场且源码证据支持周期边界才放行。

    Raises:
        RuntimeError: not_installed（附 extras 指路）或 unsupported
        （附证据/无证据说明）。
    """
    status, evidence = probe_fdtdx_periodic_support(fdtdx_module)
    if status == "not_installed":
        raise RuntimeError(
            f"周期边界通道需要 fdtdx（可选依赖）：pip install -e .[diff-fdtd]"
            f"——{evidence}")
    if status == "unsupported":
        raise RuntimeError(
            "已安装 fdtdx 的边界源码无周期支持证据（SV-4 待证项，fail-closed "
            f"拒绝猜测 API）——{evidence}；请以安装版源码实录后接线")
    return status, evidence
