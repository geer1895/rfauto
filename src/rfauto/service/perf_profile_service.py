"""代理面性能画像编排（aurora_p G3 席）。

``scripts/perf_profile.py`` 的 service 面（规则 4 薄壳反写）：对
surrogate_registry 的 5 个代表键（标量族单契约）跑缩小画像档——
fit/predict 墙钟 + ``surrogate_fit_quality`` RMSE（质量单源，铁律 7）
——快照落 ``runs/perf_profile/`` 白名单并与上一份 diff（回归检测）。

与 ``scripts/bench_surrogates.py`` 的关系：bench=全键基线记录工具
（~43s 全矩阵）；本模块=bench 的**缩小画像档**（5 键 ~4s），面形配方
（单峰半周期+观测噪声）与确定性纪律（全链固定 seed、线程钉 1、
同 seed 数值列逐位）同源继承；画像产物独立编号（profile_NNNN），
不混入 bench 基线目录。

红线（任务书 §2）：
- 画像数字=真跑计时+质量单源（铁律 7）；
- diff 红项如实列出（#122：画像是回归检测器不是宣传页）；
- 确定性：同 seed 数值列逐位（墙钟列是计时天然波动——diff 对墙钟
  用宽阈值 >2× 且设 ``WALL_FLOOR_S`` 地板豁免毫秒级计时、对 RMSE 用
  窄门 >25%，口径写死见 ``RMSE_DRIFT_RED``/``WALL_RATIO_RED``/
  ``WALL_FLOOR_S``）；
- 预算封顶：单次画像 ≤``BUDGET_CAP_S``（超限如实标注 budget_ok=False）；
- runs/ 白名单：本模块只在调用方显式给的 ``out_dir`` 落盘（无 cwd
  相对缺省路径——#144 家族免疫），真实落点由驱动钉 runs/perf_profile/。
"""

from __future__ import annotations

import os

# BLAS/OMP 线程钉 1——尽量在 numpy/torch 首次导入前生效（#258 家法：
# 小矩阵多线程反而慢且引入归约序漂移，破坏数值列逐位复现）。模块可能
# 在 numpy 已被宿主导入后才加载——此时环境变量仍约束后续 OpenBLAS 行为，
# torch 侧由 _pin_torch_threads 运行期补钉。
_THREADS_PINNED: dict[str, str] = {}
for _k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
    _THREADS_PINNED[_k] = "1"

import itertools  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

from rfauto.optimization.surrogate import surrogate_registry  # noqa: E402
from rfauto.optimization.surrogate_analysis import (  # noqa: E402
    surrogate_fit_quality,
)
from rfauto.service.envelope import error_envelope, ok_envelope  # noqa: E402

#: 快照 schema 标识。
SCHEMA = "perf_profile/v1"

#: 单次画像墙钟预算封顶（秒；套件实测 ~4s，裕量 ~70×）。
BUDGET_CAP_S = 300.0

#: RMSE 相对漂移红门（|cur−prev|/prev 超过即红项——窄门）。
RMSE_DRIFT_RED = 0.25

#: 墙钟比红门（cur/prev 超过即红项——计时天然波动的宽阈值）。
WALL_RATIO_RED = 2.0

#: 墙钟红门地板（秒）：prev 低于地板=毫秒级计时噪声主导（poly_ridge
#: fit ~2ms 实证：0.002s→0.0022s 即表观 1.1×，注入 0.5×prev 即表观
#: 2×+ 假红）——比门豁免记 note，不进红项。红门只对 prev ≥ 地板的
#: 键生效（svgp/gbdt 等 ≥0.3s 档全部在门内）。
WALL_FLOOR_S = 0.05

#: 快照文件名模式（profile_0001.json 递增编号）。
PROFILE_GLOB = "profile_*.json"
_PROFILE_RE = re.compile(r"^profile_(\d{4,})\.json$")

