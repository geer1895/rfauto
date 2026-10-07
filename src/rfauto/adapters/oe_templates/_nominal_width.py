"""50Ω 标称线宽渲染层单源（XC-W，2026-10-02）。

月度宏图 §10.1 弱点 6「50Ω 宽常数四系」的渲染缺省面收敛点：各模板
``params.get(..., 1.1134/1.113)`` 字面量缺省历史上散落（render_core/grid/
render_tl/render_antenna2/render_msl_sma/render_ratrace_cyl 共 30+ 席），
本模块收敛为对 core/synthesis.nominal_width_mm 的两个标准档引用：

- ``W50_MM``    = round4 @2.5GHz rogers4350b_h0.508（=1.1134）
- ``W50_MM_R3`` = round3 @2.5GHz 同层叠（=1.113；@2.4GHz 同档逐位同值，
  由 tests/unit/test_width_single_source.py 钉住）

**惰性纪律**：``inverse_width`` 单次 brentq ~5-15ms 且不缓存，故走 PEP 562
模块级 ``__getattr__``——模块导入零成本，首次属性访问才算（进程内 lru_cache，
此后 ~µs 级命中），同时免去归档面为避导入期计算而字面量落表的两难。
消费侧必须 ``from . import _nominal_width`` 后取属性，**禁止**
``from ._nominal_width import W50_MM``（from-import 在导入期触发求值，
渲染模块导入面会整体慢 ~1s）。

归档字面量（TEMPLATE_NOMINAL、docs/templates meta、各 *_NOMINAL 字面量
落表——后者是仓内既定惯例「避免模块导入期 IO」）不改值，由一致性测试
对本源逐位钉扎；round 为 IEEE754 就近舍入，与历史字面量 repr 同串，
渲染字节零漂移。
"""

from __future__ import annotations

from rfauto.core.synthesis import nominal_width_mm

_SUB50 = "rogers4350b_h0.508"


def __getattr__(name: str) -> float:
    """PEP 562 惰性常量（首次访问 ~10ms brentq，此后 lru_cache 命中）。"""
    if name == "W50_MM":
        return nominal_width_mm(50.0, 2.5, _SUB50)
    if name == "W50_MM_R3":
        return nominal_width_mm(50.0, 2.5, _SUB50, digits=3)
    known = "W50_MM / W50_MM_R3"
    raise AttributeError(
        f"{__name__} 无常量 {name!r}（可用 {known}；新档请在 "
        f"core/synthesis.nominal_width_mm 口径下显式扩展并补一致性测试）")
