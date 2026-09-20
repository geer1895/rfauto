r"""双向定点迭代温漂内核。

口径与公式来源（裁判 = 独立来源，不是本模块自己的推导，#118）
----------------------------------------------------------------
1) 电-热双向定点迭代（successive substitution）:

       T_{n+1} = T_amb + R_th * P_diss(T_n)

   其中 P_diss(T_n) 由链路「T_n -> eps_r(T)/tan_delta(T)/sigma(T) -> EM
   （f0, Qu）-> 损耗/失谐」给出。方法论锚：空间电子技术 2025.03.014
   星载 3D 打印天线「假定初温 -> eps_r(T) -> EM -> 损耗 -> T 定点迭代」
   （文献引用口径）；多物理电-热顺序求解（COMSOL Microwave
   Heating：Frequency-Stationary，先频域 Maxwell 再稳态热）同构。
   迭代只做确定性算术：无随机、无网络、无真机。

2) 温度系数与一阶温漂闭式（验收对照，独立于迭代实现）:

       TCDk = (1/eps_r) d(eps_r)/dT   [ppm/K]
       CTE  = (1/L)     dL/dT        [ppm/K]
       f0 = c / (2 L sqrt(eps_eff))
       =>  df0/f0 = -CTE * dT - (1/2) * TCDk_eff * dT

   来源：Pozar, Microwave Engineering, 4th ed.（谐振器温漂的对数一阶展开，
   同 core/calculators.py resonator_thermal_drift）。本模块给出该闭式的
   独立实现 closed_form_drift_ratio，单测与计算器逐值互证。

3) 微带准静态 eps_eff / Z0：Hammerstad-Jensen 闭式，Pozar 4th ed. §3.8
   eqs. (3.195)-(3.197)。

4) 导体表面电阻 Rs = sqrt(pi f mu0 / sigma)（趋肤效应，Pozar §1.7.1）；
   导体衰减 alpha_c = Rs/(Z0 w)（Pozar §2.7）；介质衰减
   alpha_d = (pi/lambda0) * (eps_r/sqrt(eps_eff)) * ((eps_eff-1)/(eps_r-1))
             * tan_delta（Hammerstad/Pozar §3.8，eps_r->1 时该项为 0）；
   半波谐振器 Qu = pi/(2 alpha L)（由 Q = beta/(2 alpha) 与 L = lambda_g/2，
   Pozar §6.4）。

5) 单端口谐振器耦合/失谐吸收率:

       |Gamma|^2 = ((1-beta)^2 + (2 Qu delta)^2) / ((1+beta)^2 + (2 Qu delta)^2)
       P_diss/P_in = 1 - |Gamma|^2 = 4 beta / ((1+beta)^2 + (2 Qu delta)^2)
       delta = (1/2)(f_drive/f0 - f0/f_drive)

   来源：Pozar §6.4（耦合系数 beta = Qu/Qe 与 loaded-Q 反射口径）。

设计约束
--------
- core 叶子层：只 import 标准库（math/dataclasses/typing），连 numpy 都不引，
  保证"core 零依赖叶子"最强口径；全部纯函数 / 冻结数据类。
- 非法输入显式 ValueError，不静默兜底；from_dict 拒绝未知字段。
- EM 评估函数（返回 f0/Qu）与损耗评估函数（返回耗散功率 W）均可注入，
  便于离线确定性测试或替换为场求解器回调；默认给微带解析链。
- 全部 to_dict 结果 JSON 可序列化（allow_nan=False 安全，不含 inf/nan）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# 物理常量与迭代默认口径
# ---------------------------------------------------------------------------

C0_M_PER_S = 299792458.0             # 真空光速 [m/s]（CODATA）
MU0_H_PER_M = 1.2566370614359173e-6  # 真空磁导率 [H/m]（CODATA 2018）

# 验收口径：微带谐振器 -40~85 C 场景迭代 <= 5 轮收敛
DEFAULT_MAX_ITERATIONS = 5
MAX_ITERATIONS_LIMIT = 100
# 收敛判据默认 1 kHz：对 GHz 级谐振器约 0.4 ppm，比温漂量级（10^2~10^3 ppm）
# 小 3 个量级，同时高于任何有意义的测量/仿真分辨需求（避免为凑精度白跑迭代）。
DEFAULT_FREQ_TOLERANCE_HZ = 1000.0
DEFAULT_DIVERGENCE_PATIENCE = 3

STATUS_CONVERGED = "converged"
STATUS_MAX_ITERATIONS = "max_iterations"
STATUS_DIVERGED = "diverged"
STATUS_OUT_OF_BOUNDS = "out_of_bounds"

EMEvaluator = Callable[["MaterialState", float], "EMEvaluation"]
LossEvaluator = Callable[["EMEvaluation", float], float]

__all__ = [
    "C0_M_PER_S",
    "DEFAULT_DIVERGENCE_PATIENCE",
    "DEFAULT_FREQ_TOLERANCE_HZ",
    "DEFAULT_MAX_ITERATIONS",
    "MAX_ITERATIONS_LIMIT",
    "MU0_H_PER_M",
    "STATUS_CONVERGED",
    "STATUS_DIVERGED",
    "STATUS_MAX_ITERATIONS",
    "STATUS_OUT_OF_BOUNDS",
    "EMEvaluation",
    "MaterialState",
    "MaterialTemperatureModel",
    "ResonatorGeometry",
    "ThermalIterationConfig",
    "ThermalIterationResult",
    "ThermalIterationStep",
    "closed_form_drift_ratio",
    "evaluate_resonator_f0",
    "make_microstrip_em",
    "microstrip_characteristic_impedance",
    "microstrip_effective_permittivity",
    "microstrip_resonator_em",
    "one_port_dissipated_power",
    "run_thermal_iteration",
    "solve_thermal_fixed_point",
    "surface_resistance",
]


# ---------------------------------------------------------------------------
# 通用校验 / JSON 解析助手
# ---------------------------------------------------------------------------

def _require_finite(value: Any, name: str) -> float:
    """把入参收敛为有限 float；非法即显式 ValueError。"""
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是实数，收到 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须是有限数，收到 {value!r}")
    return out


def _require_key(data: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ValueError(f"{where} 缺少字段 {key!r}")
    return data[key]


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{where} 含未知字段: {unknown}")


def _as_mapping(data: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError(f"{where} 必须是对象（dict）")
    return data


# ---------------------------------------------------------------------------
# 材料状态 / 几何 / 温度模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MaterialState:
    """某一温度下求解器实际看到的材料/几何状态。

    Args:
        temperature_c: 该状态的温度 [C]。
        eps_r: 相对介电常数实部（>0）。
        tan_delta: 损耗角正切（>=0）。
        sigma_s_per_m: 电导率 [S/m]（>=0；0 = 无导体损耗项）。
        length_scale: 几何长度相对参考温度的缩放 (1 + CTE dT + ...)，>0。
    """

    temperature_c: float
    eps_r: float
    tan_delta: float
    sigma_s_per_m: float
    length_scale: float

    def __post_init__(self) -> None:
        _require_finite(self.temperature_c, "temperature_c")
        if _require_finite(self.eps_r, "eps_r") <= 0.0:
            raise ValueError(f"eps_r 必须 >0，收到 {self.eps_r!r}")
        if _require_finite(self.tan_delta, "tan_delta") < 0.0:
            raise ValueError(f"tan_delta 必须 >=0，收到 {self.tan_delta!r}")
        if _require_finite(self.sigma_s_per_m, "sigma_s_per_m") < 0.0:
            raise ValueError(f"sigma_s_per_m 必须 >=0，收到 {self.sigma_s_per_m!r}")
        if _require_finite(self.length_scale, "length_scale") <= 0.0:
            raise ValueError(f"length_scale 必须 >0，收到 {self.length_scale!r}")

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典。"""
        return {
            "temperature_c": self.temperature_c,
            "eps_r": self.eps_r,
            "tan_delta": self.tan_delta,
            "sigma_s_per_m": self.sigma_s_per_m,
            "length_scale": self.length_scale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaterialState:
        """从 JSON 字典重建；未知字段/缺字段显式报错。"""
        src = _as_mapping(data, "material_state")
        _reject_unknown(src, set(cls.__dataclass_fields__), "material_state")
        return cls(
            temperature_c=_require_finite(
                _require_key(src, "temperature_c", "material_state"), "temperature_c"),
            eps_r=_require_finite(_require_key(src, "eps_r", "material_state"), "eps_r"),
            tan_delta=_require_finite(
                _require_key(src, "tan_delta", "material_state"), "tan_delta"),
            sigma_s_per_m=_require_finite(
                _require_key(src, "sigma_s_per_m", "material_state"), "sigma_s_per_m"),
            length_scale=_require_finite(
                _require_key(src, "length_scale", "material_state"), "length_scale"),
        )


@dataclass(frozen=True)
class ResonatorGeometry:
    """微带半波谐振器几何（参考温度下的物理尺寸，SI 单位）。

    Args:
        length_m: 谐振长度（参考温度下）[m]，>0。
        width_m: 导带宽度 [m]，>0。
        height_m: 基板厚度 [m]，>0。
    """

    length_m: float
    width_m: float
    height_m: float

    def __post_init__(self) -> None:
        for name in ("length_m", "width_m", "height_m"):
            if _require_finite(getattr(self, name), name) <= 0.0:
                raise ValueError(f"{name} 必须 >0，收到 {getattr(self, name)!r}")

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典。"""
        return {"length_m": self.length_m, "width_m": self.width_m,
                "height_m": self.height_m}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ResonatorGeometry:
        """从 JSON 字典重建；未知字段/缺字段显式报错。"""
        src = _as_mapping(data, "geometry")
        _reject_unknown(src, set(cls.__dataclass_fields__), "geometry")
        return cls(
            length_m=_require_finite(_require_key(src, "length_m", "geometry"), "length_m"),
            width_m=_require_finite(_require_key(src, "width_m", "geometry"), "width_m"),
            height_m=_require_finite(_require_key(src, "height_m", "geometry"), "height_m"),
        )


@dataclass(frozen=True)
class MaterialTemperatureModel:
    """确定性温度相关材料模型（相对多项式口径，TCDk/CTE/tan_delta 系数）。

    每个量的温度律统一写成:

        X(T) = X_ref * (1 + c1 * dT + c2 * dT^2),  dT = T - T_ref_c

    其中介电常数/损耗正切的 c1 由 ppm/K 系数给出（c1 = ppm * 1e-6），
    CTE 描述几何长度缩放。纯线性 = c2 全零（默认）。

    Args:
        eps_r_ref: 参考温度相对介电常数（>0）。
        sigma_ref: 参考温度电导率 [S/m]（>=0）。
        tan_delta_ref: 参考温度损耗正切（>=0）。
        tcdk_ppm_per_k: (1/eps_r) d(eps_r)/dT [ppm/K]。
        tcdk2_ppm_per_k2: 二阶介电温度系数 [ppm/K^2]。
        tan_delta_tempco_ppm_per_k: (1/tan_delta) d(tan_delta)/dT [ppm/K]。
        tan_delta_tempco2_ppm_per_k2: 二阶损耗正切温度系数 [ppm/K^2]。
        sigma_tempco_per_k: (1/sigma) d(sigma)/dT [1/K]（金属常为负）。
        cte_ppm_per_k: (1/L) dL/dT [ppm/K]。
        cte2_ppm_per_k2: 二阶线膨胀系数 [ppm/K^2]。
        t_ref_c: 参考温度 [C]。
    """

    eps_r_ref: float
    sigma_ref: float = 0.0
    tan_delta_ref: float = 0.0
    tcdk_ppm_per_k: float = 0.0
    tcdk2_ppm_per_k2: float = 0.0
    tan_delta_tempco_ppm_per_k: float = 0.0
    tan_delta_tempco2_ppm_per_k2: float = 0.0
    sigma_tempco_per_k: float = 0.0
    cte_ppm_per_k: float = 0.0
    cte2_ppm_per_k2: float = 0.0
    t_ref_c: float = 25.0

    def __post_init__(self) -> None:
        if _require_finite(self.eps_r_ref, "eps_r_ref") <= 0.0:
            raise ValueError(f"eps_r_ref 必须 >0，收到 {self.eps_r_ref!r}")
        if _require_finite(self.sigma_ref, "sigma_ref") < 0.0:
            raise ValueError(f"sigma_ref 必须 >=0，收到 {self.sigma_ref!r}")
        if _require_finite(self.tan_delta_ref, "tan_delta_ref") < 0.0:
            raise ValueError(f"tan_delta_ref 必须 >=0，收到 {self.tan_delta_ref!r}")
        _require_finite(self.t_ref_c, "t_ref_c")
        for name in ("tcdk_ppm_per_k", "tcdk2_ppm_per_k2",
                     "tan_delta_tempco_ppm_per_k", "tan_delta_tempco2_ppm_per_k2",
                     "sigma_tempco_per_k", "cte_ppm_per_k", "cte2_ppm_per_k2"):
            _require_finite(getattr(self, name), name)

    def evaluate(self, temperature_c: float) -> MaterialState:
        """把温度映射到材料状态。

        Raises:
            ValueError: 温度非有限；或多项式外推到非物理区（eps_r<=0、
                tan_delta<0、length_scale<=0）——显式报错不夹取。
        """
        temperature = _require_finite(temperature_c, "temperature_c")
        dt = temperature - self.t_ref_c
        eps_r = self.eps_r_ref * (
            1.0 + self.tcdk_ppm_per_k * 1e-6 * dt
            + self.tcdk2_ppm_per_k2 * 1e-6 * dt * dt)
        tan_delta = self.tan_delta_ref * (
            1.0 + self.tan_delta_tempco_ppm_per_k * 1e-6 * dt
            + self.tan_delta_tempco2_ppm_per_k2 * 1e-6 * dt * dt)
        sigma = self.sigma_ref * (1.0 + self.sigma_tempco_per_k * dt)
        length_scale = (1.0 + self.cte_ppm_per_k * 1e-6 * dt
                        + self.cte2_ppm_per_k2 * 1e-6 * dt * dt)
        return MaterialState(
            temperature_c=temperature,
            eps_r=eps_r,
            tan_delta=tan_delta,
            sigma_s_per_m=sigma,
            length_scale=length_scale,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典。"""
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaterialTemperatureModel:
        """从 JSON 字典重建；未知字段/缺字段显式报错。"""
        src = _as_mapping(data, "material")
        _reject_unknown(src, set(cls.__dataclass_fields__), "material")
        return cls(
            eps_r_ref=_require_finite(
                _require_key(src, "eps_r_ref", "material"), "eps_r_ref"),
            sigma_ref=_require_finite(src.get("sigma_ref", 0.0), "sigma_ref"),
            tan_delta_ref=_require_finite(src.get("tan_delta_ref", 0.0), "tan_delta_ref"),
            tcdk_ppm_per_k=_require_finite(src.get("tcdk_ppm_per_k", 0.0), "tcdk_ppm_per_k"),
            tcdk2_ppm_per_k2=_require_finite(
                src.get("tcdk2_ppm_per_k2", 0.0), "tcdk2_ppm_per_k2"),
            tan_delta_tempco_ppm_per_k=_require_finite(
                src.get("tan_delta_tempco_ppm_per_k", 0.0), "tan_delta_tempco_ppm_per_k"),
            tan_delta_tempco2_ppm_per_k2=_require_finite(
                src.get("tan_delta_tempco2_ppm_per_k2", 0.0), "tan_delta_tempco2_ppm_per_k2"),
            sigma_tempco_per_k=_require_finite(
                src.get("sigma_tempco_per_k", 0.0), "sigma_tempco_per_k"),
            cte_ppm_per_k=_require_finite(src.get("cte_ppm_per_k", 0.0), "cte_ppm_per_k"),
            cte2_ppm_per_k2=_require_finite(src.get("cte2_ppm_per_k2", 0.0), "cte2_ppm_per_k2"),
            t_ref_c=_require_finite(src.get("t_ref_c", 25.0), "t_ref_c"),
        )


# ---------------------------------------------------------------------------
# EM / 损耗评估对象
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EMEvaluation:
    """一次 EM 评估的结果：谐振频率与无载 Q。

    Args:
        f0_hz: 谐振频率 [Hz]（>0）。
        q_unloaded: 无载品质因数 Qu（>0，有限）。
    """

    f0_hz: float
    q_unloaded: float

    def __post_init__(self) -> None:
        if _require_finite(self.f0_hz, "f0_hz") <= 0.0:
            raise ValueError(f"f0_hz 必须 >0，收到 {self.f0_hz!r}")
        if _require_finite(self.q_unloaded, "q_unloaded") <= 0.0:
            raise ValueError(f"q_unloaded 必须 >0，收到 {self.q_unloaded!r}")

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典。"""
        return {"f0_hz": self.f0_hz, "q_unloaded": self.q_unloaded}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EMEvaluation:
        """从 JSON 字典重建；未知字段/缺字段显式报错。"""
        src = _as_mapping(data, "em_evaluation")
        _reject_unknown(src, set(cls.__dataclass_fields__), "em_evaluation")
        return cls(
            f0_hz=_require_finite(_require_key(src, "f0_hz", "em_evaluation"), "f0_hz"),
            q_unloaded=_require_finite(
                _require_key(src, "q_unloaded", "em_evaluation"), "q_unloaded"),
        )


# ---------------------------------------------------------------------------
# 迭代配置 / 步骤 / 结果
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThermalIterationConfig:
    """定点迭代配置（闭包参数，与材料模型分离）。

    Args:
        geometry: 谐振器几何。
        ambient_c: 环境/热沉温度 [C]。
        input_power_w: 入射功率 P_in [W]（>=0）。
        thermal_resistance_k_per_w: 热阻 R_th [K/W]（>=0）。
        drive_frequency_hz: 激励频率 [Hz]；None = 谐振点工作（delta=0）。
        coupling_beta: 耦合系数 beta = Qu/Qe（>0）。
        freq_tolerance_hz: 收敛判据 |df0| < tol [Hz]（>0）。
        max_iterations: 迭代上限（1..MAX_ITERATIONS_LIMIT）。
        relaxation: 松弛因子 omega，T <- T + omega(T_target - T)（(0,2]）。
        temperature_bounds_c: (low, high) 温度护栏 [C]；越界判 out_of_bounds。
        divergence_patience: 残差连续增长多少轮判发散（>=1）。
        reference_temperature_c: 温漂参考温度；None = 材料模型 t_ref_c。
    """

    geometry: ResonatorGeometry
    ambient_c: float
    input_power_w: float
    thermal_resistance_k_per_w: float
    drive_frequency_hz: float | None = None
    coupling_beta: float = 1.0
    freq_tolerance_hz: float = DEFAULT_FREQ_TOLERANCE_HZ
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    relaxation: float = 1.0
    temperature_bounds_c: tuple[float, float] | None = None
    divergence_patience: int = DEFAULT_DIVERGENCE_PATIENCE
    reference_temperature_c: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.geometry, ResonatorGeometry):
            raise ValueError("geometry 必须是 ResonatorGeometry")
        _require_finite(self.ambient_c, "ambient_c")
        if _require_finite(self.input_power_w, "input_power_w") < 0.0:
            raise ValueError(f"input_power_w 必须 >=0，收到 {self.input_power_w!r}")
        if _require_finite(
                self.thermal_resistance_k_per_w, "thermal_resistance_k_per_w") < 0.0:
            raise ValueError(
                f"thermal_resistance_k_per_w 必须 >=0，收到 {self.thermal_resistance_k_per_w!r}")
        if self.drive_frequency_hz is not None and _require_finite(
                self.drive_frequency_hz, "drive_frequency_hz") <= 0.0:
            raise ValueError(f"drive_frequency_hz 必须 >0，收到 {self.drive_frequency_hz!r}")
        if _require_finite(self.coupling_beta, "coupling_beta") <= 0.0:
            raise ValueError(f"coupling_beta 必须 >0，收到 {self.coupling_beta!r}")
        if _require_finite(self.freq_tolerance_hz, "freq_tolerance_hz") <= 0.0:
            raise ValueError(f"freq_tolerance_hz 必须 >0，收到 {self.freq_tolerance_hz!r}")
        if not isinstance(self.max_iterations, int) or isinstance(self.max_iterations, bool):
            raise ValueError(f"max_iterations 必须是整数，收到 {self.max_iterations!r}")
        if not 1 <= self.max_iterations <= MAX_ITERATIONS_LIMIT:
            raise ValueError(
                f"max_iterations 必须在 [1, {MAX_ITERATIONS_LIMIT}]，收到 {self.max_iterations!r}")
        if not 0.0 < _require_finite(self.relaxation, "relaxation") <= 2.0:
            raise ValueError(f"relaxation 必须在 (0, 2]，收到 {self.relaxation!r}")
        if self.temperature_bounds_c is not None:
            low = _require_finite(self.temperature_bounds_c[0], "temperature_bounds_c[0]")
            high = _require_finite(self.temperature_bounds_c[1], "temperature_bounds_c[1]")
            if low >= high:
                raise ValueError(
                    f"temperature_bounds_c 必须 low<high，收到 {self.temperature_bounds_c!r}")
        if self.reference_temperature_c is not None:
            _require_finite(self.reference_temperature_c, "reference_temperature_c")
        if not isinstance(self.divergence_patience, int) or isinstance(self.divergence_patience, bool):
            raise ValueError("divergence_patience 必须是整数")
        if self.divergence_patience < 1:
            raise ValueError(f"divergence_patience 必须 >=1，收到 {self.divergence_patience!r}")

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典（geometry 嵌套，bounds 转 list）。"""
        return {
            "geometry": self.geometry.to_dict(),
            "ambient_c": self.ambient_c,
            "input_power_w": self.input_power_w,
            "thermal_resistance_k_per_w": self.thermal_resistance_k_per_w,
            "drive_frequency_hz": self.drive_frequency_hz,
            "coupling_beta": self.coupling_beta,
            "freq_tolerance_hz": self.freq_tolerance_hz,
            "max_iterations": self.max_iterations,
            "relaxation": self.relaxation,
            "temperature_bounds_c": (
                None if self.temperature_bounds_c is None else list(self.temperature_bounds_c)),
            "divergence_patience": self.divergence_patience,
            "reference_temperature_c": self.reference_temperature_c,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ThermalIterationConfig:
        """从 JSON 字典重建；未知字段/缺字段显式报错。"""
        src = _as_mapping(data, "config")
        _reject_unknown(src, set(cls.__dataclass_fields__), "config")
        bounds = src.get("temperature_bounds_c")
        if bounds is not None:
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                raise ValueError("temperature_bounds_c 必须是长度 2 的序列或 null")
            bounds = (_require_finite(bounds[0], "temperature_bounds_c[0]"),
                      _require_finite(bounds[1], "temperature_bounds_c[1]"))
        geometry = ResonatorGeometry.from_dict(_require_key(src, "geometry", "config"))
        reference = src.get("reference_temperature_c")
        drive = src.get("drive_frequency_hz")
        return cls(
            geometry=geometry,
            ambient_c=_require_finite(_require_key(src, "ambient_c", "config"), "ambient_c"),
            input_power_w=_require_finite(
                _require_key(src, "input_power_w", "config"), "input_power_w"),
            thermal_resistance_k_per_w=_require_finite(
                _require_key(src, "thermal_resistance_k_per_w", "config"),
                "thermal_resistance_k_per_w"),
            drive_frequency_hz=(None if drive is None
                                else _require_finite(drive, "drive_frequency_hz")),
            coupling_beta=_require_finite(src.get("coupling_beta", 1.0), "coupling_beta"),
            freq_tolerance_hz=_require_finite(
                src.get("freq_tolerance_hz", DEFAULT_FREQ_TOLERANCE_HZ), "freq_tolerance_hz"),
            max_iterations=int(src.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
            relaxation=_require_finite(src.get("relaxation", 1.0), "relaxation"),
            temperature_bounds_c=bounds,
            divergence_patience=int(src.get("divergence_patience", DEFAULT_DIVERGENCE_PATIENCE)),
            reference_temperature_c=(
                None if reference is None else _require_finite(reference, "reference_temperature_c")),
        )


@dataclass(frozen=True)
class ThermalIterationStep:
    """单轮迭代记录（在 T_n 处评估）。"""

    iteration: int
    temperature_c: float
    f0_hz: float
    q_unloaded: float
    dissipated_power_w: float
    next_temperature_c: float
    residual_hz: float | None

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典。"""
        return {
            "iteration": self.iteration,
            "temperature_c": self.temperature_c,
            "f0_hz": self.f0_hz,
            "q_unloaded": self.q_unloaded,
            "dissipated_power_w": self.dissipated_power_w,
            "next_temperature_c": self.next_temperature_c,
            "residual_hz": self.residual_hz,
        }


@dataclass(frozen=True)
class ThermalIterationResult:
    """定点迭代结果（全部 JSON 友好）。"""

    converged: bool
    status: str
    iterations: int
    reference_temperature_c: float
    f0_reference_hz: float
    final_temperature_c: float
    final_f0_hz: float
    final_q_unloaded: float
    dissipated_power_w: float
    residual_hz: float | None
    f0_drift_ppm: float
    steps: tuple[ThermalIterationStep, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典。"""
        return {
            "converged": self.converged,
            "status": self.status,
            "iterations": self.iterations,
            "reference_temperature_c": self.reference_temperature_c,
            "f0_reference_hz": self.f0_reference_hz,
            "final_temperature_c": self.final_temperature_c,
            "final_f0_hz": self.final_f0_hz,
            "final_q_unloaded": self.final_q_unloaded,
            "dissipated_power_w": self.dissipated_power_w,
            "residual_hz": self.residual_hz,
            "f0_drift_ppm": self.f0_drift_ppm,
            "steps": [step.to_dict() for step in self.steps],
        }


# ---------------------------------------------------------------------------
# 微带准静态闭式（Hammerstad-Jensen，Pozar §3.8）
# ---------------------------------------------------------------------------

def microstrip_effective_permittivity(eps_r: float, width_over_height: float) -> float:
    """微带有效介电常数（Hammerstad-Jensen 准静态，Pozar 4th ed. eq. 3.195）。

    u = W/h <= 1 时含 0.04(1-u)^2 修正项，u >= 1 时取主干 1/sqrt(1+12/u)。

    Raises:
        ValueError: eps_r <= 0 或 u <= 0。
    """
    er = _require_finite(eps_r, "eps_r")
    u = _require_finite(width_over_height, "width_over_height")
    if er <= 0.0:
        raise ValueError(f"eps_r 必须 >0，收到 {eps_r!r}")
    if u <= 0.0:
        raise ValueError(f"width_over_height 必须 >0，收到 {width_over_height!r}")
    if u <= 1.0:
        correction = 1.0 / math.sqrt(1.0 + 12.0 / u) + 0.04 * (1.0 - u) ** 2
    else:
        correction = 1.0 / math.sqrt(1.0 + 12.0 / u)
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * correction


def microstrip_characteristic_impedance(eps_eff: float, width_over_height: float) -> float:
    """微带准静态特性阻抗（Pozar 4th ed. eqs. 3.196-3.197）。

    Raises:
        ValueError: eps_eff <= 0 或 u <= 0。
    """
    ee = _require_finite(eps_eff, "eps_eff")
    u = _require_finite(width_over_height, "width_over_height")
    if ee <= 0.0:
        raise ValueError(f"eps_eff 必须 >0，收到 {eps_eff!r}")
    if u <= 0.0:
        raise ValueError(f"width_over_height 必须 >0，收到 {width_over_height!r}")
    if u <= 1.0:
        return 60.0 / math.sqrt(ee) * math.log(8.0 / u + u / 4.0)
    return 120.0 * math.pi / (math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


def surface_resistance(freq_hz: float, sigma_s_per_m: float) -> float:
    """导体表面电阻 Rs = sqrt(pi f mu0 / sigma) [ohm]（Pozar §1.7.1）。

    Raises:
        ValueError: f <= 0 或 sigma <= 0。
    """
    f = _require_finite(freq_hz, "freq_hz")
    sigma = _require_finite(sigma_s_per_m, "sigma_s_per_m")
    if f <= 0.0:
        raise ValueError(f"freq_hz 必须 >0，收到 {freq_hz!r}")
    if sigma <= 0.0:
        raise ValueError(f"sigma_s_per_m 必须 >0，收到 {sigma_s_per_m!r}")
    return math.sqrt(math.pi * f * MU0_H_PER_M / sigma)


def microstrip_resonator_em(
    state: MaterialState,
    geometry: ResonatorGeometry,
    *,
    z0_ohm: float | None = None,
) -> EMEvaluation:
    """默认 EM 评估：微带半波谐振器解析链（f0, Qu）。

    f0 = c / (2 L sqrt(eps_eff))；损耗 = 导体 alpha_c = Rs/(Z0 w) 与介质
    alpha_d 之和；Qu = pi/(2 alpha L)（Pozar §6.4）。

    Args:
        state: 材料状态（含 CTE 长度缩放）。
        geometry: 参考温度几何。
        z0_ohm: 显式特性阻抗；None 用准静态闭式。

    Raises:
        ValueError: 谐振器无损（tan_delta=0 且 sigma=0）导致 Qu 无定义。
    """
    u = geometry.width_m / geometry.height_m
    eps_eff = microstrip_effective_permittivity(state.eps_r, u)
    length = geometry.length_m * state.length_scale
    f0_hz = C0_M_PER_S / (2.0 * length * math.sqrt(eps_eff))

    alpha_d = 0.0
    if state.tan_delta > 0.0 and abs(state.eps_r - 1.0) > 1e-12:
        lambda0 = C0_M_PER_S / f0_hz
        alpha_d = (math.pi / lambda0) * (state.eps_r / math.sqrt(eps_eff)) * (
            (eps_eff - 1.0) / (state.eps_r - 1.0)) * state.tan_delta

    alpha_c = 0.0
    if state.sigma_s_per_m > 0.0:
        z0 = (z0_ohm if z0_ohm is not None
              else microstrip_characteristic_impedance(eps_eff, u))
        alpha_c = surface_resistance(f0_hz, state.sigma_s_per_m) / (z0 * geometry.width_m)

    alpha = alpha_c + alpha_d
    if alpha <= 0.0:
        raise ValueError("谐振器无损（tan_delta=0 且 sigma=0）：Qu 无定义；请给至少一项损耗")
    return EMEvaluation(f0_hz=f0_hz, q_unloaded=math.pi / (2.0 * alpha * length))


def make_microstrip_em(
    geometry: ResonatorGeometry,
    *,
    z0_ohm: float | None = None,
) -> EMEvaluator:
    """构造绑定几何的默认 EM 评估回调（可直接注入 solve）。"""
    def evaluator(state: MaterialState, temperature_c: float) -> EMEvaluation:
        return microstrip_resonator_em(state, geometry, z0_ohm=z0_ohm)

    return evaluator


def one_port_dissipated_power(
    em: EMEvaluation,
    temperature_c: float,
    *,
    config: ThermalIterationConfig,
) -> float:
    """默认损耗评估：单端口谐振器失谐吸收功率 [W]（Pozar §6.4）。

    P_diss = P_in * 4 beta / ((1+beta)^2 + (2 Qu delta)^2)，
    delta = 0.5 (f_drive/f0 - f0/f_drive)；f_drive=None 时 delta=0。
    """
    beta = config.coupling_beta
    delta = 0.0
    if config.drive_frequency_hz is not None:
        ratio = config.drive_frequency_hz / em.f0_hz
        delta = 0.5 * (ratio - 1.0 / ratio)
    term = 2.0 * em.q_unloaded * delta
    return config.input_power_w * 4.0 * beta / ((1.0 + beta) ** 2 + term * term)


# ---------------------------------------------------------------------------
# 一阶温漂闭式（验收对照）与定点迭代
# ---------------------------------------------------------------------------

def closed_form_drift_ratio(
    cte_ppm_per_k: float,
    tcdk_ppm_per_k: float,
    delta_t_c: float,
) -> float:
    """一阶温漂闭式 df0/f0 = -CTE dT - (1/2) TCDk dT（Pozar；见模块头）。

    与 core/calculators.py resonator_thermal_drift 的 df_over_f 同口径
    （单测逐值互证）。
    """
    cte = _require_finite(cte_ppm_per_k, "cte_ppm_per_k")
    tcdk = _require_finite(tcdk_ppm_per_k, "tcdk_ppm_per_k")
    dt = _require_finite(delta_t_c, "delta_t_c")
    return -(cte + 0.5 * tcdk) * 1e-6 * dt


def evaluate_resonator_f0(
    model: MaterialTemperatureModel,
    geometry: ResonatorGeometry,
    temperature_c: float,
    *,
    em_evaluator: EMEvaluator | None = None,
) -> float:
    """在给定温度评估 f0 [Hz]（独立于迭代状态，供温漂对照用）。"""
    em_fn = em_evaluator if em_evaluator is not None else make_microstrip_em(geometry)
    return em_fn(model.evaluate(temperature_c), temperature_c).f0_hz


def _guard_loss(value: float) -> float:
    """校验损耗回调返回值：有限且 >=0，否则显式报错。"""
    power = _require_finite(value, "dissipated_power_w")
    if power < 0.0:
        raise ValueError(f"loss_evaluator 返回负耗散功率 {value!r}")
    return power


def solve_thermal_fixed_point(
    model: MaterialTemperatureModel,
    config: ThermalIterationConfig,
    *,
    em_evaluator: EMEvaluator | None = None,
    loss_evaluator: LossEvaluator | None = None,
) -> ThermalIterationResult:
    """双向定点迭代：T -> 材料(T) -> EM(f0,Qu) -> Q/损耗 -> P_diss -> 新 T。

    收敛判据 = 相邻两轮 f0 之差 |df0| < freq_tolerance_hz；发散由
    「残差连续增长 divergence_patience 轮」或温度护栏越界判定；
    达到 max_iterations 未收敛返回 status="max_iterations"（不抛错）。

    Args:
        model: 温度相关材料模型。
        config: 迭代配置。
        em_evaluator: 可注入 EM 回调 (state, T) -> EMEvaluation；
            None 用绑定 config.geometry 的微带解析链。
        loss_evaluator: 可注入损耗回调 (em, T) -> P_diss [W]；
            None 用单端口失谐吸收闭式。

    Returns:
        ThermalIterationResult。

    Raises:
        ValueError: 损耗回调用返回非有限/负功率，或材料多项式外推出
            非物理区（透传 MaterialState/MaterialTemperatureModel 校验）。
    """
    em_fn = em_evaluator if em_evaluator is not None else make_microstrip_em(config.geometry)
    if loss_evaluator is not None:
        loss_fn = loss_evaluator
    else:
        def loss_fn(em: EMEvaluation, temperature_c: float) -> float:
            return one_port_dissipated_power(em, temperature_c, config=config)

    reference_temperature_c = (
        model.t_ref_c if config.reference_temperature_c is None
        else config.reference_temperature_c)
    f0_reference_hz = em_fn(
        model.evaluate(reference_temperature_c), reference_temperature_c).f0_hz

    temperature_c = config.ambient_c
    steps: list[ThermalIterationStep] = []
    previous_residual: float | None = None
    growing_rounds = 0
    status = STATUS_MAX_ITERATIONS

    for iteration in range(1, config.max_iterations + 1):
        state = model.evaluate(temperature_c)
        em = em_fn(state, temperature_c)
        power_w = _guard_loss(loss_fn(em, temperature_c))
        target_c = config.ambient_c + config.thermal_resistance_k_per_w * power_w
        next_temperature_c = temperature_c + config.relaxation * (target_c - temperature_c)
        residual_hz = None if not steps else abs(em.f0_hz - steps[-1].f0_hz)
        steps.append(ThermalIterationStep(
            iteration=iteration,
            temperature_c=temperature_c,
            f0_hz=em.f0_hz,
            q_unloaded=em.q_unloaded,
            dissipated_power_w=power_w,
            next_temperature_c=next_temperature_c,
            residual_hz=residual_hz,
        ))

        if residual_hz is not None and residual_hz < config.freq_tolerance_hz:
            status = STATUS_CONVERGED
            break

        if residual_hz is not None:
            if previous_residual is not None and residual_hz > previous_residual:
                growing_rounds += 1
            else:
                growing_rounds = 0
            previous_residual = residual_hz
            if growing_rounds >= config.divergence_patience:
                status = STATUS_DIVERGED
                break

        if not math.isfinite(next_temperature_c):
            status = STATUS_DIVERGED
            break
        if config.temperature_bounds_c is not None:
            low, high = config.temperature_bounds_c
            if next_temperature_c < low or next_temperature_c > high:
                status = STATUS_OUT_OF_BOUNDS
                break

        temperature_c = next_temperature_c

    last = steps[-1]
    drift_ppm = (last.f0_hz - f0_reference_hz) / f0_reference_hz * 1e6
    return ThermalIterationResult(
        converged=status == STATUS_CONVERGED,
        status=status,
        iterations=len(steps),
        reference_temperature_c=reference_temperature_c,
        f0_reference_hz=f0_reference_hz,
        final_temperature_c=last.temperature_c,
        final_f0_hz=last.f0_hz,
        final_q_unloaded=last.q_unloaded,
        dissipated_power_w=last.dissipated_power_w,
        residual_hz=last.residual_hz,
        f0_drift_ppm=drift_ppm,
        steps=tuple(steps),
    )


def run_thermal_iteration(payload: Mapping[str, Any]) -> dict[str, Any]:
    """JSON 进出薄壳：{"material": {...}, "config": {...}} -> {"ok": ...}。

    非法输入不抛异常，返回 {"ok": False, "error": "..."}（确定性、可序列化）。
    """
    try:
        src = _as_mapping(payload, "payload")
        model = MaterialTemperatureModel.from_dict(_require_key(src, "material", "payload"))
        config = ThermalIterationConfig.from_dict(_require_key(src, "config", "payload"))
        result = solve_thermal_fixed_point(model, config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result.to_dict()}
