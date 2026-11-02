"""TRL 校准件设计数学（aurora_p G1：TRL 设计向导内核，2026-11-02）。

与 :mod:`rfauto.core.trl_solt` 方向相反的两极：trl_solt=**提取内核**
（标准件原始测量 → 误差箱）；本模块=**设计数学**（频带+介质 → 校准件
设计单：Line 长度 λg/4、带宽覆盖核算、多 Line 扩带方案、Reflect 短路/
开路建议）。信息面经用户"按设计单加工→实测"衔接，不经内存耦合（设计
产出几何，实测产物进 trl_solt 提取）。

教科书锚（出处写死 docstring，铁律 7——数值全部闭式产出）：

- **Line = λg/4 @ f0，f0=频带几何平均**：Engen & Hoer 1979 TRL 原始
  文献口径（"Thru-Reflect-Line": An Improved Technique for Network
  Analyzer Calibration, IEEE T-MTT MTT-27(12)）与微波工程教科书惯例
  （Pozar, Microwave Engineering, VNA 校准 TRL 节）；
- **电长度硬约束 θ ∈ (0°, 180°)**：仓内单源 core/trl_solt.py 模块
  docstring"line 选根"节——θ 跨半波长时 arg λ 按 2π 卷绕选根错根，
  无耗情形信息论不可辨，须由设计端排除（本模块覆盖核算即此排除的
  设计端落地）；
- **工程有效窗 20° ≤ θ ≤ 160°（单 Line 有效带宽 8:1）**：TRL 校准件
  设计惯例（Keysight AN 1287-9 "Applying Error Correction to VNA
  Measurements" 与 Dunsmore, Simplified Handbook of VNA Measurement
  的 TRL 设计节同口径）：θ<20° 时 Line 与 Thru 相位差过小、信噪退化
  不可辨；θ>160° 逼近半波长硬约束且损耗/色散放大；
- **Reflect 相位先验 ±90° 内、|Γ|≥0.3**：Keysight 口径（与
  trl_solt 提取端判据同值——提取端常量 _REFLECT_MAG_LITERATURE=0.3
  私有不可导入，本模块按同一文献值显式声明 REFLECT_GAMMA_MIN）；
- **同轴 TEM εeff=εr**：均匀介质填充传输线教科书闭式（相速
  v=c/√εr）；
- **微带 εeff**：仓内单源 :func:`rfauto.core.synthesis.forward_z0`
  （skrf MLine Hammerstad-Jensen+Kirschning-Jansen 色散，禁手抄公式）；
  线宽经 :func:`rfauto.core.synthesis.inverse_width`（50Ω 反解同源）。

准静态设计口径（#122 如实声明）：εeff 取 f0 处单源值，θ∝f 线性化
（介质色散在带内的二阶偏差不进覆盖核算——微带口径 warnings 显式带
色散注记；同轴/εeff 直给口径无此项）。

零 IO、纯函数、确定性（零 uuid 零时间戳）；单位口径 mm/GHz/deg
（与 calc_families C_MM_GHZ 同源光速）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.calc_families.registry import C_MM_GHZ

__all__ = [
    "LINE_COVERAGE_RATIO",
    "LINE_PHASE_TOL_DEG",
    "LINE_THETA_MAX_DEG",
    "LINE_THETA_MIN_DEG",
    "MAX_LINES_DEFAULT",
    "REFLECT_GAMMA_MIN",
    "SINGLE_LINE_MAX_BAND_RATIO",
    "design_trl_standards",
    "line_coverage_band_ghz",
    "line_length_mm",
    "line_theta_deg",
    "multiline_plan_centers",
    "resolve_medium",
]

# ──────────────── 设计规则常量（单源；出处见模块 docstring） ────────────────

#: Line 电长度工程有效窗下缘（deg）：θ<20° Line≈Thru 信噪退化不可辨
LINE_THETA_MIN_DEG = 20.0
#: Line 电长度工程有效窗上缘（deg）：θ>160° 逼近半波长硬约束（θ<180°
#: = core/trl_solt 选根单源硬约束；160° 留 20° 设计裕度）
LINE_THETA_MAX_DEG = 160.0
#: 单 Line 有效带宽比 θmax/θmin=8:1（覆盖带边比，εeff 不进比值）
LINE_COVERAGE_RATIO = LINE_THETA_MAX_DEG / LINE_THETA_MIN_DEG
#: 单 Line 对几何居中频带的最大带宽比：(θmax/90°)²——频带以带心几何
#: 平均居中时，上限受 θmax 约束（16/9)²≈3.16，下限 (90/20)²=20.25
#: 远不绑定
SINGLE_LINE_MAX_BAND_RATIO = (LINE_THETA_MAX_DEG / 90.0) ** 2
#: Line 相位制作容差预算（deg，设计单声明常量非文献值）：按带内最高
#: 工作频率折算长度容差 → length_tol_mm = λg·Δθ/360
LINE_PHASE_TOL_DEG = 2.0
#: 多 Line 方案 Line 数上限（设计单声明常量）：R=8:1 比特下 k=6 覆盖
#: 带宽比 ≈3.16⁶≈1000（三个量级），超限判"覆盖不可达"如实拒绝
MAX_LINES_DEFAULT = 6
#: Reflect 幅值文献判据（Keysight |Γ|≥0.3；与 trl_solt 提取端同值口径
#: ——低于此选根声明不可信，设计端即排除）
REFLECT_GAMMA_MIN = 0.3


# ──────────────────────── 入参收敛守卫（#140 家法） ────────────────────────
def _finite(value: Any, name: str) -> float:
    """收敛入参为有限实数（bool 不算数——bool 是 int 子类）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    return _require(_finite(value, name) > 0.0, name, value, "正数")


