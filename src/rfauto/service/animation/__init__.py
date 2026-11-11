"""rfauto.service.animation —— typed spec→SVG 动画内核（T-Q3 批 1）。

公开 API（后续席位消费面；规则 3 基类+注册表，新图型在 renderers/ 注册）：

- :func:`render_animation` —— spec（dict|AnimationSpec）→
  :class:`AnimationResult`（svg_str+sha256+chart_type+frame_count+
  duration_s+data_sources 摘要+warnings）；``self_check=True`` 时返回
  :class:`AnimationSelfCheckedResult`（附 :class:`AnimationSelfCheckReport`
  产物体检报告——结构/帧序 error 级+文字挤压 warn 级，缺省 False=零变化）；
- :class:`AnimationSpec` / :func:`parse_animation_spec` —— typed spec
  （schema 定稿见 spec 模块 docstring；后续 12 图型只增不改）；
- :class:`AnimationDataError` / :class:`AnimationSpecError` /
  :class:`AnimationError` —— 显式异常族（缺数据带指引文案，禁静默画空图）；
- loaders —— 数据源加载契约（sparams_csv/snip/trials/anchor_json；批 2
  field_dump/layout_json；批 3 cascade_json/nf2ff_cut/chain_json；批 4
  symbols_json/budget_json；Q-R3R 遗留清偿席 cfc_state——CfC 隐态轨迹，
  loaders.load_cfc_state）；
- renderers.base —— AnimRenderer 基类+注册表（register_anim_renderer/
  get_anim_renderer/available_chart_types）+SVG 公共件。

数据源纪律（红线）：全部数字只从确定性数据源（run 湖/仿真产物/锚点 JSON）
读出，零示意数据；渲染零算术改写（坐标映射/幅值口径等确定性显示变换除
外，逐渲染器 docstring 声明）。同 spec 两跑逐字节同（sha256 钉）。
"""

# 渲染器子包 import 期自注册（必须在 base 之后；顺序=内建图型全集）
from rfauto.service.animation import renderers  # noqa: F401  (registration side effect)
from rfauto.service.animation.loaders import (
    AnimationDataError,
    BudgetDoc,
    BudgetStage,
    CascadeDoc,
    CascadeStage,
    ChainDoc,
    ChainEdge,
    ChainNode,
    FieldFrame,
    FieldFrames,
    LayoutDoc,
    LayoutLayer,
    PatternCut,
    PatternCutSeries,
    Primitive,
    SparamsTable,
    SymbolFrame,
    SymbolsDoc,
    TrialRecord,
    load_anchor_json,
    load_budget_json,
    load_cascade_json,
    load_chain_json,
    load_field_frames,
    load_layout_json,
    load_nf2ff_cut,
    load_snip,
    load_sparams_csv,
    load_symbols_json,
    load_trials,
)
from rfauto.service.animation.renderers import base  # noqa: F401  (re-export)
from rfauto.service.animation.renderers.base import (
    ANIM_RENDERER_REGISTRY,
    AnimationResult,
    AnimationSelfCheckedResult,
    AnimationSelfCheckReport,
    AnimRenderer,
    RenderPlan,
    SelfCheckIssue,
    available_chart_types,
    detect_frame_order,
    detect_text_overlap,
    get_anim_renderer,
    register_anim_renderer,
    render_animation,
    run_animation_self_check,
    verify_svg_structure,
)
from rfauto.service.animation.spec import (
    AnimationError,
    AnimationSpec,
    AnimationSpecError,
    AnimationTiming,
    CanvasSpec,
    SourceSpec,
    StyleSpec,
    parse_animation_spec,
)

__all__ = [
    "ANIM_RENDERER_REGISTRY",
    "AnimRenderer",
    "AnimationDataError",
    "AnimationError",
    "AnimationResult",
    "AnimationSelfCheckReport",
    "AnimationSelfCheckedResult",
    "AnimationSpec",
    "AnimationSpecError",
    "AnimationTiming",
    "BudgetDoc",
    "BudgetStage",
    "CanvasSpec",
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
    "RenderPlan",
    "SelfCheckIssue",
    "SourceSpec",
    "SparamsTable",
    "StyleSpec",
    "SymbolFrame",
    "SymbolsDoc",
    "TrialRecord",
    "available_chart_types",
    "detect_frame_order",
    "detect_text_overlap",
    "get_anim_renderer",
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
    "parse_animation_spec",
    "register_anim_renderer",
    "render_animation",
    "run_animation_self_check",
    "verify_svg_structure",
]
