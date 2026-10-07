"""KD-10 出版级图表规范检查器+Zenodo 清单（round16 P3，J 流）。

定位（任务书口径，round16 原文"IEEE 双栏 rcParams 检查器"+"出版级
图表+Zenodo 清单"）：
- ``check_ieee_rcparams``：matplotlib rcParams 映射 → IEEE 出版面
  规则门（纯函数，入参任意 Mapping——零 matplotlib 依赖；真实
  rcParams 由调用方 ``matplotlib.rcParams`` 传入，配合
  ``rcparams_from_matplotlib`` 惰性适配器）；
- ``zenodo_checklist``：Zenodo  deposit 元数据 → 必备字段门（确定
  发布清单：title/creators/description/upload_type/access_right/
  license/keywords/related_identifiers）。

IEEE 双栏口径（显式声明，出处=IEEE 作者指南惯例值）：
- 双栏单栏宽 colwidth=3.5in（88.9mm），全宽 fullwidth=7.16in（181.9mm）；
- 正文最小字号 8pt（图内文字不得小于正文）；刻度/标注字号 ≥7pt；
- 线宽 ≥0.5pt；dpi ≥300（位图出版底线）；figure.dpi 仅供屏检不设门；
- 保存面 bbox="tight" 无强制——不进规则面（宁缺毋滥）。

设计约束（确定性内核）：纯函数零 IO；同输入两次输出逐位一致；
rcParams 缺键=如实 UNKNOWN（不猜缺省值——matplotlib 缺省跨版本漂移）。

用法::

    from rfauto.core.publication_standards import (
        check_ieee_rcparams, zenodo_checklist)

    report = check_ieee_rcparams({"font.size": 8, "savefig.dpi": 300,
                                  "lines.linewidth": 1.0})
    zen = zenodo_checklist({"title": "...", "creators": [...], ...})
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: 出版规范检查契约版本。
PUBLICATION_STANDARDS_SCHEMA = "rfauto-publication-standards-v1"

#: IEEE 双栏几何锚（英寸）。
IEEE_COLUMNWIDTH_IN = 3.5
IEEE_FULLWIDTH_IN = 7.16

#: IEEE 出版字号/线宽/分辨率地板。
IEEE_MIN_FONT_PT = 8.0       # 正文最小字号（图内文字跟随）
IEEE_MIN_TICK_PT = 7.0       # 刻度/标注字号地板
IEEE_MIN_LINEWIDTH_PT = 0.5  # 线宽地板（pt）
IEEE_MIN_DPI = 300           # 位图出版底线

#: 刻度字号键族（rcParams 命名跨 matplotlib 版本差异——逐键探测）。
_TICK_KEYS = ("xtick.labelsize", "ytick.labelsize",
              "xtick.major.size", "ytick.major.size")

GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_UNKNOWN = "UNKNOWN"


def _num(value: Any) -> float | None:
    """数值提取（bool 拒绝——bool 是 int 子类但语义非数值）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _size_pt(value: Any) -> float | None:
    """字号提取：数值直接 pt；字符串接受纯数字串（"8"/"8.5"），
    命名尺寸（"small"/"medium"…）如实 None（跨版本映射漂移，不猜）。"""
    n = _num(value)
    if n is not None:
        return n
    if isinstance(value, str):
        s = value.strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


def rcparams_from_matplotlib() -> dict[str, Any]:
    """真实 matplotlib rcParams → 扁平 dict（惰性 import；未装报
    RuntimeError 指向 extra，零 matplotlib 依赖的纯函数面不受影响）。"""
    try:
        import matplotlib
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib 未安装（可选依赖）；纯函数面 check_ieee_rcparams "
            "接受任意 Mapping 不需要 matplotlib") from exc
    keys = ("font.size", "axes.labelsize", "xtick.labelsize",
            "ytick.labelsize", "lines.linewidth", "savefig.dpi",
            "figure.dpi", "figure.figsize", "font.family", "savefig.format")
    flat = dict(matplotlib.rcParams)   # dict[str, Any]（RcParams 字面键型免踩）
    return {k: flat[k] for k in keys if k in flat}


