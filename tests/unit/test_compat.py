"""DP-17 O2 单测——弃用助手 infra/compat.deprecated。

判据（runs/df6_dp17/criteria.md §O2）：
- 装饰函数/类触发 DeprecationWarning 且消息含三要素（release/removal/
  alternative）；
- 运行时行为透传不变（返回值/副作用原样）；
- PEP 702 口径：``__deprecated__`` 属性在场。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.infra.compat import deprecated, deprecation_message


class TestDeprecatedHelper:
    def test_function_deprecation_warning_and_passthrough(self):
        @deprecated(release="0.9", removal="1.0", alternative="new_func")
        def old_add(a: int, b: int) -> int:
            return a + b

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert old_add(2, 3) == 5  # 行为透传不变

        assert len(caught) == 1
        warning = caught[0]
        assert warning.category is DeprecationWarning
        message = str(warning.message)
        # name 缺省取 __qualname__（嵌套定义含 <locals> 前缀，尾段匹配）
        assert "old_add is deprecated" in message
        assert "since 0.9" in message
        assert "no earlier than 1.0" in message
        assert "use new_func instead" in message
        assert getattr(old_add, "__deprecated__", None)

    def test_class_deprecation(self):
        @deprecated(release="0.8", removal="1.0",
                    alternative="NewThing", name="OldThing")
        class OldThing:
            def value(self) -> str:
                return "ok"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert OldThing().value() == "ok"

        assert caught and caught[0].category is DeprecationWarning
        assert "use NewThing instead" in str(caught[0].message)

    def test_message_format_explicit_name(self):
        message = deprecation_message("thing", "0.5", "0.9", "other.thing")
        assert message == ("rfauto.thing is deprecated since 0.5; "
                           "removal no earlier than 0.9; "
                           "use other.thing instead")

    def test_method_deprecation(self):
        class Widget:
            @deprecated(release="0.9", removal="1.0",
                        alternative="Widget.new_m")
            def old_m(self) -> str:
                return "ran"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert Widget().old_m() == "ran"
        assert caught and "Widget.old_m" in str(caught[0].message)

    @pytest.mark.parametrize("release,removal", [("0.9", "1.0"),
                                                 ("1.2", "1.4")])
    def test_removal_window_phrasing(self, release, removal):
        message = deprecation_message("x", release, removal, "y")
        assert f"since {release}" in message
        assert f"no earlier than {removal}" in message
