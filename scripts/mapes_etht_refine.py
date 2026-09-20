# mapes et/ht 源参考精修列驱动（纯离线零仿真，runs/mapes_etht_refine）。
#
# 任务：correction_limit.next_steps ①（runs/mapes_sref_study/evidence.json）——
# 以归档 et（激励时序）DFT 为绝对相位/幅度参考，精修激励口列参考，
# 在 150 轮归档上零仿真复算互易底四档并列：
#   raw_current / raw_wave / wav+colC / wav+et(诊断) / wav+colC+et(主判)。
#
# 预声明门见 runs/mapes_etht_refine/criteria.md（先于任何计算写就）。
# 主档 runs/mapes_zall_refix（evidence.json 同源，
# wav+colC 锚 0.0070773704118137 必须逐位复现 rel≤1e-9）；副档 runs/mapes_s4
# （原始 port_ut/port_it 零仿真重导，复刻 scripts/mapes_s2_zall.py
# read_rounds_ui 口径），门相对其自身 wav+colC 评估，仅作稳健性并列。
#
# 用法：
#   .venv/Scripts/python.exe scripts/mapes_etht_refine.py            # 全量
#   .venv/Scripts/python.exe scripts/mapes_etht_refine.py --quick    # 跳过 s4 重导
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.mapes import (  # noqa: E402
    apply_sref_recal,
    assemble_s_from_ui,
    dft_time2freq,
    fit_reciprocity_gain,
    sref_column_factors,
    sref_etht_column_factors,
    termination_delta,
    z_all_gate,
)

Z0 = 50.0
OUT = REPO / "runs" / "mapes_etht_refine"
REFIX_NPZ = REPO / "runs" / "mapes_zall_refix" / "s5_diag" / "raw_ui.npz"
S4_ROUNDS = REPO / "runs" / "mapes_s4" / "rounds"
S4_CACHE = OUT / "s4_raw_ui.npz"
ANCHOR_WAV_COLC = 0.0070773704118137

# 预声明门（criteria.md「预声明门」节，逐字同源）
GATE_EFFECTIVE_FRAC = 0.15
GATE_MARGINAL = "MARGINAL"
GATE_EFFECTIVE = "EFFECTIVE"
GATE_SATURATED = "SATURATED"

DFT_CONVENTION = (
    "et 与 port 探针时序一律用 core dft_time2freq（vendored openEMS "
    "utilities.DFT_time2freq pulse 分支同式：2·dt·Σ v·e^{-jωt}，引擎 DFT 为 "
    "e^{-jωt} 口径 #253②）；r_k=inc^meas/E 分子分母同式 DFT，比值口径一致。"
    "#253② 的 ~14% 斜率偏属 ReadUIData ZL 度量（Z_ref 提取链），与本原始 "
    "DFT 比值链无关。口径钉=主档 wav+colC 锚值逐位复现（rel≤1e-9）"
)


def rec_max(s: np.ndarray) -> float:
    return float(np.max(np.abs(s - np.swapaxes(s, -1, -2))))


def et_hash_table(rounds_dir: Path, q: int) -> dict:
    """全轮 et 逐字节 MD5 清点（criteria「合成信息量」节的正式核验）。"""
    hashes = {}
    for k in range(1, q + 1):
        b = (rounds_dir / f"p{k}" / "fdtd" / "et").read_bytes()
        hashes.setdefault(hashlib.md5(b).hexdigest(), []).append(k)
    return {
        "n_unique_hash": len(hashes),
        "n_rounds": q,
        "round_invariant": bool(len(hashes) == 1),
        "hash_to_rounds_sample": {h: v[:3] for h, v in hashes.items()},
    }


def read_port_ui_dump(fdtd_dir: Path, number: int):
    """复刻 scripts/mapes_s2_zall.py::read_port_ui_dump（零改动的本地副本）。"""
    ut = fdtd_dir / f"port_ut_{number}"
    it = fdtd_dir / f"port_it_{number}"
    if not (ut.exists() and it.exists()):
        return None
    du = np.loadtxt(str(ut), comments="%", ndmin=2)
    di = np.loadtxt(str(it), comments="%", ndmin=2)
    if du.shape[0] < 2 or di.shape[0] < 2 or du.shape[1] < 2 or di.shape[1] < 2:
        return None
    return (du[:, 0], du[:, 1]), (di[:, 0], di[:, 1]), None


