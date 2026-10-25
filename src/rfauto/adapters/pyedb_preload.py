"""pyedb DotNet 通道 Ansys OpenSSL 预载 helper（#373 回归实验，2026-10-14）。

背景（#373 + 内部证据档 R5 实证）：python-build-
standalone venv 上 pyedb DotNet 后端在 EDB native 初始化期因同名 OpenSSL
DLL 对撞硬崩（``0xc0000139 @ create_edb``/``legacy Provider loading
failed``/``EVP_DecryptInit``）——CPython 副本（解释器树 ``DLLs\\``）抢先
入进程后，EDB native 按名解析绑错副本。**最小可用配方**（PR #2599 代测
R5 PASS）：import pyedb 之前用 ``ctypes.WinDLL`` **绝对路径**预载 AnsysEM
自带的 ``libcrypto-3-x64.dll``/``libssl-3-x64.dll``——同名 DLL 只加载一次
（先到先得），后续 stdlib 驱动的按名加载全部绑到已在进程内的 Ansys 副本。

本模块把该配方做成 rfauto 的**可选能力**（feature-flag 配套件）：

- 纯 stdlib（模块 import 面零第三方依赖；infra settings 读在函数内惰性
  try/except——不可用时 configs 档如实跳过，不阻断）；
- **fail-soft**：任何失败（root 找不到/DLL 缺失/平台不支持）都只落在返回
  信封 ``ok=False + reason``，**绝不抛异常**（#105 观测面不阻塞主路径——
  预载失败时后续 import pyedb 自会暴露真实问题）；
- **幂等**：同 DLL 只在进程内加载一次，重复调用返回 ``already=True``
  （Windows 同名 DLL 本就先到先得，二次加载既无意义也会混淆判读）；
- 本模块**不定义** ``__all__``——公开 API 快照只登记带 ``__all__`` 的
  模块（edb_adapter 同款纪律，新模块出生零快照变化）。

信封形态（``preload_ansys_openssl`` 返回 dict）::

    {
      "ok": bool          # True = 两个 DLL 均已在进程内（本次或先前加载）
      "reason": str       # ok=False 时的中文原因（ok=True 为 ""）
      "root": str | None  # 解析出的 AnsysEM 根目录（绝对路径）
      "source": str       # root 出处："explicit" | "env" | "configs" | ""
      "tried": [str]      # 尝试过的候选路径（诊断面，含未命中者）
      "dlls": [           # 逐 DLL 加载明细（crypto 在前，加载序=配方序）
        {"name": str, "path": str, "loaded": bool,
         "already": bool, "version": str},
      ]
    }

root 解析顺序（配方证据：本机 ``ANSYSEM_ROOT251`` 直接指到含 DLL 的
AnsysEM 目录；异机布局可能是其父目录或 ``Win64`` 子目录——逐候选探测
DLL 对齐在位才算命中，不盲信单一路径形态）：

1. 显式参数 ``ansys_em_root``（文件/目录均收：文件取其父目录参与探测）；
2. env ``ANSYSEM_ROOT251``；
3. configs：``infra.load_settings().aedt_path``（settings 三层口径：env
   ``RFAUTO_AEDT_PATH`` > YAML）派生——同候选探测规则。
"""

from __future__ import annotations

import contextlib
import ctypes
import os
from pathlib import Path
from typing import Any

#: 需要预载的 Ansys OpenSSL DLL（配方序：crypto 先于 ssl——R5 逐字口径）
_PRELOAD_DLLS = ("libcrypto-3-x64.dll", "libssl-3-x64.dll")

#: root 解析的 env 键（AEDT 2025 R1 v251 安装器写入的机器级 env）
_ROOT_ENV = "ANSYSEM_ROOT251"

#: 已加载登记表（进程内幂等：dll 名 → {"path": str, "version": str}）；
#: ctypes 句柄不滞留（WinDLL 返回值不保存即释引用，模块已入进程不受影响）
_LOADED: dict[str, dict[str, str]] = {}

#: 末次信封存根（诊断/测试面；preload_ansys_openssl 每次调用覆盖）
last_result: dict | None = None


def _win_dll(abs_path: str) -> Any:
    """ctypes.WinDLL 薄包装（测试缝：单测 monkeypatch 本函数零真机依赖）。"""
    return ctypes.WinDLL(abs_path)


def _file_version(abs_path: str) -> str:
    """DLL 文件版本串（best-effort，失败返回 ""——#105 不阻塞）。

    走 Win32 Version API（stdlib ctypes；配方证据里 Ansys 副本为
    3.0.14 系，CPython 副本为 3.x.y——版本串是"绑到了谁"的直接线索）。
    """
    if os.name != "nt":
        return ""
    try:
        ver = ctypes.windll.version  # type: ignore[attr-defined]
        size = ver.GetFileVersionInfoSizeW(abs_path, None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(abs_path, 0, size, data):
            return ""
        buf = ctypes.c_void_p()
        blen = ctypes.c_uint()
        # MSFT 结构根键；VerQueryValueW 拿 VS_FIXEDFILEINFO
        if not ver.VerQueryValueW(data, "\\", ctypes.byref(buf),
                                  ctypes.byref(blen)) or not buf.value:
            return ""
        # VS_FIXEDFILEINFO: dwFileVersionMS 高 16 位=major 低 16 位=minor，
        # dwFileVersionLS 同式=patch/build（winver.h 布局，偏移 8/12）
        ms = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))[2]
        ls = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))[3]
        return (f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}")
    except Exception:
        return ""


