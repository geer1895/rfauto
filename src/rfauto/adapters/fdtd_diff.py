"""FDTDX 可微 FDTD 引擎薄封装（"真引擎"CPU 接入）。

定位：可微设计验证通道。自研小 FDTD（scripts/jax_probe.py）
确证 jax CPU 梯度通路后，本模块接入真引擎
`fdtdx <https://github.com/ymahlau/fdtdx>`_（arXiv 2412.12360，JAX 原生可微
FDTD），用于可微设计研究；**不是** S 参数求解通道，不接入 EMSolverRegistry
（EMSolverAdapter 面向频域 S 参数抽取，与本模块的 jax.grad 可微目标不同）。

纪律（与 comsol_adapter 同源）：
- fdtdx 属可选依赖（pyproject extras ``diff-fdtd``），一切 import 惰性进入，
 未安装时 :func:`fdtdx_installed` 返回 False / 调用显式报错；
- API 一律对照本地 site-packages 的 fdtdx 0.6.2 源码实录，禁止凭想象写：
 * 场景组装流程：fdtdx/utils/sparams.py ``setup_sparams_simulation``（仓内
  规范范例）——SimulationVolume + boundary_objects_from_config + 约束列表
  → place_objects → apply_params → run_fdtd；
 * 可微参数通路：fdtdx/objects/device/device.py ``Device``（连续参数、
  两材料线性插值），插值实现见 fdtdx/fdtd/initialization.py
  ``apply_params``（ParameterType.CONTINUOUS 分支）；
 * 梯度配置：fdtdx/config.py ``GradientConfig`` 双方法——"checkpointed"
  （``num_checkpoints=N``，默认，CPU 小算例现状）与 "reversible"（config.py
  ``__post_init__`` 强制 ``recorder=Recorder``，缺则 raise）；记录间隔用
  ``LinearReconstructEveryK(k)``（保存步自动补末步、重建=相邻 latent 线性
  插值，interfaces/time_filter.py:140-209 实录）；Recorder 只挂 PML 界面场
  （fdtd/initialization.py:769-784 从 objects.pml_objects 建形）——PEC-only
  腔 pml_objects 为空，空 recording_state 可机械走通（可逆性由 PEC 切向 E
  显式清零投影的反向恒等保证，objects/boundaries/pec.py:13-27）；
 * 边界类型串："pml"/"periodic"/"pec"/"pmc"/"bloch"（boundary_objects_
  from_config 源码 ValueErr 分支实录）；PEC/PMC 占 1 格，PML 厚度可配
  （from_uniform_bound(thickness=N)）；6 面可逐面 override_types 混搭
  （2D TMz 薄域 z 向放不下 PML 时钉 pec）。

最小算例（:class:`CavitySpec` 默认值）：2D TMz 型 PEC 腔——38×38×3 体素
（z 向 1 格芯层 + 上下 PEC 壳），中心 10×10 可连续变介电方块（单标量潜参
p∈[0,1] 线性插值 εr: 1→6），Ez 点偶极子激励，EnergyDetector 全域能量为
目标函数；jax.grad 对 p 求梯度，对照中心差分（有限差分残差是 float32
底噪 + O(h²) 截断，实测 320 步 rel_err≈6e-5 @ h=1e-2）。

扩展面（默认参数逐字保持上述现状）：gradient_method="reversible" 走
Recorder 可逆反传（P2⑮ 子项 A）；boundary="pml" 开放吸收腔承载非空
Recorder 界面记录，供 recorder_k 检查点/重算权衡量化（子项 B）；
nz_core>1 为 3D 真腔（子项 C，validate 增 3D 体素预算守卫，4GB 内存信封）。

fdtdx 0.6.2 实测局限（本机隔离矩阵）：可逆反传×PML 边界时，
介电器件距 PML 记录界面贴距 ≤2 格会反向重构 nan（float64 同现、前向记录
有限、20 步即现）——validate 已按实测安全界（贴距 ≥3 格）设守卫；PEC 腔
（无 PML）不受影响。
"""

from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass, field
from typing import Any

_C0 = 3e8
# fdtdx SimulationConfig.courant_number = courant_factor / sqrt(3)（config.py 实录），
# 与 c0 一起决定 dt；此处显式复算而非依赖 config2（place_objects 返回值）之外的状态。
_COURANT_FACTOR = 0.99

