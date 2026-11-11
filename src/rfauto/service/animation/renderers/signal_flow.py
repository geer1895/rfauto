"""signal_flow 渲染器——链路框图信号流向逐级点亮（批 3 图型⑫）。

动画语义：帧 k=拓扑序第 k 个节点点亮（``<set opacity>`` 逐帧计时，帧
语义=信号逐级推进）；指向该节点的边与其**同帧**点亮（源节点必在更早
帧已亮——见拓扑序性质）。

**自动分层布局（声明式几何规则，非数据；独立复算锚在测试）**：

- 分层深度：``depth(u)``=自根（无入边节点）的最长路径边数（Kahn 分层；
  ``depth(v) ≥ depth(u)+1`` 对任意边 u→v 成立——按 (depth, id) 排序即
  合法拓扑序，故边点亮帧=目标节点帧时源必已亮）；存在环/自环时节点
  永不入队→ AnimationDataError 显式报错（链路语义要求 DAG）；
- 层 x 中心：``x_d = box.x0 + box.w·(d+0.5)/(D+1)``（D=最大深度，层左→右）；
- 层内节点按 **id 字典序** 排列（确定性；数据声明序不参与布局消歧），
  层内 y 中心：``y_i = box.y0 + box.h·(i+0.5)/m``（m=该层节点数）；
- 节点盒（全图统一尺寸）：``W = 0.62·box.w/(D+1)``、
  ``H = 0.62·box.h/M``（M=各层节点数最大值）；
- 边：源盒右缘中点 → 目标盒左缘中点直线 + 箭头三角（tip 在目标缘，
  边长 ``ARROW=10`` px，沿方向单位向量×ARROW 回退、垂直向量×ARROW/2
  张开——纯解析几何）。

文本：节点标签（``label`` 直通，缺省回退 id——确定性显示回退）+
``gain_db`` 标注（数据直通 ``G={fmt_num}dB``；None=无标注）——全部
显式 x/y（自检席文字挤压检测钩子契约）。节点填充色按深度层序取调色板
（style.colors 覆盖）。
"""

from __future__ import annotations

import math

from rfauto.service.animation.loaders import ChainDoc, load_chain_json
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    esc,
    fmt_num,
    register_anim_renderer,
    svg_text,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["SignalFlowRenderer", "layer_depths"]

_CHART_TYPE = "signal_flow"

#: 节点盒宽/高占层距/层高比例（固定布局常量）
BOX_W_FRAC = 0.62
BOX_H_FRAC = 0.62

#: 箭头边长 px（固定几何）
ARROW = 10.0

EDGE_COLOR = "#555555"


