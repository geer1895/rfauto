"""格式速览层（"一屏看懂"，T-Q5：批 1=sNp/KiCad/drawio 三格式 + 共用框架；
批 2=layout 四格式 GDSII/DXF/IPC-2581/ODB++；批 3=ADS .ds + MCP 工具化）。

CADViewer 思想同构（runs/aurora_q/PLAN_DRAFT.md 方向 C）：专有格式 →
Agent 可读的结构化速览 JSON（``stats`` 统计 + ``entities`` 关键实体 +
``summary`` 结构摘要），不渲染不展示，只做"一屏看懂"的确定性读面。

批 3（Q-W9-3 接线席）：``ads_ds``——ADS 数据集 .ds（EEsof dataset 二进制
格式，magic/结构经本机 ADS 2027 安装树 examples 六样例只读探针实测，
探针与结论档 runs/aurora_q/qw93_stats/probe_ds.py）：

- **magic 双形态（实测恒定）**：全量形态=20 字节头 ``EEsof dataset\r\n\x1a
  \xfe\xed\xfa\xce``（15 字节 magic + 0xFEEDFACE 标记）；存根形态=15 字节
  ``HP EEsof data\r\n``（空数据集占位件，momentum 样例实测两例）；二进制
  magic 在全部文本格式之前扫描（gdsii 批 2 先例同序），utf-8 解码对
  ``\xfe`` 等非 UTF-8 字节有损——探测走原字节读面（:func:`_magic_head_bytes`）；
- **头部字段（实测偏移）**：0x20 字节序标记（六样例恒 ``DCBA``，原样透传
  不解释）、0x24 u32 格式版本（实测 3/4）；
- **变量名面（stdlib 可解，实测可提取）**：STRINGDATA 块（每文件恰一处，
  四全量样例实测）内 NUL 结尾变量名序列，首个空段=列表终止——原样透传
  （首串 ``DATAMANAGER_INDEX`` 系统哨兵名不滤除，零语义过滤）；
- **如实边界**：数值数据块（DOUBLEDATA 等）内部布局依赖 DIR/LINK 依赖
  结构，专有未解——速览只承诺头部+变量名面，summary 明示不承诺数值读面。

批 1 三格式（批 3=ADS .ds + MCP 工具化——只增纪律：后续批只加 kind 与
对应 loader/schema 版本键，既有 kind 的速览 JSON 形状冻结不变）：

- ``touchstone``：sNp（.s1p/.s2p/…）——skrf 读取（仓内消费先例
  adapters/interchange.py G16 / touchstone_interop.py），统计含
  端口数/点数/频率单位/z0/逐端口对角 S 参数 dB 极值；
- ``kicad_pcb``：.kicad_pcb——纯文本 s-expression 解析（复用
  adapters/kicad_sch_gen.parse_sexpr，零 pcbnew 依赖——AGENTS 规则 2
  禁 venv import pcbnew），统计含层栈/footprints/tracks/vias/zones/
  nets 计数与板框 bbox（Edge.Cuts 几何直读）；
- ``drawio``：.drawio——复用 core/drawio_xml.read_diagram 读面（仓内
  mxGraph XML 解析单源），统计含页/形状/边/图层/文本元素计数与
  逐页样式首段类型分布。

批 2 layout 四格式（速览共用一个 schema 形状；数据源单源=adapters/
layout_interchange.import_layout——规范化 Layout 全毫米，本层零几何
解析重写，loader 只做 kind→import_layout 薄编排 + 直读计数）：

- ``gdsii``：.gds/.gdsii——gdstk 惰性导入读面；层名=GDS 层号字符串
  （GDSII 不携带层名，import_gdsii 口径）；二进制 magic=HEADER 记录头
  ``\x00\x06\x00\x02``（在全部文本格式之前扫描）；nm 格点 1-ulp 舍入属
  格点差非漂移（速览计数不受影响）；钻孔在 GDSII 无原生载体（按焊盘
  圆承载，读回计为 polygon）；
- ``dxf``：.dxf——DXF R12 子集自包含解析器（POLYLINE/CIRCLE，未知实体
  跳过计数进 annotations）；组码文本形态无可靠 magic，仅扩展名路由
  （无扩展名不猜，如实 None）；loader 预检 ENTITIES 节存在——坏文件
  显式报错而非静默空成功；
- ``ipc2581``：.xml——rev C 子集骨架与 KiCad 8+/10 原生全 schema 双形态
  （adapter 自动识别）；magic=根元素 ``<IPC-2581``（大小写不敏感）；
  .xml 万金油扩展名按扩展名命中即用 + loader 根元素硬校验兜底；
- ``odbpp``：目录形态（matrix/matrix 存在性探测，KiCad 10 目录导出口径）
  与 .tgz 包（stdlib tarfile 解包系统临时目录后按目录读；解包根=唯一直
  接子目录含 matrix/matrix 者，缺席/多义显式报错）；块式 matrix NAME
  大写↔层目录小写、$idx 符号表尺寸=µm 均为 adapter 内口径，速览只消费
  规范化 Layout。

信封契约（service/envelope.py 单源）：成功
``ok_envelope(kind=, schema_version=, framework_version=, path=, stats=,
entities=, summary=)``；失败（未知格式/坏文件/解析失败）一律
``error_envelope``——未知格式显式报错信封，非异常裸抛。

schema 版本纪律：``SCHEMA_VERSIONS`` 每格式独立版本常量——速览 JSON 是
消费者契约，字段只增不改形；``FORMAT_OVERVIEW_VERSION`` 是框架/信封
自身版本（kind 探测与信封形状变更时升位）。

确定性（验收钉）：同一文件两跑速览 JSON 逐字节同——
:func:`overview_format_json` 是规范序列化单源（键序=构造序、
``sort_keys=False``、UTF-8、``allow_nan=False``、尾部换行）；统计数字
全部来自文件内容直读计数（铁律 7），仅两类声明式聚合：min/max 极值
（逐端口 S 参数 dB、板框 bbox、频率范围、layout 四格式 bbox——
canonical items 坐标直读，path/polygon 顶点与 circle/via 圆心，**不含
半径外扩**，零算术派生）与分组计数（逐层 track 分布/逐页样式首段
分布/layout per-layer 逐类型计数）——docstring 此处声明，别无算术派生。

解析边界（如实声明）：
- touchstone 走 skrf，skrf 按 .sNp 扩展名推断端口秩（#248 仓内教训）
  ——端口数与扩展名不符的文件如实报错信封，不静默猜测（#316 兜底
  方向选"多报"）；
- kicad_pcb 解析面向 KiCad 7+ 文本 s-expression（fixtures/真机板同
  口径）；未识别的顶层节点跳过计数，不猜语义；
- drawio 复用 read_diagram 的 v1 边界（未压缩 mxfile；压缩页显式
  DrawioReadError → 错误信封）；
- layout 四格式（批 2）：adapter 的 skip/注记计数（dxf_skipped_entities/
  ipc2581_skipped/odbpp_skipped/#ANN 等）经 ``annotations`` 原文透传进
  stats（跳过如实计数不凑零）；units 恒 MM（adapter 规范化口径）；
  ODB++ .tgz 解包走系统临时目录（tarfile filter="data"，用毕即清），
  runs/ 湖零写入。
"""

