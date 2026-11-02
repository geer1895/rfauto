"""remote_board_service —— remote 队列看板聚合面（aurora_p G2 席，2026-11-02）。

把 remote 读面四源聚合为**单快照结构**，供 ``rfauto remote board`` 叶渲染
（机器表+队列任务表+互斥状态+异常降级行）。**纯聚合零新探测**（审阅断言
A：本模块零 TCP/SSH/进程枚举逻辑，只调用既有 service 读面并组合其返回）：

- probe 源 = ``remote_service.remote_probe``（TCP 连通性+端口时延信封）；
- status 源 = ``remote_service.remote_status``（探活+SSH 认证可达性，
  凭据缺失如实 missing 不猜不试）；
- queue 源 = ``remote_scheduler_service.queue_view``（job_registry 在途
  作业+单写锁+席位占用+服务器在途态 ``remote_resources`` 合并）；
- mutex 源 = ``remote_scheduler_service.local_openems_view/local_hfss_view``
  （本机双通道进程互斥态，#261 指纹 census）；服务器侧通道互斥态自 queue
  源 ``remote`` 子面透传——零二次探测零重复 SSH。

诚实边界（#122/#105 家法，随信封落账）：

- **best-effort**：任一源抛错/子面 unknown → ``degradations`` 降级行留痕，
  整板照常出（单机失败不炸板）；仅机器注册表解析失败（
  ``RemoteConfigError``：未登记/多机未指名）→ error 信封（用户输入错误，
  与 probe/status/resources 既有叶同语义）；
- **主机名/IP 不落信封**：机器行自 queue 源 ``remote`` 子面透传
  （``remote_resources`` 产物本身零主机名）；probe/status 回落组装路径
  只取 name/reachable/ports/ssh 字段（host 键剥离），机器只以注册表键名
  出现；
- **零新时间戳**（确定性红线）：快照内时间字段（``probed_at`` 等）=
  service 源返回原值透传，本模块不调 time 不新造任何时间戳——同 fake
  注入两跑快照逐字节相等；
- **零写入**：本模块零文件写零落盘（``--json-out`` 导出是 CLI 层用户
  显式路径，不在本模块）；
- **无登记机器=空表如实**：``machines=[]``（本地模式；no_machine 是合法
  状态不是降级，不进 ``degradations``）。
"""

from __future__ import annotations

from typing import Any

from rfauto.infra.remote_machines import RemoteConfigError
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["BOARD_SOURCES", "board_snapshot"]

#: 四源名（``degradations[].source`` 取值域；mutex=本机双通道互斥视图源）。
BOARD_SOURCES = ("probe", "status", "queue", "mutex")

#: 服务器在途子面键（queue 源 ``remote`` 内逐面收集降级行的固定序）。
_REMOTE_SUBFACES = ("openems", "hfss", "disk")

#: 本机互斥视图通道键（mutex 源返回结构，与 remote_scheduler_service
#: local_*_view 返回形态同构：state/busy/n_procs/reason）。
_LOCAL_CHANNELS = ("openems", "hfss")


# ── 源适配（惰性导入；测试面 monkeypatch 本模块四函数即全 fake 注入） ─────

def _src_probe(machine: str | None) -> dict[str, Any]:
    """probe 源适配：``remote_service.remote_probe``（信封原样）。"""
    from rfauto.service.remote_service import remote_probe

    return remote_probe(machine)


def _src_status(machine: str | None) -> dict[str, Any]:
    """status 源适配：``remote_service.remote_status``（信封原样）。"""
    from rfauto.service.remote_service import remote_status

    return remote_status(machine)


def _src_queue(machine: str | None) -> dict[str, Any]:
    """queue 源适配：``remote_scheduler_service.queue_view``（信封原样）。"""
    from rfauto.service.remote_scheduler_service import queue_view

    return queue_view(machine)


def _src_local_mutex(machine: str | None) -> dict[str, Any]:
    """mutex 源适配：本机双通道互斥视图（machine 参数仅保持四源同构，
    本机视图与机器名无关）。"""
    del machine
    from rfauto.service.remote_scheduler_service import (
        local_hfss_view,
        local_openems_view,
    )

    return {"openems": local_openems_view(), "hfss": local_hfss_view()}


