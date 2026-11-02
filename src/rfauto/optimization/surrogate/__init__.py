"""代理模型子包：接口契约见 base（v0 起，第三方正向代理由此接入）。

历史模块 optimization/surrogate.py（P6 响应面预筛）已并入本包
prescreener.py（v0 模块化合并，2026-09-03）。
"""

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    SurrogateRegistry,
    surrogate_registry,
)
from rfauto.optimization.surrogate.conformal import ConformalSurrogate
from rfauto.optimization.surrogate.deep_ensemble import DeepEnsembleSurrogate
from rfauto.optimization.surrogate.deeponet import DeepONetSurrogate
from rfauto.optimization.surrogate.ensemble import EnsembleSurrogate
from rfauto.optimization.surrogate.fno import FNOSurrogate
from rfauto.optimization.surrogate.fno_lite import FNOLiteSurrogate
from rfauto.optimization.surrogate.green_operator import (
    GreenOperatorSurrogate,
    superpose,
    superposition_residual,
)
from rfauto.optimization.surrogate.huber_ridge import HuberRidgeSurrogate
from rfauto.optimization.surrogate.lnn_cfc import (
    DEFAULT_LNN_SEED,
    CfcNet,
    LnnCfcSurrogate,
    cfc_time_gate,
    rc_cascade_step_response,
    second_order_step_response,
)
from rfauto.optimization.surrogate.mapes_analytic import MapesAnalyticSurrogate
from rfauto.optimization.surrogate.multi_task_gp import (
    DEFAULT_MT_SEED,
    MultiTaskGPSurrogate,
    validate_coregionalization_matrix,
)
from rfauto.optimization.surrogate.ngo_stamp_rf import NgoStampRfSurrogate
from rfauto.optimization.surrogate.nn_model import (
    PHYSICS_AUGMENTERS,
    NNSurrogate,
)
from rfauto.optimization.surrogate.param_vf import (
    ParamVFSurrogate,
    convex_hull_verdict,
    local_linear_weights,
)
from rfauto.optimization.surrogate.pod_rom import (
    PODROMSurrogate,
    pod_basis,
)
from rfauto.optimization.surrogate.pole_residue import (
    PoleResidueSurrogate,
    band_edge_verdict,
    param_conflict_verdict,
    passivity_verdict,
)
from rfauto.optimization.surrogate.poly_ridge import (
    PolyRidgeSurrogate,
    loocv_rho,
)
from rfauto.optimization.surrogate.prescreener import (
    ResponseSurfaceModel,
    SurrogatePrescreener,
)
from rfauto.optimization.surrogate.rff_gp import (
    DEFAULT_RFF_SEED,
    RffGPSurrogate,
    fourier_features,
    sample_rff,
)
from rfauto.optimization.surrogate.saas_gp import SaasArdSurrogate
from rfauto.optimization.surrogate.siren import SirenFieldSurrogate
from rfauto.optimization.surrogate.sk_gbdt import GBDTSurrogate
from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate
from rfauto.optimization.surrogate.smt_mfk import SMTMultiFidelitySurrogate
from rfauto.optimization.surrogate.svgp import (
    DEFAULT_SVGP_SEED,
    SvgpSurrogate,
    farthest_point_sample,
    svgp_elbo_terms,
    svgp_inducing,
)
from rfauto.optimization.surrogate.virtual_samples import (
    VIRTUAL_WEIGHT_KEY,
    generate_virtual_samples,
)
from rfauto.optimization.surrogate.warped_kriging import (
    WarpedKrigingSurrogate,
    kumaraswamy_warp,
)

__all__ = [
    "DEFAULT_LNN_SEED",
    "DEFAULT_MT_SEED",
    "DEFAULT_RFF_SEED",
    "DEFAULT_SVGP_SEED",
    "PHYSICS_AUGMENTERS",
    "VIRTUAL_WEIGHT_KEY",
    "CfcNet",
    "ConformalSurrogate",
    "DeepEnsembleSurrogate",
    "DeepONetSurrogate",
    "EnsembleSurrogate",
    "FNOLiteSurrogate",
    "FNOSurrogate",
    "GBDTSurrogate",
    "GreenOperatorSurrogate",
    "HuberRidgeSurrogate",
    "LnnCfcSurrogate",
    "MapesAnalyticSurrogate",
    "MultiTaskGPSurrogate",
    "NNSurrogate",
    "NgoStampRfSurrogate",
    "PODROMSurrogate",
    "ParamVFSurrogate",
    "PoleResidueSurrogate",
    "PolyRidgeSurrogate",
    "ResponseSurfaceModel",
    "RffGPSurrogate",
    "SMTKrigingSurrogate",
    "SMTMultiFidelitySurrogate",
    "SaasArdSurrogate",
    "SirenFieldSurrogate",
    "SurrogateModel",
    "SurrogatePrescreener",
    "SurrogateRegistry",
    "SvgpSurrogate",
    "WarpedKrigingSurrogate",
    "band_edge_verdict",
    "cfc_time_gate",
    "convex_hull_verdict",
    "farthest_point_sample",
    "fourier_features",
    "generate_virtual_samples",
    "kumaraswamy_warp",
    "local_linear_weights",
    "loocv_rho",
    "param_conflict_verdict",
    "passivity_verdict",
    "pod_basis",
    "rc_cascade_step_response",
    "sample_rff",
    "second_order_step_response",
    "superpose",
    "superposition_residual",
    "surrogate_registry",
    "svgp_elbo_terms",
    "svgp_inducing",
    "validate_coregionalization_matrix",
]
