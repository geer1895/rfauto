"""remote_probe_machine/remote_machine_status（多机协同只读探活薄壳）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 42. 多机协同远程求解（remote_service 薄壳；MCP 面最小化注记） ────────────
# MCP 面只暴露只读探活/状态（remote_probe/remote_status，零凭据零副作用）；
# HFSS 远程会话配置组装（hfss_remote_session_config）与真机冒烟
# （remote_hfss_smoke，env RFAUTO_REMOTE_SMOKE=1 opt-in）属开发/运维面
# 不进 MCP——最小面原则；冒烟走脚本驱动（与 fd_oe_campaign 同构）。

@mcp.tool
def remote_probe_machine(machine: str | None = None) -> dict[str, Any]:
    """机器 TCP 探活（remote 域）：登记机器 → 端口连通性+时延表。

    多机协同 v0。零副作用零凭据（纯 TCP connect/close，不登录不写文件），
    不用于远程求解执行（求解面属运维不进 MCP）。machine=None 时取唯一
    登记机器；无登记=空 machines 列表（本地模式）；探活异常 → ok=False
    信封。时序：网络分区时 latency 如实变大，勿当求解失败判据。

    Args:
        machine: 机器注册表名（None=唯一登记机器或多台时报错指名）

    Returns:
        dict: {ok, machines: [{name, host, reachable, ports: {语义名:
        {port, open, latency_ms}}, probe_s}]}
    """
    from rfauto.service.remote_service import remote_probe
    try:
        return remote_probe(machine)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def remote_machine_status(machine: str | None = None) -> dict[str, Any]:
    """机器状态探活（remote 域）：TCP 端口+SSH 认证可达性（多机协同 v0）。

    在探活基础上判 SSH 认证状态：凭据缺失如实 ``missing_credentials``
    （不猜不试密码，附 env/配置提示）；凭据在则真连一次按命令回执判
    ``ok/failed``。SSH 凭据只来自 RFAUTO_REMOTE_SSH_USER/PASSWORD 环境变量
    或 remote_machines.local.yaml（gitignore），永不出现在返回值；不用于
    远程求解执行。探活/SSH 异常 → ok=False 信封如实。时序：真连一次，
    慢网下耗时秒级。

    Args:
        machine: 机器注册表名（None=唯一登记机器或多台时报错指名）

    Returns:
        dict: {ok, machines: [{name, host, reachable, ports, probe_s,
        ssh: {auth, hint?}}]}
    """
    from rfauto.service.remote_service import remote_status
    try:
        return remote_status(machine)
    except Exception as e:
        return {"ok": False, "error": str(e)}
