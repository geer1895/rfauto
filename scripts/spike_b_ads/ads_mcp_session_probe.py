"""真机评估 2：官方 MCP headless 会话冒烟（start_local_session → execute_python）。"""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# ADS 27 治理（2026-09-18）：安装根 env 优先、E:\ADS\ADS27 回退
ADS = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")

PY_CODE = (
    "import keysight.ads as ads\n"
    "result = {'ok': True, 'py': __import__('sys').version}\n"
)


async def main():
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=rf"{ADS}\bin\ads-mcp.exe",
        args=[],
        cwd=rf"{ADS}\bin",
        env={**os.environ, "HPEESOF_DIR": ADS},
    )
    async with Client(transport) as client:
        sessions = await client.call_tool("list_sessions", {})
        print("sessions:", repr(sessions)[:300])

        started = await client.call_tool("start_local_session", {})
        print("start_local_session:", repr(started)[:600])

        try:
            r = await client.call_tool("execute_python", {"code": PY_CODE})
            print("execute_python:", repr(r)[:600])
        except Exception as e:
            print("execute_python failed:", str(e)[:300])
        finally:
            try:
                await client.call_tool("disconnect_session", {})
                print("disconnected ok")
            except Exception as e:
                print("disconnect:", str(e)[:200])


asyncio.run(main())
