"""数据工厂 MFK：OE 低保真面 KOH 离散差异修正 + MFK 融合复判（纯离线）。

判据（预声明，零改动）：runs/df5_mfk_lowfi_fix/criteria.md。
背景（B2 终态 runs/factory_mf_anchors/mfk_verdict_full8.json）：held-out
|ΔΓ|max 0.09788>0.04 / εeff 1.6524%>1% / 增值门 False；w=1.5119 处 HFSS
带内 |Γ| 递增（0.055→0.107）而 OE 近平（≈0.141）——两引擎匹配谷位置横移
（OE w*≈0.918 vs HFSS w*≈1.113）的结构性分歧。

修正模型（KOH 简化式，criteria §3）：6 train 锚处 δ=HFSS−OE 残差逐头拟合
1-D squared-exp GP（独立 numpy 实现 #118，不经 SMT）：
  S11 头在线性 |Γ| 消费口径（#371：深谷 dB 表示病象——dB 残差在
  w=0.9178/1.113 达 +43/−27dB，线性同点 |δ|≤0.081 有界平滑）；
  S21 头 dB 空间（带内平坦无深谷）；εeff 头绝对差。
  超参 (l,σf) L-BFGS-B 极大对数边际似然，log 边界（criteria §3），
  确定性单起点；修正面在 train 锚处精确等于 HFSS（插值语义）。
复判：修正低保真 ×8 锚 → 同一 smt_mfk 融合链（复用
factory_m2_mfk_rejudge._fit_and_judge，只读复用零改动）→ 三 Gate
（|ΔΓ|≤0.04 / εeff≤1% / S21≤0.5dB）+ 增值门双对照（vs 纯 OE 基线与
vs 修正前 MFK）+ held-out 2 锚判读 + 非仿射差异合成回收钉（≤1e-3，#118）
+ 修正前臂回归钉（对归档 verdict |Δ|≤1e-9，证明唯一变量是低保真修正）
+ 确定性双跑 bit-identical。

用法（cwd=仓库根；venv=.venv\\Scripts\\python.exe）：
  python scripts/factory_mfk_lowfi_fix.py --judge
退出码：overall=PASS → 0，否则 1（FAIL 如实出账，不凑绿，#122）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CRITERIA_PATH = REPO / "runs" / "df5_mfk_lowfi_fix" / "criteria.md"
DATASET_DEFAULT = REPO / "runs" / "datasets" / "datafactory_m1m3_merged_20260920"
ANCHORS_ROOT_DEFAULT = REPO / "runs" / "factory_mf_anchors"
PREFIX_VERDICT_DEFAULT = ANCHORS_ROOT_DEFAULT / "mfk_verdict_full8.json"
OUT_DIR_DEFAULT = REPO / "runs" / "df5_mfk_lowfi_fix"

#: 修正模型超参 log 边界（criteria §3；w 归一化到 [0,1]）
W_DOMAIN = (0.5, 2.0)
L_BOUNDS = (0.02, 2.0)
SIGF_LO = 1e-6
SIGF_HI_FACTOR = 10.0
JITTER_REL = 1e-12  # 相对 σf² 的对角抖动（保插值语义，锚点误差 ~1e-13）
L0 = 0.3
S11_FLOOR_LIN = 1e-6
#: 合成回收钉门（criteria §5：非仿射差异语料 ≤1e-3，#118）
PIN_THRESHOLDS = {"gamma_lin": 1e-3, "eps_eff_rel": 1e-3, "s21_db": 1e-3}
#: 修正前臂回归钉容差（同链同版本应逐位一致；1e-9 相对）
REGRESSION_RTOL = 1e-9
EXACT_W_TOL = 1e-12

Row = dict[str, Any]

__all__ = [
    "DiscrepancyGP1D",
    "correct_low_rows",
    "fit_discrepancies",
    "run_fix",
    "synthetic_nonaffine_rows",
]


# ---------------------------------------------------------------- 复用


def load_scripts() -> tuple[Any, Any]:
    """importlib 只读复用 factory_m2_surrogate / factory_m2_mfk_rejudge。"""
    mods: list[Any] = []
    for name in ("factory_m2_surrogate", "factory_m2_mfk_rejudge"):
        path = REPO / "scripts" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"{name}_lowfi_fix",
                                                      path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mods.append(mod)
    return mods[0], mods[1]


# ---------------------------------------------------------------- 差异 GP


def _norm_w(w: float | np.ndarray) -> float | np.ndarray:
    return (np.asarray(w, dtype=float) - W_DOMAIN[0]) / (
        W_DOMAIN[1] - W_DOMAIN[0])


class DiscrepancyGP1D:
    """1-D squared-exp GP 离散差异项（KOH 简化式；独立 numpy 实现，#118）。

    k(x,x')=σf²·exp(−(x−x')²/(2l²))；超参 (l,σf) 极大对数边际似然，
    log 边界 + 确定性单起点（criteria §3）；对角 JITTER 保插值语义。
    """

    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        self.xn = np.asarray(_norm_w(x), dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.l: float | None = None
        self.sf: float | None = None
        self.nll: float | None = None

    def _kernel(self, a: np.ndarray, b: np.ndarray, ell: float,
                sf: float) -> np.ndarray:
        d = a[:, None] - b[None, :]
        return sf * sf * np.exp(-0.5 * d * d / (ell * ell))

    def _nll_at(self, params: np.ndarray) -> float:
        ell = float(np.exp(params[0]))
        sf = float(np.exp(params[1]))
        k_mat = self._kernel(self.xn, self.xn, ell, sf)
        k_mat[np.diag_indices_from(k_mat)] += JITTER_REL * sf * sf
        sign, logdet = np.linalg.slogdet(k_mat)
        if sign <= 0.0:
            return 1e25
        try:
            alpha = np.linalg.solve(k_mat, self.y)
        except np.linalg.LinAlgError:
            return 1e25
        return float(0.5 * alpha @ self.y + 0.5 * logdet
                     + 0.5 * self.y.size * np.log(2.0 * np.pi))

    def fit(self) -> DiscrepancyGP1D:
        sd = float(np.std(self.y))
        sf_hi = max(SIGF_HI_FACTOR * sd, SIGF_LO)
        bounds = [(np.log(L_BOUNDS[0]), np.log(L_BOUNDS[1])),
                  (np.log(SIGF_LO), np.log(sf_hi))]
        x0 = np.array([np.log(L0), np.log(max(sd, SIGF_LO))])
        if sf_hi - SIGF_LO <= 1e-15:
            # 零残差头：δ≡0，超参退化固定（预测恒 0）
            self.l, self.sf, self.nll = L_BOUNDS[0], SIGF_LO, self._nll_at(x0)
            return self
        res = minimize(self._nll_at, x0, method="L-BFGS-B", bounds=bounds)
        self.l = float(np.exp(res.x[0]))
        self.sf = float(np.exp(res.x[1]))
        self.nll = float(res.fun)
        return self

    def predict(self, w: float) -> float:
        assert self.l is not None and self.sf is not None, "先 fit() 再 predict"
        k_mat = self._kernel(self.xn, self.xn, self.l, self.sf)
        k_mat[np.diag_indices_from(k_mat)] += JITTER_REL * self.sf * self.sf
        ks = self._kernel(_norm_w(np.array([float(w)])), self.xn,
                          self.l, self.sf)[0]
        return float(ks @ np.linalg.solve(k_mat, self.y))


# ---------------------------------------------------------------- 残差/修正


def _exact_low_row(low_rows: list[Row], w: float) -> Row:
    hits = [r for r in low_rows
            if abs(float(r["w"]) - float(w)) <= EXACT_W_TOL]
    if not hits:
        raise ValueError(
            f"训练锚 w={w!r} 在低保真数据集中无精确行（嵌套 DoE 前提破坏）"
            "——拒绝最近邻替代（criteria §3）")
    return hits[0]


def fit_discrepancies(low_rows: list[Row], train_rows: list[Row],
                      freqs: np.ndarray,
                      log: Callable[[str], None]) -> dict[str, Any]:
    """6 train 锚处 δ=HFSS−OE 残差逐头拟合差异 GP（criteria §3 空间选型）。"""
    ws = np.array([float(r["w"]) for r in train_rows])
    n_f = len(freqs)
    d11 = np.zeros((len(train_rows), n_f))
    d21 = np.zeros((len(train_rows), n_f))
    de = np.zeros(len(train_rows))
    for i, t in enumerate(train_rows):
        r = _exact_low_row(low_rows, float(t["w"]))
        d11[i] = 10.0 ** (np.asarray(t["s11_db"], float) / 20.0) \
            - 10.0 ** (np.asarray(r["s11_db"], float) / 20.0)
        d21[i] = np.asarray(t["s21_db"], float) \
            - np.asarray(r["s21_db"], float)
        de[i] = float(t["eps_eff"]) - float(r["eps_eff"])
    pack: dict[str, Any] = {"w_train": ws, "d11": d11, "d21": d21, "de": de}
    pack["gp11"] = [DiscrepancyGP1D(ws, d11[:, j]).fit()
                    for j in range(n_f)]
    pack["gp21"] = [DiscrepancyGP1D(ws, d21[:, j]).fit()
                    for j in range(n_f)]
    pack["gpe"] = DiscrepancyGP1D(ws, de).fit()
    hypers = [(gp.l, gp.sf) for gp in pack["gp11"] + pack["gp21"]
              + [pack["gpe"]]]
    ls = np.array([h[0] for h in hypers])
    sfs = np.array([h[1] for h in hypers])
    pack["hyper_summary"] = {
        "l_min": float(ls.min()), "l_med": float(np.median(ls)),
        "l_max": float(ls.max()),
        "sf_max": float(sfs.max()),
        "d11_absmax": float(np.abs(d11).max()),
        "d21_absmax_db": float(np.abs(d21).max()),
        "de_absmax": float(np.abs(de).max()),
    }
    log(f"[lowfix] δGP 拟合：|δ11|max={pack['hyper_summary']['d11_absmax']:.4f}"
        f"（线性口径）|δ21|max={pack['hyper_summary']['d21_absmax_db']:.3f}dB "
        f"|δe|max={pack['hyper_summary']['de_absmax']:.4f}；"
        f"l med={pack['hyper_summary']['l_med']:.3f}")
    return pack


def correct_low_rows(low_rows: list[Row], pack: dict[str, Any],
                     freqs: np.ndarray) -> list[Row]:
    """修正低保真面：s11 线性口径加 δ 后回 dB（地板 1e-6）；s21/εeff 直接加。"""
    assert len(pack["gp11"]) == len(freqs) == len(pack["gp21"]), \
        "δGP 逐频头数与消费栅格不符"
    out: list[Row] = []
    for r in low_rows:
        w = float(r["w"])
        g_lin = 10.0 ** (np.asarray(r["s11_db"], float) / 20.0)
        d11 = np.array([gp.predict(w) for gp in pack["gp11"]])
        g_corr = np.clip(g_lin + d11, 0.0, 1.0)
        s11_db = 20.0 * np.log10(np.maximum(g_corr, S11_FLOOR_LIN))
        d21 = np.array([gp.predict(w) for gp in pack["gp21"]])
        out.append({
            **r,
            "s11_db": s11_db,
            "s21_db": np.asarray(r["s21_db"], float) + d21,
            "eps_eff": float(r["eps_eff"]) + pack["gpe"].predict(w),
            "run_id": f"lowfix::{r.get('run_id')}",
        })
    return out


# ---------------------------------------------------------------- 合成钉


def synthetic_nonaffine_rows(freqs: np.ndarray, w_low_grid: np.ndarray,
                             w_train: list[float], w_held: list[float],
                             m2: Any) -> tuple[list[Row], list[Row], list[Row]]:
    """非仿射差异合成语料（criteria §5；Forrester 仿射 + 正弦离散差异）。

    low  = 解析无耗线族 εeff_l=2.5+0.5w, Z0_l=60+15w
    high = 仿射 + 正弦：εeff_h=1.05·εeff_l+0.05+0.08·sin(π(w−0.5)/1.5)，
           Z0_h=1.15·Z0_l（仿射族 AR1 可精确表示，正弦项逼 δGP 真正工作）
    """

    def _rows(ws: list[float], hi: bool, group: str) -> list[Row]:
        out: list[Row] = []
        for w in ws:
            w = float(w)
            eps_l = 2.5 + 0.5 * w
            z0_l = 60.0 + 15.0 * w
            if hi:
                eps = 1.05 * eps_l + 0.05 + 0.08 * np.sin(
                    np.pi * (w - 0.5) / 1.5)
                z0 = 1.15 * z0_l
            else:
                eps, z0 = eps_l, z0_l
            s11, s21 = m2.line_s_complex(z0, eps, freqs)
            out.append({
                "w": w,
                "s21_db": 20 * np.log10(np.abs(s21) + 1e-30),
                "s11_db": 20 * np.log10(np.abs(s11) + 1e-30),
                "eps_eff": float(eps),
                "run_id": f"syn{'hi' if hi else 'lo'}_w{w:.4f}",
                "point_id": f"syn_{group}_w{w:.4f}",
                "group": group,
            })
        return out

    low = _rows([float(w) for w in w_low_grid], hi=False, group="low")
    train = _rows(w_train, hi=True, group="train")
    held = _rows(w_held, hi=True, group="heldout")
    return low, train, held


def run_pin(rj: Any, m2: Any,
            log: Callable[[str], None]) -> dict[str, Any]:
    """合成回收钉：非仿射差异语料全链（δGP→修正面→MFK→门统计），#118。"""
    freqs = m2.band_freqs(0.05)
    w_train = [0.5, 0.745, 0.9178, 1.113, 1.182, 2.0]
    w_held = [0.9946, 1.5119]
    # 低保真网格必须精确含 train/held 锚 w（嵌套 DoE 前提，同真实数据集）
    w_grid = np.unique(np.round(np.concatenate([
        np.linspace(0.5, 2.0, 40), np.array(w_train), np.array(w_held)]),
        12))
    low, train, held = synthetic_nonaffine_rows(freqs, w_grid, w_train,
                                                w_held, m2)
    pack = fit_discrepancies(low, train, freqs, log)
    corr = correct_low_rows(low, pack, freqs)
    # 插值语义钉：train 锚处修正面必须精确回到 HFSS 真值（1e-9）
    for t in train:
        r = _exact_low_row(corr, float(t["w"]))
        g_err = np.abs(10.0 ** (r["s11_db"] / 20.0)
                       - 10.0 ** (t["s11_db"] / 20.0)).max()
        assert g_err <= 1e-9, f"修正面锚点插值语义破坏（|ΔΓ|={g_err:.2e}）"
        assert abs(float(r["eps_eff"]) - float(t["eps_eff"])) <= 1e-9
    res = rj._fit_and_judge(m2, corr, train, held, freqs, log)
    arm = res["arms"]["smt_mfk"]
    # 增值门基线 = 合成**纯**低保真直接当预测（未修正原始 low 面）——
    # _fit_and_judge 的内部基线跟随传入面（修正面），语义不合，另算
    head_eps = m2.HEAD_EPS
    base_preds, _pairing = rj.pair_baseline(low, held, freqs, head_eps)
    arm_base_raw = rj.arm_stats(base_preds, held, freqs, head_eps)
    pin_value = bool(np.isfinite(arm["gamma_lin"]["max"])
                     and np.isfinite(arm_base_raw["gamma_lin"]["max"])
                     and arm["gamma_lin"]["max"]
                     <= arm_base_raw["gamma_lin"]["max"])
    checks = {
        "gamma_lin": bool(arm["gamma_lin"]["max"] <= PIN_THRESHOLDS["gamma_lin"]),
        "eps_eff_rel": bool(
            arm["eps_eff_rel"]["max"] <= PIN_THRESHOLDS["eps_eff_rel"]),
        "s21_db": bool(arm["s21_db"]["max"] <= PIN_THRESHOLDS["s21_db"]),
    }
    res["pin_thresholds"] = dict(PIN_THRESHOLDS)
    res["interp_semantics"] = "train 锚处修正面==HFSS（|ΔΓ|≤1e-9）已断言"
    res["value_add_pass_vs_raw_low"] = pin_value
    res["baseline_raw_low_gamma_max"] = arm_base_raw["gamma_lin"]["max"]
    res["pass"] = bool(all(checks.values()) and pin_value
                       and arm["n_fit_failures"] == 0)
    res["checks"] = checks
    log(f"[lowfix] 合成钉 pass={res['pass']} "
        f"gamma={arm['gamma_lin']['max']:.2e} "
        f"eps={arm['eps_eff_rel']['max']:.2e} "
        f"s21={arm['s21_db']['max']:.2e}")
    return res


