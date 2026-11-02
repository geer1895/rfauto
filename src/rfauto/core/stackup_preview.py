"""PCB 叠层 3D 等轴预览（aurora_p A5：T-O3 横截面 .drawio 的立体视检姊妹件）。

T-O3（core/stackup_diagram.py）给的是横截面 2D 工程图；本模块给**等轴
（isometric）立体预览 PNG**——板框（固定像素足迹 :data:`BOARD_W_PX` ×
:data:`BOARD_D_PX`）上逐层堆叠的 slab（长方体），每层三可见面（top/
left/right）+ 右侧 ASCII 标注列 + 引线。定位=报告附件/快速视检件，不是
可编辑工程图。

"算画同源"口径与 T-O3 同极（铁律 7）：图上数字只有**输入原值**——
厚度/zmin/εr 经 :func:`rfauto.core.stackup_diagram.format_number` 原值
文本化（最短往返表示，零单位换算）；``total_thickness`` 是确定性加法
（Σthickness，round 12）与 2D 的 zmin 累计同类（布局几何，非物理公式）。
Z 比例尺 :data:`Z_PX_PER_UNIT` 是**几何映射**（长度→像素），不改写任何
标注数字；等轴投影常数是字面常量（零三角函数调用）。

数据源两路（单一装配内核 :func:`build_preview_plan`，入参=中性 spec）：

1. **RFStackup**（adapters/layout_stack.py 单源 schema，zmin_m/thickness_m
   米制、kind∈signal/ground/dielectric）→ :func:`preview_spec_from_rfstackup`
   （鸭子类型读属性——core 层不得 import adapters，分层契约）：zmin/厚度
   **逐层原值直通**（``zmin_source="input"``），单位 ``"m"``；
2. **T-O3 声明式叠层**（层卡 name/kind/thickness_mm/material/er，自顶向下、
   kind∈signal/plane/dielectric）→ :func:`preview_spec_from_declarative`
   （校验复用 ``normalize_stackup`` 单源）：单位 ``"mm"``，slab 底 z 由
   布局几何得出 ``zmin_i = total − depth_i − t_i``（``zmin_source=
   "layout"``，信封如实标记来源）。

颜色单源 :data:`KIND_COLORS` = 2D 的 ``KIND_TABLE`` 原表 + ``ground``
（RFStackup 铜面枚举）与 ``plane`` 同色（同为铜面）——top 面=2D 层带
同色，left/right 面按固定因子加深（立体感），零新增调色板。

确定性：同 spec 两次 ``build_preview_plan`` 逐键相等；``render_preview_png``
两次逐字节相同（固定 DejaVu Sans/字号/dpi、PNG 元数据零时间戳零软件
串——savefig ``metadata={"Software": None}``，实测 chunk 仅
IHDR/pHYs/IDAT/IEND）。画布 1:1（1 数据 px = 1 输出 px），尺寸随内容
自适应（T-O3 页面自适应同款），超 :data:`MAX_CANVAS_PX` 显式报错（典型
=单位写错：米值当毫米）。

图内文本**一律 ASCII**（AGENTS 开源发布批⑩：matplotlib CJK 缺字形=
豆腐块）——层名/材料/标题含非 ASCII 字符时 ``backslashreplace`` 无损
转义进图并 warnings 如实提示；plan 的 name/material 字段仍是原值。

零 IO：plan 为纯 dict；:func:`render_preview_png` 返回 PNG bytes（落盘在
service 层）。matplotlib 为 core 依赖（pyproject）但只在渲染函数内惰性
import（形态③：缺席显式 RuntimeError，plan 面零 matplotlib 依赖）；
渲染走 OO 后端（Figure+FigureCanvasAgg，不 import pyplot、不切全局
backend、无 figure 注册表泄漏）。
"""

from __future__ import annotations

import io
import math
from itertools import pairwise
from typing import Any

from rfauto.core.stackup_diagram import (
    KIND_TABLE,
    PX_PER_MM,
    format_number,
    normalize_stackup,
)

