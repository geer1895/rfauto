"""F-D 验证深度战役·OE 横扫驱动（runs/ge_fd/criteria.md 预声明判据的执行器）。

用法（后台+solo，#157/#261）：
  .venv/Scripts/python.exe scripts/fd_oe_campaign.py [--only t1,t2] [--timeout 2400]
逐模板：TEMPLATE_META 名义参数→render_script（单激励，META 缺省网格/时长）→
OpenEMSSolver 真跑→健康门 G1..G5（criteria.md）→verdict JSON 落 runs/ge_fd/<t>/。

--remote [machine]（v1 调度面，2026-09-30 执行通道接线）：座位级路由到注册表
远程机器——逐座发射前 license_preflight（fail-closed：license 端口不通→该座
SKIP 不硬打，信封随 verdict 落档）；预检过=真实远程执行通道
（service/remote_oe_service：G1 本地渲染→服务器侧点驱动真跑（互斥预检
#261 命中=候跑 SKIP）→产物回拉镜像 runs/ge_fd/<t>/→判读器零改动直读；
SSH/回拉/清理失败=FAIL 如实记账，绝不假绿）。缺省（不带 --remote）=local
行为零变化。

NrTS/EndCriteria（wf:nrts-fix）：四 F-D 模板（patch_array_series/patch_eep_1x4/
ifa/ms_array_NxN）缺省由渲染链按 TEMPLATE_META.max_time_ns 终网格 CFL 折算
NrTS + 显式 EndCriteria=1e-6（−60dB）——#262 截断族修复面；--nrts/--end-criteria
为显式覆盖旋钮（探针/复跑用，c3 先例 #266）。verdict 附 nrts_converged 判读门：
引擎触 NrTS 帽且能量未达 EndCriteria=截断非物理，PASS 如实降 FAIL（#266 口径）。

退出码（H1-5 修复，F6 席 2026-10-04；scripts 退出码总表见
runs/review_ge8e/f6_scripts_fix/REPORT.md）：
  0=全座 PASS；1=发射面异常（--remote 机器解析失败/驱动级未捕获异常）；
  2=任一座 FAIL；3=任一座 SKIP（FAIL 优先于 SKIP）；4=无 FAIL/SKIP 但存在
  非 PASS 座位（PARTIAL/未知状态）；64=argparse 用法错（自定义 error，避开
  rc2 双义——H1-6 同族）。链式消费方（scripts/oe_chain_launch.py，
  oe_chain_waiter 家族收编版）只在 rc==0 时串发下一项；runs/ge8_followup/
  oe_chain_waiter.py 为 ge8b 历史档案（其"rc 恒 0"口径已被本修复取代，
  档案零改写）。注：campaign_wait_launch.py 的保留段 2/3/4/5 是其内存门/
  心跳自尽语义，该脚本只发射 calibration_campaign.py、从不发射本驱动，
  无同链冲突；如未来改接本驱动须按本表判读。
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import hashlib
import json
import re
import sys
import time
from collections.abc import Iterable
from pathlib import Path

import numpy as np

# H1-7（#295 族）修复：cwd 相对 "src" 注入改为仓根绝对锚——非仓根 cwd 执行
# （如 runs/ 子目录 spec 装载）不再 ModuleNotFoundError；去重守卫防重复注入。
REPO = Path(__file__).resolve().parents[1]
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

TARGETS = [
    "patch_array_1x4", "patch_array_2x2", "patch_array_series", "patch_eep_1x4",
    "ms_array_NxN", "ms_patch", "ms_cross", "ms_jcross", "bend",
    "branchline_2sect", "atten_pi", "atten_t", "stripline",
    "suspended_stripline", "tjunc", "monopole", "ifa",
]

# ── nrts_converged 判读门（wf:nrts-fix，#266 口径；c3 smoke_c3_filter_family
#    同款语义收窄自包含，正则与 scripts/smoke_coupled_bpf_nrts.parse_engine_log
#    同源）───────────────────────────────────────────────────────────────
_RE_DT = re.compile(
    r"FDTD timestep is: ([0-9.eE+-]+) s; Nyquist rate: (\d+) timesteps"
    r" @([0-9.eE+-]+) Hz")
_RE_EXC = re.compile(r"Excitation signal length is: (\d+) timesteps \(([0-9.eE+-]+)s\)")
_RE_MAX = re.compile(
    r"Max\.\s*number of timesteps: (\d+) \( --> ([0-9.eE+-]+) \* Excitation signal length\)")
_RE_SIZE = re.compile(r"FDTD simulation size: (\d+)x(\d+)x(\d+) --> ([0-9.eE+-]+) FDTD cells")
_RE_DONE = re.compile(r"Time for (\d+) iterations with ([0-9.eE+-]+) cells : ([0-9.]+) sec")
_RE_PROG = re.compile(r"Timestep:\s+(\d+) \|\|.*?Energy: ~([0-9.eE+-]+) \(\s*(-?[0-9.]+)dB\)")
_RE_NRTS_WARN = re.compile(
    r"Max\.\s*number of timesteps was reached before the end-criteria of (-?[0-9.]+)dB")


def parse_engine_log(text: str) -> dict:
    """openEMS 引擎 stdout → NrTS/EndCriteria 终止诊断（纯解析，离线可测）。"""
    info: dict = {}
    if (m := _RE_SIZE.search(text)):
        info["grid"] = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
        info["cells"] = float(m.group(4))
    if (m := _RE_DT.search(text)):
        info["dt_s"] = float(m.group(1))
        info["nyquist_steps"] = int(m.group(2))
        info["f_max_hz"] = float(m.group(3))
    if (m := _RE_EXC.search(text)):
        info["excitation_steps"] = int(m.group(1))
        info["excitation_s"] = float(m.group(2))
    if (m := _RE_MAX.search(text)):
        info["nrts"] = int(m.group(1))       # 引擎实收 NrTS（覆写后真值）
        info["nrts_over_excitation"] = float(m.group(2))
    if (m := _RE_DONE.search(text)):
        info["iterations_done"] = int(m.group(1))
        info["engine_wall_s"] = float(m.group(3))
    if (m := _RE_NRTS_WARN.search(text)):
        info["nrts_limit_warning"] = True
        info["end_criteria_db"] = float(m.group(1))
    elif "iterations_done" in info:
        info["nrts_limit_warning"] = False
    prog = _RE_PROG.findall(text)
    if prog:
        info["last_progress_step"] = int(prog[-1][0])
        info["last_energy_db"] = float(prog[-1][2])
        info["min_energy_db"] = float(min(float(p[2]) for p in prog))
    if "iterations_done" in info and "nrts" in info:
        done = int(info["iterations_done"])
        info["hit_nrts_limit"] = done >= int(info["nrts"])
        if "excitation_steps" in info:
            info["excitation_covered"] = done >= int(info["excitation_steps"])
    return info


def nrts_convergence(eng: dict) -> dict:
    """NrTS/EndCriteria 收敛判读（纯函数，#266 口径四分支）：

    ① 引擎触帽告警 → 未收敛；② 终止信息缺失 → 不可证明收敛（不采信）；
    ③ 触帽但日志能量最低值已达判据 → 收敛；④ 未触帽（按 EndCriteria 提前
    停机）→ 收敛。能量判据取日志显式 end_criteria_db，缺省 −60dB
    （END_CRITERIA_FD=1e-6 口径）。
    """
    crit = eng.get("end_criteria_db")
    crit_f = float(crit) if crit is not None else -60.0
    e_min = eng.get("min_energy_db")
    e_min_f = float(e_min) if e_min is not None else None
    done = eng.get("iterations_done")
    hit = eng.get("hit_nrts_limit")
    warn = bool(eng.get("nrts_limit_warning", False))
    if warn:
        ok, reason = False, "引擎告警：触 NrTS 上限时能量未达 EndCriteria"
    elif done is None:
        ok, reason = False, "终止信息缺失（无 iterations_done/nrts），无法证明收敛"
    elif hit:
        ok = bool(e_min_f is not None and e_min_f <= crit_f)
        reason = ("触 NrTS 上限但能量已达判据" if ok
                  else f"触 NrTS 上限且能量 {e_min_f} dB 未达 {crit_f} dB")
    else:
        ok, reason = True, "按 EndCriteria 提前停机（未触 NrTS 上限）"
    return {"converged": bool(ok), "reason": reason, "end_criteria_db": crit_f,
            "min_energy_db": e_min_f, "hit_nrts_limit": hit,
            "nrts_limit_warning": warn, "iterations_done": done,
            "nrts": eng.get("nrts")}


def nrts_converged_gate(run_dir: Path) -> dict:
    """run 目录收敛判读门（wf:nrts-fix）：引擎日志为主证、nrts_meta.json 旁证。

    返回 {ok: True/False/None, reason, ...}；日志文件缺=ok None（不可判，
    #105 best-effort 不阻塞主路径；#122：不凑 PASS 也不冒充 FAIL）。
    """
    log = run_dir / "_last_stdout.log"
    if not log.is_file():
        return {"ok": None,
                "reason": "引擎日志缺（_last_stdout.log），收敛不可判"}
    eng = parse_engine_log(log.read_text(encoding="utf-8", errors="replace"))
    out = nrts_convergence(eng)
    out["ok"] = out.pop("converged")
    out["evidence"] = eng
    meta_p = run_dir / "nrts_meta.json"
    if meta_p.is_file():
        with contextlib.suppress(OSError, ValueError):
            out["nrts_meta"] = json.loads(meta_p.read_text(encoding="utf-8"))
    return out


def apply_nrts_gate(verdict: dict, gate: dict) -> dict:
    """门落 verdict（#266 口径）：触帽未达判据=FAIL 如实（PASS 降级）；
    ok=None 证据缺不动状态只留痕。"""
    verdict["nrts_converged"] = gate
    if gate.get("ok") is False and verdict.get("status") == "PASS":
        verdict["status"] = "FAIL"
        verdict["reason"] = f"nrts_converged: {gate.get('reason')}"
    return verdict


def _last_timestamp(path: Path) -> float | None:
    """读 openEMS 两列时间序列（port_ut/et 等，'%'/'#' 头）末行时间轴
    （#268：求解进度唯一可信口径，best-effort #105——读不出如实 None）。"""
    try:
        last: str | None = None
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith(("%", "#")):
                    continue
                last = s
        if last is None:
            return None
        return float(last.split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _harvest_artifacts(run_dir: Path) -> dict:
    """求解完结后产物清点（无论健康与否，#105：证据面缺位要可见）。

    清点 port dump 末行时间轴（#268 口径）、sparams.csv、et/ht、模板原生
    非端口产物（array_meta.json/nf2ff——ms 族 n_ports=0 的数值面证据）。
    """
    inv: dict = {}
    fdtd = run_dir / "fdtd"
    inv["fdtd_dir"] = fdtd.is_dir()
    port_dumps: dict[str, float | None] = {}
    if fdtd.is_dir():
        for p in sorted(list(fdtd.glob("port_ut_*")) + list(fdtd.glob("port_it_*"))):
            port_dumps[p.name] = _last_timestamp(p)
    inv["port_dumps"] = port_dumps
    for name in ("et", "ht"):
        f = fdtd / name
        inv[f"{name}_t_end"] = _last_timestamp(f) if f.exists() else None
    sp = run_dir / "sparams.csv"
    inv["sparams_csv_bytes"] = sp.stat().st_size if sp.exists() else None
    inv["array_meta_json"] = (run_dir / "array_meta.json").exists()
    inv["nf2ff_files"] = (
        sorted(p.name for p in fdtd.glob("nf2ff*.h5")) if fdtd.is_dir() else [])
    return inv


def _parse_sparams_csv_disk(path: Path) -> np.ndarray | None:
    """solver 未回填 s_params 时从磁盘 best-effort 收割 sparams.csv。

    返回 (n_freq, P, P) 复矩阵；未测条目零填充=单激励部分矩阵（#314 掩码
    语义，G3 无源性按从宽口径全项判读）。不可读/列数不足如实 None。
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = [r for r in csv.reader(fh)
                    if r and not r[0].lstrip().startswith(("%", "#"))]
        if len(rows) < 2 or len(rows[0]) < 3:
            return None
        header = rows[0]
        pairs: list[tuple[int, int]] = []
        for c in range(1, len(header) - 1, 2):
            name = header[c].strip().lower()
            if not (name.startswith("re_s") and name[4:].isdigit()
                    and len(name[4:]) == 2):
                return None
            pairs.append((int(name[4]) - 1, int(name[5]) - 1))
        arr = np.array([[float(x) for x in r] for r in rows[1:]], dtype=float)
    except (OSError, ValueError):
        return None
    if arr.ndim != 2 or arr.shape[1] != 1 + 2 * len(pairs):
        return None
    size = max(max(i, j) for i, j in pairs) + 1
    s = np.zeros((arr.shape[0], size, size), dtype=complex)
    for k, (i, j) in enumerate(pairs):
        s[:, i, j] = arr[:, 1 + 2 * k] + 1j * arr[:, 2 + 2 * k]
    return s


# ── G2 portless 判据改道（T42）+ v2 前向通量升格（T49，2026-09-30）────────
# 归因=T40（runs/ms_array_nxn_rerun/g2_root_cause.md）：PORTLESS_TEMPLATES
# 无端口软平面照明模板结构上永不产 sparams，原 G2 判据（sparams.csv 存在且
# 可解析）对该模板结构性错配。改道阈值与状态映射预声明冻结于
# runs/ms_array_nxn_rerun/salvage/criteria_salvage.md（#122 先行）：
# S1 记录完整性（TD 末快照步号/预声明 NrTS ≥90%）+ S2 farfield 链可执行 +
# S3a 方向图完整/有限；Dmax 非物理=登记缺陷不消费。
# v2 升格（T47 审计定案 farfield_semantics_audit.md 结论 1/6）：
# **S3b 旧判据 Prad≥0 移除**——nf2ff 闭盒内部无源无耗，实功率流积分
# ∮Re(E×H*)·n̂dS ≡ 0（数学恒等，与反射几何无关；引擎 Prad=−1.45e-24W 即
# 此恒等式零的 float32 舍入底，镜像 on/off 消融 16 位一致坐实），闭盒
# Prad≥0 对 portless 记录结构性永假（判据物理量在该记录拓扑下无定义）。
# 替代判据 S3b-v2 前向通量：顶面(+z)前向平面波谱功率 P_up 与
# Dmax_v2=4π·U_max/P_up（audit/ff_audit_lib.py 独立管线，#118 裁判独立），
# 阈值预声明（criteria_salvage.md §六）：P_up 有限>0、Dmax_v2∈[0,40]dBi
# （ms 族物理带）、S1 覆盖 ≥90%。v2 证据=归一化 farfield_v2.json（schema
# 见 farfield_v2_health docstring）；ms_array 重判读消费 T47 在档
# audit/flux_decomp.json——审计资产只读复用（零 import 零拷贝，物理管线
# 不进本模块，本模块只做判读）。
# ported 模板原语义零变化（双路径钉 test_fd_oe_campaign_salvage.py）。
_SALVAGE_COVERAGE_MIN = 0.90    # S1 阈值（criteria_salvage.md §三）
_SALVAGE_CRITERIA_REL = "runs/ms_array_nxn_rerun/salvage/criteria_salvage.md"
_V2_DMAX_DBI_RANGE = (0.0, 40.0)     # S3b-v2 预声明：ms 族 Dmax 物理带
_V2_EVIDENCE_FILENAME = "farfield_v2.json"   # run 目录内联 v2 证据约定名
# 空场熔断地板（7×7 教训，六百九十三）：E_norm 全局 max=6.6e-9
# （−163.7dB）/P_up=2.17e-22W 时 argmax 仍给 25° 与 Dmax=35.19dBi（零/零
# 比值伪象）——低于地板=空远场，判读熔断 UNKNOWN 不产 Dmax 假值。
_V2_P_UP_ABS_FLOOR_W = 10.0 ** (-140.0 / 10.0)    # −140 dBW = 1e-14 W
_E_NORM_ABS_FLOOR = 10.0 ** (-140.0 / 20.0)       # −140 dB（引擎归一场单位）


def _nf2ff_td_last_step(h5_path: Path) -> int | None:
    """nf2ff dump h5 的 FieldData/TD 末张快照步号（T40 进度铁证口径）。

    best-effort（#105）：缺组/不可读/无 h5py → None（不可判，不阻塞主路径）。
    """
    try:
        import h5py  # 惰性：无 h5py 环境不阻塞模块导入
    except ImportError:
        return None
    try:
        with h5py.File(h5_path, "r") as fh:
            td = fh["FieldData"]["TD"]
            return max(int(k) for k in td)
    except (OSError, KeyError, ValueError):
        return None


def nf2ff_td_coverage(run_dir: Path) -> dict:
    """S1 记录完整性证据：nf2ff TD 末快照步号 / nrts_meta 预声明 NrTS。

    快照步号取 fdtd/nf2ff_E_*.h5 跨文件最大（T40 实测各文件一致）；进度
    口径以 h5 快照键为准（et/ht 的 #268 缓冲伪象不作进度证据）。任一证据
    缺=None（不可判，#122 不凑）。
    """
    run_dir = Path(run_dir)
    fdtd = run_dir / "fdtd"
    files = sorted(fdtd.glob("nf2ff_E_*.h5")) if fdtd.is_dir() else []
    last = None
    for p in files:
        step = _nf2ff_td_last_step(p)
        if step is not None and (last is None or step > last):
            last = step
    declared = None
    meta_p = run_dir / "nrts_meta.json"
    if meta_p.is_file():
        try:
            declared = int(json.loads(
                meta_p.read_text(encoding="utf-8")).get("nrts_declared"))
        except (OSError, ValueError, TypeError, AttributeError):
            declared = None
    coverage = (last / declared) if (last is not None and declared) else None
    return {"nf2ff_files": [p.name for p in files], "td_last_step": last,
            "nrts_declared": declared, "coverage": coverage}


def _read_farfield_result_h5(h5_path: Path) -> dict | None:
    """读 CalcNF2FF 结果 h5 最小面（nf2ff_results 同构；不 import openEMS）。

    返回 farfield_health 指标 dict（dmax/prad/n_theta/n_phi/shape/
    finite_all/e_norm_max，单频 f0）；不可读=None。
    """
    try:
        import h5py
    except ImportError:
        return None
    try:
        with h5py.File(h5_path, "r") as fh:
            data = fh["nf2ff"]
            e_th = (np.array(data["E_theta"]["FD"]["f0_real"])
                    + 1j * np.array(data["E_theta"]["FD"]["f0_imag"]))
            e_ph = (np.array(data["E_phi"]["FD"]["f0_real"])
                    + 1j * np.array(data["E_phi"]["FD"]["f0_imag"]))
            e_th = np.swapaxes(e_th, 0, 1)
            e_ph = np.swapaxes(e_ph, 0, 1)
            return {"dmax": float(np.atleast_1d(np.array(data.attrs["Dmax"]))[0]),
                    "prad": float(np.atleast_1d(np.array(data.attrs["Prad"]))[0]),
                    "n_theta": int(np.array(fh["Mesh"]["theta"]).size),
                    "n_phi": int(np.array(fh["Mesh"]["phi"]).size),
                    "shape": [int(v) for v in e_th.shape],
                    "finite_all": bool(np.all(np.isfinite(e_th))
                                       and np.all(np.isfinite(e_ph))),
                    "e_norm_max": float(np.max(np.hypot(np.abs(e_th),
                                                        np.abs(e_ph))))}
    except (OSError, KeyError, ValueError):
        return None


def farfield_health(m: dict | None, expect_theta: int | None = None,
                    expect_phi: int | None = None) -> dict:
    """farfield 产物健康判读（**非 Dmax 口径**，criteria_salvage.md §三）。

    m=远场指标 dict（_read_farfield_result_h5 / calc_nf2ff_offline 产物）：
    {dmax, prad, n_theta, n_phi, shape, finite_all, e_norm_max}；None=不可判。
    S3a 方向图完整性：shape==(n_theta,n_phi) 且 finite_all；expect_* 给定时
    加严格长度核对（salvage 执行器用预声明角网 181×2）。
    空场熔断（7×7 教训）：e_norm_max 低于绝对地板 _E_NORM_ABS_FLOOR（−140dB）
    → ``empty_field=True``——方向/Dmax 类 argmax 判读为零场伪象不采信，
    上层判读面（portless_g2_gate s3c）据此显式熔断。
    S3b 无源性（Prad≥0）判据**已移除**（T47 结论 1：portless 闭盒
    ∮Re(E×H*)·n̂dS≡0 恒等式零——引擎 Prad=−1.45e-24W 即此零，判据物理量
    对该记录拓扑无定义=结构性永假）——prad 只作 raw 留痕不判；无源性/物理
    值合理性改由 v2 前向通量门承担（farfield_v2_health → portless_g2_gate
    checks.s3b_v2_forward_flux，criteria_salvage.md §六）。
    Dmax：只登记 dmax_defect_registered（≤0 或 dBi<−50=非物理），不参与
    PASS/FAIL（T40 三-3 反射几何测量语义缺陷，#1b/T47 独立审计）。
    """
    if m is None:
        return {"readable": False, "chain_executed": None,
                "pattern_complete": None,
                "dmax_defect_registered": None,
                "empty_field": None,
                "detail": "farfield 结果不可读"}
    dmax = m.get("dmax")
    prad = m.get("prad")
    n_theta = int(m.get("n_theta") or 0)
    n_phi = int(m.get("n_phi") or 0)
    shape = [int(v) for v in (m.get("shape") or [])]
    shapes_ok = shape == [n_theta, n_phi] and n_theta >= 2 and n_phi >= 1
    if expect_theta is not None and expect_phi is not None:
        shapes_ok = shapes_ok and n_theta == expect_theta and n_phi == expect_phi
    finite_all = bool(m.get("finite_all"))
    dmax_ok = bool(dmax is not None and np.isfinite(dmax) and dmax > 0.0)
    dmax_defect = not dmax_ok or (dmax_ok and float(10.0 * np.log10(dmax)) < -50.0)
    e_norm_max = m.get("e_norm_max")
    empty_field = bool(
        e_norm_max is not None and np.isfinite(float(e_norm_max))
        and float(e_norm_max) < _E_NORM_ABS_FLOOR)
    return {"readable": True, "chain_executed": True,
            "pattern_complete": bool(shapes_ok and finite_all),
            "pattern_shape": shape, "n_theta": n_theta, "n_phi": n_phi,
            "prad": (None if prad is None else float(prad)),
            "dmax_linear": (None if dmax is None else float(dmax)),
            "dmax_dbi": (float(10.0 * np.log10(dmax)) if dmax_ok else None),
            "dmax_defect_registered": bool(dmax_defect),
            "empty_field": empty_field,
            "e_norm_max": e_norm_max}


def farfield_v2_health(v2: dict | None) -> dict:
    """v2 前向通量物理值判读（S3b-v2；T47 定案，criteria_salvage.md §六 预声明）。

    v2 证据 dict=归一化 schema（物理量由 audit/ff_audit_lib.py 独立管线
    产出——纯 h5py+numpy 零引擎导入、合成自检 T1–T5 前置，#118 裁判独立；
    本函数只判读不复算，审计资产只读复用）。None/非 dict=证据缺（不可判）：
      必需：p_up_w（顶面前向谱功率=v2 Prad）、dmax_v2_dbi；
      留痕：p_dn_w / p_up_over_pdn / dmax_v2_linear / theta_peak_deg /
            pad_convergence_rel(G1) / hemisphere_closure_rel(G2) /
            late_over_full_rel(G4)——质量旁证量登记不阻断（G1–G5 为管线侧
            消费前檐门，T47 离线验证已全过，见 criteria_salvage.md §六.3）。
    三态（#122 诚实条款；portless 永不 FAIL，False 也只降 PARTIAL）：
      True = P_up 有限>0 且 ≥ 空场地板 _V2_P_UP_ABS_FLOOR_W（−140dBW）且
             Dmax_v2_dbi∈[0,40]（预声明 ms 族物理带）；
      False= 值存在但 Dmax_v2 明确越界（物理不合理）；
      None = 证据缺 / P_up≤0 或非有限（恒等式零族=T47 结论 1，退化输入
             如实 UNKNOWN：不凑 PASS 也不判 FAIL）/ **空远场熔断**（P_up
             >0 但低于绝对地板——7×7 实证 P_up=2.17e-22W 时 argmax 仍产
             25° 指向与 Dmax=35.19dBi 零/零比值伪象，判读 UNKNOWN 不产
             Dmax 假值）/ dmax_v2_dbi 缺（证据不完整）。
    返回含 ``empty_field`` 键（True=空场熔断触发），judge 读回路径据此在
    reason 落 argmax 空场伪象警示。
    """
    lo, hi = _V2_DMAX_DBI_RANGE
    if not isinstance(v2, dict):
        return {"v2_available": False, "s3b_v2": None, "p_up_ok": None,
                "dmax_v2_ok": None, "p_up_w": None, "dmax_v2_dbi": None,
                "dmax_v2_range_dbi": [lo, hi], "empty_field": None,
                "quality": {},
                "detail": "v2 前向通量证据缺（farfield_v2 证据未落档，不可判）"}

    def _num(x: object) -> float | None:
        if isinstance(x, bool) or not isinstance(
                x, (int, float, np.integer, np.floating)):
            return None
        x = float(x)
        return x if np.isfinite(x) else None

    p_up = _num(v2.get("p_up_w"))
    empty_field = bool(p_up is not None and 0.0 < p_up < _V2_P_UP_ABS_FLOOR_W)
    p_up_ok = p_up is not None and p_up > 0.0 and not empty_field
    dmax_dbi = _num(v2.get("dmax_v2_dbi"))
    dmax_ok: bool | None = (lo <= dmax_dbi <= hi) if dmax_dbi is not None else None
    if p_up is None or p_up <= 0.0:
        s3b: bool | None = None
        detail = ("v2 物理量退化（P_up≤0 或非有限）——闭盒恒等式零族"
                  "（T47 结论 1）如实 UNKNOWN：不凑 PASS 也不判 FAIL")
    elif empty_field:
        s3b = None
        dmax_ok = None    # 熔断不产 Dmax 假值（零/零比值伪象）
        detail = (f"空远场熔断：P_up={p_up:.3e} W 低于绝对地板 "
                  f"{_V2_P_UP_ABS_FLOOR_W:.1e} W（−140dBW，E_norm 全局 max "
                  "同族低于 −140dB）——theta/Dmax 类 argmax 判读为零场伪象"
                  "（7×7 指向门 25° 实证）不采信，如实 UNKNOWN")
    elif dmax_ok is None:
        s3b = None
        detail = "v2 证据不完整（dmax_v2_dbi 缺或非有限），不可判"
    elif not dmax_ok:
        s3b = False
        detail = (f"v2 物理值不合理：Dmax_v2={dmax_dbi:.2f} dBi 越出预声明带 "
                  f"[{lo:g},{hi:g}] dBi")
    else:
        s3b = True
        detail = (f"v2 物理值合理：P_up={p_up:.3e} W、"
                  f"Dmax_v2={dmax_dbi:.2f} dBi")
    quality = {k: v2[k] for k in
               ("p_dn_w", "p_up_over_pdn", "dmax_v2_linear", "theta_peak_deg",
                "pad_convergence_rel", "hemisphere_closure_rel",
                "late_over_full_rel") if k in v2}
    return {"v2_available": True, "s3b_v2": s3b, "p_up_ok": p_up_ok,
            "dmax_v2_ok": dmax_ok, "p_up_w": p_up, "dmax_v2_dbi": dmax_dbi,
            "dmax_v2_range_dbi": [lo, hi], "empty_field": empty_field,
            "quality": quality, "detail": detail}


def _farfield_evidence_from_run_dir(run_dir: Path) -> dict:
    """驱动内联路径的 farfield 链证据（array_meta 新鲜度+结果 h5，S2 面）。

    链已执行判据：array_meta.json ok=True 且 mtime ≥ 最新 nf2ff_E h5 的
    mtime（陈旧=上一轮残留——T40 实证：重跑杀于 FDTD 循环时 array_meta 仍
    是前轮文件）。不新鲜→S2/S3 如实不可判（不消费陈旧数值）。
    """
    run_dir = Path(run_dir)
    fdtd = run_dir / "fdtd"
    h5s = sorted(fdtd.glob("nf2ff_E_*.h5")) if fdtd.is_dir() else []
    meta_p = run_dir / "array_meta.json"
    fresh = False
    meta_ok: bool | None = None
    meta: dict = {}
    if meta_p.is_file() and h5s:
        newest = max(p.stat().st_mtime for p in h5s)
        fresh = meta_p.stat().st_mtime >= newest
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            meta_ok = meta.get("ok") is True
        except (OSError, ValueError):
            meta_ok = None
    if fresh and meta_ok:
        out = farfield_health(_read_farfield_result_h5(fdtd / "nf2ff.h5"))
    else:
        out = farfield_health(None)
        out["chain_executed"] = False if (meta_p.is_file() and h5s) else None
    out["array_meta_fresh"] = fresh
    out["array_meta_ok"] = meta_ok
    out["array_meta_dmax_linear"] = meta.get("dmax_linear")
    out["source"] = "run_dir"
    return out


def portless_g2_gate(run_dir: Path, farfield_evidence: dict | None = None,
                     v2_evidence: dict | None = None) -> dict:
    """G2 portless 改道判读（v2 前向通量判据，T47 升格；阈值/映射=
    criteria_salvage.md §三/§六 冻结）。

    farfield_evidence=None 时自 run 目录内联收集；salvage 执行器传入离线
    CalcNF2FF 证据（source=salvage）。v2_evidence=None 时自 run 目录约定名
    farfield_v2.json 读取（离线 ff_audit_lib 管线落档）；仍缺则 s3b_v2 如实
    UNKNOWN（不凑 PASS，#122）。checks：S1 记录完整性 + S2 链可执行 +
    S3a 方向图完整 + s3b_v2_forward_flux（旧 s3b_prad_nonneg 已移除——
    portless 闭盒 Prad≡0 恒等式、判据结构性永假，T47 结论 1）。
    portless 永不产 FAIL（结构性错配≠求解失败，criteria_salvage.md §四）。
    """
    run_dir = Path(run_dir)
    cov = nf2ff_td_coverage(run_dir)
    ratio = cov["coverage"]
    s1 = None if ratio is None else bool(ratio >= _SALVAGE_COVERAGE_MIN)
    if farfield_evidence is None:
        farfield_evidence = _farfield_evidence_from_run_dir(run_dir)
    ff = dict(farfield_evidence)
    ff.setdefault("source", "run_dir")
    if v2_evidence is None:
        v2_p = run_dir / _V2_EVIDENCE_FILENAME
        if v2_p.is_file():
            with contextlib.suppress(OSError, ValueError):
                loaded = json.loads(v2_p.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    v2_evidence = loaded
    v2h = farfield_v2_health(v2_evidence)
    checks = {"s1_record_completeness": s1,
              "s2_chain_executed": ff.get("chain_executed"),
              "s3a_pattern_complete": ff.get("pattern_complete"),
              # S3b 旧判据 s3b_prad_nonneg 已移除（T47 结论 1：portless 闭盒
              # Prad≡0 恒等式、结构性永假）——代之以 v2 前向通量门。
              "s3b_v2_forward_flux": v2h["s3b_v2"]}
    # S3c 空场熔断（7×7 教训）：E_norm 全局 max 低于绝对地板 → 显式未过
    # （argmax/Dmax 判读为零场伪象不采信）。证据面不携带该键（旧式显式
    # 证据 dict）→ 不加检查键，零行为变化。
    if ff.get("empty_field") is not None:
        checks["s3c_empty_field_fuse"] = not ff["empty_field"]
    failed = [k for k, v in checks.items() if v is False]
    unknown = [k for k, v in checks.items() if v is None]
    if not failed and not unknown:
        status = "PASS"
        reason = ("G2 改道（portless·v2 前向通量）: nf2ff 记录完整+farfield "
                  f"链健康（快照覆盖 {ratio:.1%}≥{_SALVAGE_COVERAGE_MIN:.0%}，"
                  "方向图完整）+ v2 物理值合理（"
                  f"P_up={v2h['p_up_w']:.3e} W、"
                  f"Dmax_v2={v2h['dmax_v2_dbi']:.2f} dBi）")
    else:
        status = "PARTIAL"
        parts = []
        if failed:
            parts.append("未过: " + ",".join(failed))
        if unknown:
            parts.append("不可判: " + ",".join(unknown))
        reason = ("G2 改道（portless·v2 前向通量）: salvage 判据 "
                  + "；".join(parts) + "——如实不凑 PASS（#122）")
    if checks["s3b_v2_forward_flux"] is not True:
        reason += f"（{v2h['detail']}）"
    if ff.get("empty_field"):
        reason += ("；空远场警示：E_norm 全局 max 低于绝对地板——方向/Dmax "
                   "类 argmax 判读为零场伪象不采信（7×7 指向门 25° 实证）")
    if ff.get("dmax_defect_registered"):
        reason += ("；Dmax 非物理=登记缺陷不消费（farfield_semantics_defect；"
                   "引擎归档值经 T47 结论 2 判无效，物理值以 farfield_v2 为准）")
    return {"status": status, "g2_pass": status == "PASS", "reason": reason,
            "criteria_version": "v2_forward_flux",
            "coverage": cov, "farfield": ff, "farfield_v2": v2h,
            "checks": checks, "criteria": _SALVAGE_CRITERIA_REL}


# 渲染脚本常量值白名单：数字/算术/常量名引用；含括号=函数调用（如
# `FDTD = openEMS(...)`）一律跳过——解析零副作用（不实例化引擎）。
_CONST_VALUE_OK = re.compile(r"^[0-9eE+\-*/._A-Za-z\s]+$")

# E-07（2026-10-04）：字面量求值改 AST 白名单受限求值器。原 eval(...,
# {"__builtins__": {}}, env) 虽清空 builtins，但 env 里的 np 模块属性面
# 可触达任意 np 成员（DataSource 等文件读写面在属性行之下）；改收口为
# 仅算术/一元正负/列表元组字面/白名单 np 属性（arange/array/数值常量）
# 与白名单可调用（float/np.arange/np.array——theta 网格 ``np.arange(-90,
# 91,1)`` 与频率 ``float(F0)`` 两实需形态）。_CONST_VALUE_OK 前置白名单
# 兜底逻辑保持不变（含括号常量行依旧跳过）。
_NP_ATTR_OK = frozenset({"arange", "array", "pi", "e", "tau", "inf", "nan"})


def _restricted_eval(expr: str, env: dict):
    """渲染字面量受限求值：算术+白名单 np/float，其余节点一律 ValueError。

    与原 eval 的失败语义对齐（调用点 try/except → 键缺失，不臆造缺省）：
    未绑定名字、非白名单属性/调用、非白名单节点类型都抛错由上层跳过。
    """
    def _ev(node: ast.AST):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (bool, int, float, complex, str, bytes)) \
                    or node.value is None:
                return node.value
            raise ValueError(f"不支持的字面量: {type(node.value).__name__}")
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ValueError(f"未绑定名字: {node.id}")
            return env[node.id]
        if isinstance(node, ast.Attribute):
            base = _ev(node.value)
            if base is not np or node.attr not in _NP_ATTR_OK:
                raise ValueError(f"np 属性不在白名单: .{node.attr}")
            return getattr(np, node.attr)
        if isinstance(node, (ast.List, ast.Tuple)):
            items = [_ev(item) for item in node.elts]
            return tuple(items) if isinstance(node, ast.Tuple) else items
        if isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.UAdd, ast.USub)):
            value = _ev(node.operand)
            return -value if isinstance(node.op, ast.USub) else +value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (
                ast.Add, ast.Sub, ast.Mult, ast.Div,
                ast.FloorDiv, ast.Mod, ast.Pow)):
            left, right = _ev(node.left), _ev(node.right)
            return {
                ast.Add: lambda a, b: a + b,
                ast.Sub: lambda a, b: a - b,
                ast.Mult: lambda a, b: a * b,
                ast.Div: lambda a, b: a / b,
                ast.FloorDiv: lambda a, b: a // b,
                ast.Mod: lambda a, b: a % b,
                ast.Pow: lambda a, b: a ** b,
            }[type(node.op)](left, right)
        if isinstance(node, ast.Call):
            func = _ev(node.func)
            if func not in (float, np.arange, np.array):
                raise ValueError("调用面不在白名单（float/np.arange/np.array）")
            args = [_ev(arg) for arg in node.args]
            kwargs = {kw.arg: _ev(kw.value) for kw in node.keywords if kw.arg}
            return func(*args, **kwargs)
        raise ValueError(f"AST 节点不在受限求值白名单: {type(node).__name__}")

    return _ev(ast.parse(expr, mode="eval"))


def parse_nf2ff_plan(script_text: str) -> dict:
    """渲染脚本字面量 → salvage 重建远场计划（纯文本解析，离线可测）。

    提取：大写常量赋值（纯数字算术，顺序求值，函数调用行自动跳过）、
    nf2ff 盒构造的 start/stop 数组表达式（两种形态，ge7 ffrender 起）：
      旧·BC 推导形态 ``FDTD.CreateNF2FFBox("nf2ff", np.array([...]),
      np.array([...]))``；
      新·直构六面形态 ``_NF2FF(CSX, "nf2ff", np.array([...]),
      np.array([...]), directions=[True] * 6, mirror=[0] * 6)``
      （runs/ge6_ffdbg/replay_findings.md 定案：悬空 Box 底面 BC 自动
      PEC 镜像错位 → 直构闭合 6 面零镜像；directions/mirror 提取进
      ``nf2ff_directions``/``nf2ff_mirror`` 键，旧形态无此两键）。
    另提取 SetBoundaryCond 列表、_THETA_CUT/_PHI_CUT/_f_res。
    解析不出=key 缺失（如实，不臆造缺省）。
    """
    env: dict = {"np": np, "float": float}
    for m in re.finditer(r"^(_?[A-Z][A-Z_0-9]*)\s*=\s*(.+?)\s*(?:#.*)?$",
                         script_text, re.M):
        name, val = m.group(1), m.group(2)
        if "(" in val or ")" in val or not _CONST_VALUE_OK.match(val):
            continue
        try:
            env[name] = _restricted_eval(val, env)
        except Exception:
            continue
    plan: dict = {"constants": {k: v for k, v in env.items()
                                if k not in ("np", "float")}}
    m = re.search(r"(?:CreateNF2FFBox|_NF2FF)\(\s*(?:CSX\s*,\s*)?"
                  r"[\"']nf2ff[\"']\s*,\s*"
                  r"np\.array\(\[([^\]]+)\]\)\s*,\s*np\.array\(\[([^\]]+)\]\)",
                  script_text)
    if m:
        try:
            plan["box_start"] = [_restricted_eval(x.strip(), env)
                                 for x in m.group(1).split(",")]
            plan["box_stop"] = [_restricted_eval(x.strip(), env)
                                for x in m.group(2).split(",")]
        except Exception:
            pass
    # 直构六面形态的 directions/mirror 字面（含 ``[True] * 6`` 星乘形态；
    # 旧 CreateNF2FFBox 形态无此字面 → 两键缺=BC 推导口径，向后兼容）。
    m = re.search(r"directions=(\[[^\]]*\](?:\s*\*\s*\d+)?)\s*,\s*"
                  r"mirror=(\[[^\]]*\](?:\s*\*\s*\d+)?)", script_text)
    if m:
        try:
            dirs = _restricted_eval(m.group(1), env)
            mirr = _restricted_eval(m.group(2), env)
            plan["nf2ff_directions"] = dirs
            plan["nf2ff_mirror"] = mirr
        except Exception:
            pass
    m = re.search(r"SetBoundaryCond\((\[[^\]]*\])\)", script_text)
    if m:
        with contextlib.suppress(ValueError, SyntaxError):
            plan["boundary_cond"] = ast.literal_eval(m.group(1))
    for key, pat in (("theta_deg", r"_THETA_CUT\s*=\s*(\S.*)"),
                     ("phi_deg", r"_PHI_CUT\s*=\s*(\S.*)"),
                     ("freq_expr", r"_f_res\s*=\s*(\S.*)")):
        m = re.search(pat, script_text)
        if m:
            try:
                plan[key] = _restricted_eval(
                    m.group(1).strip().rstrip(","), env)
            except Exception:
                continue
    return plan


def _box_crosscheck(fdtd_dir: Path, start: list, stop: list) -> dict | None:
    """渲染字面量盒 vs h5 记录落格盒对拍（#329：记录坐标=落格事实）。

    E_0 面（x=start_x）给 start 全轴；x_stop 取 E_1 面；z_stop 取 z 顶面
    ——**顶面文件索引随记录面数位移**（ge7 ffrender）：直构六面记录
    （nf2ff_E_5.h5 在档）时 E_4=底/E_5=顶，旧 BC 推导五面（底面不记录）
    时 E_4=顶。按 E_5 存在性自适应，两代档案同口径。
    """
    try:
        import h5py
    except ImportError:
        return None
    try:
        d = Path(fdtd_dir)
        z_top_p = d / ("nf2ff_E_5.h5" if (d / "nf2ff_E_5.h5").is_file()
                       else "nf2ff_E_4.h5")
        with h5py.File(d / "nf2ff_E_0.h5", "r") as f0, \
                h5py.File(d / "nf2ff_E_1.h5", "r") as f1, \
                h5py.File(z_top_p, "r") as f4:
            m0 = f0["Mesh"]
            rec_start = [float(np.array(m0["x"])[0]), float(np.array(m0["y"])[0]),
                         float(np.array(m0["z"])[0])]
            rec_stop = [float(np.array(f1["Mesh"]["x"])[0]),
                        float(np.array(m0["y"])[-1]),
                        float(np.array(f4["Mesh"]["z"])[0])]
        deltas = ([abs(a - b) for a, b in zip(start, rec_start, strict=True)]
                  + [abs(a - b) for a, b in zip(stop, rec_stop, strict=True)])
        return {"recorded_start": rec_start, "recorded_stop": rec_stop,
                "max_delta": float(max(deltas))}
    except (OSError, KeyError):
        return None


def calc_nf2ff_offline(run_dir: Path, out_h5: Path) -> dict:
    """CalcNF2FF 读盘后处理核心（**零 FDTD**；禁止在已导入 h5py 的进程执行）。

    DLL 同名异版冲突（T42 实测）：h5py 与 openEMS vendor bin 各带
    hdf5.dll/hdf5_hl.dll/z.dll，同进程 co-load 后 CalcNF2FF 深读大 h5 硬崩
    （exit-127 无 traceback）；原 in-run 链（simulation.py）全程零 h5py。
    故本函数只许经 run_portless_salvage 生成的子进程执行（该子进程零 h5py）。

    渲染脚本字面量解析远场计划 → openEMS 同参重建（两形态，ge7 ffrender）：
      旧档案=CreateNF2FFBox 同参重建（BC 驱动 mirror 与原链逐字面同构）；
      直构六面档案（plan 带_nf2ff_directions/mirror 字面，runs/ge6_ffdbg
      定案修复后的渲染形态）=直构 nf2ff 类同参重建（闭合 6 面零镜像——
      若仍走 CreateNF2FFBox 会把 BC 推导镜像重新引入=非同参，判读失真）。
    → 读 fdtd/nf2ff_*_h5 做 DFT → 返回 farfield 指标 dict。fdtd/ 零写入
    （outfile 显式指向 out_h5）。
    """
    run_dir = Path(run_dir)
    plan = parse_nf2ff_plan(
        (run_dir / "simulation.py").read_text(encoding="utf-8"))
    need = ("box_start", "box_stop", "boundary_cond", "theta_deg", "phi_deg",
            "freq_expr")
    missing = [k for k in need if k not in plan]
    if missing:
        return {"ok": False,
                "error": f"渲染脚本远场计划解析缺 {missing}"}
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS

    t0 = time.time()
    csx = ContinuousStructure()
    fdtd_obj = openEMS(NrTS=1)   # 占位实例，绝不 Run（零 FDTD）
    fdtd_obj.SetCSX(csx)
    fdtd_obj.SetBoundaryCond(list(plan["boundary_cond"]))
    if "nf2ff_directions" in plan and "nf2ff_mirror" in plan:
        from openEMS.nf2ff import nf2ff as _nf2ff_cls
        ff_box = _nf2ff_cls(csx, "nf2ff", np.array(plan["box_start"]),
                            np.array(plan["box_stop"]),
                            directions=list(plan["nf2ff_directions"]),
                            mirror=list(plan["nf2ff_mirror"]))
    else:
        ff_box = fdtd_obj.CreateNF2FFBox("nf2ff", np.array(plan["box_start"]),
                                         np.array(plan["box_stop"]))
    res = ff_box.CalcNF2FF(str(run_dir / "fdtd"), float(plan["freq_expr"]),
                           np.asarray(plan["theta_deg"], dtype=float),
                           np.asarray(plan["phi_deg"], dtype=float),
                           outfile=str(out_h5))
    e_th = np.asarray(res.E_theta[0])
    e_ph = np.asarray(res.E_phi[0])
    return {"dmax": float(np.atleast_1d(res.Dmax)[0]),
            "prad": float(np.atleast_1d(res.Prad)[0]),
            "n_theta": int(np.asarray(res.theta).size),
            "n_phi": int(np.asarray(res.phi).size),
            "shape": [int(v) for v in e_th.shape],
            "finite_all": bool(np.all(np.isfinite(e_th))
                               and np.all(np.isfinite(e_ph))),
            "e_norm_max": float(np.max(np.hypot(np.abs(e_th), np.abs(e_ph)))),
            "wall_s": round(time.time() - t0, 1),
            "result_h5": str(out_h5)}


_SALVAGE_CHILD_TEMPLATE = r'''# T42 salvage 子进程（自动生成产物，留档自描述）。
# 无 h5py 环境：DLL 同名异版隔离见 calc_nf2ff_offline docstring。
import importlib.util
import json
import os
import sys
from pathlib import Path

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", "E:/openEMS/install/bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)
_repo = Path({repo!r})
_spec = importlib.util.spec_from_file_location(
    "fd_oe_campaign_child", _repo / "scripts" / "fd_oe_campaign.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["fd_oe_campaign_child"] = mod
_spec.loader.exec_module(mod)
run_dir, out_h5, metrics_path = (Path(a) for a in sys.argv[1:4])
try:
    metrics = mod.calc_nf2ff_offline(run_dir, out_h5)
    metrics["ok"] = True
except Exception as exc:   # 如实落错误，不凑
    metrics = {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}
metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                        encoding="utf-8")
print("nf2ff child done ok=", metrics.get("ok"), flush=True)
'''


def run_portless_salvage(run_dir: Path, out_dir: Path,
                         timeout_s: float = 14400.0) -> dict:
    """portless salvage 执行器（T42 任务 2；**零 FDTD** 读盘后处理）。

    CalcNF2FF 在**无 h5py 子进程**内执行（DLL 同名异版隔离，见
    calc_nf2ff_offline）；父进程随后做 h5py 侧证据读取（覆盖率/盒对拍）。
    fdtd/ 零写入（结果 outfile 显式落 out_dir/farfield）。
    """
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    ff_dir = out_dir / "farfield"
    ff_dir.mkdir(parents=True, exist_ok=True)
    cov = nf2ff_td_coverage(run_dir)
    plan = parse_nf2ff_plan(
        (run_dir / "simulation.py").read_text(encoding="utf-8"))
    need = ("box_start", "box_stop", "boundary_cond", "theta_deg", "phi_deg",
            "freq_expr")
    missing = [k for k in need if k not in plan]
    if missing:
        return {"status": "PARTIAL", "g2_pass": False,
                "reason": f"salvage 执行器: 渲染脚本远场计划解析缺 {missing}",
                "coverage": cov, "plan_keys": sorted(plan.keys()),
                "criteria": _SALVAGE_CRITERIA_REL}
    out_h5 = ff_dir / "nf2ff_result.h5"
    metrics_p = ff_dir / "nf2ff_metrics.json"
    child_p = ff_dir / "_nf2ff_child.py"
    repo = Path(__file__).resolve().parents[1]
    child_p.write_text(_SALVAGE_CHILD_TEMPLATE.format(repo=str(repo)),
                       encoding="utf-8")
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(child_p), str(run_dir), str(out_h5),
         str(metrics_p)],
        capture_output=True, text=True, timeout=float(timeout_s))
    tail = (proc.stderr or "")[-400:]
    if proc.returncode != 0 or not metrics_p.is_file():
        return {"status": "PARTIAL", "g2_pass": False,
                "reason": (f"salvage 执行器: CalcNF2FF 子进程失败 "
                           f"rc={proc.returncode} stderr_tail={tail!r}"),
                "coverage": cov, "criteria": _SALVAGE_CRITERIA_REL}
    metrics = json.loads(metrics_p.read_text(encoding="utf-8"))
    if not metrics.get("ok"):
        return {"status": "PARTIAL", "g2_pass": False,
                "reason": f"salvage 执行器: {metrics.get('error')}",
                "coverage": cov, "metrics": metrics,
                "criteria": _SALVAGE_CRITERIA_REL}
    evidence = farfield_health(
        metrics, expect_theta=len(np.asarray(plan["theta_deg"], dtype=float)),
        expect_phi=len(np.asarray(plan["phi_deg"], dtype=float)))
    evidence["source"] = "salvage"
    evidence["salvage_wall_s"] = metrics.get("wall_s")
    evidence["result_h5"] = str(out_h5)
    evidence["box_crosscheck"] = _box_crosscheck(
        run_dir / "fdtd", plan["box_start"], plan["box_stop"])
    judgment = portless_g2_gate(run_dir, farfield_evidence=evidence)
    judgment["salvage"] = {"wall_s": metrics.get("wall_s"),
                           "result_h5": str(out_h5),
                           "box_crosscheck": evidence["box_crosscheck"],
                           "child_rc": proc.returncode}
    return judgment


def _nominal_literal_check(
    template: str, params: dict, band: tuple[float, float], mesh: float,
    render_fn,
) -> tuple[dict[str, bool | None], str]:
    """#df5③ 渲染字面量自证：逐名义参数扰动重渲染，验证参数真流入字面量。

    返回 (flowed, base_text)。flowed[k]=True/False=该参数扰动是否改变渲染
    字面量；None=非标量或扰动渲染异常（不可判，不计吞）。全部 False=
    「恒 {}」回归签名（#P1-1：参数被吞、渲染恒走内部缺省，ms 族曾在
    h=0.508 缺省上跑）。
    """
    base = render_fn(template, dict(params), band, mesh_resolution_mm=mesh)
    flowed: dict[str, bool | None] = {}
    for key, val in params.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            flowed[key] = None
            continue
        mutated = dict(params)
        mutated[key] = val * 1.001 + (1e-9 if val >= 0 else -1e-9)
        try:
            alt = render_fn(template, mutated, band, mesh_resolution_mm=mesh)
        except Exception:
            flowed[key] = None
            continue
        flowed[key] = bool(alt != base)
    return flowed, base


def save_verdict(run_dir: Path, verdict: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")


# ── --remote 路由（v1 调度面：license 预检 fail-closed + remote_oe 执行通道）──

def _license_preflight(machine: str) -> dict:
    """license 预检薄包装（v1 调度面一级门；模块级便于单测钉通道，#139）。"""
    from rfauto.service.remote_service import license_preflight

    return license_preflight(machine)


def _remote_oe_run(machine: str, seat_spec: dict) -> dict:
    """远程 OE 执行通道薄包装（模块级便于单测钉通道，#139 同上）。"""
    from rfauto.service.remote_oe_service import remote_oe_run

    return remote_oe_run(machine, seat_spec)


def _resolve_remote_machine(name_or_empty: str) -> str:
    """--remote 机器名解析（空=唯一登记机器；注册表错误归一 ValueError）。"""
    from rfauto.infra.remote_machines import RemoteConfigError, load_remote_machines, resolve_machine

    try:
        cfg = resolve_machine(name_or_empty.strip() or None,
                              load_remote_machines())
    except RemoteConfigError as exc:
        raise ValueError(str(exc)) from exc
    if cfg is None:
        raise ValueError(
            "注册表无登记机器（configs/remote_machines.yaml）——--remote 不可用")
    return cfg.name


class _RenderSeatError(RuntimeError):
    """G1 座位渲染失败（携带 verdict 增量 meta，reason 文案与旧内联分支一致；
    literal=True=恒{}回归签名（print 标签区分，行为对齐旧内联分支）。"""

    def __init__(self, reason: str, meta: dict | None = None,
                 literal: bool = False):
        super().__init__(reason)
        self.meta = dict(meta or {})
        self.literal = bool(literal)


class _RemoteSolveResult:
    """远程座位的 solver-result 形态适配：s_params 恒 None → 判读共用尾走
    disk 收割/portless 改道；success=通道 exec_rc==0（G3 全过后据此降档
    PARTIAL——rc≠0 产物在=「数值面健康，如超时截断」口径）。"""

    def __init__(self, success: bool):
        self.success = bool(success)
        self.s_params = None


def _render_seat_text(
    template: str, params: dict, band: tuple[float, float], mesh: float,
) -> tuple[str, dict]:
    """G1 座位渲染+字面量自证（local 真跑 / --remote 上传两路共用）。

    render_script 惰性 import（保 main() 的 monkeypatch 面，salvage/nominal
    测试同源）。返回 (script_text, meta 增量)；失败抛 _RenderSeatError
    （reason 文案：恒{}回归签名 / G1 渲染: type: msg，逐字同旧内联分支）。
    """
    from rfauto.adapters.openems_templates import render_script

    if not params:
        try:
            return render_script(
                template, {}, band, mesh_resolution_mm=mesh), {}
        except Exception as exc:
            raise _RenderSeatError(
                f"G1 渲染: {type(exc).__name__}: {str(exc)[:160]}") from exc
    try:
        flowed, text = _nominal_literal_check(
            template, params, band, mesh, render_script)
    except Exception as exc:
        raise _RenderSeatError(
            f"G1 渲染: {type(exc).__name__}: {str(exc)[:160]}",
            {"nominal_literal": {"error": str(exc)[:120]}},
        ) from exc
    meta = {
        "nominal_literal": {
            "flowed": flowed,
            "all_swallowed": all(v is False for v in flowed.values()),
        },
        "render_input_sha256": hashlib.sha256(json.dumps(
            {"template": template, "params": params, "band": band,
             "mesh": mesh}, sort_keys=True).encode()).hexdigest(),
    }
    if all(v is False for v in flowed.values()):
        raise _RenderSeatError(
            "G1 渲染字面量: 名义参数全部未流入（恒{}回归签名）", meta,
            literal=True)
    return text, meta


_SEAT_CRITERIA_FALLBACK = """# F-D 验证深度战役·OE 横扫 criteria（--remote 座位随行判据；#122 先行）

> runs/ge_fd/criteria.md 缺席时的确定性回退文本（与主判据同口径，发射前随
> 座位落盘服务器侧任务目录）。
- G1 渲染审计：名义参数全部流入渲染字面量（恒{}回归签名=FAIL）。
- G2 求解完成：timeout 内结束；sparams.csv 存在且可解析。
- G3 数值健康：S 全有限（无 NaN/Inf）；无源 |S|≤1.05（5% 数值余量）。
- G4 提取面：至少 1 个端口 S11 行可提取（单激励部分矩阵，#314 掩码语义）。
- G5 health_check_run：verdict 非 corrupt（best-effort，#105）。
- nrts_converged：触 NrTS 帽且能量未达 EndCriteria=截断非物理，PASS 降 FAIL（#266）。
- 判读：PASS=G1..G5 全过；PARTIAL=超时/部分证据；FAIL=审计/数值/无源性失败。如实不凑绿。
"""


def _seat_criteria_text(out_root: Path) -> str:
    """座位随行判据（#122 判据先行）：runs/ge_fd/criteria.md 原文优先，
    缺席=确定性回退文本（同口径）——保证发射前 criteria.md 必落盘。"""
    try:
        text = (out_root / "criteria.md").read_text(encoding="utf-8")
        if text.strip():
            return text
    except OSError:
        pass
    return _SEAT_CRITERIA_FALLBACK


def remote_seat_gate(machine: str, preflight_fn, execute_fn=None,
                     seat_spec: dict | None = None) -> dict:
    """--remote 座位级门+执行通道（v1 接线，fail-closed 三态如实记账）：

    - 预检未过（license 端口不通/未登记）→ SKIP（fail-skip 不硬打）；
    - 预检过但 execute_fn/seat_spec 缺 → SKIP 如实（通道未提供，不假绿）；
    - 预检过+通道就绪 → execute_fn(machine, seat_spec) 真实远程执行：
      通道 skipped（互斥命中候跑/env 门未开/凭据缺）→ SKIP（未发射）；
      通道失败（SSH/发射/回拉空/清理）→ FAIL（已发射如实记败不假绿）；
      通道 ok → 不落 status（判读共用尾按回拉产物定 PASS/FAIL/PARTIAL），
      solve_success=（exec_rc==0）随增量落档（rc≠0 产物在=判读降档）。

    返回 verdict 增量 dict（remote/license_preflight[/remote_exec]）。
    """
    envelope = preflight_fn(machine)
    out: dict = {
        "remote": {"machine": machine, "routed": True,
                   "exec_channel": "remote_oe_service（v1 接线）"},
        "license_preflight": envelope,
    }
    if envelope.get("verdict") != "PASS":
        out["status"] = "SKIP"
        out["reason"] = (
            f"fail-skip：license 预检未过（verdict={envelope.get('verdict')}，"
            f"reason={envelope.get('reason')}）——不硬打")
        return out
    if execute_fn is None or seat_spec is None:
        out["status"] = "SKIP"
        out["reason"] = ("执行通道未提供（execute_fn/seat_spec 缺）——"
                         "如实 SKIP 不发射不假绿")
        return out
    result = execute_fn(machine, seat_spec)
    out["remote_exec"] = {
        "ok": bool(result.get("ok")),
        "skipped": bool(result.get("skipped")),
        "launched": bool(result.get("launched")),
        **{k: result.get(k) for k in (
            "machine", "batch", "task_dir_remote", "out_dir_local",
            "exec_rc", "wait_mode", "reason") if k in result},
    }
    if result.get("skipped"):
        out["status"] = "SKIP"
        out["reason"] = (f"远程通道未发射（候跑/前置不满足）："
                         f"{result.get('reason')}")
    elif not result.get("ok"):
        out["status"] = "FAIL"
        out["reason"] = f"远程执行通道失败：{result.get('reason')}"
    else:
        out["solve_success"] = result.get("exec_rc") == 0
    return out


def _judge_and_save(verdict: dict, run_dir: Path, out_root: Path,
                    result) -> dict:
    """G2 尾段判读共用体（local solver 真跑 / --remote 回拉两路同入同判）。

    s 归一三支：solver 回填 / disk 收割（sparams_source=disk_harvest）/
    portless 改道·无产物 PARTIAL → G3 有限+无源 → G5 health（best-effort
    #105）→ nrts_converged 门（#266）→ save_verdict。返回 verdict
    （循环层只做 summary/print）。health/PORTLESS 惰性 import 保
    monkeypatch 面（salvage 测试同源）。
    """
    from rfauto.adapters.openems_templates import PORTLESS_TEMPLATES
    from rfauto.service.health_service import health_check_run

    s_raw = getattr(result, "s_params", None)
    s = np.asanyarray(s_raw if s_raw is not None else [], dtype=complex)
    template = verdict.get("template")
    if s_raw is None or s.size == 0:
        # solver 未回填但磁盘 sparams.csv 在档 → 离线收割（零求解）
        disk = _parse_sparams_csv_disk(run_dir / "sparams.csv")
        if disk is not None and disk.size > 0:
            s = disk
            verdict["sparams_source"] = "disk_harvest"
        elif template in PORTLESS_TEMPLATES:
            # G2 判据改道（T42，portless）：无端口软平面照明模板结构上
            # 永不产 sparams——数值面证据改道 nf2ff dump 面（记录完整性
            # +farfield 链+产物健康）。预声明=runs/ms_array_nxn_rerun/
            # salvage/criteria_salvage.md（#122 冻结）；ported 模板原
            # 语义零变化（双路径钉）。
            salv = portless_g2_gate(run_dir)
            verdict["g2_portless_salvage"] = salv
            verdict["g3_finite"] = None       # 无 S 矩阵：G3 不判（#314）
            verdict["g3_passive_le_1p05"] = None
            verdict["status"] = salv["status"]
            verdict["reason"] = salv["reason"]
            # G5/nrts 通用门照走（与 ported 尾段同口径，best-effort）
            try:
                hc = health_check_run(run_dir.name, runs_dir=str(out_root))
                verdict["g5_health"] = {k: hc.get(k) for k in ("verdict", "ok") if k in hc}
            except Exception as exc:
                verdict["g5_health"] = {"error": str(exc)[:120]}
            try:
                verdict = apply_nrts_gate(verdict, nrts_converged_gate(run_dir))
            except Exception as exc:   # best-effort：门不得成为主路径故障点
                verdict["nrts_converged"] = {"ok": None, "reason": f"gate error: {exc}"}
            save_verdict(run_dir, verdict)
            return verdict
        else:
            verdict.update(status="PARTIAL", reason="G2: 无 S 参数产物（数值面证据缺）")
            save_verdict(run_dir, verdict)
            return verdict

    # G3 数值健康（有限+无源；单激励部分矩阵全项无源性按掩码语义从宽）
    finite = bool(np.all(np.isfinite(s)))
    passive = bool(np.all(np.abs(s) <= 1.05))
    verdict["g3_finite"] = finite
    verdict["g3_passive_le_1p05"] = passive
    verdict["shape"] = list(s.shape)
    if not finite:
        verdict["status"] = "FAIL"
        verdict["reason"] = "G3: S 含非有限值"
    elif not passive:
        verdict["status"] = "FAIL"
        verdict["reason"] = "G3: 无源性 |S|>1.05"
    elif not verdict["solve_success"]:
        verdict["status"] = "PARTIAL"
        verdict["reason"] = "求解器报告未正常结束（数值面健康，如超时截断）"
    else:
        verdict["status"] = "PASS"

    # G5 health gate（best-effort #105）
    try:
        hc = health_check_run(run_dir.name, runs_dir=str(out_root))
        verdict["g5_health"] = {k: hc.get(k) for k in ("verdict", "ok") if k in hc}
    except Exception as exc:
        verdict["g5_health"] = {"error": str(exc)[:120]}

    # nrts_converged 判读门（wf:nrts-fix，#266 口径）：触 NrTS 帽且能量未达
    # EndCriteria=截断非物理，PASS 如实降 FAIL；证据缺=留痕不判（#105/#122）
    try:
        verdict = apply_nrts_gate(verdict, nrts_converged_gate(run_dir))
    except Exception as exc:   # best-effort：门不得成为主路径故障点
        verdict["nrts_converged"] = {"ok": None, "reason": f"gate error: {exc}"}

    save_verdict(run_dir, verdict)
    return verdict


# ── 战役退出码（H1-5 修复面：座位状态聚合；消费方按此判链）────────────────
EXIT_OK = 0              # 全座 PASS
EXIT_LAUNCH_ERROR = 1    # 发射面异常（--remote 机器解析失败/驱动级未捕获异常）
EXIT_SEAT_FAIL = 2       # 任一座 FAIL（优先于 SKIP）
EXIT_SEAT_SKIP = 3       # 任一座 SKIP（无 FAIL 时）
EXIT_SEAT_NOT_PASS = 4   # 无 FAIL/SKIP 但存在非 PASS 座位（PARTIAL/未知状态）
EXIT_USAGE = 64          # argparse 用法错（自定义，避开 rc2 双义，H1-6 同族）


def campaign_exit_code(statuses: Iterable[object]) -> int:
    """座位状态序列 → 战役主退出码（纯函数，离线可测）。

    预声明优先级（H1-5：失败比跳过/降档更需要人介入，故 FAIL > SKIP >
    非 PASS > 全 PASS）：任一座 FAIL=2；否则任一座 SKIP=3；否则全 PASS=0；
    其余（PARTIAL/未知状态）=4；空序列=发射面异常 1（一个座位都没跑）。
    链式消费方只在 0 时串发下一项（修复前恒 0——全座 SKIP 被记成链完毕，
    oe_chain.log 2026-10-03 K-7 实证）。
    """
    sts = [str(s) for s in statuses]
    if not sts:
        return EXIT_LAUNCH_ERROR
    if any(s == "FAIL" for s in sts):
        return EXIT_SEAT_FAIL
    if any(s == "SKIP" for s in sts):
        return EXIT_SEAT_SKIP
    if all(s == "PASS" for s in sts):
        return EXIT_OK
    return EXIT_SEAT_NOT_PASS


def campaign_exit_code_from_summary(path: str | Path) -> int:
    """座位结果文件（campaign_summary.json）→ 退出码（消费面入口）。

    驱动批尾与 oe_chain 预检共用同一判定：文件缺/损坏/非 dict=发射面异常
    （EXIT_LAUNCH_ERROR），不猜不凑（#122）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return EXIT_LAUNCH_ERROR
    if not isinstance(data, dict):
        return EXIT_LAUNCH_ERROR
    statuses = [v.get("status", "?") if isinstance(v, dict) else "?"
                for v in data.values()]
    return campaign_exit_code(statuses)


def format_seat_line(counts: dict, rc: int) -> str:
    """批尾日志行（H1-5 规定格式）：seats=N pass=N skip=N fail=N rc=X。"""
    return (f"seats={sum(counts.values())} pass={counts.get('PASS', 0)} "
            f"skip={counts.get('SKIP', 0)} fail={counts.get('FAIL', 0)} "
            f"rc={rc}")


class _Parser(argparse.ArgumentParser):
    """argparse 用法错退出码改 64（BSD EX_USAGE 惯例）：rc2 已语义化为
    「任一座 FAIL」（H1-5），用法错若仍落 2 即双义（H1-6 同族）——链式
    消费方按 rc 判链时会把调用方笔误误读成战役失败。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    parser.add_argument("--only", default="", help="逗号分隔模板子集")
    parser.add_argument("--timeout", type=float, default=2400.0)
    parser.add_argument("--nrts", type=int, default=0,
                        help="显式 NrTS 覆盖（探针/复跑用；缺省 0=F-D 接线缺省）")
    parser.add_argument("--end-criteria", type=float, default=0.0,
                        help="显式 EndCriteria 覆盖（缺省 0=F-D 接线 1e-6）")
    parser.add_argument("--remote", nargs="?", const="", default=None,
                        metavar="MACHINE",
                        help="战役路由到注册表远程机器（v1 调度面）：逐座发射前 "
                             "license 预检 fail-closed（license 端口不通→该座 "
                             "SKIP 不硬打）；预检过=真实远程执行通道（remote_oe_"
                             "service：G1 本地渲染→服务器侧点驱动真跑，互斥命中"
                             "=候跑 SKIP→产物回拉镜像 runs/ge_fd/<t>/→判读零改"
                             "动直读）。不带值=唯一登记机器；缺省（不带 "
                             "--remote）=local 行为零变化")
    return parser


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """argparse 解析薄壳（argv=None=sys.argv；单测钉参数形态用）。"""
    return _build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    remote_machine: str | None = None
    if args.remote is not None:
        try:
            remote_machine = _resolve_remote_machine(args.remote)
        except ValueError as exc:
            # 发射面异常=rc 1（H1-5 退出码表）：战役未启动、零座位，
            # 不进编排层（旧 parser.error 路径会让 rc2=座位 FAIL 双义）。
            print(f"[fd] --remote 机器解析失败: {exc}", file=sys.stderr,
                  flush=True)
            return EXIT_LAUNCH_ERROR

    targets = [t.strip() for t in args.only.split(",") if t.strip()] or TARGETS

    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver
    from rfauto.adapters.openems_templates import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    out_root = Path("runs") / "ge_fd"
    out_root.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}

    for template in targets:
        run_dir = out_root / template
        run_dir.mkdir(parents=True, exist_ok=True)
        verdict: dict = {"template": template, "started": time.strftime("%F %T")}

        if template not in TEMPLATE_META:
            verdict.update(status="SKIP", reason="未注册模板")
            save_verdict(run_dir, verdict)
            summary[template] = verdict
            continue

        meta = TEMPLATE_META[template]
        f0 = float(meta["f0_ghz"])
        band = (0.8 * f0, 1.2 * f0)

        # 名义参数真传入（审查轨 B P1-1：META["params"] 存键名，值在
        # TEMPLATE_NOMINAL——旧写法恒 {}，ms 族曾在 h=0.508 缺省上跑）
        params = dict(TEMPLATE_NOMINAL.get(template, {}))
        # 显式覆盖旋钮（c3 先例 #266；缺省不注入=渲染链 F-D 接线缺省生效）
        if args.nrts:
            params["_nrts"] = int(args.nrts)
        if args.end_criteria:
            params["_end_criteria"] = float(args.end_criteria)
        mesh = float(meta.get("mesh_resolution_mm") or 0.0)
        solve_mesh = mesh if mesh > 0 else 0.4

        # --remote 座位级门+执行通道（v1 接线）：G1 渲染在本地（参数/网格/
        # NrTS 与 local 逐字节同源），license 预检 fail-closed→真实远程执行
        # （互斥命中=候跑 SKIP）→产物回拉 run_dir→判读共用尾。缺省（--remote
        # 未给）零行为变化。
        if remote_machine is not None:
            try:
                text, rmeta = _render_seat_text(
                    template, params, band, solve_mesh)
                verdict.update(rmeta)
                script = run_dir / "simulation.py"
                script.write_text(text, encoding="utf-8")
            except _RenderSeatError as exc:
                verdict.update(exc.meta)
                verdict.update(status="FAIL", reason=str(exc))
                save_verdict(run_dir, verdict)
                summary[template] = verdict
                tag = "G1 literal" if exc.literal else "G1"
                print(f"[fd] {template}: FAIL ({tag})", flush=True)
                continue
            except Exception as exc:
                verdict.update(
                    status="FAIL",
                    reason=f"G1 渲染: {type(exc).__name__}: {str(exc)[:160]}")
                save_verdict(run_dir, verdict)
                summary[template] = verdict
                print(f"[fd] {template}: FAIL (G1)", flush=True)
                continue
            verdict["g1_render"] = True
            verdict["mesh_mm"] = solve_mesh
            seat_spec = {
                "template": template,
                "simulation_py": text,
                "criteria_md": _seat_criteria_text(out_root),
                "timeout_s": float(args.timeout),
                "campaign": "ge_fd",
                "render_sha256": verdict.get("render_input_sha256"),
            }
            t0 = time.time()
            gate = remote_seat_gate(remote_machine, _license_preflight,
                                    execute_fn=_remote_oe_run,
                                    seat_spec=seat_spec)
            verdict.update(gate)
            pre_v = (gate.get("license_preflight") or {}).get("verdict")
            if gate.get("status") in ("SKIP", "FAIL"):
                save_verdict(run_dir, verdict)
                summary[template] = verdict
                print(f"[fd] {template}: {gate['status']} "
                      f"(remote gate: preflight={pre_v})", flush=True)
                continue
            # 通道 ok：产物已回拉 run_dir——判读共用尾（disk 收割/portless
            # 改道/G3/G5/nrts 与 local 同判，判读器零改动直读）
            verdict["wall_s"] = round(time.time() - t0, 1)
            with contextlib.suppress(Exception):
                verdict["artifacts"] = _harvest_artifacts(run_dir)
            verdict = _judge_and_save(
                verdict, run_dir, out_root,
                _RemoteSolveResult(success=bool(gate.get("solve_success"))))
            summary[template] = verdict
            print(f"[fd] {template}: {verdict['status']} "
                  f"wall={verdict['wall_s']}s (remote={remote_machine})",
                  flush=True)
            continue

        # G1 渲染（异常即 FAIL；几何审计由各模板 #212 单测承担，此处渲染通过即可）
        try:
            text: str
            text, rmeta = _render_seat_text(
                template, params, band, solve_mesh)
            verdict.update(rmeta)
            script = run_dir / "simulation.py"
            script.write_text(text, encoding="utf-8")
        except _RenderSeatError as exc:
            verdict.update(exc.meta)
            verdict.update(status="FAIL", reason=str(exc))
            save_verdict(run_dir, verdict)
            summary[template] = verdict
            tag = "G1 literal" if exc.literal else "G1"
            print(f"[fd] {template}: FAIL ({tag})", flush=True)
            continue
        except Exception as exc:
            verdict.update(status="FAIL",
                           reason=f"G1 渲染: {type(exc).__name__}: {str(exc)[:160]}")
            save_verdict(run_dir, verdict)
            summary[template] = verdict
            print(f"[fd] {template}: FAIL (G1)", flush=True)
            continue
        verdict["g1_render"] = True
        verdict["mesh_mm"] = solve_mesh

        # G2 真跑（solo 串行）
        t0 = time.time()
        try:
            solver = OpenEMSSolver(EMSolverConfig(
                solver_type="openems", exe_path=resolve_openems_exe(),
                working_dir=str(run_dir), freq_range_ghz=band,
                mesh_resolution_mm=solve_mesh,
                extra_params={"solve_timeout_s": float(args.timeout)}))
            if not solver.connect():
                raise RuntimeError("openEMS 不可用")
            if not solver.build_geometry({"template": template, "params": dict(params)}):
                raise RuntimeError("build_geometry 失败")
            result = solver.solve()
        except Exception as exc:
            # G2 异常路径同样清点产物（#105：证据面缺位要可见，不阻塞主路径）
            verdict["wall_s"] = round(time.time() - t0, 1)
            with contextlib.suppress(Exception):
                verdict["artifacts"] = _harvest_artifacts(run_dir)
            verdict.update(status="FAIL",
                           reason=f"G2 求解: {type(exc).__name__}: {str(exc)[:160]}")
            save_verdict(run_dir, verdict)
            summary[template] = verdict
            print(f"[fd] {template}: FAIL (G2)", flush=True)
            continue
        wall = time.time() - t0
        verdict["wall_s"] = round(wall, 1)
        verdict["solve_success"] = bool(getattr(result, "success", False))
        # 求解完结必清点产物（无论健康与否；#268 口径 port dump 末行时间轴）
        with contextlib.suppress(Exception):
            verdict["artifacts"] = _harvest_artifacts(run_dir)

        # G2 尾段判读共用体（s 归一三支 → G3 → G5 → nrts 门 → save）
        verdict = _judge_and_save(verdict, run_dir, out_root, result)
        summary[template] = verdict
        print(f"[fd] {template}: {verdict['status']} wall={verdict['wall_s']}s", flush=True)

    summary_path = out_root / "campaign_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for v in summary.values():
        counts[v.get("status", "?")] = counts.get(v.get("status", "?"), 0) + 1
    # H1-5：主退出码按座位状态聚合（消费面经 campaign_exit_code_from_summary
    # 读回刚落盘的座位结果文件判定——生产路径即消费路径，单一事实源）。
    rc = campaign_exit_code_from_summary(summary_path)
    print("[fd] SUMMARY:", json.dumps(counts, ensure_ascii=False), flush=True)
    print(f"[fd] {format_seat_line(counts, rc)}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
