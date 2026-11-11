"""DRC 规则文件结构化解析内核（aurora_q Q-X48，2026-11-07）。

DRC（Design Rule Check）规则文件的只读结构化解析——PCB 设计的标准
约束格式（线宽/间距/过孔/环域/屏蔽罩间距等）的统一入口：三种形态
（结构化规则 JSON / CSV / 自由文本行语法）统一解析到同一内部 schema，
RF 领域特化检查器（RF 走线阻抗精度/焊盘间距/地过孔隔离度/屏蔽罩间距）
作为 RF 规则类型的求值器追加。全部词法/语义/数值判定在 core 确定性
内核（铁律 7：结构化数字只出自数据源文本本身；LLM/agent 永不产生
物理数字）。服务包装见 :mod:`rfauto.service.drc_service`（规则 4 JSON
进出），CLI 薄壳见 cli/domains/drc.py。

内部规则 schema（单源，三形态统一落键）::

    {name, type, layer_scope: [层名...|"*"], value, unit, priority,
     enabled, group, direction, object_types, tolerance_pct,
     radius_mm, notes, line, source_format}

规则类型注册表（单源三表，schema 即语义）：

- :data:`RULE_TYPE_DIRECTIONS`：type → 方向语义（min/max/range/enum；
  常量复用 core/dfm_rule_schema 的 DIRECTION_* 单源——方向词汇表全仓
  一处定义，本内核不另造词）；未知 type 如实保留（direction=None）
  进 warnings 不中断——宁全量带警告，不半途而废；
- :data:`RULE_TYPE_DEFAULT_UNITS`：type → 缺省单位（规则未声明单位时）；
- :data:`RULE_TYPE_METRICS`：type → design 对象上的度量键（validate
  消费面；metric 缺测 = unknown 不算 fail，与 dfm_rule_schema 语义
  一致）；RF 几何检查器（pad 间距/GND 过孔围栏/屏蔽罩间距）不走度量
  键、直读对象坐标（x/y，coordinate_unit 归一）。

单位面：长度族 mm/um/µm/mil（毫欧换算系数单源 :data:`UNIT_TO_MM`）、
ohm（含 Ω 别名）、token、count——比较前先归一到族基（length→mm）；
族外/未知单位不猜（eval 侧 unknown + warning）。

三形态文法：

- JSON：``{"rules": [...], "groups": [...], "metadata": {...}}`` 或裸
  规则列表；规则字段 name/type 必填，value 数值或 [lo,hi]（range）或
  token 列表（enum）；layer_scope 列表或 "*"；
- CSV：表头必含 name/type/value 三列（unit/layer_scope/priority/
  enabled/group/direction 等可选列）；value 列 range 写 ``lo-hi``、
  enum 写逗号分隔 token；
- 自由文本：行语法——``#``/``;`` 注释、``[组名]`` 组头、规则行
  ``name | type | value[ unit] | layers | priority | enabled``（前 3
  字段必填，后 3 可选；第 7 字段起 key=value 扩展 tolerance_pct/
  radius_mm/notes）；range 值 ``lo-hi``、enum 值逗号分隔。

格式检测 :func:`detect_format`：后缀 .json/.csv 优先，否则内容 sniff
（``{``/``[`` 起头=JSON；首个非注释行含逗号且带 name/type 表头=CSV；
其余=文本）。

优先级语义：priority 数值越大优先级越高（缺省 0）。**同
(type, layer_scope) 重复规则压制**：高优先级生效，低优先级标
superseded 进 warnings 不判（平权时取文件序靠前者）；不同 layer_scope
的同类规则互不压制（各自 scope 各判）。

RF 特化检查器（RF_RULE_TYPES，--rf 启用）：

- ``rf_impedance``：value=目标阻抗（ohm）+ tolerance_pct 容差（缺声明
  = unknown 不判）；实际=对象 impedance 度量，|dev|>target·tol%/100
  即违规；
- ``rf_pad_clearance``：同层 pad 两两最小距离 < value 即违规（最近对
  落 objects）；焊盘间距按 scope 内全部 pad 计（RF 特化在规则集来源，
  不在对象筛选）；
- ``rf_ground_via_fence``：value=最少 GND 过孔数（count）+
  radius_mm 半径；每条 RF 走线参考点半径内 GND 过孔（net 匹配
  :data:`GND_NET_RE`）计数 < value 即违规；
- ``rf_shield_clearance``：RF 对象参考点到屏蔽罩矩形（type=shield，
  x/y/w/h）边界的最小距离 < value 即违规。

缺坐标/缺对象/缺半径一律 unknown + warning（unknown 不算 fail，
不伪造违规，#314 同族纪律）。内置缺省 RF 规则集
:data:`DEFAULT_RF_RULESET`（通用保守档，--rules 覆盖）——数值=确定性
内核静态常量（同 TEMPLATE_NOMINAL 注册表口径），非 LLM 产出。

与 dfm_rule_schema 的桥：:func:`to_dfm_rule` 把单条 DRC 规则映射为
core/dfm_rule_schema 规则 dict（ipc_ref=UNVERIFIED_doc_anchor 诚实
口径；count 量纲不在其 QUANTITIES 内如实跳过带原因）——消费方可继续
走 validate_rule/evaluate_ruleset 既有单源。

错误：词法/结构违规（缺 name/type、数值坏、range 倒置等）抛
:class:`DrcParseError`（ValueError 子类，带行号定位）——服务层转
error 信封，CLI 层 exit 1。零 IO（纯文本/对象进出）、零依赖、确定性
（同输入同输出）。本模块不设 ``__all__``（无 __all__ 文件不进
tests/gold/public_api.json——hfss_run_report_service 同款先例，新
模块零金快照漂移）。
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from rfauto.core.dfm_rule_schema import (
    DIRECTION_ENUM,
    DIRECTION_MAX,
    DIRECTION_MIN,
    DIRECTION_RANGE,
    QUANTITIES,
    QUANTITY_IMPEDANCE_OHM,
    QUANTITY_LENGTH_MM,
    QUANTITY_TOKEN,
)

#: 方向词汇表（dfm_rule_schema 单源镜像面——本模块只消费四数值方向）
_DIRECTIONS = (DIRECTION_MIN, DIRECTION_MAX, DIRECTION_RANGE, DIRECTION_ENUM)


class DrcParseError(ValueError):
    """DRC 规则/design 文件词法或结构违规（ValueError 子类，带行号文本）。"""


_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_INT_RE = re.compile(r"[+-]?\d+")
#: range 值文法：``lo-hi`` / ``lo~hi`` / ``lo..hi``（CSV/文本行值列）
_RANGE_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*(?:-|~|\.\.)\s*"
    r"([+-]?(?:\d+\.?\d*|\.\d+))\s*$")
#: 数值+单位连写：``0.15mm`` / ``50ohm``（文本值列单 token 形态）
_NUM_UNIT_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"([A-Za-zµΩ]+)\s*$")
#: GND 网名（地过孔判定）：GND/AGND/PGND/DGND 及其 ``_`` 后缀变体
GND_NET_RE = re.compile(r"^(?:GND|AGND|PGND|DGND)(?:_.*)?$")


# ─── 单位面（族基归一单源）─────────────────────────────────────────────────

#: 长度族 → mm 换算系数（比较前统一归一到 mm；µ 写法两形态都收）
UNIT_TO_MM: dict[str, float] = {
    "mm": 1.0,
    "um": 0.001,
    "mil": 0.0254,
}
_UNIT_ALIASES: dict[str, str] = {
    "mm": "mm",
    "millimeter": "mm",
    "um": "um",
    "µm": "um",
    "micron": "um",
    "microns": "um",
    "mil": "mil",
    "mils": "mil",
    "thou": "mil",
    "ohm": "ohm",
    "ohms": "ohm",
    "ω": "ohm",
    "token": "token",
    "-": "token",
    "count": "count",
}


def normalize_unit(unit: Any) -> str | None:
    """单位别名归一（mm/um/mil/ohm/token/count）；未知/非 str 如实 None。"""
    if not isinstance(unit, str):
        return None
    text = unit.strip().lower()
    return _UNIT_ALIASES.get(text)


def unit_family(unit: str | None) -> str | None:
    """单位 → 族（length/ohm/token/count）；未知单位如实 None（不猜）。"""
    if unit == "mm" or unit == "um" or unit == "mil":
        return "length"
    if unit == "ohm":
        return "ohm"
    if unit == "token":
        return "token"
    if unit == "count":
        return "count"
    return None


def length_to_mm(value: float, unit: str) -> float | None:
    """长度值 → mm（族内归一单源）；族外单位如实 None。"""
    factor = UNIT_TO_MM.get(unit)
    return None if factor is None else value * factor


def as_number(text: Any) -> int | float | None:
    """数值字面量转换（整型字面量→int、其余→float；失败如实 None）。"""
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return text
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not _NUM_RE.fullmatch(stripped):
        return None
    if _INT_RE.fullmatch(stripped):
        return int(stripped)
    return float(stripped)


def _finite(value: Any) -> float | None:
    """有限数判定（bool 拒收、NaN/inf 拒收——df7+⑯ 同款纪律）。"""
    num = as_number(value)
    if num is None:
        return None
    out = float(num)
    return out if math.isfinite(out) else None


def _parse_bool(text: Any) -> bool | None:
    """启用态词面解析（on/off/true/false/yes/no/enabled/disabled/1/0）。"""
    if isinstance(text, bool):
        return text
    token = str(text).strip().lower() if isinstance(text, str) else None
    if token in ("on", "true", "yes", "enabled", "1"):
        return True
    if token in ("off", "false", "no", "disabled", "0"):
        return False
    return None


# ─── 规则类型注册表（三表单源：方向/缺省单位/度量键）───────────────────────

#: type → 方向语义（DIRECTION_* 复用 dfm_rule_schema 词汇单源）
RULE_TYPE_DIRECTIONS: dict[str, str] = {
    "min_width": DIRECTION_MIN,
    "max_width": DIRECTION_MAX,
    "min_clearance": DIRECTION_MIN,
    "min_isolation": DIRECTION_MIN,
    "min_annular_ring": DIRECTION_MIN,
    "min_drill": DIRECTION_MIN,
    "impedance": DIRECTION_RANGE,
    "via_style": DIRECTION_ENUM,
    "rf_impedance": DIRECTION_MAX,
    "rf_pad_clearance": DIRECTION_MIN,
    "rf_ground_via_fence": DIRECTION_MIN,
    "rf_shield_clearance": DIRECTION_MIN,
}

#: type → 缺省单位（规则未声明 unit 时落位）
RULE_TYPE_DEFAULT_UNITS: dict[str, str] = {
    "min_width": "mm",
    "max_width": "mm",
    "min_clearance": "mm",
    "min_isolation": "mm",
    "min_annular_ring": "mm",
    "min_drill": "mm",
    "impedance": "ohm",
    "via_style": "token",
    "rf_impedance": "ohm",
    "rf_pad_clearance": "mm",
    "rf_ground_via_fence": "count",
    "rf_shield_clearance": "mm",
}

#: type → design 对象度量键（通用方向求值面；RF 几何三检查器直读坐标不走此表）
RULE_TYPE_METRICS: dict[str, str] = {
    "min_width": "width",
    "max_width": "width",
    "min_clearance": "clearance",
    "min_isolation": "isolation",
    "min_annular_ring": "annular_ring",
    "min_drill": "drill",
    "impedance": "impedance",
    "via_style": "via_style",
    "rf_impedance": "impedance",
}

#: 度量键 → 缺省单位（design 对象 metric 数值形态无单位声明时）
METRIC_DEFAULT_UNITS: dict[str, str] = {
    "width": "mm",
    "clearance": "mm",
    "isolation": "mm",
    "annular_ring": "mm",
    "drill": "mm",
    "impedance": "ohm",
    "via_style": "token",
}

#: type → 适用对象类型（validate 匹配面；"*"=不限对象类型）
RULE_TYPE_OBJECT_TYPES: dict[str, tuple[str, ...]] = {
    "min_width": ("trace",),
    "max_width": ("trace",),
    "min_clearance": ("*",),
    "min_isolation": ("*",),
    "min_annular_ring": ("via",),
    "min_drill": ("via",),
    "impedance": ("trace",),
    "via_style": ("via",),
    "rf_impedance": ("trace",),
    "rf_pad_clearance": ("pad",),
    "rf_ground_via_fence": ("trace",),
    "rf_shield_clearance": ("*",),
}

#: RF 特化检查器规则类型（--rf 启用面；四检查器=任务书四项）
RF_RULE_TYPES = (
    "rf_impedance",
    "rf_pad_clearance",
    "rf_ground_via_fence",
    "rf_shield_clearance",
)

#: 内置缺省 RF 规则集（通用保守档，--rules 覆盖；数值=内核静态常量
#: 非 LLM 产出；tolerance_pct/radius_mm 为检查器必需扩展键）
DEFAULT_RF_RULESET: tuple[dict[str, Any], ...] = (
    {
        "name": "rf_impedance_50ohm_default",
        "type": "rf_impedance",
        "value": 50.0,
        "unit": "ohm",
        "tolerance_pct": 5.0,
        "layer_scope": ["*"],
        "priority": 0,
        "enabled": True,
        "notes": "内置缺省档：RF 走线阻抗 50 ohm ±5%（--rules 覆盖）",
    },
    {
        "name": "rf_pad_clearance_default",
        "type": "rf_pad_clearance",
        "value": 0.2,
        "unit": "mm",
        "layer_scope": ["*"],
        "priority": 0,
        "enabled": True,
        "notes": "内置缺省档：同层焊盘间距 >=0.2 mm（--rules 覆盖）",
    },
    {
        "name": "rf_gnd_via_fence_default",
        "type": "rf_ground_via_fence",
        "value": 2,
        "unit": "count",
        "radius_mm": 1.0,
        "layer_scope": ["*"],
        "priority": 0,
        "enabled": True,
        "notes": "内置缺省档：RF 走线 1.0 mm 半径内 >=2 个 GND 过孔"
                 "（--rules 覆盖）",
    },
    {
        "name": "rf_shield_clearance_default",
        "type": "rf_shield_clearance",
        "value": 0.5,
        "unit": "mm",
        "layer_scope": ["*"],
        "priority": 0,
        "enabled": True,
        "notes": "内置缺省档：RF 对象到屏蔽罩 >=0.5 mm（--rules 覆盖）",
    },
)


# ─── 规则归一（三形态统一落键）─────────────────────────────────────────────


def _layer_scope_of(raw: Any, where: str) -> list[str]:
    """layer_scope 归一：``*``/str（``,``/``;`` 分隔）/列表 → str 列表。"""
    if raw is None:
        return ["*"]
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text == "*":
            return ["*"]
        return [p.strip() for p in re.split(r"[;,]", text) if p.strip()] or ["*"]
    if isinstance(raw, (list, tuple)):
        out = [str(p).strip() for p in raw if str(p).strip()]
        return out or ["*"]
    raise DrcParseError(f"{where}.layer_scope 非法：{raw!r}（列表/str/'*'）")


def _value_of(
    raw_value: Any, direction: str | None, unit: str, where: str
) -> Any:
    """value 归一：min/max=有限数、range=[lo,hi]、enum=token 列表。

    ``direction=None``（未知 type）时按数值/范围/列表三态尽力收（保持
    原值能力——面外类型不判但保真），收不动如实收原文。
    """
    if direction == DIRECTION_ENUM:
        if isinstance(raw_value, str):
            tokens = [t.strip() for t in re.split(r"[,\s]+", raw_value)
                      if t.strip()]
            if not tokens:
                raise DrcParseError(f"{where}.value 枚举白名单为空")
            return tokens
        if isinstance(raw_value, (list, tuple)) and raw_value and \
                all(isinstance(t, str) and t.strip() for t in raw_value):
            return [str(t).strip() for t in raw_value]
        raise DrcParseError(f"{where}.value 必须为 token 列表，得到 {raw_value!r}")
    if direction == DIRECTION_RANGE:
        if isinstance(raw_value, (list, tuple)):
            if len(raw_value) != 2:
                raise DrcParseError(
                    f"{where}.value range 必须为 [lo, hi]，得到 {raw_value!r}")
            lo = _finite(raw_value[0])
            hi = _finite(raw_value[1])
        elif isinstance(raw_value, str):
            m = _RANGE_RE.fullmatch(raw_value)
            if not m:
                raise DrcParseError(
                    f"{where}.value range 文法为 lo-hi/lo~hi，得到 {raw_value!r}")
            lo, hi = _finite(m.group(1)), _finite(m.group(2))
        else:
            lo = hi = None
        if lo is None or hi is None:
            raise DrcParseError(
                f"{where}.value range 端点必须为有限数，得到 {raw_value!r}")
        if lo > hi:
            raise DrcParseError(f"{where}.value range 须 lo<=hi，得到 {(lo, hi)}")
        return [lo, hi]
    # min/max（及未知 type 的数值收口）
    num = _finite(raw_value)
    if num is not None:
        return num
    if isinstance(raw_value, str):
        m = _RANGE_RE.fullmatch(raw_value)
        if m:
            lo, hi = _finite(m.group(1)), _finite(m.group(2))
            if lo is not None and hi is not None and lo <= hi:
                return [lo, hi]
    if direction in (DIRECTION_MIN, DIRECTION_MAX):
        raise DrcParseError(
            f"{where}.value 必须为有限数，得到 {raw_value!r}")
    return raw_value


def normalize_rule(
    raw: Any, *, source_format: str, line: int, warnings: list[dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    """单条规则 → 内部 schema 归一副本（非法抛 :class:`DrcParseError`）。"""
    if not isinstance(raw, dict):
        raise DrcParseError(
            f"第 {line} 条规则[{index}] 必须为 dict/mapping，得到 {raw!r}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DrcParseError(
            f"第 {line} 条规则[{index}] 缺 name（必须为非空 str）")
    rtype = raw.get("type")
    if not isinstance(rtype, str) or not rtype.strip():
        raise DrcParseError(
            f"规则 {name!r}（第 {line} 行）缺 type（必须为非空 str）")
    name, rtype = name.strip(), rtype.strip()
    where = f"规则 {name!r}"
    direction = raw.get("direction")
    if direction is not None and direction not in _DIRECTIONS:
        raise DrcParseError(
            f"{where}.direction 非法：{direction!r}（允许 {_DIRECTIONS}）")
    if direction is None:
        direction = RULE_TYPE_DIRECTIONS.get(rtype)
    if direction is None:
        warnings.append({
            "line": line,
            "rule": name,
            "note": f"未知规则类型 {rtype!r}（面外类型保留不判）",
        })
    unit = normalize_unit(raw.get("unit"))
    if raw.get("unit") is not None and unit is None:
        warnings.append({
            "line": line,
            "rule": name,
            "note": f"未知单位 {raw.get('unit')!r}（保留原词，求值面不判）",
        })
    if unit is None:
        if raw.get("unit") is None:
            unit = RULE_TYPE_DEFAULT_UNITS.get(rtype, "mm")
        else:
            # 显式未知单位保留原词（family 查不到 → 求值面 unknown 不判，
            # 与上方 warning 口径一致——静默换成缺省单位会假判）
            unit = str(raw.get("unit")).strip().lower()
    value = _value_of(raw.get("value"), direction, unit, where)
    tolerance = _finite(raw.get("tolerance_pct"))
    radius = _finite(raw.get("radius_mm"))
    priority_raw = raw.get("priority")
    priority = as_number(priority_raw)
    if priority_raw is not None and priority is None:
        warnings.append({
            "line": line,
            "rule": name,
            "note": f"priority 非数值 {priority_raw!r}（按缺省 0 收）",
        })
    priority = int(priority) if priority is not None else 0
    enabled = True
    if raw.get("enabled") is not None:
        parsed = _parse_bool(raw.get("enabled"))
        if parsed is None:
            warnings.append({
                "line": line,
                "rule": name,
                "note": f"enabled 词面非法 {raw.get('enabled')!r}（按启用收）",
            })
        else:
            enabled = parsed
    object_types = raw.get("object_types")
    if object_types is None:
        object_types = RULE_TYPE_OBJECT_TYPES.get(rtype, ("*",))
    elif isinstance(object_types, str):
        object_types = (object_types.strip(),)
    elif isinstance(object_types, (list, tuple)):
        object_types = tuple(str(t).strip() for t in object_types
                             if str(t).strip())
    else:
        raise DrcParseError(
            f"{where}.object_types 非法：{object_types!r}（列表/str）")
    if not object_types:
        object_types = ("*",)
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        notes = str(notes)
    group = raw.get("group")
    if group is not None and not isinstance(group, str):
        group = str(group)
    return {
        "name": name,
        "type": rtype,
        "layer_scope": _layer_scope_of(raw.get("layer_scope"), where),
        "value": value,
        "unit": unit,
        "priority": priority,
        "enabled": enabled,
        "group": group,
        "direction": direction,
        "object_types": tuple(object_types),
        "tolerance_pct": tolerance,
        "radius_mm": radius,
        "notes": notes,
        "line": line,
        "source_format": source_format,
    }


# ─── 三形态文法解析（JSON / CSV / 自由文本行）──────────────────────────────


def _declared_groups(raw: Any) -> list[str]:
    """groups 声明归一：str 列表 / {name} dict 列表 → 名表（序保持）。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("name"), str) \
                    and item["name"].strip():
                out.append(item["name"].strip())
        return out
    return []


