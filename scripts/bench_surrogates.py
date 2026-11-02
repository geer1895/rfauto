"""代理键性能基准套件（aurora_n 开放池席；基线记录工具，**不是门**）。

对 ``surrogate_registry`` 全部可创建注册键，在**合成数据**（解析真值）
上测 fit/predict 时长与精度（vs 解析真值 RMSE），落 json+md 基线表供
未来性能回归对照。定位=基线记录（scripts 直跑形态，不动 CLI 数字链）。

确定性红线（任务书 1）：全链固定 seed——训练采样/真值系数走
``np.random.default_rng(固定种子)``，模型侧 seed 显式写进各 case config
（torch manual_seed / sklearn random_state / numpy rng 由各内核消费）；
同 seed 重跑**精度列逐位相等**（计时列允许抖动）。BLAS/OMP/torch 线程
钉 1（#258 家法：小矩阵多线程反而慢且引入归约序漂移，破坏逐位复现），
环境变量在本模块顶部、numpy/torch 导入之前设置。

覆盖面（任务书 2）：
- 可创建键全测（numpy 系秒级）；torch 系（fno/fno_lite/deeponet/
  deep_ensemble/siren）小档（小 width/epochs，量级参照非绝对值）；
- GP 系 n=200 档 + rff_gp n=2000 规模档（XD-4 >10k 前的规模面）；
- 跳过面（缺依赖/数据面不适用）如实标注不静默（#122）——
  mapes_pixel_analytic 为解析物理模型（fit 不训练、需实测 npz 装配），
  合成精度基准不适用，按 designed_skip 登记。

用法（scripts 直跑形态）::

    .venv/Scripts/python.exe scripts/bench_surrogates.py \
        --out runs/aurora_n/bench/ --tag baseline_20261031 --repeat-check
    # 确定性复核（两个 JSON 的精度列逐位比对）：
    .venv/Scripts/python.exe scripts/bench_surrogates.py \
        --compare runs/aurora_n/bench/A.json runs/aurora_n/bench/B.json

只读跑红线（任务书红线 1）：本脚本除 ``--out`` 目录（基线产物）外
零写面——无 runs/ 湖污染、无 cwd 相对落盘（#144 家族不适用：所测
代理 fit/predict 均为纯内存契约面）。
"""

from __future__ import annotations

import os

# BLAS/OMP 线程钉 1——必须在 numpy/torch（经 rfauto）导入之前生效
# （#258 家法；同 seed 精度列逐位的前提=归约序稳定）
_THREADS_PINNED: dict[str, str] = {}
for _k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
    _THREADS_PINNED[_k] = "1"

import argparse  # noqa: E402
import contextlib  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import platform  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

from rfauto.optimization.surrogate import surrogate_registry  # noqa: E402

# gnn_geom 为惰性注册面（surrogate/__init__ 不导入、无其他 src 消费者）——
# 显式导入进注册表，覆盖报告才对全代码面诚实（缺依赖时如实 skip）
try:
    import rfauto.optimization.surrogate.gnn_geom  # noqa: F401
except ImportError as _exc:  # pragma: no cover——缺依赖面如实登记
    print(f"WARN: gnn_geom 注册面导入失败: {_exc}", file=sys.stderr)

# （rfauto 导入完成后再钉 torch 线程——BLAS 环境变量已先行，此为兜底）
try:
    import torch
    torch.set_num_threads(1)
    TORCH_VERSION: str | None = torch.__version__
except Exception:  # torch 为可选依赖；缺席时 torch 系 case 如实 skip
    torch = None  # type: ignore[assignment]
    TORCH_VERSION = None

SCHEMA = "bench_surrogates/v1"

# ── seed 政策（单一源；模型侧 seed 见各 case config，显式可复现） ────────────
SEED_SCALAR = 20261031      # 标量族训练采样
SEED_CURVE = 20261032       # 曲线族真值系数 + 训练采样
SEED_SIREN = 20261033       # siren 场采样
SEED_GNN = 20261034         # gnn_geom 采样
SEED_MFK = 20261035         # smt_mfk 低保真采样

# ── 标量族合成真值（unit 立方 u∈[0,1]^3；单峰平滑面+固定小噪声） ─────────────
# 面形设计注记：首版全周期面 2.5·sin(2πu1)cos(πu2)（无噪声）把 gp_det 系
# MLE（warped_kriging/saas_gp/rff_gp 的 ℓ 优化）推入退化最优/Cholesky 崩溃区
# （mt_gp 同核但 nugget 固定+LinAlg 兜底不受影响）——本面改单峰半周期+振幅
# 收敛，并加 σ=0.02 观测噪声（≈真值 std 的 2.4%）：真实代理数据必有噪声，
# MLE 景观回归常规，各键默认 config 即可稳定拟合；基准记录的是"常规工况"
# 性能面，非 MLE 病理面（病理面属内核 followUp，不在本席）。
SCALAR_BD: dict[str, tuple[float, float]] = {
    "x1": (0.0, 1.0), "x2": (2.0, 6.0), "x3": (-1.0, 1.0)}
SCALAR_NOISE_SD = 0.02


def _scalar_truth(u1: float, u2: float, u3: float) -> float:
    """解析真值 f(u)：单峰平滑面（半周期 sin·cos+平方+交叉+线性项）。"""
    return (1.0 + 1.6 * math.sin(math.pi * u1) * math.cos(math.pi * u2)
            + 0.5 * u3 * u3 + 0.6 * u1 * u2 - 0.3 * u3)


