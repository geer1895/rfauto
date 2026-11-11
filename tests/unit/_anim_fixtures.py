"""动图测试 fixtures 构造器（Q-W2-1；**只落 tmp_path，禁写 runs/ 湖**）。

数据面=显式字面量构造（零随机零示意数据混入渲染链——这些文件是"数据源"
本身，供渲染器确定性消费）：

- :func:`make_sparams_csv` —— run 湖 sparams.csv 契约形态；
- :func:`make_s2p` —— 2 端口 Touchstone RI（skrf 可读；对称填充）；
- :func:`make_run_dir` —— rfauto run 目录 trials/trial_N.json 惯例；
- :func:`make_anchor_series` / :func:`make_anchor_points` —— 锚点 JSON
  （fit_compare=series/smith=points 契约）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FREQS_HZ = (1e9, 2e9, 3e9)
S11 = (complex(-0.2, 0.1), complex(-0.3, -0.05), complex(-0.5, 0.02))
S21 = (complex(0.9, -0.1), complex(0.85, 0.02), complex(0.7, 0.01))


def make_sparams_csv(tmp_path: Path, name: str = "sparams.csv", *,
                     freqs: tuple[float, ...] = FREQS_HZ,
                     s11: tuple[complex, ...] = S11,
                     s21: tuple[complex, ...] | None = S21) -> Path:
    """写 sparams.csv（freq_hz,re_XX,im_XX 表头契约；值=显式字面量）。"""
    header = ["freq_hz", "re_S11", "im_S11"]
    if s21 is not None:
        header += ["re_S21", "im_S21"]
    lines = [",".join(header)]
    for k, f in enumerate(freqs):
        row = [repr(f), repr(s11[k].real), repr(s11[k].imag)]
        if s21 is not None:
            row += [repr(s21[k].real), repr(s21[k].imag)]
        lines.append(",".join(row))
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def make_s2p(tmp_path: Path, name: str = "params.s2p", *,
             freqs_ghz: tuple[float, ...] = (1.0, 2.0, 3.0),
             s11: tuple[complex, ...] = S11,
             s21: tuple[complex, ...] = S21) -> Path:
    """写 2 端口 Touchstone（RI 格式；2 端口每行 8 数据值——Touchstone 契约）。"""
    lines = ["# GHz S RI R 50"]
    for k, fg in enumerate(freqs_ghz):
        vals = [s11[k].real, s11[k].imag, s21[k].real, s21[k].imag,
                s21[k].real, s21[k].imag, s11[k].real, s11[k].imag]
        lines.append(f"{fg} " + " ".join(repr(v) for v in vals))
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def make_run_dir(tmp_path: Path, name: str = "run_a",
                 costs: tuple[float, ...] = (3.0, 2.0, 2.5, 1.5),
                 trial_numbers: tuple[int, ...] | None = None) -> Path:
    """写 rfauto run 目录形态（trials/trial_N.json；cost 必备）。"""
    numbers = trial_numbers if trial_numbers is not None \
        else tuple(range(len(costs)))
    run = tmp_path / name
    tdir = run / "trials"
    tdir.mkdir(parents=True)
    for k, cost in enumerate(costs):
        record: dict[str, Any] = {"trial_number": numbers[k],
                                  "params": {"arm_len_mm": 19.0 + k},
                                  "metrics": {"s11_db": -10.0 - k},
                                  "cost": cost}
        (tdir / f"trial_{k}.json").write_text(
            json.dumps(record), encoding="utf-8")
    return run


def make_anchor_series(tmp_path: Path, name: str = "anchor_series.json", *,
                       x: tuple[float, ...] = FREQS_HZ,
                       y: tuple[float, ...] = (-1.0, -1.2, -0.9)) -> Path:
    """写 anchor_json（fit_compare 契约=``{"series":{"x","y"}}``）。"""
    p = tmp_path / name
    p.write_text(json.dumps({"series": {"x": list(x), "y": list(y)}}),
                 encoding="utf-8")
    return p


def make_anchor_points(tmp_path: Path, name: str = "anchor_points.json",
                       pts: tuple[tuple[float, float], ...] = (
                           (0.2, -0.1), (0.5, 0.9), (0.05, 0.02))) -> Path:
    """写 anchor_json（smith 契约=``{"points":[{"re","im"},...]}``）。"""
    p = tmp_path / name
    p.write_text(json.dumps(
        {"points": [{"re": re, "im": im} for re, im in pts]}),
        encoding="utf-8")
    return p


# ─── 批 2 构造器（Q-W2-2 席；只增不改——既有构造器零触碰） ────────────────────

FIELD_FRAME_0 = (
    (0.0, 0.25, 0.5, 0.25),
    (0.25, 1.0, 1.5, 0.5),
    (0.5, 1.5, 3.0, 1.0),
)
FIELD_FRAME_1 = (
    (0.1, 0.35, 0.6, 0.35),
    (0.35, 1.1, 1.6, 0.6),
    (0.6, 1.6, 3.1, 1.1),
)


def make_field_frames_json(tmp_path: Path,
                           name: str = "field_frames.json", *,
                           frames: tuple[tuple[tuple[float, ...], ...], ...] =
                           (FIELD_FRAME_0, FIELD_FRAME_1),
                           axes: dict[str, Any] | None = None,
                           metas: tuple[dict[str, Any], ...] | None = None
                           ) -> Path:
    """写 field_dump 单文件形态（契约=``{"axes":{},"frames":[...]}``）。"""
    payload: dict[str, Any] = {
        "axes": axes if axes is not None else {"xlabel": "x_mm",
                                               "ylabel": "y_mm"},
        "frames": [{"meta": (metas[k] if metas is not None else {"t": k}),
                    "values": [list(row) for row in frames[k]]}
                   for k in range(len(frames))],
    }
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def make_field_dump_dir(tmp_path: Path, name: str = "field_dump", *,
                        frames: tuple[tuple[tuple[float, ...], ...], ...] =
                        (FIELD_FRAME_0, FIELD_FRAME_1),
                        axes: dict[str, Any] | None = None) -> Path:
    """写 field_dump 目录形态（frame_*.json sorted + 可选 axes.json）。"""
    d = tmp_path / name
    d.mkdir(parents=True)
    for k, frame in enumerate(frames):
        (d / f"frame_{k}.json").write_text(
            json.dumps({"meta": {"t": k},
                        "values": [list(row) for row in frame]}),
            encoding="utf-8")
    if axes is not None:
        (d / "axes.json").write_text(json.dumps(axes), encoding="utf-8")
    return d


def make_layout_json(tmp_path: Path, name: str = "layout.json", *,
                     layers: tuple[tuple[str, tuple[dict[str, Any], ...]], ...]
                     | None = None) -> Path:
    """写 layout_json（契约=``{"layers":[{"name","primitives":[...]}]}``）。

    缺省三层叠层（数据坐标字面量）。
    """
    if layers is None:
        layers = (
            ("substrate", ({"shape": "rect", "x": 0.0, "y": 0.0,
                            "w": 10.0, "h": 2.0},)),
            ("trace", ({"shape": "rect", "x": 2.0, "y": 2.0,
                        "w": 6.0, "h": 0.5},)),
            ("coverlay", ({"shape": "rect", "x": 0.0, "y": 2.5,
                           "w": 10.0, "h": 1.0},
                          {"shape": "rect", "x": 4.0, "y": 2.5,
                           "w": 2.0, "h": 1.0})),
        )
    payload = {"layers": [{"name": nm,
                           "primitives": [dict(prim) for prim in prims]}
                          for nm, prims in layers]}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p
