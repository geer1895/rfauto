"""S 参数曲线图装配内核（aurora_p B4：ads-circuit 反标注曲线嵌入）。

定位（语境钉死）：ads-circuit 反标注 annot_sim 层此前只上图标量指标卡
（system_gain_db/VSWR 等）；本模块把**仿真 payload（parse 后 S 参数复数
矩阵 vs 频率）装配成 |S| dB 曲线图 PNG**，经 data URI 内嵌 drawio image
cell——设计回放"改参后曲线怎么移"一眼可见。service/circuit_sim_service
只编排，数值提取单源在本模块（铁律 7）：曲线数据逐点来自 payload
（``frequency_hz`` + ``s`` dict，ads_netlist.parse_dataset 形态），dB 值
是 payload 复数的确定性函数（20·log10|hypo(re,im)|），零手抄零臆造。

形态先例（实读后同款）：
- data URI **无分号红线**（core/review_annotation.py 形态 B 先例 + T-O8
  spec §3.2）：``;`` 是 drawio style 属性分隔符，data URI 形态一律
  ``data:image/png,<base64>`` **不带** ``;base64``——:func:`curve_image_data_uri`
  与 :func:`curve_image_style` 内建自检（belt-and-suspenders，同先例）；
- PNG 确定性（core/stackup_preview.py A5 先例）：matplotlib OO Agg
  （Figure+FigureCanvasAgg，不 import pyplot、零全局副作用）+ rc_context
  钉字体 DejaVu Sans + savefig ``metadata={"Software": None}``（零时间戳
  零软件串，实测 chunk 仅 IHDR/pHYs/IDAT/IEND）→ 同 plan 两独立进程
  逐字节相同（验收 C）。

管线（三段纯函数，段间 transport 节点 JSON 可序列化——离线 annotate 消费
circuit_result.json 的 curves 节，跨进程零重解析）：

1. :func:`curve_series_from_payload`：payload → 曲线序列节点（选键/逐点
   dB 提取；|S|=0 与非有限分量如实置 None=图上断口，不凑数）；
2. :func:`build_curve_plan`：序列节点 → 渲染计划（GHz 轴、dB 限、配色、
   ASCII 纪律）；
3. :func:`render_curves_png`：计划 → PNG bytes（确定性）；
   :func:`curve_image_data_uri` + :func:`curve_image_style`：bytes →
   无分号 data URI → drawio image cell style。

图内文本**一律 ASCII**（AGENTS 开源发布批⑩：matplotlib CJK 缺字形=
豆腐块）：轴标/曲线名由键名构造（S+数字，天然 ASCII）；标题非 ASCII 时
``backslashreplace`` 无损转义进图并 warnings 如实提示（A5 同款）。

确定性：同 payload 两次全管线逐字节相同——零 uuid 零时间戳、配色/几何
全常量表、字典序只按入参 keys（不遍历 payload dict）。

分层：core 层，仅标准库 + 渲染函数内惰性 import matplotlib（缺席显式
RuntimeError，plan/URI 面零 matplotlib 依赖）；零 service/linkage 依赖
（payload 由调用方注入）。
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

__all__ = [
    "CURVE_CANVAS",
    "CURVE_COLORS",
    "DEFAULT_CURVE_KEYS",
    "build_curve_plan",
    "curve_image_data_uri",
    "curve_image_style",
    "curve_series_from_payload",
    "payload_has_sparams",
    "render_curves_png",
]

# ─── 常量单源（测试逐键断言） ────────────────────────────────────────────────

#: 缺省曲线键（v1 单页双曲线：|S11|/|S21| dB——任务书 MVP 钉死；四端口全
#: 矩阵出图=MVP 后，``keys=`` 显式扩）。键形态=``"<i>_<j>"``（payload["s"]
#: 键名，ads_netlist.parse_dataset 单源）。
DEFAULT_CURVE_KEYS: tuple[str, ...] = ("1_1", "2_1")

#: 曲线配色表（matplotlib classic 色板前五色，固定顺序按 keys 序轮转——
#: 确定性：不依赖 matplotlib 内部 color cycle 状态）。
CURVE_COLORS: tuple[str, ...] = (
    "#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
)

#: 画布（px 与 dpi；640×400 @100dpi，宽高比 1.6——service 曲线卡几何
#: 480×300 同比整数（drawio 卡面 1:1 视觉等比））。
CURVE_CANVAS: dict[str, int] = {"w_px": 640, "h_px": 400, "dpi": 100}

#: y 轴留白（数据 span 的 5%；span=0（常数曲线）时退化为 ±1 dB）。
_Y_PAD_FRACTION = 0.05
_Y_PAD_FALLBACK = 1.0
#: 单点频轴退路（±0.5 GHz 显示窗）。
_X_SINGLE_POINT_PAD = 0.5

#: drawio image cell style 模板（review_annotation 形态 B 同款骨架，去五旗标
#: 锁——曲线卡是 annot_sim 层可动卡，非锁定底图）；data URI **不带
#: ``;base64``**（``;`` 是 style 分隔符，格式红线——自检在
#: :func:`curve_image_style`）。
_IMAGE_STYLE_TEMPLATE = (
    "shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
    "imageAspect=0;aspect=fixed;image={uri};")

#: series 节点 source 属性（provenance：曲线数据提取单源函数全名）。
_SERIES_SOURCE = "rfauto.core.diagram_curve_image.curve_series_from_payload"

#: 渲染期 rcParams 钉死（rc_context 作用域内，退出即还原；A5 _RC 同款——
#: 字体=matplotlib 自带 DejaVu Sans（跨机确定性、ASCII 全覆盖）；禁 usetex）
_RC: dict[str, Any] = {
    "font.family": "DejaVu Sans",
    "font.style": "normal",
    "font.weight": "normal",
    "font.size": 9,
    "text.usetex": False,
    "axes.unicode_minus": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.edgecolor": "white",
}

_GRID_COLOR = "#cccccc"
_TEXT_COLOR = "#222222"


# ─── 1. payload → 曲线序列节点（铁律 7 单源提取） ────────────────────────────


def payload_has_sparams(payload: Any) -> bool:
    """payload 是否携带 S 参数曲线数据（鸭子判定——service 负例软跳过用）。

    判据：``s`` 为非空 dict 且 ``frequency_hz`` 为非空 list（parse_dataset
    形态）；HB 单点 payload（``harmonics``）天然 False。零异常路径。
    """
    if not isinstance(payload, dict):
        return False
    s = payload.get("s")
    freq = payload.get("frequency_hz")
    return (isinstance(s, dict) and len(s) > 0
            and isinstance(freq, list) and len(freq) > 0)


def _key_label(key: str) -> str:
    """``"<i>_<j>"`` → ``"S<i><j>"``（图例名；键形态违约显式报错）。"""
    parts = key.split("_")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(
            f"曲线键必须是 '<i>_<j>' 形态（payload['s'] 键名），收到 {key!r}")
    return f"S{parts[0]}{parts[1]}"


def _db_of(re_: float, im_: float) -> float | None:
    """复数分量 → dB（20·log10|hypot|）；|S|=0 或结果非有限 → None（如实
    断口不凑数——log10(0) 无定义，NaN/inf 分量不上图）。"""
    mag = math.hypot(re_, im_)
    if not math.isfinite(mag) or mag == 0.0:
        return None
    v = 20.0 * math.log10(mag)
    return v if math.isfinite(v) else None


def curve_series_from_payload(
    payload: Any, *, keys: tuple[str, ...] | list[str] = DEFAULT_CURVE_KEYS,
) -> dict[str, Any]:
    """仿真 payload → 曲线序列节点（JSON 可序列化——离线 annotate 的
    transport 形态，circuit_result.json curves 节原样承载）。

    Args:
        payload: ads_netlist.parse_dataset 形态 dict（``frequency_hz`` +
            ``s``；铁律 7 单源——dB 值逐点由 payload 复数算出，零手抄）。
        keys: 曲线键表（``"<i>_<j>"``；缺省 |S11|/|S21|；重复键显式报错）。

    Returns::

        {"keys": [...], "frequency_hz": [...],
         "series": [{"key", "label", "unit": "dB", "db": [float|None, ...]}],
         "source": <提取单源函数全名>}

    Raises:
        ValueError: payload 无 S 参数数据 / 键重复 / 键缺失 / 键形态违约 /
            曲线长度与频轴不齐 / 频轴非有限（fail loud，不静默截断）。
    """
    if not payload_has_sparams(payload):
        raise ValueError(
            "payload 无 S 参数数据（缺 s dict 或 frequency_hz——"
            "HB 单点族无频扫 S 参数，曲线卡如实跳过）")
    freq = payload["frequency_hz"]
    s = payload["s"]
    for i, f in enumerate(freq):
        if isinstance(f, bool) or not isinstance(f, (int, float)) \
                or not math.isfinite(float(f)):
            raise ValueError(f"frequency_hz[{i}] 必须是有限实数，收到 {f!r}")
    if isinstance(keys, str) or not isinstance(keys, (list, tuple)):
        raise ValueError(f"keys 必须是键序列，收到 {keys!r}")
    if len(set(keys)) != len(keys):
        raise ValueError(f"keys 重复：{list(keys)}")
    series: list[dict[str, Any]] = []
    for key in keys:
        key = str(key)
        col = s.get(key)
        if not isinstance(col, list):
            avail = sorted(a for a in s if isinstance(a, str))
            raise ValueError(
                f"payload['s'] 缺曲线键 {key!r}（可用 {avail}——n 端口 payload "
                f"键形态 '<i>_<j>'）")
        if len(col) != len(freq):
            raise ValueError(
                f"曲线 {key!r} 长度 {len(col)} 与频轴 {len(freq)} 不齐"
                "（数据完整性违约，不静默截断）")
        db: list[float | None] = []
        for k, pair in enumerate(col):
            if (isinstance(pair, (list, tuple)) and len(pair) == 2):
                re_, im_ = pair
                if not isinstance(re_, bool) and not isinstance(im_, bool) \
                        and isinstance(re_, (int, float)) \
                        and isinstance(im_, (int, float)):
                    db.append(_db_of(float(re_), float(im_)))
                    continue
            raise ValueError(f"曲线 {key!r}[{k}] 必须是 [re, im] 数对，收到 {pair!r}")
        series.append({"key": key, "label": _key_label(key), "unit": "dB",
                       "db": db})
    return {
        "keys": [str(k) for k in keys],
        "frequency_hz": [float(f) for f in freq],
        "series": series,
        "source": _SERIES_SOURCE,
    }


# ─── 2. 序列节点 → 渲染计划 ──────────────────────────────────────────────────


def _ascii_text(text: str, name: str, warnings: list[str]) -> str:
    """图面文本 ASCII 纪律（A5 同款）：非 ASCII ``backslashreplace`` 无损
    转义 + warnings 如实提示；plan 字段仍存原值（本函数只服务渲染入参）。"""
    if text.isascii():
        return text
    out = text.encode("ascii", "backslashreplace").decode("ascii")
    warnings.append(f"{name} 含非 ASCII 字符，图内已 backslashreplace：{out}")
    return out


def build_curve_plan(
    series_node: Any, *, title: str = "S-Parameters",
) -> dict[str, Any]:
    """曲线序列节点 → 渲染计划（确定性；JSON 往返后的节点同构可消费）。

    计划字段：GHz 显示轴（payload Hz 原值 ÷1e9——单位缩放不改数据）、
    dB 限（有限值包络 + 5% span 留白；全 None 退化 (-1, 0)）、配色按
    keys 序轮转 :data:`CURVE_COLORS`、ASCII 标题。形状违约显式报错。
    """
    if not isinstance(series_node, dict):
        raise ValueError(f"series_node 必须是 dict，收到 {type(series_node)!r}")
    for key in ("keys", "frequency_hz", "series"):
        if key not in series_node:
            raise ValueError(f"series_node 缺键 {key!r}（非 curves 节形态）")
    keys = series_node["keys"]
    freq = series_node["frequency_hz"]
    raw_series = series_node["series"]
    if not isinstance(keys, list) or not keys:
        raise ValueError(f"keys 必须是非空 list，收到 {keys!r}")
    if not isinstance(freq, list) or not freq:
        raise ValueError(f"frequency_hz 必须是非空 list，收到 {freq!r}")
    if not isinstance(raw_series, list) or len(raw_series) != len(keys):
        raise ValueError(
            f"series 必须与 keys 等长（{len(keys)}），收到 {raw_series!r}")
    x = [float(f) / 1e9 for f in freq]  # Hz → GHz（显示单位缩放）
    warnings: list[str] = []
    series: list[dict[str, Any]] = []
    finite: list[float] = []
    for i, node in enumerate(raw_series):
        if not isinstance(node, dict) or not {"key", "label", "db"} <= set(node):
            raise ValueError(
                f"series[{i}] 缺 key/label/db 键（非曲线序列形态）：{node!r}")
        if node["key"] != keys[i]:
            raise ValueError(
                f"series[{i}].key {node['key']!r} 与 keys[{i}] {keys[i]!r} 不齐")
        db = node["db"]
        if not isinstance(db, list) or len(db) != len(x):
            raise ValueError(
                f"series[{i}].db 长度与频轴不齐（{len(db) if isinstance(db, list) else db}"
                f" vs {len(x)}）")
        for v in db:
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(float(v))):
                raise ValueError(
                    f"series[{i}].db 含非有限非 None 值 {v!r}（序列节点违约——"
                    "非有限一律 None）")
            if v is not None:
                finite.append(float(v))
        n_gaps = sum(1 for v in db if v is None)
        if n_gaps:
            warnings.append(
                f"{node['label']} 有 {n_gaps} 个非有限点（|S|=0 或坏点）——"
                "图上如实断口")
        series.append({
            "key": str(node["key"]), "label": str(node["label"]),
            "color": CURVE_COLORS[i % len(CURVE_COLORS)], "db": db,
        })
    if finite:
        ymin, ymax = min(finite), max(finite)
        pad = _Y_PAD_FRACTION * (ymax - ymin)
        if pad == 0.0:
            pad = _Y_PAD_FALLBACK
        y_lim = [ymin - pad, ymax + pad]
    else:
        y_lim = [-1.0, 0.0]  # 全断口退化窗（如实空图不断言数值）
    x0, x1 = min(x), max(x)
    x_lim = [x0, x1] if x0 != x1 else [x0 - _X_SINGLE_POINT_PAD, x1 + _X_SINGLE_POINT_PAD]
    return {
        "title": _ascii_text(title, "title", warnings),
        "x_label": "Frequency (GHz)",
        "y_label": "|S| (dB)",
        "x": x,
        "series": series,
        "x_lim": x_lim,
        "y_lim": y_lim,
        "canvas": dict(CURVE_CANVAS),
        "n_points": len(x),
        "warnings": warnings,
    }


# ─── 3. 渲染（matplotlib OO Agg；A5 同款确定性纪律） ─────────────────────────


def render_curves_png(plan: dict[str, Any]) -> bytes:
    """渲染计划 → PNG bytes（确定性：同 plan 两次/两独立进程逐字节相同）。

    OO 后端（不 import pyplot、零 figure 注册表泄漏）；rc_context 钉字体；
    PNG 元数据 ``Software`` 显式 None（零时间戳零软件串，chunk 仅
    IHDR/pHYs/IDAT/IEND——A5 实测口径）。None 值 → NaN → matplotlib 天然
    断口（如实不连线）。matplotlib 缺席 → RuntimeError（环境错误不静默）。
    """
    try:
        import matplotlib  # lazy: core 依赖但只在渲染面取用
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:  # pragma: no cover - 环境缺依赖
        raise RuntimeError("matplotlib 未安装：S 参数曲线渲染需要 matplotlib") from exc
    if not isinstance(plan, dict) or not {"x", "series", "x_lim", "y_lim",
                                          "canvas"} <= set(plan):
        raise ValueError("plan 必须是 build_curve_plan 返回的渲染计划 dict")
    canvas = plan["canvas"]
    dpi = int(canvas["dpi"])
    w_px, h_px = int(canvas["w_px"]), int(canvas["h_px"])

    with matplotlib.rc_context(_RC):
        fig = Figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi)
        FigureCanvasAgg(fig)
        ax = fig.add_axes((0.115, 0.115, 0.86, 0.80))
        ax.set_xlim(float(plan["x_lim"][0]), float(plan["x_lim"][1]))
        ax.set_ylim(float(plan["y_lim"][0]), float(plan["y_lim"][1]))
        ax.grid(True, linewidth=0.4, color=_GRID_COLOR, alpha=0.6)
        for s in plan["series"]:
            ys = [float("nan") if v is None else float(v) for v in s["db"]]
            ax.plot(plan["x"], ys, color=s["color"], linewidth=1.4,
                    label=str(s["label"]))
        ax.legend(loc="best", fontsize=8, framealpha=0.9)
        ax.set_xlabel(plan["x_label"], color=_TEXT_COLOR)
        ax.set_ylabel(plan["y_label"], color=_TEXT_COLOR)
        ax.set_title(plan["title"], fontsize=10, color=_TEXT_COLOR)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, metadata={"Software": None})
    return buf.getvalue()


# ─── 4. PNG bytes → 无分号 data URI → drawio image cell style ───────────────


def curve_image_data_uri(png_bytes: Any) -> str:
    """PNG bytes → ``data:image/png,<base64>``（**无 ``;base64``**——drawio
    style ``;`` 分隔符红线，review_annotation 形态 B 同款 + 内建自检）。"""
    if not isinstance(png_bytes, (bytes, bytearray)) or not png_bytes:
        raise ValueError(f"png_bytes 必须是非空 bytes，收到 {type(png_bytes)!r}")
    data = bytes(png_bytes)
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("png_bytes 不是 PNG 头（嵌入面只收本内核渲染产物）")
    uri = "data:image/png," + base64.b64encode(data).decode("ascii")
    if ";base64" in uri:  # 格式红线自检（belt-and-suspenders，先例同款）
        raise ValueError("内部错误：data URI 混入 ;base64（style 分隔符冲突）")
    return uri


def curve_image_style(data_uri: str) -> str:
    """data URI → drawio image cell style 串（annot_sim 层曲线卡内层
    mxCell style；data URI 含分号显式拒绝——``;`` 是 style 分隔符）。"""
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
        raise ValueError(
            f"data_uri 必须以 data:image/ 开头，收到 {data_uri[:40]!r}…")
    if ";" in data_uri:
        raise ValueError(
            "data URI 不得含分号（drawio style 属性分隔符红线——"
            "禁 ;base64 形态）")
    style = _IMAGE_STYLE_TEMPLATE.format(uri=data_uri)
    if ";base64" in style:  # 格式红线自检（belt-and-suspenders）
        raise ValueError("内部错误：style 混入 ;base64（分隔符冲突）")
    return style