def _metric2_truth(u1: float, u2: float, m1: float) -> float:
    """第二指标：与 m1 共享潜变量 + 独立分量（mt_gp 跨指标面）。"""
    return 0.6 * m1 + 0.5 * math.sin(1.5 * math.pi * u2) + 0.2 * u1


def _unit_params(u: dict[str, float]) -> dict[str, float]:
    """unit 坐标 → bounds 内参数值（线性映射）。"""
    return {k: lo + u[k] * (hi - lo) for k, (lo, hi) in SCALAR_BD.items()}


def _make_scalar_samples(
    n: int, seed: int, with_m2: bool = False,
) -> list[dict[str, Any]]:
    """标量族训练样本（固定 seed 确定性；同 seed 逐位复现）。

    观测噪声 σ=SCALAR_NOISE_SD（独立种子流 seed+500）——真值列另存
    解析值，RMSE 按解析真值计（噪声只进训练目标，模拟真实采样）。
    """
    rng = np.random.default_rng(seed)
    noise = np.random.default_rng(seed + 500)
    out: list[dict[str, Any]] = []
    for _ in range(n):
        r = rng.random(3)
        u = {"x1": float(r[0]), "x2": float(r[1]), "x3": float(r[2])}
        m1 = _scalar_truth(u["x1"], u["x2"], u["x3"])
        eps = float(noise.normal(0.0, SCALAR_NOISE_SD))
        metrics: dict[str, float] = {"cost": m1 + eps}
        if with_m2:
            metrics["m2"] = _metric2_truth(u["x1"], u["x2"], m1) + float(
                noise.normal(0.0, SCALAR_NOISE_SD))
        out.append({"params": _unit_params(u), "metrics": metrics})
    return out


def _lattice_u(n_side: int, keys: list[str]) -> list[dict[str, float]]:
    """n_side^d 确定性测试栅格（unit 空间，含端点）。"""
    axes = [i / (n_side - 1) for i in range(n_side)]
    return [dict(zip(keys, combo, strict=True))
            for combo in itertools.product(axes, repeat=len(keys))]


def _scalar_test_points() -> list[tuple[dict[str, float], dict[str, Any]]]:
    """6×6×6=216 点确定性测试栅格（params + 解析真值，含 m2 面给 mt_gp）。"""
    out = []
    for u in _lattice_u(6, ["x1", "x2", "x3"]):
        truth = _scalar_truth(u["x1"], u["x2"], u["x3"])
        out.append((_unit_params(u), {
            "u": u, "truth": truth,
            "truth_m2": _metric2_truth(u["x1"], u["x2"], truth)}))
    return out


# ── 曲线族合成真值（固定极点基 + theta(u) 仿射——pole_residue 同构口径） ─────
CURVE_BD: dict[str, tuple[float, float]] = {"x1": (0.0, 1.0), "x2": (0.0, 1.0)}
FREQ_GHZ = (1.0, 3.0)
N_FREQ = 81
DB_FLOOR = 1e-30  # 同 pole_residue._DB_FLOOR（真值换算同口径）


def _to_db(curve: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(curve), DB_FLOOR))


def _curve_theta(u: np.ndarray) -> np.ndarray:
    """theta(u)=scale·(theta0 + A·u)（分量仿射——vf_parametric 局部线性
    可精确回收；分量换算不改仿射结构，只把各分量拉回自然量级）。"""
    return _CURVE_SCALE * (_CURVE_THETA0 + _CURVE_A
                           @ np.asarray(u, dtype=float))


def _curve_truth(freq_hz: np.ndarray, u: np.ndarray) -> np.ndarray:
    """解析真值复曲线（固定极点基，theta 随参数仿射变化）。"""
    from rfauto.optimization.surrogate.pole_residue import (
        evaluate_pole_residue,
        theta_to_model,
    )
    model = theta_to_model(_curve_theta(u), _CURVE_POLES)
    return evaluate_pole_residue(freq_hz, _CURVE_POLES, model["residues"],
                                 model["d"], model["e"])


def _make_curve_assets() -> None:
    """曲线族真值系数（固定 seed）+ 极点基（模块级惰性初始化）。

    theta 分量量级差数个数量级（Hz 栅格下 s~2π·1e9：留数 ~ω 量级才有
    O(1) 响应、e·s 直通项要求 e~1e-11）——单位球随机系数分量乘
    _CURVE_SCALE 拉回自然量级，|S11| 落 O(1)（dB 可读）区间。
    """
    global _CURVE_POLES, _CURVE_THETA0, _CURVE_A, _CURVE_FREQ_HZ
    global _CURVE_SCALE
    from rfauto.optimization.surrogate.pole_residue import default_pole_basis
    _CURVE_FREQ_HZ = np.linspace(FREQ_GHZ[0], FREQ_GHZ[1], N_FREQ) * 1e9
    _CURVE_POLES = default_pole_basis(
        FREQ_GHZ[0] * 1e9, FREQ_GHZ[1] * 1e9, 2, 3, 0.7)
    rng = np.random.default_rng(SEED_CURVE)
    n_theta = 2 * len(_CURVE_POLES) + 4
    n_res = 2 * len(_CURVE_POLES)
    omega_hi = 2.0 * math.pi * FREQ_GHZ[1] * 1e9
    scale = np.concatenate([
        np.full(n_res, omega_hi),          # 留数 Re/Im：r/(s-p) ~ O(1)
        np.full(2, 0.2),                   # d：O(0.1) 常数项
        np.full(2, 1e-11),                 # e：e·s 在带内 ~O(0.1)
    ])
    _CURVE_SCALE = scale
    _CURVE_THETA0 = rng.uniform(-0.4, 0.4, n_theta)
    _CURVE_A = rng.uniform(-0.8, 0.8, (n_theta, 2))