# ── seed 政策（单一源；模型侧 seed 显式写进各 case config） ────────────────
SEED_TRAIN = 20261103      # 训练采样
SEED_NOISE = 20261108      # 观测噪声（=SEED_TRAIN+5，独立流）
SEED_PROBE = 20261109      # 探针用法预留（本套件未消费；编号占位透明）

# ── 标量族合成真值（bench_surrogates 同款面形：单峰半周期+小噪声—— ───────
#    全周期面会把 GP 系 MLE 推入退化区，面形出处见 bench 模块 docstring）
SCALAR_BD: dict[str, tuple[float, float]] = {
    "x1": (0.0, 1.0), "x2": (2.0, 6.0), "x3": (-1.0, 1.0)}
SCALAR_NOISE_SD = 0.02
_N_TEST_SIDE = 6  # 6^3=216 点确定性测试 lattice


def _scalar_truth(u1: float, u2: float, u3: float) -> float:
    """解析真值 f(u)：单峰平滑面（半周期 sin·cos+平方+交叉+线性项）。"""
    return (1.0 + 1.6 * math.sin(math.pi * u1) * math.cos(math.pi * u2)
            + 0.5 * u3 * u3 + 0.6 * u1 * u2 - 0.3 * u3)


def _make_scalar_samples(n: int, seed: int = SEED_TRAIN) -> list[dict[str, Any]]:
    """标量族训练样本（固定 seed 确定性；观测噪声独立流 seed+5）。"""
    rng = np.random.default_rng(seed)
    noise = np.random.default_rng(seed + 5)
    out: list[dict[str, Any]] = []
    for _ in range(n):
        r = rng.random(3)
        u = {"x1": float(r[0]), "x2": float(r[1]), "x3": float(r[2])}
        m1 = _scalar_truth(u["x1"], u["x2"], u["x3"])
        eps = float(noise.normal(0.0, SCALAR_NOISE_SD))
        params = {k: lo + u[k] * (hi - lo) for k, (lo, hi) in SCALAR_BD.items()}
        out.append({"params": params, "metrics": {"cost": m1 + eps}})
    return out


def _test_points() -> list[tuple[dict[str, float], float]]:
    """6×6×6=216 点确定性测试 lattice（params + 解析真值）。"""
    axes = [i / (_N_TEST_SIDE - 1) for i in range(_N_TEST_SIDE)]
    out: list[tuple[dict[str, float], float]] = []
    for combo in itertools.product(axes, repeat=3):
        u = dict(zip(("x1", "x2", "x3"), combo, strict=True))
        params = {k: lo + u[k] * (hi - lo)
                  for k, (lo, hi) in SCALAR_BD.items()}
        out.append((params, _scalar_truth(u["x1"], u["x2"], u["x3"])))
    return out


# ── 套件定义（键×档；config 语义与 bench_surrogates 同源） ──────────────────


@dataclass(frozen=True)
class CaseSpec:
    """画像套件单 case（键×档；数据/seed 固定 → 数值列逐位复现）。"""

    key: str
    tier: str
    config: dict[str, Any]
    n_train: int
    notes: str = ""


def _spec(key: str, tier: str, config: dict[str, Any], n_train: int,
          notes: str = "") -> CaseSpec:
    return CaseSpec(key=key, tier=tier,
                    config={**config, "bounds": dict(SCALAR_BD)},
                    n_train=n_train, notes=notes)


#: 缺省画像套件（5 键；选键依据见 runs/aurora_p/g3/DESIGN.md）。
DEFAULT_SUITE: tuple[CaseSpec, ...] = (
    _spec("poly_ridge", "scalar_n200", {}, 200,
          "numpy 线性最快基线锚"),
    _spec("gbdt", "scalar_n200", {}, 200, "sklearn 树中等档"),
    _spec("nn", "scalar_n200",
          {"augmenter": "polynomial_cross", "epochs": 300, "n_ensemble": 2,
           "hidden": 24, "seed": 42}, 200, "torch 小 MLP"),
    _spec("svgp", "scalar_n2000", {"n_inducing": 64, "seed": 20261101},
          2000, "torch GP 规模档（M=64 诱导点）"),
    _spec("saas_gp", "scalar_n200", {}, 200,
          "gp_det 确定性 ARD GP（MAP 档）"),
)

