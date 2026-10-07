"""F-L.2 Xyce-WSL 三方对照冒烟（N7 qucsator 口径）：Xyce vs ngspice vs 解析。

预声明判据（先于真跑钉死，改动即显式评审动作）：
- 电路：V1-R(10Ω)-L(1mH)-C(100nF) 低通，取 V(C)（f0≈15.9kHz、Q=10，
  谐振峰在扫频段内；带外深截止到 ~-72dB）；
- 扫频：1kHz–1MHz **对数网格**，DEC 49 点/十倍程 → 148 点。任务书口径
  "对数 50 点"如实登记偏离：两引擎原生 sweep 类型 LIN/DEC/OCT 中 LIN 为
  线性距、DEC/OCT 无法给出恰 50 点对数网格（3 个十倍程不整除），取 DEC 49
  = 148 点对数扫（同频段、同对数语义、点数只增不减）；
- 三腿：① Xyce（WSL 默认发行版，F-L.2 通道）``.print ac`` FD.prn；
  ② ngspice-45.2（同 WSL，``.control ac dec`` + ``wrdata``，复用
  spice_netlist.parse_ngspice_wrdata_ac 格式钉）；③ 解析闭式
  ``H(w)=1/(1-w^2*L*C + j*w*R*C)``（各自在引擎自报频轴上取值）；
- 对齐（#294 纪律）：跨引擎频轴 argmin 最近邻配对，配对前 max|Δf|/f ≤1e-7
  校验（9 位有效数字打印频率的半 ulp 量级；禁 searchsorted——ADS 1 ulp
  越位假差先例）；解析腿不跨轴配对（直接用各腿自报频轴）；
- 门：三对（xyce-ngspice / xyce-analytic / ngspice-analytic）逐点
  |ΔdB(H)| 最大值 ≤ **0.1 dB**（全部扫点=带内；预期引擎双精度一致到
  ~1e-7 dB 量级，2026-09-29 适配器链预跑实测 2.3e-7）。相位差 max 只
  报告不设门；
- 产物：runs/fl2_xyce/smoke/{xyce/、ngspice/、threeway_report.json}；
  退出码 0=三对全过 / 1=门红或任一腿失败。

用法（仓根执行）::
    .venv/Scripts/python.exe scripts/xyce_smoke_threeway.py
    .venv/Scripts/python.exe scripts/xyce_smoke_threeway.py --root runs/fl2_xyce/smoke
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from rfauto.adapters.spice_netlist import parse_ngspice_wrdata_ac  # noqa: E402
from rfauto.adapters.xyce_adapter import (  # noqa: E402
    XyceError,
    decode_wsl_bytes,
    prn_path_for,
    read_prn,
    render_rlc_ac_netlist,
    resolve_xyce_exe,
    rlc_lowpass_transfer,
    run_xyce,
    verify_xyce_reachable,
    windows_to_wsl_path,
    wsl_bash_argv,
    xyce_version,
)

#: 预声明判据常量（与模块 docstring 同源，报告 JSON 原文回带）。
CRITERIA = {
    "circuit": "V1-R(10)-L(1m)-C(100n) lowpass, H=V(C)/V1",
    "r_ohm": 10.0,
    "l_henry": 1e-3,
    "c_farad": 1e-7,
    "sweep": "1kHz-1MHz log, DEC 49/decade -> 148 points",
    "sweep_points_note": (
        "task said 'log 50 points'; DEC/OCT cannot express exactly 50 log "
        "points over 3 decades and LIN is linear-spaced -> honest deviation "
        "to DEC 49 = 148 log points (same band, same semantics)"
    ),
    "pairing": "argmin nearest-neighbor, max|df|/f <= 1e-7 precheck",
    "gate_db": 0.1,
    "gate": "max pairwise |dB(H) diff| <= 0.1 dB over all sweep points",
    "phase": "reported, not gated",
}

_NGSPICE_WSL_EXE = "ngspice"  # WSL PATH 解析（usr/bin/ngspice 实测）
_PAIR_TOL_REL = 1e-7
_NGSPICE_CIR_NAME = "rlc_ngspice.cir"
_NGSPICE_TXT_NAME = "rlc_ngspice_wrdata.txt"
_XYCE_CIR_NAME = "rlc_xyce.cir"


def _num(value: float) -> str:
    return f"{float(value):.17g}"


def render_ngspice_rlc_netlist(r: float, l_h: float, c_f: float, *,
                               fstart: float, fstop: float,
                               points_per_decade: int) -> str:
    """渲染 ngspice 侧同构 RLC 网表（.control ac dec + wrdata）。"""
    lines = [
        "* rfauto F-L.2 ngspice rlc lowpass (three-way smoke)",
        "V1 1 0 AC 1",
        f"R1 1 2 {_num(r)}",
        f"L1 2 3 {_num(l_h)}",
        f"C1 3 0 {_num(c_f)}",
        ".control",
        f"ac dec {int(points_per_decade)} {_num(fstart)} {_num(fstop)}",
        f"wrdata {_NGSPICE_TXT_NAME} v(3)",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def _run_wsl(distro: str, script: str, timeout_s: float) -> subprocess.CompletedProcess:
    """WSL bash 子进程（bytes 输出，解码交给 decode_wsl_bytes——#271）。"""
    return subprocess.run(
        wsl_bash_argv(resolve_xyce_exe(distro=distro), script),
        capture_output=True, timeout=timeout_s, check=False,
    )


