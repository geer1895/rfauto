"""SV-2：PyPO 物理光学适配器——大电尺寸反射面/准光通道 + 闭式互证裁判。

规格（round14 §六 SV-2）："喇叭/反射面/罩秒级预估，horn_synthesis 闭式
互证后做布局级预筛。验收：抛物面口径效率落闭式带、指向偏差≤束宽 10%."

许可边界（与 SV-1 同门，:mod:`rfauto.adapters.gpl.license_gate`）：PyPO
为 GPL-3——进程内 import 属 GPL 传染面，故 ``require_pypo()`` 执行前
必须过显式 opt-in 门（缺省拒绝）；可选依赖（pypopy 包）缺席时显式
报错指路，绝不静默降级。

本适配器三层（只有第 3 层可离线完整验证，前两层=接口位+真机 opt-in）：

1. **配置生成**（确定性纯函数）：:func:`parabolic_reflector_config`——
   抛物面反射器 + 喇叭馈源的 PyPO 通道几何/扫频描述 dict（口径 D、
   焦距 f、边缘角、频率栅格），供 PyPO 侧消费或纯文档记录；
2. **执行通道**（opt-in+可选依赖）：:meth:`PypoAdapter.solve` 惰性
   ``import pypopy``，缺席显式报错——API 调用面按其官方文档实录后
   接线（本机未装，#215 禁臆写，solve 走 fail 路径并如实标注）；
3. **闭式互证裁判**（全离线可测，验收"口径效率落闭式带"的我方锚）：
   - :func:`ruze_surface_efficiency`——Ruze 1966 表面误差效率
     η = exp[−(4πσ/λ)²]（σ/λ 同单位）；
   - :func:`uniform_aperture_gain`——均匀照射圆口径增益闭式
     G = η·(πD/λ)²（Balanis《Antenna Theory》口径天线章标准式），
     线性/ dB 双出口；
   - :func:`aperture_efficiency_band`——"落带"判定（闭式锚 ± 相对
     带），供真机 PyPO 结果对照。

闭式裁判的数值锚见 tests/unit/test_gpl_adapters.py docstring 预声明
（σ=0 → η=1；D=10λ、η=0.55 → G≈25.4 dBi 解析带）。
"""

from __future__ import annotations

import importlib.util
import logging
import math
from collections.abc import Mapping
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    SolverCapabilities,
)
from rfauto.adapters.gpl.license_gate import require_gpl_channel

logger = logging.getLogger(__name__)

PYPO_MODULE = "pypopy"
DEFAULT_TOLERANCE_REL = 0.15


def pypo_importable() -> bool:
    """pypopy 可导入性探测（不真正 import——探测不构成 GPL 交互）。"""
    return importlib.util.find_spec(PYPO_MODULE) is not None


def require_pypo(environ: Mapping[str, str] | None = None) -> None:
    """GPL 门 + 可选依赖双门（fail-closed；通过才允许走执行通道）。"""
    require_gpl_channel("pypo", environ)
    if not pypo_importable():
        raise RuntimeError(
            f"pypo 通道需要 {PYPO_MODULE} 包（GPL-3，可选依赖）："
            "pip install rfauto[pypo] 或 pip install pypopy；许可门"
            "（RFAUTO_ALLOW_PYPO=1 或 RFAUTO_ALLOW_GPL_TOOLS=1）与依赖"
            "二者缺一不可")


def parabolic_reflector_config(
    *,
    diameter_m: float,
    focal_length_m: float,
    freq_ghz: tuple[float, float, int],
    edge_taper_db: float = -10.0,
) -> dict[str, Any]:
    """抛物面反射器通道配置（确定性纯函数；PyPO 执行面/文档面共用）。

    校验：D>0、f>0、频栅 n≥1 且 f0≤f1、边缘锥削为负 dB；边缘角由
    D/f 闭式导出（θ_e = 2·atan(D/(4f))，抛物面几何恒等式）。
    """
    d = float(diameter_m)
    f = float(focal_length_m)
    f0, f1, n = (float(freq_ghz[0]), float(freq_ghz[1]), int(freq_ghz[2]))
    if d <= 0.0 or f <= 0.0:
        raise ValueError("diameter/focal_length 必须 >0")
    if n < 1 or not 0.0 < f0 <= f1:
        raise ValueError(f"频栅非法: {freq_ghz!r}")
    et = float(edge_taper_db)
    if et >= 0.0:
        raise ValueError(f"edge_taper_db 须为负 dB（锥削），实得 {et}")
    theta_edge_rad = 2.0 * math.atan(d / (4.0 * f))
    return {
        "kind": "parabolic_reflector",
        "diameter_m": d,
        "focal_length_m": f,
        "edge_angle_rad": theta_edge_rad,
        "edge_taper_db": et,
        "freq_ghz": (f0, f1, n),
    }


def ruze_surface_efficiency(
    sigma: float, wavelength: float,
) -> float:
    """Ruze 表面误差效率 exp[−(4πσ/λ)²]（σ/λ 同单位；σ≥0、λ>0）。"""
    if isinstance(sigma, bool) or not math.isfinite(float(sigma)) or float(sigma) < 0.0:
        raise ValueError(f"sigma 必须 ≥0 有限，实得 {sigma!r}")
    if isinstance(wavelength, bool) or not math.isfinite(float(wavelength)) \
            or float(wavelength) <= 0.0:
        raise ValueError(f"wavelength 必须 >0 有限，实得 {wavelength!r}")
    x = 4.0 * math.pi * float(sigma) / float(wavelength)
    return math.exp(-x * x)


