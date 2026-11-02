"""悬置/倒置/嵌入线族色散标定曲线层（W4-B P7，通用机械件）。

规格出处（SM·core 深化报告 P7，runs/research_seats_20261004/sm_core_deepen/
REPORT.md §3 P7）：inverted_ms/embedded_line/isl_line 三族静态面为**准静态**
口径（FD 裁判 brentq 反解 / 分层串联等效），色散层无可靠闭式——L. K. Wu,
"Analysis of dispersion and series gap discontinuity in shielded suspended
striplines"（1992，全波证：悬置带线色散需全波解，闭式不可达）→ 走本仓
已验证的**标定曲线范式**（hairpin k(g) 先例）：全波引擎（openEMS/HFSS）
在 (f, geometry) 网格少量采样 εeff(f)/Z0(f) 标定表 + 域盒，设计链按表
内插取用，域外显式 REFUSE（精度档案 REFUSE/WARN 制度，宁拒不外推）。

本模块职责边界（#122 如实）：
- **只交付通用机械**：表构造与校验、log-f 内插、域盒 REFUSE、质检诊断、
  静态面一致性对账。零业务依赖、纯 numpy/stdlib 叶子；
- **缺省路径零变化**：仓内无任何既有模块 import 本模块（纯增量 API），
  inverted_ms/embedded_line/isl_line 既有设计链行为逐位不变；
- **采样数据生产属真机批次**（openEMS/HFSS 标定窗），本件不产生任何
  物理数字（铁律 7：数值只在确定性内核+全波引擎，标定表必须携带来源
  meta，无来源的表允许构造但 quality/meta 面如实标注 provenance=absent）。

插值口径：频率轴 log-线性（色散曲线标准做法，低频段分辨率需求高）；
εeff/Z0 值域线性。域盒=采样频率两端闭区间，越界 DispersionRangeError
（附越界相对余量），不外推。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DispersionRangeError",
    "DispersionTable",
    "apply_dispersion",
    "build_dispersion_table",
    "interp_eps_eff",
    "interp_z0",
    "lambda_g_mm",
    "static_consistency",
    "table_quality",
]

#: 空气中光速（m/s，SI 定义值；与 core 既有模块同值口径）
C0 = 299792458.0


class DispersionRangeError(ValueError):
    """频率越出标定表域盒（REFUSE 制度：不外推，调用方换采样窗或降级准静态）。"""


def _finite_positive(value: float, name: str) -> float:
    v = float(value)
    if not (math.isfinite(v) and v > 0.0):
        raise ValueError(f"{name} 必须为正有限数，得到 {value!r}")
    return v


@dataclass(frozen=True)
class DispersionTable:
    """单几何点的色散标定表（εeff(f)/Z0(f)，f 轴严格递增，SI 单位）。

    geometry：几何参数快照 dict（标定所属几何；None=未登记，质检面如实
    标注）。meta：来源快照（engine/模板/日期/run 目录等；消费者不得到
    无 provenance 的表上做精度声明）。
    """

    f_grid_hz: tuple[float, ...]
    eps_eff_grid: tuple[float, ...]
    z0_grid: tuple[float, ...]
    geometry: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        f = tuple(float(v) for v in self.f_grid_hz)
        e = tuple(float(v) for v in self.eps_eff_grid)
        z = tuple(float(v) for v in self.z0_grid)
        object.__setattr__(self, "f_grid_hz", f)
        object.__setattr__(self, "eps_eff_grid", e)
        object.__setattr__(self, "z0_grid", z)
        if len(f) < 2:
            raise ValueError(f"标定表至少 2 个频点，得到 {len(f)}")
        if not (len(f) == len(e) == len(z)):
            raise ValueError(
                f"三表长度不一致：f={len(f)}, eps_eff={len(e)}, z0={len(z)}")
        for i in range(1, len(f)):
            if not (f[i] > f[i - 1]):
                raise ValueError(
                    f"频率轴必须严格递增：f[{i-1}]={f[i-1]!r} >= f[{i}]={f[i]!r}")
        for name, grid in (("eps_eff", e), ("z0", z)):
            for i, v in enumerate(grid):
                if not (math.isfinite(v) and v > 0.0):
                    raise ValueError(
                        f"{name}[{i}]={v!r} 非正有限（标定值非法）")
            if name == "eps_eff" and any(v < 1.0 for v in grid):
                raise ValueError("eps_eff < 1 非物理（悬置族介质/空气混合 ≥1）")

    @property
    def f_min_hz(self) -> float:
        return self.f_grid_hz[0]

    @property
    def f_max_hz(self) -> float:
        return self.f_grid_hz[-1]

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化字典（roundtrip 由单测钉住）。"""
        return {
            "f_grid_hz": list(self.f_grid_hz),
            "eps_eff_grid": list(self.eps_eff_grid),
            "z0_grid": list(self.z0_grid),
            "geometry": dict(self.geometry) if self.geometry else None,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DispersionTable:
        return cls(
            f_grid_hz=tuple(payload["f_grid_hz"]),
            eps_eff_grid=tuple(payload["eps_eff_grid"]),
            z0_grid=tuple(payload["z0_grid"]),
            geometry=payload.get("geometry"),
            meta=dict(payload.get("meta", {})),
        )


def build_dispersion_table(
    f_grid_hz: list[float] | tuple[float, ...],
    eps_eff_grid: list[float] | tuple[float, ...],
    z0_grid: list[float] | tuple[float, ...],
    *,
    geometry: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> DispersionTable:
    """标定表构造入口（校验收敛在 DispersionTable.__post_init__）。"""
    return DispersionTable(
        f_grid_hz=tuple(f_grid_hz),
        eps_eff_grid=tuple(eps_eff_grid),
        z0_grid=tuple(z0_grid),
        geometry=geometry,
        meta=dict(meta or {}),
    )


def _interp_logf(table: DispersionTable, f_hz: float, grid: tuple[float, ...]) -> float:
    f = _finite_positive(f_hz, "f_hz")
    if f < table.f_min_hz or f > table.f_max_hz:
        lo_margin = (table.f_min_hz - f) / table.f_min_hz
        hi_margin = (f - table.f_max_hz) / table.f_max_hz
        raise DispersionRangeError(
            f"f={f:.6g} Hz 越出标定表域盒 "
            f"[{table.f_min_hz:.6g}, {table.f_max_hz:.6g}] Hz"
            f"（越界相对余量 low={lo_margin:+.3%} / high={hi_margin:+.3%}）——"
            "REFUSE 不外推（换采样窗或降级准静态口径）")
    lf = math.log(f)
    lo, hi = 0, len(table.f_grid_hz) - 1
    for i in range(1, len(table.f_grid_hz)):
        if math.log(table.f_grid_hz[i]) >= lf:
            hi = i
            lo = i - 1
            break
    lf_lo = math.log(table.f_grid_hz[lo])
    lf_hi = math.log(table.f_grid_hz[hi])
    if hi == lo:
        return float(grid[lo])
    w = (lf - lf_lo) / (lf_hi - lf_lo)
    return float(grid[lo] * (1.0 - w) + grid[hi] * w)


def interp_eps_eff(table: DispersionTable, f_hz: float) -> float:
    """εeff(f)：log-f 线性内插；域外 DispersionRangeError（不外推）。"""
    return _interp_logf(table, f_hz, table.eps_eff_grid)


def interp_z0(table: DispersionTable, f_hz: float) -> float:
    """Z0(f)：log-f 线性内插；域外 DispersionRangeError（不外推）。"""
    return _interp_logf(table, f_hz, table.z0_grid)


def lambda_g_mm(f_ghz: float, eps_eff: float) -> float:
    """导波波长 λg = c/(f·√εeff)（mm；色散面取用点值的派生量）。"""
    f = _finite_positive(f_ghz, "f_ghz")
    e = _finite_positive(eps_eff, "eps_eff")
    if e < 1.0:
        raise ValueError(f"eps_eff 须 ≥1，得到 {e!r}")
    return C0 / (f * 1e9) / math.sqrt(e) * 1e3


def apply_dispersion(
    table: DispersionTable,
    f_hz: float,
) -> dict[str, float]:
    """设计链取用点：f 处 (eps_eff, z0_ohm, lambda_g_mm)；域外 REFUSE。"""
    e = interp_eps_eff(table, f_hz)
    z = interp_z0(table, f_hz)
    return {
        "eps_eff": e,
        "z0_ohm": z,
        "lambda_g_mm": lambda_g_mm(f_hz / 1e9, e),
        "f_hz": float(f_hz),
    }


def static_consistency(
    table: DispersionTable,
    static_eps_eff: float,
    static_z0_ohm: float,
    *,
    f_ref_hz: float | None = None,
    rel_tol: float = 0.05,
) -> dict[str, Any]:
    """准静态面 vs 标定表低频极限一致性对账（WARN 级诊断，不阻断）。

    准静态值应在表域盒内某参考频点（缺省取表最低频点）与标定值吻合到
    rel_tol——系统性偏离通常指示标定表来源错位（几何/单位/引擎口径）。
    """
    f_ref = float(f_ref_hz) if f_ref_hz is not None else table.f_min_hz
    if not table.f_min_hz <= f_ref <= table.f_max_hz:
        raise DispersionRangeError(
            f"参考频点 {f_ref:.6g} Hz 在标定表域盒外")
    e_tab = interp_eps_eff(table, f_ref)
    z_tab = interp_z0(table, f_ref)
    e_dev = abs(e_tab - static_eps_eff) / static_eps_eff
    z_dev = abs(z_tab - static_z0_ohm) / static_z0_ohm
    return {
        "ok": bool(e_dev <= rel_tol and z_dev <= rel_tol),
        "eps_eff_table": e_tab,
        "z0_table": z_tab,
        "eps_eff_rel_dev": e_dev,
        "z0_rel_dev": z_dev,
        "rel_tol": float(rel_tol),
        "f_ref_hz": f_ref,
    }


def table_quality(
    table: DispersionTable,
    *,
    rel_jump_tol: float = 0.05,
) -> dict[str, Any]:
    """逐相邻频点相对跳变质检（引擎采样噪声守卫；WARN 面，不阻断）。

    真机标定数据物理上逐点光滑（色散连续）；相邻样本相对跳变超
    rel_jump_tol 的位置如实列出（嫌疑=采样噪声/提取失败，交真机批次
    复核），verdict=PASS/WARN。
    """
    worst = {"eps_eff": (0.0, -1), "z0": (0.0, -1)}
    bad: list[dict[str, Any]] = []
    for name, grid in (("eps_eff", table.eps_eff_grid), ("z0", table.z0_grid)):
        for i in range(1, len(grid)):
            jump = abs(grid[i] - grid[i - 1]) / grid[i - 1]
            if jump > worst[name][0]:
                worst[name] = (jump, i)
            if jump > rel_jump_tol:
                bad.append({"quantity": name, "index": i,
                            "rel_jump": jump,
                            "f_hz": table.f_grid_hz[i]})
    verdict = "PASS" if not bad else "WARN"
    provenance = "present" if table.meta else "absent"
    return {
        "verdict": verdict,
        "n_points": len(table.f_grid_hz),
        "rel_jump_tol": float(rel_jump_tol),
        "worst_rel_jump": {k: {"value": v[0], "index": v[1]}
                           for k, v in worst.items()},
        "violations": bad,
        "provenance": provenance,
    }
