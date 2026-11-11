"""动图内核 typed spec（T-Q3 批 1，aurora_q Q-W2-1 席）。

声明式 JSON spec → 校验后的 :class:`AnimationSpec`（pydantic v2，仓内
contracts.py 同构惯例）。渲染器按 ``chart_type`` 从注册表分派（规则 3
基类+注册表，照 EMSolverAdapter/EMSolverRegistry 先例）。

Spec schema 定稿（后续 12 图型照此扩展，只增不改）::

    {
      "chart_type": "sparam_evolution",        # 渲染器注册键（必填）
      "title": "可选标题",                      # 缺省 ""（无标题行）
      "canvas": {"width": 960, "height": 540}, # 像素，200..4096
      "style": {                                # 全部可选
        "colors": ["#1f77b4", ...],   # 系列色（按序消费，超出回退内建调色板）
        "font_size": 13,              # 8..72
        "stroke_width": 2.0,          # 0.1..10.0
        "background": "#ffffff",
        "labels": ["measured", ...],  # param_race/fit_compare 系列名覆盖
        "y_mode": "db" | "linear",    # 幅值纵轴口径（缺省 db=20*log10|S|）
        "grid_r": [0.2, 0.5, 1, 2, 5],    # smith 常数电阻圆（缺省同左）
        "grid_x": [-5, -2, -1, -0.5, 0.5, 1, 2, 5]  # smith 常数电抗弧
      },
      "source":  {"kind": "...", "path": "...", "columns": [...], "ports": [...]},
      "sources": [ {...}, {...} ],    # 与 source 二选一（多源图型：race/fit/steps）
      "animation": {"fps": 8, "duration_s": 4.0}   # 全部可选；duration_s 优先
    }

source.kind 词表（loaders.py 单源）：

- ``sparams_csv``：run 湖 sparams.csv（``freq_hz,re_S11,im_S11,...`` 表头），
  ``columns`` 选 S 参数名（如 ``["S11","S21"]``，缺省=全部，sorted 序）；
- ``snip``：Touchstone sNp（skrf 读入），``columns``/``ports``（1 基端口
  号集合，限制端口对）同上语义；
- ``trials``：run 目录（读 ``trials/trial_*.json``，sorted）/单 trial
  JSON/JSON 数组——每条须含 ``trial_number``/``params``/``cost``
  （rfauto trial 落盘惯例）；
- ``anchor_json``：锚点/导出 JSON（原始 dict 透传给渲染器按图型提取，
  smith=``{"points":[{"re","im"},...]}``，fit_compare=``{"series":{"x","y"}}``）；
- ``field_dump``（批 2）：场帧序列 JSON（单文件 ``{"axes":{...},"frames":
  [{"meta":{...},"values":[[...行...]]},...]}``）或目录（``frame_*.json``
  sorted 逐帧+可选 ``axes.json``）——场热力演进数据源；
- ``layout_json``（批 2）：图元坐标序列 ``{"layers":[{"name":...,
  "primitives":[{"shape","x","y","w","h"},...]}]}``——结构爆炸数据源；
- ``cascade_json``（批 3）：级联级表 ``{"stages":[{"name"?,"gain_db",
  "nf_db"},...]}``——NF 瀑布数据源（gain_db/nf_db 对齐 core/cascade 级表
  语义）；Friis 累计=渲染端声明式派生（nf_cascade docstring）；
- ``nf2ff_cut``（批 3）：方向图切面序列 ``{"cuts":[{"theta_deg":[...],
  "db"|"pattern_db":[...],...}]}``——pattern_scan 数据源（``pattern_db``
  键名对齐 nf2ff_service farfield_view 产物）；
- ``chain_json``（批 3）：链路框图 ``{"nodes":[{"id","label"?,"gain_db"?},
  ...],"edges":[{"from","to"},...]}``——signal_flow 数据源（对齐
  cascade/active_chain 节点语义）；
- ``symbols_json``（批 4）：数字调制符号序列 ``{"symbols":[[i,q],...]}``
  或帧序列 ``{"frames":[{"symbols":[[i,q],...]},...]}``（恰一形态）——
  constellation_eye 数据源（si_channel 面无既有产物，最小 JSON 约定）；
- ``budget_json``（批 4）：链路预算级表 ``{"stages":[{"name"?,"value_db"},
  ...]}``——budget_funnel 数据源（与 cascade_json 同构，语义=预算扣减
  负值累计；最小 JSON 约定）；
- ``cfc_state``（Q-R3R 遗留清偿席）：CfC 隐态轨迹 ``{"hidden":[[H 值]/
  step,...],"time"?:[...],"hidden_dim"?}``——cfc_state 渲染器数据源（产出
  面=lnn_cfc.hidden_state_doc/LnnCfcSurrogate.hidden_states + service/
  lnn_cfc_export_service.export_cfc_hidden_states，Q-W4-1 遗留"隐态轨迹
  从未持久化"的落盘出口；读取契约 loaders.load_cfc_state）。

tuning_replay（批 4）复用既有 **trials+sparams 双源**形态（sources 恰 2：
一个 trials + 一个 sparams_csv/snip，按 kind 定角色——fit_compare 多源
先例，spec 零扩展）；stackup_growth（批 4）复用既有 ``layout_json`` 单源。

filter_morphing（批 3）复用 ``sparams_csv``/``snip`` **多源**形态（同
sparam_evolution steps 模式：sources≥2+同栅+同列集）。

数据源纪律（红线）：全部数字只从确定性数据源读出——spec 声明路径，渲染
零算术改写（坐标映射/幅值口径等确定性变换除外，逐渲染器 docstring 声明）；
缺数据→ :class:`AnimationDataError` 显式报错（禁静默画空图）；零示意数据。

确定性：同 spec 两跑逐字节同（sha256 钉）——禁 datetime.now/locale/dict
迭代序依赖（全部 sorted），SVG 纯手写（禁 matplotlib）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "AnimationError",
    "AnimationSpec",
    "AnimationSpecError",
    "AnimationTiming",
    "CanvasSpec",
    "SourceSpec",
    "StyleSpec",
]

#: source.kind 词表（loaders.py 消费；新数据源在 loaders 加载函数同步登记）
SOURCE_KINDS = ("sparams_csv", "snip", "trials", "anchor_json",
                "field_dump", "layout_json",
                "cascade_json", "nf2ff_cut", "chain_json",
                "symbols_json", "budget_json", "cfc_state")


class AnimationError(Exception):
    """动图管线异常基类（spec 违约与数据缺失两子类）。"""


class AnimationSpecError(AnimationError, ValueError):
    """spec 违约（未知键/缺必填/图型未注册/源数量不合）——显式报错不猜。"""


class CanvasSpec(BaseModel):
    """画幅（像素；viewBox 同值，SVG 无缩放歧义）。"""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(default=960, ge=200, le=4096)
    height: int = Field(default=540, ge=200, le=4096)


class StyleSpec(BaseModel):
    """风格面（全部可选；键集只增不改——后续图型按需加新可选键）。"""

    model_config = ConfigDict(extra="forbid")

    colors: list[str] | None = Field(default=None, min_length=1)
    font_size: int = Field(default=13, ge=8, le=72)
    stroke_width: float = Field(default=2.0, gt=0.1, le=10.0)
    background: str = "#ffffff"
    labels: list[str] | None = Field(default=None, min_length=1)
    y_mode: Literal["db", "linear"] | None = None
    grid_r: list[float] | None = Field(default=None, min_length=1)
    grid_x: list[float] | None = Field(default=None, min_length=1)
    # ── 批 2 新增可选键（只增不改；batch2 Q-W2-2 席）────────────────────────
    #: field_heatmap：色标映射内建名（"iron"|"grayscale"|"coolwarm"；None=iron）
    colormap: Literal["iron", "grayscale", "coolwarm"] | None = None
    #: field_heatmap：是否画色标条（None=True）
    colorbar: bool | None = None
    #: field_heatmap：色标条标题（None=无标题行）
    colorbar_label: str | None = None
    #: structure_explode：逐层拆解间距 px（None=按层序自动等距，声明式公式见
    #: structure_explode 渲染器 docstring）；显式给出时第 k 层偏移=k×本值
    explode_gap: float | None = Field(default=None, gt=0.0, le=2000.0)
    # ── 批 3 新增可选键（只增不改；batch3 Q-W2-3 席）────────────────────────
    #: pattern_scan：极坐标径向 dB 跨度（外环=数据全局最大 dB，内环=
    #: 最大值−本值；None=40.0 缺省，声明式映射见 pattern_scan docstring）
    dynamic_range: float | None = Field(default=None, gt=0.0, le=200.0)
    # ── 批 4 新增可选键（只增不改；batch4 Q-W2-4 席）────────────────────────
    #: constellation_eye：眼图轨迹窗宽 W（当前帧向前取 W 个符号连折线；
    #: None=8 缺省，窗滑动语义见 constellation_eye docstring）
    eye_window: int | None = Field(default=None, ge=2, le=1000)


class SourceSpec(BaseModel):
    """单数据源声明（kind+路径+可选列/端口裁剪；加载契约见 loaders.py）。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sparams_csv", "snip", "trials", "anchor_json",
                  "field_dump", "layout_json",
                  "cascade_json", "nf2ff_cut", "chain_json",
                  "symbols_json", "budget_json", "cfc_state"]
    path: str = Field(min_length=1)
    columns: list[str] | None = Field(default=None, min_length=1)
    ports: list[int] | None = Field(default=None, min_length=1)