def _require(cond: bool, name: str, value: Any, expect: str) -> float:
    if not cond:
        raise ValueError(f"{name} 必须是{expect}，收到 {value!r}")
    return float(value)


# ──────────────────────────── 介质 εeff 解析（单源消费） ────────────────────
_MEDIUM_KEYS = {
    "er_eff": {"kind", "er_eff"},
    "coax": {"kind", "er"},
    "microstrip": {"kind", "er", "h_mm", "w_mm", "tand", "z0_ohm"},
}
_MICROSTRIP_REQUIRED = ("er", "h_mm")


def resolve_medium(medium: Any, f0_ghz: Any) -> dict[str, Any]:
    """介质口径 → εeff 设计值（铁律 7：微带走仓内单源，禁手抄公式）。

    三口径（kind 枚举，严格键）::

        {"kind": "er_eff", "er_eff": v}          直给（实测/未知介质）
        {"kind": "coax", "er": v}                均匀 TEM 同轴（εeff=εr）
        {"kind": "microstrip", "er", "h_mm"[,    微带（skrf HJ+KJ 单源；
            "w_mm", "tand", "z0_ohm"]}            w 缺省 50Ω 反解）

    返回 dict：kind/er_eff/er_eff_source/width_mm/z0_ohm/er/h_mm/tand。
    微带口径 ``er_eff_source`` 形如 ``"synthesis.forward_z0:ep_reff"``
    （synthesis 单源 + εeff 通道标记，XA-4 口径）。物理守卫：εeff≥1、
    εr≥1、h>0、tanδ≥0、Z0>0、w>0，违者显式 ValueError。
    """
    f0 = _positive(f0_ghz, "f0_ghz")
    if not isinstance(medium, dict):
        raise ValueError(f"medium 须为 dict，收到 {type(medium)!r}")
    kind = medium.get("kind")
    if kind not in _MEDIUM_KEYS:
        raise ValueError(
            f"medium.kind 未知 {kind!r}；枚举仅 {sorted(_MEDIUM_KEYS)}")
    allowed = _MEDIUM_KEYS[kind]
    extra = set(medium) - allowed
    if extra:
        raise ValueError(
            f"medium（kind={kind}）存在未支持键 {sorted(extra)}；"
            f"该口径严格键 {sorted(allowed)}")
    if kind == "er_eff":
        if "er_eff" not in medium:
            raise ValueError("medium（kind=er_eff）缺必填键 'er_eff'")
        er_eff = _require(_finite(medium["er_eff"], "medium.er_eff") >= 1.0,
                          "medium.er_eff", medium["er_eff"], "≥1 的实数")
        return {"kind": kind, "er_eff": er_eff,
                "er_eff_source": "user_er_eff", "width_mm": None,
                "z0_ohm": None, "er": None, "h_mm": None, "tand": None}
    er = _require(_finite(medium["er"], "medium.er") >= 1.0,
                  "medium.er", medium["er"], "≥1 的实数")
    if kind == "coax":
        # 均匀介质 TEM 闭式：相速 v=c/√εr → εeff=εr（教科书口径）
        return {"kind": kind, "er_eff": er,
                "er_eff_source": "tem_coax_closed_form", "width_mm": None,
                "z0_ohm": None, "er": er, "h_mm": None, "tand": None}
    # microstrip：εeff/线宽全走 core/synthesis 单源（skrf HJ+KJ）
    for key in _MICROSTRIP_REQUIRED:
        if key not in medium or medium[key] is None:
            raise ValueError(
                f"medium（kind=microstrip）缺必填键 {key!r}")
    h_mm = _positive(medium["h_mm"], "medium.h_mm")
    tand = 0.0 if medium.get("tand") is None else _require(
        _finite(medium["tand"], "medium.tand") >= 0.0,
        "medium.tand", medium["tand"], "≥0 的实数")
    z0_ohm = 50.0 if medium.get("z0_ohm") is None else _positive(
        medium["z0_ohm"], "medium.z0_ohm")
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    stackup = Stackup(name="trl_wizard", epsilon_r=er,
                      thickness_mm=h_mm, loss_tangent=tand)
    if medium.get("w_mm") is not None:
        width = _positive(medium["w_mm"], "medium.w_mm")
    else:
        width, _z0_actual, status = inverse_width(z0_ohm, f0, stackup)
        if status != "ok":
            raise ValueError(
                f"50Ω 线宽反解未自洽（status={status!r}，z0={z0_ohm}Ω@"
                f"{f0}GHz，εr={er} h={h_mm}mm）——几何/频率组合超出 "
                "synthesis 反解域，如实拒绝")
    media = forward_z0(width, f0, stackup)
    return {"kind": kind, "er_eff": float(media.er_eff),
            "er_eff_source": f"synthesis.forward_z0:{media.source}",
            "width_mm": float(width), "z0_ohm": float(media.z0),
            "er": er, "h_mm": h_mm, "tand": tand}


