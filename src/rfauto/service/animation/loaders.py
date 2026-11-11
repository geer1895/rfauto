"""动图数据源加载契约（T-Q3 批 1）——run 湖/仿真产物/锚点 JSON 单源。

数据源纪律（红线）的加载面落地：**全部数字只从确定性数据源读出**，缺
数据→ :class:`AnimationDataError` 显式异常（带指引文案），禁静默画空图、
禁示意数据兜底。加载零算术改写——只做解析与类型归一（str→float/complex）。

四源契约（spec.source.kind 词表）：

- :func:`load_sparams_csv` —— run 湖 ``sparams.csv``（表头
  ``freq_hz,re_S11,im_S11,re_S21,im_S21,...``，openEMS/HFSS 导出惯例）；
  ``columns`` 选 S 参数名（缺省全部，sorted 序）；
- :func:`load_snip` —— Touchstone sNp（skrf 读入；懒 import，sNp 缺席
  不影响其他源）；``columns`` 同上，``ports``（1 基）限制端口对；
- :func:`load_trials` —— run 目录（``trials/trial_*.json`` sorted）/
  单 trial JSON/JSON 数组；每条须含 ``trial_number``/``params``/``cost``
  （rfauto trial 落盘惯例，cost 缺失=显式报错不猜代理量）；
- :func:`load_anchor_json` —— 锚点/导出 JSON 原始 dict（渲染器按图型
  提取：smith=``{"points":[{"re","im"},...]}``、fit_compare=
  ``{"series":{"x","y"}}``；提取违约同样 AnimationDataError）；
- :func:`load_field_frames`（批 2 Q-W2-2）—— 场帧序列（field_dump）：
  单文件 ``{"axes":{...},"frames":[{"meta":{...},"values":[[...],...]}]}``
  或目录（``frame_*.json`` sorted 逐帧 + 可选 ``axes.json``）；
- :func:`load_layout_json`（批 2 Q-W2-2）—— 图元坐标序列（layout_json）：
  ``{"layers":[{"name":...,"primitives":[{"shape","x","y","w","h"},...]}]}``；
- :func:`load_cascade_json`（批 3 Q-W2-3）—— 级联级表（cascade_json）：
  ``{"stages":[{"name"?,"gain_db","nf_db"},...]}``——对齐
  core/cascade_service 级表语义（gain_db/nf_db 同名同义）；
- :func:`load_nf2ff_cut`（批 3 Q-W2-3）—— 方向图切面序列（nf2ff_cut）：
  ``{"cuts":[{"theta_deg":[...],"db"|"pattern_db":[...],"freq_hz"?/
  "phi_deg"?/"meta"?},...]}``——``pattern_db`` 键名对齐 nf2ff_service
  farfield_view 既有产物，``db`` 为任务书最小约定（恰一键）；
- :func:`load_chain_json`（批 3 Q-W2-3）—— 链路框图（chain_json）：
  ``{"nodes":[{"id","label"?,"gain_db"?},...],"edges":[{"from","to"},...]}``
  ——对齐 cascade/active_chain 节点语义（gain_db 可选）；
- :func:`load_symbols_json`（批 4 Q-W2-4）—— 数字调制符号序列（symbols_json）：
  单云 ``{"symbols":[[i,q],...]}`` 或帧序列 ``{"frames":[{"symbols":
  [[i,q],...]},...]}``（恰一形态；侦察 si_channel_service 无既有符号产物，
  按任务书最小 JSON 约定）；
- :func:`load_budget_json`（批 4 Q-W2-4）—— 链路预算级表（budget_json）：
  ``{"stages":[{"name"?,"value_db"},...]}``——与 cascade_json 同构但语义=
  预算扣减（value_db 为逐级增量，负值=损耗；侦察 adc_budget_service/
  am_loss_budget 无 stages+value_db 既有产物，按任务书最小 JSON 约定）；
- :func:`load_cfc_state`（Q-R3R 遗留清偿席）—— CfC 隐态轨迹（cfc_state）：
  ``{"hidden":[[H 值]/step,...],"time"?:[...],"hidden_dim"?}``（产出面=
  lnn_cfc 隐态导出链；本节新名不进 ``__all__``——公开面快照冻结本席，
  收编留后续 --generate 重钉，见节内注记）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rfauto.service.animation.spec import AnimationError

__all__ = [
    "AnimationDataError",
    "BudgetDoc",
    "BudgetStage",
    "CascadeDoc",
    "CascadeStage",
    "ChainDoc",
    "ChainEdge",
    "ChainNode",
    "FieldFrame",
    "FieldFrames",
    "LayoutDoc",
    "LayoutLayer",
    "PatternCut",
    "PatternCutSeries",
    "Primitive",
    "SparamsTable",
    "SymbolFrame",
    "SymbolsDoc",
    "TrialRecord",
    "load_anchor_json",
    "load_budget_json",
    "load_cascade_json",
    "load_chain_json",
    "load_field_frames",
    "load_layout_json",
    "load_nf2ff_cut",
    "load_snip",
    "load_sparams_csv",
    "load_symbols_json",
    "load_trials",
]

_RE_PREFIX = "re_"
_IM_PREFIX = "im_"


class AnimationDataError(AnimationError):
    """数据源缺失/残缺/形状不合——显式报错（禁静默画空图、禁示意数据）。"""


@dataclass(frozen=True)
class SparamsTable:
    """S 参数表（freq_hz 与每列 complex 等长；columns sorted 序）。"""

    freq_hz: tuple[float, ...]
    series: dict[str, tuple[complex, ...]]
    source_path: str
    columns: tuple[str, ...] = field(default=())

    @property
    def n_points(self) -> int:
        return len(self.freq_hz)


def _require_file(path: Any, kind: str) -> Path:
    """PathLike 收敛+存在性守卫（#140 第一行收敛惯例；缺文件带指引报错）。"""
    p = Path(path)
    if not p.is_file():
        raise AnimationDataError(
            f"{kind} 数据源文件不存在：{p}——请核对 spec.source.path；"
            "数据源限 run 湖/仿真产物/锚点 JSON，禁示意数据兜底")
    return p