def check_ieee_rcparams(rc: Mapping[str, Any], *,
                        target: str = "column") -> dict[str, Any]:
    """rcParams 映射 → IEEE 双栏出版门（纯函数，零 matplotlib 依赖）。

    target="column"（单栏图 ≤3.5in 宽）| "full"（全宽 ≤7.16in）。
    规则面（每条 {rule, gate, detail}）：
      font_size ≥8pt；tick_size ≥7pt（数值可判时）；line_width ≥0.5pt；
      dpi ≥300（savefig.dpi）；fig_width ≤目标宽（figsize 可判时）。
    缺键/命名字号=UNKNOWN（不翻总门；总门只看 FAIL——测量与报告面，
    #122：非清零运动）。
    """
    if target not in ("column", "full"):
        return {"ok": False, "schema": PUBLICATION_STANDARDS_SCHEMA,
                "target": target, "rules": [], "verdict": GATE_UNKNOWN,
                "issues": [f"target {target!r} 不在 {{column,full}}"]}
    width_cap = IEEE_COLUMNWIDTH_IN if target == "column" else IEEE_FULLWIDTH_IN
    rules: list[dict[str, Any]] = []

    def _add(rule: str, gate: str, detail: str) -> None:
        rules.append({"rule": rule, "gate": gate, "detail": detail})

    # 字号
    fs = _size_pt(rc.get("font.size"))
    if fs is None:
        _add("font_size", GATE_UNKNOWN, f"font.size={rc.get('font.size')!r}（缺键或命名尺寸，不猜）")
    elif fs >= IEEE_MIN_FONT_PT:
        _add("font_size", GATE_PASS, f"font.size={fs:g}pt ≥{IEEE_MIN_FONT_PT:g}")
    else:
        _add("font_size", GATE_FAIL, f"font.size={fs:g}pt <{IEEE_MIN_FONT_PT:g}（IEEE 正文地板）")

    # 刻度字号（数值可判时才判；只收 labelsize 键，major.size 线长键不混入）
    tick_vals: list[float] = []
    for k in ("xtick.labelsize", "ytick.labelsize"):
        v = _size_pt(rc.get(k))
        if v is not None:
            tick_vals.append(v)
    if not tick_vals:
        _add("tick_size", GATE_UNKNOWN, "刻度字号键缺或命名尺寸（不判）")
    elif min(tick_vals) >= IEEE_MIN_TICK_PT:
        _add("tick_size", GATE_PASS, f"min={min(tick_vals):g}pt ≥{IEEE_MIN_TICK_PT:g}")
    else:
        _add("tick_size", GATE_FAIL, f"min={min(tick_vals):g}pt <{IEEE_MIN_TICK_PT:g}")

    # 线宽
    lw = _num(rc.get("lines.linewidth"))
    if lw is None:
        _add("line_width", GATE_UNKNOWN, f"lines.linewidth={rc.get('lines.linewidth')!r}")
    elif lw >= IEEE_MIN_LINEWIDTH_PT:
        _add("line_width", GATE_PASS, f"{lw:g}pt ≥{IEEE_MIN_LINEWIDTH_PT:g}")
    else:
        _add("line_width", GATE_FAIL, f"{lw:g}pt <{IEEE_MIN_LINEWIDTH_PT:g}")

    # 分辨率（savefig.dpi 出图口径；figure.dpi 屏检不设门）
    dpi = _num(rc.get("savefig.dpi"))
    if dpi is None:
        _add("dpi", GATE_UNKNOWN, f"savefig.dpi={rc.get('savefig.dpi')!r}")
    elif dpi >= IEEE_MIN_DPI:
        _add("dpi", GATE_PASS, f"{dpi:g} ≥{IEEE_MIN_DPI:g}")
    else:
        _add("dpi", GATE_FAIL, f"{dpi:g} <{IEEE_MIN_DPI:g}（位图出版底线）")

    # 图宽（figsize=(w,h) 可判时）
    figsize = rc.get("figure.figsize")
    if isinstance(figsize, Sequence) and not isinstance(figsize, str) \
            and len(figsize) >= 1:
        w = _num(figsize[0])
        if w is None:
            _add("fig_width", GATE_UNKNOWN, f"figsize={figsize!r}")
        elif w <= width_cap + 1e-9:
            _add("fig_width", GATE_PASS, f"{w:g}in ≤{width_cap:g}in（{target}）")
        else:
            _add("fig_width", GATE_FAIL,
                 f"{w:g}in >{width_cap:g}in（{target} 版面超宽）")
    else:
        _add("fig_width", GATE_UNKNOWN, f"figure.figsize={figsize!r}（缺键，不猜）")

    has_fail = any(r["gate"] == GATE_FAIL for r in rules)
    verdict = GATE_FAIL if has_fail else GATE_PASS
    return {"ok": True, "schema": PUBLICATION_STANDARDS_SCHEMA,
            "target": target, "rules": rules, "verdict": verdict,
            "issues": [f"{r['rule']}: {r['detail']}" for r in rules
                       if r["gate"] != GATE_PASS]}