def layer_depths(n_nodes: int, edges: list[tuple[int, int]]) -> list[int]:
    """Kahn 分层：节点数+边（索引对 u→v）→ 每节点 depth（根=0）。

    Raises:
        ValueError: 存在环/自环（节点无法全部出队）——链路语义要求 DAG，
            调用方（渲染器）先经 load_chain_json 校验引用合法性，环在此
            以显式异常暴露（渲染器转 AnimationDataError 带指引）。
    """
    outgoing: list[list[int]] = [[] for _ in range(n_nodes)]
    indeg = [0] * n_nodes
    for u, v in edges:
        if u == v:
            raise ValueError(f"自环（节点 {u}）——链路语义要求 DAG")
        outgoing[u].append(v)
        indeg[v] += 1
    depth = [-1] * n_nodes
    queue = [i for i in range(n_nodes) if indeg[i] == 0]
    for i in queue:
        depth[i] = 0
    processed = 0
    while queue:
        u = queue.pop()
        processed += 1
        for v in outgoing[u]:
            depth[v] = max(depth[v], depth[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    if processed != n_nodes:
        raise ValueError(
            f"边集含环（{n_nodes - processed} 个节点无法定层）——链路语义"
            "要求 DAG，请修数据源")
    return depth


@register_anim_renderer(_CHART_TYPE)
class SignalFlowRenderer(AnimRenderer):
    """信号流向逐级点亮渲染器（单 chain_json 源，分层布局逐帧推进）。"""

    chart_type = _CHART_TYPE

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）")
        if sources[0].kind != "chain_json":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 chain_json（收到 "
                f"{sources[0].kind!r}）——级联级表归 nf_cascade，S 参数源归 "
                "sparam_evolution")
        doc: ChainDoc = load_chain_json(sources[0].path)
        return self._plan(spec, doc)

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, doc: ChainDoc) -> RenderPlan:
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        idx = {node.id: i for i, node in enumerate(doc.nodes)}
        edge_pairs = [(idx[e.from_id], idx[e.to_id]) for e in doc.edges]
        try:
            depth = layer_depths(len(doc.nodes), edge_pairs)
        except ValueError as exc:
            from rfauto.service.animation.loaders import AnimationDataError
            raise AnimationDataError(
                f"{doc.source_path} {exc}——signal_flow 按层推进点亮，"
                "环状链路无拓扑序") from exc
        d_max = max(depth)
        # 层内按 id 字典序（确定性）；(depth,id) 排序=点亮拓扑序
        order = sorted(range(len(doc.nodes)), key=lambda i: (depth[i],
                                                             doc.nodes[i].id))
        by_layer: dict[int, list[int]] = {}
        for i in order:
            by_layer.setdefault(depth[i], []).append(i)
        m_max = max(len(v) for v in by_layer.values())
        node_w = BOX_W_FRAC * box.w / (d_max + 1)
        node_h = BOX_H_FRAC * box.h / m_max
        centers: dict[int, tuple[float, float]] = {}
        for d, members in by_layer.items():
            cx_d = box.x0 + box.w * (d + 0.5) / (d_max + 1)
            for pos, i in enumerate(members):
                cy_i = box.y0 + box.h * (pos + 0.5) / len(members)
                centers[i] = (cx_d, cy_i)

        dur = self.duration_for(spec, len(doc.nodes))
        begins = [f"{k * dur / len(doc.nodes):.6f}s"
                  for k in range(len(doc.nodes))]
        colors = spec.style.colors or PALETTE

        def edge_group(ei: int, begin: str) -> str:
            e = doc.edges[ei]
            x1, y1 = centers[idx[e.from_id]]
            x2, y2 = centers[idx[e.to_id]]
            sx, sy = x1 + node_w / 2.0, y1
            tx, ty = x2 - node_w / 2.0, y2
            dx, dy = tx - sx, ty - sy
            ln = math.hypot(dx, dy) or 1.0
            ux, uy = dx / ln, dy / ln
            px_, py_ = -uy, ux
            bx, by = tx - ux * ARROW, ty - uy * ARROW
            arrow = (f'<polygon points="{fmt_num(tx)},{fmt_num(ty)} '
                     f'{fmt_num(bx + px_ * ARROW / 2.0)},'
                     f'{fmt_num(by + py_ * ARROW / 2.0)} '
                     f'{fmt_num(bx - px_ * ARROW / 2.0)},'
                     f'{fmt_num(by - py_ * ARROW / 2.0)}" '
                     f'fill="{EDGE_COLOR}"/>')
            content = (f'<line x1="{fmt_num(sx)}" y1="{fmt_num(sy)}" '
                       f'x2="{fmt_num(bx)}" y2="{fmt_num(by)}" '
                       f'stroke="{EDGE_COLOR}" stroke-width="1.5"/>{arrow}')
            return (f'<g opacity="0"><set attributeName="opacity" to="1" '
                    f'begin="{begin}"/>{content}</g>')

        def node_group(i: int, begin: str) -> str:
            node = doc.nodes[i]
            cx, cy = centers[i]
            color = colors[depth[i] % len(colors)]
            x = cx - node_w / 2.0
            y = cy - node_h / 2.0
            parts = [f'<rect x="{fmt_num(x)}" y="{fmt_num(y)}" '
                     f'width="{fmt_num(node_w)}" height="{fmt_num(node_h)}" '
                     f'fill="{esc(color)}" fill-opacity="0.18" '
                     f'stroke="{esc(color)}" stroke-width="1.5" rx="4"/>']
            label = node.label if node.label is not None else node.id
            if node.gain_db is None:
                parts.append(svg_text(cx, cy + spec.style.font_size * 0.35,
                                      label, size=spec.style.font_size,
                                      anchor="middle", fill="#222222",
                                      weight="bold"))
            else:
                parts.append(svg_text(cx, cy - spec.style.font_size * 0.2,
                                      label, size=spec.style.font_size,
                                      anchor="middle", fill="#222222",
                                      weight="bold"))
                parts.append(svg_text(cx, cy + spec.style.font_size * 1.05,
                                      f"G={fmt_num(node.gain_db)}dB",
                                      size=spec.style.font_size - 1,
                                      anchor="middle", fill="#555555"))
            return (f'<g opacity="0"><set attributeName="opacity" to="1" '
                    f'begin="{begin}"/>{"".join(parts)}</g>')

        out: list[str] = []
        for k, i in enumerate(order):
            for ei, e in enumerate(doc.edges):
                if idx[e.to_id] == i:
                    out.append(edge_group(ei, begins[k]))
            out.append(node_group(i, begins[k]))
        body = "".join(out)
        summary = {"kind": "chain_json", "path": doc.source_path,
                   "n_nodes": len(doc.nodes), "n_edges": len(doc.edges),
                   "depths": {doc.nodes[i].id: depth[i]
                              for i in sorted(range(len(doc.nodes)),
                                              key=lambda j: doc.nodes[j].id)},
                   "light_order": [doc.nodes[i].id for i in order]}
        return RenderPlan(frame_count=len(doc.nodes), body=body,
                          data_sources=(summary,), duration_s=dur)
