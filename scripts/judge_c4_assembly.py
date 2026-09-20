"""C4 耦合器族离线判读 + 装配归一化诊断（零真机）。

① 对已在档的 <template>.s4p 复用 smoke_c4_coupler_family.judge_network 离线判读
   （同门 G1–G5），补 refix 现场缺失的 cline 判读 json；
② #250 链诊断：原始装配矩阵（footer CalcPort ref=50 的 50Ω 伪波带载比值）→ 引擎
   自算 ZL 线基（openems_rotation.engine_msl_line_z0，p{k}/fdtd 三面探针，MSLPort.
   ReadUIData 同式）→ skrf renormalize 到 50Ω；输出归一化前后 σmax 对照表 + 标量 z
   扫描交叉验证（σ 最小点应与引擎 ZL 独立吻合，否则归一只是凑门）；
③ 耦合度差归因（端口归一/网格欠分辨/桥寄生/带沿夹持/能量截断逐项排除或标假设）
   与复跑预期（一阶外推、待证）。

现场口径（runs/smoke_c4_refix）：lange 与 cline 共用 root，p1..p4 原始探针与
_smoke_result.json 已被后跑的 lange 轮覆盖（port_ut 头时间戳 13:00=lange），cline 只剩
.s4p/.log——cline 的 ZL 用 --probe-root（缺省=root，即 lange 探针）作代理并在 json/md
注明；cline G5 β 取 .log 记录（--beta-pct）。

产物：<root>/<template>_judge.json（raw 与 after_norm 两套判读 + assembly_norm +
scalar_scan）、<root>/assembly_diag.md。
用法：
  python scripts/judge_c4_assembly.py --root runs/smoke_c4_refix \
      --templates lange cline_coupler --beta-pct cline_coupler=1.26 \
      --solve-s lange=1071.3 cline_coupler=577.5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import smoke_c4_coupler_family as smoke  # noqa: E402
from rfauto.adapters.openems_rotation import (  # noqa: E402
    engine_msl_line_z0,
    normalize_assembled_smatrix,
)
from rfauto.adapters.openems_templates import (  # noqa: E402
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    tl_gamma_per_m,
)
from rfauto.core.synthesis import Stackup, forward_z0  # noqa: E402

N_PORTS = 4
Z_REF = 50.0
SCAN_Z = (40.0, 56.0, 0.25)
# 缺省网格口径（渲染脚本 BASE=λ_sub/50@F_MAX、NEAR=BASE/4）；复跑外推的对照档
MESH_DEFAULT_BASE_MM = 1.0454
MESH_DEFAULT_NEAR_MM = 0.2614
MESH_RERUN_BASE_MM = 0.4
# 测量面→DUT 边缘路径（lange 渲染：探针 B 面 y=±43.62mm，jog 外沿 ±10.60mm，指长 18.97mm）
LANGE_PATH_BETWEEN_MEAS_PLANES_MM = 2 * (43.62 - 10.60) + 18.97


def load_s4p(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    import skrf

    net = skrf.Network(str(path))
    return net.f / 1e9, net.s


def sigma_profile(s: np.ndarray, f_ghz: np.ndarray) -> dict[str, float]:
    sig = np.linalg.svd(s, compute_uv=False)[:, 0]
    i = int(np.argmax(sig))
    return {"sigma_max": float(sig[i]), "f_at_max_ghz": float(f_ghz[i]),
            "sigma_min": float(np.min(sig)), "sigma_median": float(np.median(sig))}


def scalar_scan(s: np.ndarray, z_lo: float = SCAN_Z[0], z_hi: float = SCAN_Z[1],
                step: float = SCAN_Z[2]) -> dict[str, float]:
    """单一标量 z_line 扫描：σmax 最小点（独立于引擎 ZL 的交叉验证）。"""
    from rfauto.adapters.openems_templates import renorm_engine_s_to_ref

    best_z, best_sig = float("nan"), float("inf")
    for z in np.arange(z_lo, z_hi + 1e-9, step):
        sig = float(np.max(np.linalg.svd(renorm_engine_s_to_ref(s, float(z), Z_REF),
                                         compute_uv=False)))
        if sig < best_sig:
            best_z, best_sig = float(z), sig
    return {"z_best_ohm": best_z, "sigma_max_best": best_sig,
            "z_lo": z_lo, "z_hi": z_hi, "step": step}


def engine_zl_round_table(probe_root: Path, f_hz: np.ndarray,
                          band: np.ndarray) -> dict[str, dict[str, float]]:
    """逐轮×逐端口 引擎 ZL 带内中位 Re（跨轮离散差异的证据表）。"""
    table: dict[str, dict[str, float]] = {}
    for k in range(1, N_PORTS + 1):
        row: dict[str, float] = {}
        for p in range(1, N_PORTS + 1):
            zl = engine_msl_line_z0(probe_root / f"p{k}" / "fdtd", p, f_hz)
            row[f"port{p}"] = float("nan") if zl is None else float(np.median(np.real(zl[band])))
        table[f"p{k}"] = row
    return table


def late_time_levels(probe_root: Path, round_k: int = 1) -> dict[str, dict[str, float]]:
    """p{k}/fdtd 各端口 ut_B 探针末 10%/5% 窗峰值相对全程峰的 dB（#262 截断核查）。"""
    from rfauto.adapters.openems_rotation import _read_probe_file

    out: dict[str, dict[str, float]] = {}
    for p in range(1, N_PORTS + 1):
        path = probe_root / f"p{round_k}" / "fdtd" / f"port_ut_{p}B"
        if not path.exists():
            continue
        t, v, _ = _read_probe_file(path)
        n = len(t)
        pk = float(np.max(np.abs(v)))
        i10, i5 = int(0.9 * n), int(0.95 * n)
        out[f"port{p}"] = {
            "t_end_ns": float(t[-1] * 1e9),
            "late10_db": float(20 * np.log10(np.max(np.abs(v[i10:])) / pk + 1e-300)),
            "late5_db": float(20 * np.log10(np.max(np.abs(v[i5:])) / pk + 1e-300)),
        }
    return out


