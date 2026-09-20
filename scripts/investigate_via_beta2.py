"""via β2 调查（#203 遗留，分析型零求解）：定位倒置微带 port2 的 β
常数偏移（1.0491）出现在 CalcPort β 公式的哪个量。

MSLPort.ReadUIData：β² = -dEt·dHt/(Ht·Et)，其中
  Et = uf_B, dEt = (uf_C - uf_A)/(Σ|U_delta|·unit),
  Ht = (if_A + if_B)/2, dHt = (if_B - if_A)/|I_delta|·unit。
对 2.5GHz 做 DFT 重建各量，port2/port1 逐项对比。
"""
import sys
from pathlib import Path

import numpy as np

PT = Path("runs/via_smoke/pt3/fdtd")
F_TGT = 2.5e9
UNIT = 1e-3  # 模型单位 mm→m 的 delta unit


def read_td(path: Path) -> tuple[np.ndarray, np.ndarray]:
    t, v = [], []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("%") or line.startswith("t/"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            t.append(float(parts[0]))
            v.append(float(parts[1]))
    return np.array(t), np.array(v)


def dft(x: np.ndarray, v: np.ndarray, f0: float) -> complex:
    dt = x[1] - x[0]
    return np.sum(v * np.exp(-2j * np.pi * f0 * x)) * dt


def ut(path: Path, f0: float) -> complex:
    x, v = read_td(path)
    return dft(x, v, f0)


def it(path: Path, f0: float) -> complex:
    x, v = read_td(path)
    return dft(x, v, f0)


def y_of(path: Path) -> float:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if "start-coordinates" in line:
                seg = line.split("(")[1].split(")")[0]
                return float(seg.split(",")[1])
    raise ValueError(f"no start-coordinates in {path}")


def beta_of(port: int) -> dict:
    ys = {n: y_of(PT / f"port_ut_{port}{n}") for n in "ABC"}
    d_u = abs(ys["B"] - ys["A"])  # U 位置等距间隔
    d_i = d_u / 2.0               # I_delta（A/B 中点差）
    eA = ut(PT / f"port_ut_{port}A", F_TGT)
    eB = ut(PT / f"port_ut_{port}B", F_TGT)
    eC = ut(PT / f"port_ut_{port}C", F_TGT)
    hA = it(PT / f"port_it_{port}A", F_TGT)
    hB = it(PT / f"port_it_{port}B", F_TGT)
    d_et = (eC - eA) / (d_u * UNIT)
    d_ht = (hB - hA) / (d_i * UNIT)
    return {"Et": eB, "dEt": d_et, "Ht": (hA + hB) / 2, "dHt": d_ht}


def main() -> int:
    p1 = beta_of(1)
    p2 = beta_of(2)
    print("量            port2/port1  (模, 相位deg)")
    for q in ("Et", "dEt", "Ht", "dHt"):
        r = p2[q] / p1[q]
        print(f"{q:4s}  |r|={abs(r):.4f}  phase={np.degrees(np.angle(r)):+.1f}")
    for tag, p in (("port1", p1), ("port2", p2)):
        val = -p["dEt"] * p["dHt"] / (p["Ht"] * p["Et"])
        beta = np.sqrt(abs(val))
        print(f"{tag}: -dEt·dHt/(Ht·Et) = {val:.6g}  β≈{abs(beta):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