# ─── Zenodo 发布清单 ────────────────────────────────────────────────────────

#: Zenodo deposit 必备字段（open deposit 最低可发布形态）。
ZENODO_REQUIRED_FIELDS = (
    "title", "creators", "description", "upload_type",
    "access_right", "license",
)

#: Zenodo upload_type 受控词表（deposit 元数据 schema 主类型面子集，
#: 常见科研发布形态；全表见 Zenodo 官方 docs——按需扩）。
ZENODO_UPLOAD_TYPES = ("publication", "dataset", "software", "lesson",
                       "physicalobject", "workflow", "other")

#: access_right 受控词表。
ZENODO_ACCESS_RIGHTS = ("open", "embargoed", "restricted", "closed")


def zenodo_checklist(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Zenodo deposit 元数据 → 发布清单门（确定性纯函数）。

    门面：必备字段齐备（缺=FAIL）/upload_type 与 access_right 在受控
    词表（词表外=FAIL）/open 或 embargoed 须有 license/restricted 须有
    access_conditions/creators 非空表且含 name/DOI 占位符（"10.0000/
    zenodo." 自引循环）=FAIL（发布时由 Zenodo 授予，不得预写死）。
    """
    checks: list[dict[str, Any]] = []
    issues: list[str] = []

    def _add(rule: str, gate: str, detail: str) -> None:
        checks.append({"rule": rule, "gate": gate, "detail": detail})
        if gate == GATE_FAIL:
            issues.append(f"{rule}: {detail}")

    ar = metadata.get("access_right")
    missing = [f for f in ZENODO_REQUIRED_FIELDS
               if f not in metadata
               and not (f == "license" and ar == "restricted")]
    _add("required_fields", GATE_PASS if not missing else GATE_FAIL,
         "全齐" if not missing else f"缺 {missing}")

    ut = metadata.get("upload_type")
    if ut in ZENODO_UPLOAD_TYPES:
        _add("upload_type", GATE_PASS, str(ut))
    else:
        _add("upload_type", GATE_FAIL, f"{ut!r} 不在受控词表")

    ar = metadata.get("access_right")
    if ar in ZENODO_ACCESS_RIGHTS:
        _add("access_right", GATE_PASS, str(ar))
    else:
        _add("access_right", GATE_FAIL, f"{ar!r} 不在受控词表")

    if not isinstance(metadata.get("creators"), (list, tuple)) or \
            not metadata.get("creators"):
        _add("creators", GATE_FAIL, "creators 须为非空列表")
    else:
        creators = list(metadata["creators"])
        bad = [c for c in creators
               if not isinstance(c, Mapping) or not str(c.get("name", "")).strip()]
        _add("creators", GATE_PASS if not bad else GATE_FAIL,
             f"{len(creators)} 位" if not bad else f"{len(bad)} 条缺 name")

    if ar in ("open", "embargoed") and not metadata.get("license"):
        _add("license", GATE_FAIL, f"access_right={ar} 须声明 license")
    elif ar == "restricted" and not str(metadata.get("access_conditions", "")).strip():
        _add("access_conditions", GATE_FAIL,
             "restricted 访问须给 access_conditions")
    else:
        _add("license_conditions", GATE_PASS,
             f"license={metadata.get('license')!r}, "
             f"access_right={ar!r}")

    doi = str(metadata.get("doi", "") or "")
    if "zenodo." in doi and doi.startswith("10.0000/"):
        _add("doi_placeholder", GATE_FAIL,
             "DOI 是 Zenodo 占位符（自引循环）——发布由平台授予，须删")
    else:
        _add("doi_placeholder", GATE_PASS, doi or "（未预写，正确）")

    verdict = GATE_FAIL if issues else GATE_PASS
    return {"ok": True, "schema": PUBLICATION_STANDARDS_SCHEMA,
            "verdict": verdict, "checks": checks, "issues": issues}