def _to_float(value: Any, where: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise AnimationDataError(f"{where} 不是合法数值：{value!r}") from exc
    if not math.isfinite(v):
        raise AnimationDataError(f"{where} 出现非有限数值 {value!r}——残缺数据"
                                 "显式拒绝（修数据源或裁剪 columns，不静默画）")
    return v


def _sparam_columns_from_header(header: list[str]) -> list[str]:
    """表头 → S 参数名列表（``re_XX``/``im_XX`` 成对出现才算，sorted 序）。"""
    re_cols = {h[len(_RE_PREFIX):] for h in header if h.startswith(_RE_PREFIX)}
    im_cols = {h[len(_IM_PREFIX):] for h in header if h.startswith(_IM_PREFIX)}
    return sorted(re_cols & im_cols)


def load_sparams_csv(path: Any, columns: list[str] | None = None) -> SparamsTable:
    """读 run 湖 ``sparams.csv`` → :class:`SparamsTable`（零算术改写）。

    Args:
        path: CSV 路径（run 湖产物；缺文件→ AnimationDataError 带指引）。
        columns: S 参数名列表（如 ``["S11","S21"]``；None=全部）。

    Raises:
        AnimationDataError: 文件缺失/表头缺 freq_hz/列不成对/点数不等/
            非有限数值——全部显式报错。
    """
    p = _require_file(path, "sparams_csv")
    import csv

    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = [row for row in reader if row]
    if len(rows) < 2:
        raise AnimationDataError(
            f"{p} 缺表头或数据行（至少 2 行）——残缺数据显式拒绝，不画空图")
    header = [h.strip() for h in rows[0]]
    if "freq_hz" not in header:
        raise AnimationDataError(
            f"{p} 表头缺 freq_hz 列（实测表头={header[:8]}...）——"
            "sparams_csv 契约=``freq_hz,re_S11,im_S11,...``")
    available = _sparam_columns_from_header(header)
    if not available:
        raise AnimationDataError(
            f"{p} 表头无任何 re_/im_ 成对 S 参数列——sparams_csv 契约="
            "``freq_hz,re_S11,im_S11,...``")
    wanted = sorted(set(columns)) if columns is not None else available
    unknown = [c for c in wanted if c not in available]
    if unknown:
        raise AnimationDataError(
            f"{p} 缺请求列 {sorted(unknown)}；可用 S 参数列={available}——"
            "请核对 spec.source.columns")
    col_idx = {c: (header.index(f"re_{c}"), header.index(f"im_{c}"))
               for c in wanted}
    freq: list[float] = []
    series: dict[str, list[complex]] = {c: [] for c in wanted}
    for lineno, row in enumerate(rows[1:], start=2):
        if len(row) < len(header):
            raise AnimationDataError(
                f"{p} 第 {lineno} 行列数 {len(row)} < 表头列数 {len(header)}"
                "——残缺数据显式拒绝")
        freq.append(_to_float(row[header.index("freq_hz")], f"{p}:{lineno}:freq_hz"))
        for c, (ri, ii) in col_idx.items():
            re_v = _to_float(row[ri], f"{p}:{lineno}:re_{c}")
            im_v = _to_float(row[ii], f"{p}:{lineno}:im_{c}")
            series[c].append(complex(re_v, im_v))
    if not freq:
        raise AnimationDataError(f"{p} 数据行为空——不画空图")
    n = len(freq)
    for c, vals in series.items():
        if len(vals) != n:  # 防御性（逐行 append 恒等长；契约钉死）
            raise AnimationDataError(f"{p} 列 {c} 点数 {len(vals)} != freq 点数 {n}")
    return SparamsTable(freq_hz=tuple(freq),
                        series={c: tuple(v) for c, v in series.items()},
                        source_path=str(p), columns=tuple(wanted))


def load_snip(path: Any, columns: list[str] | None = None,
              ports: list[int] | None = None) -> SparamsTable:
    """读 Touchstone sNp（skrf）→ :class:`SparamsTable`（零算术改写）。

    skrf 懒 import（sNp 源缺席不拖累其他源）；Network.f（Hz）+ Network.s
    (n_freq, n_port, n_port) → series ``S<i><j>``（1 基命名，sorted 序）。
    ``ports``（1 基）限制端口对（双向两端都须在集合内）；``columns`` 直接
    选 S 参数名。溢出/未知列显式报错。
    """
    p = _require_file(path, "snip")
    try:
        import skrf
    except ImportError as exc:  # pragma: no cover - 环境缺依赖显式暴露
        raise AnimationDataError(
            f"snip 源需要 skrf 依赖（当前环境不可用）：{exc}") from exc
    try:
        net = skrf.Network(str(p))
    except Exception as exc:  # skrf 解析错误族收敛为数据错误（显式，不静默）
        raise AnimationDataError(f"sNp 解析失败：{p}（{type(exc).__name__}: {exc}"
                                 "）——请核对文件完整性") from exc
    if net.s.size == 0 or net.f.size == 0:
        raise AnimationDataError(f"{p} 网络数据为空——不画空图")
    n_port = net.s.shape[1]
    all_names = sorted(f"S{i + 1}{j + 1}"
                       for i in range(n_port) for j in range(n_port))
    port_set = None
    if ports is not None:
        port_set = set()
        for q in ports:
            qi = int(q)
            if not 1 <= qi <= n_port:
                raise AnimationDataError(
                    f"{p} 端口号 {q} 越界（文件共 {n_port} 端口，1 基）——"
                    "请核对 spec.source.ports")
            port_set.add(qi)
    allowed = all_names
    if port_set is not None:
        allowed = sorted(nm for nm in all_names
                         if int(nm[1]) in port_set and int(nm[2]) in port_set)
    wanted = sorted(set(columns)) if columns is not None else allowed
    unknown = [c for c in wanted
               if c not in all_names or (port_set is not None and c not in allowed)]
    if unknown:
        raise AnimationDataError(
            f"{p} 缺请求列 {sorted(unknown)}；可用 S 参数列={allowed}——"
            "请核对 spec.source.columns/ports")
    freq = tuple(_to_float(f, f"{p}:freq") for f in net.f)
    series: dict[str, tuple[complex, ...]] = {}
    for c in wanted:
        i, j = int(c[1]) - 1, int(c[2]) - 1
        vals = []
        for k in range(net.s.shape[0]):
            z = complex(net.s[k, i, j])
            if not (math.isfinite(z.real) and math.isfinite(z.imag)):
                raise AnimationDataError(
                    f"{p} {c} 第 {k} 点非有限数值——残缺数据显式拒绝")
            vals.append(z)
        series[c] = tuple(vals)
    return SparamsTable(freq_hz=freq, series=series,
                        source_path=str(p), columns=tuple(wanted))


@dataclass(frozen=True)
class TrialRecord:
    """单条 trial（run 湖 ``trial_N.json`` 惯例字段；零字段改写）。"""

    number: int
    params: dict[str, Any]
    metrics: dict[str, Any]
    cost: float
    source_path: str


def _trial_from_obj(obj: Any, where: str) -> TrialRecord:
    """trial dict → TrialRecord（trial_number/params/cost 必备，缺=显式报错）。"""
    if not isinstance(obj, dict):
        raise AnimationDataError(f"{where} 不是 dict（收到 {type(obj).__name__}）"
                                 "——trials 契约=trial_number/params/metrics/cost")
    for key in ("trial_number", "params", "cost"):
        if key not in obj:
            raise AnimationDataError(
                f"{where} 缺必备键 {key!r}（trials 契约=trial_number/params/"
                "metrics/cost）——cost 缺失不猜代理量，请换数据源或补齐产物")
    num = obj["trial_number"]
    if isinstance(num, bool) or not isinstance(num, int):
        raise AnimationDataError(f"{where}.trial_number 必须是整数，收到 {num!r}")
    params = obj["params"]
    if not isinstance(params, dict):
        raise AnimationDataError(f"{where}.params 必须是 dict，收到 {type(params).__name__}")
    metrics = obj.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise AnimationDataError(f"{where}.metrics 必须是 dict")
    cost = _to_float(obj["cost"], f"{where}.cost")
    return TrialRecord(number=num, params=dict(params), metrics=dict(metrics),
                       cost=cost, source_path=where)


def load_trials(path: Any) -> list[TrialRecord]:
    """读 trials 数据源 → list[:class:`TrialRecord`]（trial_number 升序）。

    Args:
        path: 三形态——run 目录（读 ``trials/trial_*.json``，sorted）/
            单 trial JSON 文件/JSON 数组文件。

    Raises:
        AnimationDataError: 路径缺失/无 trial/字段残缺/非有限 cost。
    """
    p = Path(path)
    records: list[TrialRecord] = []
    if p.is_dir():
        trial_dir = p / "trials"
        files = sorted(trial_dir.glob("trial_*.json")) if trial_dir.is_dir() else []
        if not files:
            raise AnimationDataError(
                f"{p} 下无 trials/trial_*.json——trials 源=rfauto run 目录"
                "（含 trials/trial_N.json）；请核对 spec.source.path")
        for f in files:
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise AnimationDataError(f"trial 文件读取失败：{f}（{exc}）") from exc
            records.append(_trial_from_obj(obj, str(f)))
    else:
        p = _require_file(p, "trials")
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AnimationDataError(f"trials 文件读取失败：{p}（{exc}）") from exc
        items = obj if isinstance(obj, list) else [obj]
        if not items:
            raise AnimationDataError(f"{p} trials 数组为空——不画空图")
        for k, item in enumerate(items):
            records.append(_trial_from_obj(item, f"{p}[{k}]"))
    if not records:
        raise AnimationDataError(f"{path} 无任何 trial 记录——不画空图")
    return sorted(records, key=lambda r: (r.number, r.source_path))


def load_anchor_json(path: Any) -> dict[str, Any]:
    """读锚点/导出 JSON → 原始 dict（提取按图型；根必须是 object）。"""
    p = _require_file(path, "anchor_json")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"锚点 JSON 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "anchor_json 契约：smith=``{'points':[{'re','im'},...]}``，"
            "fit_compare=``{'series':{'x','y'}}``")
    return obj


