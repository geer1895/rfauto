"""PR-8 剖析入口：py-spy 火焰图落 runs/（UI 面数据层，JSON 进出）。

规格=研究扩充 round16 §四 PR-8："剖析入口：
封装 py-spy（MIT）火焰图落 runs/"。本席按任务书收窄为 **UI 面**（不加
CLI/MCP 新面）：Starlette ``/api/profile`` 薄路由（server.py）+ 仪表盘
剖析卡消费本模块。

形态：

- ``profile_status``：py-spy 可执行探测（``shutil.which``）+ 安装提示
  （未装=诚实降级，不假装可用）；
- ``profile_run``：``py-spy record`` 子进程封装——目标二选一（**pid**
  附着既有进程 / **cmd** 新起被测命令），输出落 ``runs/profile/``，
  格式 flamegraph（.svg，浏览器直接看）或 speedscope（.json，可交互）；
  超时=duration+120s 余量，非零退出带 stderr 尾段。

py-spy 为可选依赖（MIT，未入 extras 主列表——剖析是开发面不是运行时
面；缺装提示 ``pip install py-spy`` 即可，不阻塞 UI 其余面，#105）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "PROFILE_FORMATS",
    "profile_run",
    "profile_status",
]

#: py-spy record 支持并经本模块验证的输出格式（→ 扩展名）。
PROFILE_FORMATS: dict[str, str] = {"flamegraph": ".svg", "speedscope": ".json"}

#: 输出缺省目录（runs/ 下，随 runs 静态挂载可人工直接打开）。
DEFAULT_OUT_DIR = "runs/profile"

#: duration/rate 合法窗（py-spy 自身约束的工程化收窄）。
MIN_DURATION_S = 1.0
MAX_DURATION_S = 3600.0
MIN_RATE_HZ = 10
MAX_RATE_HZ = 1000


def profile_status() -> dict[str, Any]:
    """py-spy 可用性探测（JSON 信封；未装=ok 信封内 available=False+提示）。"""
    exe = shutil.which("py-spy")
    if exe is None:
        return ok_envelope(
            available=False,
            exe=None,
            hint="py-spy 未安装：pip install py-spy（MIT；剖析为开发面可选依赖）",
        )
    return ok_envelope(available=True, exe=exe, hint=None)


def _slug(cmd: list[str]) -> str:
    """命令 → 文件名安全 slug（字母数字连字符，其余折叠为 '-'）。"""
    raw = "-".join(cmd) if cmd else "pid"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return (slug or "target")[:60]


def profile_run(
    *,
    pid: int | None = None,
    cmd: list[str] | None = None,
    out_dir: str = DEFAULT_OUT_DIR,
    duration_s: float = 30.0,
    rate_hz: int = 100,
    fmt: str = "flamegraph",
    out_name: str | None = None,
) -> dict[str, Any]:
    """py-spy record 封装（JSON 信封；产物落 out_dir 供 /runs 静态查看）。

    Args:
        pid: 附着既有进程（与 cmd 二选一，都给/都不给=显错）。
        cmd: 新起被测命令（argv list，如 ``["python", "scripts/x.py"]``）。
        out_dir: 产物目录（缺省 runs/profile）。
        duration_s: 采样时长（秒，[1, 3600]）。
        rate_hz: 采样频率（[10, 1000]）。
        fmt: ``flamegraph``(.svg) | ``speedscope``(.json)。
        out_name: 显式产物名（缺省 ``pyspy_<slug>.<ext>``；同名覆盖如实
            在 docstring 声明——剖析产物非确定性资产，不重名保护）。
    """
    if (pid is None) == (cmd is None):
        return error_envelope(
            ["pid 与 cmd 必须二选一（附着既有进程或新起被测命令）"])
    if fmt not in PROFILE_FORMATS:
        return error_envelope(
            [f"fmt 必须在 {sorted(PROFILE_FORMATS)} 内: {fmt!r}"])
    if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) \
            or not MIN_DURATION_S <= float(duration_s) <= MAX_DURATION_S:
        return error_envelope(
            [f"duration_s 必须在 [{MIN_DURATION_S}, {MAX_DURATION_S}] 内: "
             f"{duration_s!r}"])
    if not isinstance(rate_hz, int) or isinstance(rate_hz, bool) \
            or not MIN_RATE_HZ <= rate_hz <= MAX_RATE_HZ:
        return error_envelope(
            [f"rate_hz 必须在 [{MIN_RATE_HZ}, {MAX_RATE_HZ}] 内的整数: {rate_hz!r}"])
    status = profile_status()
    if not status.get("available"):
        return error_envelope([str(status.get("hint"))])

    target_arg = ["--pid", str(pid)] if pid is not None else ["--", *map(str, cmd or [])]
    slug = _slug(cmd if cmd is not None else [f"pid{pid}"])
    name = out_name or f"pyspy_{slug}{PROFILE_FORMATS[fmt]}"
    out_path = Path(out_dir) / name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        str(status["exe"]), "record",
        "-o", str(out_path),
        "--format", fmt,
        "-d", str(float(duration_s)),
        "-r", str(rate_hz),
        *target_arg,
    ]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=float(duration_s) + 120.0,
        )
    except subprocess.TimeoutExpired:
        return error_envelope(
            [f"py-spy 采样超时（>{float(duration_s) + 120.0:.0f}s）"])
    except OSError as exc:
        return error_envelope([f"py-spy 启动失败: {exc}"])
    if result.returncode != 0 or not out_path.is_file():
        return error_envelope(
            [f"py-spy 失败（rc={result.returncode}）: {(result.stderr or '')[-500:]}"])
    return ok_envelope(
        output_path=str(out_path),
        fmt=fmt,
        duration_s=float(duration_s),
        rate_hz=rate_hz,
        target=({"pid": pid} if pid is not None else {"cmd": [str(c) for c in cmd or []]}),
    )
