"""fake_adapter.fault —— 故障注入配置（FaultInjection）。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（aurora_h W4-S2，T2 范式/
AU-1 工艺）：代码体自原节「故障注入配置」逐字节搬迁，零逻辑改动。
"""

from __future__ import annotations

# ─── 故障注入配置 ────────────────────────────────────────────────────────────

class FaultInjection:
    """可配置的故障注入器，用于测试错误处理路径。

    Parameters
    ----------
    fail_connect : bool
        connect() 时抛出 ConnectFailedError。
    fail_build : bool
        build_and_setup() 时抛出 ModelBuildError。
    fail_solve : bool
        solve() 时抛出 SimulationFailedError。
    passivity_violation : bool
        solve() 返回的网络包含非被动 S 参数（|S|>1）。
    slow_solve_s : float
        模拟求解延迟（秒），0 表示无延迟。
    """

    def __init__(
        self,
        fail_connect: bool = False,
        fail_build: bool = False,
        fail_solve: bool = False,
        passivity_violation: bool = False,
        slow_solve_s: float = 0.0,
    ) -> None:
        self.fail_connect = fail_connect
        self.fail_build = fail_build
        self.fail_solve = fail_solve
        self.passivity_violation = passivity_violation
        self.slow_solve_s = slow_solve_s
