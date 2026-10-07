"""LC-10 STEP MCAD 协同：KiCad 官方 ``kicad-cli pcb export step`` 子进程面。

规格=研究扩充 round15 §四 LC-10"STEP 板级+
屏蔽腔 MCAD 协同（P3/L）"；席D3 任务书口径："KiCad step 导出子进程面
（铁律 2；kicad-cli 探测+skipif，真跑非本席门）"。

定位（诚实边界）：本面=**板级 STEP 导出通道**（.kicad_pcb → .step，
供 MCAD 协同消费）；屏蔽腔 B-rep 建模（round15 663 号②③④）不在本面
（登记级后续）。KiCad 调用形态=官方 CLI 可执行文件子进程（铁律 2 的
 pcbnew-in-project-venv 禁令不触碰；与 kicad_drc 子进程同型）。

探测顺序（resolve_kicad_cli）：显式参 > env ``RFAUTO_KICAD_CLI`` >
缺省安装位 ``E:\\KiCad\\bin\\kicad-cli.exe``（存在才用）> ``PATH`` 上
的 ``kicad-cli``（shutil.which）。全落空 → 导出走 **skipped 信封**
（前置不满足=如实跳过，非错误；真跑由真机门 opt-in）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_KICAD_CLI",
    "export_step",
    "kicad_cli_info",
    "resolve_kicad_cli",
]

#: KiCad 官方 CLI 缺省安装位（与本仓 KICAD_PYTHON 同目录惯例；存在才用）。
DEFAULT_KICAD_CLI = r"E:\KiCad\bin\kicad-cli.exe"

#: 环境变量覆盖名（与 RFAUTO_KICAD_PYTHON 同族口径）。
ENV_KICAD_CLI = "RFAUTO_KICAD_CLI"


def resolve_kicad_cli(explicit: str | Path | None = None) -> Path | None:
    """kicad-cli 探测（显式参 > env > 缺省位 > PATH；全落空 None）。"""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env_val = os.environ.get(ENV_KICAD_CLI)
    if env_val:
        candidates.append(Path(env_val))
    for c in candidates:
        if c.is_file():
            return c
    default = Path(DEFAULT_KICAD_CLI)
    if default.is_file():
        return default
    which = shutil.which("kicad-cli")
    if which:
        return Path(which)
    return None


def _run_cli(
    cli: Path,
    args: list[str],
    *,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(cli), *args],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def kicad_cli_info(
    *,
    cli_path: str | Path | None = None,
    timeout_s: float = 15.0,
) -> dict[str, Any]:
    """kicad-cli 探测信息（可用性+版本；探测完成=ok，缺 CLI 不是错误）。"""
    from rfauto.service.envelope import ok_envelope

    cli = resolve_kicad_cli(cli_path)
    if cli is None:
        return ok_envelope(
            available=False,
            path=None,
            version=None,
            env_hint=ENV_KICAD_CLI,
            note="kicad-cli 未找到；STEP 导出走 skipped（安装 KiCad 或设 "
                 f"{ENV_KICAD_CLI}）",
        )
    version: str | None = None
    try:
        proc = _run_cli(cli, ["version"], timeout_s=timeout_s)
        if proc.returncode == 0:
            version = (proc.stdout or "").strip() or None
    except (OSError, subprocess.TimeoutExpired):
        version = None
    return ok_envelope(
        available=True, path=str(cli), version=version,
        note="version 探测失败时 version=None 如实留空（可用性以 path 为准）",
    )


def export_step(
    board_path: str | Path,
    out_path: str | Path | None = None,
    *,
    cli_path: str | Path | None = None,
    timeout_s: float = 180.0,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """KiCad 板 → STEP（``kicad-cli pcb export step``；信封返回）。

    Args:
        board_path: .kicad_pcb 路径（必须存在）。
        out_path: 输出 .step 路径（缺省与板同目录同名换后缀）。
        cli_path: 显式 kicad-cli 路径（缺省走 :func:`resolve_kicad_cli`）。
        timeout_s: 子进程超时 [s]。
        extra_args: 透传 kicad-cli 的附加参数（如
            ``["--subst-models"]``；本面不解释）。

    Returns:
        - CLI 未找到 → **skipped 信封**（reason 带安装/env 提示）；
        - 板文件缺失 → error 信封；
        - 退出码 0 且产物存在 → ok 信封（out_path/size_bytes/cmd）；
        - 非 0/超时/OS 错 → error 信封（stderr 尾部如实留痕）。
    """
    from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

    cli = resolve_kicad_cli(cli_path)
    if cli is None:
        return skipped_envelope(
            f"kicad-cli 未找到（缺省位/PATH/env {ENV_KICAD_CLI} 均落空）；"
            "STEP 导出跳过——真机导出由真机门 opt-in")
    board = Path(board_path)
    if not board.is_file():
        return error_envelope(f"板文件不存在: {board}")
    out = Path(out_path) if out_path is not None else \
        board.with_suffix(".step")
    cmd = ["pcb", "export", "step", str(board), "-o", str(out)]
    if extra_args:
        cmd += [str(a) for a in extra_args]
    try:
        proc = _run_cli(cli, cmd, timeout_s=timeout_s)
    except subprocess.TimeoutExpired:
        return error_envelope(
            f"kicad-cli 超时（>{timeout_s}s）；可调大 timeout_s")
    except OSError as exc:
        return error_envelope(f"kicad-cli 启动失败: {exc}")
    tail = ((proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            if (proc.stderr or proc.stdout) else [])
    if proc.returncode != 0:
        return error_envelope(
            f"kicad-cli 退出码 {proc.returncode}", stderr_tail=tail)
    if not out.is_file():
        return error_envelope(
            "kicad-cli 退出码 0 但产物缺失", out_path=str(out),
            stderr_tail=tail)
    return ok_envelope(
        out_path=str(out),
        size_bytes=out.stat().st_size,
        cmd=[str(cli), *cmd],
    )