__all__ = [
    "BOARD_D_PX",
    "BOARD_W_PX",
    "KIND_COLORS",
    "MAX_CANVAS_PX",
    "PREVIEW_DPI",
    "Z_PX_PER_UNIT",
    "build_preview_plan",
    "preview_spec_from_declarative",
    "preview_spec_from_rfstackup",
    "render_preview_png",
]

# ─── 常量单源（颜色/比例尺/足迹/投影/标注几何；测试逐键断言） ───────────────

#: kind → (top 面填充色, 描边色)。= 2D ``KIND_TABLE`` 原表（signal 走线红/
#: plane 铜面橙/dielectric 介质蓝）+ ``ground``（RFStackup 枚举）与 plane
#: 同色——两路数据源一张色表，未知 kind 显式 ValueError（不静默 generic）。
KIND_COLORS: dict[str, tuple[str, str]] = {
    **KIND_TABLE,
    "ground": KIND_TABLE["plane"],
}

#: 声明长度单位 → Z 向像素比例尺（px/unit）。两档都 = 200 px/mm
#: （= 2D 横截面 ``PX_PER_MM`` 同一比例尺：1oz 铜 35µm→7px、1.6mm 板→320px），
#: 跨图同尺度可比；单位不在表内显式报错（不猜单位）。
Z_PX_PER_UNIT: dict[str, float] = {
    "mm": PX_PER_MM,
    "m": PX_PER_MM * 1000.0,
}

#: 板框像素足迹（等轴视图的 x 向宽 / y 向深；固定常量——板框只是 slab 的
#: 公共底面，不编码真实板尺寸，图上也不标板尺寸数字）
BOARD_W_PX = 320.0
BOARD_D_PX = 240.0

#: 等轴投影常数（字面常量，零三角函数调用）：x 轴→右上 (cos30, sin30)、
#: y 轴→左上 (−cos30, sin30)、z 轴→正上；原点=最近角（屏幕最低点）。
#: u = cos30·(x − y)；v = sin30·(x + y) + z_px
_ISO_COS30 = 0.8660254037844386
_ISO_SIN30 = 0.5

#: 侧面加深因子（top=kind 原色；right 轻加深、left 重加深——左上光源惯例）
_SHADE_RIGHT = 0.90
_SHADE_LEFT = 0.78

#: 标注列几何（数据 px = 输出 px，1:1 画布）：标注锚=right 面远端竖边中点
#: （x=W, y=0, z=slab 中心），标注起点 = 锚 + LABEL_GAP；行高 LABEL_H ≥
#: 8pt 字高（100dpi 下 ≈11px）；贪心非叠=只上推不下拉（处理序=zmin 升序）
LABEL_GAP = 24.0
LABEL_H = 14.0
LABEL_VGAP = 2.0
LABEL_FONT_PT = 8.0
#: 标注宽度估计（px/字符，8pt DejaVu Sans 平均步进 ≈6px，取 7 留余）——
#: 只用于画布包络（防裁切），不影响几何
_LABEL_CHAR_PX = 7.0
_LEADER_INSET = 4.0

#: 画布：边距/标题带/dpi/上限。1:1 映射（figsize = 像素/dpi），dpi 固定
#: ——字号 pt→px 与 LABEL_H 配套，不作参数
_MARGIN_PX = 24.0
_TITLE_BAND_PX = 28.0
TITLE_FONT_PT = 10.0
PREVIEW_DPI = 100
#: 画布任一边超此像素即显式 ValueError（典型=单位写错：米值填进 mm 档
#: 或 mm 值填进 m 档→厚度放大 1000×）
MAX_CANVAS_PX = 8000

#: 薄带可见性提示阈值（px；与 2D 同值——高度不 clamp，比例失真才是画假图）
_MIN_VISIBLE_PX = 6.0

#: 缺省标题（ASCII）
_DEFAULT_TITLE = "PCB stackup isometric preview"

_ZMIN_SOURCES = ("input", "layout")

