"""RF 链路框图 .drawio 生成器（"算画同源"——图上数字全部来自确定性内核）。

XML 装配内核（T-O2 抽取，2026-11-01）：本模块的 mxGraph XML 骨架装配
（文档结构/cell 基座/几何与连线语义/ET.indent/确定性）已抽取为通用内核
:mod:`rfauto.core.drawio_xml`（:class:`~rfauto.core.drawio_xml.DrawioDocument`
写面 + ``read_diagram`` read 面）——叠层图（T-O3）/ADS 前仿链（T-O4）/
测试连接图（T-O6）/评审标注（T-O8）一律走该内核，本模块只保留 link 语义
（布局常量/级标签文本/Friis 数字消费）。抽取门 = 本模块既有 26 钉测试
零改动全绿（XML 输出逐字节不变）。

XML 格式出处（实读 2026-10-31，T-O1 席；详录 core/drawio_xml.py docstring）：
- .drawio / mxGraph XML 格式为开放规范（JGraph mxGraph/drawio，Apache-2.0；
  格式结构实读 docs.fileformat.com/web/drawio 与 jgraph/drawio 开源仓）：
  ``mxfile > diagram > mxGraphModel > root > mxCell``——root 恒含 ``id="0"``
  与 ``id="1" parent="0"`` 两个基 cell；
  - vertex 形态：``vertex="1" parent="1"`` + 子元素
    ``<mxGeometry x= y= width= height= as="geometry"/>``；
  - edge 形态：``edge="1" parent="1" source=<id> target=<id>`` + 子元素
    ``<mxGeometry relative="1" as="geometry"/>``。
- 产物为未压缩原生 mxfile XML，draw.io 桌面/网页版与 VS Code Draw.io
  插件可直接打开编辑（非截图、原生可编辑工程图）。
- 许可红线：装配内核为自研 ElementTree XML 装配器，零第三方依赖、零复制
  （AGPL-3.0 的 drawio-engineering-mcp 等工具代码不看不抄；mxGraph XML
  格式本身开放，装配自写合法）。

数字单源（铁律 7：数值只在确定性内核）：
- 每级增益/NF 与级联累计（Friis 公式）全部来自 core/budget.py::LinkBudget
  （E8c 链路预算引擎，教科书 Friis 级联
  ``F_tot = F1 + (F2−1)/G1 + (F3−1)/(G1G2) + …``，逐级
  cumulative_gain_db / cumulative_nf_db + cascade 总量）——本模块零公式
  逻辑，只做"内核数值 → 确定性文本"渲染；
- dB 数值文本格式化单源 = :func:`format_db`（XML 装配与测试断言消费同一
  函数，图内数字与内核计算值逐位一致可断言）。

确定性：同输入两次调用 XML 逐字节相同——cell id 按索引生成
（``stage0/edge0/…``，禁 uuid）、无时间戳、ElementTree 属性序=插入序。

零 IO（纯函数返回 XML 字符串；落盘在 service 层）、零第三方依赖
（仅 xml.etree/math 标准库 + 同层 core.budget）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.budget import BudgetResult, LinkBudget, StageResult
from rfauto.core.drawio_xml import new_document

__all__ = [
    "build_link_diagram_xml",
    "compute_link_chain",
    "format_db",
    "normalize_chain",
]

#: dB 数值文本精度（固定位小数——确定性渲染，禁随 repr 长尾漂移）
_DB_DECIMALS = 2

#: 几何常量（px；水平链式布局，从左到右=信号流向）
_MARGIN_X = 40
_MARGIN_Y = 60
_BOX_W = 180
_BOX_H = 72
_GAP_X = 60
_STEP_X = _BOX_W + _GAP_X
_SUMMARY_W = 220
_TITLE_Y = 20
_TITLE_W = 420
_TITLE_H = 26

#: |gain_db|/nf_db 上界（防 10**(dB/10) 线性域溢出产生 inf/nan 的守卫，
#: 与 core/cascade.py MAX_ABS_GAIN_DB 同量级口径）
_MAX_ABS_GAIN_DB = 1000.0
_MAX_NF_DB = 1000.0

_STAGE_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
_SUMMARY_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"
_TITLE_STYLE = ("text;html=1;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1")
_EDGE_STYLE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
               "jettySize=auto;html=1;")


def _finite(value: Any, name: str) -> float:
    """收敛入参为有限实数，否则 ValueError（bool 不算数——bool 是 int 子类）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def format_db(value: float) -> str:
    """dB 数值 → 固定精度文本（格式化单源：XML 装配与测试断言同函数）。"""
    return f"{float(value):.{_DB_DECIMALS}f}"


