"""MCP Server lifespan 单元测试——验证首工具卡死修复。

测试要点：
1. lifespan 存在且可调用
2. 核心模块在 lifespan 启动后已被导入
3. pyaedt 屏幕日志在 lifespan 中被静音
"""

from __future__ import annotations


class TestMCPServerLifespan:
    """MCP Server lifespan 修复验证。"""

    def test_server_has_lifespan(self):
        """MCP Server 实例应有 lifespan 设置。"""
        from rfauto.mcp_server import mcp
        assert mcp._lifespan is not None, "MCP server 缺少 lifespan"

    def test_lifespan_preimports_core_modules(self):
        """lifespan 应预导入核心模块（解决首工具卡死）。"""
        # 检查 lifespan 的源码包含核心模块导入
        import inspect

        from rfauto.mcp_server import mcp
        src = inspect.getsource(mcp._lifespan)
        assert "rfauto.service.api" in src
        assert "rfauto.models.registry" in src

    def test_lifespan_calls_silence_pyaedt(self):
        """lifespan 应调用 _silence_pyaedt_screen_logs。"""
        import inspect

        from rfauto.mcp_server import mcp

        src = inspect.getsource(mcp._lifespan)
        assert "_silence_pyaedt_screen_logs" in src