_CURVE_POLES: np.ndarray | None = None
_CURVE_THETA0: np.ndarray | None = None
_CURVE_A: np.ndarray | None = None
_CURVE_FREQ_HZ: np.ndarray | None = None
_CURVE_SCALE: np.ndarray | None = None


def _make_curve_samples(n: int) -> list[dict[str, Any]]:
    """曲线族训练样本（复 S11 + dB 双键并存——极点族与 fno 族同源数据）。"""
    assert _CURVE_FREQ_HZ is not None
    rng = np.random.default_rng(SEED_CURVE + 1)
    out = []
    for _ in range(n):
        u = rng.random(2)
        curve = _curve_truth(_CURVE_FREQ_HZ, u)
        out.append({
            "params": {"x1": float(u[0]), "x2": float(u[1])},
            "metrics": {"s11_curve": curve, "s11_curve_db": _to_db(curve)},
        })
    return out


def _curve_test_points() -> list[tuple[dict[str, float], dict[str, Any]]]:
    """5×5=25 点确定性测试栅格（truth 曲线按评估网格现算）。"""
    out = []
    for u in _lattice_u(5, ["x1", "x2"]):
        out.append(({"x1": u["x1"], "x2": u["x2"]},
                    {"u": np.array([u["x1"], u["x2"]])}))
    return out


# ── siren 场真值（坐标→场；k=1.5/单位长谱内容，w0=15 档） ────────────────────
def _field_truth(x: float, y: float) -> float:
    return math.sin(2.0 * math.pi * 1.5 * x) * math.cos(2.0 * math.pi * y) \
        + 0.3 * x


def _make_siren_samples() -> list[dict[str, Any]]:
    """32×32=1024 网格场采样（确定性坐标栅格，零随机）。"""
    out = []
    for i in range(32):
        for j in range(32):
            x, y = i / 31.0, j / 31.0
            out.append({"params": {"x": x, "y": y},
                        "metrics": {"field": _field_truth(x, y)}})
    return out


def _siren_test_points() -> list[tuple[dict[str, float], dict[str, Any]]]:
    out = []
    for u in _lattice_u(20, ["x", "y"]):
        x, y = u["x"], u["y"]
        out.append(({"x": x, "y": y}, {"truth": _field_truth(x, y)}))
    return out


# ── gnn_geom 真值（4×4 像素占据 → 平滑标量） ─────────────────────────────────
def _gnn_truth(p: dict[str, float]) -> float:
    vals = [p[f"p{i}"] for i in range(16)]
    return 2.0 * sum(vals) / 16.0 + 0.6 * vals[0] * vals[15] \
        - 0.4 * (vals[3] - vals[12]) ** 2


def _make_gnn_samples(n: int) -> list[dict[str, Any]]:
    rng = np.random.default_rng(SEED_GNN)
    out = []
    for _ in range(n):
        p = {f"p{i}": float(v) for i, v in enumerate(rng.random(16))}
        out.append({"params": p, "metrics": {"cost": _gnn_truth(p)}})
    return out


def _gnn_test_points() -> list[tuple[dict[str, float], dict[str, Any]]]:
    rng = np.random.default_rng([SEED_GNN, 1])
    out = []
    for _ in range(40):
        p = {f"p{i}": float(v) for i, v in enumerate(rng.random(16))}
        out.append((p, {"truth": _gnn_truth(p)}))
    return out


# ── 精度评估器（固定求和序——确定性前提） ─────────────────────────────────────
def _rmse(errs: list[float]) -> tuple[float, float, float]:
    """(rmse, mae, max_abs_err)；求和按固定顺序保证逐位复现。"""
    n = len(errs)
    sq = 0.0
    ab = 0.0
    mx = 0.0
    for e in errs:
        sq += e * e
        a = abs(e)
        ab += a
        if a > mx:
            mx = a
    return math.sqrt(sq / n), ab / n, mx


def _eval_scalar(model: Any, preds: list[dict[str, Any]],
                 test_points: list[tuple[dict[str, float], dict[str, Any]]],
                 ) -> tuple[float, dict[str, Any]]:
    errs = [float(p["cost"]) - tp[1]["truth"]
            for p, tp in zip(preds, test_points, strict=True)]
    rmse, mae, mx = _rmse(errs)
    return rmse, {"mae": mae, "max_abs_err": mx}


def _eval_mt(model: Any, preds: list[dict[str, Any]],
             test_points: list[tuple[dict[str, float], dict[str, Any]]],
             ) -> tuple[float, dict[str, Any]]:
    """双指标池化 RMSE（逐指标值进 accuracy——池化口径=全体误差平方均值）。"""
    errs: list[float] = []
    per: dict[str, float] = {}
    for key, truth_key in (("cost", "truth"), ("m2", "truth_m2")):
        sub = [float(p[key]) - tp[1][truth_key]
               for p, tp in zip(preds, test_points, strict=True)]
        errs.extend(sub)
        per[key] = _rmse(sub)[0]
    rmse, mae, mx = _rmse(errs)
    return rmse, {"mae": mae, "max_abs_err": mx, "rmse_by_metric": per}