def parse_rules_json(text: str) -> tuple[list[Any], list[str], dict[str, Any]]:
    """JSON 文本 → (原始规则表, 组声明, 元数据声明)。"""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise DrcParseError(f"JSON 解析失败: {exc}") from exc
    if isinstance(data, list):
        return data, [], {}
    if isinstance(data, dict):
        rules = data.get("rules")
        if not isinstance(rules, list):
            raise DrcParseError("JSON 规则文件缺 rules 列表（或裸列表形态）")
        meta = data.get("metadata")
        return rules, _declared_groups(data.get("groups")), (
            dict(meta) if isinstance(meta, dict) else {})
    raise DrcParseError(
        f"JSON 规则文件必须是对象或列表，得到 {type(data).__name__}")


_CSV_REQUIRED_COLUMNS = ("name", "type", "value")


def parse_rules_csv(text: str) -> tuple[list[Any], list[str], dict[str, Any]]:
    """CSV 文本 → (行 dict 规则表, [], {})；表头必含 name/type/value。"""
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or []) if h]
    missing = [c for c in _CSV_REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise DrcParseError(
            f"CSV 表头缺必填列 {missing}（必含 {_CSV_REQUIRED_COLUMNS}）")
    rows: list[Any] = []
    for row in reader:
        line = reader.line_num
        clean = {
            (k.strip() if isinstance(k, str) else k):
                (v.strip() if isinstance(v, str) else v)
            for k, v in row.items() if k is not None
        }
        if not any(v for v in clean.values()):
            continue  # 全空行（尾换行）跳过
        clean["__line__"] = line
        rows.append(clean)
    return rows, [], {}


def _split_value_field(
    field: str, direction: str | None, default_unit: str, where: str
) -> tuple[Any, str]:
    """文本/CSV value 列 → (value, unit)：``0.15 mm``/``0.15mm``/
    ``49-51 ohm``/``via,blind`` 四形态（unit 缺省按类型注册表）。"""
    text = field.strip()
    if direction == DIRECTION_ENUM:
        tokens = [t for t in re.split(r"[,\s]+", text) if t]
        if not tokens:
            raise DrcParseError(f"{where}.value 枚举白名单为空")
        return tokens, "token"
    unit = default_unit
    num_text = text
    m = _NUM_UNIT_RE.fullmatch(text)
    if m:
        num_text, unit_text = m.group(1), m.group(2)
        canon = normalize_unit(unit_text)
        if canon is None:
            raise DrcParseError(f"{where}.value 未知单位 {unit_text!r}")
        unit = canon
    else:
        tokens = text.split()
        if len(tokens) >= 2:
            canon = normalize_unit(tokens[-1])
            if canon is not None:
                unit = canon
                num_text = " ".join(tokens[:-1])
    if direction == DIRECTION_RANGE:
        m2 = _RANGE_RE.fullmatch(num_text)
        if not m2:
            raise DrcParseError(
                f"{where}.value range 文法为 lo-hi/lo~hi，得到 {num_text!r}")
        lo, hi = _finite(m2.group(1)), _finite(m2.group(2))
        if lo is None or hi is None:
            raise DrcParseError(
                f"{where}.value range 端点必须为有限数，得到 {num_text!r}")
        if lo > hi:
            raise DrcParseError(f"{where}.value range 须 lo<=hi，得到 {(lo, hi)}")
        return [lo, hi], unit
    num = _finite(num_text)
    if num is None:
        raise DrcParseError(f"{where}.value 必须为有限数，得到 {num_text!r}")
    return num, unit


_TEXT_EXTRA_KEYS = ("tolerance_pct", "radius_mm", "notes")


def parse_rules_text(
    text: str,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """自由文本行语法 → (原始规则 dict 表, 组声明, {})。

    文法（模块 docstring 节录）：``#``/``;`` 注释、``[组名]`` 组头、
    规则行 ``name | type | value[ unit] | layers | priority | enabled``
    ——前 3 字段必填；第 7 字段起 key=value 扩展（tolerance_pct/
    radius_mm/notes 白名单，面外键报错防静默吞）。
    """
    rules: list[dict[str, Any]] = []
    groups: list[str] = []
    current_group: str | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            gname = stripped[1:-1].strip()
            if gname:
                groups.append(gname)
                current_group = gname
            continue
        fields = [f.strip() for f in stripped.split("|")]
        while fields and fields[-1] == "":
            fields.pop()
        if len(fields) < 3:
            raise DrcParseError(
                f"第 {lineno} 行：规则行至少需要 name|type|value 三字段，"
                f"得到 {len(fields)} 字段")
        raw: dict[str, Any] = {"name": fields[0], "type": fields[1]}
        if current_group is not None:
            raw["group"] = current_group  # 组头归组（后续规则隶属）
        if len(fields) >= 4 and fields[3]:
            raw["layer_scope"] = fields[3]
        if len(fields) >= 5 and fields[4]:
            raw["priority"] = fields[4]
        if len(fields) >= 6 and fields[5]:
            raw["enabled"] = fields[5]
        for extra in fields[6:]:
            key, sep, val = extra.partition("=")
            key = key.strip()
            if not sep or key not in _TEXT_EXTRA_KEYS:
                raise DrcParseError(
                    f"第 {lineno} 行：扩展字段须为 {'/'.join(_TEXT_EXTRA_KEYS)}"
                    f" 形态 key=value，得到 {extra!r}")
            raw[key] = val.strip()
        raw["__value_field__"] = fields[2]
        raw["__line__"] = lineno
        rules.append(raw)
    return rules, groups, {}


def _finalize_raw_rules(
    rules_raw: list[Any], source_format: str, warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """原始规则表 → 归一规则表（文本/CSV 行的 value 列先拆值+单位）。

    ``__value_field__``（文本行形态）先经 :func:`_split_value_field` 落
    value/unit 两键再归一；``__line__`` 为行号，缺省按序号。
    """
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(rules_raw, 1):
        if not isinstance(raw, dict):
            raise DrcParseError(
                f"第 {i} 条规则必须为 mapping，得到 {raw!r}")
        line = int(raw.get("__line__") or i)
        item = {k: v for k, v in raw.items() if not k.startswith("__")}
        rtype = str(item.get("type") or "").strip()
        direction = item.get("direction")
        if direction is None:
            direction = RULE_TYPE_DIRECTIONS.get(rtype)
        if "__value_field__" in raw:
            default_unit = RULE_TYPE_DEFAULT_UNITS.get(rtype, "mm")
            explicit = normalize_unit(item.get("unit"))
            value, unit = _split_value_field(
                str(raw["__value_field__"]), direction,
                explicit or default_unit, f"第 {line} 行规则")
            item["value"] = value
            item.setdefault("unit", unit)
        out.append(normalize_rule(
            item, source_format=source_format, line=line,
            warnings=warnings, index=i))
    return out


def detect_format(text: str, path: str | Path = "") -> str:
    """格式检测：后缀 .json/.csv 优先，内容 sniff 兜底（json/csv/text）。

    sniff 规则（确定性）：剥空白后 ``{``/``[`` 起头=JSON；首个非注释
    行含逗号且切分表头含 name 与 type=CSV；其余=文本行语法。
    """
    suffix = Path(str(path)).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    for line in stripped.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        if "," in s:
            header = [h.strip().lower() for h in s.split(",")]
            if "name" in header and "type" in header:
                return "csv"
        break
    return "text"


#: 合法格式名（parse_drc_rules 的 fmt 面外值报错）
FORMATS = ("auto", "json", "csv", "text")

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"


def parse_drc_rules(text: str, *, fmt: str = "auto") -> dict[str, Any]:
    """DRC 规则文本 → 统一结构化文档（schema 见模块 docstring；零 IO）。

    返回 ``{"schema", "format", "rules", "groups", "metadata",
    "warnings"}``（``"schema"="drc/<N.0>"`` 自描述复合键——R-22 schema
    升位批补键，既有 ``"format"`` 键=源格式面语义不动）：
    rules 为归一规则表（文件序）；groups 为组声明序+隐式组（规则
    group 字段首现序）；metadata=声明元数据+计算计数键（同键计算值
    覆盖声明值，确定性口径）；warnings=未知类型/未知单位/坏 priority/
    坏 enabled 等非致命项（line+rule+note）。``fmt`` 面外值报错。
    """
    if fmt not in FORMATS:
        raise DrcParseError(f"fmt 必须为 {FORMATS}，得到 {fmt!r}")
    warnings: list[dict[str, Any]] = []
    resolved = detect_format(text) if fmt == "auto" else fmt
    if resolved == "json":
        rules_raw, declared, declared_meta = parse_rules_json(text)
    elif resolved == "csv":
        rules_raw, declared, declared_meta = parse_rules_csv(text)
    else:
        rules_raw, declared, declared_meta = parse_rules_text(text)
    rules = _finalize_raw_rules(rules_raw, resolved, warnings)
    groups = _build_groups(rules, declared)
    metadata: dict[str, Any] = dict(declared_meta)
    metadata.update({
        "source_format": resolved,
        "n_rules": len(rules),
        "n_enabled": sum(1 for r in rules if r["enabled"]),
        "n_disabled": sum(1 for r in rules if not r["enabled"]),
        "n_rf_rules": sum(1 for r in rules if r["type"] in RF_RULE_TYPES),
        "n_groups": len(groups),
        "n_warnings": len(warnings),
    })
    return {
        "schema": f"drc/{PARSER_SCHEMA_VERSION}",
        "format": resolved,
        "rules": rules,
        "groups": groups,
        "metadata": metadata,
        "warnings": warnings,
    }


def _build_groups(
    rules: list[dict[str, Any]], declared: list[str],
) -> list[dict[str, Any]]:
    """组表：声明序在前（空组如实保留），规则 group 字段隐式组随后
    （首现序）；每组 {name, rule_names, n_rules, n_enabled}。"""
    order: list[str] = list(declared)
    for rule in rules:
        gname = rule.get("group")
        if gname and gname not in order:
            order.append(gname)
    out: list[dict[str, Any]] = []
    for gname in order:
        members = [r for r in rules if r.get("group") == gname]
        out.append({
            "name": gname,
            "rule_names": [r["name"] for r in members],
            "n_rules": len(members),
            "n_enabled": sum(1 for r in members if r["enabled"]),
        })
    return out


# ─── design 对象归一与度量读取（validate 消费面）───────────────────────────


def extract_design_objects(design: Any) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """design dict → (对象表, coordinate_unit, warnings)。

    design 必为 dict 且含 ``objects`` 列表（否则 :class:`DrcParseError`）；
    每对象须 dict 且 name 非空（否则报错——design 文件结构性损坏宁可
    早炸不静默）；coordinate_unit 归一长度族（缺省 mm，族外报错——
    坐标系不猜）。
    """
    warnings: list[dict[str, Any]] = []
    if not isinstance(design, dict):
        raise DrcParseError(
            f"design 必须为 JSON 对象，得到 {type(design).__name__}")
    objects_raw = design.get("objects")
    if not isinstance(objects_raw, list):
        raise DrcParseError("design JSON 缺 objects 列表")
    unit_raw = design.get("coordinate_unit", "mm")
    coord_unit = normalize_unit(unit_raw)
    if coord_unit not in ("mm", "um", "mil"):
        raise DrcParseError(
            f"design.coordinate_unit 必须为长度族（mm/um/mil），"
            f"得到 {unit_raw!r}")
    objects: list[dict[str, Any]] = []
    for i, obj in enumerate(objects_raw, 1):
        if not isinstance(obj, dict):
            raise DrcParseError(f"objects[{i}] 必须为 dict，得到 {obj!r}")
        name = obj.get("name")
        if not isinstance(name, str) or not name.strip():
            raise DrcParseError(f"objects[{i}] 缺 name（必须为非空 str）")
        objects.append({
            "name": name.strip(),
            "type": str(obj.get("type") or "").strip(),
            "layer": str(obj.get("layer") or "*").strip() or "*",
            "rf": obj.get("rf") is True,
            "net": str(obj.get("net") or "").strip(),
            "metrics": (obj.get("metrics")
                        if isinstance(obj.get("metrics"), dict) else {}),
            "flat": {k: v for k, v in obj.items()
                     if k not in ("name", "type", "layer", "rf", "net",
                                  "metrics")},
            "x": _finite(obj.get("x")),
            "y": _finite(obj.get("y")),
            "w": _finite(obj.get("w")),
            "h": _finite(obj.get("h")),
        })
    return objects, coord_unit, warnings


def _metric_value(
    obj: dict[str, Any], key: str,
) -> tuple[Any, str] | None:
    """对象度量读取：metrics[key] 优先、顶层同名键兜底。

    值形态：数值（单位按 :data:`METRIC_DEFAULT_UNITS`）或
    ``{"value", "unit"}``；缺测/非数值如实 None。
    """
    raw = obj["metrics"].get(key)
    if raw is None:
        raw = obj["flat"].get(key)
    if raw is None:
        return None
    if isinstance(raw, dict):
        value = raw.get("value")
        unit = normalize_unit(raw.get("unit")) or METRIC_DEFAULT_UNITS.get(
            key, "mm")
    else:
        value = raw
        unit = METRIC_DEFAULT_UNITS.get(key, "mm")
    if isinstance(value, str):
        text = value.strip()
        return (text, "token") if text else None
    num = _finite(value)
    if num is None:
        return None
    return (num, unit)


def _canonical_compare(
    rule_value: Any, rule_unit: str, metric: tuple[Any, str],
) -> tuple[str, Any, Any]:
    """规则值 × 度量 → (status, canonical_actual, canonical_expected_value)。

    status ∈ {"ok", "violation", "unknown"}；族不匹配/未知单位 =
    unknown（不猜）；长度族双方归一 mm 比较，ohm/count 直比，token
    集合包含比较。
    """
    fam_rule = unit_family(rule_unit)
    actual, unit_m = metric
    fam_metric = unit_family(unit_m)
    if fam_rule is None or fam_metric is None or fam_rule != fam_metric:
        return ("unknown", actual, rule_value)
    if fam_rule == "length":
        return ("len", length_to_mm(float(actual), unit_m),
                length_to_mm(float(rule_value), rule_unit))
    return ("same", actual, rule_value)


# ─── 通用方向求值 + RF 四检查器 ────────────────────────────────────────────


def _scope_match(rule: dict[str, Any], obj: dict[str, Any]) -> bool:
    """层 scope × 对象类型 双匹配（"*" 全配）。"""
    scope = rule["layer_scope"]
    if "*" not in scope and obj["layer"] not in scope:
        return False
    otypes = rule["object_types"]
    return "*" in otypes or obj["type"] in otypes


def _expected_text(rule: dict[str, Any]) -> str:
    """规则 → 人读期望串（violation.expected）。"""
    unit = rule["unit"]
    value = rule["value"]
    if rule["direction"] == DIRECTION_MIN:
        return f">= {_fmt_num(value)} {unit}"
    if rule["direction"] == DIRECTION_MAX:
        return f"<= {_fmt_num(value)} {unit}"
    if rule["direction"] == DIRECTION_RANGE:
        return f"in [{_fmt_num(value[0])}, {_fmt_num(value[1])}] {unit}"
    if rule["direction"] == DIRECTION_ENUM:
        return "in {" + ", ".join(value) + "}"
    return f"{_fmt_num(value)} {unit}"


def _fmt_num(value: Any) -> str:
    """数值极简格式（整数不带小数点；浮点去尾零）。"""
    if isinstance(value, int):
        return str(value)
    out = f"{float(value):g}"
    return out


def _violating(
    rule: dict[str, Any], measured: list[tuple[dict[str, Any], Any]],
) -> tuple[list[tuple[dict[str, Any]], Any], int, int]:
    """通用方向判定：返回 (违规(对象,规范值)表, unknown 数, ok 数)。

    违规规范值用于 worst 实际值选取（min 取最小/max 取最大/range 取
    距带最远/enum 首个违规 token）。
    """
    direction = rule["direction"]
    unknown = 0
    ok = 0
    bad: list[tuple[dict[str, Any], Any]] = []
    for obj, canonical in measured:
        status, actual, expected = canonical
        if status == "unknown":
            unknown += 1
            continue
        if direction == DIRECTION_MIN:
            violated = float(actual) < float(expected)
        elif direction == DIRECTION_MAX:
            violated = float(actual) > float(expected)
        elif direction == DIRECTION_RANGE:
            lo, hi = expected
            violated = float(actual) < lo or float(actual) > hi
        else:  # enum：actual=token（str）、expected=白名单列表
            violated = str(actual) not in expected
        if violated:
            bad.append((obj, actual))
        else:
            ok += 1
    return bad, unknown, ok


def _worst_actual(
    rule: dict[str, Any], bad: list[tuple[dict[str, Any], Any]],
) -> Any:
    """违规表 → worst 实际值（min 最小/max 最大/range 距带最远/enum 首个）。"""
    direction = rule["direction"]
    values = [v for _, v in bad]
    if direction == DIRECTION_MIN:
        return min(float(v) for v in values)
    if direction == DIRECTION_MAX:
        return max(float(v) for v in values)
    if direction == DIRECTION_RANGE:

        def dist(v: Any) -> float:
            lo, hi = rule["value"]
            x = float(v)
            return lo - x if x < lo else max(x - hi, 0.0)

        return max(values, key=dist)
    return values[0]


def _check_rf_impedance(
    rule: dict[str, Any], objects: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """RF 走线阻抗精度：|Z-目标| > 目标·tol% 即违规。

    返回 (violation|None, warning|None, measured_any)；tolerance_pct
    缺声明 / scope 内无带阻抗测量的 RF 走线 → unknown（warning）。
    """
    tol = rule["tolerance_pct"]
    if tol is None or tol <= 0:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": "rf_impedance 缺 tolerance_pct（不判，unknown）",
        }, False
    target = float(rule["value"])
    band = target * float(tol) / 100.0
    bad: list[tuple[dict[str, Any], Any]] = []
    measured = 0
    for obj in objects:
        if obj["type"] != "trace" or not obj["rf"]:
            continue
        if "*" not in rule["layer_scope"] and \
                obj["layer"] not in rule["layer_scope"]:
            continue
        metric = _metric_value(obj, "impedance")
        if metric is None:
            continue
        value, unit = metric
        if unit_family(unit) != "ohm" or not math.isfinite(float(value)):
            continue
        measured += 1
        if abs(float(value) - target) > band:
            bad.append((obj, float(value)))
    if measured == 0:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": "scope 内无带阻抗测量的 RF 走线（不判，unknown）",
        }, False
    if not bad:
        return None, None, True
    worst = max(bad, key=lambda p: abs(float(p[1]) - target))
    violation = {
        "rule": rule["name"],
        "objects": [o["name"] for o, _ in bad],
        "actual": worst[1],
        "expected": f"{_fmt_num(target)} ohm ±{_fmt_num(rule['tolerance_pct'])}%",
        "unit": "ohm",
    }
    return violation, None, True


def _point_rect_distance(
    px: float, py: float, cx: float, cy: float, w: float, h: float,
) -> float:
    """点到矩形（中心 cx/cy 宽 w 高 h）边界距离（内部=0）。"""
    dx = max(abs(px - cx) - w / 2.0, 0.0)
    dy = max(abs(py - cy) - h / 2.0, 0.0)
    return math.hypot(dx, dy)


def _check_rf_pad_clearance(
    rule: dict[str, Any], objects: list[dict[str, Any]],
    coord_unit: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """同层焊盘两两最小距离（最近对落 objects；< value 违规）。"""
    pads = []
    for obj in objects:
        if obj["type"] != "pad":
            continue
        if "*" not in rule["layer_scope"] and \
                obj["layer"] not in rule["layer_scope"]:
            continue
        if obj["x"] is None or obj["y"] is None:
            continue
        pads.append(obj)
    if len(pads) < 2:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": "scope 内带坐标 pad 少于 2（不判，unknown）",
        }, False
    scale = length_to_mm(1.0, coord_unit) or 1.0
    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for i in range(len(pads)):
        for j in range(i + 1, len(pads)):
            a, b = pads[i], pads[j]
            if a["layer"] != b["layer"]:
                continue  # 焊盘间距=同层口径
            dist = math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * scale
            if best is None or dist < best[0]:
                best = (dist, a, b)
    if best is None:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": "scope 内无同层 pad 对（不判，unknown）",
        }, False
    threshold = length_to_mm(float(rule["value"]), rule["unit"])
    if threshold is None:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": f"规则单位 {rule['unit']!r} 非长度族（不判，unknown）",
        }, False
    dist, a, b = best
    if dist >= threshold:
        return None, None, True
    return {
        "rule": rule["name"],
        "objects": [a["name"], b["name"]],
        "actual": round(dist, 9),
        "expected": f">= {_fmt_num(rule['value'])} {rule['unit']}",
        "unit": rule["unit"],
    }, None, True