# ──────────────────────────── 闭式设计数学（锚见 docstring） ────────────────
def line_length_mm(f_ghz: Any, er_eff: Any, theta_deg: Any = 90.0) -> float:
    """线长闭式：``L = λg·θ/360 = C_MM_GHZ·θ/(360·f·√εeff)``（mm）。

    θ=90° 即 λg/4（TRL Line 设计值；Engen-Hoer 1979/教科书口径）。"""
    f = _positive(f_ghz, "f_ghz")
    ee = _require(_finite(er_eff, "er_eff") >= 1.0, "er_eff", er_eff,
                  "≥1 的实数")
    theta = _positive(theta_deg, "theta_deg")
    return C_MM_GHZ * theta / (360.0 * f * math.sqrt(ee))


def line_theta_deg(f_ghz: Any, length_mm: Any, er_eff: Any) -> float:
    """电长度闭式：``θ = 360·f·L·√εeff / C_MM_GHZ``（deg；line_length_mm
    的精确逆）。"""
    f = _positive(f_ghz, "f_ghz")
    ee = _require(_finite(er_eff, "er_eff") >= 1.0, "er_eff", er_eff,
                  "≥1 的实数")
    length = _positive(length_mm, "length_mm")
    return 360.0 * f * length * math.sqrt(ee) / C_MM_GHZ