def normalize_chain(chain: Any) -> list[dict[str, Any]]:
    """校验并归一链表（顺序=信号流向）；非法入参显式 ValueError（不静默）。

    级 schema（严格三键，多余键显式拒绝防手误静默忽略）::

        {"name": str(非空), "gain_db": 有限实数, "nf_db": 有限实数(≥0)}

    负例（均显式报错）：空链/非列表、级非 dict、缺键、多余键、name 空、
    gain/nf 非有限、nf_db<0（Friis 噪声因子 F=10^(NF/10)<1 非物理）、
    |gain_db|>1000 / nf_db>1000（线性域溢出守卫，同 core/cascade.py 口径）。
    """
    if not isinstance(chain, (list, tuple)) or len(chain) == 0:
        raise ValueError("chain 必须是非空链表（按信号流向排序）")
    norm: list[dict[str, Any]] = []
    for i, raw in enumerate(chain):
        if not isinstance(raw, dict):
            raise ValueError(f"chain[{i}] 必须是 dict，收到 {type(raw)!r}")
        extra = set(raw) - {"name", "gain_db", "nf_db"}
        if extra:
            raise ValueError(
                f"chain[{i}] 存在未支持键 {sorted(extra)}；"
                "级 schema 严格三键 name/gain_db/nf_db")
        for key in ("name", "gain_db", "nf_db"):
            if key not in raw or raw[key] is None:
                raise ValueError(f"chain[{i}] 缺必填键 {key!r}")
        name = raw["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"chain[{i}].name 必须是非空字符串，收到 {name!r}")
        gain_db = _finite(raw["gain_db"], f"chain[{i}].gain_db")
        nf_db = _finite(raw["nf_db"], f"chain[{i}].nf_db")
        if abs(gain_db) > _MAX_ABS_GAIN_DB:
            raise ValueError(
                f"chain[{i}].gain_db 绝对值必须 ≤ {_MAX_ABS_GAIN_DB:.0f}，"
                f"收到 {gain_db!r}")
        if nf_db < 0.0:
            raise ValueError(
                f"chain[{i}].nf_db 必须 ≥ 0（Friis 噪声因子 F=10^(NF/10)<1 "
                f"非物理），收到 {nf_db!r}")
        if nf_db > _MAX_NF_DB:
            raise ValueError(
                f"chain[{i}].nf_db 必须 ≤ {_MAX_NF_DB:.0f}，收到 {nf_db!r}")
        norm.append({"name": name, "gain_db": gain_db, "nf_db": nf_db})
    return norm


def compute_link_chain(chain: Any) -> dict[str, Any]:
    """链表 → 内核级联数字面（Friis 单源 core/budget.py::LinkBudget）。

    Returns:
        dict：``stages``（逐级 name/gain_db/nf_db + cumulative_gain_db/
        cumulative_nf_db）、``cascade_gain_db``/``cascade_nf_db``（链路
        累计，Friis 公式）。数值全部为 LinkBudget 内核产出，本函数零公式。
    """
    norm = normalize_chain(chain)
    budget = LinkBudget()
    for st in norm:
        budget.add_stage(st["name"], gain_db=st["gain_db"], nf_db=st["nf_db"])
    result: BudgetResult = budget.compute()
    stage_views: list[dict[str, Any]] = []
    s: StageResult
    for s in result.stages:
        stage_views.append({
            "name": s.name,
            "gain_db": s.gain_db,
            "nf_db": s.nf_db,
            "cumulative_gain_db": s.cumulative_gain_db,
            "cumulative_nf_db": s.cumulative_nf_db,
        })
    return {
        "stages": stage_views,
        "cascade_gain_db": result.cascade_gain_db,
        "cascade_nf_db": result.cascade_nf_db,
    }


def _stage_label(st: dict[str, Any]) -> str:
    """级框三行文本：级名 / 本级 G·NF / 该级之后级联累计 ΣG·ΣNF（内核值）。"""
    return (
        f"{st['name']}\n"
        f"G={format_db(st['gain_db'])} dB  NF={format_db(st['nf_db'])} dB\n"
        f"ΣG={format_db(st['cumulative_gain_db'])} dB  "
        f"ΣNF={format_db(st['cumulative_nf_db'])} dB")


def build_link_diagram_xml(chain: Any, *, title: str | None = None) -> str:
    """链表 → 完整 .drawio XML 文本（未压缩原生 mxfile，逐字节确定性）。

    布局：标题文本 + 水平链式级框（每级三行=级名/本级 G·NF/级联累计
    ΣG·ΣNF）+ 级间连线箭头 + 链尾级联总计框（Friis）。数字全部来自
    :func:`compute_link_chain`（内核单源，见模块 docstring）。

    Args:
        chain: 级表（schema 见 :func:`normalize_chain`）。
        title: 图标题文本（None 用缺省标题）。

    Raises:
        ValueError: 链表非法（空链/级 schema 违约/非有限数值等，显式报错）。
    """
    norm = normalize_chain(chain)
    computed = compute_link_chain(norm)
    stages = computed["stages"]

    # XML 骨架装配走通用内核 core/drawio_xml.py（T-O2 抽取——结构/基 cell/
    # 页面属性缺省/缩进/逐字节确定性都在内核；本函数只给 link 语义图元）
    doc = new_document(diagram_id="link-diagram", diagram_name="RF Link")

    # 标题（纯文本 vertex）
    title_text = title if title else "RF 链路框图（级联 Friis，数字=内核单源）"
    doc.add_vertex("title", title_text, style=_TITLE_STYLE,
                   x=_MARGIN_X, y=_TITLE_Y, width=_TITLE_W, height=_TITLE_H)

    # 级框（vertex：每 cell 必带 mxGeometry x/y/w/h）
    for i, st in enumerate(stages):
        doc.add_vertex(f"stage{i}", _stage_label(st), style=_STAGE_STYLE,
                       x=_MARGIN_X + i * _STEP_X, y=_MARGIN_Y,
                       width=_BOX_W, height=_BOX_H)

    # 级联总计框（链尾；Friis 累计=内核值）
    doc.add_vertex(
        "cascade",
        ("级联总计（Friis）\n"
         f"ΣG={format_db(computed['cascade_gain_db'])} dB  "
         f"ΣNF={format_db(computed['cascade_nf_db'])} dB"),
        style=_SUMMARY_STYLE,
        x=_MARGIN_X + len(stages) * _STEP_X, y=_MARGIN_Y,
        width=_SUMMARY_W, height=_BOX_H)

    # 连线箭头：stage_i→stage_{i+1} + 末级→总计框（edge：source/target 必带；
    # 悬空引用由内核 to_xml 守卫）
    chain_ids = [f"stage{i}" for i in range(len(stages))] + ["cascade"]
    for i in range(len(chain_ids) - 1):
        doc.add_edge(f"edge{i}", "", style=_EDGE_STYLE,
                     source=chain_ids[i], target=chain_ids[i + 1])

    return doc.to_xml()
