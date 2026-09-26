"""仓库根 conftest：O3 doctest 制度的 opt-in 收集开关（唯一职责）。

为什么在根上：pytest 9 对 conftest 的 pytest_collect_file hookimpl 按
目录子树作用域分派——tests/conftest.py 的收集钩子够不到 src/ 下的文件
（实测探针零触发）。根 conftest 覆盖全仓收集参数，是唯一能原生接管
src/rfauto/core 白名单模块收集的位置。

缺省（不传 --doctest-rfauto）本文件所有钩子立即返回 None——缺省套件
零变化（全量门时间不变）。显式开启：

    pytest tests/unit src/rfauto/core --doctest-rfauto -q

零配置等价形式（pytest 原生 --doctest-modules，只点名白名单文件）：

    pytest --doctest-modules src/rfauto/core/cascade.py src/rfauto/core/wcd.py

制度与守护测试：tests/unit/test_docs_doctest.py；判据书
runs/df6_o3docs/criteria.md。
"""

from __future__ import annotations

# O3 doctest 制度：opt-in 原生收集白名单（纯函数、确定性、定向单测钉死）。
_DOCTEST_RFAUTO_MODULES = frozenset({"cascade.py", "wcd.py"})
_DOCTEST_RFAUTO_DIR = ("src", "rfauto", "core")


def pytest_addoption(parser):
    parser.addoption(
        "--doctest-rfauto", action="store_true", default=False,
        help="opt-in：把白名单纯函数模块（src/rfauto/core/{cascade,wcd}.py）"
             "的 docstring doctest 作为测试项原生收集"
             "（配合 src/rfauto/core 作为收集参数使用）")


def pytest_collect_file(file_path, parent):
    # 缺省关：立即返回 None（交还默认插件，缺省套件零变化）。
    if not parent.config.getoption("doctest_rfauto", default=False):
        return None
    tail = file_path.parts[-len(_DOCTEST_RFAUTO_DIR) - 1:]
    if (len(tail) == len(_DOCTEST_RFAUTO_DIR) + 1
            and tail[:-1] == _DOCTEST_RFAUTO_DIR
            and file_path.name in _DOCTEST_RFAUTO_MODULES):
        from _pytest.doctest import DoctestModule

        return DoctestModule.from_parent(parent, path=file_path)
    return None