# ─── 批 2 新增源（Q-W2-2）：field_dump / layout_json ──────────────────────────

@dataclass(frozen=True)
class FieldFrame:
    """单帧场分布（``values[ny][nx]`` 矩形网格，零值改写；meta 原样透传）。"""

    values: tuple[tuple[float, ...], ...]
    meta: dict[str, Any]
    source_path: str

    @property
    def n_rows(self) -> int:
        return len(self.values)

    @property
    def n_cols(self) -> int:
        return len(self.values[0]) if self.values else 0


@dataclass(frozen=True)
class FieldFrames:
    """场帧序列（帧数 ≥1；axes 原样透传给渲染器，零语义改写）。"""

    frames: tuple[FieldFrame, ...]
    axes: dict[str, Any]
    source_path: str

    @property
    def n_frames(self) -> int:
        return len(self.frames)


def _parse_field_frame_obj(obj: Any, where: str) -> FieldFrame:
    """单帧 dict → :class:`FieldFrame`（values 必备、矩形网格、全有限数值）。"""
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{where} 不是 dict（收到 {type(obj).__name__}）——field_dump 帧"
            "契约=``{'meta':{...},'values':[[...],...]}``")
    raw = obj.get("values")
    if not isinstance(raw, list) or not raw:
        raise AnimationDataError(
            f"{where} 缺非空 values 数组——field_dump 帧契约="
            "``{'meta':{...},'values':[[...],...]}``（values[ny][nx] 矩形网格）")
    rows: list[tuple[float, ...]] = []
    width: int | None = None
    for ri, row in enumerate(raw):
        if not isinstance(row, list) or not row:
            raise AnimationDataError(
                f"{where}.values[{ri}] 须为非空数组（矩形网格行）——残缺数据显式拒绝")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise AnimationDataError(
                f"{where}.values[{ri}] 列数 {len(row)} != 第 0 行 {width}"
                "——非矩形网格显式拒绝")
        rows.append(tuple(_to_float(v, f"{where}.values[{ri}][{ci}]")
                          for ci, v in enumerate(row)))
    meta = obj.get("meta") or {}
    if not isinstance(meta, dict):
        raise AnimationDataError(f"{where}.meta 必须是 dict（收到 {type(meta).__name__}）")
    return FieldFrame(values=tuple(rows), meta=dict(meta), source_path=where)


