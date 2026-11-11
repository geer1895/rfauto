"""论文/报告图风格单源（R11 Top4 吸收批；SciencePlots 思想零新依赖）。

定位（与 :mod:`rfauto.core.publication_standards` 的分工）：
- ``publication_standards.check_ieee_rcparams`` = **检查器**（rcParams 映射
  → IEEE 双栏出版门，纯函数零 matplotlib 依赖）；
- 本模块 = **施加器/单源**：论文与报告图产出面消费同一份 :data:`STYLE`
  常量（字号/线宽/颜色序/字体栈），消除"每图各配一套 rcParams"的漂移面；
  STYLE 数值锚全部满足 IEEE 出版门（ STYLE → check_ieee_rcparams → PASS，
  判据钉见 tests/unit/test_plot_style.py——裁判面独立于本模块，#118 家法）。

零新依赖（R11 判定"仓内单源形态优先于引依赖"）：不引 SciencePlots；
matplotlib/cycler 均为项目既有依赖（cycler 随 matplotlib 硬依赖安装）。
分层：core 纯常量+contextmanager（零 I/O、零 pyplot import），service/
adapters 图产出面按需消费（matplotlib 本体一律惰性 import——cli 注册根
轻载家法）。

CJK 豆腐块家族预防（AGENTS 速查·发布批⑩"中文图逐张目检"的机制化）：
- 字体栈 sans-serif 首位 DejaVu Sans（matplotlib 自带、跨机确定性、ASCII
  全覆盖），后位 Microsoft YaHei/SimHei（Windows 本机 CJK 族）——
  ``font.sans-serif`` 列表形逐字形回退：ASCII 字形取首位不变，中文字符
  落 CJK 族不豆腐；
- ``axes.unicode_minus=False``——CJK 字体普遍缺 U+2212（MINUS SIGN）
  字形，负号豆腐是中文图最高频翻车点；此键退回 ASCII '-'。

快照面注记：本模块**不设 ``__all__``**——无 __all__ 的非门面文件不进
tests/gold/public_api.json（check_public_api 口径），新模块零金快照漂移
（publication_standards 同款先例）。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from cycler import cycler  # matplotlib 硬依赖（随 matplotlib 安装），零新依赖

from rfauto.core.publication_standards import (
    IEEE_COLUMNWIDTH_IN,
    IEEE_FULLWIDTH_IN,
)

#: 论文图配色序（tab10 前六，matplotlib 缺省 prop_cycle 同序——消费图
#: 色彩观感零变化，同时把"缺省"钉成显式单源，防上游缺省漂移传染）。
PAPER_COLORS: list[str] = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
]

#: IEEE 单栏图 figsize 锚（宽=publication_standards.IEEE_COLUMNWIDTH_IN 单源）。
PAPER_FIGSIZE_SINGLE: tuple[float, float] = (IEEE_COLUMNWIDTH_IN, 2.5)

#: IEEE 全宽图 figsize 锚（宽=IEEE_FULLWIDTH_IN 单源）。
PAPER_FIGSIZE_DOUBLE: tuple[float, float] = (IEEE_FULLWIDTH_IN, 4.0)

#: 论文图 rcParams 单源（键集冻结钉见 tests/unit/test_plot_style.py）。
#: 数值判据：font.size ≥8pt、刻度 ≥7pt、lines.linewidth ≥0.5pt、
#: savefig.dpi ≥300、figsize 宽 ≤3.5in——全部 IEEE 出版门 PASS 档。
STYLE: dict[str, Any] = {
    # 字体栈（CJK 回退，见模块 docstring 豆腐块预防节）
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Microsoft YaHei", "SimHei", "Arial"],
    # 字号（pt；IEEE 地板 font 8 / tick 7）
    "font.size": 9.0,
    "axes.titlesize": 10.0,
    "axes.labelsize": 9.0,
    "xtick.labelsize": 8.0,
    "ytick.labelsize": 8.0,
    "legend.fontsize": 8.0,
    # 线宽/标记（IEEE 地板 0.5pt）
    "axes.linewidth": 0.6,
    "lines.linewidth": 1.0,
    "lines.markersize": 4.0,
    "grid.linewidth": 0.4,
    # 非线性域/字形守卫：禁 usetex（跨机确定性）；禁 unicode 负号（CJK 缺字形）
    "axes.unicode_minus": False,
    "text.usetex": False,
    # 版面/底色/分辨率
    "figure.figsize": PAPER_FIGSIZE_SINGLE,
    "figure.facecolor": "white",
    "figure.dpi": 100,
    "savefig.facecolor": "white",
    "savefig.edgecolor": "white",
    "savefig.dpi": 300,
    # 配色序（显式单源，tab10 缺省同序）
    "axes.prop_cycle": cycler("color", PAPER_COLORS),
}


def style_as_dict() -> dict[str, Any]:
    """STYLE 浅拷贝（纯 dict 形态；消费方零共享可变状态）。"""
    return dict(STYLE)


def apply_paper_style() -> None:
    """STYLE 施加到全局 rcParams（脚本面；库内图产出面请用
    :func:`paper_figure_context`——作用域临时施加零污染）。"""
    import matplotlib

    matplotlib.rcParams.update(style_as_dict())


@contextlib.contextmanager
def paper_figure_context(**overrides: Any) -> Iterator[None]:
    """论文风格 rcParams 作用域（进入=施加 STYLE，退出=逐键还原，异常同还原
    ——matplotlib.rc_context 承载保存/恢复语义，零全局残留）。

    Args:
        **overrides: 逐键覆盖（如 ``figure_figsize=(6.0, 4.5)``——注意
            rcParams 键名含点，覆盖键用 ``**`` 字典解包形态传入：
            ``paper_figure_context(**{"figure.figsize": (6, 4)})``）。
    """
    import matplotlib

    rc = style_as_dict()
    if overrides:
        rc.update(overrides)
    with matplotlib.rc_context(rc):
        yield