def line_coverage_band_ghz(f0_ghz: Any) -> tuple[float, float]:
    """单 Line（λg/4@f0）有效覆盖带 ``[f0·θmin/90, f0·θmax/90]``（GHz）。

    准静态口径 θ∝f（εeff 不进比值）→ 覆盖带边比恒
    θmax/θmin=8:1（LINE_COVERAGE_RATIO；出处=模块 docstring 有效窗锚）。
    """
    f0 = _positive(f0_ghz, "f0_ghz")
    return (f0 * LINE_THETA_MIN_DEG / 90.0,
            f0 * LINE_THETA_MAX_DEG / 90.0)


def multiline_plan_centers(f_start_ghz: Any, f_stop_ghz: Any,
                           k_lines: Any) -> list[float]:
    """k 条 Line 的几何分带带心列（GHz）：子带按等比几何切分，第 j 条
    带心=其子带的几何平均 ``f0_j = f_start·R^((2j-1)/(2k))``。

    每条 Line 仍 λg/4@自身带心；子带比 ρ=R^(1/k) ≤ SINGLE_LINE_MAX_
    BAND_RATIO 时全部子带被各自 Line 覆盖（design_trl_standards 内
    逐条核算）。相邻 Line 双有效窗（拼接区）=[f0_{j+1}·θmin/90,
    f0_j·θmax/90]，ρ≤8 时非空（ρ≤3.16 设计下恒成立）。
    """
    f_lo = _positive(f_start_ghz, "f_start_ghz")
    f_hi = _finite(f_stop_ghz, "f_stop_ghz")
    if not isinstance(k_lines, int) or isinstance(k_lines, bool) or k_lines < 1:
        raise ValueError(f"k_lines 必须是正整数，收到 {k_lines!r}")
    k = int(k_lines)
    _require(f_hi > f_lo, "f_stop_ghz", f_hi, "大于 f_start_ghz 的实数")
    ratio = f_hi / f_lo
    return [f_lo * ratio ** ((2.0 * j - 1.0) / (2.0 * k))
            for j in range(1, k + 1)]


# ──────────────────────────── 设计单（含覆盖三态核算） ────────────────────
_ANCHORS = {
    "line_length": "λg/4 @ f0（带心=几何平均；Engen-Hoer 1979 TRL / "
                   "Pozar Microwave Engineering TRL 节）",
    "theta_window": "有效窗 20°–160°、单 Line 8:1（Keysight AN 1287-9 / "
                    "Dunsmore Handbook TRL 设计节；硬约束 θ∈(0°,180°)="
                    "core/trl_solt line 选根单源）",
    "reflect": "相位先验 ±90° 内、|Γ|≥0.3（Keysight；trl_solt reflect_kind "
               "选根声明同口径）",
    "coax_er_eff": "均匀介质 TEM εeff=εr（教科书闭式）",
    "microstrip_er_eff": "core/synthesis.forward_z0 单源（skrf HJ+KJ），"
                         "线宽 inverse_width(50) 同源",
}