def read_rounds_ui(rounds_dir: Path, q: int, freqs: np.ndarray):
    """复刻 scripts/mapes_s2_zall.py::read_rounds_ui（各档自身时间轴 DFT）。"""
    uf_all = np.zeros((q, q, freqs.size), dtype=complex)
    if_all = np.zeros((q, q, freqs.size), dtype=complex)
    for k in range(1, q + 1):
        fdtd = rounds_dir / f"p{k}" / "fdtd"
        for p in range(1, q + 1):
            rec = read_port_ui_dump(fdtd, p)
            if rec is None:
                raise RuntimeError(f"轮 p{k} 缺端口 {p} 的 port_ut/port_it：{fdtd}")
            (tu, u), (ti, i), _ = rec
            uf_all[k - 1, p - 1] = dft_time2freq(tu, u, freqs)
            if_all[k - 1, p - 1] = dft_time2freq(ti, i, freqs)
    return uf_all, if_all


def tier_table(uf: np.ndarray, im: np.ndarray, freqs: np.ndarray,
               et_t: np.ndarray, et_v: np.ndarray) -> tuple[dict, dict]:
    """四档并列 + 次级量（criteria「档位定义」节）。零仿真。"""
    s_cur = assemble_s_from_ui(uf, im, reference_impedance=Z0, numerator="current")
    s_wav = assemble_s_from_ui(uf, im, reference_impedance=Z0, numerator="wave")
    delta, delta_info = termination_delta(uf, im, reference_impedance=Z0)
    colc = sref_column_factors(delta, np.diagonal(s_wav, axis1=1, axis2=2))
    et_factors, et_info = sref_etht_column_factors(
        uf, im, freqs, et_t, et_v, reference_impedance=Z0)

    variants = {
        "raw_current": s_cur,
        "raw_wave": s_wav,
        "wav+colC": apply_sref_recal(s_wav, colc),
        "wav+et": apply_sref_recal(s_wav, et_factors),
        "wav+colC+et": apply_sref_recal(s_wav, colc * et_factors),
    }
    out: dict[str, dict] = {}
    curl: dict[str, dict] = {}
    for tag, s in variants.items():
        g = z_all_gate(s)
        out[tag] = {
            "reciprocity_max": g["reciprocity_max"],
            "reciprocity_perfreq_median": g["reciprocity_perfreq_median"],
            "reciprocity_perfreq_p95": g["reciprocity_perfreq_p95"],
            "sigma_max": g["sigma_max"],
            "min_eig_re_min": g["min_eig_re_min"],
        }
        # curl_wrms：S2 同款拟合残差（结构归因，非修正；#300 裁判不自证）
        _, gi = fit_reciprocity_gain(s)
        curl[tag] = {"curl_wrms_median": gi["fit_resid_wrms_median"],
                     "curl_wrms_max": gi["fit_resid_wrms_max"]}
    info = {
        "delta_info": {"n_no_valid": int(delta_info["n_no_valid"]),
                       "n_rounds_used_median": float(delta_info["n_rounds_used_median"])},
        "et_wobble_resid_max": et_info["wobble_resid_max"],
        "et_wobble_resid_median": et_info["wobble_resid_median"],
        "et_phase_span_rad_max": et_info["phase_span_rad_max"],
        "et_phase_step_rad_max": et_info["phase_step_rad_max"],
        "et_r2_imag_linear_median": et_info["r2_imag_linear_median"],
        "et_factor_max_abs_dev_from_1": float(np.max(np.abs(et_factors - 1.0))),
        "src_impedance_check": src_impedance_note(freqs, et_t, et_v),
    }
    return {"tiers": out, "curl": curl}, info