#: warnings 文案（固定顺序=确定性；信封逐条可断言）
_WARN_THIN = ("layer {name!r} slab height {h}px (<{th}px visible threshold; "
              "height stays proportional to thickness, zoom to inspect)")
_WARN_NO_DIELECTRIC = "no dielectric layer (conductor-only declaration; drawn as given)"
_WARN_NO_CONDUCTOR = "no conductor layer (signal/plane/ground all absent; dielectric-only stack)"
_WARN_GAP = ("z gap between layer {a!r} (zmax={za}) and layer {b!r} (zmin={zb}) "
             "in draw order; slabs drawn at declared z, gap left empty")
_WARN_OVERLAP = ("z overlap between layer {a!r} (zmax={za}) and layer {b!r} (zmin={zb}) "
                 "in draw order; slabs drawn at declared z, upper slab paints over")
_WARN_NON_ASCII = ("{where} contains non-ASCII characters; escaped as \\uXXXX in the "
                   "figure (matplotlib CJK glyph risk), plan keeps the original value")


# ─── 小工具 ──────────────────────────────────────────────────────────────────


def _r6(v: float) -> float:
    """几何数值收敛 round 6（与 2D 同口径；1e-6px 远低于视觉分辨率）。"""
    return round(float(v), 6)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def _ascii(text: str) -> tuple[str, bool]:
    """文本 → ASCII（非 ASCII 字符 ``\\uXXXX`` 无损转义）；返回 (文本, 是否改写)。"""
    out = text.encode("ascii", "backslashreplace").decode("ascii")
    return out, out != text


def _shade(hex_color: str, factor: float) -> str:
    """``#rrggbb`` 按因子整体加深（通道 ×factor，四舍五入夹 0..255；确定性）。"""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    scaled = (max(0, min(255, round(c * factor))) for c in (r, g, b))
    return "#{:02x}{:02x}{:02x}".format(*scaled)


def _iso(x: float, y: float, z_px: float) -> tuple[float, float]:
    """等轴投影（字面常量线性映射）：(x, y, z_px) → (u, v)，round 6。"""
    return (_r6(_ISO_COS30 * (x - y)), _r6(_ISO_SIN30 * (x + y) + z_px))


# ─── spec 适配（两路数据源 → 中性 spec；数字原值直通） ───────────────────────


def preview_spec_from_rfstackup(stackup: Any) -> dict[str, Any]:
    """RFStackup（鸭子类型）→ 预览 spec（单位 m；zmin/厚度逐层原值直通）。

    鸭子契约（core 不 import adapters）：``stackup.name``（可缺）、
    ``stackup.layers`` 可迭代，每层具 ``name/kind/zmin_m/thickness_m/
    material`` 属性（RFRouteLayer 即是；``er`` RFStackup 无此字段→None）。
    缺属性显式 ValueError。零厚度层（RFStackup 合法的零厚金属片）在
    :func:`build_preview_plan` 显式报错——零体积 slab 无立体可画。
    """
    if not hasattr(stackup, "layers"):
        raise ValueError(
            "stackup 缺 layers 属性（期望 RFStackup 鸭子类型：name + "
            "layers[*].name/kind/zmin_m/thickness_m/material）")
    raw_layers = stackup.layers
    try:
        raw_list = list(raw_layers)
    except TypeError as exc:
        raise ValueError(f"stackup.layers 必须可迭代，收到 {type(raw_layers)!r}") from exc
    layers: list[dict[str, Any]] = []
    for i, lay in enumerate(raw_list):
        for attr in ("name", "kind", "zmin_m", "thickness_m", "material"):
            if not hasattr(lay, attr):
                raise ValueError(
                    f"stackup.layers[{i}] 缺属性 {attr!r}（期望 RFRouteLayer 形态）")
        layers.append({
            "name": lay.name,
            "kind": lay.kind,
            "thickness": lay.thickness_m,
            "zmin": lay.zmin_m,
            "material": lay.material,
            "er": None,
            "zmin_source": "input",
        })
    name = getattr(stackup, "name", None)
    return {"name": name if isinstance(name, str) and name else None,
            "unit": "m", "layers": layers}