#: 套件键白名单（可用键过滤面——选键必须落在此集合内）。
SUITE_KEYS: tuple[str, ...] = tuple(s.key for s in DEFAULT_SUITE)


def build_suite(keys: list[str] | tuple[str, ...] | None = None,
                ) -> list[CaseSpec]:
    """按键过滤缺省套件（保持套件定义序）；空键集显式报错（负例契约）。"""
    if keys is not None and len(keys) == 0:
        raise ValueError("keys 空集——画像套件至少需要 1 个键（显式报错"
                         "不静默返回空套件）")
    if keys is None:
        return list(DEFAULT_SUITE)
    unknown = [k for k in keys if k not in SUITE_KEYS]
    if unknown:
        raise ValueError(f"未知画像键: {unknown}（可用键={list(SUITE_KEYS)}）")
    seen: set[str] = set()
    out: list[CaseSpec] = []
    for spec in DEFAULT_SUITE:
        if spec.key in keys and spec.key not in seen:
            out.append(spec)
            seen.add(spec.key)
    missing = [k for k in keys if k not in seen]
    if missing:  # 不可达面（SUITE_KEYS 与 DEFAULT_SUITE 同源）——防御性
        raise ValueError(f"套件定义缺键: {missing}")
    return out


# ── 单 case 执行（真跑计时+质量单源） ───────────────────────────────────────


def _pin_torch_threads() -> int | None:
    """torch 线程运行期钉 1（环境变量的运行期兜底；torch 可选依赖）。"""
    try:
        import torch
        torch.set_num_threads(1)
        return int(torch.get_num_threads())
    except Exception:
        return None


def _git_sha() -> str | None:
    try:
        repo = Path(__file__).resolve().parents[2]
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=repo, capture_output=True, text=True,
                             timeout=10, check=False)
        sha = out.stdout.strip()
        return sha or None
    except Exception:
        return None