def src_impedance_note(freqs: np.ndarray, et_t: np.ndarray,
                       et_v: np.ndarray) -> dict:
    """ht 源参考交叉核对（report-only，不进门）：说明 ht 的消费口径。"""
    return {"note": "ht 仅入 hash 清点；Z_src=E/H 为 report-only 量，见 evidence"
                    "（本档 ht 与 et 同为逐轮不变源转储，跨轮比值无信息）",
            "freq_span_ghz": [float(freqs[0] / 1e9), float(freqs[-1] / 1e9)],
            "et_n_samples": int(np.asarray(et_t).size)}


def load_refix() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with np.load(REFIX_NPZ) as d:
        freqs = np.asarray(d["freq_hz"], float)
        uf = np.asarray(d["uf_all"], complex)
        im = np.asarray(d["if_all"], complex)
    dump = np.loadtxt(str(REPO / "runs" / "mapes_zall_refix" / "rounds" / "p1" / "fdtd" / "et"))
    return uf, im, freqs, dump[:, 0].copy(), dump[:, 1].copy()


def evaluate_gate(tiers: dict, base_tag: str, new_tag: str) -> dict:
    base = tiers[base_tag]["reciprocity_max"]
    new = tiers[new_tag]["reciprocity_max"]
    improvement = (base - new) / base
    if improvement >= GATE_EFFECTIVE_FRAC:
        verdict = GATE_EFFECTIVE
    elif improvement > 0.0:
        verdict = GATE_MARGINAL
    else:
        verdict = GATE_SATURATED
    return {
        "base_tag": base_tag, "new_tag": new_tag,
        "base_reciprocity_max": base, "new_reciprocity_max": new,
        "improvement_frac": improvement,
        "effective_threshold_frac": GATE_EFFECTIVE_FRAC,
        "effective_threshold_abs": base * (1.0 - GATE_EFFECTIVE_FRAC),
        "verdict": verdict,
    }