# ── 聚合内核（纯组合：源信封 → 单快照；零探测零写入零时间戳） ────────────────

def _unknown_face(reason: str) -> dict[str, Any]:
    """通道子面降级形态（与 remote_scheduler_service._unknown 同构：
    state/busy/n_procs/reason——视图侧独立定义，避免跨模块私用）。"""
    return {"state": "unknown", "busy": None, "n_procs": None,
            "reason": reason}


def _safe_source(
    fn: Any, machine: str | None,
) -> tuple[dict[str, Any] | None, Exception | None]:
    """单源 best-effort 采集（#105：异常逐源降级不炸板）。

    ``RemoteConfigError`` 原样上抛（注册表解析失败=用户输入错误，整板
    error 信封，调用方统一处理）；其余异常 → ``(None, exc)`` 降级留痕。
    """
    try:
        return fn(machine), None
    except RemoteConfigError:
        raise
    except Exception as exc:  # #105：观测面单源失败降级，不阻塞整板
        return None, exc


def _deg(source: str, face: str, reason: Any) -> dict[str, str]:
    """降级行（``{"source", "face", "reason"}``；reason 恒 str 留痕）。"""
    return {"source": source, "face": face, "reason": str(reason)}


def _first_machine_row(env: dict[str, Any] | None) -> dict[str, Any]:
    """probe/status 信封 → 首机器行（无登记=空 dict；host 键消费面剥离）。"""
    rows = (env or {}).get("machines") or []
    return rows[0] if rows else {}


def _machine_row(
    queue_env: dict[str, Any] | None,
    probe_env: dict[str, Any] | None,
    status_env: dict[str, Any] | None,
) -> dict[str, Any]:
    """机器行组装（queue 源 ``remote`` 子面优先透传；queue 缺席回落
    probe/status 瘦组装——通道/磁盘面 unknown 留痕，零补探测）。

    两条路径的机器行都**零主机名**（queue 透传产物本就无 host；回落路径
    只取 name/reachable/ports/ssh 四类字段）。
    """
    remote = (queue_env or {}).get("remote")
    if isinstance(remote, dict):
        return dict(remote)  # remote_resources 产物透传（含 probed_at 原值）
    probe_row = _first_machine_row(probe_env)
    status_row = _first_machine_row(status_env)
    reason = "queue 源失败降级——服务器在途/磁盘面 unknown（#105 不阻塞）"
    return {
        "machine": probe_row.get("name") or status_row.get("name"),
        "reachable": probe_row.get("reachable"),
        "ports": dict(probe_row.get("ports") or {}),
        "ssh": status_row.get("ssh"),
        "openems": _unknown_face(reason),
        "hfss": _unknown_face(reason),
        "disk": {"state": "unknown", "free_gb": None, "drive": None,
                 "reason": reason},
        "n_tasks": None,
        "state": "unknown",
        "reason": reason,
        "probed_at": None,
    }


