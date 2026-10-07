"""DXF 真值对照三归一纯内核（L0：零文件 IO、零 ezdxf 依赖）.

源仓 §2.11/§6-10 规范（ge5 Goal Wave3 F 组）：凡与外部图纸（手绘真值）
对照，先做**三归一**——否则「误差」是对照器伪象不是零件误差：

1. **块内 INSERT 展开**（手绘图常把轮廓装进块，逐实体对照前必须展开；
   展开是 ezdxf 读取面职责，见 adapters.fab_export.dxf_truth）；
2. **重复线段去重**（TRL3 手绘 M1 每段画两遍——不去重则逐实体匹配
   双倍报差；去重后与导出 1:1）；
3. **Y 原点归一**（手绘 Y 原点与导出可差常数——先各自平移到 y_min=0
   再对照，位移量留痕进报告）。

本模块只做归一后的纯集合匹配与判据；文件读取/INSERT 展开在
adapters.fab_export.dxf_truth。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]
Segment = tuple[Point, Point]
Circle = tuple[Point, float]

DEFAULT_TOL_MM = 1e-3


def _canonical_segment(seg: Segment) -> Segment:
    """端点排序规范化（线段无方向）。"""
    (x1, y1), (x2, y2) = seg
    if (x2, y2) < (x1, y1):
        return ((x2, y2), (x1, y1))
    return ((x1, y1), (x2, y2))


def dedup_segments(
    segments: Sequence[Segment],
    *,
    tol: float = DEFAULT_TOL_MM,
) -> tuple[list[Segment], dict]:
    """重复线段去重（归一之二）.

    端点在 tol 内视为同段（先规范化端点序再聚类）。返回
    (去重后段列表, trace)；trace 记录去重前后计数（报告留痕）。
    """
    kept: list[Segment] = []
    dup_count = 0
    for seg in segments:
        can = _canonical_segment(seg)
        dup = False
        for k in kept:
            kc = _canonical_segment(k)
            if (
                math.hypot(can[0][0] - kc[0][0], can[0][1] - kc[0][1]) <= tol
                and math.hypot(can[1][0] - kc[1][0], can[1][1] - kc[1][1]) <= tol
            ):
                dup = True
                break
        if dup:
            dup_count += 1
        else:
            kept.append(can)
    trace = {
        "before": len(segments),
        "after": len(kept),
        "duplicates_removed": dup_count,
        "tol_mm": tol,
    }
    return kept, trace


def dedup_circles(
    circles: Sequence[Circle],
    *,
    tol: float = DEFAULT_TOL_MM,
) -> tuple[list[Circle], dict]:
    """重复圆去重（归一之二对圆的扩展：手绘真值圆孔同样会画两遍）.

    圆心距与半径差都 ≤ tol 视为同圆。返回 (去重后列表, trace)。
    """
    kept: list[Circle] = []
    dup_count = 0
    for c, r in circles:
        dup = any(
            math.hypot(c[0] - kc[0], c[1] - kc[1]) <= tol and abs(r - kr) <= tol
            for kc, kr in kept
        )
        if dup:
            dup_count += 1
        else:
            kept.append((c, r))
    trace = {
        "before": len(circles),
        "after": len(kept),
        "duplicates_removed": dup_count,
        "tol_mm": tol,
    }
    return kept, trace


def shift_y(
    segments: Sequence[Segment],
    circles: Sequence[Circle],
    dy: float,
) -> tuple[list[Segment], list[Circle]]:
    """整体 Y 平移 -dy（配合 normalize_y 的文件级位移使用）."""
    if abs(dy) < 1e-12:
        return list(segments), list(circles)
    segs = [((p[0], p[1] - dy), (q[0], q[1] - dy)) for p, q in segments]
    circs = [((c[0], c[1] - dy), r) for c, r in circles]
    return segs, circs


def normalize_y(
    segments: Sequence[Segment],
    circles: Sequence[Circle],
) -> tuple[list[Segment], list[Circle], float]:
    """Y 原点归一（归一之三）：整体平移使 y_min=0，返回位移量.

    位移量由调用方写进对照报告（归一步骤留痕）。**文件级语义**：真值
    与导出的 Y 原点差是整图常数——对全文件实体集求一个 dy，再统一平移
    （逐层各自归一会掩盖真实的层间 Y 错位，属误定口径）。
    """
    ys = [p[1] for seg in segments for p in seg]
    ys += [c[0][1] for c in circles]
    if not ys:
        return list(segments), list(circles), 0.0
    dy = min(ys)
    segs, circs = shift_y(segments, circles, dy)
    return segs, circs, dy


def match_geometry(
    produced_segs: Sequence[Segment],
    truth_segs: Sequence[Segment],
    produced_circles: Sequence[Circle],
    truth_circles: Sequence[Circle],
    *,
    tol: float = DEFAULT_TOL_MM,
) -> dict:
    """归一后逐实体集合匹配（贪心最近邻 + tol 判等）.

    返回报告 dict：线段 matched/only_in_produced（漏画）/only_in_truth
    （多画）（含逐实体坐标差）、圆 matched/only_in_produced/
    only_in_truth（圆心差+半径差）、max 段偏差、总判 passed。"""
    seg_report = _match_segments(produced_segs, truth_segs, tol)
    circ_report = _match_circles(produced_circles, truth_circles, tol)
    passed = (
        not seg_report["only_in_produced"]
        and not seg_report["only_in_truth"]
        and not circ_report["only_in_produced"]
        and not circ_report["only_in_truth"]
    )
    return {
        "segments": seg_report,
        "circles": circ_report,
        "max_segment_dev_mm": seg_report["max_dev_mm"],
        "passed": passed,
        "tol_mm": tol,
    }


def _match_segments(
    produced: Sequence[Segment], truth: Sequence[Segment], tol: float
) -> dict:
    """段级贪心匹配：produced 每段在 truth 找最近且 ≤tol 的对.

    only_in_produced = produced 有而 truth 无（相对真值多出）；
    only_in_truth = truth 有而 produced 无（相对真值缺失）。
    """
    truth_rest = [list(s) for s in (_canonical_segment(t) for t in truth)]
    matched: list[dict] = []
    only_produced: list[dict] = []
    max_dev = 0.0
    for seg in produced:
        can = _canonical_segment(seg)
        best_i = -1
        best_dev = math.inf
        for i, t in enumerate(truth_rest):
            if t is None:
                continue
            d1 = math.hypot(can[0][0] - t[0][0], can[0][1] - t[0][1])
            d2 = math.hypot(can[1][0] - t[1][0], can[1][1] - t[1][1])
            dev = max(d1, d2)
            if dev < best_dev:
                best_dev = dev
                best_i = i
        if best_i >= 0 and best_dev <= tol:
            matched.append({"produced": list(can), "truth": truth_rest[best_i], "dev_mm": best_dev})
            max_dev = max(max_dev, best_dev)
            truth_rest[best_i] = None
        else:
            only_produced.append({"produced": list(can), "nearest_dev_mm": best_dev if best_i >= 0 else None})
    only_truth = [{"truth": t} for t in truth_rest if t is not None]
    return {
        "matched": matched,
        "matched_count": len(matched),
        "only_in_produced": only_produced,
        "only_in_truth": only_truth,
        "max_dev_mm": max_dev,
        "produced_count": len(produced),
        "truth_count": len(truth),
    }


def _match_circles(
    produced: Sequence[Circle], truth: Sequence[Circle], tol: float
) -> dict:
    """圆级贪心匹配：圆心距 + 半径差都 ≤ tol 判等（通孔完整不简化）."""
    truth_rest = [list(c) for c in truth]
    matched: list[dict] = []
    only_produced: list[dict] = []
    for pc, pr in produced:
        best_i = -1
        best_dev = math.inf
        for i, (tc, tr) in enumerate(truth_rest):
            if tc is None:
                continue
            dev = max(math.hypot(pc[0] - tc[0], pc[1] - tc[1]), abs(pr - tr))
            if dev < best_dev:
                best_dev = dev
                best_i = i
        if best_i >= 0 and best_dev <= tol:
            tc, tr = truth_rest[best_i]
            matched.append(
                {
                    "produced": [list(pc), pr],
                    "truth": [tc, tr],
                    "center_dev_mm": math.hypot(pc[0] - tc[0], pc[1] - tc[1]),
                    "radius_dev_mm": abs(pr - tr),
                }
            )
            truth_rest[best_i] = None
        else:
            only_produced.append(
                {"produced": [list(pc), pr], "nearest_dev_mm": best_dev if best_i >= 0 else None}
            )
    only_truth = [{"truth": t} for t in truth_rest if t is not None]
    return {
        "matched": matched,
        "matched_count": len(matched),
        "only_in_produced": only_produced,
        "only_in_truth": only_truth,
        "produced_count": len(produced),
        "truth_count": len(truth),
    }
