"""O3 文档制度：docstring doctest 守护（文档示例永远可跑）。

两层机制（缺省套件零额外收集，全量门时间不变）：
① 本文件显式 doctest.testmod 形态——缺省即跑，毫秒级，断言
   failed==0 且 attempted≥下限（防示例被清空后假绿）；
② tests/conftest.py 的 opt-in `--doctest-rfauto` 开关——开启时把
   下方 DOCTEST_MODULES 对应源文件作为 DoctestModule 原生收集：

       pytest tests/unit src/rfauto/core --doctest-rfauto -q

   等价的零配置形式（不依赖 conftest 开关）：
       pytest --doctest-modules src/rfauto/core/cascade.py src/rfauto/core/wcd.py

目标模块选择（O3 判据书 runs/df6_o3docs/criteria.md §1.2）：纯函数、
零 IO、确定性、定向单测钉死（test_cascade.py / test_wcd.py）；
core/calculators.py 的示例由 docs/how-to/ 以 CLI/service 形式覆盖。
"""

from __future__ import annotations

import doctest
import importlib

import pytest

DOCTEST_MODULES: list[str] = [
    "rfauto.core.cascade",
    "rfauto.core.wcd",
]

# 下限 = 当前 docstring 示例语句数（cascade 13 / wcd 16）减余量；
# 示例扩写无需改这里，清空/意外删节会在此被拦下。
MIN_ATTEMPTED: dict[str, int] = {
    "rfauto.core.cascade": 10,
    "rfauto.core.wcd": 12,
}


@pytest.mark.parametrize("modname", DOCTEST_MODULES)
def test_docstring_doctests_pass(modname: str) -> None:
    """doctest.testmod 形态：指定模块 docstring 示例全部通过。"""
    module = importlib.import_module(modname)
    result = doctest.testmod(module, verbose=False)
    assert result.failed == 0, (
        f"{modname} docstring 示例失败 {result.failed} 条——"
        "文档示例必须永远可跑（O3 制度）；修模块或同步示例，二选一")
    assert result.attempted >= MIN_ATTEMPTED[modname], (
        f"{modname} docstring 示例仅剩 {result.attempted} 条"
        f"（下限 {MIN_ATTEMPTED[modname]}）——疑似示例被清空")