def uniform_aperture_gain(
    diameter: float, wavelength: float, eta: float,
) -> float:
    """均匀照射圆口径增益 G = η·(πD/λ)²（线性倍数；η∈(0,1]）。"""
    for name, val in (("diameter", diameter), ("wavelength", wavelength)):
        if isinstance(val, bool) or not math.isfinite(float(val)) \
                or float(val) <= 0.0:
            raise ValueError(f"{name} 必须 >0 有限，实得 {val!r}")
    if isinstance(eta, bool) or not 0.0 < float(eta) <= 1.0:
        raise ValueError(f"eta 必须落在 (0,1]，实得 {eta!r}")
    return float(eta) * (math.pi * float(diameter) / float(wavelength)) ** 2


def uniform_aperture_gain_db(
    diameter: float, wavelength: float, eta: float,
) -> float:
    """同上，dB（dBi）。"""
    return 10.0 * math.log10(uniform_aperture_gain(diameter, wavelength, eta))


def aperture_efficiency_band(
    gain_db_measured: float,
    diameter: float,
    wavelength: float,
    *,
    tol_rel: float = DEFAULT_TOLERANCE_REL,
) -> dict[str, Any]:
    """「口径效率落闭式带」判定（SV-2 验收我方锚；fail-closed 形态）。

    由实测/预估增益反解 η_meas = G_lin/(πD/λ)²，与理想带 [η_lo, 1]
    对照：η_lo = 声明锥削档的名义口径效率（缺省 0.35=典型边缘锥削
    -10dB 档的工程下界，Balanis 口径天线章量级——声明为工程锚非精确
    闭式），tol_rel 为 η 相对带容差。
    """
    g_lin = 10.0 ** (float(gain_db_measured) / 10.0)
    g_ideal = (math.pi * float(diameter) / float(wavelength)) ** 2
    if g_ideal <= 0.0:
        raise ValueError("口径/波长非法（理想增益 ≤0）")
    eta_meas = g_lin / g_ideal
    eta_lo = 0.35 * (1.0 - float(tol_rel))
    eta_hi = min(1.0 * (1.0 + float(tol_rel)), 1.05)
    in_band = eta_lo <= eta_meas <= eta_hi
    return {
        "eta_measured": float(eta_meas),
        "band": (float(eta_lo), float(eta_hi)),
        "tol_rel": float(tol_rel),
        "in_band": bool(in_band),
    }


class PypoAdapter(EMSolverAdapter):
    """PyPO 物理光学通道（GPL opt-in 门 + 可选依赖双门；闭式裁判见模块级）。"""

    #: 能力声明（如实：PO 预估面=接口位；场导出/端口/收敛报告/SAR 均
    #: 未实现；license=GPL 免费但 fail-closed opt-in 门）
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="pypo",
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="3d",
        material_models=("pec",),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=(),
        requires_license=False,
        availability_gate="gpl_optin+pypopy",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        self._geometry: dict[str, Any] | None = None

    def is_available(self) -> bool:
        # 可用性=依赖在盘（探测不执行工具）；许可门在 connect 执行点强制。
        return pypo_importable()

    def connect(self) -> bool:
        require_pypo()
        self._connected = True
        return True

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        if not self._connected:
            return False
        try:
            cfg = parabolic_reflector_config(
                diameter_m=float(geometry["diameter_m"]),
                focal_length_m=float(geometry["focal_length_m"]),
                freq_ghz=tuple(geometry["freq_ghz"]),
                edge_taper_db=float(geometry.get("edge_taper_db", -10.0)))
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("pypo 配置生成失败: %s", exc)
            return False
        self._geometry = cfg
        return True

    def solve(self) -> EMSolverResult:
        """执行 PyPO 物理光学预估（API 面待实录；未装/未接线如实 FAIL）。

        本机未装 pypopy（可选依赖）且其 API 调用面未经源码实录（#215
        禁臆写）——通道在此如实走失败路径并指明接线要求；闭式裁判
        （ruze/uniform_aperture_gain）不依赖本方法，可独立离线使用。
        """
        try:
            require_pypo()
        except (RuntimeError, PermissionError) as exc:
            return EMSolverResult(success=False, message=str(exc))
        # 到这里=已装+已 opt-in；API 实录接线为后续项（spec 真机面）。
        return EMSolverResult(
            success=False,
            message="pypopy API 调用面待官方文档实录后接线（#215 禁臆写）；"
                    "闭式裁判面（ruze_surface_efficiency / "
                    "uniform_aperture_gain）与执行无关，可直接使用")

    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        raise RuntimeError("pypo 为 PO 预估通道（无 S 参数产物）；"
                           "远场/口径面接线后另行声明")

    def close(self) -> None:
        self._connected = False


def register_pypo(registry: Any | None = None) -> None:
    """注册 pypo 通道（自定义字符串键；import rfauto.adapters.gpl 即注册）。"""
    from rfauto.adapters.em_solver_base import get_global_registry

    target = registry or get_global_registry()
    target.register("pypo", PypoAdapter)


register_pypo()
