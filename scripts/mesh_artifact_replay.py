"""网格伪象诊断三教训复算脚本（真实/带 provenance 数据 → runs/mesh_artifact/*.json）。

三案例（全部有出处，禁止编造）：
1. ratrace pt8 回放——真实逐点归档 runs/ratrace_smoke/pt8/ratrace.s4p（0.4mm、k=1
   原始渲染）+ runs/ratrace_arbitration/openems_convergence.json（0.4→0.2mm 中心上移）
   + 定版 k=1.0975。期望 MESH_ARTIFACT 且 k≈1.10。
2. via 1.0491——真实逐点归档 runs/via_smoke/pt3/port_beta.csv（β2/β1 带内恒定，
   1.0491±0.0011）。期望 PROBE_SCALE（探针尺度常数，非网格伪象）。
3. #152 nm 近重合网格线——实测塌缩值 7.7e-19 s（正常 CFL 步长按 0.4mm
   网格闭式 dx/(2c) 推算）。期望 TIMESTEP_COLLAPSE。

用法：.venv\\Scripts\\python.exe scripts\\mesh_artifact_replay.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.mesh_artifact import (  # noqa: E402
    diagnose_mesh_artifact,
    locate_hybrid_center_ghz,
)

OUT_DIR = REPO / "runs" / "mesh_artifact"
C0 = 299792458.0

# 带 provenance 的定版常量（改动须同步核对出处）
TARGET_GHZ = 2.5
# 模板注（openems_templates.py pt7/pt8 注）"实测 hybrid 中心 ≈2.28GHz"
CENTER_RAW_GHZ = 2.279
EPS_EQUIV = 3.28       # 等效 εeff=3.28 超微带物理上限（pt8 定标）
EPS_CLOSED = 2.7246    # HJ 直线 2.72（同几何闭式）
EPS_R = 3.66           # rogers4350b（hfss_arbitration.json sub.er）
VIA_BETA_RATIO = 1.0491  # via β2/β1 带内恒定比（#205 定征）
TIMESTEP_COLLAPSED_S = 7.7e-19  # #152 实测 CFL 塌缩值


def _panel(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _load_s4p(path: Path):
    import skrf

    net = skrf.Network(str(path))
    return net.frequency.f, net.s


def _eps_from_beta(freq_hz: float, beta: float) -> float:
    return float((beta * C0 / (2 * np.pi * freq_hz)) ** 2)


def _read_beta_at(path: Path, freq_ghz: float = 2.5) -> tuple[float, list[float]]:
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    data = np.array([[float(x) for x in r] for r in rows[1:]])
    j = int(np.argmin(np.abs(data[:, 0] - freq_ghz * 1e9)))
    return float(data[j, 0]), [float(v) for v in data[j, 1:]]


def _write(name: str, report: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    return path


def _print_report(tag: str, report: dict[str, Any]) -> None:
    print(f"[{tag}] status = {report['status']}")
    if report.get("recovered_scale") is not None:
        print(f"      反推电长缩放 k = {report['recovered_scale']:.5f} "
              f"routes={report['recovered_scale_routes']}")
    if report.get("located_center_ghz") is not None:
        print(f"      S 参数定位中心 = {report['located_center_ghz']:.4f} GHz")
    for fac in report["factors"]:
        print(f"      - {fac['factor']:<20s} {fac['status']:<7s} {fac['detail'][:88]}")
    for act in report["actions"]:
        print(f"      → {act}")


# ---------------------------------------------------------------------------
# 案例 1：ratrace pt8
# ---------------------------------------------------------------------------

def case_ratrace_pt8() -> dict[str, Any]:
    _panel("案例 1：ratrace pt8（0.4mm k=1 原始渲染）回放 → 期望 MESH_ARTIFACT")
    s4p = REPO / "runs" / "ratrace_smoke" / "pt8" / "ratrace.s4p"
    conv_path = REPO / "runs" / "ratrace_arbitration" / "openems_convergence.json"
    packet: dict[str, Any] = {
        "target_freq_ghz": TARGET_GHZ,
        "center_ghz": CENTER_RAW_GHZ,
        "equiv_eps_eff": EPS_EQUIV,
        "eps_eff_closed_form": EPS_CLOSED,
        "eps_r": EPS_R,
    }
    sources = {
        "k_definition": "openems_templates._RATRACE_RING_MESH_K=1.0975（pt8 定标）",
        "center_raw": "模板注（openems_templates.py pt7/pt8 注）≈2.28GHz",
        "equiv_eps_eff": "等效 εeff=3.28（HJ 直线 2.7246，εr=3.66）",
        "mesh_study": str(conv_path),
        "s4p": str(s4p),
    }
    if conv_path.exists():
        conv = json.loads(conv_path.read_text(encoding="utf-8"))
        packet["mesh_study"] = [
            {"mesh_mm": 0.4, "f_center_ghz": conv["f_center_avg_0p4mm"]},
            {"mesh_mm": 0.2, "f_center_ghz": conv["f_center_avg_0p2mm"]},
        ]
        sources["mesh_study_values"] = (
            f"0.4mm={conv['f_center_avg_0p4mm']} / 0.2mm={conv['f_center_avg_0p2mm']} "
            f"(k_applied={conv['k_current']})")
    else:
        packet["mesh_study"] = [{"mesh_mm": 0.4, "f_center_ghz": 2.3544},
                                {"mesh_mm": 0.2, "f_center_ghz": 2.5225}]

    if s4p.exists():
        freq_hz, s_matrix = _load_s4p(s4p)
        packet["freq_hz"], packet["s_matrix"] = freq_hz, s_matrix
        located = locate_hybrid_center_ghz(freq_hz, s_matrix)
        print(f"真实归档 {s4p.relative_to(REPO)}：{len(freq_hz)} 点，"
              f"badness 最小点（带沿定位）= {located:.4f} GHz")
        eps_by_port: dict[str, float] = {}
        for p in (1, 2, 3, 4):
            bp = REPO / "runs" / "ratrace_smoke" / "pt8" / f"p{p}" / "port_beta.csv"
            if bp.exists():
                f_hz, betas = _read_beta_at(bp, TARGET_GHZ)
                eps_by_port[f"port{p}"] = _eps_from_beta(f_hz, betas[0])
        if len(eps_by_port) >= 2:
            packet["eps_eff_by_port"] = eps_by_port
            sources["eps_eff_by_port"] = "runs/ratrace_smoke/pt8/p*/port_beta.csv @2.5GHz"
            print("pt8 各端口 εeff @2.5GHz：" + ", ".join(
                f"{k}={v:.4f}" for k, v in eps_by_port.items()))
    else:
        print(f"警告：缺 {s4p}（真实归档），仅用带 provenance 的定版包复算")

    packet["provenance"] = {"sources": sources,
                            "note": "pt8 全 4×4 矩阵线性幅值拟合 k=1.0975"}
    report = diagnose_mesh_artifact(**packet)
    report["case"] = "ratrace_pt8"
    report["sources"] = sources
    path = _write("ratrace_pt8.json", report)
    _print_report("ratrace_pt8", report)
    print(f"      已落盘 {path.relative_to(REPO)}")
    return report


# ---------------------------------------------------------------------------
# 案例 2：via 1.0491
# ---------------------------------------------------------------------------

def case_via_probe() -> dict[str, Any]:
    _panel("案例 2：via 1.0491（倒置叠层 MSLPort 探针尺度常数）→ 期望 PROBE_SCALE")
    beta_path = REPO / "runs" / "via_smoke" / "pt3" / "port_beta.csv"
    sources = {"probe_constant": "via β2/β1=1.0491±0.0011 带内恒定（#205 定征）",
               "derivation": "via β2 倒置叠层调查定征（#205）"}
    packet: dict[str, Any] = {"eps_r": EPS_R}
    if beta_path.exists():
        f_hz, betas = _read_beta_at(beta_path, 2.5)
        b1, b2 = betas[0], betas[1]
        e1, e2 = _eps_from_beta(f_hz, b1), _eps_from_beta(f_hz, b2)
        packet["beta_by_port"] = {"port1": b1, "port2": b2}
        packet["eps_eff_by_port"] = {"port1": e1, "port2": e2}
        packet["equiv_eps_eff"] = e1
        packet["eps_eff_closed_form"] = e1
        sources["port_beta"] = str(beta_path)
        print(f"真实归档 {beta_path.relative_to(REPO)} @2.5GHz："
              f"β1={b1:.4f} β2={b2:.4f} 比={b2 / b1:.5f}；"
              f"εeff1={e1:.4f} εeff2={e2:.4f}")
    else:
        packet["beta_by_port"] = {"port1": 80.0, "port2": 80.0 * VIA_BETA_RATIO}
        sources["port_beta"] = "缺失——用定版 β 比 1.0491"
        print("警告：缺 via 归档，用定版 β 比复算")

    packet["provenance"] = {"sources": sources,
                            "note": "探针尺度是端口提取链乘性偏移，非网格病"}
    report = diagnose_mesh_artifact(**packet)
    report["case"] = "via_probe_scale"
    report["sources"] = sources
    path = _write("via_probe.json", report)
    _print_report("via_probe", report)
    print(f"      已落盘 {path.relative_to(REPO)}")
    return report


# ---------------------------------------------------------------------------
# 案例 3：#152 时间步塌缩
# ---------------------------------------------------------------------------

def case_timestep_152() -> dict[str, Any]:
    _panel("案例 3：#152 nm 近重合网格线 → CFL 时间步塌缩 → 期望 TIMESTEP_COLLAPSE")
    dt_normal = (0.4e-3) / (2.0 * C0)  # 0.4mm 网格 CFL 步长闭式推算
    packet = {
        "timestep_values": [dt_normal, TIMESTEP_COLLAPSED_S],
        "mesh_line_gaps_m": [1e-9, 4e-4, 5e-4],
        "provenance": {
            "sources": {
                "collapsed_timestep": "#152 实测 CFL 塌缩 7.7e-19 s",
                "normal_step": f"0.4mm 网格闭式 dx/(2c)={dt_normal:.3e} s",
                "near_coincident_gap": "nm 级近重合线（#152 SmoothMesh/AddEdges2Grid）",
            },
            "note": "最小间距守卫口径 <1µm",
        },
    }
    report = diagnose_mesh_artifact(**packet)
    report["case"] = "timestep_152"
    report["sources"] = packet["provenance"]["sources"]
    path = _write("timestep_152.json", report)
    _print_report("timestep_152", report)
    print(f"      已落盘 {path.relative_to(REPO)}")
    return report


def main() -> int:
    reports = [case_ratrace_pt8(), case_via_probe(), case_timestep_152()]
    _panel("三教训复算汇总")
    for rep in reports:
        scale = rep.get("recovered_scale")
        extra = f"  k={scale:.5f}" if scale is not None else ""
        print(f"  {rep['case']:<20s} -> {rep['status']}{extra}")
    expect = {"ratrace_pt8": "MESH_ARTIFACT", "via_probe_scale": "PROBE_SCALE",
              "timestep_152": "TIMESTEP_COLLAPSE"}
    bad = [r["case"] for r in reports if expect[r["case"]] != r["status"]]
    if bad:
        print(f"\n不符预期的案例：{bad}")
        return 1
    print("\n三案例判定与预期一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
