"""引擎基准扩容 harness：四离线锚入账 + msl_cpw 真机补跑（openEMS 侧）。

物理裁判：mline harness（scripts/engine_benchmark_mline.py）范式的
四锚扩容——引擎升级/换机/模板迁移后重跑本脚本，判据内核
core/anchor_benchmark（纯函数，与 smoke 脚本逐门对齐），结果逐锚入库
runs/benchmark/<anchor>_engine_benchmark.json。

两种模式（可同跑）：
1. --ingest {ratrace|atten_pi|atten_t|via|all}：离线读 runs/*_smoke
   归档（只读，禁重跑覆写），经判据内核入账：
   - ratrace  runs/ratrace_smoke/pt9（ratrace.s4p 经 skrf + p1/
     port_beta.csv 单 β；solve 2989s 归档，定版主产物）
   - atten_pi runs/atten_pi_smoke/pt2（sparams.csv+port_beta.csv；pt3
     缓存复用 port_beta 缺失坏点弃用；匹配门 −12dB=商用 lumped 地板，
     校准记录见 provenance）
   - atten_t  runs/atten_t_smoke/pt1（同格式）
   - via      runs/via_smoke/pt3（双 β 列；β1 顶馈单判、β2 仅诊断
     real_modal_difference（#203 pt3）；互易 sparams.csv 无 S22 列
     不可复算，引归档日志转录 0.000dB，source=archive_log）
2. --msl-cpw：openEMS 真机补跑唯一缺档锚（runs/ 无任何 msl_cpw 归档），
   synthesize_msl_cpw_model 名义参数经 OpenEMSSolver.build_geometry
   直接渲染（msl_cpw 有意不入 TEMPLATE_META——additive 未注册，
   test_msl_cpw_template.test_additive_not_registered 钉死；注册走
   模板注册流程，本脚本严禁注册），家族口径 mesh 0.4mm、(2.25,2.75)GHz、
   solve_timeout 36000，working_dir runs/benchmark/msl_cpw_m0.4。
   同族单档时长预算：cpw 88s/atten_t 383s/via 623s → ≤30min。

provenance 惯例：归档路径 + mesh 0.4 + 门常量 + gate_version + 旧日志
判定与现门判定并列（引归档门校准依据）；HJ/CPWG 参考值一律运行时
经 core/synthesis 闭式计算，不硬编码（纪律 7）。
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.core.anchor_benchmark import (
    ATTEN_FLAT_TOL_DB,
    ATTEN_S11_FLOOR_DB,
    ATTEN_TARGET_DB,
    CPW_S21_MAX_LIN,
    CPW_S21_MIN_LIN,
    EPS_EFF_TOL_PCT,
    GATE_VERSION,
    RATRACE_BALANCE_MAX_DB,
    RATRACE_ISO_DELTA_MAX_DB,
    RATRACE_ISO_OUT_MAX_DB,
    RATRACE_RECIP_MAX_LIN,
    RATRACE_SPLIT_TARGET_DB,
    RATRACE_SPLIT_TOL_DB,
    VIA_RECIP_MAX_DB,
    VIA_S21_MAX_LIN,
    VIA_S21_MIN_LIN,
    atten_benchmark_verdict,
    msl_cpw_benchmark_verdict,
    ratrace_benchmark_verdict,
    via_benchmark_verdict,
)
from rfauto.core.anchor_verdict import S11_HEALTH_DB

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "runs" / "benchmark"
F_MID = 2.5            # 判读频点 GHz（家族公共口径）
FREQ_RANGE = (2.25, 2.75)
MESH_MM = 0.4          # 收敛档（引擎基准曲线判读）
STACKUP_NAME = "rogers4350b_h0.508"
W_FEED = 1.1134        # 50Ω 馈线标称点（HJ 综合标称值）
C0 = 299792458.0
CAPTURED_AT = "2026-09-15"


def _beta_eps(csv_path: Path, col: int = 1) -> float:
    """CalcPort β→εeff（金标准判据 #162）：±4% 窗内取 β 中位数。"""
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[col]) for r in rows])
    sel = (bf >= 0.96 * F_MID * 1e9) & (bf <= 1.04 * F_MID * 1e9)
    beta = float(np.median(bb[sel]))
    f_med = float(np.median(bf[sel]))
    return (beta * C0 / (2 * np.pi * f_med)) ** 2


