"""F-J.5 过孔工艺参数面（能力表 + 背钻联动 + IPC-4761 登记 + 可制造性判定）。

定位（研究扩充 round5 §三件 5）：过孔工艺能力
**登记面**——机械钻/激光钻带、孔铜 20–25µm（IPC-6012 Class 2/3 最小平均
孔铜口径带）、埋盲孔叠构约束，常量+来源登记；背钻残段 → fres → 奈奎斯特
带 verdict 为 core/fab_check.py HS-2 面（``stub_resonance_ghz``/
``check_stub_resonance``/``check_backdrill``，DP-7 件）的**薄包装（只读
复用，同输入同输出逐位一致，判定行 codes 原样透传）**；IPC-4761 塞孔
覆围口径登记（Type VII 填充+帽盖为盘内孔/BGA 惯例要求）——登记面，
不做 DFM 全门（round5 规格标"登记"）。

UNVERIFIED 清单（厂商能力表多半不可达——用 IPC 公开带+惯例量级+如实
标注，不虚构出处；具体 fab 以 core/fab_check.py FabProfile 剖面为准，
本模块 capability 参数可整体替换）：
- 机械钻最小孔径 0.15mm（先进 0.10mm）与纵横比 8:1（先进 10:1）：
  IPC-2222 设计指南惯例带与行业公开能力页量级，未逐厂商 verified-web；
- 成品孔径公差 ±0.08mm：IPC-2222 惯例口径带 UNVERIFIED；
- 激光钻 UV/CO2 孔径域与盲孔深径比 ≤1：行业惯例量级 UNVERIFIED；
- 孔铜 Class 2 ≥20µm / Class 3 ≥25µm（最小平均口径，20–25µm 带=
  round5 规格给定）：IPC-6012 常引口径，本模块未持原文逐位核对；
- IPC-4761 Type I–VII 分类表体：标准分类结构登记，逐类型定义以标准
  原文为准（UNVERIFIED 未持原文）。

判定口径（#122 先行，钉死一种）：区间判定 ``value < limit → FAIL``，
**恰等上界 = PASS**（与 fab_check.check_stub_resonance 的
``fres < limit`` 违规判据同向）；可选几何（board_thickness_mm/
hole_copper_um）判缺失一律 is not None——缺省跳过该检查并在 checks
留 ``verdict="skipped"``（不静默）；数值 0.0 合法（给了 0.0 即按 0.0
判，#364④）；bool 显式拒收（df7+⑯）。

接口：纯函数零 IO（fab_check 亦零 IO 面）；Capability/Report dataclass
+to_dict（JSON 可序列化）。不进 calculators 注册表（core 叶约定）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from rfauto.core.fab_check import check_backdrill, check_stub_resonance, stub_resonance_ghz

__all__ = [
    "HOLE_COPPER_UM_BY_CLASS",
    "IPC4761_TYPE_VII",
    "IPC4761_VIA_PROTECTION_TYPES",
    "LASER_DRILL_CO2",
    "LASER_DRILL_UV",
    "MECHANICAL_DRILL",
    "LaserDrillCapability",
    "MechanicalDrillCapability",
    "ViaMfgReport",
    "backdrill_fres_verdict",
    "backdrill_residual_len_mm",
    "backdrill_verdict_from_span",
    "check_via_manufacturability",
    "residual_stub_fres_ghz",
]

# ─── 数值守卫（bool 拒收，df7+⑯；0.0 合法，#364④） ───────────────────────────


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {out!r}")
    return out


def _nonneg(value: float, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 ≥0，收到 {out!r}")
    return out


# ─── 工艺能力表（常量登记；UNVERIFIED 见模块 docstring） ──────────────────────


@dataclass(frozen=True)
class MechanicalDrillCapability:
    """机械钻能力带（mm / 无量纲纵横比；整体可被 fab 剖面能力替换）。"""

    min_drill_mm: float
    advanced_min_drill_mm: float
    finished_hole_tol_mm: float
    max_aspect_ratio: float
    advanced_max_aspect_ratio: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_drill_mm": self.min_drill_mm,
            "advanced_min_drill_mm": self.advanced_min_drill_mm,
            "finished_hole_tol_mm": self.finished_hole_tol_mm,
            "max_aspect_ratio": self.max_aspect_ratio,
            "advanced_max_aspect_ratio": self.advanced_max_aspect_ratio,
            "source": self.source,
        }


@dataclass(frozen=True)
class LaserDrillCapability:
    """激光钻能力带（band=uv/co2；盲孔微孔域）。"""

    band: str
    min_drill_mm: float
    max_drill_mm: float
    max_aspect_ratio: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "min_drill_mm": self.min_drill_mm,
            "max_drill_mm": self.max_drill_mm,
            "max_aspect_ratio": self.max_aspect_ratio,
            "source": self.source,
        }


#: 机械钻缺省能力（UNVERIFIED 惯例带，见模块 docstring）：0.15mm 量产/
#: 0.10mm 先进最小孔径；成品孔径公差 ±0.08mm；纵横比 8:1 常规/10:1 先进。
MECHANICAL_DRILL = MechanicalDrillCapability(
    min_drill_mm=0.15,
    advanced_min_drill_mm=0.10,
    finished_hole_tol_mm=0.08,
    max_aspect_ratio=8.0,
    advanced_max_aspect_ratio=10.0,
    source=(
        "IPC-2222 设计指南惯例带+行业公开能力页量级；UNVERIFIED 未逐厂商核对——"
        "具体 fab 以 core/fab_check.py FabProfile.min_drill_mm 为准（capability 可替换）"
    ),
)

#: 激光钻 UV/CO2 缺省能力（UNVERIFIED 惯例量级）：UV 50–150µm、CO2
#: 100–250µm，盲孔深径比 ≤1。
LASER_DRILL_UV = LaserDrillCapability(
    band="uv",
    min_drill_mm=0.05,
    max_drill_mm=0.15,
    max_aspect_ratio=1.0,
    source="UV 激光微孔惯例带（50–150µm、盲孔深径比 ≤1）；UNVERIFIED",
)
LASER_DRILL_CO2 = LaserDrillCapability(
    band="co2",
    min_drill_mm=0.10,
    max_drill_mm=0.25,
    max_aspect_ratio=1.0,
    source="CO2 激光微孔惯例带（100–250µm、盲孔深径比 ≤1）；UNVERIFIED",
)

#: 孔铜厚度带（µm，最小平均口径）：IPC-6012 Class 2 ≥20µm / Class 3
#: ≥25µm——round5 规格"孔铜 20–25µm"口径（常引带，UNVERIFIED 未持原文）。
HOLE_COPPER_UM_BY_CLASS: dict[str, float] = {
    "class_2": 20.0,
    "class_3": 25.0,
}

#: 埋盲孔叠构约束（登记面，UNVERIFIED 惯例量级；具体叠构以 fab 剖面为准）。
BLIND_BURIED_STACKUP_CONSTRAINTS: dict[str, Any] = {
    "max_sequential_lamination_cycles": 2,  # 连续压合次数惯例上限（HDI 任意层另议）
    "blind_via_max_aspect_ratio": 1.0,  # 机械盲孔深径比惯例上限
    "laser_microvia_max_aspect_ratio": 1.0,  # 激光微孔深径比（与 LASER_DRILL_* 一致）
    "min_stagger_distance_mm": 0.15,  # 相邻层盲孔错位间距惯例量级
    "source": "HDI 惯例量级登记；UNVERIFIED 未逐厂商核对",
}


# ─── IPC-4761 塞孔覆围口径登记（登记面，不做 DFM 全门） ───────────────────────

#: IPC-4761 过孔保护类型 I–VII（分类结构登记；逐类型定义以标准原文为准，
#: UNVERIFIED 未持原文）。filled=孔内填充；capped=填充上再电镀帽盖。
IPC4761_VIA_PROTECTION_TYPES: dict[str, dict[str, Any]] = {
    "type_i": {
        "label": "Type I",
        "en": "tented over via",
        "zh": "阻焊/干膜盖孔（跨孔盖帽，无填充）",
        "filled": False,
        "capped": False,
    },
    "type_ii": {
        "label": "Type II",
        "en": "tented and plugged",
        "zh": "盖孔+堵塞（次要面堵塞）",
        "filled": False,
        "capped": False,
    },
    "type_iii": {
        "label": "Type III",
        "en": "plugged and covered",
        "zh": "堵塞+覆盖（非电镀覆盖）",
        "filled": False,
        "capped": False,
    },
    "type_iv": {
        "label": "Type IV",
        "en": "plugged and capped",
        "zh": "堵塞+电镀帽盖",
        "filled": False,
        "capped": True,
    },
    "type_v": {
        "label": "Type V",
        "en": "filled",
        "zh": "孔内填充（树脂/导电胶，无覆盖）",
        "filled": True,
        "capped": False,
    },
    "type_vi": {
        "label": "Type VI",
        "en": "filled and covered",
        "zh": "填充+覆盖（非电镀覆盖）",
        "filled": True,
        "capped": False,
    },
    "type_vii": {
        "label": "Type VII",
        "en": "filled and capped",
        "zh": "填充+电镀帽盖（盘内孔/BGA 惯例要求）",
        "filled": True,
        "capped": True,
        "design_note": "盘内孔（via-in-pad）/BGA 扇出过孔推荐 Type VII——填实防吸锡/冒锡，镀帽保焊盘平面度",
    },
}

#: Type VII 直取键（登记面消费者免拼字符串）。
IPC4761_TYPE_VII = IPC4761_VIA_PROTECTION_TYPES["type_vii"]


# ─── 背钻联动（fab_check HS-2 面薄包装，只读复用，同输入同输出逐位一致） ─────


def residual_stub_fres_ghz(stub_len_mm: float, er_eff: float) -> float:
    """背钻残段 fres（GHz）——``fab_check.stub_resonance_ghz`` 薄包装。

    逐位一致（同一实现），手算锚 L=10mm/εr_eff=4.0 → 3.747405725 GHz
    （tests/unit/test_fab_stub_gate.py 同源锚）。
    """
    return stub_resonance_ghz(stub_len_mm, er_eff)


def backdrill_residual_len_mm(via_span_mm: float, backdrill_depth_mm: float) -> float:
    """背钻残段长 = max(span − depth, 0)（与 ``fab_check.check_backdrill`` 同式）。"""
    span = _positive(via_span_mm, "via_span_mm")
    depth = _nonneg(backdrill_depth_mm, "backdrill_depth_mm")
    return max(span - depth, 0.0)


def backdrill_fres_verdict(
    stub_len_mm: float,
    er_eff: float,
    nyquist_ghz: float,
    margin_frac: float = 1.0,
) -> dict[str, Any]:
    """残段 → fres → 奈奎斯特带 verdict（薄包装，判定与 HS-2 逐位一致）。

    口径钉死（恰等上界=PASS 一种）：fres ≥ margin_frac×nyquist（**含
    恰等**）→ ``outside_band``（ok=True）；fres < 门限 → ``notch_risk``
    （带内 notch 风险，ok=False）——与 fab_check.check_stub_resonance 的
    ``fres < limit`` 违规判据逐位同向（判定行由该函数产出，本函数只聚合）。
    """
    nyq = _positive(nyquist_ghz, "nyquist_ghz")
    mf = _positive(margin_frac, "margin_frac")
    fres = residual_stub_fres_ghz(stub_len_mm, er_eff)
    rows = check_stub_resonance(stub_len_mm, er_eff, nyquist_ghz=nyq, margin_frac=mf)
    notch = any(r["code"] == "STUB_RES" for r in rows)
    return {
        "ok": not notch,
        "fres_ghz": fres,
        "nyquist_ghz": nyq,
        "margin_frac": mf,
        "limit_ghz": mf * nyq,
        "verdict": "notch_risk" if notch else "outside_band",
        "in_band": notch,
        "rows": rows,
        "source": "core/fab_check.check_stub_resonance 薄包装（判定逐位一致）",
    }


def backdrill_verdict_from_span(
    via_span_mm: float,
    backdrill_depth_mm: float,
    min_remaining_mm: float,
    er_eff: float,
    nyquist_ghz: float | None = None,
) -> dict[str, Any]:
    """过孔跨度+背钻深度 → 聚合 verdict（``fab_check.check_backdrill`` 薄包装）。

    codes/rows 与 fab_check.check_backdrill **同输入逐行一致**（原样透传）；
    ok = 无硬违规行（code 不以 ``_INFO`` 结尾，fab_check 聚合口径）；
    residual/fres 为聚合视图（残段=0 时 fres=None——与 check_backdrill
    残段 0 不做谐振比对同口径）。
    """
    rows = check_backdrill(
        via_span_mm, backdrill_depth_mm, min_remaining_mm, er_eff, nyquist_ghz=nyquist_ghz
    )
    residual = backdrill_residual_len_mm(via_span_mm, backdrill_depth_mm)
    fres = residual_stub_fres_ghz(residual, er_eff) if residual > 0.0 else None
    hard = [r for r in rows if not r["code"].endswith("_INFO")]
    return {
        "ok": not hard,
        "codes": [r["code"] for r in rows],
        "rows": rows,
        "residual_len_mm": residual,
        "fres_ghz": fres,
        "nyquist_ghz": nyquist_ghz,
        "source": "core/fab_check.check_backdrill 薄包装（同输入同输出）",
    }


# ─── 可制造性判定面（区间判定，恰等上界=PASS） ────────────────────────────────


@dataclass(frozen=True)
class ViaMfgReport:
    """过孔可制造性判定报告（ok=无 FAIL 检查项；checks 逐项留痕）。"""

    ok: bool
    ipc_class: str
    checks: list[dict[str, Any]]
    capability: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "ipc_class": self.ipc_class,
            "checks": [dict(c) for c in self.checks],
            "capability": dict(self.capability),
        }


def check_via_manufacturability(
    drill_mm: float,
    *,
    board_thickness_mm: float | None = None,
    hole_copper_um: float | None = None,
    ipc_class: str = "class_2",
    capability: MechanicalDrillCapability | None = None,
) -> ViaMfgReport:
    """过孔参数 vs 能力表区间判定：孔径 / 纵横比 / 孔铜三面。

    - 孔径：``drill_mm ≥ capability.min_drill_mm``（恰等 = PASS）；
    - 纵横比（可选，board_thickness_mm 给出才判）：``板厚/孔径 ≤
      capability.max_aspect_ratio``（恰等 = PASS）；
    - 孔铜（可选，hole_copper_um 给出才判）：``hole_copper_um ≥
      HOLE_COPPER_UM_BY_CLASS[ipc_class]``（恰等 = PASS）。

    可选几何判缺失 is not None——缺省跳过并在 checks 记
    ``verdict="skipped"``（不静默）；数值 0.0 是合法给定值（按 0.0 判，
    #364④）。ipc_class 不在能力表 → ValueError。code 命名对齐
    fab_check VIOLATION_CODES 风格（``*_BELOW_MIN``/``*_ABOVE_MAX``）。
    """
    if ipc_class not in HOLE_COPPER_UM_BY_CLASS:
        raise ValueError(
            f"ipc_class 必须是 {sorted(HOLE_COPPER_UM_BY_CLASS)} 之一，实际 {ipc_class!r}"
        )
    cap = MECHANICAL_DRILL if capability is None else capability
    drill = _positive(drill_mm, "drill_mm")

    checks: list[dict[str, Any]] = []
    drill_ok = drill >= cap.min_drill_mm
    checks.append(
        {
            "check": "min_drill_mm",
            "value": drill,
            "limit": cap.min_drill_mm,
            "verdict": "pass" if drill_ok else "fail",
            "code": None if drill_ok else "DRILL_BELOW_MIN",
            "detail": f"孔径 {drill}mm vs 最小孔径 {cap.min_drill_mm}mm（恰等=PASS 口径）",
        }
    )

    aspect_ok = True
    if board_thickness_mm is not None:
        thickness = _positive(board_thickness_mm, "board_thickness_mm")
        aspect = thickness / drill
        aspect_ok = aspect <= cap.max_aspect_ratio
        checks.append(
            {
                "check": "aspect_ratio",
                "value": aspect,
                "limit": cap.max_aspect_ratio,
                "verdict": "pass" if aspect_ok else "fail",
                "code": None if aspect_ok else "ASPECT_RATIO_ABOVE_MAX",
                "detail": (
                    f"纵横比 板厚 {thickness}mm/孔径 {drill}mm={aspect:.4g} vs 上限 "
                    f"{cap.max_aspect_ratio}（恰等=PASS 口径）"
                ),
            }
        )
    else:
        checks.append(
            {
                "check": "aspect_ratio",
                "value": None,
                "limit": cap.max_aspect_ratio,
                "verdict": "skipped",
                "code": None,
                "detail": "board_thickness_mm 未给（None），跳过纵横比判定",
            }
        )

    copper_ok = True
    if hole_copper_um is not None:
        copper = _nonneg(hole_copper_um, "hole_copper_um")
        min_um = HOLE_COPPER_UM_BY_CLASS[ipc_class]
        copper_ok = copper >= min_um
        checks.append(
            {
                "check": "hole_copper_um",
                "value": copper,
                "limit": min_um,
                "verdict": "pass" if copper_ok else "fail",
                "code": None if copper_ok else "HOLE_COPPER_BELOW_MIN",
                "detail": (
                    f"孔铜 {copper}µm vs {ipc_class} 最小平均 {min_um}µm（恰等=PASS 口径）"
                ),
            }
        )
    else:
        checks.append(
            {
                "check": "hole_copper_um",
                "value": None,
                "limit": HOLE_COPPER_UM_BY_CLASS[ipc_class],
                "verdict": "skipped",
                "code": None,
                "detail": "hole_copper_um 未给（None），跳过孔铜判定",
            }
        )

    ok = drill_ok and aspect_ok and copper_ok
    return ViaMfgReport(
        ok=ok,
        ipc_class=ipc_class,
        checks=checks,
        capability=cap.to_dict(),
    )
