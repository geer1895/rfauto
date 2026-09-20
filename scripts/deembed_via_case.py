r"""§10.20 ② via β2 去嵌入案例——把 #205 常数 1.0491 变成可推导量的证据脚本。

用法（工作区根目录）：
    .venv\Scripts\python.exe scripts\deembed_via_case.py

输出（确定性、无网络、无真机）：
1. 真实归档 runs/via_smoke/pt3/port_beta.csv → 乘性尺度 s=β2/β1、εeff1/εeff2、
   去嵌后 εeff2'，以及"是否复现 #205 定版 1.0491±0.0011"。
2. 两个端口 uf/if 探针坐标对比 → H 探针对与镜像参考的错位（#205 机制所在）。
3. 诚实结论块。

诚实边界（不得含糊）
--------------------
- 归档里只有 β 与 2 端口 S，**没有** thru/line/open/short 实测标准件，因此
  core/deembed.py 的 thru-line / OpenShort 通路无法作用在 via 案例上；
  这里能做的只有"以镜像对称的 port1 为标准的乘性端口尺度去嵌"。
- 该去嵌**复现**了 1.0491（归档自算 1.049083，落 1.0491±0.0011 窗内）。
- **收口修订**：镜像前提已被原始电压探针场的三点波动方程估计器
  （core/deembed.beta_from_voltage_trio，驻波免疫、与 CalcPort 链路无关）
  否证——β2/β1=1.0466 带内平坦，偏移主要是**真实模态差异**
  （εeff2/εeff1≈1.095），链路残差仅 ~0.23%。本脚本的"去嵌后 εeff2'≈εeff1"
  在 s=mean(β2/β1) 相除下是代数近恒等（自证）。权威口径见
  scripts/via_beta2_derivation.py 与 core/deembed.derive_via_mirror_verdict。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.deembed import analyze_via_port_scale  # noqa: E402

BETA_CSV = REPO / "runs" / "via_smoke" / "pt3" / "port_beta.csv"
FDTD_DIR = REPO / "runs" / "via_smoke" / "pt3" / "fdtd"


def load_beta_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """读取 port_beta.csv（freq_hz, beta1_rad_per_m, beta2_rad_per_m）。"""
    if not path.exists():
        raise SystemExit(f"归档缺失: {path}")
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    b1 = np.array([float(r["beta1_rad_per_m"]) for r in rows])
    b2 = np.array([float(r["beta2_rad_per_m"]) for r in rows])
    return freq, b1, b2


def probe_start_y(path: Path) -> float:
    """从 openEMS uf/if 文件头读 start-coordinates 的 y（m）。"""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if "start-coordinates" in line:
                seg = line.split("(")[1].split(")")[0]
                return float(seg.split(",")[1])
    raise ValueError(f"{path.name} 无 start-coordinates")


def probe_geometry() -> dict[str, dict[str, float]]:
    """两端口 u/if 探针 y 坐标（对齐检查用；文件缺失返回空表）。"""
    out: dict[str, dict[str, float]] = {}
    for port in (1, 2):
        entry: dict[str, float] = {}
        for kind, tags in (("ut", "ABC"), ("it", "AB")):
            for tag in tags:
                f = FDTD_DIR / f"port_{kind}_{port}{tag}"
                if f.exists():
                    entry[f"{kind}_{tag}"] = probe_start_y(f)
        out[f"port{port}"] = entry
    return out


def main() -> int:
    freq, b1, b2 = load_beta_csv(BETA_CSV)
    report = analyze_via_port_scale(b1, b2, freq)

    print("=== 1. 归档去嵌入报告（core/deembed.analyze_via_port_scale）===")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"原始 εeff1={report['eps_eff1_mean']:.6f} "
          f"εeff2={report['eps_eff2_raw_mean']:.6f} "
          f"(偏差 {report['raw_rel_deviation'] * 100:.3f}%)")
    print(f"去嵌 εeff2'={report['eps_eff2_deembedded_mean']:.6f} "
          f"(偏差 {report['deembedded_rel_deviation'] * 100:.4f}%) "
          f"→ ≤1%: {report['consistent']}")
    print(f"尺度 s={report['scale']:.6f}±{report['scale_std']:.6f} "
          f"(带内起伏 {report['flatness'] * 100:.3f}%) "
          f"复现 #205 1.0491±0.0011: {report['reproduces_documented']}")

    print("\n=== 2. 探针坐标（#205 机制：H 探针与镜像参考错位）===")
    geom = probe_geometry()
    print(json.dumps(geom, indent=2))
    p1, p2 = geom.get("port1", {}), geom.get("port2", {})
    if {"it_A", "it_B"} <= p1.keys() and {"it_A", "it_B"} <= p2.keys():
        step = abs(p1["ut_B"] - p1["ut_A"])
        mirror_center = -0.5 * (p1["it_A"] + p1["it_B"])
        actual_center = 0.5 * (p2["it_A"] + p2["it_B"])
        print(f"网格步长={step * 1e3:.6f} mm；镜像参考 H 中心={mirror_center * 1e3:.6f} mm；"
              f"port2 实取 H 中心={actual_center * 1e3:.6f} mm；"
              f"错位={(actual_center - mirror_center) / step:.3f} 格")
    else:
        print("（fdtd 探针文件不全，跳过坐标对比——归档 port_beta.csv 不受影响）")

    print("\n=== 3. 诚实结论（收口修订）===")
    print("复现：1.049083（=mean(β2/β1)，带内起伏 0.107%）落 #205 定版 1.0491±0.0011。")
    print("收口修订：镜像前提已被原始探针场的波动方程估计器否证")
    print("（β2/β1=1.0466 带内平坦——真实模态差异为主，链路残差仅 ~0.23%）；")
    print("本脚本的去嵌自洽是代数近恒等。权威口径 scripts/via_beta2_derivation.py。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