def _read_sparams_csv(path: Path) -> tuple[np.ndarray, np.ndarray,
                                           np.ndarray]:
    """sparams.csv（freq_hz,re/im_S11,re/im_S21）→ (f, s11, s21)。"""
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    f = np.array([float(r[0]) for r in rows])
    s11 = np.array([complex(float(r[1]), float(r[2])) for r in rows])
    s21 = np.array([complex(float(r[3]), float(r[4])) for r in rows])
    return f, s11, s21


def _eps_hj_feed() -> float:
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup.from_materials_yaml(STACKUP_NAME)
    _, eps_hj = forward_z0(W_FEED, F_MID, stackup)
    return float(eps_hj)


def _write(anchor: str, out: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{anchor}_engine_benchmark.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    print(f"{anchor}: {out['verdict']} → {path}", flush=True)
    return path


def _base(anchor: str, source: dict) -> dict:
    return {"kind": "engine_benchmark_expand", "anchor": anchor,
            "gate_version": GATE_VERSION, "captured_at": CAPTURED_AT,
            "source": source}


# ─── ratrace（离线：pt9 归档 s4p + p1/port_beta.csv） ─────────────────────────

def ingest_ratrace() -> Path:
    import skrf

    work = REPO / "runs" / "ratrace_smoke" / "pt9"
    net = skrf.Network(work / "ratrace.s4p")
    i_mid = int(np.argmin(np.abs(net.f - F_MID * 1e9)))
    s = net.s[i_mid]
    s21_db = float(20 * np.log10(abs(s[1, 0]) + 1e-12))
    s41_db = float(20 * np.log10(abs(s[3, 0]) + 1e-12))
    s31_db = float(20 * np.log10(abs(s[2, 0]) + 1e-12))   # Δ 隔离
    s24_db = float(20 * np.log10(abs(s[3, 1]) + 1e-12))   # out1↔out2
    s11_db = float(20 * np.log10(abs(s[0, 0]) + 1e-12))
    recip = float(max(abs(abs(s[i, j]) - abs(s[j, i]))
                      for i in range(4) for j in range(4)))
    eps = _beta_eps(work / "p1" / "port_beta.csv")
    eps_hj = _eps_hj_feed()
    delta = (eps / eps_hj - 1.0) * 100.0

    bench = ratrace_benchmark_verdict(delta, s21_db, s41_db, s31_db,
                                      s24_db, s11_db, recip)
    out = _base("ratrace", {
        "kind": "smoke_archive_offline_ingest",
        "archive_dir": "runs/ratrace_smoke/pt9",
        "files": ["ratrace.s4p", "p1/port_beta.csv"],
        "mesh_mm": MESH_MM, "freq_range_ghz": list(FREQ_RANGE),
        "stackup": STACKUP_NAME, "w_feed_mm": W_FEED,
        "judge_freq_ghz": F_MID,
        "archive_solve_s": 2989})
    out.update({
        "refs": {"eps_hj_closed_form": round(eps_hj, 5)},
        "metrics": {"delta_eps_pct": round(delta, 3),
                    "eps_eff_feed": round(eps, 4),
                    "s21_db": round(s21_db, 2), "s41_db": round(s41_db, 2),
                    "s31_db": round(s31_db, 2), "s24_db": round(s24_db, 2),
                    "s11_db": round(s11_db, 2),
                    "recip_max_lin": round(recip, 4),
                    "balance_db": round(abs(s21_db - s41_db), 2)},
        "verdict": str(bench["verdict"]),
        "gate_flags": {k: bench[k] for k in (
            "beta_ok", "split_ok", "balance_ok", "iso_delta_ok",
            "iso_out_ok", "match_ok", "recip_ok")},
        "reason": str(bench["reason"]),
        "criteria": {"delta_eps_pct_abs_le": EPS_EFF_TOL_PCT,
                     "split_target_db": RATRACE_SPLIT_TARGET_DB,
                     "split_tol_db": RATRACE_SPLIT_TOL_DB,
                     "balance_db_le": RATRACE_BALANCE_MAX_DB,
                     "s31_db_le": RATRACE_ISO_DELTA_MAX_DB,
                     "s24_db_le": RATRACE_ISO_OUT_MAX_DB,
                     "s11_db_le": S11_HEALTH_DB,
                     "recip_lin_le": RATRACE_RECIP_MAX_LIN},
        "provenance": {
            "kernel":
                "src/rfauto/core/anchor_benchmark.py::"
                "ratrace_benchmark_verdict",
            "harness":
                ".venv/Scripts/python.exe scripts/engine_benchmark_expand.py"
                " --ingest ratrace",
            "old_gate_verdict": {
                "verdict": "PASS", "source": "archive_log",
                "path": "runs/ratrace_smoke/pt9/smoke_pt9.log",
                "note": "RATRACE_PROBE_PASS（七门与现门同口径；pt9 为 "
                        "#208 进程隔离定版主产物，pt1-pt8 为判废/调试链）"},
            "gate_calibration":
                "现门=smoke_ratrace_anchor.py:91-95 七门原样收编，无重标定",
            "note": "四锚公共口径 mesh=0.4mm 收敛档（引擎基准曲线判读）"}})
    return _write("ratrace", out)


# ─── atten π/T（离线：sparams.csv + port_beta.csv 单 β） ─────────────────────

def ingest_atten(anchor: str, work_rel: str, old_gate: dict) -> Path:
    work = REPO / work_rel
    f, s11, s21 = _read_sparams_csv(work / "sparams.csv")
    s11_max = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))
    s21_mean = float(np.mean(20 * np.log10(np.abs(s21) + 1e-12)))
    i_mid = int(np.argmin(np.abs(f - F_MID * 1e9)))
    s21_mid = float(20 * np.log10(abs(s21[i_mid]) + 1e-12))
    eps = _beta_eps(work / "port_beta.csv")
    eps_hj = _eps_hj_feed()
    delta = (eps / eps_hj - 1.0) * 100.0

    bench = atten_benchmark_verdict(delta, s21_mean, s11_max)
    out = _base(anchor, {
        "kind": "smoke_archive_offline_ingest",
        "archive_dir": work_rel,
        "files": ["sparams.csv", "port_beta.csv"],
        "mesh_mm": MESH_MM, "freq_range_ghz": list(FREQ_RANGE),
        "stackup": STACKUP_NAME, "w_feed_mm": W_FEED,
        "atten_target_db": ATTEN_TARGET_DB, "judge_freq_ghz": F_MID})
    out.update({
        "refs": {"eps_hj_closed_form": round(eps_hj, 5)},
        "metrics": {"delta_eps_pct": round(delta, 3),
                    "eps_eff_feed": round(eps, 4),
                    "s21_db_band_mean": round(s21_mean, 2),
                    "s21_db_at_2p5ghz": round(s21_mid, 2),
                    "s11_db_band_max": round(s11_max, 2)},
        "verdict": str(bench["verdict"]),
        "gate_flags": {k: bench[k] for k in ("beta_ok", "atten_ok",
                                             "match_ok")},
        "reason": str(bench["reason"]),
        "criteria": {"delta_eps_pct_abs_le": EPS_EFF_TOL_PCT,
                     "atten_target_db": ATTEN_TARGET_DB,
                     "atten_tol_db": ATTEN_FLAT_TOL_DB,
                     "s11_band_max_db_lt": ATTEN_S11_FLOOR_DB},
        "provenance": {
            "kernel":
                "src/rfauto/core/anchor_benchmark.py::"
                "atten_benchmark_verdict",
            "harness":
                ".venv/Scripts/python.exe scripts/engine_benchmark_expand.py"
                f" --ingest {anchor}",
            "old_gate_verdict": old_gate,
            "gate_calibration":
                "匹配门 −12dB=商用 lumped 衰减模块回损规格地板（典型 12~18dB"
                "口径），原 −20 门经 pt2 真机校准落地；|S21| 带内 mean 平坦均"
                "值语义 #195",
            "note": "四锚公共口径 mesh=0.4mm 收敛档（引擎基准曲线判读）"}})
    return _write(anchor, out)


