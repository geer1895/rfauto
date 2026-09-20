"""像素域生成式逆设计最小闭环（stage-1：提议器 × MAPES 闭式评判 × top-k）。

方案口径（边界：与 PCell DSL 参数化路线**正交**，作用于像素化设计域）：

    像素提议器 → 图案 P → MAPES 闭式内核（占用→Z_L(P)→Schur 补→S，
    core/mapes.py 既有实现，本模块零改动复用）→ 指定双/三频段传输响应
    评判（hinge 误差 dB + 等级）→ top-k 记录 → 局部搜索精修。

数值只在确定性内核：提议器只产出**拓扑**（0/1 像素矩阵），
全部数字（误差/等级/S 参数）由 MAPES 闭式评判器产出；同参数同输出，
无 LLM、无随机数值进入评判链。

诚实边界（stage-1，如实标注）：
- 提议器 = 随机伯努利 + 1-bit 翻转局部贪心两档；可选第三档为
  core/inverse_diffusion.DiffusionProposer（**确定性退火
  噪声-去噪**提议器，``diffusion_steps>0`` 启用）——它不是训练出的神经扩散/
  流匹配生成模型，**流匹配仍未实现**（可选上档）；
- Z_ALL 由合成 RLC 网格（core/mapes.RlcMesh/fake_mesh）显式构造，**不是
  真机提取**——stage-2 才接 adapters/openems_rotation.py 多端口轮转；
- 评判目标是"图案可实现的指定频段传输响应"（BPF 式通带/阻带 hinge
  口径），在合成网格可达空间内演示闭环，不冒充真实滤波器工艺；
- 判等：error_db ≤ 0（规格全满足）= PASS；≤ 3 dB = NEAR；否则 MISS。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import MapesModel, MapesResult, PixelLayout, fake_mesh

__all__ = [
    "PassbandTarget",
    "build_demo_model",
    "evaluate_design",
    "evaluate_occupancy",
    "one_flip_neighbors",
    "propose_random",
    "run_inverse_search",
]

#: 判等阈值（dB）：≤0 规格全满足；≤3 接近；>3 未达
GRADE_NEAR_LIMIT_DB = 3.0
_DB_FLOOR = 1.0e-30


@dataclass(frozen=True)
class PassbandTarget:
    """像素滤波器目标响应（dB 阈值口径，全部数值语义由评判器解释）。

    - 通带 `band_ghz`：|S21| 不得低于 `s21_pass_min_db`；
    - 低阻带 `stop_low_ghz`：|S21| 不得高于 `s21_stop_low_max_db`；
    - 高阻带 `stop_high_ghz`：|S21| 不得高于 `s21_stop_high_max_db`。
    """

    band_ghz: tuple[float, float]
    stop_low_ghz: tuple[float, float]
    stop_high_ghz: tuple[float, float]
    s21_pass_min_db: float
    s21_stop_low_max_db: float
    s21_stop_high_max_db: float

    def __post_init__(self) -> None:
        for name in ("band_ghz", "stop_low_ghz", "stop_high_ghz"):
            band = tuple(getattr(self, name))
            if len(band) != 2 or not (band[0] < band[1]):
                raise ConfigError(
                    f"{name} 必须是 (低, 高) 且低<高，实得 {band}")
            if not all(np.isfinite(x) for x in band):
                raise ConfigError(f"{name} 含非有限值：{band}")
        if self.stop_low_ghz[1] > self.band_ghz[0]:
            raise ConfigError("低阻带上缘必须 ≤ 通带下缘")
        if self.band_ghz[1] > self.stop_high_ghz[0]:
            raise ConfigError("通带上缘必须 ≤ 高阻带下缘")

    def to_dict(self) -> dict[str, Any]:
        return {
            "band_ghz": list(self.band_ghz),
            "stop_low_ghz": list(self.stop_low_ghz),
            "stop_high_ghz": list(self.stop_high_ghz),
            "s21_pass_min_db": self.s21_pass_min_db,
            "s21_stop_low_max_db": self.s21_stop_low_max_db,
            "s21_stop_high_max_db": self.s21_stop_high_max_db,
        }


def _band_mask(freq_ghz: np.ndarray, band: tuple[float, float]) -> np.ndarray:
    return (freq_ghz >= band[0]) & (freq_ghz <= band[1])


def _s21_db(result: MapesResult) -> np.ndarray:
    if result.n_io < 2:
        raise ConfigError(
            f"评判 S21 需要至少 2 个外部端口，实得 n_io={result.n_io}")
    s21 = np.asarray(result.s_external)[:, 1, 0]
    return 20.0 * np.log10(np.maximum(np.abs(s21), _DB_FLOOR))


def evaluate_design(result: MapesResult, target: PassbandTarget) -> dict[str, Any]:
    """MAPES 求检结果 → 频段 hinge 误差（dB，≥0）与等级（确定性纯函数）。

    误差 = 通带欠达 + 低阻带泄漏 + 高阻带泄漏（各自取带内 hinge 均值）。
    频段与扫频无交集时显式报错（#121 精神：空交集不得静默通过）。
    """
    freq_ghz = np.asarray(result.freq_hz, dtype=float) / 1.0e9
    s21 = _s21_db(result)
    parts: dict[str, tuple[np.ndarray, float, str, tuple[float, float]]] = {
        "pass": (_band_mask(freq_ghz, target.band_ghz),
                 target.s21_pass_min_db, "欠达", target.band_ghz),
        "stop_low": (_band_mask(freq_ghz, target.stop_low_ghz),
                     target.s21_stop_low_max_db, "泄漏", target.stop_low_ghz),
        "stop_high": (_band_mask(freq_ghz, target.stop_high_ghz),
                      target.s21_stop_high_max_db, "泄漏",
                      target.stop_high_ghz),
    }
    out: dict[str, Any] = {}
    for key, (mask, threshold, kind, band) in parts.items():
        if not bool(np.any(mask)):
            raise ConfigError(
                f"{key} 频段 [{band[0]:g}, {band[1]:g}] GHz 与扫频无交集"
                f"（扫频 {freq_ghz[0]:g}–{freq_ghz[-1]:g} GHz，"
                f"#121：空交集不得静默通过）")
        band_db = s21[mask]
        hinge = (np.maximum(0.0, threshold - band_db) if kind == "欠达"
                 else np.maximum(0.0, band_db - threshold))
        out[f"{key}_violation_db"] = float(np.mean(hinge))
        out[f"n_{key}_freq"] = int(mask.sum())
    out["s21_passband_min_db"] = float(np.min(s21[parts["pass"][0]]))
    out["s21_stopband_max_db"] = float(np.max(
        np.concatenate([s21[parts["stop_low"][0]],
                        s21[parts["stop_high"][0]]])))
    error = (out["pass_violation_db"] + out["stop_low_violation_db"]
             + out["stop_high_violation_db"])
    out["error_db"] = float(error)
    out["grade"] = ("PASS" if error <= 1e-9
                    else "NEAR" if error <= GRADE_NEAR_LIMIT_DB else "MISS")
    return out


def evaluate_occupancy(
    model: MapesModel,
    occupancy: Any,
    target: PassbandTarget,
    *,
    vias: Any = None,
) -> dict[str, Any]:
    """单图案闭环一步：P → MAPES 闭式求检 → 评判（含展平参数回传）。"""
    params = model.layout.flatten(occupancy, vias)
    result = model.evaluate(params)
    out = evaluate_design(result, target)
    out["params"] = params
    out["topology_key"] = result.topology_key
    return out


def propose_random(
    layout: PixelLayout,
    rng: random.Random,
    *,
    p_on: float = 0.5,
) -> np.ndarray:
    """随机伯努利像素提议器（只产出拓扑；rng 注入保证可复现）。"""
    if not 0.0 <= p_on <= 1.0:
        raise ConfigError(f"p_on 必须落在 [0,1]，实得 {p_on}")
    occ = np.zeros((layout.n_rows, layout.n_cols), dtype=bool)
    for r in range(layout.n_rows):
        for c in range(layout.n_cols):
            occ[r, c] = rng.random() < p_on
    return occ


def one_flip_neighbors(occupancy: Any) -> list[np.ndarray]:
    """1-bit 翻转邻域（行主序枚举，确定性；M*N 个候选）。"""
    occ = np.asarray(occupancy, dtype=bool)
    if occ.ndim != 2:
        raise ConfigError(f"occupancy 必须是二维矩阵，实得 shape={occ.shape}")
    out: list[np.ndarray] = []
    for r in range(occ.shape[0]):
        for c in range(occ.shape[1]):
            cand = occ.copy()
            cand[r, c] = not cand[r, c]
            out.append(cand)
    return out


def build_demo_model(
    layout: PixelLayout,
    freq_hz: Any,
    *,
    mesh_kwargs: dict[str, float] | None = None,
) -> MapesModel:
    """合成 Z_ALL 的 MAPES 模型（stage-1 演示档：RlcMesh 网格，非真机）。"""
    mesh = fake_mesh(layout.n_ports, **(mesh_kwargs or {}))
    freqs = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    z_all = np.stack([mesh.z_all(float(f)) for f in freqs])
    return MapesModel(layout, z_all, freqs)


def _record(occupancy: np.ndarray, judged: dict[str, Any]) -> dict[str, Any]:
    occ = np.asarray(occupancy, dtype=bool)
    params = dict(judged["params"])
    return {
        "occupancy": [[int(x) for x in row] for row in occ],
        "params": params,
        "topology_key": judged["topology_key"],
        "error_db": judged["error_db"],
        "grade": judged["grade"],
        "n_occupied": int(occ.sum()),
        "pass_violation_db": judged["pass_violation_db"],
        "stop_low_violation_db": judged["stop_low_violation_db"],
        "stop_high_violation_db": judged["stop_high_violation_db"],
        "s21_passband_min_db": judged["s21_passband_min_db"],
        "s21_stopband_max_db": judged["s21_stopband_max_db"],
    }


def _occ_key(occupancy: np.ndarray) -> bytes:
    return np.ascontiguousarray(np.asarray(occupancy, dtype=bool)).tobytes()


def run_inverse_search(
    model: MapesModel,
    target: PassbandTarget,
    *,
    n_random: int = 64,
    p_on: float = 0.5,
    max_local_steps: int = 8,
    k_top: int = 5,
    seed: int = 7,
    diffusion_steps: int = 0,
    diffusion_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """逆设计搜索主环：随机提议 →（可选）扩散式提议 → 局部 1-bit 贪心精修 → top-k。

    确定性：random.Random(seed) + 行主序邻域枚举 + (error_db, 占位字节)
    排序——同 seed 同模型同目标，结果逐字段一致（elapsed_s 除外）。
    全部数字出自 evaluate_design（MAPES 闭式内核），提议器只给拓扑。

    ``diffusion_steps>0`` 时在随机阶段与局部精修之间插入
    ``core/inverse_diffusion.DiffusionProposer``（确定性退火噪声-去噪，非训练
    生成模型）的 ``diffusion_steps`` 个提议：每个提议以当前最优为种子、
    评判器引导去噪；只有严格改善才推进搜索起点（单调护栏），全部提议照常
    进 top-k 池。缺省 0 → 与 stage-1 行为逐字节一致。
    """
    t0 = time.time()
    layout = model.layout
    rng = random.Random(seed)
    cache: dict[bytes, dict[str, Any]] = {}
    hits = {"n": 0}

    def judge(occ: np.ndarray) -> dict[str, Any]:
        key = _occ_key(occ)
        if key in cache:
            hits["n"] += 1
            return cache[key]
        cache[key] = evaluate_occupancy(model, occ, target)
        return cache[key]

    pool: list[tuple[float, bytes, np.ndarray, dict[str, Any]]] = []

    def remember(occ: np.ndarray, judged: dict[str, Any]) -> None:
        pool.append((judged["error_db"], _occ_key(occ), occ, judged))

    # ── 阶段 1：随机伯努利提议（生成模型只提议拓扑） ─────────────────────
    n_random = max(1, int(n_random))
    random_best_err = float("inf")
    random_best_occ: np.ndarray | None = None
    for _ in range(n_random):
        occ = propose_random(layout, rng, p_on=p_on)
        judged = judge(occ)
        remember(occ, judged)
        if judged["error_db"] < random_best_err:
            random_best_err = judged["error_db"]
            random_best_occ = occ
    random_phase_best_err = random_best_err

    # ── 阶段 1.5（可选）：扩散式噪声-去噪提议 ───────────
    diffusion_steps = max(0, int(diffusion_steps))
    proposers = ["random_bernoulli"]
    diffusion_phase: dict[str, Any] | None = None
    if diffusion_steps > 0:
        # 惰性导入：inverse_diffusion 依赖本模块的 propose_random/one_flip_neighbors。
        from rfauto.core.inverse_diffusion import create_proposer

        proposer = create_proposer("diffusion_annealed", **(diffusion_kwargs or {}))
        proposers.append(proposer.name)

        def score(occ: np.ndarray) -> float:
            return float(judge(occ)["error_db"])

        n_improving = 0
        for _ in range(diffusion_steps):
            occ = proposer.propose(
                layout, rng, seed_pattern=random_best_occ, score_fn=score)
            judged = judge(occ)
            remember(occ, judged)
            if judged["error_db"] < random_best_err - 1e-12:
                random_best_err = judged["error_db"]
                random_best_occ = occ
                n_improving += 1
        diffusion_phase = {
            "proposer": proposer.describe(),
            "n_proposals": diffusion_steps,
            "start_error_db": random_phase_best_err,
            "best_error_db": random_best_err,
            "improvement_db": random_phase_best_err - random_best_err,
            "n_improving_proposals": n_improving,
        }
    proposers.append("local_1bit_greedy")

    # ── 阶段 2：1-bit 翻转局部贪心精修 ──────────────────────────────────
    current = random_best_occ
    cur_err = random_best_err
    steps = 0
    stop_reason = "local_optimum"
    for _step in range(max(0, int(max_local_steps))):
        best_nb: np.ndarray | None = None
        best_nb_err = cur_err
        for nb in one_flip_neighbors(current):
            err = judge(nb)["error_db"]
            if err < best_nb_err - 1e-12:
                best_nb_err = err
                best_nb = nb
        if best_nb is None:
            break
        judged = judge(best_nb)
        remember(best_nb, judged)
        current, cur_err = best_nb, judged["error_db"]
        steps += 1
    else:
        stop_reason = "max_steps"

    pool.sort(key=lambda item: (item[0], item[1]))
    k_top = max(1, int(k_top))
    top_k = [_record(occ, judged) for _err, _key, occ, judged in pool[:k_top]]

    generative_note = (
        "扩散式提议器=确定性退火噪声-去噪（core/inverse_diffusion，非训练"
        "生成模型）；流匹配未实现；Z_ALL 真机段 followUp"
        if diffusion_steps > 0
        else "扩散/流匹配提议器未实现（可选上档）"
    )
    return {
        "ok": True,
        "algorithm": (
            "pixel_random_diffusion_local_inverse" if diffusion_steps > 0
            else "pixel_random_local_inverse"),
        "layout": layout.topology_key,
        "target": target.to_dict(),
        "proposers": proposers,
        "generative_note": generative_note,
        "judge": "core/mapes.py 闭式内核（占用→Z_L(P)→Schur 补→S）",
        "best": top_k[0] if top_k else None,
        "top_k": top_k,
        "n_random": n_random,
        "n_evaluated": len(cache),
        "n_cache_hits": hits["n"],
        "random_phase": {"best_error_db": random_phase_best_err},
        "diffusion_phase": diffusion_phase,
        "local_phase": {
            "steps": steps,
            "start_error_db": random_best_err,
            "final_error_db": cur_err,
            "improvement_db": random_best_err - cur_err,
            "stop_reason": stop_reason,
        },
        "elapsed_s": round(time.time() - t0, 2),
    }