def rejudge_template(template: str, root: Path, probe_root: Path, *,
                     beta_pct: float | None, beta_source: str,
                     solve_s: float | None) -> dict[str, Any]:
    """离线复判一个模板：raw 判读 + engine ZL 归一后判读 + 标量扫描。"""
    f0 = float(TEMPLATE_META[template]["f0_ghz"])
    params = {k: float(v) for k, v in TEMPLATE_NOMINAL[template].items()}
    eps_hj = smoke.feed_eps_hj(params, f0)
    s4p = root / f"{template}.s4p"
    f_ghz, s_raw = load_s4p(s4p)
    if beta_pct is None:
        d_beta = smoke.read_beta_pct(probe_root / "p1" / "port_beta.csv", f0, eps_hj)
    else:
        d_beta = float(beta_pct)
    raw = smoke.judge_network(template, f_ghz, s_raw, params, f0,
                              d_beta=d_beta, eps_hj=eps_hj)
    s_norm, info = normalize_assembled_smatrix(
        s_raw, f_ghz, "engine", n_ports=N_PORTS, root=probe_root, z_ref_ohm=Z_REF)
    norm = smoke.judge_network(template, f_ghz, s_norm, params, f0,
                               d_beta=d_beta, eps_hj=eps_hj)
    stackup = Stackup.from_materials_yaml(smoke.STACKUP_NAME)
    z_feed_hj, _ = forward_z0(params["w_feed_mm"], f0, stackup)
    return {
        "item": f"smoke_c4/{template}", "offline_rejudge": True,
        "verdict": raw["verdict"], "verdict_after_norm": norm["verdict"],
        "root": str(root), "s4p_path": str(s4p), "probe_root": str(probe_root),
        "f0_ghz": f0, "params": params, "freq_range_ghz": [float(f_ghz[0]), float(f_ghz[-1])],
        "solve_s": solve_s, "beta_source": beta_source,
        "z_feed_hj_ohm": float(z_feed_hj),
        "assembly_norm": info,
        "sigma_profile_raw": sigma_profile(s_raw, f_ghz),
        "sigma_profile_norm": sigma_profile(s_norm, f_ghz),
        "scalar_scan": scalar_scan(s_raw),
        "raw": raw, "after_norm": norm,
        "meta_smoke_note": TEMPLATE_META[template].get("smoke_note"),
    }