def _collect_degradations(
    row: dict[str, Any],
    status_env: dict[str, Any] | None,
    queue_exc: Exception | None,
    mutex_env: dict[str, Any] | None,
    mutex_exc: Exception | None,
    probe_exc: Exception | None,
    status_exc: Exception | None,
) -> list[dict[str, str]]:
    """全板降级行归集（四源失败行+子面 unknown 行；#122：如实留痕不凑判）。

    豁免口径：``machine is None``（无登记机器=合法本地模式）时跳过
    queue ``remote`` 子面逐行（三子面 unknown 均系"无机器"单一事实，
    不刷屏）；``status`` 源 SSH ``auth="failed"`` 是真实失败信号，照记。
    """
    degradations: list[dict[str, str]] = []
    if probe_exc is not None:
        degradations.append(_deg(
            "probe", "probe", f"{type(probe_exc).__name__}: {probe_exc}"))
    if status_exc is not None:
        degradations.append(_deg(
            "status", "status", f"{type(status_exc).__name__}: {status_exc}"))
    if queue_exc is not None:
        degradations.append(_deg(
            "queue", "queue", f"{type(queue_exc).__name__}: {queue_exc}"))
    if mutex_exc is not None:
        degradations.append(_deg(
            "mutex", "local", f"{type(mutex_exc).__name__}: {mutex_exc}"))

    if row.get("machine") is not None:
        for key in _REMOTE_SUBFACES:
            face = row.get(key)
            if isinstance(face, dict) and face.get("state") != "ok":
                degradations.append(_deg(
                    "queue", f"remote.{key}",
                    face.get("reason") or f"state={face.get('state')}"))
        ssh = _first_machine_row(status_env).get("ssh")
        if isinstance(ssh, dict) and ssh.get("auth") == "failed":
            degradations.append(_deg(
                "status", "ssh",
                f"SSH 认证失败: {ssh.get('error') or ssh.get('rc')}"))

    if isinstance(mutex_env, dict):
        for key in _LOCAL_CHANNELS:
            face = mutex_env.get(key)
            if isinstance(face, dict) and face.get("state") != "ok":
                degradations.append(_deg(
                    "mutex", f"local.{key}",
                    face.get("reason") or f"state={face.get('state')}"))
    return degradations


def board_snapshot(machine: str | None = None) -> dict[str, Any]:
    """聚合 probe/status/queue/mutex 四源 → 单快照信封（纯只读零写入）。

    Parameters
    ----------
    machine
        机器注册表名；None=唯一登记机器（多台未指名按注册表语义显式报
        RemoteConfigError → error 信封）；未登记机器名同语义报错。

    Returns
    -------
    dict
        ``{"ok": True, "machines": [机器行 0..1], "jobs": [队列行...],
        "counts", "write_lock", "seat_occupancy",
        "local_mutex": {"openems", "hfss"}, "degradations": [降级行...]}``。

        - ``machines``：queue 源 ``remote`` 子面透传（含
          reachable/ports/ssh/双通道 busy/n_tasks/disk/probed_at 原值）；
          无登记机器=``[]``（本地模式空表如实）；
        - ``jobs/counts/write_lock/seat_occupancy``：queue 源瘦形透传
          （队列任务表[任务/状态/归属]+单写锁+席位占用）；
        - ``local_mutex``：本机双通道互斥态（mutex 源）；
        - ``degradations``：四源失败/子面 unknown 降级行（#105 单机失败
          不炸板；#122 unknown 如实不凑判）。

        注册表解析失败 → ``{"ok": False, "errors": [...]}``（error 信封，
        与既有 remote 读面叶同语义）。
    """
    try:
        probe_env, probe_exc = _safe_source(_src_probe, machine)
        status_env, status_exc = _safe_source(_src_status, machine)
        queue_env, queue_exc = _safe_source(_src_queue, machine)
        mutex_env, mutex_exc = _safe_source(_src_local_mutex, machine)
    except RemoteConfigError as exc:
        # 未登记/多机未指名=用户输入错误：整板 error 信封（既有叶同语义，
        # 不冒充空板假绿——#122 如实失败）
        return error_envelope([f"机器注册表解析失败: {exc}"])

    row = _machine_row(queue_env, probe_env, status_env)
    degradations = _collect_degradations(
        row, status_env, queue_exc, mutex_env, mutex_exc,
        probe_exc, status_exc)

    local_mutex = (
        dict(mutex_env) if isinstance(mutex_env, dict)
        else {key: _unknown_face("mutex 源失败降级（#105）")
              for key in _LOCAL_CHANNELS})

    return ok_envelope(
        machines=[row] if row.get("machine") is not None else [],
        jobs=list((queue_env or {}).get("jobs") or []),
        counts=dict((queue_env or {}).get("counts") or {}),
        write_lock=dict((queue_env or {}).get("write_lock") or {}),
        seat_occupancy=dict((queue_env or {}).get("seat_occupancy") or {}),
        local_mutex=local_mutex,
        degradations=degradations,
    )