def _configs_aedt_path() -> str:
    """configs 档：settings 三层口径的 ``aedt_path``（best-effort）。

    infra.load_settings 惰性 import（本模块 import 面保持纯 stdlib）；
    不可用/未配置返回 ""（configs 档如实跳过，不报错）。
    """
    try:
        from rfauto.infra.config import load_settings
    except Exception:
        return ""
    try:
        return str(load_settings().aedt_path or "")
    except Exception:
        return ""


def _dir_candidates(raw: str) -> list[Path]:
    """单个 root 线索 → 参与探测的目录候选（文件取父目录）。"""
    if not raw:
        return []
    p = Path(raw)
    with contextlib.suppress(OSError):
        p = p.resolve()
    if p.is_file():
        p = p.parent
    return [p]


def _resolve_root(explicit: str | Path | None) -> tuple[str, str, list[str]]:
    """root 解析（显式参数 > env > configs）→ (命中目录|"", 出处, tried)。

    命中判据=目录（或其 ``AnsysEM``/``Win64`` 子目录）同时含两个预载
    DLL——异机布局（安装器把 env 钉在父目录/Win64 布局）不盲信单一路径
    形态；全部候选落空返回 ("", "", tried)。
    """
    tried: list[str] = []
    tiers: list[tuple[str, str]] = []
    if explicit is not None and str(explicit).strip():
        tiers.append((str(explicit), "explicit"))
    env_val = os.environ.get(_ROOT_ENV, "")
    if env_val.strip():
        tiers.append((env_val, "env"))
    tiers.append((_configs_aedt_path(), "configs"))

    for raw, source in tiers:
        for base in _dir_candidates(raw):
            for cand in (base, base / "AnsysEM", base / "Win64"):
                tried.append(str(cand))
                if all((cand / dll).is_file() for dll in _PRELOAD_DLLS):
                    return str(cand), source, tried
    return "", "", tried


def preload_ansys_openssl(ansys_em_root: str | Path | None = None) -> dict:
    """import pyedb 前预载 AnsysEM 的 OpenSSL 副本（#373 R5 配方，fail-soft）。

    Args:
        ansys_em_root: AnsysEM 根目录显式路径（含两个预载 DLL 的目录；或
            其父目录/含 ``AnsysEM``/``Win64`` 子目录的线索路径）。缺省走
            env ``ANSYSEM_ROOT251`` → configs（``aedt_path`` 派生）链。

    Returns:
        信封 dict（形态见模块 docstring）。``ok=True`` 表示两个 DLL 均已
        在进程内（本次 ``loaded`` 或先前 ``already``）；任何失败只落
        ``ok=False + reason``，**绝不抛异常**。

    幂等：进程内同 DLL 二次调用不重复加载（``already=True``）——Windows
    同名 DLL 先到先得，本函数与该语义对齐。
    """
    global last_result
    envelope: dict = {"ok": False, "reason": "", "root": None, "source": "",
                      "tried": [], "dlls": []}
    if not hasattr(ctypes, "WinDLL"):
        envelope["reason"] = "非 Windows 平台（ctypes.WinDLL 不可用）——预载不适用"
        last_result = envelope
        return envelope
    try:
        root, source, tried = _resolve_root(ansys_em_root)
        envelope["tried"] = tried
        if not root:
            envelope["reason"] = (
                f"未找到含 {_PRELOAD_DLLS[0]}/{_PRELOAD_DLLS[1]} 的 AnsysEM "
                f"目录（解析链：显式参数 > {_ROOT_ENV} env > configs "
                f"aedt_path；tried={tried}）——显式传 ansys_em_root 或核对"
                " AEDT 安装")
            last_result = envelope
            return envelope
        envelope["root"] = root
        envelope["source"] = source
        all_ok = True
        for dll in _PRELOAD_DLLS:
            entry = {"name": dll, "path": str(Path(root) / dll),
                     "loaded": False, "already": False, "version": ""}
            prev = _LOADED.get(dll)
            if prev is not None and Path(prev["path"]).is_file():
                # 幂等命中：先前已加载且登记路径仍存在（不重复加载）
                entry["already"] = True
                entry["version"] = prev.get("version", "")
            else:
                _win_dll(entry["path"])  # 绝对路径加载（配方核心：抢在
                # stdlib 按名解析之前；失败 OSError→fail-soft 落 reason）
                entry["loaded"] = True
                entry["version"] = _file_version(entry["path"])
                _LOADED[dll] = {"path": entry["path"],
                                "version": entry["version"]}
            if not (entry["loaded"] or entry["already"]):
                all_ok = False
            envelope["dlls"].append(entry)
        envelope["ok"] = all_ok
        if not all_ok:
            envelope["reason"] = "部分 DLL 未就位（见 dlls 明细）"
    except OSError as exc:
        # 绝对路径 WinDLL 失败的主形态（文件损坏/位数不符/被杀软拦截）
        envelope["ok"] = False
        envelope["reason"] = f"预载加载失败（OSError: {exc}）"
    except Exception as exc:  # fail-soft 兜底：观测面绝不抛（#105）
        envelope["ok"] = False
        envelope["reason"] = f"预载失败（{type(exc).__name__}: {exc}）"
    last_result = envelope
    return envelope


def reset_loaded_registry() -> None:
    """清空进程内幂等登记表（仅测试面用；生产不调用）。"""
    global last_result
    _LOADED.clear()
    last_result = None