def _line_entry(index: int, f0_j: float, med: dict[str, Any],
                band_lo: float, band_hi: float) -> dict[str, Any]:
    """单条 Line 设计行（几何+带缘电长度核算+容差折算；内部一致性守卫：
    带缘电长度必须落在有效窗内，违者=设计数学 bug 显式炸）。"""
    ee = med["er_eff"]
    length = line_length_mm(f0_j, ee, 90.0)
    theta_lo = line_theta_deg(band_lo, length, ee)
    theta_hi = line_theta_deg(band_hi, length, ee)
    if not (LINE_THETA_MIN_DEG <= theta_lo <= theta_hi <= LINE_THETA_MAX_DEG):
        raise ValueError(
            f"Line[{index}] 带缘电长度 [{theta_lo:.3f}, {theta_hi:.3f}]deg "
            f"越出有效窗 [{LINE_THETA_MIN_DEG}, {LINE_THETA_MAX_DEG}]deg"
            "（设计数学内部一致性违约），如实拒绝")
    # 长度制作容差按该 Line 服务子带最高频率折算（Δθ→ΔL 线性，高频绑定）
    tol_mm = line_length_mm(band_hi, ee, LINE_PHASE_TOL_DEG)
    return {
        "role": "line",
        "index": index,
        "f_center_ghz": f0_j,
        "length_mm": length,
        "electrical_length_at_center_deg": 90.0,
        "served_band_ghz": [band_lo, band_hi],
        "theta_at_band_edges_deg": [theta_lo, theta_hi],
        "length_tolerance_mm": tol_mm,
        "phase_tolerance_deg": LINE_PHASE_TOL_DEG,
        "width_mm": med.get("width_mm"),
        "z0_ohm": med.get("z0_ohm"),
    }