from __future__ import annotations

import json
import re
import struct
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import skrf

from rfauto.adapters.kicad_sch_gen import parse_sexpr
from rfauto.adapters.layout_interchange import (
    LayoutCircle,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
    import_layout,
)
from rfauto.core.drawio_xml import read_diagram
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "FORMAT_OVERVIEW_VERSION",
    "SCHEMA_VERSIONS",
    "SUPPORTED_KINDS",
    "detect_format_kind",
    "overview_format",
    "overview_format_json",
]

#: 框架/信封自身版本（kind 探测规则与信封形状变更时升位；批 1 首版 1.0，
#: 批 2 layout 四格式+目录形态/二进制 magic 探测规则扩位 → 1.1；
#: 批 3 ads_ds kind+EEsof 二进制 magic 探测扩位 → 1.2）。
FORMAT_OVERVIEW_VERSION = "1.2"

#: 每格式速览 schema 独立版本（消费者契约；字段只增不改形——只增纪律）。
SCHEMA_VERSIONS: dict[str, str] = {
    "touchstone": "1.0",
    "kicad_pcb": "1.0",
    "drawio": "1.0",
    "gdsii": "1.0",
    "dxf": "1.0",
    "ipc2581": "1.0",
    "odbpp": "1.0",
    "ads_ds": "1.0",
}

#: 已注册 kind（批 3：ads_ds 已入）。
SUPPORTED_KINDS: tuple[str, ...] = tuple(SCHEMA_VERSIONS)

#: touchstone 扩展名（.s1p/.s2p/…/.s99p，大小写不敏感；.sNp 家族口径）。
_TOUCHSTONE_SUFFIX_RE = re.compile(r"^\.s\d+p$", re.IGNORECASE)
_KICAD_PCB_SUFFIX = ".kicad_pcb"
_DRAWIO_SUFFIX = ".drawio"
_GDSII_SUFFIXES = (".gds", ".gdsii")
_DXF_SUFFIX = ".dxf"
_IPC2581_SUFFIX = ".xml"  # 万金油扩展名：命中即用，loader 根元素硬校验兜底
_ODBPP_TGZ_SUFFIX = ".tgz"  # 目录形态不经扩展名（matrix/matrix 存在性探测）
_ADS_DS_SUFFIX = ".ds"