def load_field_frames(path: Any) -> FieldFrames:
    """读场帧序列（field_dump）→ :class:`FieldFrames`（零算术改写）。

    两形态（spec.source.kind=``field_dump``）：

    - 单 JSON 文件：根 object 含非空 ``frames`` 数组（每帧
      ``{"meta":{...},"values":[[...],...]}``）+ 可选 ``axes``（dict 透传）；
    - 目录：``frame_*.json`` sorted 逐帧文件（每文件一帧）+ 可选
      ``axes.json``（dict 透传；存在但非 dict 显式报错）。

    Raises:
        AnimationDataError: 路径缺失/无帧/缺帧字段/非矩形网格/非有限数值/
            axes 形态不合——全部显式报错（缺帧不画空图）。
    """
    p = Path(path)
    frames: list[FieldFrame] = []
    axes: dict[str, Any] = {}
    if p.is_dir():
        frame_files = sorted(p.glob("frame_*.json"))
        if not frame_files:
            raise AnimationDataError(
                f"{p} 下无 frame_*.json——field_dump 目录契约=frame_*.json"
                "（sorted 逐帧）+可选 axes.json；请核对 spec.source.path")
        for f in frame_files:
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise AnimationDataError(f"场帧文件读取失败：{f}（{exc}）") from exc
            frames.append(_parse_field_frame_obj(obj, str(f)))
        axes_path = p / "axes.json"
        if axes_path.is_file():
            try:
                axes_obj = json.loads(axes_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise AnimationDataError(f"axes.json 读取失败：{axes_path}（{exc}）") from exc
            if not isinstance(axes_obj, dict):
                raise AnimationDataError(
                    f"{axes_path} 根必须是 JSON object（收到 "
                    f"{type(axes_obj).__name__}）——axes 契约=坐标轴/单位元数据 dict")
            axes = axes_obj
    else:
        p = _require_file(p, "field_dump")
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AnimationDataError(f"field_dump 文件读取失败：{p}（{exc}）") from exc
        if not isinstance(obj, dict):
            raise AnimationDataError(
                f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
                "field_dump 契约=``{'axes':{...},'frames':[...]}``")
        raw_frames = obj.get("frames")
        if not isinstance(raw_frames, list) or not raw_frames:
            raise AnimationDataError(
                f"{p} 缺非空 frames 数组——field_dump 契约="
                "``{'axes':{...},'frames':[{'meta','values'},...]}``"
                "（缺帧显式报错，不画空图）")
        for k, item in enumerate(raw_frames):
            frames.append(_parse_field_frame_obj(item, f"{p}.frames[{k}]"))
        raw_axes = obj.get("axes") or {}
        if not isinstance(raw_axes, dict):
            raise AnimationDataError(f"{p}.axes 必须是 dict（收到 {type(raw_axes).__name__}）")
        axes = raw_axes
    if not frames:
        raise AnimationDataError(f"{path} 无任何场帧——不画空图")
    return FieldFrames(frames=tuple(frames), axes=dict(axes), source_path=str(p))


@dataclass(frozen=True)
class Primitive:
    """图元（layout_json 契约：shape/x/y/w/h 数据直通，零坐标改写）。"""

    shape: str
    x: float
    y: float
    w: float
    h: float
    source_path: str


@dataclass(frozen=True)
class LayoutLayer:
    """单层（name + 图元序列；渲染端按层组消费）。"""

    name: str
    primitives: tuple[Primitive, ...]
    source_path: str


@dataclass(frozen=True)
class LayoutDoc:
    """layout_json 文档（层数 ≥1；层序=数据声明序，渲染器不做重排）。"""

    layers: tuple[LayoutLayer, ...]
    source_path: str

    @property
    def n_layers(self) -> int:
        return len(self.layers)


def load_layout_json(path: Any) -> LayoutDoc:
    """读图元坐标序列（layout_json）→ :class:`LayoutDoc`（零坐标改写）。

    契约：根 object 含非空 ``layers`` 数组；每层 ``{"name": str,
    "primitives": [{"shape","x","y","w","h"}, ...]}``（primitives 允许空
    数组=空层照收，渲染端空层只有标签无图元）。

    Raises:
        AnimationDataError: 路径缺失/根非 object/缺层/层字段残缺/图元
            键缺失/非有限坐标——缺层显式报错（不画空图）。
    """
    p = _require_file(path, "layout_json")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"layout_json 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "layout_json 契约=``{'layers':[{'name','primitives'},...]}``")
    raw_layers = obj.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise AnimationDataError(
            f"{p} 缺非空 layers 数组——layout_json 契约="
            "``{'layers':[{'name':...,'primitives':[{'shape','x','y','w','h'},...]},...]}``"
            "（缺层显式报错，不画空图）")
    layers: list[LayoutLayer] = []
    for li, layer in enumerate(raw_layers):
        where = f"{p}.layers[{li}]"
        if not isinstance(layer, dict):
            raise AnimationDataError(
                f"{where} 不是 dict（收到 {type(layer).__name__}）")
        name = layer.get("name")
        if not isinstance(name, str) or not name:
            raise AnimationDataError(
                f"{where} 缺非空字符串 name——layout_json 层契约"
                "=``{'name':...,'primitives':[...]} ``")
        raw_prims = layer.get("primitives")
        if not isinstance(raw_prims, list):
            raise AnimationDataError(
                f"{where} 缺 primitives 数组（layout_json 层契约）")
        prims: list[Primitive] = []
        for pi, prim in enumerate(raw_prims):
            pwhere = f"{where}.primitives[{pi}]"
            if not isinstance(prim, dict):
                raise AnimationDataError(
                    f"{pwhere} 不是 dict（收到 {type(prim).__name__}）——"
                    "图元契约=``{'shape','x','y','w','h'}``")
            missing = [k for k in ("shape", "x", "y", "w", "h") if k not in prim]
            if missing:
                raise AnimationDataError(
                    f"{pwhere} 缺必备键 {missing}——图元契约="
                    "``{'shape','x','y','w','h'}``")
            shape = prim["shape"]
            if not isinstance(shape, str) or not shape:
                raise AnimationDataError(f"{pwhere}.shape 须为非空字符串")
            prims.append(Primitive(
                shape=shape,
                x=_to_float(prim["x"], f"{pwhere}.x"),
                y=_to_float(prim["y"], f"{pwhere}.y"),
                w=_to_float(prim["w"], f"{pwhere}.w"),
                h=_to_float(prim["h"], f"{pwhere}.h"),
                source_path=pwhere))
        layers.append(LayoutLayer(name=name, primitives=tuple(prims),
                                  source_path=where))
    return LayoutDoc(layers=tuple(layers), source_path=str(p))


# ─── 批 3 新增源（Q-W2-3）：cascade_json / nf2ff_cut / chain_json ────────────

@dataclass(frozen=True)
class CascadeStage:
    """单级（cascade_json 契约：gain_db/nf_db 数据直通；name 可选）。

    ``name=None`` 时渲染端用位置缺省标签 ``stage{k}``（0 基序号；确定性
    显示回退，非数据补造）。gain_db/nf_db 语义与 core/cascade_service
    级表同名同义（dB 域）。
    """

    name: str | None
    gain_db: float
    nf_db: float
    source_path: str


@dataclass(frozen=True)
class CascadeDoc:
    """级联级表文档（级数 ≥1；级序=数据声明序=信号流向，不重排）。"""

    stages: tuple[CascadeStage, ...]
    source_path: str

    @property
    def n_stages(self) -> int:
        return len(self.stages)


def load_cascade_json(path: Any) -> CascadeDoc:
    """读级联级表（cascade_json）→ :class:`CascadeDoc`（零数值改写）。

    契约：根 object 含非空 ``stages`` 数组；每级
    ``{"name"?: str, "gain_db": number, "nf_db": number}``（gain_db/nf_db
    必备有限数值；name 缺省 None，渲染端位置回退）。

    Raises:
        AnimationDataError: 路径缺失/根非 object/缺级/级字段残缺/非有限
            数值——缺级显式报错（不画空图）。
    """
    p = _require_file(path, "cascade_json")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"cascade_json 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "cascade_json 契约=``{'stages':[{'name'?,'gain_db','nf_db'},...]}``")
    raw_stages = obj.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise AnimationDataError(
            f"{p} 缺非空 stages 数组——cascade_json 契约="
            "``{'stages':[{'name'?,'gain_db','nf_db'},...]}``"
            "（缺级显式报错，不画空图）")
    stages: list[CascadeStage] = []
    for si, raw in enumerate(raw_stages):
        where = f"{p}.stages[{si}]"
        if not isinstance(raw, dict):
            raise AnimationDataError(
                f"{where} 不是 dict（收到 {type(raw).__name__}）——"
                "级契约=``{'name'?,'gain_db','nf_db'}``")
        for key in ("gain_db", "nf_db"):
            if key not in raw:
                raise AnimationDataError(
                    f"{where} 缺必备键 {key!r}——级契约="
                    "``{'name'?,'gain_db','nf_db'}``（对齐 core/cascade "
                    "级表语义；缺数据不猜不兜底）")
        name = raw.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise AnimationDataError(
                f"{where}.name 须为非空字符串或省略（收到 {name!r}）")
        stages.append(CascadeStage(
            name=name,
            gain_db=_to_float(raw["gain_db"], f"{where}.gain_db"),
            nf_db=_to_float(raw["nf_db"], f"{where}.nf_db"),
            source_path=where))
    return CascadeDoc(stages=tuple(stages), source_path=str(p))


@dataclass(frozen=True)
class PatternCut:
    """单幅方向图切面（theta_deg/db 等长序列；零数值改写）。

    ``freq_hz``/``phi_deg`` 为可选切面标识（数据直通，渲染端标签派生用）；
    ``meta`` 原样透传。
    """

    theta_deg: tuple[float, ...]
    db: tuple[float, ...]
    source_path: str
    freq_hz: float | None = None
    phi_deg: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_points(self) -> int:
        return len(self.theta_deg)


@dataclass(frozen=True)
class PatternCutSeries:
    """方向图切面序列（切面数 ≥1；帧=切面，帧语义=频率/俯仰步）。"""

    cuts: tuple[PatternCut, ...]
    source_path: str

    @property
    def n_cuts(self) -> int:
        return len(self.cuts)


def load_nf2ff_cut(path: Any) -> PatternCutSeries:
    """读方向图切面序列（nf2ff_cut）→ :class:`PatternCutSeries`。

    契约：根 object 含非空 ``cuts`` 数组；每幅切面 dict：

    - ``theta_deg``：非空数组（有限数值，角度 deg；数据序直通不排序）；
    - dB 序列：``db``（任务书最小约定）**或** ``pattern_db``（nf2ff_service
      farfield_view 既有产物键名）——恰一键，双给/双缺均显式报错；
    - 可选 ``freq_hz``（number）/ ``phi_deg``（number）/ ``meta``（dict 透传）。

    Raises:
        AnimationDataError: 路径缺失/根非 object/缺切面/键缺失/等长破坏/
            非有限数值/dB 键双给或双缺。
    """
    p = _require_file(path, "nf2ff_cut")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"nf2ff_cut 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "nf2ff_cut 契约=``{'cuts':[{'theta_deg',[...],'db'|'pattern_db':[...]}]}``")
    raw_cuts = obj.get("cuts")
    if not isinstance(raw_cuts, list) or not raw_cuts:
        raise AnimationDataError(
            f"{p} 缺非空 cuts 数组——nf2ff_cut 契约="
            "``{'cuts':[{'theta_deg':[...],'db'|'pattern_db':[...],...]}``"
            "（缺切面显式报错，不画空图）")
    cuts: list[PatternCut] = []
    for ci, raw in enumerate(raw_cuts):
        where = f"{p}.cuts[{ci}]"
        if not isinstance(raw, dict):
            raise AnimationDataError(
                f"{where} 不是 dict（收到 {type(raw).__name__}）——切面契约="
                "``{'theta_deg':[...],'db'|'pattern_db':[...]}``")
        raw_theta = raw.get("theta_deg")
        if not isinstance(raw_theta, list) or not raw_theta:
            raise AnimationDataError(
                f"{where} 缺非空 theta_deg 数组——nf2ff_cut 切面契约="
                "``{'theta_deg':[...],'db'|'pattern_db':[...]}``")
        db_keys = [k for k in ("db", "pattern_db") if k in raw]
        if len(db_keys) != 1:
            raise AnimationDataError(
                f"{where} dB 序列键 {db_keys or ['（无）']} 不合契约——须恰给"
                " ``db``（任务书约定）或 ``pattern_db``（nf2ff_service "
                "farfield_view 产物键名）其一")
        raw_db = raw[db_keys[0]]
        if not isinstance(raw_db, list) or not raw_db:
            raise AnimationDataError(
                f"{where} 缺非空 dB 数组（{db_keys[0]}）——残缺数据显式拒绝")
        if len(raw_db) != len(raw_theta):
            raise AnimationDataError(
                f"{where} dB 点数 {len(raw_db)} != theta_deg 点数 "
                f"{len(raw_theta)}——等长破坏显式拒绝")
        theta = tuple(_to_float(t, f"{where}.theta_deg[{k}]")
                      for k, t in enumerate(raw_theta))
        db = tuple(_to_float(v, f"{where}.{db_keys[0]}[{k}]")
                   for k, v in enumerate(raw_db))
        freq_hz = (_to_float(raw["freq_hz"], f"{where}.freq_hz")
                   if "freq_hz" in raw else None)
        phi_deg = (_to_float(raw["phi_deg"], f"{where}.phi_deg")
                   if "phi_deg" in raw else None)
        meta = raw.get("meta") or {}
        if not isinstance(meta, dict):
            raise AnimationDataError(
                f"{where}.meta 必须是 dict（收到 {type(meta).__name__}）")
        cuts.append(PatternCut(theta_deg=theta, db=db, source_path=where,
                               freq_hz=freq_hz, phi_deg=phi_deg,
                               meta=dict(meta)))
    return PatternCutSeries(cuts=tuple(cuts), source_path=str(p))


@dataclass(frozen=True)
class ChainNode:
    """链路框图节点（chain_json 契约：id 必备唯一；label/gain_db 可选）。

    ``label=None`` 时渲染端用 id 作显示标签（确定性回退）；``gain_db``
    数据直通标注（None=无标注）。
    """

    id: str
    source_path: str
    label: str | None = None
    gain_db: float | None = None


@dataclass(frozen=True)
class ChainEdge:
    """链路框图有向边（from/to 必须引用已声明节点 id）。"""

    from_id: str
    to_id: str
    source_path: str


@dataclass(frozen=True)
class ChainDoc:
    """链路框图文档（节点 ≥1；边可为空=全部节点为根逐帧点亮）。"""

    nodes: tuple[ChainNode, ...]
    edges: tuple[ChainEdge, ...]
    source_path: str

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(n.id for n in self.nodes)


def load_chain_json(path: Any) -> ChainDoc:
    """读链路框图（chain_json）→ :class:`ChainDoc`（零语义改写）。

    契约：根 object 含非空 ``nodes`` 数组 + ``edges`` 数组（可为空）；
    节点 ``{"id": str(必备唯一), "label"?: str, "gain_db"?: number}``；
    边 ``{"from": str, "to": str}``（必须引用已声明节点 id——悬空引用
    显式报错）。

    Raises:
        AnimationDataError: 路径缺失/根非 object/缺节点/节点字段残缺/
            id 重复/边字段残缺/边引用未知节点/非有限 gain_db。
    """
    p = _require_file(path, "chain_json")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"chain_json 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "chain_json 契约=``{'nodes':[{'id','label'?,'gain_db'?},...],"
            "'edges':[{'from','to'},...]}``")
    raw_nodes = obj.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise AnimationDataError(
            f"{p} 缺非空 nodes 数组——chain_json 契约="
            "``{'nodes':[{'id','label'?,'gain_db'?},...],"
            "'edges':[{'from','to'},...]}``（缺节点显式报错，不画空图）")
    nodes: list[ChainNode] = []
    seen: set[str] = set()
    for ni, raw in enumerate(raw_nodes):
        where = f"{p}.nodes[{ni}]"
        if not isinstance(raw, dict):
            raise AnimationDataError(
                f"{where} 不是 dict（收到 {type(raw).__name__}）——"
                "节点契约=``{'id','label'?,'gain_db'?}``")
        nid = raw.get("id")
        if not isinstance(nid, str) or not nid:
            raise AnimationDataError(
                f"{where} 缺非空字符串 id——chain_json 节点契约="
                "``{'id','label'?,'gain_db'?}``")
        if nid in seen:
            raise AnimationDataError(
                f"{where} 节点 id {nid!r} 重复——链路节点 id 必须唯一"
                "（布局与点亮序按 id 消歧）")
        seen.add(nid)
        label = raw.get("label")
        if label is not None and (not isinstance(label, str) or not label):
            raise AnimationDataError(
                f"{where}.label 须为非空字符串或省略（收到 {label!r}）")
        gain_db = (_to_float(raw["gain_db"], f"{where}.gain_db")
                   if "gain_db" in raw else None)
        nodes.append(ChainNode(id=nid, source_path=where, label=label,
                               gain_db=gain_db))
    raw_edges = obj.get("edges")
    if not isinstance(raw_edges, list):
        raise AnimationDataError(
            f"{p} 缺 edges 数组（可为空但键必须在）——chain_json 契约")
    edges: list[ChainEdge] = []
    for ei, raw in enumerate(raw_edges):
        where = f"{p}.edges[{ei}]"
        if not isinstance(raw, dict):
            raise AnimationDataError(
                f"{where} 不是 dict（收到 {type(raw).__name__}）——"
                "边契约=``{'from','to'}``")
        missing = [k for k in ("from", "to") if k not in raw]
        if missing:
            raise AnimationDataError(
                f"{where} 缺必备键 {missing}——边契约=``{'from','to'}``")
        fid, tid = raw["from"], raw["to"]
        for k, v in (("from", fid), ("to", tid)):
            if not isinstance(v, str) or not v:
                raise AnimationDataError(
                    f"{where}.{k} 须为非空字符串（收到 {v!r}）")
        for k, v in (("from", fid), ("to", tid)):
            if v not in seen:
                raise AnimationDataError(
                    f"{where}.{k}={v!r} 引用未声明节点——chain_json 边必须"
                    "引用 nodes 中已声明的 id（悬空引用显式报错不猜）")
        edges.append(ChainEdge(from_id=fid, to_id=tid, source_path=where))
    return ChainDoc(nodes=tuple(nodes), edges=tuple(edges),
                    source_path=str(p))


# ─── 批 4 新增源（Q-W2-4）：symbols_json / budget_json ───────────────────────

@dataclass(frozen=True)
class SymbolFrame:
    """单帧符号集（symbols_json 契约：``[[i,q],...]`` 数据直通零改写）。

    每符号=(I,Q) 二元组（有限数值）；帧内符号序=数据声明序（星座散点与
    眼图轨迹按此序连接，不重排）。
    """

    symbols: tuple[tuple[float, float], ...]
    source_path: str

    @property
    def n_symbols(self) -> int:
        return len(self.symbols)


@dataclass(frozen=True)
class SymbolsDoc:
    """符号序列文档（帧数 ≥1；单云形态归一为单帧——帧边界供渲染端眼图
    轨迹分段用：轨迹不跨帧连接）。"""

    frames: tuple[SymbolFrame, ...]
    source_path: str

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def n_symbols(self) -> int:
        return sum(f.n_symbols for f in self.frames)


def _parse_symbol_pairs(raw: Any, where: str) -> tuple[tuple[float, float], ...]:
    """symbols 数组 → (I,Q) 元组序列（每项恰 2 个有限数值，显式拒绝残缺）。"""
    if not isinstance(raw, list) or not raw:
        raise AnimationDataError(
            f"{where} 缺非空 symbols 数组——symbols_json 契约="
            "``{'symbols':[[i,q],...]}``（缺符号显式报错，不画空图）")
    pairs: list[tuple[float, float]] = []
    for k, item in enumerate(raw):
        swhere = f"{where}.symbols[{k}]"
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise AnimationDataError(
                f"{swhere} 须为 [i, q] 二元数组（收到 {item!r}）——"
                "symbols_json 符号契约=[[i,q],...]（恰 2 分量）")
        pairs.append((_to_float(item[0], f"{swhere}[0]"),
                      _to_float(item[1], f"{swhere}[1]")))
    return tuple(pairs)


def load_symbols_json(path: Any) -> SymbolsDoc:
    """读数字调制符号序列（symbols_json）→ :class:`SymbolsDoc`（零数值改写）。

    恰一形态（双给/双缺均显式报错）：

    - 单云：根 object 含非空 ``symbols`` 数组（``[[i,q],...]``）——归一为
      单帧（帧边界=整段，眼图轨迹单段）；
    - 帧序列：根 object 含非空 ``frames`` 数组，每帧 ``{"symbols":
      [[i,q],...]}``（帧内符号非空；帧=符号窗捕获分组，渲染端轨迹不跨帧
      连接）。侦察 si_channel_service 无既有符号产物——本契约为任务书
      最小 JSON 约定。

    Raises:
        AnimationDataError: 路径缺失/根非 object/形态双给或双缺/帧字段残缺/
            符号非二元数组/非有限数值。
    """
    p = _require_file(path, "symbols_json")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"symbols_json 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "symbols_json 契约=``{'symbols':[...]}`` 或 "
            "``{'frames':[{'symbols':[...]},...]}``（恰一形态）")
    has_single = "symbols" in obj
    has_frames = "frames" in obj
    if has_single and has_frames:
        raise AnimationDataError(
            f"{p} symbols 与 frames 双给——symbols_json 恰一形态（单云或帧"
            "序列），双给显式拒绝不猜")
    if not has_single and not has_frames:
        raise AnimationDataError(
            f"{p} 缺 symbols 或 frames 键——symbols_json 契约="
            "``{'symbols':[[i,q],...]}``（单云）或 "
            "``{'frames':[{'symbols':[...]},...]}``（帧序列）")
    frames: list[SymbolFrame] = []
    if has_single:
        frames.append(SymbolFrame(
            symbols=_parse_symbol_pairs(obj["symbols"], str(p)),
            source_path=str(p)))
    else:
        raw_frames = obj["frames"]
        if not isinstance(raw_frames, list) or not raw_frames:
            raise AnimationDataError(
                f"{p} 缺非空 frames 数组——symbols_json 帧序列契约="
                "``{'frames':[{'symbols':[[i,q],...]},...]}``（缺帧显式报错）")
        for fi, raw in enumerate(raw_frames):
            fwhere = f"{p}.frames[{fi}]"
            if not isinstance(raw, dict):
                raise AnimationDataError(
                    f"{fwhere} 不是 dict（收到 {type(raw).__name__}）——"
                    "帧契约=``{'symbols':[[i,q],...]}``")
            if "symbols" not in raw:
                raise AnimationDataError(
                    f"{fwhere} 缺 symbols 键——symbols_json 帧契约="
                    "``{'symbols':[[i,q],...]}``")
            frames.append(SymbolFrame(
                symbols=_parse_symbol_pairs(raw["symbols"], fwhere),
                source_path=fwhere))
    return SymbolsDoc(frames=tuple(frames), source_path=str(p))