def preview_spec_from_declarative(stackup: Any) -> dict[str, Any]:
    """T-O3 声明式叠层 → 预览 spec（单位 mm；schema 校验复用 normalize_stackup）。

    层卡自顶向下声明（T-O3 口径）；slab 底 z（自底向上）由布局几何得出
    ``zmin_i = total − depth_i − t_i``（total=Σt、depth_i=Σt[0..i-1]，
    round 6；``zmin_source="layout"``）。厚度/εr/材料/层名原值直通。
    非法输入（空层/kind 非法/厚度 ≤0/多余键…）由 normalize_stackup 显式
    ValueError。
    """
    norm = normalize_stackup(stackup)
    ths = [lay["thickness_mm"] for lay in norm["layers"]]
    total = 0.0
    for t in ths:
        total += t
    layers: list[dict[str, Any]] = []
    depth = 0.0
    for lay, t in zip(norm["layers"], ths, strict=True):
        layers.append({
            "name": lay["name"],
            "kind": lay["kind"],
            "thickness": t,
            "zmin": _r6(total - depth - t),
            "material": lay["material"],
            "er": lay["er"],
            "zmin_source": "layout",
        })
        depth += t
    return {"name": norm["title"], "unit": "mm", "layers": layers}


# ─── 装配计划（校验 + 投影几何 + 标注列 + 画布包络 + warnings） ───────────────


def _validate_spec(spec: Any) -> tuple[str | None, str, list[dict[str, Any]]]:
    if not isinstance(spec, dict):
        raise ValueError(f"spec 必须是 dict，收到 {type(spec)!r}")
    extra = set(spec) - {"name", "unit", "layers"}
    if extra:
        raise ValueError(f"spec 存在未支持键 {sorted(extra)}；严格三键 name/unit/layers")
    name = spec.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ValueError(f"spec.name 必须是非空字符串或 None，收到 {name!r}")
    unit = spec.get("unit")
    if unit not in Z_PX_PER_UNIT:
        raise ValueError(
            f"spec.unit 未知 {unit!r}；比例尺表仅 {sorted(Z_PX_PER_UNIT)}（不猜单位）")
    raw_layers = spec.get("layers")
    if not isinstance(raw_layers, (list, tuple)) or len(raw_layers) == 0:
        raise ValueError("spec.layers 必须是非空层列表（空叠层无立体可画）")
    allowed = {"name", "kind", "thickness", "zmin", "material", "er", "zmin_source"}
    layers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_layers):
        where = f"layers[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} 必须是 dict，收到 {type(raw)!r}")
        extra = set(raw) - allowed
        if extra:
            raise ValueError(f"{where} 存在未支持键 {sorted(extra)}")
        lname = raw.get("name")
        if not isinstance(lname, str) or not lname.strip():
            raise ValueError(f"{where}.name 必须是非空字符串，收到 {lname!r}")
        if lname in seen:
            raise ValueError(f"{where}.name 层名重名：{lname!r}")
        seen.add(lname)
        kind = raw.get("kind")
        if kind not in KIND_COLORS:
            raise ValueError(
                f"{where}.kind 未知 {kind!r}；色表枚举仅 {sorted(KIND_COLORS)}（不静默 generic）")
        thickness = _finite(raw.get("thickness"), f"{where}.thickness")
        if thickness <= 0:
            raise ValueError(
                f"{where}.thickness 必须 >0（层 {lname!r} 厚度 {thickness!r}：零/负厚度"
                " slab 无立体可画；RFStackup 零厚金属片不可预览）")
        zmin = _finite(raw.get("zmin"), f"{where}.zmin")
        material = raw.get("material")
        if material is not None and not isinstance(material, str):
            raise ValueError(f"{where}.material 必须是字符串或 None，收到 {type(material)!r}")
        er = raw.get("er")
        if er is not None:
            er = _finite(er, f"{where}.er")
            if er < 1.0:
                raise ValueError(f"{where}.er 必须 ≥1（真空下界），收到 {er!r}")
        zsrc = raw.get("zmin_source", "input")
        if zsrc not in _ZMIN_SOURCES:
            raise ValueError(f"{where}.zmin_source 必须在 {_ZMIN_SOURCES}，收到 {zsrc!r}")
        layers.append({"name": lname, "kind": kind, "thickness": thickness,
                       "zmin": zmin, "material": material, "er": er,
                       "zmin_source": zsrc})
    return name, unit, layers


