r"""§10.20 ③ S 参数时域门控案例——归档上的 before/after 对比证据脚本。

用法（工作区根目录）：
    .venv\Scripts\python.exe scripts\time_gating_demo.py

输出（确定性、无网络、无真机）：对每个存在的归档跑固定门参数，打印
"谷位 GHz / 谷深 dB / 带内纹波 dB / 肩部纹波 dB / 门外冲激能量比"的 before/after，
并对预点名的两个优先归档给出"是否适合做门控验收"的裁决。

固定口径（与 tests/unit/test_time_gating.py 同源）：
    patch sparams.csv  门 span=20 ns  → 谷位 0 Hz 不漂，但凹口被削平（不适合）
    pt8 ratrace.s4p    门 span=40 ns  → 谷位贴带边，门后内移 18 频点（不适合）
    hfss_ratrace.s4p   门 span=20 ns  → 漂移 0 Hz，纹波 12.68→10.37 dB
    pt9 ratrace.s4p    门 span=40 ns  → 漂移 0 Hz，纹波 19.28→17.68 dB
    msl_repro m.s2p    门 span=10 ns  → 漂移 0 Hz，纹波 17.63→14.66 dB

诚实边界
--------
门参数（center=0、显式秒、fft_window=None）是本机在归档上的实测选择，不是物理
第一性推导；out_of_gate_energy_ratio 给出"门到底丢了若干冲激能量"，三个可用归档
均 < 0.003 —— 频域纹波的下降同时包含门自身的平滑成分，不全是寄生物剔除。真正的
"剔除寄生物"定量证据在合成用例（回波与主响应相距 120 ns，门外能量比 3.85%）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import skrf

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.time_gating import (  # noqa: E402
    TimeGate,
    compare_gate,
    gate_network,
    has_interior_valley,
)

PATCH_CSV = (
    REPO
    / "runs"
    / "20260908_122552_01847f02"
    / "calibration"
    / "openems_work"
    / "pt_8841552996"
    / "sparams.csv"
)
PT8_S4P = REPO / "runs" / "ratrace_smoke" / "pt8" / "ratrace.s4p"
PT9_S4P = REPO / "runs" / "ratrace_smoke" / "pt9" / "ratrace.s4p"
HFSS_RATRACE_S4P = REPO / "runs" / "ratrace_arbitration" / "hfss_ratrace.s4p"
MSL_FLUSH_S2P = (
    REPO / "runs" / "audit_freq_scale" / "hfss_mline_repro" / "diag_flush_originfix" / "m.s2p"
)


def _gate(span_ns: float) -> TimeGate:
    return TimeGate.from_center_span(0.0, span_ns, unit="ns", fft_window=None)


def _load_patch_csv(path: Path) -> skrf.Network:
    data = np.genfromtxt(str(path), delimiter=",", names=True)
    freq = skrf.Frequency.from_f(np.asarray(data["freq_hz"], dtype=float), unit="hz")
    s11 = np.asarray(data["re_S11"], dtype=float) + 1j * np.asarray(data["im_S11"], dtype=float)
    return skrf.Network(frequency=freq, s=s11.reshape(-1, 1, 1), z0=50.0)


def _load_s11(path: Path) -> skrf.Network:
    return skrf.Network(str(path)).s11


# (标签, 装载器, 门宽 ns, 裁决)
CASES = [
    ("patch_csv(优先)", lambda: _load_patch_csv(PATCH_CSV), 20.0,
     "unsuitable：S11≡S21 退化、|S11|≈1 非无源；纹波下降=凹口被削平而非剔寄生物"),
    ("pt8(优先)", lambda: _load_s11(PT8_S4P), 40.0,
     "unsuitable：谷位贴下带边，带内无谷，门后内移 18 频点"),
    ("pt9_openems", lambda: _load_s11(PT9_S4P), 40.0, "suitable"),
    ("hfss_ratrace", lambda: _load_s11(HFSS_RATRACE_S4P), 20.0, "suitable"),
    ("msl_repro_flush", lambda: _load_s11(MSL_FLUSH_S2P), 10.0, "suitable"),
]


def main() -> int:
    print("§10.20 ③ S 参数时域门控 demo（确定性，无网络/无真机）")
    print("=" * 100)
    rows = []
    for label, loader, span_ns, verdict in CASES:
        try:
            net = loader()
        except FileNotFoundError:
            print(f"[skip] {label}: 归档缺失")
            continue
        gate = _gate(span_ns)
        report = compare_gate(net, gate_network(net, gate), gate=gate)
        report["label"] = label
        report["gate_span_ns"] = span_ns
        report["interior_valley"] = has_interior_valley(net)
        report["verdict"] = verdict
        report["freq_step_hz"] = float(net.f[1] - net.f[0])
        rows.append(report)
        b, a = report["before"], report["after"]
        print(
            f"{label:18s} span={span_ns:5.1f}ns interior={report['interior_valley']!s:5s} "
            f"dip {b['dip_freq_ghz']:.6f}->{a['dip_freq_ghz']:.6f} GHz "
            f"(shift {report['dip_shift_hz'] / 1e6:+.3f} MHz) | "
            f"band ripple {b['band_ripple_db']:.4f}->{a['band_ripple_db']:.4f} dB "
            f"({report['band_ripple_delta_db']:+.4f}) | "
            f"shoulder {b['shoulder_ripple_db']:.4f}->{a['shoulder_ripple_db']:.4f} dB | "
            f"out-of-gate E {report['out_of_gate_energy_ratio']:.5f}"
        )
        print(f"{'':18s} 裁决：{verdict}")
    print("=" * 100)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
