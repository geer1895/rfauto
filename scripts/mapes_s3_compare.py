r"""A8 MAPES stage-3：像素滤波器闭式 S vs openEMS 全波对照 + 筛选档达标门 + 环 A/B。

链路（stage-3，承接 stage-2 followUps ③⑥）：
1. **新增滤波器图案**（`patterns`）：阶梯金属桥链 route_full / route_broken /
   route_half——像素桥链 = 串联桥（L）+ 贴片接地（并联对地）的梯形像素滤波
   结构，直通 / 中断 / 半程三档给排序面；直接全波每图案 2 激励（渲染器与
   断点缓存复用 stage-2 脚本，进程隔离 #208 同源）。
2. **对照+达标门**（`compare`）：Z_ALL（runs/mapes_s2，raw 与 (Z+Zᵀ)/2 对称化
   双消费口径，stage-2 followUp ⑥）Schur 闭式 vs openEMS 直接全波（基准），
   逐案矩阵级 max|ΔS| + 指标级（s11_db_min / |S21|@fc 线性）误差 +
   Spearman ρ 排序保真 → 预声明门（GATE_*，写死于本文件常量，#190 精神：
   先定判读带与指标再给诚实判定）→ report.json。
3. **环 A/B**（`ab`）：同一 evaluate_fn（openEMS 直接全波真跑）+
   同一环参数，surrogate_kind="mapes_pixel_analytic"（解析代理档）vs
   "poly_ridge"（环默认数据驱动档），如实记录不强求胜出 → ab_loop.json。

用法（工作区根目录）：
    .venv/Scripts/python.exe scripts/mapes_s3_compare.py patterns
    .venv/Scripts/python.exe scripts/mapes_s3_compare.py compare
    .venv/Scripts/python.exe scripts/mapes_s3_compare.py ab
    # stage-4 质量版（runs/mapes_s4）复测与 α 校准：
    .venv/Scripts/python.exe scripts/mapes_s3_compare.py patterns --out-dir runs/mapes_s4
    .venv/Scripts/python.exe scripts/mapes_s3_compare.py compare --z-all runs/mapes_s4/z_all.npz \
        --s2-dir runs/mapes_s4 --patterns-dir runs/mapes_s4/patterns --out-dir runs/mapes_s4/s3
    .venv/Scripts/python.exe scripts/mapes_s3_compare.py calibrate --z-all runs/mapes_s4/z_all.npz \
        --s2-dir runs/mapes_s4 --patterns-dir runs/mapes_s4/patterns --out-dir runs/mapes_s4/s3
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.mapes import (
    VIA_GROUND,
    MapesModel,
    PixelLayout,
    occupancy_to_load,
)
from rfauto.core.objectives import Objective

REPO = Path(__file__).resolve().parents[1]
S2_DIR = REPO / "runs" / "mapes_s2"
S3_DIR = REPO / "runs" / "mapes_s3"
STAGE2_SCRIPT = REPO / "scripts" / "mapes_s2_zall.py"
Z0 = 50.0

#: 阶梯路由贴片（io1 在 (0,0)、io2 在 (5,5) 的角贴片）：h/v 桥链
#: (0,0)-(0,1)-(1,1)-(1,2)-...-(5,5)，像素在场=中心接地（梯形并联臂）。
ROUTE_PATCHES: tuple[tuple[int, int], ...] = (
    (0, 0), (0, 1), (1, 1), (1, 2), (2, 2),
    (2, 3), (3, 3), (3, 4), (4, 4), (4, 5), (5, 5),
)

# ── 预声明达标门（筛选档；全波=基准。先于任何 stage-3 全波测量写死，#190） ──
#: G1 匹配深度：逐案 |Δs11_db_min| ≤ 2.0 dB（筛选级回损精度）
GATE_S11_DB_MIN_MAX_ABS_DELTA = 2.0
#: G2 传输@fc：逐案 ||S21|@fc 闭式 − 全波|（线性）≤ 0.05（≈ −26dB 底）
GATE_S21_LIN_FC_MAX_ABS_DELTA = 0.05
#: G3 排序保真（#190）：cost = −|S21|@fc 的闭式 vs 全波 Spearman ρ ≥ 0.80
GATE_MIN_RANK_RHO = 0.80
#: G3 生效最低案数（低于此数 ρ 无意义 → 门按 FAIL 处理并如实标注）
GATE_MIN_CASES = 6


def build_layout() -> PixelLayout:
    """stage-2 固定拓扑（与 runs/mapes_s2/z_all.npz 同布局，不得改）。"""
    return PixelLayout(6, 6, 1, 2, ((0, 5, VIA_GROUND), (5, 0, VIA_GROUND)))


def stage3_patterns() -> dict[str, np.ndarray]:
    """stage-3 新增滤波器图案（桥链三档；对角槽/过孔槽不启用，同 stage-2）。"""
    full = np.zeros((6, 6), dtype=bool)
    for r, c in ROUTE_PATCHES:
        full[r, c] = True
    broken = full.copy()
    broken[2, 2] = False  # 链在中段断开（两侧桥自动失效：AND 语义）
    half = np.zeros((6, 6), dtype=bool)
    for r, c in ROUTE_PATCHES[:5]:  # 半程死通到 (2,2)，不达 io2
        half[r, c] = True
    return {"route_full": full, "route_broken": broken, "route_half": half}


def stage2_patterns() -> dict[str, np.ndarray]:
    """stage-2 四图案（定义与 scripts/mapes_s2_zall.py 逐字节一致）。"""
    idx = np.arange(6)
    single = np.zeros((6, 6), dtype=bool)
    single[2, 3] = True
    row2 = np.zeros((6, 6), dtype=bool)
    row2[2, :] = True
    checker = np.add.outer(idx, idx) % 2 == 0
    return {
        "all_empty": np.zeros((6, 6), dtype=bool),
        "single_2_3": single,
        "row2": row2,
        "checker": checker,
    }


def _stage2_module():
    spec = importlib.util.spec_from_file_location("mapes_s2_zall", STAGE2_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# 直接全波 S 读取 / 指标（与 MapesModel.predict 同键同式）
# --------------------------------------------------------------------------- #

def load_direct_s(case_dir: Path, n_freq: int) -> np.ndarray:
    """读图案直接全波两激励轮 sparams.csv → (n_freq, 2, 2) 复 S。"""
    s = np.zeros((n_freq, 2, 2), dtype=complex)
    for exc in (1, 2):
        data = np.loadtxt(str(case_dir / f"p{exc}" / "sparams.csv"),
                          delimiter=",", skiprows=1, ndmin=2)
        if data.shape[0] != n_freq:
            raise ValueError(f"{case_dir}/p{exc} 频点数 {data.shape[0]} != {n_freq}")
        s[:, 0, exc - 1] = data[:, 1] + 1j * data[:, 2]
        s[:, 1, exc - 1] = data[:, 3] + 1j * data[:, 4]
    return s


def metrics_from_s(s: np.ndarray) -> dict[str, float]:
    """(n,2,2) 复 S → MapesModel.predict 同键指标（公式逐行同 core/mapes.py:959）。

    键集合与 :meth:`MapesModel.predict` 完全一致——真跑 evaluate_fn 与解析
    代理产出同构 metrics，WP3.2 环与 SpecEvaluator 无差别消费。
    """
    sm = np.asarray(s, dtype=complex)
    if sm.ndim != 3 or sm.shape[1:] != (2, 2):
        raise ValueError(f"期望 (n,2,2) 复 S，实得 {sm.shape}")
    db = 20.0 * np.log10(np.maximum(np.abs(sm), 1.0e-30))
    center = sm.shape[0] // 2
    metrics: dict[str, float] = {}
    for i in range(2):
        for j in range(2):
            metrics[f"s{i + 1}{j + 1}_db_at_fc"] = float(db[center, i, j])
    metrics["s11_db_min"] = float(np.min(db[:, 0, 0]))
    metrics["s21_db_at_fc"] = float(db[center, 1, 0])
    metrics["s21_db_min"] = float(np.min(db[:, 1, 0]))
    metrics["passive_margin"] = float(
        1.0 - np.max(np.linalg.norm(sm, ord=2, axis=(-2, -1))))
    metrics["reciprocity_err"] = float(np.max(np.abs(
        sm - np.swapaxes(sm, -1, -2))))
    return metrics


def s21_lin_at_fc(s: np.ndarray) -> float:
    """|S21|@中心频点（线性）——深截止 dB 误差失真时的判读量（#195 同源）。"""
    return float(np.abs(np.asarray(s)[np.asarray(s).shape[0] // 2, 1, 0]))


# --------------------------------------------------------------------------- #
# patterns：stage-3 图案直接全波（渲染/断点缓存复用 stage-2 脚本）
# --------------------------------------------------------------------------- #

def cmd_patterns(args: argparse.Namespace) -> int:
    mod = _stage2_module()
    layout = build_layout()
    geom = mod.build_geom(layout)
    out_dir = Path(args.out_dir) if args.out_dir else S3_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    only = set(args.patterns.split(",")) if args.patterns else None
    for name, pattern in stage3_patterns().items():
        if only is not None and name not in only:
            continue
        loads = occupancy_to_load(pattern, layout, np.zeros(2, dtype=int))
        short_numbers = tuple(
            int(i) + 3 for i in np.flatnonzero(np.isfinite(loads)))
        n_pix = int(layout.slot_occupancy(
            pattern, np.zeros(2, dtype=int)).sum())
        print(f"[patterns] {name}: short_slots={len(short_numbers)}", flush=True)
        for exc in (1, 2):
            script = mod.render_round_script(
                geom, excite_port=exc, virtual_ports=False,
                short_numbers=short_numbers)
            work = out_dir / "patterns" / name / f"p{exc}"
            try:
                _fh, _cols, elapsed, resumed = mod._run_round(
                    work, script, 2, resume=not args.fresh)
            except mod.subprocess.TimeoutExpired:
                print(f"[patterns] {name} p{exc} 超时，如实终止", flush=True)
                return 2
            print(f"[patterns] {name} p{exc} done elapsed={elapsed:.1f}s "
                  f"resumed={resumed}", flush=True)
        print(f"[patterns] {name}: n_short={n_pix} 落盘 "
              f"{out_dir / 'patterns' / name}", flush=True)
    return 0


# --------------------------------------------------------------------------- #
# compare：闭式 vs 全波 + 预声明达标门
# --------------------------------------------------------------------------- #

def evaluate_gate(
    cases: dict[str, dict[str, Any]],
    *,
    rank_rho: float,
) -> dict[str, Any]:
    """预声明达标门（G1/G2/G3，阈值=本模块常量，先于 stage-3 测量写死）。

    - G1：逐案 |Δs11_db_min| ≤ 2.0 dB（筛选级回损精度）；
    - G2：逐案 ||S21|@fc| 线性误差 ≤ 0.05（深截止 dB 误差失真，#195 同源）；
    - G3：cost=−|S21|@fc 的闭式 vs 全波 Spearman ρ ≥ 0.80 且案数 ≥ 6（#190）。
    """
    n_cases = len(cases)
    worst_s11 = max(abs(v["delta_s11_db_min_db"]) for v in cases.values())
    worst_s21 = max(abs(v["delta_s21_lin_at_fc"]) for v in cases.values())
    gate: dict[str, Any] = {
        "n_cases": n_cases,
        "g1_s11_db_min_worst_abs_delta_db": worst_s11,
        "g1_pass": bool(worst_s11 <= GATE_S11_DB_MIN_MAX_ABS_DELTA),
        "g2_s21_lin_fc_worst_abs_delta": worst_s21,
        "g2_pass": bool(worst_s21 <= GATE_S21_LIN_FC_MAX_ABS_DELTA),
        "g3_rank_rho": float(rank_rho),
        "g3_pass": bool(
            n_cases >= GATE_MIN_CASES and np.isfinite(rank_rho)
            and rank_rho >= GATE_MIN_RANK_RHO),
    }
    gate["pass"] = bool(gate["g1_pass"] and gate["g2_pass"] and gate["g3_pass"])
    return gate


def _case_direct_dir(
    name: str,
    *,
    s2_dir: Path = S2_DIR,
    s3_dir: Path = S3_DIR,
    patterns_dir: Path | None = None,
) -> Path:
    """案的直接全波目录。

    缺省口径：stage-2 四案在 ``<s2_dir>/patterns``、stage-3 三案在
    ``<s3_dir>/patterns``；给了 ``patterns_dir`` 则 7 案同根（质量版复测：
    runs/mapes_s4/patterns 同时装 s2 四案与 s3 三案）。
    """
    if patterns_dir is not None:
        return patterns_dir / name
    if name in stage2_patterns():
        return s2_dir / "patterns" / name
    return s3_dir / "patterns" / name


def cmd_compare(args: argparse.Namespace) -> int:
    layout = build_layout()
    s2_dir = Path(args.s2_dir) if args.s2_dir else S2_DIR
    out_dir = Path(args.out_dir) if args.out_dir else S3_DIR
    patterns_dir = Path(args.patterns_dir) if args.patterns_dir else None
    npz = Path(args.z_all) if args.z_all else s2_dir / "z_all.npz"
    if not npz.exists():
        print(f"[compare] 缺 {npz}：先完成 stage-2 rotate", flush=True)
        return 2
    with np.load(npz) as data:
        freq_hz = data["freq_hz"]
        z_raw = data["z_all"]
    z_sym = 0.5 * (z_raw + np.swapaxes(z_raw, -1, -2))
    variants = {
        "raw": MapesModel(layout, z_raw, freq_hz, reference_impedance=Z0),
        "sym": MapesModel(layout, z_sym, freq_hz, reference_impedance=Z0),
    }
    vias = np.zeros(len(layout.via_slots), dtype=int)
    patterns = {**stage2_patterns(), **stage3_patterns()}

    report: dict[str, Any] = {
        "stage": "stage-3 closed vs full-wave (screening gate)",
        "fullwave_baseline": "openEMS direct pattern runs (stage-2 + stage-3)",
        "z_all_source": str(npz),
        "patterns_dir": (str(patterns_dir) if patterns_dir is not None
                         else f"{s2_dir / 'patterns'} (s2 cases) + "
                              f"{out_dir / 'patterns'} (s3 cases)"),
        "gate_pre_declared": {
            "g1_s11_db_min_max_abs_delta_db": GATE_S11_DB_MIN_MAX_ABS_DELTA,
            "g2_s21_lin_fc_max_abs_delta": GATE_S21_LIN_FC_MAX_ABS_DELTA,
            "g3_min_rank_rho": GATE_MIN_RANK_RHO,
            "g3_cost": "-|S21|@fc (linear), Spearman over all cases",
            "g3_min_cases": GATE_MIN_CASES,
        },
        "variants": {},
    }
    for tag, model in variants.items():
        cases: dict[str, Any] = {}
        rho_closed: list[float] = []
        rho_direct: list[float] = []
        for name, pattern in patterns.items():
            params = layout.flatten(pattern, vias)
            closed = model.evaluate(params).s_external
            s_direct = load_direct_s(
                _case_direct_dir(name, s2_dir=s2_dir, s3_dir=out_dir,
                                 patterns_dir=patterns_dir),
                len(freq_hz))
            mc = metrics_from_s(closed)
            md = metrics_from_s(s_direct)
            delta = np.abs(closed - s_direct)
            lin_c, lin_d = s21_lin_at_fc(closed), s21_lin_at_fc(s_direct)
            cases[name] = {
                "n_short_slots": int(
                    layout.slot_occupancy(pattern, vias).sum()),
                "max_abs_delta_s": float(np.max(delta)),
                "per_entry_max_abs_delta_s": [
                    [float(np.max(delta[:, i, j])) for j in range(2)]
                    for i in range(2)],
                "closed": mc,
                "direct": md,
                "closed_s21_lin_at_fc": lin_c,
                "direct_s21_lin_at_fc": lin_d,
                "delta_s11_db_min_db": mc["s11_db_min"] - md["s11_db_min"],
                "delta_s21_lin_at_fc": lin_c - lin_d,
            }
            rho_closed.append(-lin_c)
            rho_direct.append(-lin_d)
        from scipy.stats import spearmanr  # 延迟导入（仓库惯例：scipy 按需）

        rho = float(spearmanr(rho_closed, rho_direct).statistic)
        gate = evaluate_gate(cases, rank_rho=rho)
        report["variants"][tag] = {"cases": cases, "gate": gate}
        print(f"[compare][{tag}] worst|Δs11_db_min|="
              f"{gate['g1_s11_db_min_worst_abs_delta_db']:.3f}dB "
              f"worst|Δ|S21|@fc|={gate['g2_s21_lin_fc_worst_abs_delta']:.4f} "
              f"ρ={rho:.3f} gate_pass={gate['pass']}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    overall = any(v["gate"]["pass"] for v in report["variants"].values())
    print(f"[compare] report -> {out}  overall_gate_pass={overall}")
    return 0


# --------------------------------------------------------------------------- #
# ab：WP3.2 代理环 A/B（同一真跑 evaluate_fn，解析档 vs poly_ridge）
# --------------------------------------------------------------------------- #

#: A/B 设计空间 = 阶梯路由 11 贴片占位（其余像素恒空、过孔恒开）。
AB_PARAM_PATCHES = ROUTE_PATCHES


def _ab_bounds(layout: PixelLayout) -> dict[str, tuple[float, float]]:
    return {f"occ{r}_{c}": (0.0, 1.0) for r, c in AB_PARAM_PATCHES}


def _snap_pattern(params: dict[str, float], layout: PixelLayout) -> np.ndarray:
    """连续 [0,1] 参数 → 0/1 图案（≥0.5 判 1，确定性、闭式与真跑同规则）。"""
    pattern = np.zeros((layout.n_rows, layout.n_cols), dtype=bool)
    for r, c in AB_PARAM_PATCHES:
        pattern[r, c] = float(params.get(f"occ{r}_{c}", 0.0)) >= 0.5
    return pattern


def cmd_ab(args: argparse.Namespace) -> int:
    from rfauto.optimization.surrogate_loop import run_surrogate_loop  # 延迟导入

    mod = _stage2_module()
    layout = build_layout()
    geom = mod.build_geom(layout)
    S3_DIR.mkdir(parents=True, exist_ok=True)
    bounds = _ab_bounds(layout)
    # 目标：像素加载下压出最深匹配谐振（s11_db_min 越负越好）。op=max_below
    # + value=-100 → cost = max(0, s11_db_min-(-100)) = s11_db_min+100，对谷深
    # 单调（显式 _min 指标名直取谷深语义，#195/#197 口径）。
    objectives = [Objective(metric="s11_db_min",
                            op="max_below", value=-100.0, weight=1.0)]
    n_rounds = [0]

    def evaluate_fn(params: dict[str, float]) -> dict[str, float]:
        """真跑面：图案直接全波（2 激励，断点缓存同 patterns 段）。"""
        pattern = _snap_pattern(params, layout)
        loads = occupancy_to_load(pattern, layout, np.zeros(2, dtype=int))
        short_numbers = tuple(
            int(i) + 3 for i in np.flatnonzero(np.isfinite(loads)))
        tag = "-".join(
            f"{r}{c}{'1' if pattern[r, c] else '0'}" for r, c in AB_PARAM_PATCHES)
        work_root = S3_DIR / "ab" / tag
        cols_by_exc: list[list[Any]] = []
        fh: Any = None
        for exc in (1, 2):
            script = mod.render_round_script(
                geom, excite_port=exc, virtual_ports=False,
                short_numbers=short_numbers)
            fh, cols, elapsed, resumed = mod._run_round(
                work_root / f"p{exc}", script, 2, resume=True)
            cols_by_exc.append(cols)
            n_rounds[0] += 0 if resumed else 1
            print(f"[ab] {tag} p{exc} elapsed={elapsed:.1f}s resumed={resumed}",
                  flush=True)
        s = np.zeros((len(fh), 2, 2), dtype=complex)
        for exc, cols in enumerate(cols_by_exc, start=1):
            s[:, 0, exc - 1] = cols[0]
            s[:, 1, exc - 1] = cols[1]
        return metrics_from_s(s)

    results: dict[str, Any] = {
        "stage": "stage-3 WP3.2 loop A/B (truth = openEMS direct full-wave)",
        "objective": "minimize cost = s11_db_min + 100（谷深最大化为唯一目标，"
                     "非退化景观：全波实测案值 −1.05~−4.80dB）",
        "space": "11 阶梯路由像素占位 [0,1]（≥0.5 判 1，闭式/真跑同规则）",
        "loop_args": {
            "n_init": args.n_init, "top_k": args.top_k,
            "max_real": args.max_real, "virtual_trials": args.virtual_trials,
            "seed": args.seed,
        },
        "arms": {},
    }
    for arm_kind in ("mapes_pixel_analytic", "poly_ridge"):
        surrogate_config: dict[str, Any] = {}
        if arm_kind == "mapes_pixel_analytic":
            surrogate_config = {
                "z_all_npz": str(S2_DIR / "z_all.npz"),
                "layout": {
                    "n_rows": 6, "n_cols": 6, "n_layers": 1, "n_io_ports": 2,
                    "via_slots": [[0, 5, VIA_GROUND], [5, 0, VIA_GROUND]],
                },
                "reference_impedance": Z0,
                "symmetrize": False,
            }
        t0 = time.time()
        res = run_surrogate_loop(
            bounds, objectives, evaluate_fn,
            n_init=args.n_init, top_k=args.top_k, max_real=args.max_real,
            virtual_trials=args.virtual_trials, seed=args.seed,
            surrogate_kind=arm_kind, surrogate_config=surrogate_config)
        best = res.get("best") or {}
        results["arms"][arm_kind] = {
            "ok": res["ok"],
            "stop_reason": res["stop_reason"],
            "n_real_used": res["n_real_used"],
            "n_failures": res["n_failures"],
            "best_cost": best.get("cost"),
            "best_params": best.get("params"),
            "real_cost_trace": res["real_cost_trace"],
            "rounds": res["rounds"],
            "elapsed_s": round(time.time() - t0, 1),
            "fresh_openems_rounds": n_rounds[0],
        }
        n_rounds[0] = 0
        print(f"[ab] arm={arm_kind} best_cost={best.get('cost')} "
              f"n_real={res['n_real_used']} stop={res['stop_reason']}",
              flush=True)
    out = S3_DIR / "ab_loop.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[ab] -> {out}")
    return 0


# --------------------------------------------------------------------------- #
# calibrate：α 频率缩放确定性校准（直接全波 7 案基准 + 留一验证，#190 范式）
# --------------------------------------------------------------------------- #

def _direct_cases(
    layout: PixelLayout,
    freq_hz: np.ndarray,
    *,
    s2_dir: Path,
    s3_dir: Path,
    patterns_dir: Path | None,
) -> list[tuple[dict[str, Any], dict[str, float]]]:
    """7 案 (params_flat, 直接全波 metrics) —— fit_alpha_scaling 的输入合同。"""
    vias = np.zeros(len(layout.via_slots), dtype=int)
    cases: list[tuple[dict[str, Any], dict[str, float]]] = []
    for name, pattern in {**stage2_patterns(), **stage3_patterns()}.items():
        s_direct = load_direct_s(
            _case_direct_dir(name, s2_dir=s2_dir, s3_dir=s3_dir,
                             patterns_dir=patterns_dir), len(freq_hz))
        cases.append((layout.flatten(pattern, vias), metrics_from_s(s_direct)))
    return cases


def cmd_calibrate(args: argparse.Namespace) -> int:
    from rfauto.core.mapes import fit_alpha_scaling  # 延迟导入：子命令级依赖清晰

    mod = _stage2_module()
    layout = build_layout()
    geom = mod.build_geom(layout)
    s2_dir = Path(args.s2_dir) if args.s2_dir else S2_DIR
    out_dir = Path(args.out_dir) if args.out_dir else S3_DIR
    patterns_dir = Path(args.patterns_dir) if args.patterns_dir else None
    npz = Path(args.z_all) if args.z_all else s2_dir / "z_all.npz"
    if not npz.exists():
        print(f"[calibrate] 缺 {npz}", flush=True)
        return 2
    with np.load(npz) as data:
        freq_hz = data["freq_hz"]
        z_raw = data["z_all"]
    z_sym = 0.5 * (z_raw + np.swapaxes(z_raw, -1, -2))
    cases = _direct_cases(layout, freq_hz, s2_dir=s2_dir, s3_dir=out_dir,
                          patterns_dir=patterns_dir)
    # β 等效值：本实现的提取几何超参 = 缝隙口横向半宽占比 2·hy/a（几何实测，非常数）
    gap_port = next(p for p in geom.ports if p.kind == "lumped_gap"
                    and abs(p.stop[0] - p.start[0]) > abs(p.stop[1] - p.start[1]))
    beta_equiv = float((gap_port.stop[1] - gap_port.start[1]) / geom.cell_m)
    report: dict[str, Any] = {
        "stage": "stage-4 alpha frequency-scaling calibration (#190 范式)",
        "z_all_source": str(npz),
        "n_cases": len(cases),
        "case_names": list({**stage2_patterns(), **stage3_patterns()}.keys()),
        "alpha_provenance": (
            "openEMS-internal：基准为同引擎直接全波 7 案；HFSS 仲裁背书未做"
            "（#190），α 数值仅作 openEMS 同引擎口径，不得当作跨引擎常数"),
        "beta_equivalent": {
            "value": beta_equiv,
            "definition": "缝隙口横向跨度 / 像素边长 = 2·port_half_y/cell（几何实测）",
            "sensitivity_smoke": "deferred：每档 β 需整套 150 轮重提取（~37min@14.6s/轮）",
        },
        "variants": {},
    }
    for tag, z in (("raw", z_raw), ("sym", z_sym)):
        rep = fit_alpha_scaling(layout, z, freq_hz, cases, reference_impedance=Z0)
        report["variants"][tag] = rep
        print(f"[calibrate][{tag}] alpha_best={rep['alpha_best']:.4f} "
              f"SSE {rep['sse_at_alpha_1']:.4f}→{rep['sse_at_alpha_best']:.4f} "
              f"(x{rep['improvement_ratio']:.2f})  LOO α∈[{rep['loo_alpha_min']:.4f},"
              f"{rep['loo_alpha_max']:.4f}] held-out norm err "
              f"{rep['loo_mean_norm_err_at_1']:.4f}→{rep['loo_mean_norm_err_at_fit']:.4f}",
              flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "alpha_calibration.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[calibrate] β_equiv={beta_equiv:.3f}  report -> {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    p_pat = sub.add_parser("patterns")
    p_pat.add_argument("--patterns", default=None, help="逗号分隔子集")
    p_pat.add_argument("--fresh", action="store_true")
    p_pat.add_argument("--out-dir", default=None,
                       help="图案产物根目录（缺省 runs/mapes_s3；质量版复测指向 runs/mapes_s4）")
    p_cmp = sub.add_parser("compare")
    p_cmp.add_argument("--z-all", default=None,
                       help="Z_ALL npz 路径（缺省 <s2-dir>/z_all.npz）")
    p_cmp.add_argument("--s2-dir", default=None,
                       help="stage-2 数据目录（缺省 runs/mapes_s2）")
    p_cmp.add_argument("--patterns-dir", default=None,
                       help="7 案直接全波根目录（缺省 <s2-dir>/patterns）")
    p_cmp.add_argument("--out-dir", default=None,
                       help="report.json 落盘目录（缺省 runs/mapes_s3）")
    p_cal = sub.add_parser("calibrate")
    for flag, help_ in (("--z-all", "Z_ALL npz 路径（缺省 <s2-dir>/z_all.npz）"),
                        ("--s2-dir", "stage-2 数据目录（缺省 runs/mapes_s2）"),
                        ("--patterns-dir", "7 案直接全波根目录"),
                        ("--out-dir", "alpha_calibration.json 落盘目录（缺省 runs/mapes_s3）")):
        p_cal.add_argument(flag, default=None, help=help_)
    p_ab = sub.add_parser("ab")
    p_ab.add_argument("--n-init", type=int, default=6)
    p_ab.add_argument("--top-k", type=int, default=2)
    p_ab.add_argument("--max-real", type=int, default=12)
    p_ab.add_argument("--virtual-trials", type=int, default=600)
    p_ab.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.stage == "patterns":
        return cmd_patterns(args)
    if args.stage == "compare":
        return cmd_compare(args)
    if args.stage == "calibrate":
        return cmd_calibrate(args)
    return cmd_ab(args)


if __name__ == "__main__":
    raise SystemExit(main())