#: GDSII 二进制 magic：HEADER 记录头（长度 0x0006 + rectype 0x00 + int2 0x02，
#: GDSII 规范恒定首记录）——文本格式之前扫描。
_GDSII_MAGIC = "\x00\x06\x00\x02"

#: ADS .ds 二进制 magic 双形态（EEsof dataset 格式，只读侦察实测：
#: 本机 ADS 2027 安装树 examples 六样例，探针存 aurora_q 侦察档）。
#: 全量形态=15 字节 magic + 0xFEEDFACE 标记（20 字节头）；存根形态=15 字节
#: ``HP EEsof data\r\n``（空数据集占位件）。均在文本格式之前扫描。
_ADS_DS_FULL_MAGIC = b"EEsof dataset\r\n\x1a\xfe\xed\xfa\xce"
_ADS_DS_STUB_MAGIC = b"HP EEsof data\r\n"

#: magic 头探测读取窗口 [字节]。
_MAGIC_HEAD_BYTES = 8192

#: 速览 JSON 浮点定标（逐字节确定性：固定小数位而非 repr 长尾）。
_OVERVIEW_ROUND_DIGITS = 6


def _round(value: Any) -> Any:
    """浮点定标（确定性口径单一入口）；非浮点原样透传。"""
    if isinstance(value, float):
        return round(value, _OVERVIEW_ROUND_DIGITS)
    return value


