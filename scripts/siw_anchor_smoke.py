"""直 SIW 线段 OE 锚冒烟驱动（siw-family 首族；2026-09-22 备妥，真机锚已落判）。

**已真跑落判**（G1 勘误 PASS/G2 PASS/G3 口径裁定/G4 PASS，
runs/siw_family/；本驱动复跑即重走同链）。预声明门与预算：
runs/siw_family/criteria.md §6（#122：判据先写
后跑，真跑后不因结果改门；#350：AGREE 需幅度差 ≤ 门限且方向一致）。

用法（真跑时）：
    .venv/Scripts/python.exe scripts/siw_anchor_smoke.py --pt pt1
    # 可选：--mesh-mm 0.4 --flo 6.0 --fhi 13.0 --nrts 100000 --timeout-s 6120

口径（criteria §6 预声明，写死不因结果改）：
  频带 (6, 13) GHz（F0=9.5GHz 宽脉冲；6.2GHz 在带内供 G2 波导性滚降门）；
  显式 mesh_resolution_mm=0.4 审计档；NrTS 上限 100000（EndCriteria 缺省
  能量判据自停）；port1 单激励、port2 R=闭式 Z_PV 端接。

预声明门：
  G1（主门，fc10 单参数拟合）  ：带 [9,11]GHz 内 S21 解缠相位对
      φ(f) = −β(f; fc)·L + φ0 做 fc 单参数拟合（φ0 线性消去，variable
      projection；β(f;fc)=(2π/c)·√(εr·f²−fc²)）。
      |fc_fit/fc_closed − 1| ≤ 3% PASS / ≤ 5% PARTIAL / 其余 FAIL；
      fc_fit − fc_closed 符号如实记录（#350 方向项）。
      ⚠ 口径=cps 同款（S21 解缠相位斜率，LumpedPort 无 β）；uf 相位含端口
      分解伪象的风险如实（#161）——G1 FAIL 时双行波拟合口径为 followUp，
      不事后改门。
  G2（波导性滚降）            ：|S21|@6.2GHz ≤ |S21|@10GHz − 15 dB
      （6.2GHz 低于闭式 fc10=6.667GHz，倏逝 α≈97.5 Np/m×63mm≈−53dB，
      15dB 门留足余量）。
  G3（物理量级地板+无源性）    ：max|S21|@[9,11]GHz ≥ −3 dB；
      max(|S11|²+|S21|²) ≤ 1.05（带内）。
  G4（口径自洽）              ：port_beta.csv 实测 plane_dist 与名义
      line_len 差 ≤ 1·BASE（端口元落格尺度，cps 契约）。

预算（#328/#329）：0.4mm 档 ≈0.91M cells（exec 实测 0.84M）；时窗
=NrTS×dt=100000×0.1936ps=19.36ns（终网格实算钉值，dt 为 as-run 引擎
日志实测，同下 v2 段与 criteria §6；单轴 CFL 估计 0.42ps→42ns 是禁用
口径——虚标余量 2.2×，round6 E-LOW 勘误）≥ 需求 ≈19ns（余量紧：
max|S11|>1 先查 NrTS 截断再疑物理，#262）；墙钟预估
≈50min ×2 余量 → timeout 缺省 6120s，solo 单飞（#246）。

互斥（#261）：起跑前命令行查 python 进程含 _rfauto_runner|simulation.py
（临时 .ps1 走 -NoProfile -ExecutionPolicy Bypass，#289）；命中即拒绝起跑
不代杀；探测失败 fail-closed。自身（驱动进程名 siw_anchor_smoke.py）不匹配
该模式——无 #261 自锁（互斥模式自排除纪律）。
锁面（round6 L-E5 裁定）：另占 runs/.oe_collect.lock（O_CREAT|O_EXCL 原子
建、30s 轮询、stale 接管、finally 释放，factory_m4/gysel 家族同式）——
命令行查→起跑之间的一次性 TOCTOU 窗由此收口；#261 查保留作双保险。

端口方案 v2（2026-09-23，runs/siw_family/v2_criteria.md）：
  --port-mode v2 = 藩篱止于端口面+端面口径 LumpedPort（跨介质孔径 ±W/2，
  R=Z_PV 闭式不变）——消除 §R2 归因的端面 fixture 汇（延拓支路 4/9 分光+
  探针中间抽头耗散）后按**原 G3 门（≥−3dB）**重裁；缺省 v1（上列口径）
  渲染逐字节不变。四门与门值零改动（#122）；G1 拟合公式=§R1 勘误口径
  （beta_closed）。v2 预算：终网格最小格逐轴与 v1 实测相同（x 50µm/y 40µm/
  z 127µm，离线 exec）→ 引擎 dt=0.1936ps 同 v1、NrTS=1e5 时窗 19.36ns≥需求
  ~19ns；cells<0.84M、墙钟 ≤v1 实测 210.5s×2（timeout 缺省 6120s 不动），
  solo 单飞。wave2 执行（C14a 轨让位后）：
      .venv/Scripts/python.exe scripts/siw_anchor_smoke.py --port-mode v2 --pt pt2_v2

**R*=2·Z_PV/π=14.5402Ω 旋钮语义收档（2026-09-24 df6 A2）**：该备选是 siw
LumpedPort 端口的条件触发 followUp（v2_criteria.md §2：v2 真跑带内
max|S11|²>0.5 才触发）。本驱动新增的 MSL 线基端口口径（--template
msl_siw_taper）下该旋钮**语义废弃**——MSLPort 无 R_PORT 常数、匹配由锥形
几何承担，Z_PV 只进锥末宽度设计式；触发条件仅对 siw v2 路线有效，历史档
不删（#122 收档纪律）。

msl_siw_taper 模板点（2026-09-24 df6 A2，runs/df6_a2siwmsl/criteria.md §4
预声明）：--template msl_siw_taper。频带 (6,13)/0.4mm 审计档/NrTS=100000/
#261 互斥与 siw 全同；四门：
  G1'（fc10 相位拟合）        ：带 [9,11] S21 解缠相位对 φ(f)=−β(f;fc)·L_siw
      +(a+b·f) 拟合（fc 非线性单参+a/b 线性消去——线性项吸收 MSL 馈线+锥
      群延迟，vpair=variable projection）；L_siw=名义 siw_len（渲染字面）。
      |fc_fit/6.6667−1|≤3% PASS / ≤5% PARTIAL / 其余 FAIL；符号如实。
  G2（波导性滚降，沿用）      ：|S21|@6.2GHz ≤ |S21|@10GHz − 15dB。
  G3'（匹配+传输+无源性）     ：带 [9,11] max|S11| ≤ −15dB（RL>15dB 起步门）
      且 max|S21| ≥ −1.5dB（预算预期 ≈−0.6dB，criteria §4）且
      max(|S11|²+|S21|²) ≤ 1.05；RL 臂单落 (−15,−12]dB 记 PARTIAL。
  G4'（口径自洽）             ：port_beta.csv plane_dist 与 2·(DOM_Y−
      FEED_LEN/3) 名义差 ≤1·BASE（layout 单源同参复算）。
  INFO：max|S11|² 仪表化（g3.s11_max_pow_in_band，两模板一并生效——纯新增
  字段，siw 门逻辑/门值零改动）；--line-z0 engine 时端口引擎自算 ZL 中位与
  偏差（#250/#280 诊断面；S 重归一走 rotation 链 followUp——单激励部分
  矩阵掩码纪律 #314，不在本驱动内做整矩阵 renorm）。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.adapters.openems_templates import (  # noqa: E402
    TEMPLATE_NOMINAL,
    msl_siw_taper_layout,
    render_script,
)

C0 = 299792458.0
ER = 3.66
FC10_CLOSED_GHZ = 10.0 / 1.5          # 闭式 fc10=6.6667GHz（criteria §2）
LINE_LEN_MM = 63.0724                  # 名义两端口面间距（闭式链 4 位舍入）
G1_BAND_GHZ = (9.0, 11.0)
G2_F_GHZ = 6.2
G2_REF_GHZ = 10.0
G3_BAND_GHZ = (9.0, 11.0)
#: 预声明门限（#122 不因结果改门）
G1_PASS_PCT = 3.0
G1_PARTIAL_PCT = 5.0
G2_ROLLOFF_DB = 15.0
G3_S21_MIN_DB = -3.0
G3_PASSIVITY_MAX = 1.05
# msl_siw_taper G3' 门（runs/df6_a2siwmsl/criteria.md §4 预声明，#122）
G3M_S11_MAX_DB = -15.0        # RL>15dB 起步门
G3M_S11_PARTIAL_DB = -12.0    # RL 臂单落 (−15,−12] 记 PARTIAL
G3M_S21_MIN_DB = -1.5         # 传输连续门（预算预期 ≈−0.6dB）


def oe_foreign_running() -> list[str]:
    """#261 互斥查（factory_g2_collect 同式；fail-closed）。"""
    root = REPO / "runs" / "siw_family"
    root.mkdir(parents=True, exist_ok=True)
    ps1 = root / "_oe_proc_check.ps1"
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match '_rfauto_runner|simulation\\.py' "
        "} | ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }\n",
        encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        ps1.unlink(missing_ok=True)
    if out.returncode != 0:
        raise RuntimeError(
            f"#261 进程查询失败 rc={out.returncode}: {out.stderr[:300]}")
    own = str(os.getpid())
    return [ln.strip() for ln in (out.stdout or "").splitlines()
            if ln.strip() and not ln.strip().startswith(own + "\t")]


