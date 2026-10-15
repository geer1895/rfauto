"""真机评估：ADS 2027 官方 MCP server（bin/ads-mcp.exe）握手 + 工具枚举。"""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# ADS 27 治理（2026-09-18）：安装根 env 优先、E:\ADS\ADS27 回退
ADS = os.environ.get("RFAUTO_HPEESOF_DIR", r"E:\ADS\ADS27")


async def main():
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=rf"{ADS}\bin\ads-mcp.exe",
        args=[],
        cwd=rf"{ADS}\bin",
        env={**os.environ, "HPEESOF_DIR": ADS},
    )
    try:
        async with Client(transport) as client:
            try:
                info = client.server_info
            except Exception:
                info = None
            print("server_info:", info)
            try:
                tools = await client.list_tools()
                print(f"\n=== tools ({len(tools)}) ===")
                for t in tools:
                    desc = (t.description or "").strip().replace("\n", " ")[:110]
                    print(f"  {t.name}: {desc}")
            except Exception as e:
                print("list_tools failed:", e)
    except Exception as e:
        print("CONNECT FAILED:", type(e).__name__, str(e)[:500])


asyncio.run(main())