def design_trl_standards(f_start_ghz: Any, f_stop_ghz: Any, medium: Any,
                         *, max_lines: int = MAX_LINES_DEFAULT) -> dict[str, Any]:
    """TRL 校准件设计单（覆盖三态核算，#122 如实不硬凑）。

    Args:
        f_start_ghz/f_stop_ghz: 频带端点（GHz，f_start>0 且 f_stop>f_start，
            倒置/非有限显式 ValueError）。
        medium: 介质口径 dict（三口径见 resolve_medium）。
        max_lines: 多 Line 方案 Line 数上限（>MAX_LINES_DEFAULT 上限截断）。

    Returns:
        设计单 dict（零 IO，落盘在 service 层）::

            {"method": "trl_design",
             "band_ghz": [f_start, f_stop], "band_ratio": R,
             "f_center_ghz": f0（几何平均）,
             "medium": {...resolve_medium 产物},
             "verdict": "single_line" | "multiline" | "uncovered",
             "covered": bool,
             "single_line_coverage_ghz": [lo, hi],
             "n_lines": int,
             "standards": [thru, reflect, line...]（uncovered 时=[]）,
             "line_overlap_windows_ghz": [[lo, hi], ...],
             "warnings": [str, ...],
             "anchors": {...出处声明}}

    三态语义（验收冻结口径）：

    - ``single_line``：单 Line 覆盖（band ⊆ [f0·2/9, f0·16/9]）；
    - ``multiline``：单 Line 不足但 k=⌈ln R/ln(16/9)²⌉ ≤ max_lines，
      k 条 λg/4 各自覆盖几何子带（逐条核算+相邻拼接窗非空核验）；
    - ``uncovered``：所需 k 超上限——standards=[] 如实拒绝（不硬凑），
      warnings 指明所需 k 与上限。
    """
    f_lo = _positive(f_start_ghz, "f_start_ghz")
    f_hi = _finite(f_stop_ghz, "f_stop_ghz")
    _require(f_hi > f_lo, "f_stop_ghz", f_hi,
             "大于 f_start_ghz 的实数（频率倒置显式拒绝）")
    if not isinstance(max_lines, int) or isinstance(max_lines, bool) \
            or max_lines < 1:
        raise ValueError(f"max_lines 必须是正整数，收到 {max_lines!r}")
    max_lines = min(max_lines, MAX_LINES_DEFAULT)
    ratio = f_hi / f_lo
    f0 = math.sqrt(f_lo * f_hi)  # 带心=几何平均（TRL 设计惯例）
    med = resolve_medium(medium, f0)
    warnings: list[str] = []
    if med["kind"] == "microstrip":
        warnings.append(
            "微带口径 εeff 取带心 f0 处单源值（skrf HJ+KJ 色散）：带内"
            "色散二阶偏差不进覆盖核算（准静态设计口径，#122 如实声明）")
    cov = line_coverage_band_ghz(f0)
    through = {
        "role": "thru",
        "length_mm": 0.0,
        "note": "0 长度直连（两校准面背靠背；同轴系=适配器直连，"
                "微带系=共面直连线段）",
    }
    reflect = {
        "role": "reflect",
        "recommended": "short",
        "gamma_design": "-1（短路，相位 -90°）",
        "alternative": "open（+1，+90°；短路的替换档，两端口同一标准件）",
        "constraints": [
            f"|Γ|≥{REFLECT_GAMMA_MIN}（Keysight 文献判据；低于此提取端 "
            "trl_solt 显式拒绝）",
            "相位已知 ±90° 内（提取端 reflect_kind=short/open 选根声明）",
            "置于 Thru 同一参考平面（校准面=DUT 端口平面）",
        ],
    }

    def _finish(verdict: str, covered: bool, lines: list[dict[str, Any]],
                overlaps: list[list[float]]) -> dict[str, Any]:
        # uncovered=设计单整体拒绝（standards=[]，不硬凑半份单）
        standards: list[dict[str, Any]] = [] if verdict == "uncovered" \
            else [through, reflect, *lines]
        return {
            "method": "trl_design",
            "band_ghz": [f_lo, f_hi],
            "band_ratio": ratio,
            "f_center_ghz": f0,
            "medium": med,
            "verdict": verdict,
            "covered": covered,
            "single_line_coverage_ghz": [cov[0], cov[1]],
            "n_lines": len(lines),
            "standards": standards,
            "line_overlap_windows_ghz": overlaps,
            "warnings": warnings,
            "anchors": dict(_ANCHORS),
        }

    if cov[0] <= f_lo and f_hi <= cov[1]:
        return _finish("single_line", True,
                       [_line_entry(1, f0, med, f_lo, f_hi)], [])
    k = max(1, math.ceil(math.log(ratio) / math.log(SINGLE_LINE_MAX_BAND_RATIO)))
    if k > max_lines:
        warnings.append(
            f"频带比 {ratio:.4g} 需 {k} 条 Line 才能全带覆盖"
            f"（单 Line 8:1 有效窗、几何居中上限 (16/9)²≈3.16），超出"
            f"上限 {max_lines}——如实拒绝出单，不硬凑（#122）")
        return _finish("uncovered", False, [], [])
    warnings.append(
        f"单 Line 覆盖不足（频带比 {ratio:.4g} 超 (16/9)²≈3.16 几何居中"
        f"上限）：已给 k={k} Line 等比分带方案（每条 λg/4@子带带心，"
        "相邻 Line 留拼接窗）")
    lines: list[dict[str, Any]] = []
    overlaps: list[list[float]] = []
    centers = multiline_plan_centers(f_lo, f_hi, k)
    for j, f0_j in enumerate(centers, start=1):
        band_j_lo = f_lo * ratio ** ((j - 1) / k)
        band_j_hi = f_lo * ratio ** (j / k)
        lines.append(_line_entry(j, f0_j, med, band_j_lo, band_j_hi))
    for j in range(k - 1):
        # 相邻 Line 双有效窗（两线电长度同时落在 [20°,160°] 的拼接区）
        ov_lo = centers[j + 1] * LINE_THETA_MIN_DEG / 90.0
        ov_hi = centers[j] * LINE_THETA_MAX_DEG / 90.0
        if ov_lo >= ov_hi:
            raise ValueError(
                f"Line[{j + 1}]/Line[{j + 2}] 拼接窗为空（等比分带系数越界"
                "——设计数学内部一致性违约），如实拒绝")
        overlaps.append([ov_lo, ov_hi])
    return _finish("multiline", True, lines, overlaps)