def _label_text(lay: dict[str, Any], unit: str) -> str:
    segs = [lay["name"], f"[{lay['kind']}]"]
    if lay["material"]:
        segs.append(lay["material"])
    segs.append(f"t={format_number(lay['thickness'])} {unit}")
    if lay["er"] is not None:
        segs.append(f"er={format_number(lay['er'])}")
    return " ".join(segs)


def build_preview_plan(spec: Any, *, title: str | None = None) -> dict[str, Any]:
    """中性 spec → 等轴装配计划（纯 dict；service 与测试同源消费）。

    spec 严格三键::

        {"name": str|None, "unit": "m"|"mm",
         "layers": [{"name", "kind", "thickness", "zmin",
                     "material"?, "er"?, "zmin_source"?}, ...]}

    Returns（关键面）::

        {"unit", "z_px_per_unit", "board_px": {"w","d"},
         "n_layers", "total_thickness", "total_thickness_text",
         "title", "title_source": "param"|"spec"|"default",
         "layers": [{index, name, kind, material, er,
                     thickness, thickness_text, zmin, zmax, zmin_source,
                     height_px, z0_px, z1_px,
                     colors: {top,left,right,edge},
                     faces: {left,right,top: [(u,v)×4]},
                     label, label_anchor: (u,v), label_pos: (u,v)}, ...]
           （声明序；index=声明索引）,
         "draw_order": [index...]（zmin 升序、同 z 按声明序——画家算法）,
         "canvas": {"w_px","h_px","x0","y0","x1","y1","dpi"},
         "warnings": [str...]}

    Raises:
        ValueError: spec 违约（空层/未知 kind/厚度 ≤0/非有限/重名/未知单位
            /多余键）或画布超 :data:`MAX_CANVAS_PX`。
    """
    name, unit, layers = _validate_spec(spec)
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError(f"title 必须是非空字符串或 None，收到 {title!r}")
    scale = Z_PX_PER_UNIT[unit]
    warnings: list[str] = []

    kinds = {lay["kind"] for lay in layers}
    if "dielectric" not in kinds:
        warnings.append(_WARN_NO_DIELECTRIC)
    if not kinds & {"signal", "plane", "ground"}:
        warnings.append(_WARN_NO_CONDUCTOR)

    total = 0.0
    for lay in layers:
        total += lay["thickness"]
    total = round(total, 12)

    w, d = BOARD_W_PX, BOARD_D_PX
    out_layers: list[dict[str, Any]] = []
    for i, lay in enumerate(layers):
        zmax = lay["zmin"] + lay["thickness"]
        z0 = _r6(lay["zmin"] * scale)
        z1 = _r6(zmax * scale)
        h = _r6(lay["thickness"] * scale)
        if h < _MIN_VISIBLE_PX:
            warnings.append(_WARN_THIN.format(
                name=lay["name"], h=format_number(h), th=format_number(_MIN_VISIBLE_PX)))
        fill, edge = KIND_COLORS[lay["kind"]]
        label, changed = _ascii(_label_text(lay, unit))
        if changed:
            warnings.append(_WARN_NON_ASCII.format(where=f"layers[{i}] label"))
        faces = {
            "left": [_iso(0, 0, z0), _iso(0, d, z0), _iso(0, d, z1), _iso(0, 0, z1)],
            "right": [_iso(0, 0, z0), _iso(w, 0, z0), _iso(w, 0, z1), _iso(0, 0, z1)],
            "top": [_iso(0, 0, z1), _iso(w, 0, z1), _iso(w, d, z1), _iso(0, d, z1)],
        }
        out_layers.append({
            "index": i, "name": lay["name"], "kind": lay["kind"],
            "material": lay["material"], "er": lay["er"],
            "thickness": lay["thickness"],
            "thickness_text": format_number(lay["thickness"]),
            "zmin": lay["zmin"], "zmax": round(zmax, 12),
            "zmin_source": lay["zmin_source"],
            "height_px": h, "z0_px": z0, "z1_px": z1,
            "colors": {"top": fill, "left": _shade(fill, _SHADE_LEFT),
                       "right": _shade(fill, _SHADE_RIGHT), "edge": edge},
            "faces": faces,
            "label": label,
            "label_anchor": _iso(w, 0, (z0 + z1) / 2.0),
            "label_pos": None,
        })

    draw_order = sorted(range(len(out_layers)),
                        key=lambda k: (out_layers[k]["zmin"], k))

    # 相邻（画序）slab z 连续性守卫：画按声明 z，缝/叠如实提示不修正
    for a, b in pairwise(draw_order):
        la, lb = out_layers[a], out_layers[b]
        if math.isclose(la["zmax"], lb["zmin"], rel_tol=1e-9, abs_tol=1e-12):
            continue
        fmt = _WARN_GAP if lb["zmin"] > la["zmax"] else _WARN_OVERLAP
        warnings.append(fmt.format(a=la["name"], za=format_number(la["zmax"]),
                                   b=lb["name"], zb=format_number(lb["zmin"])))

    # 标注列：zmin 升序处理，理想位=锚 v；与下一（已放）卡净距不足则上推
    prev_v: float | None = None
    for k in draw_order:
        lay = out_layers[k]
        au, av = lay["label_anchor"]
        v = av
        if prev_v is not None:
            v = max(v, prev_v + LABEL_H + LABEL_VGAP)
        v = _r6(v)
        lay["label_pos"] = (_r6(au + LABEL_GAP), v)
        prev_v = v

    # 标题（参数 > spec 名 > 缺省；ASCII 转义）+ 统计尾
    if title is not None:
        base, src = title, "param"
    elif name:
        base, src = name, "spec"
    else:
        base, src = _DEFAULT_TITLE, "default"
    base_ascii, changed = _ascii(base)
    if changed:
        warnings.append(_WARN_NON_ASCII.format(where="title"))
    total_text = format_number(total)
    title_text = (f"{base_ascii} - {len(out_layers)} layers, total t={total_text} {unit}, "
                  f"z scale {format_number(scale)} px/{unit}")

    # 画布包络（全部面顶点 + 标注盒 + 标题带 + 边距；ceil 整像素，1:1）
    us: list[float] = []
    vs: list[float] = []
    for lay in out_layers:
        for pts in lay["faces"].values():
            for u, v in pts:
                us.append(u)
                vs.append(v)
        lu, lv = lay["label_pos"]
        us.extend([lu, lu + len(lay["label"]) * _LABEL_CHAR_PX])
        vs.extend([lv - LABEL_H / 2.0, lv + LABEL_H / 2.0])
    title_w = len(title_text) * _LABEL_CHAR_PX * (TITLE_FONT_PT / LABEL_FONT_PT)
    us.append(min(us) + title_w)
    x0 = _r6(min(us) - _MARGIN_PX)
    y0 = _r6(min(vs) - _MARGIN_PX)
    w_px = math.ceil(max(us) - min(us) + 2 * _MARGIN_PX)
    h_px = math.ceil(max(vs) - min(vs) + 2 * _MARGIN_PX + _TITLE_BAND_PX)
    if w_px > MAX_CANVAS_PX or h_px > MAX_CANVAS_PX:
        raise ValueError(
            f"画布 {w_px}×{h_px}px 超上限 {MAX_CANVAS_PX}px（总厚 {total_text} {unit} "
            f"× {format_number(scale)} px/{unit}）——请核对 spec.unit 与厚度数值是否同一单位")
    canvas = {"w_px": w_px, "h_px": h_px, "x0": x0, "y0": y0,
              "x1": _r6(x0 + w_px), "y1": _r6(y0 + h_px), "dpi": PREVIEW_DPI}

    return {
        "unit": unit,
        "z_px_per_unit": scale,
        "board_px": {"w": w, "d": d},
        "n_layers": len(out_layers),
        "total_thickness": total,
        "total_thickness_text": total_text,
        "title": title_text,
        "title_source": src,
        "layers": out_layers,
        "draw_order": draw_order,
        "canvas": canvas,
        "warnings": warnings,
    }