def _r(value: Any) -> float | None:
    """float 化失败回 None（不猜不炸——坏数值如实缺席）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# kind 探测
# ---------------------------------------------------------------------------

def _suffix_to_kind(suffix: str) -> str | None:
    if _TOUCHSTONE_SUFFIX_RE.match(suffix):
        return "touchstone"
    lowered = suffix.lower()
    if lowered == _KICAD_PCB_SUFFIX:
        return "kicad_pcb"
    if lowered == _DRAWIO_SUFFIX:
        return "drawio"
    if lowered in _GDSII_SUFFIXES:
        return "gdsii"
    if lowered == _DXF_SUFFIX:
        return "dxf"
    if lowered == _IPC2581_SUFFIX:
        return "ipc2581"
    if lowered == _ODBPP_TGZ_SUFFIX:
        return "odbpp"
    if lowered == _ADS_DS_SUFFIX:
        return "ads_ds"
    return None


def _magic_head(path: Path) -> str:
    """前 _MAGIC_HEAD_BYTES 字节 → 文本（utf-8 宽松解码，仅探测用）。"""
    with path.open("rb") as fh:
        head = fh.read(_MAGIC_HEAD_BYTES)
    return head.decode("utf-8", errors="replace")


def _magic_head_bytes(path: Path) -> bytes:
    """前 _MAGIC_HEAD_BYTES 字节原文（二进制 magic 探测用）。

    utf-8 解码有损（``\\xfe`` 等非 UTF-8 字节经 errors=replace 不可复原），
    EEsof dataset 头含此类字节——ADS .ds 探测必须走原字节面（批 3）。
    """
    with path.open("rb") as fh:
        return fh.read(_MAGIC_HEAD_BYTES)


def _magic_matches(kind: str, head: str) -> bool:
    """magic 头判定（扩展名缺失/存疑时的第二证据；口径从宽——解析器
    会做硬校验并出错误信封，探测只负责路由）。

    批 2 边界：gdsii 是二进制 magic（:data:`_GDSII_MAGIC`，在
    :func:`detect_format_kind` 里先于文本格式扫描，不经本函数）；odbpp
    无文本 magic（目录形态走 matrix/matrix 存在性、.tgz 走扩展名路由）。
    """
    stripped = head.lstrip("\ufeff \t\r\n")
    if kind == "kicad_pcb":
        return "(kicad_pcb" in stripped
    if kind == "drawio":
        return "<mxfile" in stripped
    if kind == "ipc2581":
        return "<ipc-2581" in stripped.lower()
    if kind == "touchstone":
        first = next((ln for ln in stripped.splitlines() if ln.strip()), "")
        return first.startswith(("!", "#"))
    return False


def detect_format_kind(path: str | Path) -> str | None:
    """目录形态/扩展名 + magic 头 kind 探测（不读全文件）。

    返回 kind 串或 None（无法判定）。目录形态：唯一目录 kind=odbpp
    （matrix/matrix 存在性探测，KiCad 10 目录导出口径）。文件扩展名命中
    即用（后续 loader 硬校验兜底）；未命中时先扫二进制 magic（ADS .ds
    EEsof 头 → GDSII HEADER 记录头，批 3/gdsii 先例同序——二进制具体
    格式优先），再按 kicad_pcb → drawio → ipc2581 → touchstone 顺序扫
    文本 magic（touchstone 的 ``!``/``#`` 首行太宽泛排最后）。
    """
    p = Path(path)  # PathLike 入参第一行收敛（#140）
    if p.is_dir():
        return "odbpp" if (p / "matrix" / "matrix").is_file() else None
    kind = _suffix_to_kind(p.suffix)
    if kind is not None:
        return kind
    try:
        raw_head = _magic_head_bytes(p)
    except OSError:
        return None
    if (raw_head.startswith(_ADS_DS_FULL_MAGIC)
            or raw_head.startswith(_ADS_DS_STUB_MAGIC)):
        return "ads_ds"
    head = raw_head.decode("utf-8", errors="replace")
    if head.startswith(_GDSII_MAGIC):
        return "gdsii"
    for candidate in ("kicad_pcb", "drawio", "ipc2581", "touchstone"):
        if _magic_matches(candidate, head):
            return candidate
    return None


# ---------------------------------------------------------------------------
# loader 1：touchstone（skrf 读面）
# ---------------------------------------------------------------------------

def _parse_touchstone_header(text: str) -> dict[str, Any]:
    """注释行数 / 选项行原文 / [Version] 关键字值（文件文本直读）。"""
    comment_lines = 0
    option_line: str | None = None
    version: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("!"):
            comment_lines += 1
            continue
        if option_line is None and line.startswith("#"):
            option_line = line
        if version is None and "[Version]" in line:
            # TS2 关键字行形态 "[Version] 2.1"——关键字后首个 token 原样。
            tail = line.split("[Version]", 1)[1].split()
            if tail:
                version = tail[0]
    return {
        "comment_lines": comment_lines,
        "option_line": option_line,
        "version": version,
    }


def _load_touchstone(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """touchstone → (stats, entities, summary)。dB 极值=min/max 声明式聚合。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    header = _parse_touchstone_header(text)
    ntw = skrf.Network(str(path))
    n_points, n_ports = int(ntw.s.shape[0]), int(ntw.s.shape[1])

    per_port: list[dict[str, Any]] = []
    n_nonfinite = 0
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(n_ports):
            db = 20.0 * np.log10(np.abs(ntw.s[:, i, i]))
            finite = db[np.isfinite(db)]
            n_nonfinite += int(db.size - finite.size)
            per_port.append({
                "port": i,
                "label": f"S{i + 1}{i + 1}",
                "min_db": _round(float(finite.min())) if finite.size else None,
                "max_db": _round(float(finite.max())) if finite.size else None,
            })

    # z0：逐端口取首频点 [re, im]（直读采样，声明式——z0 随频变的文件以
    # 首点为速览口径，全数组不进速览）。
    z0_first = ntw.z0[0]
    z0_ohm = [[_round(float(v.real)), _round(float(v.imag))] for v in z0_first]
    port_names = [str(n) for n in (ntw.port_names or [])]

    stats = {
        "n_ports": n_ports,
        "n_points": n_points,
        "frequency_unit": str(ntw.frequency.unit),
        "f_min_hz": _round(float(np.min(ntw.f))),
        "f_max_hz": _round(float(np.max(ntw.f))),
        "z0_first_point_ohm": z0_ohm,
        "comment_lines": header["comment_lines"],
        "option_line": header["option_line"],
        "version": header["version"],
        "n_nonfinite_db": n_nonfinite,
    }
    entities = {
        "port_names": port_names,
        "per_port_s_ii_db": per_port,
    }
    summary = (
        f"{n_ports} 端口 / {n_points} 点 / 单位 {stats['frequency_unit']} / "
        f"注释 {header['comment_lines']} 行 / "
        f"版本 {header['version'] if header['version'] else '1.x（无 [Version] 关键字）'}"
    )
    return stats, entities, summary


# ---------------------------------------------------------------------------
# loader 2：kicad_pcb（纯文本 s-expression，零 pcbnew 依赖）
# ---------------------------------------------------------------------------

def _node(node: list, tag: str) -> list | None:
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == tag:
            return child
    return None