def _eval_conformal(
    model: Any, preds: list[dict[str, Any]],
    test_points: list[tuple[dict[str, float], dict[str, Any]]],
) -> tuple[float, dict[str, Any]]:
    rmse, acc = _eval_scalar(model, preds, test_points)
    q = (model.uncertainty(test_points[0][0]) or {}).get("cost")
    if q is not None and math.isfinite(float(q)):
        hit = sum(1 for p, tp in zip(preds, test_points, strict=True)
                  if abs(float(p["cost"]) - tp[1]["truth"]) <= float(q))
        acc["coverage_nominal90"] = hit / len(preds)
        acc["q_cost"] = float(q)
    return rmse, acc


def _eval_ensemble(
    model: Any, preds: list[dict[str, Any]],
    test_points: list[tuple[dict[str, float], dict[str, Any]]],
) -> tuple[float, dict[str, Any]]:
    rmse, acc = _eval_scalar(model, preds, test_points)
    acc["weights"] = dict(model.fit_info.get("weights", {}))
    acc["n_members_effective"] = model.fit_info.get("n_members_effective")
    return rmse, acc


def _eval_curve_complex(
    model: Any, preds: list[Any],
    test_points: list[tuple[dict[str, float], dict[str, Any]]],
) -> tuple[float, dict[str, Any]]:
    assert _CURVE_FREQ_HZ is not None
    errs: list[float] = []
    for pred, tp in zip(preds, test_points, strict=True):
        truth = _to_db(_curve_truth(_CURVE_FREQ_HZ, tp[1]["u"]))
        pred_db = _to_db(np.asarray(pred))  # 复曲线→dB（与真值同口径）
        errs.extend((pred_db - truth).tolist())
    rmse, mae, mx = _rmse(errs)
    return rmse, {"mae": mae, "max_abs_err": mx, "domain": "s11_db",
                  "n_grid": int(N_FREQ)}


def _eval_curve_dict(
    model: Any, preds: list[dict[str, Any]],
    test_points: list[tuple[dict[str, float], dict[str, Any]]],
) -> tuple[float, dict[str, Any]]:
    errs: list[float] = []
    n_grid = 0
    for pred, tp in zip(preds, test_points, strict=True):
        grid = np.asarray(pred["freq_ghz"], dtype=float)
        truth = _to_db(_curve_truth(grid * 1e9, tp[1]["u"]))
        arr = np.asarray(pred["s11_db"], dtype=float)
        n_grid = int(arr.size)
        errs.extend((arr - truth).tolist())
    rmse, mae, mx = _rmse(errs)
    return rmse, {"mae": mae, "max_abs_err": mx, "domain": "s11_db",
                  "n_grid": n_grid}


def _eval_siren(model: Any, preds: list[dict[str, Any]],
                test_points: list[tuple[dict[str, float], dict[str, Any]]],
                ) -> tuple[float, dict[str, Any]]:
    def field_float(v: Any) -> float:
        # 实数模式直取（abs 会把负场值折号成系统伪差）；复数模式取模
        c = complex(v)
        return c.real if c.imag == 0.0 else abs(c)

    errs = [field_float(p["field"]) - tp[1]["truth"]
            for p, tp in zip(preds, test_points, strict=True)]
    rmse, mae, mx = _rmse(errs)
    return rmse, {"mae": mae, "max_abs_err": mx, "domain": "field_value"}


# ── case 装配 ────────────────────────────────────────────────────────────────


@dataclass
class Case:
    """单个基准 case（键×档；samples/test 固定→确定性）。"""

    key: str
    tier: str
    config: dict[str, Any]
    meta_config: dict[str, Any]  # JSON 记录面（剔除大体积数据键）
    samples: list[dict[str, Any]]
    test_points: list[tuple[dict[str, float], dict[str, Any]]]
    eval_fn: Callable[..., tuple[float, dict[str, Any]]]
    predict_fn: Callable[[Any, dict[str, float]], Any] = (
        lambda model, params: model.predict(params))
    notes: str = ""
    designed_skip: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _predict_curve_fn(n_points: int) -> Callable[[Any, dict[str, float]], Any]:
    """曲线代理的计时预测面（predict_curve/predict_curve_with_std）。"""

    def call(model: Any, params: dict[str, float]) -> Any:
        if hasattr(model, "predict_curve_with_std"):
            return model.predict_curve_with_std(params, n_points=n_points)
        return model.predict_curve(params, n_points=n_points)

    return call


def _predict_pole_curve_fn() -> Callable[[Any, dict[str, float]], Any]:
    """极点族曲线代理的计时预测面（predict_curve→复数组，无 n_points）。"""

    def call(model: Any, params: dict[str, float]) -> Any:
        return model.predict_curve(params)

    return call


def _scalar_case(key: str, tier: str, config: dict[str, Any],
                 n: int, *, with_m2: bool = False, notes: str = "",
                 eval_fn: Callable[..., tuple[float, dict[str, Any]]]
                 | None = None) -> Case:
    meta = {k: v for k, v in config.items()
            if k not in ("low_fi_samples",)}
    return Case(
        key=key, tier=tier, config=config, meta_config=meta,
        samples=_make_scalar_samples(n, SEED_SCALAR, with_m2=with_m2),
        test_points=_scalar_test_points(),
        eval_fn=eval_fn or _eval_scalar,
        notes=notes or (f"n_train={n} 解析真值面（训练目标含 "
                        f"σ={SCALAR_NOISE_SD} 观测噪声，RMSE 对解析真值）"
                        + (" 双指标(cost+m2)" if with_m2 else "")))