def _check_rf_ground_via_fence(
    rule: dict[str, Any], objects: list[dict[str, Any]],
    coord_unit: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """RF 走线参考点半径内 GND 过孔计数下限（value=count, radius_mm）。

    GND 过孔判定=type via 且 net 匹配 :data:`GND_NET_RE`；缺 radius_mm/
    无带坐标 RF 走线 → unknown。
    """
    radius = rule["radius_mm"]
    if radius is None or radius <= 0:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": "rf_ground_via_fence 缺 radius_mm（不判，unknown）",
        }, False
    scale = length_to_mm(1.0, coord_unit) or 1.0
    traces = []
    for obj in objects:
        if obj["type"] != "trace" or not obj["rf"]:
            continue
        if "*" not in rule["layer_scope"] and \
                obj["layer"] not in rule["layer_scope"]:
            continue
        if obj["x"] is None or obj["y"] is None:
            continue
        traces.append(obj)
    vias = [o for o in objects
            if o["type"] == "via" and o["x"] is not None
            and o["y"] is not None and GND_NET_RE.match(o["net"].upper())]
    if not traces:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": "scope 内无带坐标 RF 走线（不判，unknown）",
        }, False
    min_count = int(rule["value"])
    radius_mm = radius * scale
    deficits: list[tuple[dict[str, Any], int]] = []
    for trace in traces:
        count = sum(
            1 for v in vias
            if math.hypot(v["x"] - trace["x"], v["y"] - trace["y"]) * scale
            <= radius_mm)
        if count < min_count:
            deficits.append((trace, count))
    if not deficits:
        return None, None, True
    worst = min(deficits, key=lambda p: p[1])
    return {
        "rule": rule["name"],
        "objects": [t["name"] for t, _ in deficits],
        "actual": worst[1],
        "expected": (f">= {min_count} GND via within "
                     f"{_fmt_num(radius)} mm"),
        "unit": "count",
    }, None, True