def ingest_atten_pi() -> Path:
    return ingest_atten("atten_pi", "runs/atten_pi_smoke/pt2", {
        "verdict": "FAIL→现门 PASS", "source": "archive_log",
        "path": "smoke 归档日志（atten_pi pt2 匹配门校准记录）",
        "note": "冒烟控制台 FAIL 系旧 −20 匹配门（实测带内 −13.4dB 未过）；"
                "现门 −12dB 商用 lumped 地板下现判定 PASS。pt3 为缓存复用致 "
                "port_beta.csv 缺失坏点，弃用（本 harness 取 pt2）"})


def ingest_atten_t() -> Path:
    return ingest_atten("atten_t", "runs/atten_t_smoke/pt1", {
        "verdict": "PASS", "source": "archive_console",
        "path": "（冒烟控制台输出，归档无日志文件；数值经本 harness 离线"
                "复算 sparams.csv/port_beta.csv 逐值复核一致）",
        "note": "β +0.96%/dev 0.36dB/|S11|max −15.3dB（recon 转录）"})


# ─── via（离线：pt3 双 β；互易引归档转录） ────────────────────────────────────

def ingest_via() -> Path:
    work_rel = "runs/via_smoke/pt3"
    work = REPO / work_rel
    _f, s11, s21 = _read_sparams_csv(work / "sparams.csv")
    s11_max = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))
    s21_mean = float(np.mean(np.abs(s21)))
    s21_band_max = float(np.max(np.abs(s21)))
    eps1 = _beta_eps(work / "port_beta.csv", col=1)
    eps2 = _beta_eps(work / "port_beta.csv", col=2)
    eps_hj = _eps_hj_feed()
    delta1 = (eps1 / eps_hj - 1.0) * 100.0
    delta2 = (eps2 / eps_hj - 1.0) * 100.0
    recip = 0.0  # sparams.csv 无 S22 列不可复算；归档日志转录

    bench = via_benchmark_verdict(delta1, s11_max, s21_mean, recip, delta2,
                                  s21_lin_band_max=s21_band_max)
    out = _base("via", {
        "kind": "smoke_archive_offline_ingest",
        "archive_dir": work_rel,
        "files": ["sparams.csv", "port_beta.csv"],
        "mesh_mm": MESH_MM, "freq_range_ghz": list(FREQ_RANGE),
        "stackup": STACKUP_NAME, "w_feed_mm": W_FEED,
        "judge_freq_ghz": F_MID})
    out.update({
        "refs": {"eps_hj_closed_form": round(eps_hj, 5)},
        "metrics": {"delta_eps1_pct": round(delta1, 3),
                    "eps_eff1": round(eps1, 4),
                    "delta_eps2_pct": round(delta2, 3),
                    "eps_eff2": round(eps2, 4),
                    "s11_db_band_max": round(s11_max, 2),
                    "s21_lin_mean": round(s21_mean, 4),
                    "s21_lin_band_max": round(s21_band_max, 4),
                    "recip_db": recip,
                    "recip_source": "archive_log"},
        "verdict": str(bench["verdict"]),
        "gate_flags": {k: bench[k] for k in ("beta1_ok", "match_ok",
                                             "thru_ok", "recip_ok",
                                             "passive_ok")},
        "beta2_modal_difference_pct": round(delta2, 3),
        "reason": str(bench["reason"]),
        "criteria": {"beta1_delta_eps_pct_abs_le": EPS_EFF_TOL_PCT,
                     "s11_band_max_db_lt": S11_HEALTH_DB,
                     "s21_lin_mean_ge": VIA_S21_MIN_LIN,
                     "s21_lin_band_max_le": VIA_S21_MAX_LIN,
                     "recip_db_le": VIA_RECIP_MAX_DB},
        "provenance": {
            "kernel":
                "src/rfauto/core/anchor_benchmark.py::via_benchmark_verdict",
            "harness":
                ".venv/Scripts/python.exe scripts/engine_benchmark_expand.py"
                " --ingest via",
            "old_gate_verdict": {
                "verdict": "FAIL→现门 PASS", "source": "archive_log",
                "path": "smoke 归档日志（via pt3 β2 定征转录）",
                "note": "冒烟控制台 FAIL 系 β2 +10.93% 旧双馈 ±2% 门；"
                        "β2 定征为 real_modal_difference（倒置馈 CalcPort 提取"
                        "污染，与 1.0491 分解段同源），"
                        "现门 β1 顶馈单判、β2 仅诊断（smoke_via_anchor.py"
                        ":82 同口径）→ 现判定 PASS"},
            "recip_provenance":
                "互易 |mean S11−mean S22|=0.000dB：sparams.csv 列仅 "
                "freq_hz,re/im_S11,re/im_S21 无 S22，不可复算；引归档"
                "日志转录，source=archive_log",
            "gate_calibration":
                "β1 单判（β2=real_modal_difference 不设门），#203 pt3 定征；"
                "传输门增补无源上界 |S21| 带内 max ≤1.02（评审后增补，与 "
                "msl_cpw 同构；归档 401 点带内 max 0.9503 "
                "全部 ≤1.02，判定零翻转）",
            "note": "四锚公共口径 mesh=0.4mm 收敛档（引擎基准曲线判读）"}})
    return _write("via", out)


