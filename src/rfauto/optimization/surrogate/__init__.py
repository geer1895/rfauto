"""代理模型子包：接口契约见 base（v0 起，第三方正向代理由此接入）。

历史模块 optimization/surrogate.py（P6 响应面预筛）已并入本包
prescreener.py（v0 模块化合并）。
"""

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    SurrogateRegistry,
    surrogate_registry,
)
from rfauto.optimization.surrogate.deeponet import DeepONetSurrogate
from rfauto.optimization.surrogate.fno import FNOSurrogate
from rfauto.optimization.surrogate.fno_lite import FNOLiteSurrogate
from rfauto.optimization.surrogate.mapes_analytic import MapesAnalyticSurrogate
from rfauto.optimization.surrogate.nn_model import (
    PHYSICS_AUGMENTERS,
    NNSurrogate,
)
from rfauto.optimization.surrogate.pod_rom import (
    PODROMSurrogate,
    pod_basis,
)
from rfauto.optimization.surrogate.poly_ridge import (
    PolyRidgeSurrogate,
    loocv_rho,
)
from rfauto.optimization.surrogate.prescreener import (
    ResponseSurfaceModel,
    SurrogatePrescreener,
)
from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate
from rfauto.optimization.surrogate.smt_mfk import SMTMultiFidelitySurrogate

__all__ = [
    "PHYSICS_AUGMENTERS",
    "DeepONetSurrogate",
    "FNOLiteSurrogate",
    "FNOSurrogate",
    "MapesAnalyticSurrogate",
    "NNSurrogate",
    "PODROMSurrogate",
    "PolyRidgeSurrogate",
    "ResponseSurfaceModel",
    "SMTKrigingSurrogate",
    "SMTMultiFidelitySurrogate",
    "SurrogateModel",
    "SurrogatePrescreener",
    "SurrogateRegistry",
    "loocv_rho",
    "pod_basis",
    "surrogate_registry",
]