def build_cases() -> list[Case]:
    """全 case 清单（覆盖 registered keys 的 1:1 映射；见模块 docstring）。"""
    _make_curve_assets()
    cases: list[Case] = []

    # ── 标量族 n=200 档 ──
    bd = dict(SCALAR_BD)
    cases.append(_scalar_case("poly_ridge", "scalar_n200", {"bounds": bd}, 200))
    cases.append(_scalar_case("huber_ridge", "scalar_n200", {"bounds": bd}, 200))
    cases.append(_scalar_case("gbdt", "scalar_n200", {"bounds": bd}, 200))
    cases.append(_scalar_case(
        "nn", "scalar_n200",
        {"bounds": bd, "augmenter": "polynomial_cross", "epochs": 300,
         "n_ensemble": 2, "hidden": 24, "seed": 42}, 200))
    cases.append(_scalar_case("pod_rom", "scalar_n40", {"bounds": bd}, 40))
    cases.append(_scalar_case("smt_kriging", "scalar_n200", {"bounds": bd}, 200))
    cases.append(_scalar_case("warped_kriging", "scalar_n200",
                              {"bounds": bd}, 200))
    cases.append(_scalar_case("saas_gp", "scalar_n200",
                              {"bounds": bd}, 200,
                              notes="n_train=200 MAP 档（无 posterior）"))
    cases.append(_scalar_case(
        "mt_gp", "scalar_n200_m2", {"bounds": bd, "seed": 42}, 200,
        with_m2=True, eval_fn=_eval_mt,
        notes="n_train=200 双指标 ICM（cost+m2 共享潜变量）；"
              "因子初值 seed=42——缺省 seed 在本面落入 ℓ 下界退化盆"
              "（双稳 MLE 的种子敏感性如实记录）；共享 ℓ 跨指标折衷"
              "面（rmse 高于逐指标独立 GP 属 ICM 建模特征）"))
    cases.append(_scalar_case(
        "conformal", "scalar_n200",
        {"base_kind": "poly_ridge", "base_config": {"bounds": bd},
         "alpha": 0.1, "cal_ratio": 0.5, "seed": 7}, 200,
        eval_fn=_eval_conformal,
        notes="wrapper(poly_ridge) alpha=0.1 附带名义90%覆盖实证"
              "（格点测试面+二阶 base 系统偏差下实测覆盖可低于名义——"
              "边际覆盖保证以同分布随机样本为前提，实测值如实记录）"))
    cases.append(_scalar_case(
        "ensemble", "scalar_n64",
        {"bounds": bd, "members": ["poly_ridge", "huber_ridge",
                                   {"kind": "gbdt",
                                    "config": {"n_estimators": 30}}],
         "rho_metric": "cost"}, 64,
        eval_fn=_eval_ensemble,
        notes="n_train=64（LOOCV O(n)·成员 fits 预算）；"
              "成员=poly_ridge/huber_ridge/gbdt(30)"))
    cases.append(_scalar_case(
        "smt_mfk", "mf_n40hi80lo",
        {"bounds": bd, "low_fi_samples": _make_mfk_low_samples(80),
         "theta0": 1e-2}, 40,
        notes="双保真 co-kriging：hi=40 真值 / lo=80 低保真"
              "（0.85·f+0.5 偏置面）"))

    # ── gnn_geom（像素图，16 维占据） ──
    cases.append(Case(
        key="gnn_geom", tier="pixel_grid4x4_n120",
        config={"grid_shape": [4, 4], "n_rounds": 2, "hidden_dim": 8,
                "ridge_lam": 1e-3},
        meta_config={"grid_shape": [4, 4], "n_rounds": 2,
                     "hidden_dim": 8, "ridge_lam": 1e-3},
        samples=_make_gnn_samples(120), test_points=_gnn_test_points(),
        eval_fn=_eval_scalar,
        notes="4×4 像素占据 p0..p15；真值=平滑像素泛函 n_train=120"))

    # ── rff_gp 规模面（n=200 与 n=2000 两档，任务书 GP 系） ──
    cases.append(_scalar_case(
        "rff_gp", "rff_n200",
        {"bounds": bd, "n_features": 256}, 200,
        notes="n_features=256"))
    cases.append(_scalar_case(
        "rff_gp", "rff_n2000",
        {"bounds": bd, "n_features": 512, "mle_subsample": 256}, 2000,
        notes="规模档 n_train=2000；ℓ-MLE 固定 seed 子样本 256"
              "（O(n³) 诚实近似档）"))

    # ── 曲线族（小档 torch + 极点族闭式） ──
    curve_bd = dict(CURVE_BD)
    curve_samples = _make_curve_samples(48)
    curve_test = _curve_test_points()
    curve_note = "S11 dB 曲线真值（固定极点基+仿射 theta）；n_train=48"
    cases.append(Case(
        key="fno", tier="curve_small",
        config={"bounds": curve_bd, "freq_grid": list(FREQ_GHZ),
                "curve_samples": 32, "width": 16, "n_modes": 4,
                "n_layers": 2, "epochs": 300, "seed": 42,
                "curve_key": "s11_curve_db"},
        meta_config={"freq_grid": list(FREQ_GHZ), "curve_samples": 32,
                     "width": 16, "n_modes": 4, "n_layers": 2,
                     "epochs": 300, "seed": 42},
        samples=curve_samples, test_points=curve_test,
        predict_fn=_predict_curve_fn(32), eval_fn=_eval_curve_dict,
        extra={"predict_api": "predict_curve(n_points=32)"},
        notes="torch 小档 " + curve_note))
    cases.append(Case(
        key="fno_lite", tier="curve_small",
        config={"bounds": curve_bd, "freq_grid": list(FREQ_GHZ),
                "curve_samples": 32, "hidden": 32, "epochs": 300,
                "seed": 42, "curve_key": "s11_curve_db"},
        meta_config={"freq_grid": list(FREQ_GHZ), "curve_samples": 32,
                     "hidden": 32, "epochs": 300, "seed": 42},
        samples=curve_samples, test_points=curve_test,
        predict_fn=_predict_curve_fn(32), eval_fn=_eval_curve_dict,
        extra={"predict_api": "predict_curve(n_points=32)"},
        notes="torch 小档 " + curve_note))
    cases.append(Case(
        key="deeponet", tier="curve_small",
        config={"bounds": curve_bd, "freq_grid": list(FREQ_GHZ),
                "curve_samples": 32, "p": 16, "hidden": 32, "depth": 2,
                "trunk_fourier_feats": 6, "epochs": 300, "seed": 42,
                "curve_key": "s11_curve_db"},
        meta_config={"freq_grid": list(FREQ_GHZ), "curve_samples": 32,
                     "p": 16, "hidden": 32, "depth": 2,
                     "trunk_fourier_feats": 6, "epochs": 300, "seed": 42},
        samples=curve_samples, test_points=curve_test,
        predict_fn=_predict_curve_fn(32), eval_fn=_eval_curve_dict,
        extra={"predict_api": "predict_curve(n_points=32)"},
        notes="torch 小档 " + curve_note))
    cases.append(Case(
        key="deep_ensemble", tier="curve_small_m3",
        config={"bounds": curve_bd, "base_kind": "fno", "n_members": 3,
                "seed": 42, "bootstrap": True, "dispersion": "std",
                "freq_grid": list(FREQ_GHZ), "curve_samples": 32,
                "width": 12, "n_modes": 4, "n_layers": 2, "epochs": 200,
                "curve_key": "s11_curve_db"},
        meta_config={"base_kind": "fno", "n_members": 3, "seed": 42,
                     "bootstrap": True, "freq_grid": list(FREQ_GHZ),
                     "curve_samples": 32, "width": 12, "epochs": 200},
        samples=curve_samples, test_points=curve_test,
        predict_fn=_predict_curve_fn(32), eval_fn=_eval_curve_dict,
        extra={"predict_api": "predict_curve_with_std(n_points=32)"},
        notes="torch 小档 M=3 成员（fno 小档 bootstrap）；" + curve_note))
    cases.append(Case(
        key="pole_residue", tier="curve_pole_n48",
        config={"bounds": curve_bd, "freq_grid_ghz": list(FREQ_GHZ),
                "n_freq": N_FREQ, "head": "ridge"},
        meta_config={"freq_grid_ghz": list(FREQ_GHZ), "n_freq": N_FREQ,
                     "head": "ridge"},
        samples=curve_samples, test_points=curve_test,
        predict_fn=_predict_pole_curve_fn(), eval_fn=_eval_curve_complex,
        extra={"predict_api": "predict_curve(训练栅格)"},
        notes="闭式 ridge 头（真值同构：固定极点基+仿射 theta）；"
              + curve_note))
    cases.append(Case(
        key="vf_parametric", tier="curve_pole_n48",
        config={"bounds": curve_bd, "freq_grid_ghz": list(FREQ_GHZ),
                "n_freq": N_FREQ, "k_neighbors": 4},
        meta_config={"freq_grid_ghz": list(FREQ_GHZ), "n_freq": N_FREQ,
                     "k_neighbors": 4},
        samples=curve_samples, test_points=curve_test,
        predict_fn=_predict_pole_curve_fn(), eval_fn=_eval_curve_complex,
        extra={"predict_api": "predict_curve(训练栅格)"},
        notes="邻域插值（theta 仿射→局部线性精确回收面）；" + curve_note))

    # ── siren 场代理（torch 小档） ──
    cases.append(Case(
        key="siren", tier="field_n1024",
        config={"coord_keys": ["x", "y"], "field_key": "field",
                "bounds": {"x": (0.0, 1.0), "y": (0.0, 1.0)},
                "w0": 15.0, "n_hidden": 3, "width": 64, "epochs": 1000,
                "lr": 1e-3, "seed": 42},
        meta_config={"coord_keys": ["x", "y"], "w0": 15.0, "n_hidden": 3,
                     "width": 64, "epochs": 1000, "lr": 1e-3, "seed": 42},
        samples=_make_siren_samples(), test_points=_siren_test_points(),
        eval_fn=_eval_siren,
        notes="坐标→场（k=1.5 谱内容 w0=15）；N=1024 网格采样，"
              "测试 20×20 栅格"))

    # ── 跳过面（designed skip，如实登记） ──
    cases.append(Case(
        key="mapes_pixel_analytic", tier="designed_skip", config={},
        meta_config={}, samples=[], test_points=[], eval_fn=_eval_scalar,
        designed_skip="解析物理模型（fit 不训练；需实测 npz 装配面 "
                      "z_all_npz）——合成精度基准不适用，加载/装配面由"
                      "既有单测覆盖",
        notes="designed_skip"))
    return cases