def run_case(spec: CaseSpec, test_points: list[tuple[dict[str, float], float]],
             ) -> dict[str, Any]:
    """跑单 case：create → fit 计时 → 测试面逐点 predict 计时 → 质量单源。

    返回行形态（快照 results 列元素）：{key, tier, status, fit_s,
    predict_s, n_train, n_test, rmse, mae, r2, spearman_rho, notes,
    config(记录面), error}。error/skip 如实落账（#122 不静默）。
    """
    row: dict[str, Any] = {
        "key": spec.key, "tier": spec.tier, "status": "error",
        "fit_s": 0.0, "predict_s": 0.0, "n_train": spec.n_train,
        "n_test": len(test_points), "rmse": None, "mae": None, "r2": None,
        "spearman_rho": None, "notes": spec.notes, "error": None,
    }
    try:
        model = surrogate_registry.create(spec.key, config=dict(spec.config))
        samples = _make_scalar_samples(spec.n_train)
        t0 = time.perf_counter()
        model.fit(samples)
        row["fit_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        preds = [model.predict(params) for params, _t in test_points]
        row["predict_s"] = time.perf_counter() - t0

        y_true = [float(t) for _p, t in test_points]
        y_pred = [float(p["cost"]) for p in preds]
        q = surrogate_fit_quality(y_true, y_pred)
        row["rmse"] = q["rms_error"]
        row["mae"] = q["mae"]
        row["r2"] = q["r2"]
        row["spearman_rho"] = q["spearman_rho"]
        row["status"] = "ok"
        row["error"] = None
    except Exception as exc:  # 坏 case 如实落账不中断套件
        row["status"] = "error"
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


# ── diff 口径（纯函数，红绿两态可注入单测） ─────────────────────────────────


def _rmse_verdict(cur: float | None, prev: float | None,
                  ) -> tuple[str, str | None]:
    """RMSE 漂移判定 → (verdict, detail)。verdict ∈ ok|red|note。"""
    if prev is None:
        return "note", "prev_rmse 缺失（新键/prev 非法）"
    if cur is None:
        return "red", f"cur_rmse 缺失（prev={prev!r}）"
    if prev <= 0.0:
        if cur <= 0.0:
            return "ok", None
        return "red", f"prev_rmse={prev!r}≤0 且 cur={cur!r}>0"
    drift = abs(cur - prev) / prev
    if drift > RMSE_DRIFT_RED:
        return "red", f"rmse 相对漂移 {drift:.1%} > {RMSE_DRIFT_RED:.0%}"
    return "ok", f"rmse 漂移 {drift:.1%}"


def _wall_verdict(cur: float, prev: float | None, label: str,
                  ) -> tuple[str, str | None]:
    """墙钟比判定 → (verdict, detail)。

    prev 缺失或低于 ``WALL_FLOOR_S`` 地板 → note 豁免（毫秒级计时
    噪声主导，比门假红源——见 WALL_FLOOR_S 注记）。
    """
    if prev is None:
        return "note", f"{label} prev 缺失"
    if prev < WALL_FLOOR_S:
        return "note", (f"{label} prev={prev:.4f}s < 地板 "
                        f"{WALL_FLOOR_S:.2f}s（毫秒级计时噪声主导，豁免）")
    ratio = cur / prev
    if ratio > WALL_RATIO_RED:
        return "red", (f"{label} {prev:.4f}s→{cur:.4f}s "
                       f"（{ratio:.2f}× > {WALL_RATIO_RED:.1f}×）")
    return "ok", f"{label} {ratio:.2f}×"


def diff_rows(cur_rows: list[dict[str, Any]],
              prev_rows: list[dict[str, Any]] | None,
              ) -> dict[str, Any]:
    """当前套件结果 vs 上一份画像结果 → diff 载荷（纯函数，无 IO）。

    返回 {items: [{key, verdict, red:[...], details:[...], prev/cur 摘要}],
    n_red, summary}。红项如实逐条列出（#122：画像是回归检测器）。
    """
    if prev_rows is None:
        return {"items": [], "n_red": 0,
                "summary": "首跑基线建立态（无上一份画像可比）"}
    prev_by_key = {r["key"]: r for r in prev_rows}
    items: list[dict[str, Any]] = []
    for cur in cur_rows:
        key = cur["key"]
        prev = prev_by_key.get(key)
        red: list[str] = []
        details: list[str | None] = []
        if prev is None:
            items.append({"key": key, "verdict": "note",
                          "red": [], "details": ["prev 无此键（新键）"],
                          "cur_status": cur["status"], "prev_status": None,
                          "cur_rmse": cur.get("rmse"), "prev_rmse": None,
                          "fit_ratio": None, "predict_ratio": None})
            continue
        if prev.get("status") != "ok":
            # prev 非 ok → 恢复面：cur ok=修复如实记 note；仍非 ok=延续
            if cur["status"] == "ok":
                details.append(f"prev_status={prev.get('status')}→恢复 ok"
                               "（修复面记 note 不红）")
            else:
                details.append(f"prev_status={prev.get('status')}、"
                               f"cur_status={cur['status']}（延续非 ok）")
        else:
            v, d = _rmse_verdict(cur.get("rmse"), prev.get("rmse"))
            details.append(d)
            if v == "red":
                red.append(d or "rmse 漂移红")
            if cur["status"] != "ok":
                red.append(f"prev ok → cur {cur['status']}"
                           f"（{cur.get('error') or '无错误详情'}）")
            for label, ck, pk in (("fit", cur.get("fit_s"),
                                   prev.get("fit_s")),
                                  ("predict", cur.get("predict_s"),
                                   prev.get("predict_s"))):
                wv, wd = _wall_verdict(float(ck or 0.0), pk, label)
                details.append(wd)
                if wv == "red":
                    red.append(wd or f"{label} 墙钟红")
        fit_ratio = (None if not prev.get("fit_s")
                     else float(cur.get("fit_s") or 0.0) / prev["fit_s"])
        predict_ratio = (None if not prev.get("predict_s")
                         else float(cur.get("predict_s") or 0.0)
                         / prev["predict_s"])
        items.append({
            "key": key,
            "verdict": "red" if red else "ok",
            "red": red, "details": details,
            "cur_status": cur["status"], "prev_status": prev.get("status"),
            "cur_rmse": cur.get("rmse"), "prev_rmse": prev.get("rmse"),
            "fit_ratio": fit_ratio, "predict_ratio": predict_ratio,
        })
    n_red = sum(1 for it in items if it["verdict"] == "red")
    return {"items": items, "n_red": n_red,
            "summary": (f"{len(items)} 键比对，红项 {n_red} 键"
                        if items else "无可比行")}


# ── 快照发现与产物渲染 ───────────────────────────────────────────────────────


def latest_profile(out_dir: str | Path) -> tuple[int, dict[str, Any]] | None:
    """目录内最新快照 → (编号, doc)；无快照返回 None。"""
    best: tuple[int, Path] | None = None
    for p in Path(out_dir).glob(PROFILE_GLOB):
        m = _PROFILE_RE.match(p.name)
        if m is None:
            continue
        n = int(m.group(1))
        if best is None or n > best[0]:
            best = (n, p)
    if best is None:
        return None
    try:
        doc = json.loads(best[1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"上一份画像读取失败 {best[1]}: {exc}") from exc
    return best[0], doc


def render_diff_markdown(doc: dict[str, Any], diff: dict[str, Any],
                         ) -> str:
    """快照 doc + diff 载荷 → md 报告（含口径与接线候选尾注）。"""
    head = doc.get("diff_against")
    lines = [
        f"# 代理面性能画像 diff（profile {doc.get('profile_id')}）",
        "",
        f"- 工具：scripts/perf_profile.py（schema {SCHEMA}；回归检测器，"
        "不是门）",
        f"- 时间：{doc.get('created_utc')}；git: "
        f"{(doc.get('env') or {}).get('git_sha')}",
        f"- 对比对象：{head if head else '无（首跑基线建立态）'}",
        "- 口径：RMSE 相对漂移 >25% = 红项（窄门）；fit/predict 墙钟比 "
        ">2.0× = 红项（宽阈值，prev<0.05s 地板豁免——毫秒级计时噪声"
        "主导）；同 seed 数值列逐位（墙钟列豁免）；质量单源 "
        "surrogate_fit_quality。",
        "",
        "| 键 | verdict | rmse prev→cur | fit prev→cur | predict prev→cur"
        " | 红项 |",
        "|---|---|---|---|---|---|",
    ]
    prev_rows_by_key = {}
    if head:
        prev_rows_by_key = {r["key"]: r for r in doc.get("prev_results", [])}
    for it in diff["items"]:
        key = it["key"]
        prev = prev_rows_by_key.get(key, {})
        cur = next((r for r in doc["results"] if r["key"] == key), {})
        rms = f"{it.get('prev_rmse')!r}→{it.get('cur_rmse')!r}"
        fits = f"{prev.get('fit_s', 0.0):.4f}s→{cur.get('fit_s', 0.0):.4f}s"
        preds = (f"{prev.get('predict_s', 0.0):.4f}s"
                 f"→{cur.get('predict_s', 0.0):.4f}s")
        reds = "；".join(it["red"]) if it["red"] else "-"
        lines.append(f"| {key} | {it['verdict']} | {rms} | {fits} "
                     f"| {preds} | {reds} |")
    lines += [
        "",
        "## 摘要",
        "",
        f"- {diff['summary']}",
        f"- budget_ok={doc.get('budget_ok')}（cap {BUDGET_CAP_S:.0f}s；"
        f"wall {doc.get('wall_s', 0.0):.1f}s）",
        "",
        "## 尾注（接线候选建议，本席未接线）",
        "",
        "- 画像红项可作 merge_preflight 可选快速段（~5s 级）或 gate_daily"
        " 日次档；接线前需多份快照定墙钟噪声底（2× 阈值首轮实证校准）。",
        "- 本报告为回归检测产物：红项如实列出（#122），修复后重跑画像"
        "即绿。",
    ]
    return "\n".join(lines) + "\n"


# ── 画像编排（信封进出） ─────────────────────────────────────────────────────


def run_profile(out_dir: str | Path,
                keys: list[str] | tuple[str, ...] | None = None,
                ) -> dict[str, Any]:
    """跑画像套件 → 快照+diff 落 ``out_dir`` → 信封。

    首跑（目录无快照）=基线建立态：快照落盘、diff 记基线、无红项判定。
    out_dir 由调用方显式给定（无 cwd 相对缺省——#144 家族免疫）。
    """
    try:
        suite = build_suite(keys)
    except ValueError as exc:
        return error_envelope([str(exc)], schema=SCHEMA,
                              stage="build_suite")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    prev = latest_profile(out)
    prev_id = None
    prev_rows: list[dict[str, Any]] | None = None
    if prev is not None:
        prev_id = prev[0]
        prev_rows = list(prev[1].get("results") or [])

    torch_threads = _pin_torch_threads()
    test_points = _test_points()

    t0 = time.perf_counter()
    rows = [run_case(spec, test_points) for spec in suite]
    wall_s = time.perf_counter() - t0
    budget_ok = wall_s <= BUDGET_CAP_S

    diff = diff_rows(rows, prev_rows)
    next_n = (prev_id + 1) if prev_id is not None else 1
    profile_id = f"profile_{next_n:04d}"

    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "profile_id": profile_id,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "diff_against": (f"profile_{prev_id:04d}"
                         if prev_id is not None else None),
        "prev_results": prev_rows if prev_rows is not None else [],
        "env": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "torch_num_threads": torch_threads,
            "threads_pinned": dict(_THREADS_PINNED),
            "git_sha": _git_sha(),
        },
        "seed_policy": {"train": SEED_TRAIN, "noise": SEED_NOISE,
                        "probe": SEED_PROBE,
                        "model_side": "显式在各 case config"},
        "diff_thresholds": {"rmse_drift_red": RMSE_DRIFT_RED,
                            "wall_ratio_red": WALL_RATIO_RED},
        "budget_cap_s": BUDGET_CAP_S,
        "wall_s": wall_s,
        "budget_ok": budget_ok,
        "n_keys": len(rows),
        "n_ok": sum(1 for r in rows if r["status"] == "ok"),
        "n_error": sum(1 for r in rows if r["status"] == "error"),
        "results": rows,
    }

    json_path = out / f"{profile_id}.json"
    json_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    md_path = out / f"{profile_id}_diff.md"
    md_path.write_text(render_diff_markdown(doc, diff), encoding="utf-8")

    return ok_envelope(
        schema=SCHEMA,
        profile_id=profile_id,
        profile_path=str(json_path),
        diff_path=str(md_path),
        diff_against=doc["diff_against"],
        wall_s=wall_s,
        budget_ok=budget_ok,
        n_keys=len(rows),
        n_ok=doc["n_ok"],
        n_error=doc["n_error"],
        n_red=diff["n_red"],
        red_items=[{"key": it["key"], "red": it["red"]}
                   for it in diff["items"] if it["verdict"] == "red"],
        first_run=prev_id is None,
        summary=diff["summary"],
    )