@dataclass(frozen=True)
class BudgetStage:
    """单级预算项（budget_json 契约：value_db 数据直通；name 可选）。

    ``name=None`` 时渲染端用位置缺省标签 ``stage{k}``（0 基序号；确定性
    显示回退，非数据补造）。value_db 语义=逐级增量 dB（负值=损耗扣减，
    正值=增益/预算注入）；累计余量=渲染端声明式派生（budget_funnel
    docstring 公式，测试独立复算锚）。
    """

    name: str | None
    value_db: float
    source_path: str


@dataclass(frozen=True)
class BudgetDoc:
    """链路预算级表文档（级数 ≥1；级序=数据声明序=发射→接收流向，不重排）。"""

    stages: tuple[BudgetStage, ...]
    source_path: str

    @property
    def n_stages(self) -> int:
        return len(self.stages)


def load_budget_json(path: Any) -> BudgetDoc:
    """读链路预算级表（budget_json）→ :class:`BudgetDoc`（零数值改写）。

    契约：根 object 含非空 ``stages`` 数组；每级 ``{"name"?: str,
    "value_db": number}``（value_db 必备有限数值；name 缺省 None，渲染端
    位置回退）。与 cascade_json 同构但语义=预算扣减（value_db 增量，
    负值累计）——侦察 adc_budget_service/am_loss_budget 无 stages+value_db
    既有产物，本契约为任务书最小 JSON 约定。

    Raises:
        AnimationDataError: 路径缺失/根非 object/缺级/级字段残缺/非有限
            数值——缺级显式报错（不画空图）。
    """
    p = _require_file(path, "budget_json")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"budget_json 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "budget_json 契约=``{'stages':[{'name'?,'value_db'},...]}``")
    raw_stages = obj.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise AnimationDataError(
            f"{p} 缺非空 stages 数组——budget_json 契约="
            "``{'stages':[{'name'?,'value_db'},...]}``"
            "（缺级显式报错，不画空图）")
    stages: list[BudgetStage] = []
    for si, raw in enumerate(raw_stages):
        where = f"{p}.stages[{si}]"
        if not isinstance(raw, dict):
            raise AnimationDataError(
                f"{where} 不是 dict（收到 {type(raw).__name__}）——"
                "级契约=``{'name'?,'value_db'}``")
        if "value_db" not in raw:
            raise AnimationDataError(
                f"{where} 缺必备键 'value_db'——级契约="
                "``{'name'?,'value_db'}``（预算扣减语义；缺数据不猜不兜底）")
        name = raw.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise AnimationDataError(
                f"{where}.name 须为非空字符串或省略（收到 {name!r}）")
        stages.append(BudgetStage(
            name=name,
            value_db=_to_float(raw["value_db"], f"{where}.value_db"),
            source_path=where))
    return BudgetDoc(stages=tuple(stages), source_path=str(p))