# ── 共享锁面（round6 L-E5 裁定：并入 .oe_collect.lock 家族单锁面）──────────
# v1/v2 原只有一次性 #261 命令行查（查询→起跑之间分钟级 TOCTOU 窗，查后
# 他轨仍可起跑且互相不可见）。O_CREAT|O_EXCL 原子占锁对"同锁面消费者"
# 无 TOCTOU（建文件即占位，他轨原子可见）；#261 命令行查保留作 belt-and-
# braces（factory_m4/gysel/marchand 同为锁+查双保险）。#261 查→占锁之间
# 的残余窗口=非同锁面对象，任何脚本侧锁无法消除，如实记账不声称全消除。
LOCK_PATH = REPO / "runs" / ".oe_collect.lock"
LOCK_POLL_S = 30.0


def _pid_alive(pid: int) -> bool:
    """进程存活探测（Get-Process）；探测失败按存活（不误抢陈锁）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"if (Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue) "
             f"{{ Write-Output ALIVE }}"],
            capture_output=True, text=True, timeout=30)
        return "ALIVE" in (out.stdout or "")
    except Exception:
        return True


def _lock_owner() -> dict | None:
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def lock_acquire(timeout_s: float) -> dict:
    """runs/.oe_collect.lock O_CREAT|O_EXCL 原子占锁；被占 30s 轮询；
    持有进程已死（stale）→ 记录后接管（factory_m4 同式）。返回
    {acquired, attempts, waited_s, owner}。"""
    t0 = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        try:
            fd = os.open(str(LOCK_PATH), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"pid": os.getpid(), "task": "siw_anchor_smoke",
                     "ts": datetime.now(timezone.utc).isoformat()},
                    ensure_ascii=False))
            return {"acquired": True, "attempts": attempts,
                    "waited_s": round(time.monotonic() - t0, 1), "owner": None}
        except FileExistsError:
            owner = _lock_owner()
            if isinstance(owner, dict) and isinstance(owner.get("pid"), int) \
                    and not _pid_alive(int(owner["pid"])):
                try:
                    LOCK_PATH.unlink()
                    print(f"[siw-anchor][lock] stale 锁接管：owner={owner}")
                except OSError:
                    pass  # 他进程同时接管：下一轮重试
                continue
            if time.monotonic() - t0 > timeout_s:
                return {"acquired": False, "attempts": attempts,
                        "waited_s": round(time.monotonic() - t0, 1),
                        "owner": owner}
            time.sleep(LOCK_POLL_S)


def lock_release() -> None:
    """释放锁（幂等：不存在则吞；异常不阻断判读收尾）。"""
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[siw-anchor][lock] 释放异常（不阻断）：{exc!r}")


def beta_closed(f_hz: np.ndarray, fc10_ghz: float, er: float = ER) -> np.ndarray:
    """等效 RWG TE10 闭式 β(f; fc)：(2π/c)·√(εr·(f²−fc²))；f<fc 为 NaN。

    fc10=介质填充实际截止 c/(2·w_eff·√εr)，f 与 fc 同单位 Hz。
    §2 钉值互洽校验：β(f0=10GHz, fc10=6.6667, εr=3.66)≈298.8 rad/m
    （λg≈21.02mm）。不得写成 √(εr·f²−fc²)——那是空波导截止口径，与
    fc10 的实际截止定义不自洽（f=fc 时 β≠0 非物理，pt1 as-run 判读
    假 FAIL 根因之一，2026-09-23 勘误）。
    """
    f = np.asarray(f_hz, dtype=float)
    fc = fc10_ghz * 1e9
    k0 = 2.0 * np.pi * f / C0
    val = er * (f**2 - fc**2)
    out = np.where(val > 0.0,
                   k0 * np.sqrt(np.maximum(val, 0.0)) / f, np.nan)
    return out


def fit_fc10(f_hz: np.ndarray, s21: np.ndarray, plane_dist_m: float,
             fc_lo_ghz: float = 5.0, fc_hi_ghz: float = 8.5) -> dict:
    """G1：S21 解缠相位对 φ(f)=−β(f;fc)·L+φ0 做 fc 单参数拟合（φ0 线性消去）。

    返回 {fc_fit_ghz, dev_pct, sign, rms_rad}；fc_closed=闭式 6.6667GHz。
    """
    from scipy.optimize import minimize_scalar

    sel = ((f_hz >= G1_BAND_GHZ[0] * 1e9) & (f_hz <= G1_BAND_GHZ[1] * 1e9))
    f_sel = f_hz[sel]
    phase = np.unwrap(np.angle(s21[sel]))

    def err(fc_ghz: float) -> float:
        beta = beta_closed(f_sel, fc_ghz)
        if np.any(~np.isfinite(beta)):
            return float("inf")
        resid = phase + beta * plane_dist_m        # = φ0 + 噪声
        return float(np.sum((resid - resid.mean()) ** 2))

    res = minimize_scalar(err, bounds=(fc_lo_ghz, fc_hi_ghz),
                          method="bounded",
                          options={"xatol": 1e-5})
    fc_fit = float(res.x)
    dev_pct = (fc_fit - FC10_CLOSED_GHZ) / FC10_CLOSED_GHZ * 100.0
    beta_fit = beta_closed(f_sel, fc_fit)
    resid = phase + beta_fit * plane_dist_m
    return {"fc_fit_ghz": round(fc_fit, 5),
            "fc_closed_ghz": round(FC10_CLOSED_GHZ, 5),
            "dev_pct": round(dev_pct, 4),
            "sign": "+" if fc_fit > FC10_CLOSED_GHZ else "-",
            "rms_rad": round(float(np.sqrt(np.mean((resid - resid.mean()) ** 2))),
                             5)}


def fit_fc10_with_linear(f_hz: np.ndarray, s21: np.ndarray,
                         line_len_m: float,
                         fc_lo_ghz: float = 5.0,
                         fc_hi_ghz: float = 8.5) -> dict:
    """G1'（msl_siw_taper）：φ(f)=−β(f;fc)·L_siw+(a+b·f)，fc 非线性单参 +
    a/b 线性消去（variable projection；b 吸收 MSL 馈线+锥群延迟）。

    L_siw=名义 siw_len（渲染字面，m）。fc_closed=6.6667GHz（w_eff 决定，
    与带心无关——criteria §4 口径分列）。
    """
    from scipy.optimize import minimize_scalar

    sel = ((f_hz >= G1_BAND_GHZ[0] * 1e9) & (f_hz <= G1_BAND_GHZ[1] * 1e9))
    f_sel = f_hz[sel]
    phase = np.unwrap(np.angle(s21[sel]))
    basis = np.stack([np.ones_like(f_sel), f_sel - f_sel.mean()], axis=1)

    def err(fc_ghz: float) -> float:
        beta = beta_closed(f_sel, fc_ghz)
        if np.any(~np.isfinite(beta)):
            return float("inf")
        resid = phase + beta * line_len_m          # = a + b·(f−f̄) + 噪声
        coef, *_ = np.linalg.lstsq(basis, resid, rcond=None)
        r = resid - basis @ coef
        return float(np.sum(r ** 2))

    res = minimize_scalar(err, bounds=(fc_lo_ghz, fc_hi_ghz),
                          method="bounded",
                          options={"xatol": 1e-5})
    fc_fit = float(res.x)
    dev_pct = (fc_fit - FC10_CLOSED_GHZ) / FC10_CLOSED_GHZ * 100.0
    beta_fit = beta_closed(f_sel, fc_fit)
    resid = phase + beta_fit * line_len_m
    coef, *_ = np.linalg.lstsq(basis, resid, rcond=None)
    r = resid - basis @ coef
    return {"fc_fit_ghz": round(fc_fit, 5),
            "fc_closed_ghz": round(FC10_CLOSED_GHZ, 5),
            "dev_pct": round(dev_pct, 4),
            "sign": "+" if fc_fit > FC10_CLOSED_GHZ else "-",
            "rms_rad": round(float(np.sqrt(np.mean(r ** 2))), 5),
            "fit_model": "phi=-beta*L+ (a+b*f) linear-absorbed"}


def db(x: np.ndarray | float) -> np.ndarray:
    v = np.abs(np.asarray(x))
    return 20.0 * np.log10(np.maximum(v, 1e-300))


def main() -> int:
    ap = argparse.ArgumentParser(description="直 SIW 线段 OE 锚冒烟（预声明门）")
    ap.add_argument("--pt", default="pt1")
    ap.add_argument("--template", choices=("siw", "msl_siw_taper"),
                    default="siw",
                    help="siw=直 SIW 线段（df4f/v2 口径，缺省）；"
                         "msl_siw_taper=MSL 锥形过渡+SIW 直段（df6 A2，"
                         "criteria runs/df6_a2siwmsl/criteria.md §4）")
    ap.add_argument("--mesh-mm", type=float, default=0.4)
    ap.add_argument("--flo", type=float, default=6.0)
    ap.add_argument("--fhi", type=float, default=13.0)
    ap.add_argument("--nrts", type=int, default=100000)
    ap.add_argument("--timeout-s", type=float, default=6120.0)
    ap.add_argument("--port-mode", choices=("v1", "v2"), default="v1",
                    help="端口方案（仅 --template siw）：v1=z 桥（df4f 口径，"
                         "缺省）；v2=藩篱止于端口面+端面口径（v2_criteria.md，"
                         "按原门重裁 G3）")
    ap.add_argument("--line-z0", choices=("none", "engine"), default="none",
                    help="engine=判读侧回读端口引擎自算 ZL（#250/#280 诊断"
                         "面：ZL 中位与偏差进 summary INFO；S 整矩阵重归一走 "
                         "rotation 链 followUp，#314 部分矩阵掩码纪律）；"
                         "none=主口径 ref=50 不动（缺省）")
    ap.add_argument("--skip-mutex", action="store_true",
                    help="跳过 #261 互斥查询（仅调试用；.oe_collect.lock "
                         "与真跑 OE 不受影响）")
    ap.add_argument("--lock-wait-s", type=float, default=1800.0,
                    help=".oe_collect.lock 忙等上限 s（30s 轮询，stale 接管；"
                         "超时拒跑不代杀）")
    args = ap.parse_args()

    if not args.skip_mutex:
        foreign = oe_foreign_running()
        if foreign:
            print("[siw-anchor] #261 互斥命中（他轨 OE 在跑，拒绝起跑，不代杀）：")
            for ln in foreign[:10]:
                print("   ", ln)
            return 2
        print("[siw-anchor] #261 命令行查：无他轨 OE 进程，起跑")

    lock = lock_acquire(args.lock_wait_s)
    if not lock["acquired"]:
        print(f"[siw-anchor] .oe_collect.lock 占锁失败（owner={lock['owner']}"
              f"，忙等 {lock['waited_s']:.0f}s 超时）——拒绝起跑，不代杀")
        return 3
    print(f"[siw-anchor] .oe_collect.lock 已占（attempts={lock['attempts']}，"
          f"waited={lock['waited_s']}s）")
    try:
        return run_smoke(args)
    finally:
        lock_release()


def run_smoke(args: argparse.Namespace) -> int:
    """渲染+求解+门判读（.oe_collect.lock 持有期内执行；互斥/锁在 main）。

    --template siw（缺省）：df4f/v2 四门口径（本函数上半）零改动——仅 G3
    增加 s11_max_pow_in_band 仪表化字段（纯新增，门逻辑不变）。
    --template msl_siw_taper：G1'/G2/G3'/G4'（runs/df6_a2siwmsl/criteria.md
    §4 预声明），判读共用本文件闭式与 db()。
    """
    is_msl = args.template == "msl_siw_taper"
    out_dir = REPO / "runs" / ("df6_a2siwmsl" if is_msl else "siw_family") / args.pt
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 渲染（显式审计档 + NrTS 旋钮；criteria §6 运行口径）─────────────────
    band = (args.flo, args.fhi)
    if is_msl:
        params = {**TEMPLATE_NOMINAL["msl_siw_taper"], "_nrts": args.nrts}
    else:
        params = {**TEMPLATE_NOMINAL["siw"], "_nrts": args.nrts}
    if args.port_mode == "v2" and not is_msl:
        params["_port_mode"] = "v2"
    text = render_script(args.template, params, band,
                         mesh_resolution_mm=args.mesh_mm)
    sim_path = out_dir / "simulation.py"
    sim_path.write_text(text, encoding="utf-8")

    t0 = time.time()
    py = str(REPO / ".venv" / "Scripts" / "python.exe")
    proc = subprocess.run(
        [py, "-u", str(sim_path)],
        cwd=str(out_dir), capture_output=True, text=True,
        timeout=args.timeout_s)
    solve_wall = time.time() - t0
    (out_dir / "run_stdout.log").write_text(
        f"rc={proc.returncode}\n\n{proc.stdout}\n\n{proc.stderr}",
        encoding="utf-8")
    if proc.returncode != 0:
        print(f"[siw-anchor] 求解失败 rc={proc.returncode}（详见 "
              f"{out_dir / 'run_stdout.log'}）")
        (out_dir / "summary.json").write_text(json.dumps({
            "ok": False, "stage": "solve",
            "rc": proc.returncode, "wall_s": round(solve_wall, 1),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return 1

    # ── 判读（预声明门 criteria §6 / df6 criteria §4）───────────────────────
    with open(out_dir / "sparams.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    head = rows[0]
    i_f = head.index("freq_hz")
    i_s11 = (head.index("re_S11"), head.index("im_S11"))
    i_s21 = (head.index("re_S21"), head.index("im_S21"))
    arr = np.asarray([[float(r[i]) for i in range(len(head))] for r in rows[1:]])
    f_hz = arr[:, i_f]
    s11 = arr[:, i_s11[0]] + 1j * arr[:, i_s11[1]]
    s21 = arr[:, i_s21[0]] + 1j * arr[:, i_s21[1]]

    def s_db_at(x: np.ndarray, f_ghz: float) -> float:
        j = int(np.argmin(np.abs(f_hz - f_ghz * 1e9)))
        return float(db(x[j]))

    sel3 = ((f_hz >= G3_BAND_GHZ[0] * 1e9) & (f_hz <= G3_BAND_GHZ[1] * 1e9))
    s11_max_pow = round(float(np.max(np.abs(s11[sel3]) ** 2)), 4)

    if is_msl:
        # G1'（fc10 相位拟合，线性项吸收馈线/锥群延迟；L_siw=名义渲染字面）
        with open(out_dir / "port_beta.csv", newline="") as fh:
            beta_rows = list(csv.DictReader(fh))
        plane_dist = float(beta_rows[0]["plane_dist_m"])
        lay = msl_siw_taper_layout(
            dict(TEMPLATE_NOMINAL["msl_siw_taper"]), band,
            args.mesh_mm * 1e-3,
            float(TEMPLATE_NOMINAL["msl_siw_taper"]["h_mm"]) * 1e-3)
        line_len_m = lay["siw_len"]
        g1 = fit_fc10_with_linear(f_hz, s21, line_len_m)
        g1_verdict = ("PASS" if abs(g1["dev_pct"]) <= G1_PASS_PCT
                      else "PARTIAL" if abs(g1["dev_pct"]) <= G1_PARTIAL_PCT
                      else "FAIL")
        # G2（波导性滚降，沿用 siw 口径）
        g2 = {"s21_db_at_6g2": round(s_db_at(s21, G2_F_GHZ), 3),
              "s21_db_at_10g": round(s_db_at(s21, G2_REF_GHZ), 3)}
        g2["rolloff_db"] = round(g2["s21_db_at_10g"]
                                 - g2["s21_db_at_6g2"], 3)
        g2_verdict = "PASS" if g2["rolloff_db"] >= G2_ROLLOFF_DB else "FAIL"
        # G3'（匹配+传输+无源性；RL 臂单落 (−15,−12] 记 PARTIAL）
        s11_max_db = round(float(np.max(db(s11[sel3]))), 3)
        s21_max_db = round(float(np.max(db(s21[sel3]))), 3)
        passivity_max = round(float(np.max(np.abs(s11[sel3]) ** 2
                                           + np.abs(s21[sel3]) ** 2)), 4)
        g3 = {"s11_max_db_in_band": s11_max_db,
              "s21_max_db_in_band": s21_max_db,
              "passivity_max": passivity_max,
              "s11_max_pow_in_band": s11_max_pow}
        g3_verdict = "FAIL"
        if (s21_max_db >= G3M_S21_MIN_DB
                and passivity_max <= G3_PASSIVITY_MAX):
            if s11_max_db <= G3M_S11_MAX_DB:
                g3_verdict = "PASS"
            elif s11_max_db <= G3M_S11_PARTIAL_DB:
                g3_verdict = "PARTIAL"
        # G4'（口径自洽：plane_dist vs 2·(DOM_Y−FEED_LEN/3)，layout 同参复算）
        nominal_plane_dist = 2.0 * (lay["dom_y"] - lay["feed_len"] / 3.0)
        g4 = {"plane_dist_m": plane_dist,
              "nominal_plane_dist_m": round(nominal_plane_dist, 9),
              "diff_cells": round(abs(plane_dist - nominal_plane_dist)
                                  / (args.mesh_mm * 1e-3), 3)}
        g4_verdict = "PASS" if g4["diff_cells"] <= 1.0 else "FAIL"
        verdicts = {"G1_fc_fit": g1_verdict, "G2_rolloff": g2_verdict,
                    "G3_rl_tx_passivity": g3_verdict,
                    "G4_plane_dist": g4_verdict}
        verdict = ("PASS" if all(v == "PASS" for v in verdicts.values())
                   else "PARTIAL" if all(v in ("PASS", "PARTIAL")
                                         for v in verdicts.values())
                   else "FAIL")
        if args.line_z0 == "engine":
            g3["zl_engine_info"] = _engine_zl_info(out_dir, f_hz)
        summary = {
            "ok": True,
            "template": "msl_siw_taper",
            "pt": args.pt,
            "band_ghz": list(band),
            "mesh_resolution_mm": args.mesh_mm,
            "nrts": args.nrts,
            "solve_wall_s": round(solve_wall, 1),
            "ts": datetime.now(timezone.utc).isoformat(),
            "gates": {"G1": g1, "G2": g2, "G3": g3, "G4": g4},
            "verdicts": verdicts,
            "verdict": verdict,
            "criteria": "runs/df6_a2siwmsl/criteria.md §4（预声明 #122）",
        }
        (out_dir / "summary.json").write_text(json.dumps(
            summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        print(f"[siw-anchor] {args.pt} template=msl_siw_taper verdict="
              f"{verdict} (G1' {g1_verdict} dev={g1['dev_pct']:+.2f}%, "
              f"G2 {g2_verdict}, G3' {g3_verdict} "
              f"RL={g3['s11_max_db_in_band']}dB, G4 {g4_verdict})")
        return 0

    # ── siw（缺省）：df4f/v2 四门（原路径，仅 G3 增仪表化字段）───────────────
    with open(out_dir / "port_beta.csv", newline="") as fh:
        beta_rows = list(csv.DictReader(fh))
    plane_dist = float(beta_rows[0]["plane_dist_m"])
    port_y1 = float(beta_rows[0]["port_y1_m"])
    port_y2 = float(beta_rows[0]["port_y2_m"])

    base = args.mesh_mm * 1e-3  # BASE（显式档；自动档时≈λ_sub/50，仅作 G4 尺度）
    line_len_m = LINE_LEN_MM * 1e-3

    g1 = fit_fc10(f_hz, s21, plane_dist)
    g1_verdict = ("PASS" if abs(g1["dev_pct"]) <= G1_PASS_PCT
                  else "PARTIAL" if abs(g1["dev_pct"]) <= G1_PARTIAL_PCT
                  else "FAIL")

    g2 = {"s21_db_at_6g2": round(s_db_at(s21, G2_F_GHZ), 3),
          "s21_db_at_10g": round(s_db_at(s21, G2_REF_GHZ), 3)}
    g2["rolloff_db"] = round(g2["s21_db_at_10g"] - g2["s21_db_at_6g2"], 3)
    g2_verdict = "PASS" if g2["rolloff_db"] >= G2_ROLLOFF_DB else "FAIL"

    g3 = {"s21_max_db_in_band": round(float(np.max(db(s21[sel3]))), 3),
          "passivity_max": round(float(np.max(np.abs(s11[sel3]) ** 2
                                              + np.abs(s21[sel3]) ** 2)), 4),
          "s11_max_pow_in_band": s11_max_pow}
    g3_verdict = ("PASS" if (g3["s21_max_db_in_band"] >= G3_S21_MIN_DB
                             and g3["passivity_max"] <= G3_PASSIVITY_MAX)
                  else "FAIL")

    g4 = {"plane_dist_m": plane_dist, "port_y1_m": port_y1, "port_y2_m": port_y2,
          "nominal_line_len_m": line_len_m,
          "diff_cells": round(abs(plane_dist - line_len_m) / base, 3)}
    g4_verdict = "PASS" if g4["diff_cells"] <= 1.0 else "FAIL"

    verdicts = {"G1_fc_fit": g1_verdict, "G2_rolloff": g2_verdict,
                "G3_floor_passivity": g3_verdict, "G4_plane_dist": g4_verdict}
    verdict = ("PASS" if all(v == "PASS" for v in verdicts.values())
               else "PARTIAL" if (verdicts["G1_fc_fit"] == "PARTIAL"
                                  and all(v in ("PASS", "PARTIAL")
                                          for v in verdicts.values()))
               else "FAIL")

    summary = {
        "ok": True,
        "template": "siw",
        "pt": args.pt,
        "port_mode": args.port_mode,
        "band_ghz": list(band),
        "mesh_resolution_mm": args.mesh_mm,
        "nrts": args.nrts,
        "solve_wall_s": round(solve_wall, 1),
        "ts": datetime.now(timezone.utc).isoformat(),
        "gates": {"G1": g1, "G2": g2, "G3": g3, "G4": g4},
        "verdicts": verdicts,
        "verdict": verdict,
        "criteria": ("runs/siw_family/v2_criteria.md §4（v2 预声明 #122）"
                     if args.port_mode == "v2" else
                     "runs/siw_family/criteria.md §6（预声明 #122）"),
    }
    (out_dir / "summary.json").write_text(json.dumps(
        summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"[siw-anchor] {args.pt} port_mode={args.port_mode} "
          f"verdict={verdict} "
          f"(G1 {g1_verdict} dev={g1['dev_pct']:+.2f}% sign={g1['sign']}, "
          f"G2 {g2_verdict}, G3 {g3_verdict}, G4 {g4_verdict})")
    return 0


def _engine_zl_info(out_dir: Path, f_hz: np.ndarray) -> dict | None:
    """--line-z0 engine：端口引擎自算 ZL 中位与 50Ω 偏差（#250/#280 诊断面）。

    三面探针文件任一缺失（无 fdtd 产物/审计 dry-run）返回 None 如实降级；
    S 整矩阵重归一不在本驱动做（单激励部分矩阵掩码纪律 #314，rotation 链
    followUp）。
    """
    try:
        from rfauto.adapters.openems_rotation import engine_msl_line_z0
    except Exception:
        return None
    info: dict = {}
    for p in (1, 2):
        try:
            zl = engine_msl_line_z0(out_dir / "fdtd", p, f_hz)
        except Exception:
            zl = None
        if zl is None or not np.all(np.isfinite(zl)):
            info[f"port{p}"] = None
            continue
        sel = (f_hz >= 9e9) & (f_hz <= 11e9)
        med = float(np.median(np.real(zl[sel])))
        info[f"port{p}"] = {"zl_median_ohm": round(med, 3),
                            "dev_pct_vs_50": round((med / 50.0 - 1) * 100, 3)}
    return info


if __name__ == "__main__":
    raise SystemExit(main())