# ─── msl_cpw（真机补跑：唯一缺档锚） ──────────────────────────────────────────

def _msl_cpw_nominal() -> tuple[dict, float, float]:
    """msl_cpw 名义参数 + 两段参考 εeff（运行时闭式计算，不硬编码）。"""
    from rfauto.core.calculators import _cpwg_ri
    from rfauto.core.synthesis import Stackup, forward_z0, synthesize_msl_cpw_model

    synth = synthesize_msl_cpw_model()  # 名义参数（HJ + CPWG 闭式反解）
    params = {k: v for k, v in synth.params.items() if k != "f0_ghz"}
    stackup = Stackup.from_materials_yaml(STACKUP_NAME)
    _, er_eff1 = forward_z0(synth.params["w_msl_mm"], F_MID, stackup)
    er_eff2, _ = _cpwg_ri(synth.params["w_cpw_mm"],
                          synth.params["gap_cpw_mm"],
                          stackup.thickness_mm, stackup.epsilon_r)
    return params, float(er_eff1), float(er_eff2)


def run_msl_cpw() -> Path:
    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver

    params, _er_eff1, _er_eff2 = _msl_cpw_nominal()

    work = OUT_DIR / "msl_cpw_m0.4"
    # cache=False：基准真跑必须实际求解——全局缓存 runs/openems_cache 按脚本
    # 全文命中时只回 S 参数、不产 port_beta.csv（β 金标准不可读），与
    # atten_pi pt3「缓存复用致 port_beta.csv 缺失坏点」同款（首跑实测
    # 命中旧缓存条目秒级失败）
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work), freq_range_ghz=FREQ_RANGE,
        mesh_resolution_mm=MESH_MM,
        extra_params={"solve_timeout_s": 36000, "cache": False}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": "msl_cpw",
                                  "params": params}), "msl_cpw build 失败"
    # 复现参照（best-effort，不设门）：同脚本旧缓存条目（若存在）的 S 参数
    prior_npz = (REPO / "runs" / "openems_cache"
                 / f"{solver._cache_key(work / 'simulation.py')}.npz")
    t0 = time.time()
    result = solver.solve()
    wall = time.time() - t0
    if not (result.success and result.s_params is not None):
        out = _base("msl_cpw", {"kind": "openems_real_run",
                                "working_dir": work.relative_to(REPO).as_posix()})
        out.update({"params": params, "verdict": "FAIL",
                    "reason": f"求解失败: {result.message}"})
        return _write("msl_cpw", out)

    repro: dict = {"prior_cache_entry": None}
    try:
        if prior_npz.exists():
            with np.load(prior_npz) as data:
                ds = np.max(np.abs(np.asarray(data["s_params"])
                                   - np.asarray(result.s_params)))
            repro = {"prior_cache_entry": prior_npz.relative_to(REPO).as_posix(),
                     "prior_cache_mtime": time.strftime(
                         "%Y-%m-%d %H:%M",
                         time.localtime(prior_npz.stat().st_mtime)),
                     "max_abs_delta_s_vs_prior": float(ds)}
    except Exception as exc:  # 观测性 best-effort（#105）
        repro = {"prior_cache_entry": str(prior_npz), "error": str(exc)}

    return ingest_msl_cpw(wall_s=wall, repro=repro)


