r"""A8 MAPES stage-1 演示：fake Z_ALL + 占用→对角负载 + Schur 补闭式全链。

跑代表像素图案（全空 / 全占 / 棋盘 / 一行 / 单像素），打印外端口 S 参数
摘要，并把结果落盘到 `runs/mapes_s1/*.json`。

口径与边界（见 src/rfauto/core/mapes.py 模块 docstring）：
- Z_ALL 由 `fake_mesh` 合成的互易无源 RLC 网格给出，**不是真机提取**；
  stage-2 才接 adapters/openems_rotation.py 的 openEMS 多端口轮转；
- β/α 校准超参不在 stage-1；
- 每个图案同时用**独立裁判**（全节点 Kirchhoff 直接解）交叉校验 Schur
  闭式结果，`cross_check.max_abs_delta_s` 落盘。

用法（工作区根目录）：
    .venv\Scripts\python.exe scripts/mapes_s1_demo.py
    .venv\Scripts\python.exe scripts/mapes_s1_demo.py --n 6 --freq-ghz 1.0 2.5 5.0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from rfauto.core.mapes import MapesModel, PixelLayout, RlcMesh, fake_mesh, occupancy_to_load

REPO = Path(__file__).resolve().parents[1]
DB_FLOOR = 1.0e-30


def _patterns(n: int) -> dict[str, np.ndarray]:
    idx = np.arange(n)
    single = np.zeros((n, n), dtype=bool)
    single[0, 0] = True
    one_row = np.zeros((n, n), dtype=bool)
    one_row[n // 2, :] = True
    return {
        "all_empty": np.zeros((n, n), dtype=bool),
        "all_full": np.ones((n, n), dtype=bool),
        "checkerboard": (np.add.outer(idx, idx) % 2 == 0),
        "one_row": one_row,
        "single_pixel": single,
    }


def _s_db(s: np.ndarray) -> list[list[list[float]]]:
    mag = np.maximum(np.abs(s), DB_FLOOR)
    return [[[float(x) for x in row] for row in mat]
            for mat in (20.0 * np.log10(mag))]


def _io_neighbour_slots(mesh: RlcMesh, n_io: int) -> list[int]:
    """外部 I/O 端口在底层网络里的**直接邻居虚拟端口**槽号。

    这些槽全部短路时，I/O 端口与其余网络去耦（只剩本地并联支路）——任何
    满足该条件的图案都会给出与"全占用"相同的外端口 Z/S（物理事实，非 bug）。
    """
    neighbours: set[int] = set()
    for i, j in mesh.edges:
        if i < n_io <= j:
            neighbours.add(j)
        if j < n_io <= i:
            neighbours.add(i)
    return sorted(node - n_io for node in neighbours)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=6, help="像素矩阵 M=N（默认 6）")
    parser.add_argument("--freq-ghz", type=float, nargs="+",
                        default=[1.0, 2.5, 5.0], help="频点 GHz（默认 1/2.5/5）")
    parser.add_argument("--out", default=str(REPO / "runs" / "mapes_s1"))
    args = parser.parse_args()

    layout = PixelLayout(n_rows=args.n, n_cols=args.n, n_io_ports=2)
    mesh = fake_mesh(layout.n_ports)
    freqs = np.asarray([f * 1.0e9 for f in args.freq_ghz], dtype=float)
    z_stack = np.stack([mesh.z_all(f) for f in freqs])
    model = MapesModel(layout, z_stack, freqs)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[mapes-s1] topology={layout.topology_key}")
    print(f"[mapes-s1] Q={layout.n_ports} (io=2 + load={layout.n_load_ports}) "
          f"fake=RlcMesh(ports={mesh.n_ports}, edges={len(mesh.edges)})")
    print(f"[mapes-s1] freq_ghz={[float(f) / 1e9 for f in freqs]}")
    critical_slots = _io_neighbour_slots(mesh, layout.n_io_ports)
    print(f"[mapes-s1] I/O 邻居虚拟端口槽={critical_slots}（全短接即与像素域去耦）")
    print(f"{'pattern':<14}{'occ':>5}{'S11@fc(dB)':>13}{'S21@fc(dB)':>13}"
          f"{'S11min(dB)':>13}{'passive':>10}{'×check':>11}")

    index_patterns: list[dict[str, object]] = []
    for name, pattern in _patterns(args.n).items():
        params = layout.flatten(pattern)
        result = model.evaluate(params)
        metrics = model.predict(params)
        loads = occupancy_to_load(pattern, layout)
        delta = 0.0
        for k, freq in enumerate(freqs):
            s_ref = mesh.reference_s(
                n_io=layout.n_io_ports, load_impedances=loads,
                freq_hz=float(freq), reference_impedance=model.reference_impedance)
            delta = max(delta, float(np.max(np.abs(result.s_external[k] - s_ref))))
        summary = result.summary()
        decouples = bool(np.all(loads[critical_slots] == 0.0)) if critical_slots else False
        record = {
            "pattern": name,
            "topology_key": layout.topology_key,
            "occupancy": pattern.astype(int).tolist(),
            "n_ports": layout.n_ports,
            "n_load_ports": layout.n_load_ports,
            "n_occupied_slots": summary["n_occupied_slots"],
            "n_open_slots": summary["n_open_slots"],
            "decouples_io": decouples,
            "freq_ghz": [float(f) / 1e9 for f in freqs],
            "s_db": _s_db(result.s_external),
            "metrics": metrics,
            "cross_check": {
                "method": "nodal_reference_s (Kirchhoff 全节点直接解，独立于 Schur 补)",
                "max_abs_delta_s": delta,
            },
        }
        (out_dir / f"{name}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        index_patterns.append({
            "pattern": name,
            "n_occupied_slots": summary["n_occupied_slots"],
            "decouples_io": decouples,
            "s11_db_at_fc": metrics["s11_db_at_fc"],
            "s21_db_at_fc": metrics["s21_db_at_fc"],
            "s11_db_min": metrics["s11_db_min"],
            "passive_margin": metrics["passive_margin"],
            "max_abs_delta_s": delta,
        })
        print(f"{name:<14}{summary['n_occupied_slots']:>5}"
              f"{metrics['s11_db_at_fc']:>13.3f}{metrics['s21_db_at_fc']:>13.3f}"
              f"{metrics['s11_db_min']:>13.3f}{metrics['passive_margin']:>10.4f}"
              f"{delta:>11.2e}"
              + ("   [I/O 去耦→与 all_full 等价]"
                 if decouples and name != "all_full" else ""))

    index = {
        "generated_by": "scripts/mapes_s1_demo.py",
        "stage": "stage-1 (fake Z_ALL, 零真机)",
        "topology_key": layout.topology_key,
        "n_ports": layout.n_ports,
        "n_load_ports": layout.n_load_ports,
        "freq_ghz": [float(f) / 1e9 for f in freqs],
        "fake_z_all": {
            "kind": "RlcMesh",
            "n_ports": mesh.n_ports,
            "n_edges": len(mesh.edges),
            "r_edge": mesh.r_edge,
            "l_edge": mesh.l_edge,
            "g_node": mesh.g_node,
            "c_node": mesh.c_node,
            "note": "合成互易无源 RLC 网格；非真机提取（stage-2 接 openEMS）",
        },
        "io_neighbour_slots": critical_slots,
        "patterns": index_patterns,
        "notes": [
            "Z_ALL 由合成 RLC 网格给出（非真机）；stage-2 才接 openEMS 多端口提取。",
            "decouples_io=true 表示该图案短接了 I/O 端口全部直接邻居虚拟端口："
            "外部端口与像素域物理去耦，外端口 S 与 all_full 等价（非内核缺陷，"
            "tests/unit/test_mapes.py::test_shorting_io_neighbour_ports_decouples_external_ports 钉死）。",
        ],
    }
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[mapes-s1] wrote {len(index_patterns) + 1} files -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