_DEVICE_NAME = "Block"
_SOURCE_NAME = "Dipole"
_DETECTOR_NAME = "Energy"
_VOLUME_NAME = "Background"


def fdtdx_installed() -> bool:
  """fdtdx 可导入性探测（不真正 import，避免把重依赖拉进无关进程）。"""
  return importlib.util.find_spec("fdtdx") is not None


def _require_fdtdx() -> Any:
  if not fdtdx_installed():
    raise RuntimeError(
      "fdtdx 未安装。请安装可选依赖：pip install -e .[diff-fdtd]"
      "（fdtdx>=0.6.2，经 tidy3d 间接要求 numpy<2.5、fastmcp<4）"
    )
  import fdtdx  # 惰性导入（可选依赖纪律）

  return fdtdx


@dataclass(frozen=True)
class CavitySpec:
  """2D TMz 型 PEC 腔最小可微算例的几何/物理参数。

  单位约定：resolution 为米（fdtdx 全程 SI），网格数为整数体素计数。
  网格规模约束（A7 CPU 小验证口径）：nx,ny ≤ 64、steps ≤ 320。
  """

  #: x/y 向芯层体素数（另加四周各 1 格 PEC 壳）
  nx: int = 36
  ny: int = 36
  #: z 向芯层体素数（TMz 型取 1，另加上下各 1 格 PEC 壳）
  nz_core: int = 1
  #: 空间分辨率（米/体素）
  resolution: float = 20e-9
  #: 时间步数（≤320 控 CPU 时长）
  steps: int = 320
  #: 激励波长（米）
  wavelength: float = 600e-9
  #: 可变介电方块的边长（体素，x/y 向；z 向 1 体素芯层）
  device_voxels: int = 10
  #: 偶极子偏置（占全域边长的比例，从 min 角量起）
  source_offset_frac: float = 0.30
  #: 插值区间两端介电常数：p=0 → eps_air，p=1 → eps_diel
  eps_air: float = 1.0
  eps_diel: float = 6.0
  #: 潜参数张量形状（fdtdx Device 的 voxel 矩阵；(1,1,1)=单标量有效介电）
  param_shape: tuple[int, int, int] = (1, 1, 1)
  #: 梯度反传方法："checkpointed"（默认现状）| "reversible"（Recorder 可逆梯度）
  gradient_method: str = "checkpointed"
  #: checkpointed 反传检查点数（gradient_method="checkpointed" 时生效，fdtdx 要求 ≥1）
  num_checkpoints: int = 8
  #: reversible 反传的 LinearReconstructEveryK 记录间隔 k（保存步自动补末步）
  recorder_k: int = 2
  #: 边界类型："pec"（全封闭腔，默认现状）| "pml"（开放吸收边界，承载 Recorder 界面记录）
  boundary: str = "pec"
  #: pml 边界厚度（体素；boundary="pml" 时生效，pec 恒 1 格）
  boundary_thickness: int = 2
  #: 3D 体素预算上限（nz_core>1 时芯层总体素 nx*ny*nz_core 的守卫线，4GB 内存信封）
  voxel_budget_3d: int = 4096

  def validate(self) -> None:
    if self.nx <= 0 or self.ny <= 0 or self.nz_core <= 0:
      raise ValueError(f"网格数必须为正：nx={self.nx}, ny={self.ny}, nz_core={self.nz_core}")
    if self.nx > 64 or self.ny > 64:
      raise ValueError(f"CPU 小算例约束 nx,ny ≤ 64，得到 nx={self.nx}, ny={self.ny}")
    if not 0 < self.steps <= 320:
      raise ValueError(f"CPU 小算例约束 0 < steps ≤ 320，得到 steps={self.steps}")
    if self.resolution <= 0:
      raise ValueError(f"resolution 必须为正，得到 {self.resolution}")
    if self.device_voxels <= 0 or self.device_voxels > min(self.nx, self.ny):
      raise ValueError(f"device_voxels 必须在 (0, min(nx,ny)] 内，得到 {self.device_voxels}")
    if self.eps_air <= 0 or self.eps_diel <= 0:
      raise ValueError("介电常数必须为正（fdtdx 材料口径）")
    # —— 以下为 P2⑮ 扩展守卫（默认参数全部放行，不改变既有行为）——
    if self.gradient_method not in ("checkpointed", "reversible"):
      raise ValueError(f"gradient_method 必须为 checkpointed|reversible，得到 {self.gradient_method}")
    if self.num_checkpoints <= 0:
      raise ValueError(f"num_checkpoints 必须为正整数（fdtdx GradientConfig 要求），得到 {self.num_checkpoints}")
    if self.recorder_k <= 0:
      raise ValueError(f"recorder_k 必须为正整数（LinearReconstructEveryK.k），得到 {self.recorder_k}")
    if self.boundary not in ("pec", "pml"):
      raise ValueError(f"boundary 必须为 pec|pml，得到 {self.boundary}")
    if self.boundary_thickness <= 0:
      raise ValueError(f"boundary_thickness 必须为正整数，得到 {self.boundary_thickness}")
    if self.boundary == "pml":
      free_x = self.nx + 2 - 2 * self.boundary_thickness
      free_y = self.ny + 2 - 2 * self.boundary_thickness
      if min(free_x, free_y) < 1:
        raise ValueError(
          f"pml 厚度 {self.boundary_thickness} 放不进 x/y 向包络"
          f"（自由区 {min(free_x, free_y)} 格），请减薄 pml 或加大网格"
        )
      if self.device_voxels > min(free_x, free_y):
        raise ValueError(
          f"device_voxels={self.device_voxels} 超出 pml 内侧自由区 {min(free_x, free_y)} 格"
        )
      if self.nz_core > 1 and self.nz_core + 2 - 2 * self.boundary_thickness < 1:
        raise ValueError(
          f"pml 厚度 {self.boundary_thickness} 放不进 z 向包络（nz_core={self.nz_core}）"
        )
    if self.nz_core > 1:
      core_voxels = self.nx * self.ny * self.nz_core
      if core_voxels > self.voxel_budget_3d:
        raise ValueError(
          f"3D 体素预算守卫（4GB 内存信封，shape 派生）：芯层总体素"
          f" nx*ny*nz_core={self.nx}*{self.ny}*{self.nz_core}={core_voxels}"
          f" > {self.voxel_budget_3d}，请缩网格（1e-3 梯度门限不缩）"
        )
    if self.boundary == "pml" and self.gradient_method == "reversible":
      # 本机隔离矩阵实测（fdtdx 0.6.2）：介电器件距 PML 记录界面贴距 ≤2 格时
      # 反向重构产生 nan（2D gap2 nan / gap3 正常；3D z 向贴距 ≤1 nan；float64
      # 同现、前向记录有限、20 步即现——非溢出累积，机制归因待上游）。贴距 ≥3
      # 格为实测安全界，写入守卫防静默 nan。
      free_x = self.nx + 2 - 2 * self.boundary_thickness
      free_y = self.ny + 2 - 2 * self.boundary_thickness
      gaps = [(free_x - self.device_voxels) / 2.0, (free_y - self.device_voxels) / 2.0]
      if self.nz_core > 1:
        free_z = self.nz_core + 2 - 2 * self.boundary_thickness
        gaps.append((free_z - self.device_z_voxels) / 2.0)
      if min(gaps) < 3:
        raise ValueError(
          f"可逆反传×pml 贴距守卫：介电器件须距 PML 记录界面 ≥3 格"
          f"（实测 gap≤2 反传 nan），当前最小贴距 {min(gaps)} 格，"
          f"请缩小 device_voxels 或减薄 boundary_thickness"
        )

  @property
  def total_voxels(self) -> tuple[int, int, int]:
    """全域体素数（每向 +2 壳包络；boundary="pml" 时厚 PML 同样占用该包络，
    内侧自由区相应收窄为 N+2-2*thickness 格）。"""
    return (self.nx + 2, self.ny + 2, self.nz_core + 2)

  @property
  def device_z_voxels(self) -> int:
    """器件 z 向体素数：z 向为 PEC 时填满芯层（=nz_core，含既有 2D 现状）；
    z 向为 PML 时留 3 格贴距（fdtdx 0.6.2 可逆反传实测安全界，见 validate）。"""
    if self.boundary == "pml" and self.nz_core > 1:
      return max(1, self.nz_core + 2 - 2 * self.boundary_thickness - 6)
    return self.nz_core

  def time_total(self) -> float:
    """总仿真时长（秒）= steps × dt，dt=courant·resolution/c（config.py 实录）。"""
    return self.steps * (_COURANT_FACTOR / math.sqrt(3.0)) * self.resolution / _C0

  def eps_eff(self, p: float) -> float:
    """潜参数 p 的等效介电常数（inv-ε 线性插值的倒数，与 apply_params 连续分支一致）。"""
    return 1.0 / ((1.0 - p) / self.eps_air + p / self.eps_diel)