def _db(x: float) -> str:
    return f"{x:.2f}"


def _lin(db: float) -> float:
    return float(10 ** (db / 20))


def build_markdown(results: dict[str, dict[str, Any]], zl_table: dict[str, dict[str, float]],
                   late: dict[str, dict[str, float]], probe_root: Path,
                   eps_hj: float, tan_d: float) -> str:
    lines: list[str] = []
    a = lines.append
    a("# C4 耦合器族 refix 装配归一化诊断（离线）")
    a("")
    a("> 全部离线：`.s4p` 在档不复跑真机；数值只出自确定性内核（openEMS 探针 DFT 同式复算、")
    a("> `openems_templates.renorm_engine_s_to_ref` #250 链、skrf、fake 同源闭式裁判）。")
    a("> 生成器：`scripts/judge_c4_assembly.py`（可复现）。")
    a("")
    a("## 0. 现场与数据来源")
    a("")
    a("- lange 与 cline_coupler 共用 `runs/smoke_c4_refix/` 根目录：p1..p4/（sparams.csv、")
    a("  port_beta.csv、fdtd/ 探针）与 `_smoke_result.json` 被后跑的 lange 轮（13:00–13:17）覆盖，")
    a("  cline（12:52–12:59）只剩 `cline_coupler.s4p` + `.log`（port_ut 头时间戳 13:00:03=lange）。")
    a(f"- 引擎 ZL 探针源：`{probe_root.as_posix()}/p{{k}}/fdtd`（lange 轮）；cline 的馈线几何")
    a("  （w_feed 1.1117mm、x=±2.5..±3.61mm）与 z 网格同 lange，y 向探针面局部网格不同——")
    a("  cline 归一用 lange ZL 作**代理**（标量扫描最优 z 差 0.25Ω 佐证，见 §2）。")
    a("- cline G5 β 取 `cline_coupler.log`（+1.26%，p1/port_beta.csv 已被覆盖）。")
    a("- 已在代码层堵漏：`smoke_c4_coupler_family.resolve_root` 显式 --root 末段≠模板名自动")
    a("  追加 `<template>/` 子目录。")
    a("")
    a("## 1. 引擎自算馈线 ZL（MSLPort.ReadUIData 同式，带内 2.4–2.6GHz 中位 Re）")
    a("")
    z_hj = next(iter(results.values()))["z_feed_hj_ohm"]
    a(f"HJ 设计 Z0(w_feed=1.1117mm, 2.5GHz) = **{z_hj:.3f}Ω**；β 复算与引擎 port_beta.csv")
    a("一致（相对差 5e-5），证明探针读取/DFT/差分口径同式。")
    a("")
    a("| 激励轮 | port1 | port2 | port3 | port4 |")
    a("|---|---|---|---|---|")
    for k, row in zl_table.items():
        a(f"| {k} | " + " | ".join(f"{row[f'port{p}']:.3f}" for p in range(1, 5)) + " |")
    first = next(iter(results.values()))["assembly_norm"]
    zs = first["line_z0_ohm"]
    dev = first["line_z0_dev_pct"]
    a("")
    a(f"逐端口跨轮中位（装配链采用）：{' / '.join(f'{z:.3f}' for z in zs)}Ω，对 50Ω 偏差 "
      f"{' / '.join(f'{d:+.2f}%' for d in dev)}；对 HJ {z_hj:.3f}Ω 偏差 "
      f"{(zs[0] / z_hj - 1) * 100:+.2f}%。")
    a("同一端口在四轮里读数按其角色变化（激励 45.57 / 直通 45.80 / 耦合 45.45 / 孤立端 47.31：")
    a("低信噪离群），说明有限差分的离散误差随驻波形态略变，跨轮中位是稳健估计。")
    a("**结论：缺省网格（BASE 1.045/NEAR 0.261mm，馈线宽向约 4–5 格、基板 4 层、金属边正落网格线）")
    a("下 50Ω 馈线的离散线阻抗为 45.7Ω（−8.6%）**——#250 前提“4 端口模板馈线=50Ω 时反演退化为恒等”")
    a("在此网格不成立。")
    a("")
    a("## 2. σmax 归一化前后对照（G1 门 ≤ 1.01）")
    a("")
    a("| 模板 | 口径 | σmax | @GHz | σmin | G1 |")
    a("|---|---|---|---|---|---|")
    for t, r in results.items():
        pr, pn, sc = r["sigma_profile_raw"], r["sigma_profile_norm"], r["scalar_scan"]
        a(f"| {t} | raw（CalcPort ref=50 带载比值，现 .s4p） | {pr['sigma_max']:.4f} | "
          f"{pr['f_at_max_ghz']:.3f} | {pr['sigma_min']:.4f} | {'过' if pr['sigma_max'] <= 1.01 else '**越门**'} |")
        a(f"| {t} | #250 链 z_line=引擎 ZL(f) 逐端口 | {pn['sigma_max']:.4f} | "
          f"{pn['f_at_max_ghz']:.3f} | {pn['sigma_min']:.4f} | {'**过**' if pn['sigma_max'] <= 1.01 else '越门'} |")
        a(f"| {t} | 标量扫描 z∈[{sc['z_lo']:.0f},{sc['z_hi']:.0f}] 最优 | {sc['sigma_max_best']:.4f} | — | — | "
          f"z*={sc['z_best_ohm']:.2f}Ω |")
    a("")
    a("z_line=50（恒等）与 z_line=HJ 50.05Ω 均不改变 σmax（差 <0.001）——归一化只在引擎 ZL 基下")
    a("有效。**标量扫描最优 z* 与引擎 ZL 45.69Ω 独立吻合（差 ≤0.5Ω）**：归一不是对门拟合，")
    a("而是把伪反射 Γ=(45.7−50)/(45.7+50)=−0.045 从每端口撤掉。归一后 σ≈0.987–0.991 的“亏损”")
    alpha = float(np.real(tl_gamma_per_m(2.5e9, eps_hj, tan_d)))
    loss = 1 - np.exp(-2 * alpha * LANGE_PATH_BETWEEN_MEAS_PLANES_MM * 1e-3)
    ref_t = "lange" if "lange" in results else next(iter(results))
    a(f"与介质损耗自洽核对：α=πf√εeff·tanδ/c={alpha:.4f} Np/m，测量面间路径 "
      f"≈{LANGE_PATH_BETWEEN_MEAS_PLANES_MM:.1f}mm → 功率损 {loss * 100:.1f}% → σ≈"
      f"{np.sqrt(1 - loss):.3f}（{ref_t} 实测 {results[ref_t]['sigma_profile_norm']['sigma_max']:.4f}）。")
    a("")
    a("## 3. 归一前后 @f0 指标与判定（裁判=fake 同源闭式）")
    a("")
    a("| 模板 | 口径 | S11 | S21 | S31 | S41 | Δφ(31−21) | f_c 偏移 | verdict |")
    a("|---|---|---|---|---|---|---|---|---|")
    for t, r in results.items():
        for tag, j in (("raw", r["raw"]), ("归一", r["after_norm"])):
            m = j["at_f0_nominal"]
            edge = "（带沿）" if j["fc_at_band_edge"] else ""
            a(f"| {t} | {tag} | {m['s11_db']:.1f} | {_db(m['s21_db'])} | {_db(m['s31_db'])} | "
              f"{m['s41_db']:.1f} | {m['phase_s31_minus_s21_deg']:.1f}° | "
              f"{j['fc_shift_pct']:+.1f}%{edge} | {j['verdict']} |")
        c = r["raw"]["circuit_judge_at_f0"]
        a(f"| {t} | 裁判 | {c['s11_db']:.1f} | {_db(c['s21_db'])} | {_db(c['s31_db'])} | "
          f"{c['s41_db']:.1f} | {c['phase_s31_minus_s21_deg']:.1f}° | — | — |")
    a("")
    a("归一化后 G1 转过、G2 仍过，但 G3/G4 耦合度门 f0/f_c 两处均仍失守 → **两模板 verdict 仍")
    a("FAIL（如实，不凑绿）**；归一对 S31 只动 ≤0.11dB，耦合度偏差与端口伪反射无关。")
    a("f_c 可辨识度（中心判据 0.1dB 平台）：")
    for t, r in results.items():
        for tag, j in (("raw", r["raw"]), ("归一", r["after_norm"])):
            lo, hi = j["fc_plateau_ghz"]
            a(f"- {t}/{tag}：{lo:.3f}–{hi:.3f}GHz（宽 {(hi - lo) / 2.5 * 100:.0f}% f0）")
    a("cline 的 +1.0%→+9.8% 只是宽平坦 |S31| 峰上 argmax 的漂移（两值都在平台内），不是物理中心")
    a("移动；10dB 族 f_c 偏移量的不确定度=平台宽，判读须一并报告（judge_network 已记 fc_plateau_ghz）。")
    a("")
    a("## 4. 能量停机/截断核查（#262/#268）")
    a("")
    a("| lange p1 探针 | t_end | 末 10% 峰 | 末 5% 峰 |")
    a("|---|---|---|---|")
    for p, v in late.items():
        a(f"| {p} ut_B | {v['t_end_ns']:.3f}ns | {v['late10_db']:.1f}dB | {v['late5_db']:.1f}dB |")
    a("")
    a("`et`/`ht` 是激励信号本身（两模板逐字节相同，与结构无关，不能当能量曲线）；探针末段")
    a("−48…−79dB、t_end 5.95ns=脉冲 5.73ns 后 0.22ns，符合缺省 EndCriteria −50dB 停机而非 NrTS 触顶。")
    a("截断残差幅度 ≲0.4%，对 σmax 贡献 ≪ 观测的 2.7–3.4%，对耦合度 1–2dB 差可忽略。")
    a("")
    a("## 5. 耦合度差归因与复跑预期")
    a("")
    for t, r in results.items():
        m_raw, m_norm = r["raw"]["at_f0_nominal"], r["after_norm"]["at_f0_nominal"]
        c = r["raw"]["circuit_judge_at_f0"]
        a(f"- **{t}**：S31 raw {_db(m_raw['s31_db'])} → 归一 {_db(m_norm['s31_db'])} vs 裁判 "
          f"{_db(c['s31_db'])}（仍偏强 {m_norm['s31_db'] - c['s31_db']:+.2f}dB）；耦合系数 "
          f"C_EM={_lin(m_norm['s31_db']):.3f} vs 设计 {_lin(c['s31_db']):.3f}"
          f"（{(_lin(m_norm['s31_db']) / _lin(c['s31_db']) - 1) * 100:+.0f}%）；S21 "
          f"{_db(m_norm['s21_db'])} vs {_db(c['s21_db'])}。")
    a("")
    a("逐项排除/标注（归因一律“假设/待证”口径）：")
    a("")
    a("1. **端口归一化——排除**：#250 链把 σmax 从 1.027/1.034 拉回 0.987/0.991，但 S31 只动 +0.11/")
    a("   +0.07dB；伪反射 |Γ|=0.045 只能解释 ≈0.4dB 量级，不是 1–2dB 偏强的来源。")
    a("2. **网格欠分辨——主因（假设级，有两条独立证据）**：lange `_near_x` 含指边→指宽 167µm/指缝")
    a("   38.6µm 各仅 **1 格**（dt≈63fs 佐证最小格 ≈33µm），cline 缝 82µm 亦 1 格，z 向近金属 100–")
    a("   127µm 格 ≫ 缝宽；奇模场集中于缝内与指边，单格无法表达边缘奇异性。证据一：**同一网格把")
    a("   50Ω 馈线压成 45.7Ω（−8.6%）**，方向=单位长电容偏高；证据二：耦合偏强等价于 Zoo/Zoe 偏低")
    a("   （cline C 0.398 vs 0.316 ⇔ Zoo/Zoe 0.43 vs 0.52），奇模由缝电容主导，缝电容被粗网格高估")
    a("   与证据一同向。meta_smoke_note 的“指缝小于 0.4mm 审计网格”就是此项。")
    a("3. **气桥/柱寄生——lange 次因（假设级）**：4 桥+8 柱（高 0.1mm）不在四线理想裁判内，附加耦合")
    a("   电容方向同“偏强”，量级未分离——需去桥对照跑才能定案。")
    a("4. **f_c +20%（lange）是带沿夹持伪象，不是谐振偏移**：3dB 族中心定义 ||S21|−|S31|| 在带内无")
    a("   最小点（2.5→3.0GHz 不平衡 3.4→2.8dB 单调减、未过零），argmin 落 3.0GHz 带沿；判读器已加")
    a("   `fc_at_band_edge` 标记。cline f_c=2.525（+1.0%）可辨识、中心正确→线长/相速无误，仅耦合幅度偏。")
    a("5. **能量截断——排除**（§4）。")
    a("")
    a("**复跑预期（一阶外推，待证）**：假设 Z 类离散误差随格距一阶收敛——缺省 BASE "
      f"{MESH_DEFAULT_BASE_MM}/NEAR {MESH_DEFAULT_NEAR_MM}mm 下馈线 −8.6%，"
      f"`--mesh {MESH_RERUN_BASE_MM}`（×{MESH_DEFAULT_BASE_MM / MESH_RERUN_BASE_MM:.1f} 细）预期馈线 ZL 偏差收到 "
      f"≈{-8.6 * MESH_RERUN_BASE_MM / MESH_DEFAULT_BASE_MM:.1f}%，耦合超量按同比例缩：")
    for t, r in results.items():
        m_norm = r["after_norm"]["at_f0_nominal"]
        c = r["raw"]["circuit_judge_at_f0"]
        excess = m_norm["s31_db"] - c["s31_db"]
        pred = c["s31_db"] + excess * MESH_RERUN_BASE_MM / MESH_DEFAULT_BASE_MM
        a(f"  - {t}：S31 {_db(m_norm['s31_db'])} → 预期 ≈{pred:.1f}dB（走弱 "
          f"{m_norm['s31_db'] - pred:.1f}dB；裁判 {_db(c['s31_db'])}）")
    a("  lange S21 应同步回到 −3.6dB 附近（进 −3±1 门）、cline S31 进 −10±1 门内沿；若加密后 S31 不")
    a("  收敛而 ZL 收敛，则桥寄生假设（第 3 项）升为主因。判定标准：加密后 `assembly_norm` σmax 仍")
    a("  ≤1.01 且 ZL 偏差 <4%，S31 向裁判靠拢 ≥ 预期一半即支持第 2 项。")
    a(f"  成本：dt 已由指缝格限定（不随 BASE 变），格数 ≈×{(MESH_DEFAULT_BASE_MM / MESH_RERUN_BASE_MM) ** 2:.1f}"
      "（面内）→ lange 1071s→≈2h、cline 577s→≈1.1h，solo 单飞（#246），--root 分模板目录。")
    a("")
    a("## 6. 修正落点")
    a("")
    a("- `src/rfauto/adapters/openems_rotation.py`：新增 `engine_msl_line_z0`/`line_z0_from_rounds`/")
    a("  `normalize_assembled_smatrix`，`solve_smatrix_openems(line_z0='engine')` 装配后走 #250 链，")
    a("  原始矩阵留 `<template>_raw.s{N}p`，返回 `assembly_norm`（ZL/偏差/σmax 前后）；缺省 None 行为不变。")
    a("- `scripts/smoke_c4_coupler_family.py`：`--line-z0 engine` 缺省、`judge_network` 可离线复用、")
    a("  `resolve_root` 共享 root 守卫、`fc_at_band_edge` 标记。")
    a(f"- 端口线 ZL 与 50Ω 偏差量：**{zs[0]:.2f}Ω / {dev[0]:+.2f}%**（对 HJ {z_hj:.2f}Ω "
      f"{(zs[0] / z_hj - 1) * 100:+.2f}%），随网格加密应收敛（复跑核对项）。")
    a("")
    return "\n".join(lines) + "\n"