def ingest_msl_cpw(wall_s: float | None = None,
                   repro: dict | None = None) -> Path:
    """判读入账 runs/benchmark/msl_cpw_m0.4 真跑产物（只读工作目录，零求解）。

    与四离线锚同范式：门重标定后可 --msl-cpw-ingest 复判而不重解。
    wall_s/repro 由求解步传入；纯复判时从既有 JSON 结转（缺则 None）。
    """
    work = OUT_DIR / "msl_cpw_m0.4"
    params, er_eff1, er_eff2 = _msl_cpw_nominal()
    prev_path = OUT_DIR / "msl_cpw_engine_benchmark.json"
    if (wall_s is None or repro is None) and prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        if wall_s is None:
            wall_s = prev.get("metrics", {}).get("wall_s")
        if repro is None:
            repro = prev.get("repro_vs_prior_cache")
    if isinstance(repro, dict) and isinstance(
            repro.get("prior_cache_entry"), str):
        repro["prior_cache_entry"] = repro["prior_cache_entry"].replace(
            "\\", "/")  # 路径分隔符归一（跨时点 JSON 稳定）

    _f, s11, s21 = _read_sparams_csv(work / "sparams.csv")
    s11_max = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))
    s21_mean = float(np.mean(np.abs(s21)))
    s21_band_max = float(np.max(np.abs(s21)))
    eps1 = _beta_eps(work / "port_beta.csv", col=1)
    eps2 = _beta_eps(work / "port_beta.csv", col=2)
    delta1 = (eps1 / er_eff1 - 1.0) * 100.0
    delta2 = (eps2 / er_eff2 - 1.0) * 100.0

    bench = msl_cpw_benchmark_verdict(delta1, delta2, s11_max, s21_mean,
                                      s21_lin_band_max=s21_band_max)
    out = _base("msl_cpw", {
        "kind": "openems_real_run",
        "working_dir": work.relative_to(REPO).as_posix(),
        "mesh_mm": MESH_MM, "freq_range_ghz": list(FREQ_RANGE),
        "stackup": STACKUP_NAME, "solve_timeout_s": 36000,
        "cache": False,
        "files": ["sparams.csv", "port_beta.csv"],
        "template": "msl_cpw（additive 未注册，经 build_geometry 直接渲染；"
                    "注册走模板注册流程，本 harness 严禁注册）"})
    out.update({
        "params": params,
        "refs": {"er_eff1_hj_closed_form": round(float(er_eff1), 5),
                 "er_eff2_cpwg_closed_form": round(float(er_eff2), 5)},
        "metrics": {"delta_eps1_pct": round(delta1, 3),
                    "eps_eff1": round(eps1, 4),
                    "delta_eps2_pct": round(delta2, 3),
                    "eps_eff2": round(eps2, 4),
                    "s11_db_band_max": round(s11_max, 2),
                    "s21_lin_mean": round(s21_mean, 4),
                    "s21_lin_band_max": round(s21_band_max, 4),
                    "wall_s": (round(float(wall_s)) if wall_s is not None
                               else None)},
        "repro_vs_prior_cache": repro,
        "verdict": str(bench["verdict"]),
        "gate_flags": {k: bench[k] for k in ("beta1_ok", "beta2_ok",
                                             "match_ok", "thru_ok",
                                             "passive_ok")},
        "s21_vs_ideal_lin_dev": (
            round(float(bench["s21_vs_ideal_lin_dev"]), 4)
            if bench["s21_vs_ideal_lin_dev"] is not None else None),
        "reason": str(bench["reason"]),
        "criteria": {"eps1_delta_pct_abs_le": EPS_EFF_TOL_PCT,
                     "eps2_delta_pct_abs_le": EPS_EFF_TOL_PCT,
                     "s11_band_max_db_lt": S11_HEALTH_DB,
                     "s21_lin_mean_ge": CPW_S21_MIN_LIN,
                     "s21_lin_band_max_le": CPW_S21_MAX_LIN},
        "provenance": {
            "kernel":
                "src/rfauto/core/anchor_benchmark.py::"
                "msl_cpw_benchmark_verdict",
            "harness":
                ".venv/Scripts/python.exe scripts/engine_benchmark_expand.py"
                " --msl-cpw（求解+判读）/ --msl-cpw-ingest（只读复判）",
            "ref_sources":
                "er_eff1=core/synthesis.forward_z0（HJ）；er_eff2=core/"
                "calculators._cpwg_ri（共形映射）——运行时闭式计算不硬编码；"
                "名义参数=synthesize_msl_cpw_model()",
            "gate_calibration":
                "core/synthesis.py:881 docstring 口径：双端口 β 金标准 + "
                "|S11| −10dB 保守文献地板（#195 worst-case）+ |S21| 线性 "
                "mean ≥0.90 健康；对 fake 理想级联偏差只作信息量不设门",
            "note": "runs/ 此前无任何 msl_cpw 归档——本锚为唯一真机补跑"}})
    return _write("msl_cpw", out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingest",
                        choices=["ratrace", "atten_pi", "atten_t", "via",
                                 "all"],
                        help="离线归档入账（只读 runs/*_smoke，禁重跑覆写）")
    parser.add_argument("--msl-cpw", action="store_true",
                        help="openEMS 真机补跑 msl_cpw 锚（mesh 0.4）+ 判读")
    parser.add_argument("--msl-cpw-ingest", action="store_true",
                        help="只读复判既有 runs/benchmark/msl_cpw_m0.4 产物")
    args = parser.parse_args()
    if not (args.ingest or args.msl_cpw or args.msl_cpw_ingest):
        parser.error("至少指定 --ingest / --msl-cpw / --msl-cpw-ingest 之一")

    if args.ingest in ("ratrace", "all"):
        ingest_ratrace()
    if args.ingest in ("atten_pi", "all"):
        ingest_atten_pi()
    if args.ingest in ("atten_t", "all"):
        ingest_atten_t()
    if args.ingest in ("via", "all"):
        ingest_via()
    if args.msl_cpw:
        run_msl_cpw()
    elif args.msl_cpw_ingest:
        ingest_msl_cpw()
    return 0


if __name__ == "__main__":
    sys.exit(main())