@dataclass
class _SceneContainers:
  """place_objects 产出的三大容器（类型留 Any：fdtdx pytree 不进本层签名）。"""

  arrays: Any
  objects: Any
  config: Any
  key: Any


@dataclass
class GradCheck:
  """单点梯度核对结果（jax.grad vs 中心差分）。"""

  p: float
  loss: float
  grad: float
  finite_diff: float
  rel_err: float
  h: float


@dataclass
class DiffCavity:
  """已装配的可微 PEC 腔：提供 jax 可追踪的能量目标函数与梯度核对。

  用法（fdtdx 已安装时）::

    cavity = DiffCavity.build(CavitySpec())
    loss = cavity.energy_loss(0.5)         # 前向
    g = cavity.grad_at(0.5)            # jax.grad
    chk = cavity.grad_fd_check(0.5, h=1e-2)    # 对照中心差分
  """

  spec: CavitySpec
  _scene: _SceneContainers = field(repr=False)

  @classmethod
  def build(cls, spec: CavitySpec | None = None) -> DiffCavity:
    """按 spec 组装场景（约束解析 + 网格放置 + 参数/数组初始化）。"""
    spec = spec or CavitySpec()
    spec.validate()
    fdtdx = _require_fdtdx()

    import jax
    from fdtdx.config import GradientConfig, SimulationConfig
    from fdtdx.core.wavelength import WaveCharacter
    from fdtdx.fdtd.initialization import place_objects
    from fdtdx.materials import Material
    from fdtdx.objects.boundaries.initialization import BoundaryConfig, boundary_objects_from_config
    from fdtdx.objects.device.device import Device

    res = spec.resolution
    total = tuple(n * res for n in spec.total_voxels)
    if spec.gradient_method == "reversible":
      # config.py __post_init__ 强制：reversible 缺 recorder 显式 raise
      grad_cfg = GradientConfig(
        method="reversible",
        recorder=fdtdx.Recorder(modules=[fdtdx.LinearReconstructEveryK(k=spec.recorder_k)]),
      )
    else:
      grad_cfg = GradientConfig(method="checkpointed", num_checkpoints=spec.num_checkpoints)
    config = SimulationConfig(
      time=spec.time_total(),
      resolution=res,
      backend="cpu",
      gradient_config=grad_cfg,
    )

    volume = fdtdx.SimulationVolume(partial_real_shape=total, name=_VOLUME_NAME)
    # 2D TMz 薄域（nz_core=1，z 向总高 3 格）放不下 PML（2*thickness>3），
    # z 向钉 pec：Ez 为 z 壁法向场，TMz 物理不受 z 壁类型影响
    if spec.boundary == "pml":
      override = None
      if spec.nz_core == 1:
        override = {"min_z": "pec", "max_z": "pec"}
      bound_cfg = BoundaryConfig.from_uniform_bound(
        thickness=spec.boundary_thickness,
        boundary_type="pml",
        override_types=override,
      )
    else:
      bound_cfg = BoundaryConfig.from_uniform_bound(thickness=1, boundary_type="pec")
    boundaries, boundary_constraints = boundary_objects_from_config(bound_cfg, volume)

    dv = spec.device_voxels
    dz = spec.device_z_voxels
    device = Device(
      materials={
        "air": Material(permittivity=spec.eps_air),
        "diel": Material(permittivity=spec.eps_diel),
      },
      param_transforms=(),
      partial_real_shape=(dv * res, dv * res, dz * res),
      partial_voxel_grid_shape=(dv, dv, dz),
      name=_DEVICE_NAME,
    )
    source = fdtdx.PointDipoleSource(
      partial_real_shape=(res, res, res),
      polarization=2, # Ez（TMz 型激励）
      wave_character=WaveCharacter(wavelength=spec.wavelength),
      name=_SOURCE_NAME,
    )
    detector = fdtdx.EnergyDetector(
      partial_real_shape=total,
      reduce_volume=True, # 每步记录标量能量 {"energy": (1,)}
      name=_DETECTOR_NAME,
    )

    margins = (
      spec.source_offset_frac * spec.total_voxels[0] * res,
      spec.source_offset_frac * spec.total_voxels[1] * res,
      # 芯层 z 中心：min 壳(1 格) + 芯层一半
      (1.0 + spec.nz_core / 2.0) * res,
    )
    object_list = [volume, *boundaries.values(), device, source, detector]
    constraints = [
      *boundary_constraints,
      device.place_at_center(volume),
      source.place_relative_to(
        volume,
        axes=(0, 1, 2),
        own_positions=(0, 0, 0),
        other_positions=(-1, -1, -1),
        margins=margins,
      ),
      detector.place_at_center(volume),
    ]

    key = jax.random.PRNGKey(0)
    objects, arrays, _params, config2, _info = place_objects(
      object_list=object_list,
      config=config,
      constraints=constraints,
      key=key,
    )
    return cls(spec=spec, _scene=_SceneContainers(arrays=arrays, objects=objects, config=config2, key=key))

  def energy_loss(self, p: float | Any) -> Any:
    """目标函数：给定潜参数 p，返回仿真末步全域能量（jax 可追踪标量）。

    内部走 fdtdx 规范流程 apply_params（Device 连续两材料插值写入
    inv_permittivities，梯度可穿）→ run_fdtd（checkpointed 反传）。
    """
    import jax.numpy as jnp
    from fdtdx.fdtd.initialization import apply_params
    from fdtdx.fdtd.wrapper import run_fdtd

    scene = self._scene
    p_arr = jnp.asarray(p, dtype=jnp.float32) * jnp.ones(self.spec.param_shape, dtype=jnp.float32)
    arrays, objects, _ = apply_params(scene.arrays, scene.objects, {_DEVICE_NAME: p_arr}, scene.key)
    _, final = run_fdtd(arrays=arrays, objects=objects, config=scene.config, key=scene.key, show_progress=False)
    return final.detector_states[_DETECTOR_NAME]["energy"][-1, 0]

  def loss_at(self, p: float) -> float:
    """前向求值（jit 编译缓存由 jax 管理）。"""
    import jax

    return float(jax.jit(self.energy_loss)(p))

  def grad_at(self, p: float) -> float:
    """jax.grad 对潜参数 p 的梯度（标量）。"""
    import jax

    return float(jax.jit(jax.grad(lambda q: self.energy_loss(q)))(p))

  def grad_fd_check(self, p: float, h: float = 1e-2) -> GradCheck:
    """单点梯度核对：jax.grad 对照中心差分 (L(p+h)-L(p-h))/(2h)。"""
    import jax

    if not 0.0 + h <= p <= 1.0 - h:
      raise ValueError(f"中心差分要求 h ≤ p ≤ 1-h：p={p}, h={h}")
    loss_fn = jax.jit(self.energy_loss)
    loss = float(loss_fn(p))
    grad = float(jax.jit(jax.grad(lambda q: self.energy_loss(q)))(p))
    fd = (float(loss_fn(p + h)) - float(loss_fn(p - h))) / (2.0 * h)
    rel = abs(grad - fd) / max(abs(fd), 1e-30)
    return GradCheck(p=p, loss=loss, grad=grad, finite_diff=fd, rel_err=rel, h=h)

  def recording_bytes(self) -> int:
    """reversible 反传 recording_state.data 的总字节数（shape 派生估算，零新依赖）。

    口径（fdtdx/interfaces/recorder.py ``init_state`` 实录）：data 各键形状 =
    (latent 数, *输出形状)，latent 数由 LinearReconstructEveryK 的保存步表决定
    （步数/k 向上取整，末步自动补）。checkpointed（无 recorder）或 PEC-only 腔
    （pml_objects 空 → 无界面键）返回 0，如实反映"无可记录数据"。
    """
    grad_cfg = self._scene.config.gradient_config
    if grad_cfg is None or grad_cfg.recorder is None:
      return 0
    rec = grad_cfg.recorder
    per_latent = 0
    for sd in rec._output_shape_dtypes.values():
      n = 1
      for d in sd.shape:
        n *= int(d)
      per_latent += n * int(sd.dtype.itemsize)
    return per_latent * int(rec._latent_array_size)


def cpu_probe_gradient_rel_err(spec: CavitySpec | None = None, p: float = 0.5, h: float = 1e-2) -> GradCheck:
  """便捷入口：装配 → 单点梯度核对（脚本/冒烟用；单测直接用 DiffCavity）。"""
  return DiffCavity.build(spec).grad_fd_check(p, h=h)