# ---------------------------------------------------------------- 判读


def _canonical(obj: Any) -> str:
    """剔除时变键后的规范化 JSON（确定性比对用）。"""
    if isinstance(obj, dict):
        return json.dumps(
            {k: _canonical(v) for k, v in sorted(obj.items())
             if k not in ("generated_at", "wall_s")},
            ensure_ascii=False, sort_keys=True, indent=1)
    if isinstance(obj, list):
        return json.dumps([_canonical(v) for v in obj],
                          ensure_ascii=False, sort_keys=True)
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _stat_close(a: dict[str, Any], b: dict[str, Any],
                rtol: float) -> list[str]:
    """两臂统计量逐头对比，返回不一致描述列表（空=一致）。"""
    bad: list[str] = []
    for head in ("gamma_lin", "eps_eff_rel", "s21_db"):
        for k in ("max", "mean"):
            va, vb = a[head][k], b[head][k]
            ok = (np.isfinite(va) and np.isfinite(vb)
                  and abs(va - vb) <= rtol * max(abs(va), abs(vb), 1e-30))
            if not ok:
                bad.append(f"{head}.{k}: {va!r} vs {vb!r}")
    return bad


def run_fix(low_rows: list[Row], high_rows: list[Row], freqs: np.ndarray,
            *, prefix_verdict_path: Path | None = None,
            out_dir: Path | None = None,
            log: Callable[[str], None] = print) -> dict[str, Any]:
    """复判主链：合成钉→δGP 修正→四臂判读→双对照→确定性→verdict。"""
    m2, rj = load_scripts()
    out_dir = out_dir or OUT_DIR_DEFAULT
    out_dir = Path(out_dir)
    t0 = time.perf_counter()
    train_rows = [r for r in high_rows if r.get("group") == "train"]
    held_rows = [r for r in high_rows if r.get("group") == "heldout"]
    verdict: dict[str, Any] = {
        "schema": "factory_mfk_lowfi_fix_verdict/1",
        "criteria": str(CRITERIA_PATH),
        "generated_at": datetime.now(UTC).isoformat(),
        "thresholds": dict(rj.GATE_THRESHOLDS),
    }
    if len(train_rows) < 2 or not held_rows:
        verdict.update({"overall": "PENDING_HIGH_FI",
                        "n_train_anchors": len(train_rows),
                        "n_held_anchors": len(held_rows),
                        "note": "锚点不足，如实挂起（先采集锚点）"})
        return verdict

    # 1) 合成回收钉（非仿射差异，先于真实判读，#118）
    log("[lowfix] 合成回收钉（非仿射差异语料，criteria §5）")
    pin = run_pin(rj, m2, log)

    # 2) δGP 修正低保真面
    log(f"[lowfix] δGP 修正：lo={len(low_rows)} train={len(train_rows)} "
        f"held={len(held_rows)}")
    pack = fit_discrepancies(low_rows, train_rows, freqs, log)
    corr_rows = correct_low_rows(low_rows, pack, freqs)

    # 3) 四臂判读（修正 MFK / 纯 OE 基线 / 修正前 MFK / KOH 直接诊断臂）
    # 语义钉：_fit_and_judge 的内部基线臂跟随传入面——传修正面时其内部
    # 基线=修正面直接当预测（KOH 诊断臂），传原 OE 面时内部基线=纯 OE
    # 直接当预测（G4 门基线，与 B2 完全同链）。
    log("[lowfix] 修正 MFK 臂（内部基线=修正面 direct，作 KOH 诊断臂）")
    res_fix = rj._fit_and_judge(m2, corr_rows, train_rows, held_rows, freqs,
                                log)
    log("[lowfix] 修正前 MFK 对照臂（原 OE 面同链；内部基线=纯 OE direct）")
    res_prefix = rj._fit_and_judge(m2, low_rows, train_rows, held_rows, freqs,
                                   log)

    # 4) 回归钉：修正前臂须复现归档 B2 verdict（唯一变量=低保真修正）
    regression: dict[str, Any] = {"prefix_verdict": str(prefix_verdict_path),
                                  "ok": None, "mismatches": []}
    if prefix_verdict_path is not None and Path(prefix_verdict_path).exists():
        archived = json.loads(
            Path(prefix_verdict_path).read_text(encoding="utf-8"))
        arch_arms = archived["judgment"]["arms"]
        for name, got in (("smt_mfk", res_prefix["arms"]["smt_mfk"]),
                          ("baseline_oe_direct",
                           res_prefix["arms"]["baseline_oe_direct"])):
            bad = _stat_close(got, arch_arms[name], REGRESSION_RTOL)
            regression["mismatches"] += [f"{name}.{m}" for m in bad]
        regression["ok"] = not regression["mismatches"]
        log(f"[lowfix] 回归钉（对 B2 归档 verdict）ok={regression['ok']}")
    else:
        # 归档缺失：回归钉无法执行，如实记 skipped（不冒充 PASS 也不硬造）
        regression["ok"] = None
        regression["skipped"] = "prefix_verdict 归档缺失，回归钉跳过"

    # 5) 确定性：同输入第二次全新拟合链，canonical JSON 逐字节一致
    log("[lowfix] 确定性双跑（第二次全新拟合链）")
    pack2 = fit_discrepancies(low_rows, train_rows, freqs,
                              lambda _m: None)
    corr2 = correct_low_rows(low_rows, pack2, freqs)
    res_fix2 = rj._fit_and_judge(m2, corr2, train_rows, held_rows, freqs,
                                 lambda _m: None)
    deterministic = (_canonical(res_fix) == _canonical(res_fix2)
                     and _canonical(pack["hyper_summary"])
                     == _canonical(pack2["hyper_summary"]))
    log(f"[lowfix] 确定性 bit-identical={deterministic}")

    # 6) 门汇总（criteria §4：门零改动 + 双对照）
    mfk = res_fix["arms"]["smt_mfk"]
    arm_koh = res_fix["arms"]["baseline_oe_direct"]  # 修正面 direct（诊断臂）
    base = res_prefix["arms"]["baseline_oe_direct"]  # 纯 OE direct（G4 基线）
    prefix = res_prefix["arms"]["smt_mfk"]
    blocker = mfk["n_fit_failures"] > 0
    value_vs_oe = bool(
        np.isfinite(mfk["gamma_lin"]["max"])
        and np.isfinite(base["gamma_lin"]["max"])
        and mfk["gamma_lin"]["max"] <= base["gamma_lin"]["max"])
    second_control = bool(
        np.isfinite(mfk["gamma_lin"]["max"])
        and np.isfinite(prefix["gamma_lin"]["max"])
        and mfk["gamma_lin"]["max"] <= prefix["gamma_lin"]["max"])
    overall = "PASS" if (
        all(res_fix["gates_pass"].values()) and value_vs_oe
        and second_control and pin["pass"]
        and regression["ok"] is not False
        and deterministic and not blocker) else "FAIL"
    verdict.update({
        "overall": overall,
        "n_low": len(low_rows),
        "n_train_anchors": len(train_rows),
        "n_held_anchors": len(held_rows),
        "train_anchors": [{"point_id": r.get("point_id"), "w": r["w"]}
                          for r in train_rows],
        "held_anchors": [{"point_id": r.get("point_id"), "w": r["w"]}
                         for r in held_rows],
        "correction_model": {
            "form": ("KOH 简化式离散差异 GP：δ=HFSS−OE 逐头 1-D "
                     "squared-exp GP（S11 线性 |Γ| 口径 / S21 dB / "
                     "εeff 绝对差），修正面=OE+δ"),
            "hyper_summary": pack["hyper_summary"],
        },
        "synthetic_recovery": pin,
        "regression_pin": regression,
        "deterministic": bool(deterministic),
        "judgment": {
            "arms": {"mfk_lowfi_fix": mfk,
                     "baseline_oe_direct": base,
                     "mfk_prefix": prefix,
                     "koh_lowfi_direct": arm_koh},
            "gates_pass": res_fix["gates_pass"],
            "value_add_pass_vs_oe": value_vs_oe,
            "second_control_vs_prefix": second_control,
            "baseline_pairing": res_prefix["baseline_pairing"],
            "n_held": len(held_rows),
        },
        "fit_failure_blocker": bool(blocker),
        "freq_grid_ghz": [float(f) for f in freqs],
    })
    if blocker:
        verdict["blocker_note"] = (
            f"mfk_lowfi_fix 缺头/NaN {mfk['n_fit_failures']} 项——多报不放过"
            "（#314/#316）整体判 FAIL")
    verdict["wall_s"] = round(time.perf_counter() - t0, 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "discrepancy_gp_hyper.json").write_text(
        json.dumps({"hyper_summary": pack["hyper_summary"],
                    "l_s11": [gp.l for gp in pack["gp11"]],
                    "sf_s11": [gp.sf for gp in pack["gp11"]],
                    "l_s21": [gp.l for gp in pack["gp21"]],
                    "l_eps": pack["gpe"].l, "sf_eps": pack["gpe"].sf,
                    "d11_train": pack["d11"].tolist(),
                    "d21_train": pack["d21"].tolist(),
                    "de_train": pack["de"].tolist(),
                    "w_train": pack["w_train"].tolist()},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "mfk_verdict_lowfi_fix.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    _plot(verdict, held_rows,
          out_dir / "heldout_compare_fix.png")
    log(f"[lowfix] verdict → {out_dir / 'mfk_verdict_lowfi_fix.json'}")
    return verdict


def _plot(verdict: dict[str, Any], held_rows: list[Row],
          out_png: Path) -> None:  # pragma: no cover - 图像产物
    """held-out 四臂对比图（英文标注避免 CJK 缺字形，#370 家族）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    arms = verdict["judgment"]["arms"]
    gate_gamma = verdict["thresholds"]["gamma_lin"]
    gate_eps = verdict["thresholds"]["eps_eff_rel"] * 100.0
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    names = ["mfk_lowfi_fix", "koh_lowfi_direct", "baseline_oe_direct",
             "mfk_prefix"]
    labels = ["MFK fixed", "OE+delta(KOH) direct", "OE direct",
              "MFK pre-fix"]
    colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#d62728"]
    x = np.arange(len(names))
    for ax, t in zip(axes[:2], held_rows, strict=True):
        pid = t.get("point_id")
        vals = [next(p["gamma_lin_max"] for p in arms[n]["per_point"]
                     if p["point_id"] == pid) for n in names]
        bars = ax.bar(x, vals, color=colors)
        ax.axhline(gate_gamma, color="r", ls="--", lw=1)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.set_ylabel("max linear |dGamma| (held)")
        ax.set_title(f"{pid} w={float(t['w']):.4f} mm")
        for b, v in zip(bars, vals, strict=True):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.4f}",
                    ha="center", va="bottom", fontsize=8)
        ax.text(0.02, gate_gamma, f"gate {gate_gamma}", color="r",
                fontsize=8, va="bottom", transform=ax.get_yaxis_transform())
    ax = axes[2]
    gt = [float(t["w"]) for t in held_rows]
    width = 0.2
    for i, (n, lab, c) in enumerate(zip(names, labels, colors, strict=True)):
        vals = []
        for t in held_rows:
            pid = t.get("point_id")
            p = next(p["eps_eff_rel"] for p in arms[n]["per_point"]
                     if p["point_id"] == pid)
            vals.append(float(p) * 100.0)
        ax.bar(np.array(gt) + (i - 1.5) * width, vals, width=width,
               label=lab, color=c)
    ax.axhline(gate_eps, color="r", ls="--", lw=1, label=f"gate {gate_eps}%")
    ax.set_xticks(gt)
    ax.set_xticklabels([f"w={g:.4f}" for g in gt])
    ax.set_ylabel("eps_eff rel diff (%)")
    ax.set_title("eps_eff gate per held anchor")
    ax.legend(fontsize=8)
    fig.suptitle(
        f"low-fi fix re-judge: overall={verdict['overall']} "
        f"(gates {verdict['judgment']['gates_pass']}, "
        f"vsOE {verdict['judgment']['value_add_pass_vs_oe']}, "
        f"vsPrefix {verdict['judgment']['second_control_vs_prefix']})")
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="MFK 低保真面 KOH 修正 + MFK 复判（--judge）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--judge", action="store_true", help="执行复判")
    ap.add_argument("--dataset", type=str, default=str(DATASET_DEFAULT))
    ap.add_argument("--anchors-root", type=str,
                    default=str(ANCHORS_ROOT_DEFAULT))
    ap.add_argument("--prefix-verdict", type=str,
                    default=str(PREFIX_VERDICT_DEFAULT))
    ap.add_argument("--out-dir", type=str, default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--freq-step", type=float, default=0.01)
    args = ap.parse_args(argv)
    if not args.judge:
        print(f"加 --judge 执行复判；判据见 {CRITERIA_PATH}")
        return 0
    m2, rj = load_scripts()
    freqs = m2.band_freqs(args.freq_step)
    log: Callable[[str], None] = print
    log(f"[lowfix] 低保真数据集：{args.dataset}（消费栅格 {len(freqs)} 点）")
    low_rows = m2.load_dataset(Path(args.dataset), freqs)
    log(f"[lowfix] 低保真行数 {len(low_rows)}")
    high_rows, notes = rj.load_high_anchors(Path(args.anchors_root), freqs,
                                            m2)
    for n in notes:
        log(f"[lowfix][note] {n}")
    log(f"[lowfix] 高保真锚点 {len(high_rows)} 行")
    verdict = run_fix(low_rows, high_rows, freqs,
                      prefix_verdict_path=Path(args.prefix_verdict),
                      out_dir=Path(args.out_dir), log=log)
    print(f"\n===== 低保真修正复判摘要（overall={verdict['overall']}） =====")
    if "judgment" in verdict:
        for name, arm in verdict["judgment"]["arms"].items():
            print(f"{name:>20}: |ΔΓ|max={arm['gamma_lin']['max']:.5f} "
                  f"εeff_max={arm['eps_eff_rel']['max'] * 100:.4f}% "
                  f"S21_max={arm['s21_db']['max']:.4f}dB")
        j = verdict["judgment"]
        print(f"门: {j['gates_pass']} 增值门(vs OE)={j['value_add_pass_vs_oe']}"
              f" 第二对照(vs prefix)={j['second_control_vs_prefix']}")
    print(f"合成钉: {verdict['synthetic_recovery']['pass']}  "
          f"回归钉: {verdict['regression_pin']['ok']}  "
          f"确定性: {verdict['deterministic']}")
    return 0 if verdict["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