def _check_rf_shield_clearance(
    rule: dict[str, Any], objects: list[dict[str, Any]],
    coord_unit: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """RF 对象参考点到屏蔽罩矩形边界最小距离下限。

    屏罩=type shield 且 x/y/w/h 齐备；RF 对象=rf=True 且带坐标
    （除 shield 自身）；缺任一侧 → unknown。
    """
    scale = length_to_mm(1.0, coord_unit) or 1.0
    shields = []
    for obj in objects:
        if obj["type"] != "shield":
            continue
        if "*" not in rule["layer_scope"] and \
                obj["layer"] not in rule["layer_scope"]:
            continue
        if None in (obj["x"], obj["y"], obj["w"], obj["h"]):
            continue
        shields.append(obj)
    rf_objs = [o for o in objects
               if o["rf"] and o["type"] != "shield"
               and o["x"] is not None and o["y"] is not None]
    if not shields or not rf_objs:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": "缺屏蔽罩矩形或带坐标 RF 对象（不判，unknown）",
        }, False
    threshold = length_to_mm(float(rule["value"]), rule["unit"])
    if threshold is None:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": f"规则单位 {rule['unit']!r} 非长度族（不判，unknown）",
        }, False
    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for rf in rf_objs:
        for sh in shields:
            dist = _point_rect_distance(
                rf["x"] * scale, rf["y"] * scale, sh["x"] * scale,
                sh["y"] * scale, sh["w"] * scale, sh["h"] * scale)
            if best is None or dist < best[0]:
                best = (dist, rf, sh)
    dist, rf, sh = best
    if dist >= threshold:
        return None, None, True
    return {
        "rule": rule["name"],
        "objects": [rf["name"], sh["name"]],
        "actual": round(dist, 9),
        "expected": f">= {_fmt_num(rule['value'])} {rule['unit']}",
        "unit": rule["unit"],
    }, None, True