def _make_mfk_low_samples(n: int) -> list[dict[str, Any]]:
    """smt_mfk 低保真样本（便宜偏置面 0.85·f+0.5；AR(1) 融合可辨）。"""
    rng = np.random.default_rng(SEED_MFK)
    noise = np.random.default_rng(SEED_MFK + 500)
    out = []
    for _ in range(n):
        r = rng.random(3)
        u = {"x1": float(r[0]), "x2": float(r[1]), "x3": float(r[2])}
        out.append({"params": _unit_params(u),
                    "metrics": {"cost": 0.85
                                * _scalar_truth(u["x1"], u["x2"], u["x3"])
                                + 0.5
                                + float(noise.normal(0.0, SCALAR_NOISE_SD))}})
    return out


# ── 执行器 ───────────────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    """单 case 结果（json 落盘形态；精度字段=逐位比对对象）。"""

    key: str
    tier: str
    status: str  # ok | skipped | error
    fit_s: float = 0.0
    predict_s: float = 0.0
    n_train: int = 0
    n_test: int = 0
    rmse: float | None = None
    accuracy: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    meta_config: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key, "tier": self.tier, "status": self.status,
            "fit_s": self.fit_s, "predict_s": self.predict_s,
            "n_train": self.n_train, "n_test": self.n_test,
            "rmse": self.rmse, "accuracy": self.accuracy,
            "notes": self.notes, "config": self.meta_config,
            "extra": self.extra, "error": self.error,
        }


