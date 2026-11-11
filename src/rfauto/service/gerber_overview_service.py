"""RS-274X Gerber 最小读入口（T-Q6，aurora_q Q-W7-1）——统计级，零完整解析。

**禁写完整 Gerber 解析器**（任务书铁律）：本模块只做统计级读入——

- 格式判定：``%FS``（零省略 L/T + 记法 A/I + X/Y 整数·小数位）与
  ``%MO``（单位 MM/IN）参数原文；
- D 码清单：``%ADD<码><模板>,<参数>*%`` 逐条（模板名+参数**原文串**，
  零数值解释）；aperture 宏 ``%AM`` 只计数（宏体不解析）；
- 指令计数：体指令 D01（绘制/曝光）/D02（移动）/D03（闪光）直读计数 +
  D 码选择（D≥10）计数；
- 坐标 bbox：**声明聚合**（铁律 7）——只聚合语句里**显式出现**的 X/Y 词
  （整数原文）；I/J 是圆弧圆心偏移量（非坐标）**不入 bbox**；模态续用
  （隐式坐标）不模拟——bbox 是"显式坐标词的范围"而非渲染几何范围
  （aperture 尺寸不外扩），两边界都在 docstring 声明。

单位换算边界：FS 已知时 min/max 除以 ``10^小数位`` 得文件单位（MO）值
——这是 FS 规范**定义的记法换算**（X 整数位+小数位=数字小数点位置），
非几何派生；FS 缺失时坐标词无法定标（前导/尾随零歧义）→ min/max 置
None、只给整数原文（不猜，#316 兜底方向=多报）。

解析边界（如实声明）：
- X2 属性（``%TF/%TA/%TD``）不解析——core/gerber_export.parse_x2_file_attributes
  与 fab_export 面已有专责消费，此处只归入 other_extended 计数；
- 注释（G04）内与扩展命令块外的同形文本不做豁免（统计级口径）；G 码
  （G01/G36/G37…）与 M02 不计数（不在最小读入口清单）；
- 只认大写标准词法（RS-274X 规范词法即大写）；无法识别的扩展字段名
  归入 ``other_extended`` 计数（原样清单，不猜语义）。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "GERBER_OVERVIEW_SCHEMA_VERSION",
    "gerber_overview",
]

#: gerber_overview 信封 schema 版本（字段只增不改形——只增纪律）。
GERBER_OVERVIEW_SCHEMA_VERSION = "1.0"

#: 扩展命令块 ``%...%``（RS-274X 4.11；块内可含多个 ``*`` 分隔字段）。
_EXT_BLOCK_RE = re.compile(r"%([^%]*)%", re.DOTALL)
#: ``%FS`` 格式规范：零省略（L/T）+ 记法（A/I）+ X/Y 各整数位·小数位一位数字。
_FS_RE = re.compile(r"^FS([LT])([AI])X(\d)(\d)Y(\d)(\d)$")
#: ``%ADD`` 孔径定义：D 码（≥10）+ 模板名（C/R/O/P/宏名）+ 参数原文。
_ADD_RE = re.compile(r"^ADD(\d+)([A-Za-z0-9_.$\-]+)(?:,(.*))?$")
#: 体指令：可选坐标词串 + D 码 + ``*``（D01 可缩写 D1；G54D10 前缀兼容）。
_STMT_RE = re.compile(r"((?:[XYIJ][+-]?\d+)*)D0*(\d+)\*")
#: 坐标词拆解（只取 X/Y——I/J 是圆弧偏移不入 bbox）。
_XY_RE = re.compile(r"([XY])([+-]?\d+)")


def _scale(raw: int, decimals: int) -> float:
    """FS 记法定义的定标（raw 整数 ÷ 10^小数位；规范语义非几何派生）。"""
    return round(raw / (10 ** decimals), 6)


def _axis_range(vals: list[int], decimals: int | None) -> dict[str, Any]:
    """单轴声明聚合：整数原文 min/max + FS 已知时文件单位值（缺则 None）。"""
    if not vals:
        return {"raw_min": None, "raw_max": None, "min": None, "max": None}
    lo, hi = min(vals), max(vals)
    return {
        "raw_min": lo,
        "raw_max": hi,
        "min": _scale(lo, decimals) if decimals is not None else None,
        "max": _scale(hi, decimals) if decimals is not None else None,
    }


def gerber_overview(gerber_path: str | Path) -> dict[str, Any]:
    """RS-274X Gerber 文本 → 最小统计读信封（格式/D 码/指令计数/声明 bbox）。

    Returns:
        envelope：``{ok, kind: "gerber", path, schema_version, format,
        apertures, n_apertures, n_aperture_macros, n_aperture_selects,
        ops, bbox, other_extended, n_other_body_commands}``；

        - ``format``：``{unit, fs, fs_present}``——unit ∈ {"MM","IN",None}；
          fs=``{zero_omission, notation, x: [整数位, 小数位], y: [...]}`
          （多块 FS 取末块，键序文件序）；
        - ``apertures``：``{dcode, template, params}`` 列表（文件序；
          params 原文串不拆不解释）；
        - ``ops``：``{"d01": n, "d02": n, "d03": n}`` 直读计数；
        - ``bbox``：``{raw_min: [x,y], raw_max: [x,y], min, max, unit,
          fs_decimals, n_declared_points}``——min/max=[x, y] 逐轴（FS 已知
          时=文件单位值；FS 缺失或该轴无显式词 → 该轴 None）；无任何坐标
          词时 bbox=None。

    坏文件（不可读/空文件/无扩展命令且无 D 码指令）→ error 信封。
    """
    path = Path(gerber_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return error_envelope([f"文件不可读: {path}（{exc}）"],
                              kind="gerber", path=str(path))

    unit: str | None = None
    fs: dict[str, Any] | None = None
    apertures: list[dict[str, Any]] = []
    n_macros = 0
    other_extended: Counter[str] = Counter()

    for m in _EXT_BLOCK_RE.finditer(text):
        in_macro = False
        for fld in m.group(1).split("*"):
            fld = fld.strip()
            if not fld or in_macro:
                continue  # %AM 宏体字段不分类（边界：宏体不解析）
            if fld.startswith("AM"):
                n_macros += 1
                in_macro = True
                continue
            fm = _FS_RE.match(fld)
            if fm:
                fs = {
                    "zero_omission": fm.group(1),
                    "notation": fm.group(2),
                    "x": [int(fm.group(3)), int(fm.group(4))],
                    "y": [int(fm.group(5)), int(fm.group(6))],
                }
                continue
            if fld.startswith("MO"):
                arg = fld[2:]
                if arg in ("MM", "IN"):
                    unit = arg
                else:
                    other_extended[fld.split(",")[0]] += 1
                continue
            am = _ADD_RE.match(fld)
            if am:
                apertures.append({
                    "dcode": int(am.group(1)),
                    "template": am.group(2),
                    "params": am.group(3) or "",
                })
                continue
            other_extended[fld.split(",")[0]] += 1

    body = _EXT_BLOCK_RE.sub("", text)
    xs: list[int] = []
    ys: list[int] = []
    ops = {"d01": 0, "d02": 0, "d03": 0}
    n_aperture_selects = 0
    n_other_body = 0
    for m in _STMT_RE.finditer(body):
        coords, dcode = m.group(1), int(m.group(2))
        if dcode in (1, 2, 3):
            ops[f"d0{dcode}"] += 1
            for axis, val in _XY_RE.findall(coords):
                (xs if axis == "X" else ys).append(int(val))
        elif dcode >= 10:
            n_aperture_selects += 1
        else:
            n_other_body += 1

    if fs is None and not apertures and not n_macros \
            and not any(ops.values()) and not n_aperture_selects:
        return error_envelope(
            ["不像 RS-274X Gerber 文件（无 FS/MO/ADD 扩展命令也无 D 码指令）"],
            kind="gerber", path=str(path))

    bbox: dict[str, Any] | None = None
    if xs or ys:
        decimals = None if fs is None else (fs["x"][1], fs["y"][1])
        xr = _axis_range(xs, None if decimals is None else decimals[0])
        yr = _axis_range(ys, None if decimals is None else decimals[1])
        bbox = {
            "raw_min": [xr["raw_min"], yr["raw_min"]],
            "raw_max": [xr["raw_max"], yr["raw_max"]],
            "min": [xr["min"], yr["min"]],
            "max": [xr["max"], yr["max"]],
            "unit": unit,
            "fs_decimals": list(decimals) if decimals is not None else None,
            "n_declared_points": len(xs) + len(ys),
        }

    return ok_envelope(
        kind="gerber",
        path=str(path),
        schema_version=GERBER_OVERVIEW_SCHEMA_VERSION,
        format={"unit": unit, "fs": fs, "fs_present": fs is not None},
        apertures=apertures,
        n_apertures=len(apertures),
        n_aperture_macros=n_macros,
        n_aperture_selects=n_aperture_selects,
        ops=ops,
        bbox=bbox,
        other_extended=dict(sorted(other_extended.items())),
        n_other_body_commands=n_other_body,
    )