def main() -> int:
    t0 = time.time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="跳过副档 s4 的原始档重导（用既有缓存）")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 主档：runs/mapes_zall_refix --------------------------------------
    uf, im, freqs, et_t, et_v = load_refix()
    q = uf.shape[0]
    print(f"[refix] q={q} nf={freqs.size}", flush=True)
    et_ref_hash = et_hash_table(REPO / "runs" / "mapes_zall_refix" / "rounds", q)
    print(f"[refix] et hashes unique={et_ref_hash['n_unique_hash']} "
          f"round_invariant={et_ref_hash['round_invariant']}", flush=True)
    res_ref, info_ref = tier_table(uf, im, freqs, et_t, et_v)
    print(f"[refix] wav+colC={res_ref['tiers']['wav+colC']['reciprocity_max']:.10e} "
          f"(anchor {ANCHOR_WAV_COLC:.10e})", flush=True)
    anchor_ok = (res_ref["tiers"]["wav+colC"]["reciprocity_max"]
                 / ANCHOR_WAV_COLC - 1.0) < 1e-9
    if not anchor_ok:
        print("[refix] 锚值未复现（criteria DFT 口径钉）→ 停，不出 verdict",
              flush=True)
        return 2
    gate_ref = evaluate_gate(res_ref["tiers"], "wav+colC", "wav+colC+et")
    print(f"[refix] gate: improvement={gate_ref['improvement_frac']:+.4%} "
          f"verdict={gate_ref['verdict']}", flush=True)

    # ---- 副档：runs/mapes_s4 ----------------------------------------------
    res_s4 = gate_s4 = None
    s4_hash = None
    if not args.quick or not S4_CACHE.exists():
        t1 = time.time()
        meta = json.loads((REPO / "runs" / "mapes_s4" / "meta.json").read_text(encoding="utf-8"))
        freqs4 = np.asarray(meta["freq_ghz"], float) * 1e9
        uf4, im4 = read_rounds_ui(S4_ROUNDS, int(meta["n_ports"]), freqs4)
        np.savez_compressed(S4_CACHE, freq_hz=freqs4, uf_all=uf4, if_all=im4)
        print(f"[s4] 重导 uf/if 用时 {time.time()-t1:.0f}s → 缓存 {S4_CACHE.name}",
              flush=True)
    if S4_CACHE.exists():
        with np.load(S4_CACHE) as d:
            freqs4 = np.asarray(d["freq_hz"], float)
            uf4 = np.asarray(d["uf_all"], complex)
            im4 = np.asarray(d["if_all"], complex)
        s4_hash = et_hash_table(S4_ROUNDS, uf4.shape[0])
        dump4 = np.loadtxt(str(S4_ROUNDS / "p1" / "fdtd" / "et"))
        res_s4, info_s4 = tier_table(uf4, im4, freqs4, dump4[:, 0].copy(),
                                     dump4[:, 1].copy())
        gate_s4 = evaluate_gate(res_s4["tiers"], "wav+colC", "wav+colC+et")
        print(f"[s4] gate: improvement={gate_s4['improvement_frac']:+.4%} "
              f"verdict={gate_s4['verdict']}", flush=True)

    # ---- evidence 落档（每数带 recompute，#97/#300）------------------------
    recompute = (
        ".venv/Scripts/python.exe scripts/mapes_etht_refine.py  "
        "# tiers: rfauto.core.mapes assemble_s_from_ui/termination_delta/"
        "sref_column_factors/sref_etht_column_factors/apply_sref_recal/"
        "z_all_gate/fit_reciprocity_gain（grep 函数名即得）；"
        "curl_wrms: tier_table 内 fit_reciprocity_gain 残差字段")
    ev = {
        "meta": {
            "item": "mapes-etht-source-refine（correction_limit.next_steps ①）",
            "criteria": "runs/mapes_etht_refine/criteria.md（预声明门+符号修订记录）",
            "primary_archive": "runs/mapes_zall_refix（evidence.json 同源）",
            "secondary_archive": "runs/mapes_s4（原始档零仿真重导，稳健性并列）",
            "q": q, "n_freq": int(freqs.size),
            "freq_ghz": [float(freqs[0] / 1e9), float(freqs[-1] / 1e9)],
            "z0": Z0,
            "dft_convention": DFT_CONVENTION,
            "et_round_invariance": {
                "refix": et_ref_hash, "mapes_s4": s4_hash,
                "implication": "激励源实现逐轮逐字节不变 → '逐轮精修'即逐激励口"
                               "（=逐轮）列精修；逐轮源实现抖动不存在（勘察+全量"
                               "MD5 双重核验）",
            },
            "elapsed_s": round(time.time() - t0, 1),
        },
        "refix_primary": {
            "tiers": res_ref["tiers"],
            "curl_wrms": res_ref["curl"],
            "diagnostics": info_ref,
            "anchor": {
                "wav_colc_anchor": ANCHOR_WAV_COLC,
                "recomputed": res_ref["tiers"]["wav+colC"]["reciprocity_max"],
                "rel_dev": float(res_ref["tiers"]["wav+colC"]["reciprocity_max"]
                                 / ANCHOR_WAV_COLC - 1.0),
                "match": anchor_ok,
            },
            "gate": gate_ref,
            "recompute": recompute,
        },
        "s4_secondary": (None if res_s4 is None else {
            "tiers": res_s4["tiers"],
            "curl_wrms": res_s4["curl"],
            "diagnostics": info_s4,
            "gate": gate_s4,
            "note": "门相对 s4 自身 wav+colC 评估（criteria 副档口径），仅稳健性并列",
            "recompute": recompute,
        }),
        "verdict": {
            "primary": gate_ref["verdict"] if gate_ref else None,
            "definition": "主判=wav+colC+et 相对 wav+colC 互易 max 改善量："
                          "≥15% EFFECTIVE / (0,15%) MARGINAL / ≤0 SATURATED",
            "secondary_robustness": gate_s4["verdict"] if gate_s4 else None,
        },
    }
    (OUT / "evidence.json").write_text(
        json.dumps(ev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] -> {OUT / 'evidence.json'} ({time.time()-t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