def _nodes(node: list, tag: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def _token(node: list | None, idx: int) -> str | None:
    if node is None or len(node) <= idx:
        return None
    return str(node[idx])


def _prop_value(node: list, name: str) -> str:
    for p in _nodes(node, "property"):
        if len(p) > 2 and p[1] == name:
            return str(p[2])
    return ""


def _layer_entries(layers_node: list) -> list[dict[str, Any]]:
    """(layers ...) 直系层条目原文直读。

    注意 layers 条目的 token 布局与其余节点不同：首 token 是**数字 id**
    而非节点名——``(0 "F.Cu" signal)`` / ``(36 "B.SilkS" user "B.Silkscreen")``。
    """
    out: list[dict[str, Any]] = []
    for child in layers_node[1:]:
        if not isinstance(child, list) or len(child) < 2:
            continue
        out.append({
            "id": str(child[0]),
            "name": str(child[1]),
            "type": str(child[2]) if len(child) > 2 else None,
        })
    return out


def _load_kicad_pcb(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """kicad_pcb → (stats, entities, summary)。bbox=Edge.Cuts 坐标
    min/max 声明式聚合（直读 start/end/center/xy 原文，零算术派生）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    top = parse_sexpr(text)
    if (len(top) != 1 or not isinstance(top[0], list) or not top[0]
            or top[0][0] != "kicad_pcb"):
        raise ValueError("根表达式不是 (kicad_pcb ...)——文件损坏或非 .kicad_pcb")
    root = top[0]

    layers: list[dict[str, Any]] = []
    layers_node = _node(root, "layers")
    if layers_node is not None:
        layers = _layer_entries(layers_node)

    stackup_layers: list[dict[str, Any]] = []
    stackup_node = _node(root, "stackup")
    if stackup_node is not None:
        for sl in _nodes(stackup_node, "layer"):
            stackup_layers.append({
                "name": _token(sl, 1),
                "type": _token(_node(sl, "type"), 1),
                "thickness_mm": _r(_token(_node(sl, "thickness"), 1)),
                "epsilon_r": _r(_token(_node(sl, "epsilon_r"), 1)),
                "loss_tangent": _r(_token(_node(sl, "loss_tangent"), 1)),
            })

    net_names: list[str] = []
    for net in _nodes(root, "net"):
        name = _token(net, 2)
        if name:
            net_names.append(name)

    footprints: list[dict[str, Any]] = []
    for fp in _nodes(root, "footprint"):
        at = _node(fp, "at")
        footprints.append({
            "lib_id": _token(fp, 1),
            "reference": _prop_value(fp, "Reference"),
            "value": _prop_value(fp, "Value"),
            "at_mm": [x for x in (_r(_token(at, 1)), _r(_token(at, 2)))
                      if x is not None],
            "n_pads": len(_nodes(fp, "pad")),
        })

    tracks = _nodes(root, "segment")
    track_by_layer = Counter(
        _token(_node(seg, "layer"), 1) or "" for seg in tracks)

    vias = _nodes(root, "via")
    zones = _nodes(root, "zone")

    edge_pts: list[tuple[float, float]] = []
    for graphic in root[1:]:
        if not isinstance(graphic, list) or not graphic:
            continue
        if _token(_node(graphic, "layer"), 1) != "Edge.Cuts":
            continue
        for tag in ("start", "end", "center"):
            pt = _node(graphic, tag)
            x, y = _r(_token(pt, 1)), _r(_token(pt, 2))
            if x is not None and y is not None:
                edge_pts.append((x, y))
        pts_node = _node(graphic, "pts")
        if pts_node is not None:
            for xy in _nodes(pts_node, "xy"):
                x, y = _r(_token(xy, 1)), _r(_token(xy, 2))
                if x is not None and y is not None:
                    edge_pts.append((x, y))
    bbox = None
    if edge_pts:
        xs = [pt[0] for pt in edge_pts]
        ys = [pt[1] for pt in edge_pts]
        bbox = {
            "min_mm": [_round(min(xs)), _round(min(ys))],
            "max_mm": [_round(max(xs)), _round(max(ys))],
            "n_points": len(edge_pts),
        }

    stats = {
        "n_layers": len(layers),
        "n_stackup_layers": len(stackup_layers),
        "n_nets": len(net_names),
        "n_footprints": len(footprints),
        "n_tracks": len(tracks),
        "n_vias": len(vias),
        "n_zones": len(zones),
        "n_edge_cuts_points": len(edge_pts),
        "track_by_layer": dict(sorted(track_by_layer.items())),
        "board_bbox_mm": bbox,
    }
    entities = {
        "layers": layers,
        "stackup_layers": stackup_layers,
        "net_names": net_names,
        "footprints": footprints,
    }
    summary = (
        f"footprints {len(footprints)} / tracks {len(tracks)} / "
        f"vias {len(vias)} / zones {len(zones)} / nets {len(net_names)} / "
        f"层表 {len(layers)} 项"
    )
    return stats, entities, summary


# ---------------------------------------------------------------------------
# loader 3：drawio（复用 core/drawio_xml 读面）
# ---------------------------------------------------------------------------

def _style_head(style: Any) -> str:
    """样式首段 token 原样（``;`` 切分首项；None/空 → ""）。"""
    if not isinstance(style, str) or not style:
        return ""
    return style.split(";", 1)[0]


def _load_drawio(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """drawio → (stats, entities, summary)。逐页样式首段分布=分组计数。"""
    doc = read_diagram(path)
    pages: list[dict[str, Any]] = []
    total_v = total_e = total_layers = total_text = 0
    for page in doc["pages"]:
        n_v, n_e = len(page["vertices"]), len(page["edges"])
        layers = page["layers"]
        n_layers = len(layers)
        text_count = sum(
            1 for cell in [*page["vertices"], *page["edges"]]
            if str(cell.get("value") or "").strip())
        style_dist = Counter(
            _style_head(v.get("style")) for v in page["vertices"])
        pages.append({
            "diagram_id": page["diagram_id"],
            "diagram_name": page["diagram_name"],
            "n_vertices": n_v,
            "n_edges": n_e,
            "n_layers": n_layers,
            "layer_names": [ln.get("name") or "" for ln in layers],
            "text_value_count": text_count,
            "style_head_distribution": dict(sorted(style_dist.items())),
        })
        total_v += n_v
        total_e += n_e
        total_layers += n_layers
        total_text += text_count

    stats = {
        "n_pages": int(doc["n_pages"]),
        "n_vertices": total_v,
        "n_edges": total_e,
        "n_layers": total_layers,
        "n_text_values": total_text,
    }
    entities = {"pages": pages}
    summary = (
        f"{stats['n_pages']} 页 / shapes {total_v}+边 {total_e} / "
        f"图层 {total_layers} / 文本 {total_text}"
    )
    return stats, entities, summary


# ---------------------------------------------------------------------------
# loader 4-7（批 2）：layout 四格式（gdsii/dxf/ipc2581/odbpp）
#
# 共用 schema（速览形状冻结口径）：stats=层数/逐类型直读计数/per-layer
# 分组计数/bbox（canonical items 坐标 min/max 声明聚合）/units=MM/
# annotations 原文透传；entities=层名清单（gdsii 层号=名字符串口径）+
# per-layer 计数分布；数据源单源=adapters.layout_interchange.import_layout
# （规范化 Layout 全毫米），本层零几何解析重写。
# ---------------------------------------------------------------------------

_LAYOUT_TYPE_KEYS = ("path", "polygon", "circle", "via")


def _layout_item_type(item: Any) -> str:
    if isinstance(item, LayoutPath):
        return "path"
    if isinstance(item, LayoutPolygon):
        return "polygon"
    if isinstance(item, LayoutCircle):
        return "circle"
    if isinstance(item, LayoutVia):
        return "via"
    raise TypeError(f"未知版图项类型: {type(item).__name__}")  # pragma: no cover


def _layout_item_coords(item: Any) -> tuple[tuple[float, float], ...]:
    """bbox 坐标直读口径：path/polygon 取顶点、circle/via 取圆心（不含
    半径外扩——半径折叠属算术派生，速览零派生纪律）。"""
    if isinstance(item, (LayoutPath, LayoutPolygon)):
        return tuple(item.points)
    if isinstance(item, LayoutCircle):
        return (item.center,)
    return (item.position,)  # LayoutVia


def _load_layout_generic(path: Path, fmt: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """layout 四格式共用读面：import_layout 薄编排 + 直读计数。

    bbox=min/max 声明式聚合（坐标直读，n_points=消费坐标点数）；per-layer
    逐类型计数=分组计数；annotations（adapter skip/注记计数）原文透传。
    """
    layout = import_layout(path, fmt)
    n_by_type = dict.fromkeys(_LAYOUT_TYPE_KEYS, 0)
    per_layer: dict[str, dict[str, int]] = {}
    xs: list[float] = []
    ys: list[float] = []
    n_points = 0
    for item in layout.items:
        type_key = _layout_item_type(item)
        n_by_type[type_key] += 1
        layer_name = item.pad_layer if isinstance(item, LayoutVia) else item.layer
        bucket = per_layer.setdefault(layer_name, dict.fromkeys(_LAYOUT_TYPE_KEYS, 0))
        bucket[type_key] += 1
        coords = _layout_item_coords(item)
        for x, y in coords:
            xs.append(x)
            ys.append(y)
        n_points += len(coords)

    bbox = None
    if xs:
        bbox = {
            "min_mm": [_round(min(xs)), _round(min(ys))],
            "max_mm": [_round(max(xs)), _round(max(ys))],
            "n_points": n_points,
        }

    per_layer_type_counts = {
        name: dict(sorted(bucket.items())) for name, bucket in sorted(per_layer.items())
    }
    stats = {
        "units": "MM",
        "n_layers": len(layout.layers),
        "n_items": len(layout.items),
        "n_paths": n_by_type["path"],
        "n_polygons": n_by_type["polygon"],
        "n_circles": n_by_type["circle"],
        "n_vias": n_by_type["via"],
        "per_layer_type_counts": per_layer_type_counts,
        "bbox_mm": bbox,
        "annotations": dict(sorted(layout.annotations.items())),
    }
    entities = {
        "layout_name": layout.name,
        "layers": [
            {
                "name": layer.name,
                "gds_layer": layer.gds_layer,
                "gds_datatype": layer.gds_datatype,
            }
            for layer in layout.layers
        ],
        "per_layer_distribution": {
            name: sum(bucket.values()) for name, bucket in sorted(per_layer.items())
        },
    }
    if bbox:
        bbox_txt = (
            f"bbox [{bbox['min_mm'][0]}, {bbox['min_mm'][1]}]-"
            f"[{bbox['max_mm'][0]}, {bbox['max_mm'][1]}] mm"
        )
    else:
        bbox_txt = "bbox 无几何"
    summary = (
        f"{stats['n_layers']} 层 / {stats['n_items']} 项"
        f"（path {stats['n_paths']}+polygon {stats['n_polygons']}"
        f"+circle {stats['n_circles']}+via {stats['n_vias']}）/ {bbox_txt}"
    )
    return stats, entities, summary


def _load_gdsii(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """gdsii → 速览。预检 HEADER 记录头（坏文件显式报错，不让 gdstk 消费
    任意文本/非 GDS 二进制）；层名=GDS 层号字符串口径（adapter 约定）。"""
    if not _magic_head(path).startswith(_GDSII_MAGIC):
        raise ValueError(f"非 GDSII 文件（缺 HEADER 记录头 00 06 00 02 字节序）: {path}")
    return _load_layout_generic(path, "gdsii")


def _load_dxf(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """dxf → 速览。预检 ENTITIES 节存在（本读面只承诺 DXF R12 子集——
    无 ENTITIES 的文件即便格式合法也零几何可读，显式报错不静默空成功）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    if "ENTITIES" not in text.upper():
        raise ValueError(f"DXF 无 ENTITIES 节——非本读面承诺的 DXF R12 子集口径: {path}")
    return _load_layout_generic(path, "dxf")


def _load_ipc2581(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """ipc2581 → 速览（子集骨架/KiCad 原生全 schema 双形态由 adapter 识别；
    根元素硬校验兜底 .xml 万金油扩展名的误路由）。"""
    return _load_layout_generic(path, "ipc2581")


def _odbpp_archive_root(extracted: Path) -> Path:
    """tgz 解包根定位：解包目录本身或唯一直接子目录含 matrix/matrix 者。

    多义（≥2 命中）与缺席（0 命中）显式报错——不猜归哪层。
    """
    candidates = [extracted, *sorted(p for p in extracted.iterdir() if p.is_dir())]
    hits = [c for c in candidates if (c / "matrix" / "matrix").is_file()]
    if len(hits) == 1:
        return hits[0]
    raise FileNotFoundError(
        f"tgz 解包后未定位到唯一 matrix/matrix 根（命中 {len(hits)} 个候选）: {extracted}")


def _load_odbpp(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """odbpp → 速览。目录形态直读；.tgz 包（KiCad ODB++ 打包惯例）解包
    系统临时目录（stdlib tarfile，filter="data" 防路径逃逸，用毕即清——
    runs/ 湖零写入）后按目录读；其余文件形态交 import_layout 如实报错。"""
    if path.is_dir():
        return _load_layout_generic(path, "odbpp")
    if tarfile.is_tarfile(path):
        with tempfile.TemporaryDirectory() as tmp_dir:
            extracted = Path(tmp_dir)
            with tarfile.open(path) as tar:
                tar.extractall(extracted, filter="data")
            return _load_layout_generic(_odbpp_archive_root(extracted), "odbpp")
    return _load_layout_generic(path, "odbpp")


# ---------------------------------------------------------------------------
# loader 8（批 3）：ADS .ds（EEsof dataset 二进制格式）
# ---------------------------------------------------------------------------

def _ads_ds_string_names(raw: bytes) -> list[str]:
    """STRINGDATA 块变量名序列（侦察实测口径：块标记后直接跟 NUL 结尾
    字符串，首个空段=列表终止；原样透传零语义过滤）。"""
    start = raw.find(b"STRINGDATA\x00")
    if start < 0:
        return []
    names: list[str] = []
    for seg in raw[start + len(b"STRINGDATA\x00"):].split(b"\x00"):
        if not seg:
            break  # 首个空段=列表终止（实测 NUL 填充区）
        names.append(seg.decode("utf-8", errors="replace"))
    return names


def _load_ads_ds(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """ads_ds → 速览。EEsof dataset 头硬校验（坏文件显式报错，非 EEsof
    冒充 .ds 不静默）；读面承诺=magic 形态/字节序标记/格式版本/STRINGDATA
    变量名（侦察实测 stdlib 可解边界），数值数据块专有布局未解——summary
    明示，速览不承诺数值读面。"""
    raw = path.read_bytes()
    if raw.startswith(_ADS_DS_FULL_MAGIC):
        if len(raw) < 0x28:
            raise ValueError(f"EEsof dataset 头不完整（<40 字节）: {path}")
        marker = raw[0x20:0x24].decode("ascii", errors="replace")
        version = int(struct.unpack_from("<I", raw, 0x24)[0])
        names = _ads_ds_string_names(raw)
        magic_form = "full"
        summary = (
            f"EEsof dataset v{version} / 字节序标记 {marker} / "
            f"变量 {len(names)} 个 / 数值数据块专有布局未解"
            "（速览只承诺头部+变量名面）"
        )
    elif raw.startswith(_ADS_DS_STUB_MAGIC):
        marker = None
        version = None
        names = []
        magic_form = "stub"
        summary = "EEsof 存根数据集（空数据集占位件）/ 变量 0 个"
    else:
        raise ValueError(f"非 EEsof dataset 文件（缺 EEsof dataset 头）: {path}")

    stats = {
        "magic_form": magic_form,
        "byte_order_marker": marker,
        "format_version": version,
        "file_size_bytes": len(raw),
        "n_variables": len(names),
    }
    entities = {"variable_names": names}
    return stats, entities, summary


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

_LOADERS = {
    "touchstone": _load_touchstone,
    "kicad_pcb": _load_kicad_pcb,
    "drawio": _load_drawio,
    "gdsii": _load_gdsii,
    "dxf": _load_dxf,
    "ipc2581": _load_ipc2581,
    "odbpp": _load_odbpp,
    "ads_ds": _load_ads_ds,
}


def overview_format(path: str | Path, kind: str | None = None) -> dict[str, Any]:
    """格式文件 → 速览信封（统一入口；失败一律错误信封非裸抛）。

    Args:
        path: 格式文件/目录路径（.sNp / .kicad_pcb / .drawio / .gds / .dxf /
            .xml / .tgz / ODB++ 目录形态 / .ds）。
        kind: 显式 kind（跳过探测；须在 :data:`SUPPORTED_KINDS` 内）。
            None=自动探测（目录形态/扩展名/magic 头）。

    Returns:
        成功 ``ok_envelope``：
        ``{"ok": True, "kind": str, "schema_version": str,
        "framework_version": str, "path": str, "stats": dict,
        "entities": dict, "summary": str}``；
        失败 ``error_envelope``（未知 kind/未知格式/解析失败/文件不存在），
        ``kind`` 在已判定时随信封给出。
    """
    p = Path(path)  # PathLike 入参第一行收敛（#140）
    detected: str | None = None
    if kind is not None:
        if kind not in SUPPORTED_KINDS:
            return error_envelope(
                f"未知 kind：{kind!r}（已注册={list(SUPPORTED_KINDS)}）",
                kind=None, path=str(p),
                framework_version=FORMAT_OVERVIEW_VERSION)
        detected = kind
    elif not p.exists():
        return error_envelope(
            f"文件不存在：{p}", kind=None, path=str(p),
            framework_version=FORMAT_OVERVIEW_VERSION)
    else:
        detected = detect_format_kind(p)
        if detected is None:
            return error_envelope(
                f"未知格式：扩展名 {p.suffix!r} 无映射且 magic 头未命中"
                f"已知 kind {list(SUPPORTED_KINDS)}",
                kind=None, path=str(p),
                framework_version=FORMAT_OVERVIEW_VERSION)

    try:
        stats, entities, summary = _LOADERS[detected](p)
    except Exception as exc:  # 读面契约：一切解析失败走错误信封，非异常裸抛
        return error_envelope(
            f"{detected} 解析失败：{type(exc).__name__}: {exc}",
            kind=detected, path=str(p),
            framework_version=FORMAT_OVERVIEW_VERSION)

    return ok_envelope(
        kind=detected,
        schema_version=SCHEMA_VERSIONS[detected],
        framework_version=FORMAT_OVERVIEW_VERSION,
        path=str(p),
        stats=stats,
        entities=entities,
        summary=summary,
    )


def overview_format_json(
    path: str | Path,
    kind: str | None = None,
    *,
    indent: int | None = 2,
) -> str:
    """速览 JSON 规范序列化单源（确定性验收的锚点入口）。

    键序=构造序（sort_keys=False）、UTF-8、``allow_nan=False``
    （非有限浮点漏网即抛——速览面不落 ``NaN/Infinity`` 尾巴）、尾部换行。
    同一文件两调用逐字节同。
    """
    env = overview_format(path, kind=kind)
    return json.dumps(
        env, ensure_ascii=False, indent=indent, allow_nan=False) + "\n"
