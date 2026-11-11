"""ASCII 路径守卫（通用面）——``ensure_ascii_workdir`` 工作目录映射。

病灶（晶圆键合外部建模使用者实测反馈 P0-3.3，2026-11-06）：AEDT 对含非
ASCII 字符的路径（如 ``D:\\晶圆键合\\xxx.aedt``）``OpenProject`` 直接失败
（``GrpcApiError: Failed to execute gRPC AEDT command: OpenProject``），
且错误里没有任何"路径含非 ASCII"提示——外部使用者只能逐项试错排查。

分层说明：adapter 层 ``hfss_session`` 的 P5 面（``has_non_ascii``/
``ascii_workdir_path``/``prepare_ascii_workdir``/``deliver_ascii_workdir``）
是 **HFSS 工程文件**专用形态（rfauto_work.aedt 命名 + .aedtresults 拷回 +
close 交付）；本模块是**任意工作目录**的通用映射面（不绑文件形态，目录名
恒 ASCII，拷回责任在调用方）。两层各自独立实现（infra 不 import adapters，
分层方向单向）。

用法（拷回责任约定，本模块只做映射不拷回）::

    from rfauto.infra.ascii_paths import ensure_ascii_workdir, is_ascii_path

    src = Path(user_supplied_dir)          # 可能含非 ASCII
    work = ensure_ascii_workdir(src)       # ASCII → 原样；非 ASCII → %TEMP% 映射
    ...在 work 里干活（建工程/求解/导出）...
    if work != src:                        # 发生过映射
        shutil.copytree(work, src, dirs_exist_ok=True)   # 结束拷回（调用方语义）
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

#: %TEMP% 映射目录名前缀（同 hfss_session.P5 惯例：目录名恒 ASCII 且可
#: 溯源到 rfauto；散装八位哈希目录在 %TEMP% 里不可辨识、难清理）。
_ASCII_WORKDIR_PREFIX = "rfauto_ascii_"


def is_ascii_path(path: str | Path) -> bool:
    """路径字符串（含各级目录与文件名）是否全 ASCII。

    与 :func:`rfauto.adapters.hfss_session.has_non_ascii` 同判定口径
    （逐字符 ord > 127 视为非 ASCII），本模块是通用层独立实现。
    """
    return all(ord(ch) < 128 for ch in str(path))


def ascii_workdir_target(path: str | Path) -> Path:
    """映射目标（纯函数，不建目录）：``%TEMP%/rfauto_ascii_<sha8>``。

    sha8 = ``sha256(str(path))[:8]``——同一原路径（同一字符串形态）跨会话
    映射到同一目录（重跑可复用、拷回目标可预期）。
    """
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8]
    return Path(tempfile.gettempdir()) / f"{_ASCII_WORKDIR_PREFIX}{digest}"


def ensure_ascii_workdir(path: str | Path) -> Path:
    """ASCII 工作目录守卫：非 ASCII 路径映射到 ``%TEMP%`` ASCII 工作目录。

    契约（晶圆键合用户反馈 P0-3.3 落地，2026-11-06）：

    - 全 ASCII → ``Path(path)`` **原样返回**（不建目录、不改写——调用方
      既有语义零变化）；
    - 含非 ASCII → ``%TEMP%/rfauto_ascii_<sha8>``（``mkdir parents`` 幂等
      创建）并返回该目录——同一原路径恒映射同一目录（sha256 摘要，AEDT
      reopen 语义成立）；
    - **拷回责任在调用方**：本函数只做映射，结束时不拷回（与 hfss_session
      P5 工程面 ``deliver_ascii_workdir`` 的 close 交付不同——通用面不绑
      文件形态，调用方按自己的产物清单拷回）。docstring 顶部有用法样例。

    Returns
    -------
    Path
        ASCII：入参原样（相对路径不 resolve）；非 ASCII：映射后的绝对目录。
    """
    if is_ascii_path(path):
        return Path(path)
    work = ascii_workdir_target(path)
    work.mkdir(parents=True, exist_ok=True)
    return work


def ascii_path_report(path: str | Path) -> dict[str, Any]:
    """路径 ASCII 体检报告（doctor"工作目录 ASCII 检查"项数据源）。

    返回 ``{"path", "ascii", "bad_chars", "mapped_dir", "suggestion"}``：
    ``bad_chars`` 为首个非 ASCII 字符起的去重清单（≤5 个，含首现序）；
    ``mapped_dir`` 为非 ASCII 时的映射目标（**只算不建**，见
    :func:`ascii_workdir_target`）；``suggestion`` 为修正指引文案。
    """
    text = str(path)
    bad: list[str] = []
    for ch in text:
        if ord(ch) > 127 and ch not in bad:
            bad.append(ch)
            if len(bad) >= 5:
                break
    ascii_ok = not bad and is_ascii_path(text)
    mapped = None if ascii_ok else ascii_workdir_target(text)
    suggestion = (
        "路径全 ASCII，无需映射"
        if ascii_ok
        else (
            "AEDT 对非 ASCII 路径 OpenProject 直接失败（GrpcApiError: "
            "OpenProject，且错误无'路径含非 ASCII'提示，晶圆键合用户实测"
            " 2026-11-06）——用 ensure_ascii_workdir(path) 映射 "
            "%TEMP% ASCII 工作目录（rfauto_ascii_<sha8>）后再建工程/求解，"
            "结束把产物拷回原路径（拷回责任在调用方）"
        )
    )
    return {
        "path": text,
        "ascii": ascii_ok,
        "bad_chars": bad,
        "mapped_dir": str(mapped) if mapped is not None else None,
        "suggestion": suggestion,
    }