class AnimationTiming(BaseModel):
    """动画时序：帧时长=duration_s/N 帧；缺省 fps=8（duration_s 优先）。"""

    model_config = ConfigDict(extra="forbid")

    fps: int = Field(default=8, ge=1, le=60)
    duration_s: float | None = Field(default=None, gt=0.0, le=600.0)


class AnimationSpec(BaseModel):
    """动图 spec 根对象（schema 全文见本模块 docstring）。"""

    model_config = ConfigDict(extra="forbid")

    chart_type: str = Field(min_length=1)
    title: str = ""
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    style: StyleSpec = Field(default_factory=StyleSpec)
    source: SourceSpec | None = None
    sources: list[SourceSpec] | None = None
    animation: AnimationTiming = Field(default_factory=AnimationTiming)

    def resolve_sources(self) -> list[SourceSpec]:
        """source/sources 二选一归一为列表（互斥违约显式报错，不猜）。"""
        has_single = self.source is not None
        has_multi = self.sources is not None
        if has_single and has_multi:
            raise AnimationSpecError(
                "spec.source 与 spec.sources 互斥，二选一；多源图型用 sources 列表")
        if not has_single and not has_multi:
            raise AnimationSpecError(
                "spec 缺数据源：单源图型给 source，多源图型给 sources 列表"
                "（schema 见 rfauto.service.animation.spec 模块 docstring）")
        if has_multi and not self.sources:
            raise AnimationSpecError("spec.sources 不能是空列表")
        return [self.source] if has_single else list(self.sources)


def parse_animation_spec(data: AnimationSpec | dict[str, Any]) -> AnimationSpec:
    """dict/实例 → :class:`AnimationSpec`（ValidationError 收敛为
    AnimationSpecError，文案含 pydantic 逐键明细——显式报错不静默）。"""
    if isinstance(data, AnimationSpec):
        return data
    if not isinstance(data, dict):
        raise AnimationSpecError(
            f"spec 必须是 dict 或 AnimationSpec，收到 {type(data).__name__}")
    try:
        return AnimationSpec.model_validate(data)
    except ValidationError as exc:
        raise AnimationSpecError(f"spec 校验失败：{exc}") from exc
