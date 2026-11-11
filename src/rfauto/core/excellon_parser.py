"""Excellon 钻孔文件结构化解析内核（aurora_q 席位 Q-X59，2026-11-07）。

PCB 制造事实标准 **Excellon**（Excellon Dynamics CNC-7/Format 2 公开口径，
与 artwork.com 格式指南等公开文档相互印证）的只读指令级结构化解析：刀具
登记 + 钻点/槽孔/路由模式 + 孔位统计面。全部词法与数值语义在 core 确定性
内核（铁律 7：结构化数字只出自数据源文本本身）。服务包装见
:mod:`rfauto.service.fab_gerber_service`，CLI 薄壳= cli/fab_app 的
``fab parse --drill`` 消费面。

词法覆盖面（逐条落地）：

- 头部 ``M48`` 起 / ``%``（rewind=头尾界，M95 亦收尾界）；``;`` 注释行
  整行收编；``FMAT,2`` 格式代登记；
- ``INCH``/``METRIC`` + ``LZ``/``TZ``（LZ=**前导零保持**——坐标按"整数
  位+小数位"定长拆分；TZ=**尾随零保持**——同一定长拆分：两种模式只是
  缺位补零方向相反，文件中出现的数字串本身完整，整数值恒为字面量整值，
  拆分算法与模式无关）；单位换算 INCH ×25.4 → mm（精确十进制）；
- 刀具登记：头部 ``T01C0.020``（T 号 + C 直径——单位随 INCH/METRIC）+
  ``T01C0.020F090S017`` 等附加参数（F 进给/S 转速，登记原文不解释）；
  体段 ``T##`` 单独成句=选刀（模态保持）；``T0`` 复位（current=None）；
- 钻模式 ``G00``/``G05``（drill mode，登记 current drill mode）；路由
  ``G41``/``G42``（左/刀补路由模式，登记如实 ``route_mode``）；
- 钻点 ``X#Y#``（坐标按单位+定长拆分；只给 X 或只给 Y → 缺轴沿用当前
  点模态——Excellon 模态续用惯例如实遵循）；无坐标行=零移动不产 hit；
- 槽孔 ``G85``：``X..Y..G85X..Y..`` 两点槽（from/to 双点 + 选刀 D 码）；
- ``M30``/``M00`` 结束（其后残余 warning 如实忽略）；``M97/M98`` 文字
  钻/``R##`` step-repeat（登记 warning 不展开——超出本席契约面）。

坐标拆分口径：Excellon 头部**不声明整数/小数位**（与 Gerber FS 不同）
——缺省按 KiCad/行业惯例 **6 位定标**（INCH: 000000-016000 →
0.000-1.600 inch；METRIC 同 6 位小数）；``;FILE_FORMAT=2:5`` 类 X2 注释
出现时按注释位数定标（登记 format_from_comment）。该缺省是**声明限制**
（``decimals_source`` 键如实回显），非规范保证——消费方可用 summary
交叉核对。

fail-soft 口径（citi_parser/gdsii_parser/gerber_parser 家法）：单条命令
词法/语义违规 → warning + 跳过；``truncated=True``（未遇 M30 即流尾）；
非法坐标字面量 warning 保留；头部缺 M48/单位未声明 → warning + 单位
None（``_mm`` 如实 None 不猜）。文件级错误（空文本/无任何指纹）→
:class:`ExcellonParseError`（服务层转 error 信封）。

统计面：:func:`excellon_hit_grid_summary`——孔位 bbox + 最近邻间距统计
（n<2 如实 None，不做虚假统计）。

确定性（同输入同输出）、零 IO、零第三方依赖。本模块不设 ``__all__``
（无 __all__ 文件不进 tests/gold/public_api.json——verilog_netlist_
parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 缺省定标小数位（Excellon 头部不声明位数；KiCad/行业惯例 6 位）。
DEFAULT_DECIMALS = 6

#: INCH → mm 换算系数（规范定义 1 inch = 25.4 mm，精确十进制）。
INCH_TO_MM = 25.4

#: 槽孔 G 码（Format 2）。
SLOT_GCODE = "G85"


class ExcellonParseError(ValueError):
    """Excellon 文件级错误（空/不像 Excellon——区别于流中逐条 fail-soft）。"""


#: 体指令坐标词（X/Y + 符号数字，含小数点异端形态容错）。
_COORD_RE = re.compile(r"([XY])([+-]?\d+(?:\.\d+)?)")
#: 头部刀具登记：T 号 + C 直径（+ 可选 F/S 等附加参数原样）。
_TOOL_DEF_RE = re.compile(
    r"^T(\d+)C(\d*\.?\d+)(?:.*?F(\d*\.?\d+))?(?:.*?S(\d*\.?\d+))?.*$")
#: X2 注释坐标格式：;FILE_FORMAT=2:5（abs:int:dec）。
_FILE_FORMAT_RE = re.compile(r";\s*FILE_FORMAT\s*=\s*\d+:(\d+)", re.IGNORECASE)
#: G 码词提取（G00/G05/G41/G42/G85）。
_G_CODE_RE = re.compile(r"G(\d+)")
#: T 词提取（选刀 T0/T01..）。
_T_WORD_RE = re.compile(r"\bT(\d+)\b")
#: M 码词提取（M30/M00/M95/M97/M98）。
_M_CODE_RE = re.compile(r"\bM(\d+)\b")


def _warn(warnings: list[str], message: str) -> None:
    """warning 同文去重追加（逐条披露不改据）。"""
    if message not in warnings:
        warnings.append(message)


def split_excellon_number(raw: str, decimals: int) -> Fraction | None:
    """定长坐标数字 → 精确文件单位值（Fraction；LZ/TZ 两模式同算法）。

    ``INCH,LZ`` 6 位 + ``"005000"`` → 5000/10^6 = 0.005 inch（表驱动
    已知量断言家法 #118——tests 钉同表）。带小数点形态按浮点直读。
    非法字面量如实 None。
    """
    if not raw:
        return None
    if "." in raw:
        try:
            return Fraction(raw)
        except (ValueError, ZeroDivisionError):
            return None
    if not re.fullmatch(r"[+-]?\d+", raw):
        return None
    return Fraction(int(raw), 10 ** decimals)


class _UnitConv:
    """文件单位 → mm 换算（INCH ×25.4 / METRIC 恒等；缺失=不定标）。"""

    def __init__(self, units: str | None) -> None:
        self.units = units
        self._factor: Fraction | None
        if units == "METRIC":
            self._factor = Fraction(1)
        elif units == "INCH":
            self._factor = Fraction(127, 5)
        else:
            self._factor = None

    def to_mm(self, value_unit: Fraction | None) -> float | None:
        if value_unit is None or self._factor is None:
            return None
        return round(float(value_unit * self._factor), 9)


def parse_excellon(text: str) -> dict[str, Any]:
    """Excellon 文本 → 结构化文档（确定性、零 IO、fail-soft warnings）。

    Returns:
        doc：``{"schema", "units", "zero_mode", "decimals",
        "decimals_source", "fmat", "tools", "hits", "slots",
        "route_mode", "stats", "truncated", "warnings"}``。

    Raises:
        ExcellonParseError: 空文本或无任何 Excellon 指纹。
    """
    warnings: list[str] = []
    units: str | None = None
    zero_mode: str | None = None
    decimals = DEFAULT_DECIMALS
    decimals_source = "default6"
    fmat: str | None = None
    tools: dict[str, dict[str, Any]] = {}
    hits: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    route_mode: str | None = None

    conv = _UnitConv(None)
    current_tool: str | None = None
    cur_x: Fraction | None = None
    cur_y: Fraction | None = None
    in_header = False
    truncated = True
    saw_fingerprint = False

    lines = text.splitlines()

    def _xy_of(words: dict[str, str]) -> tuple[Fraction | None, Fraction | None]:
        """坐标词 + 模态续用 → (x, y)（非法/单位未知如实 None 面）。"""
        nonlocal cur_x, cur_y
        x, y = cur_x, cur_y
        for axis in ("X", "Y"):
            if axis not in words:
                continue
            val = split_excellon_number(words[axis], decimals)
            if val is None:
                _warn(warnings, f"坐标词 {axis}{words[axis]} 非法，跳过该轴")
                continue
            if axis == "X":
                x = val
            else:
                y = val
        return x, y

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()

        # 注释行（; 起头整行收编；X2 FILE_FORMAT 注释位数采纳）
        if upper.startswith(";"):
            fm = _FILE_FORMAT_RE.match(upper)
            if fm:
                decimals = int(fm.group(1))
                decimals_source = "comment"
                saw_fingerprint = True
            continue

        # 头部界
        if upper.startswith("M48"):
            in_header = True
            saw_fingerprint = True
            continue
        if upper == "%" or upper.startswith("M95"):
            in_header = False
            saw_fingerprint = True
            continue

        if in_header:
            fm = None
            if upper.startswith("FMAT"):
                fmat = upper.split(",", 1)[1].strip() if "," in upper else None
                saw_fingerprint = True
                continue
            if upper.startswith("INCH"):
                units = "INCH"
                conv = _UnitConv(units)
                if ",LZ" in upper:
                    zero_mode = "LZ"
                elif ",TZ" in upper:
                    zero_mode = "TZ"
                saw_fingerprint = True
                continue
            if upper.startswith("METRIC"):
                units = "METRIC"
                conv = _UnitConv(units)
                if ",LZ" in upper:
                    zero_mode = "LZ"
                elif ",TZ" in upper:
                    zero_mode = "TZ"
                saw_fingerprint = True
                continue
            tm = _TOOL_DEF_RE.match(upper)
            if tm:
                tool_no = tm.group(1).lstrip("0") or "0"
                try:
                    dia = float(tm.group(2))
                except ValueError:
                    _warn(warnings, f"第 {lineno} 行刀具直径非法，原样登记")
                    dia = None
                tools[tool_no] = {
                    "diameter_mm": (round(dia * float(conv._factor), 9)
                                    if dia is not None and conv._factor is not None
                                    else None),
                    "diameter_raw": tm.group(2),
                    "feed": tm.group(3),
                    "speed": tm.group(4),
                }
                saw_fingerprint = True
                continue
            if upper.startswith(("ICI", "VER,", "ATC,", "DETECT,", "THREAD,",
                                 "R,")):
                saw_fingerprint = True
                continue  # 机器控制头参，布局语义无关
            _warn(warnings, f"第 {lineno} 行头部未识别语句 {stripped[:40]!r}，跳过")
            continue

        # ── 体段 ─────────────────────────────────────────────────────
        gm = _G_CODE_RE.search(upper)
        g_code = gm.group(1) if gm else None

        # G85 槽孔：语句内按序 (X,Y) 对（单行两对=KiCad 惯例形态；
        # 缺轴模态续用——首对缺轴沿用当前点，次对缺轴沿用首对）
        if g_code == "85":
            saw_fingerprint = True
            coord_seq = _COORD_RE.findall(upper)
            pairs: list[list[str | None]] = [[None, None], [None, None]]
            pair_idx = 0
            for axis, raw in coord_seq:
                if pair_idx > 1:
                    break
                pairs[pair_idx][0 if axis == "X" else 1] = raw
                if axis == "Y":
                    pair_idx += 1
            fx = (split_excellon_number(pairs[0][0], decimals)
                  if pairs[0][0] is not None else cur_x)
            fy = (split_excellon_number(pairs[0][1], decimals)
                  if pairs[0][1] is not None else cur_y)
            tx = (split_excellon_number(pairs[1][0], decimals)
                  if pairs[1][0] is not None else fx)
            ty = (split_excellon_number(pairs[1][1], decimals)
                  if pairs[1][1] is not None else fy)
            if fx is None or fy is None or tx is None or ty is None:
                _warn(warnings, f"第 {lineno} 行 G85 槽孔坐标不完整（单位未知或缺失），如实丢弃")
                continue
            slots.append({
                "tool": current_tool,
                "from": [conv.to_mm(fx), conv.to_mm(fy)],
                "to": [conv.to_mm(tx), conv.to_mm(ty)],
            })
            cur_x, cur_y = tx, ty
            continue

        if g_code in ("00", "05"):
            saw_fingerprint = True  # drill mode 登记（模式面不产几何）
        elif g_code in ("41", "42"):
            route_mode = "G41" if g_code == "41" else "G42"
            saw_fingerprint = True

        mw = [int(mm.group(1)) for mm in _M_CODE_RE.finditer(upper)]
        if any(mm in (30, 0) for mm in mw):
            truncated = False
            break
        if any(mm in (97, 98) for mm in mw):
            _warn(warnings, "M97/M98 文字钻超出结构化契约面，登记不展开")
            continue
        if "R," in upper or re.match(r"^R\d+", upper):
            _warn(warnings, "R step-repeat 重复指令不展开（坐标原样如实）")
            continue

        tw = _T_WORD_RE.search(upper)
        if tw and not _COORD_RE.search(upper) and gm is None:
            tool_no = tw.group(1).lstrip("0") or "0"
            current_tool = None if tool_no == "0" else tool_no
            saw_fingerprint = True
            if current_tool is not None and current_tool not in tools:
                _warn(warnings, f"选刀 T{current_tool} 未在头部登记（直径未知）")
            continue

        words = dict(_COORD_RE.findall(upper))
        if not words:
            if upper and not gm and not tw and not mw:
                _warn(warnings, f"第 {lineno} 行体未识别语句 {stripped[:40]!r}，跳过")
            continue
        saw_fingerprint = True

        x, y = _xy_of(words)
        if words.get("X") and x is not None:
            cur_x = x
        if words.get("Y") and y is not None:
            cur_y = y

        hits.append({
            "tool": current_tool,
            "x_mm": conv.to_mm(cur_x),
            "y_mm": conv.to_mm(cur_y),
        })

    if not saw_fingerprint:
        raise ExcellonParseError(
            "不像 Excellon 钻孔文件（无 M48/刀具/坐标/G/M 任何指纹）")

    per_tool: dict[str, int] = {}
    for h in hits:
        t = str(h["tool"])
        per_tool[t] = per_tool.get(t, 0) + 1
    for s in slots:
        t = str(s["tool"])
        per_tool[t] = per_tool.get(t, 0) + 1

    stats = {
        "n_hits": len(hits),
        "n_slots": len(slots),
        "per_tool_counts": dict(sorted(per_tool.items())),
        "n_tools": len(tools),
        "n_warnings": len(warnings),
    }

    return {
        # 自描述键统一口径（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键。
        "schema": f"excellon/{PARSER_SCHEMA_VERSION}",
        "units": units,
        "zero_mode": zero_mode,
        "decimals": decimals,
        "decimals_source": decimals_source,
        "fmat": fmat,
        "tools": tools,
        "hits": hits,
        "slots": slots,
        "route_mode": route_mode,
        "stats": stats,
        "truncated": truncated,
        "warnings": warnings,
    }


# ── 统计面（消费函数）─────────────────────────────────────────────────────


def excellon_hit_grid_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """Excellon 文档 → 孔位网格摘要（bbox + 最近邻间距统计）。

    Returns:
        ``{"bbox_mm": [xmin, ymin, xmax, ymax] | None, "n_points",
        "nn_min_mm", "nn_median_mm", "nn_max_mm"}``——最近邻=逐点对其
        余点最近距离的全分布三元量（n<2 或含 None 坐标点剔除后 <2 如实
        None，不做虚假统计；O(n²) 纯确定性逐对扫描）。
    """
    pts: list[tuple[float, float]] = []
    for h in doc.get("hits") or []:
        if h.get("x_mm") is not None and h.get("y_mm") is not None:
            pts.append((h["x_mm"], h["y_mm"]))
    if not pts:
        return {"bbox_mm": None, "n_points": 0,
                "nn_min_mm": None, "nn_median_mm": None, "nn_max_mm": None}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bbox = [min(xs), min(ys), max(xs), max(ys)]
    if len(pts) < 2:
        return {"bbox_mm": bbox, "n_points": len(pts),
                "nn_min_mm": None, "nn_median_mm": None, "nn_max_mm": None}
    nns: list[float] = []
    for i, (xi, yi) in enumerate(pts):
        best = min(
            (xi - xj) ** 2 + (yi - yj) ** 2
            for j, (xj, yj) in enumerate(pts) if j != i)
        nns.append(best ** 0.5)
    nns.sort()
    n = len(nns)
    mid = n // 2
    median = nns[mid] if n % 2 else (nns[mid - 1] + nns[mid]) / 2
    return {
        "bbox_mm": bbox,
        "n_points": len(pts),
        "nn_min_mm": round(nns[0], 9),
        "nn_median_mm": round(median, 9),
        "nn_max_mm": round(nns[-1], 9),
    }