# ─── Q-R3R 遗留清偿席新增源：cfc_state（CfC 隐态轨迹） ───────────────────────
#
# 公开面注记：本节新名**有意不进模块 ``__all__``**——公开面快照
# tests/gold/public_api.json 本席冻结（新增公开名=显式评审动作，
# --generate 重钉留后续席位收编）；消费面走模块路径直接 import
# （``from rfauto.service.animation.loaders import load_cfc_state``）。

@dataclass(frozen=True)
class CfcStateDoc:
    """CfC 隐态轨迹文档（cfc_state 契约：hidden [T][H] 数据直通零改写）。

    T=step 数（帧语义=逐 step 揭示）、H=hidden_dim；``time`` 可选（None=
    渲染端按 step 序号横轴）；``provenance`` 原样透传（产出链溯源：lnn_cfc
    hidden_state_doc / LnnCfcSurrogate.hidden_states → service/
    lnn_cfc_export_service.export_cfc_hidden_states）。
    """

    hidden: tuple[tuple[float, ...], ...]
    source_path: str
    time: tuple[float, ...] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def n_steps(self) -> int:
        return len(self.hidden)

    @property
    def hidden_dim(self) -> int:
        return len(self.hidden[0]) if self.hidden else 0


def load_cfc_state(path: Any) -> CfcStateDoc:
    """读 CfC 隐态轨迹（cfc_state）→ :class:`CfcStateDoc`（零数值改写）。

    契约：根 object 含非空矩形 ``hidden`` 矩阵（``[[H 值]/step, ...]``，
    全行等长、全有限数值）；可选 ``time``（等长有限数组，单调性归渲染端
    逐帧揭示前提校验）；可选 ``hidden_dim``（与实测列数一致，声明不符
    显式拒绝）；可选 ``provenance``（dict 透传）。

    Raises:
        AnimationDataError: 路径缺失/根非 object/缺 hidden/非矩形/非有限
            数值/time 等长破坏/hidden_dim 不符——缺数据显式报错（不画空图）。
    """
    p = _require_file(path, "cfc_state")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnimationDataError(f"cfc_state 读取失败：{p}（{exc}）") from exc
    if not isinstance(obj, dict):
        raise AnimationDataError(
            f"{p} 根必须是 JSON object（收到 {type(obj).__name__}）——"
            "cfc_state 契约=``{'hidden':[[...],...],'time'?:[...],"
            "'hidden_dim'?}``（产出面=lnn_cfc 隐态导出链）")
    raw_hidden = obj.get("hidden")
    if not isinstance(raw_hidden, list) or not raw_hidden:
        raise AnimationDataError(
            f"{p} 缺非空 hidden 矩阵——cfc_state 契约="
            "``{'hidden':[[...],...],...}``（缺数据显式报错，不画空图）")
    width: int | None = None
    rows: list[tuple[float, ...]] = []
    for ti, row in enumerate(raw_hidden):
        where = f"{p}.hidden[{ti}]"
        if not isinstance(row, list) or not row:
            raise AnimationDataError(
                f"{where} 须为非空数值行（矩形 [T][H] 矩阵）——残缺数据"
                "显式拒绝")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise AnimationDataError(
                f"{where} 列数 {len(row)} != 第 0 行 {width}"
                "——非矩形矩阵显式拒绝")
        rows.append(tuple(_to_float(v, f"{where}[{ci}]")
                          for ci, v in enumerate(row)))
    raw_time = obj.get("time")
    time: tuple[float, ...] | None = None
    if raw_time is not None:
        if not isinstance(raw_time, list) or len(raw_time) != len(rows):
            raise AnimationDataError(
                f"{p} time 长度 {len(raw_time) if isinstance(raw_time, list) else '非数组'}"
                f" != hidden 步数 {len(rows)}——等长破坏显式拒绝")
        time = tuple(_to_float(v, f"{p}.time[{k}]")
                     for k, v in enumerate(raw_time))
    hd = obj.get("hidden_dim")
    if hd is not None:
        try:
            hd_v = int(hd)
        except (TypeError, ValueError) as exc:
            raise AnimationDataError(
                f"{p} hidden_dim 须为整数（收到 {hd!r}）") from exc
        if hd_v != width:
            raise AnimationDataError(
                f"{p} hidden_dim={hd_v} != 实测列数 {width}——声明与数据"
                "不符显式拒绝")
    provenance = obj.get("provenance")
    if provenance is not None and not isinstance(provenance, dict):
        raise AnimationDataError(
            f"{p} provenance 必须是 dict（收到 {type(provenance).__name__}）")
    return CfcStateDoc(hidden=tuple(rows), source_path=str(p), time=time,
                       provenance=dict(provenance or {}))
