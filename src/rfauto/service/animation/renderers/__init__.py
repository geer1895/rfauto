"""动图渲染器子包——import 期自注册全部内建图型（注册表契约）。

批 1：四内建图型（sparam_evolution/smith_trajectory/param_race/fit_compare）。
批 2（Q-W2-2 席）：决策②清单第 5-8 项（field_heatmap/before_after/
structure_explode/vswr_history）在此追加模块+``@register_anim_renderer``
装饰器即入注册表；消费面只走 :func:`base.get_anim_renderer`。
批 3（Q-W2-3 席）：决策②清单第 10-13 项（nf_cascade/pattern_scan/
filter_morphing/signal_flow）同款自注册。
批 4（Q-W2-4 席）：决策②清单第 13-16 项（stackup_growth/tuning_replay/
constellation_eye/budget_funnel）同款自注册。
Q-R3R 遗留清偿席：cfc_state（CfC 隐态轨迹，Q-W4-1 登记"隐态从没画过"
的动画出口）同款自注册——import 期挂载进注册表；``__all__`` 有意不收
（公开面快照 tests/gold/public_api.json 本席冻结，收编=显式评审动作，
留后续席位 ``--generate`` 重钉）。
"""

from rfauto.service.animation.renderers import (
    base,
    before_after,
    budget_funnel,
    cfc_state,  # noqa: F401  (registration side effect; __all__ 冻结见头注)
    constellation_eye,
    field_heatmap,
    filter_morphing,
    fit_compare,
    nf_cascade,
    param_race,
    pattern_scan,
    signal_flow,
    smith_trajectory,
    sparam_evolution,
    stackup_growth,
    structure_explode,
    tuning_replay,
    vswr_history,
)

__all__ = [
    "base",
    "before_after",
    "budget_funnel",
    "constellation_eye",
    "field_heatmap",
    "filter_morphing",
    "fit_compare",
    "nf_cascade",
    "param_race",
    "pattern_scan",
    "signal_flow",
    "smith_trajectory",
    "sparam_evolution",
    "stackup_growth",
    "structure_explode",
    "tuning_replay",
    "vswr_history",
]
