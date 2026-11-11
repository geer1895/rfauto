"""IPC-D-356/356A 裸板测试网表解析服务包装（aurora_q 席位 Q-X65，2026-11-07）。

:mod:`rfauto.core.ipc356_parser`（单源解析内核）的规则 4 JSON 进出薄包装
——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict），
零数值逻辑（词法与坐标语义全在 core 确定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_ipc356_file`：IPC-D-356/356A 文件 → 全结构化信封
  （``ipc356 report --file`` 消费）；
- :func:`ipc356_report`：报告面（统计+单点 net 开路嫌疑清单+测试点坐标
  bbox 聚合）——``ipc356 report`` 缺省消费形态；
- :func:`ipc356_fab_pair_check`：356×Gerber/Excellon 只读配对校验
  （``ipc356 report --check-gerber/--check-drill`` 消费）：356 焊盘落
  gerber 包络盒内越界列表 + 钻孔对 356 焊盘覆盖计数（最近邻距离 ≤ 容差
  计覆盖）。**消费 service/fab_gerber_service 的 parse 产物（Q-X59 面
  只读零改动）**——本模块只读其返回信封，不重复实现 gerber/excellon 词法。

错误归一：文件不可读/解码失败（OSError/UnicodeDecodeError）→ error
信封；文件级违规（Ipc356ParseError：空文件/无版本行/无指纹）→ error
信封（errors 恒 list[str]），CLI 层 exit 1。解码链=utf-8 优先、Latin-1
兜底（制造文件正文 ASCII 口径——fab_gerber_service 同款先例）。

配对判定口径（如实三分，#122 不凑绿）：焊盘/孔位坐标任一轴 None（缺 C
因子/单位缺失 fail-soft 面）→ skip 计数（不判越界不判覆盖）；bbox None
（gerber 无几何参照）→ 越界判定全表 skip + note。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——fab_gerber_service 同款先例，新模块零金快照
漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.ipc356_parser import Ipc356ParseError, parse_ipc356
from rfauto.service.envelope import error_envelope, ok_envelope

#: 钻孔↔焊盘覆盖判定的缺省容差（mm；最近邻距离 ≤ 容差计覆盖）。
DEFAULT_PAIR_TOL_MM = 0.5


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8 优先，Latin-1 兜底（制造文件正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _load_document(path: str | Path) -> dict[str, Any]:
    """读文件+解析两步合成（OSError/Ipc356ParseError 由调用方分型捕获）。"""
    return parse_ipc356(_read_text(path))


def parse_ipc356_file(path: str | Path) -> dict[str, Any]:
    """IPC-D-356/356A 文件 → 全结构化信封（头部+记录+net 拓扑+统计面）。

    信封：``{"ok": True, "kind": "ipc356", "path", **doc 全键}`` /
    error 信封（errors 恒 list[str]）。纯只读：不落盘、零网络、零真机。
    """
    try:
        doc = _load_document(path)
    except OSError as exc:
        return error_envelope(f"IPC-D-356 文件不可读: {exc}", kind="ipc356",
                              path=str(path))
    except Ipc356ParseError as exc:
        return error_envelope(f"IPC-D-356 解析失败: {exc}", kind="ipc356",
                              path=str(path))
    return ok_envelope(kind="ipc356", path=str(path), **doc)


def ipc356_report(path: str | Path) -> dict[str, Any]:
    """IPC-D-356 文件 → 报告信封（统计+单点 net+测试点坐标 bbox 聚合）。

    ``ipc356 report`` 缺省消费形态：全量解析单次 + 派生四件套（net 名
    录/单点 net 开路嫌疑清单/测试点 bbox/未挂 net 焊盘），信封
    ``{"ok": True, "kind": "ipc356_report", "path", "version",
    "scale_factor", "nets", "single_point_nets", "bbox_mm", "stats",
    "truncated", "warnings"}`` / error 信封。bbox 聚合口径=焊盘+过孔
    已知坐标（``_mm`` None 点如实剔除；全未知 → None 不猜）。
    """
    result = parse_ipc356_file(path)
    if not result.get("ok"):
        return result
    pts: list[tuple[float, float]] = []
    for entry in [*(result.get("pads") or []), *(result.get("vias") or [])]:
        x, y = entry.get("x_mm"), entry.get("y_mm")
        if x is not None and y is not None:
            pts.append((x, y))
    bbox = (
        [min(p[0] for p in pts), min(p[1] for p in pts),
         max(p[0] for p in pts), max(p[1] for p in pts)]
        if pts else None
    )
    return ok_envelope(
        kind="ipc356_report",
        path=str(path),
        version=result.get("version"),
        scale_factor=result.get("scale_factor"),
        nets=sorted(result.get("nets") or {}),
        single_point_nets=list(
            (result.get("stats") or {}).get("single_point_nets") or []),
        bbox_mm=bbox,
        stats=result.get("stats"),
        truncated=result.get("truncated"),
        warnings=result.get("warnings"),
    )


def ipc356_fab_pair_check(
    ipc_path: str | Path,
    gerber_path: str | Path | None = None,
    drill_path: str | Path | None = None,
    *,
    tol_mm: float = DEFAULT_PAIR_TOL_MM,
) -> dict[str, Any]:
    """IPC-D-356 × Gerber/Excellon 只读配对校验信封。

    两项判定（Q-X59 fab_gerber_service 产物只读消费，零重复词法）：

    - **越界判定**：356 焊盘（两轴已知）是否落 gerber 层包络盒
      （``outline_bbox_mm``）内——任一轴出盒即 ``out_of_bounds`` 条目
      ``{index, net, refdes, pin, x_mm, y_mm, axis, value_mm}``；坐标
      缺轴/bbox 缺失 → ``n_skipped`` 如实（不判越界）；
    - **覆盖判定**（``--check-drill`` 提供时）：Excellon 孔位对 356 焊盘
      最近邻距离 ≤ ``tol_mm`` 计覆盖，未覆盖孔如实清单（含最近邻距离
      与最近焊盘坐标；焊盘坐标全未知 → 该孔 skip）。

    ``gerber_path``/``drill_path`` 至少提供一个（否则 error 信封——CLI
    层先行 usage 守卫）；gerber/drill 任一解析失败 → 首错优先 error 信封。
    信封：``{"ok": True, "kind": "ipc356_pair_check", ...}``。纯只读。
    """
    if gerber_path is None and drill_path is None:
        return error_envelope(
            "配对校验至少需要 gerber/drill 之一（--check-gerber/--check-drill）",
            kind="ipc356_pair_check", path=str(ipc_path))

    doc_env = parse_ipc356_file(ipc_path)
    if not doc_env.get("ok"):
        return doc_env

    gerber: dict[str, Any] | None = None
    if gerber_path is not None:
        from rfauto.service.fab_gerber_service import (  # lazy: fab 配对面延迟导入
            parse_gerber_file,
        )

        gerber = parse_gerber_file(gerber_path)
        if not gerber.get("ok"):
            return gerber

    drill: dict[str, Any] | None = None
    if drill_path is not None:
        from rfauto.service.fab_gerber_service import (  # lazy: fab 配对面延迟导入
            parse_excellon_file,
        )

        drill = parse_excellon_file(drill_path)
        if not drill.get("ok"):
            return drill

    notes: list[str] = []
    pads = list(doc_env.get("pads") or [])
    pad_pts = [(p.get("x_mm"), p.get("y_mm")) for p in pads]
    known_pts = [(x, y) for x, y in pad_pts if x is not None and y is not None]

    # ── 越界判定（gerber 提供时）────────────────────────────────
    out_of_bounds: list[dict[str, Any]] = []
    n_skipped_bounds = 0
    bbox: list[float] | None = None
    bbox_usable = False
    if gerber is not None:
        bbox = gerber.get("outline_bbox_mm")
        bbox_usable = (isinstance(bbox, (list, tuple)) and len(bbox) == 4
                       and all(v is not None for v in bbox))
        if bbox is None:
            notes.append("Gerber 层无几何元素（bbox=None），越界判定全表 skip")
        elif not bbox_usable:
            notes.append("Gerber 包络盒含 None（单位缺失 fail-soft 面），"
                         "越界判定全表 skip")
        xmin, ymin, xmax, ymax = (bbox if bbox_usable else (0, 0, 0, 0))
        for idx, p in enumerate(pads):
            x, y = pad_pts[idx]
            if x is None or y is None:
                n_skipped_bounds += 1
                continue
            if not bbox_usable:
                n_skipped_bounds += 1
                continue
            for axis, val, lo, hi in (("x", x, xmin, xmax),
                                      ("y", y, ymin, ymax)):
                if val < lo or val > hi:
                    out_of_bounds.append({
                        "index": idx,
                        "net": p.get("net"),
                        "refdes": p.get("refdes"),
                        "pin": p.get("pin"),
                        "x_mm": x,
                        "y_mm": y,
                        "axis": axis,
                        "value_mm": val,
                    })
                    break

    # ── 覆盖判定（drill 提供时）─────────────────────────────────
    n_holes = n_covered = 0
    uncovered: list[dict[str, Any]] = []
    n_holes_skipped = 0
    if drill is not None:
        holes = list(drill.get("hits") or [])
        n_holes = len(holes)
        if not known_pts:
            notes.append("356 焊盘坐标全未知（缺 C 因子 fail-soft 面），"
                         "覆盖判定全表 skip")
            n_holes_skipped = n_holes
        for idx, h in enumerate(holes):
            hx, hy = h.get("x_mm"), h.get("y_mm")
            if hx is None or hy is None:
                n_holes_skipped += 1
                continue
            if not known_pts:
                continue
            best_d = None
            best_pt = None
            for px, py in known_pts:
                d = ((hx - px) ** 2 + (hy - py) ** 2) ** 0.5
                if best_d is None or d < best_d:
                    best_d, best_pt = d, (px, py)
            if best_d is not None and best_d <= tol_mm:
                n_covered += 1
            else:
                uncovered.append({
                    "index": idx,
                    "tool": h.get("tool"),
                    "x_mm": hx,
                    "y_mm": hy,
                    "nearest_pad_mm": (round(best_d, 9)
                                       if best_d is not None else None),
                    "nearest_pad_xy": (list(best_pt)
                                       if best_pt is not None else None),
                })

    return ok_envelope(
        kind="ipc356_pair_check",
        path=str(ipc_path),
        ipc_path=str(ipc_path),
        gerber_path=str(gerber_path) if gerber_path is not None else None,
        drill_path=str(drill_path) if drill_path is not None else None,
        version=doc_env.get("version"),
        scale_factor=doc_env.get("scale_factor"),
        n_pads=len(pads),
        n_pads_known=len(known_pts),
        bbox_mm=list(bbox) if bbox_usable else (list(bbox) if bbox else None),
        n_out_of_bounds=len(out_of_bounds),
        out_of_bounds=out_of_bounds,
        n_pads_skipped_bounds=n_skipped_bounds,
        tol_mm=tol_mm,
        n_holes=n_holes,
        n_covered=n_covered,
        n_uncovered=len(uncovered),
        uncovered=uncovered,
        n_holes_skipped=n_holes_skipped,
        drill_available=drill is not None,
        gerber_available=gerber is not None,
        notes=notes,
    )
