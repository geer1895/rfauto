"""IPC-D-356/356A 裸板电气测试网表结构化解析内核（aurora_q 席位 Q-X65，2026-11-07）。

PCB 制造三件套的**电气测试面**事实标准 **IPC-D-356/356A**（Per-Pin
Electrical Test Data；KiCad/Altium 导出、飞针/测试架具消费）的只读
记录级结构化解析：头部参数（版本/坐标缩放因子/用户名/日期/注释）+ 记录
状态机（元件/焊盘·V 节点/过孔/DIP 轴向/非测试面引脚/夹具探针面）+
net→pads 测试点拓扑 + DRC 类统计（单点 net=开路嫌疑如实清单）。全部词法
与数值语义在 core 确定性内核（铁律 7：结构化数字只出自数据源文本本身）。
服务包装见 :mod:`rfauto.service.ipc356_service`（规则 4 JSON 进出），CLI
薄壳= cli/domains/ipc356.py 的 ``ipc356 report`` 叶（citi/gdsii 同款独立
typer 根，合流挂账）。与 Q-X59 制造双解析（gerber/excellon）构成制造
三件套，配对校验入口在服务层 :func:`rfauto.service.ipc356_service.
ipc356_fab_pair_check`（fab_gerber_service 产物只读消费）。

记录形态覆盖面（campaign 口径逐条落地；356 旧式固定列与 356A 扩展列
+XT 后缀**双形态同读取器容忍**——tag 字段扫描天然列宽不敏感）：

- 头部：``P 2.10``/``P 3.00`` 版本行（file 级指纹，缺失=解析错误）；
  ``C<数字>`` 坐标精度参数（≥4 位数字=坐标缩放因子登记；≤3 位=记录类目
  文档行收编不解释）；``M10``/``M20`` 用户名/日期登记（其余 M 码
  warning 跳行）；``CM...`` 注释块收编；``RECORD`` 起头文档行收编；
  其余 ``C`` 起头行=注释收编；未识别头部语句 warning 跳行（fail-soft
  #208 家法零进展守卫）；
- ``317`` 元件记录（含 317XT 变体）：refdes + X/Y 坐标 + ``R<n>`` 旋转；
- ``378`` 焊盘/V 节点记录（含 378XT 变体）：net 名 + X/Y 坐标 + 孔径
  （第二个 ``X<int>`` 字段=孔径，356A 双 X 字段惯例）+ 中点标志 ``M`` +
  焊盘形状 ``S``/``R``/``C``（S 方形/R 矩形/C 圆形，尺寸码原样登记）；
- ``367`` 过孔记录：net 名（可缺）+ X/Y 坐标 + 孔径 + 形状；
- ``363`` DIP 轴向器件：refdes + X/Y 坐标 + 旋转（元件族同构）；
- ``362`` 非测试面引脚：net 名（可缺）+ X/Y 坐标 + 孔径（焊盘族同构，
  ``record="362"`` 如实标记来源）；
- ``357`` 夹具探针面：探针点名 + X/Y 坐标（收 ``probes`` 独立清单，
  不冒充板面焊盘——解析深度=坐标/点名级，探针网表关联如实不展开）；
- net 名段双形态：356A 列语义=378/367 记录尾裸词字段（tag 扫描剩余首
  token）；356 旧式=独立 ``%`` 行（``%NETNAME <net>``/``% <net>`` → 模态
  current_net 应用于后续无自带 net 的焊盘/过孔；空 ``%`` 行=清模态）；
- 坐标：tag 字段整数 × 缩放因子换算——**mm = 原始整数 × 100 / C 因子**
  （表驱动已知量钉：C1000000 + X0012345 → 1.2345 mm；C100000 +
  X0012345 → 12.345 mm；Fraction 精确十进制）。C 参数缺失 → warning +
  ``_mm`` 如实 None（单位不明不猜，gerber MO 缺失家法）；
- 终止：``9999`` 文件尾标记（``00000`` 兼容接受）→ ``truncated=False``；
  流尾无标记 → ``truncated=True`` + warning（**口径声明限制**：EOF 标记
  按 KiCad IPC-D-356 导出惯例钉定，历史工具缺标记如实报截断不报错）；
- 未知记录类目（首三数字非 317/378/367/363/362/357）→ warning + 跳行
  （逐条披露不改据）。

designator 词法（双形态）：类目码后紧跟 ``X``+非数字非负号 = 旗标 X
（XT 变体族；``X-01000`` 负坐标=非旗标），旗标摘除后到首个
``X<int>``/``Y<int>`` 坐标字段（或空白）为止的前缀 = refdes/designator；
无旗标形态到首个 ``X<int>``/``Y<int>``（含负坐标）/空白为止。病态命名
如实声明限制：designator 内嵌 ``X<数字>`` 形态（如 ``AX1B``）会被提前
截断；net 名内嵌 tag 字母+数字（如 ``S1``/``NET_X2``）会被 tag 扫描
先行消费（真实 356A designator 走旗标/固定列两惯例，net 名走列位）。

结构化输出（任务书 schema）::

    {"schema", "version", "scale_factor", "media": [...],
     "comments": [...], "user_name", "date", "components": [...],
     "pads": [...], "vias": [...], "probes": [...],
     "nets": {name: [pad 序号索引]}, "stats": {...},
     "truncated", "warnings"}

查询三函数：:func:`ipc356_net_pads`（net 全部测试点，未知 net fail-
closed ValueError 带可用名录）、:func:`ipc356_component_pins`（元件引脚
视图）、:func:`ipc356_single_point_nets`（单点 net 清单——开路嫌疑测试
语义如实标注）。

fail-soft 口径（excellon_parser/gerber_parser 家法）：单条记录词法/语义
违规 → warning + 跳过；坐标非法/缺 C 因子 → ``_mm`` None 不猜；文件级
错误（空文本/无版本行/无任何指纹）→ :class:`Ipc356ParseError`（服务层转
error 信封）。

确定性（同输入同输出）、零 IO、零第三方依赖。本模块不设 ``__all__``
（无 __all__ 文件不进 tests/gold/public_api.json——excellon_parser/
verilog_netlist_parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 文件尾标记（KiCad IPC-D-356 导出惯例；00000 兼容接受）。
END_MARKERS = ("9999", "00000")

#: 元件族记录类目（317 元件 / 363 DIP 轴向器件）。
COMPONENT_RECORDS = ("317", "363")
#: 焊盘族记录类目（378 焊盘/V 节点 / 362 非测试面引脚）。
PAD_RECORDS = ("378", "362")
#: 过孔记录类目。
VIA_RECORD = "367"
#: 夹具探针面记录类目。
PROBE_RECORD = "357"

#: 焊盘形状字母 → 语义（campaign 口径：S 方形/R 矩形/C 圆形）。
SHAPE_KINDS = {"S": "square", "R": "rectangle", "C": "circle"}

#: 头部 C 缩放因子的最短位数（≥4 位=坐标精度参数；≤3 位=记录类目文档行）。
_SCALE_MIN_DIGITS = 4

# ── 词法（正则与记录形态一一对应）───────────────────────────────────────────

#: 头部版本行：P 2.10 / P 3.00（版本号 verbatim 登记）。
_VERSION_RE = re.compile(r"^P\s+(\d+\.\d+)\s*$")
#: 头部 M 记录：M10 用户名 / M20 日期（其余 M 码 warning 跳行）。
_M_RECORD_RE = re.compile(r"^M(\d+)\s*(.*)$")
#: 头部 CM 注释块。
_CM_RE = re.compile(r"^CM\s*(.*)$")
#: 头部 C 坐标精度参数：C + ≥4 位纯数字（C1234567890 形态）。
_SCALE_RE = re.compile(rf"^C(\d{{{_SCALE_MIN_DIGITS},}})\s*$")
#: 头部 C 记录类目文档行：C + ≤3 位数字。
_RECORD_DOC_RE = re.compile(r"^C(\d{1,3})\s*$")
#: 头部 RECORD 文档行（RECORD 类目声明，收编不解释）。
_RECORD_LINE_RE = re.compile(r"^RECORD\b", re.IGNORECASE)
#: 记录类目码：行首恰三位数字。
_RECORD_CLASS_RE = re.compile(r"^(3\d\d)")
#: 坐标/形状 tag 字段：字母 + 连续数字（数字天然止于下一字母——紧凑形态
#: ``X01083Y00100X0092S0003`` 逐字段切出）。
_TAG_FIELD_RE = re.compile(r"([XYRSC])(-?\d+)")
#: designator 终界：首个坐标字段（X/Y±数字，含负坐标）或空白。
_DESIGNATOR_END_RE = re.compile(r"[XY]-?\d|\s")
#: designator 首字符合法性（tag 字段起头=无 designator 的紧凑坐标形态）。
_TAG_START_RE = re.compile(r"^[XYRSC]-?\d")
#: % 行（356 旧式 net 名段）：%NETNAME <net> / % <net>；空 % 行=清模态。
_NET_LINE_RE = re.compile(r"^%\s*(\S.*)?$")
#: % 行 NETNAME 关键字前缀（列语义关键词形态）。
_NETNAME_KEYWORD_RE = re.compile(r"^NETNAME\s+(\S+)")


class Ipc356ParseError(ValueError):
    """IPC-D-356 文件级错误（空/无版本行/无任何指纹——区别于流中逐条 fail-soft）。"""


def _warn(warnings: list[str], message: str) -> None:
    """warning 同文去重追加（逐条披露不改据；excellon 家法）。"""
    if message not in warnings:
        warnings.append(message)


def scale_to_mm(raw: int | None, scale_factor: int | None) -> Fraction | None:
    """坐标原始整数 × C 缩放因子 → 精确 mm 值（Fraction；表驱动家法）。

    换算口径（campaign 钉定）：``mm = raw × 100 / scale_factor``——
    已知量钉：C1000000 + 12345 → 1.2345 mm；C100000 + 12345 → 12.345 mm。
    raw 或 scale_factor 缺失（None/≤0）→ None（单位不明不猜）。
    """
    if raw is None or scale_factor is None or scale_factor <= 0:
        return None
    return Fraction(raw * 100, scale_factor)


def _to_mm(value: Fraction | None) -> float | None:
    """Fraction mm → float（9 位舍入，excellon _UnitConv 同款）。"""
    return None if value is None else round(float(value), 9)


class _RecordBody:
    """单条 3xx 记录体的 tag 字段解析（两阶段：tag 扫描 + 剩余裸词）。"""

    def __init__(self, *, rotation_as_shape: bool) -> None:
        # 元件族 R=旋转；焊盘/过孔族 R=矩形形状（记录类目分派语义）。
        self.rotation_as_shape = rotation_as_shape
        self.designator: str | None = None
        self.x_raw: int | None = None
        self.y_raw: int | None = None
        self.hole_raw: int | None = None
        self.rotation: int | None = None
        self.shape: str | None = None
        self.size_raw: int | None = None
        self.midpoint = False
        self.net: str | None = None

    def parse(self, body: str) -> None:
        """tag 字段扫描（首现定语义）+ 剩余裸词（M 标志/net 名）。"""
        consumed: list[tuple[int, int]] = []
        for m in _TAG_FIELD_RE.finditer(body):
            letter, digits = m.group(1), m.group(2)
            val = int(digits)
            consumed.append(m.span())
            if letter == "X":
                if self.x_raw is None:
                    self.x_raw = val
                elif self.hole_raw is None:
                    self.hole_raw = val  # 356A 双 X 字段：第二个=孔径
            elif letter == "Y" and self.y_raw is None:
                self.y_raw = val
            elif letter == "R":
                if self.rotation_as_shape:
                    if self.shape is None:
                        self.shape = SHAPE_KINDS["R"]
                        self.size_raw = val
                elif self.rotation is None:
                    self.rotation = val
            elif letter in ("S", "C") and self.shape is None:
                self.shape = SHAPE_KINDS[letter]
                self.size_raw = val
        # 剩余裸词：tag 字段覆盖区以外的 token。
        leftover = []
        pos = 0
        spans = sorted(consumed)
        pieces = []
        for start, end in spans:
            if start > pos:
                pieces.append(body[pos:start])
            pos = end
        if pos < len(body):
            pieces.append(body[pos:])
        for piece in pieces:
            leftover.extend(piece.split())
        for token in leftover:
            if token in ("M", "m"):
                self.midpoint = True
            elif len(token) == 1:
                continue  # 单字母残渣（病态形态）不冒充 net 名
            elif self.net is None:
                self.net = token


def _split_designator(body: str) -> tuple[str | None, str, bool]:
    """记录体首段 designator 摘除（旗标 X/XT 变体与无旗标双形态）。

    Returns:
        ``(designator, rest, xt_flag)``——designator=None=紧凑坐标起头。
    """
    xt = False
    second = body[1:2]
    if body.startswith("X") and second != "" and not second.isdigit() \
            and second != "-":
        xt = True  # 旗标 X（XT 变体族：XTU1/XT1 等；X-负坐标=非旗标）
        body = body[1:]
        if not body:
            return None, "", xt
    m = _DESIGNATOR_END_RE.search(body)
    name = (body[: m.start()] if m else body).strip()
    rest = body[m.start():] if m else ""
    if xt and name:
        return name, rest, xt  # 旗标形态：旗标后前缀恒为 designator
    if name and not _TAG_START_RE.match(name):
        return name, rest, xt  # 非 tag 形起头 → designator（U1-1/TP1 等）
    if name and m is not None and body[m.start()] == " ":
        return name, rest, xt  # tag 形起头但空白分隔 → designator（R1 X... 形态）
    return None, body, xt  # 紧凑坐标/歧义（R1X02000 无分隔）→ 无 designator


def _refdes_pin(designator: str | None) -> tuple[str | None, str | None]:
    """designator → (refdes, pin) 拆分（``U1-3``/``U1.3`` 形态；无分隔=全 refdes）。"""
    if not designator:
        return None, None
    for sep in ("-", "."):
        if sep in designator:
            refdes, _, pin = designator.rpartition(sep)
            return refdes or None, pin or None
    return designator, None


def parse_ipc356(text: str) -> dict[str, Any]:
    """IPC-D-356/356A 文本 → 结构化文档（确定性、零 IO、fail-soft warnings）。

    Returns:
        doc：``{"schema", "version", "scale_factor", "media",
        "comments", "user_name", "date", "components", "pads", "vias",
        "probes", "nets", "stats", "truncated", "warnings"}``。

    Raises:
        Ipc356ParseError: 空文本 / 无版本行 / 无任何 356 指纹。
    """
    warnings: list[str] = []
    version: str | None = None
    scale_factor: int | None = None
    media: list[str] = []
    comments: list[str] = []
    user_name: str | None = None
    date: str | None = None
    components: list[dict[str, Any]] = []
    pads: list[dict[str, Any]] = []
    vias: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []

    current_net: str | None = None  # % 行模态（356 旧式 net 名段）
    saw_fingerprint = False
    saw_version = False
    ended_seen = False

    lines = text.splitlines()

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()

        # ── 文件尾标记 ────────────────────────────────────────────
        if upper in END_MARKERS:
            saw_fingerprint = True
            ended_seen = True
            break

        # ── 头部参数行（P/C/M/CM/RECORD）──────────────────────────
        vm = _VERSION_RE.match(upper)
        if vm:
            version = vm.group(1)
            saw_version = True
            saw_fingerprint = True
            continue
        cm = _CM_RE.match(upper)
        if cm:
            payload = stripped[2:].strip()
            media.append(payload)
            comments.append(payload)
            saw_fingerprint = True
            continue
        mm = _M_RECORD_RE.match(upper)
        if mm:
            code, payload = mm.group(1), mm.group(2).strip()
            if code == "10":
                user_name = payload or None
            elif code == "20":
                date = payload or None
            else:
                _warn(warnings,
                      f"第 {lineno} 行头部未识别 M{code} 参数，跳过")
            saw_fingerprint = True
            continue
        sm = _SCALE_RE.match(upper)
        if sm:
            val = int(sm.group(1))
            if val > 0:
                if scale_factor is not None and scale_factor != val:
                    _warn(warnings,
                          f"第 {lineno} 行 C 缩放因子重复登记 {val}"
                          f"（首值 {scale_factor} 保留）")
                elif scale_factor is None:
                    scale_factor = val
            else:
                _warn(warnings, f"第 {lineno} 行 C 缩放因子为 0，不生效")
            saw_fingerprint = True
            continue
        if _RECORD_DOC_RE.match(upper):
            media.append(stripped)  # 记录类目文档行（≤3 位 C 码）收编
            saw_fingerprint = True
            continue
        if _RECORD_LINE_RE.match(upper):
            comments.append(stripped)
            saw_fingerprint = True
            continue
        if upper.startswith("C"):
            comments.append(stripped[1:].strip())  # 其余 C 起头=注释行
            saw_fingerprint = True
            continue

        # ── % 行（356 旧式 net 名段）─────────────────────────────
        nm = _NET_LINE_RE.match(stripped)
        if nm:
            payload = (nm.group(1) or "").strip()
            kw = _NETNAME_KEYWORD_RE.match(payload)
            if kw:
                current_net = kw.group(1)
            elif payload:
                current_net = payload.split()[0]
            else:
                current_net = None  # 空 % 行=清模态
            saw_fingerprint = True
            continue

        # ── 3xx 记录体 ───────────────────────────────────────────
        rm = _RECORD_CLASS_RE.match(upper)
        if not rm:
            _warn(warnings, f"第 {lineno} 行未识别语句 {stripped[:40]!r}，跳过")
            continue
        cls = rm.group(1)
        body = stripped[3:].lstrip()
        saw_fingerprint = True

        if cls in COMPONENT_RECORDS:
            name, rest, _xt = _split_designator(body)
            fields = _RecordBody(rotation_as_shape=False)
            fields.parse(rest)
            fields.designator = fields.designator or name
            components.append({
                "record": cls,
                "refdes": fields.designator,
                "x_mm": _to_mm(scale_to_mm(fields.x_raw, scale_factor)),
                "y_mm": _to_mm(scale_to_mm(fields.y_raw, scale_factor)),
                "rotation": fields.rotation,
                "raw": {"x": fields.x_raw, "y": fields.y_raw},
            })
            continue

        if cls in PAD_RECORDS or cls == VIA_RECORD:
            name, rest, _xt = _split_designator(body)
            fields = _RecordBody(rotation_as_shape=True)
            fields.parse(rest)
            fields.designator = fields.designator or name
            if cls == VIA_RECORD:
                refdes = None
                pin = None
            else:
                refdes, pin = _refdes_pin(fields.designator)
            entry = {
                "record": cls,
                "net": fields.net or current_net,
                "refdes": refdes,
                "pin": pin,
                "x_mm": _to_mm(scale_to_mm(fields.x_raw, scale_factor)),
                "y_mm": _to_mm(scale_to_mm(fields.y_raw, scale_factor)),
                "hole_mm": _to_mm(scale_to_mm(fields.hole_raw, scale_factor)),
                "shape": fields.shape,
                "size_raw": fields.size_raw,
                "midpoint": fields.midpoint,
                "raw": {"x": fields.x_raw, "y": fields.y_raw,
                        "hole": fields.hole_raw},
            }
            if cls == VIA_RECORD:
                vias.append(entry)
            else:
                pads.append(entry)
            continue

        if cls == PROBE_RECORD:
            name, rest, _xt = _split_designator(body)
            fields = _RecordBody(rotation_as_shape=False)
            fields.parse(rest)
            probes.append({
                "record": cls,
                "name": fields.designator or name or fields.net,
                "x_mm": _to_mm(scale_to_mm(fields.x_raw, scale_factor)),
                "y_mm": _to_mm(scale_to_mm(fields.y_raw, scale_factor)),
            })
            continue

        _warn(warnings, f"第 {lineno} 行未识别记录类目 {cls}，跳过")

    if not saw_fingerprint:
        raise Ipc356ParseError(
            "不像 IPC-D-356 网表（无 P/C/M/3xx/%/9999 任何指纹）")
    if not saw_version:
        raise Ipc356ParseError("缺 IPC-D-356 版本行（P 2.10 / P 3.00）")
    if scale_factor is None:
        _warn(warnings, "头部无 C 坐标缩放因子，全部坐标 _mm 如实 None")
    if not ended_seen:
        _warn(warnings, "流尾无文件尾标记（9999），truncated=True")

    # nets 映射（net→pad 序号索引）+ 单点 net + 未挂 net 焊盘（DRC 类统计）
    nets: dict[str, list[int]] = {}
    for idx, p in enumerate(pads):
        net = p["net"]
        if net:
            nets.setdefault(net, []).append(idx)
    single_point = sorted(n for n, idxs in nets.items() if len(idxs) == 1)
    unassigned = [
        {"index": idx, "refdes": p["refdes"], "pin": p["pin"],
         "record": p["record"]}
        for idx, p in enumerate(pads) if not p["net"]
    ]

    stats = {
        "n_components": len(components),
        "n_pads": len(pads),
        "n_vias": len(vias),
        "n_probes": len(probes),
        "n_nets": len(nets),
        "single_point_nets": single_point,
        "unassigned_pads": unassigned,
        "n_unassigned_pads": len(unassigned),
        "n_warnings": len(warnings),
    }

    return {
        # 自描述键统一口径（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键。
        "schema": f"ipc356/{PARSER_SCHEMA_VERSION}",
        "version": version,
        "scale_factor": scale_factor,
        "media": media,
        "comments": comments,
        "user_name": user_name,
        "date": date,
        "components": components,
        "pads": pads,
        "vias": vias,
        "probes": probes,
        "nets": nets,
        "stats": stats,
        "truncated": not ended_seen,
        "warnings": warnings,
    }


def _require_net(doc: dict[str, Any], net: str) -> None:
    """未知 net fail-closed（可用名录随异常给出——消费方不猜）。"""
    if net not in (doc.get("nets") or {}):
        available = ", ".join(sorted(doc.get("nets") or {})) or "无"
        raise ValueError(f"net {net!r} 不存在（可用: {available}）")


def ipc356_net_pads(doc: dict[str, Any], net: str) -> list[dict[str, Any]]:
    """net → 全部测试点焊盘（pads 列表子序列按文件序；过孔不混入）。"""
    _require_net(doc, net)
    return [doc["pads"][i] for i in doc["nets"][net]]


def ipc356_component_pins(doc: dict[str, Any], refdes: str) -> list[dict[str, Any]]:
    """refdes → 元件引脚视图（pads 中 refdes 匹配项按文件序）。"""
    known = sorted({p["refdes"] for p in doc.get("pads") or [] if p["refdes"]})
    if refdes not in known:
        raise ValueError(
            f"元件 {refdes!r} 无测试点焊盘（可用: {', '.join(known) or '无'}）")
    return [p for p in doc["pads"] if p["refdes"] == refdes]


def ipc356_single_point_nets(doc: dict[str, Any]) -> list[str]:
    """单点 net 清单（恰 1 个测试点的 net=开路嫌疑，测试语义如实标注）。"""
    return list(doc.get("stats", {}).get("single_point_nets") or [])