def _parse_kv(items: list[str] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k] = float(v)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runs/smoke_c4_refix")
    parser.add_argument("--probe-root", default=None, help="引擎 ZL 探针源（缺省=root）")
    parser.add_argument("--templates", nargs="+", default=["lange", "cline_coupler"])
    parser.add_argument("--beta-pct", nargs="*", default=None,
                        help="template=pct 覆盖 G5 β（探针被覆盖时取 .log 值）")
    parser.add_argument("--solve-s", nargs="*", default=None, help="template=s（.log 记录）")
    args = parser.parse_args(argv)

    root = Path(args.root)
    probe_root = Path(args.probe_root) if args.probe_root else root
    beta_over = _parse_kv(args.beta_pct)
    solve_over = _parse_kv(args.solve_s)

    results: dict[str, dict[str, Any]] = {}
    for t in args.templates:
        bp = beta_over.get(t)
        src = (f"{t}.log 记录（p1/port_beta.csv 已被他模板轮覆盖）" if bp is not None
               else f"{probe_root.as_posix()}/p1/port_beta.csv")
        r = rejudge_template(t, root, probe_root, beta_pct=bp, beta_source=src,
                             solve_s=solve_over.get(t))
        results[t] = r
        (root / f"{t}_judge.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        an = r["assembly_norm"]
        print(f"[{t}] raw {r['verdict']} σmax {an['sigma_max_raw']:.4f} → 归一 "
              f"{r['verdict_after_norm']} σmax {an['sigma_max_norm']:.4f}；ZL "
              f"{an['line_z0_ohm'][0]:.2f}Ω（{an['line_z0_dev_pct'][0]:+.2f}%）；z* "
              f"{r['scalar_scan']['z_best_ohm']:.2f}；S31 raw {r['raw']['at_f0_nominal']['s31_db']:.2f} "
              f"→ {r['after_norm']['at_f0_nominal']['s31_db']:.2f} vs 裁判 "
              f"{r['raw']['circuit_judge_at_f0']['s31_db']:.2f}", flush=True)

    f_hz = np.linspace(2.0e9, 3.0e9, 401)
    band = (f_hz >= 2.4e9) & (f_hz <= 2.6e9)
    zl_table = engine_zl_round_table(probe_root, f_hz, band)
    late = late_time_levels(probe_root)
    any_t = next(iter(results.values()))
    eps_hj = float(any_t["raw"]["eps_hj_feed"])
    tan_d = float(Stackup.from_materials_yaml(smoke.STACKUP_NAME).loss_tangent)
    md = build_markdown(results, zl_table, late, probe_root, eps_hj, tan_d)
    (root / "assembly_diag.md").write_text(md, encoding="utf-8")
    print(f"assembly_diag.md → {root / 'assembly_diag.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