def _classify_skip(exc: Exception) -> str | None:
    """缺依赖类异常 → skip 文案；其余 None（真 error）。"""
    if isinstance(exc, ImportError):
        return f"缺依赖: {type(exc).__name__}: {exc}"
    if isinstance(exc, RuntimeError) and "需要" in str(exc):
        return f"缺依赖: {exc}"
    return None


def run_case(case: Case) -> CaseResult:
    """跑单 case：create（不计时）→ fit 计时 → 逐点 predict 计时 → 评估。"""
    if case.designed_skip is not None:
        return CaseResult(key=case.key, tier=case.tier, status="skipped",
                          notes=case.designed_skip,
                          meta_config=case.meta_config, extra=case.extra)
    try:
        model = surrogate_registry.create(case.key, config=dict(case.config))
        t0 = time.perf_counter()
        model.fit(case.samples)
        fit_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        preds = [case.predict_fn(model, params)
                 for params, _tp in case.test_points]
        predict_s = time.perf_counter() - t0

        rmse, acc = case.eval_fn(model, preds, case.test_points)
        return CaseResult(
            key=case.key, tier=case.tier, status="ok", fit_s=fit_s,
            predict_s=predict_s, n_train=len(case.samples),
            n_test=len(case.test_points), rmse=rmse, accuracy=acc,
            notes=case.notes, meta_config=case.meta_config, extra=case.extra)
    except Exception as exc:
        # 缺依赖/坏 case 如实落账（#122 不静默——error 状态带原文）
        skip = _classify_skip(exc)
        if skip is not None:
            return CaseResult(key=case.key, tier=case.tier, status="skipped",
                              notes=skip, meta_config=case.meta_config,
                              extra=case.extra)
        return CaseResult(
            key=case.key, tier=case.tier, status="error",
            notes=case.notes, meta_config=case.meta_config, extra=case.extra,
            error=f"{type(exc).__name__}: {exc}")


# ── 确定性比对（精度列逐位；计时列豁免） ─────────────────────────────────────
_ACCURACY_KEYS = ("rmse", "accuracy")


def _accuracy_fingerprint(res: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(repr(res.get(k)) for k in _ACCURACY_KEYS)


def compare_rows(a: list[dict[str, Any]], b: list[dict[str, Any]],
                 ) -> list[str]:
    """按 (key, tier) 对齐比对精度字段；返回差异描述列表（空=逐位一致）。"""
    diffs: list[str] = []
    ma = {(r["key"], r["tier"]): r for r in a}
    mb = {(r["key"], r["tier"]): r for r in b}
    if set(ma) != set(mb):
        diffs.append(f"case 集不一致: only_a={sorted(set(ma) - set(mb))} "
                     f"only_b={sorted(set(mb) - set(ma))}")
        return diffs
    for kid in sorted(ma):
        ra, rb = ma[kid], mb[kid]
        if ra.get("status") != rb.get("status"):
            diffs.append(f"{kid}: status {ra.get('status')} != "
                         f"{rb.get('status')}")
            continue
        if ra.get("status") != "ok":
            continue  # skip 行无精度面
        fa, fb = _accuracy_fingerprint(ra), _accuracy_fingerprint(rb)
        if fa != fb:
            diffs.append(f"{kid}: 精度列不逐位 "
                         f"rmse {ra.get('rmse')!r} != {rb.get('rmse')!r}")
    return diffs


# ── 输出面 ───────────────────────────────────────────────────────────────────


def _git_sha() -> str | None:
    try:
        repo = Path(__file__).resolve().parents[1]
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=repo, capture_output=True, text=True,
                             timeout=10, check=False)
        sha = out.stdout.strip()
        return sha or None
    except Exception:
        return None


def _env_block() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "torch": TORCH_VERSION,
        "threads_pinned": dict(_THREADS_PINNED),
        "torch_num_threads": (int(torch.get_num_threads())
                              if torch is not None else None),
        "git_sha": _git_sha(),
    }