# ─── 渲染（matplotlib OO Agg；返回 PNG bytes，零落盘） ─────────────────────────

#: 渲染期 rcParams 钉死（rc_context 作用域内，退出即还原——零全局副作用）：
#: 字体=matplotlib 自带 DejaVu Sans（跨机确定性、ASCII 全覆盖）；禁 usetex；
#: 白底
_RC: dict[str, Any] = {
    "font.family": "DejaVu Sans",
    "font.style": "normal",
    "font.weight": "normal",
    "font.size": LABEL_FONT_PT,
    "text.usetex": False,
    "axes.unicode_minus": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.edgecolor": "white",
    "path.simplify": True,
}

_LEADER_COLOR = "#999999"
_TEXT_COLOR = "#222222"


def render_preview_png(plan: dict[str, Any]) -> bytes:
    """装配计划 → PNG bytes（确定性：同 plan 两次逐字节相同）。

    画布 1:1（figsize = 像素/dpi，axes 满幅，xlim/ylim = canvas 像素域），
    按 ``draw_order`` 画家算法逐 slab 画 left→right→top 三面，再画引线与
    ASCII 标注、标题。PNG 元数据 ``Software`` 显式置 None（零软件串零
    时间戳）。matplotlib 缺席 → RuntimeError（core 依赖缺失属环境错误，
    不静默返回空字节）。
    """
    try:
        import matplotlib  # lazy: optional-dep（核心依赖但只在渲染面取用；缺席显式报错）
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import Polygon
    except ImportError as exc:  # pragma: no cover - 环境缺依赖
        raise RuntimeError("matplotlib 未安装：PCB 叠层 3D 预览渲染需要 matplotlib") from exc

    if not isinstance(plan, dict) or "canvas" not in plan or "layers" not in plan:
        raise ValueError("plan 必须是 build_preview_plan 返回的装配计划 dict")
    canvas = plan["canvas"]
    dpi = int(canvas["dpi"])
    w_px, h_px = int(canvas["w_px"]), int(canvas["h_px"])

    with matplotlib.rc_context(_RC):
        fig = Figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi)
        FigureCanvasAgg(fig)
        ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
        ax.set_xlim(canvas["x0"], canvas["x1"])
        ax.set_ylim(canvas["y0"], canvas["y1"])
        ax.set_axis_off()

        layers = plan["layers"]
        for k in plan["draw_order"]:
            lay = layers[k]
            for face in ("left", "right", "top"):
                ax.add_patch(Polygon(
                    lay["faces"][face], closed=True,
                    facecolor=lay["colors"][face], edgecolor=lay["colors"]["edge"],
                    linewidth=0.6, joinstyle="miter"))
        for k in plan["draw_order"]:
            lay = layers[k]
            au, av = lay["label_anchor"]
            lu, lv = lay["label_pos"]
            ax.plot([au, lu - _LEADER_INSET], [av, lv], linestyle=(0, (3, 3)),
                    linewidth=0.5, color=_LEADER_COLOR)
            ax.text(lu, lv, lay["label"], fontsize=LABEL_FONT_PT, ha="left",
                    va="center", color=_TEXT_COLOR)
        ax.text(canvas["x0"] + _MARGIN_PX, canvas["y1"] - _MARGIN_PX / 2.0,
                plan["title"], fontsize=TITLE_FONT_PT, ha="left", va="top",
                color=_TEXT_COLOR, fontweight="bold")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, metadata={"Software": None})
    return buf.getvalue()