def ngspice_wsl_version(distro: str, timeout_s: float = 60.0) -> str | None:
    """WSL ngspice 版本串（best-effort，#105）。"""
    try:
        proc = _run_wsl(distro, f"{_NGSPICE_WSL_EXE} --version", timeout_s)
    except Exception:
        return None
    text = decode_wsl_bytes(proc.stdout) + decode_wsl_bytes(proc.stderr)
    for ln in text.splitlines():
        if "ngspice-" in ln:
            return ln.strip()
    return None


def run_ngspice_wsl(cir_path: Path, *, distro: str, timeout_s: float = 300.0) -> tuple[int, str]:
    """WSL 内批跑 ngspice（``-b``），返回 (rc, 解码输出合并文本)。"""
    wsl_dir = windows_to_wsl_path(cir_path.resolve().parent)
    script = (f"cd {wsl_dir} && {_NGSPICE_WSL_EXE} -b {cir_path.name}")
    proc = _run_wsl(distro, script, timeout_s)
    return proc.returncode, decode_wsl_bytes(proc.stdout) + decode_wsl_bytes(proc.stderr)


def align_freqs(f_ref: np.ndarray, f_move: np.ndarray) -> tuple[np.ndarray, float]:
    """argmin 最近邻配对（#294：禁 searchsorted——1 ulp 越位假差先例）。

    Returns:
        (配对下标, 最大相对频差)；越 _PAIR_TOL_REL 显式 XyceError。
    """
    f_ref = np.asarray(f_ref, dtype=float)
    f_move = np.asarray(f_move, dtype=float)
    idx = np.abs(f_move[:, None] - f_ref[None, :]).argmin(axis=0)
    rel = float(np.max(np.abs(f_move[idx] - f_ref) / f_ref))
    if rel > _PAIR_TOL_REL:
        raise XyceError(
            f"跨引擎频轴配对失败：max|df|/f={rel:.3e} > {_PAIR_TOL_REL:.0e}"
            "（网格或单位不一致，拒绝逐点比对）"
        )
    return idx, rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="F-L.2 Xyce vs ngspice vs analytic three-way smoke")
    ap.add_argument("--root", default=str(_REPO / "runs" / "fl2_xyce" / "smoke"),
                    help="产物根目录（默认 runs/fl2_xyce/smoke）")
    ap.add_argument("--distro", default=None, help="WSL 发行版（默认 Xyce 通道缺省）")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_absolute():
        root = (_REPO / root).resolve()
    xyce_dir = root / "xyce"
    ng_dir = root / "ngspice"
    xyce_dir.mkdir(parents=True, exist_ok=True)
    ng_dir.mkdir(parents=True, exist_ok=True)

    cr = CRITERIA
    r, lh, cf = cr["r_ohm"], cr["l_henry"], cr["c_farad"]
    report: dict = {"criteria": dict(cr), "legs": {}, "pairs": {}, "verdict": "FAIL"}

    # ── 腿 1：Xyce ────────────────────────────────────────────────────────
    spec = verify_xyce_reachable(resolve_xyce_exe(distro=args.distro))
    cir_x = xyce_dir / _XYCE_CIR_NAME
    cir_x.write_bytes(render_rlc_ac_netlist(
        r, lh, cf, fstart_hz=1e3, fstop_hz=1e6, points_per_decade=49,
    ).encode("ascii"))
    t0 = time.time()
    run = run_xyce(cir_x, spec=spec, timeout_s=300.0)
    prn_x = prn_path_for(cir_x, ac=True)
    if run.timed_out or run.rc != 0 or not prn_x.is_file():
        report["legs"]["xyce"] = {"ok": False, "rc": run.rc, "timed_out": run.timed_out,
                                  "stderr_tail": run.stderr[-500:]}
        report["error"] = "Xyce leg failed"
        _write_report(root, report)
        print("FAIL: Xyce leg failed:", report["legs"]["xyce"])
        return 1
    parsed_x = read_prn(prn_x)
    f_x = parsed_x["data"][parsed_x["indep"]].real
    h_x = np.asarray(parsed_x["data"][parsed_x["vars"][0]], dtype=complex)
    report["legs"]["xyce"] = {
        "ok": True, "engine": xyce_version(spec), "n_points": len(f_x),
        "wall_time_s": run.wall_time_s, "total_s": round(time.time() - t0, 2),
        "netlist": str(cir_x), "prn": str(prn_x),
    }
    print(f"[xyce] ok n={len(f_x)} engine={xyce_version(spec)} wall={run.wall_time_s}s")

    # ── 腿 2：ngspice（WSL）───────────────────────────────────────────────
    cir_n = ng_dir / _NGSPICE_CIR_NAME
    cir_n.write_bytes(render_ngspice_rlc_netlist(
        r, lh, cf, fstart=1e3, fstop=1e6, points_per_decade=49,
    ).encode("ascii"))
    txt_n = ng_dir / _NGSPICE_TXT_NAME
    txt_n.unlink(missing_ok=True)  # 防陈旧产物混入
    t0 = time.time()
    rc_n, out_n = run_ngspice_wsl(cir_n, distro=spec.distro)
    if rc_n != 0 or not txt_n.is_file():
        report["legs"]["ngspice"] = {"ok": False, "rc": rc_n, "output_tail": out_n[-500:]}
        report["error"] = "ngspice leg failed"
        _write_report(root, report)
        print("FAIL: ngspice leg failed:", out_n[-500:])
        return 1
    f_n, vals_n = parse_ngspice_wrdata_ac(txt_n.read_text(encoding="ascii"), n_vectors=1)
    h_n = np.asarray(vals_n[0], dtype=complex)
    report["legs"]["ngspice"] = {
        "ok": True, "engine": ngspice_wsl_version(spec.distro),
        "n_points": len(f_n), "total_s": round(time.time() - t0, 2),
        "netlist": str(cir_n), "wrdata": str(txt_n),
    }
    print(f"[ngspice] ok n={len(f_n)} engine={report['legs']['ngspice']['engine']}")

    # ── 对齐与逐点比对 ────────────────────────────────────────────────────
    idx_n_on_x, pair_rel = align_freqs(f_x, f_n)
    h_n_aligned = h_n[idx_n_on_x]
    db_x = 20.0 * np.log10(np.abs(h_x))
    db_n = 20.0 * np.log10(np.abs(h_n_aligned))
    db_a_x = 20.0 * np.log10(np.abs(rlc_lowpass_transfer(f_x, r, lh, cf)))
    db_a_n = 20.0 * np.log10(np.abs(rlc_lowpass_transfer(f_n, r, lh, cf)))
    deg_x = np.degrees(np.angle(h_x))
    deg_n = np.degrees(np.angle(h_n_aligned))

    pair_defs = {
        "xyce-ngspice": (db_x - db_n, f_x),
        "xyce-analytic": (db_x - db_a_x, f_x),
        "ngspice-analytic": (db_n - db_a_n, f_n),
    }
    pairs: dict[str, dict] = {}
    for name, (diff, fq) in pair_defs.items():
        i = int(np.argmax(np.abs(diff)))
        pairs[name] = {
            "db_max_abs_diff": float(abs(diff[i])),
            "worst_freq_hz": float(fq[i]),
        }
    pairs["xyce-ngspice"]["phase_max_abs_diff_deg"] = float(
        np.max(np.abs(deg_x - deg_n))
    )
    gate = float(cr["gate_db"])
    worst_pair = max(pairs, key=lambda k: pairs[k]["db_max_abs_diff"])
    worst_val = pairs[worst_pair]["db_max_abs_diff"]
    passed = worst_val <= gate
    report["pairs"] = pairs
    report["pairing_max_rel_freq_diff"] = pair_rel
    report["verdict"] = "PASS" if passed else "FAIL"
    report["worst_pair"] = worst_pair
    _write_report(root, report)
    for name, p in pairs.items():
        print(f"[pair] {name}: max|dB diff| = {p['db_max_abs_diff']:.3e} dB")
    print(f"[gate] {worst_pair} worst={worst_val:.3e} dB (gate {gate}) -> "
          f"{report['verdict']}; report={root / 'threeway_report.json'}")
    return 0 if passed else 1


def _write_report(root: Path, report: dict) -> None:
    (root / "threeway_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