def render_markdown(doc: dict[str, Any]) -> str:
    """json → md 基线表（键/fit_s/predict_s/rmse/notes 五列）。"""
    lines = [
        f"# 代理键性能基线（{doc.get('tag', 'bench')}）",
        "",
        f"- 工具：scripts/bench_surrogates.py（schema {SCHEMA}；"
        "基线记录工具，不是门）",
        f"- 时间：{doc.get('created_utc')}；环境：python "
        f"{doc['env']['python']} / numpy {doc['env']['numpy']} / "
        f"torch {doc['env']['torch']}",
        f"- git: {doc['env'].get('git_sha')}；线程钉 1 "
        "（BLAS/OMP/torch，#258 家法）",
        "- seed 政策：训练采样/真值系数固定（json.seed_policy）；"
        "模型侧 seed 显式在各 case config。",
        "- 计时口径：fit=单次 fit 全程；predict=全测试集逐点循环总时长"
        "（n_test 见 json）——跨机只作量级参照，精度列才是逐位复现面。",
        "",
        "| 键 | 档 | 状态 | fit_s | predict_s | rmse | notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in doc["results"]:
        fit_s = f"{r['fit_s']:.4f}" if r["status"] == "ok" else "-"
        pred_s = f"{r['predict_s']:.4f}" if r["status"] == "ok" else "-"
        rmse = (f"{r['rmse']:.6e}"
                if r["status"] == "ok" and r.get("rmse") is not None else "-")
        notes = r.get("notes") or ""
        if r.get("error"):
            notes = (notes + " | ERROR: " + r["error"]).strip(" |")
        lines.append(
            f"| {r['key']} | {r['tier']} | {r['status']} | {fit_s} "
            f"| {pred_s} | {rmse} | {notes} |")
    cov = doc.get("coverage", {})
    lines += [
        "",
        "## 覆盖面",
        "",
        f"- 注册键 {len(cov.get('registered', []))} 个，case 覆盖 "
        f"{len(cov.get('cased', []))} 个；未覆盖="
        f"{cov.get('missing_cases', []) or '无'}",
        f"- ok={cov.get('n_ok')} skipped={cov.get('n_skipped')} "
        f"error={cov.get('n_error')}",
    ]
    det = doc.get("determinism")
    if det:
        lines += ["", "## 确定性", "",
                  f"- repeat-check（进程内两跑精度列逐位比对）："
                  f"ok={det.get('ok')}；差异={det.get('diffs') or '无'}"]
    return "\n".join(lines) + "\n"


# ── main ─────────────────────────────────────────────────────────────────────


def _load_doc(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="代理键性能基准套件（基线记录工具，不是门）")
    parser.add_argument("--out", default="runs/aurora_n/bench",
                        help="产物目录（默认 runs/aurora_n/bench/）")
    parser.add_argument(
        "--tag", default=None,
        help="产物名前缀（默认 bench_<时间戳>；基线用 baseline_20261031）")
    parser.add_argument(
        "--repeat-check", action="store_true",
        help="进程内跑两遍矩阵并逐位比对精度列（结果计入 json.determinism）")
    parser.add_argument(
        "--compare", nargs=2, metavar=("A.json", "B.json"),
        help="两个基线 JSON 的精度列逐位比对（验证模式，不跑矩阵）")
    parser.add_argument(
        "--only", default=None,
        help="只跑逗号分隔的键（开发分诊用；默认全矩阵）")
    args = parser.parse_args(argv)

    if args.compare:
        da, db = _load_doc(args.compare[0]), _load_doc(args.compare[1])
        diffs = compare_rows(da["results"], db["results"])
        for d in diffs:
            print(f"DIFF: {d}")
        print(f"COMPARE_{'OK' if not diffs else 'FAIL'} "
              f"({len(diffs)} diffs)")
        return 0 if not diffs else 1

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    all_cases = build_cases()
    cases = [c for c in all_cases
             if only is None or c.key in only or c.tier in only]

    def run_matrix() -> list[dict[str, Any]]:
        return [run_case(c).to_json() for c in cases]

    t0 = time.perf_counter()
    results = run_matrix()
    det_block: dict[str, Any] | None = None
    if args.repeat_check:
        results_b = run_matrix()
        diffs = compare_rows(results, results_b)
        det_block = {"repeat_check": True, "ok": not diffs, "diffs": diffs}
        if diffs:
            for d in diffs:
                print(f"DETERMINISM_DIFF: {d}")
    wall_s = time.perf_counter() - t0

    registered = sorted(surrogate_registry.available())
    cased = sorted({c.key for c in all_cases})
    doc = {
        "schema": SCHEMA,
        "tag": args.tag or time.strftime("bench_%Y%m%d_%H%M%S"),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime()),
        "env": _env_block(),
        "seed_policy": {
            "scalar": SEED_SCALAR, "curve": SEED_CURVE,
            "siren": SEED_SIREN, "gnn": SEED_GNN, "mfk": SEED_MFK,
            "note": "模型侧 seed 显式在各 case config（json results.config）",
        },
        "determinism": det_block or {"repeat_check": False},
        "coverage": {
            "registered": registered, "cased": cased,
            "missing_cases": [k for k in registered if k not in cased],
            "extra_cases": [k for k in cased if k not in registered],
            "n_ok": sum(1 for r in results if r["status"] == "ok"),
            "n_skipped": sum(1 for r in results if r["status"] == "skipped"),
            "n_error": sum(1 for r in results if r["status"] == "error"),
        },
        "total_wall_s": wall_s,
        "results": results,
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{doc['tag']}.json"
    md_path = out_dir / f"{doc['tag']}.md"
    json_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    md_path.write_text(render_markdown(doc), encoding="utf-8")

    cov = doc["coverage"]
    print(f"BENCH_DONE rows={len(results)} "
          f"ok={cov['n_ok']} skipped={cov['n_skipped']} "
          f"error={cov['n_error']} missing_cases="
          f"{len(cov['missing_cases'])} wall_s={wall_s:.1f}")
    print(f"OUT {json_path}")
    print(f"OUT {md_path}")
    if det_block is not None:
        print(f"DETERMINISM_OK={det_block['ok']}")
    return 0 if cov["n_error"] == 0 else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
