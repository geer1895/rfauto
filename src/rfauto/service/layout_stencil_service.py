"""LC-9 钢网开孔设计闭式面：面积比/宽厚比判据（IPC-7525 双源）。

规格=研究扩充 round15 §四 LC-9"钢网开孔
IPC-7525（P3/S）"；席D3 任务书口径："stencil 开孔设计闭式（面积比/
宽厚比判据 IPC-7525 双源）"。纯闭式（零 IO），JSON 进出信封。

出处（双源，#118/#300；检索时点 2026-10-03，均实测可达）：

- **来源 A（IPC-7525 引述，独立行业源 3 家交叉）**：
  - Siemens EDA 博客《Stencil design considerations during library
    cell design》检索摘要钉值：IPC-7525 宽厚比 = 开孔宽 W/钢片厚 T
    **≥1.5**；面积比 **≥0.66**；
  - PCBCart《Area Ratio Calculation in Solder Paste Stencil Design》
    （WebFetch 原文实测）：矩形开孔 面积比 = (L×W)/(2×(L+W)×T)，
    "a minimum ratio of area of 0.66 is generally required"，引
    IPC-7525；
  - 7PCB《Stencil thickness calculations》（检索摘要钉值）：同公式
    同 0.66 下限。
- **来源 B（几何自明恒等，独立于文献）**：圆形 面积比 =
    (πD²/4)/(πD·T) = D/(4T)；方形（矩形 L=W 特例）= L/(4T)——
    开口面积/孔壁面积定义式的直接代数结果，测试与文献公式互证。

边界（如实登记）：0.66/1.5 为 IPC-7525 **经验推荐阈值**（印刷释放
经验面），非几何恒等式；本面不 ship IPC-7525 原文 PDF（标准文本
付费墙，原文未达——如实，与 RA.769 同口径处理）；nano-coating 等
放宽情形（Siemens 源提及"可低于 0.66"）不进缺省门，调用方以
``ar_min`` 显式覆盖。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "AR_MIN_IPC7525",
    "ASPECT_MIN_IPC7525",
    "aperture_area_ratio",
    "evaluate_apertures",
    "max_foil_thickness",
]

#: 面积比下限（IPC-7525 推荐，来源 A×3 交叉；经验阈值非几何恒等）。
AR_MIN_IPC7525 = 0.66

#: 宽厚比下限 W/T（IPC-7525 推荐，Siemens EDA+FCT 两独立源）。
ASPECT_MIN_IPC7525 = 1.5


def _pos(value: Any, name: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {value!r}")
    return v


def aperture_area_ratio(shape: str, foil_thickness_mm: Any, *,
                        length_mm: Any = None, width_mm: Any = None,
                        diameter_mm: Any = None) -> float:
    """开孔面积比（无量纲）：开口面积 / 孔壁面积。

    - ``rect``：(L×W)/(2×(L+W)×T)（来源 A 公式，L≥W 约定不强制——
      公式对 L/W 对称）；
    - ``circle``：D/(4T)（来源 B 恒等式）；
    - ``square``：A/(4T)（来源 B，矩形 L=W 特例）。

    Raises:
        ValueError: 形状未知或尺寸非正。
    """
    t = _pos(foil_thickness_mm, "foil_thickness_mm")
    s = str(shape).lower()
    if s == "rect":
        length = _pos(length_mm, "length_mm")
        width = _pos(width_mm, "width_mm")
        return (length * width) / (2.0 * (length + width) * t)
    if s == "circle":
        d = _pos(diameter_mm, "diameter_mm")
        return d / (4.0 * t)
    if s == "square":
        a = _pos(length_mm, "length_mm")
        return a / (4.0 * t)
    raise ValueError(f"shape 须 'rect'|'circle'|'square'，实际 {shape!r}")


def max_foil_thickness(
    shape: str,
    *,
    length_mm: Any = None,
    width_mm: Any = None,
    diameter_mm: Any = None,
    ar_min: float = AR_MIN_IPC7525,
    aspect_min: float = ASPECT_MIN_IPC7525,
) -> dict[str, Any]:
    """逆向设计：满足双判据的最大钢片厚度（闭式反解）。

    面积比反解（开口面积/孔壁面积 ≥ ar_min 对 T 求最大）::

        rect:   T ≤ L·W/(2·(L+W)·ar_min)
        circle: T ≤ D/(4·ar_min)      square: T ≤ A/(4·ar_min)

    宽厚比反解：T ≤ W_eff/aspect_min（W_eff=rect 的短边/square 边长/
    circle 直径）。两约束取交（min）。

    Returns:
        dict：t_max_mm（双判据交）、t_area_ratio_mm、t_aspect_mm、
        governing（"area_ratio"|"aspect_ratio"）。
    """
    s = str(shape).lower()
    if s == "rect":
        length = _pos(length_mm, "length_mm")
        width = _pos(width_mm, "width_mm")
        w_eff = min(length, width)
        t_area = length * width / (2.0 * (length + width) * ar_min)
    elif s == "circle":
        w_eff = _pos(diameter_mm, "diameter_mm")
        t_area = w_eff / (4.0 * ar_min)
    elif s == "square":
        w_eff = _pos(length_mm, "length_mm")
        t_area = w_eff / (4.0 * ar_min)
    else:
        raise ValueError(f"shape 须 'rect'|'circle'|'square'，实际 {shape!r}")
    t_aspect = w_eff / aspect_min
    t_max = min(t_area, t_aspect)
    return {
        "t_max_mm": t_max,
        "t_area_ratio_mm": t_area,
        "t_aspect_mm": t_aspect,
        "governing": "area_ratio" if t_area <= t_aspect else "aspect_ratio",
    }


def evaluate_apertures(
    apertures: list[dict[str, Any]],
    foil_thickness_mm: Any,
    *,
    ar_min: float = AR_MIN_IPC7525,
    aspect_min: float = ASPECT_MIN_IPC7525,
) -> dict[str, Any]:
    """批量开孔评估（IPC-7525 双判据逐孔+汇总，信封返回）。

    Args:
        apertures: 逐孔 ``{"name": str, "shape": "rect"|"circle"|
            "square", "length_mm"/"width_mm"/"diameter_mm": ...}``
            （rect 须 length+width；circle 须 diameter；square 须
            length）。
        foil_thickness_mm: 钢片厚度 [mm]。
        ar_min/aspect_min: 判据下限（缺省 IPC-7525；nano-coating 等
            放宽显式传参）。

    Returns:
        ok 信封：results 逐孔（ar/aspect/pass/verdict）、n_pass/n_fail/
        n_total、all_pass；入参非法 error 信封。
    """
    from rfauto.service.envelope import error_envelope, ok_envelope

    if not isinstance(apertures, list) or not apertures:
        return error_envelope("apertures 必须为非空列表")
    try:
        t = _pos(foil_thickness_mm, "foil_thickness_mm")
    except ValueError as exc:
        return error_envelope(str(exc))
    if ar_min <= 0.0 or aspect_min <= 0.0:
        return error_envelope("ar_min/aspect_min 必须为正")

    results: list[dict[str, Any]] = []
    n_pass = 0
    for idx, ap in enumerate(apertures):
        name = str(ap.get("name", f"aperture_{idx}"))
        item: dict[str, Any] = {"name": name}
        try:
            ar = aperture_area_ratio(
                ap.get("shape", ""), t,
                length_mm=ap.get("length_mm"),
                width_mm=ap.get("width_mm"),
                diameter_mm=ap.get("diameter_mm"))
        except (ValueError, TypeError) as exc:
            item.update(ok=False, verdict="INVALID", reason=str(exc))
            results.append(item)
            continue
        # 宽厚比特征宽：rect 短边/square 边长/circle 直径
        shape = str(ap.get("shape", "")).lower()
        if shape == "rect":
            w_eff = min(float(ap["length_mm"]), float(ap["width_mm"]))
        elif shape in ("square", "circle"):
            key = "length_mm" if shape == "square" else "diameter_mm"
            w_eff = float(ap[key])
        else:  # aperture_area_ratio 已报 INVALID，占位跳过
            continue
        aspect = w_eff / t
        passed = ar >= ar_min and aspect >= aspect_min
        item.update(
            ok=True,
            area_ratio=ar,
            aspect_ratio=aspect,
            pass_area_ratio=ar >= ar_min,
            pass_aspect_ratio=aspect >= aspect_min,
            verdict="PASS" if passed else "FAIL",
        )
        if passed:
            n_pass += 1
        results.append(item)
    return ok_envelope(
        results=results,
        n_total=len(results),
        n_pass=n_pass,
        n_fail=len(results) - n_pass,
        all_pass=n_pass == len(results),
        criteria={"ar_min": ar_min, "aspect_min": aspect_min,
                  "source": "IPC-7525（经验推荐阈值）"},
    )