def _active_rules(
    rules: list[dict[str, Any]], warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """生效规则表：禁用剔除 + 同 (type, layer_scope) 重复压制。

    压制语义：同键重复时 priority 最大者生效（平权取文件序靠前），
    其余标 superseded 进 warnings 不判——priority 数值越大优先级越高。
    """
    enabled = [r for r in rules if r["enabled"]]
    buckets: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    for i, rule in enumerate(enabled):
        key = (rule["type"], tuple(sorted(rule["layer_scope"])))
        buckets.setdefault(key, []).append(i)
    active: list[dict[str, Any]] = []
    for _key, idxs in buckets.items():
        if len(idxs) == 1:
            active.append(enabled[idxs[0]])
            continue
        winner = max(idxs, key=lambda i: (enabled[i]["priority"], -i))
        for i in idxs:
            if i == winner:
                active.append(enabled[i])
                continue
            loser = enabled[i]
            warnings.append({
                "line": loser["line"], "rule": loser["name"],
                "note": (f"规则 {loser['name']!r} 同 type+layer_scope 重复"
                         f"被 priority={enabled[winner]['priority']} 的 "
                         f"{enabled[winner]['name']!r} 压制（superseded 不判）"),
            })
    return active


def evaluate_drc_rules(
    rules: list[dict[str, Any]], objects: list[dict[str, Any]],
    *, coord_unit: str = "mm", rf_checks: bool = False,
) -> dict[str, Any]:
    """规则集 × design 对象 → 结构化判定（violations/summary/verdict）。

    判定语义：violation 行数>0→issues；unknown（缺测/缺坐标/未知单位/
    unknown type/RF 未启用）>0→attention；否则 clean（与
    dfm_rule_schema verdict 语义同族）。violations 行=任务书 schema
    ``{rule, objects, actual, expected}``+unit。
    """
    warnings: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    summary = {
        "n_rules": len(rules),
        "n_enabled": sum(1 for r in rules if r["enabled"]),
        "n_evaluated": 0,
        "n_passed_rules": 0,
        "n_violation_rules": 0,
        "n_unknown_rules": 0,
        "n_rf_skipped": 0,
        "n_superseded": 0,
        "n_object_checks": 0,
    }
    active = _active_rules(rules, warnings)
    summary["n_superseded"] = summary["n_enabled"] - len(active)
    for rule in active:
        rtype = rule["type"]
        if rule["direction"] is None:
            summary["n_unknown_rules"] += 1
            warnings.append({
                "line": rule["line"], "rule": rule["name"],
                "note": f"未知规则类型 {rtype!r}（不判）",
            })
            continue
        if rtype in RF_RULE_TYPES and not rf_checks:
            summary["n_rf_skipped"] += 1
            warnings.append({
                "line": rule["line"], "rule": rule["name"],
                "note": "RF 检查未启用（--rf），规则未判",
            })
            continue
        if rtype == "rf_impedance":
            violation, warning, measured = _check_rf_impedance(
                rule, objects)
        elif rtype == "rf_pad_clearance":
            violation, warning, measured = _check_rf_pad_clearance(
                rule, objects, coord_unit)
        elif rtype == "rf_ground_via_fence":
            violation, warning, measured = _check_rf_ground_via_fence(
                rule, objects, coord_unit)
        elif rtype == "rf_shield_clearance":
            violation, warning, measured = _check_rf_shield_clearance(
                rule, objects, coord_unit)
        else:
            violation, warning, measured = _evaluate_generic(
                rule, objects, summary)
        if warning is not None:
            summary["n_unknown_rules"] += 1
            warnings.append(warning)
            continue
        if not measured:
            summary["n_unknown_rules"] += 1
            warnings.append({
                "line": rule["line"], "rule": rule["name"],
                "note": "scope 内无可判对象（不判，unknown）",
            })
            continue
        summary["n_evaluated"] += 1
        if violation is None:
            summary["n_passed_rules"] += 1
        else:
            summary["n_violation_rules"] += 1
            violations.append(violation)
    if summary["n_violation_rules"] > 0:
        verdict = "issues"
    elif summary["n_unknown_rules"] > 0 or warnings:
        verdict = "attention"
    else:
        verdict = "clean"
    return {
        "violations": violations,
        "summary": summary,
        "verdict": verdict,
        "warnings": warnings,
    }


def _evaluate_generic(
    rule: dict[str, Any], objects: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """通用方向规则求值（min/max/range/enum × 度量键）。"""
    key = RULE_TYPE_METRICS.get(rule["type"])
    if key is None:
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": f"规则类型 {rule['type']!r} 无度量键映射（不判，unknown）",
        }, False
    unknown_note: str | None = None
    measured: list[tuple[dict[str, Any], Any]] = []
    for obj in objects:
        if not _scope_match(rule, obj):
            continue
        metric = _metric_value(obj, key)
        if metric is None:
            continue
        summary["n_object_checks"] += 1
        status, actual, expected = _canonical_compare(
            rule["value"], rule["unit"], metric)
        if status == "unknown":
            unknown_note = (f"度量单位族与规则单位 "
                            f"{rule['unit']!r} 不匹配（不判，unknown）")
            continue
        measured.append((obj, (status, actual, expected)))
    if not measured:
        if unknown_note is not None:
            return None, {
                "line": rule["line"], "rule": rule["name"],
                "note": unknown_note,
            }, False
        return None, None, False
    bad, n_unknown, _ok = _violating(rule, measured)
    if n_unknown:
        # 任一对象度量单位族与规则不匹配=规则级不判（单位不猜，宁 unknown
        # 不误判；family mismatch 是规则×对象配对性质，如实披露）
        return None, {
            "line": rule["line"], "rule": rule["name"],
            "note": unknown_note
            or f"{n_unknown} 个对象度量单位不可归一（unknown）",
        }, True
    if not bad:
        return None, None, True
    violation = {
        "rule": rule["name"],
        "objects": [o["name"] for o, _ in bad],
        "actual": _worst_actual(rule, bad),
        "expected": _expected_text(rule),
        "unit": rule["unit"],
    }
    return violation, None, True


# ─── 缺省 RF 规则集归一 + dfm_rule_schema 桥 ───────────────────────────────


def default_rf_rules() -> list[dict[str, Any]]:
    """:data:`DEFAULT_RF_RULESET` → 归一规则表（与解析产物同 schema）。"""
    warnings: list[dict[str, Any]] = []
    return [
        normalize_rule(raw, source_format="builtin", line=i,
                       warnings=warnings, index=i)
        for i, raw in enumerate(DEFAULT_RF_RULESET, 1)
    ]


_QUANTITY_BY_FAMILY = {
    "length": QUANTITY_LENGTH_MM,
    "ohm": QUANTITY_IMPEDANCE_OHM,
    "token": QUANTITY_TOKEN,
}


def to_dfm_rule(rule: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """DRC 规则 → dfm_rule_schema 规则 dict（不可映射如实 (None, 原因)）。

    映射：id=name、direction 直通、quantity 按单位族（长度值归一 mm）、
    ipc_ref=UNVERIFIED_doc_anchor（#df6-⑨ 诚实口径——DRC 规则文件无
    IPC 条款锚，不臆造）、source=drc:<source_format>:<name>、
    severity=hard；count 量纲不在 dfm QUANTITIES 内如实跳过。
    """
    direction = rule.get("direction")
    if direction not in _DIRECTIONS:
        return None, (f"规则 {rule.get('name')!r} 方向 {direction!r} "
                      "不在 dfm 方向词汇内")
    unit = rule.get("unit") or "mm"
    family = unit_family(unit)
    quantity = _QUANTITY_BY_FAMILY.get(family)
    if quantity is None:
        return None, (f"规则 {rule.get('name')!r} 单位 {unit!r}（count）"
                      f"量纲不在 dfm QUANTITIES {QUANTITIES} 内")
    value = rule.get("value")
    if family == "length":
        if isinstance(value, (list, tuple)):
            value = [length_to_mm(float(v), unit) for v in value]
        else:
            value = length_to_mm(float(value), unit)
    dfm: dict[str, Any] = {
        "id": rule["name"],
        "direction": direction,
        "quantity": quantity,
        "value": value,
        "ipc_ref": "UNVERIFIED_doc_anchor",
        "source": f"drc:{rule.get('source_format', 'unknown')}:{rule['name']}",
        "severity": "hard",
        "notes": rule.get("notes", ""),
    }
    return dfm, None
