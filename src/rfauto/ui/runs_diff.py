"""双 run 只读对比（PR-4 报告页深化 ③）——薄 re-export 壳（SN-15）。

唯一事实源已迁 :mod:`rfauto.service.runs_diff_service`（W6-A，2026-10-06：
``rfauto runs diff`` CLI 叶需要同一能力，业务面按分层纪律落 service，
本模块保留 import 路径使 ui/server.py 与既有 UI 测试零改动）。名字逐个
显式 re-export（#116 遮蔽教训：禁止在尾部重定义同名函数）。
"""

from __future__ import annotations

from rfauto.service.runs_diff_service import recursive_diff as recursive_diff
from rfauto.service.runs_diff_service import runs_diff as runs_diff
